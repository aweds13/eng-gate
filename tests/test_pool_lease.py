r"""租约命令行（`tools/pool/lease.py`，卡 195 · T-G295）的测试 —— 三条反例钉子。

**为什么值当测**：派活有两个入口，只有 CodeBuddy 那条（`wb_dispatch`）写租约；码道那条
（`infra/pool/dispatch.py`）不写 ⇒ 守卫看不见码道那一半。本 CLI 把码道那条路接进**同一本账**。
三条钉子钉的是"**同一本账**"这件事本身 —— 故意坏掉会红：

| 钉子 | 钉什么 | 怎么坏掉会红 |
|---|---|---|
| ① 跨入口相交 | `lease.claim` 写的账，`registry.reserve`（CodeBuddy 那条路）也能读到 ⇒ 守卫拦得住
    `registry.reserve` 看不到 ⇒ 拦不住 |
| ② release 之后不再拦 | `lease.release` 真删了那条租约 ⇒ 再 claim 同一文件能过 | release 不真删 ⇒
    |
| ③ 字段同形 | `lease.claim` 写下的记录能被**现有守卫**（`guards.domain_guard`）原样读到 | 字段名 /
    |

★ 一律用 `TF_POOL_REGISTRY` 指临时目录 —— **不往真的 `gates/diag/` 里写**。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from pool import (  # noqa: E402 —— tools/ 已在 sys.path 上
    guards,
    lease,  # noqa: E402
    registry,
)

NOW = 1_700_000_000.0


@pytest.fixture()
def reg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把登记文件指到临时目录（**绝不动真的 `gates/diag/pool-registry.json`**）。"""
    path = tmp_path / "reg.json"
    monkeypatch.setenv("TF_POOL_REGISTRY", str(path))
    return path


@pytest.fixture()
def quiet_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    """守卫里的门禁锁一律当"空着" —— 测试不依赖真的门禁锁文件。"""
    monkeypatch.setattr(registry, "read_lock_body", lambda *a, **k: "")


# ================================================================ ① 跨入口相交看得见


def test_nail_1_cross_entry_intersection_is_seen(reg: Path, quiet_lock: None,
                                                 capsys: pytest.CaptureFixture) -> None:
    """钉子①：`lease.claim`（码道入口）写的账，`registry.reserve`（CodeBuddy 入口）也看得见
    ⇒ 守卫能看出相交。

    ★ 故意坏掉会红：若 `lease.claim` 另起一本账（不写 `registry` 那份），则
      `registry.reserve` 看不到它 ⇒ 下面那条直接调 `registry.reserve` 的断言会抛
      `GuardError` 不发生 ⇒ `pytest.raises` 失败。
    """
    # 码道入口登记卡 154 占 shared.py
    assert lease.main(["claim", "--card", "154", "--tree", ".wt/a",
                       "--files", "shared.py"]) == 0
    capsys.readouterr()

    # 码道入口再登记卡 166 占同一文件 ⇒ 守卫咬（退 1，逐条点名）
    assert lease.main(["claim", "--card", "166", "--tree", ".wt/b",
                       "--files", "shared.py"]) == 1
    err = capsys.readouterr().err
    assert "冲突域相交" in err and "shared.py" in err

    # ★ 跨入口：CodeBuddy 那条路（`registry.reserve` 直接调）也看得见 lease 写的那条
    #   —— 这是本卡的要害。若另起一本账，这条 `pytest.raises` 就不成立。
    with pytest.raises(registry.GuardError) as exc:
        registry.reserve("177", tree=".wt/c", files=["shared.py"], now=NOW)
    assert any("冲突域相交" in p and "shared.py" in p for p in exc.value.problems)
    # 且登记文件里确实只有 lease 写的那一条（没被 registry.reserve 多写）
    rows = json.loads(reg.read_text(encoding="utf-8"))
    assert [r["card"] for r in rows] == ["154"]


# ================================================================ ② release 之后不再拦


def test_nail_2_release_clears_the_lease(reg: Path, quiet_lock: None,
                                         capsys: pytest.CaptureFixture) -> None:
    """钉子②：`lease.release` 之后那条租约不再拦 ⇒ 再 claim 同一文件能过。

    ★ 故意坏掉会红：若 `lease.release` 不真删（或删了另一本账里的），再 claim 会被咬
      ⇒ 退出码 1 ⇒ `== 0` 断言失败。
    """
    assert lease.main(["claim", "--card", "154", "--tree", ".wt/a",
                       "--files", "shared.py"]) == 0
    capsys.readouterr()

    assert lease.main(["release", "--card", "154"]) == 0
    capsys.readouterr()

    # 同一文件再 claim（不同卡）⇒ 应该能过（退 0）
    assert lease.main(["claim", "--card", "166", "--tree", ".wt/b",
                       "--files", "shared.py"]) == 0
    out = capsys.readouterr().out
    assert "已登记" in out
    # 登记文件里只剩卡 166 那一条
    rows = json.loads(reg.read_text(encoding="utf-8"))
    assert [r["card"] for r in rows] == ["166"]


# ================================================================ ③ claim
    # 写下的记录能被现有守卫原样读到


def test_nail_3_claim_record_is_readable_by_existing_guards(
        reg: Path, quiet_lock: None, capsys: pytest.CaptureFixture) -> None:
    """钉子③：`lease.claim` 写下的记录**能被现有守卫原样读到**（字段名 / 位置与
    CodeBuddy 那条路一致）。

    ★ 故意坏掉会红：若 `lease.claim` 把字段写成 `file_list` / `tree_path` 之类，
      `guards.domain_guard` 读 `res.get("files")` ⇒ 拿不到 ⇒ 拦不住 ⇒
      `assert problems` 失败。
    """
    assert lease.main(["claim", "--card", "154", "--tree", ".wt/a",
                       "--files", "shared.py", "other.py"]) == 0
    capsys.readouterr()

    # ① 字段名与 registry.reserve 写的逐字一致
    rows = json.loads(reg.read_text(encoding="utf-8"))
    assert len(rows) == 1
    entry = rows[0]
    assert entry["card"] == "154"
    assert entry["tree"] == ".wt/a"
    assert entry["files"] == ["shared.py", "other.py"]
    # 这些字段是守卫 / 死租约判据要读的 —— 缺一个就判不了
    for key in ("owner", "at", "ttl_seconds"):
        assert key in entry, f"字段 {key} 缺失 ⇒ 守卫 / 死租约判据读不到"

    # ② 现有守卫（guards.domain_guard）原样读这条记录 ⇒ 能拦住另一个卡占同一文件
    live = registry.list_reservations(NOW)
    assert [r["card"] for r in live] == ["154"]
    problems = guards.domain_guard(["shared.py"], live, NOW)
    assert problems, "守卫没拦住 ⇒ lease 写的字段守卫读不到（字段名不一致）"
    assert any("冲突域相交" in p and "shared.py" in p for p in problems)

    # ③ 与 CodeBuddy 那条路（registry.reserve）写的字段**同形**
    #   —— 同一棵树、同一文件，直接调 registry.reserve 写一条，比对字段集合
    reg.unlink()
    lease.main(["claim", "--card", "200", "--tree", ".wt/x",
                "--files", "z.py"])
    capsys.readouterr()
    lease_entry = json.loads(reg.read_text(encoding="utf-8"))[0]
    reg.unlink()
    registry.reserve("200", tree=".wt/x", files=["z.py"], now=NOW)
    registry_entry = json.loads(reg.read_text(encoding="utf-8"))[0]
    assert set(lease_entry.keys()) == set(registry_entry.keys()), (
        "lease 与 registry.reserve 写的字段集合不一致 ⇒ 守卫读到的形状不同")
