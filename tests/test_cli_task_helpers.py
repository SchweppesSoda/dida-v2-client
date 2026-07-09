import json

from dida_v2_client import cli


class FakeClient:
    def create_task(self, payload):
        return {"created": payload}

    def update_task(self, payload):
        return {"updated": payload}

    def delete_task(self, task_id, *, project_id):
        return {"deleted": {"task_id": task_id, "project_id": project_id}}

    def complete_task(self, task_id, *, project_id):
        return {"completed": {"task_id": task_id, "project_id": project_id}}

    def reopen_task(self, task_id, *, project_id):
        return {"reopened": {"task_id": task_id, "project_id": project_id}}

    def abandon_task(self, task_id, *, project_id):
        return {"abandoned": {"task_id": task_id, "project_id": project_id}}


def test_tasks_create_dry_run_builds_common_payload(monkeypatch, capsys):
    monkeypatch.setattr(cli, "client_from_args", lambda args: FakeClient())

    assert cli.main([
        "tasks", "create",
        "--title", "Smoke",
        "--project-id", "p1",
        "--content", "body",
        "--priority", "3",
        "--tag", "a",
        "--tag", "b",
        "--kind", "TEXT",
    ]) == 0

    assert json.loads(capsys.readouterr().out) == {
        "dry_run": True,
        "would_create_task": {
            "title": "Smoke",
            "projectId": "p1",
            "content": "body",
            "priority": 3,
            "tags": ["a", "b"],
            "kind": "TEXT",
        },
    }


def test_tasks_create_apply_calls_client(monkeypatch, capsys):
    monkeypatch.setattr(cli, "client_from_args", lambda args: FakeClient())

    assert cli.main(["tasks", "create", "--title", "Smoke", "--project-id", "p1", "--apply"]) == 0

    assert json.loads(capsys.readouterr().out) == {"created": {"title": "Smoke", "projectId": "p1"}}


def test_task_status_and_delete_commands_are_dry_run_by_default(monkeypatch, capsys):
    monkeypatch.setattr(cli, "client_from_args", lambda args: FakeClient())

    assert cli.main(["tasks", "complete", "t1", "--project-id", "p1"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "dry_run": True,
        "would_update_task": {"id": "t1", "projectId": "p1", "status": 2},
    }

    assert cli.main(["tasks", "reopen", "t1", "--project-id", "p1"]) == 0
    assert json.loads(capsys.readouterr().out)["would_update_task"]["status"] == 0

    assert cli.main(["tasks", "abandon", "t1", "--project-id", "p1"]) == 0
    assert json.loads(capsys.readouterr().out)["would_update_task"]["status"] == -1

    assert cli.main(["tasks", "delete", "t1", "--project-id", "p1"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "dry_run": True,
        "would_delete_task": {"task_id": "t1", "project_id": "p1"},
    }


def test_task_status_apply_calls_client(monkeypatch, capsys):
    monkeypatch.setattr(cli, "client_from_args", lambda args: FakeClient())

    assert cli.main(["tasks", "complete", "t1", "--project-id", "p1", "--apply"]) == 0
    assert json.loads(capsys.readouterr().out) == {"completed": {"task_id": "t1", "project_id": "p1"}}
