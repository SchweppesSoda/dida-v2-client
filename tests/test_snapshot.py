from dida_v2_client.snapshot import SyncSnapshot


def test_snapshot_extracts_sync_collections(load_fixture):
    raw = load_fixture("full_sync_with_filters.json")

    snapshot = SyncSnapshot.from_payload(raw)

    assert snapshot.filters[0]["name"] == "Today P1"
    assert snapshot.projects[0]["id"] == "project-1"
    assert snapshot.project_groups[0]["id"] == "group-work"
    assert snapshot.tags[0]["name"] == "work"
    assert snapshot.tasks == ()
    assert snapshot.checkpoint == 101


def test_snapshot_extracts_tasks_from_sync_task_bean(load_fixture):
    snapshot = SyncSnapshot.from_payload(load_fixture("full_sync_minimal.json"))

    assert [task["id"] for task in snapshot.tasks] == ["task-1"]


def test_snapshot_handles_non_dict_payload():
    snapshot = SyncSnapshot.from_payload([])

    assert snapshot.tasks == ()
    assert snapshot.projects == ()
    assert dict(snapshot.raw) == {}
