# dida-v2-client

Small, conservative Dida365-first private v2 client.

## Design

- Dida365 / 中国版 is the default profile.
- TickTick international compatibility is a profile switch; it is mostly the same API shape with different domains.
- We are moving toward **v2-first** coverage, while keeping write operations safe by default.
- Prefer official v1 / `dida` CLI only as a fallback while the v2 client is still gaining typed wrappers and live verification.
- Authentication resolves in session-first order: explicitly supplied token, optional OS credential-vault session, profile-specific local session env, direct local web sign-on, then Selenium fallback. All accepted profile aliases are canonicalized before selecting keyring entries, environment variables, credentials, or device ids, so Dida and TickTick auth material cannot cross profiles. Direct sign-on uses a stable live-verified 24-hex `X-Device` id by default; override with the canonical profile's device-id environment variable only if needed.
- CLI write operations default to dry-run; pass `--apply` to write.
- Safe reads (`GET`/`HEAD`) use bounded retry/backoff for transient network failures, HTTP 429, and selected 5xx responses. Write methods are never retried automatically.

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

For a checkout with `uv.lock`, use `uv sync --locked` and `uv run --locked`.
Select optional extras on every sync/run that needs them: uv may remove unselected
extras, including `keyring`, when it synchronizes or rebuilds the environment.
Linux, Windows, and uv-managed Python remain supported; the following policy is
optional and specific to Macs that already have Homebrew Python installed.

### macOS: reuse Homebrew Python

Reuse the base interpreter, not its global site-packages: dependencies still live
in the project's isolated `.venv`. This does not remove the Python requirement
or install/upgrade Homebrew Python for you.

From the cloned project directory, pin Homebrew's stable entry (not a versioned
Cellar path). These two files are machine-local and ignored by Git:

```bash
PROJECT="$PWD"
uv python pin --project "$PROJECT" --no-managed-python --no-python-downloads /opt/homebrew/bin/python3
```

Create `uv.toml` in that directory with:

```toml
python-preference = "only-system"
python-downloads = "never"
```

Do not use `uv python pin --resolved`: `.python-version` should contain the
literal stable path `/opt/homebrew/bin/python3`. Do not commit either local file
or point this project at another application's internal Python/venv.

```bash
# Initial install (or resync after a user-approved Homebrew Python upgrade)
uv sync --project "$PROJECT" --locked --extra secure-store

# Canonical invocation, also from outside the project directory
uv run --project "$PROJECT" --locked --extra secure-store dida-v2 --help

# Development only; pytest need not remain installed for normal CLI use
uv run --project "$PROJECT" --locked --extra secure-store --extra dev pytest
```

Keep `--extra secure-store` on every normal Mac invocation so a future venv
rebuild also installs `keyring`. Add `--extra headless` only when you need the
optional Selenium fallback. For the CLI examples below, replace the abbreviated
`uv run dida-v2` prefix with
`uv run --project "$PROJECT" --locked --extra secure-store dida-v2`.

After Homebrew changes the interpreter behind its stable entry, the next native
uv command reselects it and rebuilds `.venv` when required. If the pinned entry
is missing or broken, the command fails rather than downloading another Python
or falling back to Apple/uv/another application's Python. This is not an
automatic `brew upgrade` service or a guarantee of compatibility with every
future Python release; run the tests after upgrading, and retain the lockfile.

Native path-pin integration tests use disposable projects, an isolated HOME,
null keyring, and blocked runtime networking. They require uv plus two existing,
different Python versions, supplied via `DIDA_TEST_UV_PYTHON` and
`DIDA_TEST_UV_ALTERNATE_PYTHON`; otherwise only those integration tests skip.
CI supplies both interpreters and runs them on Python 3.9 and the latest stable
3.x, including venv creation/rebuilding, temporary entry retargeting, missing
pins, project-external invocation, secure-store retention, and external-venv
symlink/target preservation across version rebuilds. No test removes a real
interpreter or accesses a real account.

### Cloud-synced checkouts: keep the venv outside syncing folders

On affected macOS/iCloud filesystems (such as synced Documents folders), newly
created `.pth` files can acquire hidden flags. CPython 3.14 deliberately ignores
hidden `.pth` files, which can prevent an editable install from finding this
project's source. The real CLI can then fail with `ModuleNotFoundError` even
while pytest passes, because pytest adds `src` to its import path. This is local
filesystem behavior, not a runtime-source bug; do not disable Python's security
check or repeatedly clear file flags. See [uv#9902](https://github.com/astral-sh/uv/issues/9902)
and [CPython#148121](https://github.com/python/cpython/issues/148121).

Prefer keeping the checkout outside iCloud/cloud-sync folders. If the code must
stay there, keep the ordinary project `.venv` entry as a symlink to a
project-specific environment in a non-synced user-data directory. Use a unique
`ENV_DIR` for each checkout and verify that its location is not synced.

For a fresh setup, select Python first (including the local Homebrew pin/config
above if used), then run this from the checkout. The guard also detects broken
links: if either path already exists, stop and preserve the existing venv/link
before proceeding; do not overwrite or delete it blindly.

```bash
PROJECT="$PWD"
ENV_DIR="$HOME/.local/share/dida-v2-client/venvs/my-checkout"
if [ -e "$PROJECT/.venv" ] || [ -L "$PROJECT/.venv" ] ||
   [ -e "$ENV_DIR" ] || [ -L "$ENV_DIR" ]; then
    printf '%s\n' 'Preserve the existing .venv/link or ENV_DIR before proceeding.' >&2
else
    mkdir -p "$(dirname "$ENV_DIR")" &&
        UV_PROJECT_ENVIRONMENT="$ENV_DIR" uv sync --project "$PROJECT" --locked --extra secure-store &&
        ln -s "$ENV_DIR" "$PROJECT/.venv"
fi
```

`UV_PROJECT_ENVIRONMENT` is only for that initial sync; do not export it for
normal runs. Native uv follows the project's `.venv` link, so the canonical
invocation is unchanged, with no extra daily flags:

```bash
uv run --project "$PROJECT" --locked --extra secure-store dida-v2 --help
```

Native integration tests verify the link and target survive interpreter-version
rebuilds while core imports, `keyring`, and CLI help keep working. This covers the
tested native uv behavior, not every cloud provider or future uv release. No
runner, service, Cron job, shared application runtime, or extra Python install
is needed for this layout.

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
uv run dida-v2 --no-headless verified update <task_id> --project-id <project_id> --priority 5 --tag focus  # dry-run
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

Implemented through v0.3.0:

- config profiles: `dida` and `ticktick`; CLI/API share aliases `dida365`/`cn`/`china` and `global`/`intl`/`international`
- v2 transport with cookie auth; bounded exponential backoff with jitter for `GET`/`HEAD` only, `Retry-After` support capped at 30 seconds, retryable HTTP statuses limited to 429/500/502/503/504, and secret-free malformed-response/network errors; writes are never automatically retried
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
- verified action layer: identity-bound, strict-acknowledgement, refreshed-snapshot verification for `verified_update_task()`, `verified_move_task()`, `verified_set_task_parent()`, `verified_unset_task_parent()`, and `verified_set_project_folder()`; generic verified task updates require a non-empty snapshot `etag` revision, merge the current full task, and support validated title/content/description, priority/status, offset-aware due/start datetimes, valid IANA timezone names, unique tags, column, and all-day fields. Invalid verified-update dry-runs fail locally before session resolution or client creation
- CLI dry-run/apply for write operations; read-only commands for history, trash, stats, sync-backed lists, and query views

Saved-filter evaluation currently supports nested boolean groups, strict Dida priority values (`0`, `1`, `3`, `5`), relative `dueDate` values (`today`, `tomorrow`, `yesterday`, `thisWeek`, `nextWeek`, `overdue`), and relative `startDate` values (`today`, `tomorrow`, `yesterday`, `thisWeek`, `nextWeek`). The complete AST, root-only metadata placement, and node-specific keys are validated before explanation or task matching—even for an empty task collection—so mixed node shapes, metadata hidden in child nodes, unknown conditions, empty groups/value lists, malformed priorities, and unknown relative-date keywords fail closed. The CLI resolves the account/profile timezone before attaching a zone to naive `--now` values and converts normal filter/date/timezone validation errors into concise `ERROR:` output with exit code 2. Richer saved-filter condition names and filter CRUD remain unsupported until source or disposable-account evidence proves their exact semantics/endpoints.

Python 3.9 is exercised with functional compact-offset (`+0000`/`+0800`) and saved-filter tests, not only an import smoke test.

See `docs/v2-capability-matrix.md` for migration status and remaining v2-first work.

## Next likely additions

- cascade-safe move helpers for parent tasks and their children
- live sandbox tests using a disposable project/list
- high-level attachment helpers after disposable-account endpoint verification
