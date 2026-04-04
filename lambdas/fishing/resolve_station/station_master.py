"""
DynamoDB-backed station master loader.

The boto3 resource is created once at module level so warm-start Lambda
executions skip the connection setup overhead.

In-memory cache: _STATION_CACHE holds the loaded station list keyed by table
name.  A warm-start invocation that targets the same table skips the full
DynamoDB scan entirely.  Cache is invalidated only on cold-start or when the
Lambda execution environment is recycled by AWS.

DYNAMODB_ENDPOINT can be set for local integration testing (e.g. DynamoDB Local).
"""
import logging
import os
from math import atan2, cos, radians, sin, sqrt
from typing import Any, Dict, List, Optional

import boto3
import botocore

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_dynamodb: Any = None

# Keyed by resolved table name.  Survives warm-start invocations.
_STATION_CACHE: Dict[str, List[Dict[str, Any]]] = {}


def _get_dynamodb() -> Any:
    """Lazily create the DynamoDB resource on first use."""
    global _dynamodb
    if _dynamodb is None:
        endpoint = os.environ.get("DYNAMODB_ENDPOINT") or None
        region = os.environ.get("AWS_DEFAULT_REGION") or os.environ.get("AWS_REGION") or "ap-northeast-1"
        _dynamodb = boto3.resource("dynamodb", endpoint_url=endpoint, region_name=region)
    return _dynamodb


def load_station_master(table_name: Optional[str] = None) -> List[Dict[str, Any]]:
    resolved = table_name or os.environ.get("STATIONS_TABLE") or "StationsTable"

    if resolved in _STATION_CACHE:
        logger.debug("station_master cache hit for table %s (%d stations)", resolved, len(_STATION_CACHE[resolved]))
        return _STATION_CACHE[resolved]

    table = _get_dynamodb().Table(resolved)
    items: List[Dict[str, Any]] = []

    try:
        response = table.scan()
    except botocore.exceptions.ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        logger.exception("Failed to scan table %s: %s", table.table_name, e)
        if code in ("ResourceNotFoundException", "UnrecognizedClientException", "AccessDeniedException"):
            return []
        raise
    except Exception:
        logger.exception("Unexpected error scanning table %s", table.table_name)
        return []

    items.extend(response.get("Items", []))
    while response.get("LastEvaluatedKey"):
        try:
            response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        except Exception:
            logger.exception("Failed to continue scan on table %s", table.table_name)
            break
        items.extend(response.get("Items", []))

    normalized: List[Dict[str, Any]] = []
    for i in items:
        if not isinstance(i, dict):
            continue
        try:
            station_id = i.get("station_id") or i.get("stationId") or i.get("id")
            lat_raw = i.get("latitude") or i.get("lat")
            lon_raw = i.get("longitude") or i.get("lon")
            if station_id is None or lat_raw is None or lon_raw is None:
                continue
            normalized.append(
                {"station_id": station_id, "latitude": float(lat_raw), "longitude": float(lon_raw)}
            )
        except Exception:
            logger.exception("Skipping malformed station item: %s", i)

    logger.info("Loaded %d station(s) from table %s", len(normalized), table.table_name)
    _STATION_CACHE[resolved] = normalized
    return normalized


def clear_station_cache(table_name: Optional[str] = None) -> None:
    """
    Evict one or all entries from the in-memory cache.

    Intended for testing only – production code should never call this.
    Pass table_name to evict a single entry; omit to clear the whole cache.
    """
    global _dynamodb
    if table_name is None:
        _STATION_CACHE.clear()
        _dynamodb = None
    else:
        _STATION_CACHE.pop(table_name, None)


def find_nearest_station(lat: float, lon: float, stations: List[Dict[str, Any]]) -> Optional[str]:
    if not stations:
        return None

    min_dist = float("inf")
    nearest: Optional[Dict[str, Any]] = None

    for s in stations:
        try:
            slat = float(s["latitude"])
            slon = float(s["longitude"])
        except Exception:
            continue

        dlat = radians(slat - lat)
        dlon = radians(slon - lon)
        a = sin(dlat / 2) ** 2 + cos(radians(lat)) * cos(radians(slat)) * sin(dlon / 2) ** 2
        dist_km = 6371.0 * 2 * atan2(sqrt(a), sqrt(1 - a))

        if dist_km < min_dist:
            min_dist = dist_km
            nearest = s

    return nearest.get("station_id") if nearest else None
