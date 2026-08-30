# 09 本地审计查询器

在不安装数据库的情况下查询 JSONL 审计日志。可以按事件类型、来源和 ISO 8601 时间范围筛选，
也可以快速统计不同事件及设备出现的次数。时间必须带时区，避免树莓派与电脑时区不同造成误判。

```bash
python projects/09_local_audit_explorer/main.py data/operations.jsonl --limit 20
python projects/09_local_audit_explorer/main.py data/operations.jsonl --kind alert_opened
python projects/09_local_audit_explorer/main.py data/operations.jsonl --source water-valve --summary
python projects/09_local_audit_explorer/main.py data/operations.jsonl --since 2026-08-30T08:00:00+08:00
```

默认逐行输出 JSON，适合继续交给其他命令处理；`--summary` 输出匹配记录的起止时间、总数、
事件类型计数和来源计数。工具只读取日志，不会修改或标记记录。
