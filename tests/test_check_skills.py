"""钉子②（`skills/nails/check_skills.py`）的测试 —— 给「skill 层加严」四条判据上护栏。

两层：
1. **零件层**：`tmp_path` 里造一个假的 `skills/`（一个技能目录 + `SKILL.md` + `NOTES.md`），
   逐条造反例 ⇒ 黑盒跑 `main()` 必须红、且点得出是哪一条；
   全合规 ⇒ 绿（`rc=0`）。
2. **数据层**：拿**真仓库**跑一遍，断言 `rc=0` —— 真 5 份 SKILL + 5 份 NOTES 都过新四条判据。

★ 判据口径（长度 120 行 / 流程 ≤3 / 「怎么读结果」每条指向真脚本 / NOTES.md 三节）写在
  `skills/nails/check_skills.py` 的模块 docstring 里，本测试只**验它真的看得见东西**。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "nails"))

import check_skills as cs  # noqa: E402 —— 需要先把 skills/nails 挂上 sys.path

NAME = "fake-skill"

GOOD_SKILL = """---
name: fake-skill
description: 假技能，只给测试用。
---

# fake-skill

## 什么时候用
- 用。

## 什么时候别用
- 别用。

## 前置检查
1. 有 python。

## 真命令
```bash
python -X utf8 tools/wb_plan.py check
```

## 怎么读结果
- 退 `0`：过（复核：`python -X utf8 tools/wb_plan.py check`）。

## 常见错与处置
| 现象 | 真因 | 处置 |
|---|---|---|
| 红 | 没跑 | 跑 |
"""

GOOD_NOTES = """# fake-skill 人类理解版

## 这一层在防哪类错误
防误用。

## 失败过什么（带读数）
- 造钉子时故意写错命令名：`pipe initt` ⇒ 钉子①红点名。

## 脚本接口与以后怎么改
脚本是 `tools/wb_plan.py`；改判据去库里改。
"""


def _wire(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """把被测模块的两根根指到假树：<tmp>/ 当仓根，<tmp>/skills 当 skills/。"""
    monkeypatch.setattr(cs, "SKILLS_ROOT", tmp_path / "skills")
    monkeypatch.setattr(cs, "REPO_ROOT", tmp_path)


def _build(
    tmp_path: Path,
    *,
    skill: str = GOOD_SKILL,
    notes: str | None = GOOD_NOTES,
    name: str = NAME,
) -> Path:
    """搭假技能目录；顺带放一个「真实存在」的脚本 `tools/wb_plan.py` 给指针指。

    ★ 指针的存在性检查要能真找到文件，所以假树里必须先有一个真 `tools/wb_plan.py`
      —— 否则「合规」那条会因找不到脚本而红（那是验法错，不是被测错）。
    """
    (tmp_path / "tools").mkdir(exist_ok=True)
    (tmp_path / "tools" / "wb_plan.py").write_text("# 桩\n", encoding="utf-8")
    skill_dir = tmp_path / "skills" / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(skill, encoding="utf-8")
    if notes is not None:
        (skill_dir / "NOTES.md").write_text(notes, encoding="utf-8")
    return skill_dir


def _pad_to(text: str, total: int) -> str:
    """把文本补到 `total` 行（用非标题的注释行补，免得顺手改了流程数）。"""
    lines = text.splitlines()
    lines += ["<!-- pad -->"] * max(0, total - len(lines))
    return "\n".join(lines) + "\n"


def _run(tmp_path: Path, monkeypatch, capsys) -> tuple[int, str]:  # type: ignore[no-untyped-def]
    _wire(monkeypatch, tmp_path)
    rc = cs.main()
    return rc, capsys.readouterr().out


# ------------------------------------------------------------------ 合规（绿）


def test_compliant_tree_is_green(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """全合规的假树 ⇒ `rc=0`，且绿行点名了这个技能。"""
    _build(tmp_path)
    rc, out = _run(tmp_path, monkeypatch, capsys)
    assert rc == 0, out
    assert "skills/fake-skill/SKILL.md" in out


# ------------------------------------------------------------------ 判据 A：长度上限


def test_over_length_is_red(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """★ 判据 A 反例：SKILL.md 超 120 行 ⇒ 红，点名文件 + 报实际行数。"""
    _build(tmp_path, skill=_pad_to(GOOD_SKILL, cs.MAX_LINES + 5))
    rc, out = _run(tmp_path, monkeypatch, capsys)
    assert rc == 1, out
    assert "太长" in out
    assert str(cs.MAX_LINES + 5) in out


def test_exactly_at_limit_is_green(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """★ 边界：正好 120 行 ⇒ 绿（上限是「≤」，不是「<」）。"""
    _build(tmp_path, skill=_pad_to(GOOD_SKILL, cs.MAX_LINES))
    rc, out = _run(tmp_path, monkeypatch, capsys)
    assert rc == 0, out


# ------------------------------------------------------------------ 判据 B：流程数上限


def test_four_flows_is_red(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """★ 判据 B 反例：第四条「流程级」小节 ⇒ 红，点名超出的那条。"""
    skill = GOOD_SKILL + "".join(f"\n### 流程{i}\n- 做点事。\n" for i in range(1, 5))
    _build(tmp_path, skill=skill)
    rc, out = _run(tmp_path, monkeypatch, capsys)
    assert rc == 1, out
    assert "流程级小节" in out
    assert "流程4" in out


def test_three_flows_is_green(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """★ 边界：正好三条流程 ⇒ 绿；六个固定小节**不算**流程。"""
    skill = GOOD_SKILL + "".join(f"\n### 流程{i}\n- 做点事。\n" for i in range(1, 4))
    _build(tmp_path, skill=skill)
    rc, out = _run(tmp_path, monkeypatch, capsys)
    assert rc == 0, out


def test_flow_titles_skip_the_six_required_sections() -> None:
    """零件层：口径 B 的「固定六节不算」写死在函数里 —— 真六节 ⇒ 0 条流程。"""
    _fm, body = cs.parse_frontmatter(GOOD_SKILL)
    assert cs.flow_titles(body) == []
    assert cs.flow_titles(body + "\n### 甲\n") == ["甲"]


def test_flow_count_ignores_fenced_code_blocks() -> None:
    """★ 口径 B：围栏代码块里的 `# 1)` 之类是命令注释，**不是**标题（真 pipe-forensics 有）。"""
    body = "## 真命令\n```bash\n# 1) 注释\n# 2) 注释\n```\n"
    assert cs.flow_titles(body) == []


# ------------------------------------------------------------------ 判据 C：验收口径指向真脚本


def test_result_item_without_script_is_red(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """★ 判据 C 反例：「怎么读结果」有一条只写『看输出对不对』⇒ 红，点名是哪一条。"""
    skill = GOOD_SKILL.replace(
        "- 退 `0`：过（复核：`python -X utf8 tools/wb_plan.py check`）。",
        "- 看输出对不对，看着像过就行了。",
    )
    _build(tmp_path, skill=skill)
    rc, out = _run(tmp_path, monkeypatch, capsys)
    assert rc == 1, out
    assert "没指向真脚本" in out
    assert "看输出对不对" in out


def test_result_item_pointing_at_a_ghost_script_is_red(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """★ 判据 C 反例（假指针）：指到 `tools/不存在的.py` ⇒ 红（路径必须**真存在**）。"""
    skill = GOOD_SKILL.replace(
        "`python -X utf8 tools/wb_plan.py check`",
        "`python -X utf8 tools/ghost.py check`",
    )
    _build(tmp_path, skill=skill)
    rc, out = _run(tmp_path, monkeypatch, capsys)
    assert rc == 1, out
    assert "没指向真脚本" in out


def test_pointer_needs_a_script_root_and_suffix(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """★ 判据 C 口径：非脚本根（`docs/x.py`）/ 非脚本后缀（`tools/x.md`）都**不算**指针。"""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "x.py").write_text("", encoding="utf-8")
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "x.md").write_text("", encoding="utf-8")
    (tmp_path / "tools" / "wb_plan.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(cs, "REPO_ROOT", tmp_path)
    assert cs.points_to_real_script("- 复核：`python -X utf8 docs/x.py`") is False
    assert cs.points_to_real_script("- 复核：`python -X utf8 tools/x.md`") is False
    assert cs.points_to_real_script("- 复核：`python -X utf8 tools/wb_plan.py check`") is True


# ------------------------------------------------------------------ 判据 D：NOTES.md 三节


def test_missing_notes_is_red(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """★ 判据 D 反例：目录下没有 NOTES.md ⇒ 红并点名。"""
    _build(tmp_path, notes=None)
    rc, out = _run(tmp_path, monkeypatch, capsys)
    assert rc == 1, out
    assert "NOTES.md" in out


def test_notes_missing_a_section_is_red(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """★ 判据 D 反例：NOTES.md 缺「失败过什么」那节 ⇒ 红并点名该节。"""
    notes = GOOD_NOTES.replace("## 失败过什么（带读数）", "## 别的")
    _build(tmp_path, notes=notes)
    rc, out = _run(tmp_path, monkeypatch, capsys)
    assert rc == 1, out
    assert "失败过什么" in out


def test_notes_sections_are_the_three_named_ones() -> None:
    """零件层：三节名字逐字写死（改口径只能改常量 + 这条）。"""
    assert cs.NOTES_SECTIONS == [
        "这一层在防哪类错误",
        "失败过什么（带读数）",
        "脚本接口与以后怎么改",
    ]


# ------------------------------------------------------------------ 既有判据不松（回归）


def test_missing_frontmatter_still_red(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """回归：老判据（frontmatter / kebab / 目录名 / 六个必需小节）一条都不许松。"""
    _build(tmp_path, skill=GOOD_SKILL.replace("---\nname: fake-skill", "name: fake-skill"))
    rc, out = _run(tmp_path, monkeypatch, capsys)
    assert rc == 1, out
    assert "缺 frontmatter" in out


def test_name_dir_mismatch_still_red(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    _build(tmp_path, skill=GOOD_SKILL.replace("name: fake-skill", "name: other-name"))
    rc, out = _run(tmp_path, monkeypatch, capsys)
    assert rc == 1, out
    assert "不一致" in out


def test_missing_required_section_still_red(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    _build(tmp_path, skill=GOOD_SKILL.replace("## 什么时候别用", "## 别的"))
    rc, out = _run(tmp_path, monkeypatch, capsys)
    assert rc == 1, out
    assert "什么时候别用" in out


def test_no_skill_at_all_is_red(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "skills").mkdir()
    rc, out = _run(tmp_path, monkeypatch, capsys)
    assert rc == 1
    assert "一个 SKILL.md 都没有" in out


# ------------------------------------------------------------------ 数据层（真仓库）


def test_real_repo_is_green(capsys) -> None:  # type: ignore[no-untyped-def]
    """真仓库：5 份 SKILL + 5 份 NOTES 全过（这条进不了门禁也当场咬住回归）。"""
    rc = cs.main()
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "pipe-init/SKILL.md" in out
    assert "pipe-forensics/SKILL.md" in out
