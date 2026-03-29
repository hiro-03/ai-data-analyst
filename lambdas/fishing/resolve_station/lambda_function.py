import logging
from typing import Any

from fishing_common.lambda_utils import json_response, unwrap_lambda_proxy
from station_master import find_nearest_station, load_station_master

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    unwrapped = unwrap_lambda_proxy(event)
    if not isinstance(unwrapped, dict):
        return json_response(400, {"error": "invalid input"})

    try:
        lat = float(unwrapped.get("lat"))
        lon = float(unwrapped.get("lon"))
    except Exception:
        return json_response(400, {"error": "lat and lon are required numbers"})

    stations = load_station_master()
    if not stations:
        logger.error("No stations loaded from DynamoDB (check STATIONS_TABLE content/permissions)")
        return json_response(500, {"error": "no stations available"})

    station_id = find_nearest_station(lat, lon, stations)
    if not station_id:
        return json_response(500, {"error": "cannot determine nearest station"})

    return json_response(200, {"station_id": station_id, "lat": lat, "lon": lon})
