"""
Tests for fishing_proxy Lambda (API Gateway entry point).

Coverage:
- Input validation (lat/lon range, missing fields, malformed JSON)
- Step Functions status handling: SUCCEEDED / FAILED / TIMED_OUT / ABORTED
- Trace ID and latency injection
- Optional field forwarding
"""
import json
import uuid
from unittest.mock import patch

import pytest

_LAMBDA = "lambdas/api_proxy/fishing_proxy"
_SM_ARN = "arn:aws:states:ap-northeast-1:123456789012:stateMachine:test"


class _FakeSfnClient:
    """Configurable fake that returns an arbitrary SFN response dict."""
    def __init__(self, sfn_response: dict):
        self._response = sfn_response

    def start_sync_execution(self, **kwargs):
        return self._response


def _sfn_ok(output: dict) -> dict:
    return {"status": "SUCCEEDED", "output": json.dumps(output)}


def _sfn_failed(cause: str = "Lambda raised an error") -> dict:
    return {"status": "FAILED", "error": "States.TaskFailed", "cause": cause}


def _sfn_timed_out() -> dict:
    return {"status": "TIMED_OUT", "cause": "Execution timed out after 30 seconds"}


def _event(body=None):
    if body is None:
        return {}
    if isinstance(body, dict):
        body = json.dumps(body)
    return {"body": body}


class TestFishingProxyInputValidation:
    def _lf(self, load_lambda, monkeypatch):
        monkeypatch.setenv("FISHING_STATE_MACHINE_ARN", _SM_ARN)
        return load_lambda(_LAMBDA)

    def test_valid_request_returns_200(self, load_lambda, monkeypatch, lambda_context):
        sfn_output = {
            "summary": "good", "score": {"value": 80, "label": "great"},
            "season": {"month": 4, "label": "spring"},
            "best_windows": [], "recommended_tactics": [],
            "risk_and_safety": [], "evidence": [],
        }
        lf = self._lf(load_lambda, monkeypatch)
        with patch.object(lf, "_sfn", _FakeSfnClient(_sfn_ok(sfn_output))):
            resp = lf.lambda_handler(_event({"lat": 35.68, "lon": 139.77}), lambda_context)
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert "trace_id" in body
        assert "latency_ms" in body

    def test_invalid_json_returns_400(self, load_lambda, monkeypatch, lambda_context):
        lf = self._lf(load_lambda, monkeypatch)
        resp = lf.lambda_handler({"body": "{not valid json}"}, lambda_context)
        assert resp["statusCode"] == 400

    def test_lat_out_of_range_returns_400(self, load_lambda, monkeypatch, lambda_context):
        lf = self._lf(load_lambda, monkeypatch)
        resp = lf.lambda_handler(_event({"lat": 9999, "lon": 139.0}), lambda_context)
        assert resp["statusCode"] == 400
        body = json.loads(resp["body"])
        assert body["error"] == "validation failed"
        assert any(e["loc"] == ["lat"] for e in body["detail"])

    def test_lon_out_of_range_returns_400(self, load_lambda, monkeypatch, lambda_context):
        lf = self._lf(load_lambda, monkeypatch)
        resp = lf.lambda_handler(_event({"lat": 35.0, "lon": -999.0}), lambda_context)
        assert resp["statusCode"] == 400

    def test_missing_lat_returns_400(self, load_lambda, monkeypatch, lambda_context):
        lf = self._lf(load_lambda, monkeypatch)
        resp = lf.lambda_handler(_event({"lon": 139.0}), lambda_context)
        assert resp["statusCode"] == 400

    def test_missing_body_returns_400(self, load_lambda, monkeypatch, lambda_context):
        lf = self._lf(load_lambda, monkeypatch)
        resp = lf.lambda_handler({}, lambda_context)
        assert resp["statusCode"] == 400

    def test_no_state_machine_arn_returns_500(self, load_lambda, monkeypatch, lambda_context):
        monkeypatch.delenv("FISHING_STATE_MACHINE_ARN", raising=False)
        lf = load_lambda(_LAMBDA)
        resp = lf.lambda_handler(_event({"lat": 35.0, "lon": 139.0}), lambda_context)
        assert resp["statusCode"] == 500

    def test_trace_id_is_valid_uuid(self, load_lambda, monkeypatch, lambda_context):
        lf = self._lf(load_lambda, monkeypatch)
        with patch.object(lf, "_sfn", _FakeSfnClient(_sfn_ok({}))):
            resp = lf.lambda_handler(_event({"lat": 35.0, "lon": 139.0}), lambda_context)
        body = json.loads(resp["body"])
        assert "trace_id" in body
        uuid.UUID(body["trace_id"])  # raises if not valid UUID

    def test_optional_fields_forwarded_to_sfn(self, load_lambda, monkeypatch, lambda_context):
        captured = {}

        class CapturingSfn:
            def start_sync_execution(self, **kwargs):
                captured.update(json.loads(kwargs["input"]))
                return _sfn_ok({})

        lf = self._lf(load_lambda, monkeypatch)
        with patch.object(lf, "_sfn", CapturingSfn()):
            lf.lambda_handler(
                _event({"lat": 35.0, "lon": 139.0, "target_species": "aji", "spot_type": "harbor"}),
                lambda_context,
            )
        assert captured.get("target_species") == "aji"
        assert captured.get("spot_type") == "harbor"


# ─────────────────────────────────────────────────────────────────────────────
# Step Functions status handling
# ─────────────────────────────────────────────────────────────────────────────

class TestSfnStatusHandling:
    """
    Verify that non-SUCCEEDED statuses map to correct HTTP error codes and
    that the failure cause is surfaced to the caller.
    """

    def _lf(self, load_lambda, monkeypatch):
        monkeypatch.setenv("FISHING_STATE_MACHINE_ARN", _SM_ARN)
        return load_lambda(_LAMBDA)

    def test_sfn_succeeded_returns_200(self, load_lambda, monkeypatch, lambda_context):
        lf = self._lf(load_lambda, monkeypatch)
        with patch.object(lf, "_sfn", _FakeSfnClient(_sfn_ok({"summary": "ok"}))):
            resp = lf.lambda_handler(_event({"lat": 35.0, "lon": 139.0}), lambda_context)
        assert resp["statusCode"] == 200

    def test_sfn_failed_returns_502(self, load_lambda, monkeypatch, lambda_context):
        """FAILED execution → 502 Bad Gateway with cause in body."""
        lf = self._lf(load_lambda, monkeypatch)
        with patch.object(lf, "_sfn", _FakeSfnClient(_sfn_failed("timeout in get_tide"))):
            resp = lf.lambda_handler(_event({"lat": 35.0, "lon": 139.0}), lambda_context)

        assert resp["statusCode"] == 502
        body = json.loads(resp["body"])
        assert "FAILED" in body["error"]
        assert "timeout in get_tide" in body["cause"]

    def test_sfn_timed_out_returns_504(self, load_lambda, monkeypatch, lambda_context):
        """TIMED_OUT execution → 504 Gateway Timeout."""
        lf = self._lf(load_lambda, monkeypatch)
        with patch.object(lf, "_sfn", _FakeSfnClient(_sfn_timed_out())):
            resp = lf.lambda_handler(_event({"lat": 35.0, "lon": 139.0}), lambda_context)

        assert resp["statusCode"] == 504
        body = json.loads(resp["body"])
        assert "TIMED_OUT" in body["error"]

    def test_sfn_aborted_returns_502(self, load_lambda, monkeypatch, lambda_context):
        """ABORTED execution → 502 (same bucket as FAILED)."""
        lf = self._lf(load_lambda, monkeypatch)
        aborted = {"status": "ABORTED", "cause": "Manual stop"}
        with patch.object(lf, "_sfn", _FakeSfnClient(aborted)):
            resp = lf.lambda_handler(_event({"lat": 35.0, "lon": 139.0}), lambda_context)

        assert resp["statusCode"] == 502
        body = json.loads(resp["body"])
        assert "ABORTED" in body["error"]

    def test_trace_id_present_in_error_response(self, load_lambda, monkeypatch, lambda_context):
        """Even on error, trace_id must be returned for end-to-end correlation."""
        lf = self._lf(load_lambda, monkeypatch)
        with patch.object(lf, "_sfn", _FakeSfnClient(_sfn_failed())):
            resp = lf.lambda_handler(_event({"lat": 35.0, "lon": 139.0}), lambda_context)

        body = json.loads(resp["body"])
        assert "trace_id" in body
        uuid.UUID(body["trace_id"])
