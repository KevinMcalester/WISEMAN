#!/usr/bin/env python3
import array
import json
import socket
import threading
import time

from quanser.hardware import HIL
from quanser.hardware import PWMMode

HOST = "0.0.0.0"
PORT = 9001

PWM_CHANNELS = array.array("I", [0, 1, 2, 3])

# Keep test throttle LOW at first.
# This is a normalized UI value from 0.0 to 1.0, not a raw DSHOT packet.
MAX_THROTTLE = 0.10

# DSHOT command meanings used here:
# 0  = disarm
# 48 = armed / normal throttle operation
DSHOT_CMD_DISARM = 0
DSHOT_CMD_ARMED = 48

# QDrone 2 docs say PWM 0:3 can use DSHOT and should be configured in RAW mode.
# ESC Output docs say DSHOT1200 corresponds to 1200e3 PWM frequency.
DSHOT_PWM_FREQUENCY = array.array("d", [1200000.0, 1200000.0, 1200000.0, 1200000.0])
DSHOT_PWM_MODE = array.array(
    "i",
    [int(PWMMode.RAW), int(PWMMode.RAW), int(PWMMode.RAW), int(PWMMode.RAW)]
)

# How long to stream disarm packets on startup / disarm.
# This is a conservative practical step; many DSHOT ESC paths expect repeated
# disarm/zero frames before accepting throttle.
DISARM_BURST_SECONDS = 0.5
DISARM_BURST_PERIOD = 0.02


class DroneDSHOTReceiver:
    def __init__(self):
        self.card = None
        self.running = True
        self.armed = False

        self.lock = threading.Lock()
        self.last_throttle = [0.0, 0.0, 0.0, 0.0]

    def clamp_throttle(self, values):
        bounded = []
        for v in values[:4]:
            try:
                num = float(v)
            except Exception:
                num = 0.0

            if num < 0.0:
                num = 0.0
            if num > MAX_THROTTLE:
                num = MAX_THROTTLE

            bounded.append(num)

        while len(bounded) < 4:
            bounded.append(0.0)

        return bounded

    def dshot_make_packet(self, throttle_fraction, telemetry=0, command=DSHOT_CMD_ARMED):
        """
        Build a 16-bit DSHOT packet:
        - 11 bits data
        - 1 bit telemetry request
        - 4 bits checksum

        For normal motor operation, command must be 48 and throttle is encoded.
        For special commands 0..47, the throttle is ignored by the ESC protocol.
        """
        telemetry = 1 if telemetry else 0

        if command == DSHOT_CMD_ARMED:
            # DSHOT throttle field range:
            # 0 reserved for stop/disarm area
            # normal throttle values start above command range
            #
            # We map:
            #   0.0 -> 48
            #   1.0 -> 2047
            #
            # Since MAX_THROTTLE is capped low, test values stay modest.
            throttle_fraction = max(0.0, min(1.0, throttle_fraction))
            throttle_value = 48 + int(round(throttle_fraction * (2047 - 48)))
            if throttle_value > 2047:
                throttle_value = 2047
            data = throttle_value
        else:
            # special command path
            data = int(command) & 0x7FF

        value = ((data & 0x7FF) << 1) | telemetry
        checksum = (value ^ (value >> 4) ^ (value >> 8)) & 0x0F
        packet = ((value << 4) | checksum) & 0xFFFF
        return packet

    def write_dshot_packets(self, packets):
        packet_array = array.array("d", [float(p) for p in packets])
        self.card.write_pwm(
            PWM_CHANNELS,
            len(PWM_CHANNELS),
            packet_array
        )

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

        # Enable DSHOT on PWM 0:3 for QDrone 2
        options = "pwm03_dshot=1"
        self.card.set_card_specific_options(options, len(options))

        # RAW mode is required when DSHOT is enabled
        self.card.set_pwm_mode(
            PWM_CHANNELS,
            len(PWM_CHANNELS),
            DSHOT_PWM_MODE
        )

        # DSHOT1200 bitrate
        self.card.set_pwm_frequency(
            PWM_CHANNELS,
            len(PWM_CHANNELS),
            DSHOT_PWM_FREQUENCY
        )

        print("[DRONE] qdrone2 opened successfully")
        print("[DRONE] DSHOT enabled on PWM 0:3")
        print("[DRONE] PWM mode set to RAW")
        print("[DRONE] PWM frequency set to DSHOT1200")

        # Start from repeated disarm packets
        self.send_disarm_burst()
        print("[DRONE] Initial disarm burst sent")

    def arm(self):
        with self.lock:
            if self.card is None:
                raise RuntimeError("Card not open")

            # Send zero-throttle ARMED packets so the ESC path sees valid
            # normal-operation packets without immediately adding thrust.
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
            self.last_throttle = [0.0, 0.0, 0.0, 0.0]
            print("[DRONE] ARMED (DSHOT)")

    def disarm(self):
        with self.lock:
            if self.card is None:
                return

            self.armed = False
            self.last_throttle = [0.0, 0.0, 0.0, 0.0]

            self.send_disarm_burst()
            print("[DRONE] DISARMED (DSHOT)")

    def apply_throttle(self, values):
        bounded = self.clamp_throttle(values)

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
            self.last_throttle = bounded
            print("[DRONE] Throttle applied: {}".format(bounded))
            print("[DRONE] DSHOT packets: {}".format(packets))

    def handle_client(self, conn, addr):
        print("[DRONE] Client connected: {}".format(addr))
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
                    continue

                msg_type = msg.get("type")

                if msg_type == "hello":
                    print("[DRONE] HELLO from {}".format(msg.get("from")))

                elif msg_type == "arm":
                    self.arm()

                elif msg_type == "disarm":
                    self.disarm()

                elif msg_type in ("set_pwm", "set_throttle"):
                    self.apply_throttle(msg.get("values", [0.0, 0.0, 0.0, 0.0]))

                else:
                    print("[DRONE] Unknown message type: {}".format(msg_type))

        except Exception as exc:
            print("[DRONE] Client error: {}".format(exc))

        finally:
            print("[DRONE] Client disconnected: {}".format(addr))

            try:
                conn.close()
            except Exception:
                pass

            self.disarm()

    def serve(self):
        self.open_card()

        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, PORT))
        server.listen(1)

        print("[DRONE] Listening on {}:{}".format(HOST, PORT))

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

            print("[DRONE] Shutdown complete")


def main():
    receiver = DroneDSHOTReceiver()
    receiver.serve()


if __name__ == "__main__":
    main()
