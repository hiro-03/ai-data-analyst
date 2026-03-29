"""
Fishing inference Lambda.

Unwraps Step Functions envelopes, assembles facts from tide/marine/forecast,
then calls Amazon Bedrock AgentCore (InvokeAgent) for the final advice.
"""
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import boto3

from fishing_common.lambda_utils import json_response, try_parse_json, unwrap_lambda_proxy

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Module-level clients: reused across warm-start invocations.
_bedrock_agent = boto3.client("bedrock-agent-runtime")
_cloudwatch = boto3.client("cloudwatch")


def _season_label(month: int) -> str:
    if month in (12, 1, 2):
        return "winter"
    if month in (3, 4, 5):
        return "spring"
    if month in (6, 7, 8):
        return "summer"
    return "autumn"


def _normalize_extras(extras: Any) -> Any:
    """
    Step Functions Parallel returns an array of branch outputs.
    Merge into a single dict keyed by data type.
    """
    extras = unwrap_lambda_proxy(extras)
    if not isinstance(extras, list):
        return extras

    merged: Dict[str, Any] = {}
    for item in extras:
        item = unwrap_lambda_proxy(item)
        if not isinstance(item, dict):
            continue
        if "tide" in item:
            merged["tide"] = item
        elif "marine" in item:
            merged["marine"] = item
        elif "forecast" in item:
            merged["forecast"] = item
        else:
            merged.setdefault("other", []).append(item)
    return merged


def _collect_agent_completion(resp: Dict[str, Any]) -> Tuple[str, Optional[Dict[str, Any]]]:
    text_parts = []
    trace = None
    for event in resp.get("completion", []):
        if "chunk" in event:
            data = event["chunk"].get("bytes")
            if data:
                try:
                    text_parts.append(data.decode("utf-8"))
                except Exception:
                    pass
        if "trace" in event:
            trace = event.get("trace")
    return "".join(text_parts).strip(), trace


def _invoke_agentcore(facts: Dict[str, Any], context) -> Dict[str, Any]:
    agent_id = os.environ.get("BEDROCK_AGENT_ID")
    agent_alias_id = os.environ.get("BEDROCK_AGENT_ALIAS_ID")
    if not agent_id or not agent_alias_id:
        raise RuntimeError("BEDROCK_AGENT_ID / BEDROCK_AGENT_ALIAS_ID are required")

    session_id = getattr(context, "aws_request_id", None) or "session"
    input_payload = {
        "task": "fishing_advice",
        "facts": facts,
        "output_schema": {
            "summary": "string",
            "score": {"value": "0-100", "label": "string"},
            "season": {"month": "1-12", "label": "winter|spring|summer|autumn"},
            "best_windows": "array",
            "recommended_tactics": "array",
            "risk_and_safety": "array",
            "evidence": "array",
        },
        "rules": [
            "Return JSON only. No markdown. No extra keys.",
            "If some data is missing, reflect uncertainty in evidence.",
        ],
    }

    resp = _bedrock_agent.invoke_agent(
        agentId=agent_id,
        agentAliasId=agent_alias_id,
        sessionId=session_id,
        inputText=json.dumps(input_payload, ensure_ascii=False),
        enableTrace=True,
    )

    completion_text, _trace = _collect_agent_completion(resp)
    parsed = try_parse_json(completion_text)
    if isinstance(parsed, dict):
        return parsed

    return {
        "summary": str(completion_text)[:2000],
        "score": {"value": 50, "label": "unstructured"},
        "season": {},
        "best_windows": [],
        "recommended_tactics": [],
        "risk_and_safety": [],
        "evidence": ["Agent output was not valid JSON."],
    }


def lambda_handler(event, context):
    now = datetime.now(timezone.utc)
    month = now.month
    season = _season_label(month)

    provider = os.environ.get("INFERENCE_PROVIDER", "bedrock-agentcore").lower()
    unwrapped = unwrap_lambda_proxy(event)

    station = unwrap_lambda_proxy(unwrapped.get("station")) if isinstance(unwrapped, dict) else None
    extras = _normalize_extras(unwrapped.get("extras")) if isinstance(unwrapped, dict) else None
    target_species = unwrapped.get("target_species") if isinstance(unwrapped, dict) else None
    spot_type = unwrapped.get("spot_type") if isinstance(unwrapped, dict) else None
    start_at = unwrapped.get("start_at") if isinstance(unwrapped, dict) else None

    facts: Dict[str, Any] = {
        "requested_at": now.isoformat(),
        "location": {
            "lat": unwrapped.get("lat") if isinstance(unwrapped, dict) else None,
            "lon": unwrapped.get("lon") if isinstance(unwrapped, dict) else None,
        },
        "season": {"month": month, "label": season},
        "intent": {
            "target_species": target_species,
            "spot_type": spot_type,
            "start_at": start_at,
        },
        "station": station,
        "extras": extras,
    }

    if provider in ("mock", "local"):
        response = {
            "summary": "mock fishing advice (set INFERENCE_PROVIDER=bedrock-agentcore for real)",
            "score": {"value": 50, "label": "mock"},
            "season": {"month": month, "label": season},
            "best_windows": [],
            "recommended_tactics": [],
            "risk_and_safety": [],
            "evidence": ["This is a placeholder response."],
        }
    else:
        response = _invoke_agentcore(facts, context)

    _emit_score_metric(response)
    return json_response(200, response)


def _emit_score_metric(response: Dict[str, Any]) -> None:
    """
    Publish AdviceScore to CloudWatch for drift detection.
    Never raises – metrics are best-effort and must not block the main path.
    """
    try:
        score_value = response.get("score", {}).get("value")
        if not isinstance(score_value, (int, float)):
            return
        _cloudwatch.put_metric_data(
            Namespace="FishingAdvice/Inference",
            MetricData=[
                {
                    "MetricName": "AdviceScore",
                    "Value": float(score_value),
                    "Unit": "None",
                }
            ],
        )
    except Exception:
        logger.warning("Failed to emit AdviceScore metric; skipping (non-fatal)", exc_info=True)
