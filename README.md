# 树莓派：从入门到精通

一套中文、可运行、可测试的树莓派学习仓库。所有核心示例都支持两种模式：

- **真机模式**：在 Raspberry Pi 上控制 GPIO、传感器和执行器。
- **模拟模式**：没有树莓派时也能在 Windows、macOS 或 Linux 上学习与测试。

## 学习路线

| 阶段 | 项目 | 学到什么 |
|---|---|---|
| 0 | 环境与安全 | 系统安装、Python、GPIO 电气安全 |
| 1 | LED 呼吸灯 | GPIO、PWM、异常退出清理 |
| 2 | 智能环境站 | 传感器、采样、校准、CSV 数据 |
| 3 | 局域网设备 API | FastAPI、远程控制、健康检查 |
| 4 | 边缘视觉哨兵 | 摄像头、事件检测、隐私优先设计 |
| 5 | 离线智能中枢 | 规则引擎、故障降级、自动化决策 |
| 6 | 本地能源调度器 | 分时电价、太阳能利用、负载优先级 |

完整课程见 [`docs/CURRICULUM.md`](docs/CURRICULUM.md)，接线安全见
[`docs/SAFETY.md`](docs/SAFETY.md)。

## 快速开始

```bash
git clone https://github.com/zwuyang9-commits/12.git
cd 12
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,web]"
pytest
```

Windows 激活虚拟环境：

```powershell
.venv\Scripts\Activate.ps1
```

运行模拟 LED：

```bash
python projects/01_led_breathing/main.py --simulate --cycles 2
```

运行智能中枢演示：

```bash
python projects/05_resilient_home_hub/main.py --simulate
```

运行能源调度演示：

```bash
python projects/06_local_energy_scheduler/main.py
```

运行局域网 API：

```bash
uvicorn projects.03_local_device_api.main:app --host 0.0.0.0 --port 8000
```

## “划时代”的落地点

旗舰项目不是依赖云端的玩具，而是一个**断网可用、数据不出家门、硬件故障可降级**
的边缘智能框架。它把传感器事件转换成可审计的自动化决策，后续可以接入本地语音模型、
视觉模型、能源管理和无障碍设备。创新必须可以测试，因此规则引擎与硬件层均有自动化测试。

## 支持硬件

- Raspberry Pi 3B+/4/5/Zero 2 W
- LED、按钮、蜂鸣器、继电器（必须使用合适驱动电路）
- DHT22/BME280 等环境传感器
- 官方 Camera Module 或 USB 摄像头

## 项目原则

1. 默认安全：输出引脚启动时保持关闭。
2. 离线优先：断网不影响基本自动化。
3. 隐私优先：原始图像和语音默认只在本地处理。
4. 可测试：业务逻辑不依赖真实 GPIO。
5. 可解释：每次自动决策都给出原因。

## 许可证

MIT。涉及市电、继电器、电机或电池时，请由具备资质的人员检查接线。
