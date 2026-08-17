"""결과물(Result) 저장·조회·날짜 필터·페이징."""
import unittest
from datetime import datetime, timedelta, timezone

from app.errors import NotFound, Validation
from app.repositories import categories as category_repo
from app.repositories import results as result_repo
from app.repositories import todos as todo_repo
from app.repositories import workspaces as workspace_repo
from tests.support import temp_db


class ResultRepoTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()
        dev = category_repo.get_by_name(self.con, "개발")["id"]
        workspace = workspace_repo.create(self.con, dev, "포트폴리오")
        self.todo = todo_repo.create(self.con, "이력서 Figma", workspace_id=workspace["id"])

    def test_create_requires_kind(self):
        with self.assertRaises(Validation):
            result_repo.create(self.con, self.todo["id"], "  ")

    def test_create_rejects_unknown_todo(self):
        with self.assertRaises(NotFound):
            result_repo.create(self.con, 9999, "Figma")

    def test_create_requires_link_url(self):
        with self.assertRaises(Validation):
            result_repo.create(
                self.con, self.todo["id"], "Figma", links=[{"label": "x", "url": ""}]
            )

    def test_create_and_get_round_trips_links(self):
        created = result_repo.create(
            self.con,
            self.todo["id"],
            "배포",
            summary="백엔드·프런트 배포",
            session_cwd="~/work/work-dashboard",
            links=[
                {"label": "Backend - Railway", "url": "https://railway.app/x"},
                {"url": "https://vercel.com/y"},
            ],
        )
        fetched = result_repo.get(self.con, created["id"])
        self.assertEqual(fetched["kind"], "배포")
        self.assertEqual(fetched["session_cwd"], "~/work/work-dashboard")
        self.assertEqual(
            fetched["links"],
            [
                {"label": "Backend - Railway", "url": "https://railway.app/x"},
                {"label": "", "url": "https://vercel.com/y"},
            ],
        )

    def test_get_unknown_result_raises_not_found(self):
        with self.assertRaises(NotFound):
            result_repo.get(self.con, 9999)

    def test_list_by_todo_ids_orders_by_recent_first(self):
        first = result_repo.create(self.con, self.todo["id"], "Figma")
        second = result_repo.create(self.con, self.todo["id"], "Velog")
        rows = result_repo.list_by_todo_ids(self.con, [self.todo["id"]])
        self.assertEqual([row["id"] for row in rows], [second["id"], first["id"]])

    def test_list_by_todo_ids_empty_list_returns_empty(self):
        self.assertEqual(result_repo.list_by_todo_ids(self.con, []), [])

    def test_delete_removes_and_then_raises(self):
        created = result_repo.create(self.con, self.todo["id"], "Figma")
        result_repo.delete(self.con, created["id"])
        with self.assertRaises(NotFound):
            result_repo.get(self.con, created["id"])

    def test_delete_rejects_unknown_result(self):
        with self.assertRaises(NotFound):
            result_repo.delete(self.con, 9999)


class ResultPageTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()
        dev = category_repo.get_by_name(self.con, "개발")["id"]
        workspace = workspace_repo.create(self.con, dev, "포트폴리오")
        self.todo = todo_repo.create(self.con, "이력서 Figma", workspace_id=workspace["id"])

    def _stamp(self, result_id, when):
        self.con.execute("UPDATE results SET updated_at=? WHERE id=?", (when, result_id))
        self.con.commit()

    def test_pagination_splits_pages(self):
        for index in range(3):
            result_repo.create(self.con, self.todo["id"], f"결과{index}")
        first_page = result_repo.list_page(self.con, page=1, page_size=2)
        self.assertEqual(first_page["total"], 3)
        self.assertEqual(len(first_page["items"]), 2)
        second_page = result_repo.list_page(self.con, page=2, page_size=2)
        self.assertEqual(len(second_page["items"]), 1)

    def test_today_preset_excludes_older_entries(self):
        today = result_repo.create(self.con, self.todo["id"], "오늘")
        old = result_repo.create(self.con, self.todo["id"], "예전")
        self._stamp(old["id"], "2000-01-01T00:00:00+00:00")
        page = result_repo.list_page(self.con, preset="today")
        self.assertEqual([row["id"] for row in page["items"]], [today["id"]])

    def test_this_week_preset_excludes_last_week(self):
        this_week = result_repo.create(self.con, self.todo["id"], "이번주")
        last_week_entry = result_repo.create(self.con, self.todo["id"], "지난주")
        self._stamp(last_week_entry["id"], f"{_last_monday()}T00:00:00+00:00")
        page = result_repo.list_page(self.con, preset="this_week")
        self.assertEqual([row["id"] for row in page["items"]], [this_week["id"]])

    def test_last_week_preset_only_returns_last_week(self):
        entry = result_repo.create(self.con, self.todo["id"], "지난주")
        self._stamp(entry["id"], f"{_last_monday()}T00:00:00+00:00")
        result_repo.create(self.con, self.todo["id"], "이번주")
        page = result_repo.list_page(self.con, preset="last_week")
        self.assertEqual([row["id"] for row in page["items"]], [entry["id"]])

    def test_custom_range_filters_by_date(self):
        entry = result_repo.create(self.con, self.todo["id"], "지정일")
        self._stamp(entry["id"], "2026-08-01T00:00:00+00:00")
        other = result_repo.create(self.con, self.todo["id"], "다른날")
        self._stamp(other["id"], "2026-08-10T00:00:00+00:00")
        page = result_repo.list_page(self.con, date_from="2026-07-30", date_to="2026-08-05")
        self.assertEqual([row["id"] for row in page["items"]], [entry["id"]])

    def test_unknown_preset_is_rejected(self):
        with self.assertRaises(Validation):
            result_repo.list_page(self.con, preset="tomorrow")

    def test_bad_custom_date_is_rejected(self):
        with self.assertRaises(Validation):
            result_repo.list_page(self.con, date_from="08/01/2026")


def _last_monday():
    today = datetime.now(timezone.utc).date()
    monday = today - timedelta(days=today.weekday())
    return (monday - timedelta(days=7)).isoformat()


if __name__ == "__main__":
    unittest.main()
