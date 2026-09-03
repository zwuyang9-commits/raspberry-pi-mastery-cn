# 01 呼吸灯

第一个硬件项目：使用 PWM 平滑改变 LED 亮度。默认 BCM 18，引脚与 LED 之间串联电阻。

```bash
python main.py --simulate --cycles 2
python main.py --pin 18 --cycles 5
python main.py --pin 18 --cycles 5 --watchdog-timeout 2
```

`--watchdog-timeout` 会在超过指定秒数没有收到新输出命令时自动把输出归零，适合演示程序卡住时的
软件安全状态。如果计时器本身无法创建或启动，输出也会立即归零并向调用方报告错误。看门狗关闭时
也会在关闭底层适配器前显式写入安全值，即使写入失败仍会尝试释放设备。它不能替代
硬件看门狗、急停、保险丝或合规的驱动隔离。
> 已经过树莓派 5 软件测试（2026-09-03，代码版本 `36b7614`）。呼吸灯模拟 CLI 与硬件适配/看门狗单元测试通过；未验证实际 LED 接线。
> 详见[实机验证范围与记录](../../docs/real-device-validation.md)。
