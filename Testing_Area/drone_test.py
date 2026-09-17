#!/usr/bin/env python3
import array
import time
from statistics import mean

from quanser.hardware import HIL, PWMMode

PWM_CHANNELS = array.array("I", [0, 1, 2, 3])

GYRO_CHANNELS = array.array("I", [3000, 3001, 3002])   # gyro0 x,y,z
ACCEL_CHANNELS = array.array("I", [4000, 4001, 4002])  # accel0 x,y,z

DSHOT_PWM_FREQUENCY = array.array("d", [1200000.0, 1200000.0, 1200000.0, 1200000.0])
DSHOT_PWM_MODE = array.array("i", [int(PWMMode.RAW)] * 4)

DSHOT_CMD_DISARM = 0
DSHOT_CMD_ARMED = 48

SAMPLE_PERIOD = 0.005
WRITE_PERIOD = 0.02

GYRO_EVENT_THRESHOLD = 0.05
ACCEL_EVENT_THRESHOLD = 0.10


def dshot_make_packet(throttle_fraction, telemetry=0, command=DSHOT_CMD_ARMED):
    telemetry = 1 if telemetry else 0

    if command == DSHOT_CMD_ARMED:
        throttle_fraction = max(0.0, min(1.0, throttle_fraction))
        throttle_value = 48 + int(round(throttle_fraction * (2047 - 48)))
        throttle_value = min(throttle_value, 2047)
        data = throttle_value
    else:
        data = int(command) & 0x7FF

    value = ((data & 0x7FF) << 1) | telemetry
    checksum = (value ^ (value >> 4) ^ (value >> 8)) & 0x0F
    return ((value << 4) | checksum) & 0xFFFF


def write_packets(card, packets):
    packet_array = array.array("d", [float(p) for p in packets])
    card.write_pwm(PWM_CHANNELS, len(PWM_CHANNELS), packet_array)


def send_disarm_burst(card, seconds=0.5):
    end_time = time.time() + seconds
    packets = [dshot_make_packet(0.0, 0, DSHOT_CMD_DISARM)] * 4
    last_print = 0.0

    while time.time() < end_time:
        write_packets(card, packets)

        now = time.time()
        if now - last_print >= 0.2:
            print("[DISARM] sending continuous disarm packets")
            last_print = now

        time.sleep(WRITE_PERIOD)


def arm_zero(card, repeats=25):
    packets = [dshot_make_packet(0.0, 0, DSHOT_CMD_ARMED)] * 4
    for i in range(repeats):
        write_packets(card, packets)
        if i % 5 == 0:
            print("[ARM] sending armed-zero packets")
        time.sleep(WRITE_PERIOD)


def hold_armed_zero(card, seconds=0.5):
    end_time = time.time() + seconds
    packets = [dshot_make_packet(0.0, 0, DSHOT_CMD_ARMED)] * 4
    last_print = 0.0

    while time.time() < end_time:
        write_packets(card, packets)

        now = time.time()
        if now - last_print >= 0.2:
            print("[ARMED-ZERO] actively refreshing zero-throttle DSHOT")
            last_print = now

        time.sleep(WRITE_PERIOD)


def read_vector(card, channels):
    buf = array.array("d", [0.0] * len(channels))
    card.read_other(channels, len(channels), buf)
    return list(buf)


def read_gyro(card):
    return read_vector(card, GYRO_CHANNELS)


def read_accel(card):
    return read_vector(card, ACCEL_CHANNELS)


def average_sensor(card, seconds=0.5):
    gx_list, gy_list, gz_list = [], [], []
    ax_list, ay_list, az_list = [], [], []

    end_time = time.time() + seconds
    while time.time() < end_time:
        gx, gy, gz = read_gyro(card)
        ax, ay, az = read_accel(card)

        gx_list.append(gx)
        gy_list.append(gy)
        gz_list.append(gz)

        ax_list.append(ax)
        ay_list.append(ay)
        az_list.append(az)

        time.sleep(SAMPLE_PERIOD)

    return {
        "gyro": [mean(gx_list), mean(gy_list), mean(gz_list)],
        "accel": [mean(ax_list), mean(ay_list), mean(az_list)],
    }


def sign(v, deadband=0.03):
    if v > deadband:
        return "+"
    if v < -deadband:
        return "-"
    return "0"


def magnitude3(v):
    return (v[0] ** 2 + v[1] ** 2 + v[2] ** 2) ** 0.5


def pulse_single_motor(card, motor_index, throttle_fraction=0.08, pulse_seconds=0.8):
    baseline = average_sensor(card, seconds=0.4)

    packets = [dshot_make_packet(0.0, 0, DSHOT_CMD_ARMED)] * 4
    packets[motor_index] = dshot_make_packet(throttle_fraction, 0, DSHOT_CMD_ARMED)

    gx_list, gy_list, gz_list = [], [], []
    ax_list, ay_list, az_list = [], [], []

    end_time = time.time() + pulse_seconds
    last_print = 0.0

    while time.time() < end_time:
        write_packets(card, packets)

        gx, gy, gz = read_gyro(card)
        ax, ay, az = read_accel(card)

        gx_list.append(gx)
        gy_list.append(gy)
        gz_list.append(gz)

        ax_list.append(ax)
        ay_list.append(ay)
        az_list.append(az)

        now = time.time()
        if now - last_print >= 0.2:
            print(f"[ACTIVE] single motor {motor_index} throttle={throttle_fraction:.3f}")
            last_print = now

        time.sleep(SAMPLE_PERIOD)

    hold_armed_zero(card, seconds=0.5)

    during = {
        "gyro": [mean(gx_list), mean(gy_list), mean(gz_list)],
        "accel": [mean(ax_list), mean(ay_list), mean(az_list)],
    }

    delta = {
        "gyro": [during["gyro"][i] - baseline["gyro"][i] for i in range(3)],
        "accel": [during["accel"][i] - baseline["accel"][i] for i in range(3)],
    }

    return baseline, during, delta


def hold_collective_and_measure(card, throttle_fraction, hold_seconds=1.5):
    baseline = average_sensor(card, seconds=0.4)

    packets = [dshot_make_packet(throttle_fraction, 0, DSHOT_CMD_ARMED)] * 4

    gx_list, gy_list, gz_list = [], [], []
    ax_list, ay_list, az_list = [], [], []

    end_time = time.time() + hold_seconds
    last_print = 0.0

    while time.time() < end_time:
        write_packets(card, packets)

        gx, gy, gz = read_gyro(card)
        ax, ay, az = read_accel(card)

        gx_list.append(gx)
        gy_list.append(gy)
        gz_list.append(gz)

        ax_list.append(ax)
        ay_list.append(ay)
        az_list.append(az)

        now = time.time()
        if now - last_print >= 0.2:
            print(f"[ACTIVE] collective throttle={throttle_fraction:.3f}")
            last_print = now

        time.sleep(SAMPLE_PERIOD)

    hold_armed_zero(card, seconds=0.5)

    during = {
        "gyro": [mean(gx_list), mean(gy_list), mean(gz_list)],
        "accel": [mean(ax_list), mean(ay_list), mean(az_list)],
    }

    delta = {
        "gyro": [during["gyro"][i] - baseline["gyro"][i] for i in range(3)],
        "accel": [during["accel"][i] - baseline["accel"][i] for i in range(3)],
    }

    gyro_mag = magnitude3(delta["gyro"])
    accel_mag = magnitude3(delta["accel"])

    lift_hint = abs(delta["accel"][2]) > ACCEL_EVENT_THRESHOLD
    instability_hint = (
            abs(delta["gyro"][0]) > GYRO_EVENT_THRESHOLD or
            abs(delta["gyro"][1]) > GYRO_EVENT_THRESHOLD or
            abs(delta["gyro"][2]) > GYRO_EVENT_THRESHOLD
    )

    return baseline, during, delta, gyro_mag, accel_mag, lift_hint, instability_hint


def auto_collective_sweep(card, start=0.02, stop=0.20, step=0.01, hold_seconds=1.2):
    results = []

    throttle = start
    while throttle <= stop + 1e-9:
        print(f"\n[SWEEP] Testing collective throttle = {throttle:.3f}")

        baseline, during, delta, gyro_mag, accel_mag, lift_hint, instability_hint = \
            hold_collective_and_measure(card, throttle, hold_seconds)

        result = {
            "throttle": throttle,
            "baseline": baseline,
            "during": during,
            "delta": delta,
            "gyro_mag": gyro_mag,
            "accel_mag": accel_mag,
            "lift_hint": lift_hint,
            "instability_hint": instability_hint,
        }
        results.append(result)

        print(f"  delta gyro  : x={delta['gyro'][0]:+.4f}, y={delta['gyro'][1]:+.4f}, z={delta['gyro'][2]:+.4f}")
        print(f"  delta accel : x={delta['accel'][0]:+.4f}, y={delta['accel'][1]:+.4f}, z={delta['accel'][2]:+.4f}")
        print(f"  gyro mag    : {gyro_mag:.4f}")
        print(f"  accel mag   : {accel_mag:.4f}")
        print(f"  lift hint   : {lift_hint}")
        print(f"  unstable    : {instability_hint}")

        if instability_hint:
            print("[SWEEP] Instability threshold likely reached. Stopping sweep.")
            break

        throttle += step

    return results


def print_single_motor_result(motor_index, baseline, during, delta):
    print(f"\nMotor {motor_index}")
    print(f"  baseline gyro   : x={baseline['gyro'][0]:+.4f}, y={baseline['gyro'][1]:+.4f}, z={baseline['gyro'][2]:+.4f}")
    print(f"  during gyro     : x={during['gyro'][0]:+.4f}, y={during['gyro'][1]:+.4f}, z={during['gyro'][2]:+.4f}")
    print(f"  delta gyro      : x={delta['gyro'][0]:+.4f}, y={delta['gyro'][1]:+.4f}, z={delta['gyro'][2]:+.4f}")
    print(f"  gyro signature  : roll={sign(delta['gyro'][0])}, pitch={sign(delta['gyro'][1])}, yaw={sign(delta['gyro'][2])}")

    print(f"  baseline accel  : x={baseline['accel'][0]:+.4f}, y={baseline['accel'][1]:+.4f}, z={baseline['accel'][2]:+.4f}")
    print(f"  during accel    : x={during['accel'][0]:+.4f}, y={during['accel'][1]:+.4f}, z={during['accel'][2]:+.4f}")
    print(f"  delta accel     : x={delta['accel'][0]:+.4f}, y={delta['accel'][1]:+.4f}, z={delta['accel'][2]:+.4f}")


def main():
    card = HIL()

    try:
        print("[TEST] Opening qdrone2...")
        card.open("qdrone2", "0")

        options = "pwm03_dshot=1"
        card.set_card_specific_options(options, len(options))
        card.set_pwm_mode(PWM_CHANNELS, len(PWM_CHANNELS), DSHOT_PWM_MODE)
        card.set_pwm_frequency(PWM_CHANNELS, len(PWM_CHANNELS), DSHOT_PWM_FREQUENCY)

        print("[TEST] Ready.")
        print("[TEST] Keep the drone firmly restrained/tethered.")
        print("[TEST] This script helps identify lift threshold and instability threshold.")
        print()

        send_disarm_burst(card)
        arm_zero(card)

        while True:
            print("\nChoose test:")
            print("  1 = baseline sample")
            print("  2 = single motor pulse")
            print("  3 = collective hold")
            print("  4 = auto collective sweep")
            print("  q = quit")

            choice = input("> ").strip().lower()

            if choice == "q":
                break

            elif choice == "1":
                baseline = average_sensor(card, seconds=1.0)
                print("\n[BASELINE]")
                print(f"  gyro  : x={baseline['gyro'][0]:+.4f}, y={baseline['gyro'][1]:+.4f}, z={baseline['gyro'][2]:+.4f}")
                print(f"  accel : x={baseline['accel'][0]:+.4f}, y={baseline['accel'][1]:+.4f}, z={baseline['accel'][2]:+.4f}")

            elif choice == "2":
                raw = input("Enter motor_index throttle pulse_seconds: ").strip()
                try:
                    motor_str, thr_str, sec_str = raw.split()
                    motor_index = int(motor_str)
                    throttle = float(thr_str)
                    pulse_seconds = float(sec_str)
                except Exception:
                    print("Example: 0 0.08 0.8")
                    continue

                if motor_index < 0 or motor_index > 3:
                    print("motor_index must be 0..3")
                    continue

                baseline, during, delta = pulse_single_motor(
                    card,
                    motor_index=motor_index,
                    throttle_fraction=throttle,
                    pulse_seconds=pulse_seconds,
                )
                print_single_motor_result(motor_index, baseline, during, delta)

            elif choice == "3":
                raw = input("Enter collective throttle hold_seconds: ").strip()
                try:
                    thr_str, sec_str = raw.split()
                    throttle = float(thr_str)
                    hold_seconds = float(sec_str)
                except Exception:
                    print("Example: 0.08 1.5")
                    continue

                baseline, during, delta, gyro_mag, accel_mag, lift_hint, instability_hint = \
                    hold_collective_and_measure(card, throttle, hold_seconds)

                print(f"\n[COLLECTIVE {throttle:.3f}]")
                print(f"  delta gyro  : x={delta['gyro'][0]:+.4f}, y={delta['gyro'][1]:+.4f}, z={delta['gyro'][2]:+.4f}")
                print(f"  delta accel : x={delta['accel'][0]:+.4f}, y={delta['accel'][1]:+.4f}, z={delta['accel'][2]:+.4f}")
                print(f"  gyro mag    : {gyro_mag:.4f}")
                print(f"  accel mag   : {accel_mag:.4f}")
                print(f"  lift hint   : {lift_hint}")
                print(f"  unstable    : {instability_hint}")

            elif choice == "4":
                raw = input("Enter start stop step hold_seconds: ").strip()
                try:
                    start_str, stop_str, step_str, sec_str = raw.split()
                    start = float(start_str)
                    stop = float(stop_str)
                    step = float(step_str)
                    hold_seconds = float(sec_str)
                except Exception:
                    print("Example: 0.02 0.20 0.01 1.2")
                    continue

                results = auto_collective_sweep(
                    card,
                    start=start,
                    stop=stop,
                    step=step,
                    hold_seconds=hold_seconds,
                )

                print("\n[SWEEP SUMMARY]")
                first_lift = None
                first_unstable = None

                for r in results:
                    if first_lift is None and r["lift_hint"]:
                        first_lift = r["throttle"]
                    if first_unstable is None and r["instability_hint"]:
                        first_unstable = r["throttle"]

                print(f"  first lift-like response       : {first_lift}")
                print(f"  first instability-like response: {first_unstable}")

            else:
                print("Unknown choice.")

    except Exception as exc:
        print(f"[TEST] FAILED: {exc}")

    finally:
        try:
            send_disarm_burst(card)
        except Exception:
            pass
        try:
            card.close()
        except Exception:
            pass
        print("[TEST] Closed.")


if __name__ == "__main__":
    main()
