"""할일 관계 그래프 저장소 — 맥락·근거 문서 노드(graph_nodes)와 관계(edges).

노드는 (종류, id) 쌍이고 id 는 늘 글자다. 할일·세션은 제 테이블이 있어 여기서는 존재만 확인한다.
수행(세션 → 할일)은 session_todos 가 정본이라 이 저장소가 쓰지 않는다 — 읽을 때는 graph_edges 뷰.

연결 저장 규칙
- 같은 (출발, 도착, 관계) 는 한 행. 자동으로 다시 만들어도 사람이 확정·거절한 상태를 덮지 않는다
- 상위·선행은 저장할 때 순환을 거부한다(거절된 연결은 세지 않는다)
- 관련은 방향이 없어 (종류, id) 가 작은 쪽을 출발로 둔다
"""
from app import evidence as evidence_refs
from app.constants import (
    ACYCLIC_RELATIONS,
    BASIS_TRIGGER,
    BY_NOTE,
    BY_PARENT_COLUMN,
    BY_SHARED_DOC,
    BY_SPAWN,
    BY_USER,
    CONTEXT_TITLE_MSG,
    EDGE_BASIS_MSG,
    EDGE_CONFIRMED,
    EDGE_CYCLE_MSG,
    EDGE_KIND_MSG,
    EDGE_PROPOSED,
    EDGE_REJECTED,
    EDGE_RELATION_MSG,
    EDGE_SELF_MSG,
    EDGE_STATE_MSG,
    EDGE_STATES,
    NODE_CONTEXT,
    NODE_DOC,
    NODE_SESSION,
    NODE_TODO,
    PARENT_BASES,
    REL_EVIDENCE,
    REL_PARENT,
    REL_PRECEDES,
    REL_RELATED,
    RELATION_KINDS,
    SHARED_DOC_MAX_TODOS,
)
from app.db import now, transaction
from app.errors import NotFound, Validation

# 사람이 정한 상태는 자동이 못 바꾼다. 자동끼리는 확정이 제안을 이긴다
STATE_RANK = {EDGE_PROPOSED: 0, EDGE_CONFIRMED: 1}


# ── 노드 ────────────────────────────────────────────────────────────────


def create_context(con, title, workspace_id=None, category_id=None, note=None, created_by=BY_USER):
    """맥락 = 할일은 아니지만 할일들의 배경이 되는 묶음. 워크스페이스 아래 루트로 선다.
    카테고리는 워크스페이스가 있으면 그쪽을 따른다(할일과 같은 규칙)"""
    cleaned = (title or "").strip()
    if not cleaned:
        raise Validation(CONTEXT_TITLE_MSG)
    category_id = _context_category(con, workspace_id, category_id)
    stamp = now()
    with transaction(con):
        cursor = con.execute(
            "INSERT INTO graph_nodes(kind, ref, title, note, workspace_id, category_id, created_by,"
            " created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (NODE_CONTEXT, None, cleaned, note, workspace_id, category_id, created_by, stamp, stamp),
        )
    return get_context(con, cursor.lastrowid)


def get_context(con, context_id):
    row = con.execute(
        "SELECT * FROM graph_nodes WHERE id=? AND kind=?", (int(context_id), NODE_CONTEXT)
    ).fetchone()
    if not row:
        raise NotFound("맥락을 찾을 수 없습니다")
    return dict(row)


def list_contexts(con):
    return [
        dict(row)
        for row in con.execute(
            "SELECT * FROM graph_nodes WHERE kind=? ORDER BY id", (NODE_CONTEXT,)
        )
    ]


def update_context(con, context_id, **fields):
    current = get_context(con, context_id)
    allowed = {"title", "note", "workspace_id"}
    unknown = set(fields) - allowed
    if unknown:
        raise Validation(f"수정할 수 없는 필드: {sorted(unknown)}")
    if "title" in fields:
        fields["title"] = (fields["title"] or "").strip()
        if not fields["title"]:
            raise Validation(CONTEXT_TITLE_MSG)
    if "workspace_id" in fields:
        fields["category_id"] = _context_category(
            con, fields["workspace_id"], current["category_id"]
        )
    if not fields:
        return current
    fields["updated_at"] = now()
    clause = ",".join(f"{key}=?" for key in fields)
    with transaction(con):
        con.execute(
            f"UPDATE graph_nodes SET {clause} WHERE id=?", (*fields.values(), current["id"])
        )
    return get_context(con, current["id"])


def delete_context(con, context_id):
    """맥락을 지우면 그 아래 할일은 지우지 않고 연결만 끊는다 — 맥락의 상위는 없으므로 올릴 곳도 없다"""
    current = get_context(con, context_id)
    with transaction(con):
        _drop_node_edges(con, NODE_CONTEXT, str(current["id"]))
        con.execute("DELETE FROM graph_nodes WHERE id=?", (current["id"],))


def ensure_doc(con, ref, title=None):
    """근거 문서 노드. 처음 보는 문서면 만들고, 제목을 주면 비어 있는 제목만 채운다"""
    stamp = now()
    with transaction(con):
        con.execute(
            "INSERT OR IGNORE INTO graph_nodes(kind, ref, title, url, created_by, created_at,"
            " updated_at) VALUES(?,?,?,?,?,?,?)",
            (NODE_DOC, ref, title or evidence_refs.label_of(ref), evidence_refs.url_of(ref), BY_USER,
             stamp, stamp),
        )
        if title:
            con.execute(
                "UPDATE graph_nodes SET title=?, updated_at=? WHERE kind=? AND ref=? AND title=?",
                (title, stamp, NODE_DOC, ref, evidence_refs.label_of(ref)),
            )
    return get_doc(con, ref)


def get_doc(con, ref):
    row = con.execute(
        "SELECT * FROM graph_nodes WHERE kind=? AND ref=?", (NODE_DOC, ref)
    ).fetchone()
    if not row:
        raise NotFound("근거 문서를 찾을 수 없습니다")
    return dict(row)


def docs_by_ref(con):
    return {
        row["ref"]: dict(row)
        for row in con.execute("SELECT * FROM graph_nodes WHERE kind=?", (NODE_DOC,))
    }


# ── 관계 ────────────────────────────────────────────────────────────────


def add_edge(
    con,
    src,
    dst,
    relation,
    basis=None,
    evidence=None,
    state=EDGE_CONFIRMED,
    created_by=BY_USER,
):
    """연결 하나를 저장하고 그 행을 돌려준다. src·dst 는 (종류, id).

    이미 있으면: 사람이 만드는 것이면 상태·기준·근거를 새 값으로 바꾸고, 자동이면 사람이 확정·거절한
    상태를 그대로 두고 제안을 확정으로 올리는 것만 한다 — 거절한 연결이 자동 추출로 되살아나면 안 된다
    """
    src, dst = _node(src), _node(dst)
    relation = _clean_relation(relation)
    state = _clean_state(state)
    if relation == REL_RELATED and dst < src:
        src, dst = dst, src
    _validate_kinds(relation, src, dst)
    if src == dst:
        raise Validation(EDGE_SELF_MSG)
    if relation == REL_PARENT:
        if basis not in PARENT_BASES:
            raise Validation(EDGE_BASIS_MSG)
    else:
        basis = None
    for node in (src, dst):
        _require_node(con, node)
    existing = _find(con, src, dst, relation)
    if existing and not _should_overwrite(existing, state, created_by):
        return existing
    if state != EDGE_REJECTED and relation in ACYCLIC_RELATIONS and reaches(con, relation, dst, src):
        raise Validation(EDGE_CYCLE_MSG)
    if relation == REL_EVIDENCE:
        ensure_doc(con, dst[1])
    stamp = now()
    with transaction(con):
        if existing:
            con.execute(
                "UPDATE edges SET basis=?, evidence=?, state=?, created_by=?, updated_at=? WHERE id=?",
                (basis, evidence, state, created_by, stamp, existing["id"]),
            )
        else:
            con.execute(
                "INSERT INTO edges(src_kind, src_id, dst_kind, dst_id, relation, basis, evidence,"
                " state, created_by, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (*src, *dst, relation, basis, evidence, state, created_by, stamp, stamp),
            )
    return _find(con, src, dst, relation)


def get_edge(con, edge_id):
    row = con.execute("SELECT * FROM edges WHERE id=?", (edge_id,)).fetchone()
    if not row:
        raise NotFound("연결을 찾을 수 없습니다")
    return dict(row)


def set_state(con, edge_id, state):
    """확인(confirmed)·거절(rejected)·제안으로 되돌리기. 거절을 풀 때도 순환을 다시 본다"""
    edge = get_edge(con, edge_id)
    state = _clean_state(state)
    if (
        state != EDGE_REJECTED
        and edge["state"] == EDGE_REJECTED
        and edge["relation"] in ACYCLIC_RELATIONS
        and reaches(con, edge["relation"], _dst(edge), _src(edge))
    ):
        raise Validation(EDGE_CYCLE_MSG)
    with transaction(con):
        con.execute(
            "UPDATE edges SET state=?, updated_at=? WHERE id=?", (state, now(), edge["id"])
        )
        if state == EDGE_REJECTED:
            _release_parent_column(con, edge)
    return get_edge(con, edge["id"])


def update_edge(con, edge_id, basis=None, evidence=None):
    """기준·근거 문장 고치기. 상위가 아니면 기준은 비운다"""
    edge = get_edge(con, edge_id)
    if edge["relation"] == REL_PARENT and basis is not None and basis not in PARENT_BASES:
        raise Validation(EDGE_BASIS_MSG)
    with transaction(con):
        con.execute(
            "UPDATE edges SET basis=COALESCE(?, basis), evidence=COALESCE(?, evidence),"
            " updated_at=? WHERE id=?",
            (basis if edge["relation"] == REL_PARENT else None, evidence, now(), edge["id"]),
        )
    return get_edge(con, edge["id"])


def delete_edge(con, edge_id):
    edge = get_edge(con, edge_id)
    with transaction(con):
        con.execute("DELETE FROM edges WHERE id=?", (edge["id"],))
        _release_parent_column(con, edge)


def list_edges(con, relations=None, states=None):
    where, params = [], []
    if relations:
        where.append(f"relation IN ({_marks(relations)})")
        params += list(relations)
    if states:
        where.append(f"state IN ({_marks(states)})")
        params += list(states)
    clause = f" WHERE {' AND '.join(where)}" if where else ""
    return [dict(row) for row in con.execute(f"SELECT * FROM edges{clause} ORDER BY id", params)]


def edges_of(con, node, include_performs=False):
    """그 노드에 닿은 연결 전부(출발·도착 어느 쪽이든). include_performs 면 수행(뷰)까지"""
    kind, ident = _node(node)
    table = "graph_edges" if include_performs else "edges"
    return [
        dict(row)
        for row in con.execute(
            f"SELECT * FROM {table} WHERE (src_kind=? AND src_id=?) OR (dst_kind=? AND dst_id=?)"
            " ORDER BY created_at",
            (kind, ident, kind, ident),
        )
    ]


def reaches(con, relation, start, target):
    """start 에서 relation 을 따라 내려가 target 에 닿는지(거절된 연결은 빼고). 재귀 CTE —
    UNION 이 이미 본 노드를 거르므로 손으로 고친 DB 에 고리가 있어도 끝난다"""
    start, target = _node(start), _node(target)
    row = con.execute(
        """WITH RECURSIVE reach(kind, ident) AS (
               SELECT ?, ?
               UNION
               SELECT e.dst_kind, e.dst_id FROM edges e
               JOIN reach r ON e.src_kind = r.kind AND e.src_id = r.ident
               WHERE e.relation = ? AND e.state <> ?
           )
           SELECT 1 FROM reach WHERE kind = ? AND ident = ? LIMIT 1""",
        (*start, relation, EDGE_REJECTED, *target),
    ).fetchone()
    return row is not None


def ancestors(con, node, states=(EDGE_CONFIRMED, EDGE_PROPOSED)):
    """상위를 끝까지 거슬러 올라간 노드 [(종류, id)]. 가까운 것부터"""
    kind, ident = _node(node)
    rows = con.execute(
        f"""WITH RECURSIVE up(kind, ident, depth) AS (
               SELECT ?, ?, 0
               UNION
               SELECT e.src_kind, e.src_id, up.depth + 1 FROM edges e
               JOIN up ON e.dst_kind = up.kind AND e.dst_id = up.ident
               WHERE e.relation = ? AND e.state IN ({_marks(states)})
           )
           SELECT kind, ident, MIN(depth) AS depth FROM up WHERE depth > 0
           GROUP BY kind, ident ORDER BY depth, kind, ident""",
        (kind, ident, REL_PARENT, *states),
    )
    return [(row["kind"], row["ident"]) for row in rows]


# ── 할일과 맞물리는 것 ──────────────────────────────────────────────────


def sync_parent_column(con, todo_id, old_parent, new_parent):
    """todos.parent_id 가 바뀌면 그 짝 연결(created_by=parent_id)을 따라 바꾼다. 다른 주체가 만든
    상위 연결은 건드리지 않는다 — 사람이 그래프에서 이은 상위가 열 하나 바꿨다고 사라지면 안 된다"""
    child = (NODE_TODO, str(todo_id))
    if old_parent is not None and old_parent != new_parent:
        con.execute(
            "DELETE FROM edges WHERE src_kind=? AND src_id=? AND dst_kind=? AND dst_id=?"
            " AND relation=? AND created_by=?",
            (NODE_TODO, str(old_parent), *child, REL_PARENT, BY_PARENT_COLUMN),
        )
    if new_parent is not None:
        stamp = now()
        con.execute(
            "INSERT OR IGNORE INTO edges(src_kind, src_id, dst_kind, dst_id, relation, basis,"
            " evidence, state, created_by, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (NODE_TODO, str(new_parent), *child, REL_PARENT, "background",
             "상위 할일(parent_id)로 지정", EDGE_CONFIRMED, BY_PARENT_COLUMN, stamp, stamp),
        )


def drop_todo(con, todo_id):
    """할일을 지울 때. 그 할일의 하위는 그 할일의 상위 밑으로 한 단계 올린다(parent_id 와 같은 규칙) —
    중간 하나를 지웠다고 아래 가지가 루트로 흩어지면 왜 생긴 일인지가 사라진다. 트랜잭션은 부르는 쪽"""
    node = (NODE_TODO, str(todo_id))
    parents = _parent_edges(con, node, incoming=True)
    children = _parent_edges(con, node, incoming=False)
    stamp = now()
    for parent in parents:
        for child in children:
            if (parent["src_kind"], parent["src_id"]) == (child["dst_kind"], child["dst_id"]):
                continue
            state = EDGE_PROPOSED if EDGE_PROPOSED in (parent["state"], child["state"]) else EDGE_CONFIRMED
            con.execute(
                "INSERT OR IGNORE INTO edges(src_kind, src_id, dst_kind, dst_id, relation, basis,"
                " evidence, state, created_by, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (parent["src_kind"], parent["src_id"], child["dst_kind"], child["dst_id"], REL_PARENT,
                 child["basis"], f"중간 할일 #{todo_id} 를 지워 한 단계 올림 — {child['evidence'] or ''}".rstrip(" —"),
                 state, child["created_by"], stamp, stamp),
            )
    _drop_node_edges(con, *node)


def sync_text_evidence(con, todo_id, title, note):
    """제목·note 에 적힌 문서 키를 근거로 잇는다. 이 경로로 만든 연결(created_by=auto:note)만 맞춘다 —
    note 에서 키가 빠지면 걷고, 사람이 잇거나 재구성이 대화에서 찾은 근거는 그대로 둔다"""
    ident = str(todo_id)
    refs = evidence_refs.extract(f"{title or ''}\n{note or ''}")
    current = {
        row["dst_id"]: row
        for row in con.execute(
            "SELECT * FROM edges WHERE relation=? AND src_kind=? AND src_id=?",
            (REL_EVIDENCE, NODE_TODO, ident),
        )
    }
    with transaction(con):
        for ref, row in current.items():
            if row["created_by"] == BY_NOTE and ref not in refs:
                con.execute("DELETE FROM edges WHERE id=?", (row["id"],))
    for ref in refs:
        if ref not in current:
            add_edge(
                con, (NODE_TODO, ident), (NODE_DOC, ref), REL_EVIDENCE,
                evidence="제목·note 에 적힘", created_by=BY_NOTE,
            )
    refresh_shared_related(con, todo_id)


def record_spawn(con, claude_session_id, origin_session_id=None, manager_task_id=None, title=None):
    """매니저가 세션을 띄웠다는 기록. 그 세션이 이미 할일을 잡았으면 바로 상위 제안을 잇고,
    아니면 할일을 잡을 때(link_todo → apply_origin) 잇는다. 같은 세션을 다시 적으면 덮는다"""
    with transaction(con):
        con.execute(
            "INSERT INTO session_origins(claude_session_id, origin_session_id, manager_task_id, title,"
            " created_at) VALUES(?,?,?,?,?) ON CONFLICT(claude_session_id) DO UPDATE SET"
            " origin_session_id=excluded.origin_session_id, manager_task_id=excluded.manager_task_id,"
            " title=excluded.title",
            (claude_session_id, origin_session_id, manager_task_id, title, now()),
        )
    linked = [
        row["todo_id"]
        for row in con.execute(
            "SELECT st.todo_id FROM session_todos st JOIN sessions s ON s.id = st.session_id"
            " WHERE s.claude_session_id=?",
            (claude_session_id,),
        )
    ]
    made = []
    for todo_id in linked:
        made += apply_origin(con, claude_session_id, todo_id)
    return made


def origin_todos(con, claude_session_id):
    """그 세션을 띄운 출처 세션이 띄울 때 붙잡고 있던 할일(가장 최근 연결 하나). 없으면 []"""
    origin = con.execute(
        "SELECT * FROM session_origins WHERE claude_session_id=?", (claude_session_id,)
    ).fetchone()
    if not origin or not origin["origin_session_id"]:
        return origin, []
    row = con.execute(
        "SELECT st.todo_id FROM session_todos st JOIN sessions s ON s.id = st.session_id"
        " WHERE s.claude_session_id=? AND st.created_at<=? ORDER BY st.created_at DESC LIMIT 1",
        (origin["origin_session_id"], origin["created_at"]),
    ).fetchone()
    return origin, [row["todo_id"]] if row else []


def apply_origin(con, claude_session_id, todo_id):
    """띄운 세션이 할일을 잡으면 출처 세션의 할일을 그 할일의 상위(계기)로 '제안' 한다 — 확정은 사람이.
    순환·자기 자신이면 조용히 건너뛴다(제안 하나 때문에 할일 연결이 실패하면 안 된다)"""
    origin, parents = origin_todos(con, claude_session_id)
    made = []
    for parent_id in parents:
        if parent_id == todo_id:
            continue
        reason = f"매니저가 출처 세션 {origin['origin_session_id'][:8]} 의 할일 #{parent_id} 에서 띄움"
        if origin["title"]:
            reason += f" — '{origin['title']}'"
        if origin["manager_task_id"]:
            reason += f" (매니저 할일 {origin['manager_task_id']})"
        try:
            made.append(add_edge(
                con, (NODE_TODO, parent_id), (NODE_TODO, todo_id), REL_PARENT,
                basis=BASIS_TRIGGER, evidence=reason, state=EDGE_PROPOSED, created_by=BY_SPAWN,
            ))
        except Validation:
            continue
    return made


def refresh_shared_related(con, todo_id):
    """같은 근거 문서를 가리키는 할일끼리 관련(자동)으로 잇는다. 그 할일과 문서를 공유하는 할일들까지
    다시 계산한다 — 문서 하나에 할일이 늘어 묶음(SHARED_DOC_MAX_TODOS 초과)이 되면 그 쌍들은 걷는다"""
    touched = {str(todo_id)} | _doc_partners(con, str(todo_id))
    for ident in touched:
        _refresh_shared_for(con, ident)


def _refresh_shared_for(con, ident):
    wanted = {}
    for ref, members in _docs_of_todo(con, ident).items():
        if len(members) > SHARED_DOC_MAX_TODOS:
            continue
        for other in members - {ident}:
            wanted.setdefault(other, ref)
    current = {
        (row["dst_id"] if row["src_id"] == ident else row["src_id"]): row
        for row in con.execute(
            "SELECT * FROM edges WHERE relation=? AND created_by=? AND src_kind=? AND dst_kind=?"
            " AND (src_id=? OR dst_id=?)",
            (REL_RELATED, BY_SHARED_DOC, NODE_TODO, NODE_TODO, ident, ident),
        )
    }
    with transaction(con):
        for other, row in current.items():
            if other not in wanted and row["state"] != EDGE_REJECTED:
                con.execute("DELETE FROM edges WHERE id=?", (row["id"],))
    for other, ref in wanted.items():
        if other in current or _linked_otherwise(con, ident, other):
            continue
        add_edge(
            con,
            (NODE_TODO, ident),
            (NODE_TODO, other),
            REL_RELATED,
            evidence=f"같은 근거 {evidence_refs.label_of(ref)}",
            state=EDGE_CONFIRMED,
            created_by=BY_SHARED_DOC,
        )


def _docs_of_todo(con, ident):
    """그 할일의 근거 문서 → 그 문서를 근거로 둔 할일 id 집합"""
    rows = con.execute(
        """SELECT e2.dst_id AS ref, e2.src_id AS todo FROM edges e1
           JOIN edges e2 ON e2.dst_kind = e1.dst_kind AND e2.dst_id = e1.dst_id
           WHERE e1.relation = ? AND e1.src_kind = ? AND e1.src_id = ? AND e1.state <> ?
             AND e2.relation = ? AND e2.src_kind = ? AND e2.state <> ?""",
        (REL_EVIDENCE, NODE_TODO, ident, EDGE_REJECTED, REL_EVIDENCE, NODE_TODO, EDGE_REJECTED),
    )
    found = {}
    for row in rows:
        found.setdefault(row["ref"], set()).add(row["todo"])
    return found


def shared_doc_partners(con, todo_id):
    """그 할일과 근거 문서를 하나라도 공유하는 다른 할일 id(글자) 집합"""
    return _doc_partners(con, str(todo_id))


def _doc_partners(con, ident):
    partners = set()
    for members in _docs_of_todo(con, ident).values():
        partners |= members
    return partners - {ident}


def _linked_otherwise(con, a, b):
    """상위·선행으로 이미 이어진 쌍이면 관련은 군더더기다 — 관련은 '위 어느 것도 아닌' 경우만"""
    row = con.execute(
        f"""SELECT 1 FROM edges WHERE relation IN (?,?) AND state <> ?
            AND src_kind = ? AND dst_kind = ?
            AND ((src_id = ? AND dst_id = ?) OR (src_id = ? AND dst_id = ?)) LIMIT 1""",
        (REL_PARENT, REL_PRECEDES, EDGE_REJECTED, NODE_TODO, NODE_TODO, a, b, b, a),
    ).fetchone()
    return row is not None


# ── 내부 ────────────────────────────────────────────────────────────────


def _should_overwrite(existing, state, created_by):
    if created_by == BY_USER:
        return True
    if existing["created_by"] == BY_USER or existing["state"] == EDGE_REJECTED:
        return False
    return STATE_RANK.get(state, 0) > STATE_RANK.get(existing["state"], 0)


def _release_parent_column(con, edge):
    """parent_id 와 짝인 상위 연결을 지우거나 거절하면 그 열도 비운다 — 되돌렸을 때 옛 트리가
    지운 상위를 되살리면 안 된다"""
    if edge["relation"] != REL_PARENT or edge["src_kind"] != NODE_TODO or edge["dst_kind"] != NODE_TODO:
        return
    con.execute(
        "UPDATE todos SET parent_id=NULL, updated_at=? WHERE id=? AND parent_id=?",
        (now(), int(edge["dst_id"]), int(edge["src_id"])),
    )


def _parent_edges(con, node, incoming):
    column = "dst" if incoming else "src"
    return [
        dict(row)
        for row in con.execute(
            f"SELECT * FROM edges WHERE relation=? AND state<>? AND {column}_kind=? AND {column}_id=?",
            (REL_PARENT, EDGE_REJECTED, *node),
        )
    ]


def _drop_node_edges(con, kind, ident):
    con.execute(
        "DELETE FROM edges WHERE (src_kind=? AND src_id=?) OR (dst_kind=? AND dst_id=?)",
        (kind, ident, kind, ident),
    )


def _find(con, src, dst, relation):
    row = con.execute(
        "SELECT * FROM edges WHERE src_kind=? AND src_id=? AND dst_kind=? AND dst_id=? AND relation=?",
        (*src, *dst, relation),
    ).fetchone()
    return dict(row) if row else None


def _require_node(con, node):
    kind, ident = node
    if kind == NODE_TODO:
        row = con.execute("SELECT 1 FROM todos WHERE id=?", (_int(ident),)).fetchone()
    elif kind == NODE_CONTEXT:
        row = con.execute(
            "SELECT 1 FROM graph_nodes WHERE id=? AND kind=?", (_int(ident), NODE_CONTEXT)
        ).fetchone()
    elif kind == NODE_SESSION:
        row = con.execute(
            "SELECT 1 FROM sessions WHERE claude_session_id=?", (ident,)
        ).fetchone()
    else:
        # 문서는 처음 이을 때 만든다(ensure_doc). 키 모양만 본다
        row = True if evidence_refs.url_of(ident) else None
    if not row:
        raise NotFound(f"연결할 대상을 찾을 수 없습니다: {kind} {ident}")


def _validate_kinds(relation, src, dst):
    sources, targets = RELATION_KINDS[relation]
    if src[0] not in sources or dst[0] not in targets:
        raise Validation(EDGE_KIND_MSG)


def _clean_relation(relation):
    if relation not in RELATION_KINDS:
        raise Validation(EDGE_RELATION_MSG)
    return relation


def _clean_state(state):
    if state not in EDGE_STATES:
        raise Validation(EDGE_STATE_MSG)
    return state


def _node(node):
    kind, ident = node
    if kind not in (NODE_TODO, NODE_CONTEXT, NODE_DOC, NODE_SESSION):
        raise Validation(EDGE_KIND_MSG)
    return (kind, str(ident).strip())


def _src(edge):
    return (edge["src_kind"], edge["src_id"])


def _dst(edge):
    return (edge["dst_kind"], edge["dst_id"])


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise Validation(f"번호가 아닙니다: {value}")


def _context_category(con, workspace_id, category_id):
    if workspace_id is None:
        return category_id
    row = con.execute("SELECT category_id FROM workspaces WHERE id=?", (workspace_id,)).fetchone()
    if not row:
        raise NotFound("워크스페이스를 찾을 수 없습니다")
    return row["category_id"]


def _marks(values):
    return ",".join("?" * len(values))
