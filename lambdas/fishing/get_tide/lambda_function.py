import json
import os
from datetime import timedelta
from typing import Any, Dict
from urllib.parse import urlencode

from fishing_common.datetime_utils import parse_iso8601, utc_now
from fishing_common.dynamo_utils import get_cached, put_cached
from fishing_common.http_utils import http_get_json_with_retry
from fishing_common.lambda_utils import json_response


def _cache_key(lat: float, lon: float, day_utc) -> str:
    return f"tide:stormglass:{lat:.3f}:{lon:.3f}:{day_utc.strftime('%Y-%m-%d')}"


def _stormglass_request(
    api_key: str, lat: float, lon: float, start, end
) -> Dict[str, Any]:
    qs = urlencode(
        {
            "lat": f"{lat:.6f}",
            "lng": f"{lon:.6f}",
            "start": str(int(start.timestamp())),
            "end": str(int(end.timestamp())),
        }
    )
    return http_get_json_with_retry(
        url=f"https://api.stormglass.io/v2/tide/extremes?{qs}",
        headers={
            "Authorization": api_key,
            "Accept": "application/json",
            "User-Agent": "ai-data-analyst/1.0",
        },
    )


def _normalize_extremes(resp: Dict[str, Any]) -> Dict[str, Any]:
    data = resp.get("data") if isinstance(resp, dict) else None
    if not isinstance(data, list):
        return {"extremes": [], "next_high": None, "next_low": None}

    now = utc_now()
    extremes = []
    next_high = next_low = None

    for e in data:
        if not isinstance(e, dict):
            continue
        ex = {
            "time": e.get("time"),
            "type": e.get("type") or e.get("state"),
            "height_m": e.get("height"),
        }
        extremes.append(ex)
        dt = parse_iso8601(ex.get("time"))
        if dt is not None and dt >= now:
            typ = (ex.get("type") or "").lower()
            if next_high is None and "high" in typ:
                next_high = ex
            if next_low is None and "low" in typ:
                next_low = ex

    return {"extremes": extremes, "next_high": next_high, "next_low": next_low}


def lambda_handler(event, context):
    requested_at = utc_now()

    try:
        lat = float((event or {}).get("lat"))
        lon = float((event or {}).get("lon"))
    except Exception:
        return json_response(400, {"error": "lat/lon are required numbers"})

    provider = os.environ.get("TIDE_PROVIDER", "mock").lower()
    cache_table = os.environ.get("CACHE_TABLE", "")

    anchor = parse_iso8601((event or {}).get("start_at")) or requested_at
    day = anchor.replace(hour=0, minute=0, second=0, microsecond=0)
    key = _cache_key(lat, lon, day)
    ttl_epoch = int((day + timedelta(days=2)).timestamp())

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
            {**base, "tide": {"summary": "mock tide", "extremes": [], "next_high": None, "next_low": None}},
        )

    if provider != "stormglass":
        return json_response(200, {**base, "error": f"unsupported provider: {provider}"})

    api_key = os.environ.get("STORMGLASS_API_KEY", "").strip()
    if not api_key:
        return json_response(200, {**base, "error": "STORMGLASS_API_KEY not set"})

    end = day + timedelta(days=1)
    try:
        resp = _stormglass_request(api_key, lat, lon, day, end)
        payload = {
            **base,
            "tide": _normalize_extremes(resp),
            "meta": {"window_utc": {"start": day.isoformat(), "end": end.isoformat()}},
        }
        if cache_table:
            put_cached(cache_table, key, ttl_epoch, payload)
        return json_response(200, payload)
    except Exception as e:
        return json_response(200, {**base, "error": str(e)[:500]})
