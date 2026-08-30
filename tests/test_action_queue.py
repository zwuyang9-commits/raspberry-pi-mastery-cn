from datetime import datetime, timezone

import pytest

from rpi_mastery.action_queue import ActionQueueError, DurableActionQueue
from rpi_mastery.audit import AuditLog
from rpi_mastery.automation import Action

NOW = datetime(2026, 8, 30, 9, 0, tzinfo=timezone.utc)


def test_completed_action_is_removed_and_survives_restart(tmp_path):
    audit = AuditLog(tmp_path / "queue.jsonl")
    queue = DurableActionQueue(audit)
    queued = queue.enqueue(
        Action("fan", "set", 1, "temperature high"),
        action_id="action-001",
        now=NOW,
    )
    handled = []

    report = queue.dispatch(handled.append, now=NOW)

    assert handled == [queued]
    assert report.completed == ("action-001",)
    assert DurableActionQueue(audit).pending() == ()


def test_failed_action_remains_pending_and_does_not_block_next_item(tmp_path):
    queue = DurableActionQueue(AuditLog(tmp_path / "queue.jsonl"))
    queue.enqueue(Action("broken", "set", 1, "test"), action_id="action-001", now=NOW)
    queue.enqueue(Action("fan", "set", 1, "test"), action_id="action-002", now=NOW)
    handled = []

    def handler(item):
        if item.action.target == "broken":
            raise RuntimeError("device offline")
        handled.append(item.action_id)

    report = queue.dispatch(handler, now=NOW)

    assert report.failed == ("action-001",)
    assert report.completed == ("action-002",)
    assert handled == ["action-002"]
    [pending] = queue.pending()
    assert pending.action_id == "action-001"
    assert pending.attempts == 1
    assert pending.last_error == "device offline"


def test_retry_completes_previous_failure(tmp_path):
    queue = DurableActionQueue(AuditLog(tmp_path / "queue.jsonl"))
    queue.enqueue(Action("fan", "set", 1, "test"), action_id="retry-me", now=NOW)
    queue.dispatch(lambda item: (_ for _ in ()).throw(RuntimeError("temporary")), now=NOW)

    report = queue.dispatch(lambda item: None, now=NOW)

    assert report.completed == ("retry-me",)
    assert queue.pending() == ()


def test_dispatch_limit_preserves_remaining_order(tmp_path):
    queue = DurableActionQueue(AuditLog(tmp_path / "queue.jsonl"))
    for index in range(3):
        queue.enqueue(
            Action("fan", "set", index / 2, "test"),
            action_id=f"action-{index}",
            now=NOW,
        )

    report = queue.dispatch(lambda item: None, max_items=2, now=NOW)

    assert report.processed == 2
    assert [item.action_id for item in queue.pending()] == ["action-2"]


def test_rejects_duplicate_id_and_non_json_value(tmp_path):
    queue = DurableActionQueue(AuditLog(tmp_path / "queue.jsonl"))
    queue.enqueue(Action("fan", "set", 1, "test"), action_id="same", now=NOW)

    with pytest.raises(ActionQueueError, match="already exists"):
        queue.enqueue(Action("fan", "set", 0, "test"), action_id="same", now=NOW)
    with pytest.raises(ActionQueueError, match="JSON"):
        queue.enqueue(Action("fan", "set", object(), "test"), now=NOW)


def test_failed_action_moves_to_dead_letters_at_attempt_limit(tmp_path):
    queue = DurableActionQueue(AuditLog(tmp_path / "queue.jsonl"))
    queue.enqueue(Action("fan", "set", 1, "test"), action_id="give-up", now=NOW)

    first = queue.dispatch(
        lambda item: (_ for _ in ()).throw(RuntimeError("offline")),
        max_attempts=2,
        now=NOW,
    )
    second = queue.dispatch(
        lambda item: (_ for _ in ()).throw(RuntimeError("offline")),
        max_attempts=2,
        now=NOW,
    )

    assert first.dead_lettered == ()
    assert second.dead_lettered == ("give-up",)
    assert queue.pending() == ()
    [dead] = queue.dead_letters()
    assert dead.action_id == "give-up"
    assert dead.attempts == 2
    assert dead.last_error == "offline"


def test_dead_letter_can_be_requeued_with_new_id(tmp_path):
    queue = DurableActionQueue(AuditLog(tmp_path / "queue.jsonl"))
    queue.enqueue(Action("fan", "set", 1, "test"), action_id="old-id", now=NOW)
    queue.dispatch(
        lambda item: (_ for _ in ()).throw(RuntimeError("offline")),
        max_attempts=1,
        now=NOW,
    )

    requeued = queue.requeue_dead_letter("old-id", new_action_id="new-id", now=NOW)

    assert requeued.action_id == "new-id"
    assert [item.action_id for item in queue.pending()] == ["new-id"]


def test_dispatch_validates_attempt_limit(tmp_path):
    queue = DurableActionQueue(AuditLog(tmp_path / "queue.jsonl"))
    with pytest.raises(ValueError, match="max_attempts"):
        queue.dispatch(lambda item: None, max_attempts=0)
