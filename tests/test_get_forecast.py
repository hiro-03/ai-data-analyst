"""
Tests for get_forecast Lambda – office code selection, mock mode, cache, JMA API.
"""
import json
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import boto3
import pytest
from moto import mock_aws

_LAMBDA = "lambdas/fishing/get_forecast"


class TestGuessOfficeCode:
    def _fn(self, load_lambda):
        return load_lambda(_LAMBDA)._guess_office_code

    def test_near_tokyo(self, load_lambda):
        assert self._fn(load_lambda)(35.68, 139.77) == "130000"

    def test_near_osaka(self, load_lambda):
        assert self._fn(load_lambda)(34.70, 135.50) == "270000"

    def test_near_sapporo(self, load_lambda):
        assert self._fn(load_lambda)(43.07, 141.35) == "016000"

    def test_near_naha_okinawa(self, load_lambda):
        assert self._fn(load_lambda)(26.21, 127.68) == "471000"

    def test_env_override_takes_precedence(self, load_lambda, monkeypatch, lambda_context):
        monkeypatch.setenv("JMA_OFFICE_CODE_DEFAULT", "999000")
        monkeypatch.setenv("FORECAST_PROVIDER", "mock")
        monkeypatch.setenv("CACHE_TABLE", "")
        lf = load_lambda(_LAMBDA)
        resp = lf.lambda_handler({"lat": 35.68, "lon": 139.77}, lambda_context)
        assert json.loads(resp["body"])["office_code"] == "999000"


class TestGetForecastMockMode:
    def test_mock_mode_returns_200(self, load_lambda, monkeypatch, lambda_context):
        monkeypatch.setenv("FORECAST_PROVIDER", "mock")
        monkeypatch.setenv("CACHE_TABLE", "")
        monkeypatch.delenv("JMA_OFFICE_CODE_DEFAULT", raising=False)
        lf = load_lambda(_LAMBDA)
        resp = lf.lambda_handler({"lat": 35.0, "lon": 139.0}, lambda_context)
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["provider"] == "mock"
        assert "forecast" in body

    def test_missing_lat_returns_400(self, load_lambda, monkeypatch, lambda_context):
        monkeypatch.setenv("FORECAST_PROVIDER", "mock")
        monkeypatch.setenv("CACHE_TABLE", "")
        lf = load_lambda(_LAMBDA)
        resp = lf.lambda_handler({"lon": 139.0}, lambda_context)
        assert resp["statusCode"] == 400


class TestGetForecastJma:
    def test_jma_api_called_on_cache_miss(
        self, load_lambda, cache_table_name, monkeypatch, lambda_context
    ):
        monkeypatch.setenv("FORECAST_PROVIDER", "jma")
        monkeypatch.setenv("CACHE_TABLE", cache_table_name)
        monkeypatch.setenv("JMA_OFFICE_CODE_DEFAULT", "130000")

        jma_body = [{
            "publishingOffice": "気象庁",
            "reportDatetime": "2026-03-28T05:00:00+09:00",
            "headlineText": "",
            "timeSeries": [],
        }]
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps(jma_body).encode()

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
            resp = lf.lambda_handler({"lat": 35.68, "lon": 139.77}, lambda_context)

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["provider"] == "jma"
        assert "forecast" in body

    def test_cache_hit_skips_api(
        self, load_lambda, cache_table_name, monkeypatch, lambda_context
    ):
        monkeypatch.setenv("FORECAST_PROVIDER", "jma")
        monkeypatch.setenv("CACHE_TABLE", cache_table_name)
        monkeypatch.setenv("JMA_OFFICE_CODE_DEFAULT", "130000")

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cache_key = f"forecast:jma:130000:{today}"
        cached = {"provider": "jma", "forecast": {"headline": "cached"}, "cache": {"hit": False}}

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
            resp = lf.lambda_handler({"lat": 35.68, "lon": 139.77}, lambda_context)

        assert resp["statusCode"] == 200
        assert json.loads(resp["body"])["cache"]["hit"] is True
