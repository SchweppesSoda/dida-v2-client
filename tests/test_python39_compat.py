import os
from pathlib import Path
import shutil
import subprocess

import pytest


def test_core_datetime_and_filter_features_run_under_supported_python39():
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is unavailable")
    assert uv is not None
    found = subprocess.run([uv, "python", "find", "3.9"], capture_output=True, text=True)
    if found.returncode != 0:
        pytest.skip("Python 3.9 is unavailable")
    python = found.stdout.strip()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")

    script = """
from datetime import date, datetime
from zoneinfo import ZoneInfo
import dida_v2_client
from dida_v2_client.datetime_utils import local_date
from dida_v2_client.filters import FilterContext, SavedFilterEvaluator

assert local_date('2026-07-10T15:59:59.000+0000', 'Asia/Shanghai') == date(2026, 7, 10)
assert local_date('2026-07-10T08:00:00.000+0800', 'Asia/Shanghai') == date(2026, 7, 10)
context = FilterContext(
    now=datetime(2026, 7, 10, 9, tzinfo=ZoneInfo('Asia/Shanghai')),
    timezone='Asia/Shanghai',
)
rule = {'and': [
    {'conditionName': 'priority', 'or': [5]},
    {'conditionName': 'dueDate', 'or': ['today']},
]}
task = {'priority': 5, 'dueDate': '2026-07-10T00:00:00+0000'}
assert SavedFilterEvaluator().matches(task, rule, context)
print(dida_v2_client.SyncSnapshot)
"""
    result = subprocess.run(
        [python, "-c", script],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
