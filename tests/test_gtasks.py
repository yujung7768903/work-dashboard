"""구글 태스크 양방향 동기화. 네트워크를 타지 않고 가짜 클라이언트로 규칙만 검증한다"""
import unittest
from datetime import datetime, timedelta, timezone

from app.constants import GTASKS_STATUS_DONE, GTASKS_STATUS_TODO, STATUS_DONE, STATUS_TODO
from app.repositories import categories as category_repo
from app.repositories import subtasks as subtask_repo
from app.repositories import todos as todo_repo
from app.services import gtasks
from tests.support import temp_db


def _stamp(offset_seconds=0):
    moment = datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class FakeClient:
    """메모리 위의 Google Tasks. 호출 순서와 결과만 재현하면 충분하다"""

    def __init__(self, lists=None, tasks=None):
        self._lists = lists or {}
        self._tasks = tasks or {}
        self._next = 1

    def lists(self):
        return [{"id": key, "title": title} for key, title in self._lists.items()]

    def create_list(self, title):
        list_id = f"list{self._next}"
        self._next += 1
        self._lists[list_id] = title
        self._tasks[list_id] = []
        return {"id": list_id, "title": title}

    def tasks(self, list_id):
        return list(self._tasks.get(list_id, []))

    def insert(self, list_id, body):
        task = dict(body, id=f"task{self._next}", updated=_stamp())
        self._next += 1
        self._tasks.setdefault(list_id, []).append(task)
        return task

    def patch(self, list_id, task_id, body):
        for task in self._tasks.get(list_id, []):
            if task["id"] == task_id:
                task.update(body)
                task["updated"] = _stamp()
                return task
        raise AssertionError(f"없는 태스크 patch: {task_id}")

    def delete(self, list_id, task_id):
        self._tasks[list_id] = [
            task for task in self._tasks.get(list_id, []) if task["id"] != task_id
        ]

    def only_task(self):
        for tasks in self._tasks.values():
            for task in tasks:
                return task
        return None

    def task_count(self):
        return sum(len(tasks) for tasks in self._tasks.values())


class GtasksSyncTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()
        self.category = category_repo.list_all(self.con)[0]
        self.client = FakeClient()

    def _todo(self, title="배포 스크립트 정리", **kwargs):
        return todo_repo.create(
            self.con, title=title, category_id=self.category["id"], **kwargs
        )

    def _sync(self):
        return gtasks.sync(self.con, client=self.client)

    def test_로컬_할일이_구글_목록으로_올라가고_링크가_남는다(self):
        todo = self._todo(note="본문", precondition="서버 재기동 후")

        report = self._sync()

        self.assertEqual(len(report["created_remote"]), 1)
        task = self.client.only_task()
        self.assertEqual(task["title"], "배포 스크립트 정리")
        self.assertIn("착수 조건: 서버 재기동 후", task["notes"])
        self.assertEqual(todo_repo.get(self.con, todo["id"])["google_task_id"], task["id"])

    def test_빈_카테고리는_목록을_만들지_않는다(self):
        self._sync()

        self.assertEqual(self.client.lists(), [])

    def test_두번_돌려도_같은_태스크를_다시_만들지_않는다(self):
        self._todo()

        self._sync()
        report = self._sync()

        self.assertEqual(self.client.task_count(), 1)
        self.assertEqual(report["created_remote"], [])
        self.assertEqual(report["pushed"], [])

    def test_폰에서_완료하면_로컬도_완료된다(self):
        todo = self._todo()
        self._sync()
        task = self.client.only_task()
        task["status"] = GTASKS_STATUS_DONE
        task["updated"] = _stamp(60)  # 폰 쪽이 더 최신

        report = self._sync()

        self.assertEqual(todo_repo.get(self.con, todo["id"])["status"], STATUS_DONE)
        self.assertEqual(len(report["pulled"]), 1)

    def test_로컬이_더_최신이면_폰의_제목_수정이_밀려난다(self):
        todo = self._todo()
        self._sync()
        task = self.client.only_task()
        task["title"] = "폰에서 고친 제목"
        task["updated"] = _stamp(-600)  # 로컬 수정보다 과거
        todo_repo.update(self.con, todo["id"], title="대시보드에서 고친 제목")

        report = self._sync()

        self.assertEqual(self.client.only_task()["title"], "대시보드에서 고친 제목")
        self.assertEqual(todo_repo.get(self.con, todo["id"])["title"], "대시보드에서 고친 제목")
        self.assertEqual(len(report["pushed"]), 1)

    def test_폰이_더_최신이면_제목이_내려온다(self):
        todo = self._todo()
        self._sync()
        task = self.client.only_task()
        task["title"] = "폰에서 고친 제목"
        task["updated"] = _stamp(600)

        self._sync()

        self.assertEqual(todo_repo.get(self.con, todo["id"])["title"], "폰에서 고친 제목")

    def test_폰에서_만든_태스크가_그_카테고리의_할일이_된다(self):
        self._todo()
        self._sync()
        list_id = self.client.lists()[0]["id"]
        self.client.insert(list_id, {"title": "폰에서 적은 일", "status": GTASKS_STATUS_TODO})

        report = self._sync()

        titles = [t["title"] for t in todo_repo.list_by_category(self.con, self.category["id"])]
        self.assertIn("폰에서 적은 일", titles)
        self.assertEqual(len(report["created_local"]), 1)

    def test_로컬에서_지운_할일은_구글에서도_지워진다(self):
        todo = self._todo()
        self._sync()
        todo_repo.delete(self.con, todo["id"])

        report = self._sync()

        self.assertEqual(self.client.task_count(), 0)
        self.assertEqual(len(report["deleted_remote"]), 1)

    def test_폰에서_지운_미완료_할일은_되살아난다(self):
        self._todo()
        self._sync()
        list_id = self.client.lists()[0]["id"]
        self.client.delete(list_id, self.client.only_task()["id"])

        self._sync()

        self.assertEqual(self.client.task_count(), 1)

    def test_완료된_할일은_폰에서_지워도_되살리지_않는다(self):
        todo = self._todo()
        self._sync()
        todo_repo.update(self.con, todo["id"], status=STATUS_DONE)
        self._sync()
        list_id = self.client.lists()[0]["id"]
        self.client.delete(list_id, self.client.only_task()["id"])

        self._sync()

        self.assertEqual(self.client.task_count(), 0)

    def test_하위할일이_남으면_폰의_완료를_받지_않고_건너뛴다(self):
        todo = self._todo()
        subtask_repo.create(self.con, todo["id"], "남은 하위할일")
        self._sync()
        task = self.client.only_task()
        task["status"] = GTASKS_STATUS_DONE
        task["updated"] = _stamp(60)

        report = self._sync()

        self.assertEqual(todo_repo.get(self.con, todo["id"])["status"], STATUS_TODO)
        self.assertEqual(len(report["skipped"]), 1)

    def test_dry_run_은_양쪽_다_건드리지_않는다(self):
        todo = self._todo()

        report = gtasks.sync(self.con, client=self.client, dry_run=True)

        self.assertEqual(len(report["created_remote"]), 1)
        self.assertEqual(self.client.task_count(), 0)
        self.assertIsNone(todo_repo.get(self.con, todo["id"])["google_task_id"])

    def test_밀어넣은_직후_같은_초에_고쳐도_되돌려지지_않는다(self):
        """로컬은 초까지, 구글은 밀리초까지 적는다. 그대로 비교하면 로컬 수정이 조용히 사라진다"""
        todo = self._todo()
        self._sync()
        task = self.client.only_task()
        local_second = todo_repo.get(self.con, todo["id"])["updated_at"][:19]
        task["updated"] = f"{local_second}.999Z"  # 같은 초, 밀리초만 뒤
        todo_repo.update(self.con, todo["id"], title="같은 초에 고친 제목")

        self._sync()

        self.assertEqual(todo_repo.get(self.con, todo["id"])["title"], "같은 초에 고친 제목")
        self.assertEqual(self.client.only_task()["title"], "같은 초에 고친 제목")

    def test_기존_목록을_제목으로_찾아_다시_만들지_않는다(self):
        self.client.create_list(f"대시보드 · {self.category['name']}")
        self._todo()

        self._sync()

        self.assertEqual(len(self.client.lists()), 1)


class GtasksTimestampTest(unittest.TestCase):
    def test_구글의_Z_표기를_읽는다(self):
        parsed = gtasks._parsed("2026-08-02T10:00:00.000Z")

        self.assertEqual(parsed.tzinfo, timezone.utc)
        self.assertEqual(parsed.hour, 10)

    def test_읽을_수_없는_시각은_가장_과거로_취급한다(self):
        self.assertLess(gtasks._parsed("망가진 값"), gtasks._parsed(_stamp(-99999)))


if __name__ == "__main__":
    unittest.main()
