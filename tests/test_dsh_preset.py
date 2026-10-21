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
