#!/usr/bin/env python3
import array
import json
import socket
import threading
import time
from pathlib import Path

from quanser.hardware import HIL
from quanser.hardware import PWMMode

HOST = "0.0.0.0"
PORT = 9001

PWM_CHANNELS = array.array("I", [0, 1, 2, 3])

# Sensor channels
OTHER_CHANNELS = array.array("I", [
    3000, 3001, 3002,   # gyro0
    3003, 3004, 3005,   # gyro1
    4000, 4001, 4002,   # accel0
    4003, 4004, 4005,   # accel1
    17000, 17001, 17002 # flow x, flow y, features
])

ANALOG_CHANNELS = array.array("I", [
    1, 2, 3             # electronics current, motor current, battery voltage
])

# Safe low limits for live testing
MAX_THROTTLE = 0.10
MAX_AXIS_CMD = 0.03

# DSHOT
DSHOT_CMD_DISARM = 0
DSHOT_CMD_ARMED = 48
DSHOT_PWM_FREQUENCY = array.array("d", [1200000.0, 1200000.0, 1200000.0, 1200000.0])
DSHOT_PWM_MODE = array.array("i", [int(PWMMode.RAW)] * 4)

DISARM_BURST_SECONDS = 0.5
DISARM_BURST_PERIOD = 0.02

# Logging
LOG_DIR = Path.home() / "rotor_mapping" / "flight_logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "control_log.jsonl"

# Loop timing
CONTROL_PERIOD = 0.02   # 50 Hz


class DroneControlLogger:
    def __init__(self):
        self.card = None
        self.running = True
        self.armed = False

        self.lock = threading.Lock()

        self.last_throttle_only = [0.0, 0.0, 0.0, 0.0]
        self.last_axes = {
            "throttle": 0.0,
            "roll": 0.0,
            "pitch": 0.0,
            "yaw": 0.0,
        }

        self.last_motor_outputs = [0.0, 0.0, 0.0, 0.0]
        self.last_packets = [0, 0, 0, 0]

        self.other_buf = array.array("d", [0.0] * len(OTHER_CHANNELS))
        self.analog_buf = array.array("d", [0.0] * len(ANALOG_CHANNELS))

        self.loop_thread = threading.Thread(target=self.control_loop, daemon=True)

    def log_event(self, event_type, extra=None):
        record = {
            "ts": time.time(),
            "event": event_type,
            "armed": self.armed,
            "last_axes": self.last_axes,
            "last_motor_outputs": self.last_motor_outputs,
            "last_packets": self.last_packets,
        }

        if extra:
            record.update(extra)

        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def clamp_scalar(self, value, low, high):
        if value < low:
            return low
        if value > high:
            return high
        return value

    def clamp_throttle(self, value):
        try:
            x = float(value)
        except Exception:
            x = 0.0
        return self.clamp_scalar(x, 0.0, MAX_THROTTLE)

    def clamp_axis(self, value):
        try:
            x = float(value)
        except Exception:
            x = 0.0
        return self.clamp_scalar(x, -MAX_AXIS_CMD, MAX_AXIS_CMD)

    def clamp_motor_outputs(self, values):
        return [self.clamp_scalar(v, 0.0, MAX_THROTTLE) for v in values[:4]]

    def dshot_make_packet(self, throttle_fraction, telemetry=0, command=DSHOT_CMD_ARMED):
        telemetry = 1 if telemetry else 0

        if command == DSHOT_CMD_ARMED:
            throttle_fraction = max(0.0, min(1.0, throttle_fraction))
            throttle_value = 48 + int(round(throttle_fraction * (2047 - 48)))
            if throttle_value > 2047:
                throttle_value = 2047
            data = throttle_value
        else:
            data = int(command) & 0x7FF

        value = ((data & 0x7FF) << 1) | telemetry
        checksum = (value ^ (value >> 4) ^ (value >> 8)) & 0x0F
        packet = ((value << 4) | checksum) & 0xFFFF
        return packet

    def write_dshot_packets(self, packets):
        packet_array = array.array("d", [float(p) for p in packets])
        self.card.write_pwm(PWM_CHANNELS, len(PWM_CHANNELS), packet_array)

    def read_sensors(self):
        self.card.read_other(OTHER_CHANNELS, len(OTHER_CHANNELS), self.other_buf)
        self.card.read_analog(ANALOG_CHANNELS, len(ANALOG_CHANNELS), self.analog_buf)

        return {
            "gyro0": list(self.other_buf[0:3]),
            "gyro1": list(self.other_buf[3:6]),
            "accel0": list(self.other_buf[6:9]),
            "accel1": list(self.other_buf[9:12]),
            "flow_xy": list(self.other_buf[12:14]),
            "flow_features": self.other_buf[14],
            "analog": list(self.analog_buf),
        }

    def send_disarm_burst(self):
        end_time = time.time() + DISARM_BURST_SECONDS
        disarm_packets = [
            self.dshot_make_packet(0.0, telemetry=0, command=DSHOT_CMD_DISARM),
            self.dshot_make_packet(0.0, telemetry=0, command=DSHOT_CMD_DISARM),
            self.dshot_make_packet(0.0, telemetry=0, command=DSHOT_CMD_DISARM),
            self.dshot_make_packet(0.0, telemetry=0, command=DSHOT_CMD_DISARM),
        ]

        while time.time() < end_time:
            self.write_dshot_packets(disarm_packets)
            time.sleep(DISARM_BURST_PERIOD)

    def open_card(self):
        self.card = HIL()
        self.card.open("qdrone2", "0")

        if not self.card.is_valid():
            raise RuntimeError("HIL card is not valid")

        options = "pwm03_dshot=1"
        self.card.set_card_specific_options(options, len(options))
        self.card.set_pwm_mode(PWM_CHANNELS, len(PWM_CHANNELS), DSHOT_PWM_MODE)
        self.card.set_pwm_frequency(PWM_CHANNELS, len(PWM_CHANNELS), DSHOT_PWM_FREQUENCY)

        print("[DRONE] qdrone2 opened successfully")
        print("[DRONE] DSHOT enabled on PWM 0:3")
        print("[DRONE] PWM mode set to RAW")
        print("[DRONE] PWM frequency set to DSHOT1200")

        self.send_disarm_burst()
        self.log_event("startup_complete")
        print("[DRONE] Initial disarm burst sent")

    def arm(self):
        with self.lock:
            if self.card is None:
                raise RuntimeError("Card not open")

            packets = [
                self.dshot_make_packet(0.0, telemetry=0, command=DSHOT_CMD_ARMED),
                self.dshot_make_packet(0.0, telemetry=0, command=DSHOT_CMD_ARMED),
                self.dshot_make_packet(0.0, telemetry=0, command=DSHOT_CMD_ARMED),
                self.dshot_make_packet(0.0, telemetry=0, command=DSHOT_CMD_ARMED),
            ]

            for _ in range(25):
                self.write_dshot_packets(packets)
                time.sleep(0.02)

            self.armed = True
            self.last_axes = {
                "throttle": 0.0,
                "roll": 0.0,
                "pitch": 0.0,
                "yaw": 0.0,
            }
            self.last_motor_outputs = [0.0, 0.0, 0.0, 0.0]
            self.last_packets = packets
            self.log_event("armed")
            print("[DRONE] ARMED (DSHOT)")

    def disarm(self):
        with self.lock:
            if self.card is None:
                return

            self.armed = False
            self.last_axes = {
                "throttle": 0.0,
                "roll": 0.0,
                "pitch": 0.0,
                "yaw": 0.0,
            }
            self.last_motor_outputs = [0.0, 0.0, 0.0, 0.0]
            self.last_packets = [0, 0, 0, 0]

            self.send_disarm_burst()
            self.log_event("disarmed")
            print("[DRONE] DISARMED (DSHOT)")

    def apply_throttle(self, values):
        bounded = []
        for v in values[:4]:
            bounded.append(self.clamp_throttle(v))
        while len(bounded) < 4:
            bounded.append(0.0)

        with self.lock:
            if self.card is None:
                raise RuntimeError("Card not open")

            if not self.armed:
                print("[DRONE] Ignored throttle update while DISARMED")
                return

            packets = [
                self.dshot_make_packet(bounded[0], telemetry=0, command=DSHOT_CMD_ARMED),
                self.dshot_make_packet(bounded[1], telemetry=0, command=DSHOT_CMD_ARMED),
                self.dshot_make_packet(bounded[2], telemetry=0, command=DSHOT_CMD_ARMED),
                self.dshot_make_packet(bounded[3], telemetry=0, command=DSHOT_CMD_ARMED),
            ]

            self.write_dshot_packets(packets)
            sensors = self.read_sensors()

            self.last_axes = {
                "throttle": 0.0,
                "roll": 0.0,
                "pitch": 0.0,
                "yaw": 0.0,
            }
            self.last_throttle_only = bounded
            self.last_motor_outputs = bounded
            self.last_packets = packets

            self.log_event("apply_throttle", {
                "requested_throttle_vector": bounded,
                "sensors": sensors,
            })

            print("[DRONE] Throttle applied:", bounded)
            print("[DRONE] DSHOT packets:", packets)

    def apply_axes(self, throttle, roll, pitch, yaw):
        throttle = self.clamp_throttle(throttle)
        roll = self.clamp_axis(roll)
        pitch = self.clamp_axis(pitch)
        yaw = self.clamp_axis(yaw)

        # Confirmed motor mapping:
        # M1 = top right
        # M0 = bottom right
        # M2 = bottom left
        # M3 = top left
        #
        # Mixer order is [M0, M1, M2, M3]
        m0 = throttle - roll + pitch + yaw   # bottom right
        m1 = throttle - roll - pitch - yaw   # top right
        m2 = throttle + roll + pitch - yaw   # bottom left
        m3 = throttle + roll - pitch + yaw   # top left

        motors = self.clamp_motor_outputs([m0, m1, m2, m3])

        with self.lock:
            if self.card is None:
                raise RuntimeError("Card not open")

            if not self.armed:
                print("[DRONE] Ignored axis update while DISARMED")
                return

            packets = [
                self.dshot_make_packet(motors[0], telemetry=0, command=DSHOT_CMD_ARMED),
                self.dshot_make_packet(motors[1], telemetry=0, command=DSHOT_CMD_ARMED),
                self.dshot_make_packet(motors[2], telemetry=0, command=DSHOT_CMD_ARMED),
                self.dshot_make_packet(motors[3], telemetry=0, command=DSHOT_CMD_ARMED),
            ]

            self.write_dshot_packets(packets)
            sensors = self.read_sensors()

            self.last_axes = {
                "throttle": throttle,
                "roll": roll,
                "pitch": pitch,
                "yaw": yaw,
            }
            self.last_motor_outputs = motors
            self.last_packets = packets

            self.log_event("apply_axes", {
                "requested_axes": self.last_axes,
                "mixed_motors": motors,
                "sensors": sensors,
            })

            print("[DRONE] Axes:", self.last_axes)
            print("[DRONE] Mixed motors:", motors)
            print("[DRONE] DSHOT packets:", packets)

    def control_loop(self):
        while self.running:
            time.sleep(CONTROL_PERIOD)
            with self.lock:
                if self.card is None:
                    continue
                try:
                    sensors = self.read_sensors()
                    self.log_event("telemetry", {"sensors": sensors})
                except Exception as exc:
                    self.log_event("telemetry_error", {"error": str(exc)})

    def handle_client(self, conn, addr):
        print("[DRONE] Client connected: {}".format(addr))
        self.log_event("client_connected", {"addr": "{}:{}".format(addr[0], addr[1])})
        file_obj = conn.makefile("r")

        try:
            for line in file_obj:
                line = line.strip()
                if not line:
                    continue

                try:
                    msg = json.loads(line)
                except ValueError:
                    print("[DRONE] Bad JSON: {!r}".format(line))
                    self.log_event("bad_json", {"raw_line": line})
                    continue

                msg_type = msg.get("type")

                if msg_type == "hello":
                    print("[DRONE] HELLO from {}".format(msg.get("from")))
                    self.log_event("hello", {"from": msg.get("from")})

                elif msg_type == "arm":
                    self.arm()

                elif msg_type == "disarm":
                    self.disarm()

                elif msg_type in ("set_pwm", "set_throttle"):
                    self.apply_throttle(msg.get("values", [0.0, 0.0, 0.0, 0.0]))

                elif msg_type == "set_axes":
                    self.apply_axes(
                        throttle=msg.get("throttle", 0.0),
                        roll=msg.get("roll", 0.0),
                        pitch=msg.get("pitch", 0.0),
                        yaw=msg.get("yaw", 0.0),
                    )

                else:
                    print("[DRONE] Unknown message type: {}".format(msg_type))
                    self.log_event("unknown_message_type", {"message": msg})

        except Exception as exc:
            print("[DRONE] Client error: {}".format(exc))
            self.log_event("client_error", {"error": str(exc)})

        finally:
            print("[DRONE] Client disconnected: {}".format(addr))
            self.log_event("client_disconnected", {"addr": "{}:{}".format(addr[0], addr[1])})

            try:
                conn.close()
            except Exception:
                pass

            self.disarm()

    def serve(self):
        self.open_card()
        self.loop_thread.start()

        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, PORT))
        server.listen(1)

        print("[DRONE] Listening on {}:{}".format(HOST, PORT))
        print("[DRONE] Logging to {}".format(LOG_FILE))

        try:
            while self.running:
                conn, addr = server.accept()
                self.handle_client(conn, addr)
        finally:
            try:
                server.close()
            except Exception:
                pass

            self.disarm()

            if self.card is not None:
                try:
                    self.card.close()
                except Exception:
                    pass

            self.log_event("shutdown_complete")
            print("[DRONE] Shutdown complete")


def main():
    receiver = DroneControlLogger()
    receiver.serve()


if __name__ == "__main__":
    main()
