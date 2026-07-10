from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .datetime_utils import matches_relative_date


class FilterRuleError(ValueError):
    """Raised when a saved-filter rule cannot be parsed or evaluated safely."""


class UnsupportedFilterCondition(FilterRuleError):
    """Raised when a saved filter contains a condition we do not implement."""


@dataclass(frozen=True)
class FilterContext:
    now: datetime
    timezone: str
    project_by_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    folder_by_id: dict[str, dict[str, Any]] = field(default_factory=dict)


class SavedFilterEvaluator:
    _SUPPORTED_CONDITIONS = {"priority", "dueDate", "startDate"}
    _SUPPORTED_PRIORITIES = {0, 1, 3, 5}
    _SUPPORTED_RELATIVE_DATES = {"overdue", "today", "tomorrow", "yesterday", "thisWeek", "nextWeek"}

    def parse(self, raw_rule: str | dict[str, Any]) -> dict[str, Any]:
        if isinstance(raw_rule, str):
            try:
                parsed = json.loads(raw_rule)
            except json.JSONDecodeError as exc:
                raise FilterRuleError("Saved filter rule is not valid JSON") from exc
        elif isinstance(raw_rule, dict):
            parsed = dict(raw_rule)
        else:
            raise FilterRuleError("Saved filter rule must be a JSON string or object")
        if not isinstance(parsed, dict):
            raise FilterRuleError("Saved filter rule must decode to an object")
        return parsed

    def matches(self, task: dict[str, Any], rule: dict[str, Any], context: FilterContext) -> bool:
        self._validate_node(rule)
        return self._matches_node(task, rule, context)

    def filter_tasks(
        self,
        tasks: list[dict[str, Any]],
        rule: dict[str, Any],
        context: FilterContext,
    ) -> list[dict[str, Any]]:
        self._validate_node(rule)
        return [dict(task) for task in tasks if self._matches_node(task, rule, context)]

    def explain(self, rule: dict[str, Any]) -> dict[str, Any]:
        self._validate_node(rule)
        if isinstance(rule.get("and"), list):
            return {
                "operator": "and",
                "conditions": [self._explain_node(node) for node in rule["and"]],
            }
        if isinstance(rule.get("or"), list) and not rule.get("conditionName"):
            return {
                "operator": "or",
                "conditions": [self._explain_node(node) for node in rule["or"]],
            }
        return {"operator": "condition", "conditions": [self._explain_node(rule)]}

    def _validate_node(self, node: Any) -> None:
        if not isinstance(node, dict):
            raise FilterRuleError("Saved filter condition must be an object")
        condition = node.get("conditionName")
        has_condition = "conditionName" in node
        if "and" in node and ("or" in node or has_condition):
            raise FilterRuleError("Saved filter node has mixed boolean/leaf shapes")
        if "and" in node or ("or" in node and not has_condition):
            allowed_keys = {"and", "or", "type", "version"}
        elif has_condition:
            allowed_keys = {"conditionName", "or", "conditionType"}
        else:
            allowed_keys = {"and", "or", "conditionName"}
        unexpected = set(node) - allowed_keys
        if unexpected:
            key = sorted(unexpected)[0]
            raise FilterRuleError(f"Saved filter node has unexpected key: {key}")
        if "and" in node:
            if not isinstance(node["and"], list):
                raise FilterRuleError("Saved filter and-group must be a list")
            if not node["and"]:
                raise FilterRuleError("Saved filter boolean group must not be empty")
            for child in node["and"]:
                self._validate_node(child)
            return
        if "or" in node and not has_condition:
            if not isinstance(node["or"], list):
                raise FilterRuleError("Saved filter or-group must be a list")
            if not node["or"]:
                raise FilterRuleError("Saved filter boolean group must not be empty")
            for child in node["or"]:
                self._validate_node(child)
            return
        values = node.get("or")
        if not condition or not isinstance(values, list):
            raise FilterRuleError("Saved filter leaf needs conditionName and an or-value list")
        if not values:
            raise FilterRuleError("Saved filter leaf value list must not be empty")
        if str(condition) not in self._SUPPORTED_CONDITIONS:
            raise UnsupportedFilterCondition(f"Unsupported saved filter condition: {condition}")
        if condition == "priority":
            invalid = [value for value in values if type(value) is not int or value not in self._SUPPORTED_PRIORITIES]
            if invalid:
                raise FilterRuleError(f"Saved filter value is not a supported priority: {invalid[0]!r}")
        if condition in {"dueDate", "startDate"}:
            invalid = [value for value in values if not isinstance(value, str) or value not in self._SUPPORTED_RELATIVE_DATES]
            if invalid:
                raise FilterRuleError(f"Unsupported relative date keyword: {invalid[0]}")

    def _matches_node(self, task: dict[str, Any], node: Any, context: FilterContext) -> bool:
        if not isinstance(node, dict):
            raise FilterRuleError("Saved filter condition must be an object")
        if isinstance(node.get("and"), list):
            return all(self._matches_node(task, child, context) for child in node["and"])
        if isinstance(node.get("or"), list) and not node.get("conditionName"):
            return any(self._matches_node(task, child, context) for child in node["or"])
        condition = node.get("conditionName")
        values = node.get("or")
        if not condition or not isinstance(values, list):
            raise FilterRuleError("Saved filter leaf needs conditionName and an or-value list")
        return any(self._matches_condition(task, str(condition), value, context) for value in values)

    def _matches_condition(
        self,
        task: dict[str, Any],
        condition: str,
        value: Any,
        context: FilterContext,
    ) -> bool:
        if condition == "priority":
            task_priority = task.get("priority", 0)
            return type(task_priority) is int and task_priority == value
        if condition in {"dueDate", "startDate"} and isinstance(value, str):
            return matches_relative_date(task, condition, value, context.now, context.timezone)
        raise UnsupportedFilterCondition(f"Unsupported saved filter condition: {condition}")

    def _explain_node(self, node: Any) -> str:
        if not isinstance(node, dict):
            raise FilterRuleError("Saved filter condition must be an object")
        condition = node.get("conditionName")
        values = node.get("or")
        if condition and isinstance(values, list):
            return f"{condition} in {values!r}"
        if isinstance(node.get("and"), list):
            return "AND(" + ", ".join(self._explain_node(child) for child in node["and"]) + ")"
        if isinstance(node.get("or"), list):
            return "OR(" + ", ".join(self._explain_node(child) for child in node["or"]) + ")"
        raise FilterRuleError("Saved filter node cannot be explained")
