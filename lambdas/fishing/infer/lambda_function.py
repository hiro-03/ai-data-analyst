import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import boto3


def _season_label(month: int) -> str:
    if month in (12, 1, 2):
        return "winter"
    if month in (3, 4, 5):
        return "spring"
    if month in (6, 7, 8):
        return "summer"
    return "autumn"


def _try_parse_json(s: Any) -> Any:
    if not isinstance(s, str):
        return s
    s = s.strip()
    if not s:
        return s
    if not (s.startswith("{") or s.startswith("[")):
        return s
    try:
        return json.loads(s)
    except Exception:
        return s


def _unwrap_lambda_proxy(obj: Any) -> Any:
    """
    Step Functions lambda:invoke returns objects that often embed a Lambda proxy response:
      {"statusCode": 200, "body": "{\"k\":1}", ...}
    This function recursively tries to unwrap common shapes so inference gets clean dicts.
    """
    if isinstance(obj, dict):
        # If this is a Lambda proxy response, prefer parsing body
        if "statusCode" in obj and "body" in obj:
            body = _try_parse_json(obj.get("body"))
            return body
        # If this is a Step Functions invoke envelope, unwrap Payload
        if "Payload" in obj and len(obj) <= 3:
            return _unwrap_lambda_proxy(obj.get("Payload"))
        # Otherwise recurse shallowly
        return {k: _unwrap_lambda_proxy(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_unwrap_lambda_proxy(v) for v in obj]
    return obj


def _normalize_extras(extras: Any) -> Any:
    """
    Step Functions Parallel returns an array of branch outputs.
    Convert common branch payloads into a single dict for AgentCore.
    """
    extras = _unwrap_lambda_proxy(extras)
    if not isinstance(extras, list):
        return extras

    merged: Dict[str, Any] = {}
    for item in extras:
        item = _unwrap_lambda_proxy(item)
        if not isinstance(item, dict):
            continue
        if "tide" in item:
            merged["tide"] = item
            continue
        if "marine" in item:
            merged["marine"] = item
            continue
        if "forecast" in item:
            merged["forecast"] = item
            continue
        # fallback bucket
        merged.setdefault("other", []).append(item)
    return merged


def _collect_invoke_agent_completion(resp: Dict[str, Any]) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    bedrock-agent-runtime invoke_agent returns an event stream in resp["completion"].
    Collect the bytes chunks into a single string.
    """
    text_parts = []
    trace = None

    completion = resp.get("completion")
    if completion is None:
        return "", resp

    for event in completion:
        if "chunk" in event:
            chunk = event["chunk"]
            data = chunk.get("bytes")
            if data:
                try:
                    text_parts.append(data.decode("utf-8"))
                except Exception:
                    # best-effort; drop undecodable segments
                    pass
        if "trace" in event:
            trace = event.get("trace")

    return "".join(text_parts).strip(), trace


def _invoke_agentcore(facts: Dict[str, Any], context) -> Dict[str, Any]:
    agent_id = os.environ.get("BEDROCK_AGENT_ID")
    agent_alias_id = os.environ.get("BEDROCK_AGENT_ALIAS_ID")
    if not agent_id or not agent_alias_id:
        raise RuntimeError("BEDROCK_AGENT_ID / BEDROCK_AGENT_ALIAS_ID are required")

    client = boto3.client("bedrock-agent-runtime")
    session_id = getattr(context, "aws_request_id", None) or "session"

    # AgentCore inputText is plain text; we pass a single JSON blob for determinism.
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
            "evidence": "array"
        },
        "rules": [
            "Return JSON only. No markdown. No extra keys.",
            "If some data is missing, reflect uncertainty in evidence."
        ],
    }

    resp = client.invoke_agent(
        agentId=agent_id,
        agentAliasId=agent_alias_id,
        sessionId=session_id,
        inputText=json.dumps(input_payload, ensure_ascii=False),
        enableTrace=True,
    )

    completion_text, _trace = _collect_invoke_agent_completion(resp)
    parsed = _try_parse_json(completion_text)
    if isinstance(parsed, dict):
        return parsed
    # If the agent returned non-JSON, wrap it (keeps API stable)
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
    """
    Fishing inference.
    - Unwrap Step Functions lambda:invoke envelopes
    - Build facts (weather/tide/marine/season)
    - Invoke Amazon Bedrock AgentCore (InvokeAgent)
    """
    now = datetime.now(timezone.utc)
    month = now.month
    season = _season_label(month)

    provider = os.environ.get("INFERENCE_PROVIDER", "bedrock-agentcore").lower()
    unwrapped = _unwrap_lambda_proxy(event)

    # Extract the most useful fields we have at this stage.
    station = _unwrap_lambda_proxy(unwrapped.get("station")) if isinstance(unwrapped, dict) else None
    extras = _normalize_extras(unwrapped.get("extras")) if isinstance(unwrapped, dict) else None
    target_species = unwrapped.get("target_species") if isinstance(unwrapped, dict) else None
    spot_type = unwrapped.get("spot_type") if isinstance(unwrapped, dict) else None
    start_at = unwrapped.get("start_at") if isinstance(unwrapped, dict) else None

    facts: Dict[str, Any] = {
        "requested_at": now.isoformat(),
        "location": {
            "lat": (unwrapped.get("lat") if isinstance(unwrapped, dict) else None),
            "lon": (unwrapped.get("lon") if isinstance(unwrapped, dict) else None),
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
            "evidence": [
                "This is a placeholder response.",
            ],
        }
    else:
        response = _invoke_agentcore(facts, context)

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(response, ensure_ascii=False),
    }

