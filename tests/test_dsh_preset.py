"""软工预设片段：结构与安装幂等。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import dsh_preset  # noqa: E402

GOOD = """- insert:
    - id: preset-softeng
      name: '@deepseek-ai/dsh-agent-preset'
      config:
        id: softeng
        plugins:
          - id: tool-bash
            name: '@deepseek-ai/dsh-tool-bash'
            disabled: false
          - id: skill-filesystem
            name: '@deepseek-ai/dsh-skill-filesystem'
            config:
              customSkillDirs:
                - C:/Users/example/.dsh/skills-softeng
"""


def test_real_fragment_is_green():
    assert dsh_preset.check_file() == []


def test_good_sample_passes_and_keeps_bash():
    assert dsh_preset.check_text(GOOD) == []


def test_pwsh_row_is_rejected():
    bad = GOOD.replace(
        "          - id: skill-filesystem",
        "          - id: tool-pwsh\n            disabled: true\n          - id: skill-filesystem",
    )
    assert any("tool-pwsh" in p for p in dsh_preset.check_text(bad))


def test_bash_must_be_enabled():
    bad = GOOD.replace("disabled: false", "disabled: true")
    assert any("tool-bash" in p for p in dsh_preset.check_text(bad))


def test_bare_id_row_is_rejected():
    assert any("insert" in p for p in dsh_preset.check_text(GOOD.replace("- insert:\n", "", 1)))


def test_install_is_idempotent(tmp_path):
    profile = tmp_path / "profile"
    profile.mkdir()
    patch = profile / "cordis.patch.yml"
    patch.write_text("- id: ui-chat\n  name: '@deepseek-ai/dsh-client-ui-chat'\n", encoding="utf-8")
    assert dsh_preset.install(profile) == 0
    assert dsh_preset.install(profile) == 0
    text = patch.read_text(encoding="utf-8")
    assert text.count("- id: preset-softeng") == 1
    assert text.startswith("- id: ui-chat")
    assert list(profile.glob("cordis.patch.yml.bak-preset-*"))

def test_persona_routes_management_and_blocks_unconfirmed_writing():
    """persona 必须把「管理类先走 softeng-manage」和「写文档先过 grill-me」写进去。"""
    text = (Path(__file__).resolve().parent.parent / "docs/presets/softeng.patch.yml").read_text(
        encoding="utf-8"
    )
    assert "softeng-manage skill first" in text, "persona 缺 softeng-manage 入口规则"
    assert "grill-me" in text, "persona 缺 grill-me 前置规则"
    assert "explicitly confirmed" in text, "persona 缺「明确确认」这一句"


def test_skills_require_grill_me_before_writing():
    """新建/接手技能必须把「先 grill-me 再动笔」写成前置步骤。"""
    root = Path(__file__).resolve().parent.parent
    for rel in ("skills/pipe-new/SKILL.md", "skills/pipe-takeover/SKILL.md"):
        body = (root / rel).read_text(encoding="utf-8")
        assert "grill-me" in body, f"{rel} 缺 grill-me 前置"
        assert "未确认不得动笔" in body, f"{rel} 缺「未确认不得动笔」"
