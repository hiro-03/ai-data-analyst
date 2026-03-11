import pytest
import sys
import os

# プロジェクトルートを基準に lambda/weather_observation_api を import パスに追加
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OBS_API_DIR = os.path.join(ROOT, "lambda", "weather_observation_api")
sys.path.append(OBS_API_DIR)

from parse_observation import parse_observation


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