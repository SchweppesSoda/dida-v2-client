from __future__ import annotations

from datetime import date, datetime, timedelta
import re
from typing import Any
from zoneinfo import ZoneInfo


def parse_dida_datetime(raw: str, *, assume_timezone: str = "UTC") -> datetime:
    normalized = raw.strip().replace("Z", "+00:00")
    normalized = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", normalized)
    value = datetime.fromisoformat(normalized)
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo(assume_timezone))
    return value


def local_date(raw: str, timezone_name: str) -> date:
    return parse_dida_datetime(raw).astimezone(ZoneInfo(timezone_name)).date()


def task_local_date(task: dict[str, Any], field: str, timezone_name: str) -> date | None:
    raw = task.get(field)
    if not raw:
        return None
    return local_date(str(raw), timezone_name)


def is_due_on(task: dict[str, Any], target: date, timezone_name: str) -> bool:
    return task_local_date(task, "dueDate", timezone_name) == target


def is_overdue(task: dict[str, Any], now: datetime, timezone_name: str) -> bool:
    raw = task.get("dueDate")
    if not raw or int(task.get("status") or 0) == 2:
        return False
    zone = ZoneInfo(timezone_name)
    local_now = now.astimezone(zone) if now.tzinfo else now.replace(tzinfo=zone)
    due = parse_dida_datetime(str(raw)).astimezone(zone)
    if task.get("allDay"):
        return due.date() < local_now.date()
    return due < local_now


def matches_relative_date(
    task: dict[str, Any],
    field: str,
    keyword: str,
    now: datetime,
    timezone_name: str,
) -> bool:
    zone = ZoneInfo(timezone_name)
    local_now = now.astimezone(zone) if now.tzinfo else now.replace(tzinfo=zone)
    if keyword == "overdue":
        return field == "dueDate" and is_overdue(task, local_now, timezone_name)
    value = task_local_date(task, field, timezone_name)
    if value is None:
        return False
    today = local_now.date()
    if keyword == "today":
        return value == today
    if keyword == "tomorrow":
        return value == today + timedelta(days=1)
    if keyword == "yesterday":
        return value == today - timedelta(days=1)
    week_start = today - timedelta(days=today.weekday())
    if keyword == "thisWeek":
        return week_start <= value < week_start + timedelta(days=7)
    if keyword == "nextWeek":
        next_start = week_start + timedelta(days=7)
        return next_start <= value < next_start + timedelta(days=7)
    raise ValueError(f"Unsupported relative date keyword: {keyword}")
