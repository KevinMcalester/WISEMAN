import socket
import ssl
import json
import hashlib
import hmac
import logging
import threading
import time
import struct
from collections import defaultdict

from storage import TelemetryStorage

import cv2
import numpy as np

from ground_control.gcs_src.older_src import config


class Server:
    def __init__(self):
        try:
            # Core bind settings
            self.host = config.HOST
            self.port = config.PORT

            # TLS files
            self.cert = config.SERVER_CERT
            self.key = config.SERVER_KEY
            self.ca_cert = config.CA_CERT

            # HMAC key file
            self.hmac_key_path = config.HMAC_KEY

            # Separate files
            self.runtime_logs = config.SERVER_RUNTIME_LOGS
            self.telemetry_logs = config.TELEMETRY_LOGS

            self.buffer = getattr(config, "BUFFER_SIZE", 4096)

            # Small secure JSON/control packets
            self.max_packet = getattr(config, "MAX_PACKET_SIZE", 65536)

            # Separate larger limit for video frames
            self.max_frame_size = getattr(config, "MAX_FRAME_SIZE", 10 * 1024 * 1024)

            self.max_connections = config.MAX_CONNECTIONS
            self.time_window = config.TIME_WINDOW
            self.requests = defaultdict(list)

            self.valid_commands = set(getattr(config, "VALID_COMMANDS", []))
            self.allowed_clients = set(getattr(config, "ALLOWED_CLIENTS", []))

            # Thread protection
            self.rate_lock = threading.Lock()
            self.thread_limit = threading.Semaphore(getattr(config, "MAX_THREADS", 20))

            # Replay tracking
            self.seen_nonces = defaultdict(dict)
            self.nonce_lock = threading.Lock()

            # Video options
            self.show_video = getattr(config, "SHOW_VIDEO", True)
            self.window_name = getattr(config, "WINDOW_NAME", "Quanser Drone Feed")
            self.print_frame_every = getattr(config, "PRINT_FRAME_EVERY", 30)

            # Load HMAC secret once
            with open(self.hmac_key_path, "rb") as f:
                self.hmac_key = f.read()

            # Telemetry storage once
            self.telemetry_storage = TelemetryStorage(self.telemetry_logs)

            # Create TLS server context once
            self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            self.context.minimum_version = ssl.TLSVersion.TLSv1_2
            self.context.load_cert_chain(certfile=self.cert, keyfile=self.key)
            self.context.verify_mode = ssl.CERT_REQUIRED
            self.context.load_verify_locations(cafile=self.ca_cert)

            try:
                self.context.set_ciphers("ECDHE+AESGCM")
            except ssl.SSLError:
                logging.warning("Could not restrict cipher suites on this platform")

            # Create listening socket once
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind((self.host, self.port))
            self.sock.listen(15)

            logging.info(f"[!] Server started on {self.host}:{self.port}")
            print(f"[+] Server started on {self.host}:{self.port}")

        except Exception as e:
            logging.error(f"Server init error: {e}")
            raise

    def extract_client_identity(self, wrapped_conn) -> str | None:
        try:
            cert = wrapped_conn.getpeercert()
            if not cert:
                return None

            subject = cert.get("subject", ())
            for entry in subject:
                for key, value in entry:
                    if key == "commonName":
                        return value

            return None

        except Exception as e:
            logging.error(f"extract_client_identity error: {e}")
            return None

    def verify_certificate(self, wrapped_conn) -> bool:
        try:
            cert = wrapped_conn.getpeercert()
            if not cert:
                logging.warning("No client certificate found")
                return False

            client_id = self.extract_client_identity(wrapped_conn)
            if not client_id:
                logging.warning("Client certificate missing commonName")
                return False

            if self.allowed_clients and client_id not in self.allowed_clients:
                logging.warning(f"Unauthorized certificate identity: {client_id}")
                return False

            return True

        except Exception as e:
            logging.error(f"Certificate verification error: {e}")
            return False

    def check_rate_limit(self, addr) -> bool:
        try:
            now = time.time()
            ip = addr[0]

            with self.rate_lock:
                self.requests[ip] = [
                    t for t in self.requests[ip]
                    if now - t < self.time_window
                ]

                if len(self.requests[ip]) >= self.max_connections:
                    logging.warning(f"Rate limit exceeded for {ip}")
                    return False

                self.requests[ip].append(now)

            return True

        except Exception as e:
            logging.error(f"Rate limit error: {e}")
            return False

    def _cleanup_nonces(self, client_id: str, now: float) -> None:
        cache = self.seen_nonces[client_id]
        expired = [nonce for nonce, ts in cache.items() if now - ts > self.time_window]
        for nonce in expired:
            del cache[nonce]

    def recv_exact(self, wrapped_conn, num_bytes: int) -> bytes | None:
        data = bytearray()

        while len(data) < num_bytes:
            try:
                chunk = wrapped_conn.recv(num_bytes - len(data))
            except socket.timeout:
                return None
            except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
                return None
            except OSError as e:
                logging.info(f"Socket closed while receiving: {e}")
                return None

            if not chunk:
                return None

            data.extend(chunk)

        return bytes(data)

    def recv_framed_message(self, wrapped_conn):
        """
        Frame format:
        [1 byte type length][type bytes][8 byte payload length][payload bytes][32 byte HMAC]

        HMAC is over:
        type bytes + payload bytes
        """
        try:
            # 1) type length
            header = self.recv_exact(wrapped_conn, 1)
            if header is None:
                return None

            type_len = struct.unpack("!B", header)[0]
            if type_len <= 0 or type_len > 64:
                logging.warning(f"Invalid type length: {type_len}")
                return None

            # 2) type bytes
            type_bytes = self.recv_exact(wrapped_conn, type_len)
            if type_bytes is None:
                return None

            # 3) payload length
            size_bytes = self.recv_exact(wrapped_conn, 8)
            if size_bytes is None:
                return None

            payload_len = struct.unpack("!Q", size_bytes)[0]
            msg_type = type_bytes.decode("utf-8", errors="replace")

            # 4) validate payload size
            if msg_type == "video":
                if payload_len <= 0 or payload_len > self.max_frame_size:
                    logging.warning(f"Video frame too large or invalid: {payload_len}")
                    return None
            else:
                if payload_len <= 0 or payload_len > self.max_packet:
                    logging.warning(f"Payload too large or invalid: {payload_len}")
                    return None

            # 5) payload
            payload = self.recv_exact(wrapped_conn, payload_len)
            if payload is None:
                return None

            # 6) HMAC
            received_sig = self.recv_exact(wrapped_conn, 32)
            if received_sig is None:
                return None

            expected_sig = hmac.new(
                self.hmac_key,
                type_bytes + payload,
                hashlib.sha256
            ).digest()

            if not hmac.compare_digest(expected_sig, received_sig):
                logging.warning("Framed packet HMAC verification failed")
                return None

            return msg_type, payload

        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            logging.info("Client closed the connection.")
            return None
        except OSError as e:
            logging.info(f"Socket closed during framed read: {e}")
            return None
        except Exception as e:
            logging.error(f"recv_framed_message error: {e}")
            return None
    def validate_command(self, data: bytes, client_id: str) -> tuple[bool, dict | None]:
        try:
            packet = json.loads(data.decode("utf-8"))

            required_fields = {"command", "timestamp", "nonce"}
            if not required_fields.issubset(packet):
                logging.warning("Packet missing required fields")
                return False, None

            command = packet.get("command")
            timestamp = packet.get("timestamp")
            nonce = packet.get("nonce")

            if not isinstance(command, str):
                logging.warning("Invalid packet: command must be a string")
                return False, None

            if self.valid_commands and command not in self.valid_commands:
                logging.warning(f"Invalid command from {client_id}: {command}")
                return False, None

            if not isinstance(timestamp, (int, float)):
                logging.warning("Invalid packet: timestamp must be numeric")
                return False, None

            now = time.time()
            if abs(now - timestamp) > self.time_window:
                logging.warning(f"Replay/stale packet from {client_id}")
                return False, None

            if not isinstance(nonce, str) or len(nonce) < 8:
                logging.warning("Invalid packet: nonce missing or too short")
                return False, None

            with self.nonce_lock:
                self._cleanup_nonces(client_id, now)

                if nonce in self.seen_nonces[client_id]:
                    logging.warning(f"Replay nonce detected from {client_id}")
                    return False, None

                self.seen_nonces[client_id][nonce] = now

            return True, packet

        except json.JSONDecodeError:
            logging.warning("Malformed packet: not valid JSON")
            return False, None
        except Exception as e:
            logging.error(f"validate_command error: {e}")
            return False, None

    def handle_handshake(self, packet: dict, client_id: str, addr) -> None:
        try:
            logging.info(
                f"Handshake accepted from {client_id}@{addr}: "
                f"{packet.get('message', 'NO_MESSAGE')}"
            )
        except Exception as e:
            logging.error(f"handle_handshake error: {e}")

    def handle_telemetry(self, packet: dict, client_id: str, addr) -> None:
        try:
            self.telemetry_storage.store_telemetry(packet, client_id, addr)

            data = packet.get("data", {})
            logging.info(
                f"Telemetry ingested from {client_id}@{addr} | "
                f"lat={data.get('lat')} lon={data.get('lon')} "
                f"altitude={data.get('altitude')} signal={data.get('signal_strength')}"
            )
        except Exception as e:
            logging.error(f"handle_telemetry error: {e}")

    def handle_video_stream(self, wrapped_conn, first_payload: bytes, client_id: str, addr) -> None:
        frame_counter = 0
        start_time = time.time()

        try:
            if self.show_video:
                cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)

            current_payload = first_payload

            while True:
                frame_size = len(current_payload)

                if frame_size <= 0:
                    logging.warning(f"Invalid frame size from {client_id}@{addr}: {frame_size}")
                    break

                if frame_size > self.max_frame_size:
                    logging.warning(f"Frame too large from {client_id}@{addr}: {frame_size}")
                    break

                np_frame = np.frombuffer(current_payload, dtype=np.uint8)
                frame = cv2.imdecode(np_frame, cv2.IMREAD_COLOR)

                if frame is None:
                    logging.warning(f"Failed to decode JPEG frame from {client_id}@{addr}")
                    break

                frame_counter += 1

                if frame_counter % self.print_frame_every == 0:
                    elapsed = max(time.time() - start_time, 1e-6)
                    fps = frame_counter / elapsed
                    h, w = frame.shape[:2]
                    logging.info(
                        f"Video from {client_id}@{addr} | "
                        f"frame={frame_counter} size={frame_size} "
                        f"resolution={w}x{h} avg_fps={fps:.2f}"
                    )

                if self.show_video:
                    cv2.imshow(self.window_name, frame)
                    key = cv2.waitKey(1) & 0xFF
                    if key == ord("q"):
                        logging.info("Video closed by local user with 'q'")
                        break

                next_msg = self.recv_framed_message(wrapped_conn)
                if next_msg is None:
                    logging.info(f"Video stream ended for {client_id}@{addr}")
                    break

                next_type, next_payload = next_msg
                if next_type != "video":
                    logging.warning(
                        f"Expected 'video' frame but received '{next_type}' from {client_id}@{addr}"
                    )
                    break

                current_payload = next_payload

        except socket.timeout:
            logging.warning(f"Video stream timeout for {client_id}@{addr}")
        except Exception as e:
            logging.error(f"handle_video_stream error for {client_id}@{addr}: {e}")
        finally:
            if self.show_video:
                cv2.destroyAllWindows()

            total_time = max(time.time() - start_time, 1e-6)
            if frame_counter > 0:
                logging.info(
                    f"Video session summary for {client_id}@{addr}: "
                    f"{frame_counter} frames in {total_time:.2f}s "
                    f"({frame_counter / total_time:.2f} avg FPS)"
                )

    def handle_conn(self, wrapped_conn, addr):
        client_id = "unknown"

        try:
            wrapped_conn.settimeout(getattr(config, "READ_TIMEOUT", 10))

            if not self.verify_certificate(wrapped_conn):
                logging.warning(f"Certificate verification failed for {addr}")
                return

            client_id = self.extract_client_identity(wrapped_conn) or "unknown"
            logging.info(f"Accepted TLS client {client_id}@{addr}")

            while True:
                if not self.check_rate_limit(addr):
                    break

                msg = self.recv_framed_message(wrapped_conn)
                if msg is None:
                    break

                msg_type, payload = msg

                if msg_type in ("handshake", "telemetry"):
                    valid, packet = self.validate_command(payload, client_id)
                    if not valid or packet is None:
                        break

                    if msg_type == "handshake":
                        self.handle_handshake(packet, client_id, addr)
                    else:
                        self.handle_telemetry(packet, client_id, addr)

                        # Current client sends one telemetry packet and closes.
                        # Breaking here avoids an unnecessary extra read cycle.
                        break

                elif msg_type == "video":
                    self.handle_video_stream(wrapped_conn, payload, client_id, addr)
                    break

                else:
                    logging.warning(f"Unknown message type '{msg_type}' from {client_id}@{addr}")
                    break

        except socket.timeout:
            logging.warning(f"Connection timeout for {client_id}@{addr}")
        except Exception as e:
            logging.error(f"Connection handler error for {client_id}@{addr}: {e}")
        finally:
            try:
                wrapped_conn.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass

            try:
                wrapped_conn.close()
            except Exception:
                pass

            self.thread_limit.release()

    def start(self):
        while True:
            conn = None
            addr = None

            try:
                conn, addr = self.sock.accept()
                conn.settimeout(getattr(config, "HANDSHAKE_TIMEOUT", 10))

                logging.info(f"TCP connection accepted from {addr}")

                try:
                    wrapped_conn = self.context.wrap_socket(conn, server_side=True)
                    logging.info(f"TLS handshake completed for {addr}")
                except ssl.SSLError as e:
                    logging.warning(f"TLS handshake failed for {addr}: {e}")
                    try:
                        conn.close()
                    except Exception:
                        pass
                    continue
                except OSError as e:
                    logging.warning(f"Socket closed during TLS setup for {addr}: {e}")
                    try:
                        conn.close()
                    except Exception:
                        pass
                    continue

                self.thread_limit.acquire()
                thread = threading.Thread(
                    target=self.handle_conn,
                    args=(wrapped_conn, addr),
                    daemon=True
                )
                thread.start()

            except socket.timeout:
                continue
            except OSError as e:
                logging.warning(f"Accept loop socket issue: {e}")
            except Exception as e:
                logging.error(f"Accept loop error: {e}")


def main():
    logging.basicConfig(
        filename=config.SERVER_RUNTIME_LOGS,
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s]: %(message)s"
    )

    server = Server()
    server.start()


if __name__ == "__main__":
    main()
