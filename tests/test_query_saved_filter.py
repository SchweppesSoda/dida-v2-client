from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from dida_v2_client.config import DidaConfig
from dida_v2_client.query import DidaV2QueryService
from dida_v2_client.snapshot import SyncSnapshot
from dida_v2_client.transport import DidaV2Client, DidaV2Error


class UnboundSnapshotClient:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def get_snapshot(self):
        return self.snapshot


class SnapshotClient:
    config = DidaConfig.for_profile("dida")

    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.snapshot_calls = 0

    def _get_snapshot_with_identity(self):
        self.snapshot_calls += 1
        return self.snapshot, (self.config, None)

    def get_snapshot(self):
        self.snapshot_calls += 1
        return self.snapshot


class PreferencesClient(SnapshotClient):
    config = DidaConfig.for_profile("ticktick")

    def user_preferences(self, *, _identity=None):
        return {"timeZone": "America/New_York"}


class TickTickNoTimezoneClient(SnapshotClient):
    config = DidaConfig.for_profile("ticktick")

    def user_preferences(self, *, _identity=None):
        return {}


class DidaNoTimezoneClient(SnapshotClient):
    config = DidaConfig.for_profile("dida")

    def user_preferences(self, *, _identity=None):
        return {}


class IdentitySwitchingClient(DidaV2Client):
    def __init__(self, payload):
        super().__init__(DidaConfig.for_profile("dida"), "TOKEN_A")
        self.payload = payload
        self.preference_identities = []

    def full_sync(self, *, _identity=None):
        payload = self.payload
        self.set_identity(DidaConfig.for_profile("ticktick"), "TOKEN_B")
        return payload

    def user_preferences(self, *, _identity=None):
        self.preference_identities.append(_identity)
        config, _session = _identity or (self.config, self.session_token)
        return {"timeZone": "Asia/Shanghai" if config.profile == "dida" else "UTC"}


def test_saved_filter_query_rejects_unbound_snapshot_client(load_fixture):
    client = UnboundSnapshotClient(SyncSnapshot.from_payload(load_fixture("full_sync_with_filters.json")))

    with pytest.raises(DidaV2Error, match="identity-bound snapshot"):
        DidaV2QueryService(client).query_saved_filter(
            "filter-today-p1",
            now=datetime(2026, 7, 10, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
            timezone="Asia/Shanghai",
        )


def test_query_saved_filter_keeps_snapshot_and_preferences_on_one_identity(load_fixture):
    client = IdentitySwitchingClient(load_fixture("full_sync_with_filters.json"))
    service = DidaV2QueryService(client)

    result = service.query_saved_filter(
        "filter-today-p1",
        now=datetime(2026, 7, 10, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert result["timezone"] == "Asia/Shanghai"
    assert client.preference_identities == [(DidaConfig.for_profile("dida"), "TOKEN_A")]


def test_query_saved_filter_uses_one_snapshot_and_enriches_results(load_fixture):
    raw = load_fixture("full_sync_with_filters.json")
    raw["syncTaskBean"] = load_fixture("full_sync_timezone_edges.json")["syncTaskBean"]
    client = SnapshotClient(SyncSnapshot.from_payload(raw))
    service = DidaV2QueryService(client)

    result = service.query_saved_filter(
        "Today P1",
        now=datetime(2026, 7, 10, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
        timezone="Asia/Shanghai",
    )

    assert client.snapshot_calls == 1
    assert result["filter"]["name"] == "Today P1"
    assert result["count"] == 1
    assert result["items"][0]["id"] == "task-all-day-cn"
    assert result["items"][0]["project_name"] == "Work List"
    assert result["items"][0]["folder_name"] == "Work"
    assert result["grouping"] == "project"
    assert result["sort"] == {"groupBy": "project", "orderBy": "dueDate", "order": None}
    assert result["timezone"] == "Asia/Shanghai"
    assert result["explanation"]["operator"] == "and"


def test_query_saved_filter_uses_account_timezone_when_not_explicit(load_fixture):
    raw = load_fixture("full_sync_with_filters.json")
    client = PreferencesClient(SyncSnapshot.from_payload(raw))
    service = DidaV2QueryService(client)

    result = service.query_saved_filter(
        "filter-today-p1",
        now=datetime(2026, 7, 10, 9, tzinfo=ZoneInfo("America/New_York")),
    )

    assert result["timezone"] == "America/New_York"


def test_query_saved_filter_naive_now_uses_resolved_timezone(load_fixture):
    raw = load_fixture("full_sync_with_filters.json")
    service = DidaV2QueryService(PreferencesClient(SyncSnapshot.from_payload(raw)))

    result = service.query_saved_filter("filter-today-p1", now=datetime(2026, 7, 10, 9))

    assert result["timezone"] == "America/New_York"
    assert result["evaluated_at"] == "2026-07-10T09:00:00-04:00"


def test_query_saved_filter_explicit_timezone_overrides_account_preference(load_fixture):
    raw = load_fixture("full_sync_with_filters.json")
    client = PreferencesClient(SyncSnapshot.from_payload(raw))
    service = DidaV2QueryService(client)

    result = service.query_saved_filter(
        "filter-today-p1",
        now=datetime(2026, 7, 10, 9, tzinfo=ZoneInfo("Europe/London")),
        timezone="Europe/London",
    )

    assert result["timezone"] == "Europe/London"


def test_query_saved_filter_ticktick_profile_falls_back_to_utc(load_fixture):
    raw = load_fixture("full_sync_with_filters.json")
    service = DidaV2QueryService(TickTickNoTimezoneClient(SyncSnapshot.from_payload(raw)))

    result = service.query_saved_filter("filter-today-p1", now=datetime(2026, 7, 10, 9, tzinfo=ZoneInfo("UTC")))

    assert result["timezone"] == "UTC"


def test_query_saved_filter_dida_profile_falls_back_to_shanghai(load_fixture):
    raw = load_fixture("full_sync_with_filters.json")
    service = DidaV2QueryService(DidaNoTimezoneClient(SyncSnapshot.from_payload(raw)))

    result = service.query_saved_filter(
        "filter-today-p1",
        now=datetime(2026, 7, 10, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert result["timezone"] == "Asia/Shanghai"


def test_query_saved_filter_accepts_filter_id(load_fixture):
    raw = load_fixture("full_sync_with_filters.json")
    client = SnapshotClient(SyncSnapshot.from_payload(raw))
    service = DidaV2QueryService(client)

    result = service.query_saved_filter(
        "filter-today-p1",
        now=datetime(2026, 7, 10, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
        timezone="Asia/Shanghai",
    )

    assert result["filter"]["id"] == "filter-today-p1"
