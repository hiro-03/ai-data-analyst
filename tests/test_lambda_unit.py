import json
import pytest

# lambda_function モジュールのシンボルを直接モックする
import lambda_function as L

def test_preprocess_valid():
    payload = L.preprocess({"body": json.dumps({"lat": 35.7, "lon": 139.7})})
    assert payload == {"lat": 35.7, "lon": 139.7}

def test_preprocess_invalid_json():
    with pytest.raises(ValueError):
        L.preprocess({"body": "not-a-json"})

def test_infer_success(monkeypatch):
    # lambda_function 内で参照されている load_station_master をモック
    monkeypatch.setattr(L, "load_station_master", lambda table_name=None: [
        {"station_id": "TEST001", "latitude": 35.7, "longitude": 139.7}
    ])
    # observation_repository.save_observation をモックして副作用を抑える
    import observation_repository
    monkeypatch.setattr(observation_repository, "save_observation", lambda *a, **k: None)

    result = L.infer({"lat": 35.7, "lon": 139.7})
    assert result["station_id"] == "TEST001"
    assert "timestamp" in result
    assert isinstance(result["temperature"], (int, float))