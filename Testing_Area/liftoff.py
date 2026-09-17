#!/usr/bin/env python3
import array
import json
import socket
import threading
import time

from quanser.hardware import HIL, PWMMode


HOST = "0.0.0.0"
PORT = 9001

PWM_CHANNELS = array.array("I", [0, 1, 2, 3])
OTHER_CHANNELS = array.array("I", [3000, 3001, 3002, 4000, 4001, 4002])

MAX_LIFT = 1.00
CONTROL_PERIOD = 0.02

DEFAULT_LIFT_TARGET = 0.90
DEFAULT_HOVER_TARGET = 0.72

LIFT_RAMP_STEP = 0.003
HOVER_RAMP_STEP = 0.001
LIFTOFF_HOLD_SECONDS = 2.50

DSHOT_CMD_DISARM = 0
DSHOT_CMD_ARMED = 48

DSHOT_PWM_FREQUENCY = array.array("d", [1200000.0] * 4)
DSHOT_PWM_MODE = array.array("i", [int(PWMMode.RAW)] * 4)

DISARM_BURST_SECONDS = 0.5
DISARM_BURST_PERIOD = 0.02

DEFAULT_FORMAT_NAME = "C neutral"
DEFAULT_MOTOR_ORDER = [0, 1, 2, 3]
DEFAULT_MOTOR_TRIMS = [0.97, 0.97, 1.03, 1.03]

STABILIZE_DEFAULT = True

KP_ROLL = 0.006
KP_PITCH = 0.006
KP_YAW = 0.001

MAX_CORRECTION = 0.020

AUTO_SIGN_TUNE = False
SIGN_TEST_SECONDS = 1.25
SIGN_FLIP_THRESHOLD = 0.18
SIGN_COOLDOWN_SECONDS = 0.35


class LiftHoverServer:
    def __init__(self):
        self.card = None
        self.running = True
        self.lock = threading.Lock()

        self.client_conn = None
        self.client_send_lock = threading.Lock()

        self.armed = False
        self.mode = "idle"

        self.current_lift = 0.0
        self.lift_target = DEFAULT_LIFT_TARGET
        self.hover_target = DEFAULT_HOVER_TARGET

        self.format_name = DEFAULT_FORMAT_NAME
        self.motor_order = list(DEFAULT_MOTOR_ORDER)
        self.motor_trims = list(DEFAULT_MOTOR_TRIMS)

        self.stabilize = STABILIZE_DEFAULT
        self.kp_roll = KP_ROLL
        self.kp_pitch = KP_PITCH
        self.kp_yaw = KP_YAW
        self.max_correction = MAX_CORRECTION

        self.roll_sign = 1.0
        self.pitch_sign = -1.0
        self.yaw_sign = -1.0

        self.auto_sign_tune = AUTO_SIGN_TUNE
        self.sign_test_start_time = None
        self.last_sign_flip_time = 0.0
        self.prev_abs_gyro = [0.0, 0.0, 0.0]
        self.bad_sign_score = [0, 0, 0]

        self.gyro_bias = [0.0, 0.0, 0.0]
        self.last_gyro = [0.0, 0.0, 0.0]
        self.last_accel = [0.0, 0.0, 0.0]

        self.lift_start_time = None
        self.last_packets = [0, 0, 0, 0]
        self.last_motor_values = [0.0, 0.0, 0.0, 0.0]

        self.loop_thread = threading.Thread(target=self.control_loop, daemon=True)

    def clamp(self, value, low, high):
        return max(low, min(high, value))

    def clamp_lift(self, value):
        try:
            return self.clamp(float(value), 0.0, MAX_LIFT)
        except Exception:
            return 0.0

    def clamp_trim(self, value):
        try:
            return self.clamp(float(value), 0.85, 1.15)
        except Exception:
            return 1.0

    def valid_order(self, order):
        return isinstance(order, list) and sorted(order) == [0, 1, 2, 3]

    def send_client_message(self, payload):
        if self.client_conn is None:
            return

        try:
            data = (json.dumps(payload) + "\n").encode("utf-8")
            with self.client_send_lock:
                self.client_conn.sendall(data)
        except Exception:
            pass

    def status_payload(self, note=None):
        return {
            "type": "status",
            "armed": self.armed,
            "mode": self.mode,
            "current_lift": self.current_lift,
            "lift_target": self.lift_target,
            "hover_target": self.hover_target,
            "format_name": self.format_name,
            "motor_order": self.motor_order,
            "motor_trims": self.motor_trims,
            "stabilize": self.stabilize,
            "auto_sign_tune": self.auto_sign_tune,
            "signs": {
                "roll": self.roll_sign,
                "pitch": self.pitch_sign,
                "yaw": self.yaw_sign,
            },
            "gains": {
                "roll": self.kp_roll,
                "pitch": self.kp_pitch,
                "yaw": self.kp_yaw,
                "max": self.max_correction,
            },
            "gyro": self.last_gyro,
            "accel": self.last_accel,
            "last_motor_values": self.last_motor_values,
            "last_packets": self.last_packets,
            "note": note,
        }

    def send_status(self, note=None):
        self.send_client_message(self.status_payload(note))

    def send_ack(self, command, ok=True, note=None):
        payload = self.status_payload(note)
        payload["type"] = "ack"
        payload["command"] = command
        payload["ok"] = bool(ok)
        self.send_client_message(payload)

    def dshot_make_packet(self, throttle_fraction, telemetry=0, command=DSHOT_CMD_ARMED):
        telemetry = 1 if telemetry else 0

        if command == DSHOT_CMD_ARMED:
            throttle_fraction = self.clamp(throttle_fraction, 0.0, 1.0)
            throttle_value = 48 + int(round(throttle_fraction * (2047 - 48)))
            data = int(self.clamp(throttle_value, 48, 2047))
        else:
            data = int(command) & 0x7FF

        value = ((data & 0x7FF) << 1) | telemetry
        checksum = (value ^ (value >> 4) ^ (value >> 8)) & 0x0F
        return ((value << 4) | checksum) & 0xFFFF

    def write_dshot_packets(self, packets):
        packet_array = array.array("d", [float(p) for p in packets])
        self.card.write_pwm(PWM_CHANNELS, len(PWM_CHANNELS), packet_array)

    def send_disarm_burst(self):
        packets = [self.dshot_make_packet(0.0, 0, DSHOT_CMD_DISARM)] * 4
        end_time = time.time() + DISARM_BURST_SECONDS

        while time.time() < end_time:
            self.write_dshot_packets(packets)
            time.sleep(DISARM_BURST_PERIOD)

    def read_motion(self):
        values = array.array("d", [0.0] * len(OTHER_CHANNELS))

        try:
            self.card.read_other(OTHER_CHANNELS, len(OTHER_CHANNELS), values)

            gyro = [
                values[0] - self.gyro_bias[0],
                values[1] - self.gyro_bias[1],
                values[2] - self.gyro_bias[2],
                ]

            accel = [values[3], values[4], values[5]]

            self.last_gyro = gyro
            self.last_accel = accel

            return gyro, accel

        except Exception:
            return self.last_gyro, self.last_accel

    def calibrate_gyro(self, samples=200):
        sums = [0.0, 0.0, 0.0]
        values = array.array("d", [0.0] * len(OTHER_CHANNELS))

        for _ in range(samples):
            try:
                self.card.read_other(OTHER_CHANNELS, len(OTHER_CHANNELS), values)
                sums[0] += values[0]
                sums[1] += values[1]
                sums[2] += values[2]
            except Exception:
                pass

            time.sleep(0.005)

        self.gyro_bias = [s / float(samples) for s in sums]
        print(f"[DRONE] gyro bias = {self.gyro_bias}")

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

        self.calibrate_gyro()
        self.send_disarm_burst()

    def arm(self):
        with self.lock:
            if self.card is None:
                self.send_ack("arm", False, "card_not_open")
                return

            packets = [self.dshot_make_packet(0.0, 0, DSHOT_CMD_ARMED)] * 4

            for _ in range(25):
                self.write_dshot_packets(packets)
                time.sleep(0.02)

            self.armed = True
            self.mode = "armed"
            self.current_lift = 0.0
            self.lift_start_time = None
            self.last_packets = packets
            self.last_motor_values = [0.0] * 4

            print("[DRONE] ARMED")
            self.send_ack("arm", True, "armed")
            self.send_status("armed")

    def disarm(self):
        with self.lock:
            if self.card is None:
                return

            self.armed = False
            self.mode = "idle"
            self.current_lift = 0.0
            self.lift_start_time = None
            self.last_packets = [0, 0, 0, 0]
            self.last_motor_values = [0.0] * 4

            self.send_disarm_burst()

            print("[DRONE] DISARMED")
            self.send_ack("disarm", True, "disarmed")
            self.send_status("disarmed")

    def set_lift(self, lift):
        with self.lock:
            self.lift_target = self.clamp_lift(lift)
            self.send_ack("set_lift", True, f"lift_target={self.lift_target:.3f}")

    def set_hover(self, hover):
        with self.lock:
            self.hover_target = self.clamp_lift(hover)
            self.send_ack("set_hover", True, f"hover_target={self.hover_target:.3f}")

    def set_stabilize(self, enabled):
        with self.lock:
            self.stabilize = bool(enabled)
            self.send_ack("set_stabilize", True, f"stabilize={self.stabilize}")

    def set_auto_sign_tune(self, enabled):
        with self.lock:
            self.auto_sign_tune = bool(enabled)
            self.send_ack("set_auto_sign_tune", True, f"auto_sign_tune={self.auto_sign_tune}")

    def set_gains(self, msg):
        with self.lock:
            self.kp_roll = float(msg.get("roll", self.kp_roll))
            self.kp_pitch = float(msg.get("pitch", self.kp_pitch))
            self.kp_yaw = float(msg.get("yaw", self.kp_yaw))
            self.max_correction = float(msg.get("max", self.max_correction))
            self.send_ack("set_gains", True, "gains_updated")

    def set_motor_format(self, name, order, trims):
        with self.lock:
            if not self.valid_order(order):
                self.send_ack("set_motor_format", False, "bad_motor_order")
                return

            if not isinstance(trims, list) or len(trims) != 4:
                self.send_ack("set_motor_format", False, "bad_trims")
                return

            self.format_name = str(name)
            self.motor_order = list(order)
            self.motor_trims = [self.clamp_trim(x) for x in trims]

            print(f"[DRONE] FORMAT {self.format_name}: order={self.motor_order}, trims={self.motor_trims}")
            self.send_ack("set_motor_format", True, self.format_name)

    def lift_start(self):
        with self.lock:
            if not self.armed:
                self.send_ack("lift_start", False, "not_armed")
                return

            self.mode = "lifting"
            self.current_lift = 0.0
            self.lift_start_time = time.time()

            self.sign_test_start_time = time.time()
            self.bad_sign_score = [0, 0, 0]
            self.prev_abs_gyro = [0.0, 0.0, 0.0]
            self.last_sign_flip_time = 0.0

            print("[DRONE] LIFT START")
            self.send_ack("lift_start", True, "lifting_started")

    def lift_stop(self):
        with self.lock:
            self.mode = "armed" if self.armed else "idle"
            self.current_lift = 0.0
            self.lift_start_time = None
            self.sign_test_start_time = None

            print("[DRONE] LIFT STOP")
            self.send_ack("lift_stop", True, "lift_stopped")

    def ramp_toward(self, current, target, step):
        if current < target:
            return min(current + step, target)
        if current > target:
            return max(current - step, target)
        return current

    def auto_tune_signs(self, gyro):
        if not self.auto_sign_tune:
            return

        if self.sign_test_start_time is None:
            return

        now = time.time()

        if now - self.sign_test_start_time > SIGN_TEST_SECONDS:
            return

        if now - self.last_sign_flip_time < SIGN_COOLDOWN_SECONDS:
            return

        abs_gyro = [abs(gyro[0]), abs(gyro[1]), abs(gyro[2])]

        for i in range(3):
            if self.prev_abs_gyro[i] <= 0.0001:
                self.prev_abs_gyro[i] = abs_gyro[i]
                continue

            growth = abs_gyro[i] - self.prev_abs_gyro[i]

            if growth > SIGN_FLIP_THRESHOLD:
                self.bad_sign_score[i] += 1
            else:
                self.bad_sign_score[i] = max(0, self.bad_sign_score[i] - 1)

        if self.bad_sign_score[0] >= 2:
            self.roll_sign *= -1.0
            self.bad_sign_score[0] = 0
            self.last_sign_flip_time = now
            print(f"[DRONE] AUTO FLIPPED ROLL SIGN -> {self.roll_sign}")

        if self.bad_sign_score[1] >= 2:
            self.pitch_sign *= -1.0
            self.bad_sign_score[1] = 0
            self.last_sign_flip_time = now
            print(f"[DRONE] AUTO FLIPPED PITCH SIGN -> {self.pitch_sign}")

        if self.bad_sign_score[2] >= 2:
            self.yaw_sign *= -1.0
            self.bad_sign_score[2] = 0
            self.last_sign_flip_time = now
            print(f"[DRONE] AUTO FLIPPED YAW SIGN -> {self.yaw_sign}")

        self.prev_abs_gyro = abs_gyro

    def make_packets(self, base_lift, gyro):
        roll_rate = gyro[0]
        pitch_rate = gyro[1]
        yaw_rate = gyro[2]

        roll_corr = 0.0
        pitch_corr = 0.0
        yaw_corr = 0.0

        if self.stabilize and self.mode in ("lifting", "hover"):
            roll_corr = self.clamp(
                self.roll_sign * self.kp_roll * roll_rate,
                -self.max_correction,
                self.max_correction,
                )

            pitch_corr = self.clamp(
                self.pitch_sign * self.kp_pitch * pitch_rate,
                -self.max_correction,
                self.max_correction,
                )

            yaw_corr = self.clamp(
                self.yaw_sign * self.kp_yaw * yaw_rate,
                -self.max_correction,
                self.max_correction,
                )

        logical = [
            base_lift - pitch_corr + roll_corr + yaw_corr,
            base_lift + pitch_corr + roll_corr - yaw_corr,
            base_lift - pitch_corr - roll_corr - yaw_corr,
            base_lift + pitch_corr - roll_corr + yaw_corr,
            ]

        logical = [
            self.clamp(logical[0] * self.motor_trims[0], 0.0, MAX_LIFT),
            self.clamp(logical[1] * self.motor_trims[1], 0.0, MAX_LIFT),
            self.clamp(logical[2] * self.motor_trims[2], 0.0, MAX_LIFT),
            self.clamp(logical[3] * self.motor_trims[3], 0.0, MAX_LIFT),
        ]

        channel_values = [0.0, 0.0, 0.0, 0.0]

        for logical_index in range(4):
            channel_index = self.motor_order[logical_index]
            channel_values[channel_index] = logical[logical_index]

        self.last_motor_values = channel_values

        return [
            self.dshot_make_packet(channel_values[0], 0, DSHOT_CMD_ARMED),
            self.dshot_make_packet(channel_values[1], 0, DSHOT_CMD_ARMED),
            self.dshot_make_packet(channel_values[2], 0, DSHOT_CMD_ARMED),
            self.dshot_make_packet(channel_values[3], 0, DSHOT_CMD_ARMED),
        ]

    def control_loop(self):
        while self.running:
            time.sleep(CONTROL_PERIOD)

            try:
                with self.lock:
                    if self.card is None or not self.armed:
                        continue

                    gyro, _accel = self.read_motion()
                    self.auto_tune_signs(gyro)

                    if self.mode == "lifting":
                        self.current_lift = self.ramp_toward(
                            self.current_lift,
                            self.lift_target,
                            LIFT_RAMP_STEP,
                        )

                        if self.lift_start_time is not None:
                            elapsed = time.time() - self.lift_start_time

                            if elapsed >= LIFTOFF_HOLD_SECONDS:
                                self.mode = "hover"
                                self.lift_start_time = None
                                self.sign_test_start_time = None
                                print("[DRONE] AUTO SWITCH TO HOVER")

                    elif self.mode == "hover":
                        self.current_lift = self.ramp_toward(
                            self.current_lift,
                            self.hover_target,
                            HOVER_RAMP_STEP,
                        )

                    elif self.mode == "armed":
                        self.current_lift = 0.0

                    else:
                        self.current_lift = 0.0

                    base = self.clamp(self.current_lift, 0.0, MAX_LIFT)
                    packets = self.make_packets(base, gyro)

                    self.write_dshot_packets(packets)
                    self.last_packets = packets

            except Exception as exc:
                print(f"[DRONE] control loop error: {exc}")

    def handle_client(self, conn, addr):
        print("[DRONE] Client connected:", addr)
        self.client_conn = conn
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
                    self.send_ack("bad_json", False, "invalid_json")
                    continue

                msg_type = msg.get("type")
                print(f"[DRONE] received: {msg}")

                if msg_type == "hello":
                    self.send_ack("hello", True, "hello_received")

                elif msg_type == "status":
                    self.send_status("status_requested")

                elif msg_type == "arm":
                    self.arm()

                elif msg_type == "disarm":
                    self.disarm()

                elif msg_type == "set_lift":
                    self.set_lift(msg.get("lift", DEFAULT_LIFT_TARGET))

                elif msg_type == "set_hover":
                    self.set_hover(msg.get("hover", DEFAULT_HOVER_TARGET))

                elif msg_type == "set_stabilize":
                    self.set_stabilize(msg.get("enabled", True))

                elif msg_type == "set_auto_sign_tune":
                    self.set_auto_sign_tune(msg.get("enabled", True))

                elif msg_type == "set_gains":
                    self.set_gains(msg)

                elif msg_type == "set_motor_format":
                    self.set_motor_format(
                        msg.get("name", DEFAULT_FORMAT_NAME),
                        msg.get("order", DEFAULT_MOTOR_ORDER),
                        msg.get("trims", DEFAULT_MOTOR_TRIMS),
                    )

                elif msg_type == "lift_start":
                    self.lift_start()

                elif msg_type == "lift_stop":
                    self.lift_stop()

                else:
                    self.send_ack(msg_type or "unknown", False, "unknown_message_type")

        except Exception as exc:
            print(f"[DRONE] client error: {exc}")

        finally:
            try:
                conn.close()
            except Exception:
                pass

            self.client_conn = None

            try:
                self.disarm()
            except Exception:
                pass

            print("[DRONE] Client disconnected:", addr)

    def serve(self):
        self.open_card()
        self.loop_thread.start()

        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, PORT))
        server.listen(1)

        print(f"[DRONE] Listening on {HOST}:{PORT}")

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


def main():
    server = LiftHoverServer()
    server.serve()


if __name__ == "__main__":
    main()
