# 02 智能环境站

这个项目按固定间隔读取温度和湿度，并把数据追加到 CSV。重复运行不会清空旧记录；如果传感器
偶尔读不到数据，程序会先重试，再决定是否退出。

## 先用模拟数据跑通

在仓库根目录执行：

```bash
python projects/02_environment_station/main.py \
  --sensor simulated \
  --samples 10 \
  --interval 0.5 \
  --output data/environment.csv
```

原来的 `--simulate` 参数仍然可用。查看全部参数：

```bash
python projects/02_environment_station/main.py --help
```

## 接 DHT22

安装树莓派依赖：

```bash
pip install -e ".[pi]"
```

DHT22 的 VCC 接 3.3V、GND 接 GND、DATA 默认接 GPIO4。裸传感器通常还需要在 VCC 和
DATA 之间接 4.7kΩ–10kΩ 上拉电阻。这里使用的是 CircuitPython 引脚名，所以 GPIO4 写作
`D4`。

```bash
python projects/02_environment_station/main.py \
  --sensor dht22 \
  --pin D4 \
  --interval 2 \
  --output data/dht22.csv
```

## 接 BME280

先在 `raspi-config` 中打开 I2C，再安装驱动：

```bash
pip install adafruit-circuitpython-bme280
```

模块使用 3.3V 供电，SDA 接 GPIO2，SCL 接 GPIO3。常见 I2C 地址是 `0x76`，有些模块是
`0x77`。

```bash
python projects/02_environment_station/main.py \
  --sensor bme280 \
  --i2c-address 0x76 \
  --samples 60 \
  --interval 10 \
  --output data/bme280.csv
```

## 断线重试

`--retries` 表示首次失败后最多再试几次，`--retry-delay` 是两次尝试之间的秒数：

```bash
python projects/02_environment_station/main.py \
  --sensor dht22 \
  --retries 5 \
  --retry-delay 2
```

CSV 固定使用 `timestamp_utc,temperature_c,humidity_pct` 三列。如果目标文件已有其他表头，
程序会停止并保留原文件，避免把两种格式混在一起。

## 数据质量限制

可以按安装环境设置合理范围和相邻读数的最大变化。超出限制的读数不会写进 CSV，而是按现有
重试策略重新读取；全部尝试失败后安全退出。采集完成时会显示温湿度的最小值、最大值和平均值。

```bash
python projects/02_environment_station/main.py \
  --sensor bme280 \
  --temperature-range -20 60 \
  --humidity-range 5 100 \
  --max-temperature-step 5 \
  --max-humidity-step 15
```

变化限制从第二个有效读数开始计算。应根据采样间隔和真实环境设定，不要照搬示例数值。
