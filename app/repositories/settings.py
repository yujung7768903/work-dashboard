"""앱 전체에 하나뿐인 설정. 행이 늘지 않으므로 테이블을 새로 만들지 않고 meta 를 쓴다"""
from app.constants import DEFAULT_LANGUAGE, LANGUAGE_KEY, LANGUAGES
from app.db import meta_get, meta_set
from app.errors import Validation


def language(con):
    """고른 적이 없으면 원문 언어(ko). 값이 깨져 있어도 화면이 뜨는 쪽을 택한다"""
    stored = meta_get(con, LANGUAGE_KEY)
    return stored if stored in LANGUAGES else DEFAULT_LANGUAGE


def set_language(con, code):
    cleaned = (code or "").strip().lower()
    if cleaned not in LANGUAGES:
        raise Validation(f"언어는 {', '.join(LANGUAGES)} 중 하나여야 합니다")
    meta_set(con, LANGUAGE_KEY, cleaned)
    return cleaned


def payload(con):
    """화면이 첫 렌더 전에 한 번 가져가는 모양. 설정이 늘면 여기에 붙인다"""
    return {"language": language(con)}
