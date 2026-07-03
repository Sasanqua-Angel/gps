"""Project configuration for the GPS simulation and replay system."""

from __future__ import annotations


PROJECT_NAME = "模拟 GPS 定位 + 轨迹回放系统"

MQTT_HOST = "127.0.0.1"
MQTT_PORT = 1883
MQTT_TOPIC_TEMPLATE = "gps/device/{device_id}"

HTTP_HOST = "127.0.0.1"
HTTP_PORT = 8000

DEVICE_ID = "GPS001"
COORDINATE_SYSTEM = "BD09"

# Replace this value with a Baidu Maps browser-side AK before demo.
BAIDU_MAP_AK = "OeSFrKWSg06nbQmHzIQ2Osfkm493WeXe"

SIMULATION_STEP_METERS = 18
SIMULATION_SPEED_KMH = 36
SIMULATION_TICK_SECONDS = 1.0
GPS_ERROR_MIN_METERS = 5
GPS_ERROR_MAX_METERS = 10
DROP_POINT_PROBABILITY = 0.10

SHORT_LOSS_SECONDS = 3
OFFLINE_SECONDS = 10

# Demo route around Shanghai People's Square area, using BD-09-like coordinates.
DEFAULT_ROUTE = [
    (31.233812, 121.475350),
    (31.233250, 121.478120),
    (31.231680, 121.477960),
    (31.230720, 121.476180),
    (31.231120, 121.473920),
    (31.232760, 121.473660),
    (31.233812, 121.475350),
]

