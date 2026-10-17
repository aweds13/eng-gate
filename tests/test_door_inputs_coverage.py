"""卡 161 · 门的输入面与跑法：补全 + 跑法落盘 + PYTHONPATH 钉子 + gitignored 判据。

每条**先红后绿**（卡 §判据与钉子）：
  - 改 `render_signatures.json` 一字节 ⇒ 复用哈希必变（item 1）；
  - `gates/last.json` 缺 `workers`/`pytest_mode` ⇒ 本卡没做到位（item 2，这里钉字段在 payload 里）；
  - `tree_pythonpath` 把本树 src 放 PYTHONPATH 首位（item 3）；
  - 门表里塞一个未 git 跟踪的字面路径 ⇒ `door_input_violations` 咬（item 4）。

边界：不跑任何门（只 `import run_gates` 当模块，造临时根 / 桩表）。
真机全量由主控收口时跑。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import run_gates as rg  # noqa: E402


def _seed(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------- item 1：补全 DOOR_INPUTS


def test_render_signatures_json_is_a_render_input() -> None:
    """INV-24：`render` 真读 `tools/render_signatures.json` ⇒ 必须在门的输入表里。"""
    assert "tools/render_signatures.json" in rg.DOOR_INPUTS["render"]
    # REUSE_INPUTS 从 DOOR_INPUTS 派生（同一条）—— 不许写两份
    assert "tools/render_signatures.json" in rg.REUSE_INPUTS["render"]


def test_phone_check_mjs_is_a_web_live_input() -> None:
    """INV-24：`web_live` 真跑 `tools/phone_check.mjs` ⇒ 必须在门的输入表里。"""
    assert "tools/phone_check.mjs" in rg.DOOR_INPUTS["web_live"]
    assert "tools/phone_check.mjs" in rg.REUSE_INPUTS["web_live"]


def test_reuse_inputs_derives_from_door_inputs_one_source() -> None:
    """★ 输入表只有一份真源：`REUSE_INPUTS` 必须逐条等于 `DOOR_INPUTS` 的对应条目。"""
    for name in rg.REUSABLE:
        assert rg.REUSE_INPUTS[name] == rg.DOOR_INPUTS[name]


def test_changing_render_signatures_breaks_reuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """★ 先红后绿：改 `tools/render_signatures.json` 一字节 ⇒ `input_hash` 必变（不复用）。

    没补进输入表时，改这个文件哈希不变 ⇒ 命中复用 ⇒ 假绿（INV-24 的病）。
    补进之后，它和 `src/**` 一样会让哈希随内容变。
    """
    monkeypatch.setattr(rg, "ROOT", tmp_path)
    patterns = rg.REUSE_INPUTS["render"]
    _seed(tmp_path, "tools/render_signatures.json", '{"today": {"must": ["A"]}}')
    before = rg.input_hash(patterns)
    _seed(tmp_path, "tools/render_signatures.json", '{"today": {"must": ["B"]}}')  # 改一字节
    assert rg.input_hash(patterns) != before, (
        "改 render_signatures.json 哈希没变 ⇒ 没被算进输入")


def test_changing_phone_check_breaks_web_live_reuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """★ 同上：改 `tools/phone_check.mjs` 一字节 ⇒ `web_live` 哈希必变。"""
    monkeypatch.setattr(rg, "ROOT", tmp_path)
    patterns = rg.REUSE_INPUTS["web_live"]
    _seed(tmp_path, "tools/phone_check.mjs", "/* v1 */\n")
    before = rg.input_hash(patterns)
    _seed(tmp_path, "tools/phone_check.mjs", "/* v2 */\n")
    assert rg.input_hash(patterns) != before, "改 phone_check.mjs 哈希没变 ⇒ 没被算进输入"


# ---------------------------------------------------------------- item 2：跑法落盘


def test_pytest_workers_is_the_single_read_point(monkeypatch: pytest.MonkeyPatch) -> None:
    """★ 不许把 worker 数写成第二份口径：`pytest_workers()` 是唯一读取处。"""
    # ★ 卡 A266：默认（不设环境变量）**不再等于** `min(4, cpu)` —— 改成**按可用内存自适应**
    #   （可用 < 2.5 GB ⇒ 1、< 4 GB ⇒ 2、否则 `min(4, cpu)`）。断言强度一个字不动：
    #   三种取值都落在 1 ≤ w ≤ max(4, cpu)。
    monkeypatch.delenv("TF_PYTEST_WORKERS", raising=False)
    w = rg.pytest_workers()
    assert w >= 1
    assert w <= max(4, os.cpu_count() or 1)


def test_pytest_mode_and_workers_are_recorded_in_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """★ INV-24：`gates/last.json` 必须记 `workers` 与 `pytest_mode`。

    证字段进了 payload：构造 payload 的代码路径引用了 `pytest_workers()` 与 `mode`。
    这里钉死「main 的源码里出现了这两个键」—— 改没了就红。
    """
    src = (ROOT / "scripts" / "run_gates.py").read_text(encoding="utf-8")
    assert '"workers": pytest_workers()' in src, "payload 没记 workers（卡 161 §2）"
    assert '"pytest_mode": mode' in src, "payload 没记 pytest_mode（卡 161 §2）"
    assert '"slow_doors"' in src, "payload 没记慢门清单（卡 161 §2 验收）"


def test_door_budget_reads_env_and_zero_disables(monkeypatch: pytest.MonkeyPatch) -> None:
    """慢门软预算：不设 = 600；设了用该值；`0` = 关（None）。"""
    monkeypatch.delenv("TF_GATE_DOOR_BUDGET", raising=False)
    assert rg.door_budget() == 600.0
    monkeypatch.setenv("TF_GATE_DOOR_BUDGET", "120")
    assert rg.door_budget() == 120.0
    monkeypatch.setenv("TF_GATE_DOOR_BUDGET", "0")
    assert rg.door_budget() is None


# ---------------------------------------------------------------- item 3：tree_pythonpath 钉子


def test_tree_pythonpath_puts_tree_src_first() -> None:
    """★ INV-25：`run_gates` 起的子进程 PYTHONPATH 首位必须是本树 src。

    没这层 ⇒ worktree 里门禁验到主树 src ⇒ 同源黄金一比必绿（假绿）。
    """
    e = rg.tree_pythonpath({})
    first = e["PYTHONPATH"].split(os.pathsep)[0]
    assert first == str(rg.ROOT / "src"), f"PYTHONPATH 首位不是本树 src，是 {first!r}"


def test_tree_pythonpath_prepends_even_when_pythonpath_set() -> None:
    """已有 PYTHONPATH 时，本树 src 仍要在首位（不追加到后面）。"""
    e = rg.tree_pythonpath({"PYTHONPATH": "/some/other/path"})
    parts = e["PYTHONPATH"].split(os.pathsep)
    assert parts[0] == str(rg.ROOT / "src")
    assert "/some/other/path" in parts  # 原有的不丢


def test_env_uses_tree_pythonpath() -> None:
    """`env()`（给子进程构造环境）走的就是 `tree_pythonpath`。"""
    e = rg.env()
    assert e["PYTHONPATH"].split(os.pathsep)[0] == str(rg.ROOT / "src")


# ---------------------------------------------------------------- item 4：gitignored / 未 pin 判据


def test_real_door_inputs_are_all_tracked() -> None:
    """★ 绿：真门表的字面路径全部被 git 跟踪（换台机器也都在）。"""
    assert rg.door_input_violations() == []


def test_door_input_violations_catches_untracked_literal() -> None:
    """★ 红：门表里塞一个未 git 跟踪的字面路径 ⇒ 必须咬。

    现场造一个不存在的字面路径（既未跟踪也未 gitignore）⇒ git ls-files 查不到 ⇒ 违规。
    """
    fake_table = {"fake_door": ("src/**", "tools/this_does_not_exist_xyz.json")}
    violations = rg.door_input_violations(fake_table)
    assert "tools/this_does_not_exist_xyz.json" in violations


def test_door_input_violations_ignores_glob_patterns() -> None:
    """glob（`src/**`）不是字面路径 —— 由 `--affected` 与复用哈希各自把关，不在此列。"""
    fake_table = {"fake_door": ("src/**", "docs/contracts/**")}
    assert rg.door_input_violations(fake_table) == []
