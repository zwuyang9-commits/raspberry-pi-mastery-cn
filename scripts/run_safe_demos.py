"""Run bounded, simulated feature demos with isolated logs and a JSON summary."""

from __future__ import annotations

import argparse
import codecs
import json
import math
import os
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
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


def select_commands(data: Path, steps: list[str] | None = None) -> list[tuple[str, list[str]]]:
    commands = demo_commands(data)
    if steps is None:
        return commands
    names = {name for name, _ in commands}
    if not steps or any(step not in names for step in steps):
        raise ValueError("select at least one valid demo name")
    selected = set(steps)
    if "audit-summary" in selected:
        selected.add("operations")  # Produce the isolated audit input first.
    return [(name, command) for name, command in commands if name in selected]


@contextmanager
def live_log(path: Path):
    """Tail bytes incrementally, including UTF-8 characters split across writes."""
    done = threading.Event()

    def display():
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        with path.open("rb") as reader:
            while True:
                chunk = reader.read(8192)
                if chunk:
                    print(decoder.decode(chunk), end="", flush=True)
                elif done.is_set():
                    print(decoder.decode(b"", final=True), end="", flush=True)
                    return
                else:
                    done.wait(0.05)

    worker = threading.Thread(target=display, name="demo-live-log", daemon=True)
    worker.start()
    try:
        yield
    finally:
        done.set()
        worker.join()


def run_demos(output: Path, timeout: float = 30, steps: list[str] | None = None) -> dict:
    if not math.isfinite(timeout) or timeout <= 0 or timeout > 300:
        raise ValueError("timeout must be finite and between 0 (exclusive) and 300 seconds")
    output = output.resolve()
    commands = select_commands(output, steps)
    # Never overwrite a previous run or user data.
    output.mkdir(parents=True, exist_ok=False)
    env = dict(
        os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1"
    )
    results = []
    summary = {
        "schema_version": 1,
        "complete": False,
        "ok": False,
        "mode": "simulated",
        "planned_steps": [name for name, _ in commands],
        "steps": results,
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    for name, arguments in commands:
        print(f"\n>>> RUNNING {name} (simulated hardware)", flush=True)
        started = time.monotonic()
        log = output / f"{name}.log"
        status = "failed"
        code = None
        with log.open("w", encoding="utf-8", buffering=1) as stream, live_log(log):
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
        entry = {
            "name": name,
            "status": status,
            "exit_code": code,
            "duration_seconds": round(time.monotonic() - started, 3),
            "log": log.name,
        }
        results.append(entry)
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
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--list", action="store_true", help="list demos without running or writing"
    )
    selection.add_argument(
        "--step",
        action="append",
        choices=[name for name, _ in demo_commands(ROOT)],
        help="run selected demos; repeatable; audit includes operations",
    )
    args = parser.parse_args()
    if args.list:
        for name, _ in demo_commands(ROOT):
            print(name)
        return 0
    if not math.isfinite(args.timeout) or not 0 < args.timeout <= 300:
        parser.error("timeout must be finite and between 0 (exclusive) and 300 seconds")
    output = args.output or Path(tempfile.mkdtemp(prefix="rpi-demos-")) / "run"
    print(f"Results: {output.resolve()}", flush=True)
    try:
        summary = run_demos(output, args.timeout, args.step)
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
