import json
from urllib.parse import urlparse

import pytest

from dida_v2_client.config import DidaConfig
from dida_v2_client.transport import DidaV2Client, DidaV2Error


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


def test_list_tasks_reads_sync_task_updates(monkeypatch):
    def fake_urlopen(req, timeout):
        return FakeResponse(b'{"syncTaskBean":{"update":[{"id":"t1","title":"A"}]}}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = DidaV2Client(DidaConfig.default(), session_token="SECRET")

    assert client.list_tasks() == [{"id": "t1", "title": "A"}]


def test_get_task_finds_by_task_id_and_optional_project_id(monkeypatch):
    def fake_urlopen(req, timeout):
        return FakeResponse(
            b'{"syncTaskBean":{"update":[{"id":"same","projectId":"p1","title":"One"},{"id":"same","projectId":"p2","title":"Two"}]}}'
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = DidaV2Client(DidaConfig.default(), session_token="SECRET")

    assert client.get_task("same", project_id="p2") == {"id": "same", "projectId": "p2", "title": "Two"}
    with pytest.raises(DidaV2Error, match="Task not found"):
        client.get_task("missing")


def test_batch_tasks_posts_v2_payload_with_attachment_slots(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["method"] = req.get_method()
        seen["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse(b'{"id2etag":{"t1":"etag"},"id2error":{}}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = DidaV2Client(DidaConfig.default(), session_token="SECRET")

    result = client.batch_tasks(add=[{"title":"New"}], update=[{"id":"t1","projectId":"p1","title":"Updated"}], delete=[{"taskId":"t2","projectId":"p1"}])

    assert result == {"id2etag": {"t1": "etag"}, "id2error": {}}
    parsed = urlparse(seen["url"])
    assert seen["method"] == "POST"
    assert parsed.scheme + "://" + parsed.netloc + parsed.path == "https://api.dida365.com/api/v2/batch/task"
    assert seen["body"] == {
        "add": [{"title": "New"}],
        "update": [{"id": "t1", "projectId": "p1", "title": "Updated"}],
        "delete": [{"taskId": "t2", "projectId": "p1"}],
        "addAttachments": [],
        "updateAttachments": [],
        "deleteAttachments": [],
    }


def test_move_task_posts_v2_task_project_batch(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse(b'{"ok":true}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = DidaV2Client(DidaConfig.default(), session_token="SECRET")

    assert client.move_task("t1", from_project_id="p1", to_project_id="p2") == {"ok": True}
    assert urlparse(seen["url"]).path == "/api/v2/batch/taskProject"
    assert seen["body"] == [{"taskId": "t1", "fromProjectId": "p1", "toProjectId": "p2"}]


def test_set_and_unset_task_parent_use_v2_task_parent_batch(monkeypatch):
    bodies = []

    def fake_urlopen(req, timeout):
        bodies.append(json.loads(req.data.decode("utf-8")))
        return FakeResponse(b'{"ok":true}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = DidaV2Client(DidaConfig.default(), session_token="SECRET")

    assert client.set_task_parent("child", project_id="p1", parent_id="parent") == {"ok": True}
    assert client.unset_task_parent("child", project_id="p1", old_parent_id="parent") == {"ok": True}
    assert bodies == [
        [{"taskId": "child", "projectId": "p1", "parentId": "parent"}],
        [{"taskId": "child", "projectId": "p1", "oldParentId": "parent"}],
    ]
