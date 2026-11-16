"""글에서 근거 문서(Jira 이슈·Confluence 페이지·PR)를 뽑는다.

문서 id 는 정규화한 키다 — 같은 문서를 note 마다 다르게 적어도(URL·키만·쿼리 꼬리) 한 노드로 모여야
'같은 근거를 공유하는 할일'을 셀 수 있다.
- Jira:       jira:PFD-6350
- Confluence: confluence:7233175648   (pages/ 뒤 숫자 또는 pageId=)
- PR:         pr:hkilbo/hk-herb-server#27

Jira 키는 모양만으로는 'UTF-8'·'SHA-256' 같은 오탐이 많아 회사 프로젝트 접두사(JIRA_PROJECTS)만 받고,
브라우즈 URL 로 적힌 것은 접두사와 관계없이 받는다. 'HK #35' 처럼 레포를 줄여 적은 PR 은 어느 레포인지
코드가 확정할 수 없어 잇지 않는다
"""
import re

from app.constants import ATLASSIAN_BASE, GITHUB_BASE, JIRA_PROJECTS, KNOWN_REPOS

JIRA, CONFLUENCE, PR = "jira", "confluence", "pr"
JIRA_URL = re.compile(r"atlassian\.net/browse/([A-Z][A-Z0-9]{1,9}-\d+)")
# 앞뒤 경계는 \w(한글 포함) — 'KT-1차' 처럼 글자가 바로 붙으면 키가 아니다. 브랜치 이름처럼
# 'KT-1530-status' 로 이어지는 것은 키다
JIRA_KEY = re.compile(r"(?<![\w-])(" + "|".join(JIRA_PROJECTS) + r")-(\d+)(?!\w)(?!-\d)")
CONFLUENCE_URL = re.compile(r"atlassian\.net/wiki/(?:spaces/[^/\s]+/pages/|[^\s]*?[?&]pageId=)(\d+)")
PR_URL = re.compile(r"github\.com/([\w.-]+)/([\w.-]+)/pull/(\d+)")
PR_SLUG = re.compile(r"(?<![\w./-])([\w.-]+)/([\w.-]+)#(\d+)\b")
REPO_PR = re.compile(r"(?<![\w./-])(" + "|".join(map(re.escape, KNOWN_REPOS)) + r")\s+(?:PR\s*)?#(\d+)\b")


def extract(text):
    """글에 나온 문서 키 목록. 처음 나온 순서, 중복 없음"""
    found = []
    seen = set()

    def add(ref):
        if ref not in seen:
            seen.add(ref)
            found.append(ref)

    text = text or ""
    for match in JIRA_URL.finditer(text):
        add(f"{JIRA}:{match.group(1)}")
    for match in JIRA_KEY.finditer(text):
        add(f"{JIRA}:{match.group(1)}-{match.group(2)}")
    for match in CONFLUENCE_URL.finditer(text):
        add(f"{CONFLUENCE}:{match.group(1)}")
    for match in PR_URL.finditer(text):
        add(f"{PR}:{match.group(1)}/{_repo(match.group(2))}#{match.group(3)}")
    for match in PR_SLUG.finditer(text):
        add(f"{PR}:{match.group(1)}/{_repo(match.group(2))}#{match.group(3)}")
    for match in REPO_PR.finditer(text):
        repo = match.group(1)
        add(f"{PR}:{KNOWN_REPOS[repo]}/{repo}#{match.group(2)}")
    return found


def url_of(ref):
    """문서 키 → 열 주소. 모르는 종류면 None"""
    kind, _, key = ref.partition(":")
    if kind == JIRA:
        return f"{ATLASSIAN_BASE}/browse/{key}"
    if kind == CONFLUENCE:
        return f"{ATLASSIAN_BASE}/wiki/pages/viewpage.action?pageId={key}"
    if kind == PR:
        slug, _, number = key.partition("#")
        return f"{GITHUB_BASE}/{slug}/pull/{number}"
    return None


def label_of(ref):
    """카드에 찍는 짧은 이름. Jira 는 키 그대로, PR 은 레포#번호, Confluence 는 'Confluence 번호'"""
    kind, _, key = ref.partition(":")
    if kind == PR:
        return f"{key.split('/', 1)[-1]}"
    if kind == CONFLUENCE:
        # 페이지 번호만으로는 무엇인지 안 읽힌다. 제목을 알면 화면이 제목을 쓴다
        return f"Confluence {key}"
    return key


def kind_of(ref):
    return ref.partition(":")[0]


def _repo(name):
    # URL 끝의 .git 이나 문장부호가 붙어 와도 같은 레포로 모은다
    return name[:-4] if name.endswith(".git") else name.rstrip(".")
