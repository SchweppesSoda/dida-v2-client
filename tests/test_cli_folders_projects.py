import json

from dida_v2_client import cli


class FakeClient:
    def list_project_folders(self):
        return [{"id": "g1", "name": "Work"}]

    def create_project_folder(self, name, sort_order=None):
        return {"created_folder": {"name": name, "sort_order": sort_order}}

    def update_project_folder(self, folder_id, name=None, sort_order=None):
        return {"updated_folder": {"id": folder_id, "name": name, "sort_order": sort_order}}

    def delete_project_folder(self, folder_id):
        return {"deleted_folder": folder_id}

    def list_projects(self):
        return [{"id": "p1", "name": "List", "groupId": "g1"}]

    def set_project_folder(self, project_id, folder_id):
        return {"set_project_folder": {"project_id": project_id, "folder_id": folder_id}}


def test_folders_list(monkeypatch, capsys):
    monkeypatch.setattr(cli, "client_from_args", lambda args: FakeClient())

    assert cli.main(["folders", "list"]) == 0

    assert json.loads(capsys.readouterr().out) == [{"id": "g1", "name": "Work"}]


def test_folders_create_defaults_to_dry_run(monkeypatch, capsys):
    monkeypatch.setattr(cli, "client_from_args", lambda args: FakeClient())

    assert cli.main(["folders", "create", "Work", "--sort-order", "10"]) == 0

    assert json.loads(capsys.readouterr().out) == {
        "dry_run": True,
        "would_create_folder": {"name": "Work", "sort_order": 10},
    }


def test_folders_delete_apply(monkeypatch, capsys):
    monkeypatch.setattr(cli, "client_from_args", lambda args: FakeClient())

    assert cli.main(["folders", "delete", "g1", "--apply"]) == 0

    assert json.loads(capsys.readouterr().out) == {"deleted_folder": "g1"}


def test_projects_list(monkeypatch, capsys):
    monkeypatch.setattr(cli, "client_from_args", lambda args: FakeClient())

    assert cli.main(["projects", "list"]) == 0

    assert json.loads(capsys.readouterr().out) == [{"id": "p1", "name": "List", "groupId": "g1"}]


def test_projects_set_folder_dry_run(monkeypatch, capsys):
    monkeypatch.setattr(cli, "client_from_args", lambda args: FakeClient())

    assert cli.main(["projects", "set-folder", "p1", "g2"]) == 0

    assert json.loads(capsys.readouterr().out) == {
        "dry_run": True,
        "would_set_project_folder": {"project_id": "p1", "folder_id": "g2"},
    }


def test_projects_set_folder_none_apply(monkeypatch, capsys):
    monkeypatch.setattr(cli, "client_from_args", lambda args: FakeClient())

    assert cli.main(["projects", "set-folder", "p1", "none", "--apply"]) == 0

    assert json.loads(capsys.readouterr().out) == {"set_project_folder": {"project_id": "p1", "folder_id": None}}
