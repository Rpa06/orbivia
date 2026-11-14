"""Healthcheck del contenedor: python -m social_graph.healthcheck

Sale con 0 si el servicio ha guardado un checkpoint hace poco.
"""

import os
import sys
import time

MAX_AGE_S = float(os.environ.get("SG_HEARTBEAT_MAX_AGE_S", "120"))


def main() -> int:
    path = os.environ.get("SG_HEARTBEAT_FILE", "/tmp/social_graph.heartbeat")
    try:
        age = time.time() - os.path.getmtime(path)
    except OSError:
        return 1
    return 0 if age <= MAX_AGE_S else 1


if __name__ == "__main__":
    sys.exit(main())
