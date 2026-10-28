
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "5000"))

SENSOR_STALE_SECONDS = float(
    os.getenv("SENSOR_STALE_SECONDS", "5")
)
FALL_THRESHOLD = float(os.getenv("FALL_THRESHOLD", "0.75"))

CSV_PATH = DATA_DIR / "sensor_log.csv"
EVENTS_PATH = DATA_DIR / "events.json"
