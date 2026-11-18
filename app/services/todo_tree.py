"""할일 트리 조립. 상위 연결(edges)이 없는 할일·맥락 하나가 트리 하나(맨 위)이고, 그 아래에 맥락·할일이
상위 연결로 깊이 제한 없이 매달린다. 워크스페이스는 없다(사용자 결정 11-18) — 옛 워크스페이스는 이관이 맨 위
할일로 바꿔 두었고 배경·목표는 그 할일의 note 에 있다. 카테고리는 트리 맨 위 노드의 표시(색·이름)일 뿐이다.

상위는 여러 개일 수 있다. 화면은 카드를 한 번만 그리므로 할일마다 '주 상위' 하나를 골라 그 밑에 둔다:
확정 > 제안, 먼저 이은 것 순(app/services/lineage.py 와 같은 규칙). 나머지 상위·선행·관련은 links 로 따로
내려 화면이 선을 더 긋는다(목록은 각 상위 밑에도 보인다).

할일은 role 이 NULL 인 행뿐이다. 그 밖의 role(예: 매니저 보조 피드백 기록 'feedback')은 어디에도 그리지 않는다.
단계(role='step')는 노드가 아니다. 할일 하나는 결과 하나로 끝나는 일이고 그 과정의 파생 요청·결정은 그
할일의 단계다 — 할일 카드 안에 순서 목록(steps)으로 싣는다. 단계에 열린 매니저 결정·확인이 있으면 waiting.

진행률은 상위마다 자기 단계 전부 + 하위 할일 전부를 센다 — 상위가 둘인 할일은 두 상위의 진행률에 다 들어간다.
같은 상위 아래로 두 길로 닿아도 한 번만 센다. 트리 완료는 그 트리 할일이 전부 done 일 때다(저장하지 않는다)

세션 결과물(세션이 만들거나 고친 Confluence·Jira·PR·아티팩트·사이트·파일)은 그 세션이 맡던 할일의 results 로
내려 화면이 그 할일 오른쪽에 잎 카드로 그린다(단계를 맡던 세션이면 그 단계의 할일). 진행률·상태 개수에는
세지 않는다 — 할일이 아니다
"""
import os

from app import evidence as evidence_refs
from app.constants import (
    EDGE_PROPOSED,
    EDGE_REJECTED,
    NODE_CONTEXT,
    NODE_DOC,
    NODE_TODO,
    REL_EVIDENCE,
    REL_PARENT,
    REL_PRECEDES,
    REL_RELATED,
    STATUS_DONE,
    TODO_STATUSES,
)
from app.repositories import autorun as autorun_repo
from app.repositories import categories as category_repo
from app.repositories import graph as graph_repo
from app.repositories import sessions as session_repo
from app.services import lineage
from app.services import manager_links

# updated_at — 트리 목록이 '최근 작업·수정 순' 으로 세울 때 last_session_at 과 함께 본다(static/js/tree-todos.js)
NODE_FIELDS = ("id", "title", "status", "parent_id", "priority", "sort_order", "category_id", "cwd", "updated_at")
CONTEXT_STATUS = "context"  # 맥락은 할일 상태가 없다. 아래가 전부 끝나면 done 으로 본다
# 단계에 걸린 매니저 결정·확인이 아직 사람 답을 기다리는 상태
STEP_WAITING_STATUSES = ("open", "confirm")


def key_of(kind, ident):
    return f"{'c' if kind == NODE_CONTEXT else 't'}{ident}"


def forest(con):
    """주 상위가 없는 노드마다 트리 하나. 안 끝난 트리가 앞, 그 안에서 맨 위 우선순위 높은 것(없으면 뒤),
    그다음 sort_order·id (lineage.rank)"""
    categories = {row["id"]: row for row in category_repo.list_all(con)}
    nodes, steps = _load_nodes(con)
    links = _load_links(con, nodes)
    _attach(nodes, links)
    _place_children(nodes)
    _attach_steps(nodes, steps, lineage.parent_map(con))
    _attach_results(con, nodes, steps)
    tops = [node for node in nodes.values() if not any(parent["primary"] for parent in node["parents"])]
    trees = []
    for top in sorted(tops, key=lambda item: (item["sort_order"] or 0, item["id"])):
        tree = _tree(top, nodes, categories)
        head = top if top["kind"] == NODE_TODO else None
        trees.append((tree, lineage.rank(tree["complete"], head)))
    trees.sort(key=lambda pair: pair[1])
    proposals = sum(1 for link in links if link["state"] == EDGE_PROPOSED)
    return {
        "trees": [tree for tree, _ in trees],
        "links": [_public_link(link) for link in links if link["relation"] != REL_EVIDENCE],
        "proposals": proposals,
        "statuses": list(TODO_STATUSES),
    }


def proposals(con):
    """확인 대기 제안 목록 — 화면의 제안 칸이 쓴다. 양 끝 제목을 붙여 무엇과 무엇인지 바로 읽히게"""
    nodes, steps = _load_nodes(con)
    for step in steps.values():
        nodes[key_of(NODE_TODO, step["id"])] = step
    found = []
    for edge in graph_repo.list_edges(con, states=(EDGE_PROPOSED,)):
        found.append(
            {
                **_public_link(edge),
                "from_title": _title(nodes, edge["src_kind"], edge["src_id"]),
                "to_title": _title(nodes, edge["dst_kind"], edge["dst_id"]),
                "created_by": edge["created_by"],
            }
        )
    return {"proposals": found}


# ── 노드·연결 읽기 ─────────────────────────────────────────────────────


def _load_nodes(con):
    # 답 대기 중인 세션이 매니저에 권한 막힘을 남겼으면 권한 대기로 — 매니저 탭·할일 상세와 같은 구분(manager_links)
    blocked = manager_links.permission_sessions()
    waiting = session_repo.waiting_by_todo(con, lambda kind, sid: manager_links.promote(kind, sid, blocked))
    # 할일별 보기가 진행 중 할일을 세우는 순서 — 상태별 뷰(보드)와 같은 '방금 손댄 것이 위로'
    last_seen = session_repo.last_activity_by_todo(con)
    locked = autorun_repo.locked_todo_ids(con)
    sessions = {
        row["todo_id"]: row["n"]
        for row in con.execute("SELECT todo_id, COUNT(*) AS n FROM session_todos GROUP BY todo_id")
    }
    nodes, steps = {}, {}
    for row in con.execute("SELECT * FROM todos ORDER BY sort_order, id"):
        todo = dict(row)
        if lineage.is_hidden(todo):
            continue  # 할일도 단계도 아닌 기록(예: 매니저 보조 피드백)은 트리에 없다
        if lineage.is_step(todo):
            steps[todo["id"]] = {
                "id": todo["id"],
                "title": todo["title"],
                "status": todo["status"],
                "sort_order": todo["sort_order"],
                "parent_id": todo["parent_id"],
                # 결정·확인이 걸린 단계 — 매니저 칸(mgr_*)이 아직 답을 기다리면 화면이 '대기' 를 붙인다
                "decision": todo.get("mgr_kind"),
                "waiting": bool(todo.get("mgr_kind")) and todo.get("mgr_status") in STEP_WAITING_STATUSES,
            }
            continue
        node = {key: todo.get(key) for key in NODE_FIELDS}
        node.update(
            key=key_of(NODE_TODO, todo["id"]),
            kind=NODE_TODO,
            waiting=waiting.get(todo["id"]),
            # 자율 수행이 done 으로 닫았지만 사람이 아직 확인하지 않은 것 (보드의 검토 대기)
            autorun_locked=todo["id"] in locked,
            sessions=sessions.get(todo["id"], 0),
            last_session_at=last_seen.get(todo["id"]),
        )
        nodes[node["key"]] = node
    for context in graph_repo.list_contexts(con):
        node = {
            "key": key_of(NODE_CONTEXT, context["id"]),
            "kind": NODE_CONTEXT,
            "id": context["id"],
            "title": context["title"],
            "note": context["note"],
            "status": CONTEXT_STATUS,
            "category_id": context["category_id"],
            "cwd": None,
            "parent_id": None,
            "priority": None,
            "sort_order": 0,
            "waiting": None,
            "autorun_locked": False,
            "sessions": 0,
            "last_session_at": None,
            "updated_at": context["updated_at"],
        }
        nodes[node["key"]] = node
    for node in nodes.values():
        node.update(parents=[], docs=[], after=[], before=[], related=[], children=[], extra_children=[],
                    results=[], steps=[])
    return nodes, steps


def _load_links(con, nodes):
    """거절된 것을 뺀 상위·선행·관련·근거. 끝이 사라진(손으로 고친 DB) 연결은 버린다"""
    docs = graph_repo.docs_by_ref(con)
    links = []
    for edge in graph_repo.list_edges(con, relations=(REL_PARENT, REL_PRECEDES, REL_RELATED, REL_EVIDENCE)):
        if edge["state"] == EDGE_REJECTED:
            continue
        src = key_of(edge["src_kind"], edge["src_id"])
        if src not in nodes:
            continue
        if edge["relation"] == REL_EVIDENCE:
            doc = docs.get(edge["dst_id"], {})
            label = evidence_refs.label_of(edge["dst_id"])
            # 제목을 모르면 노드에는 라벨이 들어 있다 — 그건 제목이 아니라 화면이 라벨을 쓰게 비운다
            title = doc.get("title")
            if title in (label, edge["dst_id"].partition(":")[2]):
                title = None
            edge = {**edge, "from": src, "doc": {
                "ref": edge["dst_id"],
                "label": label,
                "kind": evidence_refs.kind_of(edge["dst_id"]),
                "title": title,
                "url": doc.get("url") or evidence_refs.url_of(edge["dst_id"]),
            }}
            links.append(edge)
            continue
        dst = key_of(edge["dst_kind"], edge["dst_id"])
        if dst not in nodes:
            continue
        links.append({**edge, "from": src, "to": dst})
    return links


def _attach(nodes, links):
    """연결을 노드에 붙이고 주 상위를 고른다"""
    for link in links:
        source = nodes[link["from"]]
        brief = {"edge_id": link["id"], "state": link["state"], "evidence": link["evidence"]}
        if link["relation"] == REL_EVIDENCE:
            source["docs"].append({**link["doc"], **brief})
            continue
        target = nodes[link["to"]]
        if link["relation"] == REL_PARENT:
            target["parents"].append({**brief, "key": source["key"], "title": source["title"],
                                      "basis": link["basis"], "primary": False})
        elif link["relation"] == REL_PRECEDES:
            target["after"].append({**brief, **_ref(source)})
            source["before"].append({**brief, **_ref(target)})
        else:
            source["related"].append({**brief, **_ref(target)})
            target["related"].append({**brief, **_ref(source)})
    for node in nodes.values():
        primary = _primary_parent(node, nodes)
        if primary is not None:
            primary["primary"] = True
    _break_primary_cycles(nodes)
    for link in links:
        if link["relation"] == REL_PARENT:
            link["primary"] = any(
                parent["primary"] and parent["edge_id"] == link["id"]
                for parent in nodes[link["to"]]["parents"]
            )


def _primary_parent(node, nodes):
    """상위 중 확정 > 제안, 먼저 이은 것"""
    if not node["parents"]:
        return None
    return sorted(node["parents"], key=lambda parent: (parent["state"] == EDGE_PROPOSED, parent["edge_id"]))[0]


def _break_primary_cycles(nodes):
    """저장소가 순환을 막지만 손으로 고친 DB 에 고리가 있으면 그 고리의 카드가 루트에서 닿지 않아
    화면에서 사라진다. 주 상위를 따라 올라가다 자기를 만나면 그 할일의 주 상위를 떼 루트 아래에 둔다"""
    def primary_of(key):
        return next((parent for parent in nodes[key]["parents"] if parent["primary"]), None)

    for key in nodes:
        seen, step = {key}, primary_of(key)
        while step is not None:
            if step["key"] in seen:
                own = primary_of(key)
                if own is not None:
                    own["primary"] = False
                break
            seen.add(step["key"])
            step = primary_of(step["key"])


def _attach_steps(nodes, steps, parents):
    """단계를 그 할일 카드의 steps 로. 상위는 parent_id, 없으면 그 단계로 가는 주 상위 연결(lineage.parent_map)"""
    for step in sorted(steps.values(), key=lambda item: (item["sort_order"] or 0, item["id"])):
        owner = nodes.get(key_of(NODE_TODO, step["parent_id"])) if step["parent_id"] is not None else None
        if owner is None:
            above = parents.get((NODE_TODO, str(step["id"])))
            owner = nodes.get(key_of(*above)) if above else None
        if owner is not None:
            owner["steps"].append({key: step[key] for key in ("id", "title", "status", "decision", "waiting")})


def _attach_results(con, nodes, steps=None):
    """세션 결과물(세션 → 문서 결과 관계)을 그 세션이 그때 맡던 할일 카드 밑에 붙인다.
    세션이 할일을 여럿 맡았으면 결과 시각 직전에 이은 할일, 그보다 앞선 연결이 없으면 처음 이은 할일.
    맡던 것이 단계면 그 단계의 할일 카드다.
    할일을 안 맡은 세션의 결과는 트리에 자리가 없어 그리지 않는다(관계는 DB 에 남는다).
    같은 할일 밑 같은 문서는 세션이 달라도 카드 하나로 모으고 동작을 합친다"""
    steps = steps or {}
    performed = {}
    for row in con.execute(
        "SELECT s.claude_session_id AS sid, st.todo_id, st.created_at FROM session_todos st"
        " JOIN sessions s ON s.id = st.session_id ORDER BY st.created_at, st.todo_id"
    ):
        performed.setdefault(row["sid"], []).append((row["created_at"], row["todo_id"]))
    for result in graph_repo.results(con):
        todo_id = _todo_at(performed.get(result["src_id"]), result["created_at"])
        if todo_id in steps:
            todo_id = steps[todo_id]["parent_id"]
        node = nodes.get(key_of(NODE_TODO, todo_id)) if todo_id is not None else None
        if node is None:
            continue
        same = next((item for item in node["results"] if item["ref"] == result["dst_id"]), None)
        if same is not None:
            same["actions"] = graph_repo.merge_actions(same["actions"], result["evidence"])
            continue
        node["results"].append(_result_card(result, todo_id))
    # 최근 것이 위 — 화면이 많으면 앞 몇 장만 펼치고 나머지는 접는다
    for node in nodes.values():
        node["results"].sort(key=lambda item: item["at"] or "", reverse=True)


def _todo_at(links, at):
    if not links:
        return None
    before = [todo_id for linked_at, todo_id in links if linked_at <= (at or "")]
    return before[-1] if before else links[0][1]


def _result_card(result, todo_id):
    ref = result["dst_id"]
    kind, _, key = ref.partition(":")
    label = evidence_refs.label_of(ref)
    title = result["doc_title"]
    if title in (label, key):
        title = None  # 라벨뿐인 제목은 화면이 라벨을 쓴다
    card = {
        # 같은 문서가 다른 할일 밑에도 붙을 수 있어 할일까지 넣어야 판 위에서 하나로 갈린다
        "key": f"r{result['node_id']}-t{todo_id}",
        "kind": "result",
        "node_id": result["node_id"],
        "ref": ref,
        "doc_kind": kind,
        "label": label,
        "title": title,
        "url": result["doc_url"] or evidence_refs.url_of(ref),
        "actions": result["evidence"],
        "at": result["created_at"],
        "children": [],
    }
    if kind == evidence_refs.FILE:
        card["path"] = key
        card["missing"] = not os.path.exists(key)
    return card


# ── 트리 조립 ───────────────────────────────────────────────────────────


def _place_children(nodes):
    """주 상위 밑 children·다른 상위 밑 extra_children 을 한 번에 채운다"""
    order = sorted(nodes.values(), key=lambda item: (item["kind"] != NODE_CONTEXT, item["sort_order"] or 0, item["id"]))
    for node in order:
        for parent in node["parents"]:
            target = nodes[parent["key"]]
            if parent["primary"]:
                target["children"].append(node)
            else:
                target["extra_children"].append(node["key"])


def _tree(top, nodes, categories):
    """맨 위 노드 하나와 그 아래(주 상위로 붙은 것 전부). 진행률은 모든 상위 연결을 따라 센다.
    children 에는 맨 위 노드 자신이 하나 들어 있다 — 화면은 맨 위를 할일(또는 맥락) 카드 그대로 그린다"""
    members, stack = [], [top]
    while stack:
        node = stack.pop()
        members.append(node)
        stack.extend(node["children"])
    for node in members:
        _fill_progress(node, nodes)
    todos = [node for node in members if node["kind"] == NODE_TODO]
    counts = {status: 0 for status in TODO_STATUSES}
    for todo in todos:
        counts[todo["status"]] = counts.get(todo["status"], 0) + 1
    total = len(todos)
    done = counts.get(STATUS_DONE, 0)
    category = categories.get(top["category_id"]) or {}
    return {
        "key": top["key"],
        "name": top["title"],
        "category_id": top["category_id"],
        "category_name": category.get("name"),
        "category_color": category.get("color"),
        "children": [top],
        "progress": {"done": done, "total": total},
        "counts": counts,
        "waiting": sum(1 for todo in todos if todo["waiting"] or any(step["waiting"] for step in todo["steps"])),
        "complete": total > 0 and done == total,
    }


def _fill_progress(node, nodes):
    """자기 단계 + 하위 할일 전체(모든 상위 연결을 따라) 중 완료 수. 자기 자신은 세지 않는다.
    맥락은 아래가 다 끝나면 done"""
    if "progress" in node:
        return
    found, stack = set(), [node["key"]]
    while stack:
        current = nodes[stack.pop()]
        for child in current["children"]:
            if child["key"] not in found:
                found.add(child["key"])
                stack.append(child["key"])
        for key in current["extra_children"]:
            if key not in found:
                found.add(key)
                stack.append(key)
    found.discard(node["key"])
    todos = [nodes[key] for key in found if nodes[key]["kind"] == NODE_TODO]
    done = sum(1 for todo in todos if todo["status"] == STATUS_DONE)
    done += sum(1 for step in node["steps"] if step["status"] == STATUS_DONE)
    total = len(todos) + len(node["steps"])
    node["progress"] = {"done": done, "total": total}
    if node["kind"] == NODE_CONTEXT and todos and done == total:
        node["status"] = STATUS_DONE


def _ref(node):
    return {"key": node["key"], "kind": node["kind"], "id": node["id"], "title": node["title"],
            "status": node["status"]}


def _public_link(link):
    return {
        "id": link["id"],
        "relation": link["relation"],
        "state": link["state"],
        "basis": link["basis"],
        "evidence": link["evidence"],
        "created_by": link["created_by"],
        "from": link.get("from") or key_of(link["src_kind"], link["src_id"]),
        "to": link.get("to") or (
            link["dst_id"] if link["dst_kind"] == NODE_DOC else key_of(link["dst_kind"], link["dst_id"])
        ),
        "primary": link.get("primary", False),
    }


def _title(nodes, kind, ident):
    if kind == NODE_DOC:
        return evidence_refs.label_of(ident)
    node = nodes.get(key_of(kind, ident))
    return node["title"] if node else None
