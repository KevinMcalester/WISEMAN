import json
import socket
import ssl
import time
import uuid
import struct
import hmac
import hashlib
import threading
from typing import Optional

import tkinter as tk
from tkinter import ttk

import ground_control.gcs_src.config_03 as config


CONNECT_HOST = getattr(config, "CONNECT_HOST", "127.0.0.1")
CONTROL_PORT = getattr(config, "CONTROL_PORT", 9000)

CA_CERT = config.CA_CERT
CLIENT_CERT = config.CLIENT_CERT
CLIENT_KEY = config.CLIENT_KEY
HMAC_KEY_FILE = config.HMAC_KEY

SERVER_NAME = getattr(config, "SERVER_NAME", "127.0.0.1")
READ_TIMEOUT = getattr(config, "READ_TIMEOUT", 10)

DEVICE_ID = "pilot_laptop"
SOURCE_NAME = "ui_controller"

FORWARD_SPEED = 0.6
STRAFE_SPEED = 0.6
VERTICAL_SPEED = 0.4
YAW_RATE = 30.0

HEARTBEAT_INTERVAL = 0.12
ALLOWED_KEYS = {"w", "a", "s", "d", "q", "e", "r", "f", "space", "esc"}

MAX_TYPE_LEN = 64
MAX_PAYLOAD_LEN = 65536
SIG_LEN = 32


def make_nonce() -> str:
    return uuid.uuid4().hex


def make_test_id() -> str:
    return f"test-{int(time.time())}-{uuid.uuid4().hex[:8]}"


def read_binary_file(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


class UIControllerClient:
    def __init__(self):
        self.sock: Optional[socket.socket] = None
        self.ssl_sock: Optional[ssl.SSLSocket] = None
        self.hmac_key = read_binary_file(HMAC_KEY_FILE)

        self.pressed = set()
        self.lock = threading.Lock()
        self.running = True
        self.connected = False

        self.last_sent_state = None
        self.sender_thread = None

        self.root = None
        self.status_var = None
        self.state_var = None
        self.last_event_var = None
        self.buttons = {}

        self.current_test_id = make_test_id()

    def connect(self) -> None:
        raw_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw_sock.settimeout(READ_TIMEOUT)
        raw_sock.connect((CONNECT_HOST, CONTROL_PORT))

        ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=CA_CERT)
        ctx.load_cert_chain(certfile=CLIENT_CERT, keyfile=CLIENT_KEY)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.check_hostname = False

        self.sock = raw_sock
        self.ssl_sock = ctx.wrap_socket(raw_sock, server_hostname=SERVER_NAME)
        self.connected = True
        self._set_status(f"Connected to {CONNECT_HOST}:{CONTROL_PORT} over TLS")

    def close(self) -> None:
        self.running = False
        self.connected = False

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

        self._set_status("Disconnected")

    def sign_payload(self, msg_type: bytes, payload: bytes) -> bytes:
        return hmac.new(self.hmac_key, msg_type + payload, hashlib.sha256).digest()

    def recv_exact(self, size: int) -> bytes:
        if not self.ssl_sock:
            raise ConnectionError("TLS socket not connected")

        buf = b""
        while len(buf) < size:
            chunk = self.ssl_sock.recv(size - len(buf))
            if not chunk:
                raise ConnectionError("socket closed while receiving frame")
            buf += chunk
        return buf

    def recv_framed_message(self):
        type_len = struct.unpack("!B", self.recv_exact(1))[0]
        if type_len <= 0 or type_len > MAX_TYPE_LEN:
            raise ValueError(f"invalid type length: {type_len}")

        type_bytes = self.recv_exact(type_len)

        payload_len = struct.unpack("!Q", self.recv_exact(8))[0]
        if payload_len > MAX_PAYLOAD_LEN:
            raise ValueError(f"payload too large: {payload_len}")

        payload = self.recv_exact(payload_len)
        sig = self.recv_exact(SIG_LEN)

        expected = self.sign_payload(type_bytes, payload)
        if not hmac.compare_digest(expected, sig):
            raise ValueError("ACK HMAC verification failed")

        msg_type = type_bytes.decode("utf-8")
        packet = json.loads(payload.decode("utf-8"))
        return msg_type, packet

    def send_framed_message(self, msg_type: str, packet: dict) -> bool:
        if not self.ssl_sock:
            self._set_status("TLS socket is not connected")
            return False

        try:
            type_bytes = msg_type.encode("utf-8")
            payload = json.dumps(packet).encode("utf-8")
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
            self._set_status(f"Send failed: {e}")
            self.close()
            return False

    def send_and_wait_ack(self, msg_type: str, packet: dict) -> bool:
        if not self.send_framed_message(msg_type, packet):
            return False

        try:
            ack_type, ack_packet = self.recv_framed_message()
            ack_data = ack_packet.get("data", {})

            if ack_type != "ack":
                self._set_status(f"Unexpected response type: {ack_type}")
                return False

            ok = ack_data.get("ok", False)
            note = ack_data.get("note", "")
            req_nonce = ack_data.get("request_nonce", "")

            if req_nonce and req_nonce != packet.get("nonce", ""):
                self._set_status("ACK nonce mismatch")
                return False

            if ok:
                self._set_status(f"ACK OK: {note}")
                return True

            self._set_status(f"ACK ERROR: {note}")
            return False

        except Exception as e:
            self._set_status(f"ACK read failed: {e}")
            return False

    def build_control_packet(self, event: str, key_name: str = "") -> dict:
        with self.lock:
            active = set(self.pressed)

        vx_cmd = 0.0
        vy_cmd = 0.0
        vz_cmd = 0.0
        yaw_rate_cmd = 0.0

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
                "yaw_rate_cmd": yaw_rate_cmd,
                "test_id": self.current_test_id,
            }
        }

    def _state_tuple(self):
        with self.lock:
            return tuple(sorted(self.pressed))

    def _refresh_ui_state(self):
        if self.state_var is None:
            return

        with self.lock:
            active = sorted(self.pressed)

        active_text = ", ".join(active) if active else "none"
        self.state_var.set(f"Active controls: {active_text}")

        for key_name, button in self.buttons.items():
            if key_name in active:
                button.state(["pressed"])
            else:
                button.state(["!pressed"])

    def _set_status(self, text: str):
        print(f"[UI] {text}")
        if self.status_var is not None:
            self.status_var.set(f"Status: {text}")

    def _set_last_event(self, text: str):
        print(f"[UI] {text}")
        if self.last_event_var is not None:
            self.last_event_var.set(f"Last event: {text}")

    def _send_state_if_changed(self, event: str, key_name: str) -> None:
        current_state = self._state_tuple()
        if current_state == self.last_sent_state and event != "heartbeat":
            return

        packet = self.build_control_packet(event, key_name)
        if self.send_and_wait_ack("control", packet):
            self.last_sent_state = current_state
            data = packet["data"]
            self._set_last_event(
                f"{event.upper()} {key_name} | "
                f"vx={data['vx_cmd']} vy={data['vy_cmd']} "
                f"vz={data['vz_cmd']} yaw={data['yaw_rate_cmd']} "
                f"| test_id={data['test_id']}"
            )

    def _heartbeat_loop(self):
        while self.running:
            time.sleep(HEARTBEAT_INTERVAL)

            with self.lock:
                if not self.pressed:
                    continue

            packet = self.build_control_packet("heartbeat", "")
            self.send_and_wait_ack("control", packet)

    def press_control(self, key_name: str):
        if key_name not in ALLOWED_KEYS:
            return

        if key_name == "esc":
            self.emergency_stop()
            return

        with self.lock:
            if key_name in self.pressed:
                return
            self.pressed.add(key_name)

        self._refresh_ui_state()
        self._send_state_if_changed("press", key_name)

    def release_control(self, key_name: str):
        if key_name not in ALLOWED_KEYS or key_name == "esc":
            return

        with self.lock:
            if key_name not in self.pressed:
                return
            self.pressed.remove(key_name)

        self._refresh_ui_state()
        self._send_state_if_changed("release", key_name)

    def emergency_stop(self):
        with self.lock:
            self.pressed.clear()

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
                "yaw_rate_cmd": 0.0,
                "test_id": self.current_test_id,
            }
        }

        self._refresh_ui_state()
        self.send_and_wait_ack("control", packet)
        self._set_last_event(f"EMERGENCY STOP | test_id={self.current_test_id}")

    def _bind_key(self, tk_event, key_name: str):
        self.press_control(key_name)

    def _bind_key_release(self, tk_event, key_name: str):
        self.release_control(key_name)

    def _make_hold_button(self, parent, text: str, key_name: str, row: int, col: int, width: int = 10):
        btn = ttk.Button(parent, text=text, width=width)
        btn.grid(row=row, column=col, padx=6, pady=6, sticky="nsew")

        btn.bind("<ButtonPress-1>", lambda e: self.press_control(key_name))
        btn.bind("<ButtonRelease-1>", lambda e: self.release_control(key_name))
        btn.bind("<Leave>", lambda e: self.release_control(key_name))

        self.buttons[key_name] = btn
        return btn

    def _connect_action(self):
        try:
            self.running = True
            self.current_test_id = make_test_id()
            self.connect()

            if self.sender_thread is None or not self.sender_thread.is_alive():
                self.sender_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
                self.sender_thread.start()

        except Exception as e:
            self._set_status(f"Connect failed: {e}")

    def _disconnect_action(self):
        self.close()

    def _on_window_close(self):
        self.close()
        if self.root is not None:
            self.root.destroy()

    def build_ui(self):
        self.root = tk.Tk()
        self.root.title("Drone UI Controller")
        self.root.geometry("520x420")
        self.root.protocol("WM_DELETE_WINDOW", self._on_window_close)

        self.status_var = tk.StringVar(value="Status: Disconnected")
        self.state_var = tk.StringVar(value="Active controls: none")
        self.last_event_var = tk.StringVar(value="Last event: none")

        top = ttk.Frame(self.root, padding=12)
        top.pack(fill="x")

        ttk.Button(top, text="Connect", command=self._connect_action).pack(side="left", padx=4)
        ttk.Button(top, text="Disconnect", command=self._disconnect_action).pack(side="left", padx=4)
        ttk.Button(top, text="Emergency Stop", command=self.emergency_stop).pack(side="right", padx=4)

        info = ttk.Frame(self.root, padding=(12, 6))
        info.pack(fill="x")
        ttk.Label(info, textvariable=self.status_var).pack(anchor="w")
        ttk.Label(info, textvariable=self.state_var).pack(anchor="w", pady=(4, 0))
        ttk.Label(info, textvariable=self.last_event_var).pack(anchor="w", pady=(4, 0))

        controls = ttk.LabelFrame(self.root, text="Hold buttons or use keyboard", padding=12)
        controls.pack(fill="both", expand=True, padx=12, pady=12)

        for i in range(4):
            controls.columnconfigure(i, weight=1)
        for i in range(4):
            controls.rowconfigure(i, weight=1)

        self._make_hold_button(controls, "Forward\n(W)", "w", 0, 1)
        self._make_hold_button(controls, "Yaw Left\n(Q)", "q", 0, 0)
        self._make_hold_button(controls, "Yaw Right\n(E)", "e", 0, 2)

        self._make_hold_button(controls, "Left\n(A)", "a", 1, 0)
        self._make_hold_button(controls, "Back\n(S)", "s", 1, 1)
        self._make_hold_button(controls, "Right\n(D)", "d", 1, 2)

        self._make_hold_button(controls, "Up\n(R)", "r", 2, 0)
        self._make_hold_button(controls, "Down\n(F)", "f", 2, 2)

        ttk.Label(
            controls,
            text="Keyboard also works when this window is focused:\nW/A/S/D = move | Q/E = yaw | R/F = altitude | Esc = stop"
        ).grid(row=3, column=0, columnspan=4, pady=(12, 0))

        self.root.bind("<KeyPress-w>", lambda e: self._bind_key(e, "w"))
        self.root.bind("<KeyRelease-w>", lambda e: self._bind_key_release(e, "w"))
        self.root.bind("<KeyPress-a>", lambda e: self._bind_key(e, "a"))
        self.root.bind("<KeyRelease-a>", lambda e: self._bind_key_release(e, "a"))
        self.root.bind("<KeyPress-s>", lambda e: self._bind_key(e, "s"))
        self.root.bind("<KeyRelease-s>", lambda e: self._bind_key_release(e, "s"))
        self.root.bind("<KeyPress-d>", lambda e: self._bind_key(e, "d"))
        self.root.bind("<KeyRelease-d>", lambda e: self._bind_key_release(e, "d"))
        self.root.bind("<KeyPress-q>", lambda e: self._bind_key(e, "q"))
        self.root.bind("<KeyRelease-q>", lambda e: self._bind_key_release(e, "q"))
        self.root.bind("<KeyPress-e>", lambda e: self._bind_key(e, "e"))
        self.root.bind("<KeyRelease-e>", lambda e: self._bind_key_release(e, "e"))
        self.root.bind("<KeyPress-r>", lambda e: self._bind_key(e, "r"))
        self.root.bind("<KeyRelease-r>", lambda e: self._bind_key_release(e, "r"))
        self.root.bind("<KeyPress-f>", lambda e: self._bind_key(e, "f"))
        self.root.bind("<KeyRelease-f>", lambda e: self._bind_key_release(e, "f"))
        self.root.bind("<Escape>", lambda e: self.emergency_stop())

    def run(self):
        self.build_ui()
        self.root.mainloop()


def main():
    client = UIControllerClient()
    client.run()


if __name__ == "__main__":
    main()
