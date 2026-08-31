# 09 本地审计查询器

审计日志的追加写入和归档由同目录隐藏锁文件保护，同一主机上的多个采集或自动化进程可以安全
共享一个 JSONL 文件；进程异常退出时，操作系统会自动释放锁。
如果替换保留日志失败，刚发布的归档会自动撤回，因此原日志保持完整且同一路径可以安全重试。

在不安装数据库的情况下查询 JSONL 审计日志。可以按事件类型、来源和 ISO 8601 时间范围筛选，
也可以快速统计不同事件及设备出现的次数。时间必须带时区，避免树莓派与电脑时区不同造成误判。
写入只接受标准 JSON 的有限数值；读取遇到 `NaN`、`Infinity` 或损坏记录时会报告准确行号。
顶层记录或嵌套载荷中的重复 JSON 键也会视为损坏，不会静默采用最后一个值。

```bash
python projects/09_local_audit_explorer/main.py data/operations.jsonl --limit 20
python projects/09_local_audit_explorer/main.py data/operations.jsonl --kind alert_opened
python projects/09_local_audit_explorer/main.py data/operations.jsonl --source water-valve --summary
python projects/09_local_audit_explorer/main.py data/operations.jsonl --since 2026-08-30T08:00:00+08:00
```

默认逐行输出 JSON，适合继续交给其他命令处理；`--summary` 输出匹配记录的起止时间、总数、
事件类型计数和来源计数。工具只读取日志，不会修改或标记记录。

## 安全归档

先停止正在写这个日志的服务，再预览截止时间之前的记录数量：

```bash
python projects/09_local_audit_explorer/main.py data/operations.jsonl \
  --archive-before 2026-08-01T00:00:00+08:00 \
  --archive-output archives/operations-2026-07.jsonl
```

确认数量后增加 `--apply`。工具会先验证全部源记录，完整写好独立归档和保留记录临时文件，再
替换源日志；已有归档文件不会被覆盖。归档期间不要同时启动写入服务。
