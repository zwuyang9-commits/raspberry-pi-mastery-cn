"""Create, verify and restore local state backups."""

from __future__ import annotations

import argparse
from pathlib import Path

from rpi_mastery.backup import LocalBackupManager


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="树莓派本地状态备份工具")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="源文件根目录")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="创建带校验清单的 ZIP")
    create.add_argument("archive", type=Path)
    create.add_argument("paths", nargs="+", help="相对于 root 的文件或目录")

    verify = subparsers.add_parser("verify", help="验证备份完整性")
    verify.add_argument("archive", type=Path)

    restore = subparsers.add_parser("restore", help="恢复已验证的备份")
    restore.add_argument("archive", type=Path)
    restore.add_argument("destination", type=Path)
    restore.add_argument("--overwrite", action="store_true", help="允许覆盖同名文件")

    rotate = subparsers.add_parser("rotate", help="预览或执行备份轮换")
    rotate.add_argument("directory", type=Path)
    rotate.add_argument("--keep", type=int, required=True, help="保留最新的有效备份数量")
    rotate.add_argument("--apply", action="store_true", help="实际删除预览中的旧备份")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    manager = LocalBackupManager(args.root)
    if args.command == "create":
        report = manager.create(args.archive, args.paths)
        print(f"已创建 {report.archive}：{len(report.files)} 个文件，{report.total_size} 字节")
    elif args.command == "verify":
        report = manager.verify(args.archive)
        print(f"校验通过：{len(report.files)} 个文件，创建于 {report.created_at.isoformat()}")
    elif args.command == "restore":
        restored = manager.restore(args.archive, args.destination, overwrite=args.overwrite)
        print(f"已恢复 {len(restored)} 个文件到 {args.destination.resolve()}")
    else:
        plan = manager.rotate(args.directory, keep=args.keep, apply=args.apply)
        mode = "已执行" if plan.applied else "仅预览"
        print(f"{mode}：保留 {len(plan.keep)}，清理 {len(plan.remove)}，无效 {len(plan.invalid)}")
        for archive in plan.remove:
            print(f"- 清理：{archive}")
        for archive in plan.invalid:
            print(f"- 跳过无效文件：{archive}")


if __name__ == "__main__":
    main()
