# 04 边缘视觉哨兵

演示隐私优先的视觉架构：摄像头帧默认不上传，检测器只输出事件与置信度；只有规则允许时
才保存必要证据。`main.py` 使用模拟检测器，便于替换为 OpenCV 或 TensorFlow Lite。

```bash
python main.py
```
