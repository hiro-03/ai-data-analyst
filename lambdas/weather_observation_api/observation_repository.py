import os
import time
import boto3
from decimal import Decimal
import logging
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

def _ddb_table(table_name: str):
    endpoint = os.getenv("DYNAMODB_ENDPOINT")
    region = os.environ.get("AWS_REGION", "ap-northeast-1")
    if endpoint:
        resource = boto3.resource("dynamodb", region_name=region, endpoint_url=endpoint)
    else:
        resource = boto3.resource("dynamodb", region_name=region)
    return resource.Table(table_name)

def ensure_table_exists_local(table_name: str):
    """
    When running in LOCAL_MODE with DYNAMODB_ENDPOINT set, create the table if missing.
    No-op in non-local environments.
    """
    if os.getenv("LOCAL_MODE", "").lower() != "true":
        return

    endpoint = os.getenv("DYNAMODB_ENDPOINT")
    region = os.environ.get("AWS_REGION", "ap-northeast-1")
    client = boto3.client("dynamodb", region_name=region, endpoint_url=endpoint) if endpoint else boto3.client("dynamodb", region_name=region)

    try:
        client.describe_table(TableName=table_name)
        logger.info("Local table %s already exists", table_name)
        return
    except client.exceptions.ResourceNotFoundException:
        logger.info("Creating local table %s", table_name)
        client.create_table(
            TableName=table_name,
            AttributeDefinitions=[
                {"AttributeName": "station_id", "AttributeType": "S"},
                {"AttributeName": "timestamp", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "station_id", "KeyType": "HASH"},
                {"AttributeName": "timestamp", "KeyType": "RANGE"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        waiter = client.get_waiter("table_exists")
        waiter.wait(TableName=table_name)
        # small sleep to avoid eventual consistency issues locally
        time.sleep(0.2)
        logger.info("Local table %s created and active", table_name)
    except Exception:
        logger.exception("Failed to ensure local table exists: %s", table_name)
        raise

def to_ddb_item(station_id: str, timestamp: str, lat: float, lon: float, temperature: float, humidity: float):
    return {
        "station_id": station_id,
        "timestamp": timestamp,
        "latitude": Decimal(str(lat)),
        "longitude": Decimal(str(lon)),
        "temperature": Decimal(str(temperature)),
        "humidity": Decimal(str(humidity)),
    }

def save_observation(table_name: str, station_id: str, timestamp: str, lat: float, lon: float, temperature: float, humidity: float):
    """
    Persist observation to DynamoDB using high-level resource API.
    Raises exception on failure.
    """
    logger.info("save_observation start table=%s station=%s", table_name, station_id)

    # ローカルテスト時にテーブルが無ければ作成する
    ensure_table_exists_local(table_name)

    table = _ddb_table(table_name)
    item = to_ddb_item(station_id, timestamp, lat, lon, temperature, humidity)
    try:
        table.put_item(Item=item)
        logger.info("save_observation success station=%s", station_id)
    except ClientError:
        logger.exception("DynamoDB put_item failed for %s", table_name)
        raise