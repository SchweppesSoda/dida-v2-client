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


@dataclass(frozen=True, slots=True)
class FilterContext:
    now: datetime
    timezone: str
    project_by_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    folder_by_id: dict[str, dict[str, Any]] = field(default_factory=dict)


class SavedFilterEvaluator:
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
        return self._matches_node(task, rule, context)

    def filter_tasks(
        self,
        tasks: list[dict[str, Any]],
        rule: dict[str, Any],
        context: FilterContext,
    ) -> list[dict[str, Any]]:
        return [dict(task) for task in tasks if self.matches(task, rule, context)]

    def explain(self, rule: dict[str, Any]) -> dict[str, Any]:
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
            return int(task.get("priority") or 0) == int(value)
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
