"""Verify：一条主张在给定证据下是否成立、在什么范围内成立（docs/designs/v2/operators.md §4.4）。v1 只登记契约，
不写种子。

- **身份键：** 头部的 ``claim``（被核查的主张的 id）：一条主张一份核查，共同编辑。
- **强制：** ``verdict`` 为三值 ``T`` / ``F`` / ``U``；``T`` 与 ``F`` 时正文至少有一处引用，``U`` 时正文写明原因。
- ``scope`` 可选，写成立的范围。正文按行比对。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ...model.refs import NODE_ID
from ..document import Parsed
from .base import ArtifactType, Mention, Report, cited_paragraphs, header_line, identity, leading_id

VERDICTS = ("T", "F", "U")


class Verify(ArtifactType):
    name = "Verify"
    identity_fields = ("claim",)

    def key(self, header: Mapping[str, Any]) -> str | None:
        return identity(self.name, leading_id(str(header.get("claim") or "")))

    def check(self, doc: Parsed, report: Report) -> None:
        super().check(doc, report)
        claim = doc.header.get("claim")
        if not (isinstance(claim, str) and NODE_ID.fullmatch(leading_id(claim))):
            report(
                "schema", header_line(doc, "claim"), "claim is required: the id of the claim checked, e.g. claim_0042"
            )
        verdict = doc.header.get("verdict")
        if verdict not in VERDICTS:
            report("schema", header_line(doc, "verdict"), "verdict is T (holds), F (does not hold) or U (undecided)")
            return
        paragraphs = cited_paragraphs(doc)
        if verdict in ("T", "F") and not any(c for _, c in paragraphs):
            report("schema", doc.body_start, f"verdict {verdict} needs at least one citation in the text")
        if verdict == "U" and not paragraphs:
            report("schema", doc.body_start, "verdict U needs the reason in the text")

    def mentions(self, doc: Parsed) -> list[Mention]:
        claim = leading_id(str(doc.header.get("claim") or ""))
        head = [Mention(header_line(doc, "claim"), claim, "claim")] if NODE_ID.fullmatch(claim) else []
        return head + super().mentions(doc)


VERIFY = Verify()

__all__ = ["VERIFY", "Verify"]
