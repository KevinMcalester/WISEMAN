#!/usr/bin/env python3
import json
import socket
import threading
import tkinter as tk
from tkinter import ttk

LAPTOP_IP = "192.168.2.168"
DRONE_IP = "192.168.2.232"
PORT = 9001

MAX_THROTTLE = 0.50
MAX_HOVER_THROTTLE = 0.60
MAX_AXIS_CMD = 0.03
DEFAULT_HOVER_THROTTLE = 0.30


class AxisControlUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("QDrone Axis + Hover Control UI")
        self.sock = None
        self.sock_lock = threading.Lock()
        self.connected = False
        self.receiver_thread = None
        self.receiver_running = False

        self.drone_ip_var = tk.StringVar(value=DRONE_IP)
        self.port_var = tk.StringVar(value=str(PORT))
        self.status_var = tk.StringVar(value="Disconnected")
        self.armed_var = tk.StringVar(value="DISARMED")
        self.hover_status_var = tk.StringVar(value="HOVER OFF")

        self.throttle_var = tk.DoubleVar(value=0.0)
        self.roll_var = tk.DoubleVar(value=0.0)
        self.pitch_var = tk.DoubleVar(value=0.0)
        self.yaw_var = tk.DoubleVar(value=0.0)
        self.hover_throttle_var = tk.DoubleVar(value=DEFAULT_HOVER_THROTTLE)

        self.trim0_var = tk.DoubleVar(value=1.0)
        self.trim1_var = tk.DoubleVar(value=1.0)
        self.trim2_var = tk.DoubleVar(value=1.0)
        self.trim3_var = tk.DoubleVar(value=1.0)

        self._build_ui()

        # Force the window to fully fit all widgets so ARM/DISARM are visible.
        self.root.update_idletasks()
        width = self.root.winfo_reqwidth()
        height = self.root.winfo_reqheight()
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(width, height)
    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill="both", expand=True)

        # ---------------- Top / connection section ----------------
        top = ttk.LabelFrame(main, text="Connection / Status", padding=10)
        top.pack(fill="x", pady=(0, 10))

        ttk.Label(top, text="Laptop IP:").grid(row=0, column=0, sticky="w")
        ttk.Label(top, text=LAPTOP_IP).grid(row=0, column=1, sticky="w", padx=(5, 20))

        ttk.Label(top, text="Drone IP:").grid(row=0, column=2, sticky="w")
        ttk.Entry(top, textvariable=self.drone_ip_var, width=16).grid(row=0, column=3, sticky="w", padx=(5, 20))

        ttk.Label(top, text="Port:").grid(row=0, column=4, sticky="w")
        ttk.Entry(top, textvariable=self.port_var, width=8).grid(row=0, column=5, sticky="w", padx=(5, 20))

        ttk.Button(top, text="Connect", command=self.connect).grid(row=0, column=6, padx=5)
        ttk.Button(top, text="Disconnect", command=self.disconnect).grid(row=0, column=7, padx=5)

        ttk.Label(top, text="Status:").grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Label(top, textvariable=self.status_var).grid(row=1, column=1, columnspan=3, sticky="w", pady=(10, 0))

        ttk.Label(top, text="State:").grid(row=1, column=4, sticky="e", pady=(10, 0))
        ttk.Label(top, textvariable=self.armed_var).grid(row=1, column=5, sticky="w", pady=(10, 0))

        ttk.Label(top, text="Hover:").grid(row=1, column=6, sticky="e", pady=(10, 0))
        ttk.Label(top, textvariable=self.hover_status_var).grid(row=1, column=7, sticky="w", pady=(10, 0))

        # ---------------- Middle area: two compact columns ----------------
        middle = ttk.Frame(main)
        middle.pack(fill="both", expand=True)

        left_col = ttk.Frame(middle)
        left_col.pack(side="left", fill="both", expand=True, padx=(0, 5))

        right_col = ttk.Frame(middle)
        right_col.pack(side="left", fill="both", expand=True, padx=(5, 0))

        # ---------------- Left column: axis controls ----------------
        controls = ttk.LabelFrame(left_col, text="Axis Controls", padding=10)
        controls.pack(fill="both", expand=True)

        self._add_scale(
            parent=controls,
            row=0,
            label="Throttle",
            variable=self.throttle_var,
            low=0.0,
            high=MAX_THROTTLE,
            auto_send=True
        )

        self._add_scale(
            parent=controls,
            row=1,
            label="Roll",
            variable=self.roll_var,
            low=-MAX_AXIS_CMD,
            high=MAX_AXIS_CMD,
            auto_send=True
        )

        self._add_scale(
            parent=controls,
            row=2,
            label="Pitch",
            variable=self.pitch_var,
            low=-MAX_AXIS_CMD,
            high=MAX_AXIS_CMD,
            auto_send=True
        )

        self._add_scale(
            parent=controls,
            row=3,
            label="Yaw",
            variable=self.yaw_var,
            low=-MAX_AXIS_CMD,
            high=MAX_AXIS_CMD,
            auto_send=True
        )

        # ---------------- Right column: hover + trim ----------------
        hover_frame = ttk.LabelFrame(right_col, text="Hover Controls", padding=10)
        hover_frame.pack(fill="x", pady=(0, 10))

        self._add_scale(
            parent=hover_frame,
            row=0,
            label="Hover Throttle",
            variable=self.hover_throttle_var,
            low=0.0,
            high=MAX_HOVER_THROTTLE,
            auto_send=False
        )

        hover_buttons = ttk.Frame(hover_frame)
        hover_buttons.grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))

        ttk.Button(
            hover_buttons,
            text="SET HOVER",
            command=self.set_hover_throttle
        ).pack(side="left", padx=4)

        ttk.Button(
            hover_buttons,
            text="START",
            command=self.hover_start
        ).pack(side="left", padx=4)

        ttk.Button(
            hover_buttons,
            text="STOP",
            command=self.hover_stop
        ).pack(side="left", padx=4)

        trim_frame = ttk.LabelFrame(right_col, text="Motor Trim", padding=10)
        trim_frame.pack(fill="both", expand=True)

        self._add_scale(
            parent=trim_frame,
            row=0,
            label="Motor 0",
            variable=self.trim0_var,
            low=0.90,
            high=1.10,
            auto_send=False
        )

        self._add_scale(
            parent=trim_frame,
            row=1,
            label="Motor 1",
            variable=self.trim1_var,
            low=0.90,
            high=1.10,
            auto_send=False
        )

        self._add_scale(
            parent=trim_frame,
            row=2,
            label="Motor 2",
            variable=self.trim2_var,
            low=0.90,
            high=1.10,
            auto_send=False
        )

        self._add_scale(
            parent=trim_frame,
            row=3,
            label="Motor 3",
            variable=self.trim3_var,
            low=0.90,
            high=1.10,
            auto_send=False
        )

        trim_buttons = ttk.Frame(trim_frame)
        trim_buttons.grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))

        ttk.Button(
            trim_buttons,
            text="SET TRIM",
            command=self.set_motor_trim
        ).pack(side="left", padx=4)

        ttk.Button(
            trim_buttons,
            text="RESET TRIM",
            command=self.reset_motor_trim
        ).pack(side="left", padx=4)

        # ---------------- Bottom action bar ----------------
        buttons = ttk.LabelFrame(main, text="Flight Actions", padding=10)
        buttons.pack(fill="x", pady=(10, 0))

        ttk.Button(buttons, text="ARM", command=self.arm).pack(side="left", padx=5)
        ttk.Button(buttons, text="SEND AXES", command=self.send_axes).pack(side="left", padx=5)
        ttk.Button(buttons, text="ZERO AXES", command=self.zero_axes).pack(side="left", padx=5)
        ttk.Button(buttons, text="DISARM", command=self.disarm).pack(side="left", padx=5)
        ttk.Button(buttons, text="QUIT", command=self.quit_all).pack(side="right", padx=5)

    def _add_scale(self, parent, row, label, variable, low, high, auto_send=True) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w")

        callback = (lambda _v: self.on_axis_change()) if auto_send else (lambda _v: None)

        scale = tk.Scale(
            parent,
            from_=low,
            to=high,
            resolution=0.001,
            orient="horizontal",
            length=360,
            variable=variable,
            command=callback,
        )
        scale.grid(row=row, column=1, padx=10, pady=4, sticky="w")

    def clamp(self, value: float, low: float, high: float) -> float:
        return max(low, min(high, float(value)))

    def hover_is_on(self) -> bool:
        return self.hover_status_var.get() == "HOVER ON"

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

            self.receiver_running = True
            self.receiver_thread = threading.Thread(target=self.receive_loop, daemon=True)
            self.receiver_thread.start()

            self.status_var.set(f"Connected to {host}:{port}")
            self.send_message({"type": "hello", "from": LAPTOP_IP})

        except Exception as exc:
            self.status_var.set(f"Connect failed: {exc}")

    def disconnect(self) -> None:
        self.receiver_running = False

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
        self.hover_status_var.set("HOVER OFF")

    def send_message(self, payload: dict) -> bool:
        data = (json.dumps(payload) + "\n").encode("utf-8")

        with self.sock_lock:
            if not self.connected or self.sock is None:
                self.status_var.set("Not connected")
                return False

            try:
                self.sock.sendall(data)
                return True
            except Exception as exc:
                self.status_var.set(f"Send failed: {exc}")

                try:
                    self.sock.close()
                except Exception:
                    pass

                self.sock = None
                self.connected = False
                self.receiver_running = False
                self.armed_var.set("DISARMED")
                self.hover_status_var.set("HOVER OFF")
                return False

    def receive_loop(self) -> None:
        buffer = ""

        while self.receiver_running:
            try:
                with self.sock_lock:
                    sock = self.sock

                if sock is None:
                    break

                data = sock.recv(4096)
                if not data:
                    break

                buffer += data.decode("utf-8", errors="ignore")

                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        msg = json.loads(line)
                    except Exception:
                        continue

                    self.root.after(0, self.handle_server_message, msg)

            except Exception:
                break

        self.receiver_running = False
        self.connected = False

        with self.sock_lock:
            try:
                if self.sock is not None:
                    self.sock.close()
            except Exception:
                pass
            self.sock = None

        self.root.after(0, self.armed_var.set, "DISARMED")
        self.root.after(0, self.hover_status_var.set, "HOVER OFF")
        self.root.after(0, self.status_var.set, "Disconnected")

    def handle_server_message(self, msg: dict) -> None:
        msg_type = msg.get("type")

        if msg_type == "status":
            if msg.get("armed", False):
                self.armed_var.set("ARMED")
            else:
                self.armed_var.set("DISARMED")

            if msg.get("hover_mode", False):
                self.hover_status_var.set("HOVER ON")
            else:
                self.hover_status_var.set("HOVER OFF")

            motor_trim = msg.get("motor_trim")
            if isinstance(motor_trim, list) and len(motor_trim) == 4:
                self.trim0_var.set(float(motor_trim[0]))
                self.trim1_var.set(float(motor_trim[1]))
                self.trim2_var.set(float(motor_trim[2]))
                self.trim3_var.set(float(motor_trim[3]))

            note = msg.get("note")
            if note:
                self.status_var.set(str(note))

        elif msg_type == "ack":
            command = msg.get("command", "unknown")
            ok = bool(msg.get("ok", False))
            note = msg.get("note", "")

            if msg.get("armed", False):
                self.armed_var.set("ARMED")
            else:
                self.armed_var.set("DISARMED")

            if msg.get("hover_mode", False):
                self.hover_status_var.set("HOVER ON")
            else:
                self.hover_status_var.set("HOVER OFF")

            motor_trim = msg.get("motor_trim")
            if isinstance(motor_trim, list) and len(motor_trim) == 4:
                self.trim0_var.set(float(motor_trim[0]))
                self.trim1_var.set(float(motor_trim[1]))
                self.trim2_var.set(float(motor_trim[2]))
                self.trim3_var.set(float(motor_trim[3]))

            prefix = "OK" if ok else "FAIL"
            self.status_var.set(f"{prefix} {command}: {note}")

    def build_axes_payload(self) -> dict:
        return {
            "type": "set_axes",
            "throttle": self.clamp(self.throttle_var.get(), 0.0, MAX_THROTTLE),
            "roll": self.clamp(self.roll_var.get(), -MAX_AXIS_CMD, MAX_AXIS_CMD),
            "pitch": self.clamp(self.pitch_var.get(), -MAX_AXIS_CMD, MAX_AXIS_CMD),
            "yaw": self.clamp(self.yaw_var.get(), -MAX_AXIS_CMD, MAX_AXIS_CMD),
        }

    def ensure_armed(self) -> bool:
        if not self.connected:
            self.status_var.set("Not connected")
            return False

        if self.armed_var.get().startswith("ARMED"):
            return True

        self.arm()

        # Wait briefly for async ACK/STATUS from the drone.
        for _ in range(30):  # ~1.5 seconds total
            self.root.update_idletasks()
            self.root.update()
            if self.armed_var.get().startswith("ARMED"):
                return True
            threading.Event().wait(0.05)

        self.status_var.set("Arm timed out")
        return False

    def arm(self) -> None:
        if not self.connected:
            self.status_var.set("Not connected")
            return

        if self.armed_var.get().startswith("ARMED"):
            self.status_var.set("Already armed")
            return

        self.hover_status_var.set("HOVER OFF")
        self.throttle_var.set(0.0)
        self.roll_var.set(0.0)
        self.pitch_var.set(0.0)
        self.yaw_var.set(0.0)

        if not self.send_message({
            "type": "set_axes",
            "throttle": 0.0,
            "roll": 0.0,
            "pitch": 0.0,
            "yaw": 0.0,
        }):
            return

        if not self.send_message({"type": "hover_stop"}):
            return

        if not self.send_message({"type": "arm"}):
            return

        self.status_var.set("Arm command sent")

    def send_axes(self) -> None:
        if not self.ensure_armed():
            return

        if self.hover_is_on():
            self.status_var.set("Disable hover before sending manual axes")
            return

        if self.send_message(self.build_axes_payload()):
            self.status_var.set("Axes sent")

    def zero_axes(self) -> None:
        self.throttle_var.set(0.0)
        self.roll_var.set(0.0)
        self.pitch_var.set(0.0)
        self.yaw_var.set(0.0)

        if self.armed_var.get().startswith("ARMED") and not self.hover_is_on():
            self.send_message({
                "type": "set_axes",
                "throttle": 0.0,
                "roll": 0.0,
                "pitch": 0.0,
                "yaw": 0.0,
            })

        self.status_var.set("Axes zeroed")

    def set_hover_throttle(self) -> None:
        hover_throttle = self.clamp(self.hover_throttle_var.get(), 0.0, MAX_HOVER_THROTTLE)

        if self.send_message({
            "type": "set_hover_throttle",
            "hover_throttle": hover_throttle,
        }):
            self.status_var.set(f"Hover throttle sent: {hover_throttle:.3f}")

    def set_stabilize(self, enabled: bool) -> None:
        if self.send_message({
            "type": "set_stabilize",
            "enabled": bool(enabled),
        }):
            self.status_var.set(f"Stabilize set to {enabled}")

    def set_gains(self, kp_roll: float, kp_pitch: float, kp_yaw: float) -> None:
        if self.send_message({
            "type": "set_gains",
            "kp_roll": float(kp_roll),
            "kp_pitch": float(kp_pitch),
            "kp_yaw": float(kp_yaw),
        }):
            self.status_var.set(
                f"Gains sent: roll={kp_roll:.4f}, pitch={kp_pitch:.4f}, yaw={kp_yaw:.4f}"
            )

    def set_motor_trim(self) -> None:
        trims = [
            self.clamp(self.trim0_var.get(), 0.90, 1.10),
            self.clamp(self.trim1_var.get(), 0.90, 1.10),
            self.clamp(self.trim2_var.get(), 0.90, 1.10),
            self.clamp(self.trim3_var.get(), 0.90, 1.10),
        ]

        if self.send_message({
            "type": "set_motor_trim",
            "trim": trims,
        }):
            self.status_var.set(
                f"Motor trim sent: [{trims[0]:.2f}, {trims[1]:.2f}, {trims[2]:.2f}, {trims[3]:.2f}]"
            )

    def reset_motor_trim(self) -> None:
        self.trim0_var.set(1.0)
        self.trim1_var.set(1.0)
        self.trim2_var.set(1.0)
        self.trim3_var.set(1.0)
        self.set_motor_trim()

    def hover_start(self) -> None:
        if not self.ensure_armed():
            return

        self.throttle_var.set(0.0)
        self.roll_var.set(0.0)
        self.pitch_var.set(0.0)
        self.yaw_var.set(0.0)

        if not self.send_message({
            "type": "set_axes",
            "throttle": 0.0,
            "roll": 0.0,
            "pitch": 0.0,
            "yaw": 0.0,
        }):
            return

        hover_throttle = self.clamp(
            self.hover_throttle_var.get(),
            0.0,
            MAX_HOVER_THROTTLE,
        )

        if self.send_message({
            "type": "hover_start",
            "hover_throttle": hover_throttle,
        }):
            self.status_var.set(f"Hover start command sent: {hover_throttle:.3f}")

    def hover_stop(self) -> None:
        if self.send_message({"type": "hover_stop"}):
            self.status_var.set("Hover stop command sent")

    def disarm(self) -> None:
        if not self.connected:
            self.status_var.set("Disconnected")
            return

        self.throttle_var.set(0.0)
        self.roll_var.set(0.0)
        self.pitch_var.set(0.0)
        self.yaw_var.set(0.0)

        self.send_message({"type": "hover_stop"})

        self.send_message({
            "type": "set_axes",
            "throttle": 0.0,
            "roll": 0.0,
            "pitch": 0.0,
            "yaw": 0.0,
        })

        if self.send_message({"type": "disarm"}):
            self.status_var.set("Disarm command sent")

    def on_axis_change(self) -> None:
        if not self.armed_var.get().startswith("ARMED"):
            return

        if self.hover_is_on():
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
