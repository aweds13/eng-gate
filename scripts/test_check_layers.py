"""check_layers.py 的正负样例自测（护栏脚本必须有）。

用法：python -X utf8 scripts/test_check_layers.py
退出码 0 = 全部用例通过。

★ 卡 159（T-G259 / INV-37）：用例重构成**命名用例**（`case_*` 函数），好让
不变量台账的 `nail` 能指到具体用例（`scripts/test_check_layers.py::<用例名>`，
`tools/wb_invariants.py` 已认 `scripts/` 前缀的钉子）。判据要能**证明它看得到东西**：
中文文件名断链的合成坏样例必须被抓（负样例 6）。

★★ 本自测**绝不改写真实仓库里受版本管理的文件**：负样例一律在
`tempfile.TemporaryDirectory()` 里搭一棵**只含本用例所需文件**的合成小树，
再跑 `check_layers.py --root <tmp>`，跑完即删。
（老做法是「临时改写 docs/README.md · conventions.md · flows.md · coverage.md、
跑完在 `finally` 里写回」—— 而 `scripts/run_gates.py` 是**同时**起全部轻门的，
那几秒里这些文件在磁盘上**真的**是被改过的：`tests/test_dark_teeth.py` 的
`test_5_self_proof_never_touches_the_repo` 拿 `git status` 前后快照一比，
就报「少了 [' M docs/README.md']」—— 真凶是这道自测自己。）
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import check_layers as check_layers  # noqa: E402 —— 需要先用 sys.path 把 scripts/ 挂上

SCRIPT = ROOT / "scripts" / "check_layers.py"


def run_check() -> tuple[int, str]:
    """对**真实仓库**跑一次（只读 —— 本自测唯一读真实仓库的入口）。"""
    p = subprocess.run(
        [sys.executable, "-X", "utf8", str(SCRIPT)],
        capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT),
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def run_check_at(root: Path) -> tuple[int, str]:
    """对一棵**合成小树**跑一次（`--root <root>`）：真实仓库一个字节都不写。

    `creationflags=CREATE_NO_WINDOW` —— 这仍然是起 console 子进程，带上「不弹窗」的口径
    （`tests/test_no_window.py` 认 `NO_WINDOW` / `creationflags` / `windowsHide` 三者之一）。
    """
    p = subprocess.run(
        [sys.executable, "-X", "utf8", str(SCRIPT), "--root", str(root)],
        capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT),
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def build_tree(root: Path, files: dict[str, str]) -> None:
    """按 `{相对路径: 内容}` 在 root 下造文件（父目录自动建）。"""
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def skeleton_files() -> dict[str, str]:
    """一棵**最小但完整**的合成五层树：`check_layers.py --root` 对它应当 PASS。

    负样例 = 这棵树 + **一处**缺陷 ⇒ 只该红那一条原因（判据作用在它声称的对象上）。
    """
    coverage = "# 覆盖矩阵（合成小树）\n\n" + "".join(
        f"| SR-F{i} | 合成 |\n" for i in range(1, 11)
    )
    files = {
        "docs/intention/needs.md": "# 意图（合成小树）\n",
        "docs/specification/traceability.md": "# 规格追踪（合成小树）\n",
        "docs/implementation/traceability.md": "# 实现追踪（合成小树）\n",
        "docs/specification/conventions.md": (
            "# 约定（合成小树）\n\n- 合成规则自带来源标注（N1）。\n"
        ),
        "docs/contracts/interactions.md": "# 交互契约（合成小树）\n",
        "docs/contracts/flows.md": "# 动线契约（合成小树）\n",
        "docs/implementation/coverage.md": coverage,
    }
    for i in range(1, 11):
        files[f"docs/specification/domains/F{i}-合成.md"] = f"# F{i} 详细规格（合成小树）\n"
        files[f"docs/contracts/domains/F{i}-合成.md"] = f"# F{i} 域契约（合成小树）\n"
    return files


def run_on_synthetic(files: dict[str, str]) -> tuple[int, str]:
    """在临时目录里搭合成小树并跑 `check_layers.py --root <tmp>`；跑完即删。"""
    with tempfile.TemporaryDirectory(prefix="check_layers_selftest_") as td:
        troot = Path(td)
        build_tree(troot, files)
        return run_check_at(troot)


def lines_with(out: str, keyword: str) -> list[str]:
    """输出里含某个关键词的行（点名判据用）。"""
    return [ln for ln in out.splitlines() if keyword in ln]


def only_fail(out: str, expected: str) -> bool:
    """这一趟红**只因为** expected 这一条 —— 其余 `[FAIL]` 一条都没有。"""
    fails = [ln for ln in out.splitlines() if ln.startswith("[FAIL]")]
    return len(fails) == 1 and expected in fails[0]


# ---------------------------------------------------------------- 命名用例（nail 指到这里的每一个）


def case_clean_repo_passes(failures: list[str]) -> None:
    """正样例：当前仓库应 PASS（对真实仓库只读）。"""
    code, out = run_check()
    print(f"[正样例] 干净仓库 → exit={code}")
    if code != 0:
        failures.append(f"干净仓库应 PASS，实际: {out.strip()[:200]}")


def case_missing_n_label_bites(failures: list[str]) -> None:
    """负样例 1：合成树的约定层插入无 N 标注的规则 → 应 FAIL（只因这一条）。"""
    files = skeleton_files()
    files["docs/specification/conventions.md"] += "- 故意无来源标注的测试规则。\n"
    code, out = run_on_synthetic(files)
    print(f"[负样例1] 约定层缺 N 标注 → exit={code}")
    if code == 0 or "未标注来源 N" not in out:
        failures.append(f"应抓出缺 N 标注，实际: {out.strip()[:200]}")
    elif not only_fail(out, "未标注来源 N"):
        failures.append(f"应只因「未标注来源 N」红，实际 FAIL 行: {lines_with(out, '[FAIL]')}")


def case_broken_link_bites(failures: list[str]) -> None:
    """负样例 2：合成树的 README 插入断链引用 → 应 FAIL（并点名断链目标）。"""
    files = skeleton_files()
    files["docs/README.md"] = "# 索引（合成小树）\n\n> 测试：见 `contracts/绝不存在的文件.md`\n"
    code, out = run_on_synthetic(files)
    print(f"[负样例2] 断链引用 → exit={code}")
    if code == 0 or "引用断裂" not in out:
        failures.append(f"应抓出断链引用，实际: {out.strip()[:200]}")
    elif not any("绝不存在的文件.md" in ln for ln in lines_with(out, "引用断裂")):
        failures.append(f"断链要点名目标，实际 FAIL 行: {lines_with(out, '[FAIL]')}")


def case_unknown_sr_bites(failures: list[str]) -> None:
    """负样例 3：合成树的契约层引用不存在的 SR → 应 FAIL（只因这一条，点名 SR-F99.9）。"""
    files = skeleton_files()
    files["docs/contracts/flows.md"] = "# 动线契约（合成小树）\n\n> 测试引用：SR-F99.9\n"
    code, out = run_on_synthetic(files)
    print(f"[负样例3] 契约层引用未知 SR → exit={code}")
    if code == 0 or "不存在的 SR" not in out:
        failures.append(f"应抓出未知 SR，实际: {out.strip()[:200]}")
    elif not only_fail(out, "SR-F99.9"):
        failures.append(f"应只因未知 SR 红，实际 FAIL 行: {lines_with(out, '[FAIL]')}")


def case_missing_coverage_row_bites(failures: list[str]) -> None:
    """负样例 4：合成树的覆盖矩阵缺 SR-F10 → 应 FAIL（只因这一条）。"""
    files = skeleton_files()
    files["docs/implementation/coverage.md"] = "# 覆盖矩阵（合成小树）\n\n" + "".join(
        f"| SR-F{i} | 合成 |\n" for i in range(1, 10)
    )
    code, out = run_on_synthetic(files)
    print(f"[负样例4] 覆盖矩阵缺 SR-F10 → exit={code}")
    if code == 0 or "覆盖矩阵缺 SR-F10" not in out:
        failures.append(f"应抓出覆盖矩阵缺 SR-F10，实际: {out.strip()[:200]}")
    elif not only_fail(out, "覆盖矩阵缺 SR-F10"):
        failures.append(f"应只因覆盖矩阵缺项红，实际 FAIL 行: {lines_with(out, '[FAIL]')}")


def case_known_missing_is_exempt(failures: list[str]) -> None:
    """豁免用例：待建文件（DESIGN.md）不算断链 —— 而同一棵树上真存在的引用照数。

    合成树里两条引用：`DESIGN.md`（待建 ⇒ 豁免、不计入 checked）与 `README.md`
    （真存在 ⇒ 计入）。`checked = 1` 顺带证明「判据真的看到了东西」（不是空转）。
    """
    files = skeleton_files()
    files["docs/README.md"] = (
        "# 索引（合成小树）\n\n> 待建：见 `DESIGN.md`\n> 真文件：见 `README.md`\n"
    )
    code, out = run_on_synthetic(files)
    print(f"[豁免] 待建文件 DESIGN.md → exit={code}")
    if any("DESIGN.md" in ln for ln in lines_with(out, "引用断裂")):
        failures.append("DESIGN.md 应被豁免，但仍被报断链")
    if "这次实际检查了 1 条引用" not in out:
        failures.append(
            f"应检查到 1 条（DESIGN.md 豁免、README.md 计入），实际: {out.strip()[:200]}"
        )


def case_gitignored_link_is_skipped(failures: list[str]) -> None:
    """正样例 2（T-G127）：引用 gitignored 产物（不存在但被 git 忽略）→ 只跳过、不报断链。

    ★ 判据**点名它声称的对象**：这一条引用不许出现在任何 `[FAIL] 引用断裂` 行上，
    并且真的为它打了一行 `[skip]` —— 而不是断言「整趟全绿」（合成树上站不住，
    且会随无关检查的增删假红）。
    """
    subject = "绝不存在的产物"
    files = skeleton_files()
    files["docs/README.md"] = (
        f"# 索引（合成小树）\n\n> 测试：见 `gates/diag/{subject}-别创建-T-G127.md`\n"
    )
    code, out = run_on_synthetic(files)
    print(f"[正样例2] gitignored 产物引用被跳过 → exit={code}")
    accused = [ln for ln in lines_with(out, "引用断裂") if subject in ln]
    if accused:
        failures.append(f"gitignored 产物引用被当成断链报了: {accused}")
    if not any("[skip]" in ln and subject in ln for ln in out.splitlines()):
        failures.append(
            f"gitignored 产物引用应只打一行 [skip]（也没打），实际: {out.strip()[:200]}"
        )


def case_managed_broken_link_still_bites(failures: list[str]) -> None:
    """负样例 5（T-G127）：引用不存在的受版本管理文件 → 必须仍 FAIL（只因这一条）。"""
    files = skeleton_files()
    files["docs/README.md"] = (
        "# 索引（合成小树）\n\n> 测试：见 `docs/绝不存在的受管文件-T-G127.md`\n"
    )
    code, out = run_on_synthetic(files)
    print(f"[负样例5] 受管文件断链仍咬 → exit={code}")
    if code == 0 or "引用断裂" not in out:
        failures.append(f"受管文件断链应仍被抓，实际: {out.strip()[:200]}")
    elif not only_fail(out, "绝不存在的受管文件-T-G127.md"):
        failures.append(f"应只因这一条断链红，实际 FAIL 行: {lines_with(out, '[FAIL]')}")


def case_chinese_broken_link_is_caught(failures: list[str]) -> None:
    """★ 负样例 6（卡 159 / T-G259 / INV-37 的钉子）：判据要能**证明它看得到东西**。

    合成坏样例：中文文件名之间的断链必须被抓（点名引用所在文件与目标），
    中文正常引用不许误报；且返回值带「这次实际检查了几条引用」（门的输出要打出来）。
    红读数（实现前）：`check_link_integrity` 不收 root、不回条数 ⇒ TypeError 当场红。
    """
    with tempfile.TemporaryDirectory() as td:
        troot = Path(td)
        docs = troot / "docs"
        docs.mkdir()
        (docs / "中文-存在.md").write_text("# 存在的中文文件\n", encoding="utf-8")
        (docs / "中文-断链.md").write_text(
            "坏引用：见 `中文-不存在.md`\n好引用：见 `中文-存在.md`\n", encoding="utf-8"
        )
        problems, _notes, checked = check_layers.check_link_integrity(root=troot)
        print(f"[可见性] 合成 docs：实际检查了 {checked} 条引用，断链 {len(problems)} 处")
        if checked != 2:
            failures.append(f"合成 docs 应检查 2 条引用，实际 {checked}")
        if not any("中文-不存在.md" in p for p in problems):
            failures.append(f"中文文件名断链没被抓（判据看不见它）：{problems}")
        if any("中文-存在.md" in p for p in problems):
            failures.append(f"中文正常引用被误报：{problems}")
        if not problems or "中文-断链.md" not in problems[0]:
            failures.append(f"断链要点名引用所在的中文文件：{problems}")


CASES = (
    case_clean_repo_passes,
    case_missing_n_label_bites,
    case_broken_link_bites,
    case_unknown_sr_bites,
    case_missing_coverage_row_bites,
    case_known_missing_is_exempt,
    case_gitignored_link_is_skipped,
    case_managed_broken_link_still_bites,
    case_chinese_broken_link_is_caught,
)


def main() -> int:
    failures: list[str] = []
    for case in CASES:
        case(failures)
    print()
    if failures:
        print("SELF-TEST FAIL ❌")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"SELF-TEST PASS ✅ （{len(CASES)} 条命名用例："
          "2 正样例 + 5 负样例 + 1 豁免 + 1 中文断链可见性；"
          "负样例全部在临时合成小树上跑 `--root`，真实仓库一个字节都不写）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
