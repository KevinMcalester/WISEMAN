#!/usr/bin/env python3
import json
import socket
import threading
import tkinter as tk
from tkinter import ttk

LAPTOP_IP = "192.168.2.168"
DRONE_IP = "192.168.2.232"
PORT = 9001

MAX_THROTTLE = 0.10
MAX_AXIS_CMD = 0.03


class AxisControlUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("QDrone Axis Control UI")

        self.sock = None
        self.sock_lock = threading.Lock()
        self.connected = False

        self.drone_ip_var = tk.StringVar(value=DRONE_IP)
        self.port_var = tk.StringVar(value=str(PORT))
        self.status_var = tk.StringVar(value="Disconnected")
        self.armed_var = tk.StringVar(value="DISARMED")

        self.throttle_var = tk.DoubleVar(value=0.0)
        self.roll_var = tk.DoubleVar(value=0.0)
        self.pitch_var = tk.DoubleVar(value=0.0)
        self.yaw_var = tk.DoubleVar(value=0.0)

        self._build_ui()

    def _build_ui(self) -> None:
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill="x")

        ttk.Label(top, text="Laptop IP:").grid(row=0, column=0, sticky="w")
        ttk.Label(top, text=LAPTOP_IP).grid(row=0, column=1, sticky="w", padx=(5, 20))

        ttk.Label(top, text="Drone IP:").grid(row=1, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.drone_ip_var, width=18).grid(row=1, column=1, sticky="w", padx=(5, 20))

        ttk.Label(top, text="Port:").grid(row=2, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.port_var, width=8).grid(row=2, column=1, sticky="w", padx=(5, 20))

        ttk.Button(top, text="Connect", command=self.connect).grid(row=0, column=2, padx=5)
        ttk.Button(top, text="Disconnect", command=self.disconnect).grid(row=0, column=3, padx=5)

        ttk.Label(top, text="Status:").grid(row=1, column=2, sticky="e")
        ttk.Label(top, textvariable=self.status_var).grid(row=1, column=3, sticky="w")

        ttk.Label(top, text="State:").grid(row=2, column=2, sticky="e")
        ttk.Label(top, textvariable=self.armed_var).grid(row=2, column=3, sticky="w")

        controls = ttk.LabelFrame(
            self.root,
            text="Axis controls",
            padding=10
        )
        controls.pack(fill="x", padx=10, pady=10)

        self._add_scale(
            parent=controls,
            row=0,
            label="Throttle",
            variable=self.throttle_var,
            low=0.0,
            high=MAX_THROTTLE
        )

        self._add_scale(
            parent=controls,
            row=1,
            label="Roll",
            variable=self.roll_var,
            low=-MAX_AXIS_CMD,
            high=MAX_AXIS_CMD
        )

        self._add_scale(
            parent=controls,
            row=2,
            label="Pitch",
            variable=self.pitch_var,
            low=-MAX_AXIS_CMD,
            high=MAX_AXIS_CMD
        )

        self._add_scale(
            parent=controls,
            row=3,
            label="Yaw",
            variable=self.yaw_var,
            low=-MAX_AXIS_CMD,
            high=MAX_AXIS_CMD
        )

        buttons = ttk.Frame(self.root, padding=10)
        buttons.pack(fill="x")

        ttk.Button(buttons, text="ARM", command=self.arm).pack(side="left", padx=5)
        ttk.Button(buttons, text="SEND AXES", command=self.send_axes).pack(side="left", padx=5)
        ttk.Button(buttons, text="ZERO AXES", command=self.zero_axes).pack(side="left", padx=5)
        ttk.Button(buttons, text="DISARM", command=self.disarm).pack(side="left", padx=5)
        ttk.Button(buttons, text="QUIT", command=self.quit_all).pack(side="right", padx=5)

    def _add_scale(self, parent, row, label, variable, low, high) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w")

        scale = tk.Scale(
            parent,
            from_=low,
            to=high,
            resolution=0.001,
            orient="horizontal",
            length=360,
            variable=variable,
            command=lambda _v: self.on_axis_change(),
        )
        scale.grid(row=row, column=1, padx=10, pady=4, sticky="w")

    def connect(self) -> None:
        if self.connected:
            self.status_var.set("Already connected")
            return

        try:
            host = self.drone_ip_var.get().strip()
            port = int(self.port_var.get().strip())

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3.0)
            sock.connect((host, port))
            sock.settimeout(None)

            with self.sock_lock:
                self.sock = sock
                self.connected = True

            self.status_var.set(f"Connected to {host}:{port}")
            self.send_message({"type": "hello", "from": LAPTOP_IP})

        except Exception as exc:
            self.status_var.set(f"Connect failed: {exc}")

    def disconnect(self) -> None:
        with self.sock_lock:
            try:
                if self.sock is not None:
                    self.sock.close()
            except Exception:
                pass

            self.sock = None
            self.connected = False

        self.status_var.set("Disconnected")
        self.armed_var.set("DISARMED")

    def send_message(self, payload: dict) -> None:
        data = (json.dumps(payload) + "\n").encode("utf-8")

        with self.sock_lock:
            if not self.connected or self.sock is None:
                self.status_var.set("Not connected")
                return

            try:
                self.sock.sendall(data)
            except Exception as exc:
                self.status_var.set(f"Send failed: {exc}")

                try:
                    self.sock.close()
                except Exception:
                    pass

                self.sock = None
                self.connected = False
                self.armed_var.set("DISARMED")

    def clamp(self, value: float, low: float, high: float) -> float:
        return max(low, min(high, float(value)))

    def build_axes_payload(self) -> dict:
        return {
            "type": "set_axes",
            "throttle": self.clamp(self.throttle_var.get(), 0.0, MAX_THROTTLE),
            "roll": self.clamp(self.roll_var.get(), -MAX_AXIS_CMD, MAX_AXIS_CMD),
            "pitch": self.clamp(self.pitch_var.get(), -MAX_AXIS_CMD, MAX_AXIS_CMD),
            "yaw": self.clamp(self.yaw_var.get(), -MAX_AXIS_CMD, MAX_AXIS_CMD),
        }

    def arm(self) -> None:
        self.send_message({"type": "arm"})
        self.armed_var.set("ARMED")

    def send_axes(self) -> None:
        if self.armed_var.get() != "ARMED":
            return
        self.send_message(self.build_axes_payload())

    def zero_axes(self) -> None:
        self.throttle_var.set(0.0)
        self.roll_var.set(0.0)
        self.pitch_var.set(0.0)
        self.yaw_var.set(0.0)

        if self.armed_var.get() == "ARMED":
            self.send_message({
                "type": "set_axes",
                "throttle": 0.0,
                "roll": 0.0,
                "pitch": 0.0,
                "yaw": 0.0,
            })

    def disarm(self) -> None:
        self.zero_axes()
        self.send_message({"type": "disarm"})
        self.armed_var.set("DISARMED")

    def on_axis_change(self) -> None:
        if self.armed_var.get() != "ARMED":
            return
        self.send_message(self.build_axes_payload())

    def quit_all(self) -> None:
        try:
            self.disarm()
        except Exception:
            pass

        self.disconnect()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    app = AxisControlUI(root)
    root.protocol("WM_DELETE_WINDOW", app.quit_all)
    root.mainloop()


if __name__ == "__main__":
    main()
