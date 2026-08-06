"""워크트리 이력. 병합·삭제로 사라진 워크트리도 이름과 상태가 남아야 해서 따로 쌓는다.

git 은 지워진 워크트리를 기억하지 않는다 — `worktree list` 에서도 브랜치 목록에서도
빠지고, 병합 뒤에는 브랜치 자체가 없다. 그래서 살아 있는 동안 본 것을 여기 적어 두고,
병합 사실만 기준 브랜치의 reflog 에서 되짚는다 (app.services.worktrees.merge_events).

한 줄 = 한 워크트리 디렉터리. 같은 이름을 다시 만들면 앞 것과 다른 워크트리이므로
자국(병합·삭제)을 지우고 새로 시작한다 — 판정은 생성 시각으로 한다.
"""
from app.db import transaction


def remember(con, path, repo, branch, created_at):
    """처음 본 워크트리를 적고 그 행을 돌려준다. 이미 있으면 그대로"""
    row = find(con, path)
    if row and row["created_at"] == created_at:
        return row
    with transaction(con):
        if row:
            con.execute(
                "UPDATE worktrees SET repo=?, branch=?, created_at=?, merged_at=NULL,"
                " merge_hash=NULL, merge_from=NULL, deleted_at=NULL WHERE path=?",
                (repo, branch, created_at, path),
            )
        else:
            con.execute(
                "INSERT INTO worktrees(path, repo, branch, created_at) VALUES(?,?,?,?)",
                (path, repo, branch, created_at),
            )
    return find(con, path)


def mark_merged(con, path, merged_at, merge_hash, merge_from):
    """병합 시각과 병합 커밋. reflog 는 지워지므로(기본 90일) 처음 본 때 남겨 둔다 —
    커밋 목록을 되짚는 실마리가 이 두 해시뿐이다"""
    with transaction(con):
        con.execute(
            "UPDATE worktrees SET merged_at=?, merge_hash=?, merge_from=?, deleted_at=NULL"
            " WHERE path=?",
            (merged_at, merge_hash, merge_from, path),
        )
    return find(con, path)


def mark_deleted(con, path, deleted_at):
    """병합 없이 사라진 것을 확인한 시각. 병합된 워크트리에는 쓰지 않는다"""
    with transaction(con):
        con.execute("UPDATE worktrees SET deleted_at=? WHERE path=?", (deleted_at, path))
    return find(con, path)


def find(con, path):
    row = con.execute("SELECT * FROM worktrees WHERE path=?", (path,)).fetchone()
    return dict(row) if row else None
