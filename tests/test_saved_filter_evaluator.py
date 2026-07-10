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


def test_saved_filter_validates_unsupported_and_branches_before_short_circuiting():
    evaluator = SavedFilterEvaluator()
    context = FilterContext(
        now=datetime(2026, 7, 10, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
        timezone="Asia/Shanghai",
    )
    rule = {
        "and": [
            {"conditionName": "priority", "or": [5]},
            {"conditionName": "mystery", "or": [1]},
        ]
    }

    with pytest.raises(UnsupportedFilterCondition, match="mystery"):
        evaluator.matches({"priority": 0}, rule, context)


def test_saved_filter_validates_unsupported_or_branches_before_short_circuiting():
    evaluator = SavedFilterEvaluator()
    context = FilterContext(
        now=datetime(2026, 7, 10, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
        timezone="Asia/Shanghai",
    )
    rule = {
        "or": [
            {"conditionName": "priority", "or": [5]},
            {"conditionName": "mystery", "or": [1]},
        ]
    }

    with pytest.raises(UnsupportedFilterCondition, match="mystery"):
        evaluator.matches({"priority": 5}, rule, context)


def test_saved_filter_rejects_empty_boolean_groups():
    evaluator = SavedFilterEvaluator()
    context = FilterContext(
        now=datetime(2026, 7, 10, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
        timezone="Asia/Shanghai",
    )

    for operator in ("and", "or"):
        with pytest.raises(FilterRuleError, match="must not be empty"):
            evaluator.matches({}, {operator: []}, context)


def test_saved_filter_rejects_invalid_priority_values():
    evaluator = SavedFilterEvaluator()
    context = FilterContext(
        now=datetime(2026, 7, 10, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
        timezone="Asia/Shanghai",
    )

    with pytest.raises(FilterRuleError, match="priority"):
        evaluator.matches({}, {"conditionName": "priority", "or": ["high"]}, context)


@pytest.mark.parametrize("value", [5.9, True, 2, "5"])
def test_saved_filter_rejects_non_domain_priority_values(value):
    evaluator = SavedFilterEvaluator()
    context = FilterContext(
        now=datetime(2026, 7, 10, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
        timezone="Asia/Shanghai",
    )

    with pytest.raises(FilterRuleError, match="supported priority"):
        evaluator.matches({"priority": 5}, {"conditionName": "priority", "or": [value]}, context)


def test_saved_filter_rejects_unknown_relative_date_keywords():
    evaluator = SavedFilterEvaluator()
    context = FilterContext(
        now=datetime(2026, 7, 10, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
        timezone="Asia/Shanghai",
    )

    with pytest.raises(FilterRuleError, match="relative date"):
        evaluator.matches(
            {"dueDate": "2026-07-10T00:00:00+0000"},
            {"conditionName": "dueDate", "or": ["someday"]},
            context,
        )


def test_saved_filter_rejects_empty_leaf_values():
    evaluator = SavedFilterEvaluator()
    context = FilterContext(
        now=datetime(2026, 7, 10, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
        timezone="Asia/Shanghai",
    )

    with pytest.raises(FilterRuleError, match="value list must not be empty"):
        evaluator.matches({}, {"conditionName": "priority", "or": []}, context)


def test_saved_filter_validates_rule_even_when_task_collection_is_empty():
    evaluator = SavedFilterEvaluator()
    context = FilterContext(
        now=datetime(2026, 7, 10, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
        timezone="Asia/Shanghai",
    )

    with pytest.raises(UnsupportedFilterCondition, match="unsupportedField"):
        evaluator.filter_tasks([], {"conditionName": "unsupportedField", "or": ["x"]}, context)


def test_saved_filter_explain_validates_complete_rule():
    evaluator = SavedFilterEvaluator()

    with pytest.raises(UnsupportedFilterCondition, match="unsupportedField"):
        evaluator.explain({"conditionName": "unsupportedField", "or": ["x"]})


@pytest.mark.parametrize(
    "mixed",
    [
        {
            "and": [{"conditionName": "priority", "or": [5]}],
            "or": [{"conditionName": "unsupportedField", "or": ["x"]}],
        },
        {"and": [{"conditionName": "priority", "or": [5]}], "conditionName": ""},
        {"or": [{"conditionName": "priority", "or": [5]}], "conditionName": None},
    ],
)
def test_saved_filter_rejects_mixed_boolean_shapes(mixed):
    evaluator = SavedFilterEvaluator()
    context = FilterContext(
        now=datetime(2026, 7, 10, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
        timezone="Asia/Shanghai",
    )

    with pytest.raises(FilterRuleError):
        evaluator.matches({"priority": 5}, mixed, context)


@pytest.mark.parametrize(
    "rule",
    [
        {"and": [{"conditionName": "priority", "or": [5]}], "unexpected": False},
        {"or": [{"conditionName": "priority", "or": [5]}], "unexpected": None},
        {"conditionName": "priority", "or": [5], "unexpected": {"and": []}},
    ],
)
def test_saved_filter_rejects_unknown_node_keys(rule):
    evaluator = SavedFilterEvaluator()
    context = FilterContext(
        now=datetime(2026, 7, 10, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
        timezone="Asia/Shanghai",
    )

    with pytest.raises(FilterRuleError, match="unexpected key"):
        evaluator.matches({"priority": 5}, rule, context)


def test_saved_filter_explain_lists_boolean_conditions(load_fixture):
    evaluator = SavedFilterEvaluator()

    explanation = evaluator.explain(evaluator.parse(filter_rule(load_fixture)))

    assert explanation["operator"] == "and"
    assert explanation["conditions"] == ["priority in [5]", "dueDate in ['today']"]
