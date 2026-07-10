from threading import Event, Thread

import pytest

from dida_v2_client.config import DidaConfig
from dida_v2_client.snapshot import SyncSnapshot
from dida_v2_client.transport import DidaV2Client, DidaV2Error


def test_snapshot_extracts_sync_collections(load_fixture):
    raw = load_fixture("full_sync_with_filters.json")

    snapshot = SyncSnapshot.from_payload(raw)

    assert snapshot.filters[0]["name"] == "Today P1"
    assert snapshot.projects[0]["id"] == "project-1"
    assert snapshot.project_groups[0]["id"] == "group-work"
    assert snapshot.tags[0]["name"] == "work"
    assert snapshot.tasks == ()
    assert snapshot.checkpoint == 101


def test_snapshot_extracts_tasks_from_sync_task_bean(load_fixture):
    snapshot = SyncSnapshot.from_payload(load_fixture("full_sync_minimal.json"))

    assert [task["id"] for task in snapshot.tasks] == ["task-1"]


def test_snapshot_handles_non_dict_payload():
    snapshot = SyncSnapshot.from_payload([])

    assert snapshot.tasks == ()
    assert snapshot.projects == ()
    assert dict(snapshot.raw) == {}


def test_client_invalidates_snapshot_when_session_token_changes():
    client = DidaV2Client(DidaConfig.default(), session_token="ACCOUNT_A")
    calls = []

    def fake_sync(*, _identity=None):
        calls.append(client.session_token)
        return {"syncTaskBean": {"update": [{"id": client.session_token}]}}

    client.full_sync = fake_sync

    assert client.get_snapshot().tasks[0]["id"] == "ACCOUNT_A"
    client.set_identity(client.config, "ACCOUNT_B")
    assert client.get_snapshot().tasks[0]["id"] == "ACCOUNT_B"
    assert calls == ["ACCOUNT_A", "ACCOUNT_B"]


def test_inflight_snapshot_cannot_repopulate_cache_after_session_change():
    client = DidaV2Client(DidaConfig.default(), session_token="ACCOUNT_A")
    started = Event()
    release = Event()
    calls = []

    def fake_sync(*, _identity=None):
        account = client.session_token
        calls.append(account)
        if account == "ACCOUNT_A":
            started.set()
            assert release.wait(timeout=2)
        return {"syncTaskBean": {"update": [{"id": account}]}}

    client.full_sync = fake_sync
    first_result = []
    worker = Thread(target=lambda: first_result.append(client.get_snapshot()))
    worker.start()
    assert started.wait(timeout=2)

    client.set_identity(client.config, "ACCOUNT_B")
    release.set()
    worker.join(timeout=2)
    assert not worker.is_alive()

    assert first_result[0].tasks[0]["id"] == "ACCOUNT_A"
    assert client.get_snapshot().tasks[0]["id"] == "ACCOUNT_B"
    assert calls == ["ACCOUNT_A", "ACCOUNT_B"]


def test_snapshot_fetch_uses_identity_captured_at_call_start():
    client = DidaV2Client(DidaConfig.for_profile("dida"), session_token="ACCOUNT_A")
    fetch_started = Event()
    release_fetch = Event()

    def fake_sync(*, _identity=None):
        fetch_started.set()
        assert release_fetch.wait(timeout=2)
        config, token = _identity or (client.config, client.session_token)
        return {"syncTaskBean": {"update": [{"id": f"{config.profile}:{token}"}]}}

    client.full_sync = fake_sync
    results = []
    worker = Thread(target=lambda: results.append(client.get_snapshot()))
    worker.start()
    assert fetch_started.wait(timeout=2)

    client.set_identity(DidaConfig.for_profile("ticktick"), "ACCOUNT_B")
    release_fetch.set()
    worker.join(timeout=2)
    assert not worker.is_alive()

    assert results[0].tasks[0]["id"] == "dida:ACCOUNT_A"


def test_client_invalidates_snapshot_when_profile_changes():
    client = DidaV2Client(DidaConfig.for_profile("dida"), session_token="TEST")
    calls = []

    def fake_sync(*, _identity=None):
        calls.append(client.config.profile)
        return {"syncTaskBean": {"update": [{"id": client.config.profile}]}}

    client.full_sync = fake_sync

    assert client.get_snapshot().tasks[0]["id"] == "dida"
    client.set_identity(DidaConfig.for_profile("ticktick"), client.session_token)
    assert client.get_snapshot().tasks[0]["id"] == "ticktick"
    assert calls == ["dida", "ticktick"]


def test_inflight_snapshot_cannot_repopulate_cache_after_profile_change():
    client = DidaV2Client(DidaConfig.for_profile("dida"), session_token="TEST")
    started = Event()
    release = Event()
    calls = []

    def fake_sync(*, _identity=None):
        profile = client.config.profile
        calls.append(profile)
        if profile == "dida":
            started.set()
            assert release.wait(timeout=2)
        return {"syncTaskBean": {"update": [{"id": profile}]}}

    client.full_sync = fake_sync
    worker = Thread(target=client.get_snapshot)
    worker.start()
    assert started.wait(timeout=2)

    client.set_identity(DidaConfig.for_profile("ticktick"), client.session_token)
    release.set()
    worker.join(timeout=2)
    assert not worker.is_alive()

    assert client.get_snapshot().tasks[0]["id"] == "ticktick"
    assert calls == ["dida", "ticktick"]


@pytest.mark.parametrize("ttl", [30.1, float("inf"), float("nan"), -0.1])
def test_client_rejects_unbounded_snapshot_ttl(ttl):
    with pytest.raises(ValueError, match="between 0 and 30"):
        DidaV2Client(DidaConfig.default(), session_token="TEST", snapshot_ttl_seconds=ttl)


def test_client_rejects_unbounded_snapshot_ttl_assignment():
    client = DidaV2Client(DidaConfig.default(), session_token="TEST", snapshot_ttl_seconds=10)

    with pytest.raises(ValueError, match="between 0 and 30"):
        client.snapshot_ttl_seconds = float("inf")

    assert client.snapshot_ttl_seconds == 10


def test_client_refreshes_snapshot_after_default_cache_ttl():
    current_time = [100.0]
    client = DidaV2Client(
        DidaConfig.default(),
        session_token="TEST",
        clock=lambda: current_time[0],
    )
    calls = []

    def fake_sync(*, _identity=None):
        calls.append(len(calls) + 1)
        return {"checkPoint": calls[-1]}

    client.full_sync = fake_sync

    assert client.get_snapshot().checkpoint == 1
    current_time[0] = 129.0
    assert client.get_snapshot().checkpoint == 1
    current_time[0] = 131.0
    assert client.get_snapshot().checkpoint == 2


def test_client_refresh_true_bypasses_snapshot_cache():
    client = DidaV2Client(DidaConfig.default(), session_token="TEST")
    calls = []

    def fake_sync(*, _identity=None):
        calls.append(len(calls) + 1)
        return {"checkPoint": calls[-1]}

    client.full_sync = fake_sync

    assert client.get_snapshot().checkpoint == 1
    assert client.get_snapshot(refresh=True).checkpoint == 2
    assert calls == [1, 2]


def test_older_concurrent_refresh_cannot_overwrite_newer_snapshot():
    client = DidaV2Client(DidaConfig.default(), session_token="TEST")
    first_started = Event()
    release_first = Event()
    calls = []
    results = {}

    def fake_sync(*, _identity=None):
        request_number = len(calls) + 1
        calls.append(request_number)
        if request_number == 1:
            first_started.set()
            assert release_first.wait(timeout=2)
        return {"checkPoint": request_number}

    client.full_sync = fake_sync
    first = Thread(target=lambda: results.setdefault("first", client.get_snapshot(refresh=True)))
    first.start()
    assert first_started.wait(timeout=2)

    second = Thread(target=lambda: results.setdefault("second", client.get_snapshot(refresh=True)))
    second.start()
    second.join(timeout=2)
    assert not second.is_alive()
    release_first.set()
    first.join(timeout=2)
    assert not first.is_alive()

    assert results["first"].checkpoint == 1
    assert results["second"].checkpoint == 2
    assert client.get_snapshot().checkpoint == 2
    assert calls == [1, 2]


def test_successful_write_invalidates_snapshot_and_cache_time(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"id2etag":{"task-1":"etag"},"id2error":{}}'

    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: FakeResponse())
    current_time = [100.0]
    client = DidaV2Client(
        DidaConfig.default(),
        session_token="TEST",
        clock=lambda: current_time[0],
    )
    calls = []

    def fake_sync(*, _identity=None):
        calls.append(len(calls) + 1)
        return {"checkPoint": calls[-1]}

    client.full_sync = fake_sync

    assert client.get_snapshot().checkpoint == 1
    client.update_task({"id": "task-1", "projectId": "project-1"})
    assert client.get_snapshot().checkpoint == 2
    assert calls == [1, 2]


def test_malformed_successful_write_response_still_invalidates_snapshot(monkeypatch):
    class MalformedResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b"not-json"

    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: MalformedResponse())
    client = DidaV2Client(DidaConfig.default(), session_token="TEST")
    calls = []

    def fake_sync(*, _identity=None):
        calls.append(len(calls) + 1)
        return {"checkPoint": calls[-1]}

    client.full_sync = fake_sync
    assert client.get_snapshot().checkpoint == 1

    with pytest.raises(DidaV2Error, match="Malformed JSON response"):
        client.update_task({"id": "task-1", "projectId": "project-1"})

    assert client.get_snapshot().checkpoint == 2
    assert calls == [1, 2]


def test_inflight_snapshot_cannot_repopulate_cache_after_successful_write(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"id2etag":{"task-1":"etag"},"id2error":{}}'

    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: FakeResponse())
    client = DidaV2Client(DidaConfig.default(), session_token="TEST")
    started = Event()
    release = Event()
    calls = []

    def fake_sync(*, _identity=None):
        checkpoint = len(calls) + 1
        calls.append(checkpoint)
        if checkpoint == 1:
            started.set()
            assert release.wait(timeout=2)
        return {"checkPoint": checkpoint}

    client.full_sync = fake_sync
    worker = Thread(target=client.get_snapshot)
    worker.start()
    assert started.wait(timeout=2)

    client.update_task({"id": "task-1", "projectId": "project-1"})
    release.set()
    worker.join(timeout=2)
    assert not worker.is_alive()

    assert client.get_snapshot().checkpoint == 2
    assert calls == [1, 2]


def test_snapshot_recursively_freezes_checkpoint():
    snapshot = SyncSnapshot.from_payload({"checkPoint": {"cursor": [1, {"page": 2}]}})

    with pytest.raises(TypeError):
        snapshot.checkpoint["cursor"] = []
    with pytest.raises(AttributeError):
        snapshot.checkpoint["cursor"].append(3)
    with pytest.raises(TypeError):
        snapshot.checkpoint["cursor"][1]["page"] = 3


def test_snapshot_recursively_freezes_cached_payload():
    snapshot = SyncSnapshot.from_payload(
        {
            "syncTaskBean": {
                "update": [
                    {"id": "task-1", "title": "Original", "items": [{"title": "Nested"}]}
                ]
            }
        }
    )

    with pytest.raises(TypeError):
        snapshot.tasks[0]["title"] = "Changed"
    with pytest.raises(TypeError):
        snapshot.tasks[0]["items"][0]["title"] = "Changed"
    with pytest.raises(TypeError):
        snapshot.raw["syncTaskBean"]["update"][0]["title"] = "Changed"


def test_client_returns_deep_mutable_copies_without_changing_cache():
    client = DidaV2Client(DidaConfig.default(), session_token="TEST")
    client.full_sync = lambda **_: {
        "syncTaskBean": {
            "update": [
                {"id": "task-1", "items": [{"title": "Nested"}]}
            ]
        }
    }

    first = client.list_tasks()
    first[0]["items"][0]["title"] = "Changed"

    assert client.list_tasks()[0]["items"][0]["title"] == "Nested"
