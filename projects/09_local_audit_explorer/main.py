"""Query and summarize a local JSONL audit log."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from rpi_mastery.audit import AuditEntry, AuditLog


def parse_time(value: str) -> datetime:
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("时间必须是 ISO 8601 格式") from error
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise argparse.ArgumentTypeError("时间必须包含时区，例如 +08:00 或 Z")
    return timestamp


def entry_as_dict(entry: AuditEntry) -> dict[str, object]:
    return {
        "timestamp": entry.timestamp.isoformat(),
        "kind": entry.kind,
        "source": entry.source,
        "payload": entry.payload,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="本地 JSONL 审计日志查询")
    parser.add_argument("log", type=Path, help="审计日志路径")
    parser.add_argument("--kind", help="只显示指定事件类型")
    parser.add_argument("--source", help="只显示指定设备或动作来源")
    parser.add_argument("--since", type=parse_time, help="起始时间（含边界）")
    parser.add_argument("--until", type=parse_time, help="结束时间（含边界）")
    parser.add_argument("--limit", type=int, help="只显示最后 N 条匹配记录")
    parser.add_argument("--summary", action="store_true", help="输出统计摘要")
    parser.add_argument("--archive-before", type=parse_time, help="预览归档该时间之前的记录")
    parser.add_argument("--archive-output", type=Path, help="独立归档文件路径")
    parser.add_argument("--apply", action="store_true", help="实际执行归档预览")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    audit = AuditLog(args.log)
    if args.archive_before is not None:
        if args.archive_output is None:
            raise SystemExit("使用 --archive-before 时必须指定 --archive-output")
        report = audit.archive_before(
            args.archive_before,
            args.archive_output,
            apply=args.apply,
        )
        print(
            json.dumps(
                {
                    "mode": "applied" if report.applied else "preview",
                    "archived_entries": report.archived_entries,
                    "retained_entries": report.retained_entries,
                    "archive": str(report.archive),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    if args.apply:
        raise SystemExit("--apply 只能与 --archive-before 一起使用")
    filters = {
        "kind": args.kind,
        "source": args.source,
        "since": args.since,
        "until": args.until,
    }
    if args.summary:
        summary = audit.summarize(**filters)
        print(
            json.dumps(
                {
                    "entries": summary.entries,
                    "first_timestamp": (
                        summary.first_timestamp.isoformat()
                        if summary.first_timestamp is not None
                        else None
                    ),
                    "last_timestamp": (
                        summary.last_timestamp.isoformat()
                        if summary.last_timestamp is not None
                        else None
                    ),
                    "kinds": summary.kinds,
                    "sources": summary.sources,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    for entry in audit.read(**filters, limit=args.limit):
        print(json.dumps(entry_as_dict(entry), ensure_ascii=False))


if __name__ == "__main__":
    main()
