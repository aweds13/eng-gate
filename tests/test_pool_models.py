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
