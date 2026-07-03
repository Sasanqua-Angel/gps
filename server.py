"""Server entry point for the GPS trajectory replay system."""

from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import ThreadingHTTPServer

import config
from backend.http_api import make_dashboard_handler
from backend.store import TrackStore
from mqtt_broker import MQTTBroker


STORE = TrackStore()


def run_module_simulator(sim, interval: float) -> None:
    """独立运行模块模拟器，按指定频率生成点。
    monitor 模块根据速度动态调整上传间隔（通过点中的 upload_interval 字段）。"""
    # monitor 丢点状态追踪
    monitor_was_loss = False  # 上一帧是否处于丢点状态
    
    while True:
        point = sim.step()
        
        # 丢点场景：step() 返回 None 表示本次丢点，不发送事件
        if point is None:
            if sim.name == "monitor" and sim._loss_active:
                monitor_was_loss = True
                # 丢点期间发送状态更新（地图冻结提示）
                STORE.broadcast({
                    "type": "status",
                    "module": "monitor",
                    "status": {
                        "state": "loss",
                        "text": "[monitor] GPS 信号丢失中...",
                    },
                })
            time.sleep(interval)
            continue
        
        # 计算本次 sleep 时间：monitor 使用动态间隔，其他模块使用固定间隔
        sleep_interval = point.get("upload_interval", interval) if sim.name == "monitor" else interval
        
        # smoothing 模块：将模拟点传入平滑器处理，得到 raw + smooth 双数据
        if sim.name == "smoothing":
            # 构造 raw（含偏差的原始定位）
            raw = {
                "device_id": point["device_id"],
                "seq": point["seq"],
                "timestamp": point["timestamp"],
                "iso_time": point["iso_time"],
                "lat": point["lat"],
                "lng": point["lng"],
                "true_lat": point["true_lat"],
                "true_lng": point["true_lng"],
                "speed_kmh": point["speed_kmh"],
                "direction": point["direction"],
                "offset_meters": point["offset_meters"],
                "upload_interval": point["upload_interval"],
                "coordinate_system": point["coordinate_system"],
            }
            # 经过指数平滑 + 漂移剔除
            smooth = STORE.smoother.update(raw)
            event = {
                "type": "module_point",
                "module": sim.name,
                "point": point,
                "raw": raw,
                "smooth": smooth,
                "status": {
                    "state": "online",
                    "text": f"[{sim.name}] 设备在线",
                    "last_received_at": point["received_at"],
                    "last_device_timestamp": point["timestamp"],
                },
            }
        # monitor 模块：模拟点同样经过平滑器处理，产生 raw + smooth 双数据
        # raw = 原始模拟点（含漂移、速度突变等异常），smooth = 平滑+剔除后的当前轨迹
        # 上传间隔根据速度动态调整（参考 AdaptiveUploadPolicy）
        # 丢点恢复后自动发送 Catmull-Rom 插值补点数据
        elif sim.name == "monitor":
            raw = {
                "device_id": point["device_id"],
                "seq": point["seq"],
                "timestamp": point["timestamp"],
                "iso_time": point["iso_time"],
                "lat": point["lat"],
                "lng": point["lng"],
                "true_lat": point.get("true_lat", point["lat"]),
                "true_lng": point.get("true_lng", point["lng"]),
                "speed_kmh": point["speed_kmh"],
                "direction": point["direction"],
                "offset_meters": point.get("offset_meters", 0),
                "upload_interval": point["upload_interval"],
                "coordinate_system": point["coordinate_system"],
            }
            # 经过指数平滑 + 漂移剔除（过滤速度>160km/h的异常点）
            smooth = STORE.monitor_smoother.update(raw)
            # 存储平滑后的当前轨迹点到后端，供 snapshot 使用
            STORE.monitor_smooth_points.append(smooth)
            
            event = {
                "type": "module_point",
                "module": sim.name,
                "point": point,
                "raw": raw,
                "smooth": smooth,
                "status": {
                    "state": "online",
                    "text": f"[{sim.name}] 设备在线",
                    "last_received_at": point["received_at"],
                    "last_device_timestamp": point["timestamp"],
                },
            }
            
            # 丢点恢复：先发 loss_recovery（补点虚线），再发 module_point（平滑当前轨迹）
            if monitor_was_loss:
                monitor_was_loss = False
                recovery = sim.get_loss_recovery_data()
                if recovery:
                    # 第一步：发送 loss_recovery，前端先渲染恢复后的原始节点和补点虚线
                    STORE.broadcast({
                        "type": "loss_recovery",
                        "module": "monitor",
                        "data": recovery,
                        "demo": {
                            "kind": "recover",
                            "message": "GPS 信号恢复，红色虚线为 Catmull-Rom 插值补点轨迹",
                        },
                    })
        else:
            event = {
                "type": "module_point",
                "module": sim.name,
                "point": point,
                "status": {
                    "state": "online",
                    "text": f"[{sim.name}] 设备在线",
                    "last_received_at": point["received_at"],
                    "last_device_timestamp": point["timestamp"],
                },
            }
        
        STORE.broadcast(event)
        time.sleep(sleep_interval)


def start_module_simulators() -> None:
    """启动四个模块的独立模拟线程"""
    sims = [
        (STORE.monitor_sim, STORE.monitor_sim.upload_interval),
        (STORE.smoothing_sim, STORE.smoothing_sim.upload_interval),
        (STORE.loss_sim, STORE.loss_sim.upload_interval),
        (STORE.traffic_sim, STORE.traffic_sim.upload_interval),
    ]
    for sim, interval in sims:
        t = threading.Thread(target=run_module_simulator, args=(sim, interval), daemon=True)
        t.start()
        print(f"[SIM] {sim.name} 模块模拟器已启动，上传间隔 {interval}s")


def run_server(host: str, port: int, mqtt_host: str, mqtt_port: int) -> None:
    broker = MQTTBroker(mqtt_host, mqtt_port)
    broker.subscribe_internal("gps/device/+", STORE.add_mqtt_message)
    broker.start()
    # 启动四个模块独立模拟器
    start_module_simulators()

    handler_class = make_dashboard_handler(STORE)
    httpd = ThreadingHTTPServer((host, port), handler_class)
    print(f"[MQTT] broker listening on mqtt://{mqtt_host}:{mqtt_port}")
    print(f"[HTTP] dashboard listening on http://{host}:{port}")
    print("[HTTP] press Ctrl+C to stop")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[HTTP] stopping")
    finally:
        httpd.server_close()
        broker.stop()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Start GPS replay dashboard and embedded MQTT broker.")
    parser.add_argument("--host", default=config.HTTP_HOST)
    parser.add_argument("--port", default=config.HTTP_PORT, type=int)
    parser.add_argument("--mqtt-host", default=config.MQTT_HOST)
    parser.add_argument("--mqtt-port", default=config.MQTT_PORT, type=int)
    parser.add_argument("--check", action="store_true", help="print configuration and exit")
    return parser


if __name__ == "__main__":
    args = build_parser().parse_args()
    if args.check:
        print(
            json.dumps(
                {
                    "http": f"http://{args.host}:{args.port}",
                    "mqtt": f"mqtt://{args.mqtt_host}:{args.mqtt_port}",
                    "baidu_map_ak_set": config.BAIDU_MAP_AK != "请替换为你的百度地图AK",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        run_server(args.host, args.port, args.mqtt_host, args.mqtt_port)
