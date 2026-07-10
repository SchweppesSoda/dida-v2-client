import json

from dida_v2_client import cli
from dida_v2_client.config import DidaConfig
from dida_v2_client.datetime_utils import parse_dida_datetime
from dida_v2_client.transport import DidaV2Client


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

    def resolve_timezone(self, explicit=None):
        return explicit or "Asia/Shanghai"

    def query_saved_filter(self, name_or_id, **kwargs):
        timezone_name = self.resolve_timezone(kwargs.get("timezone"))
        kwargs["timezone"] = timezone_name
        if isinstance(kwargs.get("now"), str):
            kwargs["now"] = parse_dida_datetime(
                kwargs["now"],
                assume_timezone=timezone_name,
            )
        if kwargs.get("now") is not None:
            kwargs["now"] = kwargs["now"].isoformat()
        return {"selector": name_or_id, **kwargs, "count": 1, "items": []}


class NewYorkQueryService(FakeQueryService):
    def resolve_timezone(self, explicit=None):
        return explicit or "America/New_York"


class IdentitySwitchingCLIClient(DidaV2Client):
    def __init__(self):
        super().__init__(DidaConfig.for_profile("dida"), "TOKEN_A")

    def full_sync(self, *, _identity=None):
        config, _session = _identity or (self.config, self.session_token)
        return {
            "filters": [
                {
                    **FILTER,
                    "account": config.profile,
                }
            ],
            "syncTaskBean": {"update": []},
        }

    def user_preferences(self, *, _identity=None):
        if _identity is None:
            self.set_identity(DidaConfig.for_profile("ticktick"), "TOKEN_B")
            return {"timeZone": "Asia/Shanghai"}
        config, _session = _identity
        return {"timeZone": "Asia/Shanghai" if config.profile == "dida" else "UTC"}


def test_filters_cli_run_keeps_timezone_and_snapshot_on_one_identity(monkeypatch, capsys):
    client = IdentitySwitchingCLIClient()
    monkeypatch.setattr(cli, "client_from_args", lambda args: client)

    assert cli.main(["filters", "run", "--name", "Today P1", "--now", "2026-07-10T09:00:00"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["filter"]["account"] == "dida"
    assert result["timezone"] == "Asia/Shanghai"
    assert client.config.profile == "dida"


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


def test_filters_cli_reports_invalid_now_without_traceback(monkeypatch, capsys):
    monkeypatch.setattr(cli, "client_from_args", lambda args: FakeClient())
    monkeypatch.setattr(cli, "DidaV2QueryService", FakeQueryService)

    assert cli.main(["filters", "run", "--name", "Today P1", "--now", "not-a-date"]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("ERROR: ")
    assert "Traceback" not in captured.err


def test_filters_cli_reports_invalid_timezone_without_traceback(monkeypatch, capsys):
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
                "Not/A-Timezone",
                "--now",
                "2026-07-10T09:00:00",
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("ERROR: ")
    assert "Traceback" not in captured.err


def test_filters_cli_naive_now_uses_resolved_account_timezone(monkeypatch, capsys):
    monkeypatch.setattr(cli, "client_from_args", lambda args: FakeClient())
    monkeypatch.setattr(cli, "DidaV2QueryService", NewYorkQueryService)

    assert cli.main(["filters", "run", "--name", "Today P1", "--now", "2026-07-10T09:00:00"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["timezone"] == "America/New_York"
    assert result["now"] == "2026-07-10T09:00:00-04:00"


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
