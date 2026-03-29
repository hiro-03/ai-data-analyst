"""
Shared DynamoDB cache helpers.

The boto3 resource is created once at module level so Lambda warm-start
executions reuse the existing connection pool.

Payload is stored as a JSON string ("payload_json") rather than a DynamoDB
Map to avoid the boto3 restriction that prohibits Python float values in
nested attributes (DynamoDB requires Decimal for numbers in Map types).
"""
import json
import time
from typing import Any, Dict, Optional

import boto3
from botocore.exceptions import ClientError

# Module-level resource: created once per execution environment.
_dynamodb = boto3.resource("dynamodb")


def get_table(name: str):
    return _dynamodb.Table(name)


def get_cached(table_name: str, key: str) -> Optional[Dict[str, Any]]:
    try:
        resp = get_table(table_name).get_item(Key={"cache_key": key})
        item = resp.get("Item")
        if not isinstance(item, dict):
            return None
        # Current format: payload stored as a JSON string.
        payload_json = item.get("payload_json")
        if isinstance(payload_json, str):
            return json.loads(payload_json)
        # Legacy format: payload stored as a DynamoDB Map (no floats).
        payload = item.get("payload")
        if isinstance(payload, dict):
            return payload
        return None
    except ClientError:
        return None


def put_cached(
    table_name: str,
    key: str,
    ttl_epoch: int,
    payload: Dict[str, Any],
) -> None:
    get_table(table_name).put_item(
        Item={
            "cache_key": key,
            "ttl_epoch": ttl_epoch,
            "payload_json": json.dumps(payload, ensure_ascii=False),
            "cached_at_epoch": int(time.time()),
        }
    )
