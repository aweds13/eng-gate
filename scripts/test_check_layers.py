"""check_layers.py 的正负样例自测（护栏脚本必须有）。

用法：python -X utf8 scripts/test_check_layers.py
退出码 0 = 全部用例通过。

★ 卡 159（T-G259 / INV-37）：用例重构成**命名用例**（`case_*` 函数），好让
不变量台账的 `nail` 能指到具体用例（`scripts/test_check_layers.py::<用例名>`，
`tools/wb_invariants.py` 已认 `scripts/` 前缀的钉子）。判据要能**证明它看得到东西**：
中文文件名断链的合成坏样例必须被抓（负样例 6）。
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
README = ROOT / "docs" / "README.md"
CONV = ROOT / "docs" / "specification" / "conventions.md"


def run_check() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, "-X", "utf8", str(SCRIPT)],
        capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT),
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def with_injected(path: Path, extra: str) -> tuple[int, str]:
    """临时往文件追加内容，跑检查，再还原。"""
    original = path.read_text(encoding="utf-8")
    try:
        path.write_text(original + extra, encoding="utf-8")
        return run_check()
    finally:
        path.write_text(original, encoding="utf-8")


def with_removed(path: Path, needle: str) -> tuple[int, str]:
    """临时删除文件中的一段内容，跑检查，再还原。"""
    original = path.read_text(encoding="utf-8")
    try:
        path.write_text(original.replace(needle, "", 1), encoding="utf-8")
        return run_check()
    finally:
        path.write_text(original, encoding="utf-8")


# ---------------------------------------------------------------- 命名用例（nail 指到这里的每一个）


def case_clean_repo_passes(failures: list[str]) -> None:
    """正样例：当前仓库应 PASS。"""
    code, out = run_check()
    print(f"[正样例] 干净仓库 → exit={code}")
    if code != 0:
        failures.append(f"干净仓库应 PASS，实际: {out.strip()[:200]}")


def case_missing_n_label_bites(failures: list[str]) -> None:
    """负样例 1：约定层插入无 N 标注的规则 → 应 FAIL。"""
    code, out = with_injected(CONV, "\n- 故意无来源标注的测试规则。\n")
    print(f"[负样例1] 约定层缺 N 标注 → exit={code}")
    if code == 0 or "未标注来源 N" not in out:
        failures.append(f"应抓出缺 N 标注，实际: {out.strip()[:200]}")


def case_broken_link_bites(failures: list[str]) -> None:
    """负样例 2：README 插入断链引用 → 应 FAIL。"""
    code, out = with_injected(README, "\n> 测试：见 `contracts/绝不存在的文件.md`\n")
    print(f"[负样例2] 断链引用 → exit={code}")
    if code == 0 or "引用断裂" not in out:
        failures.append(f"应抓出断链引用，实际: {out.strip()[:200]}")


def case_unknown_sr_bites(failures: list[str]) -> None:
    """负样例 3：契约层引用不存在的 SR → 应 FAIL。"""
    flows = ROOT / "docs" / "contracts" / "flows.md"
    code, out = with_injected(flows, "\n> 测试引用：SR-F99.9\n")
    print(f"[负样例3] 契约层引用未知 SR → exit={code}")
    if code == 0 or "不存在的 SR" not in out:
        failures.append(f"应抓出未知 SR，实际: {out.strip()[:200]}")


def case_missing_coverage_row_bites(failures: list[str]) -> None:
    """负样例 4：覆盖矩阵缺 SR-F10 → 应 FAIL。"""
    coverage = ROOT / "docs" / "implementation" / "coverage.md"
    code, out = with_removed(coverage, "| SR-F10 ")
    print(f"[负样例4] 覆盖矩阵缺 SR-F10 → exit={code}")
    if code == 0 or "覆盖矩阵缺 SR-F10" not in out:
        failures.append(f"应抓出覆盖矩阵缺 SR-F10，实际: {out.strip()[:200]}")


def case_known_missing_is_exempt(failures: list[str]) -> None:
    """豁免用例：待建文件（DESIGN.md）不应被报断链。"""
    code, out = run_check()
    if "DESIGN.md" in out and "引用断裂" in out:
        failures.append("DESIGN.md 应被豁免，但仍被报断链")


def case_gitignored_link_is_skipped(failures: list[str]) -> None:
    """正样例 2（T-G127）：引用 gitignored 产物（不存在但被 git 忽略）→ 应跳过。"""
    code, out = with_injected(
        README, "\n> 测试：见 `gates/diag/绝不存在的产物-别创建-T-G127.md`\n"
    )
    print(f"[正样例2] gitignored 产物引用被跳过 → exit={code}")
    if code != 0 or "引用断裂" in out:
        failures.append(f"gitignored 产物引用应被跳过，实际: {out.strip()[:200]}")


def case_managed_broken_link_still_bites(failures: list[str]) -> None:
    """负样例 5（T-G127）：引用不存在的受版本管理文件 → 必须仍 FAIL。"""
    code, out = with_injected(
        README, "\n> 测试：见 `docs/绝不存在的受管文件-T-G127.md`\n"
    )
    print(f"[负样例5] 受管文件断链仍咬 → exit={code}")
    if code == 0 or "引用断裂" not in out:
        failures.append(f"受管文件断链应仍被抓，实际: {out.strip()[:200]}")


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
          "2 正样例 + 5 负样例 + 1 豁免 + 1 中文断链可见性）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
