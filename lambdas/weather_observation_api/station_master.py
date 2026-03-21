import os
import boto3
from typing import List, Dict, Optional
from math import radians, sin, cos, sqrt, atan2

def _get_dynamodb_table(table_name: Optional[str] = None):
    """
    Resolve the DynamoDB table name in this order:
      1. explicit table_name argument
      2. STATIONS_TABLE environment variable
      3. fallback to "Stations"
    """
    resolved_name = table_name or os.environ.get("STATIONS_TABLE") or "Stations"
    dynamodb = boto3.resource("dynamodb")
    return dynamodb.Table(resolved_name)

def load_station_master(table_name: Optional[str] = None) -> List[Dict]:
    """
    Load station master items from DynamoDB.
    Accepts optional table_name for flexibility in tests and CloudFormation.
    Returns list of items (as dicts). Caller should handle empty lists.
    """
    table = _get_dynamodb_table(table_name)
    items = []
    # Use pagination to be safe for large tables
    response = table.scan()
    items.extend(response.get("Items", []))
    while response.get("LastEvaluatedKey"):
        response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        items.extend(response.get("Items", []))
    # Normalize items to expected dict format if they are DynamoDB JSON
    normalized = []
    for i in items:
        # If items are in DynamoDB JSON format (with 'S'/'N'), convert
        if isinstance(i, dict) and any(isinstance(v, dict) for v in i.values()):
            try:
                normalized.append({
                    "station_id": i.get("station_id", {}).get("S") if isinstance(i.get("station_id"), dict) else i.get("station_id"),
                    "latitude": float(i.get("latitude", {}).get("N")) if isinstance(i.get("latitude"), dict) else float(i.get("latitude")),
                    "longitude": float(i.get("longitude", {}).get("N")) if isinstance(i.get("longitude"), dict) else float(i.get("longitude")),
                })
            except Exception:
                # Skip malformed entries
                continue
        else:
            try:
                normalized.append({
                    "station_id": i.get("station_id"),
                    "latitude": float(i.get("latitude")),
                    "longitude": float(i.get("longitude")),
                })
            except Exception:
                continue
    return normalized

def find_nearest_station(lat: float, lon: float, stations: List[Dict]) -> Optional[str]:
    """
    Given latitude/longitude and a list of station dicts (with 'latitude' and 'longitude'),
    return the nearest station's station_id. Returns None if stations is empty.
    """
    if not stations:
        return None

    min_dist = float("inf")
    nearest = None

    for s in stations:
        try:
            slat = float(s["latitude"])
            slon = float(s["longitude"])
        except (KeyError, TypeError, ValueError):
            # Skip malformed entries
            continue

        # Haversine distance
        dlat = radians(slat - lat)
        dlon = radians(slon - lon)
        a = sin(dlat/2)**2 + cos(radians(lat)) * cos(radians(slat)) * sin(dlon/2)**2
        c = 2 * atan2(sqrt(a), sqrt(1 - a))
        dist = 6371 * c

        if dist < min_dist:
            min_dist = dist
            nearest = s

    if nearest is None:
        return None

    return nearest.get("station_id")