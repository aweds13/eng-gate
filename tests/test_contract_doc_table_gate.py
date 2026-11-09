"""契约对账表那道门（卡 E104 · T-AG613）：0.2 秒的判据必须在门表里，且真的会咬。

## 为什么有它

`tools/contract_audit.py --check-doc` 是 E101（`a94af526`）给 `复盘/契约-判据对账.md`
装的逐格尺子（源行号 / 原句子串 / 判据标签 / 段标题条数），0.15 s 跑完、不跑判据。
在卡 E104 之前它**不在任何一档门禁里**：`grep -rn contract_audit gates/defs/ scripts/run_gates.py`
0 命中。后果是「只改那张表的卡，落地时 pytest 一条都不跑」——
`domains.required_profiles(['复盘/契约-判据对账.md'])` 只给 `audit` 档，
而那五道门没有一道读那张表。

## 钉什么（三条）

| # | 钉子 | 坏掉会红在哪 |
|---|---|---|
| ① | 门表那一条是 `contract_audit.py --check-doc`；audit 档、非 fast | 删门 / 改开关 / 混进 fast |
| ② | 跑**注册的那条 argv**，真表现在必须 rc=0 | 表漂了没人当场拦 |
| ③ | 同一条 argv 喂一张段标题写错的表 ⇒ rc=1 且**点名**条数 | 门只打印不拦（假门） |
| ④ | 自证台账那行指向的反向用例**真存在**（同一把尺子 `defines_case`） | 台账变成空头支票 |

★ 判据 ②③ 跑的是**门表里那一条命令**，不是「另找一个工具的另一套开关」——
  否则门表可以换成一份坏的，本文件照样绿。
★ 门数不写死：本文件只读 `contract.GATES` / `GATE_PROFILES`，不数「现在几道门」。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[1]
for _extra in ("scripts", "tools", "src"):
    _p = str(ROOT / _extra)
    if _p not in sys.path:
        sys.path.insert(0, _p)

import run_gates as rg  # noqa: E402
import wb_invariants as wbi  # noqa: E402
from pool.no_window import NO_WINDOW  # noqa: E402

from gates.defs import contract  # noqa: E402

DOOR = "contract_doc_table"
LEDGER = ROOT / "gates" / "gate-selfproof.toml"
TABLE = ROOT / "复盘" / "契约-判据对账.md"


def _registered_gate() -> list[str]:
    """门表里那一条的 argv（**逐字**，不从别处另抄一份）。"""
    hits = [cmd for name, cmd in contract.GATES if str(name) == DOOR]
    assert len(hits) == 1, f"契约门表里 {DOOR} 应当恰有一条，实际 {len(hits)} 条"
    return [str(x) for x in hits[0]]


def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        **NO_WINDOW,
    )


# ---------------------------------------------------------------- ① 在门表里
def test_contract_doc_table_is_registered_in_the_audit_profile() -> None:
    """门表里逐字是 `tools/contract_audit.py --check-doc`，进 audit 档、不进 fast 档。"""
    argv = _registered_gate()
    tail = [x.replace("\\", "/") for x in argv]
    assert "tools/contract_audit.py" in tail, f"门表里那一条跑的不是那把尺子：{argv}"
    assert tail[-1] == "--check-doc", f"必须只核表、不跑判据（末位应是 --check-doc）：{argv}"
    assert DOOR in rg.GATE_PROFILES["audit"], f"{DOOR} 必须进 audit 档：{rg.GATE_PROFILES['audit']}"
    assert DOOR not in rg.FAST, f"{DOOR} 不进 fast 档（它只在改那张表时才可能漂）：{rg.FAST}"
    jobs = dict(rg.build_jobs(quick=False, fast=False))
    assert DOOR in jobs, f"真门表里没有 {DOOR}（build_jobs 装配没跟上）"
    got = [str(x) for x in jobs[DOOR]]
    assert got == argv, f"门表两条路径给了两份 argv：{got} != {argv}"


# ---------------------------------------------------------------- ② 真表绿
def test_the_registered_command_is_green_on_the_real_table() -> None:
    """跑门表里那一条：真表现在必须逐格对上（表漂 ⇒ 这道门当场红）。"""
    assert TABLE.is_file(), f"对账表不在：{TABLE}"
    proc = _run(_registered_gate())
    assert proc.returncode == 0, (
        f"门表里那条命令在真表上不绿（rc={proc.returncode}）—— 表漂了，改表或改 CONTRACTS：\n"
        + proc.stdout
        + proc.stderr
    )
    assert "[OK ]" in proc.stdout, proc.stdout


# ---------------------------------------------------------------- ③ 坏表会咬
def test_the_registered_command_bites_on_a_drifted_table(tmp_path: Path) -> None:
    """同一条 argv 喂一张段标题写错的表 ⇒ rc=1，并点名「写 N 条 / 实际 M 条」。"""
    text = TABLE.read_text(encoding="utf-8")
    stale = text.replace("### 有判据的（10 条", "### 有判据的（11 条")
    assert stale != text, "真表的「有判据的（10 条」这半句变了 ⇒ 这条钉子得跟着改"
    bad = tmp_path / "drifted.md"
    bad.write_text(stale, encoding="utf-8", newline="")
    proc = _run([*_registered_gate(), "--doc", str(bad)])
    assert proc.returncode == 1, (
        f"坏表居然通过了（rc={proc.returncode}）—— 这道门只打印不拦：\n" + proc.stdout + proc.stderr
    )
    assert "段标题写 11 条" in proc.stdout, (
        "红要红得能读：必须点名写错的条数，实际输出：\n" + proc.stdout
    )


# ---------------------------------------------------------------- ④ 自证台账不空头
def test_the_selfproof_row_points_at_a_case_that_exists() -> None:
    """台账那一行必须指名到**真存在**的用例（同一把尺子 `wb_invariants.defines_case`）。"""
    rows = [dict(r) for r in tomllib.loads(LEDGER.read_text(encoding="utf-8"))["gate"]]
    hits = [r for r in rows if str(r.get("name")) == DOOR]
    assert len(hits) == 1, f"自证台账里 {DOOR} 应当恰有一行，实际 {len(hits)} 行"
    row = hits[0]
    assert str(row.get("since", "")).strip(), f"{DOOR}: since 是空的（日期是复核锚点）"
    case = str(row.get("reverse_case", ""))
    rel, _sep, name = case.partition("::")
    assert rel.startswith("tests/") and name, (
        f"{DOOR}: reverse_case 得写成 tests/<文件>::<用例名>，实际 {case!r}"
    )
    path = ROOT / rel
    assert path.is_file(), f"{DOOR}: 反向用例的文件不在：{rel}"
    assert wbi.defines_case(path.read_text(encoding="utf-8"), wbi.case_name(name)), (
        f"{DOOR}: 反向用例 {case!r} 在 {rel} 里找不到 —— 台账成了空头支票"
    )
