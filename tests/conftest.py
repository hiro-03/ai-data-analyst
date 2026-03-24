import pytest
from moto import mock_aws
import boto3
import os
import sys


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDA_PATH = os.path.join(ROOT, "lambdas", "weather_observation_api")
if LAMBDA_PATH not in sys.path:
    sys.path.insert(0, LAMBDA_PATH)

@pytest.fixture(scope="session", autouse=True)
def mock_aws_env():
    m = mock_aws()
    m.start()
    # テーブル作成（load_station_master が期待するスキーマ）
    dynamodb = boto3.client("dynamodb", region_name="ap-northeast-1")
    dynamodb.create_table(
        TableName="Stations",
        AttributeDefinitions=[{"AttributeName":"station_id","AttributeType":"S"}],
        KeySchema=[{"AttributeName":"station_id","KeyType":"HASH"}],
        BillingMode="PAY_PER_REQUEST"
    )
    yield
    m.stop()