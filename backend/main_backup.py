
import csv
import json
import math
import threading
from datetime import datetime, timezone
from mpu_fall_inference import process_sample, get_status as get_mpu_fall_status, get_events as get_mpu_fall_events
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

CSV_FIELDS = [
    "timestamp", "device_id",
    "ax", "ay", "az",
    "gx", "gy", "gz",
    "fall_probability", "prediction_source",
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
            csv.DictWriter(f, fieldnames=CSV_FIELDS).writeheader()


ensure_csv()

if not EVENTS_PATH.exists():
    save_events([])


def sensor_status():
    
    age = None
    if last_update is not None:
        age = max(
            0.0,
            (datetime.now(timezone.utc) - last_update).total_seconds()
        )

    connected = age is not None and age <= SENSOR_STALE_SECONDS

    return {
        "sensor_connected": connected,
        "seconds_since_update": round(age, 2) if age is not None else None,
        "data_stale": not connected,
        "latest_sensor": latest_sensor,
        "fall_threshold": FALL_THRESHOLD,
        "sos_active": sos_active,
        "camera_warning_active": camera_warning_active,
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
        return jsonify({"error": "Expected a JSON object"}), 400

    device_id = payload.get("device_id")
    if not isinstance(device_id, str) or not device_id.strip():
        return jsonify({"error": "device_id must be a non-empty string"}), 400

    numeric_fields = ["ax", "ay", "az", "gx", "gy", "gz"]
    values = {}

    for field in numeric_fields:
        value = payload.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return jsonify({"error": f"{field} must be numeric"}), 400
        if not math.isfinite(value):
            return jsonify({"error": f"{field} must be finite"}), 400
        values[field] = float(value)

    probability = payload.get("fall_probability")
    if probability is not None:
        if (
            isinstance(probability, bool)
            or not isinstance(probability, (int, float))
            or not math.isfinite(probability)
            or not 0 <= probability <= 1
        ):
            return jsonify({
                "error": "fall_probability must be between 0 and 1"
            }), 400
        probability = float(probability)

    source = payload.get("prediction_source", "unknown")
    version = payload.get("model_version", "unknown")

    if not isinstance(source, str) or not isinstance(version, str):
        return jsonify({
            "error": "prediction_source and model_version must be strings"
        }), 400

    record = {
        "timestamp": utc_now(),
        "device_id": device_id.strip(),
        **values,
        "fall_probability": probability,
        "prediction_source": source,
        "model_version": version,
    }

    with lock:
        latest_sensor = record
        last_update = datetime.now(timezone.utc)

        with CSV_PATH.open("a", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=CSV_FIELDS).writerow(record)

    return jsonify({
        "message": "Sensor data received",
        "sensor": record,
    }), 201


@app.get("/api/events")
def get_events():
    return jsonify({"events": load_events()})


@app.post("/api/sos")
def trigger_sos():
    global sos_active

    payload = request.get_json(silent=True) or {}
    active = payload.get("active", True)

    if not isinstance(active, bool):
        return jsonify({"error": "active must be true or false"}), 400

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
        return jsonify({"error": "Expected a JSON object"}), 400

    active = payload.get("active")
    if not isinstance(active, bool):
        return jsonify({"error": "active must be true or false"}), 400

    message = payload.get("message", "Camera pose heuristic warning")
    if not isinstance(message, str) or len(message) > 300:
        return jsonify({"error": "message must be a string of at most 300 characters"}), 400

    with lock:
        event = None

        # Record only state transitions, not every video frame.
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
                        "message": "The camera heuristic warning is no longer active.",
                        "confirmed_accident": False,
                    },
                )

    return jsonify({
        "camera_warning_active": camera_warning_active,
        "event": event,
        "message": "Camera warning state processed",
    })



if __name__ == "__main__":
    app.run(host=HOST, port=PORT, debug=False)
