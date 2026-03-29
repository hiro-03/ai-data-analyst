"""
API Gateway proxy Lambda for POST /fishing.

Responsibilities:
- Validate and parse the request body (strict – no JSON repair hacks).
- Attach a trace_id for end-to-end correlation.
- Invoke the Step Functions Express state machine synchronously.
- Unwrap the SFN output and return it to the caller.
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

# Module-level client: reused across warm-start invocations.
_sfn = boto3.client("stepfunctions")


def _parse_body(event: Dict[str, Any]) -> Dict[str, Any]:
    body = event.get("body")
    if body is None:
        return {}
    if isinstance(body, dict):
        return body
    if isinstance(body, str) and body.strip():
        # Raise ValueError/JSONDecodeError on invalid JSON – caller returns 400.
        return json.loads(body)
    return {}


def lambda_handler(event, context):
    trace_id = str(uuid.uuid4())
    t0 = time.time()

    try:
        body = _parse_body(event)
        request = FishingRequest.model_validate(body)
    except json.JSONDecodeError as e:
        return json_response(400, {"trace_id": trace_id, "error": f"invalid JSON: {e}"})
    except ValidationError as e:
        return json_response(400, {"trace_id": trace_id, "error": "validation failed", "detail": e.errors()})

    sm_arn = os.environ.get("FISHING_STATE_MACHINE_ARN")
    if not sm_arn:
        return json_response(500, {"trace_id": trace_id, "error": "FISHING_STATE_MACHINE_ARN not set"})

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
        )

    output_raw: Optional[str] = resp.get("output")
    try:
        output_obj = json.loads(output_raw) if output_raw else {}
        payload = unwrap_lambda_proxy(output_obj)

        if isinstance(payload, dict):
            payload.setdefault("trace_id", trace_id)
            payload["latency_ms"] = elapsed_ms
            return json_response(200, payload)
    except Exception:
        pass

    return json_response(200, {"trace_id": trace_id, "latency_ms": elapsed_ms, "raw_output": output_raw})
