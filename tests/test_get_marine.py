"""
get_marine Lambda のテスト（モックモード、キャッシュヒット/ミス）。
"""
import json
import time
from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import boto3
import pytest
from moto import mock_aws

_LAMBDA = "lambdas/fishing/get_marine"


class TestGetMarineMockMode:
    def test_mock_mode_returns_200(self, load_lambda, monkeypatch, lambda_context):
        monkeypatch.setenv("MARINE_PROVIDER", "mock")
        monkeypatch.setenv("CACHE_TABLE", "")
        lf = load_lambda(_LAMBDA)
        resp = lf.lambda_handler({"lat": 35.0, "lon": 139.0}, lambda_context)
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["provider"] == "mock"
        assert "marine" in body

    def test_missing_lat_returns_400(self, load_lambda, monkeypatch, lambda_context):
        monkeypatch.setenv("MARINE_PROVIDER", "mock")
        monkeypatch.setenv("CACHE_TABLE", "")
        lf = load_lambda(_LAMBDA)
        resp = lf.lambda_handler({"lon": 139.0}, lambda_context)
        assert resp["statusCode"] == 400

    def test_unknown_provider_returns_error(self, load_lambda, monkeypatch, lambda_context):
        monkeypatch.setenv("MARINE_PROVIDER", "unknown")
        monkeypatch.setenv("CACHE_TABLE", "")
        lf = load_lambda(_LAMBDA)
        resp = lf.lambda_handler({"lat": 35.0, "lon": 139.0}, lambda_context)
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert "unsupported" in body.get("error", "")


class TestGetMarineCache:
    def test_cache_hit(self, load_lambda, cache_table_name, monkeypatch, lambda_context):
        monkeypatch.setenv("MARINE_PROVIDER", "openmeteo")
        monkeypatch.setenv("CACHE_TABLE", cache_table_name)

        now = datetime.now(timezone.utc)
        cache_key = f"marine:openmeteo:35.000:139.000:{now.strftime('%Y-%m-%dT%H')}"
        cached = {"provider": "openmeteo", "marine": {"wave_height_m": 0.5}, "cache": {"hit": False}}

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
                "payload_json": json.dumps(cached),
            })
            lf = load_lambda(_LAMBDA)
            resp = lf.lambda_handler({"lat": 35.0, "lon": 139.0}, lambda_context)

        assert resp["statusCode"] == 200
        assert json.loads(resp["body"])["cache"]["hit"] is True

    def test_cache_miss_calls_openmeteo(self, load_lambda, cache_table_name, monkeypatch, lambda_context):
        monkeypatch.setenv("MARINE_PROVIDER", "openmeteo")
        monkeypatch.setenv("CACHE_TABLE", cache_table_name)

        api_body = {"hourly": {"time": [], "sea_surface_temperature": [],
                               "wave_height": [], "wave_direction": [], "wave_period": []}}
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps(api_body).encode()

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
        assert json.loads(resp["body"])["cache"]["hit"] is False
