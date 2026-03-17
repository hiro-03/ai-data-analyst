import json
from agentcore.preprocess import Preprocessor
from agentcore.infer import InferenceEngine
from agentcore.postprocess import Postprocessor
from agentcore.adapter import ModelAdapter
from station_master import load_station_master, find_nearest_station
from logger import logger

# ★ Lambda 起動時に一度だけステーションマスタをロード（高速化）
stations = load_station_master()

def lambda_handler(event, context):
    lat = float(event["lat"])
    lon = float(event["lon"])

    # 1. 最寄り観測所（★ 修正：stations を渡す）
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
    logger.info(f"Logging observation for station {station_id}: {result}")

    # 6. API レスポンス
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(result)
    }