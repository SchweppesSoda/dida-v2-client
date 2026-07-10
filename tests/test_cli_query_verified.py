import json

from dida_v2_client import cli


class FakeQueryService:
    def __init__(self, client):
        self.client = client

    def workspace_map(self, include_counts=False, **kwargs):
        return {"workspace": True, "include_counts": include_counts}

    def query_tasks(self, **kwargs):
        return {"tasks": kwargs}

    def query_agenda(self, from_dt, to_dt, **kwargs):
        return {"agenda": {"from": from_dt, "to": to_dt, **kwargs}}

    def priority_dashboard(self, **kwargs):
        return {"priority": kwargs}


class FakeVerifier:
    def __init__(self, client):
        self.client = client

    def verified_move_task(self, task_id, *, from_project_id, to_project_id):
        return {"verified_move": {"task_id": task_id, "from": from_project_id, "to": to_project_id}}

    def verified_set_task_parent(self, task_id, *, project_id, parent_id):
        return {"verified_set_parent": {"task_id": task_id, "project_id": project_id, "parent_id": parent_id}}

    def verified_set_project_folder(self, project_id, folder_id):
        return {"verified_project_folder": {"project_id": project_id, "folder_id": folder_id}}


def test_query_cli_workspace_and_tasks(monkeypatch, capsys):
    monkeypatch.setattr(cli, "client_from_args", lambda args: object())
    monkeypatch.setattr(cli, "DidaV2QueryService", FakeQueryService)

    assert cli.main(["query", "workspace", "--counts"]) == 0
    assert json.loads(capsys.readouterr().out) == {"workspace": True, "include_counts": True}

    assert cli.main(["query", "tasks", "--tag", "work", "--text", "alpha", "--min-priority", "3"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["tasks"]["tags"] == ["work"]
    assert result["tasks"]["text_query"] == "alpha"
    assert result["tasks"]["min_priority"] == 3


def test_query_cli_agenda_and_priority(monkeypatch, capsys):
    monkeypatch.setattr(cli, "client_from_args", lambda args: object())
    monkeypatch.setattr(cli, "DidaV2QueryService", FakeQueryService)

    assert cli.main(
        [
            "query",
            "agenda",
            "2026-07-09",
            "2026-07-10",
            "--date-field",
            "scheduled",
            "--timezone",
            "Asia/Shanghai",
        ]
    ) == 0
    assert json.loads(capsys.readouterr().out)["agenda"] == {
        "from": "2026-07-09",
        "to": "2026-07-10",
        "date_field": "scheduled",
        "timezone": "Asia/Shanghai",
    }

    assert cli.main(["query", "priority-dashboard", "--limit", "10"]) == 0
    assert json.loads(capsys.readouterr().out) == {"priority": {"limit": 10}}


def test_verified_cli_uses_verifier(monkeypatch, capsys):
    monkeypatch.setattr(cli, "client_from_args", lambda args: object())
    monkeypatch.setattr(cli, "DidaV2Verifier", FakeVerifier)

    assert cli.main(["verified", "move", "t1", "--from-project", "p1", "--to-project", "p2", "--apply"]) == 0
    assert json.loads(capsys.readouterr().out) == {"verified_move": {"task_id": "t1", "from": "p1", "to": "p2"}}

    assert cli.main(["verified", "set-parent", "child", "p1", "parent", "--apply"]) == 0
    assert json.loads(capsys.readouterr().out)["verified_set_parent"]["parent_id"] == "parent"

    assert cli.main(["verified", "project-folder", "p1", "g1", "--apply"]) == 0
    assert json.loads(capsys.readouterr().out)["verified_project_folder"]["folder_id"] == "g1"
