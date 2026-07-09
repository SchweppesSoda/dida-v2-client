import pytest

from dida_v2_client.verify import DidaV2Verifier, VerificationError


class FakeClient:
    def __init__(self):
        self.moves = []
        self.parents = []
        self.folder_updates = []
        self.tasks = [
            {"id": "parent", "projectId": "p1", "title": "Parent", "childIds": []},
            {"id": "child", "projectId": "p1", "title": "Child"},
            {"id": "moved", "projectId": "p1", "title": "Move me"},
        ]
        self.projects = [
            {"id": "p1", "name": "Inbox", "groupId": None},
            {"id": "p2", "name": "Work", "groupId": "g-old"},
        ]

    def list_tasks(self):
        return [dict(task) for task in self.tasks]

    def get_task(self, task_id, *, project_id=None):
        for task in self.tasks:
            if task["id"] == task_id and (project_id is None or task.get("projectId") == project_id):
                return dict(task)
        raise RuntimeError("not found")

    def list_projects(self):
        return [dict(project) for project in self.projects]

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


def test_verified_operations_raise_when_readback_does_not_match():
    class BrokenClient(FakeClient):
        def move_task(self, task_id, *, from_project_id, to_project_id):
            return {"id2etag": {task_id: "etag"}, "id2error": {}}

    verifier = DidaV2Verifier(BrokenClient())

    with pytest.raises(VerificationError, match="not found in destination"):
        verifier.verified_move_task("moved", from_project_id="p1", to_project_id="p2")
