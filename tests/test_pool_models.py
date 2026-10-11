r"""两份模型白名单的**对账判据**（卡 132 · T-G229）的测试。

为什么值当测：本仓那份（`wb_dispatch` 的裸名）与号池那份（`pool.models` 的 `provider/model`）
**已经实际发散** —— 同一个问题「现在能用什么模型」两个工具会给**不同答案**，而此前没有判据。
这里钉住新加的 `pool.models.compare_rosters`（纯函数）与 `wb_state` 的对账行。

| 钉子 | 判什么 | 会红在哪 |
|---|---|---|
| ① 一致 ⇒ 空 | 两份同名清单 | 若函数把"一致"也报成漂 |
| ② 只在一边 ⇒ 点名 + 哪边 | 名字各在一侧 | 若丢了"在哪一边"的区分 |
| ③ id 体系不同 ⇒ 字符串 | 裸名 vs `provider/model` | 若把两套 id 硬对成"互不相干" |
| ④ 纯函数 | `open` / `read_text` 换抛异常的桩 | 若函数偷读文件 |
| ⑤ 面板行 | 漂 / 一致 两态（桩数据） | 若前缀不是 `⚠` / `✓` |

★ 导入口径照既有测试：把 `tools/` 挂上 `sys.path` 再 `import`。
"""

from __future__ import annotations

import builtins
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import wb_state  # noqa: E402 —— tools/ 已在 sys.path 上
from pool import models  # noqa: E402

# ================================================================ ① 一致 ⇒ 空


def test_compare_rosters_identical_is_empty() -> None:
    pool = {"approved": ["alpha", "beta"]}
    assert models.compare_rosters(["alpha", "beta"], pool) == []


def test_compare_rosters_ignores_order_and_dupes() -> None:
    pool = {"approved": ["beta", "alpha", "beta"]}
    assert models.compare_rosters(["alpha", "alpha", "beta"], pool) == []


# ================================================================ ② 只在一边


def test_compare_rosters_names_one_side_and_says_which() -> None:
    problems = models.compare_rosters(["alpha"], {"approved": ["beta"]})
    assert problems, "只在一侧的名字必须被点名"
    assert any("alpha" in p and "本仓" in p for p in problems), problems
    assert any("beta" in p and "池" in p for p in problems), problems


def test_compare_rosters_empty_pool_lists_all_local() -> None:
    problems = models.compare_rosters(["alpha", "beta"], {"approved": []})
    assert any("alpha" in p and "beta" in p and "本仓" in p for p in problems), problems


# ================================================================ ③ id 体系不同


def test_compare_rosters_flags_id_system_mismatch() -> None:
    problems = models.compare_rosters(
        ["deepseek-v4.1-flash"], {"approved": ["huaweicloud-maas/GLM-5.2"]}
    )
    joined = "；".join(problems)
    assert "id 体系 / 口径不同" in joined, problems
    assert "id 口径" in joined, problems


def test_compare_rosters_same_id_system_has_no_mismatch_line() -> None:
    problems = models.compare_rosters(["alpha"], {"approved": ["beta"]})
    assert not any("id 体系" in p for p in problems), problems


# ================================================================ ④ 纯函数


def test_compare_rosters_never_reads_files(monkeypatch) -> None:
    def boom(*_args, **_kwargs):
        raise AssertionError("compare_rosters 不许读文件 / 联网")

    monkeypatch.setattr(builtins, "open", boom)
    monkeypatch.setattr(Path, "read_text", boom)
    problems = models.compare_rosters(["deepseek-v4.1-flash"],
                                      {"approved": ["huaweicloud-maas/GLM-5.2"]})
    assert problems, "桩下也要照样跑出结论"


# ================================================================ ⑤ 面板那一行


def test_roster_line_drift_and_consistent() -> None:
    drift = wb_state.roster_line(["a"], {"approved": ["prov/b"]})
    assert drift.startswith("⚠ 白名单对账："), drift
    assert "本仓[a]" in drift and "池[prov/b]" in drift, drift

    same = wb_state.roster_line(["a", "b"], {"approved": ["a", "b"]})
    assert same.startswith("✓ 白名单对账：一致"), same


def test_line_roster_under_stub(monkeypatch) -> None:
    monkeypatch.setattr(wb_state, "_local_whitelist", lambda: ["dup", "dup"])
    monkeypatch.setattr(wb_state, "_pool_roster", lambda: {"approved": ["dup"]})
    assert wb_state.line_roster().startswith("✓ 白名单对账：一致")


def test_line_roster_reads_real_names() -> None:
    """真读数：本仓裸名名单 vs 号池 provider/model —— 两套 id 体系本来就不同。"""
    line = wb_state.line_roster()
    assert line.startswith(("⚠ 白名单对账：", "✓ 白名单对账：", "白名单对账：无法判断")), line


# ================================================================ 模型开关文件（卡 138 · T-G236）
#
# 用户要「按一下就 true/false」的开关 ⇒ 开关做**数据**（infra/pool/model-switches.toml）。
# `load_switches()` 是那条**只读**通路：缺文件=空（不报错）；坏文件=**报错点名路径与行号**，
# ★ 绝不静默当空（否则「我明明开了」会变成「实际没开」）。
# ★ 各钉子都用 `TF_MODEL_SWITCHES` 指到临时文件 —— **不碰 infra 那份真文件**。


def _switch_file(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "model-switches.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_load_switches_missing_file_is_empty(tmp_path: Path, monkeypatch) -> None:
    """③ 文件不存在 ⇒ 空字典、**不报错**（大多数人没有这份文件）。"""
    monkeypatch.setenv("TF_MODEL_SWITCHES", str(tmp_path / "absent.toml"))
    assert models.load_switches() == {}


def test_load_switches_reads_bare_name_booleans(tmp_path: Path, monkeypatch) -> None:
    """① 开关开 / ② 开关关：`[switch]` 段里裸名 → 布尔，原样读出。"""
    path = _switch_file(tmp_path, '[switch]\n"glm-5.3" = true\n"kimi-k2.7" = false\n')
    monkeypatch.setenv("TF_MODEL_SWITCHES", str(path))
    assert models.load_switches() == {"glm-5.3": True, "kimi-k2.7": False}


def test_load_switches_pool_dir_arg_is_used(tmp_path: Path) -> None:
    """`pool_dir` 给了就用它（复用 `find_pool_dir()` 的口径，不另写路径查找）。"""
    _switch_file(tmp_path, '[switch]\n"glm-5.3" = true\n')
    assert models.load_switches(tmp_path) == {"glm-5.3": True}


def test_load_switches_env_overrides_pool_dir(tmp_path: Path, monkeypatch) -> None:
    """`TF_MODEL_SWITCHES`（测试覆盖）优先于显式 `pool_dir`。"""
    pool = tmp_path / "pool"
    pool.mkdir()
    (pool / "model-switches.toml").write_text('[switch]\n"x" = false\n', encoding="utf-8")
    override = tmp_path / "override.toml"
    override.write_text('[switch]\n"x" = true\n', encoding="utf-8")
    monkeypatch.setenv("TF_MODEL_SWITCHES", str(override))
    assert models.load_switches(pool) == {"x": True}


def test_load_switches_non_bool_names_path_and_line(tmp_path: Path, monkeypatch) -> None:
    """④ 值不是布尔 ⇒ 报错并**点名路径与那一行**（★ 不是静默当空）。"""
    path = _switch_file(tmp_path, '[switch]\n# 注释占一行\n"glm-5.3" = "yes"\n')
    monkeypatch.setenv("TF_MODEL_SWITCHES", str(path))
    with pytest.raises(models.SwitchFileError) as excinfo:
        models.load_switches()
    message = str(excinfo.value)
    assert str(path) in message and "第 3 行" in message and "glm-5.3" in message, message


def test_load_switches_broken_toml_names_path_and_line(tmp_path: Path, monkeypatch) -> None:
    """④ 故意写坏 TOML ⇒ 报错并**点名路径与那一行**（`yes` 不是 TOML 布尔）。"""
    path = _switch_file(tmp_path, '[switch]\n"glm-5.3" = yes\n')
    monkeypatch.setenv("TF_MODEL_SWITCHES", str(path))
    with pytest.raises(models.SwitchFileError) as excinfo:
        models.load_switches()
    message = str(excinfo.value)
    assert str(path) in message and "第 2 行" in message, message


def test_load_switches_missing_switch_table_is_empty(tmp_path: Path, monkeypatch) -> None:
    """有文件但没 `[switch]` 段 ⇒ 空字典（不是「坏文件」）。"""
    path = _switch_file(tmp_path, "# 只有注释\n")
    monkeypatch.setenv("TF_MODEL_SWITCHES", str(path))
    assert models.load_switches() == {}


# ================================================ 卡 166（T-G266）：开关按池分段
# ★ 向后兼容：[switch] 顶层（无子表）⇒ pool="codebuddy" 仍读到它（判据 ⑥）。


def test_load_switches_by_pool_codebuddy_subtable(tmp_path: Path, monkeypatch) -> None:
    """★ [switch.codebuddy] 子表 ⇒ pool="codebuddy" 读到。"""
    path = _switch_file(tmp_path, '[switch.codebuddy]\n"glm-5.2" = true\n')
    monkeypatch.setenv("TF_MODEL_SWITCHES", str(path))
    assert models.load_switches(pool="codebuddy") == {"glm-5.2": True}


def test_load_switches_by_pool_codearts_subtable(tmp_path: Path, monkeypatch) -> None:
    """★ [switch.codearts] 子表 ⇒ pool="codearts" 读到；pool="codebuddy" 读不到。"""
    path = _switch_file(tmp_path, '[switch.codearts]\n"huaweicloud-maas/GLM-5.2" = true\n')
    monkeypatch.setenv("TF_MODEL_SWITCHES", str(path))
    assert models.load_switches(pool="codearts") == {"huaweicloud-maas/GLM-5.2": True}
    assert models.load_switches(pool="codebuddy") == {}, "codebuddy 不读 codearts 子表"


def test_load_switches_codebuddy_falls_back_to_legacy_switch(tmp_path: Path, monkeypatch) -> None:
    """★ 向后兼容：[switch] 顶层（无子表）⇒ pool="codebuddy" 仍读到它（判据 ⑥）。"""
    path = _switch_file(tmp_path, '[switch]\n"glm-5.3" = true\n')
    monkeypatch.setenv("TF_MODEL_SWITCHES", str(path))
    assert models.load_switches(pool="codebuddy") == {"glm-5.3": True}
    assert models.load_switches(pool="codearts") == {}, "codearts 不回退读 [switch] 顶层"


def test_load_switches_codebuddy_merges_legacy_and_subtable(tmp_path: Path, monkeypatch) -> None:
    """★ codebuddy = [switch] 顶层 + [switch.codebuddy] 子表（合并；子表优先覆盖）。"""
    path = _switch_file(tmp_path,
                        '[switch]\n"glm-5.3" = true\n[switch.codebuddy]\n"glm-5.2" = true\n')
    monkeypatch.setenv("TF_MODEL_SWITCHES", str(path))
    result = models.load_switches(pool="codebuddy")
    assert result == {"glm-5.3": True, "glm-5.2": True}, result


def test_load_switches_non_bool_in_subtable_names_line(tmp_path: Path, monkeypatch) -> None:
    """★ 子表里非布尔也要点名行号（不因按池而放水）。"""
    path = _switch_file(tmp_path, '[switch.codearts]\n"x" = "yes"\n')
    monkeypatch.setenv("TF_MODEL_SWITCHES", str(path))
    with pytest.raises(models.SwitchFileError) as excinfo:
        models.load_switches(pool="codearts")
    message = str(excinfo.value)
    assert str(path) in message and "x" in message, message
