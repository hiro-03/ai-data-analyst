import json
from lambdas.weather_observation_api.lambda_function import parse_event

def test_parse_event_v2():
    event = {
        "version": "2.0",
        "body": json.dumps({"lat": 35, "lon": 135}),
        "isBase64Encoded": False
    }
    body = parse_event(event)
    assert body["lat"] == 35
    assert body["lon"] == 135