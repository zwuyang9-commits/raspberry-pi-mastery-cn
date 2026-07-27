# 完整课程路线

## 第 0 章：准备与安全

目标：会安装 Raspberry Pi OS Lite、启用 SSH、创建虚拟环境、阅读 BCM 引脚编号。

练习：

1. 更新系统并安装 `python3-venv`。
2. 用 `pinout` 查看引脚。
3. 阅读 `SAFETY.md`，计算 LED 限流电阻。

## 第 1 章：GPIO 基础

项目：`projects/01_led_breathing`

理解数字输出、PWM 占空比、资源清理以及为何程序异常时也必须关闭执行器。

## 第 2 章：采集真实世界

项目：`projects/02_environment_station`

理解采样周期、时间戳、传感器噪声、校准和结构化数据。先使用模拟传感器，再替换为
DHT22 或 BME280 驱动。

## 第 3 章：把设备变成服务

项目：`projects/03_local_device_api`

理解 REST API、健康检查、输入约束和局域网访问。生产环境应添加身份验证、TLS 和防火墙。

## 第 4 章：边缘智能

项目：`projects/04_edge_vision_sentinel`

学习“先检测事件，再保存证据”的隐私设计。示例使用可替换检测器，方便接入 OpenCV、
TensorFlow Lite、YOLO Nano 或 Hailo 加速器。

## 第 5 章：旗舰——韧性家庭智能中枢

项目：`projects/05_resilient_home_hub`

中枢接收统一事件，通过声明式规则产生动作，并保留原因。云端不可用时，本地规则仍工作；
传感器异常时进入安全状态。可扩展方向：

- 本地语音：Whisper.cpp + Piper
- 本地视觉：TensorFlow Lite/Hailo
- 能源调度：分时电价与光伏预测
- 无障碍：语音、按钮、手势多模态控制
- 农业：土壤、灌溉、霜冻预警

## 毕业标准

- 能解释 3.3V GPIO 的限制。
- 能为传感器编写模拟器和测试。
- 能让服务断网运行并在重启后恢复。
- 能记录每个自动化动作的原因。
- 能完成一个真实场景的端到端部署。
