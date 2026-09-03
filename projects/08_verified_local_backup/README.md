# 08 可校验的本地备份

这个项目备份树莓派上的 CSV、JSONL 和配置文件。ZIP 内含 SHA-256 清单，恢复前会重新校验，
因此能发现文件损坏或被替换。校验会先核对 ZIP 元数据中的文件大小，再分块计算摘要，不会把大型
备份文件一次性载入内存；同名的重复 ZIP 条目会被拒绝，避免不同解压工具选择不同内容。大小写折叠
后冲突的路径、Windows 保留名、非法字符和尾随点或空格也会被拒绝，确保 Linux 创建的归档能安全
恢复到 Windows。默认拒绝覆盖已有文件，避免一次恢复误伤正在使用的数据。

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

创建备份时会拒绝选中路径及其下级目录中的符号链接，防止清单中的文件来源被链接静默替换。
新归档会写入唯一临时文件并完成一次清单、大小和摘要自校验，成功后才原子替换目标；如果源文件在
写入期间变化，创建会失败并保留原有备份。
恢复会拒绝目标目录中的符号链接，避免备份路径被重定向到目录外。使用 `--overwrite` 时，工具会
先保存被替换的旧文件；如果任一文件提交失败，已修改的文件会回滚，避免留下半新半旧的状态。

建议定期运行 `drill`。它会在系统临时目录完整解压备份，并再次核对每个恢复文件的大小和
SHA-256，随后自动清理演练目录，不会覆盖正式数据。单独运行 `verify` 只能证明 ZIP 内容可读，
恢复演练还能检查实际解压路径。

轮换命令默认只预览。加 `--apply` 后也只删除通过清单与 SHA-256 校验、且超过保留数量的旧备份；
损坏的 ZIP 和其他来源的 ZIP 会列为“无效文件”并保留，方便人工检查。
> 已经过树莓派 5 软件测试（2026-09-03，代码版本 `36b7614`）。备份测试及跨进程创建、校验、演练和逐字节恢复通过；未模拟介质物理故障。
> 详见[实机验证范围与记录](../../docs/real-device-validation.md)。
