from dida_v2_client.query import DidaV2QueryService


class FakeClient:
    def list_project_folders(self):
        return [
            {"id": "g-work", "name": "Work"},
            {"id": "g-life", "name": "Life"},
        ]

    def list_projects(self):
        return [
            {"id": "p-work", "name": "Client Work", "groupId": "g-work", "kind": "TASK", "closed": False},
            {"id": "p-life", "name": "Home", "groupId": "g-life", "kind": "TASK", "closed": False},
            {"id": "p-note", "name": "Notes", "kind": "NOTE", "closed": False},
            {"id": "p-closed", "name": "Old", "groupId": "g-work", "kind": "TASK", "closed": True},
        ]

    def list_tasks(self):
        return [
            {
                "id": "t1",
                "projectId": "p-work",
                "title": "Prepare report",
                "content": "client alpha",
                "tags": ["work", "deep"],
                "priority": 5,
                "dueDate": "2026-07-10T09:00:00+0800",
                "startDate": "2026-07-09T08:30:00+0800",
                "items": [{"title": "draft"}],
            },
            {
                "id": "t2",
                "projectId": "p-work",
                "title": "Email Bob",
                "tags": ["work"],
                "priority": 1,
                "dueDate": "2026-07-12T13:00:00+0800",
            },
            {
                "id": "t3",
                "projectId": "p-life",
                "title": "Buy milk",
                "content": "organic",
                "tags": ["home"],
                "priority": 3,
                "dueDate": "2026-07-09T18:00:00+0800",
                "parentId": "parent-1",
            },
        ]


def test_workspace_map_groups_projects_and_counts_tasks():
    service = DidaV2QueryService(FakeClient())

    result = service.workspace_map(include_counts=True)

    assert result["project_count"] == 3
    work = next(folder for folder in result["folders"] if folder["id"] == "g-work")
    assert work["project_count"] == 1
    assert work["projects"][0]["name"] == "Client Work"
    assert work["projects"][0]["task_count_active"] == 2
    assert result["ungrouped_projects"][0]["id"] == "p-note"


def test_query_tasks_filters_by_folder_tags_text_priority_and_due_window():
    service = DidaV2QueryService(FakeClient())

    result = service.query_tasks(
        folder_names=["Work"],
        tags=["deep"],
        text_query="report alpha",
        keyword_mode="all",
        min_priority=3,
        due_from="2026-07-10T00:00:00+0800",
        due_to="2026-07-10T23:59:59+0800",
    )

    assert result["count"] == 1
    item = result["items"][0]
    assert item["id"] == "t1"
    assert item["project_name"] == "Client Work"
    assert item["folder_name"] == "Work"
    assert result["plan"]["source"] == "v2_sync"


def test_query_tasks_supports_parent_subtask_and_checklist_filters():
    service = DidaV2QueryService(FakeClient())

    checklist = service.query_tasks(has_checklist=True)
    subtasks = service.query_tasks(subtasks_only=True)
    parents = service.query_tasks(parent_only=True)

    assert [item["id"] for item in checklist["items"]] == ["t1"]
    assert [item["id"] for item in subtasks["items"]] == ["t3"]
    assert {item["id"] for item in parents["items"]} == {"t1", "t2"}


def test_query_agenda_matches_due_or_start_window():
    service = DidaV2QueryService(FakeClient())

    due = service.query_agenda("2026-07-09T00:00:00+0800", "2026-07-09T23:59:59+0800", date_field="due")
    scheduled = service.query_agenda("2026-07-09T00:00:00+0800", "2026-07-09T23:59:59+0800", date_field="scheduled")

    assert [item["id"] for item in due["items"]] == ["t3"]
    assert {item["id"] for item in scheduled["items"]} == {"t1", "t3"}


def test_query_agenda_compares_utc_task_dates_in_requested_timezone():
    class TimezoneClient(FakeClient):
        def list_tasks(self):
            return [
                {
                    "id": "tz-task",
                    "projectId": "p-work",
                    "title": "Local midnight",
                    "priority": 5,
                    "dueDate": "2026-07-09T16:00:00.000+0000",
                    "timeZone": "Asia/Shanghai",
                }
            ]

    service = DidaV2QueryService(TimezoneClient())

    result = service.query_agenda(
        "2026-07-10T00:00:00+08:00",
        "2026-07-10T23:59:59+08:00",
        date_field="due",
        timezone="Asia/Shanghai",
    )

    assert [item["id"] for item in result["items"]] == ["tz-task"]
    assert result["agenda_window"]["timezone"] == "Asia/Shanghai"


def test_priority_dashboard_splits_high_medium_low():
    service = DidaV2QueryService(FakeClient())

    result = service.priority_dashboard()

    assert [item["id"] for item in result["high"]] == ["t1"]
    assert [item["id"] for item in result["medium"]] == ["t3"]
    assert [item["id"] for item in result["low"]] == ["t2"]
    assert result["counts"] == {"high": 1, "medium": 1, "low": 1, "none": 0}
