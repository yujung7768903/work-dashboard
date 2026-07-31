import sqlite3
import unittest

from app import ordering
from app.constants import (
    CATEGORY_PALETTE,
    SEED_CATEGORIES,
    STATUS_DOING,
    STATUS_DONE,
    STATUS_TODO,
    WORKSPACE_ACTIVE,
)
from app.db import connect
from app.errors import Conflict, NotFound, Validation
from app.repositories import categories as category_repo
from app.repositories import subtasks as subtask_repo
from app.repositories import todos as todo_repo
from app.repositories import workspaces as workspace_repo
from tests.support import temp_db, temp_db_path

STALE_STAMP = "2000-01-01T00:00:00+00:00"
MISSING_ID = 9999


class SchemaTest(unittest.TestCase):
    def test_creates_four_tables(self):
        con = temp_db()
        names = {
            row["name"]
            for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        self.assertTrue({"categories", "workspaces", "todos", "subtasks"} <= names)

    def test_seeds_default_categories(self):
        con = temp_db()
        rows = con.execute("SELECT name FROM categories ORDER BY sort_order").fetchall()
        self.assertEqual([row["name"] for row in rows], list(SEED_CATEGORIES))

    def test_seed_runs_only_once(self):
        path = temp_db_path()
        con = temp_db(path)
        con.execute("DELETE FROM categories WHERE name=?", (SEED_CATEGORIES[0],))
        con.commit()
        reopened = connect(path)
        count = reopened.execute("SELECT COUNT(*) AS n FROM categories").fetchone()["n"]
        self.assertEqual(count, len(SEED_CATEGORIES) - 1)

    def test_wal_mode_enabled(self):
        con = temp_db()
        mode = con.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(mode.lower(), "wal")


class OrderingTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()
        self.con.execute("DELETE FROM categories")
        for order, name in enumerate(["a", "b", "c"], start=1):
            self.con.execute(
                "INSERT INTO categories(name, sort_order, created_at) VALUES(?,?,?)",
                (name, order, STALE_STAMP),
            )
        self.con.commit()

    def _orders(self):
        rows = self.con.execute(
            "SELECT name, sort_order FROM categories ORDER BY sort_order"
        ).fetchall()
        return [(row["name"], row["sort_order"]) for row in rows]

    def test_next_order_is_last_plus_one(self):
        self.assertEqual(ordering.next_order(self.con, "categories", "1=1", ()), 4)

    def test_next_order_on_empty_range_is_first(self):
        self.con.execute("DELETE FROM categories")
        self.con.commit()
        self.assertEqual(ordering.next_order(self.con, "categories", "1=1", ()), 1)

    def test_reorder_reassigns_one_to_n(self):
        ids = [
            row["id"]
            for row in self.con.execute("SELECT id FROM categories ORDER BY name DESC")
        ]
        ordering.reorder(self.con, "categories", ids, "1=1", ())
        self.assertEqual(self._orders(), [("c", 1), ("b", 2), ("a", 3)])

    def test_reorder_rejects_foreign_id(self):
        with self.assertRaises(Validation):
            ordering.reorder(self.con, "categories", [MISSING_ID], "1=1", ())

    def test_reorder_rejects_partial_id_set(self):
        one = self.con.execute("SELECT id FROM categories LIMIT 1").fetchone()["id"]
        with self.assertRaises(Validation):
            ordering.reorder(self.con, "categories", [one], "1=1", ())


class CategoryRepoTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()

    def test_create_appends_to_end(self):
        created = category_repo.create(self.con, "신규")
        self.assertEqual(created["name"], "신규")
        self.assertEqual(created["sort_order"], len(SEED_CATEGORIES) + 1)

    def test_create_rejects_duplicate_name(self):
        with self.assertRaises(Conflict):
            category_repo.create(self.con, SEED_CATEGORIES[0])

    def test_create_rejects_blank_name(self):
        with self.assertRaises(Validation):
            category_repo.create(self.con, "   ")

    def test_get_missing_raises_not_found(self):
        with self.assertRaises(NotFound):
            category_repo.get(self.con, MISSING_ID)

    def test_get_by_name_finds_seeded(self):
        self.assertEqual(category_repo.get_by_name(self.con, "개발")["name"], "개발")

    def test_rename_changes_name(self):
        target = category_repo.get_by_name(self.con, "운영")
        renamed = category_repo.rename(self.con, target["id"], "운영업무")
        self.assertEqual(renamed["name"], "운영업무")

    def test_rename_rejects_duplicate(self):
        target = category_repo.get_by_name(self.con, "운영")
        with self.assertRaises(Conflict):
            category_repo.rename(self.con, target["id"], "개발")

    def test_seeded_category_gets_palette_color(self):
        self.assertEqual(category_repo.get_by_name(self.con, "개발")["color"], CATEGORY_PALETTE[0])

    def test_created_category_gets_next_palette_color(self):
        created = category_repo.create(self.con, "신규")
        expected = CATEGORY_PALETTE[len(SEED_CATEGORIES) % len(CATEGORY_PALETTE)]
        self.assertEqual(created["color"], expected)

    def test_update_sets_color_without_touching_name(self):
        target = category_repo.get_by_name(self.con, "운영")
        updated = category_repo.update(self.con, target["id"], color="#AABBCC")
        self.assertEqual(updated["color"], "#aabbcc")
        self.assertEqual(updated["name"], "운영")

    def test_update_rejects_malformed_color(self):
        target = category_repo.get_by_name(self.con, "운영")
        with self.assertRaises(Validation):
            category_repo.update(self.con, target["id"], color="red")

    def test_update_without_fields_is_rejected(self):
        target = category_repo.get_by_name(self.con, "운영")
        with self.assertRaises(Validation):
            category_repo.update(self.con, target["id"])

    def test_style_columns_backfill_on_legacy_db(self):
        """색 컬럼이 없던 DB 를 열면 팔레트 색으로 채워짐"""
        path = temp_db_path()
        legacy = sqlite3.connect(path)
        legacy.executescript(
            "CREATE TABLE categories(id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " name TEXT NOT NULL UNIQUE, sort_order INTEGER NOT NULL,"
            " created_at TEXT NOT NULL);"
            "CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);"
            "INSERT INTO categories(name, sort_order, created_at)"
            " VALUES('개발', 1, '2026-01-01T00:00:00+00:00');"
            "INSERT INTO meta(key, value)"
            " VALUES('categories_seeded', '2026-01-01T00:00:00+00:00');"
        )
        legacy.commit()
        legacy.close()

        self.assertEqual(category_repo.get_by_name(temp_db(path), "개발")["color"], CATEGORY_PALETTE[0])


    def test_delete_empty_category_succeeds(self):
        target = category_repo.get_by_name(self.con, "운영")
        category_repo.delete(self.con, target["id"])
        with self.assertRaises(NotFound):
            category_repo.get(self.con, target["id"])

    def test_delete_rejects_non_empty_category(self):
        target = category_repo.get_by_name(self.con, "개발")
        self.con.execute(
            "INSERT INTO todos(category_id, title, status, sort_order, created_at, updated_at)"
            " VALUES(?,?,?,?,?,?)",
            (target["id"], "남은 할일", STATUS_TODO, 1, STALE_STAMP, STALE_STAMP),
        )
        self.con.commit()
        with self.assertRaises(Conflict):
            category_repo.delete(self.con, target["id"])


class WorkspaceRepoTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()
        self.dev = category_repo.get_by_name(self.con, "개발")["id"]

    def test_create_defaults_to_active(self):
        created = workspace_repo.create(self.con, self.dev, "KT 동시성")
        self.assertEqual(created["status"], WORKSPACE_ACTIVE)
        self.assertEqual(created["sort_order"], 1)

    def test_create_stores_four_context_fields(self):
        created = workspace_repo.create(
            self.con,
            self.dev,
            "KT 동시성",
            background="엑셀 동시 저장 충돌",
            purpose="서버사이드 차단",
            goal="락 재설계 완료",
            considerations="웹소켓 영향 확인",
        )
        self.assertEqual(created["background"], "엑셀 동시 저장 충돌")
        self.assertEqual(created["considerations"], "웹소켓 영향 확인")

    def test_create_rejects_missing_category(self):
        with self.assertRaises(NotFound):
            workspace_repo.create(self.con, MISSING_ID, "이름")

    def test_create_rejects_blank_name(self):
        with self.assertRaises(Validation):
            workspace_repo.create(self.con, self.dev, "  ")

    def test_sort_order_is_global_across_categories(self):
        ops = category_repo.get_by_name(self.con, "운영")["id"]
        first = workspace_repo.create(self.con, self.dev, "첫번째")
        second = workspace_repo.create(self.con, ops, "두번째")
        self.assertEqual([first["sort_order"], second["sort_order"]], [1, 2])

    def test_update_rejects_unknown_status(self):
        created = workspace_repo.create(self.con, self.dev, "KT")
        with self.assertRaises(Validation):
            workspace_repo.update(self.con, created["id"], status="종료됨")

    def test_update_rejects_unknown_field(self):
        created = workspace_repo.create(self.con, self.dev, "KT")
        with self.assertRaises(Validation):
            workspace_repo.update(self.con, created["id"], sort_order=5)

    def test_update_touches_updated_at(self):
        created = workspace_repo.create(self.con, self.dev, "KT")
        self.con.execute(
            "UPDATE workspaces SET updated_at=? WHERE id=?", (STALE_STAMP, created["id"])
        )
        self.con.commit()
        updated = workspace_repo.update(self.con, created["id"], goal="새 목표")
        self.assertNotEqual(updated["updated_at"], STALE_STAMP)

    def test_get_by_jira_returns_none_when_absent(self):
        self.assertIsNone(workspace_repo.get_by_jira(self.con, "KT-9999"))

    def test_get_by_jira_is_case_insensitive(self):
        workspace_repo.create(self.con, self.dev, "KT", jira_id="KT-1530")
        self.assertIsNotNone(workspace_repo.get_by_jira(self.con, "kt-1530"))

    def test_list_all_filters_by_status(self):
        active = workspace_repo.create(self.con, self.dev, "진행중")
        paused = workspace_repo.create(self.con, self.dev, "보류")
        workspace_repo.update(self.con, paused["id"], status="paused")
        names = [
            item["name"]
            for item in workspace_repo.list_all(self.con, status=WORKSPACE_ACTIVE)
        ]
        self.assertEqual(names, [active["name"]])


class TodoRepoTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()
        self.dev = category_repo.get_by_name(self.con, "개발")["id"]
        self.ops = category_repo.get_by_name(self.con, "운영")["id"]
        self.workspace = workspace_repo.create(self.con, self.dev, "KT 동시성")

    def test_create_requires_category_or_workspace(self):
        with self.assertRaises(Validation):
            todo_repo.create(self.con, "제목만")

    def test_create_with_category_is_unassigned(self):
        created = todo_repo.create(self.con, "문의 회신", category_id=self.ops)
        self.assertIsNone(created["workspace_id"])
        self.assertEqual(created["category_id"], self.ops)

    def test_create_with_workspace_inherits_its_category(self):
        created = todo_repo.create(
            self.con, "락 재설계", workspace_id=self.workspace["id"], category_id=self.ops
        )
        self.assertEqual(created["category_id"], self.dev)

    def test_assigning_workspace_syncs_category(self):
        created = todo_repo.create(self.con, "문의", category_id=self.ops)
        moved = todo_repo.update(self.con, created["id"], workspace_id=self.workspace["id"])
        self.assertEqual(moved["category_id"], self.dev)

    def test_clearing_workspace_keeps_category(self):
        created = todo_repo.create(self.con, "락", workspace_id=self.workspace["id"])
        cleared = todo_repo.update(self.con, created["id"], workspace_id=None)
        self.assertIsNone(cleared["workspace_id"])
        self.assertEqual(cleared["category_id"], self.dev)

    def test_done_stamps_completed_at(self):
        created = todo_repo.create(self.con, "락", workspace_id=self.workspace["id"])
        done = todo_repo.update(self.con, created["id"], status=STATUS_DONE)
        self.assertIsNotNone(done["completed_at"])

    def test_leaving_done_clears_completed_at(self):
        created = todo_repo.create(self.con, "락", workspace_id=self.workspace["id"])
        todo_repo.update(self.con, created["id"], status=STATUS_DONE)
        reopened = todo_repo.update(self.con, created["id"], status=STATUS_DOING)
        self.assertIsNone(reopened["completed_at"])

    def test_done_rejected_while_subtasks_open(self):
        created = todo_repo.create(self.con, "락", workspace_id=self.workspace["id"])
        subtask_repo.create(self.con, created["id"], "k6 시나리오")
        with self.assertRaises(Validation) as caught:
            todo_repo.update(self.con, created["id"], status=STATUS_DONE)
        self.assertIn("k6 시나리오", str(caught.exception))
        self.assertEqual(todo_repo.get(self.con, created["id"])["status"], STATUS_TODO)

    def test_done_allowed_when_all_subtasks_done(self):
        created = todo_repo.create(self.con, "락", workspace_id=self.workspace["id"])
        subtask = subtask_repo.create(self.con, created["id"], "k6 시나리오")
        subtask_repo.update(self.con, subtask["id"], status=STATUS_DONE)
        done = todo_repo.update(self.con, created["id"], status=STATUS_DONE)
        self.assertEqual(done["status"], STATUS_DONE)

    def test_update_rejects_unknown_status(self):
        created = todo_repo.create(self.con, "락", workspace_id=self.workspace["id"])
        with self.assertRaises(Validation):
            todo_repo.update(self.con, created["id"], status="보류")

    def test_delete_cascades_subtasks(self):
        created = todo_repo.create(self.con, "락", workspace_id=self.workspace["id"])
        subtask_repo.create(self.con, created["id"], "k6 시나리오")
        todo_repo.delete(self.con, created["id"])
        left = self.con.execute("SELECT COUNT(*) AS n FROM subtasks").fetchone()["n"]
        self.assertEqual(left, 0)

    def test_sort_order_is_per_group(self):
        first = todo_repo.create(self.con, "1", workspace_id=self.workspace["id"])
        second = todo_repo.create(self.con, "2", workspace_id=self.workspace["id"])
        unassigned = todo_repo.create(self.con, "3", category_id=self.ops)
        self.assertEqual(
            [first["sort_order"], second["sort_order"], unassigned["sort_order"]],
            [1, 2, 1],
        )

    def test_demote_by_workspace_moves_to_unassigned(self):
        created = todo_repo.create(self.con, "락", workspace_id=self.workspace["id"])
        todo_repo.demote_by_workspace(self.con, self.workspace["id"])
        demoted = todo_repo.get(self.con, created["id"])
        self.assertIsNone(demoted["workspace_id"])
        self.assertEqual(demoted["category_id"], self.dev)

    def test_sync_category_updates_member_todos(self):
        created = todo_repo.create(self.con, "락", workspace_id=self.workspace["id"])
        todo_repo.sync_category(self.con, self.workspace["id"], self.ops)
        self.assertEqual(todo_repo.get(self.con, created["id"])["category_id"], self.ops)

    def test_list_completed_on_filters_by_date(self):
        created = todo_repo.create(self.con, "락", workspace_id=self.workspace["id"])
        todo_repo.update(self.con, created["id"], status=STATUS_DONE)
        self.con.execute(
            "UPDATE todos SET completed_at=? WHERE id=?",
            ("2026-07-28T10:00:00+00:00", created["id"]),
        )
        self.con.commit()
        self.assertEqual(len(todo_repo.list_completed_on(self.con, "2026-07-28")), 1)
        self.assertEqual(len(todo_repo.list_completed_on(self.con, "2026-07-29")), 0)


class SubtaskRepoTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()
        dev = category_repo.get_by_name(self.con, "개발")["id"]
        workspace = workspace_repo.create(self.con, dev, "KT 동시성")
        self.todo = todo_repo.create(self.con, "재현 테스트", workspace_id=workspace["id"])

    def test_create_appends_within_todo(self):
        first = subtask_repo.create(self.con, self.todo["id"], "k6 시나리오")
        second = subtask_repo.create(self.con, self.todo["id"], "결과 정리")
        self.assertEqual([first["sort_order"], second["sort_order"]], [1, 2])

    def test_create_rejects_missing_todo(self):
        with self.assertRaises(NotFound):
            subtask_repo.create(self.con, MISSING_ID, "제목")

    def test_create_rejects_blank_title(self):
        with self.assertRaises(Validation):
            subtask_repo.create(self.con, self.todo["id"], "")

    def test_update_status_validated(self):
        created = subtask_repo.create(self.con, self.todo["id"], "k6")
        with self.assertRaises(Validation):
            subtask_repo.update(self.con, created["id"], status="보류")

    def test_delete_removes_only_target(self):
        keep = subtask_repo.create(self.con, self.todo["id"], "유지")
        drop = subtask_repo.create(self.con, self.todo["id"], "삭제")
        subtask_repo.delete(self.con, drop["id"])
        left = [item["id"] for item in subtask_repo.list_by_todo(self.con, self.todo["id"])]
        self.assertEqual(left, [keep["id"]])


class WorkspaceLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()
        self.dev = category_repo.get_by_name(self.con, "개발")["id"]
        self.ops = category_repo.get_by_name(self.con, "운영")["id"]
        self.workspace = workspace_repo.create(self.con, self.dev, "KT 동시성")

    def test_delete_demotes_member_todos(self):
        todo = todo_repo.create(self.con, "락", workspace_id=self.workspace["id"])
        workspace_repo.delete(self.con, self.workspace["id"])
        demoted = todo_repo.get(self.con, todo["id"])
        self.assertIsNone(demoted["workspace_id"])
        self.assertEqual(demoted["category_id"], self.dev)

    def test_delete_removes_workspace(self):
        workspace_repo.delete(self.con, self.workspace["id"])
        with self.assertRaises(NotFound):
            workspace_repo.get(self.con, self.workspace["id"])

    def test_delete_missing_raises_not_found(self):
        with self.assertRaises(NotFound):
            workspace_repo.delete(self.con, MISSING_ID)

    def test_category_change_syncs_member_todos(self):
        todo = todo_repo.create(self.con, "락", workspace_id=self.workspace["id"])
        workspace_repo.update(self.con, self.workspace["id"], category_id=self.ops)
        self.assertEqual(todo_repo.get(self.con, todo["id"])["category_id"], self.ops)

    def test_category_change_rejects_missing_category(self):
        with self.assertRaises(NotFound):
            workspace_repo.update(self.con, self.workspace["id"], category_id=MISSING_ID)
