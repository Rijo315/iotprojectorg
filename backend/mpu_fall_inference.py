"""SENTROVA MPU6050 fall-detection prototype for Flask backend integration.

This is an explainable RULE-BASED prototype, NOT a trained ML model and NOT a
calibrated probability. It expects acceleration in m/s^2 and gyro in deg/s,
matching the supplied Adafruit_MPU6050 sketch.

Call process_sample(payload) from the existing POST /sensor route after the
route validates the six numeric sensor fields. Merge its returned fields into
that route's latest-sample/status record. See BACKEND_INTEGRATION.md.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import math
import threading
import time
from typing import Any

G = 9.80665
IMPACT_G_THRESHOLD = 2.2
ROTATION_DPS_THRESHOLD = 220.0
QUIET_G_MIN = 0.72
QUIET_G_MAX = 1.28
QUIET_GYRO_DPS_MAX = 35.0
QUIET_SAMPLES_REQUIRED = 6
CANDIDATE_TIMEOUT_SECONDS = 4.0
EVENT_COOLDOWN_SECONDS = 8.0

_lock = threading.RLock()
_devices: dict[str, dict[str, Any]] = {}
_events: deque[dict[str, Any]] = deque(maxlen=200)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()



def _finite_number(payload: dict, key: str) -> float:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a JSON number")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{key} must be finite")
    return value


def _new_state() -> dict[str, Any]:
    return {
        "last_sample_at": None,
        "accel_magnitude": None,
        "gyro_magnitude_dps": None,
        "candidate_started_monotonic": None,
        "quiet_samples": 0,
        "fall_pred": False,
        "fall_score": 0.0,
        "last_event_monotonic": 0.0,
        "last_event_at": None,
        "last_event_id": None,
        "samples_seen": 0,
        "prediction_source": "mpu_rule_based_prototype",
        "model_version": "threshold-sequence-v1",
    }


def process_sample(payload: dict) -> dict:
    """Update per-device motion state and return explicit prototype prediction fields."""
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    device_id = payload.get("device_id", "ESP32-MPU6050-01")
    if not isinstance(device_id, str) or not device_id.strip() or len(device_id) > 80:
        raise ValueError("device_id must be a non-empty string of at most 80 characters")

    ax, ay, az = (_finite_number(payload, k) for k in ("ax", "ay", "az"))
    gx, gy, gz = (_finite_number(payload, k) for k in ("gx", "gy", "gz"))
    accel_g = math.sqrt(ax * ax + ay * ay + az * az) / G
    gyro_dps = math.sqrt(gx * gx + gy * gy + gz * gz)
    now = time.monotonic()
    timestamp = _utc_now()

    with _lock:
        state = _devices.setdefault(device_id, _new_state())
        state["samples_seen"] += 1
        state["last_sample_at"] = timestamp
        state["accel_magnitude"] = round(accel_g * G, 4)
        state["gyro_magnitude_dps"] = round(gyro_dps, 3)

        impact = accel_g >= IMPACT_G_THRESHOLD
        rapid_rotation = gyro_dps >= ROTATION_DPS_THRESHOLD
        if impact or rapid_rotation:
            if state["candidate_started_monotonic"] is None:
                state["candidate_started_monotonic"] = now
                state["quiet_samples"] = 0
            # Impact/rotation is a candidate, not a confirmed fall.
            state["fall_pred"] = False
            state["fall_score"] = 0.35 if impact else 0.25

        candidate_at = state["candidate_started_monotonic"]
        if candidate_at is not None:
            age = now - candidate_at
            quiet = (QUIET_G_MIN <= accel_g <= QUIET_G_MAX and
                     gyro_dps <= QUIET_GYRO_DPS_MAX)
            state["quiet_samples"] = state["quiet_samples"] + 1 if quiet else 0

            if age > CANDIDATE_TIMEOUT_SECONDS:
                state["candidate_started_monotonic"] = None
                state["quiet_samples"] = 0
                state["fall_pred"] = False
                state["fall_score"] = 0.0
            elif age >= 0.25 and state["quiet_samples"] >= QUIET_SAMPLES_REQUIRED:
                state["fall_pred"] = True
                state["fall_score"] = 0.80  # heuristic score, not a probability
                if now - state["last_event_monotonic"] >= EVENT_COOLDOWN_SECONDS:
                    event = {
                        "event_id": f"mpu-{device_id}-{int(time.time() * 1000)}",
                        "event_type": "MPU_RULE_BASED_POTENTIAL_FALL",
                        "device_id": device_id,
                        "timestamp": timestamp,
                        "accel_magnitude_m_s2": round(accel_g * G, 4),
                        "gyro_magnitude_dps": round(gyro_dps, 3),
                        "score": 0.80,
                        "prediction_source": "mpu_rule_based_prototype",
                        "model_version": "threshold-sequence-v1",
                        "message": "Impact/rotation followed by low motion; check worker.",
                    }
                    _events.appendleft(event)
                    state["last_event_monotonic"] = now
                    state["last_event_at"] = timestamp
                    state["last_event_id"] = event["event_id"]
                # Keep latched for the status view, but clear candidate so one event
                # cannot fire repeatedly; cooldown protects subsequent events too.
                state["candidate_started_monotonic"] = None
                state["quiet_samples"] = 0
            elif not state["fall_pred"]:
                # Score describes rule evidence only, not statistical confidence.
                state["fall_score"] = 0.45 if (impact or rapid_rotation) else 0.0

        return {
            "device_id": device_id,
            "fall_pred": bool(state["fall_pred"]),
            "fall_probability": float(state["fall_score"]),
            "fall_score": float(state["fall_score"]),
            "prediction_source": state["prediction_source"],
            "model_version": state["model_version"],
            "prediction_timestamp": timestamp,
            "accel_magnitude_m_s2": state["accel_magnitude"],
            "gyro_magnitude_dps": state["gyro_magnitude_dps"],
            "samples_seen": state["samples_seen"],
            "rule_based_not_trained_model": True,
            "last_mpu_event_at": state["last_event_at"],
        }


def get_status(device_id: str | None = None) -> dict:
    """Return JSON-safe state for one device or all currently seen devices."""
    with _lock:
        if device_id:
            state = _devices.get(device_id)
            return {"device_id": device_id, "available": state is not None,
                    **(_public_state(state) if state else {})}
        return {"devices": {key: _public_state(value) for key, value in _devices.items()},
                "prediction_source": "mpu_rule_based_prototype",
                "model_version": "threshold-sequence-v1",
                "rule_based_not_trained_model": True}


def _public_state(state: dict) -> dict:
    keys = ("last_sample_at", "accel_magnitude", "gyro_magnitude_dps", "fall_pred",
            "fall_score", "last_event_at", "last_event_id", "samples_seen",
            "prediction_source", "model_version")
    return {key: state.get(key) for key in keys}


def get_events(limit: int = 50) -> list[dict]:
    """Return most recent MPU prototype events (separate from other event sources)."""
    try:
        limit = max(1, min(int(limit), 200))
    except (TypeError, ValueError):
        limit = 50
    with _lock:
        return list(_events)[:limit]
