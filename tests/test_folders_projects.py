import json
from threading import Event, Thread
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


def test_list_project_folders_reads_v2_sync_project_groups(monkeypatch):
    def fake_urlopen(req, timeout):
        return FakeResponse(b'{"projectGroups":[{"id":"g1","name":"Work"}],"projectProfiles":[]}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = DidaV2Client(DidaConfig.default(), session_token="SECRET")

    assert client.list_project_folders() == [{"id": "g1", "name": "Work"}]


def test_batch_project_folders_posts_v2_batch_project_group(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["method"] = req.get_method()
        seen["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse(b'{"id2etag":{"g1":"etag"},"id2error":{}}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = DidaV2Client(DidaConfig.default(), session_token="SECRET")

    result = client.batch_project_folders(add=[{"name": "Work"}], update=[{"id": "g1", "name": "Office"}], delete=["g2"])

    parsed = urlparse(seen["url"])
    assert result == {"id2etag": {"g1": "etag"}, "id2error": {}}
    assert seen["method"] == "POST"
    assert parsed.scheme + "://" + parsed.netloc + parsed.path == "https://api.dida365.com/api/v2/batch/projectGroup"
    assert seen["body"] == {"add": [{"name": "Work"}], "update": [{"id": "g1", "name": "Office"}], "delete": ["g2"]}


def test_list_projects_reads_v2_sync_project_profiles_with_real_group_ids(monkeypatch):
    def fake_urlopen(req, timeout):
        return FakeResponse(b'{"projectProfiles":[{"id":"p1","name":"Inboxish","groupId":"g1"}],"projectGroups":[]}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = DidaV2Client(DidaConfig.default(), session_token="SECRET")

    assert client.list_projects() == [{"id": "p1", "name": "Inboxish", "groupId": "g1"}]


def test_set_project_folder_read_modify_writes_v2_batch_project(monkeypatch):
    calls = []

    def fake_urlopen(req, timeout):
        calls.append((req.full_url, req.get_method(), req.data.decode("utf-8") if req.data else None))
        if req.get_method() == "GET":
            return FakeResponse(
                b'{"projectProfiles":[{"id":"p1","name":"List","kind":"TASK","color":"#fff","viewMode":"list","sortOrder":9,"groupId":"old"}]}'
            )
        return FakeResponse(b'{"id2etag":{"p1":"etag"},"id2error":{}}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = DidaV2Client(DidaConfig.default(), session_token="SECRET")

    assert client.set_project_folder("p1", "g2") == {"id2etag": {"p1": "etag"}, "id2error": {}}

    post_url, post_method, post_body = calls[-1]
    assert post_method == "POST"
    assert urlparse(post_url).path == "/api/v2/batch/project"
    assert json.loads(post_body) == {
        "update": [
            {
                "id": "p1",
                "name": "List",
                "kind": "TASK",
                "color": "#fff",
                "viewMode": "list",
                "sortOrder": 9,
                "groupId": "g2",
            }
        ]
    }


def test_set_project_folder_binds_read_and_write_to_one_identity(monkeypatch):
    read_started = Event()
    release_read = Event()
    seen = {}

    def fake_urlopen(req, timeout):
        if req.get_method() == "GET":
            read_started.set()
            assert release_read.wait(timeout=2)
            return FakeResponse(b'{"projectProfiles":[{"id":"p1","name":"Account A List","groupId":"old"}]}')
        seen["url"] = req.full_url
        seen["cookie"] = req.get_header("Cookie")
        seen["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse(b'{"id2etag":{"p1":"etag"},"id2error":{}}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = DidaV2Client(DidaConfig.for_profile("dida"), session_token="TOKEN_A")
    outcome = []
    worker = Thread(target=lambda: outcome.append(client.set_project_folder("p1", "g2")))
    worker.start()
    assert read_started.wait(timeout=2)

    client.set_identity(DidaConfig.for_profile("ticktick"), "TOKEN_B")
    release_read.set()
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert outcome == [{"id2etag": {"p1": "etag"}, "id2error": {}}]
    assert seen["url"].startswith("https://api.dida365.com/api/v2/")
    assert seen["cookie"] == "t=TOKEN_A"
    assert seen["body"]["update"][0]["name"] == "Account A List"


def test_set_project_folder_rejects_malformed_batch_response(monkeypatch):
    def fake_urlopen(req, timeout):
        if req.get_method() == "GET":
            return FakeResponse(b'{"projectProfiles":[{"id":"p1","name":"List","groupId":"old"}]}')
        return FakeResponse(b'{"unexpected":true}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = DidaV2Client(DidaConfig.default(), session_token="SECRET")

    with pytest.raises(DidaV2Error, match="unrecognized response shape"):
        client.set_project_folder("p1", "g2")
