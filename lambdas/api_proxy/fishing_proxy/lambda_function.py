import json
import os
import time
import uuid
from typing import Any, Dict, Optional

import boto3


def _json_response(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, ensure_ascii=False),
    }


def _parse_body(event: Dict[str, Any]) -> Dict[str, Any]:
    body = event.get("body")
    if body is None:
        return {}
    if isinstance(body, dict):
        return body
    if isinstance(body, str) and body.strip():
        try:
            return json.loads(body)
        except Exception:
            fixed = (
                body.replace("{lat:", '{"lat":')
                .replace(",lon:", ',"lon":')
                .replace(" lat:", ' "lat":')
                .replace(" lon:", ' "lon":')
            )
            return json.loads(fixed)
    return {}


def lambda_handler(event, context):
    trace_id = str(uuid.uuid4())
    t0 = time.time()

    try:
        body = _parse_body(event)
        lat = float(body.get("lat"))
        lon = float(body.get("lon"))
    except Exception:
        return _json_response(400, {"trace_id": trace_id, "error": "lat and lon are required numbers"})

    sm_arn = os.environ.get("FISHING_STATE_MACHINE_ARN")
    if not sm_arn:
        return _json_response(500, {"trace_id": trace_id, "error": "FISHING_STATE_MACHINE_ARN not set"})

    sfn = boto3.client("stepfunctions")
    input_obj = {
        "lat": lat,
        "lon": lon,
        "trace_id": trace_id,
        "target_species": body.get("target_species"),
        "spot_type": body.get("spot_type"),
        "start_at": body.get("start_at"),
    }

    resp = sfn.start_sync_execution(stateMachineArn=sm_arn, input=json.dumps(input_obj, ensure_ascii=False))
    output_raw: Optional[str] = resp.get("output")
    elapsed_ms = int((time.time() - t0) * 1000)

    try:
        output_obj = json.loads(output_raw) if output_raw else {}
        payload = output_obj.get("Payload") or output_obj.get("payload") or output_obj
        if isinstance(payload, dict) and "body" in payload and isinstance(payload["body"], str):
            try:
                result = json.loads(payload["body"])
                if isinstance(result, dict):
                    result.setdefault("trace_id", trace_id)
                    result.setdefault("latency_ms", elapsed_ms)
                return _json_response(200, result if isinstance(result, dict) else {"result": result})
            except Exception:
                return _json_response(200, {"trace_id": trace_id, "latency_ms": elapsed_ms, "raw": payload["body"]})
        if isinstance(payload, dict):
            payload["trace_id"] = payload.get("trace_id", trace_id)
            payload["latency_ms"] = elapsed_ms
            return _json_response(200, payload)
    except Exception:
        pass

    return _json_response(200, {"trace_id": trace_id, "latency_ms": elapsed_ms, "raw_output": output_raw})

