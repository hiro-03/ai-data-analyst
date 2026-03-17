import boto3
from decimal import Decimal
from math import radians, sin, cos, sqrt, atan2

dynamodb = boto3.resource("dynamodb")
STATION_TABLE = dynamodb.Table("Stations")

def load_station_master():
    response = STATION_TABLE.scan()
    return response["Items"]

def find_nearest_station(lat, lon, stations):
    min_dist = float("inf")
    nearest = None

    for s in stations:
        slat = float(s["latitude"])
        slon = float(s["longitude"])

        # Haversine 距離
        dlat = radians(slat - lat)
        dlon = radians(slon - lon)
        a = sin(dlat/2)**2 + cos(radians(lat)) * cos(radians(slat)) * sin(dlon/2)**2
        c = 2 * atan2(sqrt(a), sqrt(1 - a))
        dist = 6371 * c

        if dist < min_dist:
            min_dist = dist
            nearest = s

    # ★ station_id のみ返す（今回の修正ポイント）
    return nearest["station_id"]