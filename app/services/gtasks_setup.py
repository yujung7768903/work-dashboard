"""연동을 켤 때 한 번 도는 카테고리 맞추기. 할일은 건드리지 않는다

동기화를 바로 시작하면 사용자가 무엇이 폰으로 넘어가는지 모르는 채 수십 건이 올라간다.
그래서 카테고리(=구글 목록)만 먼저 양쪽 합집합으로 맞추고 멈춘다 — 할일 동기화는
그 다음 gtasks-sync 가 한다.

짝은 **이름이 같은지**로만 맺는다. 접두어를 붙이면 폰에서 손으로 만든 목록이 영영
안 붙어 같은 이름이 둘씩 생긴다
"""
from app.constants import (
    GTASKS_ERROR_NO_AUTH,
    GTASKS_NEED_CONNECT,
    GTASKS_NO_SSL,
    GTASKS_SEEN_KEY,
)
from app.db import meta_set
from app.errors import DomainError, Validation
from app.repositories import categories as category_repo
from app.repositories import gtasks_state
from app.repositories import todos as todo_repo
from app.services import gtasks_api, gtasks_auth


def panel(con):
    """설정 화면이 한 번에 가져가는 모양. 네트워크를 치지 않는다

    렌더할 때마다 구글에 물어보면 설정 탭을 열 때마다 왕복이 생기고, 오프라인이면
    화면 자체가 늦게 뜬다. 연결 여부는 저장된 파일로, 문제는 마지막 동기화가 남긴
    사유로 판단한다
    """
    state = gtasks_state.state(con)
    stored = gtasks_api.stored_client()
    connected = bool(stored.get("refresh_token"))
    return {
        "state": state,
        "connected": connected,
        # 이미 받아 둔 자격증명이 있으면 안내와 입력 창을 건너뛰고 바로 동의로 간다.
        # client_secret 은 내려보내지 않는다 — 화면이 쓸 일이 없다
        "has_client": bool(stored.get("client_id") and stored.get("client_secret")),
        "client_id": stored.get("client_id") or "",
        "reason": _reason(state, connected),
        "categories": [
            {
                "id": category["id"],
                "name": category["name"],
                "enabled": bool(category["gtasks_enabled"]),
                "linked": bool(category["google_list_id"]),
            }
            for category in category_repo.list_all(con)
        ],
    }


def connect(con, client_id=None, client_secret=None):
    """구글 동의를 마치고 결과를 남긴다.

    실패 사유를 안 남기면 화면에는 '연결 안 됨' 만 남아, 사용자는 왜 또 연결해야 하는지
    알 수 없다 — 자격증명은 파일에 그대로 있으니 껐다 켠 탓으로 보이기까지 한다
    """
    try:
        gtasks_auth.authorize(client_id, client_secret)
    except DomainError as error:
        gtasks_state.record_error(con, str(error))
        raise
    gtasks_state.record_error(con, None)
    return panel(con)


def disconnect(con):
    """구글 계정 연결만 끊는다. 양쪽 데이터는 그대로 둔다

    링크(google_list_id·google_task_id)는 남긴다 — 같은 계정으로 다시 붙이면 그대로
    이어진다. 대신 '지난 회차에 본 태스크' 기록은 지운다. 그게 남아 있으면 다시 붙였을 때
    사라진 태스크를 '폰에서 지웠다'로 읽어 멀쩡한 할일을 지운다
    """
    gtasks_api.forget_refresh_token()
    meta_set(con, GTASKS_SEEN_KEY, "[]")
    gtasks_state.set_enabled(con, False)
    return panel(con)


def _reason(state, connected):
    """⚠ 옆에 한 줄. 막고 있는 것 중 가장 먼저 풀어야 하는 것을 고른다

    ssl 이 없으면 무엇을 눌러도 구글에 닿지 못한다. 자격증명을 다 입력한 뒤가 아니라
    화면을 여는 순간 알려줘야 헛수고를 안 한다
    """
    if not gtasks_api.HTTPS_READY:
        return GTASKS_NO_SSL
    if state["last_error"]:
        return state["last_error"]
    return None if connected else GTASKS_ERROR_NO_AUTH


def _connected():
    """refresh_token 까지 있어야 인증이 끝난 것이다. client_id 만으로는 못 부른다"""
    return bool(gtasks_api.stored_client().get("refresh_token"))


def _client_or_guide(client):
    """인증 전이면 다음에 누를 것을 알려준다.

    이 자리를 비워 두면 Client() 안의 load_config 가 파일 경로와 CLI 명령이 박힌
    원문을 던지고, 화면에는 그게 그대로 뜬다 — 버튼이 바로 아래 있는데도
    """
    if client is not None:
        return client
    if not _connected():
        raise Validation(GTASKS_NEED_CONNECT)
    return gtasks_api.Client()


def plan(con, client=None):
    """고를 수 있는 후보를 건수까지 붙여 돌려준다. 아무것도 쓰지 않는다

    건수가 핵심이다 — 이름이 같다고 같은 것이 아니다. 대시보드 '공부'(할일 2개)와
    폰의 '공부'(61개)가 별개인데도 이름만 보고 켜면 두 뭉치가 한 번에 합쳐진다
    """
    client = _client_or_guide(client)
    local = {}
    linked = set()
    for category in category_repo.list_all(con):
        local[category["name"]] = len(todo_repo.list_by_category(con, category["id"]))
        if category["google_list_id"]:
            linked.add(category["name"])
    remote = {}
    for row in client.lists():
        title = _title(row)
        # 폰에 같은 이름이 둘이면 먼저 만든 쪽만 센다 (apply 의 짝 맺기와 같은 기준)
        if title and title not in remote:
            remote[title] = len(client.tasks(row["id"]))
    # 대시보드 순서를 앞에 두고 폰에만 있는 것을 뒤에 붙인다 — 사용자가 익숙한 순서
    names = list(local) + [title for title in remote if title not in local]
    return {
        "items": [
            {
                "name": name,
                "local": local.get(name),
                "remote": remote.get(name),
                # 이미 맺어 둔 것은 화면에서 잠근다. 여기서 다시 켜면 카드에서 꺼 둔
                # 카테고리가 되살아난다 — 끄고 켜는 것은 카드 스위치의 몫이다
                "linked": name in linked,
            }
            for name in names
        ]
    }


def apply(con, chosen, client=None):
    """고른 것만 양쪽에 만들고 링크한 뒤 켠다. 할일은 손대지 않는다

    고르지 않은 것은 양쪽 어디도 건드리지 않는다 — 예전에는 합집합을 통째로 만들어,
    폰에만 있던 목록이 전부 대시보드 카테고리가 되고 그 반대도 일어났다

    켜기까지 여기서 하는 이유는 '맞췄지만 꺼져 있는' 중간 상태를 남기지 않기 위해서다
    """
    client = _client_or_guide(client)
    wanted = [name for name in (chosen or []) if name]
    if not wanted:
        raise Validation("연동할 카테고리를 하나 이상 골라 주세요")
    remote_by_title = {}
    for row in client.lists():
        title = _title(row)
        # 폰에 같은 이름이 둘이면 먼저 만든 쪽에 붙는다. 나중 것을 잡으면 회차마다 바뀐다
        if title and title not in remote_by_title:
            remote_by_title[title] = row["id"]
    known = {category["name"]: category for category in category_repo.list_all(con)}
    report = {"created_local": [], "created_remote": [], "linked": []}
    for name in wanted:
        category = known.get(name)
        if not category:
            category = category_repo.create(con, name)
            report["created_local"].append(name)
        list_id = remote_by_title.get(name)
        if not list_id:
            list_id = client.create_list(name)["id"]
            report["created_remote"].append(name)
        else:
            report["linked"].append(name)
        category_repo.set_google_list_id(con, category["id"], list_id)
        category_repo.set_gtasks_enabled(con, category["id"], True)
    gtasks_state.set_enabled(con, True)
    return report


def _title(row):
    return (row.get("title") or "").strip()
