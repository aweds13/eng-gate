"""check_layers.py 的正负样例自测（护栏脚本必须有）。

用法：python -X utf8 scripts/test_check_layers.py
退出码 0 = 全部用例通过。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
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


def main() -> int:
    failures: list[str] = []

    # --- 正样例：当前仓库应 PASS ---
    code, out = run_check()
    print(f"[正样例] 干净仓库 → exit={code}")
    if code != 0:
        failures.append(f"干净仓库应 PASS，实际: {out.strip()[:200]}")

    # --- 负样例 1：约定层插入无 N 标注的规则 → 应 FAIL ---
    code, out = with_injected(CONV, "\n- 故意无来源标注的测试规则。\n")
    print(f"[负样例1] 约定层缺 N 标注 → exit={code}")
    if code == 0 or "未标注来源 N" not in out:
        failures.append(f"应抓出缺 N 标注，实际: {out.strip()[:200]}")

    # --- 负样例 2：README 插入断链引用 → 应 FAIL ---
    code, out = with_injected(README, "\n> 测试：见 `contracts/绝不存在的文件.md`\n")
    print(f"[负样例2] 断链引用 → exit={code}")
    if code == 0 or "引用断裂" not in out:
        failures.append(f"应抓出断链引用，实际: {out.strip()[:200]}")

    # --- 负样例 3：契约层引用不存在的 SR → 应 FAIL ---
    flows = ROOT / "docs" / "contracts" / "flows.md"
    code, out = with_injected(flows, "\n> 测试引用：SR-F99.9\n")
    print(f"[负样例3] 契约层引用未知 SR → exit={code}")
    if code == 0 or "不存在的 SR" not in out:
        failures.append(f"应抓出未知 SR，实际: {out.strip()[:200]}")

    # --- 负样例 4：覆盖矩阵缺 SR-F10 → 应 FAIL ---
    coverage = ROOT / "docs" / "implementation" / "coverage.md"
    code, out = with_removed(coverage, "| SR-F10 ")
    print(f"[负样例4] 覆盖矩阵缺 SR-F10 → exit={code}")
    if code == 0 or "覆盖矩阵缺 SR-F10" not in out:
        failures.append(f"应抓出覆盖矩阵缺 SR-F10，实际: {out.strip()[:200]}")

    # --- 豁免用例：待建文件（DESIGN.md）不应被报断链 ---
    code, out = run_check()
    if "DESIGN.md" in out and "引用断裂" in out:
        failures.append("DESIGN.md 应被豁免，但仍被报断链")

    # --- 新规则正样例（T-G127）：引用 gitignored 产物（不存在但被 git 忽略）→ 应跳过，不报断链 ---
    code, out = with_injected(
        README, "\n> 测试：见 `gates/diag/绝不存在的产物-别创建-T-G127.md`\n"
    )
    print(f"[正样例2] gitignored 产物引用被跳过 → exit={code}")
    if code != 0 or "引用断裂" in out:
        failures.append(f"gitignored 产物引用应被跳过，实际: {out.strip()[:200]}")

    # --- 新规则负样例（T-G127）：引用不存在的受版本管理文件 → 必须仍 FAIL ---
    code, out = with_injected(
        README, "\n> 测试：见 `docs/绝不存在的受管文件-T-G127.md`\n"
    )
    print(f"[负样例5] 受管文件断链仍咬 → exit={code}")
    if code == 0 or "引用断裂" not in out:
        failures.append(f"受管文件断链应仍被抓，实际: {out.strip()[:200]}")

    print()
    if failures:
        print("SELF-TEST FAIL ❌")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("SELF-TEST PASS ✅ （2 正样例 + 5 负样例 + 1 豁免用例）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
