import boto3

dynamodb = boto3.resource('dynamodb')
STATION_TABLE = dynamodb.Table('Stations')

def load_station_master():
    response = STATION_TABLE.scan()
    return response.get("Items", [])

def find_nearest_station(lat, lon, stations):
    from geo_utils import haversine

    nearest = None
    min_dist = float("inf")

    for st in stations:
        dist = haversine(
            lat,
            lon,
            float(st["latitude"]),
            float(st["longitude"])
        )
        if dist < min_dist:
            min_dist = dist
            nearest = st

    return nearest