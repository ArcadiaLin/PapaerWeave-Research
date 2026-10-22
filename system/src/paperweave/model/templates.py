"""空白模板：``checkout`` 的 ``new`` 给出的 graph-doc 片段，按 :mod:`.schema` 的登记表生成，不另写一份。

模板是可以直接填写的 graph-doc：字段后的注释说明写什么，长文字已是 ``|`` 块，出边按这个 kind 能连的关系列出。
"""

from __future__ import annotations

from .schema import CHOICES, EDGE_GLOSS, FIELD_GLOSS, FIELDS, KIND_SPECS, RELATIONSHIPS, ROLES, endpoints

_ORDER = ("name", "alias", "identities", "year", "source", "paper", "anchor", "figures", "description", "extra", "stub")
_REQUIRED_NOTE = {"Entity": ("name",), "Concept": ("name", "description"), "Content": ("paper", "anchor", "description")}


def template(kind: str) -> str:
    """一个 kind 的新节点模板（``create`` 下的一项），缩进两格。"""
    spec = KIND_SPECS[kind]
    var = f"$new_{kind.lower()}"
    lines = [f"  {var}:".ljust(35) + f" # {kind}: {spec.gloss}", f"    kind: {kind}"]
    required = _REQUIRED_NOTE[spec.family]
    for name in _ORDER:
        if name not in FIELDS[kind] or name == "stub" and not spec.stub:
            continue
        note = FIELD_GLOSS[name] + (" (required)" if name in required else "")
        if name in ("description",):
            lines += [f"    {name}: |".ljust(35) + f" # {note}", "      ..."]
        elif name == "extra":
            lines += [f"    {name}:".ljust(35) + f" # {note}", "      key: value"]
        elif name in ("alias", "identities", "source", "anchor", "figures"):
            lines.append(f"    {name}: []".ljust(35) + f" # {note}")
        else:
            lines.append(f"    {name}:".ljust(35) + f" # {note}")
    for rel_type, rel in RELATIONSHIPS.items():
        if not any(kind in srcs for srcs, _ in rel.ends):
            continue
        props = ", ".join(rel.props) if rel.props else ""
        req = f"; requires {', '.join(sorted(rel.required))}" if rel.required else ""
        lines.append(f"    {rel_type}:".ljust(35) + f" # {rel.gloss}: {endpoints(rel_type)}{req}")
        lines.append("      <target id or $name>:" + (f"        # properties: {props}" if props else ""))
        for prop in rel.props:
            if prop == "role":
                gloss = " | ".join(ROLES[rel_type]) + (" (required)" if "role" in rel.required else "")
            elif (rel_type, prop) in CHOICES:
                gloss = EDGE_GLOSS[prop]
            else:
                gloss = EDGE_GLOSS[prop]
            lines.append(f"        {prop}:".ljust(35) + f" # {gloss}")
    return "\n".join(lines) + "\n"


def templates(kinds: list[str]) -> str:
    """一份含这些 kind 的模板的 graph-doc。删掉不用的字段与关系；``$`` 名改成有意义的名字。"""
    head = (
        "# Fill in and delete what you do not use, then commit this file.\n"
        "# Long text goes in | blocks; quote short text that contains ': ' with double quotes.\n"
        "graph-doc: v0.2\ncreate:\n"
    )
    return head + "\n".join(template(k) for k in kinds)


def vocabulary() -> dict[str, str]:
    """工具说明中的词表：``kinds``（kind、类别、一句话含义、字段）与 ``relations``（关系、端点、属性）。"""
    kinds = []
    for family in ("Entity", "Concept", "Content"):
        names = [k for k, s in KIND_SPECS.items() if s.family == family]
        kinds.append(f"- {family}:")
        for k in names:
            spec = KIND_SPECS[k]
            own = f"; also {', '.join(spec.own_fields)}" if spec.own_fields else ""
            kinds.append(f"  - {k}: {spec.gloss}{own}")
    fields = {
        "Entity": "name*, alias, identities, description, extra, stub",
        "Concept": "name*, alias, description*, extra, stub",
        "Content": "paper*, anchor*, description*, extra",
    }
    kinds.append("Fields (* required; a stub needs only name): " + "; ".join(f"{f}: {v}" for f, v in fields.items()))
    rels = []
    for rel_type, rel in RELATIONSHIPS.items():
        props = []
        for prop in rel.props:
            values = ROLES.get(rel_type) if prop == "role" else CHOICES.get((rel_type, prop))
            mark = "*" if prop in rel.required else ""
            props.append(f"{prop}{mark}" + (f" ({' | '.join(values)})" if values else ""))
        if "description" in rel.required:
            props.append("description*")
        tail = f" [{', '.join(props)}]" if props else ""
        rels.append(f"- {rel_type}: {endpoints(rel_type)}: {rel.gloss}{tail}")
    return {"kinds": "\n".join(kinds), "relations": "\n".join(rels)}


__all__ = ["template", "templates", "vocabulary"]
