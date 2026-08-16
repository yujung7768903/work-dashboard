# Work Dashboard

**English** · [한국어](docs/ko-KR/README.md) · [日本語](docs/ja-JP/README.md) · [中文](docs/zh-CN/README.md)

A local work tracker for people who pair with Claude Code. You drive it from the
browser, Claude drives it from the CLI, and both read and write the same SQLite
file. No frameworks, no bundler, no `pip install`.

Work is organised in three layers — **Category → Workspace → Todo**. On top of
that, every Claude Code session is registered, classified into a workspace and
linked to the todo it is actually working on, so the board always shows what is
running and the next session knows where things stand.

> [!NOTE]
> Single user, no authentication, no external services. Everything lives in one
> SQLite file on your machine.

## Features

- **Three-layer board** — categories group workspaces, workspaces hold todos.
  Priority is expressed by order alone, and everything is drag-reorderable.
- **Live session tracking** — hooks register each Claude Code session, inject its
  workspace context, and keep the board in sync while you work.
- **Worktree lifecycle** — see each git worktree's state and commits, and start,
  restart or stop its dev server straight from the board.
- **One-command merge** — status check → pull the target branch in → run tests →
  merge → release the todo, the server and the branch, in that order.
- **Autonomous runs** — hand a labelled todo to a background `claude` job on a
  five-minute cron. Off by default.
- **Google Tasks sync** — two-way sync with Google Tasks, so the board is on your
  phone. Off per category until you turn each one on.
- **Usage view** — rate-limit windows and daily token and cost trends, read from
  local Claude Code logs.
- **Status line** — the current todo, worktree and server port, rendered into the
  Claude Code status line.
- **Four UI languages** — English (default), Korean, Japanese and Chinese from
  the globe icon. Messages the server produces follow the choice too.
- **Light and dark** — system, light or dark from the sun-and-moon icon, kept
  per browser rather than per account.

## Requirements

| | |
| --- | --- |
| Required | Python 3.9+ (standard library only), Git, a modern browser |
| Optional | Claude Code — for session tracking, status line and autonomous runs |
| Optional | `ssl` in that Python build — only for Google Tasks sync. Some 3.9 builds ship without it; the connection screen says so when `import ssl` fails |
| Optional | Node.js — some UI checks in the test suite run under `node` |
| Optional | `markdownlint-cli2` on `PATH` — used by the markdown lint hook |

## Quickstart

```bash
git clone https://github.com/yujung7768903/work-dashboard.git
cd work-dashboard
./start.sh
```

Then open `http://127.0.0.1:9080`. The database is created on first connect, so
there is no migration or setup step.

```bash
./start.sh --port 9081     # a different port, e.g. for a worktree
./start.sh --lan           # also reachable from your phone or tablet
./restart.sh               # restart the server started from this directory
./stop.sh                  # stop it
./stop.sh --port 9081      # stop only the one on that port
python3 server.py          # run in the foreground instead
```

`start.sh` passes its arguments through to `server.py` and prints the pid and log
path. Logs are one file per day (`logs/YYYY-MM-DD.log`); files untouched for more
than seven days are removed on the next start.

`stop.sh` and `restart.sh` only act on servers whose working directory is this
one, so worktree servers and the main checkout never stop each other. Add
`--port` when a single directory is running more than one.

`--lan` is the only flag `start.sh` reads itself. It binds to `0.0.0.0` and
prints the address other devices can actually open — `http://192.168.x.x:9080`
rather than the `0.0.0.0` that `server.py` echoes back.

> [!WARNING]
> With `--lan`, anything on the same network can open the dashboard, and there is
> no authentication.

Port 9080 belongs to the main checkout so that it always has the same address.
Worktrees run from 9081 up, and `server.py` refuses `--port 9080` when it is
started inside a worktree.

## The web UI

| Tab | What it holds |
| --- | --- |
| Board | The whole tree, the next todo, running sessions (polled every 2s) and the autonomous-run switch |
| Workspaces | Creating a workspace and editing its background, purpose, goal and considerations |
| Settings | The Google Tasks connection, then categories and labels |
| Usage | Rate-limit windows and the token and cost trend |

The board has two sub-tabs: **Todos** and **Worktrees**. On the worktree
sub-tab, the kebab menu (⋮) on each row applies (merges) or deletes the
worktree, and starts, restarts or stops its server. That sub-tab groups
worktrees by workspace or by project; the project view also lists worktrees no
workspace claims. Both sub-tabs lay their cards out in one or two columns, and
the left rail collapses to icons.

Clicking a todo row or a session row opens the same dialog with three tabs:

| Dialog tab | What it holds |
| --- | --- |
| Overview | Title, history, preconditions and the full context note |
| Session | Session id, location, the last 10 exchanges, and workspace/category assignment |
| Worktree | The worktrees this todo used — state, history and commits |

## The CLI

`dash.py` is what Claude Code uses. Every command works on the same database as
the web UI, so a change on one side shows up on the other after a refresh.

### Board

```bash
python3 dash.py ls                                   # the whole tree
python3 dash.py next                                 # the single next todo
python3 dash.py show <workspace-id|JIRA-1>           # workspace detail
python3 dash.py add-category <name>
python3 dash.py add-workspace <category> <name> [--background ...] [--jira KEY]
python3 dash.py add-todo <title> [--workspace ID] [--note ...] [--precondition ...]
python3 dash.py move-todo <todo-id> --workspace <id|none>
python3 dash.py set-status <todo|workspace> <id> <status>
python3 dash.py reorder <categories|workspaces|todos> <ids...>
python3 dash.py done-today [--date YYYY-MM-DD]
```

### Sessions

```bash
python3 dash.py sessions                             # running sessions
python3 dash.py classify --category <name> [--workspace <id>]
python3 dash.py link-todo <todo-id> [--status done] [--past]
python3 dash.py show-todo --session
python3 dash.py show-note <todo-id>                  # the full context note
```

`link-todo` declares that the session has started that todo and moves it to
`doing`. Link only what is actually being worked on — `merge` closes every todo
linked to the session, so a follow-up todo created for later stays unlinked
until the session that picks it up links it. `--past` links a finished history
session and leaves the status alone.

Session arguments may be omitted: the CLI falls back to `CLAUDE_CODE_SESSION_ID`,
which Claude Code sets for every process a session spawns.

### Worktrees and merging

```bash
python3 dash.py merge                        # check → pull target in → test → merge → release
python3 dash.py merge --message "title"      # merge commit title
python3 dash.py merge --test "npm test"      # a repository without tests/__main__.py
python3 dash.py merge --no-test
python3 dash.py finish [--worktree PATH]     # release only: todo done + server stopped
python3 dash.py statusline <session> [--cwd PATH]
```

`merge` runs the test suite exactly once, after the target branch has been pulled
into the worktree, so what is tested is what is merged. If it stops on a
conflict, resolve the files, `git add` them and run the same command again to
continue. It does not push, and it does not remove the worktree — `ExitWorktree`
does that.

### Google Tasks

Google allows one level of nesting, which is exactly the shape of the board:

```text
Google list          =  category
 └ top-level task    =  workspace
    └ subtask        =  a todo in that workspace
```

List names are category names verbatim. A prefix would leave the lists you made
on your phone unmatched forever, and you would end up with two of each.

Connect from the Settings tab: it walks through creating a Google Cloud project
with the Tasks API and a desktop OAuth client, stores the two values in
`~/.claude/work-dashboard/gtasks.json` (mode 600) and opens the consent screen.
The same thing from the CLI:

```bash
GTASKS_CLIENT_ID=<ID> GTASKS_CLIENT_SECRET=<SECRET> python3 dash.py gtasks-auth
python3 dash.py gtasks-sync --dry-run   # what would change; writes nothing
python3 dash.py gtasks-sync
```

Matching lists and exchanging todos are separate decisions. **Match categories**
reads both sides and lists the candidates with their counts — a `Study` with two
todos here and a `Study` with 61 on the phone are not the same thing, and
merging them cannot be undone. Only what you pick is created and linked, and
every category then starts **off**.

Titles and completion travel both ways, the newer edit wins and a tie goes to
the local side. Notes, preconditions and the workspace fields are pushed up
only. What you delete here is deleted there; what you delete on the phone is
deleted here unless it was already completed. A delete also needs proof that the
task was seen on the previous run (`meta.gtasks_seen_ids`) — without it,
switching Google accounts would make every link look stale at once.

There is no webhook, so nothing runs periodically unless you schedule it. The
settings screen reads `crontab -l` and `launchd` instead of printing an interval
it cannot vouch for.

```bash
# every 10 minutes, from crontab -e
*/10 * * * * cd ~/work/work-dashboard && /usr/bin/python3 dash.py gtasks-sync >> /tmp/gtasks.log 2>&1
```

A failure never switches the sync off — one dropped wifi should not stop it for
days without anyone noticing. The reason from the last run is shown next to the
title instead.

### Setup, language and autonomous runs

```bash
python3 dash.py onboard [--skip]             # is first-time setup still needed?
python3 dash.py scan-history --days 7        # one line per past session
python3 dash.py language [en|ko|ja|zh]       # no argument prints the current value
python3 dash.py usage                        # rate-limit usage and token trend
python3 dash.py autorun on|off|status
python3 dash.py autorun-tick [--dry-run]     # the five-minute cron entry point
python3 dash.py autorun-prompt <todo-id>     # the exact prompt an autonomous session gets
python3 dash.py autorun-request "<reason>"   # pause and ask a human to decide
python3 dash.py autorun-finish               # done, move to review
```

## Claude Code integration

### Session context

Hooks inject exactly one `<work-dashboard state="...">` block per session. Which
one depends on the state of the board.

| State | When | What is injected |
| --- | --- | --- |
| `classified` | The session has a workspace, matched by the branch's Jira ID or set with `classify --workspace` | Background, purpose, goal, considerations, the todo list, and scope rules |
| `onboarding` | No workspaces exist yet and the user has not declined | The first-time setup procedure |
| `unclassified` | Anything else | Location, branch, categories, active workspaces, and how to classify |
| `released` | Every todo this session claimed is `done` | Take new requests as a new todo, not on top of a finished one |

Classification itself is not automatic — a shell cannot tell what a question is
about. The hook injects the instruction, and Claude registers it with `classify`
and `link-todo`.

### Hooks

Every hook exits 0 silently on any failure. A dashboard problem must never stop a
session from opening or a file from being edited. `exit 2` is only used where
blocking is the point.

| Hook | Event | What it does |
| --- | --- | --- |
| `hooks/dash_hook.py` | `SessionStart`, `UserPromptSubmit`, `Stop`, `SessionEnd` | Registers sessions, tracks their state, and injects the context block above |
| `hooks/worktree_serve.py` | `Stop` | If you changed a worktree but nothing is serving it, blocks and hands over a free port (9081–9139) |
| `hooks/worktree_guard.py` | `PreToolUse` (`Write`, `Edit`, `NotebookEdit`) | Blocks source edits in the main checkout under `~/work/`. `ALLOW_MAIN_CHECKOUT=1` bypasses |
| `hooks/commit_scope_guard.py` | `PreToolUse` (`Bash`) | Blocks pathspec-less `git add -A` and `git commit -a`. `ALLOW_BROAD_COMMIT=1` bypasses |
| `hooks/md_lint.py` | `PostToolUse` (`Write`, `Edit`, `NotebookEdit`) | Lints saved `.md` files in this repository with `markdownlint-cli2` |
| `hooks/stale_base.py` | `UserPromptSubmit` | Warns once per session when the branch is behind its upstream or base branch |

`worktree_serve.py` is already registered in this repository's
`.claude/settings.json`, so a fresh clone needs no setup for it. Register the
other five in `~/.claude/settings.json` with an absolute path — pointing at the
main checkout, not a worktree, since worktrees are deleted after a merge.

```json
{
  "hooks": [
    {
      "type": "command",
      "command": "python3 /absolute/path/work-dashboard/hooks/dash_hook.py SessionStart",
      "timeout": 2
    }
  ]
}
```

`dash_hook.py` takes the event name as its only argument, so add it once per
event with the last argument changed.

### Status line

`~/.claude/statusline-command.js` calls `dash.py statusline <session> --cwd <path>`
and drops its output on the second line, under the usage bars.

```text
Context ████░░░░░░ 42% │ Usage ███░░░░░░░ 30% │ Weekly ██████░░░░ 55%
[doing | tab-underline | :9092] split todos and worktrees into board sub-tabs
```

The bracket is always **status | worktree | port**; missing parts drop out along
with their separator, and if all three are missing the bracket goes too.

### Autonomous runs

With `autorun on`, a five-minute cron picks one todo and runs it as a background
`claude` job. Only todos carrying the `auto` label are eligible — permission is
something a human grants, not something the code infers. It is off by default and
nothing turns it back on.

```cron
*/5 * * * * /usr/bin/python3 /absolute/path/work-dashboard/dash.py autorun-tick >/dev/null 2>&1
```

A tick that finds no eligible todo does nothing at all, which is why this is a
cron entry and not a daemon.

## Configuration

| What | Where |
| --- | --- |
| Database | `~/.claude/work-dashboard/dash.db`, overridden by `WORK_DASHBOARD_DB` |
| Google credentials | `~/.claude/work-dashboard/gtasks.json` (mode 600), or `GTASKS_CLIENT_ID` / `GTASKS_CLIENT_SECRET` |
| Host and port | `server.py --host` / `--port` (default `127.0.0.1:9080`) |
| UI language | The globe icon, or `dash.py language`. Stored as `meta.language` |
| Appearance | Brightness, board column count and rail state — stored per browser in `localStorage` |
| UI strings | `static/lang/{en,ko,ja,zh}.json`, keyed identically. English is the fallback |
| Design tokens | `:root` in `static/css/app.css` — the single source for spacing, type and radii |
| Markdown rules | `.markdownlint.json` |

## Data model

SQLite, opened directly by the web server, the CLI and the hooks — no process
mediates. `connect()` creates the schema, enables foreign keys and WAL, and seeds
the six default categories once. All `*_at` columns are ISO 8601 UTC text.

| Table | Role |
| --- | --- |
| `categories` | Top-level grouping. Does not affect priority |
| `workspaces` | A branch- or Jira-sized piece of work, with background, purpose, goal and considerations |
| `todos` | A todo. May belong to a workspace, or hang directly off a category |
| `labels`, `todo_labels` | Labels describe a todo's nature; a todo can carry several |
| `sessions` | Claude Code sessions, registered and updated by the hooks |
| `session_todos` | Which todo a session claimed. A session's workspace is derived from here |
| `worktrees` | Worktree history, kept after the directory is merged away or deleted |
| `usage_samples` | Rate-limit and token samples behind the usage view |
| `autorun_state`, `autorun_runs` | Autonomous-run settings and the log of runs |
| `gtasks_state` | Google Tasks sync — the master switch, the last sync and its error. Categories, workspaces and todos each carry the id of the Google list or task they are linked to |
| `meta` | Single-value settings and internal flags |

## Project structure

```text
work-dashboard/
├── dash.py               # CLI entry point — parses, delegates, prints
├── server.py             # HTTP entry point (http.server, no framework)
├── start.sh              # background start, dated logs, 7-day retention
├── stop.sh · restart.sh  # act only on this directory's server
├── serving.sh            # shared server discovery and shutdown functions
├── app/
│   ├── constants.py      # every magic number lives here
│   ├── db.py             # connection, schema, transactions
│   ├── repositories/     # per-entity storage and consistency rules
│   └── services/         # logic spanning several entities
├── hooks/                # Claude Code hooks
├── static/               # ES modules, no bundler
│   ├── index.html        # single page; carries data-i18n keys, never text
│   ├── lang/             # en · ko · ja · zh, identical key sets
│   ├── css/              # app.css defines the tokens, usage.css only uses them
│   └── js/               # boot, i18n, theme, layout, board, workspace, sessions, usage
├── tests/                # python3 -m tests
└── docs/superpowers/     # specs and plans
```

## Tests

```bash
python3 -m tests
```

The suite covers the repositories, services, CLI and hooks, checks that the four
language files agree on keys and placeholders, and enforces that CSS spacing and
type use design tokens rather than raw pixels. UI behaviour checks run under
`node` and are invoked by the Python test of the same name. The tests that
exercise `start.sh` and its siblings bring up real servers on ports 9900–9999, a
band the dashboard never displays.

## Design documents

`docs/superpowers/specs/` holds the design and confirmed decisions for each
stage; `docs/superpowers/plans/` holds the implementation plans.
