"""
Lambda / Step Functions ペイロード処理の共通ユーティリティ。

Step Functions の lambda:invoke アクションは Lambda レスポンスを以下のエンベロープで包む：
    {"Payload": {"statusCode": 200, "body": "{...}"}, "ExecutedVersion": "$LATEST"}

unwrap_lambda_proxy は SFN エンベロープと API Gateway プロキシレスポンス形式の両方を
再帰的に展開し、後続 Lambda が純粋な dict を受け取れるようにする。
これにより各 Lambda は SFN との連携詳細を意識せず、ビジネスロジックに集中できる。
"""
import json
from typing import Any, Dict


def try_parse_json(s: Any) -> Any:
    if not isinstance(s, str):
        return s
    s = s.strip()
    if not s or not (s.startswith("{") or s.startswith("[")):
        return s
    try:
        return json.loads(s)
    except Exception:
        return s


def unwrap_lambda_proxy(obj: Any) -> Any:
    if isinstance(obj, dict):
        if "statusCode" in obj and "body" in obj:
            return try_parse_json(obj.get("body"))
        if "Payload" in obj and len(obj) <= 3:
            return unwrap_lambda_proxy(obj.get("Payload"))
        return {k: unwrap_lambda_proxy(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [unwrap_lambda_proxy(v) for v in obj]
    return obj


def json_response(
    status_code: int,
    body: Dict[str, Any],
    *,
    cors: bool = False,
) -> Dict[str, Any]:
    """
    API Gateway プロキシ形式のレスポンスを返す。

    cors=True のときはブラウザ（Flutter Web 等）からのクロスオリジン呼び出し向けに
    Access-Control-* ヘッダーを付与する。Step Functions から直接呼ぶ Lambda では False のまま。
    """
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if cors:
        # ブラウザの preflight（OPTIONS）後の本レスポンスでも CORS を返す必要がある。
        headers["Access-Control-Allow-Origin"] = "*"
        headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
        headers["Access-Control-Allow-Methods"] = "POST,OPTIONS"
    return {
        "statusCode": status_code,
        "headers": headers,
        "body": json.dumps(body, ensure_ascii=False),
    }
