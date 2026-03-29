"""
Tests for the fishing inference Lambda.

Coverage targets:
- _invoke_agentcore: valid JSON response, non-JSON response, Bedrock ClientError
- _emit_score_metric: CloudWatch error is logged (non-fatal, non-blocking)
- lambda_handler: mock-provider path, bedrock-agentcore path
"""
import json
import logging
from unittest.mock import MagicMock, patch

import botocore.exceptions
import pytest

_LAMBDA = "lambdas/fishing/infer"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_bedrock_response(text: str):
    """Build a minimal invoke_agent response whose .completion is an iterable."""
    chunk = {"chunk": {"bytes": text.encode("utf-8")}}
    return {"completion": [chunk]}


def _make_context():
    ctx = MagicMock()
    ctx.aws_request_id = "test-request-id"
    return ctx


def _minimal_facts():
    return {
        "requested_at": "2026-01-01T00:00:00+00:00",
        "location": {"lat": 35.0, "lon": 139.0},
        "season": {"month": 1, "label": "winter"},
        "intent": {"target_species": None, "spot_type": None, "start_at": None},
        "station": None,
        "extras": None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# _invoke_agentcore
# ─────────────────────────────────────────────────────────────────────────────

class TestInvokeAgentcore:
    """
    Bedrock boundary: three scenarios defined by the original spec.
    """

    def _setup_env(self, monkeypatch, load_lambda):
        monkeypatch.setenv("BEDROCK_AGENT_ID", "AGENTID01")
        monkeypatch.setenv("BEDROCK_AGENT_ALIAS_ID", "ALIASID01")
        monkeypatch.setenv("INFERENCE_PROVIDER", "bedrock-agentcore")
        return load_lambda(_LAMBDA)

    # ── Case 1: agent returns valid JSON ────────────────────────────────────
    def test_valid_json_response_is_parsed(self, load_lambda, monkeypatch):
        """When Bedrock returns well-formed JSON, _invoke_agentcore returns a dict."""
        lf = self._setup_env(monkeypatch, load_lambda)

        expected = {
            "summary": "Good fishing day",
            "score": {"value": 82, "label": "excellent"},
            "season": {"month": 4, "label": "spring"},
            "best_windows": ["06:00–08:00"],
            "recommended_tactics": ["topwater lure"],
            "risk_and_safety": [],
            "evidence": ["Wind < 5m/s"],
        }
        bedrock_resp = _make_bedrock_response(json.dumps(expected))

        with patch.object(lf, "_bedrock_agent") as mock_client:
            mock_client.invoke_agent.return_value = bedrock_resp
            result = lf._invoke_agentcore(_minimal_facts(), _make_context())

        assert result["summary"] == "Good fishing day"
        assert result["score"]["value"] == 82
        assert result["best_windows"] == ["06:00–08:00"]

    # ── Case 2: agent returns non-JSON text ─────────────────────────────────
    def test_non_json_response_returns_fallback_structure(self, load_lambda, monkeypatch):
        """When agent output is not JSON, a safe fallback dict is returned (no exception)."""
        lf = self._setup_env(monkeypatch, load_lambda)

        bedrock_resp = _make_bedrock_response("Sorry, I cannot provide advice right now.")

        with patch.object(lf, "_bedrock_agent") as mock_client:
            mock_client.invoke_agent.return_value = bedrock_resp
            result = lf._invoke_agentcore(_minimal_facts(), _make_context())

        assert isinstance(result, dict)
        assert "summary" in result
        assert result["score"]["label"] == "unstructured"
        assert any("not valid JSON" in ev for ev in result["evidence"])

    # ── Case 3: Bedrock raises ClientError ──────────────────────────────────
    def test_bedrock_client_error_propagates(self, load_lambda, monkeypatch):
        """ClientError from invoke_agent must propagate so the Step Function marks FAILED."""
        lf = self._setup_env(monkeypatch, load_lambda)

        error_response = {
            "Error": {"Code": "ServiceQuotaExceededException", "Message": "Too many requests"},
        }
        exc = botocore.exceptions.ClientError(error_response, "InvokeAgent")

        with patch.object(lf, "_bedrock_agent") as mock_client:
            mock_client.invoke_agent.side_effect = exc
            with pytest.raises(botocore.exceptions.ClientError) as exc_info:
                lf._invoke_agentcore(_minimal_facts(), _make_context())

        assert exc_info.value.response["Error"]["Code"] == "ServiceQuotaExceededException"

    # ── Missing env vars ────────────────────────────────────────────────────
    def test_missing_agent_id_raises_runtime_error(self, load_lambda, monkeypatch):
        """RuntimeError is raised when BEDROCK_AGENT_ID is absent."""
        monkeypatch.delenv("BEDROCK_AGENT_ID", raising=False)
        monkeypatch.delenv("BEDROCK_AGENT_ALIAS_ID", raising=False)
        lf = load_lambda(_LAMBDA)

        with pytest.raises(RuntimeError, match="BEDROCK_AGENT_ID"):
            lf._invoke_agentcore(_minimal_facts(), _make_context())


# ─────────────────────────────────────────────────────────────────────────────
# _emit_score_metric
# ─────────────────────────────────────────────────────────────────────────────

class TestEmitScoreMetric:
    """
    CloudWatch boundary: metric emission must be non-blocking and non-silent.
    """

    def _load(self, load_lambda, monkeypatch):
        monkeypatch.setenv("BEDROCK_AGENT_ID", "AGENTID01")
        monkeypatch.setenv("BEDROCK_AGENT_ALIAS_ID", "ALIASID01")
        return load_lambda(_LAMBDA)

    # ── Happy path ──────────────────────────────────────────────────────────
    def test_happy_path_calls_put_metric_data(self, load_lambda, monkeypatch):
        """put_metric_data is invoked with the correct namespace and value."""
        lf = self._load(load_lambda, monkeypatch)

        with patch.object(lf, "_cloudwatch") as mock_cw:
            lf._emit_score_metric({"score": {"value": 75}})

        mock_cw.put_metric_data.assert_called_once()
        call_kwargs = mock_cw.put_metric_data.call_args.kwargs
        assert call_kwargs["Namespace"] == "FishingAdvice/Inference"
        metric = call_kwargs["MetricData"][0]
        assert metric["MetricName"] == "AdviceScore"
        assert metric["Value"] == 75.0

    # ── Non-numeric score is silently skipped ───────────────────────────────
    def test_non_numeric_score_skips_metric(self, load_lambda, monkeypatch):
        """If score.value is not a number, put_metric_data must NOT be called."""
        lf = self._load(load_lambda, monkeypatch)

        with patch.object(lf, "_cloudwatch") as mock_cw:
            lf._emit_score_metric({"score": {"value": "n/a"}})

        mock_cw.put_metric_data.assert_not_called()

    # ── CloudWatch error is logged, not re-raised ────────────────────────────
    def test_cloudwatch_error_is_logged_not_raised(self, load_lambda, monkeypatch, caplog):
        """
        When CloudWatch raises an exception:
        - _emit_score_metric must NOT raise (main thread stays alive).
        - A WARNING log entry must be emitted (error is not silently swallowed).
        """
        lf = self._load(load_lambda, monkeypatch)

        error_response = {"Error": {"Code": "InternalFailure", "Message": "CW down"}}
        exc = botocore.exceptions.ClientError(error_response, "PutMetricData")

        with patch.object(lf, "_cloudwatch") as mock_cw:
            mock_cw.put_metric_data.side_effect = exc
            with caplog.at_level(logging.WARNING):
                # Must NOT raise
                lf._emit_score_metric({"score": {"value": 60}})

        assert any("AdviceScore" in r.message or "metric" in r.message.lower() for r in caplog.records), \
            "Expected a warning log mentioning the metric failure"

    # ── Missing score key is silently skipped ───────────────────────────────
    def test_missing_score_key_skips_metric(self, load_lambda, monkeypatch):
        lf = self._load(load_lambda, monkeypatch)

        with patch.object(lf, "_cloudwatch") as mock_cw:
            lf._emit_score_metric({})  # no "score" key

        mock_cw.put_metric_data.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# lambda_handler (smoke tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestLambdaHandlerPaths:
    """End-to-end smoke tests through lambda_handler."""

    def _mock_event(self):
        return {
            "lat": 35.0, "lon": 139.0,
            "station": "tokyo",
            "extras": [],
        }

    def test_mock_provider_returns_200_without_bedrock(self, load_lambda, monkeypatch, lambda_context):
        """INFERENCE_PROVIDER=mock must return 200 without calling Bedrock."""
        monkeypatch.setenv("INFERENCE_PROVIDER", "mock")
        lf = load_lambda(_LAMBDA)

        with patch.object(lf, "_bedrock_agent") as mock_client, \
             patch.object(lf, "_cloudwatch"):
            resp = lf.lambda_handler(self._mock_event(), lambda_context)
            mock_client.invoke_agent.assert_not_called()

        assert resp["statusCode"] == 200
        body = __import__("json").loads(resp["body"])
        assert body["score"]["label"] == "mock"

    def test_bedrock_provider_calls_invoke_agent(self, load_lambda, monkeypatch, lambda_context):
        """INFERENCE_PROVIDER=bedrock-agentcore must delegate to _invoke_agentcore."""
        monkeypatch.setenv("INFERENCE_PROVIDER", "bedrock-agentcore")
        monkeypatch.setenv("BEDROCK_AGENT_ID", "AGENTID01")
        monkeypatch.setenv("BEDROCK_AGENT_ALIAS_ID", "ALIASID01")
        lf = load_lambda(_LAMBDA)

        advice = {
            "summary": "Great day", "score": {"value": 90, "label": "excellent"},
            "season": {"month": 6, "label": "summer"},
            "best_windows": [], "recommended_tactics": [],
            "risk_and_safety": [], "evidence": [],
        }
        bedrock_resp = _make_bedrock_response(json.dumps(advice))

        with patch.object(lf, "_bedrock_agent") as mock_ba, \
             patch.object(lf, "_cloudwatch"):
            mock_ba.invoke_agent.return_value = bedrock_resp
            resp = lf.lambda_handler(self._mock_event(), lambda_context)
            mock_ba.invoke_agent.assert_called_once()

        assert resp["statusCode"] == 200
        body = __import__("json").loads(resp["body"])
        assert body["summary"] == "Great day"
