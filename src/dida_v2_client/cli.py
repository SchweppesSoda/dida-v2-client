from __future__ import annotations

import argparse
import json
import sys
from typing import Any
from zoneinfo import ZoneInfoNotFoundError

from .auth import DidaAuthError, KeyringSessionStore, SessionStore, direct_signon_login, resolve_session_token
from .config import DidaConfig
from .filters import SavedFilterEvaluator
from .query import DidaV2QueryService
from .transport import DidaV2Client, DidaV2Error, DidaV2HTTPError
from .verify import DidaV2Verifier


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dida-v2")
    parser.add_argument("--profile", choices=DidaConfig.PROFILE_ALIASES, default="dida")
    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="Skip direct/Selenium login; use secure-store or profile-specific session env only",
    )
    sub = parser.add_subparsers(dest="resource", required=True)

    sub.add_parser("status")

    auth = sub.add_parser("auth")
    auth_sub = auth.add_subparsers(dest="action", required=True)
    for action in ("login", "status", "refresh", "logout"):
        auth_sub.add_parser(action)

    saved_filters = sub.add_parser("filters")
    saved_filter_sub = saved_filters.add_subparsers(dest="action", required=True)
    saved_filter_sub.add_parser("list")
    for action in ("get", "explain", "run"):
        command = saved_filter_sub.add_parser(action)
        selector = command.add_mutually_exclusive_group(required=True)
        selector.add_argument("--id", dest="filter_id")
        selector.add_argument("--name", dest="filter_name")
        if action == "run":
            command.add_argument("--timezone")
            command.add_argument("--now")

    tags = sub.add_parser("tags")
    tag_sub = tags.add_subparsers(dest="action", required=True)
    tag_sub.add_parser("list")
    create = tag_sub.add_parser("create")
    create.add_argument("name")
    create.add_argument("--color")
    create.add_argument("--parent")
    create.add_argument("--sort-type")
    create.add_argument("--apply", action="store_true")
    update = tag_sub.add_parser("update")
    update.add_argument("name")
    update.add_argument("--color")
    update.add_argument("--parent")
    update.add_argument("--sort-type")
    update.add_argument("--sort-order", type=int)
    update.add_argument("--apply", action="store_true")
    delete = tag_sub.add_parser("delete")
    delete.add_argument("name")
    delete.add_argument("--apply", action="store_true", help="Actually delete; without this, dry-run only")
    rename = tag_sub.add_parser("rename")
    rename.add_argument("old_name")
    rename.add_argument("new_name")
    rename.add_argument("--apply", action="store_true")
    merge = tag_sub.add_parser("merge")
    merge.add_argument("source")
    merge.add_argument("target")
    merge.add_argument("--apply", action="store_true")

    columns = sub.add_parser("columns")
    column_sub = columns.add_subparsers(dest="action", required=True)
    column_list = column_sub.add_parser("list")
    column_list.add_argument("project_id")
    column_delete = column_sub.add_parser("delete")
    column_delete.add_argument("project_id")
    column_delete.add_argument("column_id")
    column_delete.add_argument("--apply", action="store_true", help="Actually delete; without this, dry-run only")

    folders = sub.add_parser("folders")
    folder_sub = folders.add_subparsers(dest="action", required=True)
    folder_sub.add_parser("list")
    folder_create = folder_sub.add_parser("create")
    folder_create.add_argument("name")
    folder_create.add_argument("--sort-order", type=int)
    folder_create.add_argument("--apply", action="store_true")
    folder_update = folder_sub.add_parser("update")
    folder_update.add_argument("folder_id")
    folder_update.add_argument("--name")
    folder_update.add_argument("--sort-order", type=int)
    folder_update.add_argument("--apply", action="store_true")
    folder_delete = folder_sub.add_parser("delete")
    folder_delete.add_argument("folder_id")
    folder_delete.add_argument("--apply", action="store_true")

    projects = sub.add_parser("projects")
    project_sub = projects.add_subparsers(dest="action", required=True)
    project_sub.add_parser("list")
    set_folder = project_sub.add_parser("set-folder")
    set_folder.add_argument("project_id")
    set_folder.add_argument("folder_id", help="Folder/group id; use 'none' to clear folder assignment")
    set_folder.add_argument("--apply", action="store_true")

    tasks = sub.add_parser("tasks")
    task_sub = tasks.add_subparsers(dest="action", required=True)
    task_sub.add_parser("list")
    get_task = task_sub.add_parser("get")
    get_task.add_argument("task_id")
    get_task.add_argument("--project-id")
    create_task = task_sub.add_parser("create")
    create_task.add_argument("--title", required=True)
    create_task.add_argument("--project-id")
    create_task.add_argument("--content")
    create_task.add_argument("--desc")
    create_task.add_argument("--priority", type=int)
    create_task.add_argument("--tag", action="append", dest="tags")
    create_task.add_argument("--kind", choices=["TEXT", "NOTE", "CHECKLIST"])
    create_task.add_argument("--due-date")
    create_task.add_argument("--start-date")
    create_task.add_argument("--time-zone")
    create_task.add_argument("--all-day", action="store_true")
    create_task.add_argument("--column-id")
    create_task.add_argument("--items-json")
    create_task.add_argument("--apply", action="store_true")
    update_task = task_sub.add_parser("update")
    update_task.add_argument("task_id")
    update_task.add_argument("--project-id", required=True)
    update_task.add_argument("--title")
    update_task.add_argument("--content")
    update_task.add_argument("--desc")
    update_task.add_argument("--priority", type=int)
    update_task.add_argument("--tag", action="append", dest="tags")
    update_task.add_argument("--kind", choices=["TEXT", "NOTE", "CHECKLIST"])
    update_task.add_argument("--due-date")
    update_task.add_argument("--start-date")
    update_task.add_argument("--time-zone")
    update_task.add_argument("--all-day", action="store_true")
    update_task.add_argument("--column-id")
    update_task.add_argument("--items-json")
    update_task.add_argument("--apply", action="store_true")
    for status_action in ("complete", "reopen", "abandon", "delete"):
        status_cmd = task_sub.add_parser(status_action)
        status_cmd.add_argument("task_id")
        status_cmd.add_argument("--project-id", required=True)
        status_cmd.add_argument("--apply", action="store_true")
    batch = task_sub.add_parser("batch")
    batch.add_argument("--add-json")
    batch.add_argument("--update-json")
    batch.add_argument("--delete-json")
    batch.add_argument("--apply", action="store_true")
    move = task_sub.add_parser("move")
    move.add_argument("task_id")
    move.add_argument("--from-project", required=True)
    move.add_argument("--to-project", required=True)
    move.add_argument("--apply", action="store_true")
    set_parent = task_sub.add_parser("set-parent")
    set_parent.add_argument("task_id")
    set_parent.add_argument("project_id")
    set_parent.add_argument("parent_id")
    set_parent.add_argument("--apply", action="store_true")
    unset_parent = task_sub.add_parser("unset-parent")
    unset_parent.add_argument("task_id")
    unset_parent.add_argument("project_id")
    unset_parent.add_argument("old_parent_id")
    unset_parent.add_argument("--apply", action="store_true")
    closed = task_sub.add_parser("closed")
    closed.add_argument("--from", dest="from_date", required=True)
    closed.add_argument("--to", dest="to_date", required=True)
    closed.add_argument("--status", choices=["Completed", "Abandoned"], default="Completed")
    closed.add_argument("--limit", type=int, default=100)
    trash = task_sub.add_parser("trash")
    trash.add_argument("--start", type=int, default=0)
    trash.add_argument("--limit", type=int, default=500)

    habits = sub.add_parser("habits")
    habit_sub = habits.add_subparsers(dest="action", required=True)
    habit_sub.add_parser("list")
    habit_sub.add_parser("sections")
    habit_batch = habit_sub.add_parser("batch")
    habit_batch.add_argument("--add-json")
    habit_batch.add_argument("--update-json")
    habit_batch.add_argument("--delete-json")
    habit_batch.add_argument("--apply", action="store_true")
    checkins = habit_sub.add_parser("checkins")
    checkin_sub = checkins.add_subparsers(dest="checkin_action", required=True)
    checkin_query = checkin_sub.add_parser("query")
    checkin_query.add_argument("--habit-id", action="append", required=True)
    checkin_query.add_argument("--after-stamp", type=int, default=0)
    checkin_batch = checkin_sub.add_parser("batch")
    checkin_batch.add_argument("--add-json")
    checkin_batch.add_argument("--update-json")
    checkin_batch.add_argument("--delete-json")
    checkin_batch.add_argument("--apply", action="store_true")

    stats = sub.add_parser("stats")
    stats_sub = stats.add_subparsers(dest="action", required=True)
    stats_sub.add_parser("profile")
    stats_sub.add_parser("preferences")
    stats_sub.add_parser("productivity")
    heatmap = stats_sub.add_parser("focus-heatmap")
    heatmap.add_argument("from_date")
    heatmap.add_argument("to_date")
    distribution = stats_sub.add_parser("focus-dist")
    distribution.add_argument("from_date")
    distribution.add_argument("to_date")
    timeline = stats_sub.add_parser("focus-timeline")
    timeline.add_argument("--to", dest="to_timestamp", type=int)

    query = sub.add_parser("query")
    query_sub = query.add_subparsers(dest="action", required=True)
    workspace = query_sub.add_parser("workspace")
    workspace.add_argument("--counts", dest="include_counts", action="store_true")
    workspace.add_argument("--include-closed", action="store_true")
    workspace.add_argument("--project-name")
    workspace.add_argument("--project-regex")
    workspace.add_argument("--folder-name")
    workspace.add_argument("--folder-regex")
    query_tasks = query_sub.add_parser("tasks")
    query_tasks.add_argument("--project-id", action="append", dest="project_ids")
    query_tasks.add_argument("--project-name", action="append", dest="project_names")
    query_tasks.add_argument("--folder-id", action="append", dest="folder_ids")
    query_tasks.add_argument("--folder-name", action="append", dest="folder_names")
    query_tasks.add_argument("--tag", action="append", dest="tags")
    query_tasks.add_argument("--tag-mode", choices=["any", "all"], default="any")
    query_tasks.add_argument("--text", dest="text_query")
    query_tasks.add_argument("--keyword-mode", choices=["any", "all", "phrase"], default="any")
    query_tasks.add_argument("--regex")
    query_tasks.add_argument("--exclude-regex")
    query_tasks.add_argument("--due-from")
    query_tasks.add_argument("--due-to")
    query_tasks.add_argument("--start-from")
    query_tasks.add_argument("--start-to")
    query_tasks.add_argument("--min-priority", type=int)
    query_tasks.add_argument("--priority", action="append", type=int, dest="priorities")
    query_tasks.add_argument("--has-reminders", action="store_true")
    query_tasks.add_argument("--recurring", dest="is_recurring", action="store_true")
    query_tasks.add_argument("--has-checklist", action="store_true")
    query_tasks.add_argument("--parent-only", action="store_true")
    query_tasks.add_argument("--subtasks-only", action="store_true")
    query_tasks.add_argument("--limit", type=int, default=50)
    query_tasks.add_argument("--sort-by", default="dueDate")
    query_tasks.add_argument("--descending", action="store_true")
    agenda = query_sub.add_parser("agenda")
    agenda.add_argument("from_dt")
    agenda.add_argument("to_dt")
    agenda.add_argument("--date-field", choices=["scheduled", "due", "start"], default="scheduled")
    agenda.add_argument("--timezone")
    agenda.add_argument("--tag", action="append", dest="tags")
    agenda.add_argument("--text", dest="text_query")
    agenda.add_argument("--limit", type=int, default=50)
    priority = query_sub.add_parser("priority-dashboard")
    priority.add_argument("--limit", type=int, default=50)

    verified = sub.add_parser("verified")
    verified_sub = verified.add_subparsers(dest="action", required=True)
    v_update = verified_sub.add_parser("update")
    v_update.add_argument("task_id")
    v_update.add_argument("--project-id", required=True)
    v_update.add_argument("--title")
    v_update.add_argument("--content")
    v_update.add_argument("--desc")
    v_update.add_argument("--priority", type=int)
    v_update.add_argument("--status", type=int, choices=[-1, 0, 2])
    v_update.add_argument("--tag", action="append", dest="tags")
    v_update.add_argument("--due-date")
    v_update.add_argument("--start-date")
    v_update.add_argument("--time-zone")
    v_update.add_argument("--column-id")
    all_day = v_update.add_mutually_exclusive_group()
    all_day.add_argument("--all-day", dest="all_day", action="store_true")
    all_day.add_argument("--not-all-day", dest="all_day", action="store_false")
    v_update.set_defaults(all_day=None)
    v_update.add_argument("--items-json")
    v_update.add_argument("--apply", action="store_true")
    v_move = verified_sub.add_parser("move")
    v_move.add_argument("task_id")
    v_move.add_argument("--from-project", required=True)
    v_move.add_argument("--to-project", required=True)
    v_move.add_argument("--apply", action="store_true")
    v_set_parent = verified_sub.add_parser("set-parent")
    v_set_parent.add_argument("task_id")
    v_set_parent.add_argument("project_id")
    v_set_parent.add_argument("parent_id")
    v_set_parent.add_argument("--apply", action="store_true")
    v_unset_parent = verified_sub.add_parser("unset-parent")
    v_unset_parent.add_argument("task_id")
    v_unset_parent.add_argument("project_id")
    v_unset_parent.add_argument("old_parent_id")
    v_unset_parent.add_argument("--apply", action="store_true")
    v_project_folder = verified_sub.add_parser("project-folder")
    v_project_folder.add_argument("project_id")
    v_project_folder.add_argument("folder_id", help="Folder/group id; use 'none' to clear folder assignment")
    v_project_folder.add_argument("--apply", action="store_true")
    return parser


def session_store_from_args(args: argparse.Namespace, *, required: bool = False) -> SessionStore | None:
    try:
        return KeyringSessionStore()
    except DidaAuthError:
        if required:
            raise
        return None


def client_from_args(args: argparse.Namespace) -> DidaV2Client:
    cfg = DidaConfig.for_profile(args.profile)
    store = session_store_from_args(args, required=False)
    token = resolve_session_token(
        profile=args.profile,
        headless=not args.no_headless,
        session_store=store,
    )
    return DidaV2Client(cfg, session_token=token)


def _json_list_arg(value: str | None) -> list[Any]:
    if not value:
        return []
    if value.startswith("@"):
        with open(value[1:], "r", encoding="utf-8") as handle:
            value = handle.read()
    parsed = json.loads(value)
    if not isinstance(parsed, list):
        raise DidaV2Error("JSON argument must be a list")
    return parsed


def _task_payload_from_args(args: argparse.Namespace, *, include_id: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if include_id:
        payload["id"] = args.task_id
    field_map = {
        "title": "title",
        "project_id": "projectId",
        "content": "content",
        "desc": "desc",
        "priority": "priority",
        "kind": "kind",
        "due_date": "dueDate",
        "start_date": "startDate",
        "time_zone": "timeZone",
        "column_id": "columnId",
    }
    for attr, api_key in field_map.items():
        value = getattr(args, attr, None)
        if value is not None:
            payload[api_key] = value
    if getattr(args, "all_day", False):
        payload["allDay"] = True
    if getattr(args, "tags", None):
        payload["tags"] = args.tags
    if getattr(args, "items_json", None):
        payload["items"] = _json_list_arg(args.items_json)
    return payload


def _verified_task_changes_from_args(args: argparse.Namespace) -> dict[str, Any]:
    field_map = {
        "title": "title",
        "content": "content",
        "desc": "desc",
        "priority": "priority",
        "status": "status",
        "due_date": "dueDate",
        "start_date": "startDate",
        "time_zone": "timeZone",
        "column_id": "columnId",
        "all_day": "allDay",
        "tags": "tags",
    }
    changes = {
        api_key: value
        for attr, api_key in field_map.items()
        if (value := getattr(args, attr, None)) is not None
    }
    if getattr(args, "items_json", None) is not None:
        changes["items"] = _json_list_arg(args.items_json)
    return changes


def _query_filter_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "project_ids": getattr(args, "project_ids", None),
        "project_names": getattr(args, "project_names", None),
        "folder_ids": getattr(args, "folder_ids", None),
        "folder_names": getattr(args, "folder_names", None),
        "tags": getattr(args, "tags", None),
        "tag_mode": getattr(args, "tag_mode", "any"),
        "text_query": getattr(args, "text_query", None),
        "keyword_mode": getattr(args, "keyword_mode", "any"),
        "regex": getattr(args, "regex", None),
        "exclude_regex": getattr(args, "exclude_regex", None),
        "due_from": getattr(args, "due_from", None),
        "due_to": getattr(args, "due_to", None),
        "start_from": getattr(args, "start_from", None),
        "start_to": getattr(args, "start_to", None),
        "min_priority": getattr(args, "min_priority", None),
        "priorities": getattr(args, "priorities", None),
        "has_reminders": True if getattr(args, "has_reminders", False) else None,
        "is_recurring": True if getattr(args, "is_recurring", False) else None,
        "has_checklist": True if getattr(args, "has_checklist", False) else None,
        "parent_only": getattr(args, "parent_only", False),
        "subtasks_only": getattr(args, "subtasks_only", False),
        "limit": getattr(args, "limit", 50),
        "sort_by": getattr(args, "sort_by", "dueDate"),
        "descending": getattr(args, "descending", False),
    }


def _noneish(value: str) -> str | None:
    return None if value.lower() in {"none", "null", "-"} else value


def _run_auth(args: argparse.Namespace) -> int:
    config = DidaConfig.for_profile(args.profile)
    profile = config.profile
    store = session_store_from_args(args, required=True)
    if store is None:  # pragma: no cover - required=True raises first
        raise DidaAuthError("OS secure session storage is unavailable.")
    if args.action in {"login", "refresh"}:
        token = direct_signon_login(profile=profile, config=config)
        DidaV2Client(config, session_token=token).user_status()
        store.set(profile, token)
        print(json.dumps({"profile": profile, "stored": True, "valid": True}, ensure_ascii=False))
        return 0
    if args.action == "status":
        token = store.get(profile)
        if not token:
            print(json.dumps({"profile": profile, "stored": False, "valid": False}, ensure_ascii=False))
            return 1
        try:
            DidaV2Client(config, session_token=token).user_status()
        except DidaV2HTTPError as exc:
            definitively_invalid = exc.status == 401 or (
                exc.status is None and exc.error_code == "user_not_sign_on"
            )
            if not definitively_invalid:
                raise
            store.delete(profile)
            print(json.dumps({"profile": profile, "stored": False, "valid": False}, ensure_ascii=False))
            return 1
        print(json.dumps({"profile": profile, "stored": True, "valid": True}, ensure_ascii=False))
        return 0
    if args.action == "logout":
        store.delete(profile)
        print(json.dumps({"profile": profile, "stored": False, "valid": False}, ensure_ascii=False))
        return 0
    raise DidaAuthError("Unsupported auth action.")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.resource == "auth":
            try:
                return _run_auth(args)
            except Exception:
                print("ERROR: Authentication operation failed.", file=sys.stderr)
                return 2
        client = client_from_args(args)
        if args.resource == "filters":
            if args.action == "list":
                print(json.dumps(client.list_filters(), ensure_ascii=False, indent=2))
                return 0
            selector = args.filter_id or args.filter_name
            if args.action == "run":
                query_service = DidaV2QueryService(client)
                kwargs: dict[str, Any] = {}
                if args.timezone:
                    kwargs["timezone"] = args.timezone
                if args.now:
                    kwargs["now"] = args.now
                print(
                    json.dumps(
                        query_service.query_saved_filter(selector, **kwargs),
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 0
            saved_filter = client.get_filter(args.filter_id) if args.filter_id else client.find_filter(args.filter_name)
            if saved_filter is None:
                raise DidaV2Error(f"Saved filter not found: {selector}")
            if args.action == "get":
                print(json.dumps(saved_filter, ensure_ascii=False, indent=2))
                return 0
            evaluator = SavedFilterEvaluator()
            parsed = evaluator.parse(saved_filter.get("rule") or {})
            print(
                json.dumps(
                    {"filter": saved_filter, "parsed_rule": parsed, "explanation": evaluator.explain(parsed)},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.resource == "query":
            query_service = DidaV2QueryService(client)
            if args.action == "workspace":
                print(
                    json.dumps(
                        query_service.workspace_map(
                            include_closed=args.include_closed,
                            include_counts=args.include_counts,
                            project_name_query=args.project_name,
                            project_regex=args.project_regex,
                            folder_name_query=args.folder_name,
                            folder_regex=args.folder_regex,
                        ),
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 0
            if args.action == "tasks":
                print(json.dumps(query_service.query_tasks(**_query_filter_kwargs(args)), ensure_ascii=False, indent=2))
                return 0
            if args.action == "agenda":
                agenda_kwargs: dict[str, Any] = {"date_field": args.date_field}
                if args.timezone:
                    agenda_kwargs["timezone"] = args.timezone
                if args.tags:
                    agenda_kwargs["tags"] = args.tags
                if args.text_query:
                    agenda_kwargs["text_query"] = args.text_query
                if args.limit != 50:
                    agenda_kwargs["limit"] = args.limit
                print(
                    json.dumps(
                        query_service.query_agenda(
                            args.from_dt,
                            args.to_dt,
                            **agenda_kwargs,
                        ),
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 0
            if args.action == "priority-dashboard":
                print(json.dumps(query_service.priority_dashboard(limit=args.limit), ensure_ascii=False, indent=2))
                return 0
        if args.resource == "verified":
            verifier = DidaV2Verifier(client)
            if args.action == "update":
                changes = verifier.validate_task_changes(_verified_task_changes_from_args(args))
                payload = {"task_id": args.task_id, "project_id": args.project_id, "changes": changes}
                if not args.apply:
                    print(json.dumps({"dry_run": True, "would_verified_update": payload}, ensure_ascii=False))
                    return 0
                print(
                    json.dumps(
                        verifier.verified_update_task(
                            args.task_id,
                            project_id=args.project_id,
                            changes=changes,
                        ),
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 0
            if args.action == "move":
                payload = {"task_id": args.task_id, "from_project_id": args.from_project, "to_project_id": args.to_project}
                if not args.apply:
                    print(json.dumps({"dry_run": True, "would_verified_move": payload}, ensure_ascii=False))
                    return 0
                print(json.dumps(verifier.verified_move_task(args.task_id, from_project_id=args.from_project, to_project_id=args.to_project), ensure_ascii=False, indent=2))
                return 0
            if args.action == "set-parent":
                payload = {"task_id": args.task_id, "project_id": args.project_id, "parent_id": args.parent_id}
                if not args.apply:
                    print(json.dumps({"dry_run": True, "would_verified_set_parent": payload}, ensure_ascii=False))
                    return 0
                print(json.dumps(verifier.verified_set_task_parent(args.task_id, project_id=args.project_id, parent_id=args.parent_id), ensure_ascii=False, indent=2))
                return 0
            if args.action == "unset-parent":
                payload = {"task_id": args.task_id, "project_id": args.project_id, "old_parent_id": args.old_parent_id}
                if not args.apply:
                    print(json.dumps({"dry_run": True, "would_verified_unset_parent": payload}, ensure_ascii=False))
                    return 0
                print(json.dumps(verifier.verified_unset_task_parent(args.task_id, project_id=args.project_id, old_parent_id=args.old_parent_id), ensure_ascii=False, indent=2))
                return 0
            if args.action == "project-folder":
                folder_id = _noneish(args.folder_id)
                payload = {"project_id": args.project_id, "folder_id": folder_id}
                if not args.apply:
                    print(json.dumps({"dry_run": True, "would_verified_project_folder": payload}, ensure_ascii=False))
                    return 0
                print(json.dumps(verifier.verified_set_project_folder(args.project_id, folder_id), ensure_ascii=False, indent=2))
                return 0
        if args.resource == "status":
            print(json.dumps(client.user_status(), ensure_ascii=False, indent=2))
            return 0
        if args.resource == "tags" and args.action == "list":
            print(json.dumps(client.list_tags(), ensure_ascii=False, indent=2))
            return 0
        if args.resource == "tags" and args.action == "create":
            if not args.apply:
                print(
                    json.dumps(
                        {
                            "dry_run": True,
                            "would_create_tag": {
                                "name": args.name,
                                "color": args.color,
                                "parent": args.parent,
                                "sort_type": args.sort_type,
                            },
                        },
                        ensure_ascii=False,
                    )
                )
                return 0
            print(
                json.dumps(
                    client.create_tag(name=args.name, color=args.color, parent=args.parent, sort_type=args.sort_type),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.resource == "tags" and args.action == "update":
            if not args.apply:
                print(
                    json.dumps(
                        {
                            "dry_run": True,
                            "would_update_tag": {
                                "name": args.name,
                                "color": args.color,
                                "parent": args.parent,
                                "sort_type": args.sort_type,
                                "sort_order": args.sort_order,
                            },
                        },
                        ensure_ascii=False,
                    )
                )
                return 0
            print(
                json.dumps(
                    client.update_tag(
                        name=args.name,
                        color=args.color,
                        parent=args.parent,
                        sort_type=args.sort_type,
                        sort_order=args.sort_order,
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.resource == "tags" and args.action == "delete":
            if not args.apply:
                print(json.dumps({"dry_run": True, "would_delete": args.name}, ensure_ascii=False))
                return 0
            print(json.dumps(client.delete_tag(args.name), ensure_ascii=False, indent=2))
            return 0
        if args.resource == "tags" and args.action == "rename":
            if not args.apply:
                print(json.dumps({"dry_run": True, "would_rename": [args.old_name, args.new_name]}, ensure_ascii=False))
                return 0
            print(json.dumps(client.rename_tag(args.old_name, args.new_name), ensure_ascii=False, indent=2))
            return 0
        if args.resource == "tags" and args.action == "merge":
            if not args.apply:
                print(json.dumps({"dry_run": True, "would_merge": [args.source, args.target]}, ensure_ascii=False))
                return 0
            print(json.dumps(client.merge_tags(args.source, args.target), ensure_ascii=False, indent=2))
            return 0
        if args.resource == "columns" and args.action == "list":
            print(json.dumps(client.list_columns(args.project_id), ensure_ascii=False, indent=2))
            return 0
        if args.resource == "columns" and args.action == "delete":
            if not args.apply:
                print(
                    json.dumps(
                        {"dry_run": True, "would_delete_column": {"project_id": args.project_id, "column_id": args.column_id}},
                        ensure_ascii=False,
                    )
                )
                return 0
            print(json.dumps(client.delete_column(args.project_id, args.column_id), ensure_ascii=False, indent=2))
            return 0
        if args.resource == "folders" and args.action == "list":
            print(json.dumps(client.list_project_folders(), ensure_ascii=False, indent=2))
            return 0
        if args.resource == "folders" and args.action == "create":
            if not args.apply:
                print(
                    json.dumps(
                        {"dry_run": True, "would_create_folder": {"name": args.name, "sort_order": args.sort_order}},
                        ensure_ascii=False,
                    )
                )
                return 0
            print(json.dumps(client.create_project_folder(args.name, sort_order=args.sort_order), ensure_ascii=False, indent=2))
            return 0
        if args.resource == "folders" and args.action == "update":
            if not args.apply:
                print(
                    json.dumps(
                        {
                            "dry_run": True,
                            "would_update_folder": {"folder_id": args.folder_id, "name": args.name, "sort_order": args.sort_order},
                        },
                        ensure_ascii=False,
                    )
                )
                return 0
            print(
                json.dumps(
                    client.update_project_folder(args.folder_id, name=args.name, sort_order=args.sort_order),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.resource == "folders" and args.action == "delete":
            if not args.apply:
                print(json.dumps({"dry_run": True, "would_delete_folder": args.folder_id}, ensure_ascii=False))
                return 0
            print(json.dumps(client.delete_project_folder(args.folder_id), ensure_ascii=False, indent=2))
            return 0
        if args.resource == "projects" and args.action == "list":
            print(json.dumps(client.list_projects(), ensure_ascii=False, indent=2))
            return 0
        if args.resource == "projects" and args.action == "set-folder":
            folder_id = None if args.folder_id.lower() in {"none", "null", "-"} else args.folder_id
            if not args.apply:
                print(
                    json.dumps(
                        {"dry_run": True, "would_set_project_folder": {"project_id": args.project_id, "folder_id": folder_id}},
                        ensure_ascii=False,
                    )
                )
                return 0
            print(json.dumps(client.set_project_folder(args.project_id, folder_id), ensure_ascii=False, indent=2))
            return 0
        if args.resource == "tasks" and args.action == "list":
            print(json.dumps(client.list_tasks(), ensure_ascii=False, indent=2))
            return 0
        if args.resource == "tasks" and args.action == "get":
            print(json.dumps(client.get_task(args.task_id, project_id=args.project_id), ensure_ascii=False, indent=2))
            return 0
        if args.resource == "tasks" and args.action == "create":
            payload = _task_payload_from_args(args)
            if not args.apply:
                print(json.dumps({"dry_run": True, "would_create_task": payload}, ensure_ascii=False))
                return 0
            print(json.dumps(client.create_task(payload), ensure_ascii=False, indent=2))
            return 0
        if args.resource == "tasks" and args.action == "update":
            payload = _task_payload_from_args(args, include_id=True)
            if not args.apply:
                print(json.dumps({"dry_run": True, "would_update_task": payload}, ensure_ascii=False))
                return 0
            print(json.dumps(client.update_task(payload), ensure_ascii=False, indent=2))
            return 0
        if args.resource == "tasks" and args.action in {"complete", "reopen", "abandon"}:
            status = {"complete": 2, "reopen": 0, "abandon": -1}[args.action]
            payload = {"id": args.task_id, "projectId": args.project_id, "status": status}
            if not args.apply:
                print(json.dumps({"dry_run": True, "would_update_task": payload}, ensure_ascii=False))
                return 0
            method = getattr(client, f"{args.action}_task")
            print(json.dumps(method(args.task_id, project_id=args.project_id), ensure_ascii=False, indent=2))
            return 0
        if args.resource == "tasks" and args.action == "delete":
            if not args.apply:
                print(
                    json.dumps(
                        {"dry_run": True, "would_delete_task": {"task_id": args.task_id, "project_id": args.project_id}},
                        ensure_ascii=False,
                    )
                )
                return 0
            print(json.dumps(client.delete_task(args.task_id, project_id=args.project_id), ensure_ascii=False, indent=2))
            return 0
        if args.resource == "tasks" and args.action == "batch":
            add = _json_list_arg(args.add_json)
            update = _json_list_arg(args.update_json)
            delete = _json_list_arg(args.delete_json)
            if not args.apply:
                print(
                    json.dumps(
                        {"dry_run": True, "would_batch_tasks": {"add": add, "update": update, "delete": delete}},
                        ensure_ascii=False,
                    )
                )
                return 0
            result = client.batch_tasks(add=add, update=update, delete=delete)
            print(json.dumps(client.ensure_batch_ok(result), ensure_ascii=False, indent=2))
            return 0
        if args.resource == "tasks" and args.action == "move":
            if not args.apply:
                print(
                    json.dumps(
                        {
                            "dry_run": True,
                            "would_move_task": {
                                "task_id": args.task_id,
                                "from_project_id": args.from_project,
                                "to_project_id": args.to_project,
                            },
                        },
                        ensure_ascii=False,
                    )
                )
                return 0
            print(
                json.dumps(
                    client.move_task(args.task_id, from_project_id=args.from_project, to_project_id=args.to_project),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.resource == "tasks" and args.action == "set-parent":
            if not args.apply:
                print(
                    json.dumps(
                        {
                            "dry_run": True,
                            "would_set_task_parent": {
                                "task_id": args.task_id,
                                "project_id": args.project_id,
                                "parent_id": args.parent_id,
                            },
                        },
                        ensure_ascii=False,
                    )
                )
                return 0
            print(
                json.dumps(
                    client.set_task_parent(args.task_id, project_id=args.project_id, parent_id=args.parent_id),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.resource == "tasks" and args.action == "unset-parent":
            if not args.apply:
                print(
                    json.dumps(
                        {
                            "dry_run": True,
                            "would_unset_task_parent": {
                                "task_id": args.task_id,
                                "project_id": args.project_id,
                                "old_parent_id": args.old_parent_id,
                            },
                        },
                        ensure_ascii=False,
                    )
                )
                return 0
            print(
                json.dumps(
                    client.unset_task_parent(args.task_id, project_id=args.project_id, old_parent_id=args.old_parent_id),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.resource == "tasks" and args.action == "closed":
            print(
                json.dumps(
                    client.list_closed_tasks(
                        from_date=args.from_date,
                        to_date=args.to_date,
                        status=args.status,
                        limit=args.limit,
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.resource == "tasks" and args.action == "trash":
            print(json.dumps(client.list_trash_tasks(start=args.start, limit=args.limit), ensure_ascii=False, indent=2))
            return 0
        if args.resource == "habits" and args.action == "list":
            print(json.dumps(client.list_habits(), ensure_ascii=False, indent=2))
            return 0
        if args.resource == "habits" and args.action == "sections":
            print(json.dumps(client.list_habit_sections(), ensure_ascii=False, indent=2))
            return 0
        if args.resource == "habits" and args.action == "batch":
            add = _json_list_arg(args.add_json)
            update = _json_list_arg(args.update_json)
            delete = _json_list_arg(args.delete_json)
            if not args.apply:
                print(
                    json.dumps(
                        {"dry_run": True, "would_batch_habits": {"add": add, "update": update, "delete": delete}},
                        ensure_ascii=False,
                    )
                )
                return 0
            result = client.batch_habits(add=add, update=update, delete=delete)
            print(json.dumps(client.ensure_ok_response(result), ensure_ascii=False, indent=2))
            return 0
        if args.resource == "habits" and args.action == "checkins" and args.checkin_action == "query":
            print(json.dumps(client.query_habit_checkins(args.habit_id, after_stamp=args.after_stamp), ensure_ascii=False, indent=2))
            return 0
        if args.resource == "habits" and args.action == "checkins" and args.checkin_action == "batch":
            add = _json_list_arg(args.add_json)
            update = _json_list_arg(args.update_json)
            delete = _json_list_arg(args.delete_json)
            if not args.apply:
                print(
                    json.dumps(
                        {"dry_run": True, "would_batch_habit_checkins": {"add": add, "update": update, "delete": delete}},
                        ensure_ascii=False,
                    )
                )
                return 0
            result = client.batch_habit_checkins(add=add, update=update, delete=delete)
            print(json.dumps(client.ensure_ok_response(result), ensure_ascii=False, indent=2))
            return 0
        if args.resource == "stats" and args.action == "profile":
            print(json.dumps(client.user_profile(), ensure_ascii=False, indent=2))
            return 0
        if args.resource == "stats" and args.action == "preferences":
            print(json.dumps(client.user_preferences(), ensure_ascii=False, indent=2))
            return 0
        if args.resource == "stats" and args.action == "productivity":
            print(json.dumps(client.productivity_stats(), ensure_ascii=False, indent=2))
            return 0
        if args.resource == "stats" and args.action == "focus-heatmap":
            print(json.dumps(client.focus_heatmap(args.from_date, args.to_date), ensure_ascii=False, indent=2))
            return 0
        if args.resource == "stats" and args.action == "focus-dist":
            print(json.dumps(client.focus_distribution(args.from_date, args.to_date), ensure_ascii=False, indent=2))
            return 0
        if args.resource == "stats" and args.action == "focus-timeline":
            print(json.dumps(client.focus_timeline(to_timestamp=args.to_timestamp), ensure_ascii=False, indent=2))
            return 0
    except (DidaV2Error, ValueError, ZoneInfoNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
