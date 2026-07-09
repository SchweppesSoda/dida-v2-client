import json

from dida_v2_client import cli


class FakeClient:
    def list_columns(self, project_id):
        return [{"id": "c1", "projectId": project_id, "name": "Doing"}]

    def delete_column(self, project_id, column_id):
        return {"deleted": [project_id, column_id]}


def test_columns_delete_defaults_to_dry_run(monkeypatch, capsys):
    monkeypatch.setattr(cli, "client_from_args", lambda args: FakeClient())

    assert cli.main(["columns", "delete", "p1", "c1"]) == 0

    assert json.loads(capsys.readouterr().out) == {
        "dry_run": True,
        "would_delete_column": {"project_id": "p1", "column_id": "c1"},
    }


def test_columns_delete_apply_calls_client(monkeypatch, capsys):
    monkeypatch.setattr(cli, "client_from_args", lambda args: FakeClient())

    assert cli.main(["columns", "delete", "p1", "c1", "--apply"]) == 0

    assert json.loads(capsys.readouterr().out) == {"deleted": ["p1", "c1"]}


def test_columns_list_calls_client(monkeypatch, capsys):
    monkeypatch.setattr(cli, "client_from_args", lambda args: FakeClient())

    assert cli.main(["columns", "list", "p1"]) == 0

    assert json.loads(capsys.readouterr().out) == [{"id": "c1", "projectId": "p1", "name": "Doing"}]
