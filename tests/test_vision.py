from datetime import datetime, timedelta, timezone

import pytest

from rpi_mastery.vision import Detection, PrivacyFirstSentinel

NOW = datetime(2026, 8, 30, 8, 0, tzinfo=timezone.utc)


def test_requires_consecutive_detections_before_event():
    sentinel = PrivacyFirstSentinel(
        threshold=0.8,
        required_consecutive=2,
        cooldown=timedelta(seconds=30),
    )

    assert sentinel.process([Detection("person", 0.9)], observed_at=NOW) == []
    [event] = sentinel.process(
        [Detection("person", 0.85)],
        observed_at=NOW + timedelta(seconds=1),
    )

    assert event.label == "person"
    assert event.confirmed_frames == 2
    assert event.as_dict()["event"] == "presence"


def test_low_confidence_frame_resets_confirmation_streak():
    sentinel = PrivacyFirstSentinel(required_consecutive=2)
    sentinel.process([Detection("person", 0.9)], observed_at=NOW)
    sentinel.process([Detection("person", 0.2)], observed_at=NOW + timedelta(seconds=1))

    assert sentinel.process(
        [Detection("person", 0.9)], observed_at=NOW + timedelta(seconds=2)
    ) == []


def test_cooldown_suppresses_repeated_event_then_allows_later_event():
    sentinel = PrivacyFirstSentinel(required_consecutive=1, cooldown=timedelta(seconds=10))

    assert len(sentinel.process([Detection("person", 0.9)], observed_at=NOW)) == 1
    assert sentinel.process(
        [Detection("person", 0.9)], observed_at=NOW + timedelta(seconds=9)
    ) == []
    assert len(
        sentinel.process(
            [Detection("person", 0.9)], observed_at=NOW + timedelta(seconds=10)
        )
    ) == 1
    assert sentinel.stats.frames_processed == 3
    assert sentinel.stats.events_emitted == 2


def test_uses_strongest_detection_for_each_label():
    sentinel = PrivacyFirstSentinel(required_consecutive=1, cooldown=timedelta(0))

    [event] = sentinel.process(
        [Detection("person", 0.81), Detection("person", 0.95)],
        observed_at=NOW,
    )

    assert event.confidence == 0.95
    assert sentinel.stats.detections_seen == 2


def test_rejects_invalid_detection_and_out_of_order_frame():
    with pytest.raises(ValueError, match="confidence"):
        Detection("person", 1.1)

    sentinel = PrivacyFirstSentinel()
    sentinel.process([], observed_at=NOW)
    with pytest.raises(ValueError, match="timestamp order"):
        sentinel.process([], observed_at=NOW - timedelta(seconds=1))
