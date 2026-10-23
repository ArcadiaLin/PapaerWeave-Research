"""f3 写者组的离线读者：读者配置的合并、读者沙箱、放行名单的核对与证据请求的统计（库的恢复与核对要真实容器，
在运行中由 ``--check-only`` 检查）。"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from pweval.harness import store_readers
from pweval.harness.store_readers import HIDDEN, TOOLS

WRITERS = {
    "probes_repo": "~/probes", "corpus_papers": "~/papers", "code": "~/code", "workdir_root": "~/runs",
    "plan": "tasks/plan-f3.yml", "materials": "tasks/materials.yml", "seed": "seed/f3",
    "arms": {"A3": {"neo4j": "bolt://localhost:7696", "neo4j_container": "neo4j-a3", "llm": "http://h:30000/v1"},
             "A2": {"neo4j": "bolt://localhost:7697", "neo4j_container": "neo4j-a2", "llm": "http://h:30000/v1",
                    "ablate": ["dedup"]}},
    "runner": {"model": "sglang/m", "probe_timeout_min": 15, "reader_workers": 4, "thinking": "medium"},
}  # fmt: skip
READERS = {"writers": "w.yml", "llm": "http://h:30000/v1",
           "arms": {"A3": {"neo4j": "bolt://localhost:7700", "neo4j_container": "neo4j-a3-reader"}},
           "runner": {"probe_timeout_min": 60, "max_tool_calls": 300}}  # fmt: skip


def configs(tmp_path: Path, readers: dict = READERS) -> Path:
    (tmp_path / "w.yml").write_text(yaml.safe_dump(WRITERS))
    (tmp_path / "r.yml").write_text(yaml.safe_dump(readers))
    return tmp_path / "r.yml"


def test_the_reader_config_overrides_only_what_readers_change(tmp_path: Path) -> None:
    config = store_readers.load(configs(tmp_path))
    assert config["arms"]["A3"] == {"neo4j": "bolt://localhost:7700", "neo4j_container": "neo4j-a3-reader",
                                    "llm": "http://h:30000/v1"}  # fmt: skip
    assert list(config["arms"]) == ["A3"]  # 没有声明读者库的组不留，不会回退到写者的库
    assert config["writer_stores"]["A2"] == {"neo4j": "bolt://localhost:7697", "neo4j_container": "neo4j-a2"}
    a2 = {**READERS, "arms": {"A2": {"neo4j": "bolt://localhost:7701", "neo4j_container": "neo4j-a2-reader"}}}
    assert store_readers.load(configs(tmp_path, a2))["arms"]["A2"]["ablate"] == ["dedup"]  # 其余项取写者配置
    assert config["runner"] == {**WRITERS["runner"], "probe_timeout_min": 60, "max_tool_calls": 300}
    assert config["writers_sha256"] == hashlib.sha256((tmp_path / "w.yml").read_bytes()).hexdigest()
    assert config["probes_repo"] == Path("~/probes").expanduser()


@pytest.mark.parametrize(("spec", "message"), [
    ({"neo4j": "bolt://localhost:7700", "neo4j_container": "neo4j-a3"}, "writers' store \\(neo4j-a3\\)"),
    ({"neo4j": "bolt://localhost:7700", "neo4j_container": "neo4j-a2"}, "writers' store \\(neo4j-a2\\)"),  # 别组的也不行
    ({"neo4j": "bolt://localhost:7697", "neo4j_container": "neo4j-x"}, "writers' store \\(bolt://localhost:7697\\)"),
    ({"neo4j_container": "neo4j-x"}, "own store \\(neo4j missing\\)"),
    ({"neo4j": "bolt://localhost:7700"}, "own store \\(neo4j_container missing\\)"),
])  # fmt: skip
def test_readers_must_declare_their_own_store(tmp_path: Path, spec: dict, message: str) -> None:
    with pytest.raises(SystemExit, match=message):
        store_readers.load(configs(tmp_path, {**READERS, "arms": {"A3": spec}}))


def container(data: Path, port: str = "7687", *, rm: bool = False, logs: Path | None = None) -> dict:
    mounts = [{"Source": str(data), "Destination": "/data"}] + ([{"Source": str(logs), "Destination": "/logs"}] if logs else [])
    return {"HostConfig": {"AutoRemove": rm, "PortBindings": {"7687/tcp": [{"HostIp": "", "HostPort": port}]}},
            "Mounts": mounts}  # fmt: skip


def inspect(monkeypatch, found: dict) -> None:
    """假的 docker inspect：``found`` 中的值为容器、``None``（Docker 答复不存在）或异常（查询失败）。"""

    def fake(name: str) -> dict | None:
        value = found[name]
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(store_readers, "_inspect", fake)


def test_the_guard_runs_before_any_restore(tmp_path: Path, monkeypatch) -> None:
    config = store_readers.load(configs(tmp_path))
    reader, w3, w2 = tmp_path / "r3/data", tmp_path / "w3/data", tmp_path / "w2/data"
    ok = {"neo4j-a3-reader": container(reader, "7700"), "neo4j-a3": container(w3), "neo4j-a2": container(w2)}
    inspect(monkeypatch, ok)
    assert store_readers.guard(config, "A3") == reader.resolve()
    with pytest.raises(RuntimeError, match="no readers' store"):
        store_readers.guard(config, "A2")
    with pytest.raises(RuntimeError, match="no readers' store"):
        store_readers.reader_arm(config, tmp_path, tmp_path, "A2", 10, "p")
    inspect(monkeypatch, {**ok, "neo4j-a3-reader": container(w3, "7700")})  # 读者容器挂着写者的数据目录
    with pytest.raises(RuntimeError, match="overlaps .* of the writers' neo4j-a3"):
        store_readers.guard(config, "A3")
    inspect(monkeypatch, {**ok, "neo4j-a3-reader": container(tmp_path / "w2", "7700")})  # 包含写者的数据目录也不行
    with pytest.raises(RuntimeError, match="overlaps"):
        store_readers.guard(config, "A3")
    inspect(monkeypatch, {**ok, "neo4j-a2": container(w2, logs=reader)})  # 写者的其他挂载也算
    with pytest.raises(RuntimeError, match="overlaps .* of the writers' neo4j-a2"):
        store_readers.guard(config, "A3")
    inspect(monkeypatch, {**ok, "neo4j-a3-reader": container(reader, "7701")})  # 地址连的不是这个容器
    with pytest.raises(RuntimeError, match="not the bolt port of neo4j-a3-reader"):
        store_readers.guard(config, "A3")

    def never(*args, **kwargs):
        raise AssertionError("restore must not start")

    monkeypatch.setattr(store_readers, "restore", never)
    with pytest.raises(RuntimeError, match="not the bolt port"):
        store_readers.run_readers(config, tmp_path, tmp_path, "A3", 10, ["main"])
    with pytest.raises(RuntimeError, match="no readers' store"):
        store_readers.run_readers(config, tmp_path, tmp_path, "A2", 10, ["main"])


def test_the_guard_skips_a_writers_container_only_when_docker_says_it_does_not_exist(tmp_path: Path,
                                                                                      monkeypatch) -> None:  # fmt: skip
    config = store_readers.load(configs(tmp_path))
    reader = tmp_path / "r3/data"
    ok = {"neo4j-a3-reader": container(reader, "7700"), "neo4j-a3": container(tmp_path / "w3/data"), "neo4j-a2": None}
    inspect(monkeypatch, ok)
    assert store_readers.guard(config, "A3") == reader.resolve()  # 写者的 neo4j-a2 不存在：跳过
    inspect(monkeypatch, {**ok, "neo4j-a2": RuntimeError("docker inspect neo4j-a2 failed: daemon down")})
    with pytest.raises(RuntimeError, match="daemon down"):  # 查询失败：停下，不当作不存在
        store_readers.guard(config, "A3")
    inspect(monkeypatch, {**ok, "neo4j-a2": container(reader, rm=True)})  # --rm 的写者容器照样核对挂载
    with pytest.raises(RuntimeError, match="overlaps .* of the writers' neo4j-a2"):
        store_readers.guard(config, "A3")
    inspect(monkeypatch, {**ok, "neo4j-a3-reader": None})
    with pytest.raises(RuntimeError, match="does not exist"):
        store_readers.guard(config, "A3")
    inspect(monkeypatch, {**ok, "neo4j-a3-reader": container(reader, "7700", rm=True)})  # 读者容器停下即被删除
    with pytest.raises(RuntimeError, match="--rm"):
        store_readers.guard(config, "A3")


@pytest.mark.parametrize(("code", "stderr", "expected"), [
    (0, "", {"Id": "x"}),
    (1, "Error response from daemon: No such container: neo4j-a2\n", None),
    (1, "Error: No such object: neo4j-a2\n", None),
    (1, "Cannot connect to the Docker daemon at unix:///var/run/docker.sock\n", RuntimeError),
    (1, "Error response from daemon: No such container: neo4j-a2-old\n", RuntimeError),  # 别的名字不算
])  # fmt: skip
def test_only_a_clear_no_such_container_counts_as_absent(monkeypatch, code: int, stderr: str, expected) -> None:
    done = subprocess.CompletedProcess([], code, stdout=json.dumps([{"Id": "x"}]) if code == 0 else "[]", stderr=stderr)
    monkeypatch.setattr(store_readers.subprocess, "run", lambda *a, **k: done)
    if expected is RuntimeError:
        with pytest.raises(RuntimeError, match="docker inspect neo4j-a2 failed"):
            store_readers._inspect("neo4j-a2")
    else:
        assert store_readers._inspect("neo4j-a2") == expected


def test_one_process_at_a_time_uses_a_readers_store(tmp_path: Path) -> None:
    data = tmp_path / "r3/data"
    data.mkdir(parents=True)
    with store_readers.store_lock(data):
        with pytest.raises(RuntimeError, match="another process"), store_readers.store_lock(data):
            pass
        other = subprocess.run([sys.executable, "-c", "import sys; from pathlib import Path; "
                                "from pweval.harness.store_readers import store_lock\n"
                                "with store_lock(Path(sys.argv[1])): pass", str(data)],
                               capture_output=True, text=True)  # fmt: skip
        assert other.returncode != 0 and "another process" in other.stderr
    with store_readers.store_lock(data):  # 放开之后可以再拿
        pass


def test_resumed_answers_must_share_the_version_and_the_allowlist(tmp_path: Path) -> None:
    store_readers.check_answers(tmp_path, "A3", 10, "c25", "a" * 64)  # 还没有回答
    path = store_readers.answers_file(tmp_path, "A3", 10, "aux")
    path.parent.mkdir(parents=True)
    good = {"arm": "A3", "checkpoint": 10, "probe": "p1", "version": "c25", "allowlist_sha256": "a" * 64}
    path.write_text(json.dumps(good) + "\n")
    store_readers.check_answers(tmp_path, "A3", 10, "c25", "a" * 64)
    path.write_text(json.dumps(good) + "\n" + json.dumps({**good, "probe": "p2", "allowlist_sha256": "b" * 64}) + "\n")
    with pytest.raises(RuntimeError, match="1 answers \\(such as p2\\).*another --out"):
        store_readers.check_answers(tmp_path, "A3", 10, "c25", "a" * 64)
    with pytest.raises(RuntimeError, match="2 answers"):
        store_readers.check_answers(tmp_path, "A3", 10, "c26", "a" * 64)


def test_a_graph_reader_is_isolated_read_only_and_reads_sources_only_through_the_evidence_server(tmp_path: Path) -> None:
    config = store_readers.load(configs(tmp_path))
    run, out = tmp_path / "run", tmp_path / "out"
    box = store_readers.reader_arm(config, run, out, "A3", 10, "p1")
    assert box.read_only and box.hide_tools == HIDDEN == ("read_evidence",)
    assert box.isolated_llm == "http://h:30000/v1" and box.papers is None and box.code is None
    assert box.read_source is None and box.evidence_scope is None
    assert box.neo4j == "bolt://localhost:7700" and box.data == out / "A3/readers/k10/data"
    assert box.evidence is not None and box.evidence.allowlist == run / "allowlists/A3/k10.json"  # 输入在运行目录
    assert box.evidence.library == box.sources == out / "A3/readers/k10/sources"
    a2 = {**READERS, "arms": {"A2": {"neo4j": "bolt://localhost:7701", "neo4j_container": "neo4j-a2-reader"}}}
    assert store_readers.reader_arm(store_readers.load(configs(tmp_path, a2)), run, out, "A2", 20, "p").ablate == ("dedup",)
    with pytest.raises(NotImplementedError):
        store_readers.reader_arm(config, run, out, "A0", 10, "p")
    assert TOOLS["PaperWeave"].isdisjoint({"commit", "read_evidence"})


def test_the_allowlist_must_be_of_this_checkpoint(tmp_path: Path) -> None:
    path = store_readers.allowlist_of(tmp_path, "A3", 10)
    path.parent.mkdir(parents=True)

    def write(data: dict, digest: str | None = None) -> None:
        path.write_text(json.dumps(data))
        real = hashlib.sha256(path.read_bytes()).hexdigest()
        path.with_suffix(".json.sha256").write_text(f"{digest or real}  k10.json\n")

    meta = {"version": "commit_000025"}
    write({"arm": "A3", "checkpoint": 10, "version": "commit_000025"})
    assert store_readers.check_allowlist(tmp_path, "A3", 10, meta) == hashlib.sha256(path.read_bytes()).hexdigest()
    write({"arm": "A3", "checkpoint": 10, "version": "commit_000025"}, digest="0" * 64)
    with pytest.raises(RuntimeError, match="sha256"):
        store_readers.check_allowlist(tmp_path, "A3", 10, meta)
    write({"arm": "A3", "checkpoint": 10, "version": "commit_000030"})
    with pytest.raises(RuntimeError, match="the backup is at"):
        store_readers.check_allowlist(tmp_path, "A3", 10, meta)


def test_evidence_requests_are_summarised_with_the_cut_lines(tmp_path: Path) -> None:
    log = tmp_path / "evidence.jsonl"
    assert store_readers.evidence_summary(log) == {"calls": 0, "errors": 0, "refs": 0, "status": {}, "bytes": 0, "cut": []}
    rows = [
        {"refs": ["P::1:2", "Q::3:4"], "error": False, "bytes": 100,
         "items": [{"ref": "P::1:2", "status": "available"}, {"ref": "Q::3:4", "status": "refused"}]},
        {"refs": ["C::f.py::2:2"], "error": False, "bytes": 4100,
         "items": [{"ref": "C::f.py::2:2", "status": "partial", "cut": [{"line": 2, "bytes": 10000}]}]},
        {"refs": [], "error": True, "bytes": 60},
    ]  # fmt: skip
    log.write_text("".join(json.dumps(r) + "\n" for r in rows))
    assert store_readers.evidence_summary(log) == {
        "calls": 3, "errors": 1, "refs": 3, "status": {"available": 1, "refused": 1, "partial": 1}, "bytes": 4260,
        "cut": [{"ref": "C::f.py::2:2", "line": 2, "bytes": 10000}]}  # fmt: skip
