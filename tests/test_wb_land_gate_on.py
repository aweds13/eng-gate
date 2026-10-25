r"""落地链「门禁在哪跑」的钉子（卡 E42 · `T-AG494` 判据 2 至少 6 条）。

钉的是四件事：

| # | 钉子 | 坏掉会红在哪 |
|---|---|---|
| ① | 真仓有 `tools/gate_pool.py`，且 `--help` 里有 `--gate-on` | 删掉云门禁池那支 = 悄悄回本机 |
| ② | `--gate-on cloud` + 没配云机 ⇒ **退 2**，且**没有**继续落地 | 改成回落本机 ⇒ 本钉子红 |
| ③ | `--gate-on cloud` + 假云机不可达 ⇒ **退 2**，卡树一个字节不动 | 先去写文书再判 ⇒ 钉子红 |
| ④ | 假云机回传合格 ⇒ 落地成功：trailer 有 `Gates-on: cloud@<host>` | 写死 `local` ⇒ 钉子红 |
| ⑤ | 回传缺 `host` / `rev` 不匹配 / 用例 <95% ⇒ **拒**（不提交） | 任一条放宽 ⇒ 对应钉子红 |
| ⑥ | `Gates-on:` 与实际一致（云带 `@host`、本机是裸 `local`） | 两套字面 ⇒ 钉子红 |
| ⑦ | 显式 `--gate-on local` ⇒ 走老路（门禁桩被真跑到） | 把 local 也拐去云 ⇒ 钉子红 |

★ 一律用**假云机**（`TF_GATE_CLOUD_FAKE` 指向一份 JSON）与**桩门禁**：不连任何云机、
  不跑真门禁（卡规格：云机实测由主控做）。
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType

import pytest  # noqa: E402 —— 用在 monkeypatch 注解与 pytest.raises

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
TESTS = ROOT / "tests"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import gate_pool as gp  # noqa: E402


def _load(name: str, path: Path) -> ModuleType:
    """按路径加载模块（不污染 `sys.path` 的包布局）。"""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


#: `tests/test_wb_land.py` 的假仓夹具（复用，不另写第二份；它只做 git 与桩）。
_wand_mod = _load("_e52_wb_land_fixture", TESTS / "test_wb_land.py")


#: 沙箱的 `scripts/run_gates.py` 桩：**带上门表**（云那趟要按门表现读应有门名）。
#: 只两条门（pytest / ruff）—— 假回传就照这两条造，钉子只判"门数/门名对得上"。
_STUB_RUN_GATES = '''import pathlib
import sys

DOORS = ["pytest", "ruff"]


def build_jobs(quick, fast, profile="all"):
    return [(name, []) for name in DOORS]


def main():
    pathlib.Path("gate_ran.marker").write_text("ran", encoding="utf-8")
    print("stub-run_gates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

#: 沙箱用的 `.gitignore` 追加项：云那趟的运行时产物（真仓里 `gates/**` 本就被忽略）。
_GITIGNORE_EXTRA = "gates/logs/\ngates/diag/\ngates/diag/pytest_baseline.json\n"


def _cloud_repo(tmp_path: Path) -> Path:
    """假仓库 + 云门禁池 + 带门表的门禁桩（`gates/**` 产物按真仓口径忽略）。"""
    repo = _wand_mod._mk_repo(tmp_path, run_gates_body=_STUB_RUN_GATES)
    (repo / "tools" / "gate_pool.py").write_bytes((TOOLS / "gate_pool.py").read_bytes())
    gi = repo / ".gitignore"
    gi.write_text(gi.read_text(encoding="utf-8") + _GITIGNORE_EXTRA, encoding="utf-8")
    _wand_mod._git(repo, "add", "-A")
    _wand_mod._git(repo, "commit", "-q", "-m", "cloud-pool")
    _wand_mod._mk_pen(repo)
    return repo


def _fake(tmp_path: Path, payload: dict, *, reachable: bool = True,
          pytest_log: str = "100 passed in 1s", clean: bool = True) -> Path:
    path = tmp_path / ("fake-cloud.json" if reachable else "fake-down.json")
    path.write_text(json.dumps({
        "reachable": reachable, "payload": payload, "pytest_log": pytest_log,
        "workspace_clean": clean, "logs": {"pytest.log": pytest_log},
    }, ensure_ascii=False), encoding="utf-8")
    return path


def _head(repo: Path, tree: str = ".pen") -> str:
    return _wand_mod._git(repo, "rev-parse", "HEAD").stdout.strip()


def _env(fake: Path | None = None, *, host: str = "fake-cloud",
         baseline: str = "100") -> dict[str, str]:
    env = {**_wand_mod._ENV, "TF_GATE_CLOUD_HOST": host, "TF_PYTEST_BASELINE": baseline}
    if fake is not None:
        env["TF_GATE_CLOUD_FAKE"] = str(fake)
    return env


# ---------------------------------------------------------------- ① 入口在
def test_default_gate_on_is_cloud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**默认 cloud**（卡 E42 §2.1）：不给人 `--gate-on`、也没设 `TF_GATE_ON` ⇒ cloud。

    ★ 改回「默认留本机」⇒ 本钉子红，而且 `test_cloud_without_host_exits_2_and_does_not_land`
      也会红（它会真在本机跑门禁桩）。
    """
    from pool import landing

    monkeypatch.delenv("TF_GATE_ON", raising=False)
    assert landing.resolve_gate_on(None) == "cloud"
    assert landing.DEFAULT_GATE_ON == "cloud"
    assert landing.resolve_gate_on("local") == "local"
    with pytest.raises(ValueError):
        landing.resolve_gate_on("本机")


def test_real_tree_has_gate_pool_module() -> None:
    """真仓必须有 `tools/gate_pool.py`（删掉它，云那支就悄悄回本机）。"""
    assert (TOOLS / "gate_pool.py").is_file(), "云门禁池模块不见了"
    done = subprocess.run([sys.executable, "-X", "utf8", str(TOOLS / "wb_land.py"), "--help"],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env={**os.environ})
    assert done.returncode == 0, done.stderr
    assert "--gate-on" in done.stdout, "`--help` 里没有 `--gate-on`（旧调用点找不到入口）"


# ---------------------------------------------------------------- ② 没配云机 ⇒ 退 2
def test_cloud_without_host_exits_2_and_does_not_land(tmp_path: Path) -> None:
    """默认（cloud）+ 没配 `TF_GATE_CLOUD_HOST` ⇒ 退 2，且**一步都没落地**。"""
    repo = _cloud_repo(tmp_path)
    before = _head(repo)
    env = {k: v for k, v in _wand_mod._ENV.items() if k != "TF_GATE_CLOUD_HOST"}
    done = _wand_mod._wand(repo, tree=".pen", env=env)
    out = _wand_mod._out(done)
    assert done.returncode == 2, out
    assert "云机不可达" in out and "未跑门禁" in out, out
    assert "不回落本机" in out, out
    assert _head(repo) == before, "云机不可达却提交了"
    assert not (repo / "docs" / "changelog.d" / "T-G999.md").exists(), "还没跑门禁就写了文书"
    assert not (repo / ".pen" / "gate_ran.marker").exists(), "不许偷偷在本机跑门禁"


# ---------------------------------------------------------------- ③ 假云机不可达
def test_cloud_unreachable_exits_2_and_touches_nothing(tmp_path: Path) -> None:
    """假云机 `reachable=false` ⇒ 退 2，卡树 `git status` 逐字不变。"""
    repo = _cloud_repo(tmp_path)
    fake = _fake(tmp_path, {}, reachable=False)
    st_before = _wand_mod._git(repo, "status", "--porcelain", "-uall").stdout
    done = _wand_mod._wand(repo, tree=".pen", env=_env(fake))
    out = _wand_mod._out(done)
    assert done.returncode == 2, out
    assert "云机不可达" in out, out
    assert _wand_mod._git(repo, "status", "--porcelain", "-uall").stdout == st_before


# ---------------------------------------------------------------- ④ 假云机绿 ⇒ 落地
def test_cloud_fake_green_lands_with_gates_on_trailer(tmp_path: Path) -> None:
    """回传五条全过 ⇒ 落地成功；trailer 有 `Gates-on: cloud@fake-cloud`，`last.json` 有 host。"""
    repo = _cloud_repo(tmp_path)
    payload = {"rev": _head(repo)[:12], "ok": True, "host": "fake-cloud",
               "gates": [{"name": "pytest"}, {"name": "ruff"}], "not_run": []}
    fake = _fake(tmp_path, payload)
    done = _wand_mod._wand(repo, "--no-review", tree=".pen", env=_env(fake))
    out = _wand_mod._out(done)
    assert done.returncode == 0, out
    assert "云机门禁绿" in out, out
    body = _wand_mod._git(repo, "log", "-1", "--format=%B").stdout
    assert "Gates-on: cloud@fake-cloud" in body, body
    last = json.loads(_wand_mod._git(repo, "show", "HEAD:gates/last.json").stdout)
    assert last.get("host") == "fake-cloud", last
    assert gp.check_gates_on_trailer(body, expect="Gates-on: cloud@fake-cloud") == ""
    # ★ 本机那一支的门禁头（`=== ④ 锁（段 …）`）不许出现 —— 云那趟只在本机编排。
    #   （`gate_ran.marker` 会被 ⑤ 封存的 `--seal` 写一次，那**不是**跑门禁，故不拿它判。）
    assert "=== ④ 锁（段" not in out, out
    assert "stub-run_gates" in out, "⑤ 封存仍要在本机走一趟（只更新 tree，不跑门）"


# ---------------------------------------------------------------- ⑤ 五条回传校验
def _ok_payload(**over: object) -> dict:
    data = {"rev": "abc1234", "ok": True, "host": "fake-cloud",
            "gates": [{"name": "pytest"}, {"name": "ruff"}], "not_run": []}
    data.update(over)
    return data


def test_missing_host_in_last_json_is_rejected() -> None:
    """缺 `host` ⇒ 拒（去掉这条检查，本钉子红）。"""
    payload = _ok_payload()
    payload.pop("host")
    problems = gp.validate_cloud_return(
        payload, expected_rev="abc1234", expected_doors=["pytest", "ruff"],
        pytest_passed=100, pytest_total=100, workspace_clean=True)
    assert any(p.startswith("③") for p in problems), problems


def test_rev_mismatch_is_rejected() -> None:
    """`rev` 不是父提交 ⇒ 拒。"""
    problems = gp.validate_cloud_return(
        _ok_payload(rev="0000000"), expected_rev="abc1234",
        expected_doors=["pytest", "ruff"], pytest_passed=100, pytest_total=100,
        workspace_clean=True)
    assert any(p.startswith("①") for p in problems), problems


def test_pytest_below_95_percent_is_rejected() -> None:
    """`100 passed` 但全量 3303 ⇒ 拒（子集冒充全量）。"""
    problems = gp.validate_cloud_return(
        _ok_payload(), expected_rev="abc1234", expected_doors=["pytest", "ruff"],
        pytest_passed=100, pytest_total=3303, workspace_clean=True)
    assert any(p.startswith("④") for p in problems), problems


def test_dirty_cloud_workspace_is_rejected() -> None:
    """云机工作区不干净 ⇒ 拒。"""
    problems = gp.validate_cloud_return(
        _ok_payload(), expected_rev="abc1234", expected_doors=["pytest", "ruff"],
        pytest_passed=100, pytest_total=100, workspace_clean=False)
    assert any(p.startswith("⑤") for p in problems), problems


# ---------------------------------------------------------------- ⑥ Gates-on 一致
def test_gates_on_line_matches_where_it_ran() -> None:
    """`cloud` 必须带 `@host`；`local` 必须是裸 local；对不上要说话。"""
    assert gp.gates_on_line(gate_on="cloud", host="c1") == "Gates-on: cloud@c1"
    assert gp.gates_on_line(gate_on="local") == "Gates-on: local"
    assert gp.check_gates_on_trailer("x\nGates-on: local\n", expect="Gates-on: local") == ""
    assert "不符" in gp.check_gates_on_trailer(
        "Gates-on: local\n", expect="Gates-on: cloud@c1")


# ---------------------------------------------------------------- ⑦ local 仍是老路
def test_explicit_local_runs_local_gate(tmp_path: Path) -> None:
    """`--gate-on local` ⇒ 走今天的本机路（门禁桩被真跑到，trailer 写裸 `local`）。"""
    repo = _cloud_repo(tmp_path)
    done = _wand_mod._wand(repo, "--no-review", "--gate-on", "local", tree=".pen",
                           env=_env(host=""))
    out = _wand_mod._out(done)
    assert done.returncode == 0, out
    assert (repo / ".pen" / "gate_ran.marker").exists(), "local 那支必须本机跑门禁"
    body = _wand_mod._git(repo, "log", "-1", "--format=%B").stdout
    assert "Gates-on: local" in body, body
