"""
Shared pytest configuration and fixtures.

Design:
- Only the Lambda Layer (fishing_common) and resolve_station (station_master.py)
  are added to sys.path globally.
- Individual Lambda modules are loaded on-demand via the `load_lambda` fixture,
  which uses importlib to give each Lambda a unique module name and avoids
  name collisions between multiple lambda_function.py files.
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

# Layer – must be importable from every Lambda under test.
_LAYER_PYTHON = os.path.join(_REPO_ROOT, "layers", "fishing_common", "python")
if _LAYER_PYTHON not in sys.path:
    sys.path.insert(0, _LAYER_PYTHON)

# resolve_station imports station_master.py as a sibling module.
_RESOLVE_DIR = os.path.join(_REPO_ROOT, "lambdas", "fishing", "resolve_station")
if _RESOLVE_DIR not in sys.path:
    sys.path.insert(0, _RESOLVE_DIR)

import boto3
import pytest
from moto import mock_aws

import station_master as _station_master_module


# ---------------------------------------------------------------------------
# AWS credential injection (autouse – every test gets fake creds)
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def aws_credentials(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-northeast-1")


# ---------------------------------------------------------------------------
# Station master cache reset (autouse – prevents test-to-test cache bleed)
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def clear_station_master_cache():
    """Clear the in-memory station cache before every test."""
    _station_master_module.clear_station_cache()
    yield
    _station_master_module.clear_station_cache()


# ---------------------------------------------------------------------------
# Lambda module loader
# ---------------------------------------------------------------------------
@pytest.fixture
def load_lambda():
    """
    Return a factory that imports a Lambda's lambda_function.py by its
    repo-relative directory path (e.g. "lambdas/api_proxy/fishing_proxy").

    Each call produces a fresh module object with a unique name so multiple
    Lambda modules can coexist in the same test session without collision.
    """
    def _load(rel_dir: str):
        abs_dir = os.path.join(_REPO_ROOT, rel_dir)
        abs_path = os.path.join(abs_dir, "lambda_function.py")

        # Add the Lambda's own directory to sys.path so local sibling
        # imports (station_master, etc.) resolve correctly.
        if abs_dir not in sys.path:
            sys.path.insert(0, abs_dir)

        module_name = "lf_" + rel_dir.replace("/", "_").replace("\\", "_")
        spec = importlib.util.spec_from_file_location(module_name, abs_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    return _load


# ---------------------------------------------------------------------------
# DynamoDB table names
# ---------------------------------------------------------------------------
@pytest.fixture
def cache_table_name():
    return "test-ExternalApiCache"


@pytest.fixture
def stations_table_name():
    return "test-Stations"


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------
@pytest.fixture
def sample_stations():
    return [
        {"station_id": "tokyo",   "latitude": 35.681, "longitude": 139.767},
        {"station_id": "osaka",   "latitude": 34.702, "longitude": 135.496},
        {"station_id": "sapporo", "latitude": 43.069, "longitude": 141.351},
    ]


# ---------------------------------------------------------------------------
# Fake Lambda context
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
