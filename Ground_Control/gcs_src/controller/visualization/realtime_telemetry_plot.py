import math
import threading
from collections import deque

import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation


class RealtimeTelemetryPlotter:
    def __init__(self, max_points: int = 5000):
        self.lock = threading.Lock()

        self.x = 0.0
        self.y = 0.0
        self.z = 0.0

        self.last_timestamp = None

        self.path_x = deque(maxlen=max_points)
        self.path_y = deque(maxlen=max_points)
        self.path_z = deque(maxlen=max_points)

        self.path_x.append(self.x)
        self.path_y.append(self.y)
        self.path_z.append(self.z)

        self.latest_network = {
            "signal_strength": None,
            "latency_ms": None,
            "packet_loss": None,
        }

        self.fig = None
        self.ax = None
        self.line = None
        self.point = None
        self.anim = None

    def on_telemetry(self, record: dict) -> None:
        data = record.get("data", {})
        ts = record.get("timestamp")

        if ts is None:
            return

        with self.lock:
            if self.last_timestamp is None:
                self.last_timestamp = float(ts)

                altitude = data.get("altitude")
                if altitude is not None:
                    self.z = float(altitude)

                self._append_current_point()
                self._update_network(data)
                return

            dt = float(ts) - float(self.last_timestamp)
            self.last_timestamp = float(ts)

            if dt <= 0:
                return

            vx = float(data.get("vx", 0.0))
            vy = float(data.get("vy", 0.0))
            vz = float(data.get("vz", 0.0))
            yaw_deg = float(data.get("yaw_deg", 0.0))

            yaw_rad = math.radians(yaw_deg)

            world_vx = vx * math.cos(yaw_rad) - vy * math.sin(yaw_rad)
            world_vy = vx * math.sin(yaw_rad) + vy * math.cos(yaw_rad)
            world_vz = vz

            self.x += world_vx * dt
            self.y += world_vy * dt
            self.z += world_vz * dt

            altitude = data.get("altitude")
            if altitude is not None:
                self.z = float(altitude)

            self._append_current_point()
            self._update_network(data)

    def _append_current_point(self) -> None:
        self.path_x.append(self.x)
        self.path_y.append(self.y)
        self.path_z.append(self.z)

    def _update_network(self, data: dict) -> None:
        self.latest_network["signal_strength"] = data.get("signal_strength")
        self.latest_network["latency_ms"] = data.get("latency_ms")
        self.latest_network["packet_loss"] = data.get("packet_loss")

    def setup_figure(self) -> None:
        self.fig = plt.figure("Drone Live Telemetry Path")
        self.ax = self.fig.add_subplot(111, projection="3d")
        self.line, = self.ax.plot([], [], [], linewidth=2)
        self.point, = self.ax.plot([], [], [], marker="o")

        self.ax.set_xlabel("X")
        self.ax.set_ylabel("Y")
        self.ax.set_zlabel("Z")
        self.ax.set_title("Live Drone Path")

    def _update_plot(self, _frame):
        with self.lock:
            xs = list(self.path_x)
            ys = list(self.path_y)
            zs = list(self.path_z)

            if not xs or not ys or not zs:
                return self.line, self.point

            self.line.set_data(xs, ys)
            self.line.set_3d_properties(zs)

            self.point.set_data([xs[-1]], [ys[-1]])
            self.point.set_3d_properties([zs[-1]])

            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
            min_z, max_z = min(zs), max(zs)

            pad = 1.0
            self.ax.set_xlim(min_x - pad, max_x + pad)
            self.ax.set_ylim(min_y - pad, max_y + pad)
            self.ax.set_zlim(min(0.0, min_z - pad), max_z + pad)

            sig = self.latest_network["signal_strength"]
            lat = self.latest_network["latency_ms"]
            loss = self.latest_network["packet_loss"]

            self.ax.set_title(
                f"Live Drone Path | RSSI={sig} dBm | Latency={lat} ms | Loss={loss}"
            )

        return self.line, self.point

    def run(self) -> None:
        self.setup_figure()
        self.anim = FuncAnimation(
            self.fig,
            self._update_plot,
            interval=50,
            cache_frame_data=False
        )
        plt.show()
