r"""批次二分的钉子（卡 E11 · `T-AG462` 判据 1–6）。

| # | 钉子 | 坏掉会红在哪 |
|---|---|---|
| ① | 绿批**不触发**二分，`bisect.json` 不产生 | 无条件二分 ⇒ 绿批也烧门禁 |
| ② | 批红**自动**触发（不靠人记得加参数）；定位到单卡，`culprit` = 那张卡号 | 改成人工参数 ⇒ 红 |
| ③ | 轮数 ≤ `ceil(log2(n))+1`，每轮是上一轮红集的**真子集** | 原地重跑整批 ⇒ 红 |
| ④ | 卡号**精确匹配**：`G1` 不许命中 `F1`/`B1`，`E4` 不许命中 `F4` | 数字/子串当键 ⇒ 定位到别人 |
| ⑤ | 全绿但批红 ⇒ `culprit=None` + 明说「未能定位」，不许编一个 | 编一个 culprit ⇒ 红 |
| ⑥ | 绿卡重新合批的命令里是**这一轮实测绿**的那些，不是原批 | 写回全批 ⇒ 红 |
| ⑦ | 台账写「批 N 张、二分 K 轮、多花 M 分钟」；`bisect.json` 记耗时（误差 ≤5%） | 不记读数 ⇒ 红 |
| ⑧ | 审计红**不二分**（文书/台账问题，逐卡修更快） | 对审计红二分 ⇒ 红 |
| ⑨ | `bisect --dry-run` 只打印拆分计划（不跑门、不写文件） | dry-run 真跑 ⇒ 红 |

★ 全部用**假 runner / 桩落地命令**：不跑真门禁（卡规格：只跑点名测试文件）。
"""

from __future__ import annotations

import importlib.util
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import wb_batch as wb  # noqa: E402
from pool import landing as landing_mod  # noqa: E402
from pool import plan as pool_plan  # noqa: E402

BATCH = "T-9"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _cards(ids: list[str]) -> list[pool_plan.Card]:
    return [pool_plan.Card(id=i, task=f"T-{i}", title=f"卡 {i}", tree=f".wt/{i}",
                           spec=f"复盘/卡/卡{i}.md", files=(f"code/{i}.py",))
            for i in ids]


_LAND_STUB_RED = '''import sys

print("=== ④ 锁（段 9034）→ 门禁 ===")
print("[ERR] pytest exit=1 2 failed")
sys.exit(1)
'''

_LAND_STUB_GREEN = '''print("=== ④ 锁（段 9034）→ 门禁 ===")
print("质量门 + 文档同步通过")
'''

_LAND_STUB_AUDIT_RED = '''import sys

print("审计不通过：tia_map.py 没有证据指针（台账）")
sys.exit(1)
'''


def _env(tmp_path: Path, ids: list[str], *, stub: str = _LAND_STUB_RED) -> wb.Env:
    root = tmp_path / "root"
    main = tmp_path / "main"
    (root / "docs" / "changelog.d").mkdir(parents=True)
    (root / "tools").mkdir(parents=True)
    (root / "tools" / "wb_land.py").write_text(stub, encoding="utf-8")
    batch_dir = main / "gates" / "diag" / "batch"
    batch_dir.mkdir(parents=True)
    (main / wb.batch_tree_rel(BATCH)).mkdir(parents=True)
    manifest = wb.render_manifest(BATCH, _cards(ids), "测试批", wb.GATE_CMD)
    (batch_dir / f"{BATCH}.toml").write_text(manifest, encoding="utf-8")
    return wb.Env(root=root, main=main, batch_dir=batch_dir)


def _runner(red: tuple[str, ...], *, seconds: float = 1.5):
    """假 runner：**精确**按成员判断（`list.__contains__`，不是子串）。

    每趟输出都带上是哪个子集 —— 方便断言「红的原文」归给了正确的那张卡。
    """
    calls: list[list[str]] = []

    def run(members: list[str]) -> wb.GateOutcome:
        calls.append(list(members))
        hit = [m for m in members if m in red]
        if hit:
            out = f"[ERR] pytest exit=1 2 failed（子集 {'+'.join(members)}；红 {hit[0]}）"
            return wb.GateOutcome(rc=1, output=out, seconds=seconds)
        return wb.GateOutcome(rc=0, output=f"全绿（子集 {'+'.join(members)}）", seconds=seconds)

    return run, calls


def _fake_clock(step: float = 0.5):
    state = {"t": 0.0}

    def clock() -> float:
        state["t"] += step
        return state["t"]

    return clock


# ---------------------------------------------------------------- ① 绿批不触发
def test_green_batch_does_not_bisect(tmp_path: Path) -> None:
    """绿批 ⇒ 退 0、**不产生** `bisect.json`（判据 1）。"""
    env = _env(tmp_path, ["G1", "F1"], stub=_LAND_STUB_GREEN)
    run, calls = _runner(())
    rc = wb.land_batch(env, BATCH, [], runner=run, clock=_fake_clock())
    assert rc == 0
    assert not (env.batch_dir / f"{BATCH}.bisect.json").exists(), "绿批也产出了 bisect.json"
    assert calls == [], "绿批不该起任何子集门禁"


# ---------------------------------------------------------------- ②③ 批红自动二分
def test_red_batch_bisects_and_names_the_card(tmp_path: Path) -> None:
    """批红 ⇒ **自动**二分；定位到单卡，`culprit` 就是那张卡号（判据 1/2/3）。"""
    env = _env(tmp_path, ["G1", "F1", "B1"])
    run, calls = _runner(("G1",))
    rc = wb.land_batch(env, BATCH, [], runner=run, clock=_fake_clock())

    assert rc == 1, "批红要如实退非 0"
    payload = json.loads((env.batch_dir / f"{BATCH}.bisect.json").read_text(encoding="utf-8"))
    assert payload["culprit"] == "G1", payload
    assert payload["not_located"] is False
    assert payload["culprit_gate"] == "pytest", payload
    assert "[ERR] pytest exit=1" in payload["culprit_raw"], payload
    assert "子集 G1" in payload["culprit_raw"], "红的原文不是 G1 那一趟的"

    rounds = payload["rounds"]
    assert len(rounds) <= math.ceil(math.log2(3)) + 1, f"轮数超上限：{len(rounds)}"
    # 轮 0 = 整批（不重跑）；之后每轮是上一轮**红集**的真子集
    assert rounds[0]["subsets"] == [["G1", "F1", "B1"]], rounds[0]
    assert rounds[0]["source"].startswith("批次")
    assert all(len(s) < 3 for r in rounds[1:] for s in r["subsets"]), "原地重跑了整批"
    # 绿卡合一：这一轮实测绿的（F1、B1），不是原来全批
    assert sorted(payload["green"]) == ["B1", "F1"], payload["green"]
    assert payload["regroup_cmd"].endswith("--cards F1 B1"), payload["regroup_cmd"]
    assert "G1" not in payload["regroup_cmd"]
    # 不许原地重跑整批：没有任何一次 runner 收到全批三人
    assert all(sorted(c) != ["B1", "F1", "G1"] for c in calls), calls


# ---------------------------------------------------------------- ④ 精确匹配
def test_card_ids_match_exactly_not_by_digit(tmp_path: Path) -> None:
    """`E4` 与 `F4` 同数字键：只红 E4 ⇒ culprit 必须是 `E4`，不许落到 `F4`。"""
    env = _env(tmp_path, ["E4", "F4"])
    run, calls = _runner(("E4",))
    wb.land_batch(env, BATCH, [], runner=run, clock=_fake_clock())
    payload = json.loads((env.batch_dir / f"{BATCH}.bisect.json").read_text(encoding="utf-8"))
    assert payload["culprit"] == "E4", payload
    assert payload["green"] == ["F4"], payload["green"]
    assert payload["regroup_cmd"].endswith("--cards F4"), payload["regroup_cmd"]
    for subset in calls:
        assert set(subset) <= {"E4", "F4"}, subset


def test_batch_integration_does_not_confuse_g1_with_f1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """★ 批集成按卡号匹配**精确优先**：`G1` 不许拿 `F1` 的树当自己的（卡 E13 那次的真坑）。

    两个场景：
    · ① 栅栏只有 `G1`，而 backlog 里只有 `F1`（数字键都是 1）⇒ **停手**（False），
      `F1` 的改动一个字节都不许并进来；
    · ② 栅栏里 `G1` / `F1` 都在 ⇒ 各按**自己的树**并，两个文件都在。
    """
    def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=str(repo),
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", check=False)

    base = tmp_path / "repo"
    base.mkdir()
    _git(base, "init", "-q")
    _git(base, "config", "user.email", "nail@example.invalid")
    _git(base, "config", "user.name", "nail")
    (base / "seed.py").write_text("S = 1\n", encoding="utf-8")
    _git(base, "add", "-A")
    _git(base, "commit", "-q", "-m", "init")

    # 两棵卡树：G1 改 g1.py，F1 改 f1.py
    for card, name in (("G1", "g1.py"), ("F1", "f1.py")):
        tree = base / ".wt" / card
        _git(base, "worktree", "add", "--detach", str(tree), "HEAD")
        (tree / name).write_text(f"{card} = 1\n", encoding="utf-8")

    into = base / "into"
    into.mkdir()
    (into / "docs").mkdir()
    (into / "docs" / "workbacklog.toml").write_text(
        '[[cards]]\nid = "F1"\ntree = ".wt/F1"\nfiles = ["f1.py"]\n',
        encoding="utf-8")
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()
    monkeypatch.setenv("TF_BATCH_DIR", str(batch_dir))
    monkeypatch.setattr(landing_mod, "ROOT", base)

    def _manifest(members: str) -> None:
        (batch_dir / "B9.toml").write_text(
            'id = "B9"\nwhy = "测试"\ngate_cmd = "python -X utf8 scripts/run_gates.py"\n'
            f'on_complete = ["draft"]\n{members}', encoding="utf-8")

    # ① 只有 G1：backlog 里没有 G1 的块，只有 F1（数字键撞车）⇒ 停手，F1 的改动不许进来
    _manifest('\n[[member]]\nid = "G1"\nlayer = "源码层"\nwhat = "卡 G1"\n'
              'paths = ["g1.py"]\ntree = ".wt/G1"\n')
    assert landing_mod._integrate_multi_tree(into, "B9", "T-B9") is False, \
        "G1 冒用了 F1 的树却照样往下走"
    assert not (into / "f1.py").exists(), "★ F1 的改动被当成 G1 并进来了（卡号匹配不精确）"

    # ② G1 / F1 都是成员 ⇒ 各按自己的树并，两个文件都在
    (into / "docs" / "workbacklog.toml").write_text(
        '[[cards]]\nid = "G1"\ntree = ".wt/G1"\nfiles = ["g1.py"]\n\n'
        '[[cards]]\nid = "F1"\ntree = ".wt/F1"\nfiles = ["f1.py"]\n',
        encoding="utf-8")
    _manifest('\n[[member]]\nid = "G1"\nlayer = "源码层"\nwhat = "卡 G1"\n'
              'paths = ["g1.py"]\ntree = ".wt/G1"\n\n'
              '[[member]]\nid = "F1"\nlayer = "源码层"\nwhat = "卡 F1"\n'
              'paths = ["f1.py"]\ntree = ".wt/F1"\n')
    assert landing_mod._integrate_multi_tree(into, "B9", "T-B9") is True
    assert (into / "g1.py").is_file(), "G1 的改动没并进来"
    assert (into / "f1.py").is_file(), "F1 的改动没并进来"


# ---------------------------------------------------------------- ⑤ 未能定位
def test_all_green_but_batch_red_is_not_located(tmp_path: Path) -> None:
    """全绿但批仍红（环境/非确定性）⇒ `culprit=None` + 明说「未能定位」（判据 3）。"""
    env = _env(tmp_path, ["G1", "F1"])
    run, _ = _runner(())          # 每张卡单独/成组跑都绿
    result = wb.bisect_after_red(env, BATCH, ["G1", "F1"],
                                 batch_output="[ERR] pytest exit=1 2 failed",
                                 batch_seconds=2.0, runner=run)
    assert result["culprit"] is None
    assert result["not_located"] is True
    assert "未能定位" in result["note"]
    assert "未能定位" in wb.render_bisect_report(result)
    payload = json.loads((env.batch_dir / f"{BATCH}.bisect.json").read_text(encoding="utf-8"))
    assert payload["culprit"] is None


# ---------------------------------------------------------------- ⑧ 审计红不二分
def test_audit_red_is_not_bisected(tmp_path: Path) -> None:
    """审计红 ⇒ 不二分、不产生 `bisect.json`，且**一次 runner 都不起**。"""
    env = _env(tmp_path, ["G1", "F1"], stub=_LAND_STUB_AUDIT_RED)
    run, calls = _runner(("G1",))
    rc = wb.land_batch(env, BATCH, [], runner=run, clock=_fake_clock())
    assert rc == 1
    assert calls == [], "审计红却起了二分"
    assert not (env.batch_dir / f"{BATCH}.bisect.json").exists()


# ---------------------------------------------------------------- ⑦ 读数与台账
def test_bisect_json_and_changelog_record_the_readings(tmp_path: Path) -> None:
    """`bisect.json` 记耗时；台账（`docs/changelog.d/<批号>.md`）写那一行原话。"""
    env = _env(tmp_path, ["G1", "F1", "B1"])
    run, _ = _runner(("F1",), seconds=1.5)
    wb.land_batch(env, BATCH, [], runner=run, clock=_fake_clock(0.5))
    payload = json.loads((env.batch_dir / f"{BATCH}.bisect.json").read_text(encoding="utf-8"))

    measured = sum(float(r["seconds"]) for r in payload["rounds"])
    assert payload["total_seconds"] == pytest.approx(measured, abs=0.01)
    assert payload["extra_seconds"] == pytest.approx(
        payload["total_seconds"] - payload["batch_seconds"], abs=0.01)
    # 「总和与批次日志里的时长对得上」：两项相加与 total 的误差 ≤5%
    joined = payload["batch_seconds"] + sum(
        float(r["seconds"]) for r in payload["rounds"][1:])
    assert abs(joined - payload["total_seconds"]) <= 0.05 * max(payload["total_seconds"], 1e-9)

    ledger = (env.root / "docs" / "changelog.d" / f"{BATCH}.md").read_text(encoding="utf-8")
    assert "批 3 张" in ledger, ledger
    assert f"二分 {len(payload['rounds'])} 轮" in ledger, ledger
    assert "多花" in ledger and "分钟" in ledger, ledger
    assert "culprit=F1" in ledger, ledger


# ---------------------------------------------------------------- ⑨ dry-run
def test_bisect_dry_run_prints_plan_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """`bisect <批号> --dry-run` 只打印拆分计划（判据：只打印会怎么拆）。"""
    env = _env(tmp_path, ["G1", "F1", "B1"])
    rc = wb.main(["--root", str(env.root), "--main", str(env.main),
                  "--batch-dir", str(env.batch_dir), "bisect", BATCH, "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "轮 0" in out and "不重跑" in out, out
    assert "G1" in out and "F1" in out and "B1" in out, out
    assert not (env.batch_dir / f"{BATCH}.bisect.json").exists(), "dry-run 写了 bisect.json"


def test_bisect_without_land_log_refuses_to_rerun(tmp_path: Path) -> None:
    """没有落地日志 ⇒ `bisect` 拒绝凭空重跑整批（不许造二分）。"""
    env = _env(tmp_path, ["G1", "F1"])
    rc = wb.main(["--root", str(env.root), "--main", str(env.main),
                  "--batch-dir", str(env.batch_dir), "bisect", BATCH])
    assert rc == 2
