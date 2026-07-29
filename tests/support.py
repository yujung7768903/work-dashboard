"""테스트용 임시 DB 픽스처."""
import os
import tempfile

from app.db import connect


def temp_db_path():
    """호출마다 새 임시 디렉토리 아래 DB 경로. sqlite3.Connection 에는 속성을 붙일 수 없어 경로를 따로 반환"""
    return os.path.join(tempfile.mkdtemp(), "test.db")


def temp_db(path=None):
    """임시 파일 DB 연결. 같은 경로를 다시 주면 재연결"""
    return connect(path or temp_db_path())
