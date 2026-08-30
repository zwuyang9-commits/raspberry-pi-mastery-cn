# 04 边缘视觉哨兵

演示隐私优先的视觉架构：摄像头帧默认不上传，检测器只输出事件与置信度；只有规则允许时
才保存必要证据。事件需要连续多帧达到阈值，并按标签设置冷却时间，避免抖动和重复告警。
`main.py` 使用可复现的模拟检测器，便于替换为 OpenCV 或 TensorFlow Lite。

```bash
python projects/04_edge_vision_sentinel/main.py --frames 20 --threshold 0.8 \
  --confirm-frames 2 --cooldown 30
```

输出只包含标签、置信度、确认帧数和 UTC 时间，不包含原始图像。最后一行给出处理帧数、检测数和
事件数。真实摄像头接入时，把模型输出转换成 `Detection` 即可，过滤逻辑不依赖具体视觉框架。
