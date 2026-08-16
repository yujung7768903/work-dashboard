#!/usr/bin/env python3
"""영어 데모 한 벌을 만든다. 실 데이터는 읽지도 쓰지도 않는다.

만드는 것은 세 가지다 — 데모용 HOME(대시보드 DB·사용량 파일·트랜스크립트), 화면에
띄울 git 저장소와 워크트리, 그 둘을 물려 서버를 띄우는 serve.sh.

화면 문구는 이미 언어 사전에서 나오므로 여기서 영어로 채우는 것은 데이터뿐이다.
"""
import argparse
import json
import os
import random
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from app.constants import AUTORUN_LABEL, WEEK_SECONDS  # noqa: E402
from app.db import connect, palette_color  # noqa: E402

DEFAULT_ROOT = os.path.expanduser("~/work/work-dashboard-demo")
DEFAULT_PORT = 9081
ACCOUNT_UUID = "9f1c2e40-demo-4a71-9b30-6d2f5c8ae411"
ACCOUNT_PLAN = "Max 20x"
ACCOUNT_TIER = "default_claude_max_20x"
SEED = 20260816

CATEGORIES = ("Development", "Ops", "Incident", "Dev environment", "Skills", "Process")
LABELS = (("auto", "#2aa77a"), ("bug", "#e0574a"), ("research", "#2d8bdf"), ("quick", "#8a9a2d"))

# 저장소마다 master 커밋과 워크트리(브랜치 + 앞선 커밋 수)
REPOS = {
    "billing-api": {
        "commits": [
            "feat: meter usage events per workspace",
            "refactor: split the invoice builder out of the API layer",
            "fix: stop double-counting seats on plan downgrade",
            "test: cover the nightly usage rollup",
            "chore: pin the stripe client to 11.x",
        ],
        "worktrees": [
            ("invoice-preview", ["feat: preview invoices with per-seat proration",
                                 "test: proration on mid-cycle seat changes"]),
            ("stripe-retries", ["fix: retry stripe webhooks with backoff"]),
        ],
    },
    "mobile-app": {
        "commits": [
            "feat: push notification permission flow",
            "fix: keep the activity feed scrolled on refresh",
            "chore: bump the release build number",
        ],
        "worktrees": [
            ("offline-cache", ["feat: cache the activity feed for offline reads",
                               "perf: drop the cold-start feed request",
                               "fix: flicker while the cache warms up"]),
        ],
    },
    "infra": {
        "commits": [
            "feat: terraform module for the pg16 cluster",
            "chore: move pgbouncer settings into the module",
        ],
        "worktrees": [
            ("replica-cutover", ["feat: cutover script with a five-minute window",
                                 "docs: rollback steps for the cutover"]),
        ],
    },
}

WORKSPACES = (
    {
        "name": "Usage-based billing",
        "category": "Development",
        "jira_id": "BILL-214",
        "background": "Flat pricing caps revenue on the heaviest accounts, and support"
                      " hand-writes an invoice every time a team changes seats mid-cycle.",
        "purpose": "Charge teams for what they actually use, without anyone editing a"
                   " spreadsheet.",
        "goal": "Metered billing running in production behind a feature flag, with one"
                " month of shadow invoices matching the hand-written ones.",
        "considerations": "The Stripe migration has to be reversible, and no account may"
                          " ever be billed twice during the switch.",
        "repo": "billing-api",
        "todos": (
            ("done", "Model metered events in the billing schema", None, (), None),
            ("done", "Backfill six months of usage into the events table", None, (), None),
            ("doing", "Preview invoices with per-seat proration",
             "Proration rounds to the cent per seat-day. The finance team wants the"
             " rounding rule visible in the preview response, not just in the invoice.",
             (AUTORUN_LABEL,), None),
            ("todo", "Retry Stripe webhooks with backoff", None, ("bug",), None),
            ("todo", "Switch the pricing page to the new tiers", None, (),
             "The invoice preview ships behind the flag first"),
            ("todo", "Dry-run billing against last month's usage", None, (AUTORUN_LABEL,), None),
        ),
    },
    {
        "name": "Mobile app launch",
        "category": "Development",
        "jira_id": "MOB-77",
        "background": "The web app is the only way in, and half of new signups open it on"
                      " a phone.",
        "purpose": "Ship a mobile client people can actually keep on their home screen.",
        "goal": "iOS and Android builds live in both stores with a crash-free rate above"
                " 99.5%.",
        "considerations": "Store review adds a week — anything that needs a rebuild has to"
                          " land before the submission date.",
        "repo": "mobile-app",
        "todos": (
            ("done", "Push notification permission flow", None, (), None),
            ("doing", "Cache the activity feed for offline reads",
             "The feed flickers while the cache warms up. Reuse the last payload until the"
             " fresh one arrives instead of clearing the list.", (), None),
            ("todo", "Store screenshots for both platforms", None, ("quick",), None),
            ("todo", "Hold submission until crash-free rate clears 99.5%", None, (),
             "Crash-free rate over 99.5% for seven days\nCheck: the release dashboard"),
        ),
    },
    {
        "name": "Postgres 16 upgrade",
        "category": "Ops",
        "jira_id": "OPS-31",
        "background": "The primary still runs 13, which goes out of support this year, and"
                      " the query planner already struggles with the usage tables.",
        "purpose": "Get off an unsupported database before it becomes an incident.",
        "goal": "Production on Postgres 16 with under five minutes of write downtime and a"
                " rehearsed rollback.",
        "considerations": "The cutover window is a weekday evening — a rollback that takes"
                          " longer than the upgrade is not a rollback.",
        "repo": "infra",
        "todos": (
            ("done", "Benchmark pgbouncer against the new planner", None, (), None),
            ("doing", "Cutover script with a five-minute window", None, (), None),
            ("todo", "Rollback drill on the staging cluster", None, (), None),
            ("todo", "Retire the pg13 read replica", None, (),
             "The cutover has run in production"),
        ),
    },
    {
        "name": "Signup funnel rewrite",
        "category": "Process",
        "jira_id": None,
        "background": "Two thirds of trials never invite a second person, and the funnel"
                      " has not been touched since launch.",
        "purpose": "Find out where trials stall before rewriting anything else.",
        "goal": "A funnel where the first invite happens in the first session, backed by"
                " five churned-trial interviews.",
        "considerations": "Copy changes are cheap; asking for fewer fields is not — the"
                          " sales team uses company size for routing.",
        "repo": None,
        "todos": (
            ("done", "Drop the company-size question from signup", None, (), None),
            ("doing", "Rewrite the empty-state copy", None, (), None),
            ("todo", "Interview five churned trial accounts", None, ("research",), None),
        ),
    },
    {
        "name": "One-command dev setup",
        "category": "Dev environment",
        "jira_id": None,
        "background": "New engineers lose their first day to a README checklist that is"
                      " wrong in three places.",
        "purpose": "Make a working machine the default, not an achievement.",
        "goal": "One command takes a clean laptop to a running app with seeded data.",
        "considerations": "It has to work on both Apple silicon and the Linux boxes.",
        "repo": None,
        "todos": (
            ("done", "Seed script for a local database", None, (), None),
            ("todo", "Replace the env checklist with a doctor command", None,
             (AUTORUN_LABEL,), None),
        ),
    },
)

# 워크스페이스 없이 카테고리에만 붙는 할일 — 보드의 Unassigned 카드
LOOSE_TODOS = (
    ("Process", "todo", "Answer the Northwind security questionnaire", ("quick",)),
    ("Ops", "todo", "Update the on-call handover doc", ()),
    ("Incident", "done", "Write up the checkout timeout postmortem", ()),
)

# (세션 id, 상태, 저장소, 워크트리 이름 또는 None, 지시, 붙일 할일 제목, 시작 전 분, 마지막 활동 전 분)
SESSIONS = (
    ("3f8c1a2e-7b41-4d90-8c55-1e2a9f6b0d34", "working", "billing-api", "invoice-preview",
     "Add per-seat proration to the invoice preview endpoint",
     "Preview invoices with per-seat proration", 128, 0),
    ("a71d5c93-2e08-4f6b-9a12-5c7e3d8b1f60", "working", "infra", "replica-cutover",
     "Write the replica cutover script and print the downtime window",
     "Cutover script with a five-minute window", 54, 1),
    ("c2b90e17-4d63-4a28-b7f1-903e5a6c8d22", "idle", "mobile-app", "offline-cache",
     "Why does the activity feed flicker while the cache warms up?",
     "Cache the activity feed for offline reads", 310, 26),
    ("e58a4712-9c30-42db-8f6a-1b4d7e0c9355", "idle", "billing-api", None,
     "Explain how the nightly usage rollup handles late events", None, 95, 44),
    ("bd013f86-5a29-4c71-9e08-2f6b3d5a7c41", "ended", "mobile-app", None,
     "Ship the push notification permission flow",
     "Push notification permission flow", 1450, 190),
)

# 세션 팝업의 최근 대화
TRANSCRIPTS = {
    "3f8c1a2e-7b41-4d90-8c55-1e2a9f6b0d34": (
        ("user", "Add per-seat proration to the invoice preview endpoint"),
        ("assistant", "The preview builder charges a full seat for any partial cycle."
                      " I'll switch it to seat-days and keep the rounding rule in the"
                      " response so finance can check it."),
        ("user", "Round per seat, not on the total — that's what the spreadsheet does."),
        ("assistant", "Rounding per seat-day now. Two tests cover a mid-cycle upgrade and"
                      " a same-day add-and-remove."),
    ),
    "c2b90e17-4d63-4a28-b7f1-903e5a6c8d22": (
        ("user", "Why does the activity feed flicker while the cache warms up?"),
        ("assistant", "The list is cleared before the fresh payload arrives, so the empty"
                      " state renders for one frame. Keeping the last payload until the"
                      " new one resolves removes the flicker."),
    ),
    "e58a4712-9c30-42db-8f6a-1b4d7e0c9355": (
        ("user", "Explain how the nightly usage rollup handles late events"),
        ("assistant", "Events arriving after the rollup are folded into the next day's"
                      " run, which is why a late batch shows up one day off."),
    ),
}

TOKEN_MODELS = (
    ("claude-opus-5", 0.55),
    ("claude-sonnet-5", 0.35),
    ("claude-haiku-4-5-20251001", 0.10),
)
TREND_DAYS = 14
DAILY_TOKEN_RANGE = (4_000_000, 26_000_000)
COST_PER_MTOK = 2.4
SAMPLE_STEP_MIN = 10
FIVE_HOUR_SEC = 5 * 3600
PAST_WEEK_PEAKS = (54.0, 81.5, 96.2, 63.4, 88.1, 72.7)
SAMPLES_PER_PAST_WEEK = 6


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0)


def stamp(moment):
    return moment.isoformat(timespec="seconds")


def run_git(cwd, *args, env=None):
    subprocess.run(("git", *args), cwd=cwd, check=True, env=env,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def commit(path, message, when, filename):
    """파일 한 줄을 바꾸고 커밋. 작성·커밋 시각을 지정해 로그가 자연스럽게 보이게 한다"""
    target = os.path.join(path, filename)
    with open(target, "a", encoding="utf-8") as handle:
        handle.write(f"{message}\n")
    env = dict(os.environ, GIT_AUTHOR_DATE=stamp(when), GIT_COMMITTER_DATE=stamp(when),
               GIT_AUTHOR_NAME="Dana Reed", GIT_AUTHOR_EMAIL="dana@example.com",
               GIT_COMMITTER_NAME="Dana Reed", GIT_COMMITTER_EMAIL="dana@example.com")
    run_git(path, "add", "-A", env=env)
    run_git(path, "commit", "-m", message, env=env)


def build_repo(root, name, spec, now):
    """master 커밋과 워크트리까지 갖춘 저장소 하나"""
    path = os.path.join(root, "repos", name)
    os.makedirs(path)
    run_git(path, "-c", "init.defaultBranch=master", "init")
    run_git(path, "config", "user.name", "Dana Reed")
    run_git(path, "config", "user.email", "dana@example.com")
    with open(os.path.join(path, "README.md"), "w", encoding="utf-8") as handle:
        handle.write(f"# {name}\n\n")
    for index, message in enumerate(spec["commits"]):
        commit(path, message, now - timedelta(days=len(spec["commits"]) - index, hours=3),
               "CHANGELOG.md")
    for order, (branch_name, messages) in enumerate(spec["worktrees"], start=1):
        worktree = os.path.join(path, ".claude", "worktrees", branch_name)
        run_git(path, "worktree", "add", "-b", f"worktree-{branch_name}", worktree, "master")
        for index, message in enumerate(messages):
            commit(worktree, message,
                   now - timedelta(hours=order * 7 + len(messages) - index), "CHANGELOG.md")
    return path


def build_repos(root, now):
    return {name: build_repo(root, name, spec, now) for name, spec in REPOS.items()}


def session_cwd(repos, repo, worktree):
    if not repo:
        return None
    if not worktree:
        return repos[repo]
    return os.path.join(repos[repo], ".claude", "worktrees", worktree)


def write_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def build_usage_files(home, now):
    """한도 사이드카·계정 설정·비용 로그. 사용량 탭이 읽는 파일 전부"""
    five_reset = int(now.timestamp()) + 2 * 3600 + 20 * 60
    seven_reset = int(now.timestamp()) + 3 * 86400 + 5 * 3600
    write_json(os.path.join(home, ".claude/token-optimizer/rate-limits.json"), {
        "timestamp": int(now.timestamp() * 1000),
        "five_hour": {"used_percentage": 47.3, "resets_at": five_reset},
        "seven_day": {"used_percentage": 68.9, "resets_at": seven_reset},
    })
    write_json(os.path.join(home, ".claude.json"), {
        "cachedUsageUtilization": {
            "accountUuid": ACCOUNT_UUID,
            "utilization": {
                "five_hour": {"resets_at": stamp(datetime.fromtimestamp(five_reset, timezone.utc))},
                "seven_day": {"resets_at": stamp(datetime.fromtimestamp(seven_reset, timezone.utc))},
            },
        },
        "oauthAccount": {"accountUuid": ACCOUNT_UUID, "userRateLimitTier": ACCOUNT_TIER},
    })
    build_cost_log(os.path.join(home, ".claude/metrics/costs.jsonl"), now)
    return five_reset, seven_reset


def build_cost_log(path, now):
    """일별 토큰. 로그는 (세션, 모델)별 누적치라 하루에 세션 하나를 쓴다"""
    rng = random.Random(SEED)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = []
    for offset in range(TREND_DAYS):
        day = now - timedelta(days=TREND_DAYS - 1 - offset)
        weekend = day.weekday() >= 5
        total = rng.randint(*DAILY_TOKEN_RANGE) // (4 if weekend else 1)
        for model, share in TOKEN_MODELS:
            tokens = int(total * share)
            lines.append(json.dumps({
                "timestamp": stamp(day.replace(hour=21, minute=rng.randint(0, 59))),
                "session_id": f"demo-{day.date()}",
                "model": model,
                "input_tokens": int(tokens * 0.04),
                "output_tokens": int(tokens * 0.06),
                "cache_write_tokens": int(tokens * 0.20),
                "cache_read_tokens": int(tokens * 0.70),
                "estimated_cost_usd": round(tokens / 1_000_000 * COST_PER_MTOK, 2),
            }))
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def build_transcripts(home, repos):
    """세션 팝업이 glob 으로 찾는 위치에 대화 몇 줄"""
    root = os.path.join(home, ".claude/projects/demo-billing-api")
    os.makedirs(root, exist_ok=True)
    for session in SESSIONS:
        claude_id, _, repo, worktree = session[0], session[1], session[2], session[3]
        turns = TRANSCRIPTS.get(claude_id)
        if not turns:
            continue
        cwd = session_cwd(repos, repo, worktree) or ""
        moment = utc_now() - timedelta(minutes=len(turns) * 3)
        lines = []
        for index, (role, text) in enumerate(turns):
            lines.append(json.dumps({
                "type": role,
                "cwd": cwd,
                "timestamp": stamp(moment + timedelta(minutes=index * 3)),
                "message": {"content": text},
            }))
        with open(os.path.join(root, f"{claude_id}.jsonl"), "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")


def seed_db(db_path, repos, now, resets):
    con = connect(db_path)
    con.execute("DELETE FROM categories")
    stamped = stamp(now)
    category_ids = {}
    for order, name in enumerate(CATEGORIES, start=1):
        cursor = con.execute(
            "INSERT INTO categories(name, sort_order, color, created_at) VALUES(?,?,?,?)",
            (name, order, palette_color(order), stamped))
        category_ids[name] = cursor.lastrowid
    label_ids = {}
    for order, (name, color) in enumerate(LABELS, start=1):
        cursor = con.execute(
            "INSERT INTO labels(name, sort_order, color, created_at) VALUES(?,?,?,?)",
            (name, order, color, stamped))
        label_ids[name] = cursor.lastrowid

    todo_ids = {}
    for order, workspace in enumerate(WORKSPACES, start=1):
        category_id = category_ids[workspace["category"]]
        cursor = con.execute(
            "INSERT INTO workspaces(category_id, name, background, purpose, goal,"
            " considerations, status, sort_order, jira_id, created_at, updated_at)"
            " VALUES(?,?,?,?,?,?,'active',?,?,?,?)",
            (category_id, workspace["name"], workspace["background"], workspace["purpose"],
             workspace["goal"], workspace["considerations"], order, workspace["jira_id"],
             stamp(now - timedelta(days=20 - order)), stamped))
        workspace_id = cursor.lastrowid
        for index, (status, title, note, labels, precondition) in enumerate(
                workspace["todos"], start=1):
            todo_ids[title] = add_todo(con, category_id, workspace_id, title, note, labels,
                                       precondition, status, index, now, label_ids)
    for order, (category, status, title, labels) in enumerate(LOOSE_TODOS, start=1):
        todo_ids[title] = add_todo(con, category_ids[category], None, title, None, labels,
                                   None, status, order, now, label_ids)

    seed_sessions(con, repos, category_ids, todo_ids, now)
    seed_worktree_history(con, repos, now)
    seed_usage_samples(con, now, resets)
    seed_autorun(con, todo_ids, now)
    con.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('language', 'en')")
    con.commit()
    con.close()


def add_todo(con, category_id, workspace_id, title, note, labels, precondition, status,
             order, now, label_ids):
    done = status == "done"
    created = now - timedelta(days=12 - order, hours=order)
    cursor = con.execute(
        "INSERT INTO todos(category_id, workspace_id, title, note, precondition, status,"
        " sort_order, completed_at, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (category_id, workspace_id, title, note, precondition, status, order,
         stamp(now - timedelta(days=order, hours=2)) if done else None,
         stamp(created), stamp(now - timedelta(hours=order))))
    todo_id = cursor.lastrowid
    for label in labels:
        con.execute("INSERT INTO todo_labels(todo_id, label_id) VALUES(?,?)",
                    (todo_id, label_ids[label]))
    return todo_id


def seed_sessions(con, repos, category_ids, todo_ids, now):
    workspace_category = {workspace["name"]: category_ids[workspace["category"]]
                          for workspace in WORKSPACES}
    todo_category = {}
    for workspace in WORKSPACES:
        for todo in workspace["todos"]:
            todo_category[todo[1]] = workspace_category[workspace["name"]]
    for claude_id, state, repo, worktree, prompt, todo_title, started, seen in SESSIONS:
        cwd = session_cwd(repos, repo, worktree)
        branch = f"worktree-{worktree}" if worktree else "master"
        ended = stamp(now - timedelta(minutes=seen)) if state == "ended" else None
        cursor = con.execute(
            "INSERT INTO sessions(claude_session_id, cwd, git_branch, category_id, state,"
            " last_prompt, started_at, last_seen_at, ended_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (claude_id, cwd, branch, todo_category.get(todo_title), state, prompt,
             stamp(now - timedelta(minutes=started)), stamp(now - timedelta(minutes=seen)),
             ended))
        if todo_title:
            con.execute(
                "INSERT INTO session_todos(session_id, todo_id, created_at) VALUES(?,?,?)",
                (cursor.lastrowid, todo_ids[todo_title],
                 stamp(now - timedelta(minutes=started))))


def seed_worktree_history(con, repos, now):
    """병합·삭제로 사라진 워크트리. 살아 있는 것은 git 이 알려주므로 적지 않는다"""
    gone = (
        ("billing-api", "seat-downgrade", 9, "b41c07d"),
        ("mobile-app", "feed-scroll", 5, "7ae2f19"),
    )
    for repo, name, days, merge_hash in gone:
        path = os.path.join(repos[repo], ".claude", "worktrees", name)
        merged = now - timedelta(days=days)
        con.execute(
            "INSERT INTO worktrees(path, repo, branch, created_at, merged_at, merge_hash,"
            " merge_from, deleted_at) VALUES(?,?,?,?,?,?,?,?)",
            (path, repos[repo], f"worktree-{name}", stamp(merged - timedelta(days=2)),
             stamp(merged), merge_hash, "master", stamp(merged + timedelta(minutes=4))))


def seed_usage_samples(con, now, resets):
    """최근 24시간 추이와 지난 주차 최고치. 사이드카에는 이력이 없어 여기서 채운다"""
    rng = random.Random(SEED)
    five_reset, seven_reset = resets
    rows = []
    steps = 24 * 60 // SAMPLE_STEP_MIN
    level, window = 0.0, None
    for index in range(steps):
        moment = now - timedelta(minutes=SAMPLE_STEP_MIN * (steps - 1 - index))
        seconds = int(moment.timestamp())
        # 5시간 창은 초기화될 때마다 0으로 떨어지고 그 안에서는 쓴 만큼 올라가기만 한다
        elapsed = (five_reset - seconds) // FIVE_HOUR_SEC
        if elapsed != window:
            level, window = 0.0, elapsed
        awake = 9 <= moment.astimezone().hour <= 23
        level = min(96.0, level + (rng.uniform(1.0, 8.0) if awake else rng.uniform(0.0, 0.3)))
        seven = 68.9 - (steps - 1 - index) * SAMPLE_STEP_MIN / 1440 * 9.5
        rows.append((seconds * 1000, round(level, 1), five_reset - FIVE_HOUR_SEC * elapsed,
                     round(max(seven, 0.0), 1), seven_reset))
    # 오른쪽 끝은 사이드카가 지금 담고 있는 값과 같아야 한다
    rows[-1] = (rows[-1][0], 47.3, rows[-1][2], 68.9, seven_reset)
    for week, peak in enumerate(PAST_WEEK_PEAKS, start=1):
        reset_at = seven_reset - WEEK_SECONDS * week
        for index in range(SAMPLES_PER_PAST_WEEK):
            moment_ms = (reset_at - 3600 * (index + 1) * 6) * 1000
            share = (SAMPLES_PER_PAST_WEEK - index) / SAMPLES_PER_PAST_WEEK
            rows.append((moment_ms, round(peak * share * 0.6, 1), reset_at,
                         round(peak * share, 1), reset_at))
    con.executemany(
        "INSERT OR IGNORE INTO usage_samples(source_ts, five_hour_pct, five_hour_resets_at,"
        " seven_day_pct, seven_day_resets_at, account_uuid, account_plan, created_at)"
        " VALUES(?,?,?,?,?,?,?,?)",
        [(*row, ACCOUNT_UUID, ACCOUNT_PLAN, stamp(now)) for row in rows])


def seed_autorun(con, todo_ids, now):
    con.execute(
        "INSERT OR REPLACE INTO autorun_state(id, enabled, blocked_streak, last_tick_at,"
        " last_tick_reason, updated_at) VALUES(1,1,0,?,?,?)",
        (stamp(now - timedelta(minutes=4)), "시작 가능", stamp(now)))
    runs = (
        ("Dry-run billing against last month's usage", 190, 140, "review", None),
        ("Replace the env checklist with a doctor command", 900, 815, "requested",
         "Two ways to check the toolchain — a doctor command or a make target."
         " Pick one before I write it."),
    )
    for title, started, ended, outcome, note in runs:
        con.execute(
            "INSERT INTO autorun_runs(todo_id, claude_session_id, job_id, started_at,"
            " ended_at, outcome, requested_note, finished_at) VALUES(?,?,?,?,?,?,?,?)",
            (todo_ids[title], None, None, stamp(now - timedelta(minutes=started)),
             stamp(now - timedelta(minutes=ended)), outcome, note,
             stamp(now - timedelta(minutes=ended))))


def write_launcher(root, home, port):
    path = os.path.join(root, "serve.sh")
    db_path = os.path.join(home, ".claude/work-dashboard/dash.db")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(
            "#!/usr/bin/env bash\n"
            "# 데모 대시보드. HOME 을 데모 쪽으로 돌려 실 데이터와 완전히 분리한다\n"
            "set -euo pipefail\n"
            f'export HOME="{home}"\n'
            f'export WORK_DASHBOARD_DB="{db_path}"\n'
            f'cd "{REPO_ROOT}"\n'
            f'exec python3 server.py --port {port} "$@"\n')
    os.chmod(path, 0o755)
    return path


def main():
    parser = argparse.ArgumentParser(description="영어 데모 대시보드 한 벌 만들기")
    parser.add_argument("--root", default=DEFAULT_ROOT, help="데모 파일을 둘 위치")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="데모 서버 포트")
    args = parser.parse_args()

    root = os.path.abspath(os.path.expanduser(args.root))
    home = os.path.join(root, "home")
    for path in (home, os.path.join(root, "repos")):
        if os.path.exists(path):
            print(f"지움 {path}")
            shutil.rmtree(path)
    os.makedirs(home)

    now = utc_now()
    repos = build_repos(root, now)
    resets = build_usage_files(home, now)
    build_transcripts(home, repos)
    seed_db(os.path.join(home, ".claude/work-dashboard/dash.db"), repos, now, resets)
    launcher = write_launcher(root, home, args.port)
    print(f"데모 준비됨 {root}")
    print(f"띄우기 {launcher}")
    print(f"주소 http://127.0.0.1:{args.port}/")


if __name__ == "__main__":
    main()
