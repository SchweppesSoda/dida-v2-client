import json

from dida_v2_client import cli
from dida_v2_client.transport import DidaV2Error


class FakeClient:
    def list_tasks(self):
        return [{"id": "t1", "projectId": "p1", "title": "A"}]

    def get_task(self, task_id, project_id=None):
        return {"id": task_id, "projectId": project_id, "title": "A"}

    def batch_tasks(self, **kwargs):
        return {"batched": kwargs}

    def ensure_batch_ok(self, response):
        return response

    def move_task(self, task_id, *, from_project_id, to_project_id):
        return {"moved": {"task_id": task_id, "from_project_id": from_project_id, "to_project_id": to_project_id}}

    def set_task_parent(self, task_id, *, project_id, parent_id):
        return {"set_parent": {"task_id": task_id, "project_id": project_id, "parent_id": parent_id}}

    def unset_task_parent(self, task_id, *, project_id, old_parent_id):
        return {"unset_parent": {"task_id": task_id, "project_id": project_id, "old_parent_id": old_parent_id}}


def test_tasks_list_cli(monkeypatch, capsys):
    monkeypatch.setattr(cli, "client_from_args", lambda args: FakeClient())

    assert cli.main(["tasks", "list"]) == 0

    assert json.loads(capsys.readouterr().out) == [{"id": "t1", "projectId": "p1", "title": "A"}]


def test_tasks_get_cli(monkeypatch, capsys):
    monkeypatch.setattr(cli, "client_from_args", lambda args: FakeClient())

    assert cli.main(["tasks", "get", "t1", "--project-id", "p1"]) == 0

    assert json.loads(capsys.readouterr().out) == {"id": "t1", "projectId": "p1", "title": "A"}


def test_tasks_batch_defaults_to_dry_run(monkeypatch, capsys):
    monkeypatch.setattr(cli, "client_from_args", lambda args: FakeClient())

    assert cli.main(["tasks", "batch", "--add-json", '[{"title":"New"}]', "--delete-json", '[{"taskId":"old"}]']) == 0

    assert json.loads(capsys.readouterr().out) == {
        "dry_run": True,
        "would_batch_tasks": {
            "add": [{"title": "New"}],
            "update": [],
            "delete": [{"taskId": "old"}],
        },
    }


def test_tasks_batch_apply(monkeypatch, capsys):
    monkeypatch.setattr(cli, "client_from_args", lambda args: FakeClient())

    assert cli.main(["tasks", "batch", "--update-json", '[{"id":"t1"}]', "--apply"]) == 0

    assert json.loads(capsys.readouterr().out) == {"batched": {"add": [], "update": [{"id": "t1"}], "delete": []}}


def test_tasks_batch_apply_rejects_malformed_response(monkeypatch, capsys):
    class MalformedClient(FakeClient):
        def batch_tasks(self, **kwargs):
            return {"unexpected": True}

        def ensure_batch_ok(self, response):
            raise DidaV2Error("V2 batch returned an unrecognized response shape")

    monkeypatch.setattr(cli, "client_from_args", lambda args: MalformedClient())

    assert cli.main(["tasks", "batch", "--update-json", '[{"id":"t1"}]', "--apply"]) == 2
    assert "unrecognized response shape" in capsys.readouterr().err


def test_tasks_move_dry_run(monkeypatch, capsys):
    monkeypatch.setattr(cli, "client_from_args", lambda args: FakeClient())

    assert cli.main(["tasks", "move", "t1", "--from-project", "p1", "--to-project", "p2"]) == 0

    assert json.loads(capsys.readouterr().out) == {
        "dry_run": True,
        "would_move_task": {"task_id": "t1", "from_project_id": "p1", "to_project_id": "p2"},
    }


def test_tasks_set_parent_apply(monkeypatch, capsys):
    monkeypatch.setattr(cli, "client_from_args", lambda args: FakeClient())

    assert cli.main(["tasks", "set-parent", "child", "p1", "parent", "--apply"]) == 0

    assert json.loads(capsys.readouterr().out) == {"set_parent": {"task_id": "child", "project_id": "p1", "parent_id": "parent"}}


def test_tasks_unset_parent_dry_run(monkeypatch, capsys):
    monkeypatch.setattr(cli, "client_from_args", lambda args: FakeClient())

    assert cli.main(["tasks", "unset-parent", "child", "p1", "parent"]) == 0

    assert json.loads(capsys.readouterr().out) == {
        "dry_run": True,
        "would_unset_task_parent": {"task_id": "child", "project_id": "p1", "old_parent_id": "parent"},
    }
