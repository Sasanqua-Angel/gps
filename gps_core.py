"""Core GPS math, smoothing, prediction, and upload policy helpers."""

from __future__ import annotations

import math
import random
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Iterable, List, Optional, Sequence, Tuple


EARTH_RADIUS_M = 6_371_000


def haversine_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return great-circle distance between two coordinates in meters."""

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lng2 - lng1)
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def bearing_degrees(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return compass bearing from point A to point B in degrees."""

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_lambda = math.radians(lng2 - lng1)
    y = math.sin(delta_lambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(delta_lambda)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def angle_delta_degrees(a: float, b: float) -> float:
    """Return the smallest absolute difference between two bearings."""

    return abs((a - b + 180) % 360 - 180)


def move_point(lat: float, lng: float, distance_meters: float, bearing_degrees: float) -> dict:
    """Move from a coordinate by distance and bearing, returning a new coordinate."""

    angular_distance = distance_meters / EARTH_RADIUS_M
    bearing = math.radians(bearing_degrees)
    phi1 = math.radians(lat)
    lambda1 = math.radians(lng)

    phi2 = math.asin(
        math.sin(phi1) * math.cos(angular_distance)
        + math.cos(phi1) * math.sin(angular_distance) * math.cos(bearing)
    )
    lambda2 = lambda1 + math.atan2(
        math.sin(bearing) * math.sin(angular_distance) * math.cos(phi1),
        math.cos(angular_distance) - math.sin(phi1) * math.sin(phi2),
    )

    return {"lat": math.degrees(phi2), "lng": (math.degrees(lambda2) + 540) % 360 - 180}


def inject_random_offset(
    lat: float,
    lng: float,
    min_meters: float = 5,
    max_meters: float = 10,
    seed: Optional[int] = None,
) -> dict:
    """Inject a random GPS offset within the configured meter range."""

    rng = random.Random(seed)
    distance = rng.uniform(min_meters, max_meters)
    bearing = rng.uniform(0, 360)
    point = move_point(lat, lng, distance, bearing)
    point["offset_meters"] = distance
    point["offset_direction"] = bearing
    return point


def interpolate_route(
    route: Sequence[Tuple[float, float]],
    step_meters: float = 20,
    speed_kmh: float = 36,
) -> List[dict]:
    """Interpolate route coordinates into dense GPS points."""

    if len(route) < 2:
        raise ValueError("route must contain at least two coordinates")

    points: List[dict] = []
    timestamp = 0.0
    meters_per_second = max(speed_kmh, 0.1) * 1000 / 3600

    for segment_index, (start, end) in enumerate(zip(route, route[1:])):
        start_lat, start_lng = start
        end_lat, end_lng = end
        segment_distance = haversine_meters(start_lat, start_lng, end_lat, end_lng)
        direction = bearing_degrees(start_lat, start_lng, end_lat, end_lng)
        steps = max(1, int(math.ceil(segment_distance / step_meters)))

        for step in range(steps):
            if segment_index > 0 and step == 0:
                continue
            distance = min(step * step_meters, segment_distance)
            coord = move_point(start_lat, start_lng, distance, direction)
            points.append(
                {
                    "lat": coord["lat"],
                    "lng": coord["lng"],
                    "speed_kmh": speed_kmh,
                    "direction": direction,
                    "timestamp": round(timestamp, 3),
                    "segment_index": segment_index,
                }
            )
            timestamp += step_meters / meters_per_second

    final_lat, final_lng = route[-1]
    previous = points[-1]
    points.append(
        {
            "lat": final_lat,
            "lng": final_lng,
            "speed_kmh": speed_kmh,
            "direction": bearing_degrees(previous["lat"], previous["lng"], final_lat, final_lng),
            "timestamp": round(timestamp, 3),
            "segment_index": len(route) - 2,
        }
    )
    return points


@dataclass
class ExponentialTrackSmoother:
    """Smooth GPS jitter and reject physically unreasonable jumps."""

    alpha: float = 0.35
    max_reasonable_speed_kmh: float = 160
    last_point: Optional[dict] = None
    last_raw_point: Optional[dict] = None

    def update(self, raw_point: dict) -> dict:
        if self.last_point is None:
            smoothed = dict(raw_point)
            smoothed["quality"] = "real"
            smoothed["raw_lat"] = raw_point["lat"]
            smoothed["raw_lng"] = raw_point["lng"]
            self.last_point = smoothed
            self.last_raw_point = dict(raw_point)
            return smoothed

        previous = self.last_point
        previous_raw = self.last_raw_point or previous
        current_time = float(raw_point.get("timestamp", previous.get("timestamp", 0) + 1))
        previous_time = float(previous_raw.get("timestamp", current_time - 1))
        elapsed = max(current_time - previous_time, 0.001)
        distance = haversine_meters(previous_raw["lat"], previous_raw["lng"], raw_point["lat"], raw_point["lng"])
        observed_speed = distance / elapsed * 3.6

        if observed_speed > self.max_reasonable_speed_kmh:
            rejected = dict(previous)
            rejected["timestamp"] = raw_point.get("timestamp", previous.get("timestamp"))
            rejected["quality"] = "rejected"
            rejected["raw_lat"] = raw_point["lat"]
            rejected["raw_lng"] = raw_point["lng"]
            rejected["observed_speed_kmh"] = observed_speed
            rejected["reject_reason"] = f"observed speed {observed_speed:.1f} km/h is unreasonable"
            return rejected

        alpha = min(max(self.alpha, 0.01), 1.0)
        smoothed = dict(raw_point)
        smoothed["lat"] = previous["lat"] * (1 - alpha) + raw_point["lat"] * alpha
        smoothed["lng"] = previous["lng"] * (1 - alpha) + raw_point["lng"] * alpha
        smoothed["quality"] = "smoothed"
        smoothed["raw_lat"] = raw_point["lat"]
        smoothed["raw_lng"] = raw_point["lng"]
        smoothed["observed_speed_kmh"] = observed_speed
        self.last_point = smoothed
        self.last_raw_point = dict(raw_point)
        return smoothed


def predict_missing_point(last_point: dict, missing_timestamp: float) -> dict:
    """Predict a short-term missing GPS point from the last speed and direction."""

    elapsed = max(float(missing_timestamp) - float(last_point.get("timestamp", missing_timestamp)), 0)
    distance = float(last_point.get("speed_kmh", 0)) * 1000 / 3600 * elapsed
    moved = move_point(last_point["lat"], last_point["lng"], distance, float(last_point.get("direction", 0)))
    predicted = dict(last_point)
    predicted.update(moved)
    predicted["timestamp"] = missing_timestamp
    predicted["quality"] = "predicted"
    predicted["predicted_seconds"] = elapsed
    return predicted


@dataclass
class AdaptiveUploadPolicy:
    """Choose upload frequency from motion state to reduce useless traffic."""

    stationary_speed_kmh: float = 2.0
    low_speed_kmh: float = 15.0
    high_speed_kmh: float = 50.0
    stationary_interval_seconds: float = 10.0
    low_speed_interval_seconds: float = 3.0
    normal_interval_seconds: float = 1.0
    high_speed_interval_seconds: float = 0.5
    direction_immediate_degrees: float = 30.0
    min_distance_meters: float = 5.0
    distance_immediate_meters: float = 10.0

    def interval_seconds(self, speed_kmh: float, direction_delta: float, distance_delta_m: float) -> float:
        if abs(direction_delta) >= self.direction_immediate_degrees:
            return self.high_speed_interval_seconds
        if speed_kmh >= self.high_speed_kmh:
            return self.high_speed_interval_seconds
        if speed_kmh < self.stationary_speed_kmh or distance_delta_m < self.min_distance_meters:
            return self.stationary_interval_seconds
        if speed_kmh < self.low_speed_kmh:
            return self.low_speed_interval_seconds
        return self.normal_interval_seconds

    def decision_flags(
        self,
        speed_kmh: float,
        direction_delta: float,
        distance_delta_m: float,
        elapsed_seconds: float,
    ) -> dict:
        interval = self.interval_seconds(speed_kmh, direction_delta, distance_delta_m)
        return {
            "time_due": elapsed_seconds >= interval,
            "distance_due": distance_delta_m >= self.distance_immediate_meters,
            "direction_due": abs(direction_delta) >= self.direction_immediate_degrees,
        }

    def should_upload(
        self,
        speed_kmh: float,
        direction_delta: float,
        distance_delta_m: float,
        elapsed_seconds: float,
    ) -> bool:
        flags = self.decision_flags(speed_kmh, direction_delta, distance_delta_m, elapsed_seconds)
        return any(flags.values())
