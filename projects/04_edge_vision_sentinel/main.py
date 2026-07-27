from __future__ import annotations

import random
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class Detection:
    label: str
    confidence: float


class PrivacyFirstSentinel:
    def __init__(self, threshold: float = 0.8) -> None:
        self.threshold = threshold

    def process(self, detections: list[Detection]) -> list[dict]:
        return [
            {"event": "presence", "label": item.label, "confidence": item.confidence}
            for item in detections
            if item.confidence >= self.threshold
        ]


if __name__ == "__main__":
    sentinel = PrivacyFirstSentinel()
    for _ in range(5):
        simulated = [Detection("person", random.random())]
        print(sentinel.process(simulated))
        time.sleep(0.5)
