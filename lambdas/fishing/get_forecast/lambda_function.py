import json
import os
import random
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

import boto3
from botocore.exceptions import ClientError

from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso8601(s: Optional[str]) -> Optional[datetime]:
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _cache_key(office_code: str, day_utc: datetime) -> str:
    return f"forecast:jma:{office_code}:{day_utc.strftime('%Y-%m-%d')}"


def _dynamodb_table(name: str):
    return boto3.resource("dynamodb").Table(name)


def _get_cached(table_name: str, key: str) -> Optional[Dict[str, Any]]:
    try:
        resp = _dynamodb_table(table_name).get_item(Key={"cache_key": key})
        item = resp.get("Item")
        if isinstance(item, dict) and isinstance(item.get("payload"), dict):
            return item["payload"]
        return None
    except ClientError:
        return None


def _put_cached(table_name: str, key: str, ttl_epoch: int, payload: Dict[str, Any]) -> None:
    item = {
        "cache_key": key,
        "ttl_epoch": ttl_epoch,
        "payload": payload,
        "cached_at_epoch": int(time.time()),
    }
    _dynamodb_table(table_name).put_item(Item=item)


def _http_get_json_with_retry(url: str, headers: Dict[str, str], timeout_s: int = 8, attempts: int = 3) -> Any:
    last_err: Optional[Exception] = None
    for i in range(attempts):
        try:
            req = Request(url=url, headers=headers, method="GET")
            with urlopen(req, timeout=timeout_s) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw)
        except HTTPError as e:
            last_err = e
            retryable = e.code in (429, 500, 502, 503, 504)
            if not retryable or i == attempts - 1:
                raise
        except (URLError, TimeoutError) as e:
            last_err = e
            if i == attempts - 1:
                raise

        base = 0.3 * (2.5**i)
        time.sleep(base + random.random() * 0.2)
    if last_err:
        raise last_err
    raise RuntimeError("request failed")


def _guess_office_code(lat: float, lon: float) -> str:
    """
    Portfolio-friendly heuristic: choose nearest of a few major offices.
    You can extend this mapping later without changing the API contract.
    """
    candidates: Tuple[Tuple[str, float, float], ...] = (
        ("130000", 35.681236, 139.767125),  # Tokyo
        ("270000", 34.702485, 135.495951),  # Osaka
        ("016000", 43.068661, 141.350755),  # Sapporo (Ishikari/Sorachi/Shiribeshi)
    )

    best = candidates[0][0]
    best_d = float("inf")

    from math import radians, sin, cos, sqrt, atan2

    for code, clat, clon in candidates:
        dlat = radians(clat - lat)
        dlon = radians(clon - lon)
        a = sin(dlat / 2) ** 2 + cos(radians(lat)) * cos(radians(clat)) * sin(dlon / 2) ** 2
        c = 2 * atan2(sqrt(a), sqrt(1 - a))
        dist_km = 6371.0 * c
        if dist_km < best_d:
            best_d = dist_km
            best = code
    return best


def _jma_forecast_request(office_code: str) -> Any:
    url = f"https://www.jma.go.jp/bosai/forecast/data/forecast/{office_code}.json"
    return _http_get_json_with_retry(
        url=url,
        headers={"Accept": "application/json", "User-Agent": "ai-data-analyst/1.0"},
        timeout_s=8,
        attempts=3,
    )


def _normalize_jma(resp: Any) -> Dict[str, Any]:
    """
    JMA forecast response is a list of forecast blocks.
    We keep it small and stable for AgentCore: headline + first area's weather + pop.
    """
    if not isinstance(resp, list) or not resp:
        return {"headline": None, "area": None, "weather": None, "pops": []}

    block0 = resp[0] if isinstance(resp[0], dict) else {}
    headline = block0.get("headlineText")
    report_dt = block0.get("reportDatetime")
    publishing_office = block0.get("publishingOffice")

    time_series = block0.get("timeSeries")
    if not isinstance(time_series, list) or not time_series:
        return {
            "headline": headline,
            "area": None,
            "weather": None,
            "pops": [],
            "reportDatetime": report_dt,
            "publishingOffice": publishing_office,
        }

    # Usually timeSeries[0] includes weather, [1] includes pops (precip prob).
    ts_weather = time_series[0] if len(time_series) > 0 and isinstance(time_series[0], dict) else {}
    ts_pop = time_series[1] if len(time_series) > 1 and isinstance(time_series[1], dict) else {}

    def _first_area(ts: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        areas = ts.get("areas")
        if isinstance(areas, list) and areas and isinstance(areas[0], dict):
            return areas[0]
        return None

    area_w = _first_area(ts_weather) or {}
    area_p = _first_area(ts_pop) or {}

    area_name = (area_w.get("area") or {}).get("name") if isinstance(area_w.get("area"), dict) else None
    weathers = area_w.get("weathers")
    weather = weathers[0] if isinstance(weathers, list) and weathers else None

    pops = area_p.get("pops")
    pop_times = ts_pop.get("timeDefines")
    pop_items = []
    if isinstance(pops, list) and isinstance(pop_times, list):
        for t, p in zip(pop_times, pops):
            pop_items.append({"time": t, "pop": p})

    return {
        "headline": headline,
        "area": area_name,
        "weather": weather,
        "pops": pop_items,
        "reportDatetime": report_dt,
        "publishingOffice": publishing_office,
    }


def lambda_handler(event, context):
    requested_at = _utc_now()

    lat_raw = (event or {}).get("lat") if isinstance(event, dict) else None
    lon_raw = (event or {}).get("lon") if isinstance(event, dict) else None
    try:
        lat = float(lat_raw)
        lon = float(lon_raw)
    except Exception:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": "lat/lon are required numbers"}, ensure_ascii=False),
        }

    provider = os.environ.get("FORECAST_PROVIDER", "jma").lower()
    cache_table = os.environ.get("CACHE_TABLE", "")

    start_at = _parse_iso8601((event or {}).get("start_at")) if isinstance(event, dict) else None
    anchor = start_at or requested_at
    day = anchor.replace(hour=0, minute=0, second=0, microsecond=0)

    office_default = os.environ.get("JMA_OFFICE_CODE_DEFAULT", "").strip()
    office_code = office_default or _guess_office_code(lat, lon)

    key = _cache_key(office_code, day)
    ttl_epoch = int((day + timedelta(days=2)).timestamp())

    if cache_table:
        cached = _get_cached(cache_table, key)
        if cached is not None:
            cached.setdefault("cache", {})
            cached["cache"].update({"hit": True, "cache_key": key})
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps(cached, ensure_ascii=False),
            }

    if provider in ("mock", "local"):
        payload = {
            "provider": "mock",
            "requested_at": requested_at.isoformat(),
            "lat": lat,
            "lon": lon,
            "office_code": office_code,
            "forecast": {"headline": "mock forecast", "area": None, "weather": None, "pops": []},
            "cache": {"hit": False, "cache_key": key},
        }
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(payload, ensure_ascii=False),
        }

    if provider != "jma":
        payload = {
            "provider": provider,
            "requested_at": requested_at.isoformat(),
            "lat": lat,
            "lon": lon,
            "office_code": office_code,
            "error": f"unsupported provider: {provider}",
            "cache": {"hit": False, "cache_key": key},
        }
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(payload, ensure_ascii=False),
        }

    try:
        resp = _jma_forecast_request(office_code)
        normalized = _normalize_jma(resp)
        payload = {
            "provider": "jma",
            "requested_at": requested_at.isoformat(),
            "lat": lat,
            "lon": lon,
            "office_code": office_code,
            "forecast": normalized,
            "cache": {"hit": False, "cache_key": key},
        }
        if cache_table:
            _put_cached(cache_table, key, ttl_epoch, payload)
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(payload, ensure_ascii=False),
        }
    except Exception as e:
        payload = {
            "provider": "jma",
            "requested_at": requested_at.isoformat(),
            "lat": lat,
            "lon": lon,
            "office_code": office_code,
            "error": str(e)[:500],
            "cache": {"hit": False, "cache_key": key},
        }
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(payload, ensure_ascii=False),
        }

