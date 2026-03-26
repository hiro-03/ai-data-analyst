import json
from datetime import datetime, timezone


def lambda_handler(event, context):
    """
    Minimal placeholder marine response.
    In real implementation, call marine/weather API(s) for water temp and wind.
    """
    now = datetime.now(timezone.utc).isoformat()
    lat = event.get("lat")
    lon = event.get("lon")
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(
            {
                "provider": "mock",
                "requested_at": now,
                "lat": lat,
                "lon": lon,
                "marine": {
                    "water_temperature_c": None,
                    "wind_speed_mps": None,
                    "wind_direction_deg": None,
                },
            }
        ),
    }

