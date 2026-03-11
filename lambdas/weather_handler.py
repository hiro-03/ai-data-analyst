import json
import uuid
import os
from agentcore.adapter import handler as agentcore_handler

def lambda_handler(event, context):
    try:
        # API Gateway v2 (HTTP API) を想定
        body = json.loads(event.get("body", "{}"))

        # 入力バリデーション
        if "lat" not in body or "lon" not in body:
            return {
                "statusCode": 400,
                "body": json.dumps({
                    "trace_id": "invalid-request",
                    "error": "lat and lon are required"
                })
            }

        lat = body["lat"]
        lon = body["lon"]

        # 型チェック
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            return {
                "statusCode": 400,
                "body": json.dumps({
                    "trace_id": "invalid-request",
                    "error": "lat and lon must be numbers"
                })
            }

        # trace_id 生成
        trace_id = str(uuid.uuid4())

        # ステージ（dev/stg/prod）
        api_stage = os.getenv("API_STAGE", "dev")

        # AgentCore に渡す event
        agent_event = {
            "lat": lat,
            "lon": lon,
            "trace_id": trace_id,
            "api_stage": api_stage
        }

        # AgentCore 実行
        result = agentcore_handler(agent_event, context)

        # AgentCore が返す result は {statusCode, body}
        return result

    except Exception:
        trace_id = str(uuid.uuid4())
        return {
            "statusCode": 500,
            "body": json.dumps({
                "trace_id": trace_id,
                "error": "Internal inference error"
            })
        }