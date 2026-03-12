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

LOCAL_MODE = os.getenv("LOCAL_MODE", "").lower() == "true"

# -----------------------------
# boto3 クライアント
# -----------------------------
def ddb_client():
    endpoint = os.getenv("DYNAMODB_ENDPOINT")
    logger.info("LOG: ddb_client init (endpoint=%s)", endpoint)
    if endpoint:
        return boto3.client(
            "dynamodb",
            region_name=os.environ.get("AWS_REGION", "ap-northeast-1"),
            endpoint_url=endpoint,
        )
    else:
        return boto3.client(
            "dynamodb",
            region_name=os.environ.get("AWS_REGION", "ap-northeast-1"),
        )

# -----------------------------
# DynamoDB 操作
# -----------------------------
def ddb_scan(table_name):
    logger.info("LOG: before ddb_scan(%s)", table_name)
    client = ddb_client()
    try:
        resp = client.scan(TableName=table_name)
        logger.info("LOG: ddb_scan(%s) success", table_name)
        return resp
    except ClientError:
        logger.exception("DynamoDB scan failed for %s", table_name)
        raise

def ddb_put_item(table_name, item):
    logger.info("LOG: before ddb_put_item(%s)", table_name)
    client = ddb_client()
    try:
        resp = client.put_item(TableName=table_name, Item=item)
        logger.info("LOG: ddb_put_item(%s) success", table_name)
        return resp
    except ClientError:
        logger.exception("DynamoDB put_item failed for %s", table_name)
        raise

def ensure_table_exists(table_name):
    if not LOCAL_MODE:
        return

    logger.info("LOG: ensure_table_exists(%s) start", table_name)
    client = ddb_client()
    try:
        client.describe_table(TableName=table_name)
        logger.info("LOG: table %s already exists", table_name)
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
# Event パース
# -----------------------------
def parse_event(event):
    logger.info("LOG: parse_event start")
    version = event.get("version")

    if version == "2.0":
        raw = event.get("body", "")
        if event.get("isBase64Encoded"):
            raw = base64.b64decode(raw).decode("utf-8")
        try:
            parsed = json.loads(raw)
            logger.info("LOG: parse_event v2 success")
            return parsed
        except Exception:
            raise ValueError(f"invalid json body: {raw}")

    if "body" in event:
        raw = event["body"]
        if event.get("isBase64Encoded"):
            raw = base64.b64decode(raw).decode("utf-8")
        try:
            parsed = json.loads(raw)
            logger.info("LOG: parse_event v1 success")
            return parsed
        except Exception:
            raise ValueError(f"invalid json body: {raw}")

    logger.info("LOG: parse_event dict passthrough")
    return event

# -----------------------------
# Stations 読み込み
# -----------------------------
def load_station_master():
    logger.info("LOG: load_station_master start")
    try:
        logger.info("LOG: before ddb_scan Stations")
        resp = ddb_scan("Stations")
    except Exception:
        logger.exception("Failed to scan Stations table")
        raise

    logger.info("LOG: Stations scan resp: %s", resp)
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
            raise
    return stations

# -----------------------------
# 最寄り station 判定
# -----------------------------
def find_nearest_station(lat, lon, stations):
    logger.info("LOG: find_nearest_station start")
    nearest = None
    min_dist = float("inf")
    for s in stations:
        dist = haversine(lat, lon, s["latitude"], s["longitude"])
        if dist < min_dist:
            min_dist = dist
            nearest = s["station_id"]
    logger.info("LOG: nearest station = %s", nearest)
    return nearest

# -----------------------------
# 気象データ取得（ダミー）
# -----------------------------
def fetch_weather(station_id):
    logger.info("LOG: fetch_weather(%s)", station_id)
    return {"temperature": 22.5, "humidity": 45}

# -----------------------------
# Lambda Handler
# -----------------------------
def lambda_handler(event, context):
    logger.info("LOG: lambda_handler start")
    logger.info("LOG: event received: %s", event)

    try:
        try:
            ensure_table_exists("WeatherObservations")
        except Exception:
            logger.exception("ensure_table_exists failed; continuing (local only)")

        # parse_event の ValueError は API 用に 400 を返す
        try:
            body = parse_event(event)
            logger.info("LOG: body parsed: %s", body)
        except ValueError as e:
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": str(e)}),
            }

        if "lat" not in body or "lon" not in body:
            raise ValueError("lat and lon are required")

        if body["lat"] is None or body["lon"] is None:
            raise ValueError("lat/lon is None")

        try:
            lat = float(body["lat"])
            lon = float(body["lon"])
            logger.info("LOG: lat/lon parsed: %s, %s", lat, lon)
        except Exception:
            raise ValueError("lat and lon must be numbers")

        logger.info("LOG: before load_station_master")
        stations = load_station_master()
        logger.info("LOG: stations loaded: %s", stations)

        if not stations:
            raise ValueError("no stations available")

        station_id = find_nearest_station(lat, lon, stations)
        if station_id is None:
            raise ValueError("cannot determine nearest station")

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

        logger.info("LOG: before ddb_put_item: %s", item)
        try:
            ddb_put_item("WeatherObservations", item)
        except Exception:
            logger.exception("Failed to put item into WeatherObservations")
            raise

        response_body = {
            "station_id": station_id,
            "temperature": weather["temperature"],
            "humidity": weather["humidity"],
            "timestamp": timestamp,
        }

        logger.info("LOG: lambda_handler success")
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(response_body),
        }

    except Exception:
        logger.exception("Unhandled exception in lambda_handler")
        raise