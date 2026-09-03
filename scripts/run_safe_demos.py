"""Run bounded, simulated feature demos with isolated logs and a JSON summary."""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def demo_commands(data: Path) -> list[tuple[str, list[str]]]:
    return [
        ("led-simulated", ["projects/01_led_breathing/main.py", "--simulate", "--cycles", "1"]),
        (
            "environment-simulated",
            [
                "projects/02_environment_station/main.py",
                "--sensor",
                "simulated",
                "--samples",
                "3",
                "--interval",
                "0.5",
                "--output",
                str(data / "environment.csv"),
            ],
        ),
        ("home-hub-simulated", ["projects/05_resilient_home_hub/main.py", "--simulate"]),
        ("energy-plan", ["projects/06_local_energy_scheduler/main.py"]),
        (
            "operations",
            [
                "projects/07_local_operations_console/main.py",
                "--audit-log",
                str(data / "audit.jsonl"),
                "--json",
            ],
        ),
        (
            "audit-summary",
            ["projects/09_local_audit_explorer/main.py", str(data / "audit.jsonl"), "--summary"],
        ),
    ]


def run_demos(output: Path, timeout: float = 30) -> dict:
    if not math.isfinite(timeout) or timeout <= 0 or timeout > 300:
        raise ValueError("timeout must be finite and between 0 (exclusive) and 300 seconds")
    output = output.resolve()
    # Never overwrite a previous run or user data.
    output.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONIOENCODING="utf-8")
    results = []
    for name, arguments in demo_commands(output):
        print(f"\n>>> RUNNING {name} (simulated hardware)", flush=True)
        started = time.monotonic()
        log = output / f"{name}.log"
        status = "failed"
        code = None
        with log.open("w", encoding="utf-8") as stream:
            try:
                completed = subprocess.run(
                    [sys.executable, str(ROOT / arguments[0]), *arguments[1:]],
                    cwd=output,
                    env=env,
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    timeout=timeout,
                    check=False,
                )
                code = completed.returncode
                status = "passed" if code == 0 else "failed"
            except subprocess.TimeoutExpired:
                status = "timeout"
            except OSError as error:
                stream.write(f"Launch failed: {error}\n")
        print(log.read_text(encoding="utf-8", errors="replace"), end="", flush=True)
        entry = {
            "name": name,
            "status": status,
            "exit_code": code,
            "duration_seconds": round(time.monotonic() - started, 3),
            "log": log.name,
        }
        results.append(entry)
        summary = {
            "schema_version": 1,
            "complete": False,
            "ok": False,
            "mode": "simulated",
            "steps": results,
        }
        (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"<<< {name}: {status.upper()}", flush=True)
    summary.update(complete=True, ok=all(step["status"] == "passed" for step in results))
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, help="new directory only; defaults to isolated temp data"
    )
    parser.add_argument("--timeout", type=float, default=30, help="per-demo seconds, maximum 300")
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or not 0 < args.timeout <= 300:
        parser.error("timeout must be finite and between 0 (exclusive) and 300 seconds")
    output = args.output or Path(tempfile.mkdtemp(prefix="rpi-demos-")) / "run"
    print(f"Results: {output.resolve()}", flush=True)
    try:
        summary = run_demos(output, args.timeout)
    except (OSError, ValueError) as error:
        print(f"Cannot run demos: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted; no successful completion is claimed.", file=sys.stderr)
        return 130
    print(f"FINISHED: {'PASSED' if summary['ok'] else 'FAILED'}", flush=True)
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
