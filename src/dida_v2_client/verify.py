from __future__ import annotations

from typing import Any

from .transport import DidaV2Error


class VerificationError(DidaV2Error):
    """Raised when a v2 write succeeds at HTTP level but read-back does not match."""


class DidaV2Verifier:
    """Read-back verification helpers for risky v2 writes.

    Inspired by tick-mcp's `verified.py`, but kept as a small dict-based layer
    over this Dida365-first client. Every method performs one write and then
    re-reads the affected entity from v2 sync data before reporting success.
    """

    def __init__(self, client: Any):
        self.client = client

    def verified_set_task_parent(self, task_id: str, *, project_id: str, parent_id: str) -> dict[str, Any]:
        result = self.client.set_task_parent(task_id, project_id=project_id, parent_id=parent_id)
        self._ensure_batch_ok(result)
        child = self._get_task(task_id, project_id=project_id)
        parent = self._get_task(parent_id, project_id=project_id)
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

    def verified_unset_task_parent(self, task_id: str, *, project_id: str, old_parent_id: str) -> dict[str, Any]:
        result = self.client.unset_task_parent(task_id, project_id=project_id, old_parent_id=old_parent_id)
        self._ensure_batch_ok(result)
        child = self._get_task(task_id, project_id=project_id)
        old_parent = self._get_task(old_parent_id, project_id=project_id)
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

    def verified_move_task(self, task_id: str, *, from_project_id: str, to_project_id: str) -> dict[str, Any]:
        result = self.client.move_task(task_id, from_project_id=from_project_id, to_project_id=to_project_id)
        self._ensure_batch_ok(result)
        task = self._find_task(task_id, project_id=to_project_id)
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

    def verified_set_project_folder(self, project_id: str, folder_id: str | None) -> dict[str, Any]:
        result = self.client.set_project_folder(project_id, folder_id)
        self._ensure_batch_ok(result)
        project = self._find_project(project_id)
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
        if callable(ensure):
            ensure(response)
            return
        if isinstance(response, dict) and response.get("id2error"):
            raise VerificationError(f"V2 batch response contains errors: {response['id2error']}")

    def _get_task(self, task_id: str, *, project_id: str | None = None) -> dict[str, Any]:
        task = self._find_task(task_id, project_id=project_id)
        if task is None:
            suffix = f" in project {project_id}" if project_id else ""
            raise VerificationError(f"Task {task_id} not found{suffix} during verification")
        return task

    def _find_task(self, task_id: str, *, project_id: str | None = None) -> dict[str, Any] | None:
        get_task = getattr(self.client, "get_task", None)
        if callable(get_task):
            try:
                return dict(get_task(task_id, project_id=project_id))
            except Exception:
                pass
        for task in self.client.list_tasks():
            if task.get("id") == task_id and (project_id is None or task.get("projectId") == project_id):
                return dict(task)
        return None

    def _find_project(self, project_id: str) -> dict[str, Any] | None:
        for project in self.client.list_projects():
            if project.get("id") == project_id:
                return dict(project)
        return None
