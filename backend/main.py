
import csv
import json
import math
import threading
from datetime import datetime, timezone

from mpu_fall_inference import (
    process_sample,
    get_status as get_mpu_fall_status,
    get_events as get_mpu_fall_events,
)
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS

load_dotenv()

from config import (
    BASE_DIR,
    DATA_DIR,
    HOST,
    PORT,
    SENSOR_STALE_SECONDS,
    FALL_THRESHOLD,
    CSV_PATH,
    EVENTS_PATH,
)

app = Flask(__name__)
CORS(app)

DATA_DIR.mkdir(parents=True, exist_ok=True)

# Preserve the existing CSV schema so previously logged data remains compatible.
CSV_FIELDS = [
    "timestamp",
    "device_id",
    "ax", "ay", "az",
    "gx", "gy", "gz",
    "fall_probability",
    "prediction_source",
    "model_version",
]

lock = threading.Lock()

latest_sensor = None
last_update = None
sos_active = False
camera_warning_active = False


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def load_events():
    if not EVENTS_PATH.exists():
        return []

    try:
        with EVENTS_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)

        return data if isinstance(data, list) else []

    except (json.JSONDecodeError, OSError):
        return []


def save_events(events):
    temp_path = EVENTS_PATH.with_suffix(".tmp")

    with temp_path.open("w", encoding="utf-8") as f:
        json.dump(events, f, indent=2)

    temp_path.replace(EVENTS_PATH)


def record_event(event_type, details=None):
    events = load_events()

    event = {
        "event_id": len(events) + 1,
        "timestamp": utc_now(),
        "event_type": event_type,
        "details": details or {},
    }

    events.append(event)
    save_events(events)

    return event


def ensure_csv():
    if not CSV_PATH.exists() or CSV_PATH.stat().st_size == 0:
        with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
            csv.DictWriter(
                f,
                fieldnames=CSV_FIELDS,
            ).writeheader()


ensure_csv()

if not EVENTS_PATH.exists():
    save_events([])


def sensor_status():
    age = None

    if last_update is not None:
        age = max(
            0.0,
            (
                datetime.now(timezone.utc) - last_update
            ).total_seconds(),
        )

    connected = (
        age is not None
        and age <= SENSOR_STALE_SECONDS
    )

    return {
        "sensor_connected": connected,
        "seconds_since_update": (
            round(age, 2) if age is not None else None
        ),
        "data_stale": not connected,
        "latest_sensor": latest_sensor,
        "fall_threshold": FALL_THRESHOLD,
        "sos_active": sos_active,
        "camera_warning_active": camera_warning_active,

        # Separate MPU6050 inference diagnostics and events.
        "mpu_fall_status": get_mpu_fall_status(),
        "mpu_fall_events": get_mpu_fall_events(limit=10),

        "inference_type": "rule_based_prototype",
        "trained_model_available": False,
    }


@app.get("/")
def index():
    return jsonify({
        "service": "Industrial Worker Accident Detection API",
        "version": "1.0.0",
        "message": "Backend is running",
    })


@app.get("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "service": "worker-monitor-backend",
        "version": "1.0.0",
        "timestamp": utc_now(),
    })


@app.get("/api/status")
def status():
    with lock:
        return jsonify(sensor_status())


@app.post("/sensor")
def receive_sensor():
    global latest_sensor, last_update

    payload = request.get_json(silent=True)

    if not isinstance(payload, dict):
        return jsonify({
            "error": "Expected a JSON object"
        }), 400

    device_id = payload.get("device_id")

    if (
        not isinstance(device_id, str)
        or not device_id.strip()
        or len(device_id) > 80
    ):
        return jsonify({
            "error": "device_id must be a non-empty string of at most 80 characters"
        }), 400

    # Validate all six measurements before running inference.
    numeric_fields = ["ax", "ay", "az", "gx", "gy", "gz"]
    values = {}

    for field in numeric_fields:
        value = payload.get(field)

        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return jsonify({
                "error": f"{field} must be numeric"
            }), 400

        if not math.isfinite(value):
            return jsonify({
                "error": f"{field} must be finite"
            }), 400

        values[field] = float(value)

    # Run inference on the Flask backend.
    # Client-supplied fall_probability, fall_pred, prediction_source,
    # and model_version are deliberately not trusted.
    try:
        prediction = process_sample({
            "device_id": device_id.strip(),
            **values,
        })
    except ValueError as exc:
        return jsonify({
            "error": f"MPU6050 inference input error: {exc}"
        }), 400

    # Keep the current CSV fields and add richer fields to the API response.
    record = {
        "timestamp": utc_now(),
        "device_id": device_id.strip(),
        **values,

        "fall_probability": prediction["fall_probability"],
        "fall_pred": prediction["fall_pred"],
        "fall_score": prediction["fall_score"],
        "prediction_source": prediction["prediction_source"],
        "model_version": prediction["model_version"],
        "prediction_timestamp": prediction["prediction_timestamp"],
        "accel_magnitude_m_s2": prediction["accel_magnitude_m_s2"],
        "gyro_magnitude_dps": prediction["gyro_magnitude_dps"],
        "samples_seen": prediction["samples_seen"],
        "rule_based_not_trained_model": True,
    }

    with lock:
        latest_sensor = record
        last_update = datetime.now(timezone.utc)

        # Write only fields present in the existing CSV schema.
        # This prevents extra API fields from breaking DictWriter.
        csv_record = {
            field: record.get(field)
            for field in CSV_FIELDS
        }

        with CSV_PATH.open(
            "a",
            newline="",
            encoding="utf-8",
        ) as f:
            csv.DictWriter(
                f,
                fieldnames=CSV_FIELDS,
            ).writerow(csv_record)

    return jsonify({
        "message": "Sensor data received",
        "sensor": record,
        "inference": {
            "fall_pred": prediction["fall_pred"],
            "fall_probability": prediction["fall_probability"],
            "fall_score": prediction["fall_score"],
            "prediction_source": prediction["prediction_source"],
            "model_version": prediction["model_version"],
            "prediction_timestamp": prediction["prediction_timestamp"],
            "rule_based_not_trained_model": True,
        },
    }), 201


@app.get("/api/events")
def get_events():
    # Preserve the existing persistent event history.
    # MPU inference events are exposed separately in /api/status.
    return jsonify({
        "events": load_events()
    })


@app.post("/api/sos")
def trigger_sos():
    global sos_active

    payload = request.get_json(silent=True)

    if payload is None:
        payload = {}

    if not isinstance(payload, dict):
        return jsonify({
            "error": "Expected a JSON object"
        }), 400

    active = payload.get("active", True)

    if not isinstance(active, bool):
        return jsonify({
            "error": "active must be true or false"
        }), 400

    with lock:
        if active != sos_active:
            sos_active = active

            event = record_event(
                "SOS_ACTIVE" if active else "SOS_CLEARED",
                {"source": "dashboard"},
            )
        else:
            event = None

    return jsonify({
        "sos_active": sos_active,
        "event": event,
        "message": "Software SOS state updated",
    })


@app.post("/api/camera-event")
def camera_event():
    global camera_warning_active

    payload = request.get_json(silent=True)

    if not isinstance(payload, dict):
        return jsonify({
            "error": "Expected a JSON object"
        }), 400

    active = payload.get("active")

    if not isinstance(active, bool):
        return jsonify({
            "error": "active must be true or false"
        }), 400

    message = payload.get(
        "message",
        "Camera pose heuristic warning",
    )

    if not isinstance(message, str) or len(message) > 300:
        return jsonify({
            "error": "message must be a string of at most 300 characters"
        }), 400

    with lock:
        event = None

        # Record only transitions, not every video frame.
        if active != camera_warning_active:
            camera_warning_active = active

            if active:
                event = record_event(
                    "POTENTIAL_FALL_CAMERA",
                    {
                        "source": "camera_pose_heuristic",
                        "message": message,
                        "confirmed_accident": False,
                    },
                )
            else:
                event = record_event(
                    "CAMERA_WARNING_CLEARED",
                    {
                        "source": "camera_pose_heuristic",
                        "message": (
                            "The camera heuristic warning is no longer active."
                        ),
                        "confirmed_accident": False,
                    },
                )

    return jsonify({
        "camera_warning_active": camera_warning_active,
        "event": event,
        "message": "Camera warning state processed",
    })


if __name__ == "__main__":
    app.run(
        host=HOST,
        port=PORT,
        debug=False,
    )
