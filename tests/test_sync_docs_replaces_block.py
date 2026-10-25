"""卡 E38（T-AG492）：汇总器**按「台账号 + 块类型」替换**，不再按标题去重。

病（E28 现场，2026-10-25）：把 changelog 片段标题里一句「扫本笔改到的 `.md` 反引号引用」改成
「Markdown 反引号引用」⇒ 旧口径判"这段内容还没汇总过" ⇒ **再追加一块**，`docs/changelog.md`
里同一个台账号出现两份（旧那份还带裸 `.md`，`check_layers` 判引用断裂红）；更糟的是
`sync_docs.py --check` 只查「每个片段都在汇总里」，**汇总里多出来的旧块照样绿** —— 静默。

这份用例钉七条（判据 ≥5）：
1. changelog 改标题 ⇒ **原地换**，块数仍 1；
2. changelog 汇总完 `--check` **绿**（正对照：证明判据不是永远红）；
3. 手工塞进第二个同号块 ⇒ `--check` **红**并点名通道 / 台账号 / 块数（孤儿块判据）；
4. 片段被删（git 跟踪过）⇒ `--check` 仍**红**（卡 159 的反方向判据没被这次改动打穿）；
5. traceability 通道：同键改内容 ⇒ 原地换，不新增第二个 `[entries."X"]`；
6. 交接通道：改标题 ⇒ 原地换，块数仍 1；
7. E28 现场的收口形态：旧块 + 新块并存时再汇总一次 ⇒ **只剩一块**（旧块被收掉）。
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import sync_docs as sd  # noqa: E402 —— 需要先用 sys.path 把 tools/ 挂上

CL = "## 2026-10-02 —— 示例：片段 A（T-G204 / 卡 108）\n\n- 病：示例。\n- 修：示例。\n"
TRACE = (
    '[entries."T-G204"]\n'
    'id = "T-G204"\n'
    'title = "示例条目 A"\n'
    'group = "OPS"\n'
    'status = "done"\n'
    'evidence = ["file:tools/sync_docs.py"]\n'
    'gaps = ""\n'
)
HANDOFF = (
    "> **2026-10-02 · CHECKPOINT（卡 108 · `T-G204`）—— 示例 A**：\n"
    "> 一行说明。\n"
)


def _mkroot(tmp_path: Path) -> Path:
    """最小仓库骨架（三个共享文档 + 三个片段目录），形态贴近真文件。"""
    (tmp_path / "docs" / "changelog.d").mkdir(parents=True)
    (tmp_path / "docs" / "traceability.d").mkdir(parents=True)
    (tmp_path / "复盘" / "交接.d").mkdir(parents=True)
    (tmp_path / "docs" / "changelog.md").write_text(
        "## 2026-10-01 —— 旧节（T-G001）\n\n- 旧内容。\n", encoding="utf-8"
    )
    (tmp_path / "docs" / "traceability.toml").write_text(
        '# 头注释\n\n[meta]\nx = 1\n\n[entries."T-G001"]\nid = "T-G001"\nstatus = "done"\n',
        encoding="utf-8",
    )
    (tmp_path / "复盘" / "交接-重构进度.md").write_text(
        "# 交接\n\n> 引言。\n\n"
        "> **2026-10-01 · CHECKPOINT（卡 1 · `T-G001`）—— 旧**：\n"
        "> 旧一行。\n",
        encoding="utf-8",
    )
    return tmp_path


def _write(tmp: Path, name: str, text: str) -> None:
    (tmp / name).write_text(text, encoding="utf-8")


def _read(tmp: Path, name: str) -> str:
    return (tmp / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------- 1. 改标题 ⇒ 原地换


def test_changed_title_replaces_instead_of_appending(tmp_path: Path) -> None:
    """★ E28 现场：标题改了 ⇒ 同一个台账号**仍只有一节**（旧实现会变两节）。"""
    root = _mkroot(tmp_path)
    _write(root, "docs/changelog.d/T-G204.md", CL)
    assert sd.run(root, check=False) == 0
    assert _read(root, "docs/changelog.md").count("T-G204") == 1

    # 只改标题里的一句（台账号不变）—— 旧口径会认为"这段没汇总过"
    new = CL.replace("示例：片段 A", "示例：片段 A（Markdown 反引号引用）")
    _write(root, "docs/changelog.d/T-G204.md", new)
    assert sd.run(root, check=False) == 0

    text = _read(root, "docs/changelog.md")
    assert text.count("（T-G204 / 卡 108）") == 1, f"同一个台账号出现了多节：\n{text}"
    assert "Markdown 反引号引用" in text, "新标题没进去（换成了旧内容？）"
    assert "示例：片段 A（T-G204 / 卡 108）" not in text, "旧标题那一块没被换掉"


def test_check_is_green_after_replace(tmp_path: Path) -> None:
    """正对照：替换之后 `--check` 必须绿（证明第 3 条的"红"不是永远红）。"""
    root = _mkroot(tmp_path)
    _write(root, "docs/changelog.d/T-G204.md", CL)
    assert sd.run(root, check=False) == 0
    _write(root, "docs/changelog.d/T-G204.md", CL.replace("示例：片段 A", "示例：片段 A（改）"))
    assert sd.run(root, check=False) == 0
    assert sd.run(root, check=True) == 0  # 块数 1 ⇒ 无孤儿


# ---------------------------------------------------------------- 2. 孤儿块判据


def test_check_reds_on_a_second_block_for_one_unit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """★ 新判据：同一台账号被追加了第二份 ⇒ `--check` **红**并点名（不许降级成 info）。"""
    root = _mkroot(tmp_path)
    _write(root, "docs/changelog.d/T-G204.md", CL)
    assert sd.run(root, check=False) == 0

    # 模拟"旧块没被换掉"留下的孤儿：手工再塞一份（内容不同，但标题里还是同一个号）
    p = root / "docs" / "changelog.md"
    orphan = "## 2026-10-02 —— 示例：片段 A（旧版本，T-G204）\n\n- 旧。\n"
    p.write_text(_read(root, "docs/changelog.md") + orphan, encoding="utf-8")

    assert sd.run(root, check=True) == 1
    out = capsys.readouterr().out
    assert "[FAIL]" in out, out
    assert "T-G204" in out, out
    assert "2 块" in out, out
    assert "孤儿块" in out, out


def test_merge_collapses_an_existing_duplicate(tmp_path: Path) -> None:
    """★ E28 的收口形态：旧块 + 新块并存 ⇒ 再汇总一次**只剩一块**（多余的收掉）。"""
    root = _mkroot(tmp_path)
    _write(root, "docs/changelog.d/T-G204.md", CL)
    assert sd.run(root, check=False) == 0
    p = root / "docs" / "changelog.md"
    p.write_text(
        _read(root, "docs/changelog.md")
        + "## 2026-10-02 —— 示例：片段 A（旧版，T-G204）\n\n- 旧。\n",
        encoding="utf-8",
    )
    # 片段也改了（触发汇总）⇒ 该号的两块合成一块
    _write(root, "docs/changelog.d/T-G204.md", CL.replace("示例：片段 A", "示例：片段 A（二版）"))
    assert sd.run(root, check=False) == 0
    text = _read(root, "docs/changelog.md")
    assert text.count("（旧版，T-G204）") == 0, text
    assert text.count("（T-G204 / 卡 108）") == 1, text
    assert "（二版）" in text, text
    assert sd.run(root, check=True) == 0


# ---------------------------------------------------------------- 3. 卡 159 的反方向没被打穿


def test_deleted_fragment_still_reds(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """片段被删（git 跟踪过）⇒ 仍判红（这次改动**没有**顺手放宽旧判据）。"""
    root = _mkroot(tmp_path)
    _write(root, "docs/changelog.d/T-G204.md", CL)
    assert sd.run(root, check=False) == 0
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    (root / "docs" / "changelog.d" / "T-G204.md").unlink()

    assert sd.run(root, check=True) == 1
    out = capsys.readouterr().out
    assert "T-G204" in out, out
    assert "片段" in out and ("删" in out or "没了" in out), out


# ---------------------------------------------------------------- 4. 另外两个通道也替换


def test_traceability_replaces_in_place(tmp_path: Path) -> None:
    """traceability：同键改内容 ⇒ **原地换**，不新增第二个表（重复表 TOML 会解析失败）。"""
    root = _mkroot(tmp_path)
    _write(root, "docs/traceability.d/T-G204.toml", TRACE)
    assert sd.run(root, check=False) == 0
    _write(root, "docs/traceability.d/T-G204.toml",
           TRACE.replace("file:tools/sync_docs.py", "file:tools/sync_docs.py\", \"file:tests/x.py"))
    assert sd.run(root, check=False) == 0

    text = _read(root, "docs/traceability.toml")
    assert text.count('[entries."T-G204"]') == 1, text
    assert "file:tests/x.py" in text, "新内容没进去"
    assert sd.run(root, check=True) == 0


def test_handoff_replaces_in_place(tmp_path: Path) -> None:
    """交接：CHECKPOINT 改标题 ⇒ 同一块**原地换**，不插第二段。"""
    root = _mkroot(tmp_path)
    _write(root, "复盘/交接.d/T-G204.md", HANDOFF)
    assert sd.run(root, check=False) == 0
    new = HANDOFF.replace("—— 示例 A", "—— 示例 A（改标题）")
    _write(root, "复盘/交接.d/T-G204.md", new)
    assert sd.run(root, check=False) == 0

    text = _read(root, "复盘/交接-重构进度.md")
    assert text.count("CHECKPOINT（卡 108 · `T-G204`）") == 1, text
    assert "示例 A（改标题）" in text, text
    assert "示例 A**" not in text, f"旧块没被换掉：\n{text}"
    assert sd.run(root, check=True) == 0
