import multiprocessing
import time
from datetime import datetime, timedelta, timezone

import pytest

from rpi_mastery.action_queue import ActionQueueError, DurableActionQueue
from rpi_mastery.audit import AuditLog
from rpi_mastery.automation import Action

NOW = datetime(2026, 8, 30, 9, 0, tzinfo=timezone.utc)


def _dispatch_in_process(path, start, results):
    queue = DurableActionQueue(AuditLog(path))
    start.wait()

    def handle(item):
        time.sleep(0.2)

    report = queue.dispatch(handle, now=NOW)
    results.put(report.completed)


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


def test_failed_action_waits_for_persisted_exponential_backoff(tmp_path):
    audit = AuditLog(tmp_path / "queue.jsonl")
    queue = DurableActionQueue(audit)
    queue.enqueue(Action("fan", "set", 1, "test"), action_id="retry-later", now=NOW)

    first = queue.dispatch(
        lambda item: (_ for _ in ()).throw(RuntimeError("offline")),
        retry_delay=timedelta(seconds=10),
        now=NOW,
    )
    deferred = DurableActionQueue(audit).dispatch(
        lambda item: pytest.fail("handler ran before backoff elapsed"),
        retry_delay=timedelta(seconds=10),
        now=NOW + timedelta(seconds=9),
    )
    handled = []
    retried = DurableActionQueue(audit).dispatch(
        handled.append,
        retry_delay=timedelta(seconds=10),
        now=NOW + timedelta(seconds=10),
    )

    assert first.failed == ("retry-later",)
    assert deferred.deferred == ("retry-later",)
    assert deferred.processed == 0
    assert [item.action_id for item in handled] == ["retry-later"]
    assert retried.completed == ("retry-later",)


def test_retry_delay_doubles_after_each_failure(tmp_path):
    queue = DurableActionQueue(AuditLog(tmp_path / "queue.jsonl"))
    queue.enqueue(Action("fan", "set", 1, "test"), action_id="backoff", now=NOW)

    def fail(item):
        raise RuntimeError("offline")

    queue.dispatch(fail, retry_delay=timedelta(seconds=5), now=NOW)
    queue.dispatch(fail, retry_delay=timedelta(seconds=5), now=NOW + timedelta(seconds=5))
    [pending] = queue.pending()

    assert pending.attempts == 2
    assert pending.next_attempt_at == NOW + timedelta(seconds=15)


def test_dispatch_rejects_negative_retry_delay(tmp_path):
    queue = DurableActionQueue(AuditLog(tmp_path / "queue.jsonl"))
    with pytest.raises(ValueError, match="retry_delay"):
        queue.dispatch(lambda item: None, retry_delay=timedelta(seconds=-1))


def test_active_lease_defers_action_after_worker_crash(tmp_path):
    audit = AuditLog(tmp_path / "queue.jsonl")
    queue = DurableActionQueue(audit)
    queue.enqueue(Action("fan", "set", 1, "test"), action_id="leased", now=NOW)
    audit.append(
        "queued_action_attempted",
        "fan",
        {
            "action_id": "leased",
            "lease_expires_at": (NOW + timedelta(seconds=30)).isoformat(),
        },
        timestamp=NOW,
    )

    handled = []
    report = DurableActionQueue(audit).dispatch(
        handled.append,
        now=NOW + timedelta(seconds=29),
    )

    assert handled == []
    assert report.leased == ("leased",)
    assert report.processed == 0


def test_expired_lease_is_recovered_after_worker_crash(tmp_path):
    audit = AuditLog(tmp_path / "queue.jsonl")
    queue = DurableActionQueue(audit)
    queue.enqueue(Action("fan", "set", 1, "test"), action_id="recover", now=NOW)
    audit.append(
        "queued_action_attempted",
        "fan",
        {
            "action_id": "recover",
            "lease_expires_at": (NOW + timedelta(seconds=30)).isoformat(),
        },
        timestamp=NOW,
    )

    handled = []
    report = DurableActionQueue(audit).dispatch(
        handled.append,
        lease_duration=timedelta(seconds=30),
        now=NOW + timedelta(seconds=30),
    )

    assert [item.action_id for item in handled] == ["recover"]
    assert report.completed == ("recover",)
    assert queue.pending() == ()


def test_dispatch_rejects_non_positive_lease_duration(tmp_path):
    queue = DurableActionQueue(AuditLog(tmp_path / "queue.jsonl"))
    with pytest.raises(ValueError, match="lease_duration"):
        queue.dispatch(lambda item: None, lease_duration=timedelta(0))


def test_process_lock_prevents_duplicate_concurrent_dispatch(tmp_path):
    path = tmp_path / "queue.jsonl"
    queue = DurableActionQueue(AuditLog(path))
    queue.enqueue(Action("fan", "set", 1, "test"), action_id="once", now=NOW)
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    results = context.Queue()
    workers = [
        context.Process(target=_dispatch_in_process, args=(path, start, results))
        for _ in range(2)
    ]
    for worker in workers:
        worker.start()
    start.set()
    for worker in workers:
        worker.join(timeout=10)

    assert [worker.exitcode for worker in workers] == [0, 0]
    reports = [results.get(timeout=1) for _ in workers]
    assert sorted(reports, key=len) == [(), ("once",)]
    assert queue.pending() == ()
