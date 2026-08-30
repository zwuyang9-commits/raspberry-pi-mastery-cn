from __future__ import annotations

import argparse
import time

from rpi_mastery.hardware import WatchdogOutput, make_output


def breathe(output, cycles: int, delay: float = 0.02, steps: int = 50) -> None:
    try:
        for _ in range(cycles):
            for step in range(steps + 1):
                output.set(step / steps)
                time.sleep(delay)
            for step in range(steps, -1, -1):
                output.set(step / steps)
                time.sleep(delay)
    finally:
        output.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PWM LED 呼吸灯")
    parser.add_argument("--pin", type=int, default=18)
    parser.add_argument("--cycles", type=int, default=3)
    parser.add_argument("--simulate", action="store_true")
    parser.add_argument(
        "--watchdog-timeout",
        type=float,
        help="超过指定秒数没有输出命令时自动归零",
    )
    args = parser.parse_args()
    output = make_output(args.pin, args.simulate)
    if args.watchdog_timeout is not None:
        output = WatchdogOutput(output, timeout=args.watchdog_timeout)
    breathe(output, args.cycles)
