"""
Lambda 関数共通の HTTP ユーティリティ。

外部 API への全リクエストは http_get_json_with_retry を経由します。
主な機能：
- ジッター付き指数バックオフによるリトライ
- 一時的エラー（429 / 5xx / ネットワーク障害）のみリトライ対象とし、
  4xx（認証失敗・バリデーションエラー）は即時例外送出
- 外部依存を持たず stdlib のみで実装（Lambda Layer の軽量化）
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
) -> Dict[str, Any]:
    last_err: Optional[Exception] = None
    for i in range(attempts):
        try:
            req = Request(url=url, headers=headers, method="GET")
            with urlopen(req, timeout=timeout_s) as resp:
                parsed = json.loads(resp.read().decode("utf-8"))
                return dict(parsed) if isinstance(parsed, dict) else {"data": parsed}
        except HTTPError as e:
            last_err = e
            # 429・5xx はリトライ対象。4xx（認証失敗等）は即時 re-raise して上位に任せる。
            if e.code not in (429, 500, 502, 503, 504) or i == attempts - 1:
                raise
        except (URLError, TimeoutError) as e:
            last_err = e
            if i == attempts - 1:
                raise

        # ジッター（± 0.2s のランダム揺らぎ）を加えてサンダーリング・ハード問題を緩和
        time.sleep(0.3 * (2.5**i) + random.random() * 0.2)

    if last_err:
        raise last_err
    raise RuntimeError("リトライ上限到達：リクエスト失敗")
