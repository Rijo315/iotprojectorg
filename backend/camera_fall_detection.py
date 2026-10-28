
import os
import time
import cv2
from ultralytics import YOLO

# Replace this with your Android IP Webcam stream URL
CAMERA_URL = "http://10.23.28.163:8080/video"

# YOLO pose model: detects people and estimates body keypoints
MODEL_NAME = "yolo11n-pose.pt"

CONFIDENCE = 0.45
ALERT_HOLD_SECONDS = 3

def main():
    print("Loading pose model...")
    model = YOLO(MODEL_NAME)

    print("Connecting to phone camera...")
    cap = cv2.VideoCapture(CAMERA_URL)

    if not cap.isOpened():
        print("ERROR: Cannot open camera stream.")
        print("Check the phone IP, port, and /video URL.")
        return

    print("Camera connected. Press Q in the video window to quit.")

    lying_since = None
    alert_active = False

    try:
        while True:
            ok, frame = cap.read()

            if not ok:
                print("Camera frame unavailable; retrying...")
                time.sleep(1)
                continue

            results = model.predict(
                frame,
                conf=CONFIDENCE,
                imgsz=640,
                verbose=False
            )

            person_lying = False

            for result in results:
                if result.keypoints is None:
                    continue

                keypoints = result.keypoints.xy.cpu().numpy()

                for person in keypoints:
                    # COCO pose indices: shoulders 5,6; hips 11,12
                    if len(person) < 13:
                        continue

                    shoulder_y = (person[5][1] + person[6][1]) / 2
                    hip_y = (person[11][1] + person[12][1]) / 2

                    # Bounding-box posture approximation.
                    # This is a rough heuristic, not a validated fall classifier.
                    box = result.boxes
                    if box is None or len(box) == 0:
                        continue

                    # Match person keypoints to a person box by index.
                    idx = list(keypoints).index(person) if False else None

                    # Use torso direction as a rough cue.
                    shoulder_x = (person[5][0] + person[6][0]) / 2
                    hip_x = (person[11][0] + person[12][0]) / 2
                    torso_dx = abs(hip_x - shoulder_x)
                    torso_dy = abs(hip_y - shoulder_y)

                    if torso_dx > torso_dy * 1.2:
                        person_lying = True

            now = time.time()

            if person_lying:
                if lying_since is None:
                    lying_since = now

                if now - lying_since >= ALERT_HOLD_SECONDS:
                    if not alert_active:
                        print("POTENTIAL FALL: horizontal posture persisted.")
                        alert_active = True
                    cv2.putText(
                        frame,
                        "POTENTIAL FALL - CHECK PERSON",
                        (20, 40),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.8,
                        (0, 0, 255),
                        2
                    )
            else:
                lying_since = None
                alert_active = False

            annotated = results[0].plot()
            cv2.imshow("Camera Fall Detection - Prototype", annotated)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    finally:
        cap.release()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
