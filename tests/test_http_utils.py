"""
Tests for fishing_common.http_utils – retry logic.
"""
import json
from io import BytesIO
from unittest.mock import MagicMock, call, patch
from urllib.error import HTTPError, URLError

import pytest

from fishing_common.http_utils import http_get_json_with_retry

_URL = "https://api.example.com/data"
_HEADERS = {"Accept": "application/json"}


def _mock_response(status: int, body: dict):
    """Build a fake urlopen response context-manager."""
    resp = MagicMock()
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    resp.read.return_value = json.dumps(body).encode()
    resp.status = status
    return resp


def _http_error(code: int) -> HTTPError:
    return HTTPError(url=_URL, code=code, msg="err", hdrs={}, fp=None)


class TestHttpGetJsonWithRetry:
    def test_success_on_first_attempt(self):
        mock_resp = _mock_response(200, {"ok": True})
        with patch("fishing_common.http_utils.urlopen", return_value=mock_resp) as m:
            result = http_get_json_with_retry(_URL, _HEADERS)
        assert result == {"ok": True}
        assert m.call_count == 1

    def test_retries_on_429_then_succeeds(self):
        mock_resp = _mock_response(200, {"ok": True})
        with patch("fishing_common.http_utils.urlopen") as m, \
             patch("fishing_common.http_utils.time.sleep"):
            m.side_effect = [_http_error(429), mock_resp]
            result = http_get_json_with_retry(_URL, _HEADERS, attempts=3)
        assert result == {"ok": True}
        assert m.call_count == 2

    def test_retries_on_503_then_succeeds(self):
        mock_resp = _mock_response(200, {"data": "here"})
        with patch("fishing_common.http_utils.urlopen") as m, \
             patch("fishing_common.http_utils.time.sleep"):
            m.side_effect = [_http_error(503), _http_error(503), mock_resp]
            result = http_get_json_with_retry(_URL, _HEADERS, attempts=3)
        assert result == {"data": "here"}
        assert m.call_count == 3

    def test_does_not_retry_on_400(self):
        """Client errors (4xx except 429) must NOT be retried."""
        with patch("fishing_common.http_utils.urlopen") as m:
            m.side_effect = _http_error(400)
            with pytest.raises(HTTPError) as exc_info:
                http_get_json_with_retry(_URL, _HEADERS, attempts=3)
        assert exc_info.value.code == 400
        assert m.call_count == 1

    def test_does_not_retry_on_404(self):
        with patch("fishing_common.http_utils.urlopen") as m:
            m.side_effect = _http_error(404)
            with pytest.raises(HTTPError):
                http_get_json_with_retry(_URL, _HEADERS, attempts=3)
        assert m.call_count == 1

    def test_raises_after_max_retries_on_500(self):
        with patch("fishing_common.http_utils.urlopen") as m, \
             patch("fishing_common.http_utils.time.sleep"):
            m.side_effect = _http_error(500)
            with pytest.raises(HTTPError) as exc_info:
                http_get_json_with_retry(_URL, _HEADERS, attempts=3)
        assert exc_info.value.code == 500
        assert m.call_count == 3

    def test_retries_on_url_error(self):
        mock_resp = _mock_response(200, {"recovered": True})
        with patch("fishing_common.http_utils.urlopen") as m, \
             patch("fishing_common.http_utils.time.sleep"):
            m.side_effect = [URLError("connection reset"), mock_resp]
            result = http_get_json_with_retry(_URL, _HEADERS, attempts=3)
        assert result == {"recovered": True}

    def test_raises_url_error_after_max_retries(self):
        with patch("fishing_common.http_utils.urlopen") as m, \
             patch("fishing_common.http_utils.time.sleep"):
            m.side_effect = URLError("timeout")
            with pytest.raises(URLError):
                http_get_json_with_retry(_URL, _HEADERS, attempts=2)
        assert m.call_count == 2

    def test_sleep_is_called_between_retries(self):
        mock_resp = _mock_response(200, {})
        with patch("fishing_common.http_utils.urlopen") as m, \
             patch("fishing_common.http_utils.time.sleep") as sleep_mock:
            m.side_effect = [_http_error(429), mock_resp]
            http_get_json_with_retry(_URL, _HEADERS, attempts=3)
        assert sleep_mock.call_count == 1
