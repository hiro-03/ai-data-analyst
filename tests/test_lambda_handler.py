import json
from lambda_function import lambda_handler
import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "lambdas", "weather_observation_api")))
from lambda_function import lambda_handler

def test_lambda_handler_success(monkeypatch):
    event = {"lat": 35, "lon": 135}
    monkeypatch.setattr("lambda_function.load_station_master", lambda table_name=None: [{"station_id":"X","latitude":35.0,"longitude":135.0}])
    monkeypatch.setattr("lambda_function.find_nearest_station", lambda lat, lon, stations: "X")
    monkeypatch.setattr("lambda_function.fetch_weather", lambda station_id: {"temperature": 20.0, "humidity": 50})
    monkeypatch.setattr("lambda_function.ddb_put_item", lambda table_name, item: {"ResponseMetadata": {"HTTPStatusCode": 200}})

    resp = lambda_handler(event, None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["station_id"] == "X"
    assert "temperature" in body

def test_lambda_handler_ddb_failure(monkeypatch):
    event = {"lat": 35, "lon": 135}
    monkeypatch.setattr("lambda_function.load_station_master", lambda table_name=None: [{"station_id":"X","latitude":35.0,"longitude":135.0}])
    monkeypatch.setattr("lambda_function.find_nearest_station", lambda lat, lon, stations: "X")
    monkeypatch.setattr("lambda_function.fetch_weather", lambda station_id: {"temperature": 20.0, "humidity": 50})
    def raise_exc(table_name, item):
        raise Exception("ddb failed")
    monkeypatch.setattr("lambda_function.ddb_put_item", raise_exc)

    resp = lambda_handler(event, None)
    assert resp["statusCode"] == 500
    body = json.loads(resp["body"])
    assert "failed to persist" in body.get("error", "") or "internal server error" in body.get("error", "")