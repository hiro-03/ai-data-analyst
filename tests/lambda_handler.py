import json
from unittest.mock import patch
from lambdas.weather_observation_api.lambda_function import lambda_handler

@patch("lambda.weather_observation_api.lambda_function.ddb_scan")
@patch("lambda.weather_observation_api.lambda_function.ddb_put_item")
def test_lambda_handler(mock_put, mock_scan):
    mock_scan.return_value = {
        "Items": [
            {"station_id": {"S": "TOKYO"}, "latitude": {"N": "35.0"}, "longitude": {"N": "135.0"}}
        ]
    }

    event = {"lat": 35, "lon": 135}
    resp = lambda_handler(event, None)
    assert resp["statusCode"] == 200