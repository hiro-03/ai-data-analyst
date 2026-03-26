import json
from datetime import datetime, timezone


def lambda_handler(event, context):
    """
    Minimal placeholder tide response.
    In real implementation, call a tide provider API and cache in DynamoDB.
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
                "tide": {
                    "summary": "mock tide",
                    "high_tide_iso": None,
                    "low_tide_iso": None,
                },
            }
        ),
    }

