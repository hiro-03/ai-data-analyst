"""
Lambda 関数共通の DynamoDB キャッシュユーティリティ。

boto3 リソースをモジュールレベルで生成することで、Lambda のウォームスタート時に
コネクションプールを再利用し、コールドスタートのオーバーヘッドを最小化する。

ペイロードは DynamoDB Map 型ではなく JSON 文字列（"payload_json"）として保存する。
理由：boto3 の制約として、Map 型のネスト属性に Python の float 値を書き込めない
（DynamoDB の数値型は Decimal を要求するため）。JSON 文字列化することでこの制約を回避し、
float を含む外部 API レスポンスを変換なしにそのままキャッシュできる。
"""
import json
import time
from typing import Any, Dict, Optional

import boto3
from botocore.exceptions import ClientError

# モジュールレベルでリソースを生成：Lambda の実行環境ごとに1回のみ初期化される。
_dynamodb = boto3.resource("dynamodb")


def get_table(name: str) -> Any:
    return _dynamodb.Table(name)


def get_cached(table_name: str, key: str) -> Optional[Dict[str, Any]]:
    try:
        resp = get_table(table_name).get_item(Key={"cache_key": key})
        item = resp.get("Item")
        if not isinstance(item, dict):
            return None
        # 現行フォーマット：ペイロードを JSON 文字列で保存
        payload_json = item.get("payload_json")
        if isinstance(payload_json, str):
            parsed = json.loads(payload_json)
            return dict(parsed) if isinstance(parsed, dict) else None
        # 旧フォーマット互換：DynamoDB Map 型で保存（float を含まない場合のみ使用可能）
        payload = item.get("payload")
        if isinstance(payload, dict):
            return {str(k): v for k, v in payload.items()}
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
