import os
import logging
from typing import Dict, List, Optional

import boto3
import botocore


logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)


def _get_dynamodb_resource():
    endpoint = os.environ.get("DYNAMODB_ENDPOINT")
    region = os.environ.get("AWS_DEFAULT_REGION") or os.environ.get("AWS_REGION") or "ap-northeast-1"

    if endpoint:
        logger.info("Using DynamoDB endpoint from env: %s (region=%s)", endpoint, region)
        return boto3.resource("dynamodb", endpoint_url=endpoint, region_name=region)
    return boto3.resource("dynamodb", region_name=region)


def _get_dynamodb_table(table_name: Optional[str] = None):
    resolved_name = table_name or os.environ.get("STATIONS_TABLE") or "StationsTable"
    dynamodb = _get_dynamodb_resource()
    return dynamodb.Table(resolved_name)


def load_station_master(table_name: Optional[str] = None) -> List[Dict]:
    table = _get_dynamodb_table(table_name)
    items: List[Dict] = []

    try:
        response = table.scan()
    except botocore.exceptions.ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        logger.exception("Failed to scan table %s: %s", table.table_name, e)
        if code in ("ResourceNotFoundException", "UnrecognizedClientException", "AccessDeniedException"):
            return []
        raise
    except Exception as e:
        logger.exception("Unexpected error scanning table %s: %s", table.table_name, e)
        return []

    items.extend(response.get("Items", []))
    while response.get("LastEvaluatedKey"):
        try:
            response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        except Exception:
            logger.exception("Failed to continue scan on table %s", table.table_name)
            break
        items.extend(response.get("Items", []))

    normalized: List[Dict] = []
    for i in items:
        if not isinstance(i, dict):
            continue

        # boto3 Table.scan() returns plain python dicts, but keep compatibility just in case.
        is_dynamodb_json = any(
            isinstance(v, dict) and any(k in v for k in ("S", "N", "BOOL", "M", "L")) for v in i.values()
        )

        if is_dynamodb_json:
            try:
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
                    continue

                normalized.append(
                    {"station_id": station_id, "latitude": float(lat_raw), "longitude": float(lon_raw)}
                )
            except Exception:
                logger.exception("Skipping malformed DynamoDB JSON item: %s", i)
        else:
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
    return normalized


def find_nearest_station(lat: float, lon: float, stations: List[Dict]) -> Optional[str]:
    if not stations:
        return None

    from math import radians, sin, cos, sqrt, atan2

    min_dist = float("inf")
    nearest: Optional[Dict] = None

    for s in stations:
        try:
            slat = float(s["latitude"])
            slon = float(s["longitude"])
        except Exception:
            continue

        dlat = radians(slat - lat)
        dlon = radians(slon - lon)
        a = sin(dlat / 2) ** 2 + cos(radians(lat)) * cos(radians(slat)) * sin(dlon / 2) ** 2
        c = 2 * atan2(sqrt(a), sqrt(1 - a))
        dist_km = 6371.0 * c

        if dist_km < min_dist:
            min_dist = dist_km
            nearest = s

    if not nearest:
        return None

    return nearest.get("station_id")

