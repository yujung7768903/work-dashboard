"""연동을 켤 때 한 번 도는 카테고리 맞추기. 할일은 건드리지 않는다

동기화를 바로 시작하면 사용자가 무엇이 폰으로 넘어가는지 모르는 채 수십 건이 올라간다.
그래서 카테고리(=구글 목록)만 먼저 양쪽 합집합으로 맞추고 멈춘다 — 할일 동기화는
그 다음 gtasks-sync 가 한다.

짝은 **이름이 같은지**로만 맺는다. 접두어를 붙이면 폰에서 손으로 만든 목록이 영영
안 붙어 같은 이름이 둘씩 생긴다
"""
from app.constants import GTASKS_ERROR_NO_AUTH, GTASKS_NEED_CONNECT, GTASKS_NO_SSL
from app.errors import Validation
from app.repositories import categories as category_repo
from app.repositories import gtasks_state
from app.services import gtasks_api


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
    """무엇을 만들지 미리 보여준다. 아무것도 쓰지 않는다

    화면이 이 결과를 그대로 팝업에 뿌리고 사용자의 확인을 받는다
    """
    client = _client_or_guide(client)
    local = [category["name"] for category in category_repo.list_all(con)]
    remote = [_title(row) for row in client.lists()]
    remote = [title for title in remote if title]
    local_set, remote_set = set(local), set(remote)
    return {
        "local": local,
        "remote": remote,
        # 대시보드 순서를 앞에 두고 폰에만 있는 것을 뒤에 붙인다 — 사용자가 익숙한 순서
        "union": local + [title for title in remote if title not in local_set],
        "create_local": [title for title in remote if title not in local_set],
        "create_remote": [name for name in local if name not in remote_set],
    }


def apply(con, client=None):
    """합집합대로 양쪽을 맞추고 링크를 남긴 뒤 연동을 켠다. 할일은 손대지 않는다

    켜기까지 여기서 하는 이유는 '맞췄지만 꺼져 있는' 중간 상태를 남기지 않기 위해서다.
    사용자가 확인 팝업에서 누른 '진행'이 곧 켜겠다는 뜻이다
    """
    client = _client_or_guide(client)
    remote_by_title = {}
    for row in client.lists():
        title = _title(row)
        # 폰에 같은 이름이 둘이면 먼저 만든 쪽에 붙는다. 나중 것을 잡으면 회차마다 바뀐다
        if title and title not in remote_by_title:
            remote_by_title[title] = row["id"]
    report = {"created_local": [], "created_remote": [], "linked": []}
    known = {category["name"] for category in category_repo.list_all(con)}
    for title in remote_by_title:
        if title in known:
            continue
        category_repo.create(con, title)
        report["created_local"].append(title)
    for category in category_repo.list_all(con):
        list_id = remote_by_title.get(category["name"])
        if not list_id:
            list_id = client.create_list(category["name"])["id"]
            report["created_remote"].append(category["name"])
        else:
            report["linked"].append(category["name"])
        category_repo.set_google_list_id(con, category["id"], list_id)
    gtasks_state.set_enabled(con, True)
    return report


def _title(row):
    return (row.get("title") or "").strip()
