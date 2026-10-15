"""沙箱怎样找到 pi：npm 全局安装随 node 挂载；托管安装只挂当前版本的 release 目录，不挂 ``~/.pi/agent``。"""

from __future__ import annotations

from pathlib import Path

import pytest

from t1 import sandbox
from t1.sandbox import PI_DIR, pi_install


def _fake_which(node: Path):
    return lambda name: str(node) if name == "node" else None


def test_npm_global_pi_comes_with_node(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bin_dir = tmp_path / "node/bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "node").touch()
    (bin_dir / "pi").touch()
    monkeypatch.setattr(sandbox.shutil, "which", _fake_which(bin_dir / "node"))
    assert pi_install(str(bin_dir / "pi")) == (None, "pi")


def test_managed_pi_mounts_only_the_current_release(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = tmp_path / ".pi/agent"
    release = agent / "install/releases/1.2.0"
    (release / "node_modules/.bin").mkdir(parents=True)
    (release / "node_modules/.bin/pi").touch()
    (agent / "install/current-version").write_text("1.2.0\n", encoding="utf-8")
    (agent / "bin").mkdir()
    (agent / "bin/pi").touch()
    link = tmp_path / ".local/bin/pi"
    link.parent.mkdir(parents=True)
    link.symlink_to(agent / "bin/pi")
    (tmp_path / "usr/bin").mkdir(parents=True)
    monkeypatch.setattr(sandbox.shutil, "which", _fake_which(tmp_path / "usr/bin/node"))
    assert pi_install(str(link)) == (release.resolve(), f"{PI_DIR}/node_modules/.bin/pi")

    (agent / "install/current-version").write_text("9.9.9\n", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="missing"):
        pi_install(str(link))
