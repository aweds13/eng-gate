r"""门自证钉子：每道门都要有一条「故意造坏输入 ⇒ 断言它红」的反向用例。

**为什么要这个文件**：立仓原则是「判据不进技能，判据在工具与门里」，而
「一道从不红的门，等于没有门」。门绿只能说明进程退 0；它**看不见**问题时也退 0。
所以要为每道门指一条反向用例，并把这件事变成会咬的判据，否则台账会烂在原地。

台账在 `gates/gate-selfproof.toml`（一行一道门：`name` / `reverse_case` /
`why_no_case` / `since`）。本文件的判据（`_problems` 一把尺子，零件层 + 数据层分开）：

| # | 判据 | 坏掉会红在哪 |
|---|---|---|
| ① | 台账里每个 `name` 都在**真实门表**里 | 门改名/删掉，台账还指着一个不存在的门 |
| ①b | 真实门表里每道门都有台账行 | 新加一道门，没人给它造反向用例也没人说不出来 |
| ② | `reverse_case` 指的 nodeid **真的存在** | 指着不存在的用例 / 用例被改名 ⇒ 台账变成空头支票 |
| ③ | `none` 时 `why_no_case` 不许空，且 ≥`MIN_WHY` 字 | 「要真浏览器」这种空话 = 假装有门 |
| ④ | 每道门的命令不是空的（静态命令或动态门） | 门表里塞一条 `[]` 又不是动态门 ⇒ 静默空跑 |
| ⑤ | 台账行序与真门表**逐字同序** | 台账乱序，人对着门表读会看错行 |

★ 判据 ② 不是「文件在不在」，而是**用例名在不在**：`tests/` 的钉子走真
`pytest --collect-only` 拿 nodeid 集合（参数化后缀 `[acceptance]` 也认），
`scripts/` 的自测脚本钉子复用 `tools/wb_invariants.py::defines_case` 这把尺子
（**不许写第二份**）。

★ 反向用例（本文件自己的钉子，见文件末尾）：把 `reverse_case` 改到一个不存在的
nodeid、把 `why_no_case` 留空、删一行/加一行 → 判据必须红。

★ 还有一条**造坏输入 ⇒ 断言真门会红**的反向用例集（本文件下半部分）：`ruff` /
`mypy` / `pytest` / `acceptance` / `pytest_chain` / `audit_titles` / `ui_dom_probe` /
`lf1_live` / `web_live` 这几道门原本没有反向用例，就在这里现造。做法统一是：
**在 `tmp_path` 里造一份违规输入，跑门的真判据，断言它退非零** —— 绝不动真实仓库
（`tests/test_dark_teeth.py::test_5_self_proof_never_touches_the_repo` 会抓）。
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import tomllib

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "gates" / "gate-selfproof.toml"
PY = sys.executable
NODE = shutil.which("node")

#: 判据 ③ 的下限：`why_no_case` 少于这么多字符就算空话（「要真浏览器」才 5 个字，不够）。
MIN_WHY = 20


def _load(name: str, path: Path):
    """按仓里通行写法加载一个非包的脚本（必须先登记 `sys.modules`，否则 dataclass 会炸）。"""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, f"加载不了：{path}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


rg = _load("run_gates_for_selfproof", ROOT / "scripts" / "run_gates.py")
wbi = _load("wb_invariants_for_selfproof", ROOT / "tools" / "wb_invariants.py")

#: 门表里命令是动态填（`[]`）的门：`pytest` 由 `pytest_cmd()` 填，
#: 三个 node 门由 `NODE_CMD` 填（环境没有 node ⇒ 记 not_run，不算通过）。
DYNAMIC_DOORS = frozenset({"pytest", *rg.NODE_CMD})


# ────────────────────────── 判据（一把尺子 · 零件层）──────────────────────────


def real_gate_table() -> dict[str, list[str]]:
    """真实门表：`{门名: 命令}`，从 `scripts/run_gates.py` 的 `build_jobs` 读（**不写死**）。"""
    return dict(rg.build_jobs(quick=False, fast=False))


def load_ledger(path: Path = LEDGER) -> list[dict[str, object]]:
    """读自证台账，回 `[[gate]]` 条目（**不校验**内容 —— 校验在 `_problems`）。"""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    rows = data.get("gate")
    assert isinstance(rows, list) and rows, f"台账里没有 `[[gate]]` 条目：{path}"
    return [dict(row) for row in rows]


def _pytest_nodeids(rel_files: list[str]) -> set[str]:
    """真 collect 一遍 `tests/` 下的钉子文件，拿**真实 nodeid**（参数化后缀也在里面）。"""
    if not rel_files:
        return set()
    proc = subprocess.run(
        [
            PY, "-X", "utf8", "-m", "pytest", "--collect-only", "-q",
            "-o", "addopts=", "-p", "no:cacheprovider",
            *rel_files,
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    # collect-only 的退出码 5 表示「没收集到」——那本身就是判据要报的问题，
    # 交给 `_problems` 去说「这个 nodeid 不存在」，别在这里先炸。
    out = proc.stdout or ""
    return {line.strip() for line in out.splitlines() if "::" in line and line.strip()}


def _script_cases(rel_file: str) -> str:
    """自测脚本（非 pytest）的正文 —— 有没有 `def <用例名>(` 交给同一把尺子判。"""
    path = ROOT / rel_file
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _problems(
    rows: list[dict[str, object]],
    gate_names: set[str],
    nodeids: set[str],
) -> list[str]:
    """逐条核台账 —— 回一串人话问题（**空列表 = 全过**）。

    纯函数：不读真实仓库，好让反向用例能喂合成坏台账进来。
    """
    problems: list[str] = []
    seen: dict[str, int] = {}

    for index, row in enumerate(rows, 1):
        name = str(row.get("name", "") or "").strip()
        where = f"台账第 {index} 行（{name or '没写 name'}）"
        if not name:
            problems.append(f"{where}：`name` 是空的")
            continue
        seen[name] = seen.get(name, 0) + 1
        if name not in gate_names:
            problems.append(f"{where}：门表里没有这道门（台账烂了，或门改名/删了）")

        reverse = str(row.get("reverse_case", "") or "").strip()
        why = str(row.get("why_no_case", "") or "").strip()
        if not reverse:
            problems.append(f"{where}：`reverse_case` 没写（要么指 nodeid，要么明写 none）")
        elif reverse == "none":
            if not why:
                problems.append(
                    f"{where}：`reverse_case = none` 却没写 `why_no_case` "
                    "—— 没有反向用例、也说不清为什么，等于假装有门"
                )
            elif len(why) < MIN_WHY:
                problems.append(
                    f"{where}：`why_no_case` 只有 {len(why)} 个字（判据要 ≥{MIN_WHY}）"
                    "—— 空话不算理由，要写出具体技术原因（要真服务 / 要真浏览器 / …）"
                )
        else:
            match = wbi.NAIL_RE.match(reverse)
            if not match:
                problems.append(
                    f"{where}：`reverse_case` 写法不对（要 `tests/…::<用例名>` 或 "
                    f"`scripts/…::<用例名>`）：{reverse}"
                )
            elif match.group("file").startswith("tests/"):
                if reverse not in nodeids:
                    problems.append(
                        f"{where}：`reverse_case` 指的 nodeid 不存在（真 collect 过一遍，"
                        f"参数化后缀算在内）：{reverse}"
                    )
            else:
                text = _script_cases(match.group("file"))
                if not text:
                    problems.append(f"{where}：`reverse_case` 的脚本不存在：{match.group('file')}")
                elif not wbi.defines_case(text, wbi.case_name(match.group("case"))):
                    problems.append(
                        f"{where}：`reverse_case` 的用例名在 {match.group('file')} 里找不到："
                        f"{match.group('case')}"
                    )

        if not str(row.get("since", "") or "").strip():
            problems.append(f"{where}：`since` 没写（台账要知道这一行是哪天核过的）")

    for name, count in sorted(seen.items()):
        if count > 1:
            problems.append(f"台账里 `{name}` 写了 {count} 行（一道门只许一行）")

    for name in sorted(gate_names - set(seen)):
        problems.append(
            f"门表里有 `{name}`，台账里没有它 —— 新门必须交代「反向用例在哪」，"
            "或明写 `reverse_case = none` + `why_no_case`"
        )

    return problems


def _order_problems(rows: list[dict[str, object]], gate_order: list[str]) -> list[str]:
    """判据 ⑤：台账行序必须与真门表**逐字同序**（多/少一道另有 ①/①b，这里只看顺序）。"""
    known = set(gate_order)
    got = [str(row.get("name", "") or "").strip() for row in rows]
    got = [name for name in got if name in known]
    want = [name for name in gate_order if name in set(got)]
    if got == want:
        return []
    first = next(
        (i for i, (a, b) in enumerate(zip(got, want, strict=False)) if a != b),
        min(len(got), len(want)),
    )
    return [
        "台账行序与真门表对不上（逐字同序是判据 ⑤）——\n"
        f"    第 {first + 1} 行起就不一样：台账是 {got[first:first + 4]}，"
        f"门表是 {want[first:first + 4]}"
    ]


def _empty_command_problems(table: dict[str, list[str]]) -> list[str]:
    """判据 ④：门表里除了动态门，谁的命令都不许是空的（否则是静默空跑）。"""
    return [
        f"门 `{name}` 的命令是空的，又不是动态门 —— 这道门什么也没跑"
        for name, cmd in sorted(table.items())
        if not cmd and name not in DYNAMIC_DOORS
    ]


# ────────────────────────── 数据层（对着真实仓库）──────────────────────────


def test_real_ledger_passes_all_criteria() -> None:
    """台账 + 真实门表 + 真 nodeid：今天这一份必须全过。"""
    table = real_gate_table()
    rows = load_ledger()
    test_files = sorted(
        {
            str(row["reverse_case"]).split("::", 1)[0]
            for row in rows
            if str(row.get("reverse_case", "")).startswith("tests/")
        }
    )
    nodeids = _pytest_nodeids(test_files)
    problems = [
        *_problems(rows, set(table), nodeids),
        *_order_problems(rows, list(table)),
        *_empty_command_problems(table),
    ]
    assert not problems, "门自证台账有问题：\n" + "\n".join(f"  - {p}" for p in problems)


def test_ledger_covers_exactly_the_real_gate_table() -> None:
    """① 与 ①b 的正向形状：台账门集合 == 门表门集合（双向，不是单向包含）。"""
    table = real_gate_table()
    names = {str(row.get("name")) for row in load_ledger()}
    assert names == set(table), (
        "台账与门表对不上 ——\n"
        f"  门表里多出（没人写台账）：{sorted(set(table) - names)}\n"
        f"  台账里多出（门表里没有）：{sorted(names - set(table))}"
    )


def test_ledger_order_matches_the_real_gate_table() -> None:
    """⑤ 的正向形状：台账行序 == `build_jobs()` 的装配顺序（逐字、同序）。"""
    problems = _order_problems(load_ledger(), list(real_gate_table()))
    assert not problems, "\n".join(problems)


def test_ledger_is_not_trivially_all_none() -> None:
    """★ 防空转：不许整本台账都写 `none`（那样判据全绿却毫无自证）。"""
    rows = load_ledger()
    have_case = [row for row in rows if str(row.get("reverse_case")) != "none"]
    assert len(have_case) >= len(rows) // 2, (
        f"台账里只有 {len(have_case)}/{len(rows)} 道门有反向用例 —— "
        "真造不出来要写进 why_no_case，但不许把整本台账写成 none"
    )


# ────────── 反向用例：台账自己烂掉时，上面那把尺子必须红（零件层）──────────


def _sample_rows() -> list[dict[str, object]]:
    """一份**合成**台账 + 合成门表，专供反向用例用（不碰真实仓库）。"""
    return [
        {
            "name": "alpha",
            "reverse_case": "tests/test_demo.py::test_alpha_bites",
            "since": "2026-10-27",
        },
        {
            "name": "beta",
            "reverse_case": "none",
            "why_no_case": "要真 Edge 浏览器采集签名，pytest 里起不了",
            "since": "2026-10-27",
        },
    ]


def test_synthetic_good_ledger_is_green() -> None:
    """反向用例的**对照**：合成台账本身合规时必须零问题（否则下面的红不算数）。"""
    rows = _sample_rows()
    problems = _problems(rows, {"alpha", "beta"}, {"tests/test_demo.py::test_alpha_bites"})
    assert problems == [], f"合成台账该全过，实际：{problems}"
    assert _order_problems(rows, ["alpha", "beta"]) == []


def test_nail_bites_when_reverse_case_points_at_a_missing_nodeid() -> None:
    """★ 本文件自己的反向用例：把 reverse_case 指到不存在的 nodeid ⇒ 判据必须红。"""
    rows = _sample_rows()
    rows[0]["reverse_case"] = "tests/test_demo.py::test_this_case_does_not_exist_xyz"
    problems = _problems(rows, {"alpha", "beta"}, {"tests/test_demo.py::test_alpha_bites"})
    assert any(
        "nodeid 不存在" in p and "test_this_case_does_not_exist_xyz" in p for p in problems
    ), f"指到不存在的 nodeid 却没红：{problems}"


def test_nail_bites_when_none_has_no_why() -> None:
    """③ 的反向用例：`none` + 空理由 ⇒ 必须红（这才是「假装有门」）。"""
    rows = _sample_rows()
    rows[1]["why_no_case"] = ""
    problems = _problems(rows, {"alpha", "beta"}, {"tests/test_demo.py::test_alpha_bites"})
    assert any("why_no_case" in p and "假装有门" in p for p in problems), (
        f"none 且没写理由却没红：{problems}"
    )


def test_nail_bites_when_none_why_is_an_empty_phrase() -> None:
    """③ 的反向用例：`none` + 5 个字的空话（「要真浏览器」）⇒ 必须红。"""
    rows = _sample_rows()
    rows[1]["why_no_case"] = "要真浏览器"
    problems = _problems(rows, {"alpha", "beta"}, {"tests/test_demo.py::test_alpha_bites"})
    assert any("why_no_case" in p and str(MIN_WHY) in p for p in problems), (
        f"none 且理由只有 5 个字却没红（空话混过去了）：{problems}"
    )


def test_nail_bites_when_rows_are_out_of_order() -> None:
    """⑤ 的反向用例：两道门对调 ⇒ 顺序判据必须红（集合判据看不见这件事）。"""
    rows = _sample_rows()
    rows.reverse()
    assert _problems(rows, {"alpha", "beta"}, {"tests/test_demo.py::test_alpha_bites"}) == [], (
        "集合判据本来就不该管顺序 —— 那样 ⑤ 就没有存在意义"
    )
    problems = _order_problems(rows, ["alpha", "beta"])
    assert problems and "行序" in problems[0], f"台账乱序却没红：{problems}"


def test_nail_bites_when_a_row_names_a_gate_that_does_not_exist() -> None:
    """① 的反向用例：台账留一个门表里没有的门 ⇒ 必须红（台账会烂在原地）。"""
    rows = _sample_rows() + [
        {
            "name": "gamma_deleted_door",
            "reverse_case": "none",
            "why_no_case": "这道门已经从门表里删掉了，没有对应的门可跑",
            "since": "2026-10-27",
        }
    ]
    problems = _problems(rows, {"alpha", "beta"}, {"tests/test_demo.py::test_alpha_bites"})
    assert any("门表里没有这道门" in p and "gamma_deleted_door" in p for p in problems), (
        f"台账里有不存在的门却没红：{problems}"
    )


def test_nail_bites_when_a_real_gate_has_no_row() -> None:
    """①b 的反向用例：门表新加一道门、台账没跟上 ⇒ 必须红。"""
    rows = _sample_rows()
    problems = _problems(
        rows, {"alpha", "beta", "gamma_new_door"}, {"tests/test_demo.py::test_alpha_bites"}
    )
    assert any("台账里没有它" in p and "gamma_new_door" in p for p in problems), (
        f"门表多一道门却没红：{problems}"
    )


def _nodeids_from(rows: list[dict[str, object]]) -> set[str]:
    """从台账行本身反推 nodeid 集合（反向用例用：不想为了造一次红去真 collect 45 秒）。

    ★ 只喂给**故意造坏**的变形台账用；真实台账那份仍然走 `_pytest_nodeids()` 真 collect
    —— 否则「nodeid 存在性」就成了自证。
    """
    return {
        str(row.get("reverse_case", ""))
        for row in rows
        if str(row.get("reverse_case", "")).startswith("tests/")
    }


def test_nail_bites_when_the_real_ledger_loses_a_door() -> None:
    """①b 的反向用例（对着**真实**台账）：删掉一行 ⇒ 判据必须点名那道门。

    同一条里先证明**没删之前是绿的**：否则「删了就红」也可能只是「这判据对真实台账
    永远红」，那样它同样没在证明什么。
    """
    table = real_gate_table()
    rows = load_ledger()
    nodeids = _nodeids_from(rows)
    assert _problems(rows, set(table), nodeids) == [], "完整台账本来就该绿（对照不成立）"

    gone = str(rows[0]["name"])
    problems = _problems(rows[1:], set(table), nodeids)
    assert any("台账里没有它" in p and gone in p for p in problems), (
        f"真实台账少一行却没红（{gone}）：{problems}"
    )


def test_nail_bites_when_the_real_ledger_gains_a_door() -> None:
    """① 的反向用例（对着**真实**台账）：多写一行门表里没有的门 ⇒ 必须红（含绿对照）。"""
    table = real_gate_table()
    rows = load_ledger()
    nodeids = _nodeids_from(rows)
    assert _problems(rows, set(table), nodeids) == [], "完整台账本来就该绿（对照不成立）"

    extra = dict(rows[-1])
    extra["name"] = "gamma_phantom_door"
    problems = _problems([*rows, extra], set(table), nodeids)
    assert any("门表里没有这道门" in p and "gamma_phantom_door" in p for p in problems), (
        f"真实台账多一行却没红：{problems}"
    )


def test_nail_bites_when_a_door_has_no_command() -> None:
    """④ 的反向用例：门表里塞一条空命令且不是动态门 ⇒ 必须红（静默空跑）。"""
    problems = _empty_command_problems({"alpha": [PY, "-c", "pass"], "hollow": []})
    assert any("命令是空的" in p and "hollow" in p for p in problems), (
        f"空命令的门没红：{problems}"
    )
    assert _empty_command_problems({"pytest": []}) == [], "动态门（pytest）不该被这条判据误伤"


# ────────── 反向用例：给原本没有反向用例的门现造（造坏输入 ⇒ 断言真门红）──────────


def test_ruff_door_bites_on_an_unused_import(tmp_path: Path) -> None:
    """`ruff` 门：未使用 import ⇒ 退非零并报 F401；**干净文件 ⇒ 先退 0**（对照）。

    ★ 先跑绿的这一步不能省：只证明「坏文件红了」说明不了门看得见问题 ——
    门也可能对**一切**输入都红（那它同样是个没用的门）。
    """
    pytest.importorskip("ruff", reason="环境里没有 ruff，这道门的反向用例跑不了")

    def run(path: Path) -> tuple[int, str]:
        proc = subprocess.run(
            [PY, "-m", "ruff", "check", "--config", str(ROOT / "pyproject.toml"), str(path)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")

    good = tmp_path / "good_lint.py"
    good.write_text("def f() -> int:\n    return 1\n", encoding="utf-8")
    rc_ok, out_ok = run(good)
    assert rc_ok == 0, f"干净文件却退 {rc_ok}（下面那条红不算数）：\n{out_ok}"

    bad = tmp_path / "bad_lint.py"
    bad.write_text("import os\nimport sys\n\n\ndef f() -> int:\n    return 1\n", encoding="utf-8")
    rc, out = run(bad)
    assert rc != 0, f"未使用 import 却没红：rc={rc}\n{out}"
    assert "F401" in out, f"退非零但没报 F401（判据没看见问题）：\n{out}"


def test_mypy_door_bites_on_a_type_error(tmp_path: Path) -> None:
    """`mypy` 门：返回类型不匹配 ⇒ 退非零并报 return-value；**干净文件 ⇒ 先退 0**（对照）。"""
    pytest.importorskip("mypy", reason="环境里没有 mypy，这道门的反向用例跑不了")

    def run(path: Path) -> tuple[int, str]:
        proc = subprocess.run(
            [PY, "-m", "mypy", "--config-file", str(ROOT / "pyproject.toml"), str(path)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")

    good = tmp_path / "good_type.py"
    good.write_text("def f(x: int) -> str:\n    return str(x)\n", encoding="utf-8")
    rc_ok, out_ok = run(good)
    assert rc_ok == 0, f"类型正确的文件却退 {rc_ok}（下面那条红不算数）：\n{out_ok}"

    bad = tmp_path / "bad_type.py"
    bad.write_text("def f(x: int) -> str:\n    return x\n", encoding="utf-8")
    rc, out = run(bad)
    assert rc != 0, f"类型错却没红：rc={rc}\n{out}"
    assert "return-value" in out or "Incompatible return value" in out, (
        f"退非零但没报那条类型错（判据没看见问题）：\n{out}"
    )


def _run_pytest_in(tmp_path: Path, target: str, *extra: str) -> subprocess.CompletedProcess[str]:
    """在 `tmp_path` 里跑一次**隔离的** pytest（`-o addopts=` 保证不吃仓库的 addopts）。"""
    return subprocess.run(
        [
            PY, "-X", "utf8", "-m", "pytest", target,
            "-o", "addopts=", "-p", "no:cacheprovider", *extra,
        ],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )


def test_pytest_door_bites_on_a_deliberately_failing_test(tmp_path: Path) -> None:
    """`pytest` 门：造一条断言失败的用例 ⇒ 退 1；把它修绿 ⇒ 退 0（对照）。"""
    bad = tmp_path / "test_bad.py"
    bad.write_text("def test_red():\n    assert False, 'deliberate'\n", encoding="utf-8")
    proc = _run_pytest_in(tmp_path, "test_bad.py")
    assert proc.returncode == 1, (
        f"断言失败的用例没让 pytest 退 1：rc={proc.returncode}\n{proc.stdout}"
    )

    bad.write_text("def test_green():\n    assert True\n", encoding="utf-8")
    again = _run_pytest_in(tmp_path, "test_bad.py")
    assert again.returncode == 0, f"修绿了却不退 0（上面那条红不算数）：\n{again.stdout}"


@pytest.mark.parametrize("marker", ["acceptance", "chain"])
def test_marker_door_bites_on_a_marked_failure(tmp_path: Path, marker: str) -> None:
    """`acceptance` / `pytest_chain` 门：`-m <标记>` 必须**真的选中**打了标却失败的用例。

    这两道门只靠 `-m acceptance` / `-m chain` 把用例挑出来跑。如果标记没打在用例上
    （或门的 `-m` 写错了），门会「跳过一切、退 0」——**这门就不咬了**。所以这里造一条
    打了标、必定失败的用例：`-m <标记>` 必须退 1（它真跑了），`-m "not <标记>"` 必须
    退 5（一条没选中）。两个方向一起，才排掉「退 0 是因为什么都没跑」。
    """
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\nmarkers =\n    acceptance: 可执行验收层\n    chain: 真链路\n",
        encoding="utf-8",
    )
    (tmp_path / "test_marked.py").write_text(
        "import pytest\n\n\n"
        f"@pytest.mark.{marker}\n"
        "def test_red():\n"
        "    assert False, 'deliberate'\n",
        encoding="utf-8",
    )
    selected = _run_pytest_in(tmp_path, "test_marked.py", "-m", marker)
    assert selected.returncode == 1, (
        f"`-m {marker}` 没选中这条打了标、必定失败的用例（门等于没咬）："
        f"rc={selected.returncode}\n{selected.stdout}"
    )
    deselected = _run_pytest_in(tmp_path, "test_marked.py", "-m", f"not {marker}")
    assert deselected.returncode == 5, (
        f"`-m \"not {marker}\"` 应该一条都选不中（rc 5），实际 rc={deselected.returncode}"
        f"\n{deselected.stdout}"
    )


def test_audit_titles_door_bites_on_a_misaligned_title(tmp_path: Path, monkeypatch) -> None:
    """`audit_titles` 门：造一条「编号在、含义错」的台账 ⇒ `--check` 必须退 1。

    这道门守的是「编号对得上、标题含义也对得上」（`audit_progress.py` 只按编号核，
    所以含义错位能躲过它）。合成三份输入：规格两段、台账把 `SR-F1` 的标题写成
    `SR-F2` 的含义，另加一条规格里没有的 `SR-F9`。
    """
    at = _load("audit_titles_for_selfproof", ROOT / "scripts" / "audit_titles.py")

    functional = tmp_path / "functional.md"
    functional.write_text(
        "- **SR-F1**（P0）～ 任务台账与状态流转\n"
        "- **SR-F2**（P0）～ 专注计时的开始与结束\n",
        encoding="utf-8",
    )
    nonfunctional = tmp_path / "nonfunctional.md"
    nonfunctional.write_text("## SR-NF1 · 离线可用\n", encoding="utf-8")

    def _ledger(title_f1: str, extra: str = "") -> Path:
        path = tmp_path / f"traceability-{abs(hash((title_f1, extra))) % 10**8}.toml"
        path.write_text(
            f'[entries."SR-F1"]\ntitle = "{title_f1}"\n'
            f'[entries."SR-F2"]\ntitle = "专注计时的开始与结束"\n'
            f"{extra}",
            encoding="utf-8",
        )
        return path

    monkeypatch.setattr(at, "FUNCTIONAL", functional)
    monkeypatch.setattr(at, "NONFUNCTIONAL", nonfunctional)

    # ① 对照：标题对齐时必须零错位（否则下面那条红不算数）。
    monkeypatch.setattr(at, "LEDGER", _ledger("任务台账与状态流转"))
    monkeypatch.setattr(sys, "argv", ["audit_titles.py", "--check"])
    assert at.main() == 0, "标题都对齐却退非零（判据误伤）"
    assert [r for r in at.compare() if r["level"] in {"shifted", "unmapped"}] == []

    # ② 反向：SR-F1 写成 SR-F2 的含义 + 一条规格里没有的 SR-F9 ⇒ 必须退 1。
    monkeypatch.setattr(
        at,
        "LEDGER",
        _ledger("专注计时的开始与结束", extra='[entries."SR-F9"]\ntitle = "谁都不知道这是什么"\n'),
    )
    rows = {str(row["id"]): row for row in at.compare()}
    assert rows["SR-F1"]["level"] == "shifted", f"含义错位没被认成 shifted：{rows['SR-F1']}"
    assert rows["SR-F9"]["level"] == "unmapped", (
        f"规格里没有的编号没被认成 unmapped：{rows['SR-F9']}"
    )
    monkeypatch.setattr(sys, "argv", ["audit_titles.py", "--check"])
    assert at.main() == 1, "有 shifted + unmapped 却退 0（这道门不咬）"


@pytest.mark.skipif(NODE is None, reason="环境里没有 node（DOM 探针本来就跑不了）")
def test_ui_dom_probe_door_bites_on_a_throwing_view(tmp_path: Path) -> None:
    """`ui_dom_probe` 门：造一个一渲染就抛错的页面 ⇒ 探针必须退 1；真页面 ⇒ 退 0。

    探针把自己那个 `.mjs` 的**同级目录**当仓库根（`INDEX = join(HERE,'..','src','web',
    'index.html')`），所以把它复制进临时树、在旁边放一份合成 `src/web/` 就能喂坏输入，
    真实仓库一个字节都不动。
    """
    assert NODE is not None
    tool = tmp_path / "tools" / "ui_dom_probe.mjs"
    tool.parent.mkdir(parents=True)
    shutil.copy2(ROOT / "tools" / "ui_dom_probe.mjs", tool)
    web = tmp_path / "src" / "web"
    web.mkdir(parents=True)
    shutil.copy2(ROOT / "src" / "web" / "offline.js", web / "offline.js")

    def run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [NODE, str(tool)], cwd=str(tmp_path), capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=300,
        )

    (web / "index.html").write_text(
        "<html><body><div id=\"app\"></div><script>\n"
        "function render(){ throw new TypeError('boom from a deliberately broken view'); }\n"
        "render();\n"
        "</script></body></html>\n",
        encoding="utf-8",
    )
    bad = run()
    assert bad.returncode == 1, f"一渲染就抛错却没退 1：rc={bad.returncode}\n{bad.stdout}"
    assert "boom from a deliberately broken view" in (bad.stdout or "") + (bad.stderr or ""), (
        f"退 1 但没报出那个错（判据没看见问题）：\n{bad.stdout}"
    )

    # ③ 对照：换成真实页面 ⇒ 必须退 0（否则上面那条红可能只是「树搭错了」）。
    shutil.copy2(ROOT / "src" / "web" / "index.html", web / "index.html")
    good = run()
    assert good.returncode == 0, f"真页面却退非零（合成树搭得不对）：\n{good.stdout}{good.stderr}"


def test_lf1_check_helper_bites() -> None:
    """`lf1_live` 门：它的 `check()` 一发现不一致就要把标签记进 `FAILURES`（`main` 靠它退 1）。

    ★ 诚实边界：这条只盖住「不一致 ⇒ 被收进 FAILURES ⇒ 门会红」这段判据骨架；
    **真起 uvicorn、把 LF-1 主链走完**那一段在这里跑不了（要在真机起服务），
    仍是盲区，已写进台账的 `why_no_case`。
    """
    lf1 = _load("lf1_live_check_for_selfproof", ROOT / "tools" / "lf1_live_check.py")
    saved = list(lf1.FAILURES)
    try:
        lf1.FAILURES.clear()
        lf1.check("自证-一致", 2, 2)
        assert lf1.FAILURES == [], f"一致的检查被误记成失败：{lf1.FAILURES}"
        lf1.check("自证-不一致", 1, 2)
        assert "自证-不一致" in lf1.FAILURES, (
            f"不一致的检查没进 FAILURES（main 就不会退 1，这门不咬）：{lf1.FAILURES}"
        )
    finally:
        lf1.FAILURES[:] = saved


@pytest.mark.skipif(
    NODE is None, reason="这台机器没有 node（没 node 就无法做语法解析，记 not_run 不算通过）"
)
def test_web_live_js_syntax_bites(tmp_path: Path, monkeypatch) -> None:
    """`web_live` 门：页面里塞一段语法坏掉的 `<script>` ⇒ `check_js_syntax` 必须回 False。

    ★ 诚实边界：这条盖住的是「前端脚本语法坏了 ⇒ 门会红」这一条纯函数判据；
    **真起服务后的 13 组 live_* 检查**仍是盲区（要真 uvicorn），已写进台账。
    """
    web = ROOT / "tools" / "web_live_check.py"
    wlc = _load("web_live_check_for_selfproof", web)
    monkeypatch.setattr(wlc, "INDEX", tmp_path / "index.html")
    (tmp_path / "index.html").write_text(
        "<html><script>\nfunction f( { return 1 }\n</script></html>\n", encoding="utf-8"
    )
    ok, detail = wlc.check_js_syntax(tmp_path)
    assert ok is False, f"语法坏掉的 <script> 被当成通过：{detail}"

    (tmp_path / "index.html").write_text(
        "<html><script>\nfunction f() { return 1; }\n</script></html>\n", encoding="utf-8"
    )
    good_ok, good_detail = wlc.check_js_syntax(tmp_path)
    assert good_ok is True, f"语法正确的 <script> 被误判成坏（上面那条红不算数）：{good_detail}"
