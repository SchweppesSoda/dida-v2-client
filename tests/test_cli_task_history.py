import json

from dida_v2_client import cli


class FakeClient:
    def list_closed_tasks(self, *, from_date, to_date, status="Completed", limit=100):
        return [{"from": from_date, "to": to_date, "status": status, "limit": limit}]

    def list_trash_tasks(self, *, start=0, limit=500):
        return [{"start": start, "limit": limit}]


def test_tasks_closed_cli(monkeypatch, capsys):
    monkeypatch.setattr(cli, "client_from_args", lambda args: FakeClient())

    assert cli.main([
        "tasks",
        "closed",
        "--from",
        "2026-07-01 00:00:00",
        "--to",
        "2026-07-09 23:59:59",
        "--status",
        "Abandoned",
        "--limit",
        "50",
    ]) == 0

    assert json.loads(capsys.readouterr().out) == [
        {"from": "2026-07-01 00:00:00", "to": "2026-07-09 23:59:59", "status": "Abandoned", "limit": 50}
    ]


def test_tasks_trash_cli(monkeypatch, capsys):
    monkeypatch.setattr(cli, "client_from_args", lambda args: FakeClient())

    assert cli.main(["tasks", "trash", "--start", "5", "--limit", "20"]) == 0

    assert json.loads(capsys.readouterr().out) == [{"start": 5, "limit": 20}]
