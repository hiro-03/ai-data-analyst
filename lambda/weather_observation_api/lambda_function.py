import json
import os
import math
import base64
from datetime import datetime, timezone
from decimal import Decimal
import logging
from botocore.exceptions import ClientError
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# 環境変数
LOCAL_MODE = os.getenv("LOCAL_MODE", "").lower() == "true"

# -----------------------------
# boto3 クライアントユーティリティ
# -----------------------------
def ddb_client():
    if LOCAL_MODE:
        endpoint = "http://localhost:8000"
    else:
        endpoint = os.getenv("DYNAMODB_ENDPOINT")  # docker-compose では http://dynamodb-local:8000

    return boto3.client(
        "dynamodb",
        region_name=os.environ.get("AWS_REGION", "ap-northeast-1"),
        endpoint_url=endpoint,
    )

# -----------------------------
# DynamoDB 操作（例外をログに残す）
# -----------------------------
def ddb_scan(table_name):
    client = ddb_client()
    try:
        return client.scan(TableName=table_name)
    except ClientError:
        logger.exception("DynamoDB scan failed for %s", table_name)
        raise

def ddb_put_item(table_name, item):
    client = ddb_client()
    try:
        return client.put_item(TableName=table_name, Item=item)
    except ClientError:
        logger.exception("DynamoDB put_item failed for %s", table_name)
        raise

def ensure_table_exists(table_name):
    """
    ローカル実行時のみテーブルが無ければ作成する（本番では呼ばないことを推奨）。
    """
    if not LOCAL_MODE:
        return

    client = ddb_client()
    try:
        client.describe_table(TableName=table_name)
        return
    except client.exceptions.ResourceNotFoundException:
        logger.info("Creating local table %s", table_name)
        client.create_table(
            TableName=table_name,
            AttributeDefinitions=[
                {"AttributeName": "station_id", "AttributeType": "S"},
                {"AttributeName": "timestamp", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "station_id", "KeyType": "HASH"},
                {"AttributeName": "timestamp", "KeyType": "RANGE"},
            ],
            ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        )
        waiter = client.get_waiter("table_exists")
        waiter.wait(TableName=table_name)
        logger.info("Local table %s created and active", table_name)
    except Exception:
        logger.exception("Failed to ensure table exists: %s", table_name)
        raise

# -----------------------------
# Utility
# -----------------------------
def to_decimal(v):
    return Decimal(str(v)) if v is not None else None

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return 2 * R * math.asin(math.sqrt(a))

# -----------------------------
# Event パース（v1/v2 両対応）
# -----------------------------
def parse_event(event):
    """
    HTTP API v2 / REST API v1 / sam local invoke の全形式に対応した body パーサー
    """
    version = event.get("version")

    # HTTP API v2
    if version == "2.0":
        raw = event.get("body", "")
        if event.get("isBase64Encoded"):
            raw = base64.b64decode(raw).decode("utf-8")
        try:
            return json.loads(raw)
        except Exception:
            raise ValueError(f"invalid json body: {raw}")

    # REST API v1 / sam local start-api（v1）
    if "body" in event:
        raw = event["body"]
        if event.get("isBase64Encoded"):
            raw = base64.b64decode(raw).decode("utf-8")
        try:
            return json.loads(raw)
        except Exception:
            raise ValueError(f"invalid json body: {raw}")

    # sam local invoke など、dict がそのまま来るケース
    return event

# -----------------------------
# Stations 読み込み
# -----------------------------
def load_station_master():
    try:
        resp = ddb_scan("Stations")
    except Exception:
        logger.exception("Failed to scan Stations table")
        return []

    logger.info("Stations scan resp: %s", resp)
    items = resp.get("Items", [])
    stations = []
    for i in items:
        try:
            stations.append({
                "station_id": i["station_id"]["S"],
                "latitude": float(i["latitude"]["N"]),
                "longitude": float(i["longitude"]["N"]),
            })
        except Exception:
            logger.exception("Malformed station item: %s", i)
    return stations

# -----------------------------
# 最寄り station 判定
# -----------------------------
def find_nearest_station(lat, lon, stations):
    nearest = None
    min_dist = float("inf")
    for s in stations:
        dist = haversine(lat, lon, s["latitude"], s["longitude"])
        if dist < min_dist:
            min_dist = dist
            nearest = s["station_id"]
    return nearest

# -----------------------------
# 気象データ取得（ダミー）
# -----------------------------
def fetch_weather(station_id):
    # 実運用では外部 API 呼び出しやモデルに差し替える
    return {"temperature": 22.5, "humidity": 45}

# -----------------------------
# Lambda Handler
# -----------------------------
def lambda_handler(event, context):
    try:
        # ローカル実行時は必要なテーブルを確保
        try:
            ensure_table_exists("WeatherObservations")
        except Exception:
            logger.exception("ensure_table_exists failed; continuing (local only)")

        # event から body を取り出す（v1/v2 両対応）
        try:
            body = parse_event(event)
        except ValueError as e:
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": str(e)}),
            }

        # 必須パラメータ検証
        if "lat" not in body or "lon" not in body:
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": "lat and lon are required"}),
            }

        try:
            lat = float(body["lat"])
            lon = float(body["lon"])
        except Exception:
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": "lat and lon must be numbers"}),
            }

        stations = load_station_master()
        if not stations:
            logger.warning("No stations found in Stations table")
            return {
                "statusCode": 404,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": "no stations available"}),
            }

        station_id = find_nearest_station(lat, lon, stations)
        if station_id is None:
            logger.warning("Could not determine nearest station for %s,%s", lat, lon)
            return {
                "statusCode": 422,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": "cannot determine nearest station"}),
            }

        weather = fetch_weather(station_id)

        timestamp = now_iso()
        item = {
            "station_id": {"S": station_id},
            "timestamp": {"S": timestamp},
            "latitude": {"N": str(lat)},
            "longitude": {"N": str(lon)},
            "temperature": {"N": str(weather["temperature"])},
            "humidity": {"N": str(weather["humidity"])},
        }

        try:
            ddb_put_item("WeatherObservations", item)
        except Exception:
            logger.exception("Failed to put item into WeatherObservations")
            return {
                "statusCode": 500,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": "failed to persist observation"}),
            }

        response_body = {
            "station_id": station_id,
            "temperature": weather["temperature"],
            "humidity": weather["humidity"],
            "timestamp": timestamp,
        }

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(response_body),
        }

    except Exception:
        logger.exception("Unhandled exception in lambda_handler")
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "internal server error"}),
        }