# 树莓派实机回归验证

## 离线人物检测增量验证（2026-09-03）

- 已验证代码：`303781c2760af4a9095f2f8fce3109b5a59c11ec`；在此前隔离测试目录应用同一代码后运行。
- 平台：Raspberry Pi 5，Debian 13，aarch64，Python 3.13.5，OpenCV 4.14.0。
- 实际 USB 摄像头 `/dev/video0`：使用 `--frames 10 --interval 0.2 --threshold 0.5`，
  外层 `timeout 60s`；10 帧经过 HOG 推理，退出码 0，检测数 0、事件数 0。
- 没有保存或上传图像，不做人脸身份识别。**只证明采集与推理链路运行成功，未验证
  有人的正样本检出效果、准确率、无人判断、长时间稳定性或实时帧率。**
- 树莓派回归：312 passed，0 skipped，18.12 秒，覆盖率 90.21%；一条第三方
  Starlette/AnyIO 弃用警告。pip 依赖检查、Ruff、部署预检、API 配置检查及本机 API
  启动/健康/就绪检查通过，测试服务已关闭。
- Windows 对照：310 passed，2 skipped，覆盖率 90.13%；摄像头单元测试使用替身，
  不将其视为 Windows 实际摄像头验证。
- 以下记录保留为各自指定版本的历史结果，不代表每个历史提交均逐一验证。

## 已测试版本与结果

- 日期：2026-09-03。
- 已验证代码：`36b76146fe8c16615efd211af168b61be4cfa495`。
- 范围：该提交包含的此前主分支累计代码；**不是每个历史提交单独通过测试**。
- 平台：Raspberry Pi 5，Debian 13，Linux aarch64，Python 3.13.5。
- 完整回归：**266 passed，0 failed，0 skipped，14.03 秒，覆盖率 89.70%**。
- `pip check`、Ruff、部署预检、API 配置检查、本机 API 启动与健康/就绪检查均通过。
- 视觉模拟：20 帧、20 次模拟检测、0 个符合规则的事件，正常退出；不是实际图像识别结果。
- 一条第三方 Starlette/AnyIO 的 `BlockingPortal` 弃用警告，不影响本次测试通过。
- Windows 对照验证：264 passed、2 个平台相关 skipped，覆盖率 89.61%。
- GitHub 对应版本的 [CI](https://github.com/zwuyang9-commits/raspberry-pi-mastery-cn/actions/runs/33721083503)
  与 [CodeQL](https://github.com/zwuyang9-commits/raspberry-pi-mastery-cn/actions/runs/33721083534) 通过。

| 项目 | 已通过的测试 | 尚未验证的部分 |
|---|---|---|
| 01 呼吸灯 | GPIO 适配/看门狗单元测试、模拟 CLI 在树莓派运行 | LED 实际接线与 PWM 波形 |
| 02 环境站 | 采集质量和故障处理单元测试、模拟 CSV 追加 CLI | DHT22/BME280 实际读数 |
| 03 设备 API | API 自动化测试、本机服务启动、健康与就绪检查 | 真实执行器、外网或长期部署 |
| 04 视觉哨兵 | 过滤/去重单元测试、20 帧模拟 CLI；USB 采集另行验证 | 摄像头到识别模型的完整集成 |
| 05 本地中枢 | 规则和健康逻辑、模拟事件 CLI | 真实阀门/风扇动作 |
| 06 能源调度 | 调度算法测试、计划 CLI | 实际电表、逆变器、市电控制 |
| 07 控制台 | 状态/告警逻辑、JSON/Prometheus 与审计联动 CLI | 长时间在线监控 |
| 08 备份 | 完整单元测试、跨进程创建/校验/演练/逐字节恢复 | SD 卡断电、介质物理故障 |
| 09 审计 | 查询/归档/并发单元测试、只读摘要 CLI | 超大生产日志长期压力 |
| 10 动作队列 | 持久化/并发单元测试、跨进程失败/死信恢复 CLI | 实际设备幂等与掉电场景 |

这些结果不能保证所有输入、所有外设或未来提交均无故障。没有上传画面、凭据、网络地址或个人文件。

## 复测步骤

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
.venv/bin/python scripts/smoke_api.py
```

`smoke_api.py` 临时启动仅监听本机的模拟 API，检查后关闭，不向局域网或公网开放服务。

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
