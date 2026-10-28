"""技能-工具对账尺子（`tools/check_skills_claims.py`，卡 G1 / T-AG456）的钉子。

为什么值当测：这把尺子**只判别人**（技能正文写的命令还在不在）。尺子自己歪了没人看得见 ——
它要是把「判不出来」当通过，技能里的旧写法就能一路绿到有人照着敲、被 argparse 拒单那天
（卡 G1 的起因就是这个：133 处命令引用**一处都没被机器核过**）。

所以这里全是**反例钉**：坏树必须红、且**点得出是哪一条**；占位命令必须记 `not verified`
而**不许**算进「对得上」；豁免**空理由**必须红。树是临时造的（`tmp_path`），不碰真仓库。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import check_skills_claims as cs  # noqa: E402 —— 需要先把 tools/ 挂上 sys.path

TOOL_SRC = """import argparse

ap = argparse.ArgumentParser()
ap.add_argument("--check", action="store_true")
ap.add_argument("--card")
ap.add_argument("--json", action="store_true")
"""


def _doc(body: str) -> str:
    """技能正文（`body` 前面还有 4 行标题，算期望行号要用整份文本）。"""
    return f"# fake\n\n## 真命令\n\n{body}\n"


def _line_of(text: str, needle: str) -> int:
    """该片段在文本里的行号（1 起），用来算期望的「文件:行」。"""
    for lineno, line in enumerate(text.splitlines(), 1):
        if needle in line:
            return lineno
    raise AssertionError(f"夹具里找不到这一行：{needle!r}")


def _tree(tmp_path: Path, body: str, *, tool: str = "wb_plan.py") -> Path:
    """造一棵假仓：`skills/fake/SKILL.md` + `tools/<tool>`。"""
    skill_dir = tmp_path / "skills" / "fake"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(_doc(body), encoding="utf-8")
    (tmp_path / "tools").mkdir(exist_ok=True)
    (tmp_path / "tools" / tool).write_text(TOOL_SRC, encoding="utf-8")
    return tmp_path


def _run(
    tmp_path: Path,
    monkeypatch,
    capsys,
    exempt: dict[str, str] | None = None,
    mode: str | None = None,
) -> tuple[int, str]:  # type: ignore[no-untyped-def]
    """跑 CLI（`--check`），返回 `(退出码, stdout)`；豁免表按用例给。

    `mode=None` ⇒ **不传** `--mode`，走工具自己的默认档 —— 正是要钉的东西：
    默认必须是 `block`（三态），否则上面十几条反例钉会在无声中全部失效。
    """
    monkeypatch.setattr(cs, "EXEMPT", exempt if exempt is not None else {})
    argv = ["--check", "--root", str(tmp_path)]
    if mode is not None:
        argv += ["--mode", mode]
    rc = cs.main(argv)
    return rc, capsys.readouterr().out


# ------------------------------------------------------------------ 好树全绿


def test_good_tree_is_green(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """工具在、参数都在 ⇒ 退 0，计数写明「对得上 1 / 对不上 0」。"""
    body = "```bash\npython -X utf8 tools/wb_plan.py check --card x\n```"
    _tree(tmp_path, body)
    rc, out = _run(tmp_path, monkeypatch, capsys)
    assert rc == 0, out
    assert "对得上 1" in out
    assert "对不上 0" in out


# ------------------------------------------------------------------ 工具不存在点名


def test_missing_tool_is_named(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """★ 反例①：技能引用了不存在的工具 ⇒ 退 1，点名 `文件:行` 与那个工具。"""
    body = "```bash\npython -X utf8 tools/ghost.py --check\n```"
    _tree(tmp_path, body)
    rc, out = _run(tmp_path, monkeypatch, capsys)
    assert rc == 1, out
    assert "工具不存在" in out
    assert f"skills/fake/SKILL.md:{_line_of(_doc(body), 'ghost.py')}" in out
    assert "tools/ghost.py" in out


# ------------------------------------------------------------------ 参数不存在点名


def test_missing_flag_is_named(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """★ 反例②：工具在、参数退役了 ⇒ 退 1，点名是哪个 `--flag`。"""
    body = "```bash\npython -X utf8 tools/wb_plan.py --gone\n```"
    _tree(tmp_path, body)
    rc, out = _run(tmp_path, monkeypatch, capsys)
    assert rc == 1, out
    assert "参数不存在：--gone" in out


def test_flag_value_is_taken_before_equals(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """口径：`--json=true` 只取等号前那半去核（`--json` 注册过 ⇒ 绿）。"""
    body = "```bash\npython -X utf8 tools/wb_plan.py --json=true\n```"
    _tree(tmp_path, body)
    rc, out = _run(tmp_path, monkeypatch, capsys)
    assert rc == 0, out


# ------------------------------------------------------------------ 判不出来要明说


def test_placeholder_is_not_verified_and_not_green(
    tmp_path, monkeypatch, capsys
) -> None:  # type: ignore[no-untyped-def]
    """★ 反例③：写的是 `<卡号>` ⇒ 记 `not verified`，**不许**算进「对得上」，也**不许**退 0。"""
    body = "```bash\npython -X utf8 tools/wb_plan.py --card <卡号>\n```"
    _tree(tmp_path, body)
    rc, out = _run(tmp_path, monkeypatch, capsys)
    assert rc == 3, out  # 「判不出」不是通过 ⇒ 退 3「没判完」，不是 0
    assert "not verified" in out
    assert "判不出 1" in out
    assert "对得上 0" in out


def test_placeholder_does_not_hide_a_bad_flag(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """★ 占位不许当挡箭牌：命令里既有 `<卡号>` 又有个退役参数 ⇒ 照样退 1 点名。"""
    body = "```bash\npython -X utf8 tools/wb_plan.py --card <卡号> --gone\n```"
    _tree(tmp_path, body)
    rc, out = _run(tmp_path, monkeypatch, capsys)
    assert rc == 1, out
    assert "参数不存在：--gone" in out


def test_wildcard_tool_is_not_verified(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """`tools/wb_*.py` 点不出是哪个脚本 ⇒ `not verified`：不算绿（退 0）也不算红（退 1），退 3。"""
    body = "```bash\npython -X utf8 tools/wb_*.py --check\n```"
    _tree(tmp_path, body)
    rc, out = _run(tmp_path, monkeypatch, capsys)
    assert rc == 3, out
    assert "通配" in out
    assert "对得上 0" in out


# ------------------------------------------------------------------ 豁免


def test_empty_exempt_reason_is_red(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """★ 反例④：豁免写了个空理由 ⇒ 红（豁免是账，不是让门变绿的开关）。"""
    body = "```bash\npython -X utf8 tools/wb_plan.py --gone\n```"
    _tree(tmp_path, body)
    key = f"skills/fake/SKILL.md:{_line_of(_doc(body), '--gone')}"
    rc, out = _run(tmp_path, monkeypatch, capsys, exempt={key: "   "})
    assert rc == 1, out
    assert "空理由算红" in out


def test_exempt_with_reason_passes(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """有理由的豁免真放行：退 0 且计入「豁免 1」，仍然点名这条被豁免了。"""
    body = "```bash\npython -X utf8 tools/wb_plan.py --gone\n```"
    _tree(tmp_path, body)
    key = f"skills/fake/SKILL.md:{_line_of(_doc(body), '--gone')}"
    rc, out = _run(tmp_path, monkeypatch, capsys, exempt={key: "该参数在别处由外壳补"})
    assert rc == 0, out
    assert "豁免 1" in out


# ------------------------------------------------------------------ 口径细节（别把正确的判红）


def test_thin_shell_follows_its_imports(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """薄壳转发（`from pool import landing`）⇒ 跟进去找 argparse，别把正确的命令判红。"""
    body = "```bash\npython -X utf8 tools/wb_land.py --title t\n```"
    _tree(tmp_path, body, tool="wb_land.py")
    (tmp_path / "tools" / "wb_land.py").write_text(
        "from pool import landing as _landing\n", encoding="utf-8"
    )
    (tmp_path / "tools" / "pool").mkdir()
    (tmp_path / "tools" / "pool" / "landing.py").write_text(
        'ap.add_argument("--title", required=True)\n', encoding="utf-8"
    )
    rc, out = _run(tmp_path, monkeypatch, capsys)
    assert rc == 0, out
    assert "对得上 1" in out


def test_prose_without_backticks_is_not_scanned(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """散文里提一嘴命令不算引用 —— 只扫围栏块与行内反引号（否则全是假红）。"""
    body = "跑 python -X utf8 tools/ghost.py 就行，没加反引号。"
    _tree(tmp_path, body)
    rc, out = _run(tmp_path, monkeypatch, capsys)
    assert rc == 0, out
    assert "引用 0 处" in out


def test_line_number_points_into_the_fence(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """围栏块里的命令要报**它自己那一行**，不是开栏那行（否则点不到人）。"""
    body = "```bash\n# 注释\n\npython -X utf8 tools/ghost.py\n```"
    _tree(tmp_path, body)
    rc, out = _run(tmp_path, monkeypatch, capsys)
    assert rc == 1, out
    assert f"skills/fake/SKILL.md:{_line_of(_doc(body), 'ghost.py')}" in out


def test_continuation_line_stays_one_command(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """行尾 `\\` 是续行：下一行的参数属于同一条命令，不许漏核。"""
    body = "```bash\npython -X utf8 tools/wb_plan.py --check \\\n    --gone\n```"
    _tree(tmp_path, body)
    rc, out = _run(tmp_path, monkeypatch, capsys)
    assert rc == 1, out
    assert "参数不存在：--gone" in out


# ------------------------------------------------------------------ --mode report / block


def test_report_mode_is_green_but_still_prints_the_number(
    tmp_path, monkeypatch, capsys
) -> None:  # type: ignore[no-untyped-def]
    """★ `--mode report`：只有「判不出」时退 **0**（门禁不红），但读数必须在脸上。

    这是接门的全部理由：技能正文里的 `<卡号>` / `...` / `tools/wb_*.py` 是指令文档的
    固有形态，压不到 0 条；block 档会让每趟门禁都红。★ 但退 0 **不是** PASS ——
    汇总行与 `[DEBT]` 行必须把「判不出 1」写出来，且不许出现 `[OK  ]`。
    """
    body = "```bash\npython -X utf8 tools/wb_plan.py --card <卡号>\n```"
    _tree(tmp_path, body)
    rc, out = _run(tmp_path, monkeypatch, capsys, mode="report")
    assert rc == 0, out  # 判不出不红（这正是 report 档存在的理由）
    assert "判不出" in out and "判不出 1" in out, out  # 读数照打，一位都不省
    assert "对不上 0" in out, out
    assert "[OK" not in out, f"report 档判不出时不许打 OK 行（会被当成过了）：\n{out}"
    assert "[DEBT]" in out, out


def test_block_mode_is_still_three_on_not_verified(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """★ 防回退：**不给 `--mode`** 时默认是 `block`，同样输入必须退 3。

    加 `--mode` 最容易出的事故是「顺手把默认改了」—— 那样上面所有反例钉（以及仓里
    任何直接调 `cs.main([...])` 的地方）都会在无声中失去意义：判不出重新变成退 0，
    也就是「没判」重新冒充「通过」。这条钉把默认档钉死在 block。
    """
    body = "```bash\npython -X utf8 tools/wb_plan.py --card <卡号>\n```"
    _tree(tmp_path, body)
    rc, out = _run(tmp_path, monkeypatch, capsys)  # 刻意不传 mode
    assert rc == 3, out
    assert "判不出 1" in out
    # 显式写 block 也必须一样（默认值 == block，不是两套语义）
    rc2, out2 = _run(tmp_path, monkeypatch, capsys, mode="block")
    assert rc2 == 3, out2


def test_report_mode_is_still_red_on_real_drift(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """★ `--mode report` 不是「什么都放过」：有**真对不上**照样退 1 并点名。"""
    body = "```bash\npython -X utf8 tools/wb_plan.py --card <卡号> --gone\n```"
    _tree(tmp_path, body)
    rc, out = _run(tmp_path, monkeypatch, capsys, mode="report")
    assert rc == 1, out  # report 只放过「判不出」，不放过「对不上」
    assert "参数不存在：--gone" in out
    assert "[FAIL]" in out, out
