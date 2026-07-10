from __future__ import annotations

from functools import wraps
from typing import Any

from .datetime_utils import parse_dida_datetime
from .snapshot import SyncSnapshot, thaw_snapshot_value
from .transport import DidaV2Error


class VerificationError(DidaV2Error):
    """Raised when a v2 write succeeds at HTTP level but read-back does not match."""


def _identity_bound(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        identity_operation: Any = getattr(self.client, "_identity_operation", None)
        if not callable(identity_operation):
            raise VerificationError("Verified actions require an identity-bound client")
        context: Any = identity_operation()
        with context:
            return method(self, *args, **kwargs)

    return wrapped


class DidaV2Verifier:
    """Read-back verification helpers for risky v2 writes.

    Inspired by tick-mcp's `verified.py`, but kept as a small dict-based layer
    over this Dida365-first client. Every method performs one write and then
    re-reads the affected entity from v2 sync data before reporting success.
    """

    _TASK_UPDATE_FIELDS = {
        "title",
        "content",
        "desc",
        "priority",
        "status",
        "dueDate",
        "startDate",
        "timeZone",
        "tags",
        "columnId",
        "allDay",
        "items",
    }
    _TASK_STRING_FIELDS = {"title", "content", "desc", "dueDate", "startDate", "timeZone", "columnId"}
    _TASK_PRIORITIES = {0, 1, 3, 5}
    _TASK_STATUSES = {-1, 0, 2}

    def __init__(self, client: Any):
        self.client = client

    @_identity_bound
    def verified_update_task(
        self,
        task_id: str,
        *,
        project_id: str,
        changes: dict[str, Any],
    ) -> dict[str, Any]:
        normalized = self.validate_task_changes(changes)
        before = self._get_task(self._readback_snapshot(), task_id, project_id=project_id)
        payload = {**before, **normalized, "id": task_id, "projectId": project_id}
        result = self.client.update_task(payload)
        self._ensure_batch_ok(result)
        task = self._get_task(self._readback_snapshot(), task_id, project_id=project_id)
        mismatches = {
            field: {"expected": expected, "actual": task.get(field)}
            for field, expected in normalized.items()
            if not self._task_field_matches(field, expected, task.get(field))
        }
        if mismatches:
            fields = ", ".join(sorted(mismatches))
            raise VerificationError(f"Task update did not verify after v2 write: {fields}")
        return {
            "verified": True,
            "result": result,
            "task": task,
            "verification": {
                "task_id": task_id,
                "project_id": project_id,
                "checked_fields": sorted(normalized),
            },
        }

    def validate_task_changes(self, changes: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(changes, dict) or not changes:
            raise VerificationError("Verified task update requires at least one field")
        unsupported = set(changes) - self._TASK_UPDATE_FIELDS
        if unsupported:
            field = sorted(unsupported)[0]
            raise VerificationError(f"Task field is not supported for verified update: {field}")
        normalized = dict(changes)
        for field in self._TASK_STRING_FIELDS & set(normalized):
            if not isinstance(normalized[field], str):
                raise VerificationError(f"Verified task field must be a string: {field}")
        if "title" in normalized and not normalized["title"].strip():
            raise VerificationError("Verified task title must not be empty")
        for field in ("dueDate", "startDate"):
            if field in normalized:
                try:
                    parse_dida_datetime(normalized[field])
                except (TypeError, ValueError):
                    raise VerificationError(f"Verified task datetime is invalid: {field}") from None
        if "priority" in normalized and (
            type(normalized["priority"]) is not int or normalized["priority"] not in self._TASK_PRIORITIES
        ):
            raise VerificationError("Verified task priority is invalid")
        if "status" in normalized and (
            type(normalized["status"]) is not int or normalized["status"] not in self._TASK_STATUSES
        ):
            raise VerificationError("Verified task status is invalid")
        if "allDay" in normalized and type(normalized["allDay"]) is not bool:
            raise VerificationError("Verified task allDay must be boolean")
        if "tags" in normalized and (
            not isinstance(normalized["tags"], list)
            or any(not isinstance(tag, str) or not tag for tag in normalized["tags"])
        ):
            raise VerificationError("Verified task tags must be a list of non-empty strings")
        if "items" in normalized and (
            not isinstance(normalized["items"], list)
            or any(not isinstance(item, dict) for item in normalized["items"])
        ):
            raise VerificationError("Verified task items must be a list of objects")
        return normalized

    @staticmethod
    def _task_field_matches(field: str, expected: Any, actual: Any) -> bool:
        if field == "tags" and isinstance(expected, list) and isinstance(actual, list):
            return sorted(expected) == sorted(actual)
        if field in {"dueDate", "startDate"} and isinstance(expected, str) and isinstance(actual, str):
            try:
                return parse_dida_datetime(expected) == parse_dida_datetime(actual)
            except (TypeError, ValueError):
                return False
        return actual == expected

    @_identity_bound
    def verified_set_task_parent(self, task_id: str, *, project_id: str, parent_id: str) -> dict[str, Any]:
        result = self.client.set_task_parent(task_id, project_id=project_id, parent_id=parent_id)
        self._ensure_batch_ok(result)
        snapshot = self._readback_snapshot()
        child = self._get_task(snapshot, task_id, project_id=project_id)
        parent = self._get_task(snapshot, parent_id, project_id=project_id)
        parent_child_ids = parent.get("childIds") or []
        verified = child.get("parentId") == parent_id and task_id in parent_child_ids
        output = {
            "verified": verified,
            "result": result,
            "child": child,
            "parent": parent,
            "verification": {
                "child_parent_id": child.get("parentId"),
                "expected_parent_id": parent_id,
                "parent_child_ids": parent_child_ids,
            },
        }
        if not verified:
            raise VerificationError("Task parent relationship did not verify after v2 write")
        return output

    @_identity_bound
    def verified_unset_task_parent(self, task_id: str, *, project_id: str, old_parent_id: str) -> dict[str, Any]:
        result = self.client.unset_task_parent(task_id, project_id=project_id, old_parent_id=old_parent_id)
        self._ensure_batch_ok(result)
        snapshot = self._readback_snapshot()
        child = self._get_task(snapshot, task_id, project_id=project_id)
        old_parent = self._get_task(snapshot, old_parent_id, project_id=project_id)
        old_parent_child_ids = old_parent.get("childIds") or []
        verified = child.get("parentId") in (None, "") and task_id not in old_parent_child_ids
        output = {
            "verified": verified,
            "result": result,
            "child": child,
            "old_parent": old_parent,
            "verification": {
                "child_parent_id": child.get("parentId"),
                "old_parent_id": old_parent_id,
                "old_parent_child_ids": old_parent_child_ids,
            },
        }
        if not verified:
            raise VerificationError("Task parent relationship did not clear after v2 write")
        return output

    @_identity_bound
    def verified_move_task(self, task_id: str, *, from_project_id: str, to_project_id: str) -> dict[str, Any]:
        result = self.client.move_task(task_id, from_project_id=from_project_id, to_project_id=to_project_id)
        self._ensure_batch_ok(result)
        snapshot = self._readback_snapshot()
        task = self._find_task(snapshot, task_id, project_id=to_project_id)
        if task is None or task.get("projectId") != to_project_id:
            raise VerificationError(f"Task {task_id} not found in destination project {to_project_id} after v2 move")
        return {
            "verified": True,
            "result": result,
            "task": task,
            "verification": {
                "task_id": task_id,
                "source_project_id": from_project_id,
                "destination_project_id": to_project_id,
                "actual_project_id": task.get("projectId"),
            },
        }

    @_identity_bound
    def verified_move_tasks(self, moves: list[dict[str, Any]]) -> dict[str, Any]:
        verifications = [
            self.verified_move_task(
                move["taskId"],
                from_project_id=move["fromProjectId"],
                to_project_id=move["toProjectId"],
            )
            for move in moves
        ]
        return {"verified": True, "moves": verifications}

    @_identity_bound
    def verified_set_project_folder(self, project_id: str, folder_id: str | None) -> dict[str, Any]:
        result = self.client.set_project_folder(project_id, folder_id)
        self._ensure_batch_ok(result)
        snapshot = self._readback_snapshot()
        project = self._find_project(snapshot, project_id)
        if project is None or project.get("groupId") != folder_id:
            raise VerificationError(f"Project {project_id} folder assignment did not verify after v2 write")
        return {
            "verified": True,
            "result": result,
            "project": project,
            "verification": {
                "project_id": project_id,
                "expected_group_id": folder_id,
                "actual_group_id": project.get("groupId"),
            },
        }

    def _ensure_batch_ok(self, response: Any) -> None:
        ensure = getattr(self.client, "ensure_batch_ok", None)
        if not callable(ensure):
            raise VerificationError("Verified actions require strict batch validation")
        ensure(response)

    def _readback_snapshot(self) -> SyncSnapshot:
        get_snapshot = getattr(self.client, "_get_snapshot_with_identity", None)
        if not callable(get_snapshot):
            raise VerificationError("Verified actions require identity-bound SyncSnapshot read-back")
        operation: Any = get_snapshot(refresh=True)
        if not isinstance(operation, tuple) or len(operation) != 2:
            raise VerificationError("Verified actions require identity-bound SyncSnapshot read-back")
        snapshot, _identity = operation
        if not isinstance(snapshot, SyncSnapshot):
            raise VerificationError("Verified actions require identity-bound SyncSnapshot read-back")
        return snapshot

    def _get_task(
        self,
        snapshot: SyncSnapshot,
        task_id: str,
        *,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        task = self._find_task(snapshot, task_id, project_id=project_id)
        if task is None:
            suffix = f" in project {project_id}" if project_id else ""
            raise VerificationError(f"Task {task_id} not found{suffix} during verification")
        return task

    def _find_task(
        self,
        snapshot: SyncSnapshot,
        task_id: str,
        *,
        project_id: str | None = None,
    ) -> dict[str, Any] | None:
        for raw_task in snapshot.tasks:
            task = thaw_snapshot_value(raw_task)
            if task.get("id") == task_id and (project_id is None or task.get("projectId") == project_id):
                return task
        return None

    def _find_project(self, snapshot: SyncSnapshot, project_id: str) -> dict[str, Any] | None:
        for raw_project in snapshot.projects:
            project = thaw_snapshot_value(raw_project)
            if project.get("id") == project_id:
                return project
        return None
