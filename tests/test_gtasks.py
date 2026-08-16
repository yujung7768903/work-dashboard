"""구글 태스크 양방향 동기화. 네트워크를 타지 않고 가짜 클라이언트로 규칙만 검증한다

매핑은 세 층이다 — 구글 목록=카테고리, 최상위 태스크=워크스페이스, 하위=그 워크스페이스의 할일
"""
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from app.constants import (
    GTASKS_AUTH_URL,
    GTASKS_CLIENT_ID_ENV,
    GTASKS_CLIENT_SECRET_ENV,
    GTASKS_ERROR_EXPIRED,
    GTASKS_NEED_CONNECT,
    GTASKS_STATUS_DONE,
    GTASKS_STATUS_TODO,
    OUTCOME_REVIEW,
    PYTHON_MIN,
    STATUS_DONE,
    STATUS_TODO,
    WORKSPACE_ACTIVE,
)
from app.errors import Validation
from app.services import gtasks_api, gtasks_auth
from app.repositories import autorun as autorun_repo
from app.repositories import categories as category_repo
from app.repositories import gtasks_state
from app.repositories import todos as todo_repo
from app.repositories import workspaces as workspace_repo
from app.services import gtasks, gtasks_setup
from tests.support import temp_db

WORKSPACE_DONE = "done"


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

    def insert(self, list_id, body, parent=None):
        task = dict(body, id=f"task{self._next}", updated=_stamp())
        if parent:
            task["parent"] = parent
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
        """구글은 최상위를 지우면 하위까지 함께 지운다. 그 성질이 규칙을 가르므로 흉내낸다"""
        gone = {task_id} | {
            task["id"]
            for task in self._tasks.get(list_id, [])
            if task.get("parent") == task_id
        }
        self._tasks[list_id] = [
            task for task in self._tasks.get(list_id, []) if task["id"] not in gone
        ]

    def only_task(self):
        for tasks in self._tasks.values():
            for task in tasks:
                return task
        return None

    def find(self, title):
        for tasks in self._tasks.values():
            for task in tasks:
                if task.get("title") == title:
                    return task
        return None

    def task_count(self):
        return sum(len(tasks) for tasks in self._tasks.values())


class GtasksSyncTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()
        category = category_repo.list_all(self.con)[0]
        self.client = FakeClient()
        # 목록 맞추기는 gtasks_setup 의 몫이라 여기서는 결과만 만들어 둔다
        created = self.client.create_list(category["name"])
        category_repo.set_google_list_id(self.con, category["id"], created["id"])
        # 목록을 맞춰도 기본은 off 다. 실제 화면과 같이 사람이 켠 상태에서 시작한다
        category_repo.set_gtasks_enabled(self.con, category["id"], True)
        self.list_id = created["id"]
        self.category = category_repo.get(self.con, category["id"])

    def _space(self, name="결제 개편", **fields):
        return workspace_repo.create(self.con, self.category["id"], name, **fields)

    def _todo(self, title="배포 스크립트 정리", **kwargs):
        kwargs.setdefault("category_id", self.category["id"])
        return todo_repo.create(self.con, title=title, **kwargs)

    def _sync(self):
        return gtasks.sync(self.con, client=self.client)

    def _reload(self, todo):
        return todo_repo.get(self.con, todo["id"])

    # ── 올려보내기 ────────────────────────────────────────────────────────

    def test_워크스페이스가_최상위_할일이_그_하위로_올라간다(self):
        space = self._space(goal="1차 배포까지")
        todo = self._todo(workspace_id=space["id"])

        report = self._sync()

        top = self.client.find("결제 개편")
        child = self.client.find("배포 스크립트 정리")
        self.assertIsNone(top.get("parent"))
        self.assertEqual(child["parent"], top["id"])
        self.assertIn("목표: 1차 배포까지", top["notes"])
        self.assertEqual(self._reload(todo)["google_task_id"], child["id"])
        self.assertEqual(len(report["created_remote"]), 2)

    def test_워크스페이스_없는_할일은_최상위로_올라간다(self):
        self._todo()

        self._sync()

        self.assertIsNone(self.client.only_task().get("parent"))

    def test_두번_돌려도_같은_태스크를_다시_만들지_않는다(self):
        space = self._space()
        self._todo(workspace_id=space["id"])

        self._sync()
        report = self._sync()

        self.assertEqual(self.client.task_count(), 2)
        self.assertEqual(report["created_remote"], [])
        self.assertEqual(report["pushed"], [])

    def test_목록이_안_붙은_카테고리는_건너뛴다(self):
        other = category_repo.create(self.con, "아직 안 맞춘 카테고리")
        todo_repo.create(self.con, title="여기 할일", category_id=other["id"])

        self._sync()

        self.assertIsNone(self.client.only_task())

    def test_꺼진_카테고리는_건드리지_않는다(self):
        self._todo()
        category_repo.set_gtasks_enabled(self.con, self.category["id"], False)

        self._sync()

        self.assertEqual(self.client.task_count(), 0)

    # ── 내려받기 ──────────────────────────────────────────────────────────

    def test_폰에서_만든_최상위는_워크스페이스가_아니라_할일이_된다(self):
        """최상위를 워크스페이스로 승격시키면 회차마다 워크스페이스가 늘어난다"""
        self.client.insert(self.list_id, {"title": "폰에서 적은 일", "status": GTASKS_STATUS_TODO})

        report = self._sync()

        self.assertEqual(workspace_repo.list_all(self.con), [])
        titles = [t["title"] for t in todo_repo.list_by_category(self.con, self.category["id"])]
        self.assertIn("폰에서 적은 일", titles)
        self.assertEqual(len(report["created_local"]), 1)

    def test_폰에서_만든_하위는_그_워크스페이스의_할일이_된다(self):
        space = self._space()
        self._sync()
        top = self.client.find("결제 개편")
        self.client.insert(
            self.list_id, {"title": "폰에서 적은 하위", "status": GTASKS_STATUS_TODO}, parent=top["id"]
        )

        self._sync()

        made = [
            todo
            for todo in todo_repo.list_by_workspace(self.con, space["id"])
            if todo["title"] == "폰에서 적은 하위"
        ]
        self.assertEqual(len(made), 1)

    def test_폰에서_완료하면_로컬도_완료된다(self):
        todo = self._todo()
        self._sync()
        task = self.client.only_task()
        task["status"] = GTASKS_STATUS_DONE
        task["updated"] = _stamp(60)  # 폰 쪽이 더 최신

        report = self._sync()

        self.assertEqual(self._reload(todo)["status"], STATUS_DONE)
        self.assertEqual(len(report["pulled"]), 1)

    def test_폰에서_워크스페이스를_완료하면_done_이_된다(self):
        space = self._space()
        self._sync()
        top = self.client.find("결제 개편")
        top["status"] = GTASKS_STATUS_DONE
        top["updated"] = _stamp(60)

        self._sync()

        self.assertEqual(workspace_repo.get(self.con, space["id"])["status"], WORKSPACE_DONE)

    def test_폰에서_완료를_풀면_워크스페이스가_다시_active_가_된다(self):
        space = self._space()
        self._sync()  # 링크가 생긴 뒤라야 완료된 워크스페이스도 계속 동기화 범위에 남는다
        workspace_repo.update(self.con, space["id"], status=WORKSPACE_DONE)
        self._sync()
        top = self.client.find("결제 개편")
        top["status"] = GTASKS_STATUS_TODO
        top["updated"] = _stamp(60)

        self._sync()

        self.assertEqual(workspace_repo.get(self.con, space["id"])["status"], WORKSPACE_ACTIVE)

    # ── 최신 우선 ─────────────────────────────────────────────────────────

    def test_로컬이_더_최신이면_폰의_제목_수정이_밀려난다(self):
        todo = self._todo()
        self._sync()
        task = self.client.only_task()
        task["title"] = "폰에서 고친 제목"
        task["updated"] = _stamp(-600)  # 로컬 수정보다 과거
        todo_repo.update(self.con, todo["id"], title="대시보드에서 고친 제목")

        report = self._sync()

        self.assertEqual(self.client.only_task()["title"], "대시보드에서 고친 제목")
        self.assertEqual(self._reload(todo)["title"], "대시보드에서 고친 제목")
        self.assertEqual(len(report["pushed"]), 1)

    def test_폰이_더_최신이면_제목이_내려온다(self):
        todo = self._todo()
        self._sync()
        task = self.client.only_task()
        task["title"] = "폰에서 고친 제목"
        task["updated"] = _stamp(600)

        self._sync()

        self.assertEqual(self._reload(todo)["title"], "폰에서 고친 제목")

    def test_밀어넣은_직후_같은_초에_고쳐도_되돌려지지_않는다(self):
        """로컬은 초까지, 구글은 밀리초까지 적는다. 그대로 비교하면 로컬 수정이 조용히 사라진다"""
        todo = self._todo()
        self._sync()
        task = self.client.only_task()
        local_second = self._reload(todo)["updated_at"][:19]
        task["updated"] = f"{local_second}.999Z"  # 같은 초, 밀리초만 뒤
        todo_repo.update(self.con, todo["id"], title="같은 초에 고친 제목")

        self._sync()

        self.assertEqual(self._reload(todo)["title"], "같은 초에 고친 제목")
        self.assertEqual(self.client.only_task()["title"], "같은 초에 고친 제목")

    def test_로컬_규칙에_막히면_폰의_완료를_받지_않고_건너뛴다(self):
        todo = self._todo()
        self._sync()
        # 자율 수행 검토 대기는 사람이 확인하기 전까지 상태 변경을 막는다 — 폰도 예외가 아니다
        run = autorun_repo.start_run(self.con, todo["id"])
        autorun_repo.close_run(self.con, run["id"], OUTCOME_REVIEW)
        task = self.client.only_task()
        task["status"] = GTASKS_STATUS_DONE
        task["updated"] = _stamp(60)

        report = self._sync()

        self.assertEqual(self._reload(todo)["status"], STATUS_TODO)
        self.assertEqual(len(report["skipped"]), 1)

    # ── 삭제 ──────────────────────────────────────────────────────────────

    def test_대시보드에서_지운_할일은_구글에서도_지워진다(self):
        todo = self._todo()
        self._sync()
        todo_repo.delete(self.con, todo["id"])

        report = self._sync()

        self.assertEqual(self.client.task_count(), 0)
        self.assertEqual(len(report["deleted_remote"]), 1)

    def test_폰에서_지운_미완료_할일은_대시보드에서도_지워진다(self):
        todo = self._todo()
        self._sync()
        self.client.delete(self.list_id, self.client.only_task()["id"])

        report = self._sync()

        self.assertEqual(self.client.task_count(), 0)
        self.assertEqual(len(report["deleted_local"]), 1)
        self.assertEqual(todo_repo.list_by_category(self.con, self.category["id"]), [])
        self.assertNotIn(todo["id"], [t["id"] for t in todo_repo.list_by_category(self.con, self.category["id"])])

    def test_완료된_할일은_폰에서_지워도_대시보드에_남는다(self):
        """구글 앱의 '완료된 항목 삭제' 한 번에 완료 기록이 통째로 날아가면 안 된다"""
        todo = self._todo()
        self._sync()
        todo_repo.update(self.con, todo["id"], status=STATUS_DONE)
        self._sync()
        self.client.delete(self.list_id, self.client.only_task()["id"])

        report = self._sync()

        self.assertEqual(self.client.task_count(), 0)
        self.assertEqual(report["deleted_local"], [])
        self.assertEqual(self._reload(todo)["status"], STATUS_DONE)

    def test_워크스페이스를_지워도_소속_할일은_사라지지_않는다(self):
        """구글은 최상위를 지우면 하위까지 지운다. 링크를 안 끊으면 멀쩡한 할일이 증발한다"""
        space = self._space()
        todo = self._todo(workspace_id=space["id"])
        self._sync()
        workspace_repo.delete(self.con, space["id"])  # 소속 할일은 미분류로 강등

        self._sync()

        survivor = self._reload(todo)
        self.assertIsNone(survivor["workspace_id"])
        self.assertEqual(self.client.task_count(), 1)
        self.assertIsNone(self.client.only_task().get("parent"))
        self.assertEqual(self.client.only_task()["id"], survivor["google_task_id"])

    def test_본_적_없는_링크는_지우지_않고_다시_올린다(self):
        """계정·목록이 바뀌면 모든 링크가 한꺼번에 낯설어진다. 지운 증거로 보면 전멸한다"""
        todo = self._todo()
        self._sync()
        # 다른 계정으로 다시 붙인 상황 — 링크는 남았는데 그 태스크를 본 기록이 없다
        gtasks._save_seen(self.con, set())
        self.client.delete(self.list_id, self.client.only_task()["id"])

        report = self._sync()

        self.assertEqual(report["deleted_local"], [])
        self.assertEqual(len(report["created_remote"]), 1)
        self.assertEqual(self._reload(todo)["google_task_id"], self.client.only_task()["id"])

    def test_dry_run_은_양쪽_다_건드리지_않는다(self):
        todo = self._todo()

        report = gtasks.sync(self.con, client=self.client, dry_run=True)

        self.assertEqual(len(report["created_remote"]), 1)
        self.assertEqual(self.client.task_count(), 0)
        self.assertIsNone(self._reload(todo)["google_task_id"])


class GtasksSetupTest(unittest.TestCase):
    """연동을 켤 때 한 번 도는 카테고리 맞추기. 할일은 건드리지 않는다"""

    def setUp(self):
        self.con = temp_db()
        self.client = FakeClient()
        self.names = [row["name"] for row in category_repo.list_all(self.con)]
        # 돌리는 기계에 ssl 이 없으면 그 사유가 모든 판정을 덮는다. 여기서는 고정한다
        ready = mock.patch.object(gtasks_api, "HTTPS_READY", True)
        ready.start()
        self.addCleanup(ready.stop)
        # connect·disconnect 를 부르는 검사를 하나 더 붙이면서 patch 를 빠뜨리면
        # 사용자의 실제 refresh_token 이 지워진다. 클래스 전체를 임시 파일로 돌린다
        self.config_path = os.path.join(tempfile.mkdtemp(), "gtasks.json")
        config = mock.patch.object(gtasks_api, "GTASKS_CONFIG_PATH", self.config_path)
        config.start()
        self.addCleanup(config.stop)

    def test_계획은_양쪽_건수를_붙여_보여주고_아무것도_쓰지_않는다(self):
        """이름이 같다고 같은 것이 아니다 — 건수가 없으면 남의 목록과 통째로 합쳐진다"""
        both = self.client.create_list(self.names[0])
        self.client.insert(both["id"], {"title": "폰에 원래 있던 것"})
        self.client.create_list("운동")
        todo_repo.create(
            self.con, title="여기 할일", category_id=category_repo.list_all(self.con)[0]["id"]
        )

        plan = gtasks_setup.plan(self.con, client=self.client)
        found = {item["name"]: item for item in plan["items"]}

        self.assertEqual(found[self.names[0]]["local"], 1)
        self.assertEqual(found[self.names[0]]["remote"], 1)
        self.assertIsNone(found["운동"]["local"])
        self.assertEqual(found["운동"]["remote"], 0)
        self.assertIsNone(found[self.names[1]]["remote"])
        self.assertEqual([row["name"] for row in category_repo.list_all(self.con)], self.names)

    def test_고른_것만_만들고_켠다(self):
        self.client.create_list("운동")

        gtasks_setup.apply(self.con, ["운동", self.names[0]], client=self.client)

        rows = {row["name"]: row for row in category_repo.list_all(self.con)}
        self.assertIn("운동", rows)  # 구글에만 있던 것을 골랐으니 카테고리가 생긴다
        self.assertTrue(rows["운동"]["gtasks_enabled"])
        self.assertTrue(rows[self.names[0]]["gtasks_enabled"])
        self.assertTrue(gtasks_state.state(self.con)["enabled"])

    def test_맞춘_뒤에도_구글에만_있는_목록을_다시_고를_수_있다(self):
        """맞추기를 마치면 팝업으로 돌아올 길이 없어 폰의 목록을 영영 못 가져왔다"""
        gtasks_setup.apply(self.con, [self.names[0]], client=self.client)
        self.client.create_list("나중에 만든 목록")

        plan = gtasks_setup.plan(self.con, client=self.client)
        found = {item["name"]: item for item in plan["items"]}

        self.assertTrue(found[self.names[0]]["linked"])  # 이미 맺은 것은 잠긴 채로 보인다
        self.assertIn("나중에 만든 목록", found)
        self.assertFalse(found["나중에 만든 목록"]["linked"])

        gtasks_setup.apply(self.con, ["나중에 만든 목록"], client=self.client)

        rows = {row["name"]: row for row in category_repo.list_all(self.con)}
        self.assertTrue(rows["나중에 만든 목록"]["gtasks_enabled"])

    def test_다시_고를_때_꺼_둔_카테고리가_되살아나지_않는다(self):
        """apply 는 받은 것만 켠다 — 잠긴 항목을 화면이 같이 보내면 꺼 둔 것이 되살아난다"""
        gtasks_setup.apply(self.con, [self.names[0], self.names[1]], client=self.client)
        target = category_repo.get_by_name(self.con, self.names[0])
        category_repo.set_gtasks_enabled(self.con, target["id"], False)
        self.client.create_list("새 목록")

        gtasks_setup.apply(self.con, ["새 목록"], client=self.client)

        rows = {row["name"]: row for row in category_repo.list_all(self.con)}
        self.assertFalse(rows[self.names[0]]["gtasks_enabled"])

    def test_고르지_않은_것은_양쪽_어디도_건드리지_않는다(self):
        """예전에는 합집합을 통째로 만들어 폰의 목록이 전부 카테고리가 됐다"""
        self.client.create_list("운동")
        self.client.create_list("회사")

        gtasks_setup.apply(self.con, [self.names[0]], client=self.client)

        rows = {row["name"]: row for row in category_repo.list_all(self.con)}
        self.assertNotIn("운동", rows)
        self.assertNotIn("회사", rows)
        # 안 고른 대시보드 카테고리도 폰에 목록을 만들지 않는다
        self.assertEqual(sorted(t["title"] for t in self.client.lists()),
                         sorted(["운동", "회사", self.names[0]]))
        for name in self.names[1:]:
            self.assertIsNone(rows[name]["google_list_id"])
            self.assertFalse(rows[name]["gtasks_enabled"])

    def test_하나도_안_고르면_거절한다(self):
        with self.assertRaises(Validation):
            gtasks_setup.apply(self.con, [], client=self.client)

    def test_이름이_같으면_목록을_다시_만들지_않고_링크만_맺는다(self):
        existing = self.client.create_list(self.names[0])

        gtasks_setup.apply(self.con, [self.names[0]], client=self.client)

        linked = category_repo.get_by_name(self.con, self.names[0])
        self.assertEqual(linked["google_list_id"], existing["id"])
        self.assertEqual(len(self.client.lists()), 1)

    def test_인증_전에_켜면_경로_대신_다음에_누를_것을_알려준다(self):
        """load_config 원문은 파일 경로와 CLI 명령이 박혀 있다. 버튼이 바로 아래 있는데도"""
        empty = mock.patch.object(gtasks_api, "stored_client", return_value={})
        calls = (
            lambda: gtasks_setup.plan(self.con),
            lambda: gtasks_setup.apply(self.con, ["개발"]),
            lambda: gtasks.sync(self.con),
        )
        for call in calls:
            with empty:
                with self.assertRaises(Validation) as caught:
                    call()
            self.assertEqual(str(caught.exception), GTASKS_NEED_CONNECT)

    def test_인증에_실패하면_사유가_남아_화면에_뜬다(self):
        """사유가 없으면 화면에 '연결 안 됨' 만 남아, 왜 또 연결해야 하는지 알 수 없다"""
        blew_up = mock.patch.object(
            gtasks_auth, "authorize", side_effect=Validation("동의가 오지 않음")
        )

        with blew_up:
            with self.assertRaises(Validation):
                gtasks_setup.connect(self.con)

        self.assertEqual(gtasks_state.state(self.con)["last_error"], "동의가 오지 않음")
        self.assertEqual(gtasks_setup.panel(self.con)["reason"], "동의가 오지 않음")

    def test_인증에_성공하면_지난_사유가_지워진다(self):
        gtasks_state.record_error(self.con, "지난번 실패")

        with mock.patch.object(gtasks_auth, "authorize", return_value="path"):
            gtasks_setup.connect(self.con)

        self.assertIsNone(gtasks_state.state(self.con)["last_error"])

    def test_연결_해제는_승인만_버리고_링크와_자격증명은_남긴다(self):
        """다시 붙일 때 콘솔에 또 가지 않아야 하고, 같은 계정이면 그대로 이어져야 한다"""
        config = os.path.join(tempfile.mkdtemp(), "gtasks.json")
        with open(config, "w", encoding="utf-8") as handle:
            handle.write('{"client_id": "a", "client_secret": "b", "refresh_token": "c"}')
        gtasks_setup.apply(self.con, [self.names[0]], client=self.client)
        linked = category_repo.list_all(self.con)[0]["google_list_id"]

        with mock.patch.object(gtasks_api, "GTASKS_CONFIG_PATH", config):
            payload = gtasks_setup.disconnect(self.con)
            left = gtasks_api.stored_client(config)

        self.assertNotIn("refresh_token", left)
        self.assertEqual(left["client_id"], "a")  # 앱 등록은 남는다
        self.assertFalse(payload["state"]["enabled"])
        self.assertEqual(category_repo.list_all(self.con)[0]["google_list_id"], linked)
        # 본 기록을 남기면 다시 붙였을 때 사라진 태스크를 '폰에서 지웠다'로 읽는다
        self.assertEqual(gtasks._load_seen(self.con), set())

    def test_등록된_자동_실행이_없으면_주기가_없다고_알린다(self):
        """상수로 '10분마다' 라고 적으면 아무것도 등록 안 한 사람에게 거짓말이 된다"""
        with mock.patch.object(gtasks_setup, "schedule", return_value=None):
            self.assertIsNone(gtasks_setup.panel(self.con)["every_sec"])

    def test_launchd_에_걸어_두면_주기를_읽는다(self):
        folder = tempfile.mkdtemp()
        with open(os.path.join(folder, "sync.plist"), "w", encoding="utf-8") as handle:
            handle.write(
                "<plist><dict>"
                "<key>ProgramArguments</key><array>"
                "<string>dash.py</string><string>gtasks-sync</string></array>"
                "<key>StartInterval</key><integer>600</integer>"
                "</dict></plist>"
            )

        with mock.patch.object(gtasks_setup.os.path, "expanduser", return_value=folder):
            self.assertEqual(gtasks_setup._launchd_interval(), 600)

    def test_crontab_에_걸어_두면_주기를_읽는다(self):
        line = "*/10 * * * * cd ~/work && python3 dash.py gtasks-sync\n"
        done = subprocess.CompletedProcess([], 0, stdout=line, stderr="")

        with mock.patch.object(gtasks_setup.subprocess, "run", return_value=done):
            self.assertEqual(gtasks_setup._cron_interval(), 600)

    def test_주석_처리된_줄은_등록으로_보지_않는다(self):
        line = "# */10 * * * * python3 dash.py gtasks-sync\n"
        done = subprocess.CompletedProcess([], 0, stdout=line, stderr="")

        with mock.patch.object(gtasks_setup.subprocess, "run", return_value=done):
            self.assertIsNone(gtasks_setup._cron_interval())

    def test_crontab_이_없거나_막혀도_화면은_뜬다(self):
        """설정 탭을 여는 길목이라 여기서 터지면 화면 자체가 안 뜬다"""
        for blow_up in (OSError("없음"), subprocess.TimeoutExpired("crontab", 2)):
            with mock.patch.object(gtasks_setup.subprocess, "run", side_effect=blow_up):
                self.assertIsNone(gtasks_setup._cron_interval())

    def test_ssl_이_없으면_화면을_여는_순간_그_사유부터_보인다(self):
        """자격증명을 다 입력한 뒤에 알려주면 헛수고가 된다"""
        with mock.patch.object(gtasks_api, "HTTPS_READY", False):
            payload = gtasks_setup.panel(self.con)

        self.assertIn(PYTHON_MIN, payload["reason"])

    def test_설정_화면_payload_는_네트워크를_치지_않는다(self):
        with mock.patch.object(gtasks_api, "HTTPS_READY", True):
            payload = gtasks_setup.panel(self.con)

        self.assertFalse(payload["state"]["enabled"])
        self.assertEqual(len(payload["categories"]), len(self.names))
        # 목록을 맞추는 것과 할일을 주고받는 것은 다른 결정이다 — 켜는 것은 사람이 고른다
        self.assertFalse(any(row["enabled"] for row in payload["categories"]))
        self.assertFalse(any(row["linked"] for row in payload["categories"]))


class GtasksRunTest(unittest.TestCase):
    """cron 과 웹이 같이 쓰는 입구. 설정을 보고 돌지 말지 정한다"""

    def setUp(self):
        self.con = temp_db()

    def test_꺼져_있으면_아무것도_하지_않는다(self):
        self.assertIsNone(gtasks.run(self.con))

    def test_실패해도_켜진_상태는_유지하고_사유만_남긴다(self):
        gtasks_state.set_enabled(self.con, True)
        blow_up = mock.patch.object(
            gtasks, "sync", side_effect=gtasks_api.GtasksError("invalid_grant: 어쩌고")
        )

        with blow_up:
            with self.assertRaises(gtasks_api.GtasksError):
                gtasks.run(self.con)

        state = gtasks_state.state(self.con)
        self.assertTrue(state["enabled"])
        self.assertEqual(state["last_error"], GTASKS_ERROR_EXPIRED)

    def test_성공하면_사유가_지워지고_시각이_남는다(self):
        gtasks_state.set_enabled(self.con, True)
        gtasks_state.record_error(self.con, "지난번 실패")

        with mock.patch.object(gtasks, "sync", return_value={}):
            gtasks.run(self.con)

        state = gtasks_state.state(self.con)
        self.assertIsNone(state["last_error"])
        self.assertTrue(state["last_sync_at"])


class GtasksAuthArgsTest(unittest.TestCase):
    """최초 인증의 자격증명 출처. 브라우저까지 가기 전에 걸러지는 구간만 본다

    사용자의 실제 gtasks.json 을 절대 읽지 않도록 설정 경로를 매번 임시 파일로 돌린다
    """

    def setUp(self):
        self.config_path = os.path.join(tempfile.mkdtemp(), "gtasks.json")
        patcher = mock.patch.object(gtasks_api, "GTASKS_CONFIG_PATH", self.config_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        # 돌리는 기계의 Python 에 ssl 이 있든 없든 같은 결과가 나와야 한다.
        # 고정하지 않으면 ssl 없는 기계에서 아래 검사들이 전부 그 안내로 덮인다
        ready = mock.patch.object(gtasks_api, "HTTPS_READY", True)
        ready.start()
        self.addCleanup(ready.stop)

    def _write_config(self, payload):
        with open(self.config_path, "w", encoding="utf-8") as handle:
            handle.write(payload)

    def _reaches_consent(self):
        """동의 화면 직전에서 멈춰 세운다 — 여기까지 왔으면 자격증명을 찾았다는 뜻"""
        stopped = mock.patch.object(
            gtasks_auth, "HTTPServer", side_effect=RuntimeError("여기까지")
        )
        with stopped:
            with self.assertRaises(RuntimeError):
                gtasks_auth.authorize()

    def test_아무_데도_없으면_세_가지_방법을_다_알려주고_멈춘다(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(Validation) as caught:
                gtasks_auth.authorize()

        message = str(caught.exception)
        self.assertIn(GTASKS_CLIENT_ID_ENV, message)
        self.assertIn(GTASKS_CLIENT_SECRET_ENV, message)
        self.assertIn(self.config_path, message)

    def test_환경변수만_있어도_인증_흐름으로_넘어간다(self):
        env = {GTASKS_CLIENT_ID_ENV: "id-from-env", GTASKS_CLIENT_SECRET_ENV: "secret"}
        with mock.patch.dict(os.environ, env, clear=True):
            self._reaches_consent()

    def test_파일에_적어_둔_자격증명만으로_돌아간다(self):
        self._write_config('{"client_id": "id-in-file", "client_secret": "secret"}')

        with mock.patch.dict(os.environ, {}, clear=True):
            self._reaches_consent()

    def test_인자가_파일보다_우선한다(self):
        self._write_config('{"client_id": "id-in-file", "client_secret": "secret"}')
        seen = {}

        def _capture(client_id, redirect_uri, challenge):
            seen["client_id"] = client_id
            raise RuntimeError("여기까지")

        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch.object(gtasks_auth, "_consent_url", _capture):
                with self.assertRaises(RuntimeError):
                    gtasks_auth.authorize("id-from-arg", "secret-from-arg")

        self.assertEqual(seen["client_id"], "id-from-arg")

    def test_깨진_파일은_없는_것으로_보고_안내로_끝낸다(self):
        self._write_config("{ 이건 JSON 이 아니다")

        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(Validation):
                gtasks_auth.authorize()

    def test_ssl_없는_Python_이면_최소_버전을_알려주고_멈춘다(self):
        """같은 3.9 라도 ssl 없이 빌드되면 urllib 이 'unknown url type: https' 로 끝난다"""
        self._write_config('{"client_id": "a", "client_secret": "b"}')
        broken = mock.patch.object(gtasks_api, "HTTPS_READY", False)

        with broken:
            with self.assertRaises(Validation) as caught:
                gtasks_auth.authorize()

        message = str(caught.exception)
        self.assertIn(PYTHON_MIN, message)
        self.assertIn("ssl", message)

    def test_브라우저가_안_열리면_주소를_알려주고_멈춘다(self):
        """웹 화면에서는 서버 콘솔의 안내를 볼 수 없다. 그냥 기다리면 스피너만 남는다"""
        self._write_config('{"client_id": "a", "client_secret": "b"}')

        with mock.patch.object(gtasks_auth.webbrowser, "open", return_value=False):
            with self.assertRaises(Validation) as caught:
                gtasks_auth.authorize()

        self.assertIn(GTASKS_AUTH_URL, str(caught.exception))

    def test_부분_저장이_refresh_token_을_지우지_않는다(self):
        """동의 화면을 다시 거쳐야만 나오는 값이라, 한 번 덮이면 재인증밖에 길이 없다"""
        self._write_config(
            '{"client_id": "a", "client_secret": "b", "refresh_token": "keep-me"}'
        )

        gtasks_api.save_config({"client_id": "새 값", "client_secret": "새 비밀"})

        left = gtasks_api.stored_client(self.config_path)
        self.assertEqual(left["refresh_token"], "keep-me")
        self.assertEqual(left["client_id"], "새 값")

    def test_쓰는_도중에_읽어도_빈_파일이_보이지_않는다(self):
        """곧바로 truncate 하면 그 사이 읽는 쪽이 빈 값으로 판단해 토큰을 잃는다"""
        self._write_config(
            '{"client_id": "a", "client_secret": "b", "refresh_token": "keep-me"}'
        )
        seen = []
        original = gtasks_api.json.dump

        def peeking(*args, **kwargs):
            # 새 내용을 쓰는 도중에 다른 프로세스가 읽은 셈 친다
            seen.append(gtasks_api.stored_client(self.config_path))
            return original(*args, **kwargs)

        with mock.patch.object(gtasks_api.json, "dump", peeking):
            gtasks_api.save_config({"client_id": "새 값"})

        self.assertEqual(seen[0].get("refresh_token"), "keep-me")

    def test_연결_해제만_refresh_token_을_지운다(self):
        self._write_config(
            '{"client_id": "a", "client_secret": "b", "refresh_token": "keep-me"}'
        )

        gtasks_api.forget_refresh_token()

        left = gtasks_api.stored_client(self.config_path)
        self.assertNotIn("refresh_token", left)
        self.assertEqual(left["client_id"], "a")

    def test_refresh_token_까지_있으면_동기화는_인증_없이_읽는다(self):
        self._write_config(
            '{"client_id": "a", "client_secret": "b", "refresh_token": "c"}'
        )

        config = gtasks_api.load_config(self.config_path)

        self.assertEqual(config["refresh_token"], "c")


class GtasksTimestampTest(unittest.TestCase):
    def test_구글의_Z_표기를_읽는다(self):
        parsed = gtasks._parsed("2026-08-02T10:00:00.000Z")

        self.assertEqual(parsed.tzinfo, timezone.utc)
        self.assertEqual(parsed.hour, 10)

    def test_읽을_수_없는_시각은_가장_과거로_취급한다(self):
        self.assertLess(gtasks._parsed("망가진 값"), gtasks._parsed(_stamp(-99999)))


if __name__ == "__main__":
    unittest.main()
