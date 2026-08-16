# 03 局域网设备 API

把一个可调输出封装成 HTTP 服务。当前接的是内存模拟器，先把读取状态、写入亮度、权限和退出
清理跑通，再换成 GPIO 适配器。

只在树莓派本机使用时，保持 Uvicorn 默认的 `127.0.0.1` 即可：

```bash
uvicorn projects.03_local_device_api.main:app --port 8000
```

访问 `http://127.0.0.1:8000/docs`。没有设置令牌时，程序只接受来自本机的写请求；读取健康状态
和当前输出不受影响。

需要让局域网里的其他设备控制时，先设置令牌，再监听局域网地址：

```bash
export RPI_API_TOKEN='换成一段足够长的随机字符串'
uvicorn projects.03_local_device_api.main:app --host 0.0.0.0 --port 8000
```

PowerShell 写法：

```powershell
$env:RPI_API_TOKEN = '换成一段足够长的随机字符串'
uvicorn projects.03_local_device_api.main:app --host 0.0.0.0 --port 8000
```

写入时把令牌放进 `X-API-Token` 请求头：

```bash
curl -X PUT http://树莓派IP:8000/output \
  -H 'Content-Type: application/json' \
  -H "X-API-Token: $RPI_API_TOKEN" \
  -d '{"value": 0.5}'
```

应用退出时会自动关闭输出并回到 0。真正接继电器前，还需要根据负载增加硬件隔离、保险和手动
急停；令牌也不要提交进仓库。
