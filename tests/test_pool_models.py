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

import ast
import builtins
import json
import sys
import tempfile
from datetime import datetime, timedelta
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


def test_snapshot_age_is_computed_not_guessed() -> None:
    """快照时间戳读得出来 ⇒ 给小时数；读不出来 ⇒ None（不猜）。"""
    from pool.models import snapshot_age_hours

    now = datetime(2026, 10, 23, 18, 0, 0)
    assert snapshot_age_hours("2026-10-23 06:00:00", now=now) == 12.0
    assert snapshot_age_hours("坏时间戳", now=now) is None
    assert snapshot_age_hours(None, now=now) is None


def test_stale_snapshot_is_flagged_loudly() -> None:
    """超过 24 小时 ⇒ `snapshot_stale` 为真且带提示语；新鲜快照不许嚷。"""
    from pool.models import STALE_HOURS, load_pool_models

    stamp = (datetime.now() - timedelta(hours=STALE_HOURS + 30)).strftime("%Y-%m-%d %H:%M:%S")
    fresh = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with tempfile.TemporaryDirectory() as tmp:
        pool = Path(tmp)
        # ★ 直接写字面 TOML（`tomllib` 只有 loads 家族，没有 `dumps` —— 别绕这一圈）。
        (pool / "models.whitelist.toml").write_text(
            '[[approved]]\npool = "codebuddy"\nmodel = "m1"\n', encoding="utf-8"
        )
        for stamp_value, expect in ((stamp, True), (fresh, False)):
            (pool / "models.live.json").write_text(
                json.dumps({"at": stamp_value, "live": ["m1"]}), encoding="utf-8"
            )
            data = load_pool_models(pool)
            assert data["snapshot_stale"] is expect, (stamp_value, data)
            if expect:
                assert data["snapshot_note"]


def test_unreadable_snapshot_stamp_is_stale_not_fresh() -> None:
    """★ 卡 320 钉子：`at` **有值但读不出来** ⇒ `snapshot_stale` 必须为真（不许字段与文案打架）。

    对照：`at` **本身为空** = 「没记录」，不等于过期 ⇒ `snapshot_stale` 为假、提示语为空。
    这两条必须一起钉住 —— 只钉坏时间戳那半，改坏了「空 ≠ 过期」不会被发现；
    只钉空那半，改坏了「坏 ⇒ 过期」也不会被发现。
    """
    from pool.models import load_pool_models

    with tempfile.TemporaryDirectory() as tmp:
        pool = Path(tmp)
        (pool / "models.whitelist.toml").write_text(
            '[[approved]]\npool = "codebuddy"\nmodel = "m1"\n', encoding="utf-8"
        )
        # ① `at` 有值但读不出来 ⇒ 过期，且文案说的是「读不出来」这件事本身
        (pool / "models.live.json").write_text(
            json.dumps({"at": "不是时间戳", "live": ["m1"]}), encoding="utf-8"
        )
        bad = load_pool_models(pool)
        assert bad["snapshot_at"] == "不是时间戳"
        assert bad["snapshot_age_hours"] is None, "读不出来就是 None，不许猜成 0"
        assert bad["snapshot_stale"] is True, f"坏时间戳必须算过期，实际 {bad}"
        assert bad["snapshot_note"], "过期了就得有提示语"
        assert "读不出来" in bad["snapshot_note"], bad["snapshot_note"]
        # ② `at` 为空 ⇒ 没记录（不是过期）：两者不许混成同一件事
        (pool / "models.live.json").write_text(
            json.dumps({"live": ["m1"]}), encoding="utf-8"
        )
        empty = load_pool_models(pool)
        assert empty["snapshot_at"] is None
        assert empty["snapshot_age_hours"] is None
        assert empty["snapshot_stale"] is False, f"没记录不等于过期，实际 {empty}"
        assert empty["snapshot_note"] == ""

# ========================================== 卡 E110（T-AG619）：过期要说清怎么探


def _stale_pool(
    tmp: Path, *, at: str, script: bool = True, subdir: str = "infra/pool"
) -> Path:
    """造一个号池目录（批准集 + 快照）；`script=False` ⇒ 不放那份探测脚本。"""
    pool = tmp / subdir
    pool.mkdir(parents=True, exist_ok=True)
    if script:
        (pool / "pool_models.py").write_text("", encoding="utf-8")
    (pool / "models.whitelist.toml").write_text(
        '[[approved]]\npool = "codebuddy"\nmodel = "m1"\n', encoding="utf-8"
    )
    (pool / "models.live.json").write_text(
        json.dumps({"at": at, "live": ["m1"]}), encoding="utf-8"
    )
    return pool


def test_probe_hint_computes_the_path_instead_of_hardcoding_it(tmp_path: Path) -> None:
    """★ 判据 1：那条命令的路径必须**现算**（写死路径换台机器就废）。

    写死 infra/pool/pool_models.py 也过不了：号池目录可以在任何祖先层级下。
    """
    pool = _stale_pool(tmp_path, at="2020-01-01 00:00:00", subdir="elsewhere/pool")
    hint = models.probe_hint(pool)
    assert "--check" in hint, hint
    assert (pool / "pool_models.py").as_posix() in hint, hint
    assert "D:" not in hint, hint
    assert "infra/pool/pool_models.py" not in hint, "写死相对片段 = 换机器就废：" + hint


def test_probe_hint_says_so_when_the_script_is_missing(tmp_path: Path) -> None:
    """★ 判据 1 第二条：目录里没有那份脚本 ⇒ 明说没有，**不给**假命令。"""
    pool = _stale_pool(tmp_path, at="2020-01-01 00:00:00", script=False)
    assert models.probe_command(pool) is None
    hint = models.probe_hint(pool)
    assert "--check" not in hint, "脚本都不在，还给命令就是给假命令：" + hint
    assert "没有" in hint, hint


def test_stale_note_carries_the_probe_command(tmp_path: Path) -> None:
    """★ 判据 2：过期与坏时间戳两态的 snapshot_note 都要带那条命令。"""
    pool = _stale_pool(tmp_path, at="2020-01-01 00:00:00")
    stale = models.load_pool_models(pool)
    assert stale["snapshot_stale"] is True
    assert "--check" in stale["snapshot_note"], stale["snapshot_note"]
    assert (pool / "pool_models.py").as_posix() in stale["snapshot_note"]

    (pool / "models.live.json").write_text(
        json.dumps({"at": "不是时间戳", "live": ["m1"]}), encoding="utf-8"
    )
    bad = models.load_pool_models(pool)
    assert bad["snapshot_stale"] is True
    assert "--check" in bad["snapshot_note"], bad["snapshot_note"]
    assert (pool / "pool_models.py").as_posix() in bad["snapshot_note"]


# ==================================== 卡 E131（T-AG639）：坏文件那几处不许宽捕


def _except_clauses(path: Path) -> list[str | None]:
    """把一份源文件的 `except` 子句的异常类型逐条 unparse 成字符串（裸 except ⇒ None）。"""
    tree = ast.parse(path.read_bytes().decode("utf-8"))
    out: list[str | None] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            out.append(ast.unparse(node.type) if node.type is not None else None)
    return out


def test_pool_readers_never_use_bare_except(tmp_path: Path) -> None:
    """★ 判据 7：坏文件处必须是具名异常元组，**不许** `except:` / `except Exception:`。

    理由不是洁癖：宽捕会把「程序写错了」（AttributeError / TypeError / KeyError）也念成
    「文件坏了」，于是真正的 bug 永远没人看见 —— 判据 2 的 AttributeError 就是这样被吞的。
    """
    for rel in ("tools/pool/models.py", "tools/pool_quota.py"):
        clauses = _except_clauses(ROOT / rel)
        assert None not in clauses, rel + " 里有裸 except:"
        assert not [c for c in clauses if "Exception" in c], rel + " 里有 except Exception"
    got = {
        frozenset(part.strip() for part in c.strip("()").split(","))
        for c in _except_clauses(ROOT / "tools" / "pool" / "models.py")
        if c
    }
    assert frozenset({"OSError", "tomllib.TOMLDecodeError"}) in got, got
    assert frozenset({"OSError", "json.JSONDecodeError"}) in got, got
    quota_got = {
        frozenset(part.strip() for part in c.strip("()").split(","))
        for c in _except_clauses(ROOT / "tools" / "pool_quota.py")
        if c
    }
    assert frozenset({"OSError", "json.JSONDecodeError"}) in quota_got, quota_got

    # 同一条钉子再钉一次「不抛」：五种坏法逐个真跑 load_pool_models。
    good_toml = '[[approved]]\npool = "codebuddy"\nmodel = "m1"\n'
    good_json = '{"live": ["m1"], "live_names": {}, "at": ""}'
    cases = [
        ("坏 TOML", '[[approved]\n', good_json, "whitelist_error"),
        ("坏 JSON", good_toml, "{bad", "snapshot_error"),
        ("approved 是字符串", 'approved = "abc"\n', good_json, "whitelist_error"),
        ("snapshot 是数组", good_toml, "[1, 2, 3]", "snapshot_error"),
        ("approved 条目是字符串", 'approved = ["x"]\n', good_json, "whitelist_error"),
    ]
    for index, (label, whitelist, snapshot, key) in enumerate(cases):
        pool = tmp_path / ("case" + str(index)) / "infra" / "pool"
        pool.mkdir(parents=True, exist_ok=True)
        (pool / "models.whitelist.toml").write_text(whitelist, encoding="utf-8")
        (pool / "models.live.json").write_text(snapshot, encoding="utf-8")
        info = models.load_pool_models(pool)  # 抛了就是这条钉子红
        assert info[key] is not None, label + "：读数没留下证据"
