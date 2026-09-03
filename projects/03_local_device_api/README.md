# 03 局域网设备 API

把一个可调输出封装成 HTTP 服务。当前接的是内存模拟器，先把读取状态、写入亮度、权限和退出
清理跑通，再换成 GPIO 适配器。

只在树莓派本机使用时，保持 Uvicorn 默认的 `127.0.0.1` 即可：

```bash
python scripts/run_api.py
```

访问 `http://127.0.0.1:8000/docs`。没有设置令牌时，程序只接受来自本机的写请求；读取健康状态
和当前输出不受影响。

需要让局域网里的其他设备控制时，先设置至少 16 位、无空格的可打印 ASCII 随机令牌，再监听
局域网地址：

```bash
export RPI_API_TOKEN='replace-with-random-token-123'
export RPI_API_HOST=0.0.0.0
python scripts/run_api.py
```

PowerShell 写法：

```powershell
$env:RPI_API_TOKEN = 'replace-with-random-token-123'
$env:RPI_API_HOST = '0.0.0.0'
python scripts/run_api.py
```

写入时把令牌放进 `X-API-Token` 请求头：

```bash
curl -X PUT http://树莓派IP:8000/output \
  -H 'Content-Type: application/json' \
  -H "X-API-Token: $RPI_API_TOKEN" \
  -H 'Idempotency-Key: phone-command-0001' \
  -d '{"value": 0.5}'
```

建议每一个逻辑控制命令使用一个新的 `Idempotency-Key`（8–128 位字母、数字或 `._:-`）。网络
超时后用同一个键和相同内容重试，服务不会再次操作输出，并返回 `Idempotency-Replayed: true`；
同一个键配不同值会返回 409。设置 `RPI_API_AUDIT_LOG=data/device-api.jsonl` 后，幂等记录可在
重启后恢复，每次首次写入和重放也会写入本地审计日志。

安全启动脚本会先执行部署预检；可以用 `python scripts/run_api.py --check` 只检查而不启动。
应用退出时会自动关闭输出并回到 0。真正接继电器前，还需要根据负载增加硬件隔离、保险和手动
急停；令牌也不要提交进仓库。
> 已经过树莓派 5 软件测试（2026-09-03，代码版本 `36b7614`）。API 自动化测试及本机服务启动检查通过；执行器仍是模拟设备。
> 详见[实机验证范围与记录](../../docs/real-device-validation.md)。
