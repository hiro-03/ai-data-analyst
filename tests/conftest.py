"""
共有 pytest 設定とフィクスチャ。

設計:
- グローバルに sys.path に載せるのは Lambda Layer（fishing_common）と
  resolve_station（station_master.py）のみ。
- 各 Lambda モジュールは `load_lambda` フィクスチャでオンデマンド読み込み。
  importlib で一意のモジュール名を付け、複数の lambda_function.py 間の
  名前衝突を避ける。
"""
import importlib.util
import os
import sys

# station_master がモジュールレベルで boto3.resource() を呼び出すため、
# インポート前にダミー認証情報を設定しておく。
# setdefault を使うことで、実際の認証情報が存在する場合は上書きしない。
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-northeast-1")

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Layer – テスト対象の各 Lambda から import 可能である必要がある（パッケージは layers/fishing_common/fishing_common）。
_LAYER_ROOT = os.path.join(_REPO_ROOT, "layers", "fishing_common")
if _LAYER_ROOT not in sys.path:
    sys.path.insert(0, _LAYER_ROOT)

# resolve_station は station_master.py を兄弟モジュールとして import する。
_RESOLVE_DIR = os.path.join(_REPO_ROOT, "lambdas", "fishing", "resolve_station")
if _RESOLVE_DIR not in sys.path:
    sys.path.insert(0, _RESOLVE_DIR)

import boto3
import pytest
from moto import mock_aws

import station_master as _station_master_module


# ---------------------------------------------------------------------------
# AWS 認証情報の注入（autouse – 全テストにダミー認証情報を付与）
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def aws_credentials(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-northeast-1")


# ---------------------------------------------------------------------------
# 観測所マスタキャッシュのリセット（autouse – テスト間のキャッシュ汚染を防ぐ）
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def clear_station_master_cache():
    """各テストの前後でインメモリの観測所キャッシュをクリアする。"""
    _station_master_module.clear_station_cache()
    yield
    _station_master_module.clear_station_cache()


# ---------------------------------------------------------------------------
# Lambda モジュールローダー
# ---------------------------------------------------------------------------
@pytest.fixture
def load_lambda():
    """
    リポジトリ相対ディレクトリパス（例: lambdas/api_proxy/fishing_proxy）から
    その Lambda の lambda_function.py を import するファクトリを返す。

    呼び出しごとに一意の名前の新しいモジュールオブジェクトを生成し、
    同一セッション内で複数 Lambda を衝突なく共存させる。
    """
    def _load(rel_dir: str):
        abs_dir = os.path.join(_REPO_ROOT, rel_dir)
        abs_path = os.path.join(abs_dir, "lambda_function.py")

        # Lambda 自身のディレクトリを sys.path に追加し、兄弟 import（station_master 等）を解決する。
        if abs_dir not in sys.path:
            sys.path.insert(0, abs_dir)

        module_name = "lf_" + rel_dir.replace("/", "_").replace("\\", "_")
        spec = importlib.util.spec_from_file_location(module_name, abs_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    return _load


# ---------------------------------------------------------------------------
# DynamoDB テーブル名
# ---------------------------------------------------------------------------
@pytest.fixture
def cache_table_name():
    return "test-ExternalApiCache"


@pytest.fixture
def stations_table_name():
    return "test-Stations"


# ---------------------------------------------------------------------------
# サンプルデータ
# ---------------------------------------------------------------------------
@pytest.fixture
def sample_stations():
    return [
        {"station_id": "tokyo",   "latitude": 35.681, "longitude": 139.767},
        {"station_id": "osaka",   "latitude": 34.702, "longitude": 135.496},
        {"station_id": "sapporo", "latitude": 43.069, "longitude": 141.351},
    ]


# ---------------------------------------------------------------------------
# 擬似 Lambda コンテキスト
# ---------------------------------------------------------------------------
class _FakeLambdaContext:
    aws_request_id = "test-request-id"
    function_name = "test-function"
    memory_limit_in_mb = 256

    def get_remaining_time_in_millis(self):
        return 30000


@pytest.fixture
def lambda_context():
    return _FakeLambdaContext()
