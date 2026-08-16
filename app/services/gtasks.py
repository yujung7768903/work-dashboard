"""대시보드 ↔ Google Tasks 양방향 동기화

구조
    구글 목록      = 카테고리
     └ 최상위 태스크 = 워크스페이스
        └ 하위 태스크 = 그 워크스페이스의 할일
구글은 1단계 중첩만 허용하므로 이 세 층이 정확히 들어맞는다.

규칙
- 제목과 완료 여부만 양방향. 양쪽이 다르면 수정 시각이 최신인 쪽이 이긴다
- notes 는 내려보내기 전용. 한 칸짜리 notes 에 여러 필드를 왕복시키면 반드시 깨지므로,
  폰에서 메모를 고쳐도 대시보드는 안 바뀐다
- 워크스페이스가 없는 할일은 최상위로 올린다. 그 최상위는 링크가 남으므로 다음 회차에
  '이미 짝이 있는 것'으로 걸러진다 — 짝 없는 최상위만 워크스페이스로 받으므로 수가
  회차마다 늘어나지 않는다
- 삭제: 대시보드에서 지우면 구글에서도 지운다. 폰에서 지운 미완료는 대시보드에서도
  지우고, **완료된 것은 그대로 둔다** — 구글 앱의 '완료된 항목 삭제' 한 번으로 완료
  기록이 통째로 사라지면 안 되기 때문이다
- 목록(카테고리)은 여기서 만들지 않는다. gtasks_setup 이 켤 때 한 번 맞춘다

구글 태스크에는 웹훅이 없어 이 함수를 주기적으로 부르는 것 말고는 방법이 없다
"""
import json
from datetime import datetime, timezone

from app.constants import (
    GTASKS_ERROR_EXPIRED,
    GTASKS_ERROR_NO_AUTH,
    GTASKS_NEED_CONNECT,
    GTASKS_NOTES_MAX,
    GTASKS_SEEN_KEY,
    GTASKS_STATUS_DONE,
    GTASKS_STATUS_TODO,
    GTASKS_UNTITLED,
    STATUS_DONE,
    STATUS_TODO,
    WORKSPACE_ACTIVE,
)
from app.db import meta_get, meta_set
from app.errors import DomainError, Validation
from app.repositories import categories as category_repo
from app.repositories import gtasks_state
from app.repositories import todos as todo_repo
from app.repositories import workspaces as workspace_repo
from app.services import gtasks_api

ACTIONS = (
    "pushed",
    "pulled",
    "created_local",
    "created_remote",
    "deleted_local",
    "deleted_remote",
    "skipped",
)
WORKSPACE_DONE = "done"
# 워크스페이스 본문에 실어 보내는 순서. 폰에서는 이 네 줄이 착수 판단의 전부다
CONTEXT_LABELS = (
    ("배경", "background"),
    ("목적", "purpose"),
    ("목표", "goal"),
    ("고려사항", "considerations"),
)


def run(con, dry_run=False):
    """설정을 보고 도는 입구. cron 과 웹이 같이 쓴다. 꺼져 있으면 None

    실패해도 enabled 를 내리지 않는다 — 와이파이가 한 번 끊겼다고 연동이 꺼지면
    사용자가 그 사실을 모른 채 며칠을 보낸다. 사유만 남기고 화면이 ⚠ 로 알린다
    """
    if not gtasks_state.state(con)["enabled"]:
        return None
    try:
        report = sync(con, dry_run=dry_run)
    except DomainError as error:
        gtasks_state.record_error(con, _reason(error))
        raise
    if not dry_run:
        gtasks_state.record_success(con)
    return report


def _reason(error):
    """⚠ 옆에 한 줄로 보일 사유. 원문은 길고 영어가 섞여 있어 그대로 못 쓴다"""
    text = str(error)
    if "invalid_grant" in text or "unauthorized_client" in text:
        return GTASKS_ERROR_EXPIRED
    if "인증 정보 없음" in text or "빠진 항목" in text:
        return GTASKS_ERROR_NO_AUTH
    return text


def _guided_client():
    """인증 전이면 파일 경로가 박힌 원문 대신 다음에 누를 것을 알려준다"""
    if not gtasks_api.stored_client().get("refresh_token"):
        raise Validation(GTASKS_NEED_CONNECT)
    return gtasks_api.Client()


def sync(con, client=None, dry_run=False):
    """한 바퀴 돌고 무엇을 했는지 보고. dry_run 이면 아무것도 쓰지 않는다"""
    client = client if client is not None else _guided_client()
    report = {action: [] for action in ACTIONS}
    previous = _load_seen(con)
    seen = set()
    for category in category_repo.list_all(con):
        if not category.get("gtasks_enabled") or not category.get("google_list_id"):
            continue  # 꺼져 있거나 아직 목록을 안 맞춘 카테고리
        _sync_list(con, client, category, previous, seen, report, dry_run)
    if not dry_run:
        _save_seen(con, seen)
    return report


def _sync_list(con, client, category, previous, seen, report, dry_run):
    list_id = category["google_list_id"]
    remote = {task["id"]: task for task in client.tasks(list_id)}
    spaces = _scoped_workspaces(con, category["id"])
    todos = _scoped_todos(con, category["id"])
    linked_space = {s["google_task_id"]: s for s in spaces if s["google_task_id"]}
    linked_todo = {t["google_task_id"]: t for t in todos if t["google_task_id"]}

    seen.update(remote)
    dropped = set()
    # 최상위를 먼저 본다. 최상위를 지우면 구글이 하위까지 함께 지우므로,
    # 하위를 먼저 처리하면 방금 사라질 태스크에 대고 수정을 날리게 된다
    for task_id, task in sorted(remote.items(), key=lambda pair: bool(pair[1].get("parent"))):
        if task_id in dropped:
            continue
        space = linked_space.get(task_id)
        if space:
            _merge_space(con, client, list_id, space, task, report, dry_run)
            continue
        todo = linked_todo.get(task_id)
        if todo:
            _merge_todo(con, client, list_id, todo, task, report, dry_run)
            continue
        if task_id in previous:
            # 지난 회차엔 짝이 있었는데 사라졌다 = 대시보드에서 지운 것
            _drop_remote(con, client, list_id, task, remote, linked_todo,
                         seen, dropped, report, dry_run)
            continue
        _create_local(con, category, linked_space, task, report, dry_run)

    # 워크스페이스를 먼저 올려야 그 아래 할일이 붙을 parent id 가 생긴다
    for space in spaces:
        _push_space(con, client, list_id, space, remote, linked_space, previous, seen,
                    report, dry_run)
    for todo in todos:
        _push_todo(con, client, list_id, todo, remote, linked_space, previous, seen,
                   report, dry_run)


# ── 양쪽에 다 있는 짝 ────────────────────────────────────────────────────────


def _merge_space(con, client, list_id, space, task, report, dry_run):
    desired = _space_body(space)
    done = space["status"] == WORKSPACE_DONE
    if _same(task, desired, done):
        return
    if _notes_only(task, desired, done):
        _patch(client, list_id, task, {"notes": desired["notes"]}, space["name"], report, dry_run)
        return
    if _local_newer(space, task):
        _patch(client, list_id, task, desired, space["name"], report, dry_run)
        return
    _pull_space(con, space, task, report, dry_run)


def _merge_todo(con, client, list_id, todo, task, report, dry_run):
    """내용이 실제로 다를 때만 움직인다

    시각만 보면 우리가 방금 밀어넣은 것 때문에 원격이 늘 최신이라 무한 왕복이 된다.
    내용 비교를 먼저 두면 시계 오차와 메아리를 한 번에 피한다
    """
    desired = _todo_body(todo)
    done = todo["status"] == STATUS_DONE
    if _same(task, desired, done):
        return
    if _notes_only(task, desired, done):
        _patch(client, list_id, task, {"notes": desired["notes"]}, todo["title"], report, dry_run)
        return
    if _local_newer(todo, task):
        _patch(client, list_id, task, desired, todo["title"], report, dry_run)
        return
    _pull_todo(con, todo, task, report, dry_run)


def _same(task, desired, done):
    return (
        (task.get("title") or "") == desired["title"]
        and _remote_done(task) == done
        and (task.get("notes") or "") == desired["notes"]
    )


def _notes_only(task, desired, done):
    """notes 만 다르다. 내려보내기 전용이라 시각을 보지 않고 그대로 민다"""
    return (task.get("title") or "") == desired["title"] and _remote_done(task) == done


def _pull_space(con, space, task, report, dry_run):
    fields = {}
    title = task.get("title") or ""
    if title and title != space["name"]:
        fields["name"] = title
    remote_done = _remote_done(task)
    if remote_done != (space["status"] == WORKSPACE_DONE):
        # 완료를 풀면 active 로 돌아온다 — 폰에는 paused 에 해당하는 표현이 없다
        fields["status"] = WORKSPACE_DONE if remote_done else WORKSPACE_ACTIVE
    _apply_pull(con, workspace_repo, space["id"], fields, f"[{space['name']}]", report, dry_run)


def _pull_todo(con, todo, task, report, dry_run):
    fields = {}
    title = task.get("title") or ""
    if title and title != todo["title"]:
        fields["title"] = title
    remote_done = _remote_done(task)
    if remote_done != (todo["status"] == STATUS_DONE):
        # 폰에는 doing 이 없다. 완료를 풀면 doing 이었어도 todo 로 내려온다
        fields["status"] = STATUS_DONE if remote_done else STATUS_TODO
    _apply_pull(con, todo_repo, todo["id"], fields, f"#{todo['id']} {todo['title']}", report, dry_run)


def _apply_pull(con, repo, row_id, fields, label, report, dry_run):
    """폰이 이겼다. 로컬 규칙에 막히면 건너뛰고 보고한다 — 로컬 규칙이 이긴다"""
    if not fields:
        return
    if dry_run:
        report["pulled"].append(label)
        return
    try:
        repo.update(con, row_id, **fields)
    except DomainError as error:
        report["skipped"].append(f"{label} — {error}")
        return
    report["pulled"].append(label)


def _patch(client, list_id, task, body, label, report, dry_run):
    if not dry_run:
        client.patch(list_id, task["id"], body)
    report["pushed"].append(label)


# ── 한쪽에만 있는 것 ─────────────────────────────────────────────────────────


def _create_local(con, category, linked_space, task, report, dry_run):
    """폰에서 새로 만든 태스크. 구조를 그대로 받는다 — 최상위는 워크스페이스, 하위는 그 할일

    우리가 올린 것은 링크가 남아 위에서 이미 걸러졌다. 여기까지 온 최상위는 폰에서
    새로 만든 것이므로 승격시켜도 회차마다 늘어나지 않는다
    """
    title = (task.get("title") or "").strip() or GTASKS_UNTITLED
    if not task.get("parent"):
        _create_space(con, category, linked_space, task, title, report, dry_run)
        return
    # 부모가 워크스페이스면 그 소속으로. 아니면(카테고리 직속 할일의 자식) 직속으로 둔다
    parent = linked_space.get(task.get("parent"))
    where = f"{category['name']}" + (f" / [{parent['name']}]" if parent else "")
    report["created_local"].append(f"{where} / {title}")
    if dry_run:
        return
    todo = todo_repo.create(
        con,
        title=title,
        category_id=category["id"],
        workspace_id=parent["id"] if parent else None,
        note=task.get("notes") or None,
    )
    todo_repo.set_google_link(con, todo["id"], task["id"])
    if _remote_done(task):
        todo_repo.update(con, todo["id"], status=STATUS_DONE)


def _create_space(con, category, linked_space, task, title, report, dry_run):
    """최상위 태스크 하나가 워크스페이스 하나.

    같은 회차의 하위가 이 워크스페이스를 부모로 찾을 수 있게 linked_space 에 바로 넣는다 —
    최상위를 먼저 도는 정렬이 이걸 전제로 한다
    """
    report["created_local"].append(f"{category['name']} / [{title}]")
    if dry_run:
        return
    space = workspace_repo.create(con, category["id"], title)
    workspace_repo.set_google_link(con, space["id"], task["id"])
    linked_space[task["id"]] = space
    if _remote_done(task):
        workspace_repo.update(con, space["id"], status=WORKSPACE_DONE)


def _push_space(con, client, list_id, space, remote, linked_space, previous, seen, report, dry_run):
    task_id = space["google_task_id"]
    if task_id and task_id in remote:
        return
    if task_id and task_id in previous:
        _drop_local(con, workspace_repo, space["id"],
                    space["status"] == WORKSPACE_DONE, f"[{space['name']}]", report, dry_run)
        return
    report["created_remote"].append(f"[{space['name']}]")
    if dry_run:
        return
    created = client.insert(list_id, _space_body(space))
    workspace_repo.set_google_link(con, space["id"], created["id"])
    # 방금 만든 최상위도 부모 후보에 넣는다. 빠뜨리면 이 워크스페이스의 할일이
    # 첫 회차에 전부 최상위로 올라가고, 그 뒤로는 링크가 있어 영영 안 고쳐진다
    linked_space[created["id"]] = space
    seen.add(created["id"])


def _push_todo(con, client, list_id, todo, remote, linked_space, previous, seen, report, dry_run):
    task_id = todo["google_task_id"]
    if task_id and task_id in remote:
        return
    if task_id and task_id in previous:
        _drop_local(con, todo_repo, todo["id"], todo["status"] == STATUS_DONE,
                    f"#{todo['id']} {todo['title']}", report, dry_run)
        return
    # 링크는 있는데 지난 회차에 본 적이 없다 = 목록이나 계정이 바뀐 것.
    # 지운 증거가 없으므로 지우지 않고 다시 올린다 (아래에서 링크가 새 id 로 덮인다)
    report["created_remote"].append(f"#{todo['id']} {todo['title']}")
    if dry_run:
        return
    created = client.insert(list_id, _todo_body(todo), parent=_parent_id(todo, linked_space))
    todo_repo.set_google_link(con, todo["id"], created["id"])
    # 이번 회차에 만든 것도 '봤다'에 넣어야 한다. 빠뜨리면 다음 회차가
    # '대시보드에서 지운 태스크'로 오해해 방금 만든 걸 지운다
    seen.add(created["id"])


def _parent_id(todo, linked_space):
    """워크스페이스에 속하면 그 최상위 태스크의 자식으로. 없으면 최상위로 올린다"""
    for task_id, space in linked_space.items():
        if space["id"] == todo["workspace_id"]:
            return task_id
    return None


def _drop_local(con, repo, row_id, done, label, report, dry_run):
    """링크는 있는데 원격에 없다 = 폰에서 지운 것

    완료된 것은 지우지 않는다. 구글 앱의 '완료된 항목 삭제' 한 번에 완료 기록이
    통째로 날아가면 되돌릴 방법이 없다. 링크는 남겨 둔다 — 지우면 다음 회차가
    '아직 안 올린 것'으로 보고 무덤을 다시 파낸다
    """
    if done:
        return
    report["deleted_local"].append(label)
    if not dry_run:
        repo.delete(con, row_id)


def _drop_remote(con, client, list_id, task, remote, linked_todo, seen, dropped, report, dry_run):
    """지난 회차엔 있었는데 로컬에서 사라진 짝 = 대시보드에서 지운 것

    최상위를 지우면 구글이 하위까지 함께 지운다. 워크스페이스를 지울 때 소속 할일은
    미분류로 살아남는데, 그 할일들의 링크를 그대로 두면 다음 회차가 '폰에서 지웠다'로
    읽어 멀쩡한 할일을 지운다. 그래서 함께 사라질 하위의 링크를 미리 끊어 둔다 —
    다음 회차에 최상위 태스크로 다시 올라간다
    """
    report["deleted_remote"].append(task.get("title") or GTASKS_UNTITLED)
    seen.discard(task["id"])
    dropped.add(task["id"])
    for child_id, child in remote.items():
        if child.get("parent") != task["id"]:
            continue
        seen.discard(child_id)
        dropped.add(child_id)
        todo = linked_todo.get(child_id)
        if not todo:
            continue
        todo["google_task_id"] = None  # 아래 _push_todo 가 같은 판단을 하도록 함께 지운다
        if not dry_run:
            todo_repo.set_google_link(con, todo["id"], None)
    if not dry_run:
        client.delete(list_id, task["id"])


# ── 범위와 본문 ──────────────────────────────────────────────────────────────


def _scoped_workspaces(con, category_id):
    """미완료 전부 + 이미 붙어 있는 완료분. 오래된 완료 이력까지 폰에 밀어넣지 않는다"""
    return [
        space
        for space in workspace_repo.list_all(con)
        if space["category_id"] == category_id
        and (space["status"] != WORKSPACE_DONE or space["google_task_id"])
    ]


def _scoped_todos(con, category_id):
    return [
        todo
        for todo in todo_repo.list_by_category(con, category_id)
        if todo["status"] != STATUS_DONE or todo["google_task_id"]
    ]


def _space_body(space):
    return {
        "title": space["name"],
        "notes": _space_notes(space),
        "status": GTASKS_STATUS_DONE
        if space["status"] == WORKSPACE_DONE
        else GTASKS_STATUS_TODO,
    }


def _todo_body(todo):
    return {
        "title": todo["title"],
        "notes": _todo_notes(todo),
        "status": GTASKS_STATUS_DONE if todo["status"] == STATUS_DONE else GTASKS_STATUS_TODO,
    }


def _space_notes(space):
    parts = [f"{label}: {space[key]}" for label, key in CONTEXT_LABELS if space.get(key)]
    return "\n\n".join(parts)[:GTASKS_NOTES_MAX]


def _todo_notes(todo):
    """상한을 넘겨 보내면 호출 전체가 400 이라 잘라서 보낸다"""
    parts = []
    if todo.get("precondition"):
        parts.append(f"착수 조건: {todo['precondition']}")
    if todo.get("note"):
        parts.append(todo["note"])
    return "\n\n".join(parts)[:GTASKS_NOTES_MAX]


def _remote_done(task):
    return task.get("status") == GTASKS_STATUS_DONE


def _local_newer(row, task):
    """동점이면 로컬이 이긴다 — 우리가 방금 민 것일 가능성이 높다.

    두 시각은 서로 다른 시계에서 온다(우리 기계 vs 구글 서버). 내용이 다를 때만
    여기까지 오므로 초 단위 오차는 실질적으로 문제가 되지 않는다
    """
    return _parsed(row["updated_at"]) >= _parsed(task.get("updated"))


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
    """다음 회차가 '폰에서 새로 만든 것'과 '대시보드에서 지운 것'을 가르는 유일한 근거"""
    meta_set(con, GTASKS_SEEN_KEY, json.dumps(sorted(seen)))
