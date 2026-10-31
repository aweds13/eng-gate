r"""CI 项目书的计数钉子（卡 F12 · `T-AG560`）：数字要么现读真源，要么是带日期的快照。

钉的是「同一份文档不许自相矛盾，也不许拿三天前的数当现在」：

| # | 钉子 | 坏掉会红在哪 |
|---|---|---|
| ① | README 里「全量 N 道」的 N == 现读 `build_jobs` 的长度 | 门表加了一道而文档还说旧数 ⇒ 红 |
| ② | §2 表逐行点名的门数 + 「其余 N 道」= 现读门数 | 加一道门、「其余」没跟着减 ⇒ 红 |
| ③ | `2955` 与「19 道」在两份 CI 文档里零命中 | 塞回去 ⇒ 红 |
| ④ | `pytest` 收集条数两份文档同一个数、且带探针 + 日期 | 两处不一致 / 只有数字没探针 ⇒ 红 |
| ⑤ | README 仍是纯 CRLF、行数没跑飞（卡规格判据 5） | 行尾被编辑器改成裸 LF ⇒ 红 |

★ **门数不写死**：`live_door_count()` 现读 `build_jobs`，门表加一道门本文件**一行都不用改**；
  会红的只有「文档说 19 / 21 / 23 道，而门表是别的数」。体例照 `tests/test_ci_docs.py`
  的 `door_table_names()`（写死的门数是会漂的第二真源，卡 208 §2）。
★ **条数为什么是快照而不是现读**：`pytest --collect-only` 要 5 s 上下，且在 xdist 的 4 个
  worker 里会各跑一次；更要紧的是**每加一个用例它都变** —— 那样一来「别人加测试」就会让
  本文件红，钉子变成噪音。卡规格判据 2 明说允许「带日期的快照 + 能重跑的探针」，所以这里
  只钉两件事：**两处同一个数**、**同一行有那条探针命令**（谁都可以立刻重跑对账）。
★ 反向验证：每条钉子都配一条反向用例，用**同一个检查函数**把数字改坏，看它咬不咬
  （另有一份全流程的反向脚本 `gates/diag/_rev_F12.py`，gitignored，不入库）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CI_DOCS = ROOT / "docs" / "subsystems" / "ci"
README = CI_DOCS / "README.md"
CHECKLIST = CI_DOCS / "事后判据清单.md"
SCRIPTS = ROOT / "scripts"
for _p in (SCRIPTS, ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


# ---------------------------------------------------------------- 真源（现读，不写死）
def live_door_names() -> list[str]:
    """**全量档**的门名 —— 现读 `run_gates.build_jobs(False, False)`，不抄第二份名单。"""
    import run_gates as rg

    return [str(name) for name, _ in rg.build_jobs(False, False)]


def live_door_count() -> int:
    return len(live_door_names())


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------- ① 门数 == 现读
_ALL_DOOR_RE = re.compile(r"全量\s*(\d+)\s*道")
_REST_DOOR_RE = re.compile(r"其余\s*(\d+)\s*道")


def doc_door_counts(text: str) -> list[int]:
    """文档里「全量 N 道」这类句子的 N（按出现顺序）。"""
    return [int(m) for m in _ALL_DOOR_RE.findall(text)]


def door_count_diff(text: str, live: int) -> str:
    """文档门数 vs 现读门数（返回空串 = 一致）。

    ★ 判据只比**两个数**，本文件里没有任何「本页应当写 N 道」的字面量：门表加一道门
      ⇒ `live` 自己变，这里不改；会红的只有「文档写在纸上的那个数 ≠ 现读的那个数」。
    """
    found = doc_door_counts(text)
    if not found:
        return ("README 里找不到「全量 N 道」这句话了：门数必须能被现读核对，删掉它等于把"
                f"判据弄瞎（现读 {live} 道）")
    bad = [n for n in found if n != live]
    if not bad:
        return ""
    return f"README 说全量 {bad[0]} 道 / 现读 build_jobs 是 {live} 道"


def test_door_count_matches_live_gate_table() -> None:
    """① README 的「全量 N 道」必须等于现读门数。"""
    live = live_door_count()
    assert live > 0, "真门表读出来是空的（取数口径坏了，不是文档的问题）"
    assert README.is_file(), f"缺文档：{README}"
    diff = door_count_diff(_text(README), live)
    assert diff == "", f"门数与真门表对不上：{diff}"


def test_door_count_drift_both_directions_bite() -> None:
    """① 反向：门数改成现读值 ±1 ⇒ 同一个检查函数必须红，并**点名两个数**。"""
    text = _text(README)
    live = live_door_count()
    assert door_count_diff(text, live) == ""
    for wrong in (live + 1, live - 1):
        broken = _ALL_DOOR_RE.sub(f"全量 {wrong} 道", text, count=1)
        assert broken != text, "替换没生效（检查函数与文档口径脱节）"
        diff = door_count_diff(broken, live)
        assert diff != "", f"门数改成 {wrong} 却照样判一致"
        assert str(wrong) in diff and str(live) in diff, f"报是报了，但没点名：{diff}"


# ---------------------------------------------------------------- ② §2 耗时表的加法
def timing_rows(text: str) -> list[list[str]]:
    """§2 耗时表的每一行（去掉表头与分隔行），逐格文本，反引号剥掉。"""
    if "## 2." not in text:
        return []
    section = text.split("## 2.", 1)[1].split("## 3.", 1)[0]
    rows: list[list[str]] = []
    for line in section.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [c.strip().strip("`").strip() for c in line.strip().strip("|").split("|")]
        if not cells or cells[0] == "门":
            continue
        if set(cells[0]) <= set("-: "):
            continue
        rows.append(cells)
    return rows


def remaining_door_diff(text: str, live: int, doors: list[str]) -> str:
    """「逐行点名的门数 + 其余 N 道」必须等于现读门数（返回空串 = 一致）。

    ★ 不留白：加一道门后「其余 18 道」不会自己变，这条当场把它咬出来。
    """
    rows = timing_rows(text)
    if not rows:
        return "§2 的耗时表读不出来（标题或表没了）"
    listed: list[str] = []
    rest: list[int] = []
    for cells in rows:
        first = cells[0].replace("*", "").strip()
        if first in doors:
            listed.append(first)
        rest += [int(n) for n in _REST_DOOR_RE.findall(cells[0])]
    if len(rest) != 1:
        return f"§2 耗时表里「其余 N 道」应当恰好一行，读到 {len(rest)} 处：{rows}"
    if len(set(listed)) != len(listed):
        return f"§2 耗时表里有重复点名的门：{listed}"
    total = len(listed) + rest[0]
    if total != live:
        return (f"§2 耗时表点名 {len(listed)} 道 + 「其余 {rest[0]} 道」= {total} 道 /"
                f" 现读 build_jobs 是 {live} 道（点名：{listed}）")
    return ""


def test_timing_table_arithmetic_matches_live() -> None:
    """② 耗时表点名 + 「其余 N 道」== 现读门数。"""
    live, doors = live_door_count(), live_door_names()
    diff = remaining_door_diff(_text(README), live, doors)
    assert diff == "", diff


def test_timing_table_drift_bites() -> None:
    """② 反向：改「其余 N 道」±1、或门表多一道 ⇒ 都必须红。"""
    text = _text(README)
    live, doors = live_door_count(), live_door_names()
    assert remaining_door_diff(text, live, doors) == ""
    m = _REST_DOOR_RE.search(text)
    assert m, "文档里没有「其余 N 道」这一行"
    rest = int(m.group(1))
    for wrong in (rest + 1, rest - 1):
        broken = text.replace(m.group(0), f"其余 {wrong} 道", 1)
        assert broken != text
        diff = remaining_door_diff(broken, live, doors)
        assert diff != "", f"「其余」改成 {wrong} 道却照样判一致"
    diff = remaining_door_diff(text, live + 1, doors)
    assert diff != "", "门表多了一道，「其余 N 道」没跟着变却没报"


# ---------------------------------------------------------------- ③ 过期读数清零
#: 本卡要清掉的两个过期读数（`2955` = 旧收集条数；`19 道` = 旧门数）。
_STALE = ("2955", "19 道")


def stale_hits(text: str) -> list[str]:
    return [token for token in _STALE if token in text]


def stale_diff(texts: dict[str, str]) -> str:
    """两份文档里还有哪些过期读数（返回空串 = 都没有）。"""
    bad = [f"{name}：还有 {hits}" for name, text in texts.items() if (hits := stale_hits(text))]
    if not bad:
        return ""
    return "过期读数还在：\n  " + "\n  ".join(bad)


def test_stale_counts_are_gone() -> None:
    """③ `2955` 与「19 道」在两份 CI 文档里零命中。"""
    diff = stale_diff({"README.md": _text(README), "事后判据清单.md": _text(CHECKLIST)})
    assert diff == "", diff


def test_stale_counts_bite_when_reinserted() -> None:
    """③ 反向：把过期读数塞回任一文档 ⇒ 同一个检查函数必须红。"""
    readme, checklist = _text(README), _text(CHECKLIST)
    assert stale_diff({"README.md": readme, "事后判据清单.md": checklist}) == ""
    for token in _STALE:
        broken = readme.replace("## 2.", f"## 2. {token}", 1)
        assert token in broken
        diff = stale_diff({"README.md": broken})
        assert token in diff, f"塞回 {token} 却没被点出来：{diff!r}"
    broken_checklist = checklist.replace("- **E2**：", "- **E2**：pytest 2955 条；", 1)
    assert "2955" in broken_checklist
    assert "2955" in stale_diff({"事后判据清单.md": broken_checklist})


# ---------------------------------------------------------------- ④ 两处条数同一个数
#: 收集条数句的探针命令（卡规格判据 2 要求「能重跑的探针」）。
_PROBE = "--collect-only"
_COUNT_RE = re.compile(r"(\d{3,5})\s*条")
_DATE_RE = re.compile(r"20\d\d-\d\d-\d\d")


def _probe_paragraphs(text: str) -> list[str]:
    """含探针命令的**段**（文档按 ~80 字折行，探针与它算出来的数常被折到两行上）。"""
    return [p for p in re.split(r"\n\s*\n", text) if _PROBE in p]


def pytest_count_claims(text: str) -> list[int]:
    """带探针命令那一段里的收集条数（按出现顺序）。"""
    claims: list[int] = []
    for para in _probe_paragraphs(text):
        claims += [int(n) for n in _COUNT_RE.findall(para)]
    return claims


def pytest_count_diff(readme: str, checklist: str) -> str:
    """两处的 pytest 条数必须**同一个数**（返回空串 = 一致）。"""
    a, b = pytest_count_claims(readme), pytest_count_claims(checklist)
    if len(a) != 1 or len(b) != 1:
        return (f"pytest 条数句必须恰好一条带 `{_PROBE}` 的行、行内恰好一个数："
                f"README={a} / 事后判据清单={b}")
    if a[0] != b[0]:
        return f"两处的 pytest 条数不一致：README {a[0]} 条 / 事后判据清单 {b[0]} 条"
    return ""


def pytest_count_sourceless(text: str) -> list[str]:
    """条数句缺日期的段（快照必须带日期，否则读者判不出它是什么时候的）。"""
    return [p.strip().replace("\n", " ")[:60] for p in _probe_paragraphs(text)
            if _COUNT_RE.search(p) and not _DATE_RE.search(p)]


def test_pytest_count_claims_agree() -> None:
    """④ 两处条数一致，且同一行带探针 + 日期。"""
    readme, checklist = _text(README), _text(CHECKLIST)
    diff = pytest_count_diff(readme, checklist)
    assert diff == "", diff
    for name, text in (("README.md", readme), ("事后判据清单.md", checklist)):
        bad = pytest_count_sourceless(text)
        assert not bad, f"{name} 的条数句没有日期：{bad}"


def test_pytest_count_mismatch_bites() -> None:
    """④ 反向：把一处改成别的数 ⇒ 同一个检查函数必须红并点名两个数。"""
    readme, checklist = _text(README), _text(CHECKLIST)
    assert pytest_count_diff(readme, checklist) == ""
    claims = pytest_count_claims(readme)
    assert len(claims) == 1, f"README 的条数句不止一个数：{claims}"
    n = claims[0]
    broken = checklist.replace(f"{n} 条", f"{n + 1} 条", 1)
    assert broken != checklist, "替换没生效（检查函数与文档口径脱节）"
    diff = pytest_count_diff(readme, broken)
    assert diff != "", "两处条数不一样却照样判一致"
    assert str(n) in diff and str(n + 1) in diff, f"报是报了，但没点名：{diff}"


# ---------------------------------------------------------------- ⑤ 行尾不变
def ending_readings(path: Path) -> tuple[int, int, int]:
    """`(字节数, CRLF 数, 裸 LF 数)`。"""
    raw = path.read_bytes()
    crlf = raw.count(b"\r\n")
    return len(raw), crlf, raw.count(b"\n") - crlf


def ending_problems(path: Path, *, min_lines: int, max_lines: int) -> str:
    """纯 CRLF 且行数在区间内（返回空串 = 没问题）。"""
    size, crlf, bare = ending_readings(path)
    if bare:
        return f"{path.name}：{bare} 处裸 LF（必须纯 CRLF；{size} B / crlf {crlf}）"
    if not min_lines <= crlf <= max_lines:
        return f"{path.name}：{crlf} 行（{size} B），超出 {min_lines}–{max_lines} 行"
    return ""


def test_line_endings_stay_crlf() -> None:
    """⑤ README 纯 CRLF 且仍是 69 行上下（卡规格判据 5）；本文件自己也一样。"""
    problems = [
        p for p in (
            ending_problems(README, min_lines=54, max_lines=84),
            ending_problems(CHECKLIST, min_lines=1, max_lines=200),
            ending_problems(Path(__file__), min_lines=1, max_lines=400),
        ) if p
    ]
    assert not problems, "\n".join(problems)
