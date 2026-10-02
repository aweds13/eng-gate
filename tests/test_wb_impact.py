r"""影响面反推 `tools/wb_impact.py` 的钉子（卡 142 · T-G241）。

## 为什么有它

今晚连续四次「写卡人漏项」（卡 121 / 125 / 120 / 140），共同形态是
**「改了某文件 ⇒ 还有哪些文件被连带」靠手打、不靠机器算**。本卡把这件事变成一条命令
（`tools/wb_impact.py`）。下面五条钉子钉住它**真会咬**：门反推 / 测试钉住 / `--check` 咬人 /
不误伤 / **不复刻第二份门表**。

## 五条钉子（每条都配反例）

| # | 钉什么 |
|---|---|
| ① | 给 `tools/pool/task.py` ⇒ 含"无输入映射"的门 + 被它命中的门（宁多勿漏） |
| ② | 同一次反推**必须**列出 `tests/test_pool_task.py`（它 import `pool.task`） |
| ③ | `--declared tools/a.py` 而改动面含 `tools/b.py` ⇒ **非零退出并点名** |
| ④ | 改动面 ⊆ 声明域 ⇒ **退 0**（不误伤） |
| ⑤ | ★ 门表**取**自 `scripts/run_gates.py`：桩掉它的 `DOOR_INPUTS` ⇒ 输出跟着变（不硬编码一张表） |

## 怎么验（把工具当模块 import，**不跑任何门**）

`plan_gates` / `pinned_tests` / `check_domain` 都是**纯函数**（+ 只读 `tests/**`）：喂路径直接判
"选了哪几道门、列了哪些测试、退几"。`main()` 只跑"读 `tests/**` + 打印"，**不起服务、不跑门禁**。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "scripts"))

import run_gates as rg  # noqa: E402 —— 门 × 输入表真源（测试要桩它）
import wb_impact as wi  # noqa: E402 —— tools/ 已在 sys.path 上

# ------------------------------------------------------------------ ① 门反推（宁多勿漏）


def test_gates_reverse_for_tools_file() -> None:
    """★ 判据①：给 `tools/pool/task.py` ⇒ 含所有"无输入映射"的门 + 所有"输入被它命中"的门。"""
    path = "tools/pool/task.py"
    doors = wi.all_doors()
    plan = wi.plan_gates([path])

    # (a) 表里没有输入映射的门 ⇒ **永远跑**（一个不许少）
    no_input = [d for d in doors if d not in rg.DOOR_INPUTS]
    assert no_input, "真表里应当有无输入映射的门（pytest / ruff / mypy …）"
    for d in no_input:
        assert d in plan.ran, f"{d} 无输入映射，必须永远跑"

    # (b) 输入会被这条路径命中的门（真表下为空，但这条性质必须成立）
    expected_hit = [
        d for d, pats in rg.DOOR_INPUTS.items()
        if any(rg.path_matches_glob(path, p) for p in pats)
    ]
    for d in expected_hit:
        assert d in plan.ran, f"{d} 的输入被 {path} 命中，必须跑"

    # (c) 宁多勿漏：`tools/pool/task.py` 命不中任何门 ⇒ 落**全量**
    assert plan.full_fallback is True, plan.note
    assert set(plan.ran) == set(doors)
    print(f"[门集合] 无输入映射 {len(plan.always)} 道：{'、'.join(plan.always)}")
    print(f"[门集合] 输入命中 {len(plan.matched)} 道：{plan.matched}")
    print(f"[门集合] 要跑 {len(plan.ran)} 道：{'、'.join(plan.ran)}")


# ------------------------------------------------------------------ ② 测试钉住


def test_pins_pool_task_test() -> None:
    """★ 判据②：给 `tools/pool/task.py` ⇒ **必须**列出 `tests/test_pool_task.py`。"""
    pins = wi.pinned_tests(["tools/pool/task.py"])
    hit = next((p for p in pins if p.test == "tests/test_pool_task.py"), None)
    assert hit is not None, f"没列出 tests/test_pool_task.py：{[p.test for p in pins]}"
    # 它是靠"模块导入名 pool.task"命中的（`from pool import task` / `pool.task`）
    assert "module" in hit.forms, hit.forms
    assert hit.strength == "strong"

    # 反例：换个**没人提过**的名字 ⇒ 不该列出来（名字现拼，免得本文件自己提到它）
    ghost_path = "/".join(["tools", "zz" + "z_no_such" + "_thing.py"])
    assert wi.pinned_tests([ghost_path]) == (), "幽灵文件不该命中"

    line = next(
        ln for ln in wi.render(wi.analyze(["tools/pool/task.py"])).splitlines()
        if "tests/test_pool_task.py" in ln
    )
    print(f"[原样行] {line}")


# ------------------------------------------------------------------ ③ --check 咬人


def test_check_bites_when_outside_domain(capsys: pytest.CaptureFixture[str]) -> None:
    """★ 判据③：改动面含域外文件 ⇒ 非零退出并**点名** `tools/b.py`。"""
    rc = wi.main(["--files", "tools/b.py", "--declared", "tools/a.py"])
    out = capsys.readouterr().out
    assert rc != 0, "域外改动必须非零退出"
    assert "tools/b.py" in out, out


# ------------------------------------------------------------------ ④ 不误伤


def test_check_passes_when_subset(capsys: pytest.CaptureFixture[str]) -> None:
    """★ 判据④：改动面 ⊆ 声明域 ⇒ **退 0**。"""
    rc = wi.main(["--files", "tools/b.py", "--declared", "tools/**"])
    out = capsys.readouterr().out
    assert rc == 0, out
    # 精确域（非 glob）也要放行
    assert wi.main(["--files", "tools/b.py", "--declared", "tools/b.py"]) == 0


# ------------------------------------------------------------------ ⑤ 不复刻第二份真源


def test_gate_table_comes_from_run_gates(monkeypatch: pytest.MonkeyPatch) -> None:
    """★ 判据⑤：门表**取**自 `run_gates.DOOR_INPUTS` —— 桩掉它，输出跟着变。"""
    # 本工具不许自己硬编码一张门表
    assert not hasattr(wi, "DOOR_INPUTS"), "wb_impact 不该持有第二份门表"

    path = "tools/wb_impact.py"
    real = wi.plan_gates([path])
    assert "pytest" in real.always, "真表里 pytest 无输入映射 ⇒ 必跑"

    stub = dict(rg.DOOR_INPUTS)
    stub["pytest"] = ("tools/**",)          # 给 pytest 安一条"输入含 tools/**"
    monkeypatch.setattr(rg, "DOOR_INPUTS", stub)

    changed = wi.plan_gates([path])
    assert "pytest" not in changed.always, "桩表里 pytest 有输入映射了 ⇒ 不该再算'永远跑'"
    assert "pytest" in changed.matched, "tools/wb_impact.py 命中 tools/** ⇒ pytest 该被输入命中"
    assert "pytest" in changed.ran
