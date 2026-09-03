# 树莓派实机回归验证

建议在独立检出目录和虚拟环境运行，避免修改设备上正在使用的程序：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install '.[dev,web]'
export PYTHONPATH="$PWD/src"
.venv/bin/python -m pip check
.venv/bin/python -m ruff check .
.venv/bin/python -m pytest -q
.venv/bin/python scripts/preflight.py --json
.venv/bin/python scripts/run_api.py --check
```

`tests/test_cli_workflows.py` 增加跨进程端到端回归，可单独运行：

```bash
.venv/bin/python -m pytest tests/test_cli_workflows.py --no-cov -q
```

覆盖备份创建、校验、恢复演练与逐字节恢复；队列跨进程状态读取、模拟失败、死信恢复；
控制台 JSON/Prometheus 输出与只读审计查询；环境站重复采集追加 CSV；以及呼吸灯、家庭中枢、
能源调度的模拟命令。每项测试使用独立临时目录，子进程设有 30 秒超时。
不会驱动真实 GPIO、读取摄像头、控制市电或开启网络服务。

## USB 摄像头单独验证

项目视觉哨兵仍使用模拟检测器。以下操作只验证 Linux 摄像头采集，不代表模型识别已接入。
先确认摄像头视野内可以测试，再检查设备名称和格式：

```bash
lsusb
v4l2-ctl --list-devices
v4l2-ctl -d /dev/video0 --get-fmt-video
timeout 20s v4l2-ctl -d /dev/video0 --stream-mmap --stream-count=30 --stream-to=/dev/null
```

设备编号可能变化，应使用 `--list-devices` 的实际结果。画面直接丢弃，不保存、不上传；
观察命令退出码、采集帧率和丢帧数。短时间成功不代表长时间稳定运行。

2026-09-03 已在 Raspberry Pi 5、Debian 13、Python 3.13.5、aarch64 环境完成验证。
USB Microdia 摄像头在 1920×1080 MJPEG 格式下完成 30 帧采集，约 29.35 fps，报告 1 次丢帧。
GPIO 外设、真实传感器和市电控制未进行物理验证。
