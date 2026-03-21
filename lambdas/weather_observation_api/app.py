import os
import json
from agentcore.preprocess import Preprocessor
from agentcore.infer import InferenceEngine
from agentcore.postprocess import Postprocessor
from agentcore.adapter import ModelAdapter
from station_master import load_station_master, find_nearest_station
from logger import logger

def _load_stations(table_name=None):
    """
    Load station master. Try to pass table_name to load_station_master if supported,
    otherwise call without arguments. Cache is handled by caller if desired.
    """
    try:
        # If station_master.load_station_master accepts a table name, pass it
        return load_station_master(table_name)
    except TypeError:
        # Fallback to calling without arguments for backward compatibility
        return load_station_master()

def lambda_handler(event, context):
    # Read table name from environment variable set by CloudFormation
    stations_table = os.environ.get("STATIONS_TABLE")

    # Load stations at invocation time to avoid import-time DynamoDB calls
    stations = _load_stations(stations_table)

    # Validate input and coerce types safely
    try:
        lat = float(event.get("lat"))
        lon = float(event.get("lon"))
    except Exception as e:
        logger.error("Invalid input for lat/lon: %s", e)
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "Invalid input: lat and lon are required and must be numbers"})
        }

    # 1. 最寄り観測所
    station_id = find_nearest_station(lat, lon, stations)

    # 2. 前処理（気象庁データ取得）
    preprocessor = Preprocessor()
    features = preprocessor.run(lat, lon, station_id)

    # 3. 推論
    model = ModelAdapter().load("weather_model")
    raw_output = InferenceEngine(model).run(features)

    # 4. 後処理
    result = Postprocessor().run(raw_output)

    # 5. DynamoDB 保存（ログのみ）
    logger.info("Logging observation for station %s: %s", station_id, result)

    # 6. API レスポンス
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(result)
    }