import json
import os
from datetime import timedelta
from typing import Any, Dict, Optional
from urllib.parse import urlencode

from fishing_common.datetime_utils import parse_iso8601, utc_now
from fishing_common.dynamo_utils import get_cached, put_cached
from fishing_common.http_utils import http_get_json_with_retry
from fishing_common.lambda_utils import json_response


def _cache_key(lat: float, lon: float, hour_utc: Any) -> str:
    return f"marine:openmeteo:{lat:.3f}:{lon:.3f}:{hour_utc.strftime('%Y-%m-%dT%H')}"


def _openmeteo_request(lat: float, lon: float, start: Any, end: Any) -> Dict[str, Any]:
    qs = urlencode(
        {
            "latitude": f"{lat:.6f}",
            "longitude": f"{lon:.6f}",
            "hourly": ",".join(
                ["sea_surface_temperature", "wave_height", "wave_direction", "wave_period"]
            ),
            "start_date": start.strftime("%Y-%m-%d"),
            "end_date": end.strftime("%Y-%m-%d"),
            "timezone": "UTC",
        }
    )
    return http_get_json_with_retry(
        url=f"https://marine-api.open-meteo.com/v1/marine?{qs}",
        headers={"Accept": "application/json", "User-Agent": "ai-data-analyst/1.0"},
    )


def _pick_hourly_point(marine_resp: Dict[str, Any], target_hour: Any) -> Dict[str, Any]:
    hourly = marine_resp.get("hourly") if isinstance(marine_resp, dict) else None
    if not isinstance(hourly, dict):
        return {"point": None, "note": "missing hourly"}

    times = hourly.get("time")
    if not isinstance(times, list):
        return {"point": None, "note": "missing hourly.time"}

    target_key = target_hour.strftime("%Y-%m-%dT%H:00")
    try:
        idx: Optional[int] = times.index(target_key)
    except ValueError:
        idx = None

    def _at(name: str) -> Optional[Any]:
        arr = hourly.get(name)
        if idx is None or not isinstance(arr, list) or idx >= len(arr):
            return None
        return arr[idx]

    return {
        "point": {
            "time": target_key,
            "sea_surface_temperature_c": _at("sea_surface_temperature"),
            "wave_height_m": _at("wave_height"),
            "wave_direction_deg": _at("wave_direction"),
            "wave_period_s": _at("wave_period"),
        },
        "note": None if idx is not None else "target hour not in response",
    }


def lambda_handler(event: Any, context: Any) -> Dict[str, Any]:
    requested_at = utc_now()

    try:
        lat = float((event or {}).get("lat") or "")
        lon = float((event or {}).get("lon") or "")
    except Exception:
        return json_response(400, {"error": "lat/lon are required numbers"})

    provider = os.environ.get("MARINE_PROVIDER", "mock").lower()
    cache_table = os.environ.get("CACHE_TABLE", "")

    anchor = parse_iso8601((event or {}).get("start_at")) or requested_at
    hour = anchor.replace(minute=0, second=0, microsecond=0)
    key = _cache_key(lat, lon, hour)
    ttl_epoch = int((hour + timedelta(days=3)).timestamp())

    if cache_table:
        cached = get_cached(cache_table, key)
        if cached is not None:
            cached.setdefault("cache", {}).update({"hit": True, "cache_key": key})
            return json_response(200, cached)

    base: Dict[str, Any] = {
        "provider": provider,
        "requested_at": requested_at.isoformat(),
        "lat": lat,
        "lon": lon,
        "cache": {"hit": False, "cache_key": key},
    }

    if provider in ("mock", "local"):
        return json_response(
            200,
            {
                **base,
                "marine": {
                    "sea_surface_temperature_c": None,
                    "wave_height_m": None,
                    "wave_direction_deg": None,
                    "wave_period_s": None,
                },
            },
        )

    if provider != "openmeteo":
        return json_response(200, {**base, "error": f"unsupported provider: {provider}"})

    day = hour.replace(hour=0)
    try:
        resp = _openmeteo_request(lat, lon, day, day)
        picked = _pick_hourly_point(resp, hour)
        payload = {
            **base,
            "marine": picked.get("point"),
            "note": picked.get("note"),
            "meta": {"window_utc": {"start": day.date().isoformat(), "end": day.date().isoformat()}},
        }
        if cache_table:
            put_cached(cache_table, key, ttl_epoch, payload)
        return json_response(200, payload)
    except Exception as e:
        return json_response(200, {**base, "error": str(e)[:500]})
