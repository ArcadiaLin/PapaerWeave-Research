"""Skill：怎样做出某类文档（docs/discussions/2026-10-13-skills-catalog-and-checkin.md §2、§9）。

用 Agent Skills 格式：头部是 ``name``、``description`` 与 ``metadata``，``type: Skill`` 以及取出时的 ``id``、
``base`` 写在 ``metadata`` 下。``name`` 是身份键，也是检索的标题；v1 约定它就是所服务的类型名（如
``leaderboard``、``paper-form``），每个类型一份，共同编辑。``description`` 是检索的摘要。

取出时写到写者工作目录的 ``.agents/skills/<name>/SKILL.md``，pi 启动时从这里扫描 skill。正文按行比对。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from ..document import Parsed
from .base import ArtifactType, Report, header_line, identity, normalize

NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")  # Agent Skills 规范：小写字母、数字与连字符
NAME_MAX = 64
DESCRIPTION_MAX = 1024


class Skill(ArtifactType):
    name = "Skill"
    nested = True

    def title(self, header: Mapping[str, Any]) -> str:
        return normalize(header.get("name"))

    def abstract(self, header: Mapping[str, Any]) -> str:
        return str(header.get("description") or "").strip()

    def key(self, header: Mapping[str, Any]) -> str | None:
        return identity(self.name, self.title(header))

    def check(self, doc: Parsed, report: Report) -> None:
        name = doc.header.get("name")
        if not (isinstance(name, str) and NAME.fullmatch(name) and len(name) <= NAME_MAX):
            msg = f"name is required: lowercase letters, digits and hyphens, at most {NAME_MAX} characters"
            report("schema", header_line(doc, "name"), msg)
        description = doc.header.get("description")
        if not (isinstance(description, str) and description.strip() and len(description) <= DESCRIPTION_MAX):
            msg = (
                f"description is required: what the skill does and when to use it, at most {DESCRIPTION_MAX} characters"
            )
            report("schema", header_line(doc, "description"), msg)

    def checkout_path(self, header: Mapping[str, Any]) -> str:
        return f".agents/skills/{self.title(header)}/SKILL.md"


SKILL = Skill()

__all__ = ["SKILL", "Skill"]
