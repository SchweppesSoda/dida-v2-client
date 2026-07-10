import io
import traceback
import urllib.error
from threading import Event, Thread
from urllib.parse import parse_qs, urlparse

import pytest

from dida_v2_client.config import DidaConfig
from dida_v2_client.transport import DidaV2Client, DidaV2Error, DidaV2HTTPError
from dida_v2_client.version import USER_AGENT


class FakeResponse:
    def __init__(self, status=200, body=b"{}"):
        self.status = status
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._body


def test_delete_tag_uses_dida_v2_endpoint_and_cookie(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["method"] = req.get_method()
        seen["cookie"] = req.headers.get("Cookie")
        seen["user_agent"] = req.headers.get("User-agent")
        return FakeResponse(200, b"{}")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = DidaV2Client(DidaConfig.default(), session_token="SECRET")

    assert client.delete_tag("提醒") == {}

    parsed = urlparse(seen["url"])
    assert seen["method"] == "DELETE"
    assert parsed.scheme + "://" + parsed.netloc + parsed.path == "https://api.dida365.com/api/v2/tag"
    assert parse_qs(parsed.query) == {"name": ["提醒"]}
    assert seen["cookie"] == "t=SECRET"
    assert seen["user_agent"] == USER_AGENT


def test_request_uses_one_atomic_profile_and_session_identity(monkeypatch):
    client = DidaV2Client(DidaConfig.for_profile("dida"), session_token="TOKEN_A")
    original_headers = client._headers
    header_build_started = Event()
    release_headers = Event()
    seen = {}

    def blocking_headers(*args, **kwargs):
        header_build_started.set()
        assert release_headers.wait(timeout=2)
        return original_headers(*args, **kwargs)

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["cookie"] = req.headers.get("Cookie")
        seen["origin"] = req.headers.get("Origin")
        return FakeResponse(200, b"{}")

    monkeypatch.setattr(client, "_headers", blocking_headers)
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    worker = Thread(target=lambda: client.request("GET", "/user/status"))
    worker.start()
    assert header_build_started.wait(timeout=2)

    client.set_identity(DidaConfig.for_profile("ticktick"), "TOKEN_B")
    release_headers.set()
    worker.join(timeout=2)
    assert not worker.is_alive()

    assert seen["url"].startswith("https://api.dida365.com/")
    assert seen["origin"] == "https://dida365.com"
    assert seen["cookie"] == "t=TOKEN_A"


def test_identity_fields_require_atomic_replacement():
    client = DidaV2Client(DidaConfig.for_profile("dida"), session_token="TOKEN_A")

    with pytest.raises(AttributeError, match="set_identity"):
        client.config = DidaConfig.for_profile("ticktick")
    with pytest.raises(AttributeError, match="set_identity"):
        client.session_token = "TOKEN_B"

    client.set_identity(DidaConfig.for_profile("ticktick"), "TOKEN_B")
    assert client.config.profile == "ticktick"
    assert client.session_token == "TOKEN_B"


def test_request_exposes_structured_http_status_without_response_secrets(monkeypatch):
    def fake_urlopen(req, timeout):
        body = b'{"errorCode":"user_not_sign_on","message":"TOKEN_SENTINEL"}'
        raise urllib.error.HTTPError(req.full_url, 503, "unavailable", {}, io.BytesIO(body))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = DidaV2Client(DidaConfig.default(), session_token="TOKEN_SENTINEL")

    with pytest.raises(DidaV2HTTPError) as excinfo:
        client.user_status()
    assert excinfo.value.status == 503
    assert excinfo.value.error_code == "user_not_sign_on"
    assert "TOKEN_SENTINEL" not in str(excinfo.value)
    formatted = "".join(traceback.format_exception(excinfo.type, excinfo.value, excinfo.tb))
    assert "TOKEN_SENTINEL" not in formatted


def test_request_sanitizes_network_failure_reason(monkeypatch):
    def fake_urlopen(req, timeout):
        raise urllib.error.URLError("network echoed TOKEN_SENTINEL")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = DidaV2Client(DidaConfig.default(), session_token="TOKEN_SENTINEL")

    with pytest.raises(DidaV2Error) as excinfo:
        client.user_status()
    assert "TOKEN_SENTINEL" not in str(excinfo.value)
    formatted = "".join(traceback.format_exception(excinfo.type, excinfo.value, excinfo.tb))
    assert "TOKEN_SENTINEL" not in formatted


def test_request_sanitizes_http_error_body_read_failure(monkeypatch):
    class BrokenHTTPError(urllib.error.HTTPError):
        def read(self, *args, **kwargs):
            raise OSError("body read echoed TOKEN_SENTINEL")

    def fake_urlopen(req, timeout):
        raise BrokenHTTPError(req.full_url, 503, "TOKEN_SENTINEL", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = DidaV2Client(DidaConfig.default(), session_token="TOKEN_SENTINEL")

    with pytest.raises(DidaV2HTTPError) as excinfo:
        client.user_status()
    assert excinfo.value.status == 503
    formatted = "".join(traceback.format_exception(excinfo.type, excinfo.value, excinfo.tb))
    assert "TOKEN_SENTINEL" not in formatted


def test_requires_session_token():
    client = DidaV2Client(DidaConfig.default(), session_token=None)
    with pytest.raises(DidaV2Error, match="session token"):
        client.user_status()
