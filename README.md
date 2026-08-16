# Raspberry Pi 本地自动化笔记

这是我整理树莓派实验的地方。代码从 GPIO 和温湿度采集开始，后来逐渐加上了本地规则、
设备心跳、能源计划和运行状态控制台。现在的重点不是堆很多“智能家居”名词，而是先把几个
实际问题做扎实：断网后还能不能工作、设备掉线能不能看见、一次自动操作能不能追溯。

大部分项目可以先在普通电脑上运行。我把真机接口和模拟逻辑分开了，这样没有硬件时也能
调试；但模拟通过不等于真机已经验证，下面把目前做到的程度写清楚。

## 目前做到哪了

| 项目 | 现在可以做什么 | 硬件状态 |
|---|---|---|
| 01 呼吸灯 | 用 PWM 调整亮度，退出时关闭输出 | 有 `gpiozero` 真机适配，也可模拟 |
| 02 环境站 | 定时采集、失败重试、追加写入 CSV | 有 DHT22/BME280 适配；默认用模拟数据 |
| 03 局域网设备 API | 读取和修改一个输出值，提供健康检查 | 目前只接模拟输出 |
| 04 边缘视觉哨兵 | 按置信度把检测结果变成事件 | 目前只用模拟检测结果，未接摄像头 |
| 05 本地自动化中枢 | 规则判断、设备心跳和 JSONL 审计 | 目前是模拟事件演示 |
| 06 能源调度器 | 按电价、光伏余量和优先级安排负载 | 只给出计划，不控制市电 |
| 07 运行状态控制台 | 汇总状态、持久化告警、确认与恢复 | 使用模拟数据，可输出文本或 JSON |

课程顺序和每一步的练习记在 [`docs/CURRICULUM.md`](docs/CURRICULUM.md)，接线前先看
[`docs/SAFETY.md`](docs/SAFETY.md)。每个项目目录也有一份短说明。

## 先在电脑上跑起来

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
```

局域网 API 需要 `web` 依赖：

```bash
uvicorn projects.03_local_device_api.main:app --host 127.0.0.1 --port 8000
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

更新内容记在 [`CHANGELOG.md`](CHANGELOG.md)。项目使用 MIT 许可证。涉及继电器、电机、电池或
市电时，请使用合规器件，并让有资质的人检查接线。
