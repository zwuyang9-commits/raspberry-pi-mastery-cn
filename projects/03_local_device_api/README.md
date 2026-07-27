# 03 局域网设备 API

把 GPIO 输出封装为 HTTP 服务。API 提供健康检查、读取状态和设置亮度。

```bash
uvicorn projects.03_local_device_api.main:app --host 0.0.0.0 --port 8000
```

访问 `http://树莓派IP:8000/docs`。公网部署前必须添加认证和 HTTPS。
