# dida-v2-client

Small, conservative Dida365-first private v2 client.

## Design

- Dida365 / 中国版 is the default profile.
- TickTick international compatibility is a profile switch; it is mostly the same API shape with different domains.
- We are moving toward **v2-first** coverage, while keeping write operations safe by default.
- Prefer official v1 / `dida` CLI only as a fallback while the v2 client is still gaining typed wrappers and live verification.
- Authentication resolves in session-first order: explicitly supplied token, optional OS credential-vault session, profile-specific local session env, direct local web sign-on, then Selenium fallback. All accepted profile aliases are canonicalized before selecting keyring entries, environment variables, credentials, or device ids, so Dida and TickTick auth material cannot cross profiles. Direct sign-on uses a stable live-verified 24-hex `X-Device` id by default; override with the canonical profile's device-id environment variable only if needed.
- CLI write operations default to dry-run; pass `--apply` to write.

## Reference repositories and acknowledgements

This project is an independent Dida365-first implementation. Its endpoint inventory and design were informed by these public repositories:

- [`KpihX/tick-mcp`](https://github.com/KpihX/tick-mcp) — primary reference for private v2 endpoint evidence, tag/column/project/task batch operations, and the higher-level query/verified-action design.
- [`OliverStoll/ticktick-api-v2`](https://github.com/OliverStoll/ticktick-api-v2) — reference for TickTick v2 cookie/Selenium authentication patterns and task, habit, focus, and pomodoro reads.

The upstream repositories are not bundled as runtime dependencies. This client adapts the observed API behavior for Dida365 China endpoints, adds its own safety defaults, tests, CLI, and verification layer, and remains unofficial and unaffiliated with Dida365/TickTick or the referenced projects.

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

## Installation

```bash
uv pip install .
uv pip install '.[secure-store]'  # optional OS keychain / credential vault
uv pip install '.[headless]'      # optional Selenium fallback
```

The `secure-store` extra uses `keyring`; it does not create a plaintext session-token file.

## CLI examples

```bash
# session / sync; credentials stay in local env/secret store, not chat
DIDA_EMAIL='<local-email>' DIDA_PASSWORD='<local-password>' uv run dida-v2 status

# validate and store a session in the OS credential vault
DIDA_EMAIL='<local-email>' DIDA_PASSWORD='<local-password>' uv run dida-v2 auth login
uv run dida-v2 auth status
uv run dida-v2 auth refresh
uv run dida-v2 auth logout

# saved Web UI filters / smart lists
uv run dida-v2 filters list
uv run dida-v2 filters get --name 'Today P1'
uv run dida-v2 filters explain --name 'Today P1'
uv run dida-v2 filters run --name 'Today P1' --timezone Asia/Shanghai

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

Implemented through v0.2.1:

- config profiles: `dida` and `ticktick`; CLI/API share aliases `dida365`/`cn`/`china` and `global`/`intl`/`international`
- v2 transport with cookie auth
- session/account: explicit/store/env/direct/Selenium session-first resolution, optional `KeyringSessionStore`, `auth login/status/refresh/logout`, `user_status()`, `user_profile()`, and `user_preferences()`; all profile aliases are canonicalized before auth-material selection, new sessions are validated before storage, refresh failures preserve the old session, only structured HTTP 401 or status-less `user_not_sign_on` failures remove stored sessions, and auth CLI failures use fixed secret-free output
- sync: `full_sync()`, recursively immutable `SyncSnapshot`, deep-copy return boundaries, and a cache capped at 30 seconds; `config`/`session_token` are read-only and must be replaced together with `set_identity()`, request identities are captured atomically, only the newest eligible fetch may commit, explicit refresh supersedes older fetches, and write attempts or identity changes invalidate stale generations
- saved Web UI filters: `list_filters()`, `get_filter()`, `find_filter()`, `SavedFilterEvaluator`, and `filters list/get/explain/run`
- tasks: `list_tasks()`, `get_task()`, `batch_tasks()`, `batch_errors()`, `ensure_batch_ok()`, `create_task()`, `update_task()`, `delete_task()`, `complete_task()`, `reopen_task()`, `abandon_task()`, `move_tasks()`, `move_task()`, `batch_task_parents()`, `set_task_parent()`, `unset_task_parent()`, `list_closed_tasks()`, `list_trash_tasks()`
- tags: `list_tags()`, `batch_tags()`, `create_tag()`, `update_tag()`, `delete_tag()`, `rename_tag()`, `merge_tags()`
- columns: `list_columns()`, `batch_columns()`, `delete_column()`
- folders/projects: `list_project_folders()`, `batch_project_folders()`, `create_project_folder()`, `update_project_folder()`, `delete_project_folder()`, `list_projects()`, `batch_projects()`, `set_project_folder()`
- habits/check-ins: `list_habits()`, `list_habit_sections()`, `batch_habits()`, `query_habit_checkins()`, `batch_habit_checkins()`
- focus/productivity stats: `productivity_stats()`, `focus_heatmap()`, `focus_distribution()`, `focus_timeline()`
- query/read layer: `DidaV2QueryService.workspace_map()`, `query_tasks()`, timezone-aware `query_agenda()`, `priority_dashboard()`, and `query_saved_filter()`; a saved-filter operation binds its snapshot, preference lookup, and profile fallback to one captured identity, with timezone order explicit option → account Web preference → profile fallback (`Asia/Shanghai` for Dida, `UTC` for TickTick)
- verified action layer: `DidaV2Verifier.verified_move_task()`, `verified_set_task_parent()`, `verified_unset_task_parent()`, `verified_set_project_folder()`
- CLI dry-run/apply for write operations; read-only commands for history, trash, stats, sync-backed lists, and query views

Saved-filter evaluation currently supports nested boolean groups, strict Dida priority values (`0`, `1`, `3`, `5`), and relative `dueDate`/`startDate` values (`today`, `tomorrow`, `yesterday`, `thisWeek`, `nextWeek`, `overdue`). The complete AST is validated before explanation or task matching—even for an empty task collection—so mixed node shapes, unknown conditions, empty groups/value lists, malformed priorities, and unknown relative-date keywords fail closed. The CLI resolves the account/profile timezone before attaching a zone to naive `--now` values and converts normal filter/date/timezone validation errors into concise `ERROR:` output with exit code 2. The client does not guess private write endpoints for filter CRUD.

Python 3.9 is exercised with functional compact-offset (`+0000`/`+0800`) and saved-filter tests, not only an import smoke test.

See `docs/v2-capability-matrix.md` for migration status and remaining v2-first work.

## Next likely additions

- live-backed verification harness using a disposable project/list
- cascade-safe move helpers for parent tasks and their children
- live sandbox tests using a disposable project/list
