"""项目级技能 junction（卡 206 · T-G314）的判据 —— 在 tmp_path 里**真建** junction 来验。

判什么（每条都是卡规格里点名的）：
1. **只挂技能目录**（含 `SKILL.md`）—— `README.md` / `GLUE-harness.md` / `nails` 一个都不挂；
2. **幂等** —— 跑两次结果一样，第二次全部「跳过」；
3. `--check` 对**指错**的 junction ⇒ 非零并**点名**；
4. ★ **反例** —— 把 `nails` 也挂上 ⇒ `--check` 必须红（证明这条判据真看得见东西）。

★ junction 是 Windows 概念 —— 非 Windows 上整模块 skip（既不假绿、也不假红）。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import dsh_skills_link as dsl  # noqa: E402  —— 先把 tools/ 挂上 sys.path 才能 import

pytestmark = pytest.mark.skipif(os.name != "nt", reason="目录 junction 是 Windows 概念")

#: 假 skills/ 里那几个真技能（含 SKILL.md）。
SKILL_NAMES = ("pipe-alpha", "pipe-beta", "pipe-gamma")
#: 假 skills/ 里那几个**不该挂**的东西。
NON_SKILLS = ("README.md", "GLUE-harness.md", "nails")

_NO_WINDOW = {"creationflags": 0x08000000} if os.name == "nt" else {}


def _make_skills(root: Path) -> None:
    """搭一个假 `skills/`：3 个技能目录 + `README.md` + `GLUE-harness.md` + `nails/`。"""
    skills = root / "skills"
    for name in SKILL_NAMES:
        skill = skills / name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(f"---\nname: {name}\n---\n", encoding="utf-8")
    (skills / "README.md").write_text("# 技能总览\n", encoding="utf-8")
    (skills / "GLUE-harness.md").write_text("# 缝层\n", encoding="utf-8")
    (skills / "nails").mkdir()
    (skills / "nails" / "check_skills.py").write_text("# 钉子\n", encoding="utf-8")


def _link_dir(root: Path) -> Path:
    return root / ".dsh" / "skills"


def _entries(root: Path) -> list[str]:
    """`.dsh/skills` 下实际有哪些条目（没有目录 ⇒ 空）。"""
    link_dir = _link_dir(root)
    if not link_dir.is_dir():
        return []
    return sorted(child.name for child in link_dir.iterdir())


def _junction(to: Path, target: Path) -> None:
    """手工建一个 junction（造反例 / 指错用）；失败即测试失败。"""
    to.parent.mkdir(parents=True, exist_ok=True)
    done = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(to), str(target)],
        capture_output=True, **_NO_WINDOW,
    )
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")


def _same_path(a: str, b: str) -> bool:
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


# ------------------------------------------------------------------ 1. 只挂技能目录


def test_only_skill_dirs_are_linked(tmp_path: Path) -> None:
    """跑一次 ⇒ **只有** 3 个技能目录被挂上；`README.md`/`GLUE-harness.md`/`nails` 都不挂。"""
    _make_skills(tmp_path)
    assert dsl.main(["--root", str(tmp_path)]) == 0

    assert _entries(tmp_path) == list(SKILL_NAMES)
    link_dir = _link_dir(tmp_path)
    for name in SKILL_NAMES:
        link = link_dir / name
        assert dsl.is_junction(link), f"{name} 不是 junction"
        assert _same_path(dsl.junction_target(link) or "",
                          dsl.expected_target(link_dir, name)), name
    for name in NON_SKILLS:
        assert not (link_dir / name).exists(), f"{name} 不该被挂"


# ------------------------------------------------------------------ 2. 幂等


def test_second_run_is_idempotent(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """跑两次 ⇒ 第二次全部「跳过」、结果不变（已存在且指向正确就不重复建）。"""
    _make_skills(tmp_path)
    assert dsl.main(["--root", str(tmp_path)]) == 0
    first = capsys.readouterr().out
    assert "[建 ]" in first

    link_dir = _link_dir(tmp_path)
    before = {name: dsl.junction_target(link_dir / name) for name in SKILL_NAMES}

    assert dsl.main(["--root", str(tmp_path)]) == 0
    second = capsys.readouterr().out
    assert "[跳过]" in second
    assert "[建 ]" not in second

    after = {name: dsl.junction_target(link_dir / name) for name in SKILL_NAMES}
    assert before == after
    assert _entries(tmp_path) == list(SKILL_NAMES)


# ------------------------------------------------------------------ 3. --check 抓指错


def test_check_flags_wrong_direction_and_names_it(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """`--check` 对**指错方向**的 junction ⇒ 非零并点名哪一个。"""
    _make_skills(tmp_path)
    assert dsl.main(["--root", str(tmp_path)]) == 0

    link = _link_dir(tmp_path) / "pipe-alpha"
    os.rmdir(link)  # junction 用 rmdir 只删联接、不动真源
    _junction(link, tmp_path / "skills" / "pipe-beta")  # 故意指错
    capsys.readouterr()

    assert dsl.main(["--root", str(tmp_path), "--check"]) == 1
    err = capsys.readouterr().err
    assert "pipe-alpha" in err and "指错" in err, err


def test_check_is_red_when_missing(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """一个都没建时 `--check` 必须红，并点名缺哪个。"""
    _make_skills(tmp_path)
    assert dsl.main(["--root", str(tmp_path), "--check"]) == 1
    err = capsys.readouterr().err
    assert "没挂" in err and "pipe-alpha" in err, err


# ------------------------------------------------------------------ 4. ★ 反例


def test_check_is_red_when_a_non_skill_is_mounted(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """★ 反例：把 `nails/` 也挂上 ⇒ `--check` 必须**红**（证明这条判据真看得见东西）。

    先跑一次是对的（绿）作对照，再手工把 `nails` 挂上 ⇒ 那条「只挂技能目录」的判据当场咬。
    """
    _make_skills(tmp_path)
    assert dsl.main(["--root", str(tmp_path)]) == 0
    assert dsl.main(["--root", str(tmp_path), "--check"]) == 0  # 对照：没挂 nails 时绿
    capsys.readouterr()

    _junction(_link_dir(tmp_path) / "nails", tmp_path / "skills" / "nails")  # ★ 多余的那一个

    assert dsl.main(["--root", str(tmp_path), "--check"]) == 1
    err = capsys.readouterr().err
    assert "nails" in err and "多余" in err, err


def test_link_refuses_to_silently_rebuild_wrong_junction(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """★ 已存在但指向错 ⇒ 建的动作**报错停下**，**不静默重建**（保留「有人手工改过」这件事）。"""
    _make_skills(tmp_path)
    assert dsl.main(["--root", str(tmp_path)]) == 0

    link = _link_dir(tmp_path) / "pipe-alpha"
    os.rmdir(link)
    _junction(link, tmp_path / "skills" / "pipe-beta")
    capsys.readouterr()

    assert dsl.main(["--root", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "pipe-alpha" in err, err
    # 没有被悄悄改成正确目标 —— 仍指向 pipe-beta
    assert _same_path(dsl.junction_target(link) or "", str(tmp_path / "skills" / "pipe-beta"))


# ------------------------------------------------------------------ 附带：--list


def test_list_prints_name_and_target(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """`--list` 打印「技能名 → 目标」，人读；只列技能、不列多余的。"""
    _make_skills(tmp_path)
    assert dsl.main(["--root", str(tmp_path)]) == 0
    capsys.readouterr()

    assert dsl.main(["--root", str(tmp_path), "--list"]) == 0
    out = capsys.readouterr().out
    for name in SKILL_NAMES:
        assert name in out, out
    assert "→" in out, out
