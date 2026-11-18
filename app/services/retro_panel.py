"""매니저 탭 '회고' — 위: 대기 중인 피드백(입력창으로 보낸 것·세션 회고의 개선 후보), 아래: 날짜별 하루 회고.

매니저 CLI 만 부른다(manager.py retro list|show · feedback add). 피드백 대기열과 회고 기록의 정본은 매니저 DB 이고,
판정·반영(보조 세션·결정)은 매니저의 하루 회고(retro.py)가 한다 — 여기서는 읽고 쌓기만 한다.
사용자 지시(11-18): 매니저 개선건이 메인 매니저 대화·알림에 끼어들지 않게 따로 쌓고, 회고 결과를 여기서 본다.
글은 --text=<글> 한 덩어리 리스트 인자로만 넘긴다 — 셸·argparse 가 글을 명령·옵션으로 읽지 않게.
"""
from app.errors import Validation
from app.services import decision_answer

TEXT_MAX = 4000


def listing(home=None):
    """{feedback: [...], retros: [...], last_started}"""
    return decision_answer._call(["retro", "list", "--json"], home) or {"feedback": [], "retros": []}


def show(retro_id, home=None):
    return decision_answer._call(["retro", "show", str(int(retro_id)), "--json"], home)


def add(text, home=None):
    """입력창 피드백 하나를 쌓는다 → {id}. 하루 회고가 처리할 때까지 '대기'로 보인다"""
    text = (text or "").strip()
    if not text:
        raise Validation("보낼 피드백을 적어 주세요")
    return decision_answer._call(["feedback", "add", "--source", "ui", "--json", f"--text={text[:TEXT_MAX]}"], home)
