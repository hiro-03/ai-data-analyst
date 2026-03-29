"""
Shared HTTP utility for Lambda functions.

All external API calls go through http_get_json_with_retry, which provides:
- Exponential backoff with jitter
- Retry only on transient errors (429 / 5xx / network)
"""
import json
import random
import time
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def http_get_json_with_retry(
    url: str,
    headers: Dict[str, str],
    timeout_s: int = 8,
    attempts: int = 3,
) -> Any:
    last_err: Optional[Exception] = None
    for i in range(attempts):
        try:
            req = Request(url=url, headers=headers, method="GET")
            with urlopen(req, timeout=timeout_s) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            last_err = e
            if e.code not in (429, 500, 502, 503, 504) or i == attempts - 1:
                raise
        except (URLError, TimeoutError) as e:
            last_err = e
            if i == attempts - 1:
                raise

        time.sleep(0.3 * (2.5**i) + random.random() * 0.2)

    if last_err:
        raise last_err
    raise RuntimeError("request failed after retries")
