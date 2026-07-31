import sqlite3
import unittest
from datetime import datetime, timedelta, timezone

from app.constants import (
    ENDED_RETENTION_DAYS,
    LAST_PROMPT_MAX_CHARS,
    SESSION_STATES,
    STALE_IDLE_HOURS,
    STATE_ENDED,
    STATE_IDLE,
    STATE_WORKING,
    STATUS_DOING,
    STATUS_DONE,
)
from app.errors import NotFound, Validation
from app.repositories import categories as category_repo
from app.repositories import sessions as session_repo
from app.repositories import todos as todo_repo
from app.repositories import workspaces as workspace_repo
from app.services import session_link
from tests.support import temp_db

SID = "sess-1"
MISSING_ID = 9999


def _ago(**kwargs):
    return (datetime.now(timezone.utc) - timedelta(**kwargs)).isoformat(timespec="seconds")


class SessionSchemaTest(unittest.TestCase):
    def test_creates_session_tables(self):
        con = temp_db()
        names = {
            row["name"]
            for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        self.assertTrue({"sessions", "session_todos"} <= names)

    def test_session_state_default_is_idle(self):
        con = temp_db()
        con.execute(
            "INSERT INTO sessions(claude_session_id, started_at, last_seen_at)"
            " VALUES(?,?,?)",
            ("abc", "2026-07-29T00:00:00+00:00", "2026-07-29T00:00:00+00:00"),
        )
        con.commit()
        self.assertEqual(
            con.execute("SELECT state FROM sessions").fetchone()["state"], STATE_IDLE
        )

    def test_claude_session_id_is_unique(self):
        con = temp_db()
        con.execute(
            "INSERT INTO sessions(claude_session_id, started_at, last_seen_at)"
            " VALUES(?,?,?)",
            ("dup", "t", "t"),
        )
        con.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            con.execute(
                "INSERT INTO sessions(claude_session_id, started_at, last_seen_at)"
                " VALUES(?,?,?)",
                ("dup", "t", "t"),
            )

    def test_states_are_three(self):
        self.assertEqual(SESSION_STATES, ("working", "idle", "ended"))


class SessionRepoTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()

    def test_register_creates_session(self):
        created = session_repo.register(self.con, SID, cwd="/tmp", git_branch="master")
        self.assertEqual(created["claude_session_id"], SID)
        self.assertEqual(created["state"], STATE_IDLE)
        self.assertEqual(created["cwd"], "/tmp")

    def test_register_twice_updates_and_keeps_classification(self):
        session_repo.register(self.con, SID, cwd="/a")
        self.con.execute(
            "UPDATE sessions SET category_id=1 WHERE claude_session_id=?", (SID,)
        )
        self.con.commit()
        again = session_repo.register(self.con, SID, cwd="/b")
        self.assertEqual(again["cwd"], "/b")
        self.assertEqual(again["category_id"], 1)

    def test_register_rejects_blank_id(self):
        with self.assertRaises(Validation):
            session_repo.register(self.con, "  ")

    def test_get_missing_raises_not_found(self):
        with self.assertRaises(NotFound):
            session_repo.get(self.con, "nope")

    def test_find_missing_returns_none(self):
        self.assertIsNone(session_repo.find(self.con, "nope"))

    def test_set_state_transitions(self):
        session_repo.register(self.con, SID)
        working = session_repo.set_state(self.con, SID, STATE_WORKING)
        self.assertEqual(working["state"], STATE_WORKING)
        ended = session_repo.set_state(self.con, SID, STATE_ENDED)
        self.assertIsNotNone(ended["ended_at"])

    def test_set_state_rejects_unknown(self):
        session_repo.register(self.con, SID)
        with self.assertRaises(Validation):
            session_repo.set_state(self.con, SID, "paused")

    def test_set_state_on_missing_session_is_ignored(self):
        self.assertIsNone(session_repo.set_state(self.con, "gone", STATE_WORKING))

    def test_last_prompt_is_truncated(self):
        session_repo.register(self.con, SID)
        updated = session_repo.set_last_prompt(self.con, SID, "가" * 500)
        self.assertEqual(len(updated["last_prompt"]), LAST_PROMPT_MAX_CHARS)

    def test_last_prompt_collapses_whitespace(self):
        session_repo.register(self.con, SID)
        updated = session_repo.set_last_prompt(self.con, SID, "여러\n줄   지시")
        self.assertEqual(updated["last_prompt"], "여러 줄 지시")

    def test_last_prompt_on_missing_session_is_ignored(self):
        self.assertIsNone(session_repo.set_last_prompt(self.con, "gone", "x"))


class SessionClassifyTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()
        self.dev = category_repo.get_by_name(self.con, "개발")["id"]
        self.ops = category_repo.get_by_name(self.con, "운영")["id"]
        self.workspace = workspace_repo.create(self.con, self.dev, "KT 동시성")
        session_repo.register(self.con, SID, cwd="/tmp")

    def test_classify_category_only(self):
        result = session_repo.classify(self.con, SID, category_name="운영")
        self.assertEqual(result["category_id"], self.ops)
        self.assertIsNone(result["workspace_id"])

    def test_classify_with_workspace_overrides_category(self):
        result = session_repo.classify(
            self.con, SID, category_name="운영", workspace_id=self.workspace["id"]
        )
        self.assertEqual(result["workspace_id"], self.workspace["id"])
        self.assertEqual(result["category_id"], self.dev)

    def test_classify_requires_something(self):
        with self.assertRaises(Validation):
            session_repo.classify(self.con, SID)

    def test_classify_rejects_unknown_category(self):
        with self.assertRaises(NotFound):
            session_repo.classify(self.con, SID, category_name="없는카테고리")

    def test_classify_rejects_unknown_workspace(self):
        with self.assertRaises(NotFound):
            session_repo.classify(self.con, SID, workspace_id=MISSING_ID)

    def test_classify_missing_session_raises(self):
        with self.assertRaises(NotFound):
            session_repo.classify(self.con, "gone", category_name="운영")

    def test_classify_by_ids_for_dashboard(self):
        row_id = session_repo.get(self.con, SID)["id"]
        result = session_repo.classify_by_ids(self.con, row_id, category_id=self.ops)
        self.assertEqual(result["category_id"], self.ops)

    def test_classify_by_ids_missing_session(self):
        with self.assertRaises(NotFound):
            session_repo.classify_by_ids(self.con, MISSING_ID, category_id=self.ops)

    def test_classify_by_ids_requires_something(self):
        row_id = session_repo.get(self.con, SID)["id"]
        with self.assertRaises(Validation):
            session_repo.classify_by_ids(self.con, row_id)

    def test_link_todo_ignores_duplicate(self):
        todo = todo_repo.create(self.con, "락", workspace_id=self.workspace["id"])
        session_repo.link_todo(self.con, SID, todo["id"])
        session_repo.link_todo(self.con, SID, todo["id"])
        self.assertEqual(session_repo.linked_todo_ids(self.con, SID), [todo["id"]])

    def test_link_todo_starts_the_todo(self):
        """연결 = 착수 선언"""
        todo = todo_repo.create(self.con, "락", workspace_id=self.workspace["id"])
        session_repo.link_todo(self.con, SID, todo["id"])
        self.assertEqual(todo_repo.get(self.con, todo["id"])["status"], STATUS_DOING)

    def test_link_todo_keeps_done_todo_done(self):
        todo = todo_repo.create(self.con, "락", workspace_id=self.workspace["id"])
        todo_repo.update(self.con, todo["id"], status=STATUS_DONE)
        session_repo.link_todo(self.con, SID, todo["id"])
        self.assertEqual(todo_repo.get(self.con, todo["id"])["status"], STATUS_DONE)

    def test_link_todo_rejects_missing_todo(self):
        with self.assertRaises(NotFound):
            session_repo.link_todo(self.con, SID, MISSING_ID)

    def test_count_unclassified(self):
        session_repo.register(self.con, "sess-2")
        session_repo.classify(self.con, SID, category_name="운영")
        self.assertEqual(session_repo.count_unclassified(self.con), 1)

    def test_list_active_carries_names(self):
        session_repo.classify(self.con, SID, workspace_id=self.workspace["id"])
        row = session_repo.list_active(self.con)[0]
        self.assertEqual(row["workspace_name"], "KT 동시성")
        self.assertEqual(row["category_name"], "개발")


class SessionSweepTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()
        self.dev = category_repo.get_by_name(self.con, "개발")["id"]
        self.workspace = workspace_repo.create(self.con, self.dev, "KT")

    def _age(self, session_id, last_seen=None, ended_at=None):
        self.con.execute(
            "UPDATE sessions SET last_seen_at=COALESCE(?, last_seen_at),"
            " ended_at=COALESCE(?, ended_at) WHERE claude_session_id=?",
            (last_seen, ended_at, session_id),
        )
        self.con.commit()

    def test_stale_idle_becomes_ended(self):
        session_repo.register(self.con, SID)
        self._age(SID, last_seen=_ago(hours=STALE_IDLE_HOURS + 1))
        session_repo.sweep(self.con)
        self.assertEqual(session_repo.get(self.con, SID)["state"], STATE_ENDED)

    def test_fresh_idle_survives_sweep(self):
        session_repo.register(self.con, SID)
        session_repo.sweep(self.con)
        self.assertEqual(session_repo.get(self.con, SID)["state"], STATE_IDLE)

    def test_ended_without_todo_is_deleted_after_retention(self):
        session_repo.register(self.con, SID)
        session_repo.set_state(self.con, SID, STATE_ENDED)
        self._age(SID, ended_at=_ago(days=ENDED_RETENTION_DAYS + 1))
        session_repo.sweep(self.con)
        self.assertIsNone(session_repo.find(self.con, SID))

    def test_ended_with_todo_survives(self):
        session_repo.register(self.con, SID)
        todo = todo_repo.create(self.con, "락", workspace_id=self.workspace["id"])
        session_repo.link_todo(self.con, SID, todo["id"])
        session_repo.set_state(self.con, SID, STATE_ENDED)
        self._age(SID, ended_at=_ago(days=ENDED_RETENTION_DAYS + 1))
        session_repo.sweep(self.con)
        self.assertIsNotNone(session_repo.find(self.con, SID))

    def test_list_active_excludes_ended(self):
        session_repo.register(self.con, SID)
        session_repo.set_state(self.con, SID, STATE_ENDED)
        self.assertEqual(session_repo.list_active(self.con), [])


class SessionLinkTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()
        self.dev = category_repo.get_by_name(self.con, "개발")["id"]
        self.workspace = workspace_repo.create(
            self.con, self.dev, "KT 동시성", background="엑셀 충돌",
            purpose="서버사이드 차단", goal="락 재설계", jira_id="KT-1530",
        )

    def test_jira_from_branch(self):
        self.assertEqual(session_link.jira_from_branch("KT-1530-phase1-lock"), "KT-1530")
        self.assertEqual(session_link.jira_from_branch("kt-1530"), "KT-1530")
        self.assertIsNone(session_link.jira_from_branch("master"))
        self.assertIsNone(session_link.jira_from_branch(None))

    def test_attach_by_branch_finds_workspace(self):
        session_repo.register(self.con, SID)
        attached = session_link.attach_by_branch(self.con, SID, "feature/KT-1530-lock")
        self.assertEqual(attached["workspace_id"], self.workspace["id"])

    def test_attach_by_branch_returns_none_without_match(self):
        session_repo.register(self.con, SID)
        self.assertIsNone(session_link.attach_by_branch(self.con, SID, "master"))

    def test_attach_by_branch_unknown_jira(self):
        session_repo.register(self.con, SID)
        self.assertIsNone(session_link.attach_by_branch(self.con, SID, "AB-1"))

    def test_classified_context_has_workspace_fields(self):
        session_repo.register(self.con, SID)
        session_link.attach_by_branch(self.con, SID, "KT-1530")
        text = session_link.render_context(self.con, SID)
        self.assertIn('state="classified"', text)
        self.assertIn("엑셀 충돌", text)
        self.assertIn("락 재설계", text)

    def test_unclassified_context_lists_catalog(self):
        session_repo.register(self.con, SID, cwd="/home/ujung/work")
        text = session_link.render_context(self.con, SID)
        self.assertIn('state="unclassified"', text)
        self.assertIn("개발", text)
        self.assertIn("KT 동시성", text)
        self.assertIn("/home/ujung/work", text)

    def test_context_for_missing_session_is_empty(self):
        self.assertEqual(session_link.render_context(self.con, "gone"), "")

    def test_active_payload_shape(self):
        session_repo.register(self.con, SID)
        payload = session_link.active_payload(self.con)
        self.assertEqual(payload["unclassified_count"], 1)
        self.assertEqual(len(payload["sessions"]), 1)


class ScopeGuardRenderTest(unittest.TestCase):
    def test_scope_block_has_background_goal_and_steps(self):
        con = temp_db()
        dev = category_repo.get_by_name(con, "개발")["id"]
        workspace = workspace_repo.create(
            con, dev, "KT 동시성", background="엑셀 충돌", purpose="차단",
            goal="락 재설계", jira_id="KT-1530",
        )
        todo_repo.create(con, "락 초안", workspace_id=workspace["id"])
        text = session_link.scope_guard_block(con, "kt-1530")
        self.assertIn('<scope-guard active="KT-1530"', text)
        self.assertIn("배경: 엑셀 충돌", text)
        self.assertIn("목표: 락 재설계", text)
        self.assertIn("1. [todo] 락 초안", text)

    def test_scope_block_missing_jira(self):
        con = temp_db()
        self.assertIn('missing="KT-9999"', session_link.scope_guard_block(con, "KT-9999"))
