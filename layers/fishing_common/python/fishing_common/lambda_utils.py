"""
Shared utilities for Lambda / Step Functions payload handling.

Step Functions lambda:invoke wraps the Lambda response in a Payload envelope:
    {"Payload": {"statusCode": 200, "body": "{...}"}, "ExecutedVersion": "$LATEST"}

unwrap_lambda_proxy recursively unwraps both the SFN envelope and the API
Gateway proxy response shape so downstream functions receive plain dicts.
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


def json_response(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, ensure_ascii=False),
    }
