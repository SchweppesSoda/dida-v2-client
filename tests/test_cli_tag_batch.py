import json

from dida_v2_client import cli


class FakeClient:
    def create_tag(self, **kwargs):
        return {"created": kwargs}

    def update_tag(self, **kwargs):
        return {"updated": kwargs}


def test_tags_create_defaults_to_dry_run(monkeypatch, capsys):
    monkeypatch.setattr(cli, "client_from_args", lambda args: FakeClient())

    assert cli.main(["tags", "create", "新标签", "--color", "#fff"]) == 0

    assert json.loads(capsys.readouterr().out) == {
        "dry_run": True,
        "would_create_tag": {"name": "新标签", "color": "#fff", "parent": None, "sort_type": None},
    }


def test_tags_update_apply_calls_client(monkeypatch, capsys):
    monkeypatch.setattr(cli, "client_from_args", lambda args: FakeClient())

    assert cli.main(["tags", "update", "新标签", "--parent", "", "--sort-order", "12", "--apply"]) == 0

    assert json.loads(capsys.readouterr().out) == {
        "updated": {"name": "新标签", "color": None, "parent": "", "sort_type": None, "sort_order": 12}
    }
