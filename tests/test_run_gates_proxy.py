"""钉子：把代理指标过期对账接进门禁（卡 208 · T-G317）—— 先红后绿。

## 为什么有这张测试

卡 202（`fa2f2e8`）交了**零件**：`docs/proxy-map.toml`（5 条代理指标登记表）+
`tools/proxy_audit.py --check`（过期退非零），但**没接门禁** ⇒ 那 5 条代理指标
**没有任何东西在定期对账** ⇒ 「防近视」只是话。卡 208 把它接进 `scripts/run_gates.py` 的
`build_jobs()` / `FAST`。这张测试钉的是**接线真的通**（本卡 §3）：

  - `proxy` 在**全量门清单**里，也在 **`FAST`** 里；
  - 门里调的就是 `tools/proxy_audit.py --check` **本身**（判据**只许一份真源** —— 不在
    `run_gates.py` 里重写「过期怎么算」）；
  - 三态：**绿**（真登记表） / **改成过期 ⇒ 红** / **删表·坏 TOML ⇒ 红并点名**。

## 怎么验（不跑重活、不改真登记表）

把 `run_gates.py` 当模块 import 取**门表**（现读）；门的**命令**直接 `subprocess.run` 跑
（就是门禁跑的那一条）；**过期用 temp 登记表**（`--map`）—— 真 `docs/proxy-map.toml`
**一个字节不改**（`proxy_audit.py` 是只读的）。

## 边界（如实写，未覆盖）

端到端（真跑 `run_gates.py main()` 把这道门的 `exit_code` 记进 `gates/last.json`）本文件
**没跑**（那是重活，卡里也不许）。这里钉的是「**门命令的退出码**」—— 那正是
`run_gates.py` 判红 / 判绿的依据（退出码非零 ⇒ 该门红）。
"""

from __future__ import annotations

import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tools"))

import proxy_audit as pa  # noqa: E402 —— 需要先用 sys.path 把 tools/ 挂上
import run_gates as rg  # noqa: E402 —— 需要先用 sys.path 把 scripts/ 挂上
from pool.no_window import NO_WINDOW  # noqa: E402 —— 子进程不许弹窗（卡 148）

REAL_MAP = ROOT / "docs" / "proxy-map.toml"
#: `proxy` 门**应有的**命令（判据真源 = `tools/proxy_audit.py --check` 本身）。
PROXY_CMD = [sys.executable, "-X", "utf8", "tools/proxy_audit.py", "--check"]


def _gate_command() -> list[str]:
    """从门表现读 `proxy` 门的命令（现读，不写死）。"""
    jobs = dict(rg.build_jobs(False, False))
    assert "proxy" in jobs, "全量门清单里没有 `proxy` 门"
    return list(jobs["proxy"])


def _run(cmd: list[str], *extra: str) -> tuple[int, str]:
    """跑一条门命令（带 NO_WINDOW），返回 `(退出码, 合并输出)`。"""
    proc = subprocess.run(
        [*cmd, *extra],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8", errors="replace",
        **NO_WINDOW,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _map_with_first_entry_dated(tmp_path: Path, when: str) -> Path:
    """把**真登记表**的第一条 `last_verified` 换成 `when`，落成 temp 登记表（真表不动）。"""
    text = REAL_MAP.read_text(encoding="utf-8")
    marker = 'last_verified = "'
    i = text.index(marker) + len(marker)
    j = text.index('"', i)
    p = tmp_path / "proxy-map.toml"
    p.write_text(text[:i] + when + text[j:], encoding="utf-8")
    return p


# ------------------------------------------------------------------ 接线：在不在门表里

def test_proxy_gate_is_in_full_list_and_fast() -> None:
    """★ `proxy` 在**全量门清单**里、也在 **`FAST`** 里，且 `--fast` 那一趟真带上它。"""
    names = [n for n, _ in rg.build_jobs(False, False)]
    assert "proxy" in names, f"全量门清单里没有 proxy：{names}"
    assert "proxy" in rg.FAST, f"FAST 里没有 proxy：{rg.FAST}"
    assert "proxy" in [n for n, _ in rg.build_jobs(False, True)], "--fast 那一趟没带上 proxy"


def test_gate_command_calls_proxy_audit_check_itself() -> None:
    """★ 判据**只许一份真源**：门里调的就是 `tools/proxy_audit.py --check` 本身
    （不在 `run_gates.py` 里重写「过期怎么算」）。"""
    assert _gate_command() == PROXY_CMD


# ------------------------------------------------------------------ 绿：真登记表新鲜

def test_real_map_makes_the_gate_green() -> None:
    """★ 绿：门禁跑的那条命令打在**真登记表**上 ⇒ 退 0（5 条都新鲜）。"""
    rc, out = _run(_gate_command())
    assert rc == 0, out
    assert "[OK  ]" in out and "全新鲜" in out, out


# ------------------------------------------------------------------ 红：过期 ⇒ 红（改回 ⇒ 绿）

def test_shifted_date_goes_red_then_back_to_green(tmp_path: Path) -> None:
    """★ 三态核心（先红后绿）：第一条 `last_verified` 改成**很久以前** ⇒ 门**必须红**并点名；
    改回**今天** ⇒ 门**必须绿**（在同一 temp 登记表上一红一绿，证明判据**会咬**、不是恒真）。"""
    stale_id = pa.load_map(REAL_MAP)[0].id
    gate = _gate_command()

    red_map = _map_with_first_entry_dated(tmp_path, "2000-01-01")
    rc, out = _run(gate, "--map", str(red_map))
    assert rc != 0, f"改成过期了门却不红：\n{out}"
    assert stale_id in out, f"红了却没点名过期的那条 id={stale_id}：\n{out}"
    assert "过期" in out, out

    green_map = _map_with_first_entry_dated(tmp_path, date.today().isoformat())
    rc2, out2 = _run(gate, "--map", str(green_map))
    assert rc2 == 0, f"改回新鲜后门却不绿：\n{out2}"
    assert "[OK  ]" in out2, out2


def test_days_zero_also_turns_the_gate_red() -> None:
    """★ 卡 §3 的「（或 `--days 0`）」：零容忍阈值下，真登记表（全部昨天验证）也必须红。"""
    rc, out = _run(_gate_command(), "--days", "0")
    assert rc != 0, out
    assert "过期" in out, out


# ------------------------------------------------------------------ 反例：删表 / 坏 TOML ⇒ 红并点名

def test_missing_map_goes_red_and_names_the_path(tmp_path: Path) -> None:
    """★ 反例①：登记表**删掉**（读不到）⇒ 门**必须红并点名**那个路径
    （`proxy_audit.py` 的口径：读不到就当不过，退 2）。"""
    missing = tmp_path / "nope.toml"
    rc, out = _run(_gate_command(), "--map", str(missing))
    assert rc != 0, out
    assert "读不到" in out and "nope.toml" in out, out


def test_broken_toml_goes_red_and_names_the_file(tmp_path: Path) -> None:
    """★ 反例②：登记表写成**坏 TOML** ⇒ 门**必须红并点名**（退 2，报「TOML 坏了」）。"""
    bad = tmp_path / "proxy-map.toml"
    bad.write_text('[[proxy]]\nid = "broken\n', encoding="utf-8")
    rc, out = _run(_gate_command(), "--map", str(bad))
    assert rc != 0, out
    assert "TOML 坏了" in out and "proxy-map.toml" in out, out
