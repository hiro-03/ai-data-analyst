"""
resolve_station Lambda のテスト（find_nearest_station と lambda_handler）。
"""
import json

import boto3
import pytest
from moto import mock_aws

import station_master as sm


class TestFindNearestStation:
    def test_returns_nearest_tokyo(self, sample_stations):
        assert sm.find_nearest_station(35.68, 139.77, sample_stations) == "tokyo"

    def test_returns_nearest_osaka(self, sample_stations):
        assert sm.find_nearest_station(34.70, 135.50, sample_stations) == "osaka"

    def test_returns_nearest_sapporo(self, sample_stations):
        assert sm.find_nearest_station(43.06, 141.35, sample_stations) == "sapporo"

    def test_empty_stations_returns_none(self):
        assert sm.find_nearest_station(35.68, 139.77, []) is None

    def test_single_station_always_returns_it(self):
        stations = [{"station_id": "only", "latitude": 0.0, "longitude": 0.0}]
        assert sm.find_nearest_station(90.0, 180.0, stations) == "only"

    def test_skips_malformed_entry(self, sample_stations):
        bad = [{"station_id": "bad"}] + sample_stations
        assert sm.find_nearest_station(35.68, 139.77, bad) == "tokyo"


class TestLoadStationMaster:
    def test_returns_empty_when_table_missing(self):
        with mock_aws():
            result = sm.load_station_master("nonexistent-table")
        assert result == []

    def test_loads_stations_from_dynamodb(self, stations_table_name):
        with mock_aws():
            boto3.client("dynamodb", region_name="ap-northeast-1").create_table(
                TableName=stations_table_name,
                AttributeDefinitions=[{"AttributeName": "station_id", "AttributeType": "S"}],
                KeySchema=[{"AttributeName": "station_id", "KeyType": "HASH"}],
                BillingMode="PAY_PER_REQUEST",
            )
            boto3.resource("dynamodb", region_name="ap-northeast-1").Table(
                stations_table_name
            ).put_item(Item={"station_id": "t1", "latitude": "35.0", "longitude": "139.0"})
            boto3.resource("dynamodb", region_name="ap-northeast-1").Table(
                stations_table_name
            ).put_item(Item={"station_id": "t2", "latitude": "34.0", "longitude": "135.0"})

            result = sm.load_station_master(stations_table_name)

        assert len(result) == 2
        assert {s["station_id"] for s in result} == {"t1", "t2"}


class TestLambdaHandler:
    _LAMBDA = "lambdas/fishing/resolve_station"

    def test_valid_request(self, load_lambda, stations_table_name, monkeypatch, lambda_context):
        monkeypatch.setenv("STATIONS_TABLE", stations_table_name)
        with mock_aws():
            boto3.client("dynamodb", region_name="ap-northeast-1").create_table(
                TableName=stations_table_name,
                AttributeDefinitions=[{"AttributeName": "station_id", "AttributeType": "S"}],
                KeySchema=[{"AttributeName": "station_id", "KeyType": "HASH"}],
                BillingMode="PAY_PER_REQUEST",
            )
            boto3.resource("dynamodb", region_name="ap-northeast-1").Table(
                stations_table_name
            ).put_item(Item={"station_id": "s1", "latitude": "35.0", "longitude": "139.0"})

            lf = load_lambda(self._LAMBDA)
            resp = lf.lambda_handler({"lat": 35.0, "lon": 139.0}, lambda_context)

        assert resp["statusCode"] == 200
        assert json.loads(resp["body"])["station_id"] == "s1"

    def test_missing_lat_lon_returns_400(self, load_lambda, lambda_context):
        lf = load_lambda(self._LAMBDA)
        resp = lf.lambda_handler({}, lambda_context)
        assert resp["statusCode"] == 400

    def test_invalid_input_type_returns_400(self, load_lambda, lambda_context):
        lf = load_lambda(self._LAMBDA)
        resp = lf.lambda_handler("not-a-dict", lambda_context)
        assert resp["statusCode"] == 400
