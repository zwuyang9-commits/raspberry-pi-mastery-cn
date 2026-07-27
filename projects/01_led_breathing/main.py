from __future__ import annotations

import argparse
import time

from rpi_mastery.hardware import make_output


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
    args = parser.parse_args()
    breathe(make_output(args.pin, args.simulate), args.cycles)
