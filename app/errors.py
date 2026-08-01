"""도메인 예외. HTTP 계층이 타입만 보고 상태 코드를 정함"""


class DomainError(Exception):
    """모든 도메인 예외의 부모"""


class NotFound(DomainError):
    """대상 리소스 없음 → 404"""


class UnknownEndpoint(NotFound):
    """라우트 자체가 없음 → 404.

    '있는 경로인데 대상이 없음' 과 구분해야, 프런트가 부르는 엔드포인트가 서버에
    다 등록돼 있는지 테스트가 가려낼 수 있다 (tests/test_frontend_contract.py)
    """


class Conflict(DomainError):
    """현재 상태와 충돌하는 요청 → 409"""


class NeedsConfirm(Conflict):
    """되돌리기 어려운 부수효과가 있어 사용자 확인이 필요함 → 409 + confirm 플래그"""


class Validation(DomainError):
    """입력값이 규칙 위반 → 400"""
