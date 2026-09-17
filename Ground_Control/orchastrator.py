from __future__ import annotations

import os
import sys
import threading
import time
import traceback

# Make ground_control, Router, and gcs_src importable
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROUTER_DIR = os.path.join(BASE_DIR, "Router")
GCS_DIR = os.path.join(BASE_DIR, "gcs_src")

for path in (BASE_DIR, ROUTER_DIR, GCS_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

from Router.router_monitor import main as router_main
from gcs_src.server_03 import main as gcs_server_main


def _run_named_target(name: str, target) -> None:
    try:
        print(f"[ORCHASTRATOR] Starting {name}...")
        target()
    except Exception as error:
        print(f"[ORCHASTRATOR] {name} crashed: {error}")
        traceback.print_exc()


def main() -> None:
    router_thread = threading.Thread(
        target=_run_named_target,
        args=("router subsystem", router_main),
        daemon=True,
    )

    gcs_thread = threading.Thread(
        target=_run_named_target,
        args=("GCS server subsystem", gcs_server_main),
        daemon=True,
    )

    router_thread.start()
    gcs_thread.start()

    print("[ORCHASTRATOR] Router and GCS server are running.")

    try:
        while True:
            if not router_thread.is_alive():
                print("[ORCHASTRATOR] Router thread stopped.")
                break

            if not gcs_thread.is_alive():
                print("[ORCHASTRATOR] GCS server thread stopped.")
                break

            time.sleep(1)

    except KeyboardInterrupt:
        print("\n[ORCHASTRATOR] Shutdown requested by user.")

    print("[ORCHASTRATOR] Exiting.")


if __name__ == "__main__":
    main()
