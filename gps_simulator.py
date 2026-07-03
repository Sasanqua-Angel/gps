"""Simulated GPS device that uploads noisy location points through MQTT."""

from __future__ import annotations

import argparse
import json
import random
import time
from datetime import datetime

import config
from gps_core import (
    AdaptiveUploadPolicy,
    angle_delta_degrees,
    haversine_meters,
    inject_random_offset,
    interpolate_route,
)
from mqtt_client import MQTTClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Simulate a GPS device and publish MQTT location data.")
    parser.add_argument("--host", default=config.MQTT_HOST, help="MQTT broker host")
    parser.add_argument("--port", default=config.MQTT_PORT, type=int, help="MQTT broker port")
    parser.add_argument("--device-id", default=config.DEVICE_ID, help="simulated device id")
    parser.add_argument("--speed", default=config.SIMULATION_SPEED_KMH, type=float, help="route speed in km/h")
    parser.add_argument("--drop-rate", default=config.DROP_POINT_PROBABILITY, type=float, help="point loss probability")
    parser.add_argument("--max-points", default=0, type=int, help="stop after N route ticks; 0 means keep running")
    parser.add_argument("--seed", default=None, type=int, help="random seed for repeatable demos")
    return parser


def make_payload(device_id: str, seq: int, base_point: dict, noisy_point: dict, upload_interval: int) -> dict:
    return {
        "device_id": device_id,
        "seq": seq,
        "timestamp": time.time(),
        "iso_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "lat": noisy_point["lat"],
        "lng": noisy_point["lng"],
        "true_lat": base_point["lat"],
        "true_lng": base_point["lng"],
        "speed_kmh": base_point["speed_kmh"],
        "direction": base_point["direction"],
        "offset_meters": round(noisy_point["offset_meters"], 2),
        "upload_interval": upload_interval,
        "coordinate_system": config.COORDINATE_SYSTEM,
    }


def run_simulator(args: argparse.Namespace) -> None:
    rng = random.Random(args.seed)
    route_points = interpolate_route(
        config.DEFAULT_ROUTE,
        step_meters=config.SIMULATION_STEP_METERS,
        speed_kmh=args.speed,
    )
    topic = config.MQTT_TOPIC_TEMPLATE.format(device_id=args.device_id)
    policy = AdaptiveUploadPolicy()
    client = MQTTClient(args.host, args.port, client_id=f"{args.device_id}-simulator")
    client.connect()

    print(f"[GPS] connected to mqtt://{args.host}:{args.port}, topic={topic}")
    last_sent_payload = None
    last_sent_time = 0.0
    tick_count = 0
    published = 0

    try:
        while args.max_points <= 0 or tick_count < args.max_points:
            base_point = route_points[tick_count % len(route_points)]
            seed = rng.randint(0, 10_000_000)
            noisy_point = inject_random_offset(
                base_point["lat"],
                base_point["lng"],
                config.GPS_ERROR_MIN_METERS,
                config.GPS_ERROR_MAX_METERS,
                seed=seed,
            )

            now = time.time()
            if rng.random() < args.drop_rate:
                print(f"[GPS] seq={tick_count:04d} simulated point loss")
                tick_count += 1
                time.sleep(config.SIMULATION_TICK_SECONDS)
                client.ping_if_needed()
                continue

            if last_sent_payload is None:
                direction_delta = 0
                distance_delta = config.GPS_ERROR_MAX_METERS
                elapsed = 999
            else:
                direction_delta = angle_delta_degrees(base_point["direction"], last_sent_payload["direction"])
                distance_delta = haversine_meters(
                    last_sent_payload["lat"],
                    last_sent_payload["lng"],
                    noisy_point["lat"],
                    noisy_point["lng"],
                )
                elapsed = now - last_sent_time

            interval = policy.interval_seconds(base_point["speed_kmh"], direction_delta, distance_delta)
            should_upload = last_sent_payload is None or policy.should_upload(
                base_point["speed_kmh"],
                direction_delta,
                distance_delta,
                elapsed,
            )

            if should_upload:
                payload = make_payload(args.device_id, tick_count, base_point, noisy_point, interval)
                client.publish(topic, json.dumps(payload, ensure_ascii=False))
                last_sent_payload = payload
                last_sent_time = now
                published += 1
                print(
                    f"[GPS] upload seq={tick_count:04d} "
                    f"lat={payload['lat']:.6f} lng={payload['lng']:.6f} "
                    f"speed={payload['speed_kmh']:.1f}km/h direction={payload['direction']:.0f} "
                    f"interval={interval}s offset={payload['offset_meters']:.1f}m"
                )
            else:
                print(
                    f"[GPS] skip seq={tick_count:04d} traffic optimized "
                    f"elapsed={elapsed:.1f}s interval={interval}s distance={distance_delta:.1f}m"
                )

            tick_count += 1
            time.sleep(config.SIMULATION_TICK_SECONDS)
            client.ping_if_needed()
    except KeyboardInterrupt:
        print("\n[GPS] stopped by user")
    finally:
        client.disconnect()
        print(f"[GPS] finished ticks={tick_count}, published={published}")


if __name__ == "__main__":
    run_simulator(build_parser().parse_args())

