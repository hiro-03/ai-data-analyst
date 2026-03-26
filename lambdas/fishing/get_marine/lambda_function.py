import json
import os
import random
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

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


def _cache_key(lat: float, lon: float, hour_utc: datetime) -> str:
    return f"marine:openmeteo:{lat:.3f}:{lon:.3f}:{hour_utc.strftime('%Y-%m-%dT%H')}"


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


def _openmeteo_marine_request(lat: float, lon: float, start: datetime, end: datetime) -> Dict[str, Any]:
    base_url = "https://marine-api.open-meteo.com/v1/marine"
    qs = urlencode(
        {
            "latitude": f"{lat:.6f}",
            "longitude": f"{lon:.6f}",
            "hourly": ",".join(
                [
                    "sea_surface_temperature",
                    "wave_height",
                    "wave_direction",
                    "wave_period",
                ]
            ),
            "start_date": start.strftime("%Y-%m-%d"),
            "end_date": end.strftime("%Y-%m-%d"),
            "timezone": "UTC",
        }
    )
    url = f"{base_url}?{qs}"
    return _http_get_json_with_retry(
        url=url,
        headers={"Accept": "application/json", "User-Agent": "ai-data-analyst/1.0"},
        timeout_s=8,
        attempts=3,
    )


def _pick_hourly_point(marine_resp: Dict[str, Any], target_hour: datetime) -> Dict[str, Any]:
    hourly = marine_resp.get("hourly") if isinstance(marine_resp, dict) else None
    if not isinstance(hourly, dict):
        return {"point": None, "note": "missing hourly"}

    times = hourly.get("time")
    if not isinstance(times, list):
        return {"point": None, "note": "missing hourly.time"}

    # open-meteo returns time strings like "2026-03-26T13:00"
    target_key = target_hour.strftime("%Y-%m-%dT%H:00")
    try:
        idx = times.index(target_key)
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

    provider = os.environ.get("MARINE_PROVIDER", "mock").lower()
    cache_table = os.environ.get("CACHE_TABLE", "")

    start_at = _parse_iso8601((event or {}).get("start_at")) if isinstance(event, dict) else None
    anchor = start_at or requested_at
    hour = anchor.replace(minute=0, second=0, microsecond=0)

    key = _cache_key(lat, lon, hour)
    ttl_epoch = int((hour + timedelta(days=3)).timestamp())

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
            "marine": {
                "sea_surface_temperature_c": None,
                "wave_height_m": None,
                "wave_direction_deg": None,
                "wave_period_s": None,
            },
            "cache": {"hit": False, "cache_key": key},
        }
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(payload, ensure_ascii=False),
        }

    if provider != "openmeteo":
        payload = {
            "provider": provider,
            "requested_at": requested_at.isoformat(),
            "lat": lat,
            "lon": lon,
            "error": f"unsupported provider: {provider}",
            "cache": {"hit": False, "cache_key": key},
        }
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(payload, ensure_ascii=False),
        }

    # Open-Meteo marine uses date range; request just the anchor day (UTC)
    day = hour.replace(hour=0)
    start = day
    end = day

    try:
        resp = _openmeteo_marine_request(lat=lat, lon=lon, start=start, end=end)
        picked = _pick_hourly_point(resp, hour)
        payload = {
            "provider": "openmeteo",
            "requested_at": requested_at.isoformat(),
            "lat": lat,
            "lon": lon,
            "marine": picked.get("point"),
            "note": picked.get("note"),
            "meta": {"window_utc": {"start": start.date().isoformat(), "end": end.date().isoformat()}},
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
            "provider": "openmeteo",
            "requested_at": requested_at.isoformat(),
            "lat": lat,
            "lon": lon,
            "error": str(e)[:500],
            "cache": {"hit": False, "cache_key": key},
        }
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(payload, ensure_ascii=False),
        }

