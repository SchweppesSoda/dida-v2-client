from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True)
class SyncSnapshot:
    """Read-only view over one Dida/TickTick full-sync payload."""

    raw: Mapping[str, Any]
    tasks: tuple[dict[str, Any], ...]
    projects: tuple[dict[str, Any], ...]
    project_groups: tuple[dict[str, Any], ...]
    tags: tuple[dict[str, Any], ...]
    filters: tuple[dict[str, Any], ...]
    checkpoint: Any = None

    @classmethod
    def from_payload(cls, payload: Any) -> "SyncSnapshot":
        data = payload if isinstance(payload, dict) else {}
        raw_bean = data.get("syncTaskBean")
        bean: dict[str, Any] = raw_bean if isinstance(raw_bean, dict) else {}
        tasks = bean.get("update") if isinstance(bean.get("update"), list) else data.get("tasks", [])

        def rows(value: Any) -> tuple[dict[str, Any], ...]:
            if not isinstance(value, list):
                return ()
            return tuple(dict(item) for item in value if isinstance(item, dict))

        return cls(
            raw=MappingProxyType(dict(data)),
            tasks=rows(tasks),
            projects=rows(data.get("projectProfiles")),
            project_groups=rows(data.get("projectGroups")),
            tags=rows(data.get("tags")),
            filters=rows(data.get("filters")),
            checkpoint=data.get("checkPoint"),
        )
