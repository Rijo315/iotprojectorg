
import csv
import json
import math

import pytest

import main


@pytest.fixture
def client(tmp_path, monkeypatch):
    csv_path = tmp_path / "sensor_log.csv"
    events_path = tmp_path / "events.json"

    monkeypatch.setattr(main, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main, "CSV_PATH", csv_path)
    monkeypatch.setattr(main, "EVENTS_PATH", events_path)
    monkeypatch.setattr(main, "SENSOR_STALE_SECONDS", 5.0)
    monkeypatch.setattr(main, "FALL_THRESHOLD", 0.75)

    with csv_path.open("w", newline="", encoding="utf-8") as file:
        csv.DictWriter(file, fieldnames=main.CSV_FIELDS).writeheader()

    events_path.write_text("[]", encoding="utf-8")

    with main.lock:
        main.latest_sensor = None
        main.last_update = None
        main.sos_active = False

    main.app.config.update(TESTING=True)

    yield main.app.test_client()

    with main.lock:
        main.latest_sensor = None
        main.last_update = None
        main.sos_active = False


def valid_payload(**overrides):
    payload = {
        "device_id": "ESP32-TEST",
        "ax": 0.1,
        "ay": 0.2,
        "az": 9.7,
        "gx": 0.01,
        "gy": 0.02,
        "gz": 0.03,
    }
    payload.update(overrides)
    return payload


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"


def test_root(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "service" in response.get_json()


def test_status_initially_has_no_fresh_sensor(client):
    response = client.get("/api/status")
    data = response.get_json()
    assert response.status_code == 200
    assert data["sensor_connected"] is False
    assert data["data_stale"] is True
    assert data["latest_sensor"] is None


def test_accepts_valid_sensor_payload_and_logs_csv(client):
    response = client.post("/sensor", json=valid_payload())
    assert response.status_code == 201

    data = response.get_json()["sensor"]
    assert data["device_id"] == "ESP32-TEST"
    assert math.isclose(data["az"], 9.7)
    assert data["fall_probability"] is None

    with main.CSV_PATH.open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))

    assert len(rows) == 1
    assert rows[0]["device_id"] == "ESP32-TEST"


def test_valid_sensor_updates_status(client):
    client.post("/sensor", json=valid_payload())
    data = client.get("/api/status").get_json()

    assert data["sensor_connected"] is True
    assert data["data_stale"] is False
    assert data["latest_sensor"]["device_id"] == "ESP32-TEST"


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {"device_id": "ESP32-TEST"},
        valid_payload(device_id=""),
        valid_payload(ax="0.1"),
        valid_payload(ay=True),
        valid_payload(gz=float("nan")),
        valid_payload(gx=float("inf")),
        valid_payload(fall_probability=1.2),
        valid_payload(fall_probability=-0.1),
        valid_payload(fall_probability=True),
        valid_payload(prediction_source=123),
    ],
)
def test_rejects_invalid_sensor_payloads(client, payload):
    response = client.post("/sensor", json=payload)
    assert response.status_code == 400


def test_accepts_probability_in_range(client):
    response = client.post(
        "/sensor",
        json=valid_payload(
            fall_probability=0.42,
            prediction_source="test",
            model_version="demo",
        ),
    )
    assert response.status_code == 201
    data = response.get_json()["sensor"]
    assert data["fall_probability"] == 0.42
    assert data["prediction_source"] == "test"


def test_sos_activation_and_clear_are_persisted(client):
    activated = client.post("/api/sos", json={"active": True})
    assert activated.status_code == 200
    assert activated.get_json()["sos_active"] is True

    cleared = client.post("/api/sos", json={"active": False})
    assert cleared.status_code == 200
    assert cleared.get_json()["sos_active"] is False

    events = client.get("/api/events").get_json()["events"]
    assert [event["event_type"] for event in events] == [
        "SOS_ACTIVE",
        "SOS_CLEARED",
    ]

    saved = json.loads(main.EVENTS_PATH.read_text(encoding="utf-8"))
    assert len(saved) == 2


def test_repeated_sos_state_does_not_duplicate_event(client):
    client.post("/api/sos", json={"active": True})
    client.post("/api/sos", json={"active": True})

    events = client.get("/api/events").get_json()["events"]
    assert len(events) == 1


def test_rejects_non_boolean_sos_state(client):
    response = client.post("/api/sos", json={"active": "yes"})
    assert response.status_code == 400


def test_event_list_is_initially_empty(client):
    response = client.get("/api/events")
    assert response.status_code == 200
    assert response.get_json()["events"] == []
