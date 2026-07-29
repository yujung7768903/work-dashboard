"""도메인 예외. HTTP 계층이 타입만 보고 상태 코드를 정함"""


class DomainError(Exception):
    """모든 도메인 예외의 부모"""


class NotFound(DomainError):
    """대상 리소스 없음 → 404"""


class Conflict(DomainError):
    """현재 상태와 충돌하는 요청 → 409"""


class Validation(DomainError):
    """입력값이 규칙 위반 → 400"""
