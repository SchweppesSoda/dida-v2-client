import json

from dida_v2_client import cli
from dida_v2_client.transport import DidaV2Error


class FakeClient:
    def list_habits(self):
        return [{"id": "h1", "name": "Drink"}]

    def list_habit_sections(self):
        return [{"id": "s1", "name": "Morning"}]

    def batch_habits(self, **kwargs):
        return {"habits_batched": kwargs}

    def query_habit_checkins(self, habit_ids, after_stamp=0):
        return {"habit_ids": habit_ids, "after_stamp": after_stamp}

    def batch_habit_checkins(self, **kwargs):
        return {"checkins_batched": kwargs}

    def ensure_ok_response(self, response):
        return response

    def user_profile(self):
        return {"profile": True}

    def user_preferences(self):
        return {"preferences": True}

    def productivity_stats(self):
        return {"productivity": True}

    def focus_heatmap(self, from_date, to_date):
        return {"heatmap": [from_date, to_date]}

    def focus_distribution(self, from_date, to_date):
        return {"distribution": [from_date, to_date]}

    def focus_timeline(self, to_timestamp=None):
        return {"timeline_to": to_timestamp}


def test_habits_list_and_sections_cli(monkeypatch, capsys):
    monkeypatch.setattr(cli, "client_from_args", lambda args: FakeClient())

    assert cli.main(["habits", "list"]) == 0
    assert json.loads(capsys.readouterr().out) == [{"id": "h1", "name": "Drink"}]
    assert cli.main(["habits", "sections"]) == 0
    assert json.loads(capsys.readouterr().out) == [{"id": "s1", "name": "Morning"}]


def test_habits_batch_dry_run(monkeypatch, capsys):
    monkeypatch.setattr(cli, "client_from_args", lambda args: FakeClient())

    assert cli.main(["habits", "batch", "--add-json", '[{"name":"Drink"}]', "--delete-json", '["h2"]']) == 0

    assert json.loads(capsys.readouterr().out) == {
        "dry_run": True,
        "would_batch_habits": {"add": [{"name": "Drink"}], "update": [], "delete": ["h2"]},
    }


def test_habits_batch_apply_rejects_malformed_response(monkeypatch, capsys):
    class MalformedClient(FakeClient):
        def batch_habits(self, **kwargs):
            return {"unexpected": True}

        def ensure_ok_response(self, response):
            raise DidaV2Error("Habit batch returned an unrecognized response shape")

    monkeypatch.setattr(cli, "client_from_args", lambda args: MalformedClient())

    assert cli.main(["habits", "batch", "--add-json", '[{"name":"Drink"}]', "--apply"]) == 2
    assert "unrecognized response shape" in capsys.readouterr().err


def test_habit_checkins_query_and_batch_cli(monkeypatch, capsys):
    monkeypatch.setattr(cli, "client_from_args", lambda args: FakeClient())

    assert cli.main(["habits", "checkins", "query", "--habit-id", "h1", "--habit-id", "h2", "--after-stamp", "20260701"]) == 0
    assert json.loads(capsys.readouterr().out) == {"habit_ids": ["h1", "h2"], "after_stamp": 20260701}

    assert cli.main(["habits", "checkins", "batch", "--update-json", '[{"id":"c1"}]', "--apply"]) == 0
    assert json.loads(capsys.readouterr().out) == {"checkins_batched": {"add": [], "update": [{"id": "c1"}], "delete": []}}


def test_habit_checkins_batch_apply_rejects_malformed_response(monkeypatch, capsys):
    class MalformedClient(FakeClient):
        def batch_habit_checkins(self, **kwargs):
            return {"unexpected": True}

        def ensure_ok_response(self, response):
            raise DidaV2Error("Habit check-in batch returned an unrecognized response shape")

    monkeypatch.setattr(cli, "client_from_args", lambda args: MalformedClient())

    assert cli.main(["habits", "checkins", "batch", "--update-json", '[{"id":"c1"}]', "--apply"]) == 2
    assert "unrecognized response shape" in capsys.readouterr().err


def test_stats_cli(monkeypatch, capsys):
    monkeypatch.setattr(cli, "client_from_args", lambda args: FakeClient())

    assert cli.main(["stats", "profile"]) == 0
    assert json.loads(capsys.readouterr().out) == {"profile": True}
    assert cli.main(["stats", "focus-heatmap", "20260701", "20260709"]) == 0
    assert json.loads(capsys.readouterr().out) == {"heatmap": ["20260701", "20260709"]}
    assert cli.main(["stats", "focus-timeline", "--to", "12345"]) == 0
    assert json.loads(capsys.readouterr().out) == {"timeline_to": 12345}
