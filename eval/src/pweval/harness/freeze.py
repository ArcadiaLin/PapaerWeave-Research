"""写者时间线代码的冻结副本（f3 工程记录 4.6 第 3 条）：正式运行从副本启动，主工作区之后的改动（如 M2 的开发）
影响不到运行中的会话。

    uv run --frozen python -m pweval.harness.freeze <commit> [--dest ~/pw-lab/frozen]   # 在仓库根目录

步骤：

1. ``git worktree add --detach <dest>/<commit 短号> <commit>``；
2. 在副本根目录建它自己的 ``.venv``，只装 system 与 eval 两个包（``uv sync --frozen``，版本由锁文件固定）；
3. 预编译副本中的源码与 ``.venv``，再把副本中属于当前用户的文件与目录全部去掉写权限。第三方包是 uv 缓存的
   硬链接，不属于当前用户，改不了权限，版本由锁文件固定；
4. 用副本自己的解释器核对冻结条件（:func:`pweval.harness.timeline.frozen_problems`）并打印代码指纹。

启动：``<副本>/.venv/bin/python -m pweval.harness.timeline <运行名> …``。撤除：``chmod -R u+w <副本>`` 后
``git worktree remove <副本>``。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from ..paths import REPO

DEST = Path("~/pw-lab/frozen").expanduser()
CHECK = ("import json; from pweval.harness.timeline import code_fingerprint, frozen_problems; "
         "print(json.dumps({'problems': frozen_problems(), 'code': code_fingerprint()}))")  # fmt: skip


def _run(*args: str | Path, cwd: Path = REPO) -> str:
    return subprocess.run([str(a) for a in args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def freeze(commit: str, dest: Path = DEST) -> Path:
    short = _run("git", "rev-parse", "--short=7", f"{commit}^{{commit}}").strip()
    copy = dest / short
    if copy.exists():
        raise SystemExit(f"{copy} exists; remove it first (chmod -R u+w, then git worktree remove)")
    dest.mkdir(parents=True, exist_ok=True)
    _run("git", "worktree", "add", "--detach", copy, short)
    _run("uv", "sync", "--frozen", "--no-default-groups", "--package", "paperweave-eval", "--package", "paperweave",
         cwd=copy)  # fmt: skip
    python = copy / ".venv/bin/python"
    _run(python, "-m", "compileall", "-q", "system/src", "eval/src", "eval/baselines", "packages/graph-doc/src",
         "packages/graph-vc/src", ".venv/lib", cwd=copy)  # fmt: skip
    me = os.getuid()
    for root, dirs, files in os.walk(copy, topdown=False):
        for name in [*files, *dirs, None]:
            path = Path(root, name) if name else Path(root)
            st = path.lstat()
            if st.st_uid == me and not path.is_symlink():
                path.chmod(st.st_mode & ~0o222)
    result = json.loads(_run(python, "-c", CHECK, cwd=copy))
    if result["problems"]:
        raise SystemExit(f"{copy} is not frozen:\n" + "\n".join(result["problems"]))
    print(f"code fingerprint {result['code']['sha256']} ({result['code']['files']} files)")
    return copy


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("commit")
    parser.add_argument("--dest", default=str(DEST))
    args = parser.parse_args(argv)
    print(freeze(args.commit, Path(args.dest).expanduser()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
