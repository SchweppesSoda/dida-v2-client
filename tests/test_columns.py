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


def test_list_columns_uses_v2_project_column_endpoint(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["method"] = req.get_method()
        return FakeResponse(b'[{"id":"c1","name":"Doing"}]')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = DidaV2Client(DidaConfig.default(), session_token="SECRET")

    assert client.list_columns("p1") == [{"id": "c1", "name": "Doing"}]

    parsed = urlparse(seen["url"])
    assert seen["method"] == "GET"
    assert parsed.scheme + "://" + parsed.netloc + parsed.path == "https://api.dida365.com/api/v2/column/project/p1"


def test_delete_column_posts_batch_column_delete_payload(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["method"] = req.get_method()
        seen["body"] = req.data.decode("utf-8")
        return FakeResponse(b'{"id2etag":{"c1":"etag"},"id2error":{}}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = DidaV2Client(DidaConfig.default(), session_token="SECRET")

    assert client.delete_column("p1", "c1") == {"id2etag": {"c1": "etag"}, "id2error": {}}

    parsed = urlparse(seen["url"])
    assert seen["method"] == "POST"
    assert parsed.scheme + "://" + parsed.netloc + parsed.path == "https://api.dida365.com/api/v2/column"
    assert seen["body"] == '{"add": [], "update": [], "delete": [{"id": "c1", "projectId": "p1"}]}'


def test_batch_columns_autofills_project_id_for_add_and_delete(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["body"] = req.data.decode("utf-8")
        return FakeResponse(b"{}")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = DidaV2Client(DidaConfig.default(), session_token="SECRET")

    client.batch_columns(
        project_id="p1",
        add=[{"name": "New"}],
        update=[{"id": "c2", "projectId": "p1", "name": "Later"}],
        delete=["c3"],
    )

    assert seen["body"] == '{"add": [{"name": "New", "projectId": "p1"}], "update": [{"id": "c2", "projectId": "p1", "name": "Later"}], "delete": [{"id": "c3", "projectId": "p1"}]}'
