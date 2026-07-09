import json
from urllib.parse import parse_qs, urlparse

import pytest

from dida_v2_client.config import DidaConfig
from dida_v2_client.transport import DidaV2Client, DidaV2Error


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
        return FakeResponse(200, b"{}")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = DidaV2Client(DidaConfig.default(), session_token="SECRET")

    assert client.delete_tag("提醒") == {}

    parsed = urlparse(seen["url"])
    assert seen["method"] == "DELETE"
    assert parsed.scheme + "://" + parsed.netloc + parsed.path == "https://api.dida365.com/api/v2/tag"
    assert parse_qs(parsed.query) == {"name": ["提醒"]}
    assert seen["cookie"] == "t=SECRET"


def test_requires_session_token():
    client = DidaV2Client(DidaConfig.default(), session_token=None)
    with pytest.raises(DidaV2Error, match="session token"):
        client.user_status()
