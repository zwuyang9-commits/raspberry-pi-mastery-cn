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
python projects/10_durable_action_queue/main.py run-demo --fail-target fan --retry-delay 10
```

失败动作默认最多尝试 3 次，达到上限后进入死信区，不再占用正常队列：

```bash
python projects/10_durable_action_queue/main.py list-dead
python projects/10_durable_action_queue/main.py requeue fan-command-001 --new-id fan-command-002
```

误加入的待办可以带原因取消，取消记录会保留在审计日志中：

```bash
python projects/10_durable_action_queue/main.py cancel fan-command-001 --reason "设备维护"
```

调用 `dispatch` 时可传入 `retry_delay`。连续失败会按 1、2、4 倍延长等待时间；下次重试时间
写入审计日志，因此程序重启后仍会遵守退避窗口，不会对离线设备进行紧密重试。

每次领取动作还会写入默认 30 秒的执行租约，可用 `--lease-seconds` 调整。工作进程意外退出后，
其他进程会等待租约到期再恢复该动作，降低同一命令被立即并发执行的风险。

队列还使用同目录下的隐藏锁文件协调独立进程。领取、执行和完成记录处于同一个操作系统文件锁
保护区内，因此同一台主机上的多个工作进程不会同时执行相同队列；进程退出后锁会由系统释放。

重新入队必须使用新 ID，避免下游把它误判为已经处理过的旧命令。演示处理器不控制真实硬件；接 GPIO、MQTT 或 HTTP
设备时，要把动作 ID 传到下游，并让设备拒绝重复执行已经完成的 ID。
