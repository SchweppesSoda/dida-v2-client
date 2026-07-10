from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from threading import RLock
from typing import Any, Callable

from .config import DidaConfig
from .snapshot import SyncSnapshot, thaw_snapshot_value
from .version import USER_AGENT


class DidaV2Error(RuntimeError):
    pass


class DidaV2Client:
    def __init__(
        self,
        config: DidaConfig | None = None,
        session_token: str | None = None,
        *,
        clock: Callable[[], float] | None = None,
        snapshot_ttl_seconds: float = 30.0,
    ):
        self._snapshot_lock = RLock()
        self._snapshot_cache: SyncSnapshot | None = None
        self._snapshot_cached_at: float | None = None
        self._snapshot_identity: tuple[DidaConfig, str | None] | None = None
        self._snapshot_generation = 0
        self._snapshot_fetch_sequence = 0
        self._config = config or DidaConfig.default()
        self._session_token = session_token
        self._clock = clock or time.monotonic
        self._snapshot_ttl_seconds = 30.0
        self.snapshot_ttl_seconds = snapshot_ttl_seconds

    def _current_snapshot_identity(self) -> tuple[DidaConfig, str | None]:
        return (self._config, self._session_token)

    def _invalidate_snapshot_locked(self) -> None:
        self._snapshot_cache = None
        self._snapshot_cached_at = None
        self._snapshot_identity = None
        self._snapshot_generation += 1

    def _invalidate_snapshot(self) -> None:
        with self._snapshot_lock:
            self._invalidate_snapshot_locked()

    @property
    def config(self) -> DidaConfig:
        with self._snapshot_lock:
            return self._config

    @config.setter
    def config(self, value: DidaConfig) -> None:
        raise AttributeError("config is read-only; use set_identity(config, session_token)")

    @property
    def session_token(self) -> str | None:
        with self._snapshot_lock:
            return self._session_token

    @session_token.setter
    def session_token(self, value: str | None) -> None:
        raise AttributeError("session_token is read-only; use set_identity(config, session_token)")

    def set_identity(self, config: DidaConfig, session_token: str | None) -> None:
        with self._snapshot_lock:
            if (config, session_token) != self._current_snapshot_identity():
                self._config = config
                self._session_token = session_token
                self._invalidate_snapshot_locked()

    @property
    def snapshot_ttl_seconds(self) -> float:
        with self._snapshot_lock:
            return self._snapshot_ttl_seconds

    @snapshot_ttl_seconds.setter
    def snapshot_ttl_seconds(self, value: float) -> None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("snapshot_ttl_seconds must be between 0 and 30")
        ttl = float(value)
        if not math.isfinite(ttl) or not 0 <= ttl <= 30:
            raise ValueError("snapshot_ttl_seconds must be between 0 and 30")
        with self._snapshot_lock:
            if ttl != self._snapshot_ttl_seconds:
                self._snapshot_ttl_seconds = ttl
                self._invalidate_snapshot_locked()

    def _headers(self, config: DidaConfig, session_token: str | None) -> dict[str, str]:
        if not session_token:
            raise DidaV2Error("Missing v2 session token. Use headless login or fallback DIDA_SESSION_TOKEN/TICKTICK_SESSION_TOKEN.")
        return {
            "Cookie": f"{config.cookie_name}={session_token}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            "Origin": config.web_origin,
            "Referer": f"{config.web_origin}/",
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

    def request(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        payload: Any = None,
        _identity: tuple[DidaConfig, str | None] | None = None,
    ) -> Any:
        method_upper = method.upper()
        with self._snapshot_lock:
            config, session_token = _identity or self._current_snapshot_identity()
            if method_upper != "GET":
                self._invalidate_snapshot_locked()
        url = f"{config.api_v2_base.rstrip('/')}/{endpoint.lstrip('/')}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers=self._headers(config, session_token),
            method=method_upper,
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8", "replace")
                return {} if not raw else json.loads(raw)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            raise DidaV2Error(f"HTTP {exc.code} from {method_upper} {endpoint}: {body[:300]}") from exc
        finally:
            if method_upper != "GET":
                self._invalidate_snapshot()

    def user_status(self) -> Any:
        return self.request("GET", "/user/status")

    def full_sync(self, *, _identity: tuple[DidaConfig, str | None] | None = None) -> Any:
        return self.request("GET", "/batch/check/0", _identity=_identity)

    def _get_snapshot_with_identity(
        self,
        *,
        refresh: bool = False,
    ) -> tuple[SyncSnapshot, tuple[DidaConfig, str | None]]:
        with self._snapshot_lock:
            now = self._clock()
            identity = self._current_snapshot_identity()
            expired = (
                self._snapshot_cached_at is not None
                and now - self._snapshot_cached_at >= self.snapshot_ttl_seconds
            )
            if (
                not refresh
                and not expired
                and self._snapshot_cache is not None
                and self._snapshot_identity == identity
            ):
                return self._snapshot_cache, identity
            generation = self._snapshot_generation
            self._snapshot_fetch_sequence += 1
            fetch_sequence = self._snapshot_fetch_sequence

        snapshot = SyncSnapshot.from_payload(self.full_sync(_identity=identity))

        with self._snapshot_lock:
            if (
                generation == self._snapshot_generation
                and fetch_sequence == self._snapshot_fetch_sequence
                and identity == self._current_snapshot_identity()
            ):
                self._snapshot_cache = snapshot
                self._snapshot_cached_at = self._clock()
                self._snapshot_identity = identity
        return snapshot, identity

    def get_snapshot(self, *, refresh: bool = False) -> SyncSnapshot:
        snapshot, _identity = self._get_snapshot_with_identity(refresh=refresh)
        return snapshot

    def list_filters(self, *, snapshot: SyncSnapshot | None = None) -> list[dict[str, Any]]:
        current = snapshot or self.get_snapshot()
        return [thaw_snapshot_value(item) for item in current.filters]

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
        return [thaw_snapshot_value(task) for task in current.tasks]

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
        if not isinstance(response, dict) or not response:
            raise DidaV2Error("V2 batch returned an unrecognized response shape")
        fields = set(response)
        success_fields = {"id2etag", "id2error"}
        error_fields = {"errorId", "errorCode", "error"}
        if fields <= success_fields:
            if not all(isinstance(response[field], dict) for field in fields):
                raise DidaV2Error("V2 batch returned an unrecognized response shape")
            errors = self.batch_errors(response)
            if errors:
                raise DidaV2Error(f"V2 batch response contains errors: {json.dumps(errors, ensure_ascii=False)}")
            return response
        if fields <= error_fields and all(isinstance(response[field], str) and response[field] for field in fields):
            errors = {field: response[field] for field in fields}
            raise DidaV2Error(f"V2 batch response contains errors: {json.dumps(errors, ensure_ascii=False)}")
        raise DidaV2Error("V2 batch returned an unrecognized response shape")

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
        return [thaw_snapshot_value(tag) for tag in current.tags]

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
        return [thaw_snapshot_value(folder) for folder in current.project_groups]

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
        return [thaw_snapshot_value(project) for project in current.projects]

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

    def user_preferences(
        self,
        *,
        _identity: tuple[DidaConfig, str | None] | None = None,
    ) -> dict[str, Any]:
        data = self.request(
            "GET",
            "/user/preferences/settings",
            params={"includeWeb": "true"},
            _identity=_identity,
        )
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
