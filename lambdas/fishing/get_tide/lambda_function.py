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


def _cache_key(lat: float, lon: float, day_utc: datetime) -> str:
    # Round location to keep cache hit rate high for near-identical requests.
    return f"tide:stormglass:{lat:.3f}:{lon:.3f}:{day_utc.strftime('%Y-%m-%d')}"


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

        # exponential backoff + jitter
        base = 0.3 * (2.5**i)
        time.sleep(base + random.random() * 0.2)
    if last_err:
        raise last_err
    raise RuntimeError("request failed")


def _stormglass_request(api_key: str, lat: float, lon: float, start: datetime, end: datetime) -> Dict[str, Any]:
    base_url = "https://api.stormglass.io/v2/tide/extremes"
    qs = urlencode(
        {
            "lat": f"{lat:.6f}",
            "lng": f"{lon:.6f}",
            "start": str(int(start.timestamp())),
            "end": str(int(end.timestamp())),
        }
    )
    url = f"{base_url}?{qs}"
    return _http_get_json_with_retry(
        url=url,
        headers={
            "Authorization": api_key,
            "Accept": "application/json",
            "User-Agent": "ai-data-analyst/1.0",
        },
        timeout_s=8,
        attempts=3,
    )


def _normalize_extremes(resp: Dict[str, Any]) -> Dict[str, Any]:
    data = resp.get("data") if isinstance(resp, dict) else None
    if not isinstance(data, list):
        return {"extremes": [], "next_high": None, "next_low": None}

    extremes = []
    for e in data:
        if not isinstance(e, dict):
            continue
        extremes.append(
            {
                "time": e.get("time"),
                "type": e.get("type") or e.get("state"),
                "height_m": e.get("height"),
            }
        )

    now = _utc_now()
    next_high = None
    next_low = None
    for x in extremes:
        dt = _parse_iso8601(x.get("time"))
        if dt is None or dt < now:
            continue
        typ = (x.get("type") or "").lower()
        if next_high is None and "high" in typ:
            next_high = x
        if next_low is None and "low" in typ:
            next_low = x
        if next_high is not None and next_low is not None:
            break

    return {"extremes": extremes, "next_high": next_high, "next_low": next_low}


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

    provider = os.environ.get("TIDE_PROVIDER", "mock").lower()
    cache_table = os.environ.get("CACHE_TABLE", "")

    start_at = _parse_iso8601((event or {}).get("start_at")) if isinstance(event, dict) else None
    anchor = start_at or requested_at
    day = anchor.replace(hour=0, minute=0, second=0, microsecond=0)

    key = _cache_key(lat, lon, day)
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
            "tide": {"summary": "mock tide", "extremes": [], "next_high": None, "next_low": None},
            "cache": {"hit": False, "cache_key": key},
        }
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(payload, ensure_ascii=False),
        }

    if provider != "stormglass":
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

    api_key = os.environ.get("STORMGLASS_API_KEY", "").strip()
    if not api_key:
        payload = {
            "provider": "stormglass",
            "requested_at": requested_at.isoformat(),
            "lat": lat,
            "lon": lon,
            "error": "STORMGLASS_API_KEY not set",
            "cache": {"hit": False, "cache_key": key},
        }
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(payload, ensure_ascii=False),
        }

    start = day
    end = day + timedelta(days=1)
    try:
        resp = _stormglass_request(api_key=api_key, lat=lat, lon=lon, start=start, end=end)
        normalized = _normalize_extremes(resp)
        payload = {
            "provider": "stormglass",
            "requested_at": requested_at.isoformat(),
            "lat": lat,
            "lon": lon,
            "tide": normalized,
            "meta": {"window_utc": {"start": start.isoformat(), "end": end.isoformat()}},
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
            "provider": "stormglass",
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

