"""미분류 자동 분류 — 근거가 확실한 것만 분류하고 애매한 것은 미분류로 남긴다.

학습 데이터는 사용자가 이미 분류한 할일이다. 여기서는 카테고리마다 말이 뚜렷이 갈리는 할일을
심어 두고, 분류돼야 할 글과 미분류로 남아야 할 글(근거 부족·경합·학습 부족)을 나눠 본다
"""
import io
import json
import os
import unittest
from contextlib import redirect_stdout

import dash
from app.constants import CLASSIFY_MIN_TRAINING, DB_PATH_ENV, SPAWN_FALLBACK_CATEGORY
from app.repositories import categories as category_repo
from app.repositories import sessions as session_repo
from app.repositories import todos as todo_repo
from app.services import auto_classify, spawn_link
from tests.support import temp_db, temp_db_path

# 카테고리별로 반복되는 말(근거 키워드)과 할일마다 다른 대상. 근거 키워드는 3건 이상에 나와야 학습된다
CORPUS = {
    "운영": ("운영 배포 반영", "취약점 점검", "서버 인증서 갱신"),
    "문의": ("문의 회신", "기자 문의 답변", "편집국 질문 확인"),
    "공부": ("스터디 자료 정리", "강의 실습 준비", "학습 퀴즈 만들기"),
}
TARGETS = ("허브", "라이브러리", "VMS", "통합DB")


def seed(con, per_category=12):
    """카테고리마다 per_category 건씩 분류된 할일을 만든다"""
    for name, phrases in CORPUS.items():
        category = _category(con, name)
        for index in range(per_category):
            phrase = phrases[index % len(phrases)]
            target = TARGETS[index % len(TARGETS)]
            todo_repo.create(con, f"{target} {phrase}", category_id=category["id"])


def _category(con, name):
    try:
        return category_repo.get_by_name(con, name)
    except Exception:
        return category_repo.create(con, name)


class JudgeTextTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()
        seed(self.con)
        self.model = auto_classify.train(self.con)

    def test_classified_when_evidence_is_clear(self):
        cases = (
            ("허브 취약점 점검 운영 배포", "운영"),
            ("기자 문의 회신 답변 편집국 질문", "문의"),
            ("스터디 강의 실습 학습 자료", "공부"),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                verdict = self.model.judge(body=text)
                self.assertEqual(verdict["category"], expected, verdict["reason"])
                self.assertTrue(verdict["evidence"], "근거 키워드를 보여줘야 사람이 판정을 검토할 수 있다")

    def test_title_counts_more_than_body(self):
        verdict = self.model.judge(title="취약점 점검 운영 배포", body="문의")
        self.assertEqual(verdict["category"], "운영")

    def test_left_unclassified_when_ambiguous(self):
        cases = (
            ("<task-notification> <task-id>b1</task-id>", "근거 부족"),  # 시스템 알림 — 아는 말이 없다
            ("가나다", "근거 부족"),
            ("허브 확인", "근거 부족"),  # 대상 이름만 있고 카테고리 근거가 없다
            ("기자 답변 서버 점검", "경합"),  # 두 카테고리 근거가 같은 세기로 걸린다
        )
        for text, reason in cases:
            with self.subTest(text=text):
                verdict = self.model.judge(body=text)
                self.assertIsNone(verdict["category"], verdict["reason"])
                self.assertIn(reason, verdict["reason"])

    def test_common_words_are_not_evidence(self):
        """모든 카테고리에 고루 나오는 말(대상 이름)은 근거 키워드에서 빠진다"""
        self.assertNotIn("허브", self.model.vocabulary)
        self.assertIn("취약점", self.model.vocabulary)

    def test_nothing_classified_until_enough_training(self):
        con = temp_db()
        seed(con, per_category=CLASSIFY_MIN_TRAINING // len(CORPUS) - 1)
        verdict = auto_classify.train(con).judge(body="허브 취약점 점검 운영 배포")
        self.assertIsNone(verdict["category"])
        self.assertIn("학습 부족", verdict["reason"])

    def test_spawn_boilerplate_is_cut(self):
        body = "기자 문의 회신\n\n큰 단계가 바뀔 때마다 운영 배포 취약점 점검 운영 배포"
        self.assertEqual(auto_classify.clean_body(body), "기자 문의 회신")


class SessionTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()
        seed(self.con)
        self.ops = category_repo.get_by_name(self.con, "운영")

    def _session(self, sid, prompt):
        session_repo.register(self.con, sid, cwd="/tmp")
        session_repo.set_last_prompt(self.con, sid, prompt)
        return session_repo.get(self.con, sid)

    def test_linking_todo_gives_its_category(self):
        todo = todo_repo.create(self.con, "아무 제목", category_id=self.ops["id"])
        self._session("s-link", "가나다")
        session_repo.link_todo(self.con, "s-link", todo["id"])
        self.assertEqual(session_repo.get(self.con, "s-link")["category_name"], "운영")

    def test_linking_does_not_override_existing_category(self):
        todo = todo_repo.create(self.con, "아무 제목", category_id=self.ops["id"])
        self._session("s-kept", "가나다")
        session_repo.classify(self.con, "s-kept", category_name="문의")
        session_repo.link_todo(self.con, "s-kept", todo["id"])
        self.assertEqual(session_repo.get(self.con, "s-kept")["category_name"], "문의")

    def test_stop_classifies_only_when_clear(self):
        self._session("s-clear", "허브 취약점 점검 운영 배포 해줘")
        self._session("s-vague", "가나다")
        auto_classify.auto_classify_session(self.con, "s-clear")
        auto_classify.auto_classify_session(self.con, "s-vague")
        self.assertEqual(session_repo.get(self.con, "s-clear")["category_name"], "운영")
        self.assertIsNone(session_repo.get(self.con, "s-vague")["category_id"])

    def test_stop_never_overrides_manual_classification(self):
        self._session("s-manual", "허브 취약점 점검 운영 배포 해줘")
        session_repo.classify(self.con, "s-manual", category_name="문의")
        self.assertIsNone(auto_classify.auto_classify_session(self.con, "s-manual"))
        self.assertEqual(session_repo.get(self.con, "s-manual")["category_name"], "문의")

    def test_batch_is_dry_run_by_default_and_apply_leaves_ambiguous(self):
        self._session("s-a", "기자 문의 회신 답변 편집국 질문")
        self._session("s-b", "가나다")
        report = auto_classify.run(self.con)
        self.assertIsNone(report["applied"])
        self.assertIsNone(session_repo.get(self.con, "s-a")["category_id"])
        verdicts = {item["id"]: item["category"] for item in report["items"]}
        self.assertCountEqual(verdicts.values(), ["문의", None])

        report = auto_classify.run(self.con, apply=True)
        self.assertEqual(report["applied"]["sessions"], 1)
        self.assertEqual(session_repo.get(self.con, "s-a")["category_name"], "문의")
        self.assertIsNone(session_repo.get(self.con, "s-b")["category_id"])


class SpawnTest(unittest.TestCase):
    def setUp(self):
        self.con = temp_db()
        seed(self.con)
        self.fallback = _category(self.con, SPAWN_FALLBACK_CATEGORY)

    def test_spawn_todo_goes_to_guessed_category_when_clear(self):
        todo = spawn_link.on_spawn(self.con, "sp-1", "보조1 | 허브 취약점 점검 운영 배포", None, 1, "")
        self.assertEqual(category_repo.get(self.con, todo["category_id"])["name"], "운영")
        # 워크스페이스는 여전히 모른다 — 세션이 분류하면 그곳으로 옮겨질 임시 자리로 남는다
        self.assertIn(spawn_link.PROVISIONAL_LINE, todo["note"])
        # 임시 자리 할일은 사람이 고른 카테고리가 아니라 세션에 넘기지 않는다
        self.assertIsNone(session_repo.get(self.con, "sp-1")["category_id"])

    def test_spawn_todo_stays_in_fallback_when_ambiguous(self):
        todo = spawn_link.on_spawn(self.con, "sp-2", "보조2 | 가나다 확인", None, 2, "")
        self.assertEqual(todo["category_id"], self.fallback["id"])

    def test_provisional_todos_are_not_training_data(self):
        before = auto_classify.train(self.con).size
        spawn_link.on_spawn(self.con, "sp-3", "보조3 | 가나다", None, 3, "")
        self.assertEqual(auto_classify.train(self.con).size, before)


class CliTest(unittest.TestCase):
    def setUp(self):
        self.path = temp_db_path()
        self._old = os.environ.get(DB_PATH_ENV)
        os.environ[DB_PATH_ENV] = self.path
        con = temp_db(self.path)
        seed(con)
        for sid, prompt in (("c-1", "기자 문의 회신 답변 편집국 질문"), ("c-2", "가나다")):
            session_repo.register(con, sid, cwd="/tmp")
            session_repo.set_last_prompt(con, sid, prompt)
        self.con = con

    def tearDown(self):
        if self._old is None:
            os.environ.pop(DB_PATH_ENV, None)
        else:
            os.environ[DB_PATH_ENV] = self._old

    def _run(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            code = dash.main(["auto-classify", *argv])
        self.assertEqual(code, 0)
        return out.getvalue()

    def test_dry_run_prints_counts_and_left_items_without_writing(self):
        text = self._run()
        self.assertIn("문의 1건", text)
        self.assertIn("미분류로 남김 1건", text)
        self.assertIn("근거 부족", text)
        self.assertIn("dry-run", text)
        self.assertIsNone(session_repo.get(self.con, "c-1")["category_id"])

    def test_apply_and_json(self):
        payload = json.loads(self._run("--json"))
        self.assertEqual(len(payload["items"]), 2)
        self.assertIn("적용: 세션 1건", self._run("--apply"))
        self.assertEqual(session_repo.get(self.con, "c-1")["category_name"], "문의")


if __name__ == "__main__":
    unittest.main()
