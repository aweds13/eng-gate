r"""人给的名字 ↔ 账本里的那个号：唯一映射（卡 A344 · T-AG546）。

**防什么**：`tools/wb_dispatch.py --account` 收的是**人给的名字**（仓外
`codebuddy_accounts.py` 的 profile 名，实测只有 `tongxue3`），而三条闸查表用的键是
`infra/pool/accounts.toml` 的**稳定 id**（`codebuddy-tongxue3`、`codearts-1`、`trae-1`）。
两套名字之间**仓内零映射代码** ⇒ A339 的每账号并发闸（`tools/pool/lanes.toml`）、A340 的
每分钟闸（`tools/pool/rpm.toml`）、A341 的账号模型白名单（仓外 `limits.toml` 的
`[accounts."<id>"]`）**三条今天一次也不会拦** —— 配了、看着生效、实际谁也不拦，
正是本仓最忌的那种「静默失效」。

**为什么是纯函数**：判据只有一份，且要在三个地方被同一份判据使用（派活 / MCP 干跑 /
测试）。读文件的那一半（哪份账本、怎么读）归 `tools/pool_accounts.py`；本模块只收
`rows`（`[[account]]` 表的行），**不读文件、不读环境、不碰网络** —— 于是它可以在没有账本
的机器上被单测钉死，也不会因为「账本今天读不到」而换一套判据。

**三步顺序固定**（顺序本身是判据的一部分，别调换）：

1. **`profile` 键优先**：账本里写了 `profile = "<名>"` 的那一条。这是将来精确口径的来源
   —— 今天**一条都没有**（本卡不许替人往仓外账本里写这个键）。
2. **稳定 id 直给**：人直接写 `--account codebuddy-tongxue3` 也认（允许绕开映射）。
3. **`credential.locator` 末段**：`~/codebuddy-accounts/tongxue3` 的末段恰好是 profile 名。
   ★★ **只对 `credential.kind == "dir"` 的行成立**，理由不是"恰好"，而是范畴：
   - `dir` = **一个目录一个号**，目录名就是这个号的号名 ⇒ 末段当号名是**成立的推断**；
   - `file` = **一个文件可能是许多号共用的存储**：`~/.codeartsdoer/pool.env` 是**所有**
     codearts 号共用的一个凭据文件，末段 `pool.env` 是**存储名不是号名** ——
     拿它当账号名属于范畴错误，不是因为"恰好没人这么叫"才不命中。
   所以 `none` / `file` / 任何其它 kind 一律跳过 ③。

**歧义必须响亮**：①/②/③ 各自命中多于一条 ⇒ 抛 `AccountMapError` 并点名是哪几条 id。
**不许取第一条** —— 取第一条 = 悄悄替人挑一个号。

**三步都不中 ⇒ 回落原名，但把实话带出去**：返回 `(profile, "账本里没有这个 profile 的稳定 id")`，
**不抛**（今天本来就是这样，派活不许因此断掉）。调用方（`wb_dispatch.resolve_account()`）
负责把这句话打给人看 —— 「对不上」不许静默。

**边界（如实写）**：本模块不判活、不写文件、不联网、不起进程；`load_account_ids()` 那个薄壳
只给「只读展示」用，**判据本身不接受「读不到账本」这个输入**。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

try:  # 仓内两种导入形状都认：`tools/` 在 sys.path 上时是前者，包内导入是后者。
    import pool_accounts
except ImportError:  # pragma: no cover - 只在 `import tools.pool.account_id` 时走到
    from tools import pool_accounts

if TYPE_CHECKING:
    from collections.abc import Sequence

#: 三步都不中时那句话 —— 调用方靠它区分「回落」与「真解析出来了」。
NO_STABLE_ID = "账本里没有这个 profile 的稳定 id"

#: ③ 步唯一认的凭据形状（见模块 docstring 的「一个目录一个号」）。
LOCATOR_KIND = "dir"


class AccountMapError(ValueError):
    """名字 ↔ 号 解析不了（歧义 / 账本读不懂）—— 点名到具体 id，**不许**悄悄挑一个。"""


def _basename(locator: object) -> str:
    """取 locator 的末段（`~/.x/y` 与 `C:\\x\\y` 都认；不碰文件系统）。

    放在模块级（不在 `resolve_account_id()` 体内）有两个原因：
    ① 纯函数的钉子钉的是**函数体**里不出现 `Path(` / `open(` —— 拆分放在这里就干净；
    ② Windows 上 `pathlib.Path("~/a/b").name` 与 POSIX 解释一致，但 `PureWindowsPath`
       对 `\\` 才认。我改成先归一化分隔符再切，两种写法都给同一个答案，少一个平台坑。
    """
    text = str(locator).strip().replace("\\", "/")
    return text.rsplit("/", 1)[-1]


def _ids(rows: Sequence[dict]) -> str:
    """把命中的几条 id 拼成人能读的一串（只给报错文案用）。"""
    named = [str(row.get("id") or "").strip() or "（无 id）" for row in rows]
    return "、".join(named)


def resolve_account_id(profile: str, rows: Sequence[dict]) -> tuple[str, str]:
    """把 `profile`（人给的名字）解析成账本稳定 id；回 `(id, 依据说明)`。

    依据为空串 = 身份是**直接给出来的**（① 命中 `profile` 键 / ② 人直接给了 id），不必推断。
    依据非空 = 这个 id 是**推断/回落**来的，调用方应当把它打给人看。
    """
    want = str(profile or "").strip()
    if not want:
        # 钉 7：空串 / 全空白 ⇒ ("", "")，**不许**匹配上任何一条
        # （否则 `--account ""` 可能撞上一个 profile 键为空的账本行）。
        return ("", "")

    table = [row for row in rows if isinstance(row, dict)]

    # ① `profile` 键优先（将来精确口径的来源）。
    hit = [row for row in table if str(row.get("profile") or "").strip() == want]
    if len(hit) > 1:
        raise AccountMapError(
            f"歧义：账本里有 {len(hit)} 条都声称 profile = 「{want}」（{_ids(hit)}）"
            " ⇒ 不猜、不取第一条；请人工把重复的 profile 键去掉一条，或改用稳定 id",
        )
    if hit:
        return (str(hit[0].get("id") or "").strip(), "")

    # ② 稳定 id 直给。
    hit = [row for row in table if str(row.get("id") or "").strip() == want]
    if len(hit) > 1:
        raise AccountMapError(
            f"歧义：账本里有 {len(hit)} 条 id 都等于「{want}」（{_ids(hit)}）"
            " ⇒ 不猜；账本本身坏了，先修账本",
        )
    if hit:
        return (want, "")

    # ③ `credential.locator` 末段 —— **只认 kind == "dir"**（见模块 docstring 的范畴理由）。
    hit = []
    for row in table:
        cred = row.get("credential")
        if not isinstance(cred, dict):
            continue
        if str(cred.get("kind") or "").strip() != LOCATOR_KIND:
            continue  # none / file / 其它 ⇒ 末段不是号名，跳过
        locator = cred.get("locator")
        if not locator:
            continue
        if _basename(locator) == want:
            hit.append(row)
    if len(hit) > 1:
        raise AccountMapError(
            f"歧义：账本里有 {len(hit)} 条的 credential.locator 末段都等于「{want}」"
            f"（{_ids(hit)}）⇒ 不猜、不取第一条；请人工加 profile 键指明是哪一个",
        )
    if hit:
        locator = str(hit[0]["credential"].get("locator") or "")
        return (
            str(hit[0].get("id") or "").strip(),
            f"credential.locator 末段（kind={LOCATOR_KIND}）：{locator}",
        )

    # 三步都不中 ⇒ 诚实回落（不抛）。
    return (want, NO_STABLE_ID)


def load_account_ids() -> list[dict]:
    """读一次账本，回 `[[account]]` 行；读不到 ⇒ 空列表（**吞掉** `LedgerError`）。

    ★ 这个薄壳**只给 `--account` 之外的只读展示用**（例如「这个号叫什么」的帮助文本）。
      判据（`resolve_account_id()`）**不接受**「读不到账本」这个输入 —— 派活路径上的
      「读不到账本」必须由 `wb_dispatch.resolve_account()` 变成退 2 的拒派，不许降级成空表。
    """
    try:
        path = pool_accounts.find_ledger()
        data = pool_accounts.load_ledger(path)
    except (pool_accounts.LedgerError, OSError):
        return []
    rows = data.get("account")
    return list(rows) if isinstance(rows, list) else []


__all__ = ["NO_STABLE_ID", "AccountMapError", "load_account_ids", "resolve_account_id"]
