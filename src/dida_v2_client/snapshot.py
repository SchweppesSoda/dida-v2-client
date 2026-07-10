from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, cast


def freeze_snapshot_value(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: freeze_snapshot_value(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze_snapshot_value(item) for item in value)
    return value


def thaw_snapshot_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: thaw_snapshot_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_snapshot_value(item) for item in value]
    return value


@dataclass(frozen=True)
class SyncSnapshot:
    """Read-only view over one Dida/TickTick full-sync payload."""

    raw: Mapping[str, Any]
    tasks: tuple[Mapping[str, Any], ...]
    projects: tuple[Mapping[str, Any], ...]
    project_groups: tuple[Mapping[str, Any], ...]
    tags: tuple[Mapping[str, Any], ...]
    filters: tuple[Mapping[str, Any], ...]
    checkpoint: Any = None

    @classmethod
    def from_payload(cls, payload: Any) -> "SyncSnapshot":
        data = payload if isinstance(payload, dict) else {}
        raw_bean = data.get("syncTaskBean")
        bean: dict[str, Any] = raw_bean if isinstance(raw_bean, dict) else {}
        tasks = bean.get("update") if isinstance(bean.get("update"), list) else data.get("tasks", [])

        def rows(value: Any) -> tuple[Mapping[str, Any], ...]:
            if not isinstance(value, list):
                return ()
            return tuple(
                cast(Mapping[str, Any], freeze_snapshot_value(item))
                for item in value
                if isinstance(item, dict)
            )

        return cls(
            raw=cast(Mapping[str, Any], freeze_snapshot_value(data)),
            tasks=rows(tasks),
            projects=rows(data.get("projectProfiles")),
            project_groups=rows(data.get("projectGroups")),
            tags=rows(data.get("tags")),
            filters=rows(data.get("filters")),
            checkpoint=freeze_snapshot_value(data.get("checkPoint")),
        )
