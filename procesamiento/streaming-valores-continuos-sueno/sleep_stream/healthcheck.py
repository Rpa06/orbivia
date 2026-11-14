"""Comprobación de salud del servicio: el latido debe ser reciente.

    python -m sleep_stream.healthcheck
"""

import os
import sys
import time
from pathlib import Path

MAX_AGE_S = 60.0


def main() -> int:
    path = os.environ.get("SLEEP_HEARTBEAT_FILE")
    if not path:
        print("SLEEP_HEARTBEAT_FILE no está definido")
        return 1
    try:
        age = time.time() - float(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print("Sin latido todavía")
        return 1
    if age > MAX_AGE_S:
        print(f"Latido de hace {age:.0f} s")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
