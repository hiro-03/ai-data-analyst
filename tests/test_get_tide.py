"""
get_tide Lambda のテスト（モックモード、キャッシュヒット/ミス）。
"""
import json
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import boto3
import pytest
from moto import mock_aws

_LAMBDA = "lambdas/fishing/get_tide"


class TestGetTideMockMode:
    def test_mock_mode_returns_200(self, load_lambda, monkeypatch, lambda_context):
        monkeypatch.setenv("TIDE_PROVIDER", "mock")
        monkeypatch.setenv("CACHE_TABLE", "")
        lf = load_lambda(_LAMBDA)
        resp = lf.lambda_handler({"lat": 35.0, "lon": 139.0}, lambda_context)
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["provider"] == "mock"
        assert "tide" in body

    def test_missing_lat_returns_400(self, load_lambda, monkeypatch, lambda_context):
        monkeypatch.setenv("TIDE_PROVIDER", "mock")
        monkeypatch.setenv("CACHE_TABLE", "")
        lf = load_lambda(_LAMBDA)
        resp = lf.lambda_handler({"lon": 139.0}, lambda_context)
        assert resp["statusCode"] == 400

    def test_unknown_provider_returns_error_field(self, load_lambda, monkeypatch, lambda_context):
        monkeypatch.setenv("TIDE_PROVIDER", "nonexistent")
        monkeypatch.setenv("CACHE_TABLE", "")
        lf = load_lambda(_LAMBDA)
        resp = lf.lambda_handler({"lat": 35.0, "lon": 139.0}, lambda_context)
        assert resp["statusCode"] == 200
        assert "error" in json.loads(resp["body"])


class TestGetTideCache:
    def test_cache_hit(self, load_lambda, cache_table_name, monkeypatch, lambda_context):
        monkeypatch.setenv("TIDE_PROVIDER", "stormglass")
        monkeypatch.setenv("CACHE_TABLE", cache_table_name)
        monkeypatch.setenv("STORMGLASS_API_KEY", "dummy")

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cache_key = f"tide:stormglass:35.000:139.000:{today}"
        cached_payload = {
            "provider": "stormglass",
            "tide": {"extremes": [], "next_high": None, "next_low": None},
            "cache": {"hit": False},
        }

        with mock_aws():
            boto3.client("dynamodb", region_name="ap-northeast-1").create_table(
                TableName=cache_table_name,
                AttributeDefinitions=[{"AttributeName": "cache_key", "AttributeType": "S"}],
                KeySchema=[{"AttributeName": "cache_key", "KeyType": "HASH"}],
                BillingMode="PAY_PER_REQUEST",
            )
            boto3.resource("dynamodb", region_name="ap-northeast-1").Table(
                cache_table_name
            ).put_item(Item={
                "cache_key": cache_key,
                "ttl_epoch": int(time.time()) + 86400,
                "payload": cached_payload,
            })

            lf = load_lambda(_LAMBDA)
            resp = lf.lambda_handler({"lat": 35.0, "lon": 139.0}, lambda_context)

        assert resp["statusCode"] == 200
        assert json.loads(resp["body"])["cache"]["hit"] is True

    def test_cache_miss_calls_api(self, load_lambda, cache_table_name, monkeypatch, lambda_context):
        monkeypatch.setenv("TIDE_PROVIDER", "stormglass")
        monkeypatch.setenv("CACHE_TABLE", cache_table_name)
        monkeypatch.setenv("STORMGLASS_API_KEY", "dummy")

        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps({"data": []}).encode()

        with mock_aws(), \
             patch("fishing_common.http_utils.urlopen", return_value=mock_resp), \
             patch("fishing_common.http_utils.time.sleep"):
            boto3.client("dynamodb", region_name="ap-northeast-1").create_table(
                TableName=cache_table_name,
                AttributeDefinitions=[{"AttributeName": "cache_key", "AttributeType": "S"}],
                KeySchema=[{"AttributeName": "cache_key", "KeyType": "HASH"}],
                BillingMode="PAY_PER_REQUEST",
            )
            lf = load_lambda(_LAMBDA)
            resp = lf.lambda_handler({"lat": 35.0, "lon": 139.0}, lambda_context)

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["cache"]["hit"] is False
