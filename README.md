# 模拟 GPS 定位 + 轨迹回放系统

本项目用于物联网课程考核题目 2：电脑程序模拟 GPS 设备，加入 5-10 米随机定位偏差，生成经纬度、速度、方向，通过 MQTT 上传服务器，并在网页中使用百度地图 API 展示实时轨迹和轨迹回放。

## 一、运行环境

- Windows / macOS / Linux
- Python 3.9 或以上
- 浏览器：Chrome / Edge
- 百度地图开放平台浏览器端 AK

项目后端只使用 Python 标准库，不需要安装第三方 Python 包。

## 二、需要先做的操作

1. 到百度地图开放平台创建浏览器端应用，获取 AK。
2. 打开 `config.py`。
3. 把下面这一行替换成你的 AK：

```python
BAIDU_MAP_AK = "请替换为你的百度地图AK"
```

如果不配置 AK，服务器和 MQTT 仍可运行，但网页地图无法正常显示百度地图。

## 三、启动方法

先启动服务器，服务器包含 HTTP 网页服务和内置轻量 MQTT Broker：

```bash
python server.py
```

看到类似输出后保持窗口不要关闭：

```text
[MQTT] broker listening on mqtt://127.0.0.1:1883
[HTTP] dashboard listening on http://127.0.0.1:8000
```

再打开第二个终端，启动 GPS 模拟器：

```bash
python gps_simulator.py
```

然后用浏览器访问：

```text
http://127.0.0.1:8000
```

## 四、功能说明

- GPS 模拟器按预设路线生成经纬度。
- 每个定位点加入 5-10 米随机偏差，模拟真实 GPS 漂移。
- 根据路径点计算速度和方向。
- 使用 MQTT PUBLISH 报文上传到服务器。
- 服务器接收 MQTT 数据，保存原始点和平滑点。
- 网页使用百度地图 API 展示原始轨迹和平滑轨迹。
- 支持轨迹回放、清空轨迹、显示/隐藏原始点和平滑轨迹。

## 五、核心设计

### 1. 坐标点平滑处理

系统使用“异常点剔除 + 指数平滑”：

- 如果新点与上一点之间的速度超过合理阈值，判定为漂移点，不更新轨迹。
- 对正常点使用指数平滑：

```text
平滑点 = 上一次平滑点 * (1 - alpha) + 当前定位点 * alpha
```

这样可以减少 GPS 抖动，同时保留运动趋势。

### 2. 定位点丢失处理

GPS 模拟器会按一定概率丢弃定位点，模拟信号遮挡或网络不稳定。

服务器处理策略：

- 3 秒内没有新点：认为短时丢点，根据最后速度和方向预测位置。
- 超过 10 秒没有新点：认为设备离线，网页显示离线状态。
- 重新收到真实点后，恢复在线状态并继续平滑。

### 3. 流量优化策略

系统不是固定频率上传，而是动态调整：

| 场景 | 上传策略 |
|---|---|
| 静止或距离变化小 | 5 秒上传一次 |
| 普通移动 | 2 秒上传一次 |
| 高速移动 | 1 秒上传一次 |
| 方向变化超过 30° | 立即上传 |

这样可以减少无意义定位包，降低网络流量。

## 六、项目文件结构

```text
.
├─ config.py              # 项目配置和模拟路线
├─ gps_core.py            # 坐标计算、平滑、预测、上传策略
├─ gps_simulator.py       # GPS 设备模拟程序
├─ mqtt_broker.py         # 内置轻量 MQTT Broker
├─ mqtt_client.py         # MQTT 发布客户端
├─ mqtt_packet.py         # MQTT 报文编码解码工具
├─ server.py              # HTTP 服务 + MQTT 数据接收
├─ web/
│  ├─ index.html          # 百度地图展示页面
│  ├─ style.css           # 页面样式
│  └─ app.js              # 轨迹显示和回放逻辑
├─ tests/
│  ├─ test_gps_core.py    # 核心 GPS 算法测试
│  └─ test_mqtt_packet.py # MQTT 报文测试
├─ requirements.txt
└─ README.md
```

## 七、测试方法

运行自动化测试：

```bash
python -m unittest discover -s tests
```

检查 Python 文件语法：

```bash
python -m py_compile config.py gps_core.py gps_simulator.py mqtt_broker.py mqtt_client.py mqtt_packet.py server.py
```

## 八、小组分工建议

- 成员 1：GPS 模拟器、MQTT 上传、数据生成、注释说明。
- 成员 2：服务器接收、平滑处理、网页轨迹显示、PPT 美化。
- 共同完成：测试、运行截图、答辩准备、最终压缩包整理。

