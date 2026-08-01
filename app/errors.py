"""도메인 예외. HTTP 계층이 타입만 보고 상태 코드를 정함"""


class DomainError(Exception):
    """모든 도메인 예외의 부모"""


class NotFound(DomainError):
    """대상 리소스 없음 → 404"""


class Conflict(DomainError):
    """현재 상태와 충돌하는 요청 → 409"""


class NeedsConfirm(Conflict):
    """되돌리기 어려운 부수효과가 있어 사용자 확인이 필요함 → 409 + confirm 플래그"""


class Validation(DomainError):
    """입력값이 규칙 위반 → 400"""
