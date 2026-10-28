"""
SENTROVA Demo Video Service
Separate from the live-camera server and main Flask backend.
- Upload a prerecorded video.
- Run YOLO pose inference and save an annotated MP4.
- Store demo-only warning events in this service's in-memory job record.
- Does NOT post demo events to backend/main.py or the live-camera event endpoint.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import cv2
from flask import Flask, jsonify, request, send_file, url_for
from flask_cors import CORS
from werkzeug.utils import secure_filename
from ultralytics import YOLO

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "demo_uploads"
OUTPUT_DIR = BASE_DIR / "demo_outputs"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

HOST = os.environ.get("DEMO_VIDEO_HOST", "127.0.0.1")
PORT = int(os.environ.get("DEMO_VIDEO_PORT", "5002"))
MAX_UPLOAD_BYTES = int(os.environ.get("DEMO_VIDEO_MAX_BYTES", str(200 * 1024 * 1024)))
ALLOWED_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".mpeg", ".mpg", ".m4v"}
MODEL_ENV = os.environ.get("YOLO_POSE_MODEL", "yolo11n-pose.pt")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
CORS(app, resources={r"/api/*": {"origins": "*"}, r"/health": {"origins": "*"}})

jobs: dict[str, dict] = {}
jobs_lock = threading.RLock()
processing_lock = threading.Lock()
model = None
model_error = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_model_path() -> Path | None:
    supplied = Path(MODEL_ENV)
    candidates = [supplied] if supplied.is_absolute() else [
        BASE_DIR / supplied,
        BASE_DIR.parent / supplied,
        Path.cwd() / supplied,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def load_model() -> None:
    global model, model_error
    path = resolve_model_path()
    if path is None:
        model_error = (
            f"Could not find {MODEL_ENV}. Put yolo11n-pose.pt in the backend folder "
            "or set YOLO_POSE_MODEL to its full path."
        )
        print(f"[demo-video] MODEL ERROR: {model_error}")
        return
    try:
        model = YOLO(str(path))
        model_error = None
        print(f"[demo-video] YOLO pose model loaded: {path}")
    except Exception as exc:
        model = None
        model_error = f"YOLO model load failed: {exc}"
        print(f"[demo-video] MODEL ERROR: {model_error}")


def update_job(job_id: str, **values) -> None:
    with jobs_lock:
        if job_id in jobs:
            jobs[job_id].update(values)


def public_job(job: dict) -> dict:
    keys = (
        "job_id", "filename", "state", "progress", "frame_count", "frames_processed",
        "fps", "duration_seconds", "error", "events", "warning_active",
        "started_at", "finished_at", "video_url", "model_name",
    )
    return {key: job.get(key) for key in keys}


def pose_warning(result) -> tuple[bool, float | None]:
    """
    Demonstration heuristic only: warning when shoulder-to-hip torso axis is
    close to horizontal. COCO keypoint indices: shoulders 5/6, hips 11/12.
    This is not a validated fall detector and can produce false positives.
    """
    try:
        keypoints = result.keypoints
        if keypoints is None or keypoints.xy is None:
            return False, None
        xy = keypoints.xy.cpu().numpy()
        conf = keypoints.conf.cpu().numpy() if keypoints.conf is not None else None
        for person_index, points in enumerate(xy):
            required = [5, 6, 11, 12]
            if any(index >= len(points) for index in required):
                continue
            if conf is not None:
                scores = conf[person_index]
                if any(float(scores[index]) < 0.35 for index in required):
                    continue
            shoulder_mid = (points[5] + points[6]) / 2.0
            hip_mid = (points[11] + points[12]) / 2.0
            dx = float(shoulder_mid[0] - hip_mid[0])
            dy = float(shoulder_mid[1] - hip_mid[1])
            if abs(dx) + abs(dy) < 1.0:
                continue
            angle_from_horizontal = abs(__import__("math").degrees(__import__("math").atan2(abs(dy), abs(dx))))
            if angle_from_horizontal <= 35.0:
                return True, round(angle_from_horizontal, 1)
        return False, None
    except Exception:
        return False, None


def process_video(job_id: str, source_path: Path, output_path: Path) -> None:
    # OpenCV writes a temporary MJPEG AVI; FFmpeg then converts it to browser-friendly H.264 MP4.
    intermediate_path = output_path.with_name(f"{output_path.stem}_temp.avi")
    if not processing_lock.acquire(blocking=False):
        update_job(job_id, state="error", error="Another demo video is currently processing.")
        return

    cap = None
    writer = None
    try:
        if model is None:
            raise RuntimeError(model_error or "YOLO pose model is unavailable.")

        cap = cv2.VideoCapture(str(source_path))
        if not cap.isOpened():
            raise RuntimeError("OpenCV could not open this video. Try a standard MP4 or AVI file.")

        fps = float(cap.get(cv2.CAP_PROP_FPS))
        if not (1.0 <= fps <= 120.0):
            fps = 25.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        if width < 2 or height < 2:
            raise RuntimeError("The uploaded file does not contain readable video frames.")

        duration = total_frames / fps if total_frames > 0 else None
        # MJPEG AVI is used as an intermediate because OpenCV Windows builds often
        # cannot encode H.264 directly. FFmpeg converts it to H.264 after annotation.
        fourcc = cv2.VideoWriter_fourcc(*"MJPG")
        writer = cv2.VideoWriter(str(intermediate_path), fourcc, fps, (width, height))
        if not writer.isOpened():
            raise RuntimeError("Could not create the temporary annotated AVI. Check that OpenCV video codecs are installed.")

        update_job(
            job_id, state="processing", fps=round(fps, 3), frame_count=total_frames,
            duration_seconds=round(duration, 3) if duration is not None else None,
            started_at=utc_now(), model_name=Path(MODEL_ENV).name,
        )

        frame_index = 0
        warning_active = False
        events = []
        last_status_update = time.monotonic()

        while True:
            ok, frame = cap.read()
            if not ok:
                break

            results = model.predict(frame, verbose=False, conf=0.35)
            result = results[0]
            annotated = result.plot()
            warning, torso_angle = pose_warning(result)

            if warning and not warning_active:
                events.append({
                    "event_id": f"{job_id}-evt-{len(events)+1}",
                    "event_type": "DEMO_POTENTIAL_FALL",
                    "clip_time_seconds": round(frame_index / fps, 3),
                    "frame_index": frame_index,
                    "timestamp": utc_now(),
                    "message": "Pose heuristic reports a near-horizontal torso in the demo clip.",
                    "details": {"torso_angle_from_horizontal_deg": torso_angle},
                    "source": "uploaded_demo_video",
                })
            elif warning_active and not warning:
                events.append({
                    "event_id": f"{job_id}-evt-{len(events)+1}",
                    "event_type": "DEMO_WARNING_CLEARED",
                    "clip_time_seconds": round(frame_index / fps, 3),
                    "frame_index": frame_index,
                    "timestamp": utc_now(),
                    "message": "Pose heuristic no longer reports a near-horizontal torso.",
                    "details": {},
                    "source": "uploaded_demo_video",
                })
            warning_active = warning
            writer.write(annotated)
            frame_index += 1

            if time.monotonic() - last_status_update >= 0.25:
                progress = min(99, int(frame_index * 100 / total_frames)) if total_frames > 0 else 0
                update_job(
                    job_id, progress=progress, frames_processed=frame_index,
                    events=list(events), warning_active=warning_active,
                )
                last_status_update = time.monotonic()

        writer.release()
        writer = None
        cap.release()
        cap = None

        if frame_index == 0 or not intermediate_path.exists() or intermediate_path.stat().st_size == 0:
            raise RuntimeError("No video frames were processed. Try another video file.")

        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError(
                "FFmpeg was not found. Install FFmpeg and add its bin folder to Windows PATH, "
                "then restart the SENTROVA demo-video service. The annotated frames were created, "
                "but the browser-compatible H.264 MP4 could not be generated."
            )

        command = [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(intermediate_path),
            "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(output_path),
        ]
        conversion = subprocess.run(command, capture_output=True, text=True, timeout=600)
        if conversion.returncode != 0 or not output_path.is_file() or output_path.stat().st_size == 0:
            detail = (conversion.stderr or "FFmpeg did not produce an output file.").strip()
            raise RuntimeError(f"H.264 MP4 conversion failed: {detail[-1200:]}")
        intermediate_path.unlink(missing_ok=True)

        update_job(
            job_id, state="completed", progress=100, frames_processed=frame_index,
            events=list(events), warning_active=warning_active, finished_at=utc_now(),
            video_url=f"/api/demo/video/{job_id}",
        )
        print(f"[demo-video] Job {job_id} completed: {frame_index} frames, {len(events)} demo events")
    except Exception as exc:
        update_job(job_id, state="error", error=str(exc), finished_at=utc_now())
        print(f"[demo-video] Job {job_id} failed: {exc}")
    finally:
        if writer is not None:
            writer.release()
        if cap is not None:
            cap.release()
        # Keep no temporary AVI after a failed/successful processing attempt.
        try:
            intermediate_path.unlink(missing_ok=True)
        except Exception:
            pass
        processing_lock.release()


@app.errorhandler(413)
def upload_too_large(_error):
    return jsonify({"error": f"Video is too large. Maximum upload size is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."}), 413


@app.get("/health")
def health():
    return jsonify({
        "service": "sentrova-demo-video",
        "status": "ok",
        "model_loaded": model is not None,
        "model_error": model_error,
        "ffmpeg_available": shutil.which("ffmpeg") is not None,
        "active_job": next((j["job_id"] for j in jobs.values() if j.get("state") in {"queued", "processing"}), None),
        "timestamp": utc_now(),
    })


@app.post("/api/demo/upload")
def upload_demo():
    if model is None:
        return jsonify({"error": model_error or "YOLO model is not available."}), 503
    if not processing_lock.acquire(blocking=False):
        return jsonify({"error": "A demo video is already processing. Wait for it to finish before uploading another."}), 409
    processing_lock.release()

    uploaded = request.files.get("video")
    if uploaded is None or not uploaded.filename:
        return jsonify({"error": "Choose a video file first."}), 400
    safe_name = secure_filename(uploaded.filename)
    extension = Path(safe_name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        return jsonify({"error": "Unsupported video type. Use MP4, AVI, MOV, MKV, MPEG, MPG, or M4V."}), 415

    job_id = uuid.uuid4().hex[:12]
    source_path = UPLOAD_DIR / f"{job_id}_{safe_name}"
    output_path = OUTPUT_DIR / f"{job_id}_annotated.mp4"
    uploaded.save(source_path)

    cap = cv2.VideoCapture(str(source_path))
    readable = cap.isOpened()
    ok, _frame = cap.read() if readable else (False, None)
    cap.release()
    if not readable or not ok:
        source_path.unlink(missing_ok=True)
        return jsonify({"error": "The uploaded file could not be decoded as video. Try a standard MP4 or AVI."}), 400

    job = {
        "job_id": job_id, "filename": safe_name, "state": "queued", "progress": 0,
        "frame_count": 0, "frames_processed": 0, "fps": None, "duration_seconds": None,
        "error": None, "events": [], "warning_active": False, "started_at": None,
        "finished_at": None, "video_url": None, "model_name": Path(MODEL_ENV).name,
    }
    with jobs_lock:
        jobs[job_id] = job

    thread = threading.Thread(
        target=process_video, args=(job_id, source_path, output_path),
        name=f"demo-video-{job_id}", daemon=True,
    )
    thread.start()
    return jsonify({"job_id": job_id, "state": "queued", "filename": safe_name}), 202


@app.get("/api/demo/status/<job_id>")
def demo_status(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
        if job is None:
            return jsonify({"error": "Demo job not found. It may have expired after a server restart."}), 404
        return jsonify(public_job(job))


@app.get("/api/demo/video/<job_id>")
def demo_video(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
        if job is None:
            return jsonify({"error": "Demo job not found."}), 404
        if job.get("state") != "completed":
            return jsonify({"error": "Annotated video is not ready yet."}), 409
    output_path = OUTPUT_DIR / f"{job_id}_annotated.mp4"
    if not output_path.is_file():
        return jsonify({"error": "Annotated video file is missing."}), 404
    response = send_file(output_path, mimetype="video/mp4", conditional=True, download_name=f"sentrova_demo_{job_id}.mp4")
    response.headers["Cache-Control"] = "no-store"
    return response


if __name__ == "__main__":
    load_model()
    print(f"[demo-video] Starting at http://{HOST}:{PORT}")
    print(f"[demo-video] Upload limit: {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    print(f"[demo-video] FFmpeg available: {shutil.which('ffmpeg') is not None}")
    app.run(host=HOST, port=PORT, threaded=True, debug=False)
