import json
import socket
import ssl
import time
import uuid
import struct
import hmac
import hashlib
import traceback
from typing import Optional
from pynput import keyboard
import ground_control.gcs_src.config_03 as config


CONNECT_HOST = getattr(config, "CONNECT_HOST", "127.0.0.1")
PORT = config.PORT

CA_CERT = config.CA_CERT
CLIENT_CERT = config.CLIENT_CERT
CLIENT_KEY = config.CLIENT_KEY
HMAC_KEY_FILE = config.HMAC_KEY

SERVER_NAME = getattr(config, "SERVER_NAME", CONNECT_HOST)
READ_TIMEOUT = getattr(config, "READ_TIMEOUT", 10)

DEVICE_ID = "pilot_laptop"
SOURCE_NAME = "wasd_controller"

FORWARD_SPEED = 0.6
STRAFE_SPEED = 0.6
VERTICAL_SPEED = 0.4
YAW_RATE = 30.0


def make_nonce() -> str:
    return uuid.uuid4().hex


def read_binary_file(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


class WasdControllerClient:
    def __init__(self):
        self.sock: Optional[socket.socket] = None
        self.ssl_sock: Optional[ssl.SSLSocket] = None
        self.pressed = set()

        self.ca_cert = CA_CERT
        self.client_cert = CLIENT_CERT
        self.client_key = CLIENT_KEY
        self.hmac_key_path = HMAC_KEY_FILE

        self.server_name = SERVER_NAME
        self.relax_tls = getattr(config, "RELAX_TLS", True)
        self.require_client_cert = getattr(config, "REQUIRE_CLIENT_CERT", True)

        self.hmac_key = read_binary_file(self.hmac_key_path)

        self.context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)

        if self.ca_cert:
            self.context.load_verify_locations(cafile=self.ca_cert)

        if self.require_client_cert:
            self.context.load_cert_chain(
                certfile=self.client_cert,
                keyfile=self.client_key
            )

        self.context.verify_mode = ssl.CERT_REQUIRED

        if self.relax_tls or CONNECT_HOST not in ("localhost", "127.0.0.1"):
            self.context.check_hostname = False
        else:
            self.context.check_hostname = True

        if hasattr(ssl, "OP_NO_TLSv1"):
            self.context.options |= ssl.OP_NO_TLSv1
        if hasattr(ssl, "OP_NO_TLSv1_1"):
            self.context.options |= ssl.OP_NO_TLSv1_1

    def log(self, msg: str) -> None:
        print(f"[WASD] {msg}")

    def connect(self) -> None:
        raw_sock = None
        wrapped_sock = None

        try:
            raw_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            raw_sock.settimeout(READ_TIMEOUT)

            self.log(f"Connecting to {CONNECT_HOST}:{PORT} ...")
            self.log(f"CA_CERT        : {self.ca_cert}")
            self.log(f"CLIENT_CERT    : {self.client_cert}")
            self.log(f"CLIENT_KEY     : {self.client_key}")
            self.log(f"SERVER_NAME    : {self.server_name}")
            self.log(f"check_hostname : {self.context.check_hostname}")
            self.log(f"RELAX_TLS      : {self.relax_tls}")

            raw_sock.connect((CONNECT_HOST, PORT))

            wrap_kwargs = {"server_side": False}
            if self.context.check_hostname:
                wrap_kwargs["server_hostname"] = self.server_name

            wrapped_sock = self.context.wrap_socket(raw_sock, **wrap_kwargs)

            local_ip, local_port = wrapped_sock.getsockname()
            peer_ip, peer_port = wrapped_sock.getpeername()

            self.sock = raw_sock
            self.ssl_sock = wrapped_sock

            self.log("TLS connection established successfully.")
            self.log(f"Local endpoint  : {local_ip}:{local_port}")
            self.log(f"Remote endpoint : {peer_ip}:{peer_port}")

        except ssl.SSLError as err:
            self.log(f"TLS failed: {err}")
            self.log(f"Raw SSL error: {repr(err)}")
            if wrapped_sock:
                try:
                    wrapped_sock.close()
                except Exception:
                    pass
            if raw_sock:
                try:
                    raw_sock.close()
                except Exception:
                    pass
            raise

        except Exception as err:
            self.log(f"Unexpected connect error: {type(err).__name__}: {err}")
            traceback.print_exc()
            if wrapped_sock:
                try:
                    wrapped_sock.close()
                except Exception:
                    pass
            if raw_sock:
                try:
                    raw_sock.close()
                except Exception:
                    pass
            raise

    def close(self) -> None:
        if self.ssl_sock:
            try:
                self.ssl_sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                self.ssl_sock.close()
            except Exception:
                pass
            self.ssl_sock = None

        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

    def sign_payload(self, msg_type: bytes, payload: bytes) -> bytes:
        return hmac.new(self.hmac_key, msg_type + payload, hashlib.sha256).digest()

    def send_framed_message(self, msg_type: str, packet: dict) -> bool:
        if not self.ssl_sock:
            self.log("TLS socket is not connected")
            return False

        try:
            type_bytes = msg_type.encode("utf-8")
            payload = json.dumps(packet, separators=(",", ":")).encode("utf-8")
            sig = self.sign_payload(type_bytes, payload)

            frame = bytearray()
            frame.extend(struct.pack("!B", len(type_bytes)))
            frame.extend(type_bytes)
            frame.extend(struct.pack("!Q", len(payload)))
            frame.extend(payload)
            frame.extend(sig)

            self.ssl_sock.sendall(frame)
            return True

        except Exception as e:
            self.log(f"Send failed: {e}")
            self.close()
            return False

    def build_control_packet(self, event: str, key_name: str) -> dict:
        vx_cmd = 0.0
        vy_cmd = 0.0
        vz_cmd = 0.0
        yaw_rate_cmd = 0.0

        active = set(self.pressed)

        if "w" in active:
            vx_cmd += FORWARD_SPEED
        if "s" in active:
            vx_cmd -= FORWARD_SPEED
        if "a" in active:
            vy_cmd += STRAFE_SPEED
        if "d" in active:
            vy_cmd -= STRAFE_SPEED
        if "q" in active:
            yaw_rate_cmd += YAW_RATE
        if "e" in active:
            yaw_rate_cmd -= YAW_RATE
        if "r" in active:
            vz_cmd += VERTICAL_SPEED
        if "f" in active:
            vz_cmd -= VERTICAL_SPEED

        return {
            "command": "CONTROL",
            "timestamp": time.time(),
            "nonce": make_nonce(),
            "device_id": DEVICE_ID,
            "source": SOURCE_NAME,
            "data": {
                "event": event,
                "key": key_name,
                "pressed_keys": sorted(active),
                "vx_cmd": vx_cmd,
                "vy_cmd": vy_cmd,
                "vz_cmd": vz_cmd,
                "yaw_rate_cmd": yaw_rate_cmd
            }
        }

    def _normalize_key(self, key) -> Optional[str]:
        try:
            if hasattr(key, "char") and key.char is not None:
                return key.char.lower()
        except Exception:
            pass

        special_map = {
            keyboard.Key.space: "space",
            keyboard.Key.esc: "esc",
        }
        return special_map.get(key)

    def on_press(self, key):
        key_name = self._normalize_key(key)
        if key_name is None:
            return

        if key_name == "esc":
            packet = {
                "command": "CONTROL",
                "timestamp": time.time(),
                "nonce": make_nonce(),
                "device_id": DEVICE_ID,
                "source": SOURCE_NAME,
                "data": {
                    "event": "emergency_stop",
                    "key": "esc",
                    "pressed_keys": [],
                    "vx_cmd": 0.0,
                    "vy_cmd": 0.0,
                    "vz_cmd": 0.0,
                    "yaw_rate_cmd": 0.0
                }
            }
            if self.send_framed_message("control", packet):
                self.log("Emergency stop sent")
            return False

        if key_name not in self.pressed:
            self.pressed.add(key_name)
            packet = self.build_control_packet("press", key_name)
            if self.send_framed_message("control", packet):
                self.log(f"PRESS {key_name} -> {packet['data']}")

    def on_release(self, key):
        key_name = self._normalize_key(key)
        if key_name is None:
            return

        if key_name in self.pressed:
            self.pressed.remove(key_name)
            packet = self.build_control_packet("release", key_name)
            if self.send_framed_message("control", packet):
                self.log(f"RELEASE {key_name} -> {packet['data']}")

    def run(self) -> None:
        self.connect()

        self.log("Controls:")
        print("        W/S = forward/back")
        print("        A/D = left/right strafe")
        print("        Q/E = yaw left/right")
        print("        R/F = up/down")
        print("        ESC = emergency stop + quit")

        with keyboard.Listener(
                on_press=self.on_press,
                on_release=self.on_release
        ) as listener:
            listener.join()

        self.close()


def main():
    client = WasdControllerClient()
    try:
        client.run()
    finally:
        client.close()


if __name__ == "__main__":
    main()
