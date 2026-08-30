from __future__ import annotations

import argparse
import json
import random
import time
from datetime import datetime, timedelta, timezone

from rpi_mastery.vision import Detection, PrivacyFirstSentinel


def main() -> None:
    parser = argparse.ArgumentParser(description="隐私优先的边缘视觉事件过滤器")
    parser.add_argument("--frames", type=int, default=10)
    parser.add_argument("--threshold", type=float, default=0.8)
    parser.add_argument("--confirm-frames", type=int, default=2)
    parser.add_argument("--cooldown", type=float, default=30.0)
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.frames < 1 or args.interval < 0:
        parser.error("frames 必须为正整数且 interval 不能为负数")

    sentinel = PrivacyFirstSentinel(
        threshold=args.threshold,
        required_consecutive=args.confirm_frames,
        cooldown=timedelta(seconds=args.cooldown),
    )
    generator = random.Random(args.seed)
    started_at = datetime.now(timezone.utc)
    for index in range(args.frames):
        simulated = [Detection("person", generator.random())]
        events = sentinel.process(
            simulated,
            observed_at=started_at + timedelta(seconds=index * args.interval),
        )
        for event in events:
            print(json.dumps(event.as_dict(), ensure_ascii=False))
        if index + 1 < args.frames:
            time.sleep(args.interval)
    print(json.dumps(sentinel.stats.__dict__, ensure_ascii=False))


if __name__ == "__main__":
    main()
