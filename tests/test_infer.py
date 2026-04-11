"""
釣り推論 Lambda のテスト。

カバレッジ対象:
- _invoke_agentcore: 正常 JSON、非 JSON、Bedrock ClientError
- _emit_score_metric: CloudWatch エラーはログのみ（致命的でない・ブロックしない）
- lambda_handler: mock プロバイダー経路、bedrock-agentcore 経路
"""
import json
import logging
from unittest.mock import MagicMock, patch

import botocore.exceptions
import pytest

_LAMBDA = "lambdas/fishing/infer"


# ─────────────────────────────────────────────────────────────────────────────
# ヘルパー
# ─────────────────────────────────────────────────────────────────────────────

def _make_bedrock_response(text: str):
    """invoke_agent 応答の最小形。.completion がイテラブルになる。"""
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
    Bedrock 境界: 元仕様で定義された 3 シナリオ。
    """

    def _setup_env(self, monkeypatch, load_lambda):
        monkeypatch.setenv("BEDROCK_AGENT_ID", "AGENTID01")
        monkeypatch.setenv("BEDROCK_AGENT_ALIAS_ID", "ALIASID01")
        monkeypatch.setenv("INFERENCE_PROVIDER", "bedrock-agentcore")
        return load_lambda(_LAMBDA)

    # ── ケース1: エージェントが有効な JSON を返す ────────────────────────────
    def test_valid_json_response_is_parsed(self, load_lambda, monkeypatch):
        """Bedrock が整った JSON を返すとき、_invoke_agentcore は dict を返す。"""
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

    # ── ケース2: 非 JSON テキスト → ValueError → SFN FAILED ────────────────
    def test_non_json_response_raises_value_error(self, load_lambda, monkeypatch):
        """
        エージェント出力が JSON でないとき、_invoke_agentcore は ValueError を出し
        Step Functions が実行を FAILED にし Catch で処理できるようにする。
        黙ってフォールバックを返すとプロンプトずれが隠れ、下流が壊れる。
        """
        lf = self._setup_env(monkeypatch, load_lambda)

        bedrock_resp = _make_bedrock_response("Sorry, I cannot provide advice right now.")

        with patch.object(lf, "_bedrock_agent") as mock_client:
            mock_client.invoke_agent.return_value = bedrock_resp
            with pytest.raises(ValueError, match="non-JSON"):
                lf._invoke_agentcore(_minimal_facts(), _make_context())

    # ── ケース2b: JSON だがスキーマ検証に失敗 ────────────────────────────────
    def test_schema_invalid_json_raises_validation_error(self, load_lambda, monkeypatch):
        """
        Bedrock が JSON を返しても FishingAdviceResponse に違反する場合（例: score.value が範囲外）、
        Pydantic の ValidationError を伝播させ Step Function を FAILED にする。黙って通さない。
        """
        import pydantic

        lf = self._setup_env(monkeypatch, load_lambda)

        # score.value = 999 は [0, 100] の範囲外
        bad_response = {
            "summary": "ok",
            "score": {"value": 999, "label": "broken"},
            "season": {"month": 4, "label": "spring"},
            "best_windows": [], "recommended_tactics": [],
            "risk_and_safety": [], "evidence": [],
        }
        bedrock_resp = _make_bedrock_response(__import__("json").dumps(bad_response))

        with patch.object(lf, "_bedrock_agent") as mock_client:
            mock_client.invoke_agent.return_value = bedrock_resp
            with pytest.raises(pydantic.ValidationError):
                lf._invoke_agentcore(_minimal_facts(), _make_context())

    # ── ケース3: Bedrock が ClientError ────────────────────────────────────
    def test_bedrock_client_error_propagates(self, load_lambda, monkeypatch):
        """invoke_agent の ClientError は伝播し、Step Function が FAILED にする。"""
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

    # ── 環境変数欠落 ────────────────────────────────────────────────────────
    def test_missing_agent_id_raises_runtime_error(self, load_lambda, monkeypatch):
        """BEDROCK_AGENT_ID が無いとき RuntimeError。"""
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
    CloudWatch 境界: メトリクス送信はブロックせず、失敗も黙殺しない。
    """

    def _load(self, load_lambda, monkeypatch):
        monkeypatch.setenv("BEDROCK_AGENT_ID", "AGENTID01")
        monkeypatch.setenv("BEDROCK_AGENT_ALIAS_ID", "ALIASID01")
        return load_lambda(_LAMBDA)

    # ── 正常系 ──────────────────────────────────────────────────────────────
    def test_happy_path_calls_put_metric_data(self, load_lambda, monkeypatch):
        """put_metric_data が正しい Namespace と値で呼ばれる。"""
        lf = self._load(load_lambda, monkeypatch)

        with patch.object(lf, "_cloudwatch") as mock_cw:
            lf._emit_score_metric({"score": {"value": 75}})

        mock_cw.put_metric_data.assert_called_once()
        call_kwargs = mock_cw.put_metric_data.call_args.kwargs
        assert call_kwargs["Namespace"] == "FishingAdvice/Inference"
        metric = call_kwargs["MetricData"][0]
        assert metric["MetricName"] == "AdviceScore"
        assert metric["Value"] == 75.0

    # ── 数値でない score はスキップ ─────────────────────────────────────────
    def test_non_numeric_score_skips_metric(self, load_lambda, monkeypatch):
        """score.value が数値でないとき put_metric_data は呼ばれない。"""
        lf = self._load(load_lambda, monkeypatch)

        with patch.object(lf, "_cloudwatch") as mock_cw:
            lf._emit_score_metric({"score": {"value": "n/a"}})

        mock_cw.put_metric_data.assert_not_called()

    # ── CloudWatch エラーはログのみ、再送出しない ───────────────────────────
    def test_cloudwatch_error_is_logged_not_raised(self, load_lambda, monkeypatch, caplog):
        """
        CloudWatch が例外を出したとき:
        - _emit_score_metric は再送出しない（メインスレッドは継続）。
        - WARNING ログが出る（黙って飲み込まない）。
        """
        lf = self._load(load_lambda, monkeypatch)

        error_response = {"Error": {"Code": "InternalFailure", "Message": "CW down"}}
        exc = botocore.exceptions.ClientError(error_response, "PutMetricData")

        with patch.object(lf, "_cloudwatch") as mock_cw:
            mock_cw.put_metric_data.side_effect = exc
            with caplog.at_level(logging.WARNING):
                # 再送出してはならない
                lf._emit_score_metric({"score": {"value": 60}})

        assert any("AdviceScore" in r.message or "metric" in r.message.lower() for r in caplog.records), \
            "メトリクス失敗を示す WARNING ログが期待される"

    # ── score キー欠落はスキップ ───────────────────────────────────────────
    def test_missing_score_key_skips_metric(self, load_lambda, monkeypatch):
        lf = self._load(load_lambda, monkeypatch)

        with patch.object(lf, "_cloudwatch") as mock_cw:
            lf._emit_score_metric({})  # "score" キーなし

        mock_cw.put_metric_data.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# lambda_handler（スモーク）
# ─────────────────────────────────────────────────────────────────────────────

class TestLambdaHandlerPaths:
    """lambda_handler 経由のエンドツーエンドスモーク。"""

    def _mock_event(self):
        return {
            "lat": 35.0, "lon": 139.0,
            "station": "tokyo",
            "extras": [],
        }

    def test_mock_provider_returns_200_without_bedrock(self, load_lambda, monkeypatch, lambda_context):
        """INFERENCE_PROVIDER=mock は Bedrock を呼ばず 200 を返す。"""
        monkeypatch.setenv("INFERENCE_PROVIDER", "mock")
        lf = load_lambda(_LAMBDA)

        with patch.object(lf, "_bedrock_agent") as mock_client, \
             patch.object(lf, "_cloudwatch"):
            resp = lf.lambda_handler(self._mock_event(), lambda_context)
            mock_client.invoke_agent.assert_not_called()

        assert resp["statusCode"] == 200
        body = __import__("json").loads(resp["body"])
        assert body["score"]["label"] == "mock"
        assert "depth_advice" in body and body["depth_advice"]
        assert "casting_advice" in body and body["casting_advice"]

    def test_bedrock_provider_calls_invoke_agent(self, load_lambda, monkeypatch, lambda_context):
        """INFERENCE_PROVIDER=bedrock-agentcore は _invoke_agentcore に委譲。"""
        monkeypatch.setenv("INFERENCE_PROVIDER", "bedrock-agentcore")
        monkeypatch.setenv("BEDROCK_AGENT_ID", "AGENTID01")
        monkeypatch.setenv("BEDROCK_AGENT_ALIAS_ID", "ALIASID01")
        lf = load_lambda(_LAMBDA)

        advice = {
            "summary": "Great day", "score": {"value": 90, "label": "excellent"},
            "season": {"month": 6, "label": "summer"},
            "best_windows": [], "recommended_tactics": [],
            "risk_and_safety": [], "evidence": [],
            "depth_advice": "mid layer",
            "casting_advice": "30m",
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
