"""卡 A344（T-AG546）钉子：人给的名字 ↔ 账本稳定 id 的唯一映射.

判据原文见 `复盘/卡/卡A344-名字与号对不上闸就永远不生效.md` 判据 1 + 钉子表 1-9。
十条钉子（第 10 条是父代理裁定加的：③ 步**只认 `kind == "dir"`**，
文件类凭据的末段是**存储名不是号名** —— 得有一枚钉子证明排除的是 kind，不是巧合）：

| 用例名 | 断言什么 |
|---|---|
| `test_profile_key_wins` | `profile = "demo"` ⇒ 回它的 id、依据为空串 |
| `test_stable_id_itself_passes_through` | 直给 `codebuddy-tongxue3` ⇒ 原样回、依据为空串 |
| `test_locator_basename_is_the_last_resort` | 没有 profile 键 ⇒ `kind=dir` 的 locator 末段 |
| `test_locator_is_not_a_general_rule` | `codearts-1` 的末段 `pool.env` **不**被当 profile 名命中 |
| `test_file_credential_is_never_a_name` | `kind=file` + 末段**恰好**等于某个 id ⇒ 也不许命中 |
| `test_ambiguity_is_loud` | 两条都声称同一 profile ⇒ `AccountMapError` 点名两条 id |
| `test_unmatched_falls_back_and_says_so` | 三步不中 ⇒ `(原名, 非空依据)`，不抛 |
| `test_empty_profile_resolves_to_nothing` | 空串 / 全空白 ⇒ `("", "")`，不匹配任何一条 |
| `test_kind_none_credential_is_skipped` | `kind="none"` 且无 locator 的行不参与 ③ 也不炸 |
| `test_pure_no_io` | **函数体内**不出现 `open(` / `Path(` / `os.environ` / `subprocess` |

★ `test_pure_no_io` 钉的是 `resolve_account_id()` 的**函数体**（含 docstring），不是整个模块：
  拆分 locator 末段的 helper `_basename()` 故意放在模块级 —— 纯函数的边界是「这个函数不碰 IO」，
  不是「这个文件里不许出现 `Path` 这个词」。
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from pool import account_id  # noqa: E402
from pool.account_id import (  # noqa: E402
    NO_STABLE_ID,
    AccountMapError,
    resolve_account_id,
)


def _row(
    ident: str,
    *,
    profile: str | None = None,
    kind: str = "dir",
    locator: str | None = "~/.x/y",
) -> dict:
    """造一条 `[[account]]` 行（只带本题要用的键；账本校验归 `pool_accounts` 那边）。"""
    row: dict = {"id": ident}
    if profile is not None:
        row["profile"] = profile
    cred: dict = {"kind": kind}
    if locator is not None:
        cred["locator"] = locator
    row["credential"] = cred
    return row


#: 与仓外真账本同形状的四条（今天一条 `profile` 键都没有 —— 这是判据的起点）。
def _ledger() -> list[dict]:
    return [
        _row("codearts-1", kind="file", locator="~/.codeartsdoer/pool.env"),
        _row("codebuddy-tongxue3", kind="dir", locator="~/codebuddy-accounts/tongxue3"),
        _row("workbuddy-1", kind="dir", locator="~/.workbuddy"),
        _row("trae-1", kind="dir", locator="~/.trae"),
    ]


# ============================================================ ① profile 键优先
def test_profile_key_wins() -> None:
    """账本里写了 `profile = "demo"` ⇒ 回它的 id，**依据为空串**（身份是直接给出来的，不必推断）。

    ★ 若有人把 ① 步挪到 ② 之后、或干脆删掉这一步，`demo` 会落到 ③/兜底 ⇒ 红。
    """
    rows = [
        *_ledger(),
        _row("codebuddy-demo", profile="demo", locator="~/codebuddy-accounts/tongxue3"),
    ]
    got = resolve_account_id("demo", rows)
    assert got == ("codebuddy-demo", "")


# ============================================================ ② 稳定 id 直给
def test_stable_id_itself_passes_through() -> None:
    """直接给账本的稳定 id ⇒ 原样回、依据为空串（允许人绕开映射直写 id）。"""
    got = resolve_account_id("codebuddy-tongxue3", _ledger())
    assert got == ("codebuddy-tongxue3", "")


# ============================================================ ③ locator 末段（唯一今天能用的路）
def test_locator_basename_is_the_last_resort() -> None:
    """没有 `profile` 键时，`kind=dir` 的 `credential.locator` 末段就是号名（codebuddy 那一条）。

    ★ 依据必须**非空**：调用方要靠它决定「要不要打那行实话」——
      推断出来的身份不许与「直接给出来的」混成一样。
    ★ 反斜杠写法（Windows 习惯）也要认：末段就是末段。
    """
    for locator in ("~/codebuddy-accounts/tongxue3", r"~\codebuddy-accounts\tongxue3"):
        rows = [_row("codebuddy-tongxue3", kind="dir", locator=locator)]
        ident, why = resolve_account_id("tongxue3", rows)
        assert ident == "codebuddy-tongxue3"
        assert why, "③ 步命中的依据必须是**非空**说明（推断来的身份要能被人看出来）"
        assert "locator" in why


# ============================================================ ③ 不是通用规则（范畴错误）
def test_locator_is_not_a_general_rule() -> None:
    """`codearts-1` 的末段 `pool.env` **不会**被当 profile 名命中。

    `~/.codeartsdoer/pool.env` 是**所有** codearts 号共用的一个凭据文件 ——
    末段是**存储名不是号名**。所以拿 `pool.env` 当账号名必须落回兜底，不许回 `codearts-1`。
    ★ 反向验证「③ 改成匹配任何 locator 末段」时，这条必红。
    """
    ident, why = resolve_account_id("pool.env", _ledger())
    assert ident == "pool.env"
    assert ident != "codearts-1"
    assert why == NO_STABLE_ID


# ============================================================ ③ 排除的是 kind，不是巧合
def test_file_credential_is_never_a_name() -> None:
    """`kind="file"` 的行即使末段**恰好**等于某个 id，也不许命中那个 id。

    这条证明 `test_locator_is_not_a_general_rule` 排除的是**凭据形状**（file = 共享存储），
    不是「恰好 `pool.env` 不是某个 profile 名」这种巧合。
    """
    # 号的 id 与文件末段**故意不同**（`codearts-prod` vs `pool.env` 那种共享存储命名），
    # 这样 ② 步不会先命中 id，单钉 ③。
    rows = [
        _row("codearts-prod", kind="file", locator="~/somewhere/codearts-1"),
        _row("codebuddy-tongxue3", kind="dir", locator="~/codebuddy-accounts/tongxue3"),
    ]
    assert resolve_account_id("codearts-1", rows) == ("codearts-1", NO_STABLE_ID)
    # 同一形状换成 dir 就该命中 —— 差别只在 kind，证明排除的是凭据形状不是名字。
    dirs = [_row("codearts-prod", kind="dir", locator="~/somewhere/codearts-1")]
    assert resolve_account_id("codearts-1", dirs)[0] == "codearts-prod"


# ============================================================ 歧义必须响亮
def test_ambiguity_is_loud() -> None:
    """两条都声称同一 profile ⇒ `AccountMapError`，文案点名**两条** id。

    ★ 反向验证「歧义取第一条」⇒ 这条必红。
    """
    rows = [
        _row("codebuddy-a", profile="demo", locator="~/a"),
        _row("codebuddy-b", profile="demo", locator="~/b"),
    ]
    with pytest.raises(AccountMapError) as caught:
        resolve_account_id("demo", rows)
    text = str(caught.value)
    assert "codebuddy-a" in text
    assert "codebuddy-b" in text
    assert "歧义" in text


def test_ambiguity_in_step_three_is_loud_too() -> None:
    """③ 步也会歧义：两个目录末段同名 ⇒ 抛（不取第一条）。"""
    rows = [
        _row("codebuddy-a", kind="dir", locator="~/accounts/demo"),
        _row("codebuddy-b", kind="dir", locator="~/other/demo"),
    ]
    with pytest.raises(AccountMapError) as caught:
        resolve_account_id("demo", rows)
    assert "codebuddy-a" in str(caught.value)
    assert "codebuddy-b" in str(caught.value)


# ============================================================ 三步不中 ⇒ 诚实回落
def test_unmatched_falls_back_and_says_so() -> None:
    """三步都不中 ⇒ `(原名, 非空依据)`，**不抛**（今天本来就是这样，派活不许因此断掉）。

    ★ 反向验证「不中时抛错」⇒ 这条必红。
    """
    got = resolve_account_id("nobody-named-this", _ledger())
    assert got == ("nobody-named-this", NO_STABLE_ID)
    assert got[1], "回落的依据必须非空 —— 静默回落正是本卡要消灭的东西"


# ============================================================ 空输入不匹配任何一条
def test_empty_profile_resolves_to_nothing() -> None:
    """空串 / 全空白 ⇒ `("", "")`；**不许**匹配上任何一条（连「有 row 的 profile 是空」也不行）。"""
    rows = [
        _row("codebuddy-blank", profile="", locator="~/accounts/"),
        _row("codebuddy-space", profile="   ", locator="~/accounts/   "),
        *_ledger(),
    ]
    assert resolve_account_id("", rows) == ("", "")
    assert resolve_account_id("   ", rows) == ("", "")
    assert resolve_account_id("", []) == ("", "")


# ============================================================ kind=none 跳过 ③
def test_kind_none_credential_is_skipped() -> None:
    """`credential.kind == "none"`（无 locator）的行不参与 ③，也**不许炸**。"""
    rows = [
        _row("manual-1", kind="none", locator=None),
        _row("codebuddy-tongxue3", kind="dir", locator="~/codebuddy-accounts/tongxue3"),
    ]
    assert resolve_account_id("tongxue3", rows)[0] == "codebuddy-tongxue3"
    assert resolve_account_id("manual-1", rows) == ("manual-1", "")
    assert resolve_account_id("anything", rows) == ("anything", NO_STABLE_ID)
    # 没有 credential 表 / credential 不是 dict 的行也只是被跳过，不许 KeyError。
    assert resolve_account_id("x", [{"id": "no-cred"}]) == ("x", NO_STABLE_ID)
    assert resolve_account_id("x", [{"id": "bad-cred", "credential": "oops"}]) == (
        "x",
        NO_STABLE_ID,
    )


# ============================================================ 纯函数：不碰 IO
def test_pure_no_io() -> None:
    """`resolve_account_id()` 的**函数体**里不出现 `open(` / `Path(` / `os.environ` / `subprocess`。

    ★ 钉的是函数体（含 docstring），不是整个文件：`_basename()` 是模块级 helper，本来就不该
      被算进「这个函数不碰 IO」的范围。若有人把读账本的代码塞进 `resolve_account_id()`，
      这条会红。
    """
    body = inspect.getsource(account_id.resolve_account_id)
    for bad in ("open(", "Path(", "os.environ", "subprocess"):
        assert bad not in body, (
            f"resolve_account_id() 里出现了 IO 记号 {bad!r}（判据 1 要求纯函数）"
        )
    # `load_account_ids()` 是**唯一**允许读账本的那一半，且必须吞掉 LedgerError 回空列表。
    loader = inspect.getsource(account_id.load_account_ids)
    assert "LedgerError" in loader
    assert "return []" in loader
