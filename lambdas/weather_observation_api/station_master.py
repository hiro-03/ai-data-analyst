import os
import logging
from typing import List, Dict, Optional

import boto3

# Logger setup
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)


def _get_dynamodb_table(table_name: Optional[str] = None):
    """
    Resolve the DynamoDB table name in this order:
      1. explicit table_name argument
      2. STATIONS_TABLE environment variable
      3. fallback to "Stations"

    Use DYNAMODB_ENDPOINT when provided so code running inside Docker can reach
    the host's DynamoDB Local (use host.docker.internal in env.json).
    """
    resolved_name = table_name or os.environ.get("STATIONS_TABLE") or "Stations"
    endpoint = os.environ.get("DYNAMODB_ENDPOINT")
    region = os.environ.get("AWS_REGION") or "ap-northeast-1"

    logger.info("Resolving DynamoDB table: resolved_name=%s, endpoint=%s, region=%s", resolved_name, endpoint, region)

    if endpoint:
        dynamodb = boto3.resource("dynamodb", endpoint_url=endpoint, region_name=region)
    else:
        dynamodb = boto3.resource("dynamodb", region_name=region)

    return dynamodb.Table(resolved_name)


def load_station_master(table_name: Optional[str] = None) -> List[Dict]:
    """
    Load station master items from DynamoDB and normalize them to a list of dicts:
      [{"station_id": "...", "latitude": 35.0, "longitude": 135.0}, ...]
    Accepts optional table_name for tests and CloudFormation flexibility.
    """
    table = _get_dynamodb_table(table_name)
    items: List[Dict] = []

    logger.info("Scanning DynamoDB table for stations: %s", table.table_name)

    try:
        response = table.scan()
    except Exception as e:
        logger.exception("Failed to scan table %s: %s", table.table_name, e)
        raise

    items.extend(response.get("Items", []))
    while response.get("LastEvaluatedKey"):
        try:
            response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        except Exception as e:
            logger.exception("Failed to continue scan on table %s: %s", table.table_name, e)
            break
        items.extend(response.get("Items", []))

    normalized: List[Dict] = []
    for i in items:
        if not isinstance(i, dict):
            continue

        # Detect DynamoDB JSON style (e.g., {"lat": {"N": "35"}})
        is_dynamodb_json = any(isinstance(v, dict) and any(k in v for k in ("S", "N", "BOOL", "M", "L")) for v in i.values())

        if is_dynamodb_json:
            try:
                # Accept multiple possible attribute names
                station_id = (
                    i.get("station_id", {}).get("S")
                    if isinstance(i.get("station_id"), dict)
                    else i.get("station_id")
                ) or (
                    i.get("stationId", {}).get("S")
                    if isinstance(i.get("stationId"), dict)
                    else i.get("stationId")
                )
                lat_raw = (
                    i.get("latitude", {}).get("N")
                    if isinstance(i.get("latitude"), dict)
                    else i.get("latitude")
                ) or (
                    i.get("lat", {}).get("N")
                    if isinstance(i.get("lat"), dict)
                    else i.get("lat")
                )
                lon_raw = (
                    i.get("longitude", {}).get("N")
                    if isinstance(i.get("longitude"), dict)
                    else i.get("longitude")
                ) or (
                    i.get("lon", {}).get("N")
                    if isinstance(i.get("lon"), dict)
                    else i.get("lon")
                )

                if station_id is None or lat_raw is None or lon_raw is None:
                    logger.debug("Skipping incomplete DynamoDB JSON item: %s", i)
                    continue

                normalized.append({
                    "station_id": station_id,
                    "latitude": float(lat_raw),
                    "longitude": float(lon_raw),
                })
            except Exception:
                logger.exception("Skipping malformed DynamoDB JSON item: %s", i)
                continue
        else:
            try:
                station_id = i.get("station_id") or i.get("stationId") or i.get("id")
                lat_raw = i.get("latitude") or i.get("lat")
                lon_raw = i.get("longitude") or i.get("lon")

                if station_id is None or lat_raw is None or lon_raw is None:
                    logger.debug("Skipping incomplete plain item: %s", i)
                    continue

                normalized.append({
                    "station_id": station_id,
                    "latitude": float(lat_raw),
                    "longitude": float(lon_raw),
                })
            except Exception:
                logger.exception("Skipping malformed plain item: %s", i)
                continue

    logger.info("Loaded %d station(s) from table %s", len(normalized), table.table_name)
    return normalized


def find_nearest_station(lat: float, lon: float, stations: List[Dict]) -> Optional[str]:
    """
    Given latitude/longitude and a list of station dicts (with 'latitude' and 'longitude'),
    return the nearest station's station_id. Returns None if stations is empty.
    Uses Haversine formula to compute great-circle distance in kilometers.
    """
    if not stations:
        logger.info("No stations provided to find_nearest_station")
        return None

    from math import radians, sin, cos, sqrt, atan2

    min_dist = float("inf")
    nearest: Optional[Dict] = None

    for s in stations:
        try:
            slat = float(s["latitude"])
            slon = float(s["longitude"])
        except (KeyError, TypeError, ValueError):
            logger.debug("Skipping malformed station entry: %s", s)
            continue

        # Haversine distance
        dlat = radians(slat - lat)
        dlon = radians(slon - lon)
        a = sin(dlat / 2) ** 2 + cos(radians(lat)) * cos(radians(slat)) * sin(dlon / 2) ** 2
        c = 2 * atan2(sqrt(a), sqrt(1 - a))
        dist_km = 6371.0 * c

        if dist_km < min_dist:
            min_dist = dist_km
            nearest = s

    if nearest is None:
        logger.info("No valid nearest station found")
        return None

    station_id = nearest.get("station_id")
    logger.info("Nearest station: %s (distance_km=%.3f)", station_id, min_dist)
    return station_id