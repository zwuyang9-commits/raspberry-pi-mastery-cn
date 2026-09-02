import multiprocessing
import time
from datetime import datetime, timedelta, timezone

import pytest

from rpi_mastery.action_queue import ActionQueueError, DurableActionQueue
from rpi_mastery.audit import AuditLog
from rpi_mastery.automation import Action

NOW = datetime(2026, 8, 30, 9, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("identifier", ["", False, 0, 1, b"valid", [], {}, "a" * 129])
def test_explicit_invalid_id_is_rejected_without_creating_files(tmp_path, identifier):
    queue = DurableActionQueue(AuditLog(tmp_path / "queue.jsonl"))
    with pytest.raises(ActionQueueError, match="action_id"):
        queue.enqueue(Action("fan", "set", 1, "test"), action_id=identifier, now=NOW)
    assert list(tmp_path.iterdir()) == []


def test_omitted_ids_are_unique_and_max_length_id_is_preserved(tmp_path):
    queue = DurableActionQueue(AuditLog(tmp_path / "queue.jsonl"))
    action = Action("fan", "set", 1, "test")
    first = queue.enqueue(action, now=NOW)
    second = queue.enqueue(action, now=NOW)
    explicit = queue.enqueue(action, action_id="a" * 128, now=NOW)
    assert first.action_id != second.action_id
    assert len(first.action_id) == len(second.action_id) == 32
    assert explicit.action_id == "a" * 128


def test_empty_recovery_id_does_not_append_or_replace_dead_letter(tmp_path):
    audit = AuditLog(tmp_path / "queue.jsonl")
    queue = DurableActionQueue(audit)
    queue.enqueue(Action("fan", "set", 1, "test"), action_id="old", now=NOW)
    queue.dispatch(lambda item: (_ for _ in ()).throw(RuntimeError("offline")),
                   max_attempts=1, now=NOW)
    before = audit.path.read_bytes()
    with pytest.raises(ActionQueueError, match="action_id"):
        queue.requeue_dead_letter("old", new_action_id="", now=NOW)
    assert audit.path.read_bytes() == before
    assert queue.pending() == ()
    assert queue.dead_letters()[0].action_id == "old"


def test_dead_letter_scheduled_recovery_survives_restart(tmp_path):
    audit = AuditLog(tmp_path / "queue.jsonl")
    queue = DurableActionQueue(audit)
    queue.enqueue(Action("fan", "set", 1, "test"), action_id="old", now=NOW)
    queue.dispatch(lambda item: (_ for _ in ()).throw(RuntimeError("offline")),
                   max_attempts=1, now=NOW)
    dead = queue.dead_letters()
    future = NOW + timedelta(hours=1)
    recovered = queue.requeue_dead_letter("old", new_action_id="recovery",
                                         now=NOW, not_before=future)
    restarted = DurableActionQueue(audit)
    assert restarted.pending() == (recovered,)
    assert recovered.attempts == 0
    assert recovered.last_error is None
    assert restarted.dead_letters() == dead
    assert restarted.dispatch(lambda item: pytest.fail("early"), now=NOW).processed == 0
    assert restarted.dispatch(lambda item: None, now=future).completed == ("recovery",)


def test_invalid_requeue_schedule_preserves_dead_letter(tmp_path):
    audit = AuditLog(tmp_path / "queue.jsonl")
    queue = DurableActionQueue(audit)
    queue.enqueue(Action("fan", "set", 1, "test"), action_id="old", now=NOW)
    queue.dispatch(lambda item: (_ for _ in ()).throw(RuntimeError("offline")),
                   max_attempts=1, now=NOW)
    before = audit.path.read_bytes()
    with pytest.raises(ActionQueueError, match="timezone"):
        queue.requeue_dead_letter("old", not_before=NOW.replace(tzinfo=None))
    assert audit.path.read_bytes() == before
    assert queue.pending() == ()


@pytest.mark.parametrize("parameter", ["max_items", "max_attempts"])
@pytest.mark.parametrize("value", [True, False, 1.0, 1.5, float("nan"), float("inf"), "2", 0, -1])
def test_dispatch_rejects_invalid_counts_before_any_side_effect(tmp_path, parameter, value):
    path = tmp_path / "queue.jsonl"
    queue = DurableActionQueue(AuditLog(path))
    queue.enqueue(Action("fan", "set", 1, "test"), now=NOW)
    before = {file.name: file.read_bytes() for file in tmp_path.iterdir()}
    with pytest.raises(ValueError, match=parameter):
        queue.dispatch(lambda item: pytest.fail("invalid config executed an action"),
                       now=NOW, **{parameter: value})
    assert {file.name: file.read_bytes() for file in tmp_path.iterdir()} == before


def test_dispatch_rejects_none_attempt_limit_without_creating_files(tmp_path):
    queue = DurableActionQueue(AuditLog(tmp_path / "missing" / "queue.jsonl"))
    with pytest.raises(ValueError, match="max_attempts"):
        queue.dispatch(lambda item: None, max_attempts=None)
    assert not (tmp_path / "missing").exists()


def test_scheduled_action_survives_restart_and_runs_at_boundary(tmp_path):
    audit = AuditLog(tmp_path / "queue.jsonl")
    queue = DurableActionQueue(audit)
    scheduled = NOW + timedelta(hours=1)
    item = queue.enqueue(
        Action("fan", "set", 1, "scheduled"), action_id="scheduled", now=NOW,
        not_before=scheduled.astimezone(timezone(timedelta(hours=8))),
    )
    assert item.next_attempt_at == scheduled
    restored = DurableActionQueue(audit)
    assert restored.pending() == (item,)
    status = restored.status(now=NOW)
    assert (status.ready, status.deferred, status.next_ready_at) == (0, 1, scheduled)
    assert restored.dispatch(lambda item: pytest.fail("too early"), now=NOW).processed == 0
    assert restored.dispatch(lambda item: None, now=scheduled).completed == ("scheduled",)


def test_waiting_action_does_not_consume_dispatch_limit(tmp_path):
    queue = DurableActionQueue(AuditLog(tmp_path / "queue.jsonl"))
    queue.enqueue(Action("fan", "set", 1, "later"), action_id="later", now=NOW,
                  not_before=NOW + timedelta(hours=1))
    queue.enqueue(Action("fan", "set", 0, "ready"), action_id="ready", now=NOW)
    report = queue.dispatch(lambda item: None, now=NOW, max_items=1)
    assert report.completed == ("ready",)
    assert report.deferred == ("later",)
    assert report.processed == 1


def test_scheduling_requires_timezone_without_writing(tmp_path):
    audit = AuditLog(tmp_path / "queue.jsonl")
    with pytest.raises(ActionQueueError, match="timezone"):
        DurableActionQueue(audit).enqueue(
            Action("fan", "set", 1, "test"), not_before=NOW.replace(tzinfo=None)
        )
    assert audit.read() == []


@pytest.mark.parametrize("raw", [None, 42, "bad", "2026-09-02T12:00:00"])
def test_malformed_persisted_schedule_is_rejected(tmp_path, raw):
    audit = AuditLog(tmp_path / "queue.jsonl")
    audit.append("queued_action_created", "fan", {
        "action_id": "bad", "command": "set", "value": 1, "reason": "test",
        "not_before": raw,
    }, timestamp=NOW)
    queue = DurableActionQueue(audit)
    for read in (queue.pending, queue.dead_letters):
        with pytest.raises(ActionQueueError, match="not_before"):
            read()


def test_scheduled_failure_uses_retry_backoff(tmp_path):
    audit = AuditLog(tmp_path / "queue.jsonl")
    queue = DurableActionQueue(audit)
    queue.enqueue(Action("fan", "set", 1, "test"), now=NOW, not_before=NOW)
    queue.dispatch(lambda item: (_ for _ in ()).throw(RuntimeError("offline")),
                   now=NOW, retry_delay=timedelta(seconds=10))
    assert DurableActionQueue(audit).pending()[0].next_attempt_at == NOW + timedelta(seconds=10)


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


def test_dispatch_normalizes_naive_time_before_backoff_comparison(tmp_path):
    audit = AuditLog(tmp_path / "queue.jsonl")
    queue = DurableActionQueue(audit)
    queue.enqueue(Action("fan", "set", 1, "test"), action_id="naive-time", now=NOW)
    queue.dispatch(
        lambda item: (_ for _ in ()).throw(RuntimeError("offline")),
        retry_delay=timedelta(seconds=10),
        now=NOW,
    )

    deferred = DurableActionQueue(audit).dispatch(
        lambda item: pytest.fail("handler ran before backoff elapsed"),
        now=(NOW + timedelta(seconds=9)).replace(tzinfo=None),
    )

    assert deferred.deferred == ("naive-time",)
    assert audit.read(kind="queued_action_attempted")[0].timestamp.tzinfo is timezone.utc


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


def test_pending_action_can_be_cancelled_and_stays_cancelled_after_restart(tmp_path):
    audit = AuditLog(tmp_path / "queue.jsonl")
    queue = DurableActionQueue(audit)
    queue.enqueue(Action("pump", "set", 1, "rule"), action_id="cancel-me", now=NOW)

    queue.cancel("cancel-me", reason="maintenance window", now=NOW)

    assert DurableActionQueue(audit).pending() == ()
    [entry] = audit.read(kind="queued_action_cancelled")
    assert entry.payload == {
        "action_id": "cancel-me",
        "reason": "maintenance window",
    }


def test_cancel_rejects_unknown_or_completed_action(tmp_path):
    queue = DurableActionQueue(AuditLog(tmp_path / "queue.jsonl"))
    with pytest.raises(ActionQueueError, match="pending action not found"):
        queue.cancel("missing", reason="not needed", now=NOW)

    queue.enqueue(Action("fan", "set", 1, "test"), action_id="done", now=NOW)
    queue.dispatch(lambda item: None, now=NOW)
    with pytest.raises(ActionQueueError, match="pending action not found"):
        queue.cancel("done", reason="too late", now=NOW)


def test_cancel_requires_a_reason(tmp_path):
    queue = DurableActionQueue(AuditLog(tmp_path / "queue.jsonl"))
    queue.enqueue(Action("fan", "set", 1, "test"), action_id="pending", now=NOW)
    with pytest.raises(ValueError, match="reason"):
        queue.cancel("pending", reason="   ", now=NOW)


def test_terminal_archive_preserves_pending_dead_letters_and_id_tombstones(tmp_path):
    path = tmp_path / "queue.jsonl"
    archive = tmp_path / "terminal.jsonl"
    audit = AuditLog(path)
    queue = DurableActionQueue(audit)
    queue.enqueue(Action("fan", "set", 1, "done"), action_id="done", now=NOW)
    queue.dispatch(lambda item: None, now=NOW)
    queue.enqueue(Action("pump", "set", 0, "cancel"), action_id="cancelled", now=NOW)
    queue.cancel("cancelled", reason="maintenance", now=NOW)
    queue.enqueue(Action("valve", "set", 0, "dead"), action_id="dead", now=NOW)
    queue.dispatch(
        lambda item: (_ for _ in ()).throw(RuntimeError("offline")),
        max_attempts=1,
        now=NOW,
    )
    queue.enqueue(Action("light", "set", 1, "pending"), action_id="pending", now=NOW)

    report = queue.archive_terminal_before(
        NOW + timedelta(seconds=1), archive, apply=True
    )

    assert report.archived_entries == 5
    assert {entry.payload["action_id"] for entry in AuditLog(archive).read()} == {
        "done",
        "cancelled",
    }
    assert [item.action_id for item in queue.pending()] == ["pending"]
    assert [item.action_id for item in queue.dead_letters()] == ["dead"]
    tombstones = audit.read(kind="queued_action_archived")
    assert {entry.payload["action_id"] for entry in tombstones} == {"done", "cancelled"}
    with pytest.raises(ActionQueueError, match="already exists"):
        queue.enqueue(Action("fan", "set", 0, "reuse"), action_id="done", now=NOW)


def test_terminal_archive_preview_does_not_modify_queue(tmp_path):
    path = tmp_path / "queue.jsonl"
    archive = tmp_path / "terminal.jsonl"
    queue = DurableActionQueue(AuditLog(path))
    queue.enqueue(Action("fan", "set", 1, "done"), action_id="done", now=NOW)
    queue.dispatch(lambda item: None, now=NOW)
    before = path.read_bytes()

    report = queue.archive_terminal_before(NOW + timedelta(seconds=1), archive)

    assert report.applied is False
    assert report.archived_entries == 3
    assert path.read_bytes() == before
    assert not archive.exists()


def test_status_summarizes_ready_deferred_leased_and_dead_letters(tmp_path):
    audit = AuditLog(tmp_path / "queue.jsonl")
    queue = DurableActionQueue(audit)
    queue.enqueue(Action("ready", "set", 1, "test"), action_id="ready", now=NOW)
    queue.enqueue(Action("deferred", "set", 1, "test"), action_id="deferred", now=NOW)
    queue.dispatch(
        lambda item: (_ for _ in ()).throw(RuntimeError("offline"))
        if item.action_id == "deferred"
        else None,
        retry_delay=timedelta(seconds=20),
        max_items=2,
        now=NOW,
    )
    queue.enqueue(Action("leased", "set", 1, "test"), action_id="leased", now=NOW)
    audit.append(
        "queued_action_attempted",
        "leased",
        {
            "action_id": "leased",
            "lease_expires_at": (NOW + timedelta(seconds=10)).isoformat(),
        },
        timestamp=NOW,
    )
    queue.enqueue(Action("dead", "set", 1, "test"), action_id="dead", now=NOW)
    queue.enqueue(Action("ready", "set", 1, "test"), action_id="ready-2", now=NOW)
    queue.dispatch(
        lambda item: (_ for _ in ()).throw(RuntimeError("offline"))
        if item.action_id == "dead"
        else None,
        max_attempts=1,
        max_items=1,
        now=NOW,
    )

    status = queue.status(now=NOW)

    assert status.pending == 3
    assert status.ready == 1
    assert status.deferred == 1
    assert status.leased == 1
    assert status.dead_letters == 1
    assert status.next_ready_at == NOW + timedelta(seconds=10)
