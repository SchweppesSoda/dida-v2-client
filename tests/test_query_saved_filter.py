from datetime import datetime
from zoneinfo import ZoneInfo

from dida_v2_client.query import DidaV2QueryService
from dida_v2_client.snapshot import SyncSnapshot


class SnapshotClient:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.snapshot_calls = 0

    def get_snapshot(self):
        self.snapshot_calls += 1
        return self.snapshot


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
