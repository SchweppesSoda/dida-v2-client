from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .config import DidaConfig
from .snapshot import SyncSnapshot


class DidaV2Error(RuntimeError):
    pass


class DidaV2Client:
    def __init__(self, config: DidaConfig | None = None, session_token: str | None = None):
        self.config = config or DidaConfig.default()
        self.session_token = session_token
        self._snapshot_cache: SyncSnapshot | None = None

    def _headers(self) -> dict[str, str]:
        if not self.session_token:
            raise DidaV2Error("Missing v2 session token. Use headless login or fallback DIDA_SESSION_TOKEN/TICKTICK_SESSION_TOKEN.")
        return {
            "Cookie": f"{self.config.cookie_name}={self.session_token}",
            "Content-Type": "application/json",
            "User-Agent": "dida-v2-client/0.1",
            "Origin": self.config.web_origin,
            "Referer": f"{self.config.web_origin}/",
            "X-Device": json.dumps(
                {
                    "platform": "web",
                    "os": "macOS",
                    "device": "dida-v2-client",
                    "name": "",
                    "version": 8006,
                    "id": "6790a0b0c1d2e3f4a5b6c7d8",
                    "channel": "website",
                    "campaign": "",
                    "websocket": "",
                },
                separators=(",", ":"),
            ),
        }

    def request(self, method: str, endpoint: str, *, params: dict[str, Any] | None = None, payload: Any = None) -> Any:
        url = f"{self.config.api_v2_base.rstrip('/')}/{endpoint.lstrip('/')}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=self._headers(), method=method.upper())
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8", "replace")
                result = {} if not raw else json.loads(raw)
                if method.upper() != "GET":
                    self._snapshot_cache = None
                return result
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            raise DidaV2Error(f"HTTP {exc.code} from {method.upper()} {endpoint}: {body[:300]}") from exc

    def user_status(self) -> Any:
        return self.request("GET", "/user/status")

    def full_sync(self) -> Any:
        return self.request("GET", "/batch/check/0")

    def get_snapshot(self, *, refresh: bool = False) -> SyncSnapshot:
        if refresh or self._snapshot_cache is None:
            self._snapshot_cache = SyncSnapshot.from_payload(self.full_sync())
        return self._snapshot_cache

    def list_filters(self, *, snapshot: SyncSnapshot | None = None) -> list[dict[str, Any]]:
        current = snapshot or self.get_snapshot()
        return [dict(item) for item in current.filters]

    def get_filter(self, filter_id: str, *, snapshot: SyncSnapshot | None = None) -> dict[str, Any]:
        matches = [item for item in self.list_filters(snapshot=snapshot) if item.get("id") == filter_id]
        if not matches:
            raise DidaV2Error(f"Saved filter not found: {filter_id}")
        return matches[0]

    def find_filter(self, name: str, *, snapshot: SyncSnapshot | None = None) -> dict[str, Any] | None:
        matches = [item for item in self.list_filters(snapshot=snapshot) if item.get("name") == name]
        if len(matches) > 1:
            raise DidaV2Error(f"Saved filter name is ambiguous: {name}")
        return matches[0] if matches else None

    def list_tasks(self, *, snapshot: SyncSnapshot | None = None) -> list[dict[str, Any]]:
        current = snapshot or self.get_snapshot()
        return [dict(task) for task in current.tasks]

    def get_task(self, task_id: str, *, project_id: str | None = None) -> dict[str, Any]:
        for task in self.list_tasks():
            if task.get("id") == task_id and (project_id is None or task.get("projectId") == project_id):
                return task
        suffix = f" in project {project_id}" if project_id else ""
        raise DidaV2Error(f"Task not found in v2 sync: {task_id}{suffix}")

    def batch_tasks(
        self,
        *,
        add: list[dict[str, Any]] | None = None,
        update: list[dict[str, Any]] | None = None,
        delete: list[dict[str, Any]] | None = None,
        add_attachments: list[dict[str, Any]] | None = None,
        update_attachments: list[dict[str, Any]] | None = None,
        delete_attachments: list[dict[str, Any]] | None = None,
    ) -> Any:
        return self.request(
            "POST",
            "/batch/task",
            payload={
                "add": add or [],
                "update": update or [],
                "delete": delete or [],
                "addAttachments": add_attachments or [],
                "updateAttachments": update_attachments or [],
                "deleteAttachments": delete_attachments or [],
            },
        )

    def batch_errors(self, response: Any) -> dict[str, Any]:
        if not isinstance(response, dict):
            return {}
        errors: dict[str, Any] = {}
        id2error = response.get("id2error")
        if isinstance(id2error, dict) and id2error:
            errors["id2error"] = id2error
        for key in ("errorId", "errorCode", "error"):
            if response.get(key):
                errors[key] = response[key]
        return errors

    def ensure_batch_ok(self, response: Any) -> Any:
        errors = self.batch_errors(response)
        if errors:
            raise DidaV2Error(f"V2 batch response contains errors: {json.dumps(errors, ensure_ascii=False)}")
        return response

    def create_task(self, task: dict[str, Any]) -> Any:
        return self.ensure_batch_ok(self.batch_tasks(add=[task]))

    def update_task(self, task: dict[str, Any]) -> Any:
        return self.ensure_batch_ok(self.batch_tasks(update=[task]))

    def delete_task(self, task_id: str, *, project_id: str) -> Any:
        return self.ensure_batch_ok(self.batch_tasks(delete=[{"taskId": task_id, "projectId": project_id}]))

    def complete_task(self, task_id: str, *, project_id: str) -> Any:
        return self.update_task({"id": task_id, "projectId": project_id, "status": 2})

    def reopen_task(self, task_id: str, *, project_id: str) -> Any:
        return self.update_task({"id": task_id, "projectId": project_id, "status": 0})

    def abandon_task(self, task_id: str, *, project_id: str) -> Any:
        return self.update_task({"id": task_id, "projectId": project_id, "status": -1})

    def move_tasks(self, moves: list[dict[str, Any]]) -> Any:
        return self.request("POST", "/batch/taskProject", payload=moves)

    def move_task(self, task_id: str, *, from_project_id: str, to_project_id: str) -> Any:
        return self.move_tasks([{"taskId": task_id, "fromProjectId": from_project_id, "toProjectId": to_project_id}])

    def batch_task_parents(self, relationships: list[dict[str, Any]]) -> Any:
        return self.request("POST", "/batch/taskParent", payload=relationships)

    def set_task_parent(self, task_id: str, *, project_id: str, parent_id: str) -> Any:
        return self.batch_task_parents([{"taskId": task_id, "projectId": project_id, "parentId": parent_id}])

    def unset_task_parent(self, task_id: str, *, project_id: str, old_parent_id: str) -> Any:
        return self.batch_task_parents([{"taskId": task_id, "projectId": project_id, "oldParentId": old_parent_id}])

    def list_tags(self, *, snapshot: SyncSnapshot | None = None) -> list[dict[str, Any]]:
        current = snapshot or self.get_snapshot()
        return [dict(tag) for tag in current.tags]

    def batch_tags(self, *, add: list[dict[str, Any]] | None = None, update: list[dict[str, Any]] | None = None) -> Any:
        return self.request("POST", "/batch/tag", payload={"add": add or [], "update": update or []})

    def create_tag(
        self,
        name: str,
        *,
        color: str | None = None,
        parent: str | None = None,
        sort_type: str | None = None,
    ) -> Any:
        tag: dict[str, Any] = {"name": name, "label": name}
        if color is not None:
            tag["color"] = color
        if parent is not None:
            tag["parent"] = parent
        if sort_type is not None:
            tag["sortType"] = sort_type
        return self.batch_tags(add=[tag])

    def update_tag(
        self,
        name: str,
        *,
        color: str | None = None,
        parent: str | None = None,
        sort_type: str | None = None,
        sort_order: int | None = None,
    ) -> Any:
        tag: dict[str, Any] = {"name": name}
        if color is not None:
            tag["color"] = color
        if parent is not None:
            tag["parent"] = parent
        if sort_type is not None:
            tag["sortType"] = sort_type
        if sort_order is not None:
            tag["sortOrder"] = sort_order
        return self.batch_tags(update=[tag])

    def delete_tag(self, name: str) -> Any:
        return self.request("DELETE", "/tag", params={"name": name})

    def rename_tag(self, old_name: str, new_name: str) -> Any:
        return self.request("PUT", "/tag/rename", payload={"name": old_name, "newName": new_name})

    def merge_tags(self, source_name: str, target_name: str) -> Any:
        return self.request("PUT", "/tag/merge", payload={"name": source_name, "newName": target_name})

    def list_columns(self, project_id: str) -> list[dict[str, Any]]:
        data = self.request("GET", f"/column/project/{project_id}")
        return [column for column in data if isinstance(column, dict)] if isinstance(data, list) else []

    def batch_columns(
        self,
        *,
        project_id: str,
        add: list[dict[str, Any]] | None = None,
        update: list[dict[str, Any]] | None = None,
        delete: list[str | dict[str, Any]] | None = None,
    ) -> Any:
        add_items = [dict(column, projectId=column.get("projectId", project_id)) for column in (add or [])]
        update_items = update or []
        delete_items = [
            column if isinstance(column, dict) else {"id": column, "projectId": project_id}
            for column in (delete or [])
        ]
        return self.request(
            "POST",
            "/column",
            payload={"add": add_items, "update": update_items, "delete": delete_items},
        )

    def delete_column(self, project_id: str, column_id: str) -> Any:
        return self.batch_columns(project_id=project_id, delete=[column_id])

    def list_project_folders(self, *, snapshot: SyncSnapshot | None = None) -> list[dict[str, Any]]:
        current = snapshot or self.get_snapshot()
        return [dict(folder) for folder in current.project_groups]

    def batch_project_folders(
        self,
        *,
        add: list[dict[str, Any]] | None = None,
        update: list[dict[str, Any]] | None = None,
        delete: list[str] | None = None,
    ) -> Any:
        return self.request(
            "POST",
            "/batch/projectGroup",
            payload={"add": add or [], "update": update or [], "delete": delete or []},
        )

    def create_project_folder(self, name: str, *, sort_order: int | None = None) -> Any:
        folder: dict[str, Any] = {"name": name}
        if sort_order is not None:
            folder["sortOrder"] = sort_order
        return self.batch_project_folders(add=[folder])

    def update_project_folder(self, folder_id: str, *, name: str | None = None, sort_order: int | None = None) -> Any:
        folder: dict[str, Any] = {"id": folder_id}
        if name is not None:
            folder["name"] = name
        if sort_order is not None:
            folder["sortOrder"] = sort_order
        return self.batch_project_folders(update=[folder])

    def delete_project_folder(self, folder_id: str) -> Any:
        return self.batch_project_folders(delete=[folder_id])

    def list_projects(self, *, snapshot: SyncSnapshot | None = None) -> list[dict[str, Any]]:
        current = snapshot or self.get_snapshot()
        return [dict(project) for project in current.projects]

    def batch_projects(self, *, update: list[dict[str, Any]]) -> Any:
        return self.request("POST", "/batch/project", payload={"update": update})

    def set_project_folder(self, project_id: str, folder_id: str | None) -> Any:
        project = next((item for item in self.list_projects() if item.get("id") == project_id), None)
        if project is None:
            raise DidaV2Error(f"Project not found in v2 sync: {project_id}")
        update_item = {key: value for key, value in project.items() if value is not None}
        update_item["id"] = project_id
        update_item["groupId"] = folder_id
        return self.batch_projects(update=[update_item])

    def list_closed_tasks(self, *, from_date: str, to_date: str, status: str = "Completed", limit: int = 100) -> list[dict[str, Any]]:
        data = self.request(
            "GET",
            "/project/all/closed",
            params={"from": from_date, "to": to_date, "status": status, "limit": limit},
        )
        return [task for task in data if isinstance(task, dict)] if isinstance(data, list) else []

    def list_trash_tasks(self, *, start: int = 0, limit: int = 500) -> list[dict[str, Any]]:
        data = self.request("GET", "/project/all/trash/pagination", params={"start": start, "limit": limit})
        if isinstance(data, list):
            return [task for task in data if isinstance(task, dict)]
        if isinstance(data, dict) and isinstance(data.get("tasks"), list):
            return [task for task in data["tasks"] if isinstance(task, dict)]
        return []

    def list_habits(self) -> list[dict[str, Any]]:
        data = self.request("GET", "/habits")
        return [habit for habit in data if isinstance(habit, dict)] if isinstance(data, list) else []

    def list_habit_sections(self) -> list[dict[str, Any]]:
        data = self.request("GET", "/habitSections")
        return [section for section in data if isinstance(section, dict)] if isinstance(data, list) else []

    def batch_habits(
        self,
        *,
        add: list[dict[str, Any]] | None = None,
        update: list[dict[str, Any]] | None = None,
        delete: list[str] | None = None,
    ) -> Any:
        return self.request("POST", "/habits/batch", payload={"add": add or [], "update": update or [], "delete": delete or []})

    def query_habit_checkins(self, habit_ids: list[str], *, after_stamp: int = 0) -> Any:
        return self.request("POST", "/habitCheckins/query", payload={"habitIds": habit_ids, "afterStamp": after_stamp})

    def batch_habit_checkins(
        self,
        *,
        add: list[dict[str, Any]] | None = None,
        update: list[dict[str, Any]] | None = None,
        delete: list[str] | None = None,
    ) -> Any:
        return self.request("POST", "/habitCheckins/batch", payload={"add": add or [], "update": update or [], "delete": delete or []})

    def user_profile(self) -> dict[str, Any]:
        data = self.request("GET", "/user/profile")
        return data if isinstance(data, dict) else {}

    def user_preferences(self) -> dict[str, Any]:
        data = self.request("GET", "/user/preferences/settings", params={"includeWeb": "true"})
        return data if isinstance(data, dict) else {}

    def productivity_stats(self) -> dict[str, Any]:
        data = self.request("GET", "/statistics/general")
        return data if isinstance(data, dict) else {}

    def focus_heatmap(self, from_date: str, to_date: str) -> Any:
        return self.request("GET", f"/pomodoros/statistics/heatmap/{from_date}/{to_date}")

    def focus_distribution(self, from_date: str, to_date: str) -> Any:
        return self.request("GET", f"/pomodoros/statistics/dist/{from_date}/{to_date}")

    def focus_timeline(self, *, to_timestamp: int | None = None) -> Any:
        params = {"to": to_timestamp} if to_timestamp is not None else None
        return self.request("GET", "/pomodoros/timeline", params=params)
