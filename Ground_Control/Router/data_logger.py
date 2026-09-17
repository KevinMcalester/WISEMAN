import json
import os
import time
import uuid
import random
import threading
import subprocess
from pathlib import Path
from datetime import datetime


class DataLogger:
    """
    Collects router events and stores them for AI training.
    Runs for a fixed session time (default: 30 minutes).
    """

    def __init__(self, label="normal", duration_minutes=30):
        base_dir = Path(__file__).parent

        self.training_dir = base_dir / "training_logs"
        self.training_dir.mkdir(exist_ok=True)

        self.label = label
        self.session_id = str(uuid.uuid4())[:8]

        self.duration_seconds = duration_minutes * 60
        self.start_time = time.time()

        timestamp = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
        filename = f"session_{timestamp}_{label}.jsonl"

        self.file_path = self.training_dir / filename
        self.file = open(self.file_path, "a", encoding="utf-8")

        self.active = True
        self.lock = threading.Lock()

        # Optional configuration through environment variables.
        # Set these before running router_monitor.py
        self.network_adapter_name = os.getenv("DATA_LOGGER_NETWORK_ADAPTER", "").strip()
        self.arduino_instance_id = os.getenv("DATA_LOGGER_ARDUINO_INSTANCE_ID", "").strip()

        # Fallback so the generator still works even if CLion/terminal env is inconsistent.
        if not self.network_adapter_name:
            self.network_adapter_name = "Wi-Fi"

        # Random timing controls (seconds)
        self.min_wait_seconds = int(os.getenv("DATA_LOGGER_MIN_WAIT_SECONDS", "120"))
        self.max_wait_seconds = int(os.getenv("DATA_LOGGER_MAX_WAIT_SECONDS", "240"))

        self.min_network_off_seconds = int(os.getenv("DATA_LOGGER_MIN_NETWORK_OFF_SECONDS", "4"))
        self.max_network_off_seconds = int(os.getenv("DATA_LOGGER_MAX_NETWORK_OFF_SECONDS", "8"))

        self.min_arduino_off_seconds = int(os.getenv("DATA_LOGGER_MIN_ARDUINO_OFF_SECONDS", "3"))
        self.max_arduino_off_seconds = int(os.getenv("DATA_LOGGER_MAX_ARDUINO_OFF_SECONDS", "8"))

        self.command_timeout_seconds = int(os.getenv("DATA_LOGGER_COMMAND_TIMEOUT_SECONDS", "20"))
        self.recovery_observation_seconds = int(os.getenv("DATA_LOGGER_RECOVERY_OBSERVATION_SECONDS", "15"))

        # Threshold used by router_monitor.py logic too if you want consistency
        self.abnormal_reconnect_threshold_seconds = int(
            os.getenv("DATA_LOGGER_ABNORMAL_RECONNECT_THRESHOLD_SECONDS", "15")
        )

        # Training-oriented metadata/counters
        self.event_index = 0
        self.generator_cycle_index = 0
        self.network_cycle_index = 0
        self.arduino_cycle_index = 0

        self.stats = {
            "network_disable_attempts": 0,
            "network_disable_successes": 0,
            "network_enable_attempts": 0,
            "network_enable_successes": 0,
            "arduino_disable_attempts": 0,
            "arduino_disable_successes": 0,
            "arduino_enable_attempts": 0,
            "arduino_enable_successes": 0,
            "generator_errors": 0,
            "generator_skips": 0,
            "abnormal_event_count": 0
        }

        self.last_generator_action_time = None
        self.last_network_cycle_id = None
        self.last_arduino_cycle_id = None

        self.worker = threading.Thread(target=self._run_generator_loop, daemon=True)
        self.worker.start()

    def log_event(self, event_type, **data):
        """
        Store a structured training event.

        Supports optional per-event overrides in data:
            event_label="abnormal"
            abnormal=True
            abnormal_reason="slow_reconnect"
        """

        if not self.active:
            return

        if time.time() - self.start_time > self.duration_seconds:
            self.stop()
            return

        self.event_index += 1

        event_label = data.pop("event_label", self.label)
        abnormal = bool(data.get("abnormal", False))

        if abnormal:
            self.stats["abnormal_event_count"] += 1

        entry = {
            "session_id": self.session_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "event_index": self.event_index,
            "elapsed_seconds": round(time.time() - self.start_time, 3),
            "event": event_type,
            "label": event_label,
            "session_label": self.label,
            "data": data
        }

        with self.lock:
            self.file.write(json.dumps(entry) + "\n")
            self.file.flush()

    def stop(self):
        """
        End the training session.
        """

        if self.active:
            self._log_session_summary()
            self.active = False

            if (
                    hasattr(self, "worker")
                    and self.worker.is_alive()
                    and threading.current_thread() is not self.worker
            ):
                self.worker.join(timeout=2)

            with self.lock:
                if not self.file.closed:
                    self.file.close()

    def _run_generator_loop(self):
        self.log_event(
            "GENERATOR_STARTED",
            network_adapter_name=self.network_adapter_name,
            arduino_instance_id_set=bool(self.arduino_instance_id),
            min_wait_seconds=self.min_wait_seconds,
            max_wait_seconds=self.max_wait_seconds,
            min_network_off_seconds=self.min_network_off_seconds,
            max_network_off_seconds=self.max_network_off_seconds,
            min_arduino_off_seconds=self.min_arduino_off_seconds,
            max_arduino_off_seconds=self.max_arduino_off_seconds,
            command_timeout_seconds=self.command_timeout_seconds,
            recovery_observation_seconds=self.recovery_observation_seconds,
            abnormal_reconnect_threshold_seconds=self.abnormal_reconnect_threshold_seconds
        )

        while self.active:
            if time.time() - self.start_time > self.duration_seconds:
                break

            wait_seconds = random.randint(self.min_wait_seconds, self.max_wait_seconds)

            self.log_event(
                "GENERATOR_WAIT_SELECTED",
                wait_seconds=wait_seconds
            )

            slept = 0
            while self.active and slept < wait_seconds:
                time.sleep(1)
                slept += 1

                if time.time() - self.start_time > self.duration_seconds:
                    break

            if not self.active:
                break

            if time.time() - self.start_time > self.duration_seconds:
                break

            available_actions = []

            if self.network_adapter_name:
                available_actions.append("network")

            if self.arduino_instance_id:
                available_actions.append("arduino")

            if not available_actions:
                self.stats["generator_skips"] += 1
                self.log_event(
                    "GENERATOR_SKIPPED",
                    target="all",
                    reason="No configured targets available"
                )
                continue

            action = random.choice(available_actions)
            self.generator_cycle_index += 1
            generator_cycle_id = f"{self.session_id}_gen_{self.generator_cycle_index:05d}"
            self.last_generator_action_time = time.time()

            self.log_event(
                "GENERATOR_CYCLE_STARTED",
                generator_cycle_id=generator_cycle_id,
                action=action,
                available_actions=available_actions
            )

            try:
                if action == "network":
                    self._trigger_network_cycle()
                else:
                    self._trigger_arduino_cycle()

                self.log_event(
                    "GENERATOR_CYCLE_COMPLETED",
                    generator_cycle_id=generator_cycle_id,
                    action=action
                )

            except Exception as error:
                self.stats["generator_errors"] += 1
                self.log_event(
                    "GENERATOR_ERROR",
                    generator_cycle_id=generator_cycle_id,
                    action=action,
                    message=str(error),
                    abnormal=True,
                    abnormal_reason="generator_exception",
                    event_label="abnormal"
                )

        self.log_event("GENERATOR_STOPPED")

    def _trigger_network_cycle(self):
        if not self.network_adapter_name:
            self.stats["generator_skips"] += 1
            self.log_event(
                "GENERATOR_SKIPPED",
                target="network",
                reason="DATA_LOGGER_NETWORK_ADAPTER not set"
            )
            return

        self.network_cycle_index += 1
        cycle_id = f"{self.session_id}_net_{self.network_cycle_index:05d}"
        self.last_network_cycle_id = cycle_id

        off_seconds = random.randint(
            self.min_network_off_seconds,
            self.max_network_off_seconds
        )

        cycle_started_at = time.time()

        self.log_event(
            "GENERATOR_ACTION",
            target="network",
            action="disable_enable",
            adapter=self.network_adapter_name,
            downtime_seconds=off_seconds,
            cycle_id=cycle_id
        )

        self.stats["network_disable_attempts"] += 1
        disable_result = self._set_network_adapter(enabled=False)
        if disable_result["success"]:
            self.stats["network_disable_successes"] += 1

        self.log_event(
            "GENERATOR_COMMAND_RESULT",
            target="network",
            action="disable",
            adapter=self.network_adapter_name,
            success=disable_result["success"],
            returncode=disable_result["returncode"],
            stdout=disable_result["stdout"],
            stderr=disable_result["stderr"],
            command_duration_seconds=disable_result["duration_seconds"],
            cycle_id=cycle_id,
            abnormal=not disable_result["success"],
            abnormal_reason="network_disable_failed" if not disable_result["success"] else None,
            event_label="abnormal" if not disable_result["success"] else self.label
        )

        time.sleep(off_seconds)

        self.stats["network_enable_attempts"] += 1
        enable_result = self._set_network_adapter(enabled=True)
        if enable_result["success"]:
            self.stats["network_enable_successes"] += 1

        self.log_event(
            "GENERATOR_COMMAND_RESULT",
            target="network",
            action="enable",
            adapter=self.network_adapter_name,
            success=enable_result["success"],
            returncode=enable_result["returncode"],
            stdout=enable_result["stdout"],
            stderr=enable_result["stderr"],
            command_duration_seconds=enable_result["duration_seconds"],
            cycle_id=cycle_id,
            abnormal=not enable_result["success"],
            abnormal_reason="network_enable_failed" if not enable_result["success"] else None,
            event_label="abnormal" if not enable_result["success"] else self.label
        )

        cycle_duration = round(time.time() - cycle_started_at, 3)

        self.log_event(
            "GENERATOR_ACTION_SUMMARY",
            target="network",
            action="disable_enable",
            adapter=self.network_adapter_name,
            cycle_id=cycle_id,
            requested_downtime_seconds=off_seconds,
            disable_success=disable_result["success"],
            enable_success=enable_result["success"],
            disable_returncode=disable_result["returncode"],
            enable_returncode=enable_result["returncode"],
            total_cycle_duration_seconds=cycle_duration,
            abnormal=(not disable_result["success"]) or (not enable_result["success"]),
            abnormal_reason="network_cycle_command_failure"
            if ((not disable_result["success"]) or (not enable_result["success"])) else None,
            event_label="abnormal"
            if ((not disable_result["success"]) or (not enable_result["success"])) else self.label
        )

    def _trigger_arduino_cycle(self):
        if not self.arduino_instance_id:
            self.stats["generator_skips"] += 1
            self.log_event(
                "GENERATOR_SKIPPED",
                target="arduino",
                reason="DATA_LOGGER_ARDUINO_INSTANCE_ID not set"
            )
            return

        self.arduino_cycle_index += 1
        cycle_id = f"{self.session_id}_ard_{self.arduino_cycle_index:05d}"
        self.last_arduino_cycle_id = cycle_id

        off_seconds = random.randint(
            self.min_arduino_off_seconds,
            self.max_arduino_off_seconds
        )

        cycle_started_at = time.time()

        self.log_event(
            "GENERATOR_ACTION",
            target="arduino",
            action="disable_enable",
            instance_id=self.arduino_instance_id,
            downtime_seconds=off_seconds,
            cycle_id=cycle_id
        )

        self.stats["arduino_disable_attempts"] += 1
        disable_result = self._set_arduino_device(enabled=False)
        if disable_result["success"]:
            self.stats["arduino_disable_successes"] += 1

        self.log_event(
            "GENERATOR_COMMAND_RESULT",
            target="arduino",
            action="disable",
            instance_id=self.arduino_instance_id,
            success=disable_result["success"],
            returncode=disable_result["returncode"],
            stdout=disable_result["stdout"],
            stderr=disable_result["stderr"],
            command_duration_seconds=disable_result["duration_seconds"],
            cycle_id=cycle_id,
            abnormal=not disable_result["success"],
            abnormal_reason="arduino_disable_failed" if not disable_result["success"] else None,
            event_label="abnormal" if not disable_result["success"] else self.label
        )

        time.sleep(off_seconds)

        self.stats["arduino_enable_attempts"] += 1
        enable_result = self._set_arduino_device(enabled=True)
        if enable_result["success"]:
            self.stats["arduino_enable_successes"] += 1

        self.log_event(
            "GENERATOR_COMMAND_RESULT",
            target="arduino",
            action="enable",
            instance_id=self.arduino_instance_id,
            success=enable_result["success"],
            returncode=enable_result["returncode"],
            stdout=enable_result["stdout"],
            stderr=enable_result["stderr"],
            command_duration_seconds=enable_result["duration_seconds"],
            cycle_id=cycle_id,
            abnormal=not enable_result["success"],
            abnormal_reason="arduino_enable_failed" if not enable_result["success"] else None,
            event_label="abnormal" if not enable_result["success"] else self.label
        )

        cycle_duration = round(time.time() - cycle_started_at, 3)

        self.log_event(
            "GENERATOR_ACTION_SUMMARY",
            target="arduino",
            action="disable_enable",
            instance_id=self.arduino_instance_id,
            cycle_id=cycle_id,
            requested_downtime_seconds=off_seconds,
            disable_success=disable_result["success"],
            enable_success=enable_result["success"],
            disable_returncode=disable_result["returncode"],
            enable_returncode=enable_result["returncode"],
            total_cycle_duration_seconds=cycle_duration,
            abnormal=(not disable_result["success"]) or (not enable_result["success"]),
            abnormal_reason="arduino_cycle_command_failure"
            if ((not disable_result["success"]) or (not enable_result["success"])) else None,
            event_label="abnormal"
            if ((not disable_result["success"]) or (not enable_result["success"])) else self.label
        )

    def _set_network_adapter(self, enabled):
        state_word = "ENABLED" if enabled else "DISABLED"

        command = [
            "netsh",
            "interface",
            "set",
            "interface",
            f'name="{self.network_adapter_name}"',
            f"admin={state_word}"
        ]

        return self._run_command(command)

    def _set_arduino_device(self, enabled):
        action = "Enable-PnpDevice" if enabled else "Disable-PnpDevice"

        powershell_command = (
            f'{action} -InstanceId "{self.arduino_instance_id}" '
            f'-Confirm:$false'
        )

        command = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            powershell_command
        ]

        return self._run_command(command)

    def _run_command(self, command):
        started_at = time.time()

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.command_timeout_seconds,
                shell=False
            )

            duration_seconds = round(time.time() - started_at, 3)

            return {
                "success": completed.returncode == 0,
                "returncode": completed.returncode,
                "stdout": completed.stdout.strip(),
                "stderr": completed.stderr.strip(),
                "duration_seconds": duration_seconds
            }

        except Exception as error:
            duration_seconds = round(time.time() - started_at, 3)

            return {
                "success": False,
                "returncode": -1,
                "stdout": "",
                "stderr": str(error),
                "duration_seconds": duration_seconds
            }

    def _log_session_summary(self):
        elapsed = round(time.time() - self.start_time, 3)

        self.log_event(
            "SESSION_SUMMARY",
            file_path=str(self.file_path),
            elapsed_seconds=elapsed,
            label=self.label,
            total_events_logged=self.event_index,
            generator_cycle_index=self.generator_cycle_index,
            network_cycle_index=self.network_cycle_index,
            arduino_cycle_index=self.arduino_cycle_index,
            stats=self.stats
        )
