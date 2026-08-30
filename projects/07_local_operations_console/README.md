# 07 本地运行状态控制台

这个项目把设备心跳、自动化动作、能源计划和审计记录放到同一张状态快照里。输出是纯文本，
通过 SSH 登录树莓派也能直接查看；加上 `--json` 后，可以接到局域网页面或监控脚本。

```bash
python projects/07_local_operations_console/main.py
python projects/07_local_operations_console/main.py --json
python projects/07_local_operations_console/main.py --prometheus
```

`--prometheus` 输出 Prometheus 文本格式，包括中枢状态、每台设备的心跳年龄、活动告警、能源
计划费用和快照中的动作数量。每次快照还会在审计日志中记录健康样本，并计算最近 24 小时的
采样在线率和掉线次数。可以让局域网采集脚本调用该命令并暴露结果，无需云端服务。

告警会写进本地 JSONL 审计日志。确认告警不会让故障消失，但能让下一位查看的人知道它已经
有人处理：

```bash
python projects/07_local_operations_console/main.py --ack device:water-valve
```

同一个问题恢复后会自动关闭；以后再次出现时会重新打开，不会沿用上一次的确认状态。示例
使用模拟数据，接入真实设备时只需把心跳、传感器事件和电价时段传给 `LocalOperations`。
