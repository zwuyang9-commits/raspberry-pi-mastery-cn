# 01 呼吸灯

第一个硬件项目：使用 PWM 平滑改变 LED 亮度。默认 BCM 18，引脚与 LED 之间串联电阻。

```bash
python main.py --simulate --cycles 2
python main.py --pin 18 --cycles 5
python main.py --pin 18 --cycles 5 --watchdog-timeout 2
```

`--watchdog-timeout` 会在超过指定秒数没有收到新输出命令时自动把输出归零，适合演示程序卡住时的
软件安全状态。它不能替代硬件看门狗、急停、保险丝或合规的驱动隔离。
