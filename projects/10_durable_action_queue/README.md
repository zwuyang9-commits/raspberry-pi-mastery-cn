# 10 持久化动作队列

自动化动作在执行前追加写入本地 JSONL。执行成功后标记完成，失败时记录错误并继续处理后面的
动作；程序重启后，未完成动作仍在队列里。该模型提供“至少执行一次”语义，因此真实设备处理器
应使用 `action_id` 做幂等控制。

```bash
python projects/10_durable_action_queue/main.py enqueue fan set 1 --id fan-command-001
python projects/10_durable_action_queue/main.py list
python projects/10_durable_action_queue/main.py run-demo
```

模拟单个设备失败：

```bash
python projects/10_durable_action_queue/main.py run-demo --fail-target fan
```

失败动作会保留，稍后再次运行即可重试。演示处理器不控制真实硬件；接 GPIO、MQTT 或 HTTP
设备时，要把动作 ID 传到下游，并让设备拒绝重复执行已经完成的 ID。
