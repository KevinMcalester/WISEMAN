import json
import os
import threading
import time
from typing import Any


class ControlStorage:
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.lock = threading.Lock()
        self._ensure_parent_dir()
        self._ensure_file()

    def _ensure_parent_dir(self) -> None:
        parent = os.path.dirname(self.file_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

    def _ensure_file(self) -> None:
        if not os.path.exists(self.file_path):
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump([], f, indent=2)

    def _read_all(self) -> list[dict[str, Any]]:
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
                return []
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def _write_all(self, data: list[dict[str, Any]]) -> None:
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def append_record(self, record: dict[str, Any]) -> None:
        with self.lock:
            data = self._read_all()
            data.append(record)
            self._write_all(data)

    def store_control(self, packet: dict, client_id: str, addr) -> None:
        record = {
            "ingested_at": time.time(),
            "client_id": client_id,
            "client_ip": addr[0],
            "client_port": addr[1],
            "command": packet.get("command"),
            "timestamp": packet.get("timestamp"),
            "nonce": packet.get("nonce"),
            "device_id": packet.get("device_id"),
            "source": packet.get("source"),
            "data": packet.get("data", {})
        }
        self.append_record(record)