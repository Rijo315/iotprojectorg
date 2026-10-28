
import json
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import cv2
from flask import Flask, Response, jsonify
from ultralytics import YOLO


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

CAMERA_URL = "http://10.42.6.132:8080/video"
MODEL_NAME = "yolo11n-pose.pt"

HOST = "127.0.0.1"
PORT = 5001

BACKEND_EVENT_URL = "http://127.0.0.1:5000/api/camera-event"

WARNING_DURATION_SECONDS = 3.0
BACKEND_RETRY_SECONDS = 2.0
CAMERA_RECONNECT_SECONDS = 2.0
FRAME_READ_TIMEOUT_MS = 5000


# --------------------------------------------------
# APPLICATION STATE
# --------------------------------------------------

app = Flask(__name__)

latest_jpeg = None
frame_lock = threading.Lock()

camera_status = {
    "connected": False,
    "error": None,
    "fall_warning": False,
    "backend_connected": None,
    "backend_error": None,
    "model_loaded": False,
}

stop_event = threading.Event()


# --------------------------------------------------
# CAMERA CONNECTION
# --------------------------------------------------

def open_camera():
    """Open the phone camera stream using FFmpeg."""

    print("Opening phone camera stream...")

    try:
        cap = cv2.VideoCapture(CAMERA_URL, cv2.CAP_FFMPEG)

        if not cap.isOpened():
            cap.release()
            return None

        # These properties are supported by recent OpenCV versions.
        # Some builds may ignore them; the read loop still handles errors.
        cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, FRAME_READ_TIMEOUT_MS)

        # Verify that the connection can deliver an actual frame.
        ok, frame = cap.read()

        if not ok or frame is None:
            cap.release()
            return None

        print(f"Camera frame received: {frame.shape}")
        return cap

    except Exception as exc:
        print(f"Camera connection error: {exc}")
        return None


# --------------------------------------------------
# BACKEND EVENT REPORTING
# --------------------------------------------------

def report_warning_to_backend(active):
    """Send warning state changes to the Flask backend."""

    payload = {
        "active": active,
        "message": (
            "Person pose appears horizontal; check the person."
            if active
            else "The camera pose heuristic warning is no longer active."
        ),
    }

    request = Request(
        BACKEND_EVENT_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=2.0) as response:
            if not 200 <= response.status < 300:
                raise RuntimeError(
                    f"Backend returned HTTP {response.status}"
                )

        camera_status["backend_connected"] = True
        camera_status["backend_error"] = None

        print(f"Backend warning update successful: active={active}")
        return True

    except (HTTPError, URLError, TimeoutError, OSError, RuntimeError) as exc:
        camera_status["backend_connected"] = False
        camera_status["backend_error"] = str(exc)

        print(f"Could not report camera warning: {exc}")
        return False


# --------------------------------------------------
# POSE-BASED WARNING HEURISTIC
# --------------------------------------------------

def detect_pose_warning(result):
    """
    Preliminary heuristic, NOT a validated fall detector.

    Checks whether the shoulder-to-hip line is more horizontal
    than vertical. Other postures can trigger this heuristic.
    """

    keypoints = result.keypoints

    if keypoints is None or len(keypoints.xy) == 0:
        return False

    points = keypoints.xy[0].cpu().numpy()

    # COCO pose indices:
    # shoulders 5 and 6; hips 11 and 12.
    if len(points) < 13:
        return False

    shoulder = (points[5] + points[6]) / 2
    hip = (points[11] + points[12]) / 2

    torso_dx = abs(float(hip[0] - shoulder[0]))
    torso_dy = abs(float(hip[1] - shoulder[1]))

    return torso_dx > 1 and torso_dx > torso_dy * 1.5


# --------------------------------------------------
# CAMERA WORKER
# --------------------------------------------------

def camera_worker():
    global latest_jpeg

    print("Loading YOLO pose model...")

    try:
        model = YOLO(MODEL_NAME)
        camera_status["model_loaded"] = True
        print("YOLO pose model loaded.")

    except Exception as exc:
        camera_status["error"] = f"Model loading failed: {exc}"
        camera_status["model_loaded"] = False
        print(camera_status["error"])
        return

    warning_until = 0.0

    # None means the initial warning state has not yet been reported.
    last_reported_warning = None
    last_backend_attempt = 0.0

    cap = None

    try:
        while not stop_event.is_set():

            # Open or reconnect to the camera.
            if cap is None or not cap.isOpened():
                camera_status["connected"] = False

                if cap is not None:
                    cap.release()
                    cap = None

                cap = open_camera()

                if cap is None:
                    camera_status["error"] = (
                        "Could not read phone camera stream; retrying."
                    )
                    time.sleep(CAMERA_RECONNECT_SECONDS)
                    continue

                camera_status["connected"] = True
                camera_status["error"] = None
                print("Camera connected.")

            ok, frame = cap.read()

            if not ok or frame is None:
                camera_status["connected"] = False
                camera_status["error"] = (
                    "Camera frame read failed; reconnecting."
                )
                print(camera_status["error"])

                cap.release()
                cap = None

                time.sleep(CAMERA_RECONNECT_SECONDS)
                continue

            camera_status["connected"] = True
            camera_status["error"] = None

            try:
                results = model.predict(
                    frame,
                    imgsz=320,
                    conf=0.35,
                    verbose=False,
                )

                result = results[0]
                annotated = result.plot()

                fall_candidate = detect_pose_warning(result)

                if fall_candidate:
                    warning_until = (
                        time.time() + WARNING_DURATION_SECONDS
                    )

                warning = time.time() < warning_until
                camera_status["fall_warning"] = warning

                if warning:
                    cv2.putText(
                        annotated,
                        "POTENTIAL FALL - CHECK PERSON",
                        (10, 35),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.7,
                        (0, 0, 255),
                        2,
                    )

            except Exception as exc:
                annotated = frame
                warning = camera_status["fall_warning"]
                camera_status["error"] = (
                    f"Pose inference error: {exc}"
                )
                print(camera_status["error"])

            # Report only state transitions. If the backend is offline,
            # retry at most once every BACKEND_RETRY_SECONDS.
            now = time.time()

            if (
                last_reported_warning is None
                or warning != last_reported_warning
            ):
                if now - last_backend_attempt >= BACKEND_RETRY_SECONDS:
                    last_backend_attempt = now

                    if report_warning_to_backend(warning):
                        last_reported_warning = warning

            # Publish the annotated frame for the React dashboard.
            encoded_ok, encoded = cv2.imencode(
                ".jpg",
                annotated,
                [cv2.IMWRITE_JPEG_QUALITY, 80],
            )

            if encoded_ok:
                with frame_lock:
                    latest_jpeg = encoded.tobytes()

            # Optional local preview window.
            cv2.imshow("SENTROVA Shared Camera", annotated)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                stop_event.set()
                break

    except Exception as exc:
        camera_status["error"] = f"Camera worker error: {exc}"
        print(camera_status["error"])

    finally:
        if cap is not None:
            cap.release()

        camera_status["connected"] = False
        camera_status["fall_warning"] = False

        cv2.destroyAllWindows()
        print("Camera worker stopped.")


# --------------------------------------------------
# HEALTH ENDPOINT
# --------------------------------------------------

@app.get("/health")
def health():
    return jsonify(camera_status)


# --------------------------------------------------
# SHARED MJPEG VIDEO STREAM
# --------------------------------------------------

def generate_frames():
    while not stop_event.is_set():

        with frame_lock:
            frame = latest_jpeg

        if frame is None:
            time.sleep(0.05)
            continue

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n"
            + frame
            + b"\r\n"
        )

        time.sleep(0.02)


@app.get("/video_feed")
def video_feed():
    return Response(
        generate_frames(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


# --------------------------------------------------
# START SERVER
# --------------------------------------------------

if __name__ == "__main__":
    worker = threading.Thread(
        target=camera_worker,
        daemon=True,
    )
    worker.start()

    try:
        app.run(
            host=HOST,
            port=PORT,
            threaded=True,
            use_reloader=False,
        )
    finally:
        stop_event.set()
