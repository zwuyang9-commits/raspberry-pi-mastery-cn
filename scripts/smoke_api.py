"""Start the real API process and verify its health endpoint."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment.update({"RPI_API_HOST": "127.0.0.1", "RPI_API_PORT": "8765"})
    process = subprocess.Popen(
        [sys.executable, str(root / "scripts" / "run_api.py")],
        cwd=root,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
    )
    try:
        for _ in range(40):
            if process.poll() is not None:
                break
            try:
                with urlopen("http://127.0.0.1:8765/health", timeout=1) as response:
                    health = json.load(response)
                with urlopen("http://127.0.0.1:8765/ready", timeout=1) as response:
                    readiness = json.load(response)
                if health != {
                    "status": "ok",
                    "mode": "simulated",
                    "write_protection": "loopback-only",
                }:
                    raise RuntimeError(f"unexpected health response: {health}")
                if readiness != {"status": "ready", "mode": "simulated"}:
                    raise RuntimeError(f"unexpected readiness response: {readiness}")
                print("API process smoke test passed")
                return 0
            except URLError:
                time.sleep(0.25)

        output = process.stdout.read() if process.stdout is not None else ""
        raise RuntimeError(f"API did not become healthy\n{output}")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
                raise RuntimeError("API process did not stop gracefully")


if __name__ == "__main__":
    raise SystemExit(main())
