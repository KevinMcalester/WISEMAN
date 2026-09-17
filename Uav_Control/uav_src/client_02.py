import socket
import ssl
import json
import hmac
import hashlib
import time
import uuid
import struct
import traceback
import cv2

import uav_control.uav_src.config as config


class DroneClient:
    def __init__(self):
        try:
            self.host = config.HOST
            self.port = config.PORT
            self.buffer_size = getattr(config, "BUFFER_SIZE", 4096)
            self.connect_timeout = getattr(config, "SOCKET_TIMEOUT", 10)
            self.send_delay = getattr(config, "SEND_DELAY", 0.03)
            self.jpeg_quality = getattr(config, "JPEG_QUALITY", 80)

            self.ca_cert = config.CA_CERT
            self.client_cert = config.CLIENT_CERT
            self.client_key = config.CLIENT_KEY
            self.hmac_key_path = config.HMAC_KEY

            # TLS behavior knobs
            self.server_name = getattr(config, "SERVER_NAME", self.host)
            self.relax_tls = getattr(config, "RELAX_TLS", True)
            self.require_client_cert = getattr(config, "REQUIRE_CLIENT_CERT", True)

            with open(self.hmac_key_path, "rb") as f:
                self.hmac_key = f.read()

            self.context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)

            # Trust store / CA
            if self.ca_cert:
                self.context.load_verify_locations(cafile=self.ca_cert)

            # Optional client certificate for mutual TLS
            if self.require_client_cert:
                self.context.load_cert_chain(
                    certfile=self.client_cert,
                    keyfile=self.client_key
                )

            # Compatibility-safe TLS settings for older Python/OpenSSL
            self.context.verify_mode = ssl.CERT_REQUIRED

            # If connecting by IP to a cert issued for localhost or some DNS name,
            # hostname verification will fail. Relax it when requested.
            if self.relax_tls or self.host not in ("localhost", "127.0.0.1"):
                self.context.check_hostname = False
            else:
                self.context.check_hostname = True

            # Keep old protocols disabled when available
            if hasattr(ssl, "OP_NO_TLSv1"):
                self.context.options |= ssl.OP_NO_TLSv1
            if hasattr(ssl, "OP_NO_TLSv1_1"):
                self.context.options |= ssl.OP_NO_TLSv1_1

        except Exception as e:
            print(f"[CLIENT] Init error: {e}")
            raise

    def log(self, msg: str) -> None:
        print(f"[CLIENT] {msg}")

    def describe_socket_error(self, err: OSError) -> str:
        if isinstance(err, socket.timeout):
            return "Operation timed out. The server may be down, unreachable, blocked by firewall, or not listening on that IP/port."
        if isinstance(err, TimeoutError):
            return "Operation timed out."
        if isinstance(err, ConnectionRefusedError):
            return "Connection was refused. The server is not listening, the port is wrong, or a firewall rejected it."
        if isinstance(err, ConnectionResetError):
            return "Connection was reset after being established."
        if isinstance(err, PermissionError):
            return "Permission denied. Local policy, permissions, or security software may be blocking the socket."

        errno_val = getattr(err, "errno", None)

        if errno_val == 101:
            return "Network is unreachable."
        if errno_val == 110:
            return "Connection attempt timed out."
        if errno_val == 111:
            return "Connection refused."
        if errno_val == 113:
            return "No route to host."

        return "Unhandled socket error: {}".format(err)

    def describe_ssl_error(self, err: Exception) -> str:
        text = str(err)

        if "CERTIFICATE_VERIFY_FAILED" in text:
            return "Certificate verification failed. CA/cert chain does not match, or server cert name does not match the host/server name."
        if "hostname" in text.lower():
            return "Hostname verification failed. The certificate name does not match the requested server name."
        if "WRONG_VERSION_NUMBER" in text:
            return "TLS version mismatch or the remote side is not actually speaking TLS on this port."
        if "UNKNOWN_CA" in text:
            return "The server certificate was not signed by a CA trusted by this client."
        if "TLSV1_ALERT" in text or "SSLV3_ALERT" in text:
            return "The remote TLS endpoint rejected the handshake."

        return "TLS handshake failed."

    def connect(self):
        raw_sock = None
        wrapped_sock = None

        try:
            raw_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            raw_sock.settimeout(self.connect_timeout)

            self.log(f"Connecting to {self.host}:{self.port} ...")
            self.log(f"CA_CERT        : {self.ca_cert}")
            self.log(f"CLIENT_CERT    : {self.client_cert}")
            self.log(f"CLIENT_KEY     : {self.client_key}")
            self.log(f"SERVER_NAME    : {self.server_name}")
            self.log(f"check_hostname : {self.context.check_hostname}")
            self.log(f"RELAX_TLS      : {self.relax_tls}")

            # First establish TCP, then wrap for TLS.
            # This gives cleaner connect errors on older Python versions.
            raw_sock.connect((self.host, self.port))

            wrap_kwargs = {"server_side": False}
            if self.context.check_hostname:
                wrap_kwargs["server_hostname"] = self.server_name

            wrapped_sock = self.context.wrap_socket(raw_sock, **wrap_kwargs)

            local_ip, local_port = wrapped_sock.getsockname()
            peer_ip, peer_port = wrapped_sock.getpeername()

            self.log("TLS connection established successfully.")
            self.log(f"Local endpoint  : {local_ip}:{local_port}")
            self.log(f"Remote endpoint : {peer_ip}:{peer_port}")

            return wrapped_sock

        except ssl.SSLError as err:
            self.log(self.describe_ssl_error(err))
            self.log(f"Raw SSL error: {repr(err)}")

        except OSError as err:
            self.log("Connection failed.")
            self.log(self.describe_socket_error(err))
            self.log(f"Raw error: {repr(err)}")

        except Exception as err:
            self.log(f"Unexpected connect error: {type(err).__name__}: {err}")
            traceback.print_exc()

        try:
            if wrapped_sock:
                wrapped_sock.close()
            elif raw_sock:
                raw_sock.close()
        except Exception:
            pass

        return None

    def close_socket(self, sock):
        if sock is None:
            return

        try:
            sock.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass

        try:
            sock.close()
            self.log("Socket closed.")
        except Exception:
            self.log("Failed to close socket cleanly.")

    def sign_bytes(self, payload_bytes: bytes) -> bytes:
        return hmac.new(self.hmac_key, payload_bytes, hashlib.sha256).digest()

    def build_signed_json_packet(self, payload: dict) -> bytes:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        sig = self.sign_bytes(data)
        return data + sig

    def send_framed_message(self, sock, msg_type: str, payload_bytes: bytes) -> bool:
        """
        Frame format:
        [1 byte type length][type bytes][8 byte payload length][payload bytes][32 byte HMAC]

        HMAC is over: type bytes + payload bytes
        """
        try:
            type_bytes = msg_type.encode("utf-8")
            if len(type_bytes) > 255:
                raise ValueError("Message type too long.")

            sig = self.sign_bytes(type_bytes + payload_bytes)

            header = struct.pack("!B", len(type_bytes))
            size_field = struct.pack("!Q", len(payload_bytes))

            packet = header + type_bytes + size_field + payload_bytes + sig

            sock.sendall(packet)
            self.log(f"Sent {msg_type!r} packet ({len(payload_bytes)} bytes payload)")
            return True

        except Exception as e:
            self.log(f"Failed to send framed message: {e}")
            return False

    def run_handshake_mode(self, sock) -> None:
        try:
            payload = {
                "command": "HANDSHAKE",
                "timestamp": time.time(),
                "nonce": str(uuid.uuid4()),
                "device_id": "drone1",
                "message": "DRONE_HELLO"
            }

            payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_framed_message(sock, "handshake", payload_bytes)

        except Exception as e:
            self.log(f"Handshake error: {e}")

    def build_telemetry_payload(self) -> dict:
        return {
            "command": "TELEMETRY",
            "timestamp": time.time(),
            "nonce": str(uuid.uuid4()),
            "source": "wifi",
            "device_id": "drone1",
            "data": {
                "lat": 27.5306,
                "lon": -99.4803,
                "altitude": 120,
                "signal_strength": -54
            }
        }

    def run_telemetry_mode(self, sock) -> None:
        try:
            payload = self.build_telemetry_payload()
            payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_framed_message(sock, "telemetry", payload_bytes)

        except Exception as e:
            self.log(f"Telemetry error: {e}")

    def run_video_mode(self, sock) -> None:
        cap = None

        try:
            self.log("Opening camera...")
            cap = cv2.VideoCapture(0)

            if not cap.isOpened():
                self.log("Failed to open the drone camera.")
                return

            self.log("Camera opened successfully. Beginning frame transmission...")
            encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality]
            frame_counter = 0

            while True:
                ret, frame = cap.read()

                if not ret or frame is None:
                    self.log("Failed to read frame from camera.")
                    break

                success, encoded_frame = cv2.imencode(".jpg", frame, encode_params)
                if not success:
                    self.log("Failed to encode frame.")
                    continue

                frame_bytes = encoded_frame.tobytes()

                ok = self.send_framed_message(sock, "video", frame_bytes)
                if not ok:
                    break

                frame_counter += 1
                self.log(f"Frame #{frame_counter} sent.")
                time.sleep(self.send_delay)

        except OSError as err:
            self.log("Socket error during video mode.")
            self.log(self.describe_socket_error(err))
            self.log(f"Raw error: {repr(err)}")
        except Exception as err:
            self.log("Unexpected error during video mode.")
            self.log(f"Type: {type(err).__name__}")
            self.log(f"Message: {err}")
            traceback.print_exc()
        finally:
            if cap is not None:
                cap.release()
                self.log("Camera released.")

    def run(self, mode: str = "telemetry") -> None:
        sock = None

        try:
            self.log("Starting drone client...")
            self.log(f"Target host     : {self.host}")
            self.log(f"Target port     : {self.port}")
            self.log(f"Mode            : {mode}")
            self.log("-" * 60)

            if mode not in ("handshake", "telemetry", "video"):
                self.log("Invalid mode. Use 'handshake', 'telemetry', or 'video'.")
                return

            sock = self.connect()
            if sock is None:
                return

            if mode == "handshake":
                self.run_handshake_mode(sock)
            elif mode == "telemetry":
                self.run_telemetry_mode(sock)
            elif mode == "video":
                self.run_video_mode(sock)

        except KeyboardInterrupt:
            self.log("Stopped by user.")
        except Exception as e:
            self.log(f"Fatal client error: {e}")
            traceback.print_exc()
        finally:
            self.close_socket(sock)


def main():
    client = DroneClient()
    MODE = "telemetry"
    client.run(MODE)


if __name__ == "__main__":
    main()
