import time

def infer(data):
    time.sleep(0.05)  # ダミー推論時間
    return {
        "station_id": "JP0001",
        "lat": data["lat"],
        "lon": data["lon"],
        "temperature": 18.5,
        "confidence": 0.93,
        "timestamp": "2026-03-09T10:00:00Z"
    }