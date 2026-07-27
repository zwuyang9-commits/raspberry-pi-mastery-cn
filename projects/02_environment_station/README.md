# 02 智能环境站

按固定间隔采集温湿度并写入 CSV。模拟器生成平滑数据，方便在没有传感器时学习。

```bash
python main.py --simulate --samples 10 --output data/environment.csv
```

真机扩展：实现相同的 `read()` 接口，接入 DHT22 或 BME280。
