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
OTHER_CHANNELS = array.array("I", [
    3000, 3001, 3002,
    3003, 3004, 3005,
    4000, 4001, 4002,
    4003, 4004, 4005,
    17000, 17001, 17002
])

ANALOG_CHANNELS = array.array("I", [
    1, 2, 3
])

# Manual axis limits
MAX_THROTTLE = 0.50
MAX_AXIS_CMD = 0.03

# Hover / stabilize limits
MAX_HOVER_THROTTLE = 0.60
DEFAULT_HOVER_THROTTLE = 0.50
MAX_STAB_CORRECTION = 0.0015

DSHOT_CMD_DISARM = 0
DSHOT_CMD_ARMED = 48
DSHOT_PWM_FREQUENCY = array.array("d", [1200000.0, 1200000.0, 1200000.0, 1200000.0])
DSHOT_PWM_MODE = array.array("i", [int(PWMMode.RAW)] * 4)

DISARM_BURST_SECONDS = 0.5
DISARM_BURST_PERIOD = 0.02

LOG_DIR = Path.home() / "rotor_mapping" / "flight_logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "control_log.jsonl"

CONTROL_PERIOD = 0.02


class DroneControlLogger:
    def __init__(self):
        self.card = None
        self.running = True
        self.armed = False

        self.lock = threading.Lock()

        self.client_conn = None
        self.client_addr = None
        self.client_send_lock = threading.Lock()

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

        self.gyro_bias = [0.0, 0.0, 0.0]
        self.gyro_bias_ready = False
        self.motor_trim = [1.0, 1.0, 1.0, 1.0]

        self.stabilize = True
        self.hover_mode = False
        self.hover_throttle = DEFAULT_HOVER_THROTTLE
        self.current_hover_throttle = 0.0

        # Slower hover ramp so it does not jump into correction while still scraping ground
        self.HOVER_RAMP_STEP = 0.002

        # Do not stabilize until throttle is high enough that the craft is actually light on its feet
        self.STAB_ENABLE_THROTTLE = 0.18

        # Softer defaults
        self.KP_ROLL = 0.00025
        self.KP_PITCH = 0.00025
        self.KP_YAW = 0.0   # start with yaw damping OFF

        # Lower correction cap
        self.MAX_STAB_CORRECTION_LOCAL = 0.0008

        # Explicit sensor sign controls
        self.ROLL_RATE_SIGN = 1.0
        self.PITCH_RATE_SIGN = 1.0
        self.YAW_RATE_SIGN = 1.0

        # Explicit mixer sign controls
        self.ROLL_MIX_SIGN = 1.0
        self.PITCH_MIX_SIGN = 1.0
        self.YAW_MIX_SIGN = 1.0

    def log_event(self, event_type, extra=None):
        record = {
            "ts": time.time(),
            "event": event_type,
            "armed": self.armed,
            "hover_mode": self.hover_mode,
            "stabilize": self.stabilize,
            "hover_throttle": self.hover_throttle,
            "last_axes": self.last_axes,
            "last_motor_outputs": self.last_motor_outputs,
            "last_packets": self.last_packets,
        }

        if extra:
            record.update(extra)

        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def send_client_message(self, payload):
        if self.client_conn is None:
            return
        try:
            data = (json.dumps(payload) + "\n").encode("utf-8")
            with self.client_send_lock:
                self.client_conn.sendall(data)
        except Exception:
            pass
    def send_status(self, note=None):
        payload = {
            "type": "status",
            "armed": self.armed,
            "hover_mode": self.hover_mode,
            "stabilize": self.stabilize,
            "hover_throttle": self.hover_throttle,
            "last_axes": self.last_axes,
            "last_motor_outputs": self.last_motor_outputs,
            "motor_trim": self.motor_trim,
            "note": note,
        }
        self.send_client_message(payload)

    def send_ack(self, command, ok=True, note=None):
        self.send_client_message({
            "type": "ack",
            "command": command,
            "ok": bool(ok),
            "armed": self.armed,
            "hover_mode": self.hover_mode,
            "stabilize": self.stabilize,
            "hover_throttle": self.hover_throttle,
            "note": note,
        })

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

    def clamp_hover_throttle(self, value):
        try:
            x = float(value)
        except Exception:
            x = 0.0
        return self.clamp_scalar(x, 0.0, MAX_HOVER_THROTTLE)

    def clamp_axis(self, value):
        try:
            x = float(value)
        except Exception:
            x = 0.0
        return self.clamp_scalar(x, -MAX_AXIS_CMD, MAX_AXIS_CMD)

    def clamp_motor_outputs(self, values):
        return [self.clamp_scalar(v, 0.0, MAX_HOVER_THROTTLE) for v in values[:4]]

    def clamp_stab(self, value):
        return self.clamp_scalar(value, -self.MAX_STAB_CORRECTION_LOCAL, self.MAX_STAB_CORRECTION_LOCAL)

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

    def apply_motor_trim(self, values):
        trimmed = []
        for i, v in enumerate(values[:4]):
            trimmed.append(v * self.motor_trim[i])
        return self.clamp_motor_outputs(trimmed)
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
        self.send_disarm_burst()
        self.calibrate_gyro_bias()
        self.log_event("startup_complete")

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
            self.hover_mode = False
            self.last_axes = {"throttle": 0.0, "roll": 0.0, "pitch": 0.0, "yaw": 0.0}
            self.last_motor_outputs = [0.0, 0.0, 0.0, 0.0]
            self.last_packets = packets

            self.log_event("armed")
            self.send_ack("arm", True, "armed")
            self.send_status("armed")
            print("[DRONE] ARMED (DSHOT)")

    def disarm(self):
        with self.lock:
            if self.card is None:
                return

            self.armed = False
            self.hover_mode = False
            self.last_axes = {"throttle": 0.0, "roll": 0.0, "pitch": 0.0, "yaw": 0.0}
            self.last_motor_outputs = [0.0, 0.0, 0.0, 0.0]
            self.last_packets = [0, 0, 0, 0]

            self.send_disarm_burst()
            self.log_event("disarmed")
            self.send_ack("disarm", True, "disarmed")
            self.send_status("disarmed")
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
                return

            self.hover_mode = False

            packets = [
                self.dshot_make_packet(bounded[0], 0, DSHOT_CMD_ARMED),
                self.dshot_make_packet(bounded[1], 0, DSHOT_CMD_ARMED),
                self.dshot_make_packet(bounded[2], 0, DSHOT_CMD_ARMED),
                self.dshot_make_packet(bounded[3], 0, DSHOT_CMD_ARMED),
            ]

            self.write_dshot_packets(packets)
            sensors = self.read_sensors()

            self.last_axes = {"throttle": 0.0, "roll": 0.0, "pitch": 0.0, "yaw": 0.0}
            self.last_throttle_only = bounded
            self.last_motor_outputs = bounded
            self.last_packets = packets

            self.log_event("apply_throttle", {
                "requested_throttle_vector": bounded,
                "sensors": sensors,
            })
            self.send_status("manual_throttle")

    def compute_stabilized_axes(self, throttle, roll, pitch, yaw, sensors):
        gyro = sensors["gyro0"]

        raw_roll_rate = self.ROLL_RATE_SIGN * gyro[0]
        raw_pitch_rate = self.PITCH_RATE_SIGN * gyro[1]
        raw_yaw_rate = self.YAW_RATE_SIGN * gyro[2]

        if self.gyro_bias_ready:
            roll_rate = raw_roll_rate - self.gyro_bias[0]
            pitch_rate = raw_pitch_rate - self.gyro_bias[1]
            yaw_rate = raw_yaw_rate - self.gyro_bias[2]
        else:
            roll_rate = raw_roll_rate
            pitch_rate = raw_pitch_rate
            yaw_rate = raw_yaw_rate

        roll_cmd = roll
        pitch_cmd = pitch
        yaw_cmd = yaw

        # Important: do not apply stabilization while still at very low throttle.
        # On the ground this often causes skating / twisting instead of helping.
        if self.stabilize and throttle >= self.STAB_ENABLE_THROTTLE:
            roll_correction = self.clamp_stab(-self.KP_ROLL * roll_rate)
            pitch_correction = self.clamp_stab(-self.KP_PITCH * pitch_rate)
            yaw_correction = self.clamp_stab(-self.KP_YAW * yaw_rate)

            roll_cmd = self.clamp_axis(roll_cmd + roll_correction)
            pitch_cmd = self.clamp_axis(pitch_cmd + pitch_correction)
            yaw_cmd = self.clamp_axis(yaw_cmd + yaw_correction)

        return {
            "roll_cmd": roll_cmd,
            "pitch_cmd": pitch_cmd,
            "yaw_cmd": yaw_cmd,
            "throttle_cmd": throttle,
        }

    def calibrate_gyro_bias(self, samples=200, delay=0.01):
        if self.card is None:
            raise RuntimeError("Card not open")

        sums = [0.0, 0.0, 0.0]

        for _ in range(samples):
            sensors = self.read_sensors()
            gyro = sensors["gyro0"]
            sums[0] += gyro[0]
            sums[1] += gyro[1]
            sums[2] += gyro[2]
            time.sleep(delay)

        self.gyro_bias = [
            sums[0] / samples,
            sums[1] / samples,
            sums[2] / samples,
            ]
        self.gyro_bias_ready = True

        self.log_event("gyro_bias_calibrated", {
            "gyro_bias": self.gyro_bias
        })
        print(f"[DRONE] Gyro bias calibrated: {self.gyro_bias}")

    def mix_motors(self, throttle, roll, pitch, yaw):
        # Layout:
        # m0 = bottom right
        # m1 = top right
        # m2 = bottom left
        # m3 = top left
        #
        # Assumed convention:
        # +pitch = top/front side
        # +roll  = right side

        r = self.ROLL_MIX_SIGN * roll
        p = self.PITCH_MIX_SIGN * pitch
        y = self.YAW_MIX_SIGN * yaw

        m0 = throttle - p + r + y   # bottom right
        m1 = throttle + p + r - y   # top right
        m2 = throttle - p - r - y   # bottom left
        m3 = throttle + p - r + y   # top left

        return self.apply_motor_trim([m0, m1, m2, m3])
    def apply_axes(self, throttle, roll, pitch, yaw):
        throttle = self.clamp_throttle(throttle)
        roll = self.clamp_axis(roll)
        pitch = self.clamp_axis(pitch)
        yaw = self.clamp_axis(yaw)

        with self.lock:
            if self.card is None:
                raise RuntimeError("Card not open")
            if not self.armed:
                return

            sensors = self.read_sensors()
            effective_throttle = self.hover_throttle if self.hover_mode else throttle

            stab = self.compute_stabilized_axes(
                throttle=effective_throttle,
                roll=roll,
                pitch=pitch,
                yaw=yaw,
                sensors=sensors,
            )

            motors = self.mix_motors(
                throttle=stab["throttle_cmd"],
                roll=stab["roll_cmd"],
                pitch=stab["pitch_cmd"],
                yaw=stab["yaw_cmd"],
            )

            packets = [
                self.dshot_make_packet(motors[0], 0, DSHOT_CMD_ARMED),
                self.dshot_make_packet(motors[1], 0, DSHOT_CMD_ARMED),
                self.dshot_make_packet(motors[2], 0, DSHOT_CMD_ARMED),
                self.dshot_make_packet(motors[3], 0, DSHOT_CMD_ARMED),
            ]

            self.write_dshot_packets(packets)

            self.last_axes = {
                "throttle": stab["throttle_cmd"],
                "roll": stab["roll_cmd"],
                "pitch": stab["pitch_cmd"],
                "yaw": stab["yaw_cmd"],
            }
            self.last_motor_outputs = motors
            self.last_packets = packets

            self.log_event("apply_axes", {
                "requested_axes": {
                    "throttle": throttle,
                    "roll": roll,
                    "pitch": pitch,
                    "yaw": yaw,
                },
                "effective_axes": self.last_axes,
                "hover_mode": self.hover_mode,
                "mixed_motors": motors,
                "sensors": sensors,
            })
            self.send_status("manual_axes")

    def control_loop(self):
        while self.running:
            time.sleep(CONTROL_PERIOD)
            with self.lock:
                if self.card is None:
                    continue

                try:
                    sensors = self.read_sensors()

                    if self.armed and self.hover_mode:
                        if self.current_hover_throttle < self.hover_throttle:
                            self.current_hover_throttle = min(
                                self.current_hover_throttle + self.HOVER_RAMP_STEP,
                                self.hover_throttle
                            )
                        else:
                            self.current_hover_throttle = self.hover_throttle

                        # Do NOT stabilize while still very low on throttle.
                        # On-ground correction here can cause spinning/skating.
                        if self.current_hover_throttle < self.STAB_ENABLE_THROTTLE:
                            motors = self.apply_motor_trim([
                                self.current_hover_throttle,
                                self.current_hover_throttle,
                                self.current_hover_throttle,
                                self.current_hover_throttle,
                            ])

                            stab = {
                                "throttle_cmd": self.current_hover_throttle,
                                "roll_cmd": 0.0,
                                "pitch_cmd": 0.0,
                                "yaw_cmd": 0.0,
                            }
                        else:
                            stab = self.compute_stabilized_axes(
                                throttle=self.current_hover_throttle,
                                roll=0.0,
                                pitch=0.0,
                                yaw=0.0,
                                sensors=sensors,
                            )

                            motors = self.mix_motors(
                                throttle=stab["throttle_cmd"],
                                roll=stab["roll_cmd"],
                                pitch=stab["pitch_cmd"],
                                yaw=stab["yaw_cmd"],
                            )

                        packets = [
                            self.dshot_make_packet(motors[0], 0, DSHOT_CMD_ARMED),
                            self.dshot_make_packet(motors[1], 0, DSHOT_CMD_ARMED),
                            self.dshot_make_packet(motors[2], 0, DSHOT_CMD_ARMED),
                            self.dshot_make_packet(motors[3], 0, DSHOT_CMD_ARMED),
                        ]

                        self.write_dshot_packets(packets)

                        self.last_axes = {
                            "throttle": stab["throttle_cmd"],
                            "roll": stab["roll_cmd"],
                            "pitch": stab["pitch_cmd"],
                            "yaw": stab["yaw_cmd"],
                        }
                        self.last_motor_outputs = motors
                        self.last_packets = packets

                        self.log_event("hover_tick", {
                            "current_hover_throttle": self.current_hover_throttle,
                            "mixed_motors": motors,
                            "sensors": sensors,
                        })

                    else:
                        self.current_hover_throttle = 0.0
                        self.log_event("telemetry", {"sensors": sensors})

                except Exception as exc:
                    self.log_event("telemetry_error", {"error": str(exc)})

    def handle_client(self, conn, addr):
        print("[DRONE] Client connected:", addr)
        self.client_conn = conn
        self.client_addr = addr
        self.log_event("client_connected", {"addr": f"{addr[0]}:{addr[1]}"})

        file_obj = conn.makefile("r")

        try:
            self.send_status("client_connected")

            for line in file_obj:
                line = line.strip()
                if not line:
                    continue

                try:
                    msg = json.loads(line)
                except ValueError:
                    self.log_event("bad_json", {"raw_line": line})
                    self.send_ack("bad_json", False, "invalid_json")
                    continue

                msg_type = msg.get("type")

                if msg_type == "hello":
                    self.log_event("hello", {"from": msg.get("from")})
                    self.send_ack("hello", True, "hello_received")
                    self.send_status("hello_received")

                elif msg_type == "arm":
                    self.arm()

                elif msg_type == "disarm":
                    self.disarm()

                elif msg_type in ("set_pwm", "set_throttle"):
                    self.apply_throttle(msg.get("values", [0.0, 0.0, 0.0, 0.0]))
                    self.send_ack(msg_type, True, "throttle_applied")

                elif msg_type == "set_axes":
                    if not self.armed:
                        self.log_event("set_axes_rejected_not_armed", {"message": msg})
                        self.send_ack("set_axes", False, "not_armed")
                        self.send_status("set_axes_rejected_not_armed")
                        continue

                    if self.hover_mode:
                        self.log_event("set_axes_ignored_hover_active", {"message": msg})
                        self.send_ack("set_axes", False, "hover_active_ignore_axes")
                        self.send_status("hover_active_ignore_axes")
                        continue

                    self.apply_axes(
                        throttle=msg.get("throttle", 0.0),
                        roll=msg.get("roll", 0.0),
                        pitch=msg.get("pitch", 0.0),
                        yaw=msg.get("yaw", 0.0),
                    )
                    self.send_ack("set_axes", True, "axes_applied")
                    self.send_status("axes_applied")

                elif msg_type == "hover_start":
                    if not self.armed:
                        self.send_ack("hover_start", False, "not_armed")
                        self.send_status("hover_rejected_not_armed")
                        continue

                    requested = msg.get("hover_throttle", self.hover_throttle)
                    self.hover_throttle = self.clamp_hover_throttle(requested)
                    self.current_hover_throttle = 0.0

                    self.last_axes = {
                        "throttle": 0.0,
                        "roll": 0.0,
                        "pitch": 0.0,
                        "yaw": 0.0,
                    }

                    self.hover_mode = True
                    self.log_event("hover_start", {"hover_throttle": self.hover_throttle})
                    self.send_ack("hover_start", True, "hover_enabled")
                    self.send_status("hover_enabled")

                elif msg_type == "hover_stop":
                    self.hover_mode = False
                    self.last_axes = {
                        "throttle": 0.0,
                        "roll": 0.0,
                        "pitch": 0.0,
                        "yaw": 0.0,
                    }
                    self.log_event("hover_stop")
                    self.send_ack("hover_stop", True, "hover_disabled")
                    self.send_status("hover_disabled")

                elif msg_type == "set_hover_throttle":
                    requested = msg.get("hover_throttle", self.hover_throttle)
                    self.hover_throttle = self.clamp_hover_throttle(requested)
                    self.log_event("set_hover_throttle", {"hover_throttle": self.hover_throttle})
                    self.send_ack("set_hover_throttle", True, "hover_throttle_updated")
                    self.send_status("hover_throttle_updated")

                elif msg_type == "set_stabilize":
                    self.stabilize = bool(msg.get("enabled", True))
                    self.log_event("set_stabilize", {"enabled": self.stabilize})
                    self.send_ack("set_stabilize", True, "stabilize_updated")
                    self.send_status("stabilize_updated")

                elif msg_type == "set_gains":
                    self.KP_ROLL = float(msg.get("kp_roll", self.KP_ROLL))
                    self.KP_PITCH = float(msg.get("kp_pitch", self.KP_PITCH))
                    self.KP_YAW = float(msg.get("kp_yaw", self.KP_YAW))
                    self.log_event("set_gains", {
                        "kp_roll": self.KP_ROLL,
                        "kp_pitch": self.KP_PITCH,
                        "kp_yaw": self.KP_YAW,
                    })
                    self.send_ack("set_gains", True, "gains_updated")
                    self.send_status("gains_updated")

                elif msg_type == "set_motor_trim":
                    trims = msg.get("trim", self.motor_trim)

                    if not isinstance(trims, list) or len(trims) != 4:
                        self.send_ack("set_motor_trim", False, "trim_must_be_list_of_4")
                        continue

                    try:
                        new_trim = [float(x) for x in trims]
                    except Exception:
                        self.send_ack("set_motor_trim", False, "trim_values_must_be_numeric")
                        continue

                    bounded_trim = []
                    for t in new_trim:
                        if t < 0.90:
                            t = 0.90
                        elif t > 1.10:
                            t = 1.10
                        bounded_trim.append(t)

                    self.motor_trim = bounded_trim
                    self.log_event("set_motor_trim", {"motor_trim": self.motor_trim})
                    self.send_ack("set_motor_trim", True, "motor_trim_updated")
                    self.send_status("motor_trim_updated")

                else:
                    self.log_event("unknown_message_type", {"message": msg})
                    self.send_ack(msg_type or "unknown", False, "unknown_message_type")

        except Exception as exc:
            self.log_event("client_error", {"error": str(exc)})

        finally:
            try:
                conn.close()
            except Exception:
                pass

            self.client_conn = None
            self.client_addr = None
            self.log_event("client_disconnected", {"addr": f"{addr[0]}:{addr[1]}"})
            self.disarm()

    def serve(self):
        self.open_card()
        self.loop_thread.start()

        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, PORT))
        server.listen(1)

        print(f"[DRONE] Listening on {HOST}:{PORT}")
        print(f"[DRONE] Logging to {LOG_FILE}")

        try:
            while self.running:
                conn, addr = server.accept()
                self.handle_client(conn, addr)
        finally:
            try:
                server.close()
            except Exception:
                pass


            if self.card is not None:
                try:
                    self.card.close()
                except Exception:
                    pass

            self.log_event("shutdown_complete")


def main():
    receiver = DroneControlLogger()
    receiver.serve()


if __name__ == "__main__":
    main()

