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

import ast
import subprocess
import sys
from datetime import date, timedelta
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


def _map_with_all_entries_dated(tmp_path: Path, when: str) -> Path:
    """把**真登记表**的**每一条** `last_verified` 都换成 `when`，落成 temp 登记表（真表不动）。

    ★ 卡 E113（`T-AG622`）：`--days 0` 那条钉子要用「昨天验证过」的表 —— 拿真表跑，
      日期一改成今天它必红（`age = 0`、`overdue = 0`、`expired = False`），那不是门坏了，
      是钉子把「真表恰好比今天旧」当成了前提。所以这里**自造**一份表。
    """
    text = REAL_MAP.read_text(encoding="utf-8")
    marker = 'last_verified = "'
    parts = text.split(marker)
    assert len(parts) == 6, f"真登记表应有 5 条 last_verified，实际 {len(parts) - 1} 条"
    out = parts[0]
    for chunk in parts[1:]:
        j = chunk.index('"')
        out += marker + when + chunk[j:]
    p = tmp_path / "proxy-map-all.toml"
    p.write_text(out, encoding="utf-8")
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


def test_days_zero_also_turns_the_gate_red(tmp_path: Path) -> None:
    """★ 卡 §3 的「（或 `--days 0`）」：零容忍阈值下，全部昨天验证的登记表也必须红。

    ★ 卡 E113（`T-AG622`）修正：原版拿**真登记表**跑 `--days 0`，却把「真表恰好比今天旧」
      当成了前提 —— 重验把 `last_verified` 改成今天之后，`age = 0` ⇒ `expired = False` ⇒ 门变绿，
      这条钉子自己红了（红的是钉子，不是门）。现在自造一份「全部昨天验证」的表，前提写在夹具里。

    ★ 卡 E126（`T-AG635`）删掉后半截：E113 还留着 `rc2 == 0` 打**真登记表**跑 `--days 0`
      的断言，而那一条只在 `last_verified == 今天` 当天成立 —— 次日 00:00 起必红
      （实测 2026-11-17：五条全「过期 1 天」，`assert 1 == 0`）。它挡的不是一张卡：
      每张卡落地都要烧一次全量 pytest 再红在这条与本卡无关的钉子上。
      真表新鲜由 `test_real_map_makes_the_gate_green`（默认 30 天）负责；
      真表的**零容忍**结论随运行日变化，不是可断言的常量 ⇒ 后半截整段删除，不改成 `--days 30`。
    """
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    stale = _map_with_all_entries_dated(tmp_path, yesterday)
    rc, out = _run(_gate_command(), "--days", "0", "--map", str(stale))
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

# ------------------------------------------ 机器钉子：不许再拿真表跑零容忍（卡 E126 · T-AG635）

def test_no_zero_tolerance_call_against_the_real_map() -> None:
    """★ 零容忍阈值（`--days 0`）只许打在**自造**登记表上（同一次调用带 `--map`）。

    真表的 `last_verified` 是日期，零容忍的结论**随运行日变化** —— 今天绿、明天红。
    卡 E113 留下的那半截就是这么长出来的：它只在验证当天成立，却写成永久断言，
    结果次日 00:00 起每张卡落地都烧一次全量 pytest 再红在这条与本卡无关的钉子上
    （现场 `gates/diag/land-E118.log`）。这里扫**全仓** `tests/**/*.py`（现读，不写死清单）：
    同一个调用里同时出现字面量 `--days` 与 `0`、且**不含** `--map` ⇒ 红并点名 文件:行号。
    """
    offenders: list[str] = []
    for path in sorted((ROOT / "tests").rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError as exc:  # 语法坏的文件本来就该由别的门报，这里不吞
            raise AssertionError(f"{path.relative_to(ROOT)} 解析不了：{exc}") from exc
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            vals: set[str] = set()
            for arg in [*node.args, *(kw.value for kw in node.keywords)]:
                for sub in ast.walk(arg):
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                        vals.add(sub.value)
            if "--days" in vals and "0" in vals and "--map" not in vals:
                rel = path.relative_to(ROOT)
                offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, (
        "零容忍（--days 0）打在了**没有 --map** 的调用上 ⇒ 那是拿真登记表断言「今天」：\n  "
        + "\n  ".join(offenders)
        + "\n修法：自造一份登记表并带 --map（日期由夹具控制），真表新鲜交给默认 30 天那条钉子。"
    )
