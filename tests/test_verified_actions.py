from contextlib import contextmanager
from threading import Event, Thread
from urllib.parse import urlparse

import pytest

from dida_v2_client.config import DidaConfig
from dida_v2_client.snapshot import SyncSnapshot
from dida_v2_client.transport import DidaV2Client
from dida_v2_client.verify import DidaV2Verifier, VerificationError


class FakeClient:
    def __init__(self):
        self.moves = []
        self.parents = []
        self.folder_updates = []
        self.task_updates = []
        self.tasks = [
            {"id": "parent", "projectId": "p1", "title": "Parent", "childIds": []},
            {"id": "child", "projectId": "p1", "title": "Child"},
            {"id": "moved", "projectId": "p1", "title": "Move me"},
        ]
        self.projects = [
            {"id": "p1", "name": "Inbox", "groupId": None},
            {"id": "p2", "name": "Work", "groupId": "g-old"},
        ]

    @contextmanager
    def _identity_operation(self):
        yield

    def ensure_batch_ok(self, response):
        if not isinstance(response, dict) or not isinstance(response.get("id2etag"), dict):
            raise VerificationError("strict batch validation required")
        if not isinstance(response.get("id2error"), dict) or response["id2error"]:
            raise VerificationError("strict batch validation required")
        return response

    def _get_snapshot_with_identity(self, refresh=False):
        return (
            SyncSnapshot.from_payload(
                {
                    "projectProfiles": self.projects,
                    "syncTaskBean": {"update": self.tasks},
                }
            ),
            (None, None),
        )

    def list_tasks(self):
        return [dict(task) for task in self.tasks]

    def get_task(self, task_id, *, project_id=None):
        for task in self.tasks:
            if task["id"] == task_id and (project_id is None or task.get("projectId") == project_id):
                return dict(task)
        raise RuntimeError("not found")

    def list_projects(self):
        return [dict(project) for project in self.projects]

    def update_task(self, task):
        self.task_updates.append(dict(task))
        for current in self.tasks:
            if current["id"] == task["id"] and current.get("projectId") == task.get("projectId"):
                current.update(task)
                break
        return {"id2etag": {task["id"]: "etag"}, "id2error": {}}

    def set_task_parent(self, task_id, *, project_id, parent_id):
        self.parents.append({"task_id": task_id, "project_id": project_id, "parent_id": parent_id})
        for task in self.tasks:
            if task["id"] == task_id:
                task["parentId"] = parent_id
            if task["id"] == parent_id:
                task.setdefault("childIds", [])
                if task_id not in task["childIds"]:
                    task["childIds"].append(task_id)
        return {"id2etag": {task_id: "etag"}, "id2error": {}}

    def unset_task_parent(self, task_id, *, project_id, old_parent_id):
        self.parents.append({"task_id": task_id, "project_id": project_id, "old_parent_id": old_parent_id})
        for task in self.tasks:
            if task["id"] == task_id:
                task.pop("parentId", None)
            if task["id"] == old_parent_id:
                task["childIds"] = [child for child in task.get("childIds", []) if child != task_id]
        return {"id2etag": {task_id: "etag"}, "id2error": {}}

    def move_task(self, task_id, *, from_project_id, to_project_id):
        self.moves.append({"task_id": task_id, "from_project_id": from_project_id, "to_project_id": to_project_id})
        for task in self.tasks:
            if task["id"] == task_id and task["projectId"] == from_project_id:
                task["projectId"] = to_project_id
        return {"id2etag": {task_id: "etag"}, "id2error": {}}

    def set_project_folder(self, project_id, folder_id):
        self.folder_updates.append({"project_id": project_id, "folder_id": folder_id})
        for project in self.projects:
            if project["id"] == project_id:
                project["groupId"] = folder_id
        return {"id2etag": {project_id: "etag"}, "id2error": {}}


def test_verifier_rejects_client_without_identity_binding():
    class UnboundClient(FakeClient):
        _identity_operation = None

    with pytest.raises(VerificationError, match="identity-bound"):
        DidaV2Verifier(UnboundClient()).verified_set_project_folder("p2", "g-new")


def test_verifier_rejects_client_without_snapshot_readback():
    class ListOnlyClient(FakeClient):
        _get_snapshot_with_identity = None

    with pytest.raises(VerificationError, match="identity-bound SyncSnapshot"):
        DidaV2Verifier(ListOnlyClient()).verified_set_project_folder("p2", "g-new")


def test_verifier_rejects_client_without_strict_batch_validation():
    class NoValidatorClient(FakeClient):
        ensure_batch_ok = None

        def set_project_folder(self, project_id, folder_id):
            super().set_project_folder(project_id, folder_id)
            return {"unexpected": True}

    with pytest.raises(VerificationError, match="batch validation"):
        DidaV2Verifier(NoValidatorClient()).verified_set_project_folder("p2", "g-new")


def test_verified_set_and_unset_task_parent_reads_back_structure():
    client = FakeClient()
    verifier = DidaV2Verifier(client)

    set_result = verifier.verified_set_task_parent("child", project_id="p1", parent_id="parent")
    unset_result = verifier.verified_unset_task_parent("child", project_id="p1", old_parent_id="parent")

    assert set_result["verified"] is True
    assert set_result["verification"]["child_parent_id"] == "parent"
    assert "child" in set_result["verification"]["parent_child_ids"]
    assert unset_result["verified"] is True
    assert unset_result["verification"]["child_parent_id"] is None


def test_verified_move_task_reads_destination_project():
    client = FakeClient()
    verifier = DidaV2Verifier(client)

    result = verifier.verified_move_task("moved", from_project_id="p1", to_project_id="p2")

    assert result["verified"] is True
    assert result["verification"]["destination_project_id"] == "p2"
    assert result["task"]["projectId"] == "p2"


def test_verified_project_folder_reads_back_group_id():
    client = FakeClient()
    verifier = DidaV2Verifier(client)

    result = verifier.verified_set_project_folder("p2", "g-new")

    assert result["verified"] is True
    assert result["project"]["groupId"] == "g-new"


def test_verified_update_task_merges_full_record_and_checks_supported_fields():
    client = FakeClient()
    verifier = DidaV2Verifier(client)

    result = verifier.verified_update_task(
        "child",
        project_id="p1",
        changes={
            "title": "Updated",
            "priority": 5,
            "status": 0,
            "dueDate": "2026-07-11T09:00:00+0800",
            "startDate": "2026-07-11T08:00:00+0800",
            "tags": ["work", "focus"],
            "columnId": "column-1",
            "allDay": False,
            "items": [{"id": "item-1", "title": "Step", "status": 0}],
        },
    )

    assert result["verified"] is True
    assert result["verification"]["checked_fields"] == [
        "allDay",
        "columnId",
        "dueDate",
        "items",
        "priority",
        "startDate",
        "status",
        "tags",
        "title",
    ]
    assert client.task_updates[0]["id"] == "child"
    assert client.task_updates[0]["projectId"] == "p1"
    assert client.task_updates[0]["title"] == "Updated"
    assert result["task"]["tags"] == ["work", "focus"]


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"priority": True},
        {"priority": 2},
        {"status": 1},
        {"tags": "work"},
        {"tags": ["work", 1]},
        {"allDay": 1},
        {"items": ["not-an-object"]},
        {"reminders": [{"trigger": "PT0S"}]},
        {"repeatFlag": "RRULE:FREQ=DAILY"},
        {"projectId": "p2"},
        {"id": "other"},
        {"title": "   "},
        {"dueDate": "not-a-date"},
    ],
)
def test_verified_update_task_rejects_unverified_or_malformed_changes(changes):
    with pytest.raises(VerificationError):
        DidaV2Verifier(FakeClient()).verified_update_task("child", project_id="p1", changes=changes)


def test_verified_update_task_accepts_equivalent_datetime_formatting():
    class NormalizingClient(FakeClient):
        def update_task(self, task):
            normalized = dict(task)
            normalized["dueDate"] = normalized["dueDate"].replace("+0800", "+08:00")
            return super().update_task(normalized)

    result = DidaV2Verifier(NormalizingClient()).verified_update_task(
        "child",
        project_id="p1",
        changes={"dueDate": "2026-07-11T09:00:00+0800"},
    )
    assert result["verified"] is True


def test_verified_update_task_fails_when_readback_differs():
    class BrokenUpdateClient(FakeClient):
        def update_task(self, task):
            self.task_updates.append(dict(task))
            return {"id2etag": {task["id"]: "etag"}, "id2error": {}}

    with pytest.raises(VerificationError, match="did not verify"):
        DidaV2Verifier(BrokenUpdateClient()).verified_update_task(
            "child",
            project_id="p1",
            changes={"priority": 5},
        )


def test_verified_update_task_rejects_missing_original_task():
    with pytest.raises(VerificationError, match="not found"):
        DidaV2Verifier(FakeClient()).verified_update_task(
            "missing",
            project_id="p1",
            changes={"priority": 5},
        )


def test_verified_operations_raise_when_readback_does_not_match():
    class BrokenClient(FakeClient):
        def move_task(self, task_id, *, from_project_id, to_project_id):
            return {"id2etag": {task_id: "etag"}, "id2error": {}}

    verifier = DidaV2Verifier(BrokenClient())

    with pytest.raises(VerificationError, match="not found in destination"):
        verifier.verified_move_task("moved", from_project_id="p1", to_project_id="p2")


def test_verified_operation_blocks_identity_switch_until_readback(monkeypatch):
    class FakeResponse:
        def __init__(self, body):
            self._body = body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return self._body

    write_started = Event()
    release_write = Event()
    switch_done = Event()
    written = Event()
    seen_urls = []

    def fake_urlopen(req, timeout):
        seen_urls.append(req.full_url)
        if req.get_method() == "POST":
            write_started.set()
            assert release_write.wait(timeout=2)
            written.set()
            return FakeResponse(b'{"id2etag":{"p1":"etag"},"id2error":{}}')
        group_id = "g-new" if written.is_set() else "g-old"
        body = f'{{"projectProfiles":[{{"id":"p1","name":"Account A","groupId":"{group_id}"}}]}}'
        return FakeResponse(body.encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = DidaV2Client(DidaConfig.for_profile("dida"), "TOKEN_A")
    verifier = DidaV2Verifier(client)
    outcomes = []
    verify_worker = Thread(target=lambda: outcomes.append(verifier.verified_set_project_folder("p1", "g-new")))
    verify_worker.start()
    assert write_started.wait(timeout=2)

    switch_worker = Thread(
        target=lambda: (client.set_identity(DidaConfig.for_profile("ticktick"), "TOKEN_B"), switch_done.set())
    )
    switch_worker.start()
    identity_was_blocked = not switch_done.wait(timeout=0.05)
    release_write.set()
    verify_worker.join(timeout=2)
    switch_worker.join(timeout=2)

    assert identity_was_blocked
    assert not verify_worker.is_alive()
    assert not switch_worker.is_alive()
    assert outcomes[0]["verified"] is True
    assert all(urlparse(url).netloc == "api.dida365.com" for url in seen_urls)


def test_verified_parent_readback_uses_one_refreshed_snapshot(monkeypatch):
    class FakeResponse:
        def __init__(self, body):
            self._body = body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return self._body

    get_calls = 0

    def fake_urlopen(req, timeout):
        nonlocal get_calls
        if req.get_method() == "POST":
            return FakeResponse(b'{"id2etag":{"child":"etag"},"id2error":{}}')
        get_calls += 1
        if get_calls == 1:
            body = {
                "syncTaskBean": {
                    "update": [
                        {"id": "child", "projectId": "p1", "parentId": "parent"},
                        {"id": "parent", "projectId": "p1", "childIds": []},
                    ]
                }
            }
        else:
            body = {
                "syncTaskBean": {
                    "update": [
                        {"id": "child", "projectId": "p1", "parentId": None},
                        {"id": "parent", "projectId": "p1", "childIds": ["child"]},
                    ]
                }
            }
        import json

        return FakeResponse(json.dumps(body).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = DidaV2Client(DidaConfig.default(), "TOKEN", snapshot_ttl_seconds=0)

    with pytest.raises(VerificationError, match="did not verify"):
        DidaV2Verifier(client).verified_set_task_parent("child", project_id="p1", parent_id="parent")

    assert get_calls == 1
