"""契约段 ↔ 判据对账器（卡 217 · T-G330）的反例钉子。

这个工具的价值全在**判据真去执行**上：不是扫一遍文档看字符串像不像，而是对每条 `judge:`
**当场跑一次**贴读数。所以这张测试钉六条：

| # | 钉子 | 坏掉会红在哪 |
|---|---|---|
| ① | 一条契约段 + 一条真判据 ⇒ 绿 | 对账器把好的判成坏的 |
| ② | judge 指向**不存在**的脚本 ⇒ 红并**点名** | 指针烂了没人管 |
| ③ | no_judge ⇒ 非零（如实，不是失败但不是绿） | 把「只有话」当「有判据」 |
| ④ | 源文件不存在 / 锚点找不到 ⇒ 优雅处理并说清 | 坏文档让工具崩 |
| ⑤ | ★ **反例**：判据名写错一个字 ⇒ 必须红 | 证明它真去**执行**，不是只看字符串像不像 |
| ⑥ | ★ **真仓**对账：10 judge_ok / 3 no_judge（如实） | 美化「只有话」的条数 |
| ⑦ | ★ E96：CX-01 的**合成判据**真能证那句话（`skills/` 有无都绿） | 只核格式 ⇒ 证不了那句话 |

★ 只读：这里不写真仓的 CONTRACTS（临时契约段都落在 `tmp_path`），也不跑门禁。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import contract_audit as ca  # noqa: E402 —— 需要先用 sys.path 把 tools/ 挂上

#: 子进程不弹窗（真源在 `tools/pool/no_window.py`；这里复用 `contract_audit` 自己那份，
#: ★ 别在本文件另写一份 —— 两份迟早漂）。
NO_WINDOW: dict[str, int] = ca.NO_WINDOW


def _write_doc(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "rules.md"
    path.write_text(body, encoding="utf-8", newline="\n")
    return path


def _write_judge_ok(tmp_path: Path, name: str = "check.py") -> str:
    """在 tmp_path 写一个退 0 的判据脚本，回它的相对名。"""
    (tmp_path / name).write_text("import sys; sys.exit(0)\n", encoding="utf-8")
    return name


# ------------------------------------------------------------------ ① 真判据 ⇒ 绿


def test_one_contract_with_real_judge_is_green(tmp_path: Path) -> None:
    """一条契约段 + 一条真判据（退 0）⇒ 对账结果 judge_ok。"""
    _write_doc(tmp_path, "# 规矩\n删掉 skills 框架仍完整可用。\n")
    judge_name = _write_judge_ok(tmp_path)
    c = ca.Contract(
        cid="CX-T1",
        source=("rules.md", "删掉 skills 框架仍完整可用"),
        judge=("cmd", ["python", judge_name]),
    )
    results = ca.audit([c], tmp_path)
    assert len(results) == 1
    r = results[0]
    assert r.status == "judge_ok", f"应绿，实 {r.status}：{r.reason}"
    assert r.source_line == 2
    assert "删掉 skills 框架仍完整可用" in r.source_text
    assert r.judge_rc == 0


# ------------------------------------------------------------------ ② judge 指向不存在 ⇒ 红并点名


def test_judge_pointing_at_nonexistent_script_is_red_and_names_it(
    tmp_path: Path,
) -> None:
    """judge 指向不存在的脚本 ⇒ judge_red，且结果带那条的 id（点名）。"""
    _write_doc(tmp_path, "# 规矩\n某不变量。\n")
    c = ca.Contract(
        cid="CX-T2",
        source=("rules.md", "某不变量"),
        judge=("cmd", ["python", "no_such_check.py"]),
    )
    results = ca.audit([c], tmp_path)
    r = results[0]
    assert r.status == "judge_red", f"指向不存在的判据必须红，实 {r.status}"
    assert r.cid == "CX-T2"  # 点名
    assert r.judge_rc != 0
    assert r.reason  # 有说清为什么红


# ------------------------------------------------------------------ ③ no_judge ⇒ 非零（如实）


def test_no_judge_is_honest_nonzero(tmp_path: Path) -> None:
    """一条契约段 + no_judge ⇒ status=no_judge，且不算 ok（退出码非零的依据）。"""
    _write_doc(tmp_path, "# 规矩\n某目标态。\n")
    c = ca.Contract(
        cid="CX-T3",
        source=("rules.md", "某目标态"),
        no_judge="这是目标态，现状不满足，要等另一条卡",
    )
    results = ca.audit([c], tmp_path)
    r = results[0]
    assert r.status == "no_judge"
    assert not r.ok  # no_judge 不算 ok ⇒ 退出码非零
    assert r.judge_rc is None  # 没跑判据


# ------------------------------------------------------------------ ④ 坏文档 ⇒ 优雅处理


def test_missing_source_file_is_handled_gracefully(tmp_path: Path) -> None:
    """源文件不存在 ⇒ source_missing（不崩，说清）。"""
    c = ca.Contract(
        cid="CX-T4a",
        source=("no_such_file.md", "某契约"),
        judge=("cmd", ["python", "-c", "exit(0)"]),
    )
    results = ca.audit([c], tmp_path)
    r = results[0]
    assert r.status == "source_missing"
    assert not r.ok
    assert r.source_line is None


def test_anchor_not_found_is_handled_gracefully(tmp_path: Path) -> None:
    """源文件在但锚点子串找不到 ⇒ source_missing（不崩，说清）。"""
    _write_doc(tmp_path, "# 规矩\n这里没有那句契约。\n")
    c = ca.Contract(
        cid="CX-T4b",
        source=("rules.md", "不存在的锚点子串"),
        judge=("cmd", ["python", "-c", "exit(0)"]),
    )
    results = ca.audit([c], tmp_path)
    r = results[0]
    assert r.status == "source_missing"
    assert not r.ok
    assert "锚点" in r.reason or "找不到" in r.reason


# ------------------------------------------------------------------ ⑤ ★ 反例：判据名写错一个字 ⇒ 红


def test_typo_in_judge_name_bites(tmp_path: Path) -> None:
    """★ 反例：把判据名写错一个字 ⇒ 必须红。

    证明对账器真去**解析并执行**判据，不是只看字符串像不像：真判据是 `check.py`（退 0），
    写错成 `chekc.py`（不存在）⇒ subprocess 真去跑那个不存在的脚本 ⇒ 红。
    """
    _write_doc(tmp_path, "# 规矩\n某不变量。\n")
    _write_judge_ok(tmp_path, "check.py")  # 真判据在
    c = ca.Contract(
        cid="CX-T5",
        source=("rules.md", "某不变量"),
        judge=("cmd", ["python", "chekc.py"]),  # ★ 写错一个字
    )
    results = ca.audit([c], tmp_path)
    r = results[0]
    assert r.status == "judge_red", f"写错判据名必须红，实 {r.status}"
    assert r.judge_rc != 0


# ------------------------------------------------------------------ ⑥ ★ 真仓对账如实


def _cli_available() -> bool:
    """本仓 CLI 在不在（决定 CX-02 是「真判」还是「未验证」）。"""
    import shutil

    return (ca.ROOT / "framework" / "cli" / "main.py").is_file() or bool(shutil.which("pipe"))


def test_real_repo_audit_has_expected_shape() -> None:
    """★ 真仓 13 条契约段：0 judge_red / 0 source_missing，且 judge_ok + no_judge == 13。

    钉的是「别美化」：
      · 有 CLI 的机器 —— 10 judge_ok / 3 no_judge（框架泛用性三条目标态，一条都不许漏列）；
      · 没有 CLI 的机器（云机）—— 9 / 4：CX-02 自报未验证（rc=3），如实落 no_judge。
        卡 E49：既不许把未验证算成绿（漏真违约），也不许算成红（假红）。
    """
    results = ca.audit(ca.CONTRACTS, ca.ROOT)
    by_status: dict[str, int] = {}
    for r in results:
        by_status[r.status] = by_status.get(r.status, 0) + 1
    assert sum(by_status.values()) == 13, f"契约段应为 13 条，实 {sum(by_status.values())}"
    assert by_status.get("source_missing", 0) == 0, "源文件或锚点找不到 ⇒ 配置烂了，不是契约问题"
    reds = [r.cid for r in results if r.status == "judge_red"]
    assert by_status.get("judge_red", 0) == 0, f"判据跑红 ⇒ 有判据的那几条契约没守住：{reds}"
    ok, no = by_status.get("judge_ok", 0), by_status.get("no_judge", 0)
    assert ok + no == 13, f"judge_ok({ok}) + no_judge({no}) 应等于 13"
    if _cli_available():
        assert (ok, no) == (10, 3), f"有 CLI 时应 10 judge_ok / 3 no_judge，实 {ok}/{no}"
    else:
        assert (ok, no) == (9, 4), f"没有 CLI 时应 9 judge_ok / 4 no_judge，实 {ok}/{no}"


def test_judge_reporting_not_verified_is_neither_green_nor_red(tmp_path: Path) -> None:
    """★ 卡 E49：判据退 **3**（自报未验证）⇒ 落 no_judge，不算 judge_ok，也不算 judge_red。

    反向意义：把 rc=3 当红 ⇒ 云机（没 CLI）上 CX-02 假红；当绿 ⇒ 真违约被漏掉。
    """
    _write_doc(tmp_path, "# 规矩\n某不变量。\n")
    script = tmp_path / "unverified.py"
    script.write_text("import sys\nprint('这台机器缺前置')\nsys.exit(3)\n", encoding="utf-8")
    c = ca.Contract(
        cid="CX-NV",
        source=("rules.md", "某不变量"),
        judge=("cmd", ["python", str(script)]),
    )
    r = ca.audit([c], tmp_path)[0]
    assert r.status == "no_judge", f"rc=3 应落 no_judge，实 {r.status}"
    assert r.judge_rc == 3
    assert "未验证" in r.reason


# ------------------------------------------- ⑦ 卡 E96：CX-01 的合成判据真能证那句话


#: 门表构建链要的那几个文件（`scripts/run_gates.py` + 它的三件工具 + 四份 `gates/defs/`）。
#: ★ 只搬这一串：整棵 `tools/` 有 3.7 MB / 166 个文件，判据慢下来就成了新问题。
_GATE_TABLE_FILES = (
    "scripts/run_gates.py",
    "tools/failure_group.py",
    "tools/gate_verdict.py",
    "tools/pipe_root.py",
    "gates/defs/__init__.py",
    "gates/defs/contract.py",
    "gates/defs/lang_python.py",
    "gates/defs/product_timeflow.py",
    "gates/defs/domains.py",
)

#: 在临时树里真 import 一次门表构建器，把 audit 档的门名打出来。
#: ★ `scripts/` 与 `tools/` 都得上 `sys.path`：`run_gates` 自己会插 `tools/`，
#:   但它自己不 import 得到（只插 `tools/` ⇒ ModuleNotFoundError: run_gates）。
_BUILD_GATES = (
    "import json, sys\n"
    "sys.path.insert(0, 'tools')\n"
    "sys.path.insert(0, 'scripts')\n"
    "sys.path.insert(0, '.')\n"
    "import run_gates as rg\n"
    "print(json.dumps({'audit': [n for n, _ in rg.build_jobs(False, False, 'audit')],\n"
    "                  'root': str(rg.ROOT)}))\n"
)


def _gate_table_without_a_real_skills_tree(tmp_path: Path) -> Path:
    """造一棵「有门表构建链、没有 skills/」的临时树（产物不碰真仓库一个字节）。"""
    import shutil

    for rel in _GATE_TABLE_FILES:
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, dst)
    assert not (tmp_path / "skills").exists(), "★ 合成树里不该有 skills/（有就证明不了那句话）"
    return tmp_path


def _run_build_gates(root: Path) -> tuple[int, str, str]:
    """在 `root` 里跑一次门表构建，回 (rc, stdout, stderr)。"""
    r = subprocess.run(  # noqa: S603 —— argv 受控（本仓路径），非外部输入
        [sys.executable, "-X", "utf8", "-c", _BUILD_GATES],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        **NO_WINDOW,
    )
    return r.returncode, r.stdout, r.stderr


def test_card_e96_audit_gate_table_builds_without_skills(tmp_path: Path) -> None:
    """★ 卡 E96 · CX-01 的合成判据：**没有 `skills/` 也能构建 audit 档门表**。

    这正是 CX-01 那句话（「删掉整个 `skills/` 目录，框架仍然完整可用」）能验的最小形态：
    门表构建是框架的骨架，它不读 `skills/` 就不该因为 `skills/` 不在而塌。
    ★ 反例意义：判据若退回旧形态（只核 SKILL.md 格式），`skills/` 一删它自己就搜不到文件、
    这条一红 —— 证明「绿」不是空转。
    """
    root = _gate_table_without_a_real_skills_tree(tmp_path)
    rc, out, err = _run_build_gates(root)
    assert rc == 0, f"没有 skills/ 也构建得出来，实 rc={rc}\nSTDOUT:{out}\nSTDERR:{err}"
    import json

    payload = json.loads(out.strip().splitlines()[-1])
    assert payload["audit"] == [
        "audit",
        "invariants",
        "audit_titles",
        "docs",
        "skills_claims",
    ], payload
    # 没串到真仓库：ROOT 解析的是那棵临时树（否则这条钉的是本仓而不是「拿掉 skills/」）
    assert Path(payload["root"]).resolve() == root.resolve(), payload


def test_card_e96_cx01_judge_is_the_synthetic_one_not_the_format_checker() -> None:
    """★ 卡 E96 判据 5 的**绑定钉子**：CX-01 挂的判据必须还是那条合成用例。

    没有这一条，判据 5 就只有「用例自己绿」—— 把 `judge` 改回旧形态（只核 SKILL.md 格式）
    照样全绿，改了个寂寞。这里钉死三件事：种类是 pytest、点的是本卡那条用例、
    **不指向 `check_skills`**（旧形态的名字里带它）。
    """
    cx = next(c for c in ca.CONTRACTS if c.cid == "CX-01")
    assert cx.judge is not None, "CX-01 不许退回只有话"
    kind, test_id = cx.judge[0], cx.judge[1]
    assert kind == "pytest", f"CX-01 判据应换成 pytest，实 {kind}"
    assert "check_skills" not in test_id, f"退回只核格式的旧判据了：{test_id}"
    assert test_id.endswith("test_card_e96_audit_gate_table_builds_without_skills"), test_id
    # 指到的用例真在这个文件里（pytest 点名收不到时会 rc=4，落成 judge_red —— 但那太晚）
    rel, _, name = test_id.partition("::")
    body = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
    assert f"def {name}(" in body, f"{rel} 里没有 {name}"


def test_card_e96_audit_gate_table_is_the_same_when_skills_exists(tmp_path: Path) -> None:
    """★ 卡 E96 的反面：`skills/` **在**时门表也不变 —— 证明这条判据不是「靠 skills 不在才绿」。"""
    import json

    root = _gate_table_without_a_real_skills_tree(tmp_path)
    without: tuple[int, str, str] = _run_build_gates(root)
    (root / "skills").mkdir()
    (root / "skills" / "README.md").write_text("# 占位\n", encoding="utf-8")
    with_skills = _run_build_gates(root)
    assert without[0] == with_skills[0] == 0, (without, with_skills)
    assert json.loads(without[1].strip().splitlines()[-1])["audit"] == json.loads(
        with_skills[1].strip().splitlines()[-1]
    )["audit"]


def test_main_returns_nonzero_when_there_are_no_judge(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """有 no_judge 时 main() 退非零（如实反映「还有多少条只有话」）。"""
    _write_doc(tmp_path, "# 规矩\n某目标态。\n")
    c = ca.Contract(
        cid="CX-M1",
        source=("rules.md", "某目标态"),
        no_judge="目标态，没守住",
    )
    # main() 用模块级 CONTRACTS；这里直接验 audit 的退出码逻辑
    results = ca.audit([c], tmp_path)
    rc = 0 if all(r.ok for r in results) else 1
    assert rc == 1  # 有 no_judge ⇒ 非零
