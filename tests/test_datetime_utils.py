from datetime import date, datetime
from zoneinfo import ZoneInfo

from dida_v2_client.datetime_utils import is_due_on, is_overdue, local_date, matches_relative_date


def test_cn_all_day_due_date_is_july_10():
    raw = "2026-07-10T15:59:59.000+0000"

    assert local_date(raw, "Asia/Shanghai") == date(2026, 7, 10)


def test_due_and_overdue_use_local_timezone():
    task = {"dueDate": "2026-07-09T16:00:00.000+0000"}
    now = datetime(2026, 7, 11, 9, tzinfo=ZoneInfo("Asia/Shanghai"))

    assert is_due_on(task, date(2026, 7, 10), "Asia/Shanghai")
    assert is_overdue(task, now, "Asia/Shanghai")


def test_relative_dates_cover_today_tomorrow_and_week_ranges():
    now = datetime(2026, 7, 10, 9, tzinfo=ZoneInfo("Asia/Shanghai"))
    today = {"dueDate": "2026-07-10T06:00:00+0000"}
    tomorrow = {"dueDate": "2026-07-11T06:00:00+0000"}
    next_week = {"dueDate": "2026-07-13T06:00:00+0000"}

    assert matches_relative_date(today, "dueDate", "today", now, "Asia/Shanghai")
    assert matches_relative_date(tomorrow, "dueDate", "tomorrow", now, "Asia/Shanghai")
    assert matches_relative_date(today, "dueDate", "thisWeek", now, "Asia/Shanghai")
    assert matches_relative_date(next_week, "dueDate", "nextWeek", now, "Asia/Shanghai")
