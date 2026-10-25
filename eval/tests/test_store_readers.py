"""f3 写者组的离线读者：读者配置的合并、读者沙箱、放行名单的核对与证据请求的统计（库的恢复与核对要真实容器，
在运行中由 ``--check-only`` 检查）。"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
import yaml

from pweval.harness import store_readers
from pweval.harness.store_readers import A0_TOOLS, HIDDEN, TOOLS
from test_allowlist import P, Q, S, _a0_run, _a3f_run, _git

WRITERS = {
    "probes_repo": "~/probes", "corpus_papers": "~/papers", "code": "~/code", "workdir_root": "~/runs",
    "plan": "tasks/plan-f3.yml", "materials": "tasks/materials.yml", "seed": "seed/f3",
    "arms": {"A3": {"neo4j": "bolt://localhost:7696", "neo4j_container": "neo4j-a3", "llm": "http://h:30000/v1"},
             "A2": {"neo4j": "bolt://localhost:7697", "neo4j_container": "neo4j-a2", "llm": "http://h:30000/v1",
                    "ablate": ["dedup"]},
             "A0": {"llm": "http://h:30001/v1"}},
    "runner": {"model": "sglang/m", "probe_timeout_min": 15, "reader_workers": 4, "thinking": "medium"},
}  # fmt: skip
READERS = {"writers": "w.yml", "llm": "http://h:30000/v1",
           "arms": {"A3": {"neo4j": "bolt://localhost:7700", "neo4j_container": "neo4j-a3-reader"}},
           "runner": {"probe_timeout_min": 60, "max_tool_calls": 300}}  # fmt: skip


def configs(tmp_path: Path, readers: dict = READERS, writers: dict = WRITERS) -> Path:
    (tmp_path / "w.yml").write_text(yaml.safe_dump(writers))
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
    with pytest.raises(RuntimeError, match="A0 has no readers' store"):  # 读者配置没有声明 A0
        store_readers.reader_arm(config, run, out, "A0", 10, "p")
    with pytest.raises(RuntimeError, match="A4 has no readers' store"):  # 读者配置没有声明 A4
        store_readers.reader_arm(config, run, out, "A4", 10, "p")
    assert TOOLS["PaperWeave"].isdisjoint({"commit", "read_evidence"})


def test_the_a0_reader_reads_the_checkpoint_repository_read_only_with_only_the_evidence_server(tmp_path: Path) -> None:
    config = store_readers.load(configs(tmp_path, {**READERS, "arms": {"A0": {}}}))
    assert config["arms"]["A0"] == {"llm": "http://h:30000/v1"}  # 读者的大模型服务，不是写者的 30001
    assert store_readers.guard(config, "A0") is None  # 没有容器可查
    run, out = tmp_path / "run", tmp_path / "out"
    box = store_readers.reader_arm(config, run, out, "A0", 10, "p1")
    assert box.store == out / "A0/readers/k10/store" and box.read_only and box.isolated_llm == "http://h:30000/v1"
    assert box.neo4j is None and box.read_source is None and box.papers is None and box.code is None
    assert box.evidence.allowlist == run / "allowlists/A0/k10.json"
    assert box.evidence.library == out / "A0/readers/k10/sources"
    assert A0_TOOLS == {"Evidence": {"read_evidence"}}


@pytest.mark.parametrize("spec", [{"store": "/x/shared.git"}, {"neo4j": "bolt://localhost:7700"}])
def test_the_a0_reader_config_names_no_store(tmp_path: Path, spec: dict) -> None:
    with pytest.raises(SystemExit, match="give no store settings"):
        store_readers.load(configs(tmp_path, {**READERS, "arms": {"A0": spec}}))


def test_the_allowlist_must_be_of_this_checkpoint(tmp_path: Path) -> None:
    path = store_readers.allowlist_of(tmp_path, "A3", 10)
    path.parent.mkdir(parents=True)

    def write(data: dict, digest: str | None = None) -> None:
        path.write_text(json.dumps(data))
        real = hashlib.sha256(path.read_bytes()).hexdigest()
        path.with_suffix(".json.sha256").write_text(f"{digest or real}  k10.json\n")

    meta = {"version": "commit_000025", "sources": {"2205.13504v2": "a"}}
    inputs = {"sources": {"2205.13504v2": "a"}}
    write({"arm": "A3", "checkpoint": 10, "version": "commit_000025", "inputs": inputs})
    assert store_readers.check_allowlist(tmp_path, "A3", 10, meta) == hashlib.sha256(path.read_bytes()).hexdigest()
    write({"arm": "A3", "checkpoint": 10, "version": "commit_000025", "inputs": inputs}, digest="0" * 64)
    with pytest.raises(RuntimeError, match="sha256"):
        store_readers.check_allowlist(tmp_path, "A3", 10, meta)
    write({"arm": "A3", "checkpoint": 10, "version": "commit_000030", "inputs": inputs})
    with pytest.raises(RuntimeError, match="the backup is at"):
        store_readers.check_allowlist(tmp_path, "A3", 10, meta)
    write({"arm": "A3", "checkpoint": 10, "version": "commit_000025", "inputs": {"sources": {}}})
    with pytest.raises(RuntimeError, match="other opened sources"):  # 名单与读者拿到的原文须是同一份开放清单
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


# ---------------------------------------------------------------- A0 的读者仓库


@pytest.fixture
def a0(tmp_path: Path) -> tuple[Path, Path, dict]:
    """``test_allowlist`` 的 A0 检查点（k1），共享仓库之后又发布了一个提交（k1 的读者不能看到它）。"""
    run = _a0_run(tmp_path)
    work = tmp_path / "work"
    (work / "store/nodes/later.md").write_text("published after the checkpoint\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", "after the checkpoint")
    _git(work, "push", "-q", str(run / "A0/shared.git"), "main")
    out = tmp_path / "out"
    meta = store_readers.a0_checkpoint({"probes_repo": tmp_path / "bank"}, run, 1)
    store_readers.build_repo(run, out, "A0", 1, meta)
    return run, out, meta


def test_the_a0_readers_repository_holds_the_checkpoint_and_nothing_after(a0) -> None:
    run, out, meta = a0
    store = store_readers.repo_store(out, "A0", 1)
    checked = store_readers.verify_repo(run, out, "A0", 1, meta)
    assert checked["commits"] == 3 and checked["later_absent"] == 1 and checked["sources"] == 2
    later = _git(run / "A0/shared.git", "rev-parse", "main")
    show = subprocess.run(["git", "-C", str(store), "show", later], capture_output=True, text=True)
    assert show.returncode != 0  # 知道之后提交的哈希也取不到
    assert _git(store, "tag") == "" and _git(store, "remote") == ""
    assert not (store / ".git/FETCH_HEAD").exists() and not (store / ".git/logs").exists()
    assert str(run) not in "".join(p.read_text(errors="replace") for p in (store / ".git").rglob("*") if p.is_file()
                                   and "objects" not in p.parts)  # 不留共享仓库的路径  # fmt: skip
    # 原文只有检查点上开放的 P、Q；S 在组的来源目录中，但之后才开放
    assert sorted(p.name for p in (out / "A0/readers/k1/sources").iterdir()) == sorted([P, Q])
    assert meta["sources"].keys() == {P, Q} and S not in meta["sources"]
    assert store_readers.verify_repo(run, out, "A0", 1, meta) == checked  # 已建好的不重建，核对照样通过
    store_readers.build_repo(run, out, "A0", 1, meta)
    assert store_readers.verify_repo(run, out, "A0", 1, meta) == checked


def _hidden_objects(run: Path, store: Path) -> None:
    """把之后的提交取进来再删掉引用：对象留在库里，引用与取库记录都看不出来。"""
    _git(store, "fetch", "-q", "--no-tags", str(run / "A0/shared.git"), "refs/heads/main:refs/heads/other")
    _git(store, "update-ref", "-d", "refs/heads/other")
    (store / ".git/FETCH_HEAD").unlink()
    subprocess.run(["rm", "-rf", str(store / ".git/logs")], check=True)


@pytest.mark.parametrize(
    ("damage", "message"),
    [
        (lambda run, store, out: _hidden_objects(run, store), "objects beyond checkpoint"),
        (lambda run, store, out: _git(store, "tag", "x"), "refs"),
        (lambda run, store, out: _git(store, "remote", "add", "origin", str(run / "A0/shared.git")), "remotes"),
        (lambda run, store, out: (store / ".git/objects/info/alternates").write_text(str(run / "A0/shared.git/objects")),
         "keeps"),
        (lambda run, store, out: (store / "AGENTS.md").write_text("changed\n"), "files of the readers' repository"),
        (lambda run, store, out: (store / "extra.md").write_text("x\n"), "files of the readers' repository"),
        (lambda run, store, out: subprocess.run(["cp", "-r", str(run / "A0/sources" / S), str(out / "A0/readers/k1/sources")],
                                                check=True), "sources differ"),
    ],
)  # fmt: skip
def test_a_damaged_a0_readers_repository_stops_the_readers(a0, damage, message: str) -> None:
    run, out, meta = a0
    damage(run, store_readers.repo_store(out, "A0", 1), out)
    with pytest.raises(RuntimeError, match=message):
        store_readers.verify_repo(run, out, "A0", 1, meta)



# ---------------------------------------------------------------- A3F：A3 检查点的只读文件视图


def test_the_a3f_reader_reads_the_view_read_only_with_only_the_evidence_server(tmp_path: Path) -> None:
    config = store_readers.load(configs(tmp_path, {**READERS, "arms": {"A3F": {}}}))
    assert config["arms"]["A3F"] == {"llm": "http://h:30000/v1"}  # 不继承 A3 的库设置
    assert store_readers.guard(config, "A3F") is None
    run, out = tmp_path / "run", tmp_path / "out"
    box = store_readers.reader_arm(config, run, out, "A3F", 10, "p1")
    assert (box.name, box.store, box.read_only, box.neo4j) == ("A3F", out / "A3F/readers/k10/store", True, None)
    assert box.evidence.allowlist == run / "allowlists/A3F/k10.json"
    assert box.evidence.library == out / "A3F/readers/k10/sources"
    assert store_readers.HINT == {"A3F": "a0"}  # 说明句用 A0 的，不改题库


@pytest.mark.parametrize(("spec", "writers", "message"), [
    ({"neo4j": "bolt://localhost:7700"}, WRITERS, "give no store settings"),
    ({}, {**WRITERS, "arms": {k: v for k, v in WRITERS["arms"].items() if k != "A3"}}, "a view of A3"),
])  # fmt: skip
def test_the_a3f_reader_config_names_no_store(tmp_path: Path, spec: dict, writers: dict, message: str) -> None:
    with pytest.raises(SystemExit, match=message):
        store_readers.load(configs(tmp_path, {**READERS, "arms": {"A3F": spec}}, writers))


@pytest.fixture
def a3f(tmp_path: Path) -> tuple[Path, Path, dict]:
    """``test_allowlist`` 的 A3F 检查点（k1）；k2 的导出仓库多出两个提交（k1 的读者不能看到它们）。"""
    run, out = _a3f_run(tmp_path), tmp_path / "out"
    meta = store_readers.a3f_checkpoint(run, 1)
    store_readers.build_repo(run, out, "A3F", 1, meta)
    return run, out, meta


def test_the_a3f_readers_repository_holds_the_checkpoint_and_nothing_after(a3f) -> None:
    run, out, meta = a3f
    store = store_readers.repo_store(out, "A3F", 1)
    assert meta["version"] == _git(store, "rev-parse", "HEAD") and meta["view_of"] == "commit_000002"
    checked = store_readers.verify_repo(run, out, "A3F", 1, meta)
    assert checked["commits"] == 4 and checked["later_absent"] == 2 and checked["sources"] == 2
    later = _git(store_readers.allowlist.a3f_repo(run, 2), "rev-parse", "main")
    assert subprocess.run(["git", "-C", str(store), "show", later], capture_output=True).returncode != 0
    assert (store / "store/nodes/experiment/exp_0001.yaml").read_text().count("_revised") == 1  # 派生字段在最后的提交中
    # 原文取 A3 的来源目录，只有清单中开放的 P、Q
    assert sorted(p.name for p in (out / "A3F/readers/k1/sources").iterdir()) == sorted([P, Q])
    assert store_readers.verify_repo(run, out, "A3F", 1, meta) == checked


def _hidden_later(run: Path, store: Path) -> None:
    """把更晚检查点（k2）的导出取进来再删掉引用与取库记录：对象留在库里，引用看不出来。"""
    _git(store, "fetch", "-q", "--no-tags", str(store_readers.allowlist.a3f_repo(run, 2)), "refs/heads/main:refs/heads/other")
    _git(store, "update-ref", "-d", "refs/heads/other")
    (store / ".git/FETCH_HEAD").unlink()
    subprocess.run(["rm", "-rf", str(store / ".git/logs")], check=True)


@pytest.mark.parametrize(
    ("damage", "message"),
    [
        (lambda run, store, out: _hidden_later(run, store), "beyond checkpoint"),
        (lambda run, store, out: (store / "AGENTS.md").write_text("changed\n"), "files of the readers' repository"),
        (lambda run, store, out: subprocess.run(["cp", "-r", str(run / "A3/sources" / S), str(out / "A3F/readers/k1/sources")],
                                                check=True), "sources differ"),
    ],
)  # fmt: skip
def test_a_damaged_a3f_readers_repository_stops_the_readers(a3f, damage, message: str) -> None:
    run, out, meta = a3f
    damage(run, store_readers.repo_store(out, "A3F", 1), out)
    with pytest.raises(RuntimeError, match=message):
        store_readers.verify_repo(run, out, "A3F", 1, meta)


def test_the_a3f_checkpoint_stops_when_the_view_no_longer_matches_a3(tmp_path: Path) -> None:
    run = _a3f_run(tmp_path)
    (run / "snapshots/A3/k1/graph.jsonl").write_text("{ }\n")
    with pytest.raises(RuntimeError, match="A3 snapshot k1 changed"):
        store_readers.a3f_checkpoint(run, 1)


# ---------------------------------------------------------------- A4：Graphiti 的读者库与读者服务

A4_WRITERS = {**WRITERS, "arms": {**WRITERS["arms"], "A4": {
    "graphiti": "http://127.0.0.1:8765/mcp/", "neo4j": "bolt://localhost:7698", "neo4j_container": "neo4j-a4",
    "graphiti_log": "~/runs/graphiti.log", "group_id": "formal", "llm": "http://h:30001/v1"}}}  # fmt: skip
A4_READERS = {"neo4j": "bolt://localhost:7701", "neo4j_container": "neo4j-a4-reader",
              "graphiti": "http://127.0.0.1:8766/mcp/", "graphiti_python": "~/g/.venv/bin/python",
              "graphiti_src": "~/g/src"}  # fmt: skip


def test_the_a4_readers_get_their_own_store_and_graphiti_service(tmp_path: Path) -> None:
    config = store_readers.load(configs(tmp_path, {**READERS, "arms": {"A4": A4_READERS}}, A4_WRITERS))
    spec = config["arms"]["A4"]
    assert (spec["neo4j"], spec["graphiti"], spec["group_id"]) == ("bolt://localhost:7701", "http://127.0.0.1:8766/mcp/",
                                                                   "formal")  # fmt: skip
    assert spec["graphiti_python"] == str(Path("~/g/.venv/bin/python").expanduser()) and spec["llm"] == "http://h:30000/v1"
    run, out = tmp_path / "run", tmp_path / "out"
    box = store_readers.reader_arm(config, run, out, "A4", 10, "p1")
    assert box.graphiti == "http://127.0.0.1:8766/mcp/" and box.isolated_tcp == ("127.0.0.1:8766",)
    assert box.hide_tools == () and box.read_source is None and box.papers is None and box.neo4j is None
    assert box.isolated_llm == "http://h:30000/v1" and box.evidence.allowlist == run / "allowlists/A4/k10.json"
    assert box.evidence.library == out / "A4/readers/k10/sources"


@pytest.mark.parametrize(("spec", "message"), [
    ({**A4_READERS, "graphiti": "http://127.0.0.1:8765/mcp/"}, "writers' Graphiti"),
    ({k: v for k, v in A4_READERS.items() if k != "graphiti_src"}, "own Graphiti service \\(graphiti_src missing\\)"),
    ({**A4_READERS, "neo4j_container": "neo4j-a4"}, "writers' store \\(neo4j-a4\\)"),
    ({**A4_READERS, "neo4j": "bolt://localhost:7698"}, "writers' store \\(bolt://localhost:7698\\)"),
])  # fmt: skip
def test_the_a4_readers_never_use_the_writers_store_or_service(tmp_path: Path, spec: dict, message: str) -> None:
    with pytest.raises(SystemExit, match=message):
        store_readers.load(configs(tmp_path, {**READERS, "arms": {"A4": spec}}, A4_WRITERS))


def test_the_readers_graphiti_must_not_have_touched_its_internal_llm(tmp_path: Path) -> None:
    log = tmp_path / "serve.log"
    log.write_text("old run: llm usage prompt=5 completion=1\n")  # 上次启动的不算
    service = {"log": log, "from": log.stat().st_size}
    with log.open("a") as f:
        f.write("read-only: 31 indexes online, none built\nPOST /mcp 200\n")
    assert store_readers.check_service_log(service, 10) == {"blocked": 0, "usage": 0}
    with log.open("a") as f:
        f.write(f"{store_readers.A4_BLOCKED}: chat.completions.create\n")
    with pytest.raises(RuntimeError, match="called its internal LLM"):
        store_readers.check_service_log(service, 10)


# ---------------------------------------------------------------- 作答中途失败与结束核验（10-25 评审）


class _Timeline:
    reader = {"user": "u"}
    hints = {"a4": {"TOOLS": "Use the tools."}, "a3": {"TOOLS": "Use the tools."}}

    def group(self, group: str) -> list[dict]:
        return [{"id": f"{group}-{i}"} for i in range(3)]


def _fake_run(monkeypatch, tmp_path: Path, *, fail_at: str | None, store_ok, log_ok: bool = True) -> dict:
    """``_run_readers`` 的外部都换成假的：A4，一组三题，单线程按序作答；``fail_at`` 那题抛错，``store_ok()`` 决定
    结束核对库是否通过。返回调用记录。"""
    calls: dict = {"answered": [], "store": 0, "service log": 0, "service": []}
    monkeypatch.setattr(store_readers, "timeline_of", lambda config: _Timeline())
    monkeypatch.setattr(store_readers, "eligible", lambda timeline, papers, group: timeline.group(group))
    monkeypatch.setattr(store_readers, "restore", lambda *a: {"version": "v1"})
    monkeypatch.setattr(store_readers, "check_allowlist", lambda *a: "d" * 64)
    monkeypatch.setattr(store_readers, "check_tools", lambda *a: {})
    pre = iter([True])

    def verify_a4(*a):
        if next(pre, False):  # 作答前的核对总是通过
            return {"version": "v1", "counts": {"nodes": 1, "edges": 0}, "store_sha256": "s" * 64, "sources": 1}
        calls["store"] += 1
        if not store_ok():
            raise RuntimeError("store changed")

    monkeypatch.setattr(store_readers, "verify_a4", verify_a4)

    @contextmanager
    def service(config, out, papers, mark):
        mark["pid"] = 42
        calls["service"].append("up")
        try:
            yield
        finally:
            calls["service"].append("down")

    def log(service, papers):
        calls["service log"] += 1
        if not log_ok:
            raise RuntimeError("called its internal LLM")
        return {"blocked": 0, "usage": 0}

    monkeypatch.setattr(store_readers, "graphiti_service", service)
    monkeypatch.setattr(store_readers, "check_service_log", log)

    def answer(config, sentence, run, out, arm, papers, group, probe, reader):
        if probe["id"] == fail_at:
            raise RuntimeError("pi crashed")
        calls["answered"].append(probe["id"])
        return {"arm": arm, "checkpoint": papers, "probe": probe["id"], "exit": 0, "seconds": 1, "tools": {}, "answer": "a"}

    monkeypatch.setattr(store_readers, "answer", answer)
    return calls


def _go(tmp_path: Path) -> None:
    config = {"runner": {"agent": "pi", "model": "m", "reader_workers": 1}}
    store_readers._run_readers(config, tmp_path / "run", tmp_path / "out", "A4", 10, ["main"], None, False)


def _ids(path: Path) -> list[str]:
    return [json.loads(line)["probe"] for line in path.read_text().splitlines()] if path.exists() else []


def test_a_crash_after_some_answers_still_runs_both_final_checks_and_keeps_verified_answers(monkeypatch, tmp_path):
    calls = _fake_run(monkeypatch, tmp_path, fail_at="main-2", store_ok=lambda: True)
    with pytest.raises(RuntimeError, match="pi crashed"):  # 核验通过：抛出的是作答的错误
        _go(tmp_path)
    assert calls["service"] == ["up", "down"] and calls["service log"] == 1 and calls["store"] == 1
    out = tmp_path / "out"
    answers = out / "answers/A4/k10.jsonl"
    assert _ids(answers) == ["main-0", "main-1"]
    assert not (out / "A4/readers/k10" / store_readers.UNVERIFIED).exists()  # 这两条已核验
    calls = _fake_run(monkeypatch, tmp_path, fail_at=None, store_ok=lambda: True)
    _go(tmp_path)
    assert calls["answered"] == ["main-2"] and _ids(answers) == ["main-0", "main-1", "main-2"]


@pytest.mark.parametrize(("store_ok", "log_ok"), [(False, True), (True, False), (False, False)])
def test_answers_of_a_run_that_fails_its_final_checks_are_set_aside_and_asked_again(monkeypatch, tmp_path, store_ok,
                                                                                    log_ok):  # fmt: skip
    out = tmp_path / "out"
    answers = out / "answers/A4/k10.jsonl"
    answers.parent.mkdir(parents=True)
    old = {"arm": "A4", "checkpoint": 10, "probe": "main-0", "version": "v1", "allowlist_sha256": "d" * 64}
    answers.write_text(json.dumps(old) + "\n")  # 早先的回答（没有运行标识）不动
    calls = _fake_run(monkeypatch, tmp_path, fail_at="main-2", store_ok=lambda: store_ok, log_ok=log_ok)
    with pytest.raises(RuntimeError, match="final verification failed") as raised:
        _go(tmp_path)
    assert isinstance(raised.value.__cause__, RuntimeError) and "pi crashed" in str(raised.value.__cause__)
    assert calls["service log"] == 1 and calls["store"] == 1  # 一项失败也不跳过另一项
    marker = yaml.safe_load((out / "A4/readers/k10" / store_readers.UNVERIFIED).read_text())
    assert len(marker["failed"]) == (not store_ok) + (not log_ok)
    assert _ids(answers) == ["main-0", "main-1"]
    calls = _fake_run(monkeypatch, tmp_path, fail_at=None, store_ok=lambda: True)
    _go(tmp_path)  # 续跑：上次的 main-1 未经核验，移开重答
    assert calls["answered"] == ["main-1", "main-2"]
    assert _ids(answers) == ["main-0", "main-1", "main-2"]
    assert json.loads(answers.read_text().splitlines()[0]) == old
    aside = out / "A4/readers/k10/unverified/k10.jsonl"
    assert _ids(aside) == ["main-1"] and json.loads(aside.read_text())["invocation"] == marker["invocation"]
    assert not (out / "A4/readers/k10" / store_readers.UNVERIFIED).exists()


def test_a_run_killed_before_its_final_checks_leaves_its_answers_unverified(monkeypatch, tmp_path):
    calls = _fake_run(monkeypatch, tmp_path, fail_at=None, store_ok=lambda: True)

    def killed(*a):
        raise SystemExit(9)

    monkeypatch.setattr(store_readers, "final_checks", killed)
    with pytest.raises(SystemExit):  # 模拟进程在结束核验前被杀：标记留下
        _go(tmp_path)
    out = tmp_path / "out"
    assert (out / "A4/readers/k10" / store_readers.UNVERIFIED).exists()
    monkeypatch.undo()
    calls = _fake_run(monkeypatch, tmp_path, fail_at=None, store_ok=lambda: True)
    _go(tmp_path)
    assert calls["answered"] == ["main-0", "main-1", "main-2"]  # 三题都重答
    assert _ids(out / "A4/readers/k10/unverified/k10.jsonl") == ["main-0", "main-1", "main-2"]
