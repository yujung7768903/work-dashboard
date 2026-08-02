"""대시보드 할일 ↔ Google Tasks 양방향 동기화

규칙
- 제목과 완료 여부만 양방향. 양쪽이 다르면 수정 시각이 최신인 쪽이 이긴다
- note/precondition 은 내려보내기 전용. 한 칸짜리 notes 에 두 필드를 왕복시키면
  반드시 깨지므로, 폰에서 메모를 고쳐도 대시보드는 안 바뀐다
- 카테고리 하나가 구글 목록 하나. 폰에서 만든 태스크는 그 목록의 카테고리로 들어온다
- 삭제: 로컬에서 지운 할일은 원격에서도 지운다. 폰에서 지운 건 되살린다.
  단 완료된 할일은 되살리지 않는다 (폰의 '완료 항목 삭제'가 무덤을 파헤치면 안 됨)

구글 태스크에는 웹훅이 없어 이 함수를 주기적으로 부르는 것 말고는 방법이 없다
"""
import json
from datetime import datetime, timezone

from app.constants import (
    GTASKS_LIST_PREFIX,
    GTASKS_NOTES_MAX,
    GTASKS_SEEN_KEY,
    GTASKS_STATUS_DONE,
    GTASKS_STATUS_TODO,
    GTASKS_UNTITLED,
    STATUS_DONE,
    STATUS_TODO,
)
from app.db import meta_get, meta_set
from app.errors import DomainError
from app.repositories import categories as category_repo
from app.repositories import todos as todo_repo
from app.services import gtasks_api

ACTIONS = ("pushed", "pulled", "created_local", "created_remote", "deleted_remote", "skipped")
# dry-run 이라 아직 안 만든 목록. 첫 동기화 계획을 보여주려면 목록이 없어도 진행해야 한다
PENDING_LIST = "(아직 없는 목록)"


def sync(con, client=None, dry_run=False):
    """한 바퀴 돌고 무엇을 했는지 보고. dry_run 이면 아무것도 쓰지 않는다"""
    client = client if client is not None else gtasks_api.Client()
    report = {action: [] for action in ACTIONS}
    previous = _load_seen(con)
    seen = set()
    remote_lists = {row["id"]: row.get("title") for row in client.lists()}
    for category in category_repo.list_all(con):
        scoped = _scoped_todos(con, category["id"])
        list_id = _ensure_list(con, client, category, remote_lists, scoped, dry_run)
        if not list_id:
            continue
        _sync_list(con, client, category, list_id, scoped, previous, seen, report, dry_run)
    if not dry_run:
        _save_seen(con, seen)
    return report


def _sync_list(con, client, category, list_id, scoped, previous, seen, report, dry_run):
    remote = {} if list_id == PENDING_LIST else {t["id"]: t for t in client.tasks(list_id)}
    linked = {todo["google_task_id"]: todo for todo in scoped if todo["google_task_id"]}
    for task_id, task in remote.items():
        seen.add(task_id)
        todo = linked.get(task_id)
        if todo:
            _merge(con, client, list_id, todo, task, report, dry_run)
        elif task_id in previous:
            _drop_remote(client, list_id, task, report, dry_run)
            seen.discard(task_id)
        else:
            _create_local(con, category, task, report, dry_run)
    for todo in scoped:
        if todo["google_task_id"] in remote:
            continue
        if todo["google_task_id"] and todo["status"] == STATUS_DONE:
            continue  # 폰에서 완료 항목을 지운 것. 되살리면 무덤을 파헤치는 꼴
        _create_remote(con, client, list_id, todo, seen, report, dry_run)


def _merge(con, client, list_id, todo, task, report, dry_run):
    """양쪽에 다 있는 짝. 내용이 실제로 다를 때만 움직인다

    시각만 보면 우리가 방금 밀어넣은 것 때문에 원격이 늘 최신이라 무한 왕복이 된다.
    내용 비교를 먼저 두면 시계 오차와 메아리를 한 번에 피한다
    """
    desired = _remote_body(todo)
    same_title = (task.get("title") or "") == desired["title"]
    same_done = _remote_done(task) == (todo["status"] == STATUS_DONE)
    same_notes = (task.get("notes") or "") == desired["notes"]
    if same_title and same_done and same_notes:
        return
    if same_title and same_done:
        _patch(client, list_id, task, {"notes": desired["notes"]}, todo, report, dry_run)
        return
    if _local_newer(todo, task):
        _patch(client, list_id, task, desired, todo, report, dry_run)
    else:
        _pull(con, todo, task, report, dry_run)


def _pull(con, todo, task, report, dry_run):
    """폰이 이겼다. 제목과 완료 여부만 받아온다"""
    fields = {}
    if (task.get("title") or "") != todo["title"]:
        fields["title"] = task.get("title") or ""
    if _remote_done(task) != (todo["status"] == STATUS_DONE):
        fields["status"] = STATUS_DONE if _remote_done(task) else STATUS_TODO
    if not fields:
        return
    label = f"#{todo['id']} {task.get('title') or GTASKS_UNTITLED}"
    if dry_run:
        report["pulled"].append(label)
        return
    try:
        todo_repo.update(con, todo["id"], **fields)
    except DomainError as error:
        # 하위할일이 남아 완료 불가, 제목이 빈 문자열 등. 로컬 규칙이 이긴다
        report["skipped"].append(f"{label} — {error}")
        return
    report["pulled"].append(label)


def _patch(client, list_id, task, body, todo, report, dry_run):
    label = f"#{todo['id']} {todo['title']}"
    if not dry_run:
        client.patch(list_id, task["id"], body)
    report["pushed"].append(label)


def _create_remote(con, client, list_id, todo, seen, report, dry_run):
    label = f"#{todo['id']} {todo['title']}"
    report["created_remote"].append(label)
    if dry_run:
        return
    created = client.insert(list_id, _remote_body(todo))
    todo_repo.set_google_link(con, todo["id"], created["id"])
    # 이번 회차에 만든 것도 '봤다'에 넣어야 한다. 빠뜨리면 다음 회차가
    # '로컬에서 지운 태스크'로 오해해 방금 만든 걸 지운다
    seen.add(created["id"])


def _create_local(con, category, task, report, dry_run):
    """폰에서 새로 만든 태스크. 카테고리만 정해지고 워크스페이스는 미분류로 들어온다"""
    title = (task.get("title") or "").strip() or GTASKS_UNTITLED
    report["created_local"].append(f"{category['name']} / {title}")
    if dry_run:
        return
    todo = todo_repo.create(
        con, title=title, category_id=category["id"], note=task.get("notes") or None
    )
    todo_repo.set_google_link(con, todo["id"], task["id"])
    if _remote_done(task):
        todo_repo.update(con, todo["id"], status=STATUS_DONE)


def _drop_remote(client, list_id, task, report, dry_run):
    """지난 회차엔 있었는데 로컬에서 사라진 짝 = 대시보드에서 지운 할일"""
    report["deleted_remote"].append(task.get("title") or GTASKS_UNTITLED)
    if not dry_run:
        client.delete(list_id, task["id"])


def _ensure_list(con, client, category, remote_lists, scoped, dry_run):
    """카테고리에 붙은 목록 id. 없으면 제목으로 찾고 그래도 없으면 만든다"""
    stored = category.get("google_list_id")
    if stored and stored in remote_lists:
        return stored
    title = GTASKS_LIST_PREFIX + category["name"]
    for list_id, list_title in remote_lists.items():
        if list_title == title:
            if not dry_run:
                category_repo.set_google_list_id(con, category["id"], list_id)
            return list_id
    if not scoped:
        return None  # 빈 카테고리까지 목록을 만들어 폰을 어지럽히지 않는다
    if dry_run:
        return PENDING_LIST
    created = client.create_list(title)
    remote_lists[created["id"]] = title
    category_repo.set_google_list_id(con, category["id"], created["id"])
    return created["id"]


def _scoped_todos(con, category_id):
    """미완료 전부 + 이미 붙어 있는 완료분. 오래된 완료 이력까지 폰에 밀어넣지 않는다"""
    return [
        todo
        for todo in todo_repo.list_by_category(con, category_id)
        if todo["status"] != STATUS_DONE or todo["google_task_id"]
    ]


def _remote_body(todo):
    return {
        "title": todo["title"],
        "notes": _notes(todo),
        "status": GTASKS_STATUS_DONE if todo["status"] == STATUS_DONE else GTASKS_STATUS_TODO,
    }


def _notes(todo):
    """상한을 넘겨 보내면 호출 전체가 400 이라 잘라서 보낸다"""
    parts = []
    if todo.get("precondition"):
        parts.append(f"착수 조건: {todo['precondition']}")
    if todo.get("note"):
        parts.append(todo["note"])
    return "\n\n".join(parts)[:GTASKS_NOTES_MAX]


def _remote_done(task):
    return task.get("status") == GTASKS_STATUS_DONE


def _local_newer(todo, task):
    """동점이면 로컬이 이긴다 — 우리가 방금 민 것일 가능성이 높다.

    두 시각은 서로 다른 시계에서 온다(우리 기계 vs 구글 서버). 내용이 다를 때만
    여기까지 오므로 초 단위 오차는 실질적으로 문제가 되지 않는다
    """
    return _parsed(todo["updated_at"]) >= _parsed(task.get("updated"))


def _parsed(text):
    """초 단위로 잘라서 비교한다. 구글의 Z 표기는 3.9 의 fromisoformat 이 못 읽는다

    db.now() 가 초까지만 적는데 구글은 밀리초까지 준다. 그대로 비교하면 방금 밀어넣은
    태스크(:13.496)가 같은 초에 고친 로컬(:13.000)보다 최신으로 보여, 로컬 수정이
    다음 회차에 조용히 되돌려진다. 우리 해상도가 1초이므로 그 아래는 잡음으로 버린다
    """
    if not text:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(microsecond=0)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def _load_seen(con):
    raw = meta_get(con, GTASKS_SEEN_KEY)
    try:
        return set(json.loads(raw)) if raw else set()
    except (TypeError, ValueError):
        return set()


def _save_seen(con, seen):
    """다음 회차가 '폰에서 새로 만든 것'과 '로컬에서 지운 것'을 가르는 유일한 근거"""
    meta_set(con, GTASKS_SEEN_KEY, json.dumps(sorted(seen)))
