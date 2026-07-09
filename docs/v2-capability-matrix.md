# V2 Capability Matrix

This project is moving toward v2-first Dida365/TickTick automation. The default profile is Dida365 China (`dida`), with TickTick international available through `--profile ticktick`.

## Latest boundary probes

- Source inventory on 2026-07-09 compared `tick-mcp 0.2.0`, GitHub `KpihX/tick-mcp` HEAD `d4dfb5c`, `OliverStoll/ticktick-api-v2`, and this repository.
- All literal v2 endpoints found in those two community codebases are now represented in this client. The only textual mismatch is `ticktick-api-v2`'s `pomodoros/timeline{timestamp_query_param}`, implemented here as `/pomodoros/timeline` plus query params.
- GitHub `KpihX/tick-mcp` adds a higher-level layer on top of endpoints: query/search views, verified actions, and live tests. This repository now implements the first Dida365-first subset: workspace map, task query, agenda query, priority dashboard, and verified move/parent/folder writes.
- Public Dida marketing/webapp bundles do **not** expose the logged-in task app v2 surface without a session. The sign-in bundle does confirm `POST /api/v2/user/signon?wc=true&remember=true`.
- Live auth probe on 2026-07-09: direct Dida v2 sign-on with temporary local credentials returned a session token, and read-only `/user/status`, `/batch/check/0`, and `/habits` requests succeeded. Selenium headless could load the login page and submit the form, but no `t` cookie was issued in headless form mode; captcha/Turnstile markers were present. The package now wraps direct sign-on and uses Selenium only as fallback.
- Unauthenticated Dida v2 probe confirms auth boundary:
  - `GET /user/status` → HTTP 401 `user_not_sign_on`
  - `GET /batch/check/0` → HTTP 500 `access_forbidden`
  - `GET /habits` → HTTP 401 `user_not_sign_on`
- No local `DIDA_SESSION_TOKEN`/`TICKTICK_SESSION_TOKEN` or password-login env was present during the latest probe, so live authenticated reads/writes were blocked.

## Safety policy

- Reads can use v2 directly once a local web session is available.
- Writes must default to dry-run in CLI.
- `--apply` is required for writes.
- Do not log or print session cookies/tokens.
- Prefer local headless/cookie auth; raw `t` cookie env vars are local fallback only.
- When replacing a v1 workflow, add read-back verification before trusting the write.
- Typed batch helpers must inspect `id2error`, `errorId`, `errorCode`, and `error` in responses.

## Implemented v2 coverage

| Area | Capability | Endpoint(s) | Client methods | CLI |
| --- | --- | --- | --- | --- |
| Auth/session | account status | `GET /user/status` | `user_status()` | `status` |
| Account | profile | `GET /user/profile` | `user_profile()` | `stats profile` |
| Account | preferences/settings | `GET /user/preferences/settings?includeWeb=true` | `user_preferences()` | `stats preferences` |
| Sync | full sync | `GET /batch/check/0` | `full_sync()` | used internally |
| Tasks | active task list/get via sync | `GET /batch/check/0` | `list_tasks()`, `get_task()` | `tasks list`, `tasks get` |
| Tasks | generic add/update/delete batch | `POST /batch/task` | `batch_tasks()` | `tasks batch` |
| Tasks | typed create/update/delete | `POST /batch/task` | `create_task()`, `update_task()`, `delete_task()` | `tasks create/update/delete` |
| Tasks | complete/reopen/abandon status writes | `POST /batch/task` | `complete_task()`, `reopen_task()`, `abandon_task()` | `tasks complete/reopen/abandon` |
| Tasks | batch error detection | response validation | `batch_errors()`, `ensure_batch_ok()` | typed commands use checked helpers on apply |
| Tasks | move between projects | `POST /batch/taskProject` | `move_tasks()`, `move_task()` | `tasks move` |
| Tasks | set/unset parent/subtask relation | `POST /batch/taskParent` | `batch_task_parents()`, `set_task_parent()`, `unset_task_parent()` | `tasks set-parent`, `tasks unset-parent` |
| Tasks | completed/abandoned history | `GET /project/all/closed` | `list_closed_tasks()` | `tasks closed` |
| Tasks | trash/deleted tasks | `GET /project/all/trash/pagination` | `list_trash_tasks()` | `tasks trash` |
| Tags | list via sync | `GET /batch/check/0` | `list_tags()` | `tags list` |
| Tags | create/update | `POST /batch/tag` | `batch_tags()`, `create_tag()`, `update_tag()` | `tags create`, `tags update` |
| Tags | delete/rename/merge | `DELETE /tag`, `PUT /tag/rename`, `PUT /tag/merge` | `delete_tag()`, `rename_tag()`, `merge_tags()` | `tags delete`, `tags rename`, `tags merge` |
| Columns | list project columns | `GET /column/project/{projectId}` | `list_columns()` | `columns list` |
| Columns | batch add/update/delete | `POST /column` | `batch_columns()`, `delete_column()` | `columns delete` |
| Folders | list project groups/folders | `GET /batch/check/0` | `list_project_folders()` | `folders list` |
| Folders | create/update/delete groups | `POST /batch/projectGroup` | `batch_project_folders()`, `create_project_folder()`, `update_project_folder()`, `delete_project_folder()` | `folders create/update/delete` |
| Projects | v2 project list with real `groupId` | `GET /batch/check/0` | `list_projects()` | `projects list` |
| Projects | update project folder assignment | `POST /batch/project` | `batch_projects()`, `set_project_folder()` | `projects set-folder` |
| Habits | list habits/sections | `GET /habits`, `GET /habitSections` | `list_habits()`, `list_habit_sections()` | `habits list`, `habits sections` |
| Habits | create/update/delete habits | `POST /habits/batch` | `batch_habits()` | `habits batch` |
| Habit check-ins | query and batch check-ins | `POST /habitCheckins/query`, `POST /habitCheckins/batch` | `query_habit_checkins()`, `batch_habit_checkins()` | `habits checkins query/batch` |
| Focus | heatmap/distribution/timeline | `/pomodoros/statistics/*`, `/pomodoros/timeline` | `focus_heatmap()`, `focus_distribution()`, `focus_timeline()` | `stats focus-*` |
| Productivity | general stats | `GET /statistics/general` | `productivity_stats()` | `stats productivity` |
| Query | workspace map and project/folder grouping | `GET /batch/check/0` | `DidaV2QueryService.workspace_map()` | `query workspace` |
| Query | task filtering by project/folder/tag/text/date/priority/hierarchy | `GET /batch/check/0` | `DidaV2QueryService.query_tasks()` | `query tasks` |
| Query | due/start/scheduled agenda windows | `GET /batch/check/0` | `DidaV2QueryService.query_agenda()` | `query agenda` |
| Query | priority buckets/dashboard | `GET /batch/check/0` | `DidaV2QueryService.priority_dashboard()` | `query priority-dashboard` |
| Verified actions | read-back verified move | `POST /batch/taskProject` + `GET /batch/check/0` | `DidaV2Verifier.verified_move_task()` | `verified move` |
| Verified actions | read-back verified parent set/unset | `POST /batch/taskParent` + `GET /batch/check/0` | `verified_set_task_parent()`, `verified_unset_task_parent()` | `verified set-parent`, `verified unset-parent` |
| Verified actions | read-back verified project folder assignment | `POST /batch/project` + `GET /batch/check/0` | `verified_set_project_folder()` | `verified project-folder` |

## Known v2 boundaries and traps

1. **Authentication**
   - v2 requires the logged-in web session cookie `t`.
   - Open API bearer tokens do not authorize v2 endpoints.
   - Direct `POST /user/signon?wc=true&remember=true` is now wrapped for local env credentials and should be preferred over Selenium form automation.
   - Selenium fallback includes Dida365 `#emailOrPhone`, but form login can still be gated by captcha/Turnstile and may not issue `t`.

2. **Task creation and subtasks**
   - `parentId` in `batch/task` create payload is reported by `tick-mcp` to be silently ignored.
   - Correct pattern: create child task, then call `POST /batch/taskParent`.

3. **Moving parent tasks**
   - `POST /batch/taskProject` moves only the listed tasks.
   - It does not automatically move children; callers must explicitly include children or add a cascade helper after project-data read support is added.

4. **Reminders through v2 batch**
   - Community evidence says v2 `batch/task` reminder updates can be silently rejected or fail to anchor if due-date state differs across v1/v2.
   - Keep reminder-heavy workflows on verified v1/Open API path until a live v2 sandbox proves payload shape.

5. **Habits batch is full-object replacement**
   - Updating a habit with a partial object can wipe fields.
   - Safe high-level update should read current habit, merge fields, then send full object. Current CLI exposes raw/dry-run `habits batch`; use carefully.

6. **Columns and tags**
   - v2 has working private endpoints for operations missing in the current `dida` CLI: tag delete/rename/merge and column batch/delete.
   - Apply only after dry-run and read-back.

## Evidence-only / not yet wrapped

| Area | Evidence | Status |
| --- | --- | --- |
| Direct web sign-on | `POST /api/v2/user/signon?wc=true&remember=true` live-verified 2026-07-09 for read-only v2 access | Wrapped in `direct_signon_login()` and used by default by `resolve_session_token()` when local env credentials are present; next: cache/keychain integration |
| Comments | v1 CLI/Open API supports comments; no confirmed v2 endpoint in inspected sources | Keep v1 for now |
| Attachments | `batch/task` payload supports `addAttachments`/`updateAttachments`/`deleteAttachments`; no high-level typed wrapper yet | Generic payload supported in client, CLI not yet exposed |
| Calendar integrations | Public web bundle exposes site/calendar paths, not confirmed task-app v2 endpoints | Not wrapped |
| Reminder writes | v2 batch task fields exist, but reliability unverified/negative community evidence | Keep v1 verified path for production reminders |

## Remaining v2-first work

1. **Auth hardening**
   - Validate Dida365 China headless login selectors.
   - Add local cookie cache with expiry checks.
   - Avoid chat-pasted cookies entirely.

2. **Safer high-level task builders**
   - Add validated payload builders for dates, reminders, repeat rules, and checklist items.
   - Keep reminders on v1 until a v2 live sandbox proves reliable behavior.

3. **Write verification**
   - Dedicated verified commands now cover task moves, parent set/unset, and project folder assignment.
   - Next: make selected `--apply` commands opt into these verified paths by default once auth/cookie cache is reliable.
   - Keep detecting `id2error` and non-empty error maps for every batch write.

4. **Coverage expansion after endpoint verification**
   - Attachments high-level helpers if `batch/task` attachment fields are live-verified.
   - Comments only if v2 endpoints are confirmed.
   - Calendar/timezone/settings writes only after live endpoint verification.
   - Any UI-only feature must be proven against v2 before adding a write wrapper.

5. **Migration away from v1**
   - Keep v1 as fallback until v2 auth and write verification are reliable.
   - Prefer v2 reads now.
   - Move routine Hermes workflows to v2 one workflow at a time with regression tests.
