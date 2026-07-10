from urllib.parse import parse_qs, urlparse

from dida_v2_client.config import DidaConfig
from dida_v2_client.transport import DidaV2Client


class FakeResponse:
    def __init__(self, body=b"[]"):
        self.status = 200
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._body


def test_list_closed_tasks_calls_v2_closed_endpoint_with_filters(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["method"] = req.get_method()
        return FakeResponse(b'[{"id":"t1","title":"Done"}]')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = DidaV2Client(DidaConfig.default(), session_token="SECRET")

    assert client.list_closed_tasks(from_date="2026-07-01 00:00:00", to_date="2026-07-09 23:59:59", status="Abandoned", limit=50) == [
        {"id": "t1", "title": "Done"}
    ]

    parsed = urlparse(seen["url"])
    assert seen["method"] == "GET"
    assert parsed.scheme + "://" + parsed.netloc + parsed.path == "https://api.dida365.com/api/v2/project/all/closed"
    assert parse_qs(parsed.query) == {
        "from": ["2026-07-01 00:00:00"],
        "to": ["2026-07-09 23:59:59"],
        "status": ["Abandoned"],
        "limit": ["50"],
    }


def test_list_trash_tasks_accepts_tasks_wrapper(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        return FakeResponse(b'{"tasks":[{"id":"t2","title":"Deleted"}]}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = DidaV2Client(DidaConfig.default(), session_token="SECRET")

    assert client.list_trash_tasks(start=5, limit=20) == [{"id": "t2", "title": "Deleted"}]

    parsed = urlparse(seen["url"])
    assert parsed.path == "/api/v2/project/all/trash/pagination"
    assert parse_qs(parsed.query) == {"start": ["5"], "limit": ["20"]}
