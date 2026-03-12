from typing import Dict, Any, Optional

def parse_observation(data: Dict[str, Any], station_id: str) -> Dict[str, Any]:
    """
    気象データをAPIレスポンス用に整形する。
    station_id は Lambda 側で決定されたものを必ず使用する。
    """
    return {
        "station_id": station_id,
        "temperature": _to_float(data.get("temperature")),
        "humidity": _to_float(data.get("humidity")),
        "timestamp": data.get("timestamp"),
        "error": None
    }

def _to_float(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (ValueError, TypeError):
        return None