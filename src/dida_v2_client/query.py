from __future__ import annotations

import re
from datetime import datetime, timezone as dt_timezone
from typing import Any
from zoneinfo import ZoneInfo

from .datetime_utils import parse_dida_datetime
from .filters import FilterContext, SavedFilterEvaluator
from .snapshot import SyncSnapshot
from .transport import DidaV2Error


class DidaV2QueryService:
    """High-level v2-first query layer inspired by tick-mcp's QueryService.

    This service is deliberately dict-based so it can sit on top of the small
    Dida365-first client without pulling in pydantic or the MCP stack.
    """

    def __init__(self, client: Any):
        self.client = client

    def workspace_map(
        self,
        *,
        include_closed: bool = False,
        include_counts: bool = False,
        project_name_query: str | None = None,
        project_regex: str | None = None,
        folder_name_query: str | None = None,
        folder_regex: str | None = None,
    ) -> dict[str, Any]:
        folders = self._folders()
        projects = self._projects()
        folder_by_id = {folder.get("id"): folder for folder in folders}

        if not include_closed:
            projects = [project for project in projects if not project.get("closed")]
        if folder_name_query or folder_regex:
            allowed = {
                folder.get("id")
                for folder in folders
                if self._matches_text([folder.get("name")], folder_name_query, "any", folder_regex)
            }
            projects = [project for project in projects if project.get("groupId") in allowed]
        if project_name_query or project_regex:
            projects = [
                project
                for project in projects
                if self._matches_text(
                    [project.get("name"), folder_by_id.get(project.get("groupId"), {}).get("name")],
                    project_name_query,
                    "any",
                    project_regex,
                )
            ]

        active_counts: dict[str, int] = {}
        if include_counts:
            for task in self._tasks():
                project_id = task.get("projectId")
                if project_id:
                    active_counts[project_id] = active_counts.get(project_id, 0) + 1

        grouped: dict[str | None, list[dict[str, Any]]] = {}
        for project in projects:
            row = dict(project)
            folder = folder_by_id.get(project.get("groupId"))
            row["folder_name"] = folder.get("name") if folder else None
            if include_counts:
                row["task_count_active"] = active_counts.get(project.get("id"), 0)
            else:
                row["task_count_active"] = None
            grouped.setdefault(project.get("groupId"), []).append(row)

        folder_rows: list[dict[str, Any]] = []
        for folder in folders:
            folder_id = folder.get("id")
            projects_in_folder = sorted(grouped.get(folder_id, []), key=lambda item: item.get("name") or "")
            if not projects_in_folder:
                continue
            folder_rows.append({**folder, "project_count": len(projects_in_folder), "projects": projects_in_folder})

        return {
            "folders": sorted(folder_rows, key=lambda item: item.get("name") or ""),
            "ungrouped_projects": sorted(grouped.get(None, []), key=lambda item: item.get("name") or ""),
            "project_count": len(projects),
            "folder_count": len(folder_rows),
            "include_counts": include_counts,
        }

    def query_tasks(
        self,
        *,
        project_ids: list[str] | None = None,
        project_names: list[str] | None = None,
        folder_ids: list[str] | None = None,
        folder_names: list[str] | None = None,
        tags: list[str] | None = None,
        tag_mode: str = "any",
        text_query: str | None = None,
        keyword_mode: str = "any",
        regex: str | None = None,
        exclude_regex: str | None = None,
        due_from: str | None = None,
        due_to: str | None = None,
        start_from: str | None = None,
        start_to: str | None = None,
        min_priority: int | None = None,
        priorities: list[int] | None = None,
        has_reminders: bool | None = None,
        is_recurring: bool | None = None,
        has_checklist: bool | None = None,
        parent_only: bool = False,
        subtasks_only: bool = False,
        limit: int = 50,
        sort_by: str = "dueDate",
        descending: bool = False,
        timezone: str | None = None,
    ) -> dict[str, Any]:
        projects = self._projects()
        folders = self._folders()
        folder_by_id = {folder.get("id"): folder for folder in folders}
        project_by_id = {project.get("id"): project for project in projects}

        allowed_project_ids = self._resolve_project_ids(
            projects=projects,
            folders=folders,
            project_ids=project_ids,
            project_names=project_names,
            folder_ids=folder_ids,
            folder_names=folder_names,
        )
        allowed_tags = set(tags or [])
        allowed_priorities = set(priorities or [])
        exclude_re = re.compile(exclude_regex, re.I) if exclude_regex else None

        rows: list[dict[str, Any]] = []
        for task in self._tasks():
            project_id = task.get("projectId")
            if allowed_project_ids is not None and project_id not in allowed_project_ids:
                continue
            task_tags = set(task.get("tags") or [])
            if allowed_tags:
                if tag_mode == "all" and not allowed_tags.issubset(task_tags):
                    continue
                if tag_mode != "all" and allowed_tags.isdisjoint(task_tags):
                    continue
            if min_priority is not None and int(task.get("priority") or 0) < min_priority:
                continue
            if allowed_priorities and int(task.get("priority") or 0) not in allowed_priorities:
                continue
            if has_reminders is not None and bool(task.get("reminders")) is not has_reminders:
                continue
            if is_recurring is not None and bool(task.get("repeatFlag") or task.get("repeatFrom")) is not is_recurring:
                continue
            if has_checklist is not None and bool(task.get("items")) is not has_checklist:
                continue
            is_subtask = bool(task.get("parentId"))
            if parent_only and is_subtask:
                continue
            if subtasks_only and not is_subtask:
                continue
            if not self._in_range(task.get("dueDate"), due_from, due_to, timezone):
                continue
            if not self._in_range(task.get("startDate"), start_from, start_to, timezone):
                continue

            project = project_by_id.get(project_id, {})
            folder = folder_by_id.get(project.get("groupId"), {})
            text_values = [
                task.get("title"),
                task.get("content"),
                task.get("desc"),
                " ".join(task.get("tags") or []),
                project.get("name"),
                folder.get("name"),
            ]
            if not self._matches_text(text_values, text_query, keyword_mode, regex, exclude_re=exclude_re):
                continue
            row = dict(task)
            row["project_name"] = project.get("name")
            row["folder_name"] = folder.get("name")
            rows.append(row)

        rows.sort(key=lambda item: self._sort_value(item, sort_by), reverse=descending)
        limited = rows[:limit]
        return {
            "count": len(limited),
            "items": limited,
            "plan": {"source": "v2_sync", "project_ids": sorted(allowed_project_ids) if allowed_project_ids else [], "project_count": len(allowed_project_ids or [])},
            "applied_filters": {
                "project_ids": project_ids,
                "project_names": project_names,
                "folder_ids": folder_ids,
                "folder_names": folder_names,
                "tags": tags,
                "text_query": text_query,
            },
        }

    def query_agenda(
        self,
        from_dt: str,
        to_dt: str,
        *,
        date_field: str = "scheduled",
        limit: int = 50,
        timezone: str | None = None,
        **filters: Any,
    ) -> dict[str, Any]:
        result = self.query_tasks(limit=10000, timezone=timezone, **filters)
        items = [
            item
            for item in result["items"]
            if self._matches_agenda_window(item, from_dt, to_dt, date_field, timezone)
        ]
        result["items"] = items[:limit]
        result["count"] = len(result["items"])
        result["agenda_window"] = {
            "from": from_dt,
            "to": to_dt,
            "date_field": date_field,
            "timezone": timezone,
        }
        return result

    def priority_dashboard(self, *, limit: int = 50, **filters: Any) -> dict[str, Any]:
        result = self.query_tasks(limit=10000, **filters)
        buckets: dict[str, list[dict[str, Any]]] = {"high": [], "medium": [], "low": [], "none": []}
        for item in result["items"]:
            priority = int(item.get("priority") or 0)
            if priority >= 5:
                buckets["high"].append(item)
            elif priority >= 3:
                buckets["medium"].append(item)
            elif priority >= 1:
                buckets["low"].append(item)
            else:
                buckets["none"].append(item)
        return {
            "high": buckets["high"][:limit],
            "medium": buckets["medium"][:limit],
            "low": buckets["low"][:limit],
            "none": buckets["none"][:limit],
            "counts": {key: len(value) for key, value in buckets.items()},
        }

    def query_saved_filter(
        self,
        name_or_id: str,
        *,
        now: datetime | None = None,
        timezone: str | None = None,
    ) -> dict[str, Any]:
        get_snapshot = getattr(self.client, "get_snapshot", None)
        if not callable(get_snapshot):
            raise DidaV2Error("Saved-filter queries require a client with get_snapshot()")
        snapshot = get_snapshot()
        if not isinstance(snapshot, SyncSnapshot):
            raise DidaV2Error("get_snapshot() returned an unsupported snapshot type")
        filters = [dict(item) for item in snapshot.filters]
        matches = [item for item in filters if item.get("id") == name_or_id or item.get("name") == name_or_id]
        if not matches:
            raise DidaV2Error(f"Saved filter not found: {name_or_id}")
        if len(matches) > 1:
            raise DidaV2Error(f"Saved filter is ambiguous: {name_or_id}")
        saved_filter = matches[0]
        timezone_name = timezone or "Asia/Shanghai"
        evaluated_at = now or datetime.now(ZoneInfo(timezone_name))
        evaluator = SavedFilterEvaluator()
        parsed = evaluator.parse(saved_filter.get("rule") or {})
        projects = [dict(item) for item in snapshot.projects]
        folders = [dict(item) for item in snapshot.project_groups]
        project_by_id: dict[str, dict[str, Any]] = {}
        folder_by_id: dict[str, dict[str, Any]] = {}
        for item in projects:
            item_id = item.get("id")
            if isinstance(item_id, str):
                project_by_id[item_id] = item
        for item in folders:
            item_id = item.get("id")
            if isinstance(item_id, str):
                folder_by_id[item_id] = item
        context = FilterContext(
            now=evaluated_at,
            timezone=timezone_name,
            project_by_id=project_by_id,
            folder_by_id=folder_by_id,
        )
        items = evaluator.filter_tasks([dict(item) for item in snapshot.tasks], parsed, context)
        enriched: list[dict[str, Any]] = []
        for task in items:
            row = dict(task)
            project_id = task.get("projectId")
            project = project_by_id.get(project_id, {}) if isinstance(project_id, str) else {}
            group_id = project.get("groupId")
            folder = folder_by_id.get(group_id, {}) if isinstance(group_id, str) else {}
            row["project_name"] = project.get("name")
            row["folder_name"] = folder.get("name")
            enriched.append(row)
        raw_sort_option = saved_filter.get("sortOption")
        sort_option: dict[str, Any] = dict(raw_sort_option) if isinstance(raw_sort_option, dict) else {}
        order_by = sort_option.get("orderBy")
        if order_by:
            enriched.sort(
                key=lambda item: self._sort_value(item, str(order_by)),
                reverse=str(sort_option.get("order") or "").lower() == "desc",
            )
        return {
            "filter": saved_filter,
            "parsed_rule": parsed,
            "explanation": evaluator.explain(parsed),
            "count": len(enriched),
            "items": enriched,
            "grouping": saved_filter.get("sortType") or sort_option.get("groupBy"),
            "sort": dict(sort_option),
            "timezone": timezone_name,
            "evaluated_at": evaluated_at.isoformat(),
        }

    def _folders(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self.client.list_project_folders()]

    def _projects(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self.client.list_projects()]

    def _tasks(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self.client.list_tasks()]

    def _resolve_project_ids(
        self,
        *,
        projects: list[dict[str, Any]],
        folders: list[dict[str, Any]],
        project_ids: list[str] | None,
        project_names: list[str] | None,
        folder_ids: list[str] | None,
        folder_names: list[str] | None,
    ) -> set[str] | None:
        explicit = set(project_ids or [])
        names = [name.lower() for name in (project_names or [])]
        folder_filter = set(folder_ids or [])
        if folder_names:
            wanted = [name.lower() for name in folder_names]
            folder_filter.update(
                folder.get("id")
                for folder in folders
                if folder.get("id") and any(name in (folder.get("name") or "").lower() for name in wanted)
            )
        has_filter = bool(explicit or names or folder_filter)
        if not has_filter:
            return None
        resolved: set[str] = set(explicit)
        for project in projects:
            project_id = project.get("id")
            if not project_id:
                continue
            if names and any(name in (project.get("name") or "").lower() for name in names):
                resolved.add(project_id)
            if folder_filter and project.get("groupId") in folder_filter:
                resolved.add(project_id)
        return resolved

    def _matches_text(
        self,
        values: list[Any],
        text_query: str | None,
        keyword_mode: str = "any",
        regex: str | None = None,
        exclude_re: re.Pattern[str] | None = None,
    ) -> bool:
        blob = " ".join(str(value) for value in values if value is not None).lower()
        if exclude_re and exclude_re.search(blob):
            return False
        if regex and not re.search(regex, blob, re.I):
            return False
        if not text_query:
            return True
        words = [word.lower() for word in text_query.split() if word]
        if keyword_mode == "phrase":
            return text_query.lower() in blob
        if keyword_mode == "all":
            return all(word in blob for word in words)
        return any(word in blob for word in words)

    def _in_range(
        self,
        raw: Any,
        start: str | None,
        end: str | None,
        timezone_name: str | None = None,
    ) -> bool:
        if not start and not end:
            return True
        if not raw:
            return False
        value = self._date_key(str(raw), timezone_name)
        if start and value < self._date_key(start, timezone_name):
            return False
        if end and value > self._date_key(end, timezone_name):
            return False
        return True

    def _matches_agenda_window(
        self,
        task: dict[str, Any],
        start: str,
        end: str,
        date_field: str,
        timezone_name: str | None = None,
    ) -> bool:
        if date_field == "due":
            return self._in_range(task.get("dueDate"), start, end, timezone_name)
        if date_field == "start":
            return self._in_range(task.get("startDate"), start, end, timezone_name)
        return self._in_range(task.get("dueDate"), start, end, timezone_name) or self._in_range(
            task.get("startDate"), start, end, timezone_name
        )

    def _date_key(self, raw: str, timezone_name: str | None = None) -> datetime:
        return parse_dida_datetime(raw, assume_timezone=timezone_name or "UTC").astimezone(dt_timezone.utc)

    def _sort_value(self, item: dict[str, Any], sort_by: str) -> Any:
        if sort_by in {"dueDate", "startDate", "createdTime", "modifiedTime"}:
            value = item.get(sort_by)
            return (value is None, self._date_key(str(value)).timestamp() if value else 0.0)
        return item.get(sort_by) or ""
