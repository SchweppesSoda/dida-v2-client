import json
from urllib.parse import urlparse

from dida_v2_client.config import DidaConfig
from dida_v2_client.transport import DidaV2Client


class FakeResponse:
    def __init__(self, body=b"{}"):
        self.status = 200
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._body


def test_create_tag_uses_v2_batch_tag_add(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["method"] = req.get_method()
        seen["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse(b'{"id2etag":{"New":"etag"},"id2error":{}}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = DidaV2Client(DidaConfig.default(), session_token="SECRET")

    assert client.create_tag("New", color="#fff", parent="状态", sort_type="project") == {
        "id2etag": {"New": "etag"},
        "id2error": {},
    }

    parsed = urlparse(seen["url"])
    assert seen["method"] == "POST"
    assert parsed.scheme + "://" + parsed.netloc + parsed.path == "https://api.dida365.com/api/v2/batch/tag"
    assert seen["body"] == {
        "add": [{"name": "New", "label": "New", "color": "#fff", "parent": "状态", "sortType": "project"}],
        "update": [],
    }


def test_update_tag_uses_v2_batch_tag_update(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse(b"{}")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = DidaV2Client(DidaConfig.default(), session_token="SECRET")

    client.update_tag("New", color="#000", parent="", sort_type="project", sort_order=12)

    assert seen["body"] == {
        "add": [],
        "update": [{"name": "New", "color": "#000", "parent": "", "sortType": "project", "sortOrder": 12}],
    }
