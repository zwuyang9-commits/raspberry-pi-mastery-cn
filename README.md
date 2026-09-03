# Raspberry Pi 本地自动化笔记

## 已经过树莓派 5 实机软件测试

2026-09-03 对提交 `36b76146fe8c16615efd211af168b61be4cfa495`（此前提交累计的主分支代码）
完成完整回归：**266 项通过、0 项失败、0 项跳过，覆盖率 89.70%**。
运行环境为 Raspberry Pi 5 / Debian 13 / Python 3.13.5 / aarch64；依赖、Ruff、部署预检、
API 配置及本机 API 实际启动检查均通过。后续版本需要重新验证，未逐个检出历史提交测试。

**实机软件测试不等于所有外设已验证。** GPIO 和温湿度传感器仍采用模拟/替身测试；
USB 摄像头已接入离线 HOG 识别链路，10 帧实测成功，但尚未验证人物正样本检出效果。
各项目范围、警告及复测命令见 [实机测试记录](docs/real-device-validation.md)。

这是我整理树莓派实验的地方。代码从 GPIO 和温湿度采集开始，后来逐渐加上了本地规则、
设备心跳、能源计划和运行状态控制台。现在的重点不是堆很多“智能家居”名词，而是先把几个
实际问题做扎实：断网后还能不能工作、设备掉线能不能看见、一次自动操作能不能追溯。

大部分项目可以先在普通电脑上运行。我把真机接口和模拟逻辑分开了，这样没有硬件时也能
调试；但模拟通过不等于真机已经验证，下面把目前做到的程度写清楚。

## 目前做到哪了

| 项目 | 现在可以做什么 | 硬件状态 |
|---|---|---|
| 01 呼吸灯 | PWM 调光、退出清理和可选安全看门狗 | 有 `gpiozero` 真机适配，也可模拟 |
| 02 环境站 | 定时采集、质量校验、统计、追加写入 CSV | 有 DHT22/BME280 适配；默认用模拟数据 |
| 03 局域网设备 API | 鉴权、幂等写入、审计和健康检查 | 目前只接模拟输出 |
| 04 边缘视觉哨兵 | 连续命中确认、冷却去重、可选离线 HOG 人物检测 | USB 摄像头推理链路通过；人物检出效果待验证 |
| 05 本地自动化中枢 | 规则故障隔离、设备心跳和 JSONL 审计 | 目前是模拟事件演示 |
| 06 能源调度器 | 按电价、光伏和优先级安排负载并解释缺口 | 只给出计划，不控制市电 |
| 07 运行状态控制台 | 汇总健康、告警、能源和持久队列状态 | 可输出文本、JSON 或 Prometheus 指标 |
| 08 可校验本地备份 | 打包状态文件、SHA-256 校验、安全恢复 | 纯本地运行，不依赖云服务 |
| 09 本地审计查询器 | 按类型、来源、时间筛选并生成摘要 | 只读 JSONL，不需要数据库 |
| 10 持久化动作队列 | 退避、租约、并发锁、取消、死信和安全归档 | 至少执行一次，处理器需支持幂等 |

课程顺序和每一步的练习记在 [`docs/CURRICULUM.md`](docs/CURRICULUM.md)，接线前先看
[`docs/SAFETY.md`](docs/SAFETY.md)。每个项目目录也有一份短说明。

准备长期运行或监听局域网前，请按 [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) 执行部署预检、
健康检查、更新备份和回滚演练。

## 先在电脑上跑起来

### 一次运行安全功能演示

在项目目录、已安装依赖的环境中运行：

```bash
python scripts/run_safe_demos.py
```

按顺序运行模拟呼吸灯、模拟环境采样、本地规则、能源计划、运行控制台和审计摘要。
终端立即显示当前阶段，每个阶段结束后显示该阶段输出。默认把数据保存到独立临时目录，
目录路径会打印出来；每一步有单独日志，`summary.json` 包含完成状态、退出码和耗时。
使用 `--output /path/to/new-directory` 指定**不存在的新目录**，绝不覆盖已有目录。
每一步默认超时 30 秒，可用 `--timeout` 指定不超过 300 秒的正数。
单步失败或超时后继续其他演示，整体退出码为 1；全部成功返回 0，中断返回 130。
只有 `complete: true` 且 `ok: true` 才表示整轮成功；缺失或不完整的摘要不能当作通过。

所有演示使用模拟硬件，不开摄像头、不驱动 GPIO、不启动网络服务。
这些演示不替代完整 pytest 回归，也不证明实际传感器、执行器或相机识别效果。
在树莓派桌面终端执行同一命令即可前台展示，结束后可直接查看日志。

### 安装与单项目运行

```bash
git clone https://github.com/zwuyang9-commits/raspberry-pi-mastery-cn.git
cd raspberry-pi-mastery-cn
python -m venv .venv
```

Linux 或 macOS：

```bash
source .venv/bin/activate
pip install -e ".[dev,web]"
```

Windows PowerShell：

```powershell
.venv\Scripts\Activate.ps1
pip install -e ".[dev,web]"
```

可以从这几个命令开始：

```bash
# 模拟呼吸灯
python projects/01_led_breathing/main.py --simulate --cycles 2

# 采集 10 组模拟温湿度，结果追加到 data/environment.csv
python projects/02_environment_station/main.py --sensor simulated --samples 10

# 查看本地中枢状态；加 --json 可交给其他脚本读取
python projects/07_local_operations_console/main.py
python projects/07_local_operations_console/main.py --json
python projects/07_local_operations_console/main.py --prometheus

# 备份并校验本地状态文件
python projects/08_verified_local_backup/main.py --root . create backups/state.zip data
python projects/08_verified_local_backup/main.py verify backups/state.zip
```

局域网 API 需要 `web` 依赖：

```bash
python scripts/run_api.py
```

启动后打开 `http://127.0.0.1:8000/docs`。默认只允许本机写入；要让局域网设备发送写请求，
需要先设置 `RPI_API_TOKEN`。这仍是实验接口，不应该直接暴露到公网。

## 接温湿度传感器

安装树莓派相关依赖：

```bash
pip install -e ".[pi]"
```

DHT22 默认使用 `D4`，BME280 默认使用 I2C 地址 `0x76`：

```bash
python projects/02_environment_station/main.py --sensor dht22 --pin D4
python projects/02_environment_station/main.py --sensor bme280 --i2c-address 0x76
```

具体接线、上拉电阻和 I2C 设置见
[`projects/02_environment_station/README.md`](projects/02_environment_station/README.md)。
我没有把“驱动已经写好”当成“所有板子都实测过”：不同传感器模块和系统镜像仍可能需要调整。

## 代码里的约定

- 输出设备关闭时回到安全状态，示例不直接驱动市电。
- 自动化逻辑不依赖 GPIO，方便在电脑上复现问题。
- 原始传感器数据、告警和审计记录默认留在本地。
- 告警确认只表示“有人在处理”，设备恢复后才会关闭告警。
- 每次新增硬件，先保留一个可重复的模拟入口。
- 自动化规则可先用 JSON 配置和模拟事件验证，配置错误时不替换上一版有效规则。

更新内容记在 [`CHANGELOG.md`](CHANGELOG.md)。项目使用 MIT 许可证。涉及继电器、电机、电池或
市电时，请使用合规器件，并让有资质的人检查接线。

安全问题请按 [`SECURITY.md`](SECURITY.md) 私密报告，不要在公开 Issue 粘贴令牌、日志或设备信息。
