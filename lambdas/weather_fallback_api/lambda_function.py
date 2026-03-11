import json

def lambda_handler(event, context):
    return {
        "station_id": "Unknown",
        "timestamp": None,
        "latitude": None,
        "longitude": None,
        "temperature": None,
        "humidity": None,
        "error": "Fallback: weather observation failed."
    }