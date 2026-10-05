"""Worker heartbeat for the server's self-healing: each worker touches a file every loop; Docker's health check runs
`python -m app.core.heartbeat SECONDS` and marks the worker unhealthy when the file is older (stuck, not crashed:
crashes are restarted by Docker's restart policy). `leapvoy heal` (a systemd timer) restarts unhealthy containers."""

import sys
import tempfile
import time
from pathlib import Path

FILE = Path(tempfile.gettempdir()) / "leapvoy-alive"


def beat() -> None:
    FILE.touch()


def healthy(max_age: float) -> bool:
    return FILE.exists() and time.time() - FILE.stat().st_mtime < max_age


if __name__ == "__main__":
    sys.exit(0 if healthy(float(sys.argv[1])) else 1)
