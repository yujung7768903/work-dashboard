"""워크트리 브랜치를 본 저장소의 브랜치로 병합.

LLM 이 매번 손으로 조립하던 순서 — 상태 확인 → 대상 브랜치 들이기 → 테스트 → 병합 → 해제 —
를 한 단계로 고정한다. 순서가 사람 기억에 달려 있으면 테스트를 두 번 돌리거나(중복) 병합
뒤에 돌린다(이미 늦음). 대상 브랜치를 먼저 들여서 테스트하면 병합 결과와 같은 트리이므로
병합 뒤 테스트가 필요 없다.

그 전제는 테스트하는 동안 대상 브랜치가 그대로일 때만 선다. 다른 세션이 그 사이 병합하면
바뀐 대상 브랜치를 다시 들여 다시 테스트한다. 그래도 남는 틈(확인과 병합 사이)에서 충돌하면
메인 체크아웃을 병합 전으로 되돌린다 — 메인 체크아웃은 여러 세션이 같이 쓰고, 워크트리에
갇힌 세션은 거기서 git 을 못 해 병합 중 상태로 남기면 사람이 풀어야 한다(11-16).

push 는 하지 않는다 — 원격 반영은 사람 몫이다.
"""
import os
import re
import subprocess

from app.constants import MERGE_TEST_TIMEOUT_SEC
from app.errors import DomainError
from app.repositories import sessions as session_repo
from app.services import release, worktrees

# 저장소마다 테스트 명령을 알 수 없다. 이 파일이 있으면 파이썬 unittest 관행으로 본다
DEFAULT_TEST_ENTRY = os.path.join("tests", "__main__.py")
DEFAULT_TEST_COMMAND = "python3 -m tests"
# 병합 커밋 제목에서 `feat: ` 같은 접두는 중복이라 뗀다
COMMIT_TYPE_PREFIX = re.compile(r"^[a-z]+(\([^)]*\))?: ")
RAN_TESTS = re.compile(r"Ran (\d+) tests?")
# 해결했다고 스테이징했는데 이 표시가 그대로 남아 있는 실수를 막는다
CONFLICT_MARKER = "<<<<<<< "
# 실패 로그는 꼬리만. 전문을 올리면 중단 사유가 묻힌다
TAIL_LINES = 15
# 테스트하는 사이 대상 브랜치가 바뀌면 다시 들여 다시 테스트하는 횟수. 다른 세션들이 쉬지 않고
# 병합하면 끝없이 돌 수 있어 상한을 둔다 — 넘으면 대상 브랜치를 건드리지 않고 멈춘다
MERGE_CATCH_UP_LIMIT = 3


def merge(con, claude_session_id, worktree=None, message=None, test=None, no_test=False):
    """단계별 결과와 중단 사유를 돌려준다.

    중단하면 그 뒤 단계는 실행하지 않는다 — 어디까지 됐는지는 steps 로 남는다.
    """
    steps = []
    session = session_repo.get(con, claude_session_id)
    root = release.worktree_of(claude_session_id, session["cwd"], worktree=worktree)
    if not root:
        return _aborted(steps, "워크트리를 찾지 못함 — 워크트리에서 실행하거나 --worktree 로 지정할 것")

    branch = _branch(root)
    main_root = worktrees.repo_root_of(root)
    target = _branch(main_root) if main_root else ""
    if not branch or not target:
        return _aborted(steps, f"브랜치를 읽지 못함 (detached HEAD?) — 워크트리 {root}")
    steps.append(("위치", f"{root} — {branch} → {target} @ {main_root}"))
    if branch == target:
        return _aborted(steps, f"워크트리가 {target} 를 그대로 보고 있어 병합할 것이 없음")

    # 이어받는 중이면 워크트리는 병합 상태라 당연히 더럽다 — 그것을 더럽다고 막으면
    # 충돌을 해결해도 진행할 방법이 없다
    resuming = _merge_in_progress(root)
    checks = [("메인 체크아웃", main_root)] if resuming else [
        ("워크트리", root),
        ("메인 체크아웃", main_root),
    ]
    for label, path in checks:
        dirty = _dirty(label, path)
        if dirty:
            return _aborted(steps, dirty)

    ahead = _subjects(root, f"{target}..HEAD")
    if not ahead:
        return _aborted(steps, f"{target} 에 없는 커밋이 없음 — 병합할 것이 없음")

    if resuming:
        step, aborted = _resume(root, target)
    else:
        step, aborted = _pull(root, target, f"{target} 들이기", "{count}개 커밋")
    steps.append(step)
    if aborted:
        return _aborted(steps, aborted)

    command = _test_command(root, test, no_test)
    aborted = _test_until_current(root, target, command, no_test, steps)
    if aborted:
        return _aborted(steps, aborted)

    subject = message or _default_message(ahead)
    step, aborted = _land(main_root, branch, target, f"merge: {subject}")
    if step:
        steps.append(step)
    if aborted:
        return _aborted(steps, aborted)

    try:
        released = release.finish(con, claude_session_id, worktree=root)
    except DomainError as error:
        # 병합은 끝났다. 해제 실패를 그냥 올리면 단계 출력이 사라져 병합까지 실패한 것처럼 보인다
        return _aborted(steps, f"병합은 됐고 해제만 실패함 — {error}")

    return {
        "steps": steps,
        "aborted": "",
        "branch": branch,
        "target": target,
        "release": released,
    }


def _aborted(steps, reason):
    return {"steps": steps, "aborted": reason, "branch": "", "target": "", "release": None}


def _dirty(label, path):
    """커밋 안 된 변경이 있으면 중단 사유.

    추적 중인 변경만 본다. 미추적 파일은 병합이 건드리지 않고, 잔여물(빈 sqlite,
    워크트리 디렉토리)로 병합이 영구히 막히면 그게 더 큰 문제다
    """
    dirty = _git_out(path, "status", "--porcelain", "--untracked-files=no")
    return f"{label} — 커밋 안 된 변경이 있음. 먼저 정리할 것:\n{dirty}" if dirty else ""


def _pull(root, target, label, done):
    """대상 브랜치를 워크트리로 들인다. (단계, 중단사유) 를 돌려준다.

    충돌이면 워크트리를 병합 중으로 둔다 — 그 워크트리를 쓰는 세션이 해결하고 다시 실행하면
    이어받는다. done 은 들인 커밋 수를 {count} 로 받는 문구
    """
    behind = _subjects(root, f"HEAD..{target}")
    if not behind:
        return (label, "이미 최신"), ""
    ok, _ = _git(root, "merge", target, "--no-edit")
    if not ok:
        return (label, "충돌"), _conflict_reason(root, target)
    return (label, done.format(count=len(behind))), ""


def _test_until_current(root, target, command, no_test, steps):
    """테스트하고, 그 사이 대상 브랜치가 바뀌었으면 다시 들여 다시 테스트한다. 중단사유를 돌려준다.

    테스트한 트리가 병합할 트리여야 병합 뒤 테스트가 필요 없다. 바뀐 대상 브랜치에 그대로
    병합하면 아무도 테스트하지 않은 조합이 들어가고, 같은 파일을 고쳤으면 메인 체크아웃에서
    충돌한다 — 워크트리에서 충돌하게 해야 그 세션이 스스로 해결할 수 있다
    """
    for attempt in range(1 + MERGE_CATCH_UP_LIMIT):
        if attempt:
            step, aborted = _pull(
                root, target, f"{target} 다시 들이기", "테스트하는 사이 바뀐 {count}개 커밋"
            )
            steps.append(step)
            if aborted:
                return aborted
        aborted = _test(root, target, command, no_test, steps)
        if aborted:
            return aborted
        if not _subjects(root, f"HEAD..{target}"):
            return ""
    return (
        f"테스트하는 사이 {target} 가 계속 바뀌어 {MERGE_CATCH_UP_LIMIT}번 다시 들이고 테스트했지만"
        f" 따라잡지 못함 — {target} 는 건드리지 않음. 잠시 뒤 같은 명령을 다시 실행할 것"
    )


def _test(root, target, command, no_test, steps):
    if not command:
        steps.append(("테스트", _skip_reason(no_test)))
        return ""
    ok, out = _run_test(root, command)
    if not ok:
        steps.append(("테스트", f"{command} — 실패"))
        return f"테스트가 실패해 {target} 에 병합하지 않음:\n{_tail(out)}"
    steps.append(("테스트", f"{command} — {_test_summary(out)}"))
    return ""


def _land(main_root, branch, target, message):
    """메인 체크아웃에서 병합. (단계, 중단사유) — 단계가 None 이면 병합을 시도하지 않았다.

    충돌하면 병합 전으로 되돌린다. 마지막 확인과 병합 사이에 다른 세션이 대상 브랜치에
    병합한 것이고, 다시 실행하면 그 변경을 워크트리로 들여 다시 테스트한다
    """
    # 테스트하는 사이 다른 세션이 메인 체크아웃을 고쳤을 수 있다. 커밋 안 된 변경 위에서
    # 충돌하면 merge --abort 가 그 변경을 되살리지 못할 수 있어 아예 병합하지 않는다
    dirty = _dirty("메인 체크아웃", main_root)
    if dirty:
        return None, dirty
    mine = _git_out(main_root, "rev-parse", branch)
    ok, out = _git(main_root, "merge", "--no-ff", branch, "-m", message)
    if ok:
        return ("병합", _git_out(main_root, "log", "--oneline", "-1")), ""
    if _git_out(main_root, "rev-parse", "-q", "--verify", "MERGE_HEAD") != mine:
        # 잠금·덮어쓸 미추적 파일 등으로 병합을 시작도 못 했다. 그때 보이는 병합 상태는
        # 다른 세션의 것이라 되돌리면 그 세션의 병합을 날린다
        return ("병합", "실패"), f"{target} 병합 실패 — 메인 체크아웃은 건드리지 않음:\n{_tail(out)}"
    conflicts = "\n".join(_unresolved(main_root) or ["(충돌 파일을 읽지 못함)"])
    _, revert_out = _git(main_root, "merge", "--abort")
    # 종료 코드가 아니라 남은 상태로 판정한다 — 되돌려졌는지가 다른 세션에 중요한 사실이다
    if _merge_in_progress(main_root) or _unresolved(main_root):
        return ("병합", "충돌 — 되돌리기 실패"), (
            f"{target} 병합이 충돌했고 되돌리기(git merge --abort)도 실패함 — 메인 체크아웃"
            f" {main_root} 가 병합 중 상태로 남아 다른 세션의 병합도 막힌다."
            f" 사람이 `git -C {main_root} merge --abort` 로 풀어야 함:\n{_tail(revert_out)}\n"
            f"충돌 파일:\n{conflicts}"
        )
    return ("병합", "충돌 — 메인 체크아웃 되돌림"), (
        f"{target} 병합이 충돌해 메인 체크아웃을 병합 전으로 되돌림 — 마지막 확인 직후 다른 세션이"
        f" {target} 에 병합한 것. 같은 명령을 다시 실행하면 바뀐 {target} 를 워크트리로 들여"
        f" 다시 테스트한다. 충돌 파일:\n{conflicts}"
    )


def _resume(root, target):
    """해결이 끝난 병합을 이어받아 커밋. (단계, 중단사유) 를 돌려준다.

    충돌은 사람에게 넘기지 않는다 — 판단은 이 커맨드를 부른 쪽(LLM)이 하고, 여기서는
    해결이 실제로 끝났는지만 기계적으로 확인한다. 양쪽 기능이 살아 있는지는 이어서 도는
    테스트가 본다.
    """
    label = f"{target} 들이기"
    unresolved = _unresolved(root)
    if unresolved:
        return (label, "충돌 미해결"), _conflict_reason(root, target)
    left = _files_adding_markers(root)
    if left:
        return (label, "충돌 표시 남음"), (
            "해결이 끝나지 않았음 — 충돌 표시(<<<<<<<)를 새로 들여온 파일:\n"
            + "\n".join(left)
        )
    ok, out = _git(root, "commit", "--no-edit")
    if not ok:
        return (label, "커밋 실패"), f"해결분을 커밋하지 못함:\n{_tail(out)}"
    return (label, "충돌 해결분 커밋"), ""


def _conflict_reason(root, target):
    """무엇을 어떻게 해결해야 하는지까지 적는다. 읽는 쪽이 판단해야 하므로 파일 목록이 핵심"""
    files = _unresolved(root) or ["(git status 로 확인)"]
    return (
        f"{target} 를 워크트리로 들이는 중 충돌. 아래 파일을 해결하고 같은 명령을 다시 실행할 것"
        f" — 한쪽을 버리지 않고 양쪽 기능이 모두 살아 있게, 최신 {target} 기준으로 맞춘다:\n"
        + "\n".join(files)
    )


def _merge_in_progress(root):
    """병합 커밋 전에 멈춘 상태. 워크트리마다 다른 git 디렉토리를 봐야 한다"""
    path = _git_out(root, "rev-parse", "--git-path", "MERGE_HEAD")
    if not path:
        return False
    return os.path.exists(path if os.path.isabs(path) else os.path.join(root, path))


def _unresolved(root):
    """아직 해결되지 않은(U) 파일"""
    return _git_out(root, "diff", "--name-only", "--diff-filter=U").splitlines()


def _files_adding_markers(root):
    """충돌 표시를 새로 들여온 파일. 원래 그 표시가 있던 문서(-S 는 개수 변화만 본다)는 걸리지 않는다"""
    return _git_out(root, "diff", "--cached", "-S", CONFLICT_MARKER, "--name-only").splitlines()


def _test_command(root, test, no_test):
    """무엇으로 테스트할지. 빈 문자열이면 테스트하지 않는다"""
    if no_test:
        return ""
    if test:
        return test
    return DEFAULT_TEST_COMMAND if os.path.isfile(os.path.join(root, DEFAULT_TEST_ENTRY)) else ""


def _skip_reason(no_test):
    return "생략 (--no-test)" if no_test else f"생략 ({DEFAULT_TEST_ENTRY} 없음 · --test 로 지정)"


def _run_test(root, command):
    """(성공, 출력). 명령은 사람이 준 한 줄이라 셸로 실행한다 (`npm test -- --run` 같은 형태)"""
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=MERGE_TEST_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        return False, f"{MERGE_TEST_TIMEOUT_SEC}초 안에 끝나지 않음"
    return result.returncode == 0, (result.stdout + result.stderr).strip()


def _test_summary(out):
    """unittest 는 개수를 찍는다. 다른 러너면 통과 사실만"""
    found = RAN_TESTS.search(out)
    return f"{found.group(1)}개 통과" if found else "통과"


def _default_message(subjects):
    """브랜치의 가장 오래된 커밋 제목. 그 브랜치가 무엇을 하려던 것인지에 가장 가깝다"""
    return COMMIT_TYPE_PREFIX.sub("", subjects[-1])


def _subjects(root, revs):
    lines = _git_out(root, "log", "--format=%s", revs).splitlines()
    return [line for line in lines if line.strip()]


def _branch(root):
    return _git_out(root, "rev-parse", "--abbrev-ref", "HEAD")


def _tail(out):
    lines = out.splitlines()
    return "\n".join(lines[-TAIL_LINES:])


def _git(root, *args):
    """(성공, 출력). 예외를 올리지 않는다 — 실패 사유를 단계 목록에 담아야 한다"""
    result = subprocess.run(
        ["git", "-C", root, *args], capture_output=True, text=True
    )
    return result.returncode == 0, (result.stdout + result.stderr).strip()


def _git_out(root, *args):
    ok, out = _git(root, *args)
    return out if ok else ""
