"""Privacy-first filtering for local edge-vision detection metadata."""

from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True)
class Detection:
    label: str
    confidence: float

    def __post_init__(self) -> None:
        if not isinstance(self.label, str):
            raise TypeError("detection label must be text")
        normalized_label = unicodedata.normalize("NFC", self.label).strip().casefold()
        if not normalized_label:
            raise ValueError("detection label cannot be empty")
        object.__setattr__(self, "label", normalized_label)
        if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)):
            raise TypeError("detection confidence must be numeric")
        if not math.isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("detection confidence must be between 0 and 1")


@dataclass(frozen=True)
class SentinelEvent:
    label: str
    confidence: float
    confirmed_frames: int
    observed_at: datetime

    def as_dict(self) -> dict[str, str | float | int]:
        return {
            "event": "presence",
            "label": self.label,
            "confidence": self.confidence,
            "confirmed_frames": self.confirmed_frames,
            "observed_at": self.observed_at.isoformat(),
        }


@dataclass(frozen=True)
class SentinelStats:
    frames_processed: int
    detections_seen: int
    events_emitted: int


class PrivacyFirstSentinel:
    """Turns local detection metadata into confirmed, rate-limited events."""

    def __init__(
        self,
        *,
        threshold: float = 0.8,
        required_consecutive: int = 2,
        cooldown: timedelta = timedelta(seconds=30),
    ) -> None:
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
            raise TypeError("threshold must be numeric")
        if not math.isfinite(threshold) or not 0.0 <= threshold <= 1.0:
            raise ValueError("threshold must be between 0 and 1")
        if not isinstance(required_consecutive, int) or isinstance(required_consecutive, bool):
            raise TypeError("required_consecutive must be an integer")
        if required_consecutive < 1:
            raise ValueError("required_consecutive must be positive")
        if not isinstance(cooldown, timedelta):
            raise TypeError("cooldown must be a timedelta")
        if cooldown < timedelta(0):
            raise ValueError("cooldown cannot be negative")
        self.threshold = threshold
        self.required_consecutive = required_consecutive
        self.cooldown = cooldown
        self._streaks: dict[str, int] = {}
        self._last_events: dict[str, datetime] = {}
        self._last_processed_at: datetime | None = None
        self._frames_processed = 0
        self._detections_seen = 0
        self._events_emitted = 0

    @property
    def stats(self) -> SentinelStats:
        return SentinelStats(
            frames_processed=self._frames_processed,
            detections_seen=self._detections_seen,
            events_emitted=self._events_emitted,
        )

    def process(
        self,
        detections: list[Detection],
        *,
        observed_at: datetime | None = None,
    ) -> list[SentinelEvent]:
        timestamp = observed_at or datetime.now(timezone.utc)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        else:
            timestamp = timestamp.astimezone(timezone.utc)
        if self._last_processed_at is not None and timestamp < self._last_processed_at:
            raise ValueError("frames must be processed in timestamp order")
        self._last_processed_at = timestamp
        self._frames_processed += 1
        self._detections_seen += len(detections)

        strongest: dict[str, Detection] = {}
        for detection in detections:
            current = strongest.get(detection.label)
            if current is None or detection.confidence > current.confidence:
                strongest[detection.label] = detection
        passing = {
            label: detection
            for label, detection in strongest.items()
            if detection.confidence >= self.threshold
        }
        for label in set(self._streaks) - set(passing):
            self._streaks.pop(label, None)

        events: list[SentinelEvent] = []
        for label in sorted(passing):
            detection = passing[label]
            streak = self._streaks.get(label, 0) + 1
            self._streaks[label] = streak
            if streak < self.required_consecutive:
                continue
            previous = self._last_events.get(label)
            if previous is not None and timestamp - previous < self.cooldown:
                continue
            event = SentinelEvent(label, detection.confidence, streak, timestamp)
            self._last_events[label] = timestamp
            self._events_emitted += 1
            events.append(event)
        return events
