"""PaperWeave 的 MCP 暴露：``server.yml`` 是给模型看的全部文字，:mod:`.spec` 按它装配工具，:mod:`.server` 提供服务。"""

from .server import enabled, main, serve
from .spec import SPEC, Spec, SpecError, load

__all__ = ["SPEC", "Spec", "SpecError", "enabled", "load", "main", "serve"]
