# 08 可校验的本地备份

这个项目备份树莓派上的 CSV、JSONL 和配置文件。ZIP 内含 SHA-256 清单，恢复前会重新校验，
因此能发现文件损坏或被替换。默认拒绝覆盖已有文件，避免一次恢复误伤正在使用的数据。

在仓库根目录运行：

```bash
python projects/08_verified_local_backup/main.py --root . create backups/state.zip data config
python projects/08_verified_local_backup/main.py verify backups/state.zip
python projects/08_verified_local_backup/main.py restore backups/state.zip restored
```

只有确认目标目录里的旧文件不再需要时才使用 `--overwrite`。备份文件应再复制到另一块存储介质；
只放在同一张 SD 卡上不能防止卡片损坏。
