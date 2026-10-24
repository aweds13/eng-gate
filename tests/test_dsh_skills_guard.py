"""技能根守卫（卡 E19 / T-AG472）的钉子 —— 四条判据各一条，外加一条「!!js 原样保留」。

口径全在 `tools/dsh_skills_guard.py` 的文件头；这里只验它**真的会咬**：

1. 正常 profile（默认预设含仓库根）⇒ 退 0；
2. 删掉仓库根的副本 ⇒ 退 1，且报行点名「默认预设」与缺的那个目录；
3. profile 不存在 ⇒ 退 2（判不了，**不许**当成绿）；
4. `!!js` 表达式折行原样保留、不被当成路径展开成乱七八糟的东西；
5. 真实 profile 上跑一次（存在才跑）—— 证明它不是空转。

夹具一律 `tmp_path` 里搭合成 profile，**不写 `~/.dsh` 任何文件**（守卫只读）。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import dsh_skills_guard as guard  # noqa: E402

EXPECT = "C:/Users/example/.dsh/skills-softeng"

PROFILE_WITH_ROOT = """\
- id: preset-standard
  name: '@deepseek-ai/dsh-agent-preset'
  plugins:
    - id: skill-filesystem
      name: '@deepseek-ai/dsh-skill-filesystem'
      config:
        customSkillDirs:
          - !!js process.getBuiltinModule('node:path').join(
            'skills')
          - C:/Users/example/.dsh/skills-softeng
    - id: tool-skill
      name: '@deepseek-ai/dsh-tool-skill'
- id: preset-softeng
  name: '@deepseek-ai/dsh-agent-preset'
  plugins:
    - id: skill-filesystem
      config:
        customSkillDirs:
          - C:/Users/example/.dsh/skills-softeng
      name: '@deepseek-ai/dsh-skill-filesystem'
"""

PROFILE_NO_ROOT = PROFILE_WITH_ROOT.replace(
    "          - C:/Users/example/.dsh/skills-softeng\n    - id: tool-skill",
    "    - id: tool-skill",
)


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "cordis.patch.yml"
    p.write_text(text, encoding="utf-8")
    return p


def test_normal_profile_passes(tmp_path: Path) -> None:
    code, lines = guard.check(_write(tmp_path, PROFILE_WITH_ROOT), EXPECT)
    assert code == 0, lines
    assert any("[OK ]" in line and EXPECT in line for line in lines)


def test_missing_root_fails_and_names_the_default_preset(tmp_path: Path) -> None:
    code, lines = guard.check(_write(tmp_path, PROFILE_NO_ROOT), EXPECT)
    assert code == 1, lines
    joined = "\n".join(lines)
    assert "默认预设" in joined, joined
    assert EXPECT in joined, joined


def test_absent_profile_is_not_verified(tmp_path: Path) -> None:
    code, lines = guard.check(tmp_path / "nope.yml", EXPECT)
    assert code == 2, lines
    assert any("判不了" in line for line in lines)


def test_js_expression_is_kept_raw(tmp_path: Path) -> None:
    segments = guard.parse_segments(PROFILE_WITH_ROOT)
    assert segments, "一段都没解析出来"
    default = next(seg for seg in segments if seg.is_default)
    raw = next(root for root in default.roots if "!!js" in root)
    assert raw.startswith("!!js process.getBuiltinModule"), raw
    assert raw.endswith("'skills')"), raw  # 折行接上了
    # 默认预设必须同时认得那条真路径
    assert any(guard._norm(root) == guard._norm(EXPECT) for root in default.roots)
    # 软工预设自己那段不带 !!js ⇒ 不会被误判成默认预设
    assert len([seg for seg in segments if seg.is_default]) == 1


def test_real_profile_passes_when_present() -> None:
    profile = guard.DEFAULT_PROFILE
    if not profile.exists():  # 别的机器上没有这份 profile —— 不硬造一份假的
        return
    code, lines = guard.check(profile, EXPECT)
    assert code == 0, "\n".join(lines)
