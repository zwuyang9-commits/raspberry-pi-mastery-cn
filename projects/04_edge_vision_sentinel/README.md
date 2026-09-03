# 04 边缘视觉哨兵

## 只读检查 USB 摄像头

```bash
python scripts/list_usb_cameras.py
```

输出一行 JSON，包含 `sysfs_available`、`capture_tested: false` 和 `nodes`。
每个节点提供 `/dev/videoN` 路径、名称、四位十六进制 USB 厂商/产品编号，按设备编号排序。
只读取 Linux sysfs，不打开摄像头、不采集或上传画面，也不读取设备序列号；不需要 OpenCV。
树莓派内部的视频编解码节点会被排除。一个摄像头可能提供采集和元数据等多个节点，
所以节点数量不是摄像头数量；本命令不判断节点是否可采集，也不承诺编号重启后不变。

没有 sysfs（例如 Windows）时返回 `sysfs_available: false` 和空列表；设备目录存在但无 USB
视频节点时返回空列表。读取权限不足、扫描时设备被拔出或编号数据损坏会返回非零退出码，
不会静默报告成功。库接口为 `rpi_mastery.cameras.list_usb_video_nodes()`。
这个命令仅用于发现设备；真实检测需要显式指定下面的 `--camera` 参数。

## 离线 USB 摄像头人物检测

在树莓派的项目虚拟环境中安装可选依赖，然后执行有限帧检测：

```bash
python -m pip install '.[vision]'
timeout 60s python projects/04_edge_vision_sentinel/main.py \
  --camera /dev/video0 --frames 10 --interval 0.2 --threshold 0.5
```

使用 OpenCV 自带 HOG 行人模型，不需要云端 API 或额外下载模型。只接受本地
`/dev/videoN`，每次限制 1–300 帧，结束或异常时释放摄像头。驱动读取可能阻塞，
因此使用外层 `timeout` 限制实际运行时间；超时不代表成功。
图像只在内存中处理，不保存、不上传、不做人脸身份识别。默认仍是模拟模式。

真实模式输出 `mode: camera-hog`。事件中的 `confidence` 是 SVM 分数的 sigmoid
映射，**不是概率或准确率**，并以 `score_kind` 明确标记。最后一行给出处理帧数和
检测数，以及 `frames_saved: 0`、`frames_uploaded: 0`。无事件可能表示没有人物，
也可能是漏检或未达到连续帧阈值，不能据此断定无人。

该模型主要用于完整直立人体；遮挡、坐姿、暗光和视角变化会影响结果，不能用于安全保障。
新增真实检测链路尚待本次树莓派实机验证，下面的历史测试记录不代表它已通过。

演示隐私优先的视觉架构：不保存或上传摄像头帧，检测器只输出事件与分数。
事件需要连续多帧达到阈值，并按标签设置冷却时间，避免抖动和重复告警。
`main.py` 默认使用可复现的模拟检测器。

```bash
python projects/04_edge_vision_sentinel/main.py --frames 20 --threshold 0.8 \
  --confirm-frames 2 --cooldown 30
```

输出只包含标签、置信度、确认帧数和 UTC 时间，不包含原始图像。最后一行给出处理帧数、检测数和
事件数。标签会统一 Unicode、去除首尾空白并折叠大小写，防止模型格式波动绕过连续帧确认或冷却
限制。阈值必须是数值、确认帧数必须是真正的正整数、冷却期必须使用 `timedelta`，不会把布尔值或
小数悄悄当成帧数。真实摄像头接入时，把模型输出转换成 `Detection` 即可，过滤逻辑不依赖具体
视觉框架。超过冷却期的标签状态会自动清理，`rate_limited_labels` 可用于观察当前保留的限流记录，
避免动态标签在长期运行中无限累积。
> 已经过树莓派 5 软件测试（2026-09-03，代码版本 `36b7614`）。视觉过滤测试与模拟 CLI 通过；USB 采集独立通过，尚未接入识别模型。
> 详见[实机验证范围与记录](../../docs/real-device-validation.md)。
