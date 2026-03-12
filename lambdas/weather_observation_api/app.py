import json
from agentcore.preprocess import Preprocessor
from agentcore.infer import InferenceEngine
from agentcore.postprocess import Postprocessor
from agentcore.adapter import ModelAdapter
from utils.station import find_nearest_station
from utils.logger import log_observation

def lambda_handler(event, context):
    lat = float(event["lat"])
    lon = float(event["lon"])

    # 1. 最寄り観測所
    station_id = find_nearest_station(lat, lon)

    # 2. 前処理（気象庁データ取得）
    preprocessor = Preprocessor()
    features = preprocessor.run(lat, lon, station_id)

    # 3. 推論
    model = ModelAdapter().load("weather_model")
    raw_output = InferenceEngine(model).run(features)

    # 4. 後処理
    result = Postprocessor().run(raw_output)

    # 5. DynamoDB 保存
    log_observation(station_id, result)

    # 6. API レスポンス
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(result)
    }