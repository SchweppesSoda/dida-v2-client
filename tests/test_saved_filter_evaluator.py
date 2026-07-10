from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from dida_v2_client import FilterContext as ExportedFilterContext
from dida_v2_client import SavedFilterEvaluator as ExportedSavedFilterEvaluator
from dida_v2_client.filters import FilterContext, FilterRuleError, SavedFilterEvaluator, UnsupportedFilterCondition


def test_saved_filter_classes_are_exported():
    assert ExportedFilterContext is FilterContext
    assert ExportedSavedFilterEvaluator is SavedFilterEvaluator


def filter_rule(load_fixture):
    return load_fixture("full_sync_with_filters.json")["filters"][0]["rule"]


def test_saved_filter_matches_priority_five_due_today(load_fixture):
    evaluator = SavedFilterEvaluator()
    rule = evaluator.parse(filter_rule(load_fixture))
    task = load_fixture("full_sync_timezone_edges.json")["syncTaskBean"]["update"][0]
    context = FilterContext(
        now=datetime(2026, 7, 10, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
        timezone="Asia/Shanghai",
    )

    assert evaluator.matches(task, rule, context)


def test_saved_filter_rejects_missing_due_or_wrong_priority(load_fixture):
    evaluator = SavedFilterEvaluator()
    rule = evaluator.parse(filter_rule(load_fixture))
    tasks = load_fixture("full_sync_timezone_edges.json")["syncTaskBean"]["update"]
    context = FilterContext(
        now=datetime(2026, 7, 10, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
        timezone="Asia/Shanghai",
    )

    assert not evaluator.matches(tasks[1], rule, context)
    assert not evaluator.matches(tasks[2], rule, context)


def test_saved_filter_parser_rejects_malformed_or_unknown_rules():
    evaluator = SavedFilterEvaluator()
    context = FilterContext(
        now=datetime(2026, 7, 10, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
        timezone="Asia/Shanghai",
    )

    with pytest.raises(FilterRuleError, match="valid JSON"):
        evaluator.parse("{broken")

    with pytest.raises(UnsupportedFilterCondition, match="mystery"):
        evaluator.matches({}, {"conditionName": "mystery", "or": [1]}, context)


def test_saved_filter_explain_lists_boolean_conditions(load_fixture):
    evaluator = SavedFilterEvaluator()

    explanation = evaluator.explain(evaluator.parse(filter_rule(load_fixture)))

    assert explanation["operator"] == "and"
    assert explanation["conditions"] == ["priority in [5]", "dueDate in ['today']"]
