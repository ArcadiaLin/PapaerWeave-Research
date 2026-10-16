"""会话开始时的库总览：MCP 服务启动时按当前库生成，附在 ``search`` 的工具说明末尾（docs/designs/v3/tools.md）。

pi 以 direct 方式列出工具时，模型看不到服务的 ``instructions``，工具说明却每轮都在模型面前；所以总览放在说明里，
让写者不必主动去想，就知道库里已有哪些论文与前人的产物。是会话开始时的快照：写者轮流运行，会话中只多出自己写的。
"""

from __future__ import annotations

from ..model.schema import ARTIFACT, ARTIFACT_TYPES, KIND_SPECS
from ..store.store import Store

PAPERS = 20  # 列出标题的论文数上限
RECENT = 3  # 每种产物列出最近几份


def overview(store: Store) -> str:
    counts = {r["kind"]: r["n"] for r in store.query(
        "MATCH (n:Searchable) WHERE NOT n:Artifact UNWIND labels(n) AS kind WITH kind, count(*) AS n "
        "WHERE kind IN $kinds RETURN kind, n", kinds=list(KIND_SPECS))}
    if not counts:
        return "The store is empty: no papers have been recorded yet."
    lines = ["Store at the start of this session:"]
    lines.append("- " + ", ".join(f"{counts[k]} {k}" for k in KIND_SPECS if counts.get(k)))
    papers = store.query(
        "MATCH (p:Paper) WHERE p.stub IS NULL OR p.stub = false "
        "RETURN p.id AS id, p.name AS name, p.year AS year ORDER BY p.id"
    )
    if papers:
        lines.append(f"- papers with text ({len(papers)}):")
        for p in papers[:PAPERS]:
            title = p["name"] if len(p["name"] or "") <= 80 else p["name"][:79] + "…"
            lines.append(f"  - {p['id']}: {title}{f' ({p['year']})' if p['year'] else ''}")
        if len(papers) > PAPERS:
            lines.append(f"  - … {len(papers) - PAPERS} more (search with kind: [Paper])")
    arts = store.query(
        f"MATCH (a:{ARTIFACT}) WHERE a.op IN $types RETURN a.op AS type, a.id AS id, a.title AS title "
        "ORDER BY a.formed_at DESC",
        types=list(ARTIFACT_TYPES),
    )
    if arts:
        lines.append("- artifacts earlier sessions made (search with kind: [<type>], read with checkout):")
        for kind in ARTIFACT_TYPES:
            mine = [a for a in arts if a["type"] == kind]
            if mine:
                shown = "; ".join(f"{a['id']} {a['title']}" for a in mine[:RECENT])
                more = f"; … {len(mine) - RECENT} more" if len(mine) > RECENT else ""
                lines.append(f"  - {kind} ({len(mine)}): {shown}{more}")
    else:
        lines.append("- no artifacts yet")
    return "\n".join(lines)


__all__ = ["overview"]
