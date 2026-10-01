#!/usr/bin/env python
"""`tools/tf_commit.py` 七步一条命令 + 硬闸门的钉子测试（T-G192 / 卡 097）。

为什么有它：提交流程从"人手工一步步敲"改成"一条命令 + 硬闸门"之后，
必须钉死"红了会说话、红了会停、红了不泄漏锁"这三件事 —— 每一条判据都要有**反例**。

★ **绝不碰真仓库**：每个用例在 `tmp_path` 里 `git init` 造一个假仓库；
  七步里的外部命令（sync_counts / gate_lock / run_gates / audit）用假 runner 替掉，
  但 **git 命令原样在假仓库里真跑** —— 于是"有没有 commit / 暂存区变没变"都是真的。

反例清单（对应卡 §硬要求）：
  ① 门禁红 → 不 commit + 打印「不提交」+ release 被调用；
  ② 白名单外被 stage → 退 2 且点名；暂存区空 → 退 3；
  ③ trailer 缺一个 / Task: 两个 → 退 4；
  ④ `--dry-run` → 假仓库 git log / status 一字未变、一条外部命令都没发；
  ⑤ `--step 3` → 第 4 步之后的东西没被执行；
  ⑥ `git add .` / `-A` → 退 2 且不 add；
  ⑦ ★ 锁的端口段：acquire 与 release 带**同一个** TF_GATE_PORT_BASE。
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]
_TF = Path(__file__).resolve().parents[1] / "tools" / "tf_commit.py"


def _load():
    import sys

    name = "tf_commit_under_test"
    spec = importlib.util.spec_from_file_location(name, _TF)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod  # dataclass 解析字符串注解会回头找 sys.modules[__module__]
    spec.loader.exec_module(mod)
    return mod


tf = _load()


# ---------------------------------------------------------------- 假仓库
def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=str(repo), check=True, capture_output=True, text=True, encoding="utf-8",
    )


def make_repo(tmp: Path) -> Path:
    repo = tmp / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "worker@example.com")
    _git(repo, "config", "user.name", "worker")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "--", "README.md")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def head(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def porcelain(repo: Path) -> str:
    return _git(repo, "status", "--porcelain").stdout


# ---------------------------------------------------------------- 假 runner
def _label(cmd: list[str]) -> str:
    s = " ".join(cmd)
    if cmd[0] == "git":
        return "git"
    if "sync_counts.py" in s:
        return "sync_counts"
    if "gate_lock.py" in s and "acquire" in s:
        return "acquire"
    if "gate_lock.py" in s and "release" in s:
        return "release"
    if "run_gates.py" in s and "--seal" in s:
        return "seal"
    if "run_gates.py" in s:
        return "gates"
    if "audit_progress.py" in s:
        return "audit"
    return "other"


class Fake:
    """外部命令替身：工具命令按 overrides 回放；git 命令原样在假仓库里真跑。"""

    def __init__(self, overrides: dict[str, object] | None = None) -> None:
        self.overrides = overrides or {}
        self.calls: list[SimpleNamespace] = []

    def __call__(self, cmd, cwd=None, env=None):
        cmd = [str(c) for c in cmd]
        self.calls.append(
            SimpleNamespace(cmd=cmd, cwd=cwd, env=dict(env or {}), label=_label(cmd))
        )
        if _label(cmd) == "git":
            return tf.sh(cmd, cwd=cwd, env=env)  # 真 git，但只在假仓库里
        if _label(cmd) in self.overrides:
            return self.overrides[_label(cmd)]
        return tf.Result(0, f"<{_label(cmd)} ok>")

    def called(self, label: str) -> list[SimpleNamespace]:
        return [c for c in self.calls if c.label == label]


# ---------------------------------------------------------------- 参数/消息
def write_msg(path: Path, task: str = "T-G192", omit: str | None = None,
              extra_task_line: str | None = None, task_value: str | None = None) -> None:
    lines: list[str] = []
    for key in ("Task", "Refs", "Ledger", "Gates"):
        if key == omit:
            continue
        if key == "Task":
            lines.append(f"Task: {task_value if task_value is not None else task}")
        else:
            lines.append(f"{key}: 见凭证")
    if extra_task_line is not None:
        lines.append(f"Task: {extra_task_line}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def argv(repo: Path, allow: list[str], msg: Path, *extra: str) -> list[str]:
    return [
        "--card", "097", "--task", "T-G192",
        "--allow", *allow, "--msg-file", str(msg), *extra,
    ]


@pytest.fixture(autouse=True)
def _isolate_port_base(monkeypatch):
    """shell 可能带着 TF_GATE_PORT_BASE（本卡自己的门禁段）—— 每个用例先隔离。"""
    monkeypatch.delenv("TF_GATE_PORT_BASE", raising=False)


# ---------------------------------------------------------------- ① 门禁红
def test_gate_red_stops_no_commit_and_releases(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("TF_GATE_PORT_BASE", "9173")
    repo = make_repo(tmp_path)
    msg = tmp_path / "msg.txt"
    write_msg(msg)
    before = head(repo)
    fake = Fake({"gates": tf.Result(1, "[FAIL] pytest 红")})

    rc = tf.main(argv(repo, ["README.md"], msg), runner=fake, repo=repo)

    out = capsys.readouterr().out
    assert rc == 1
    assert "第 4 步失败 ⇒ 不提交" in out
    assert "FAIL" in out
    assert head(repo) == before, "门禁红了绝不许 commit"
    assert len(fake.called("release")) == 1, "第③步之后失败必须释放锁"
    assert fake.called("seal") == [], "红了不许走到第⑤步"
    assert fake.called("audit") == [], "红了不许走到第⑦步"


def test_lock_segment_same_for_acquire_and_release(tmp_path, monkeypatch):
    """★ 治「release 不带同一个段 → 找默认段 → 锁泄漏」那把坑。"""
    monkeypatch.setenv("TF_GATE_PORT_BASE", "9173")
    repo = make_repo(tmp_path)
    msg = tmp_path / "msg.txt"
    write_msg(msg)
    fake = Fake({"gates": tf.Result(1, "red")})

    tf.main(argv(repo, ["README.md"], msg), runner=fake, repo=repo)

    acq = fake.called("acquire")[0].env.get("TF_GATE_PORT_BASE")
    rel = fake.called("release")[0].env.get("TF_GATE_PORT_BASE")
    assert acq == rel == "9173"


def test_lock_segment_default_when_unset(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    msg = tmp_path / "msg.txt"
    write_msg(msg)
    fake = Fake({"gates": tf.Result(1, "red")})

    tf.main(argv(repo, ["README.md"], msg), runner=fake, repo=repo)

    acq = fake.called("acquire")[0].env.get("TF_GATE_PORT_BASE")
    rel = fake.called("release")[0].env.get("TF_GATE_PORT_BASE")
    assert acq == rel == "8531"


# ---------------------------------------------------------------- ② 白名单 / 空暂存
def test_allowlist_violation_exit2_names_offender(tmp_path, capsys):
    repo = make_repo(tmp_path)
    (repo / "legit.txt").write_text("ok\n", encoding="utf-8")
    (repo / "rogue.txt").write_text("偷渡\n", encoding="utf-8")
    _git(repo, "add", "--", "rogue.txt")  # 先偷偷 stage 一个白名单外的
    msg = tmp_path / "msg.txt"
    write_msg(msg)
    before = head(repo)

    rc = tf.main(argv(repo, ["legit.txt"], msg), runner=Fake(), repo=repo)

    out = capsys.readouterr().out
    assert rc == 2
    assert "rogue.txt" in out
    assert "白名单外" in out
    assert head(repo) == before, "退 2 就是不提交"


def test_empty_stage_exit3(tmp_path, capsys):
    repo = make_repo(tmp_path)  # README.md 已提交且未改
    msg = tmp_path / "msg.txt"
    write_msg(msg)
    before = head(repo)

    rc = tf.main(argv(repo, ["README.md"], msg), runner=Fake(), repo=repo)

    out = capsys.readouterr().out
    assert rc == 3
    assert "暂存区为空" in out
    assert head(repo) == before


def test_add_dot_and_dash_a_rejected(tmp_path, capsys):
    repo = make_repo(tmp_path)
    msg = tmp_path / "msg.txt"
    write_msg(msg)
    # ".", "-A" 用 `--allow=<值>` 形式传（argparse 会把裸 `-A` 当选项 → 那是它自己的错）
    for bad in (".", "-A", "src/**"):
        argv_bad = ["--card", "097", "--task", "T-G192", f"--allow={bad}", "--msg-file", str(msg)]
        fake = Fake()
        rc = tf.main(argv_bad, runner=fake, repo=repo)
        out = capsys.readouterr().out
        assert rc == 2, bad
        assert "绝不许 git add . / -A" in out
        assert not any(c.label == "git" for c in fake.calls), "禁止项根本不许发 git add"


# ---------------------------------------------------------------- ③ trailer
def test_trailer_missing_exit4(tmp_path, capsys):
    repo = make_repo(tmp_path)
    (repo / "work.txt").write_text("w\n", encoding="utf-8")
    msg = tmp_path / "msg.txt"
    write_msg(msg, omit="Gates")
    before = head(repo)

    rc = tf.main(argv(repo, ["work.txt"], msg), runner=Fake(), repo=repo)

    out = capsys.readouterr().out
    assert rc == 4
    assert "缺" in out and "Gates" in out
    assert head(repo) == before


def test_task_not_exactly_one_exit4(tmp_path, capsys):
    repo = make_repo(tmp_path)
    (repo / "work.txt").write_text("w\n", encoding="utf-8")
    msg = tmp_path / "msg.txt"

    # (a) 两条 Task 行
    write_msg(msg, extra_task_line="T-G193")
    before = head(repo)
    rc = tf.main(argv(repo, ["work.txt"], msg), runner=Fake(), repo=repo)
    out = capsys.readouterr().out
    assert rc == 4 and "恰好一个编号" in out
    assert head(repo) == before

    # (b) 一行两个编号
    write_msg(msg, task_value="T-G192 T-G193")
    rc = tf.main(argv(repo, ["work.txt"], msg), runner=Fake(), repo=repo)
    out = capsys.readouterr().out
    assert rc == 4 and "恰好一个编号" in out
    assert head(repo) == before


def test_task_mismatch_option_exit4(tmp_path, capsys):
    repo = make_repo(tmp_path)
    (repo / "work.txt").write_text("w\n", encoding="utf-8")
    msg = tmp_path / "msg.txt"
    write_msg(msg, task="T-G111")  # 与 --task T-G192 不一致
    rc = tf.main(argv(repo, ["work.txt"], msg), runner=Fake(), repo=repo)
    out = capsys.readouterr().out
    assert rc == 4 and "不一致" in out


# ---------------------------------------------------------------- ④ dry-run
def test_dry_run_changes_nothing(tmp_path, capsys):
    repo = make_repo(tmp_path)
    (repo / "work.txt").write_text("w\n", encoding="utf-8")
    msg = tmp_path / "msg.txt"
    write_msg(msg)
    log_before, st_before = head(repo), porcelain(repo)

    fake = Fake()
    rc = tf.main(argv(repo, ["work.txt"], msg, "--dry-run"), runner=fake, repo=repo)

    out = capsys.readouterr().out
    assert rc == 0
    assert fake.calls == [], "--dry-run 一条外部命令都不许发"
    assert head(repo) == log_before
    assert porcelain(repo) == st_before
    # 七步的确切命令都要打出来
    for marker in ("[1]", "[2]", "[3]", "[4]", "[5]", "[6]", "[7]",
                   "sync_counts.py", "gate_lock.py", "run_gates.py", "audit_progress.py"):
        assert marker in out


# ---------------------------------------------------------------- ⑤ --step 截断
def test_step3_does_not_run_later_steps(tmp_path, capsys):
    repo = make_repo(tmp_path)
    msg = tmp_path / "msg.txt"
    write_msg(msg)
    before = head(repo)
    fake = Fake()

    rc = tf.main(argv(repo, ["README.md"], msg, "--step", "3"), runner=fake, repo=repo)

    out = capsys.readouterr().out
    assert rc == 0
    assert "[3]" in out
    assert len(fake.called("sync_counts")) == 1
    assert len(fake.called("acquire")) == 1
    assert fake.called("gates") == [], "第 4 步之后不许跑"
    assert fake.called("seal") == []
    assert fake.called("audit") == []
    assert fake.called("release") == [], "★ 主动截停 ≠ 失败：不释放锁（留给分步复核）"
    assert head(repo) == before


def test_skip_step(tmp_path, capsys):
    repo = make_repo(tmp_path)
    (repo / "work.txt").write_text("w\n", encoding="utf-8")
    msg = tmp_path / "msg.txt"
    write_msg(msg)
    fake = Fake()

    rc = tf.main(
        argv(repo, ["work.txt"], msg, "--skip", "2", "--skip", "5"), runner=fake, repo=repo
    )

    out = capsys.readouterr().out
    assert rc == 0
    assert "截断" in out and "七步全过" not in out, "跳了步就不许自称全过"
    assert fake.called("sync_counts") == [], "--skip 2 生效"
    assert fake.called("seal") == [], "--skip 5 生效"
    assert len(fake.called("gates")) == 1


# ---------------------------------------------------------------- 正向：真的会提交
def test_happy_path_commits_only_allowlisted(tmp_path, capsys):
    repo = make_repo(tmp_path)
    (repo / "work.txt").write_text("w\n", encoding="utf-8")
    msg = tmp_path / "msg.txt"
    write_msg(msg)
    fake = Fake()

    rc = tf.main(argv(repo, ["work.txt"], msg), runner=fake, repo=repo)

    out = capsys.readouterr().out
    assert rc == 0
    assert "七步全过 ✅" in out
    # 真提交了、且只带 work.txt
    files = _git(repo, "show", "--name-only", "--format=", "HEAD").stdout.split()
    assert files == ["work.txt"]
    body = _git(repo, "log", "-1", "--format=%B").stdout
    assert "Task: T-G192" in body and "Gates:" in body
    assert len(fake.called("release")) == 1
    assert len(fake.called("audit")) == 1


def test_no_reuse_passthrough(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "work.txt").write_text("w\n", encoding="utf-8")
    msg = tmp_path / "msg.txt"
    write_msg(msg)
    fake = Fake()

    rc = tf.main(argv(repo, ["work.txt"], msg, "--no-reuse"), runner=fake, repo=repo)

    assert rc == 0
    gates_calls = fake.called("gates")
    assert len(gates_calls) == 1 and "--no-reuse" in gates_calls[0].cmd


def test_bad_step_value_exit2(tmp_path, capsys):
    repo = make_repo(tmp_path)
    msg = tmp_path / "msg.txt"
    write_msg(msg)
    rc = tf.main(argv(repo, ["README.md"], msg, "--step", "9"), runner=Fake(), repo=repo)
    out = capsys.readouterr().out
    assert rc == 2
    assert "只接受 1..7" in out
