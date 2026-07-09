# dida-v2-client

Small, conservative Dida365-first private v2 client.

## Design

- Dida365 / 中国版 is the default profile.
- TickTick international compatibility is a profile switch; it is mostly the same API shape with different domains.
- We are moving toward **v2-first** coverage, while keeping write operations safe by default.
- Prefer official v1 / `dida` CLI only as a fallback while the v2 client is still gaining typed wrappers and live verification.
- Authentication defaults to direct local web sign-on (`DIDA_EMAIL`/`DIDA_PASSWORD`) and falls back to Selenium form automation, then raw local `t` session token env vars. Direct sign-on uses a stable live-verified 24-hex `X-Device` id by default; override with `DIDA_DEVICE_ID` only if needed.
- CLI write operations default to dry-run; pass `--apply` to write.

## Endpoints

Default Dida365 profile:

```text
web: https://dida365.com
v2:  https://api.dida365.com/api/v2
```

TickTick profile:

```text
web: https://ticktick.com
v2:  https://api.ticktick.com/api/v2
```

## CLI examples

```bash
# session / sync; credentials stay in local env/secret store, not chat
DIDA_EMAIL='<local-email>' DIDA_PASSWORD='<local-password>' uv run dida-v2 status

# tags
uv run dida-v2 --no-headless tags list
uv run dida-v2 --no-headless tags create 新标签 --color '#4AA6EF'       # dry-run
uv run dida-v2 --no-headless tags update 待检视 --color '#4AA6EF'      # dry-run
uv run dida-v2 --no-headless tags delete 提醒                          # dry-run
uv run dida-v2 --no-headless tags rename old new                       # dry-run
uv run dida-v2 --no-headless tags merge old new                        # dry-run

# projects / folders / kanban columns
uv run dida-v2 --no-headless folders list
uv run dida-v2 --no-headless folders create 工作 --sort-order 10       # dry-run
uv run dida-v2 --no-headless folders update <folder_id> --name 新名字  # dry-run
uv run dida-v2 --no-headless folders delete <folder_id>                # dry-run
uv run dida-v2 --no-headless projects list                             # v2 shows real groupId/folder assignment
uv run dida-v2 --no-headless projects set-folder <project_id> <folder_id>  # dry-run
uv run dida-v2 --no-headless projects set-folder <project_id> none         # dry-run, clear folder
uv run dida-v2 --no-headless columns list <project_id>
uv run dida-v2 --no-headless columns delete <project_id> <column_id>   # dry-run

# v2 task reads/writes
uv run dida-v2 --no-headless tasks list
uv run dida-v2 --no-headless tasks get <task_id> --project-id <project_id>
uv run dida-v2 --no-headless tasks create --title New --project-id <project_id> --priority 3     # dry-run
uv run dida-v2 --no-headless tasks update <task_id> --project-id <project_id> --title Updated    # dry-run
uv run dida-v2 --no-headless tasks complete <task_id> --project-id <project_id>                  # dry-run
uv run dida-v2 --no-headless tasks reopen <task_id> --project-id <project_id>                    # dry-run
uv run dida-v2 --no-headless tasks abandon <task_id> --project-id <project_id>                   # dry-run
uv run dida-v2 --no-headless tasks delete <task_id> --project-id <project_id>                    # dry-run
uv run dida-v2 --no-headless tasks batch --add-json '[{"title":"New","projectId":"p1"}]'  # dry-run
uv run dida-v2 --no-headless tasks move <task_id> --from-project <p1> --to-project <p2>          # dry-run
uv run dida-v2 --no-headless tasks set-parent <child_task_id> <project_id> <parent_task_id>      # dry-run
uv run dida-v2 --no-headless tasks unset-parent <child_task_id> <project_id> <old_parent_id>     # dry-run
uv run dida-v2 --no-headless tasks closed --from '2026-07-01 00:00:00' --to '2026-07-09 23:59:59'
uv run dida-v2 --no-headless tasks trash --limit 50

# v2-first query/read layer inspired by tick-mcp
uv run dida-v2 --no-headless query workspace --counts
uv run dida-v2 --no-headless query tasks --tag work --text "report alpha" --min-priority 3
uv run dida-v2 --no-headless query agenda 2026-07-09T00:00:00+0800 2026-07-09T23:59:59+0800 --date-field scheduled
uv run dida-v2 --no-headless query priority-dashboard --limit 20

# verified writes: still dry-run by default; --apply writes and then reads back
uv run dida-v2 --no-headless verified move <task_id> --from-project <p1> --to-project <p2>        # dry-run
uv run dida-v2 --no-headless verified set-parent <child_task_id> <project_id> <parent_task_id>    # dry-run
uv run dida-v2 --no-headless verified unset-parent <child_task_id> <project_id> <old_parent_id>  # dry-run
uv run dida-v2 --no-headless verified project-folder <project_id> <folder_id>                    # dry-run

# habits / check-ins
uv run dida-v2 --no-headless habits list
uv run dida-v2 --no-headless habits sections
uv run dida-v2 --no-headless habits batch --add-json '[{"name":"Drink water"}]'  # dry-run
uv run dida-v2 --no-headless habits checkins query --habit-id <habit_id> --after-stamp 20260701
uv run dida-v2 --no-headless habits checkins batch --update-json '[{"id":"checkin_id"}]'  # dry-run

# account / productivity / focus statistics
uv run dida-v2 --no-headless stats profile
uv run dida-v2 --no-headless stats preferences
uv run dida-v2 --no-headless stats productivity
uv run dida-v2 --no-headless stats focus-heatmap 20260701 20260709
uv run dida-v2 --no-headless stats focus-dist 20260701 20260709
uv run dida-v2 --no-headless stats focus-timeline --to 1234567890

# TickTick international profile
uv run dida-v2 --profile ticktick tags list
```

Fallback token mode:

```bash
DIDA_SESSION_TOKEN='<local-cookie-t-value>' uv run dida-v2 --no-headless tags list
```

Do not paste session tokens, passwords, or cookies into chat. Prefer direct local sign-on via `DIDA_EMAIL`/`DIDA_PASSWORD`; Selenium form automation is only a fallback because Dida365 login pages can change selectors or show captcha/Turnstile. If Dida returns misleading `username_password_not_match` despite correct credentials, check/override `DIDA_DEVICE_ID` with a 24-character hex string.

## Current scope

Implemented in v0.1:

- config profiles: `dida` and `ticktick` (`cn`/`global` remain compatibility aliases)
- v2 transport with cookie auth
- session/account: `user_status()`, `user_profile()`, `user_preferences()`
- sync: `full_sync()`
- tasks: `list_tasks()`, `get_task()`, `batch_tasks()`, `batch_errors()`, `ensure_batch_ok()`, `create_task()`, `update_task()`, `delete_task()`, `complete_task()`, `reopen_task()`, `abandon_task()`, `move_tasks()`, `move_task()`, `batch_task_parents()`, `set_task_parent()`, `unset_task_parent()`, `list_closed_tasks()`, `list_trash_tasks()`
- tags: `list_tags()`, `batch_tags()`, `create_tag()`, `update_tag()`, `delete_tag()`, `rename_tag()`, `merge_tags()`
- columns: `list_columns()`, `batch_columns()`, `delete_column()`
- folders/projects: `list_project_folders()`, `batch_project_folders()`, `create_project_folder()`, `update_project_folder()`, `delete_project_folder()`, `list_projects()`, `batch_projects()`, `set_project_folder()`
- habits/check-ins: `list_habits()`, `list_habit_sections()`, `batch_habits()`, `query_habit_checkins()`, `batch_habit_checkins()`
- focus/productivity stats: `productivity_stats()`, `focus_heatmap()`, `focus_distribution()`, `focus_timeline()`
- query/read layer: `DidaV2QueryService.workspace_map()`, `query_tasks()`, `query_agenda()`, `priority_dashboard()`
- verified action layer: `DidaV2Verifier.verified_move_task()`, `verified_set_task_parent()`, `verified_unset_task_parent()`, `verified_set_project_folder()`
- CLI dry-run/apply for write operations; read-only commands for history, trash, stats, sync-backed lists, and query views

See `docs/v2-capability-matrix.md` for migration status and remaining v2-first work.

## Next likely additions

- local session cache/keychain integration for direct sign-on tokens
- live-backed verification harness using a disposable project/list
- cascade-safe move helpers for parent tasks and their children
- live sandbox tests using a disposable project/list
