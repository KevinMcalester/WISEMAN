#!/usr/bin/env python3
import socket
import ssl
import json
import hmac
import hashlib
import time
import uuid
import struct
import traceback

import uav_control.uav_src.config as config


class DroneClient:
    def __init__(self):
        try:
            self.host = config.HOST
            self.port = config.PORT
            self.buffer_size = getattr(config, "BUFFER_SIZE", 4096)
            self.connect_timeout = getattr(config, "SOCKET_TIMEOUT", 10)
            self.send_delay = getattr(config, "SEND_DELAY", 0.03)

            self.ca_cert = config.CA_CERT
            self.client_cert = config.CLIENT_CERT
            self.client_key = config.CLIENT_KEY
            self.hmac_key_path = config.HMAC_KEY

            self.server_name = getattr(config, "SERVER_NAME", self.host)
            self.relax_tls = getattr(config, "RELAX_TLS", True)
            self.require_client_cert = getattr(config, "REQUIRE_CLIENT_CERT", True)

            self.heartbeat_interval = getattr(config, "HEARTBEAT_INTERVAL", 0.12)
            self.max_vx = getattr(config, "MAX_VX", 0.6)
            self.max_vy = getattr(config, "MAX_VY", 0.6)
            self.max_vz = getattr(config, "MAX_VZ", 0.4)
            self.max_yaw_rate = getattr(config, "MAX_YAW_RATE", 30.0)

            with open(self.hmac_key_path, "rb") as f:
                self.hmac_key = f.read()

            # Older-Python-compatible TLS setup
            self.context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)

            if self.ca_cert:
                self.context.load_verify_locations(cafile=self.ca_cert)

            if self.require_client_cert:
                self.context.load_cert_chain(
                    certfile=self.client_cert,
                    keyfile=self.client_key
                )

            self.context.verify_mode = ssl.CERT_REQUIRED

            # Match the older working file behavior
            if self.relax_tls or self.host not in ("localhost", "127.0.0.1"):
                self.context.check_hostname = False
            else:
                self.context.check_hostname = True

            if hasattr(ssl, "OP_NO_TLSv1"):
                self.context.options |= ssl.OP_NO_TLSv1
            if hasattr(ssl, "OP_NO_TLSv1_1"):
                self.context.options |= ssl.OP_NO_TLSv1_1

            self.max_type_len = 64
            self.max_payload_len = 65536
            self.sig_len = 32

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

        return f"Unhandled socket error: {err}"

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
            self.log(f"TLS handshake failed: {repr(err)}")

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

    def send_framed_message(self, sock, msg_type: str, payload_bytes: bytes) -> bool:
        try:
            type_bytes = msg_type.encode("utf-8")
            if len(type_bytes) > 255:
                raise ValueError("Message type too long.")

            sig = self.sign_bytes(type_bytes + payload_bytes)

            header = struct.pack("!BQ", len(type_bytes), len(payload_bytes))
            packet = header + type_bytes + payload_bytes + sig

            sock.sendall(packet)
            self.log(f"Sent {msg_type!r} packet ({len(payload_bytes)} bytes payload)")
            return True

        except Exception as e:
            self.log(f"Failed to send framed message: {e}")
            return False

    def recv_exact(self, sock, size: int) -> bytes:
        buf = b""
        while len(buf) < size:
            chunk = sock.recv(size - len(buf))
            if not chunk:
                raise ConnectionError("socket closed while receiving frame")
            buf += chunk
        return buf

    def recv_framed_message(self, sock):
        type_len = struct.unpack("!B", self.recv_exact(sock, 1))[0]
        if type_len <= 0 or type_len > self.max_type_len:
            raise ValueError(f"invalid type length: {type_len}")

        type_bytes = self.recv_exact(sock, type_len)

        payload_len = struct.unpack("!Q", self.recv_exact(sock, 8))[0]
        if payload_len > self.max_payload_len:
            raise ValueError(f"payload too large: {payload_len}")

        payload = self.recv_exact(sock, payload_len)
        sig = self.recv_exact(sock, self.sig_len)

        expected = self.sign_bytes(type_bytes + payload)
        if not hmac.compare_digest(expected, sig):
            raise ValueError("ACK HMAC verification failed")

        msg_type = type_bytes.decode("utf-8")
        packet = json.loads(payload.decode("utf-8"))
        return msg_type, packet

    def send_and_wait_ack(self, sock, msg_type: str, payload: dict) -> bool:
        payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")

        ok = self.send_framed_message(sock, msg_type, payload_bytes)
        if not ok:
            return False

        try:
            ack_type, ack_packet = self.recv_framed_message(sock)

            if ack_type != "ack":
                self.log(f"Unexpected response type: {ack_type}")
                return False

            ack_data = ack_packet.get("data", {})
            ack_ok = ack_data.get("ok", False)
            ack_note = ack_data.get("note", "")
            req_nonce = ack_data.get("request_nonce", "")

            if req_nonce and req_nonce != payload.get("nonce", ""):
                self.log("ACK nonce mismatch")
                return False

            if ack_ok:
                self.log(f"ACK OK: {ack_note}")
                return True

            self.log(f"ACK ERROR: {ack_note}")
            return False

        except Exception as e:
            self.log(f"ACK read failed: {e}")
            return False

    def clamp(self, value: float, low: float, high: float) -> float:
        return max(low, min(high, float(value)))

    def build_control_payload(
            self,
            event,
            key="",
            pressed_keys=None,
            vx_cmd=0.0,
            vy_cmd=0.0,
            vz_cmd=0.0,
            yaw_rate_cmd=0.0,
            test_id="translator_control_test",
    ):
        if pressed_keys is None:
            pressed_keys = []

        safe_vx = self.clamp(vx_cmd, -self.max_vx, self.max_vx)
        safe_vy = self.clamp(vy_cmd, -self.max_vy, self.max_vy)
        safe_vz = self.clamp(vz_cmd, -self.max_vz, self.max_vz)
        safe_yaw = self.clamp(yaw_rate_cmd, -self.max_yaw_rate, self.max_yaw_rate)

        if event == "emergency_stop":
            pressed_keys = []
            safe_vx = 0.0
            safe_vy = 0.0
            safe_vz = 0.0
            safe_yaw = 0.0
            key = "esc"

        return {
            "command": "CONTROL",
            "timestamp": time.time(),
            "nonce": str(uuid.uuid4()),
            "source": "translator_client",
            "device_id": "drone1",
            "data": {
                "event": event,
                "key": key,
                "pressed_keys": list(pressed_keys),
                "vx_cmd": safe_vx,
                "vy_cmd": safe_vy,
                "vz_cmd": safe_vz,
                "yaw_rate_cmd": safe_yaw,
                "test_id": test_id,
            }
        }

    def run_control_mode(self, sock):
        try:
            test_id = "translator-{0}".format(int(time.time()))
            self.log("Starting CONTROL mode test sequence...")

            press_payload = self.build_control_payload(
                event="press",
                key="w",
                pressed_keys=["w"],
                vx_cmd=0.20,
                vy_cmd=0.0,
                vz_cmd=0.0,
                yaw_rate_cmd=0.0,
                test_id=test_id,
            )
            if not self.send_and_wait_ack(sock, "control", press_payload):
                return

            for i in range(3):
                time.sleep(self.heartbeat_interval)
                heartbeat_payload = self.build_control_payload(
                    event="heartbeat",
                    key="",
                    pressed_keys=["w"],
                    vx_cmd=0.20,
                    vy_cmd=0.0,
                    vz_cmd=0.0,
                    yaw_rate_cmd=0.0,
                    test_id=test_id,
                )
                if not self.send_and_wait_ack(sock, "control", heartbeat_payload):
                    return
                self.log("Heartbeat {0}/3 sent.".format(i + 1))

            release_payload = self.build_control_payload(
                event="release",
                key="w",
                pressed_keys=[],
                vx_cmd=0.0,
                vy_cmd=0.0,
                vz_cmd=0.0,
                yaw_rate_cmd=0.0,
                test_id=test_id,
            )
            if not self.send_and_wait_ack(sock, "control", release_payload):
                return

            time.sleep(0.10)

            estop_payload = self.build_control_payload(
                event="emergency_stop",
                test_id=test_id,
            )
            self.send_and_wait_ack(sock, "control", estop_payload)

            self.log("CONTROL mode test sequence finished.")

        except Exception as e:
            self.log("Control error: {0}".format(e))
            traceback.print_exc()

    def run(self, mode="control"):
        sock = None

        try:
            self.log("Starting drone client...")
            self.log("Target host     : {0}".format(self.host))
            self.log("Target port     : {0}".format(self.port))
            self.log("Mode            : {0}".format(mode))
            self.log("-" * 60)

            if mode not in ("control",):
                self.log("Invalid mode. Use 'control'.")
                return

            sock = self.connect()
            if sock is None:
                return

            if mode == "control":
                self.run_control_mode(sock)

        except KeyboardInterrupt:
            self.log("Stopped by user.")
        except Exception as e:
            self.log("Fatal client error: {0}".format(e))
            traceback.print_exc()
        finally:
            self.close_socket(sock)


def main():
    client = DroneClient()
    MODE = "control"
    client.run(MODE)


if __name__ == "__main__":
    main()
