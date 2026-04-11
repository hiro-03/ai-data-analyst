"""
POST /fishing エンドポイントの API Gateway プロキシ Lambda。

責務：
- リクエストボディの厳格なバリデーション・パース（JSON 修復ハックは行わない）
- エンドツーエンド追跡用の trace_id（UUID）の発行
- Step Functions Express ステートマシンの同期実行
- SFN 出力のアンラップと呼び出し元へのレスポンス返却
"""
import json
import os
import time
import uuid
from typing import Any, Dict, Optional

import boto3
from pydantic import ValidationError

from fishing_common.lambda_utils import json_response, unwrap_lambda_proxy
from fishing_common.schemas import FishingRequest


def _extract_advice_dict(unwrapped: Any) -> Optional[Dict[str, Any]]:
    """
    Step Functions の最終出力は Lambda invoke のメタデータ付きオブジェクトになることがある。
    unwrap_lambda_proxy 後も summary がルートに無く Payload 配下だけにあるため、
    クライアント向け JSON では推論結果 dict へ正規化する。
    """
    if not isinstance(unwrapped, dict):
        return None
    score = unwrapped.get("score")
    if isinstance(unwrapped.get("summary"), str) and isinstance(score, dict):
        return unwrapped
    nested = unwrapped.get("Payload")
    if isinstance(nested, dict):
        sc = nested.get("score")
        if isinstance(nested.get("summary"), str) and isinstance(sc, dict):
            return nested
    return None

# モジュールレベルでクライアントを生成：ウォームスタート時に再利用してレイテンシを削減。
_sfn = boto3.client("stepfunctions")


def _parse_body(event: Dict[str, Any]) -> Dict[str, Any]:
    body = event.get("body")
    if body is None:
        return {}
    if isinstance(body, dict):
        return body
    if isinstance(body, str) and body.strip():
        # 不正な JSON は ValueError/JSONDecodeError を送出 → 呼び出し元が 400 を返す
        parsed = json.loads(body)
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def lambda_handler(event: Any, context: Any) -> Dict[str, Any]:
    trace_id = str(uuid.uuid4())
    t0 = time.time()

    try:
        body = _parse_body(event)
        request = FishingRequest.model_validate(body)
    except json.JSONDecodeError as e:
        return json_response(
            400,
            {"trace_id": trace_id, "error": f"invalid JSON: {e}"},
            cors=True,
        )
    except ValidationError as e:
        return json_response(
            400,
            {"trace_id": trace_id, "error": "validation failed", "detail": e.errors()},
            cors=True,
        )

    sm_arn = os.environ.get("FISHING_STATE_MACHINE_ARN")
    if not sm_arn:
        return json_response(
            500,
            {"trace_id": trace_id, "error": "FISHING_STATE_MACHINE_ARN not set"},
            cors=True,
        )

    input_obj = {
        "lat": request.lat,
        "lon": request.lon,
        "trace_id": trace_id,
        "target_species": request.target_species,
        "spot_type": request.spot_type,
        "start_at": request.start_at,
    }

    resp = _sfn.start_sync_execution(
        stateMachineArn=sm_arn,
        input=json.dumps(input_obj, ensure_ascii=False),
    )
    elapsed_ms = int((time.time() - t0) * 1000)

    status = resp.get("status", "UNKNOWN")
    if status != "SUCCEEDED":
        cause = resp.get("cause") or resp.get("error") or f"execution ended with status {status}"
        http_status = 504 if status == "TIMED_OUT" else 502
        return json_response(
            http_status,
            {"trace_id": trace_id, "error": f"state machine {status}", "cause": cause},
            cors=True,
        )

    output_raw: Optional[str] = resp.get("output")
    try:
        output_obj = json.loads(output_raw) if output_raw else {}
        payload = unwrap_lambda_proxy(output_obj)
        advice = _extract_advice_dict(payload)
        if advice is not None:
            payload = advice
        if isinstance(payload, dict):
            payload.setdefault("trace_id", trace_id)
            payload["latency_ms"] = elapsed_ms
            return json_response(200, payload, cors=True)
    except Exception:
        pass

    return json_response(
        200,
        {"trace_id": trace_id, "latency_ms": elapsed_ms, "raw_output": output_raw},
        cors=True,
    )
