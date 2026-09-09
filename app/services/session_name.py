"""할일 제목이 세션 이름이 되게 한다 — `#id | 제목`.

자율 실행 잡은 뜰 때 이 이름을 받지만, 사람이 연 세션은 처음 문장으로 이름이 붙고 그대로다.
그러면 `claude agents` 목록에서 어느 세션이 어느 할일인지 보드와 맞춰 볼 수 없다.
그래서 이름이 어긋날 수 있는 순간 — 할일을 세션에 연결할 때, 제목을 고칠 때 — 에 그
할일을 잡은 세션 전부를 다시 이름 붙인다. 주기 동기화는 없다: 어긋나는 지점이 이 둘뿐이다.

세션 종류별 길:
  --bg 잡          state.json 의 name (autorun.rename_job). 리밋 재개 플래그까지 같이 고친다
  살아 있는 대화형  cc-socks 소켓에 control/rename (session_message). /rename 과 같다
  끝난 세션         건드리지 않는다. 다시 열리면 그때 link-todo 가 다시 이름을 붙인다
"""
import threading

from app.constants import AUTORUN_JOBS_ROOT
from app.errors import Validation
from app.repositories import sessions as session_repo
from app.services import autorun, session_message


def sync_todo(con, todo, *, agents=None, deliver=None, jobs_root=AUTORUN_JOBS_ROOT):
    """그 할일을 잡은 세션의 이름을 지금 맞춘다. 바꾼 세션 id 목록. CLI 처럼 끝나기 전에 마쳐야 하는 곳용"""
    return _apply(
        session_repo.list_by_todo(con, todo["id"]), autorun.job_name(todo),
        agents=agents, deliver=deliver, jobs_root=jobs_root,
    )


def sync_todo_later(con, todo):
    """웹 요청용 — `claude agents` 1~2초가 응답을 붙잡지 않게 뒷일로. DB 는 지금 읽고 스레드는 파일·소켓만 만진다"""
    sessions = session_repo.list_by_todo(con, todo["id"])
    if not sessions:
        return
    name = autorun.job_name(todo)
    schedule(lambda: _apply(sessions, name))


def schedule(work):
    """뒷일 실행. 테스트는 이 함수를 동기 실행으로 갈아끼운다"""
    threading.Thread(target=work, daemon=True).start()


def _apply(sessions, name, agents=None, deliver=None, jobs_root=AUTORUN_JOBS_ROOT):
    renamed = []
    live = None  # `claude agents` 는 필요할 때 한 번만
    for session in sessions:
        session_id = session["claude_session_id"] or ""
        if not session_id:
            continue
        if autorun.rename_job(session_id, name, jobs_root=jobs_root):
            renamed.append(session_id)
            continue
        if live is None:
            live = (agents or session_message.live_sessions)()
        row = live.get(session_id) or {}
        if not row.get("pid") or row.get("name") == name:
            continue
        try:
            (deliver or session_message.deliver)(
                session_message.socket_path(row["pid"]), session_message.rename_line(session_id, name)
            )
        except Validation:
            continue  # 한 세션에 못 닿았다고 나머지·호출한 작업까지 멈추면 안 된다
        renamed.append(session_id)
    return renamed
