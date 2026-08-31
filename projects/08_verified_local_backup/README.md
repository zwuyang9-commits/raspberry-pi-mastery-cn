# 08 可校验的本地备份

这个项目备份树莓派上的 CSV、JSONL 和配置文件。ZIP 内含 SHA-256 清单，恢复前会重新校验，
因此能发现文件损坏或被替换。默认拒绝覆盖已有文件，避免一次恢复误伤正在使用的数据。

在仓库根目录运行：

```bash
python projects/08_verified_local_backup/main.py --root . create backups/state.zip data config
python projects/08_verified_local_backup/main.py verify backups/state.zip
python projects/08_verified_local_backup/main.py drill backups/state.zip
python projects/08_verified_local_backup/main.py restore backups/state.zip restored
python projects/08_verified_local_backup/main.py rotate backups --keep 7
python projects/08_verified_local_backup/main.py rotate backups --keep 7 --apply
```

只有确认目标目录里的旧文件不再需要时才使用 `--overwrite`。备份文件应再复制到另一块存储介质；
只放在同一张 SD 卡上不能防止卡片损坏。

建议定期运行 `drill`。它会在系统临时目录完整解压备份，并再次核对每个恢复文件的大小和
SHA-256，随后自动清理演练目录，不会覆盖正式数据。单独运行 `verify` 只能证明 ZIP 内容可读，
恢复演练还能检查实际解压路径。

轮换命令默认只预览。加 `--apply` 后也只删除通过清单与 SHA-256 校验、且超过保留数量的旧备份；
损坏的 ZIP 和其他来源的 ZIP 会列为“无效文件”并保留，方便人工检查。
