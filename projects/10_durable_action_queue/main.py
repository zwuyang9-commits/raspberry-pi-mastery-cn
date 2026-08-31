"""Inspect and exercise the durable local action queue."""

from __future__ import annotations

import argparse
import json
from datetime import timedelta
from pathlib import Path

from rpi_mastery.action_queue import DurableActionQueue, QueuedAction
from rpi_mastery.audit import AuditLog
from rpi_mastery.automation import Action


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="离线自动化持久动作队列")
    parser.add_argument("--queue", type=Path, default=Path("data/action-queue.jsonl"))
    commands = parser.add_subparsers(dest="command", required=True)

    enqueue = commands.add_parser("enqueue", help="添加一个动作")
    enqueue.add_argument("target")
    enqueue.add_argument("action_command")
    enqueue.add_argument("value", help="JSON 值，例如 true、0.5 或字符串")
    enqueue.add_argument("--reason", default="手动加入队列")
    enqueue.add_argument("--id", dest="action_id")

    commands.add_parser("list", help="列出待执行动作")
    commands.add_parser("list-dead", help="列出达到重试上限的死信动作")
    run = commands.add_parser("run-demo", help="用模拟处理器执行待处理动作")
    run.add_argument("--fail-target", help="模拟指定目标执行失败")
    run.add_argument("--max-items", type=int)
    run.add_argument("--max-attempts", type=int, default=3)
    run.add_argument("--retry-delay", type=float, default=0, help="首次重试等待秒数")
    requeue = commands.add_parser("requeue", help="用新 ID 重新加入死信动作")
    requeue.add_argument("action_id")
    requeue.add_argument("--new-id")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    queue = DurableActionQueue(AuditLog(args.queue))
    if args.command == "enqueue":
        try:
            value = json.loads(args.value)
        except json.JSONDecodeError as error:
            raise SystemExit(f"value 必须是有效 JSON：{error.msg}") from error
        queued = queue.enqueue(
            Action(args.target, args.action_command, value, args.reason),
            action_id=args.action_id,
        )
        print(json.dumps({"action_id": queued.action_id, "status": "pending"}, ensure_ascii=False))
        return

    if args.command in {"list", "list-dead"}:
        items = queue.pending() if args.command == "list" else queue.dead_letters()
        for item in items:
            print(
                json.dumps(
                    {
                        "action_id": item.action_id,
                        "target": item.action.target,
                        "command": item.action.command,
                        "value": item.action.value,
                        "attempts": item.attempts,
                        "last_error": item.last_error,
                        "next_attempt_at": (
                            item.next_attempt_at.isoformat() if item.next_attempt_at else None
                        ),
                    },
                    ensure_ascii=False,
                )
            )
        return

    if args.command == "requeue":
        item = queue.requeue_dead_letter(args.action_id, new_action_id=args.new_id)
        print(json.dumps({"action_id": item.action_id, "status": "pending"}, ensure_ascii=False))
        return

    def simulate(item: QueuedAction) -> None:
        if item.action.target == args.fail_target:
            raise RuntimeError("模拟设备离线")
        print(f"执行 {item.action_id}: {item.action.target} {item.action.command}")

    report = queue.dispatch(
        simulate,
        max_items=args.max_items,
        max_attempts=args.max_attempts,
        retry_delay=timedelta(seconds=args.retry_delay),
    )
    print(json.dumps(report.__dict__, ensure_ascii=False))


if __name__ == "__main__":
    main()
