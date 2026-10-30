r"""卡粘性的纯函数钉子（卡 A345 · `T-AG547`）。

被测：`tools/pool/sticky.py` 的 `stick_for()` / `note()` / `choose()` 与两组 `Why` 常量。
派活器那一侧的接线（`--sticky`、接入点 1/2、`reserve(account=…)`）在
`tests/test_wb_dispatch.py` 里钉 —— 那里要 sandbox 与假工人。

六条钉子（每条后面写「怎么坏掉会红」）：

① `test_stick_expires_after_stick_keep` —— `at = now - STICK_KEEP_S - 1` ⇒ `stick_for()` 回
   `None`；边界（正好 `STICK_KEEP_S`）仍回记录。坏法：判据写成 `>=` ⇒ 边界那一秒的卡被丢掉；
   或者干脆不判过期 ⇒ 记一辈子的号。顺带钉 fail-open：坏 JSON / 形状不对 / 号是空串 ⇒ `None`，
   **绝不抛**（照 `tools/pool/route.py:210 apply_order()` 的纪律）。
② `test_keeps_the_latest_512` —— 记到第 513 张卡 ⇒ 文件里剩 512 条，留下的是 `at` **最大**的
   512 条（最旧那张被挤掉）。坏法：按卡号字典序剪 ⇒ 「最近」变成「最小」；
   或者不剪 ⇒ 文件无界长大。
③ `test_reasons_keep_and_leave_are_disjoint` —— 两组不交叉，且并集**等于**模块里全部 `WHY_*`。
   坏法：漏一个常量到两组之外（新加的 `Why` 谁都不管）；或把某个 `Why` 同时塞进两组。
④ `test_reverse_sticky_must_not_carry_a_spent_account` —— **反向钉子**：`used_percent >=
   USED_SHARE` 的号**不许**被粘上，且 `WHY_SPENT` 必须在「走开」那一组。坏法：把
   `WHY_SPENT` 挪进 `REASONS_KEEP`，或删掉 `choose()` 里比 `USED_SHARE` 的那一支 ⇒ 这次必红。
⑤ `test_gone_account_falls_back` —— 记录里的号已不在账本 / `state != "active"` ⇒
   `choose()` 回 `("", WHY_GONE)`（= 回落正常挑号，不拦派活）。坏法：不复查账本就粘上去 ⇒
   把活派给一个撤掉的号。
⑥ `test_spent_account_falls_back` —— 记录里的号 `used_percent >= USED_SHARE` ⇒
   `("", WHY_SPENT)`；`used_percent` **缺省** ⇒ 当未知、照粘（账本今天就不写这个键，
   见 `infra/pool/accounts.toml`）。坏法：缺省当 100 ⇒ 所有真号都被判 spent、粘性永不生效。

★ 一律用 `TF_POOL_STICKY` 指临时文件 —— **不往真的 `gates/diag/` 里写**（那是 gitignored 的
  运行状态，测试不许碰）。
★ 时间只比**相对**差，不比绝对值：`note()` 按真实时钟修剪（判据 5 的签名只给了 `root`，
  不给 `now`），所以 `NOW` 锚在 `time.time()` 上，`at` 一律写成 `NOW ± 增量`。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from pool import (  # noqa: E402 —— 三个都是本仓包内模块（`tools/` 在 sys.path 上）
    guards,  # lane 闸唯一实现（判据 9：粘性不许覆盖它）
    route,  # 阈值唯一真源（判据 7：不许硬编码 98）
    sticky,  # 被测模块
)

#: 锚在真实钟上（`note()` 的修剪用的是 `time.time()`）；断言只比相对差。
NOW = time.time()


@pytest.fixture()
def store(tmp_path: Path, monkeypatch) -> Path:
    """粘性文件指到 tmp（`TF_POOL_STICKY` 优先于 `root`，与 `pool.sink` 同一手法）。"""
    path = tmp_path / "gates" / "diag" / "pool-sticky.json"
    monkeypatch.setenv(sticky.ENV_STICKY, str(path))
    return path


def _stick(
    card: str = "001",
    account: str = "demo",
    *,
    at: float = NOW,
    why: str = sticky.WHY_CARD,
) -> sticky.Stick:
    return sticky.Stick(card=card, account=account, tree=".wt/a", session="sid-test",
                        model="m", at=at, why=why)


def _account(name: str = "demo", *, state: str = "active", used: object = None) -> dict:
    """账本里的一行（只放本卡判据要读的那几个键）。"""
    row: dict = {"id": name, "state": state}
    if used is not None:
        row["quota"] = {"used_percent": used}
    return row


def test_stick_expires_after_stick_keep(store: Path) -> None:
    """① 过期 ⇒ None；边界不丢；坏文件 / 形状不对 / 空号 ⇒ None（fail-open，绝不抛）。"""
    # ★ 时钟**在本用例内现取**，不用模块级 `NOW`：`note()` 按真实时钟修剪
    #   （`stamp - at > STICK_KEEP_S`），而全量套件从导入到跑本条要几分钟，模块级
    #   `NOW` 早已落后 ⇒ `at=NOW-keep+60` 落盘即被当过期剪掉、这条断言假红。
    #   判据本身没变（仍是「恰好等于不算过期」），变的只是锚点取的时刻。
    now = time.time()
    keep = sticky.STICK_KEEP_S

    sticky.note(_stick(at=now - keep - 1))
    assert sticky.stick_for("001", now=now) is None, "超过 STICK_KEEP_S 的记录必须当没有"

    # ★ 恰好等于 STICK_KEEP_S ⇒ **不算**过期：判据是 `> keep`，写成 `>=` 会把这个边界
    #   一起扔掉（M4 变异就是这么咬住的 —— 少了这一行，改成 `>=` 也照样全绿）。
    sticky.note(_stick(at=now))
    assert sticky.stick_for("001", now=now + keep) is not None, (
        "恰好等于 STICK_KEEP_S 不算过期（判据是『>』，不是『≥』）"
    )

    # 边界两侧都钉：正好错开 60s，`at = now-keep+60` 是「还差 60s 到期」。
    sticky.note(_stick(at=now - keep + 60))
    near = sticky.stick_for("001", now=now + 30)
    assert near is not None, "没超过 STICK_KEEP_S 不算过期"
    assert near.account == "demo"
    assert sticky.stick_for("001", now=now + 90) is None, (
        "超过 STICK_KEEP_S 一点点也必须过期（判据是『>』，不是『≥』）"
    )

    store.write_text("{ 这不是 JSON", encoding="utf-8")
    assert sticky.stick_for("001", now=now) is None, "坏 JSON 必须当没有，不许抛"

    store.write_text(json.dumps({"stick": {"001": {"account": 42}}}), encoding="utf-8")
    assert sticky.stick_for("001", now=now) is None, "形状不对必须当没有，不许抛"

    sticky.note(_stick(account=""))
    assert sticky.stick_for("001", now=now) is None, "号是空串 ⇒ 当没有（不许粘一个空号）"


def test_keeps_the_latest_512(store: Path) -> None:
    """② 记到第 513 张卡 ⇒ 剩 512 条，且留下的是 `at` 最大的 512 条（最旧的被挤掉）。"""
    total = sticky.STICKS_KEPT + 1
    for index in range(total):
        sticky.note(_stick(card=f"k{index:04d}", at=NOW + index))

    body = json.loads(store.read_text(encoding="utf-8"))
    rows = body["stick"]
    assert len(rows) == sticky.STICKS_KEPT, f"应该只剩 {sticky.STICKS_KEPT} 条，实际 {len(rows)}"
    assert "k0000" not in rows, "最旧那张（at 最小）必须被挤掉 —— 说明排序不是字典序"
    assert f"k{total - 1:04d}" in rows, "最新那张必须在"
    stamps = sorted(row["at"] for row in rows.values())
    assert stamps == [NOW + index for index in range(1, total)], \
        "留下的必须正好是 at 最大的 512 条"


def test_reasons_keep_and_leave_are_disjoint() -> None:
    """③ 两组不交叉，且并集**等于**模块里全部 `WHY_*` 常量。"""
    keep = set(sticky.REASONS_KEEP)
    leave = set(sticky.REASONS_LEAVE)
    assert keep & leave == set(), f"两组交叉了：{sorted(keep & leave)}"
    declared = {
        name for name in dir(sticky)
        if name.startswith("WHY_") and isinstance(getattr(sticky, name), str)
    }
    assert declared, "模块里一个 WHY_* 都没有 —— 判据要自己找得到这些常量"
    values = {getattr(sticky, name) for name in declared}
    assert keep | leave == values, (
        f"漏在两组之外的 Why：{sorted(values - (keep | leave))}；"
        f"多出来的：{sorted((keep | leave) - values)}"
    )


def test_reverse_sticky_must_not_carry_a_spent_account(store: Path) -> None:
    """④ **反向**：用尽的号不许被粘上；`WHY_SPENT` 必须待在「走开」那一组。

    坏法二选一都会让这条红：把 `WHY_SPENT` 挪进 `REASONS_KEEP`，或删掉 `choose()` 里
    比 `USED_SHARE` 的那一支（那样 `choose()` 会把这个号当「还可用」粘上去）。
    """
    assert sticky.WHY_SPENT in sticky.REASONS_LEAVE, "`spent` 是走开的理由，不在保留组"
    assert sticky.WHY_SPENT not in sticky.REASONS_KEEP

    spent = _account(used=route.USED_SHARE)
    assert sticky.choose(_stick(), [spent], now=NOW) == ("", sticky.WHY_SPENT), \
        "已经用尽（>= USED_SHARE）的号绝不能被粘上"


def test_gone_account_falls_back(store: Path) -> None:
    """⑤ 号不在账本 / 已停用 ⇒ `gone` + 回落（不拦派活）。"""
    assert sticky.choose(_stick(), [], now=NOW) == ("", sticky.WHY_GONE), \
        "账本里查不到这个号 ⇒ gone"
    other = [_account("someone-else")]
    assert sticky.choose(_stick(), other, now=NOW) == ("", sticky.WHY_GONE)
    for state in ("disabled", "limited", "exhausted", "expired"):
        assert sticky.choose(_stick(), [_account(state=state)], now=NOW) == (
            "", sticky.WHY_GONE), f"state={state} 不算还在用"
    live = [_account("demo")]
    assert sticky.choose(_stick(), live, now=NOW) == ("demo", sticky.WHY_CARD), \
        "还在账本、还 active ⇒ 粘住（否则上面几条就成了『永远 gone』的空钉）"


def test_explicit_account_wins_over_sticky(store: Path) -> None:
    """显式点了号 ⇒ 派活器**根本不该读**粘性（读源码钉死这条门）。

    判据 7 的原文是 `if args.sticky and not args.account:` —— 少了后半句，`--account B`
    就会被记录里的 A 顶掉（人点名的号被静默换成上次的号，是这张卡最危险的坏法）。
    这条不需要起工人：它钉的是那一行门本身。
    """
    source = (ROOT / "tools" / "wb_dispatch.py").read_text(encoding="utf-8")
    gate = "if args.sticky and not args.account:"
    assert source.count(gate) == 1, (
        f"派活器里必须恰好有一处 `{gate}`；实际 {source.count(gate)} 处 —— "
        "少了 `not args.account` 就是显式号被粘性顶掉"
    )
    # 粘性本身也不许替人决定：`choose()` 对着记录照实回，改不改 args 是派活器的事。
    assert sticky.choose(_stick(account="A"), [_account("A"), _account("B")], now=NOW) == (
        "A", sticky.WHY_CARD)


def test_sticky_never_overrides_lane_guard(store: Path) -> None:
    """粘性命中也不能绕过 lane 闸：号占满了，`lane_guard` 照旧咬。

    坏法：为了让粘性「总能用上」去放宽 `guards.lane_guard` 或给 `reserve()` 传个假 limit ——
    那样一个会被同时派两张卡，是这张卡的收益换来的真代价。
    """
    account, why = sticky.choose(_stick(account="demo"), [_account("demo")], now=NOW)
    assert (account, why) == ("demo", sticky.WHY_CARD), "前提：这条记录本来粘得上"

    live = [{"card": "999", "account": account, "at": "2023-11-14T22:13:20",
             "tree": ".wt/other", "files": [], "ttl_seconds": 3600.0}]
    problems = guards.lane_guard(account, live, limit=1, now=NOW)
    assert problems, "号已经在上限上 ⇒ lane 闸必须咬（粘性不许把它洗白）"
    assert "上限 1 张" in problems[0]


def test_spent_account_falls_back(store: Path) -> None:
    """⑥ `used_percent >= USED_SHARE` ⇒ `spent`；缺这个键 ⇒ 当未知、照粘。"""
    assert sticky.choose(_stick(), [_account(used=route.USED_SHARE)], now=NOW) == (
        "", sticky.WHY_SPENT)
    assert sticky.choose(_stick(), [_account(used=100.0)], now=NOW) == ("", sticky.WHY_SPENT)
    assert sticky.choose(_stick(), [_account(used=route.USED_SHARE - 0.1)], now=NOW) == (
        "demo", sticky.WHY_CARD), f"差一点没用尽（< {route.USED_SHARE}）仍然可以粘"
    assert sticky.choose(_stick(), [_account()], now=NOW) == ("demo", sticky.WHY_CARD), \
        "账本今天不写 used_percent（`source = \"unknown\"`）⇒ 当未知，不许当用尽"
