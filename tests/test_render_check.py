"""渲染验证层（T-G32）的测试 —— 不用浏览器也能钉住的那几条纪律。

为什么只测这几条：这一层的主体是"真浏览器 + 逐字节比黄金"，那件事由**门禁里跑一次它本身**来证明
（而且它每轮还会把同一份清单**采两遍**做确定性自检 —— 那是比任何单元测试都硬的证据）。
这里测的是**不需要浏览器就能测的规矩**，尤其是那条最容易被人绕开、也最要紧的一条：
**改黄金必须写理由**（黄金就是判据本身，改判据不留痕，这套东西就退化回"我说它没变"）。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "render_check.mjs"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="环境里没有 node（渲染层本来就跑不了）")


def run_tool(*args: str) -> subprocess.CompletedProcess[str]:
    assert NODE is not None
    return subprocess.run(
        [NODE, str(TOOL), *args],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )


def test_update_without_reason_is_refused() -> None:
    """`--update` 不带 `--reason` → 拒绝，并且**在起服务/起浏览器之前**就退（不能先改了再说）。"""
    proc = run_tool("--update")
    assert proc.returncode == 1
    out = proc.stdout + proc.stderr
    assert "--reason" in out
    assert "黄金是判据" in out


def test_blank_reason_is_refused() -> None:
    """只写空格的理由不算理由。"""
    proc = run_tool("--update", "--reason", "   ")
    assert proc.returncode == 1
    assert "理由" in proc.stdout + proc.stderr


def test_unknown_argument_is_refused() -> None:
    """打错的参数要当场说，不许被当成"没传"静默吞掉。"""
    proc = run_tool("--no-such-flag")
    assert proc.returncode == 1
    assert "未知参数" in proc.stdout + proc.stderr


def test_golden_files_are_readable_manifests() -> None:
    """黄金的格式护栏：缺文件 / 头部对不上 / 行字段数不对 —— 现在就说清，别等门禁里报一堆 diff。

    （数量不写死：视图或宽度增减时这里不该红，红的应该是"忘了 `--update`"那道门禁。）
    """
    files = sorted((ROOT / "gates" / "render").glob("*.txt"))
    assert files, (
        "gates/render 里一份黄金都没有 —— 先跑 "
        "node tools/render_check.mjs --update --reason '为什么'"
    )
    for path in files:
        lines = path.read_text(encoding="utf-8").splitlines()
        assert lines[0].startswith("# render-manifest v1 viewport="), f"{path.name}: 头部不对"
        view = path.name.split("__")[-1].removesuffix(".txt")
        assert f"view={view}" in lines[0], f"{path.name}: 头部里的视图名对不上"
        # 每个元素一行、6 个制表符分隔的字段；行数要和头部的 rows= 一致
        rows = [ln for ln in lines[1:] if ln.strip()]
        assert f"rows={len(rows)}" in lines[0], f"{path.name}: 头部 rows= 与实际行数不符"
        for ln in rows:
            assert len(ln.split("\t")) == 6, f"{path.name}: 有一行不是 6 个字段：{ln[:80]!r}"
