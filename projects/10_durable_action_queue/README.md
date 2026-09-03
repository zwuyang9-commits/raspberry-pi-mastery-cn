# 10 持久化动作队列

设备处理器异常的摘要限制为 200 字符并折叠换行，原异常类型单独记录。
如果第三方异常对象无法生成文字，日志使用类型名和 `message unavailable`，
仍按正常失败执行重试或进入死信，不会仅因错误文字格式化失败而阻断后续动作。

只有省略动作 ID（库接口传 `None`）才会自动生成 ID。显式空字符串、非字符串或非法字符
会在写入前被拒绝，不会悄悄替换为新 ID；死信恢复的 `new_action_id` 遵循相同规则。
有效 ID 长度为 1–128，允许英文字母、数字、点、下划线、冒号和连字符。

`list` 与 `list-dead` 支持按设备精确筛选并限制显示条数：

```bash
python projects/10_durable_action_queue/main.py list --target fan --limit 10
python projects/10_durable_action_queue/main.py list-dead --target fan --limit 10
```

先筛选再取前 N 条，保持原有顺序；设备名区分大小写，不做模糊匹配。
不指定参数时显示全部，无匹配时输出为空且成功退出。查询不会更改队列或重试死信。
条数限制只约束输出，不减少重建队列状态所需的日志读取量。

`enqueue` 的 JSON 值拒绝同一对象中的重复字段（包括嵌套对象与转义后相同的键），
不会按“最后一个值覆盖前面值”的方式静默入队。不同对象可以使用相同字段名。
NaN、Infinity 和溢出为无穷大的数值同样被拒绝；验证失败时不写入动作。

命令行遇到预期的参数、日志损坏或文件读写错误时，会向标准错误输出简洁原因并以退出码 1
结束，不输出 Python 堆栈。参数语法错误仍由解析器以退出码 2 报告。错误不会被包装成成功 JSON；
如果运行中途存储失败，应先检查日志与队列状态再重试，不代表之前的动作已自动回滚。

自动化动作在执行前追加写入本地 JSONL。执行成功后标记完成，失败时记录错误并继续处理后面的
动作；程序重启后，未完成动作仍在队列里。该模型提供“至少执行一次”语义，因此真实设备处理器
应使用 `action_id` 做幂等控制。

```bash
python projects/10_durable_action_queue/main.py enqueue fan set 1 --id fan-command-001
python projects/10_durable_action_queue/main.py list
python projects/10_durable_action_queue/main.py run-demo
```

使用只读状态命令检查实际队列，输出一行 JSON，可直接用于监控脚本：

```bash
python projects/10_durable_action_queue/main.py --queue data/action-queue.jsonl status
python projects/10_durable_action_queue/main.py --queue data/action-queue.jsonl status --fail-on-dead
```

字段包括 `pending`、`ready`、`deferred`、`leased`、`dead_letters` 和 `next_ready_at`。
最后一项是等待中的动作下次可执行的最早 UTC 时间；没有等待动作时为 `null`，
即使已有立即可执行的动作，也可能同时存在未来的 `next_ready_at`。
默认成功读取时退出码为 0；加 `--fail-on-dead` 后，存在死信时仍输出 JSON，但退出码为 1。
损坏日志读取失败，不输出伪造的健康状态。查询不会创建不存在的队列，也不会执行、取消或重试动作。

也可以先定时入队，计划时间必须包含时区：

```bash
python projects/10_durable_action_queue/main.py enqueue fan set 1 --id evening-fan --not-before 2026-09-03T23:00:00+08:00
```

库接口为 `enqueue(action, not_before=带时区的datetime)`。计划时间规范化为 UTC 并写入日志，
重启后继续生效；`list` 的 `next_attempt_at` 和状态摘要的 `deferred` 展示等待状态。
这是“最早可执行时间”，不是后台定时器：仍需定期调用 `dispatch` 或 `run-demo` 才会执行。
过去的计划时间立即可执行，失败后按重试退避重新计算时间。`max_items` 只计算实际尝试的动作，
等待计划时间或租约的动作不会挡住后面的可执行动作。

模拟单个设备失败：

```bash
python projects/10_durable_action_queue/main.py run-demo --fail-target fan --retry-delay 10
```

失败动作默认最多尝试 3 次，达到上限后进入死信区，不再占用正常队列：

库接口的 `max_attempts` 必须是正整数，`max_items` 必须是正整数或 `None`（不限制）。
布尔值、小数、字符串和非有限数值会在任何动作执行或日志写入前被拒绝，避免错误配置
绕过处理数量和重试上限；有效整数及 CLI 用法保持不变。

```bash
python projects/10_durable_action_queue/main.py list-dead
python projects/10_durable_action_queue/main.py requeue fan-command-001 --new-id fan-command-002
```

维修窗口后的恢复也可以延后执行：

```bash
python projects/10_durable_action_queue/main.py requeue fan-command-001 --new-id fan-recovery --not-before 2026-09-03T08:00:00+08:00
```

对应库接口为 `requeue_dead_letter(action_id, not_before=带时区的datetime)`。
恢复动作从零次尝试开始，原死信记录不变，重启后仍保留计划时间；不指定时间时保持立即可执行。
此命令只入队，仍需运行调度器才会执行。

误加入的待办可以带原因取消，取消记录会保留在审计日志中：

```bash
python projects/10_durable_action_queue/main.py cancel fan-command-001 --reason "设备维护"
```

调用 `dispatch` 时可传入 `retry_delay`。连续失败会按 1、2、4 倍延长等待时间；下次重试时间
写入审计日志，因此程序重启后仍会遵守退避窗口，不会对离线设备进行紧密重试。
传入的无时区执行时间按 UTC 处理，与持久化的退避和租约时间保持可比较。

每次领取动作还会写入默认 30 秒的执行租约，可用 `--lease-seconds` 调整。工作进程意外退出后，
其他进程会等待租约到期再恢复该动作，降低同一命令被立即并发执行的风险。

队列还使用同目录下的隐藏锁文件协调独立进程。领取、执行和完成记录处于同一个操作系统文件锁
保护区内，因此同一台主机上的多个工作进程不会同时执行相同队列；进程退出后锁会由系统释放。

不要对队列 JSONL 调用通用 `AuditLog.archive_before`：拆开一个动作的生命周期会破坏重启恢复。
库会主动拒绝这种操作。使用专用命令先预览，再显式应用：

```bash
python projects/10_durable_action_queue/main.py archive-terminal 2026-09-01T00:00:00+00:00 archives/queue.jsonl
python projects/10_durable_action_queue/main.py archive-terminal 2026-09-01T00:00:00+00:00 archives/queue.jsonl --apply
```

专用归档只移动已完成或已取消的完整生命周期，保留待办与死信，并留下已使用动作 ID 的墓碑，
防止旧 ID 被重新使用。

重新入队必须使用新 ID，避免下游把它误判为已经处理过的旧命令。演示处理器不控制真实硬件；接 GPIO、MQTT 或 HTTP
设备时，要把动作 ID 传到下游，并让设备拒绝重复执行已经完成的 ID。
> 已经过树莓派 5 软件测试（2026-09-03，代码版本 `36b7614`）。队列测试与跨进程死信恢复 CLI 通过；处理器为模拟实现。
> 详见[实机验证范围与记录](../../docs/real-device-validation.md)。
