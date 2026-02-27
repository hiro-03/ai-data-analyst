from typing import Dict, Any, Optional

def parse_observation(data: Dict[str, Any], station: str) -> Dict[str, Any]:
    """
    気象データをAPIレスポンス用に整形する。
    """
    return {
        "station": data.get("station", station),
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
