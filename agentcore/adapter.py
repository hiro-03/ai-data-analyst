# agentcore/adapter.py
import time
import json
import os
import boto3
from .preprocess import preprocess
from .infer import infer
from .postprocess import emit_emf



LOCAL_MODE = os.getenv("LOCAL_MODE", "false").lower() == "true"

if LOCAL_MODE:
    dynamodb = boto3.client(
        "dynamodb",
        endpoint_url="http://localhost:8000",
        region_name="ap-northeast-1",
        aws_access_key_id="dummy",
        aws_secret_access_key="dummy"
    )
else:
    dynamodb = boto3.client("dynamodb")

def handler(event, context):
    start = time.time()
    trace_id = event.get("trace_id", "unknown")
    api_stage = event.get("api_stage", "dev")
    model_version = "v1.0.0"

    try:
        # 1. Preprocess
        pre = preprocess(event)

        # 2. Inference
        result = infer(pre)

        # 3. Postprocess + EMF
        latency_ms = int((time.time() - start) * 1000)
        payload_size = len(json.dumps(event).encode("utf-8"))

        emf = emit_emf(
            trace_id=trace_id,
            station_id=result["station_id"],
            model_version=model_version,
            api_stage=api_stage,
            latency_ms=latency_ms,
            confidence=result["confidence"],
            payload_size=payload_size,
            status="OK"
        )

        # 4. DynamoDB 書き込み
        write_to_dynamodb(result, trace_id)

        return {
            "statusCode": 200,
            "body": json.dumps(result)
        }

    except Exception as e:
        latency_ms = int((time.time() - start) * 1000)
        payload_size = len(json.dumps(event).encode("utf-8"))

        emit_emf(
            trace_id=trace_id,
            station_id="unknown",
            model_version=model_version,
            api_stage=api_stage,
            latency_ms=latency_ms,
            confidence=0.0,
            payload_size=payload_size,
            status="ERROR"
        )

        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }


def write_to_dynamodb(result, trace_id):
    dynamodb.put_item(
        TableName="WeatherObservations",
        Item={
            "trace_id": {"S": trace_id},
            "ts": {"S": result["timestamp"]},
            "station_id": {"S": result["station_id"]},
            "lat": {"N": str(result["lat"])},
            "lon": {"N": str(result["lon"])},
            "temperature": {"N": str(result["temperature"])},
            "confidence": {"N": str(result["confidence"])},
            "status": {"S": "OK"},
            "source": {"S": "lambda"},
            "shardType": {"S": "inference"},
            "ingestId": {"S": f"ing-{trace_id}"}
        }
    )