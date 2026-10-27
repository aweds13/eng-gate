r"""测试流程文档的钉子（卡 E43 · `T-AG495` 判据 3 至少 5 条 + 判据 4 的 `--only` 半趟）。

钉的是「文档与工具不许写成两套」：

| # | 钉子 | 坏掉会红在哪 |
|---|---|---|
| ① | 21 道门名与 `gates/defs/*.py` 的 `GATES` **逐字一致** | 门表加了一道/文档抄错一个字 ⇒ 红 |
| ② | 五维关键词（档位 / 域 / 选测 / 夜间 / 异机）都在 | 少一维 ⇒ 红 |
| ③ | 决策树里的档位名都是**真参数**（两个 parser 都认） | 文档写了一个不存在的开关 ⇒ 红 |
| ④ | 指向 `skills/pipe-gate/SKILL.md` 的链接在，且文件真存在 | 链到一篇不存在的文档 ⇒ 红 |
| ⑤ | 每条耗时都带出处（表内 `源：…`），不许写没有出处的数字 | 拍脑袋的「5 分钟」⇒ 红 |
| ⑥ | `--only` 产生的**半趟**读数被 `wb_verify` 判红 | 半趟能被当全量 ⇒ 红 |

★ 反向验证（判据 5 的第二条）做在 ① 里：把某个门名改错一个字，同一个检查函数必须报出来。
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "subsystems" / "ci" / "测试流程.md"
TOOLS = ROOT / "tools"
SCRIPTS = ROOT / "scripts"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- 门名（唯一真源）
def door_table_names() -> list[str]:
    """门表里的全部门名（`gates/defs/` 三份模块 + 真机层 + 浏览器层，顺序即真源顺序）。"""
    from gates.defs import contract, lang_python, product_timeflow

    return [str(n) for n, _ in (*lang_python.GATES, *contract.GATES,
                                *product_timeflow.GATES, *product_timeflow.REAL)] \
        + [str(n) for n in product_timeflow.BROWSER]


def doc_door_names(text: str) -> list[str]:
    """文档「表一」里第一列的反引号门名（按出现顺序）。"""
    if "## 4. 表一" not in text:
        return []
    section = text.split("## 4. 表一", 1)[1].split("## 5.", 1)[0]
    return re.findall(r"^\|\s*`([a-z0-9_]+)`\s*\|", section, re.M)


# ---------------------------------------------------------------- ① 门名逐字一致
def test_doc_exists_and_door_names_match_defs() -> None:
    """文档存在，21 道门名与 `gates/defs/*.py` 的 `GATES` **逐字一致**（顺序也一致）。"""
    assert DOC.is_file(), f"缺文档：{DOC}"
    text = DOC.read_text(encoding="utf-8")
    want = door_table_names()
    assert len(want) == 21, f"门表里现在是 {len(want)} 道（本页口径按 21 道写）"
    assert doc_door_names(text) == want, (
        f"门名对不上：\n文档 {doc_door_names(text)}\n门表 {want}")


def test_doc_door_drift_is_caught() -> None:
    """★ 反向验证：把某道门名改错一个字，同一个检查函数必须报出来。"""
    text = DOC.read_text(encoding="utf-8")
    assert doc_door_names(text) == door_table_names()
    broken = text.replace("| `ruff` |", "| `ruf` |", 1)
    assert doc_door_names(broken) != door_table_names(), "门名改错了却照样判一致"


# ---------------------------------------------------------------- ② 五维
def test_five_dimensions_present() -> None:
    """五维关键词都在，且各自出现在五维表的取值列。"""
    text = DOC.read_text(encoding="utf-8")
    section = text.split("## 2. 五维", 1)[1].split("## 3.", 1)[0]
    for word in ("档位", "域", "选测", "夜间", "异机"):
        assert f"| {word} |" in section, f"五维表里缺「{word}」这一维"


def test_three_tables_present() -> None:
    """三张表（门清单 / 红门处置 / 时机）都在。"""
    text = DOC.read_text(encoding="utf-8")
    for title in ("表一：21 道门清单表", "表二：红门处置表", "表三：时机表"):
        assert title in text, f"缺 {title}"
    assert text.count("`--only ") >= 10, "红门处置表没有逐门给 `--only` 重跑命令"


# ---------------------------------------------------------------- ③ 决策树里的档位名
def test_decision_tree_names_are_real_args() -> None:
    """决策树里的每个 `--开关` 都必须被 `run_gates.py` 或 `landing.py` 的 parser 认。"""
    text = DOC.read_text(encoding="utf-8")
    tree = text.split("## 3. 决策树", 1)[1].split("## 4.", 1)[0]
    tokens = sorted(set(re.findall(r"--[a-z][a-z-]+", tree)))
    assert tokens, "决策树里一个开关都没有"

    import run_gates as rg
    from pool import landing

    gate_opts = {opt for act in rg.build_parser()._actions for opt in act.option_strings}
    # landing 的 parser 在 `main()` 里就地建（没有独立工厂）⇒ 用 `--help` 现取，
    # 不另写第二份参数表（那正是本钉子要防的「两套」）。
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), pytest.raises(SystemExit):
        landing.main(["--help"])
    land_opts = set(re.findall(r"--[a-z][a-z-]+", buf.getvalue()))
    assert land_opts, "读不到 landing 的参数表"

    known = gate_opts | land_opts
    unknown = [t for t in tokens if t not in known]
    assert not unknown, f"决策树里写了工具不认的开关：{unknown}"
    # 档位名必须落在**门禁工具**里（不许只落在落地链里）
    for flag in ("--fast", "--quick", "--profiles", "--only", "--affected", "--seal"):
        if flag in tokens:
            assert flag in gate_opts, f"`{flag}` 不在 run_gates.py 的参数里"


# ---------------------------------------------------------------- ④ 技能链接
def test_skill_link_exists() -> None:
    """文档链到 `skills/pipe-gate/SKILL.md`，且那个文件真存在。"""
    text = DOC.read_text(encoding="utf-8")
    assert "skills/pipe-gate/SKILL.md" in text, "文档没有指向 pipe-gate 技能"
    assert (ROOT / "skills" / "pipe-gate" / "SKILL.md").is_file()


# ---------------------------------------------------------------- ⑤ 每条耗时都带出处
_TIME_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:s\b|min\b|分钟|秒)")
_SOURCE_RE = re.compile(r"源：|gates/last\.json|gates/diag/|gates/logs/")


def unsourced_time_blocks(text: str) -> list[str]:
    """没有出处的耗时行（**按表格块判**：表头/任一格写了 `源：` 就算整块有出处）。"""
    bad: list[str] = []
    block: list[str] = []
    inside_fence = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            inside_fence = not inside_fence
        if inside_fence:
            continue
        if line.lstrip().startswith("|"):
            block.append(line)
            continue
        if block:
            if any(_TIME_RE.search(x) for x in block) and not any(
                    _SOURCE_RE.search(x) for x in block):
                bad.append("\n".join(block))
            block = []
        if _TIME_RE.search(line) and not _SOURCE_RE.search(line):
            bad.append(line)
    if block and any(_TIME_RE.search(x) for x in block) and not any(
            _SOURCE_RE.search(x) for x in block):
        bad.append("\n".join(block))
    return bad


def test_every_duration_has_a_source() -> None:
    """文档里每个耗时/读数都要标出处（`源：gates/last.json` 这类）。"""
    text = DOC.read_text(encoding="utf-8")
    bad = unsourced_time_blocks(text)
    joined = "\n---\n".join(bad)
    assert not bad, f"这些耗时没有出处：\n\n{joined}"


# ---------------------------------------------------------------- ⑥ `--only` 半趟必红
def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=str(repo),
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=False)


def _repo_with_last_json(tmp_path: Path, payload: dict) -> tuple[Path, str]:
    """建一个只有 `gates/last.json` 的小 git 仓，返回 `(仓, 父提交短 sha)`。

    ★ 两笔提交：第一笔给「父提交」一个真实 sha，第二笔把这个 sha 写进 `last.json.rev`
      再提交 —— 这样 `check_gates(s, repo, parent)` 的 `rev == 父提交` 那条才成立。
    """
    repo = tmp_path / "repo"
    (repo / "gates").mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "nail@example.invalid")
    _git(repo, "config", "user.name", "nail")
    (repo / "README.md").write_text("x\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    parent = _git(repo, "rev-parse", "--short", "HEAD").stdout.strip()
    (repo / "gates" / "last.json").write_text(
        json.dumps({**payload, "rev": parent}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "gates")
    return repo, parent


def _all_doors() -> list[str]:
    import run_gates as rg

    return [str(n) for n, _ in rg.build_jobs(False, False)]


def test_only_payload_is_red_in_wb_verify(tmp_path: Path) -> None:
    """`--only` 落盘的半趟读数 ⇒ `wb_verify.check_gates` 必须判红（不许拿半趟当全量）。"""
    doors = _all_doors()
    payload = {
        "ok": True, "tree": "", "tree_scope": "worktree-minus-gates",
        "gates": [{"name": "ruff", "exit_code": 0, "seconds": 0.2,
                   "summary": "All checks passed!"}],
        "not_run": [n for n in doors if n != "ruff"],
        "only": ["ruff"], "only_counts": f"1/{len(doors)}",
    }
    repo, head = _repo_with_last_json(tmp_path, payload)
    wb_verify = _load("_e52_wb_verify_for_docs", TOOLS / "wb_verify.py")
    s = wb_verify.Screen()
    wb_verify.check_gates(s, repo, head)
    assert s.fails >= 1, "半趟读数（只跑了 1 道门）居然判绿"

    # 对照：同一份产物补齐 21 道门 ⇒ 不红（证明这条不是「永远红」）
    full = {**payload, "gates": [{"name": n, "exit_code": 0} for n in doors], "not_run": []}
    full.pop("only")
    full.pop("only_counts")
    repo2, head2 = _repo_with_last_json(tmp_path / "full", full)
    s2 = wb_verify.Screen()
    wb_verify.check_gates(s2, repo2, head2)
    assert s2.fails == 0, "全量形状的反例被误判红了"


def test_only_unknown_door_exits_2_and_lists_names() -> None:
    """★ 反向验证：`--only` 写错门名 ⇒ 退 2 且列出可用门名（不许猜、不许跑空趟）。"""
    done = subprocess.run(
        [sys.executable, "-X", "utf8", str(SCRIPTS / "run_gates.py"), "--only", "不存在的门"],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (done.stdout or "") + (done.stderr or "")
    assert done.returncode == 2, out
    assert "不认识的门名" in out, out
    assert "可用门名" in out, out
    for name in _all_doors():
        assert name in out, f"可用门名里少了 {name}"
