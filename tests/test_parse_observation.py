import pytest # type: ignore
import sys
import os
import json

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDA_DIR = os.path.join(ROOT, "lambda")
sys.path.append(LAMBDA_DIR)

from lambdas.weather_observation_api.parse_observation import parse_observation


def test_parse_observation_success():
    raw_data = {
        "temperature": 25.5,
        "humidity": 60,
        "timestamp": "2024-05-20T10:00:00Z"
    }

    station_id = "Tokyo"

    result = parse_observation(raw_data, station_id)

    assert result["station_id"] == "Tokyo"
    assert result["temperature"] == 25.5
    assert result["humidity"] == 60
    assert result["timestamp"] == "2024-05-20T10:00:00Z"
    assert result["error"] is None


def test_parse_observation_invalid_data():
    raw_data = {
        "temperature": None,
        "humidity": "invalid",
        "timestamp": "2024-05-20T10:00:00Z"
    }

    result = parse_observation(raw_data, "Osaka")

    assert result["station_id"] == "Osaka"
    assert result["temperature"] is None
    assert result["humidity"] is None
    assert result["timestamp"] == "2024-05-20T10:00:00Z"
    assert result["error"] is None

def test_parse_event_v2_preprocess(monkeypatch):
    from lambda_function import preprocess
    event = {"version": "2.0", "body": json.dumps({"lat": 35.7, "lon": 139.7})}
    assert preprocess(event) == {"lat": 35.7, "lon": 139.7}