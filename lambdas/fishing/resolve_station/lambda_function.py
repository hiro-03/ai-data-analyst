import json
import logging
from typing import Any, Dict

from station_master import load_station_master, find_nearest_station

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _unwrap_lambda_proxy(obj: Any) -> Any:
    if isinstance(obj, dict):
        if "statusCode" in obj and "body" in obj:
            body = obj.get("body")
            if isinstance(body, str):
                try:
                    return json.loads(body)
                except Exception:
                    return body
            return body
        if "Payload" in obj and len(obj) <= 3:
            return _unwrap_lambda_proxy(obj.get("Payload"))
        return {k: _unwrap_lambda_proxy(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_unwrap_lambda_proxy(v) for v in obj]
    return obj


def lambda_handler(event, context):
    """
    Resolve nearest station_id from DynamoDB StationsTable.
    Expected input (from API/SFN): { "lat": number, "lon": number, ... }
    """
    unwrapped = _unwrap_lambda_proxy(event)
    if not isinstance(unwrapped, dict):
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "invalid input"}, ensure_ascii=False),
        }

    try:
        lat = float(unwrapped.get("lat"))
        lon = float(unwrapped.get("lon"))
    except Exception:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "lat and lon are required numbers"}, ensure_ascii=False),
        }

    stations = load_station_master()
    if not stations:
        logger.error("No stations loaded from DynamoDB (check STATIONS_TABLE content/permissions)")
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "no stations available"}, ensure_ascii=False),
        }

    station_id = find_nearest_station(lat, lon, stations)
    if not station_id:
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "cannot determine nearest station"}, ensure_ascii=False),
        }

    response: Dict[str, Any] = {
        "station_id": station_id,
        "lat": lat,
        "lon": lon,
    }

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(response, ensure_ascii=False),
    }

