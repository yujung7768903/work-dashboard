"""미분류 자동 분류. 카테고리 없는 세션과, 매니저 spawn 이 임시 카테고리로 만든 할일을 근거로 분류한다.

규칙은 손으로 정한 키워드가 아니라 사용자가 이미 분류해 둔 할일에서 배운 카테고리별 근거 키워드다.
11-18 실측(할일 374·세션 10, 하나씩 빼고 나머지로 맞히기): 손 키워드 규칙은 분류한 것 중 57% 만 맞았고,
근거 키워드를 고르고 배운 방식은 할일 94%·세션 90% 맞았다(constants 의 기준). 사용자의 카테고리는 경계가 사람마다 다르다
(같은 작업 대시보드 일을 개발 35건·개발환경 개선 34건으로 나눔) — 그 사람의 습관을 따르는 쪽이 맞는다.

근거는 셋이다 — 세게 믿는 순서로:
1) 연결 할일: 세션이 이미 잡은 할일의 카테고리. 사람이(또는 세션이) 정한 자리라 그대로 따른다
2) 본문: 제목·첫 지시·note 를 배운 근거 키워드로 점수 매긴다. 제목은 두 번 센다
3) 위치(cwd)는 쓰지 않는다 — 레포마다 카테고리가 섞여 있다(manager 레포 세션은 6개 카테고리)

애매함 기준 — 아래면 분류하지 않고 미분류로 남긴다. 틀리게 붙은 분류는 사람이 다시 찾아 고쳐야 하지만
미분류는 미분류 칸에서 바로 보인다. 그래서 모르면 남긴다:
- 근거 부족: 배운 키워드가 CLASSIFY_MIN_EVIDENCE 개 미만 걸림
- 경합: 1위와 2위 점수(로그 우도) 차를 글의 키워드 수로 나눈 값이 CLASSIFY_MIN_MARGIN 미만
- 학습 부족: 분류된 할일이 CLASSIFY_MIN_TRAINING 건 미만이면 아무것도 분류하지 않는다

자동 분류는 비어 있는 자리만 채운다. 사람·세션이 정한 분류는 덮지 않는다
"""
import math
import re
from collections import Counter, defaultdict

from app.constants import (
    AUTO_CLASSIFY_BODY_CHARS,
    CLASSIFY_EVIDENCE_SHOWN,
    CLASSIFY_KEYWORD_MIN_DOCS,
    CLASSIFY_KEYWORD_SHARE,
    CLASSIFY_MIN_EVIDENCE,
    CLASSIFY_MIN_MARGIN,
    CLASSIFY_MIN_TRAINING,
    CLASSIFY_SMOOTHING,
    SPAWN_PROVISIONAL_MARK,
    SPAWN_TODO_MARK,
)
from app.db import now, transaction
from app.errors import NotFound
from app.repositories import categories as category_repo
from app.repositories import todos as todo_repo
from app.services import transcript

SOURCE_TODO = "연결 할일"
SOURCE_TEXT = "본문"
# spawn 이 임시 카테고리로 만든 할일의 표지. 임시 자리는 사람이 고른 카테고리가 아니라 학습에서 뺀다
# (넣으면 대체 카테고리가 모든 보조 일을 끌어간다)
PROVISIONAL_MARK = SPAWN_PROVISIONAL_MARK  # 임시 자리 줄의 머리 — 워크스페이스가 있던 때 줄도 이것으로 시작한다
# 매니저 spawn 지시문은 본문 뒤에 공통 안내(진행률·결정·권한·보고 방법)가 붙는다. 그 안내의
# 말이 모든 보조 세션을 같은 카테고리로 끌고 가므로 첫 표지에서 자른다
BOILERPLATE_MARKERS = (
    "\n\n큰 단계가 바뀔 때마다",
    "\n\n일의 실제 산출물",
    "\n\n사용자 결정이 필요하면",
)
WORD = re.compile(r"[A-Za-z][A-Za-z0-9_.-]+|[가-힣]+")
HANGUL = re.compile(r"[가-힣]+")
# 어절 끝 조사·어미. 긴 것부터 — '에서는' 을 '는' 만 떼고 '에서' 를 남기지 않게
ENDINGS = re.compile(
    r"(으로는|에서는|에게서|이라도|해줘요|해줘|해주세요|합니다|했는데|했어|하는데|하는|하고|하면|하지|한다|해서|했다|"
    r"된다|되는|되면|돼서|있는|없는|있다|없다|에서|에게|으로|부터|까지|처럼|보다|이랑|라고|이고|이다|"
    r"을|를|이|가|은|는|에|의|로|와|과|도|만|랑|야|지|다|고|서|면|게|요)$"
)


def tokens(text):
    """근거 키워드 후보. 영문 단어는 소문자로, 한글 어절은 뒤에 붙은 조사·어미를 떼어 —
    '배포를'·'배포가'·'배포해줘' 가 모두 '배포' 로 같은 근거가 된다. 떼고 한 글자만 남으면 버린다.
    두 글자 조각으로 쪼개면 '는다'·'않는' 같은 어미 조각이 근거로 섞여 긴 지시문을 끌고 간다(11-18 dry-run)"""
    found = set()
    for word in WORD.findall(text or ""):
        word = word.lower()
        if HANGUL.fullmatch(word):
            word = ENDINGS.sub("", word)
            if len(word) < 2:
                continue
        found.add(word)
    return found


def clean_body(text):
    """지시문·note 에서 판정에 쓸 부분만 — 공통 안내를 자르고 앞부분만 남긴다"""
    text = text or ""
    for marker in BOILERPLATE_MARKERS:
        cut = text.find(marker)
        if cut > 0:
            text = text[:cut]
    return text[:AUTO_CLASSIFY_BODY_CHARS]


class Model:
    """카테고리별 근거 키워드 빈도. 다항 나이브 베이즈 — 키워드마다 '이 카테고리에서 얼마나
    자주 쓰였나'를 세고, 판정할 글의 키워드로 카테고리별 로그 우도를 더한다"""

    def __init__(self, examples):
        self.docs = Counter()
        presence = defaultdict(Counter)  # 카테고리별로 그 말이 나온 할일 수
        raw = defaultdict(Counter)
        for category, words in examples:
            self.docs[category] += 1
            raw[category].update(words)
            presence[category].update(set(words))
        self.vocabulary = _evidence_words(self.docs, presence)
        self.counts = {
            category: Counter({w: n for w, n in counter.items() if w in self.vocabulary})
            for category, counter in raw.items()
        }
        self.totals = {category: sum(counter.values()) for category, counter in self.counts.items()}

    @property
    def size(self):
        return sum(self.docs.values())

    def judge(self, title="", body=""):
        if self.size < CLASSIFY_MIN_TRAINING:
            return _left(SOURCE_TEXT, f"학습 부족(분류된 할일 {self.size}건)")
        words = Counter(tokens(title)) + Counter(tokens(title)) + Counter(tokens(body))
        known = {word: n for word, n in words.items() if word in self.vocabulary}
        if len(known) < CLASSIFY_MIN_EVIDENCE:
            return _left(SOURCE_TEXT, f"근거 부족(아는 키워드 {len(known)}개)")
        scores = {category: self._score(category, known) for category in self.docs}
        ranked = sorted(scores.items(), key=lambda item: -item[1])
        (top, top_score), (second, second_score) = ranked[0], ranked[1]
        # 점수 차는 글이 길수록 커진다(키워드마다 더해짐). 긴 지시문이 근거 없이 확신하지 않게
        # 글의 키워드 수로 나눠 '키워드 하나당 1위가 얼마나 앞서나'로 본다
        margin = (top_score - second_score) / sum(words.values())
        evidence = self._evidence(top, second, known)
        if margin < CLASSIFY_MIN_MARGIN:
            return {
                **_left(SOURCE_TEXT, f"경합({top} vs {second}, 차 {margin:.2f})"),
                "evidence": evidence,
            }
        return {
            "source": SOURCE_TEXT,
            "category": top,
            "reason": f"{top} (2위 {second}, 차 {margin:.2f})",
            "evidence": evidence,
            "margin": margin,
        }

    def _score(self, category, known):
        prior = math.log(self.docs[category] / self.size)
        denominator = self.totals[category] + CLASSIFY_SMOOTHING * len(self.vocabulary)
        return prior + sum(
            n * math.log((self.counts[category][word] + CLASSIFY_SMOOTHING) / denominator)
            for word, n in known.items()
        )

    def _evidence(self, top, second, known):
        """1위를 2위보다 앞세운 키워드 — 사람이 판정 근거를 읽을 수 있게 보여준다"""
        def lift(word):
            mine = (self.counts[top][word] + CLASSIFY_SMOOTHING) / (self.totals[top] + 1)
            theirs = (self.counts[second][word] + CLASSIFY_SMOOTHING) / (self.totals[second] + 1)
            return math.log(mine / theirs)

        ranked = sorted((word for word in known if lift(word) > 0), key=lift, reverse=True)
        return ranked[:CLASSIFY_EVIDENCE_SHOWN]


def _evidence_words(docs, presence):
    """근거 키워드로 쓸 말만 고른다. 조사·어미 조각('의'·'는다'·'않는')은 어느 카테고리에나 고루 나와
    근거가 못 되는데, 그대로 두면 note 가 긴 카테고리로 긴 지시문을 끌고 간다(11-18 dry-run 에서
    매니저 세션 163건이 그 말들로 '개발'이 됨). 카테고리 크기를 맞춘 출현 비율에서 한 카테고리가
    CLASSIFY_KEYWORD_SHARE 이상을 차지하고, CLASSIFY_KEYWORD_MIN_DOCS 건 이상에 나온 말만 남긴다"""
    words = set()
    for counter in presence.values():
        words.update(counter)
    kept = set()
    for word in words:
        total_docs = sum(presence[category][word] for category in docs)
        if total_docs < CLASSIFY_KEYWORD_MIN_DOCS:
            continue
        rates = [presence[category][word] / docs[category] for category in docs]
        if max(rates) / sum(rates) >= CLASSIFY_KEYWORD_SHARE:
            kept.add(word)
    return kept


def _left(source, reason):
    return {"source": source, "category": None, "reason": reason, "evidence": [], "margin": 0.0}


def train(con, exclude_todo_ids=()):
    """사람·세션이 정한 할일 카테고리로 학습. 임시 자리 할일은 뺀다"""
    rows = con.execute(
        "SELECT t.id, t.title, t.note, c.name AS category FROM todos t"
        " JOIN categories c ON c.id = t.category_id"
    ).fetchall()
    examples = []
    for row in rows:
        note = row["note"] or ""
        if row["id"] in exclude_todo_ids or PROVISIONAL_MARK in note:
            continue
        title = row["title"] or ""
        words = Counter(tokens(title)) + Counter(tokens(title)) + Counter(tokens(clean_body(note)))
        examples.append((row["category"], words))
    return Model(examples)


# ── 세션 ────────────────────────────────────────────────────────────────


def judge_session(con, session, model=None, prompts=None):
    """세션 한 건 판정. 연결 할일이 있으면 그 카테고리, 없으면 첫 지시 본문으로"""
    todo = _linked_todo(con, session)
    if todo and PROVISIONAL_MARK not in (todo["note"] or ""):
        category = category_repo.get(con, todo["category_id"])["name"]
        return {
            "source": SOURCE_TODO,
            "category": category,
            "reason": f"할일 #{todo['id']} 의 카테고리",
            "evidence": [todo["title"]],
            "margin": None,
        }
    if prompts is None:
        prompts = transcript.user_prompts(session["claude_session_id"])
    body = clean_body(prompts[0]) if prompts else ""
    if not body:
        last = session.get("last_prompt") or ""
        body = "" if last.startswith("<") else clean_body(last)
    if todo:
        # 임시 자리 할일도 제목은 이 세션이 무엇을 하는지 가장 짧게 말한다
        return (model or train(con)).judge(title=todo["title"], body=body)
    return (model or train(con)).judge(body=body)


def plan_sessions(con, model=None):
    """카테고리 없는 세션(프롬프트가 한 번이라도 있던 것) 전부의 판정 → [(세션, 판정)]"""
    model = model or train(con)
    rows = con.execute(
        "SELECT * FROM sessions WHERE category_id IS NULL AND COALESCE(last_prompt,'') <> ''"
        " ORDER BY id"
    ).fetchall()
    return [(dict(row), judge_session(con, dict(row), model)) for row in rows]


def auto_classify_session(con, claude_session_id):
    """턴이 끝날 때(Stop 훅) 아직 미분류인 세션을 확실할 때만 분류한다 → 판정 또는 None.

    세션 시작(SessionStart)에는 아직 지시가 없어 근거가 없다. 첫 턴 동안은 세션이 스스로
    분류하도록 두고(분류 지시가 주입된다), 그 턴이 끝나도 비어 있을 때만 채운다
    """
    row = con.execute(
        "SELECT * FROM sessions WHERE claude_session_id=?", (claude_session_id,)
    ).fetchone()
    if not row or row["category_id"] or not (row["last_prompt"] or ""):
        return None
    verdict = judge_session(con, dict(row))
    if verdict["category"]:
        _set_session_category(con, row["id"], verdict["category"])
    return verdict


def apply_sessions(con, plan):
    """plan_sessions 결과 중 분류된 것만 적는다 → 적은 건수. 그사이 사람이 분류했으면 건너뛴다"""
    return sum(
        1
        for session, verdict in plan
        if verdict["category"] and _set_session_category(con, session["id"], verdict["category"])
    )


def _set_session_category(con, session_row_id, category_name):
    try:
        category_id = category_repo.get_by_name(con, category_name)["id"]
    except NotFound:
        return False
    with transaction(con):
        cursor = con.execute(
            "UPDATE sessions SET category_id=? WHERE id=? AND category_id IS NULL",
            (category_id, session_row_id),
        )
    return cursor.rowcount > 0


def _linked_todo(con, session):
    row = con.execute(
        "SELECT todo_id FROM session_todos WHERE session_id=?"
        " ORDER BY created_at DESC, todo_id DESC LIMIT 1",
        (session["id"],),
    ).fetchone()
    return todo_repo.get(con, row["todo_id"]) if row else None


# ── 할일 ────────────────────────────────────────────────────────────────


def category_for_new_todo(con, title, detail=""):
    """새 할일을 둘 카테고리 판정. category 가 None 이면 부르는 쪽이 임시 자리를 쓴다"""
    return train(con).judge(title=title, body=clean_body(detail))


def plan_provisional_todos(con, model=None):
    """spawn 이 임시 카테고리로 만든 할일(아직 안 끝난 것)의 판정 → [(할일, 판정)]"""
    model = model or train(con)
    rows = con.execute(
        "SELECT * FROM todos WHERE status <> 'done'"
        " AND note LIKE ? AND note LIKE ? ORDER BY id",
        (f"{SPAWN_TODO_MARK}%", f"%{PROVISIONAL_MARK}%"),
    ).fetchall()
    return [
        (dict(row), model.judge(title=row["title"], body=clean_body(row["note"])))
        for row in rows
    ]


def apply_provisional_todos(con, plan):
    """임시 카테고리 할일 중 분류된 것의 카테고리만 바꾼다 → 바꾼 건수.
    임시 표지는 남긴다 — 세션이 분류되면 그 카테고리로 다시 옮겨질 수 있게"""
    count = 0
    for todo, verdict in plan:
        if not verdict["category"]:
            continue
        try:
            category_id = category_repo.get_by_name(con, verdict["category"])["id"]
        except NotFound:
            continue
        if category_id == todo["category_id"]:
            continue
        with transaction(con):
            cursor = con.execute(
                "UPDATE todos SET category_id=?, updated_at=? WHERE id=?"
                " AND note LIKE ?",
                (category_id, now(), todo["id"], f"%{PROVISIONAL_MARK}%"),
            )
        count += cursor.rowcount
    return count


def run(con, apply=False):
    """일괄 분류. apply=False(기본)면 판정만 돌려준다 → 보고 dict"""
    model = train(con)
    sessions = plan_sessions(con, model)
    todos = plan_provisional_todos(con, model)
    report = {
        "training_size": model.size,
        "items": [_session_row(session, verdict) for session, verdict in sessions]
        + [_todo_row(todo, verdict) for todo, verdict in todos],
        "applied": None,
    }
    if apply:
        report["applied"] = {
            "sessions": apply_sessions(con, sessions),
            "todos": apply_provisional_todos(con, todos),
        }
    return report


def _session_row(session, verdict):
    return {
        "kind": "session",
        "id": session["id"],
        "state": session["state"],
        "cwd": session["cwd"],
        "text": " ".join((session.get("last_prompt") or "").split())[:80],
        **verdict,
    }


def _todo_row(todo, verdict):
    return {
        "kind": "todo",
        "id": todo["id"],
        "state": todo["status"],
        "cwd": None,
        "text": todo["title"],
        **verdict,
    }
