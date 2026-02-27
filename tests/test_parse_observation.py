import pytest
from parse_observation import parse_observation

def test_parse_observation_success():
    # 正常系のテスト
    raw_data = {
        "temperature": 25.5,
        "humidity": 60,
        "timestamp": "2024-05-20T10:00:00Z"
    }
    station = "Tokyo"
    
    result = parse_observation(raw_data, station)
    
    assert result["station"] == "Tokyo"
    assert result["temperature"] == 25.5
    assert result["humidity"] == 60

def test_parse_observation_invalid_data():
    # データが不正（None）な場合のテスト
    raw_data = {
        "temperature": None,
        "humidity": "invalid",
        "timestamp": "2024-05-20T10:00:00Z"
    }
    result = parse_observation(raw_data, "Osaka")
    
    assert result["temperature"] is None
    assert result["humidity"] is None
