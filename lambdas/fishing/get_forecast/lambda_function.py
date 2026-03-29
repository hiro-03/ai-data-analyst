import json
import os
from datetime import timedelta
from math import atan2, cos, radians, sin, sqrt
from typing import Any, Dict, List, Optional, Tuple

from fishing_common.datetime_utils import parse_iso8601, utc_now
from fishing_common.dynamo_utils import get_cached, put_cached
from fishing_common.http_utils import http_get_json_with_retry
from fishing_common.lambda_utils import json_response

# ---------------------------------------------------------------------------
# JMA office mapping – extend this list without changing the API contract.
# Format: (office_code, lat, lon, label)
# ---------------------------------------------------------------------------
_JMA_OFFICES: Tuple[Tuple[str, float, float, str], ...] = (
    ("016000", 43.068661, 141.350755, "Sapporo"),
    ("020000", 39.703531, 141.152639, "Morioka"),
    ("040000", 38.268215, 140.869356, "Sendai"),
    ("050000", 39.718012, 140.102364, "Akita"),
    ("060000", 38.240422, 140.363592, "Yamagata"),
    ("070000", 37.750149, 140.467522, "Fukushima"),
    ("080000", 36.341810, 140.446800, "Mito"),
    ("090000", 36.565073, 139.883526, "Utsunomiya"),
    ("100000", 36.390668, 139.060413, "Maebashi"),
    ("110000", 35.861227, 139.645445, "Saitama"),
    ("120000", 35.605058, 140.123108, "Chiba"),
    ("130000", 35.681236, 139.767125, "Tokyo"),
    ("140000", 35.447507, 139.642345, "Yokohama"),
    ("150000", 37.902552, 139.023095, "Niigata"),
    ("160000", 36.695290, 137.211338, "Toyama"),
    ("170000", 36.561325, 136.656205, "Kanazawa"),
    ("180000", 36.065219, 136.221641, "Fukui"),
    ("190000", 35.664158, 138.568449, "Kofu"),
    ("200000", 36.651299, 138.181224, "Nagano"),
    ("210000", 35.391227, 136.722291, "Gifu"),
    ("220000", 34.976987, 138.383016, "Shizuoka"),
    ("230000", 35.180188, 136.906565, "Nagoya"),
    ("240000", 34.730514, 136.508591, "Tsu"),
    ("250000", 35.004531, 135.868588, "Otsu"),
    ("260000", 35.021040, 135.755608, "Kyoto"),
    ("270000", 34.702485, 135.495951, "Osaka"),
    ("280000", 34.691269, 135.183073, "Kobe"),
    ("290000", 34.685334, 135.832742, "Nara"),
    ("300000", 34.226034, 135.167506, "Wakayama"),
    ("310000", 35.503846, 134.238267, "Tottori"),
    ("320000", 35.472306, 133.050499, "Matsue"),
    ("330000", 34.661772, 133.934675, "Okayama"),
    ("340000", 34.396560, 132.459595, "Hiroshima"),
    ("350000", 34.185956, 131.470649, "Yamaguchi"),
    ("360000", 34.065697, 134.559297, "Tokushima"),
    ("370000", 34.340149, 134.043444, "Takamatsu"),
    ("380000", 33.841624, 132.765681, "Matsuyama"),
    ("390000", 33.559706, 133.531080, "Kochi"),
    ("400000", 33.606785, 130.418314, "Fukuoka"),
    ("410000", 33.249442, 129.876572, "Saga"),
    ("420000", 32.744839, 129.873756, "Nagasaki"),
    ("430000", 32.789827, 130.741667, "Kumamoto"),
    ("440000", 33.238217, 131.612576, "Oita"),
    ("450000", 31.911089, 131.423855, "Miyazaki"),
    ("460100", 31.560146, 130.557989, "Kagoshima"),
    ("471000", 26.212401, 127.680932, "Naha"),
)


def _guess_office_code(lat: float, lon: float) -> str:
    best_code = _JMA_OFFICES[0][0]
    best_dist = float("inf")

    for code, olat, olon, _label in _JMA_OFFICES:
        dlat = radians(olat - lat)
        dlon = radians(olon - lon)
        a = sin(dlat / 2) ** 2 + cos(radians(lat)) * cos(radians(olat)) * sin(dlon / 2) ** 2
        dist_km = 6371.0 * 2 * atan2(sqrt(a), sqrt(1 - a))
        if dist_km < best_dist:
            best_dist = dist_km
            best_code = code

    return best_code


def _cache_key(office_code: str, day_utc: Any) -> str:
    return f"forecast:jma:{office_code}:{day_utc.strftime('%Y-%m-%d')}"


def _jma_request(office_code: str) -> Any:
    return http_get_json_with_retry(
        url=f"https://www.jma.go.jp/bosai/forecast/data/forecast/{office_code}.json",
        headers={"Accept": "application/json", "User-Agent": "ai-data-analyst/1.0"},
    )


def _normalize_jma(resp: Any) -> Dict[str, Any]:
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

    ts_weather = time_series[0] if isinstance(time_series[0], dict) else {}
    ts_pop = time_series[1] if len(time_series) > 1 and isinstance(time_series[1], dict) else {}

    def _first_area(ts: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        areas = ts.get("areas")
        if isinstance(areas, list) and areas and isinstance(areas[0], dict):
            return areas[0]
        return None

    area_w = _first_area(ts_weather) or {}
    area_p = _first_area(ts_pop) or {}

    area_name = (area_w.get("area") or {}).get("name") if isinstance(area_w.get("area"), dict) else None
    weathers: Optional[List[Any]] = area_w.get("weathers")
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


def lambda_handler(event: Any, context: Any) -> Dict[str, Any]:
    requested_at = utc_now()

    try:
        lat = float((event or {}).get("lat") or "")
        lon = float((event or {}).get("lon") or "")
    except Exception:
        return json_response(400, {"error": "lat/lon are required numbers"})

    provider = os.environ.get("FORECAST_PROVIDER", "jma").lower()
    cache_table = os.environ.get("CACHE_TABLE", "")

    anchor = parse_iso8601((event or {}).get("start_at")) or requested_at
    day = anchor.replace(hour=0, minute=0, second=0, microsecond=0)

    office_default = os.environ.get("JMA_OFFICE_CODE_DEFAULT", "").strip()
    office_code = office_default or _guess_office_code(lat, lon)

    key = _cache_key(office_code, day)
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
        "office_code": office_code,
        "cache": {"hit": False, "cache_key": key},
    }

    if provider in ("mock", "local"):
        return json_response(
            200,
            {**base, "forecast": {"headline": "mock forecast", "area": None, "weather": None, "pops": []}},
        )

    if provider != "jma":
        return json_response(200, {**base, "error": f"unsupported provider: {provider}"})

    try:
        resp = _jma_request(office_code)
        payload = {**base, "forecast": _normalize_jma(resp)}
        if cache_table:
            put_cached(cache_table, key, ttl_epoch, payload)
        return json_response(200, payload)
    except Exception as e:
        return json_response(200, {**base, "error": str(e)[:500]})
