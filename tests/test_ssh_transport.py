r"""`SshTransport.run_gate` 的钉子（卡 E82 · `T-AG587`，12 条判据）。

钉的是**薄封装**的口径：`scripts/cloud/run_gate.sh` 怎么被调起来、怎么读回传、
什么算「没跑成」。全部用**假 runner**（注入点），一条也不连云机 —— 第 ⑦ 条专门
证明单测里没有起真 `ssh` 进程。

| # | 钉子 | 坏掉会红在哪 |
|---|---|---|
| ① | argv = `bash scripts/cloud/run_gate.sh <tree.name> <port_base>` | 传卡号 ⇒ 目录不存在 |
| ② | cwd = 主仓根（不是卡树） | cwd=tree ⇒ 找不到 `scripts/cloud` |
| ③ | env 有 `CLOUD_HOST`/`TF_PROJECTS_TOML`，**无** `TF_MODEL_REGISTRY` | 带注册表 ⇒ 云机 5 条红 |
| ④ | 回传 `last.json` + `logs` ⇒ 三键齐全 | 少一键 ⇒ 落地链 KeyError |
| ⑤ | 退出码 2..9 一律 `CloudUnreachable` 且带码与段名 | 静默返回 ⇒ 假绿 |
| ⑥ | 失败消息带**末 20 行**，不是前 20 行 | 只给开头 ⇒ 看不到真错 |
| ⑦ | 单测里没有真 `ssh` 进程 | 起 ssh ⇒ 测试挂网 |
| ⑧ | seed 缺失（退 4）⇒ 抛，且**不**替人建 seed 目录 | 自己造 seed ⇒ 掩盖上一趟没跑 |
| ⑨ | 退 9（产物陈旧、脚本已删 last.json）⇒ 不读残留 | 读旧 last.json ⇒ 拿上一趟冒充 |
| ⑩ | timeout ≥ 3600 s | 按默认 30 s ⇒ 全量必被杀 |
| ⑪ | 源码无 `C:/infra`、`C:/Users/`、`AppData`、`/home/` | 私有路径进库 |
| ⑫ | `subprocess.run` 带 `creationflags`（与 `tools/test_no_window.py` 同源） | 云窗口弹窗 |
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import gate_pool as gp  # noqa: E402

PRIVATE_MARKERS = ("C:/infra", "C:\\infra", "C:/Users/", "AppData", "/home/")

BANNERS = ("=== 3/5 传补丁并应用\n=== 4/5 云机跑全量门禁\n"
           "=== 5/5 回传 gates/last.json 与日志\n")


class FakeRunner:
    """假的 `subprocess.run`：记下每次 argv/kwargs，按剧本返回。"""

    def __init__(self, rc: int = 0, stdout: str = "", stderr: str = "",
                 effect=None) -> None:
        self.rc = rc
        self.stdout = stdout
        self.stderr = stderr
        self.effect = effect
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), dict(kwargs)))
        if self.effect is not None:
            self.effect(list(argv), kwargs)
        return subprocess.CompletedProcess(argv, self.rc, self.stdout, self.stderr)


def make_tree(tmp_path: Path, name: str = "batch460") -> Path:
    tree = tmp_path / "main" / ".wt" / name
    (tree / "gates" / "logs").mkdir(parents=True)
    return tree


def make_transport(tmp_path: Path, runner) -> gp.SshTransport:
    main = tmp_path / "main"
    main.mkdir(parents=True, exist_ok=True)
    return gp.SshTransport(host="10.0.0.9", main_root=main, runner=runner)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("TF_PROJECTS_TOML", "D:/projects.toml")
    monkeypatch.delenv("TF_MODEL_REGISTRY", raising=False)


def write_payload(tree: Path, payload: dict) -> None:
    (tree / "gates" / "last.json").write_text(json.dumps(payload), encoding="utf-8")


# ---------------------------------------------------------------- ① argv
def test_argv_uses_tree_dir_name_and_port_base(tmp_path: Path) -> None:
    """第 1 个位置参数是**目录名**（卡号 ≠ 目录名：T-AG460 住在 `.wt/batch460`）。"""
    runner = FakeRunner(stdout=BANNERS)
    tree = make_tree(tmp_path, "batch460")
    write_payload(tree, {"ok": True, "host": "cloud"})
    entry = {"card": "T-AG460", "port_base": 9200}
    make_transport(tmp_path, runner).run_gate(entry, tree)
    argv, _kwargs = runner.calls[-1]
    assert argv[:2] == ["bash", "scripts/cloud/run_gate.sh"]
    assert argv[2] == "batch460"
    assert argv[2] != entry["card"]
    assert argv[3] == "9200"


# ---------------------------------------------------------------- ② cwd
def test_cwd_is_main_root_not_card_tree(tmp_path: Path) -> None:
    """cwd 必须是主仓根：脚本里的 `scripts/run_gates.py` 与 `.wt/$card` 都相对它。"""
    runner = FakeRunner(stdout=BANNERS)
    tree = make_tree(tmp_path)
    write_payload(tree, {"ok": True})
    make_transport(tmp_path, runner).run_gate({"port_base": 9200}, tree)
    _argv, kwargs = runner.calls[-1]
    assert Path(kwargs["cwd"]) == tmp_path / "main"
    assert Path(kwargs["cwd"]) != tree


def test_cwd_derived_from_git_common_dir(tmp_path: Path) -> None:
    """不给 `main_root` 时从 `--git-common-dir` 的父目录现算。"""
    main = tmp_path / "repo"
    main.mkdir()
    runner = FakeRunner(stdout=BANNERS)
    calls = {"n": 0}

    def effect(argv, _kwargs):
        calls["n"] += 1
        if argv[0] == "git":
            runner.stdout = str(main / ".git")

    runner.effect = effect
    tree = make_tree(tmp_path)
    write_payload(tree, {"ok": True})
    gp.SshTransport(host="10.0.0.9", runner=runner).run_gate(
        {"port_base": 9200}, tree)
    git_argv = runner.calls[0][0]
    assert git_argv[:3] == ["git", "-C", str(tree)]
    assert "--git-common-dir" in git_argv
    assert Path(runner.calls[1][1]["cwd"]) == main


# ---------------------------------------------------------------- ③ env
def test_env_has_cloud_host_and_projects_but_no_registry(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TF_MODEL_REGISTRY", "D:/registry.json")
    runner = FakeRunner(stdout=BANNERS)
    tree = make_tree(tmp_path)
    write_payload(tree, {"ok": True})
    make_transport(tmp_path, runner).run_gate({"port_base": 9200}, tree)
    env = runner.calls[-1][1]["env"]
    assert env["CLOUD_HOST"] == "administrator@10.0.0.9"
    assert env["TF_PROJECTS_TOML"] == "D:/projects.toml"
    assert "TF_MODEL_REGISTRY" not in env
    assert "PATH" in env


def test_missing_projects_toml_raises(tmp_path: Path,
                                      monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TF_PROJECTS_TOML", raising=False)
    runner = FakeRunner(stdout=BANNERS)
    tree = make_tree(tmp_path)
    with pytest.raises(gp.CloudUnreachable, match="TF_PROJECTS_TOML"):
        make_transport(tmp_path, runner).run_gate({"port_base": 9200}, tree)
    assert runner.calls == []


def test_empty_host_raises_before_running(tmp_path: Path) -> None:
    runner = FakeRunner(stdout=BANNERS)
    tree = make_tree(tmp_path)
    transport = gp.SshTransport(host="", main_root=tmp_path / "main", runner=runner)
    with pytest.raises(gp.CloudUnreachable, match="连接地址"):
        transport.run_gate({"port_base": 9200}, tree)
    assert runner.calls == []


# ---------------------------------------------------------------- ④ 回传三键
def test_success_returns_three_keys(tmp_path: Path) -> None:
    runner = FakeRunner(stdout=BANNERS)
    tree = make_tree(tmp_path)

    def effect(_argv, _kwargs):
        write_payload(tree, {"ok": True, "host": "iZcloud", "gates": []})
        (tree / "gates" / "logs" / "pytest.log").write_text(
            "3303 passed", encoding="utf-8")

    runner.effect = effect
    got = make_transport(tmp_path, runner).run_gate({"port_base": 9200}, tree)
    assert set(got) == {"payload", "logs", "workspace_clean"}
    assert got["payload"]["ok"] is True
    assert got["payload"]["host"] == "iZcloud"
    assert got["logs"]["pytest.log"] == "3303 passed"
    assert got["workspace_clean"] is True


def test_red_but_ran_returns_payload_not_raise(tmp_path: Path) -> None:
    """跑到了但门红（rc=1）⇒ 正常返回带 payload（判红是落地链的事，不是异常）。"""
    runner = FakeRunner(rc=1, stdout=BANNERS)
    tree = make_tree(tmp_path)
    write_payload(tree, {"ok": False, "host": "iZcloud"})
    got = make_transport(tmp_path, runner).run_gate({"port_base": 9200}, tree)
    assert got["payload"]["ok"] is False


def test_missing_last_json_after_rc0_raises(tmp_path: Path) -> None:
    runner = FakeRunner(stdout=BANNERS)
    tree = make_tree(tmp_path)
    with pytest.raises(gp.CloudUnreachable, match="last.json"):
        make_transport(tmp_path, runner).run_gate({"port_base": 9200}, tree)


def test_workspace_clean_false_without_clean_banner(tmp_path: Path) -> None:
    runner = FakeRunner(stdout="=== 2/5 对齐提交\n")
    tree = make_tree(tmp_path)
    write_payload(tree, {"ok": True})
    got = make_transport(tmp_path, runner).run_gate({"port_base": 9200}, tree)
    assert got["workspace_clean"] is False


# ---------------------------------------------------------------- ⑤ 退出码
@pytest.mark.parametrize("rc", [2, 3, 4, 5, 6, 7, 8, 9])
def test_exit_codes_raise_with_code_and_segment(tmp_path: Path, rc: int) -> None:
    runner = FakeRunner(rc=rc, stdout="=== 2/5 云机对齐到同一提交\nboom\n")
    tree = make_tree(tmp_path)
    with pytest.raises(gp.CloudUnreachable) as excinfo:
        make_transport(tmp_path, runner).run_gate({"port_base": 9200}, tree)
    text = str(excinfo.value)
    assert f"退 {rc}" in text
    assert "=== 2/5" in text


# ---------------------------------------------------------------- ⑥ 末 20 行
def test_failure_message_keeps_tail_20_lines(tmp_path: Path) -> None:
    lines = [f"line-{i:02d}" for i in range(1, 41)]
    runner = FakeRunner(rc=5, stdout="\n".join(lines) + "\n")
    tree = make_tree(tmp_path)
    with pytest.raises(gp.CloudUnreachable) as excinfo:
        make_transport(tmp_path, runner).run_gate({"port_base": 9200}, tree)
    text = str(excinfo.value)
    assert "line-40" in text
    assert "line-21" in text
    assert "line-20" not in text
    assert "line-01" not in text


# ---------------------------------------------------------------- ⑦ 没有真 ssh
def test_no_real_ssh_process_is_started(tmp_path: Path,
                                        monkeypatch: pytest.MonkeyPatch) -> None:
    """把 `gate_pool.subprocess.run` 换成炸弹：只要有人绕过 `runner` 就当场炸。"""

    def boom(*_args, **_kwargs):
        raise AssertionError("单测里起了真进程（ssh/bash）")

    monkeypatch.setattr(gp.subprocess, "run", boom)
    runner = FakeRunner(stdout=BANNERS)
    tree = make_tree(tmp_path)
    write_payload(tree, {"ok": True})
    got = make_transport(tmp_path, runner).run_gate({"port_base": 9200}, tree)
    assert got["payload"]["ok"] is True
    assert all("ssh" not in argv for argv, _kwargs in runner.calls)


# ---------------------------------------------------------------- ⑧ seed 缺失
def test_missing_seed_raises_and_does_not_create_seed_dir(tmp_path: Path) -> None:
    hint = ("处置：先在卡树跑一趟本机门禁，把 gates/last.json 播成 gates/diag/"
            "seed-batch460/last.json")
    runner = FakeRunner(rc=4, stdout="=== 2/5 对齐提交\n" + hint + "\n")
    tree = make_tree(tmp_path)
    seed = tree / "gates" / "diag" / "seed-batch460"
    with pytest.raises(gp.CloudUnreachable, match="退 4") as excinfo:
        make_transport(tmp_path, runner).run_gate({"port_base": 9200}, tree)
    assert "处置" in str(excinfo.value)
    assert not seed.exists()


# ---------------------------------------------------------------- ⑨ 退 9 不读残留
def test_exit9_does_not_read_stale_last_json(tmp_path: Path) -> None:
    runner = FakeRunner(rc=9, stdout="=== 5/5 回传\n产物陈旧，已删 last.json\n")
    tree = make_tree(tmp_path)
    write_payload(tree, {"ok": True, "host": "stale"})

    def effect(_argv, _kwargs):
        (tree / "gates" / "last.json").unlink()

    runner.effect = effect
    with pytest.raises(gp.CloudUnreachable, match="退 9") as excinfo:
        make_transport(tmp_path, runner).run_gate({"port_base": 9200}, tree)
    assert "没有可读" not in str(excinfo.value)


# ---------------------------------------------------------------- ⑩ timeout
def test_timeout_at_least_one_hour(tmp_path: Path) -> None:
    runner = FakeRunner(stdout=BANNERS)
    tree = make_tree(tmp_path)
    write_payload(tree, {"ok": True})
    make_transport(tmp_path, runner).run_gate(
        {"port_base": 9200, "timeout": 60}, tree)
    timeout = runner.calls[-1][1]["timeout"]
    assert timeout >= 3600
    assert timeout >= gp.RUN_GATE_MIN_TIMEOUT_S


def test_timeout_expired_raises_cloud_unreachable(tmp_path: Path) -> None:
    def effect(_argv, _kwargs):
        raise subprocess.TimeoutExpired("bash", 3600)

    runner = FakeRunner(stdout="")
    runner.effect = effect
    tree = make_tree(tmp_path)
    with pytest.raises(gp.CloudUnreachable, match="超时"):
        make_transport(tmp_path, runner).run_gate({"port_base": 9200}, tree)


# ---------------------------------------------------------------- ⑪ 私有路径
def test_source_has_no_private_path_literals() -> None:
    text = (ROOT / "tools" / "gate_pool.py").read_text(encoding="utf-8")
    for marker in PRIVATE_MARKERS:
        assert marker not in text, f"源码里有私有路径字面量：{marker}"


# ---------------------------------------------------------------- ⑫ creationflags
def test_subprocess_gets_creationflags(tmp_path: Path) -> None:
    runner = FakeRunner(stdout=BANNERS)
    tree = make_tree(tmp_path)
    write_payload(tree, {"ok": True})
    make_transport(tmp_path, runner).run_gate({"port_base": 9200}, tree)
    assert "creationflags" in runner.calls[-1][1]
    assert runner.calls[-1][1]["creationflags"] == getattr(
        subprocess, "CREATE_NO_WINDOW", 0)


# ---------------------------------------------------------------- 附：缺 port_base
def test_missing_port_base_raises(tmp_path: Path) -> None:
    runner = FakeRunner(stdout=BANNERS)
    tree = make_tree(tmp_path)
    with pytest.raises(gp.CloudUnreachable, match="port_base"):
        make_transport(tmp_path, runner).run_gate({}, tree)
    assert runner.calls == []
