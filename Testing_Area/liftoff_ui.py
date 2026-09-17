#!/usr/bin/env python3
import json
import socket
import threading
import tkinter as tk
from tkinter import ttk


DRONE_IP = "192.168.2.232"
PORT = 9001

MAX_LIFT = 1.00

# safer defaults
DEFAULT_LIFT = 0.90
DEFAULT_HOVER = 0.50

FORMATS = {
    "C neutral fixed": {
        "order": [0, 1, 2, 3],
        "trims": [0.97, 0.97, 1.03, 1.03],
    },
    "less right power": {
        "order": [0, 1, 2, 3],
        "trims": [0.95, 0.95, 1.05, 1.05],
    },
    "less left power": {
        "order": [0, 1, 2, 3],
        "trims": [1.03, 1.03, 0.97, 0.97],
    },
}


class LiftHoverUI:
    def __init__(self, root):
        self.root = root
        self.root.title("QDrone Safe Lift + Hover UI")

        self.sock = None
        self.sock_lock = threading.Lock()
        self.connected = False
        self.receiver_running = False

        self.drone_ip_var = tk.StringVar(value=DRONE_IP)
        self.port_var = tk.StringVar(value=str(PORT))

        self.status_var = tk.StringVar(value="Disconnected")
        self.arm_state_var = tk.StringVar(value="DISARMED")
        self.mode_var = tk.StringVar(value="idle")
        self.current_lift_var = tk.StringVar(value="0.000")
        self.gyro_var = tk.StringVar(value="gyro: 0, 0, 0")
        self.signs_var = tk.StringVar(value="signs: ?, ?, ?")
        self.format_var = tk.StringVar(value="C neutral fixed")
        self.stabilize_var = tk.BooleanVar(value=True)

        # turn this OFF so it does not flip signs mid-test
        self.auto_sign_var = tk.BooleanVar(value=False)

        self.last_msg_var = tk.StringVar(value="No messages yet")

        self.lift_var = tk.DoubleVar(value=DEFAULT_LIFT)
        self.hover_var = tk.DoubleVar(value=DEFAULT_HOVER)

        # safer gains
        self.roll_gain_var = tk.DoubleVar(value=0.006)
        self.pitch_gain_var = tk.DoubleVar(value=0.006)
        self.yaw_gain_var = tk.DoubleVar(value=0.001)
        self.max_corr_var = tk.DoubleVar(value=0.020)

        self.build_ui()
        self.update_button_states()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def build_ui(self):
        main = ttk.Frame(self.root, padding=12)
        main.grid(row=0, column=0, sticky="nsew")

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        row = 0

        ttk.Label(main, text="Drone IP").grid(row=row, column=0, sticky="w", padx=4, pady=4)
        ttk.Entry(main, textvariable=self.drone_ip_var, width=18).grid(row=row, column=1, sticky="ew", padx=4, pady=4)

        ttk.Label(main, text="Port").grid(row=row, column=2, sticky="w", padx=4, pady=4)
        ttk.Entry(main, textvariable=self.port_var, width=8).grid(row=row, column=3, sticky="ew", padx=4, pady=4)

        row += 1

        self.connect_button = ttk.Button(main, text="Connect", command=self.connect_to_drone)
        self.connect_button.grid(row=row, column=0, sticky="ew", padx=4, pady=4)

        self.disconnect_button = ttk.Button(main, text="Disconnect", command=self.disconnect_from_drone)
        self.disconnect_button.grid(row=row, column=1, sticky="ew", padx=4, pady=4)

        self.arm_button = ttk.Button(main, text="Arm", command=self.arm_drone)
        self.arm_button.grid(row=row, column=2, sticky="ew", padx=4, pady=4)

        self.disarm_button = ttk.Button(main, text="Disarm", command=self.disarm_drone)
        self.disarm_button.grid(row=row, column=3, sticky="ew", padx=4, pady=4)

        row += 1
        ttk.Separator(main).grid(row=row, column=0, columnspan=4, sticky="ew", pady=8)
        row += 1

        ttk.Label(main, text="Lift Target").grid(row=row, column=0, sticky="w", padx=4, pady=4)
        self.lift_scale = tk.Scale(main, from_=0.0, to=MAX_LIFT, resolution=0.001, orient="horizontal", length=360, variable=self.lift_var)
        self.lift_scale.grid(row=row, column=1, columnspan=3, sticky="ew", padx=4, pady=4)

        row += 1

        ttk.Label(main, text="Hover Target").grid(row=row, column=0, sticky="w", padx=4, pady=4)
        self.hover_scale = tk.Scale(main, from_=0.0, to=MAX_LIFT, resolution=0.001, orient="horizontal", length=360, variable=self.hover_var)
        self.hover_scale.grid(row=row, column=1, columnspan=3, sticky="ew", padx=4, pady=4)

        row += 1

        ttk.Label(main, text="Motor Format").grid(row=row, column=0, sticky="w", padx=4, pady=4)
        self.format_box = ttk.Combobox(main, textvariable=self.format_var, values=list(FORMATS.keys()), state="readonly")
        self.format_box.grid(row=row, column=1, columnspan=3, sticky="ew", padx=4, pady=4)

        row += 1

        self.stabilize_check = ttk.Checkbutton(main, text="Gyro Stabilize", variable=self.stabilize_var, command=self.apply_stabilize)
        self.stabilize_check.grid(row=row, column=0, sticky="w", padx=4, pady=4)

        self.auto_sign_check = ttk.Checkbutton(main, text="Auto Sign Tune OFF", variable=self.auto_sign_var, command=self.apply_auto_sign)
        self.auto_sign_check.grid(row=row, column=1, sticky="w", padx=4, pady=4)

        ttk.Label(main, textvariable=self.gyro_var).grid(row=row, column=2, sticky="w", padx=4, pady=4)
        ttk.Label(main, textvariable=self.signs_var).grid(row=row, column=3, sticky="w", padx=4, pady=4)

        row += 1

        ttk.Label(main, text="Roll P").grid(row=row, column=0, sticky="e", padx=4, pady=4)
        ttk.Entry(main, textvariable=self.roll_gain_var, width=8).grid(row=row, column=1, sticky="w", padx=4, pady=4)

        ttk.Label(main, text="Pitch P").grid(row=row, column=2, sticky="e", padx=4, pady=4)
        ttk.Entry(main, textvariable=self.pitch_gain_var, width=8).grid(row=row, column=3, sticky="w", padx=4, pady=4)

        row += 1

        ttk.Label(main, text="Yaw P").grid(row=row, column=0, sticky="e", padx=4, pady=4)
        ttk.Entry(main, textvariable=self.yaw_gain_var, width=8).grid(row=row, column=1, sticky="w", padx=4, pady=4)

        ttk.Label(main, text="Max Corr").grid(row=row, column=2, sticky="e", padx=4, pady=4)
        ttk.Entry(main, textvariable=self.max_corr_var, width=8).grid(row=row, column=3, sticky="w", padx=4, pady=4)

        row += 1

        self.apply_button = ttk.Button(main, text="Apply Safe Settings", command=self.apply_all)
        self.apply_button.grid(row=row, column=0, sticky="ew", padx=4, pady=4)

        self.lift_start_button = ttk.Button(main, text="Lift Start", command=self.lift_start)
        self.lift_start_button.grid(row=row, column=1, sticky="ew", padx=4, pady=4)

        self.stop_button = ttk.Button(main, text="Stop", command=self.stop_lift_hover)
        self.stop_button.grid(row=row, column=2, sticky="ew", padx=4, pady=4)

        self.next_format_button = ttk.Button(main, text="Next Trim", command=self.next_format)
        self.next_format_button.grid(row=row, column=3, sticky="ew", padx=4, pady=4)

        row += 1
        ttk.Separator(main).grid(row=row, column=0, columnspan=4, sticky="ew", pady=8)
        row += 1

        ttk.Label(main, text="Status").grid(row=row, column=0, sticky="w", padx=4, pady=4)
        ttk.Label(main, textvariable=self.status_var).grid(row=row, column=1, columnspan=3, sticky="w", padx=4, pady=4)

        row += 1

        ttk.Label(main, text="Arm State").grid(row=row, column=0, sticky="w", padx=4, pady=4)
        ttk.Label(main, textvariable=self.arm_state_var).grid(row=row, column=1, sticky="w", padx=4, pady=4)

        ttk.Label(main, text="Mode").grid(row=row, column=2, sticky="w", padx=4, pady=4)
        ttk.Label(main, textvariable=self.mode_var).grid(row=row, column=3, sticky="w", padx=4, pady=4)

        row += 1

        ttk.Label(main, text="Current Lift").grid(row=row, column=0, sticky="w", padx=4, pady=4)
        ttk.Label(main, textvariable=self.current_lift_var).grid(row=row, column=1, sticky="w", padx=4, pady=4)

        row += 1

        ttk.Label(main, text="Last Message").grid(row=row, column=0, sticky="nw", padx=4, pady=4)
        ttk.Label(main, textvariable=self.last_msg_var, wraplength=520, justify="left").grid(row=row, column=1, columnspan=3, sticky="w", padx=4, pady=4)

        for col in range(4):
            main.columnconfigure(col, weight=1)

    def update_button_states(self):
        state = "normal" if self.connected else "disabled"
        self.connect_button.config(state="disabled" if self.connected else "normal")

        for widget in [
            self.disconnect_button, self.arm_button, self.disarm_button,
            self.apply_button, self.lift_start_button, self.stop_button,
            self.next_format_button, self.lift_scale, self.hover_scale,
            self.stabilize_check, self.auto_sign_check,
        ]:
            widget.config(state=state)

    def connect_to_drone(self):
        host = self.drone_ip_var.get().strip()

        try:
            port = int(self.port_var.get().strip())
            sock = socket.create_connection((host, port), timeout=5.0)
            sock.settimeout(1.0)
        except Exception as exc:
            self.status_var.set(f"Connect failed: {exc}")
            return

        with self.sock_lock:
            self.sock = sock

        self.connected = True
        self.receiver_running = True
        threading.Thread(target=self.receiver_loop, daemon=True).start()

        self.status_var.set(f"Connected to {host}:{port}")
        self.update_button_states()

        self.send_message({"type": "hello"})
        self.send_message({"type": "status"})

    def disconnect_from_drone(self):
        if not self.connected:
            return

        self.receiver_running = False

        try:
            self.send_message({"type": "lift_stop"})
            self.send_message({"type": "set_lift", "lift": 0.0})
            self.send_message({"type": "disarm"})
        except Exception:
            pass

        with self.sock_lock:
            sock = self.sock
            self.sock = None

        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                sock.close()
            except Exception:
                pass

        self.connected = False
        self.arm_state_var.set("DISARMED")
        self.mode_var.set("idle")
        self.current_lift_var.set("0.000")
        self.status_var.set("Disconnected")
        self.update_button_states()

    def send_message(self, message):
        if not self.connected:
            self.status_var.set("Not connected")
            return False

        try:
            data = (json.dumps(message) + "\n").encode("utf-8")
            with self.sock_lock:
                sock = self.sock
            if sock is None:
                return False
            sock.sendall(data)
            return True
        except Exception as exc:
            self.status_var.set(f"Send failed: {exc}")
            self.disconnect_from_drone()
            return False

    def receiver_loop(self):
        buffer = b""

        while self.receiver_running:
            try:
                with self.sock_lock:
                    sock = self.sock
                if sock is None:
                    break
                chunk = sock.recv(4096)
            except socket.timeout:
                continue
            except Exception as exc:
                if self.receiver_running:
                    self.root.after(0, lambda e=exc: self.handle_disconnect(f"Receive failed: {e}"))
                return

            if not chunk:
                if self.receiver_running:
                    self.root.after(0, lambda: self.handle_disconnect("Server closed connection"))
                return

            buffer += chunk

            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                if not line.strip():
                    continue

                try:
                    msg = json.loads(line.decode("utf-8"))
                except Exception:
                    self.root.after(0, lambda: self.last_msg_var.set("Bad JSON from server"))
                    continue

                self.root.after(0, lambda m=msg: self.handle_server_message(m))

    def handle_server_message(self, msg):
        self.last_msg_var.set(json.dumps(msg))

        armed = bool(msg.get("armed", False))
        self.arm_state_var.set("ARMED" if armed else "DISARMED")
        self.mode_var.set(str(msg.get("mode", "idle")))

        try:
            self.current_lift_var.set(f"{float(msg.get('current_lift', 0.0)):.3f}")
        except Exception:
            self.current_lift_var.set("0.000")

        gyro = msg.get("gyro")
        if isinstance(gyro, list) and len(gyro) >= 3:
            self.gyro_var.set(f"gyro: {gyro[0]:.3f}, {gyro[1]:.3f}, {gyro[2]:.3f}")

        signs = msg.get("signs")
        if isinstance(signs, dict):
            self.signs_var.set(f"signs: {signs.get('roll')}, {signs.get('pitch')}, {signs.get('yaw')}")

        if msg.get("type") == "ack":
            command = msg.get("command", "unknown")
            ok = bool(msg.get("ok", False))
            note = msg.get("note", "")
            self.status_var.set(f"{'OK' if ok else 'FAIL'} {command}: {note}")

        elif msg.get("type") == "status":
            note = msg.get("note")
            if note:
                self.status_var.set(str(note))

    def handle_disconnect(self, reason):
        self.last_msg_var.set(reason)
        self.disconnect_from_drone()

    def selected_format(self):
        name = self.format_var.get()
        fmt = FORMATS[name]
        return name, fmt["order"], fmt["trims"]

    def apply_stabilize(self):
        self.send_message({"type": "set_stabilize", "enabled": bool(self.stabilize_var.get())})

    def apply_auto_sign(self):
        self.send_message({"type": "set_auto_sign_tune", "enabled": bool(self.auto_sign_var.get())})

    def apply_all(self):
        name, order, trims = self.selected_format()

        lift = float(self.lift_var.get())
        hover = float(self.hover_var.get())

        self.send_message({"type": "set_motor_format", "name": name, "order": order, "trims": trims})
        self.send_message({"type": "set_lift", "lift": lift})
        self.send_message({"type": "set_hover", "hover": hover})
        self.send_message({"type": "set_stabilize", "enabled": bool(self.stabilize_var.get())})
        self.send_message({"type": "set_auto_sign_tune", "enabled": bool(self.auto_sign_var.get())})
        self.send_message({
            "type": "set_gains",
            "roll": float(self.roll_gain_var.get()),
            "pitch": float(self.pitch_gain_var.get()),
            "yaw": float(self.yaw_gain_var.get()),
            "max": float(self.max_corr_var.get()),
        })

        self.status_var.set(f"Applied SAFE: {name}, lift={lift:.3f}, hover={hover:.3f}")

    def next_format(self):
        names = list(FORMATS.keys())
        current = self.format_var.get()

        try:
            index = names.index(current)
        except ValueError:
            index = 0

        self.format_var.set(names[(index + 1) % len(names)])
        self.apply_all()

    def arm_drone(self):
        self.send_message({"type": "set_lift", "lift": 0.0})
        self.send_message({"type": "arm"})
        self.status_var.set("Arm command sent")

    def disarm_drone(self):
        self.send_message({"type": "lift_stop"})
        self.send_message({"type": "set_lift", "lift": 0.0})
        self.send_message({"type": "disarm"})
        self.status_var.set("Disarm command sent")

    def lift_start(self):
        self.apply_all()
        self.send_message({"type": "lift_start"})
        self.status_var.set("Lift Start sent with SAFE settings")

    def stop_lift_hover(self):
        self.send_message({"type": "lift_stop"})
        self.send_message({"type": "set_lift", "lift": 0.0})
        self.status_var.set("Stopped")

    def on_close(self):
        self.disconnect_from_drone()
        self.root.destroy()


def main():
    root = tk.Tk()
    LiftHoverUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
