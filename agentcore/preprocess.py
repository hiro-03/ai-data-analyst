def preprocess(event):
    return {
        "lat": float(event["lat"]),
        "lon": float(event["lon"]),
        "trace_id": event.get("trace_id", "unknown")
    }