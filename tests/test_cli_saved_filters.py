import json

from dida_v2_client import cli


FILTER = {
    "id": "filter-today-p1",
    "name": "Today P1",
    "rule": '{"and":[{"conditionName":"priority","or":[5]}]}',
}


class FakeClient:
    def list_filters(self):
        return [FILTER]

    def get_filter(self, filter_id):
        assert filter_id == "filter-today-p1"
        return FILTER

    def find_filter(self, name):
        return FILTER if name == "Today P1" else None


class FakeQueryService:
    def __init__(self, client):
        self.client = client

    def query_saved_filter(self, name_or_id, **kwargs):
        if kwargs.get("now") is not None:
            kwargs["now"] = kwargs["now"].isoformat()
        return {"selector": name_or_id, **kwargs, "count": 1, "items": []}


def test_filters_cli_list_get_and_explain(monkeypatch, capsys):
    monkeypatch.setattr(cli, "client_from_args", lambda args: FakeClient())

    assert cli.main(["filters", "list"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["name"] == "Today P1"

    assert cli.main(["filters", "get", "--name", "Today P1"]) == 0
    assert json.loads(capsys.readouterr().out)["id"] == "filter-today-p1"

    assert cli.main(["filters", "explain", "--id", "filter-today-p1"]) == 0
    explanation = json.loads(capsys.readouterr().out)
    assert explanation["filter"]["name"] == "Today P1"
    assert explanation["explanation"]["operator"] == "and"


def test_filters_cli_run_passes_timezone_and_now(monkeypatch, capsys):
    monkeypatch.setattr(cli, "client_from_args", lambda args: FakeClient())
    monkeypatch.setattr(cli, "DidaV2QueryService", FakeQueryService)

    assert (
        cli.main(
            [
                "filters",
                "run",
                "--name",
                "Today P1",
                "--timezone",
                "Asia/Shanghai",
                "--now",
                "2026-07-10T09:00:00+08:00",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["selector"] == "Today P1"
    assert result["timezone"] == "Asia/Shanghai"
    assert result["now"] == "2026-07-10T09:00:00+08:00"
