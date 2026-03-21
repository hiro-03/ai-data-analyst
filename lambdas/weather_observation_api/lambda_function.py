import json
import os
import base64
from datetime import datetime, timezone
import logging

from station_master import load_station_master, find_nearest_station
import observation_repository

logger = logging.getLogger()
logger.setLevel(logging.INFO)

LOCAL_MODE = os.getenv("LOCAL_MODE", "").lower() == "true"

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def parse_event(event):
    """
    Parse API Gateway v1/v2 or direct invocation payload into dict.
    Raises ValueError on invalid JSON.
    """
    version = event.get("version")
    if version == "2.0":
        raw = event.get("body", "") or ""
        if event.get("isBase64Encoded"):
            raw = base64.b64decode(raw).decode("utf-8")
        try:
            return json.loads(raw)
        except Exception:
            raise ValueError(f"invalid json body: {raw}")

    if "body" in event:
        raw = event["body"] or ""
        if event.get("isBase64Encoded"):
            raw = base64.b64decode(raw).decode("utf-8")
        try:
            return json.loads(raw)
        except Exception:
            raise ValueError(f"invalid json body: {raw}")

    # direct invocation with dict
    return event

# ---- business stub (keep as-is or replace with real integration) ----
def fetch_weather(station_id):
    # Replace with real call if available
    return {"temperature": 22.5, "humidity": 45}

# ---- handler stages ----
def preprocess(event):
    """
    Validate and normalize input. Return dict with lat, lon and any metadata.
    Raise ValueError for client errors.
    """
    logger.info("preprocess start")
    body = parse_event(event)
    if "lat" not in body or "lon" not in body:
        raise ValueError("lat and lon are required")
    if body["lat"] is None or body["lon"] is None:
        raise ValueError("lat/lon is None")
    try:
        lat = float(body["lat"])
        lon = float(body["lon"])
    except Exception:
        raise ValueError("lat and lon must be numbers")
    logger.info("preprocess success lat=%s lon=%s", lat, lon)
    return {"lat": lat, "lon": lon}

def infer(payload):
    """
    Core logic: load station master, find nearest station, fetch weather, persist observation.
    Returns a result dict for postprocess.
    """
    logger.info("infer start")
    stations_table = os.environ.get("STATIONS_TABLE", "Stations")
    observations_table = os.environ.get("WEATHER_OBSERVATIONS_TABLE", "WeatherObservations")

    # Load station master (station_master handles DynamoDB details and normalization)
    stations = load_station_master(table_name=stations_table)
    logger.info("infer loaded %d stations", len(stations))

    if not stations:
        raise RuntimeError("no stations available")

    station_id = find_nearest_station(payload["lat"], payload["lon"], stations)
    if station_id is None:
        raise RuntimeError("cannot determine nearest station")

    weather = fetch_weather(station_id)

    timestamp = now_iso()

    # Persist observation via repository (abstracts DynamoDB details)
    observation_repository.save_observation(
        observations_table,
        station_id,
        timestamp,
        payload["lat"],
        payload["lon"],
        weather["temperature"],
        weather["humidity"],
    )

    logger.info("infer success station=%s", station_id)
    return {
        "station_id": station_id,
        "temperature": weather["temperature"],
        "humidity": weather["humidity"],
        "timestamp": timestamp,
    }

def postprocess(result):
    """
    Format HTTP response body.
    """
    logger.info("postprocess start")
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(result),
    }

# ---- Lambda entrypoint ----
def lambda_handler(event, context):
    logger.info("lambda_handler start")
    logger.info("event: %s", event)
    try:
        try:
            payload = preprocess(event)
        except ValueError as e:
            return {
                "statusCode": 400,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": str(e)}),
            }

        try:
            result = infer(payload)
        except RuntimeError as e:
            logger.exception("business error in infer")
            return {
                "statusCode": 500,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": str(e)}),
            }
        except Exception:
            logger.exception("unexpected error in infer")
            return {
                "statusCode": 500,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": "internal server error"}),
            }

        return postprocess(result)

    except Exception:
        logger.exception("Unhandled exception in lambda_handler")
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "internal server error"}),
        }