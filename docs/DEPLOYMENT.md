# 本地部署与回滚

这个仓库只建议部署到树莓派或可信局域网，不要把实验 API 直接暴露到公网。部署前先运行：

```bash
python scripts/preflight.py
```

默认监听 `127.0.0.1:8000`。需要让局域网设备访问时，必须同时设置一个至少 16 个字符的令牌：

```bash
export RPI_API_HOST=0.0.0.0
export RPI_API_PORT=8000
export RPI_API_TOKEN='replace-with-a-long-random-token'
export RPI_API_AUDIT_LOG=/var/lib/rpi-mastery/api-audit.jsonl
python scripts/preflight.py
python scripts/run_api.py
```

预检会拒绝无效端口、局域网无令牌、短令牌、审计与队列共用同一文件，以及不可写的状态目录。
令牌不要提交到 Git，也不要放进命令历史；正式运行时应通过受限权限的环境文件注入。

## 健康检查

启动后从同一台设备检查：

```bash
curl --fail http://127.0.0.1:8000/health
```

返回 `status=ok` 后再把流量切换到新进程。局域网写操作还应使用唯一的 `Idempotency-Key`，
避免网络重试导致动作重复执行。

仓库 CI 会运行 `python scripts/smoke_api.py`，真实启动一个仅监听回环地址的进程并检查健康接口，
而不只是导入应用或调用测试客户端。

## 更新与回滚

更新前先记录当前提交并创建备份：

```bash
git rev-parse HEAD
python projects/08_verified_local_backup/main.py --root . create backups/pre-update.zip data
python projects/08_verified_local_backup/main.py drill backups/pre-update.zip
```

更新后依次运行部署预检、测试和健康检查。若失败，停止新进程，切回先前记录的已知良好提交，
重新安装该提交的依赖，再从 `pre-update.zip` 恢复需要的状态文件。恢复默认拒绝覆盖；先恢复到新目录
核对内容，确认后才使用 `--overwrite`。不要在仍写入 JSONL 的进程运行时直接替换状态文件。
