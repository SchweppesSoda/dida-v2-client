import json
from urllib.parse import urlparse

import pytest

from dida_v2_client.config import DidaConfig
from dida_v2_client.transport import DidaV2Client, DidaV2Error


class FakeResponse:
    def __init__(self, body=b'{"id2etag":{},"id2error":{}}'):
        self.status = 200
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._body


def test_typed_task_helpers_post_expected_batch_payloads(monkeypatch):
    calls = []

    def fake_urlopen(req, timeout):
        calls.append((req.full_url, json.loads(req.data.decode("utf-8"))))
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = DidaV2Client(DidaConfig.default(), session_token="SECRET")

    client.create_task({"title": "A", "projectId": "p1"})
    client.update_task({"id": "t1", "projectId": "p1", "title": "B"})
    client.delete_task("t1", project_id="p1")
    client.complete_task("t2", project_id="p1")
    client.reopen_task("t3", project_id="p1")
    client.abandon_task("t4", project_id="p1")

    assert [urlparse(url).path for url, _ in calls] == ["/api/v2/batch/task"] * 6
    assert calls[0][1]["add"] == [{"title": "A", "projectId": "p1"}]
    assert calls[1][1]["update"] == [{"id": "t1", "projectId": "p1", "title": "B"}]
    assert calls[2][1]["delete"] == [{"taskId": "t1", "projectId": "p1"}]
    assert calls[3][1]["update"] == [{"id": "t2", "projectId": "p1", "status": 2}]
    assert calls[4][1]["update"] == [{"id": "t3", "projectId": "p1", "status": 0}]
    assert calls[5][1]["update"] == [{"id": "t4", "projectId": "p1", "status": -1}]


def test_typed_task_helpers_validate_batch_errors(monkeypatch):
    def fake_urlopen(req, timeout):
        return FakeResponse(b'{"id2etag":{},"id2error":{"t1":"boom"}}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = DidaV2Client(DidaConfig.default(), session_token="SECRET")

    with pytest.raises(DidaV2Error, match="V2 batch response contains errors"):
        client.delete_task("t1", project_id="p1")


def test_batch_error_helpers_handle_known_error_shapes():
    client = DidaV2Client(DidaConfig.default(), session_token="SECRET")

    assert client.batch_errors({"id2error": {}}) == {}
    assert client.batch_errors({"id2error": {"t1": "boom"}}) == {"id2error": {"t1": "boom"}}
    assert client.batch_errors({"errorId": "user_not_sign_on", "errorCode": "user_not_sign_on"}) == {
        "errorId": "user_not_sign_on",
        "errorCode": "user_not_sign_on",
    }
