"""仓库中的位置。评测代码不导入被测系统（evaluation_draft §10.1），仓库根目录按本文件的位置推出。"""

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
EVAL = REPO / "eval"
SEEDS = EVAL / "seeds"

__all__ = ["EVAL", "REPO", "SEEDS"]
