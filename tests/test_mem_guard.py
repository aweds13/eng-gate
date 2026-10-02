"""核「跑门禁/派活之前先过**内存闸**」会不会咬（T-G198 · 卡 102）。

## 为什么有这张测试

病根（主控 2026-10-01 亲历）：跑门禁/派活**只看"我该不该跑"，不看"这台机器扛不扛得住"**。
16.3 GB 机器上并行两趟门禁 + 4 个工人 + 无头 Edge + serve.py，同时用户在玩游戏 → 可用内存掉到
~3 GB、MemCompression 起 310 MB、整机慢 6 倍（pytest 884s vs 146s），**用户的游戏被挤崩**。
本卡：`scripts/run_gates.py` 与 `tools/wb_dispatch.py` 在开跑/派活前读**可用**内存，低于
`TF_GATE_MIN_FREE_GB`（默认 4.0，`0` = 关）就拒跑/不派活，并说清两个数、后果、怎么放行。

## 怎么验（用**桩**，不真动机器内存）

`monkeypatch` 掉 `available_memory_gb`（两个模块各一份）造"可用内存"。每条判据都配**反例**：
正常内存不许被误拦、关掉闸要好使、读不到不许当通过也不许拒跑。★ 真读那条只验"给正数或 None"。

## 边界（如实写，未覆盖）

- **不跑 `run_gates.main()` 的"正常内存"全量**（那会真跑整套门禁）：正常那一态用
  `memory_gate_problem()` 直接钉（它就是 `main()` 走到的那一条判据），低内存那一态才走 `main()`
  真路径并断言 **零门被启动**。
- `wb_dispatch` 的"正常内存"用 `preflight()` + dry-run `main()` 钉；"低内存不派活"用 `main()` 钉。
- POSIX 的 `os.sysconf` 分支没在本机（Windows）真跑过。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tools"))

import run_gates as rg  # noqa: E402 —— 需要先用 sys.path 把 scripts/ 挂上
import wb_dispatch as wd  # noqa: E402 —— 需要先用 sys.path 把 tools/ 挂上

# ============================================================ 纯函数：真读 + 阈值解析


def test_available_memory_reads_a_positive_number_or_gives_up() -> None:
    """真读一次：要么给正数（GB），要么如实说读不到（None）—— 不许给 0/负数糊人。"""
    val = rg.available_memory_gb()
    assert val is None or val > 0


def test_default_threshold_is_4gb(monkeypatch: pytest.MonkeyPatch) -> None:
    """不设变量 → 默认 4.0（两个模块同一口径）。"""
    monkeypatch.delenv("TF_GATE_MIN_FREE_GB", raising=False)
    assert rg.gate_min_free_gb() == 4.0
    assert wd.gate_min_free_gb() == 4.0


def test_bad_threshold_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """坏阈值 → 退回默认（不静默、不当成 0）。"""
    monkeypatch.setenv("TF_GATE_MIN_FREE_GB", "abc")
    assert rg.gate_min_free_gb() == 4.0


# ============================================================ run_gates：三条判据 + 反例


def test_low_memory_refuses_before_any_gate(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """★ 假"可用 1 GB" + 阈值 4 GB → `main()` 拒跑、退出码 3、输出里有 1.0/4.0 两个数、
    后果人话 + 怎么放行，且**没有任何门被启动过**。"""
    monkeypatch.setenv("TF_GATE_MIN_FREE_GB", "4")
    monkeypatch.setattr(rg, "available_memory_gb", lambda: 1.0)
    started: list[object] = []
    monkeypatch.setattr(rg, "start_gate",
                        lambda *a, **k: started.append(a) or (None, 0.0, "x"))
    monkeypatch.setattr(sys, "argv", ["run_gates.py", "--quick"])

    rc = rg.main()
    out = capsys.readouterr().out

    assert rc == 3                          # 非 0；不是 124（那是"门超时"）
    assert "1.0" in out and "4.0" in out    # ★ 两个数都在
    assert "游戏" in out                    # 后果人话
    assert "TF_GATE_MIN_FREE_GB=0" in out   # 怎么放行
    assert started == []                    # ★ 一道门都没起


def test_normal_memory_is_not_blocked(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """★ 反例：假"可用 8 GB" + 阈值 4 GB → 放行（不许误拦正常情况）。"""
    monkeypatch.setenv("TF_GATE_MIN_FREE_GB", "4")
    monkeypatch.setattr(rg, "available_memory_gb", lambda: 8.0)
    assert rg.memory_gate_problem() is None
    assert "放行" in capsys.readouterr().out


def test_zero_threshold_disables_the_gate(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """★ 反例：`TF_GATE_MIN_FREE_GB=0` → 永不拒跑（哪怕可用内存几乎没了），且打一行"闸已关"。"""
    monkeypatch.setenv("TF_GATE_MIN_FREE_GB", "0")
    monkeypatch.setattr(rg, "available_memory_gb", lambda: 0.001)
    assert rg.memory_gate_problem() is None
    assert "已关" in capsys.readouterr().out


def test_unreadable_memory_skips_without_refusing(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """★ 反例：读不到内存（桩成抛异常）→ **跳过**并打印说明，**不拒跑**（不当通过、也不乱拦）。"""
    monkeypatch.setenv("TF_GATE_MIN_FREE_GB", "4")

    def _boom() -> float:
        raise OSError("读不到内存")

    monkeypatch.setattr(rg, "available_memory_gb", _boom)
    assert rg.memory_gate_problem() is None
    assert "读不到" in capsys.readouterr().out


def test_unreadable_memory_returning_none_also_skips(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """读不到（函数直接回 None，不抛）→ 同样跳过、不拒跑。"""
    monkeypatch.setenv("TF_GATE_MIN_FREE_GB", "4")
    monkeypatch.setattr(rg, "available_memory_gb", lambda: None)
    assert rg.memory_gate_problem() is None
    assert "读不到" in capsys.readouterr().out


# ============================================================ wb_dispatch：同一套闸


@pytest.fixture()
def dispatch_sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """一个"像仓库"的临时根（规格在、node/CLI 在、工作区干净、登录通）。

    ★ 这里**不**关内存闸（与 `test_wb_dispatch.py` 的 sandbox 不同）—— 本文件就是要真验它。
    ★ 卡 125：`preflight()` 现在还走**守卫**（树 / 冲突域 / 门禁锁）—— 本文件考的是**内存闸**，
      不该被队列守卫连坐 ⇒ 把守卫需要的环境补齐（写一份最小队列、隔离登记、桩掉锁原文）。
      **判据一个字没松**（不是把守卫关掉，是把它要读的输入喂进沙箱）。
    """
    (tmp_path / "spec.md").write_text("卡规格", encoding="utf-8")
    node = tmp_path / "node.exe"
    cli = tmp_path / "codebuddy"
    node.write_text("", encoding="utf-8")
    cli.write_text("", encoding="utf-8")
    monkeypatch.setattr(wd, "ROOT", tmp_path)
    monkeypatch.setattr(wd, "paths", lambda *a, **k: (node, cli))
    monkeypatch.setattr(wd, "git_dirty", lambda: [])
    monkeypatch.setattr(wd, "auth_ok", lambda *a, **k: (True, "登录自检通过"))
    # ★ 卡 125：守卫的输入 —— 队列写一份（卡 102 的冲突域）、登记用 `TF_POOL_REGISTRY` 隔离到
    #   沙箱（绝不读主树那份真登记）、锁原文用桩（真跑 `gate_lock.py status` 会把宿主活锁读进来）。
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "workbacklog.toml").write_text(
        '[base]\nreviewed = "mem-guard-sandbox"\n\n'
        '[[cards]]\nid = "102"\ntask = "T-G198"\ntitle = "内存闸"\n'
        'tree = ""\nspec = "spec.md"\nfiles = ["sandbox-102.md"]\n',
        encoding="utf-8")
    monkeypatch.setenv("TF_POOL_REGISTRY",
                       str(tmp_path / "gates" / "diag" / "pool-registry.json"))
    monkeypatch.setattr(wd.pool_registry, "read_lock_body", lambda *a, **k: "")
    return tmp_path


def test_wb_preflight_reports_low_memory(
    dispatch_sandbox: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """前置检查里出现内存那条（含两个数）。"""
    monkeypatch.setenv("TF_GATE_MIN_FREE_GB", "4")
    monkeypatch.setattr(wd, "available_memory_gb", lambda: 0.5)
    problems, _log = wd.preflight("102", "spec.md", force=False, check_auth=False)
    assert any("可用内存 0.5 GB < 阈值 4.0 GB" in p for p in problems)


def test_wb_low_memory_does_not_dispatch(
    dispatch_sandbox: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """★ 走完整 `main()`：低内存 → 退 2、报错，且**没有派活**（`run_worker` 一次没被调）。"""
    monkeypatch.setenv("TF_GATE_MIN_FREE_GB", "4")
    monkeypatch.setattr(wd, "available_memory_gb", lambda: 1.0)
    dispatched: list[object] = []
    monkeypatch.setattr(wd, "run_worker",
                        lambda *a, **k: dispatched.append(a) or (0, "", "", "sid"))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "102", "--spec", "spec.md",
                                      "--execute"])

    assert wd.main() == 2
    err = capsys.readouterr().err
    assert "1.0" in err and "4.0" in err and "游戏" in err
    assert dispatched == []                 # ★ 没派活


def test_wb_normal_memory_still_passes(
    dispatch_sandbox: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """★ 反例：假"可用 8 GB" → 前置检查不拦，dry-run 照旧走完（退 0）。"""
    monkeypatch.setenv("TF_GATE_MIN_FREE_GB", "4")
    monkeypatch.setattr(wd, "available_memory_gb", lambda: 8.0)
    problems, _log = wd.preflight("102", "spec.md", force=False, check_auth=False)
    assert problems == []
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "102", "--spec", "spec.md"])
    assert wd.main() == 0


def test_wb_zero_and_unreadable_never_refuse(
    dispatch_sandbox: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """★ 反例：`=0` 与"读不到"两种情况下，前置检查都不因内存拒派。"""
    monkeypatch.setenv("TF_GATE_MIN_FREE_GB", "0")
    monkeypatch.setattr(wd, "available_memory_gb", lambda: 0.001)
    problems, _log = wd.preflight("102", "spec.md", force=False, check_auth=False)
    assert problems == []

    monkeypatch.setenv("TF_GATE_MIN_FREE_GB", "4")
    monkeypatch.setattr(wd, "available_memory_gb", lambda: None)
    problems, _log = wd.preflight("102", "spec.md", force=False, check_auth=False)
    assert problems == []
