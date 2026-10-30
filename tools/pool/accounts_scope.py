r"""谁可以用哪些号（卡 A342 · `T-AG544`；移植 magpie F35）。

★ 语义逐字抄 magpie `internal/access/accounts.go:63-83` 的 `AllowsAccount`：
  · 名单为空 ⇒ **不收窄**（`return True`，逐字对应第 1 支）；
  · 名单里点名了 provider A 的**任何一个**号 ⇒ **A 的其它号全部关掉**
    （逐字对应 `named` / `return !named`）；
  · 名单里**没点名**的 provider ⇒ 一切照旧。
  ★ 「closer, never wider」的落地就是：本模块只**删**候选，**从不加**。
★ 存的是 `accounts.toml` 的**稳定 id**（不是 email、不是 label）
  —— 逐字对应 magpie 存 `p.ID + "/" + id`。

## 两条落地口径（逐字，别改）

「**没设 = 不收窄**」（否则今天所有派活全挂）
+「**设了 = 只能收窄**」（否则就是放松判据）。

## 两个「空」是两种意思，**不许统一**

- 本模块的 `patterns = ()` ⇒ **不收窄**（这个 caller 没人给他设防）。
- `tools/pool_accounts.py:164-172` 的 `approved_models = []` ⇒ **这个号不许派活**
  （账号自己没被授权；那边逐字写着「空数组的含义是「这个号不许派活」，
  不是「随便用」」）。
  两处各写一份、互相引用，**不许合并成一个函数**。

## 通配只在账号维的前缀上

只认两种形态：`"provider/*"` 与 `"provider/exact-id"`。magpie 的 `AllowsAccount`
只有 `strings.HasPrefix`，**没有** glob —— 所以 `"codebuddy/tongxue*"` 这类
中间/结尾的 `*` 本模块**不认**（`ScopeError`），也**不许**改用 `fnmatch`
（那是 `pool.review.outside_allow` 的语义，`*` 跨 `/`，会让 `codebuddy/*dh*`
意外生效）。

## 策略文件（仓外，与 `accounts.toml` 同目录）

    # ★ 没写 = 不收窄。不许为了「占位」写空数组 —— 空数组在本设计里也是「不收窄」
    #   （与 accounts.toml 的 approved_models=[] 语义不同，那里的空是「不许派活」）。
    [card."A302"]
    accounts = ["codebuddy/codebuddy-tongxue3"]
    [project."OpenMAIC"]
    accounts = ["codebuddy/*"]

★ 文件里一个 caller 都没写 ⇒ `{}` ⇒ 一条都不收窄（今天的行为）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import tomllib

if TYPE_CHECKING:  # 只在注解里用（本文件已开 `from __future__ import annotations`）
    from collections.abc import Callable, Sequence

#: ★ magpie `access/accounts.go:58` —— "A key can list at most 500 accounts"
MAX_SCOPES = 500
#: ★ magpie `access/accounts.go:21` 的长度上限
MAX_SCOPE_CHARS = 300
#: 策略文件名（与账本同目录，仓外）
SCOPE_NAME = "account-scopes.toml"
#: 根推导的锚点 —— 与 `tools/pool_accounts.py:60 ANCHOR` 逐字同口径
LEDGER_ANCHOR = ("infra", "pool", "accounts.toml")
#: 三种 caller 由窄到宽（`guards.account_guard` 的判序）
CALLER_KINDS = ("card", "project", "pool")
#: 本树根（`tools/pool/accounts_scope.py` 往上三层）
TOOL_ROOT = Path(__file__).resolve().parent.parent.parent


class ScopeError(ValueError):
    """scopes 损坏 / 越界 —— 响亮拒绝，**绝不回落到「不收窄」**（回落 = 悄悄放宽）。"""


@dataclass(frozen=True, slots=True)
class Scope:
    """一条「谁」的账号白名单：`(caller_kind, caller_id, patterns)`。

    ★ `patterns` 是**已校验、已归一为小写**的元组；空元组 = 不收窄。
    """

    caller_kind: str  # "card" / "project" / "pool"
    caller_id: str
    patterns: tuple[str, ...]  # 形如 ("codebuddy/codebuddy-tongxue3", "codearts/*")


def ledger_path() -> Path:
    """按 `pool_accounts.find_ledger` 的锚点逐级向上找账本（**不跟 cwd 走**）。"""
    start = TOOL_ROOT.resolve()
    for base in (start, *start.parents):
        cand = base.joinpath(*LEDGER_ANCHOR)
        if cand.is_file():
            return cand
    raise ScopeError(
        "找不到账号账本（账号白名单判不了）：从 "
        f"{start} 起逐级向上都没有 {'/'.join(LEDGER_ANCHOR)}；"
        "账本本体在仓外 D:/repo/infra/pool/accounts.toml"
    )


def default_path() -> Path:
    """默认策略文件：与账本**同目录**的 `account-scopes.toml`（仓外，人改）。"""
    return ledger_path().with_name(SCOPE_NAME)


def _check_pattern(raw: object) -> str:
    """校验一条 pattern，回归一后的小写串（**不猜 provider**，只认两种形态）。"""
    text = str(raw or "").strip()
    if not text:
        raise ScopeError("账号白名单里有空条目（空串不是「不收窄」，是写坏了）")
    if len(text) > MAX_SCOPE_CHARS:
        raise ScopeError(
            f"账号白名单单条超过 {MAX_SCOPE_CHARS} 字符：{text[:40]}…（长 {len(text)}）"
        )
    provider, sep, rest = text.partition("/")
    if not sep or not provider or not rest:
        raise ScopeError(
            f"账号白名单条目必须是「provider/…」形态：{text!r}"
            "（合法只有 provider/* 与 provider/id）"
        )
    if "*" in provider or "/" in rest:
        raise ScopeError(
            f"账号白名单条目形状不对：{text!r}（provider 里不许有 *，id 里不许再有 /）"
        )
    if "*" in rest and rest != "*":
        raise ScopeError(
            f"账号维只许前缀通配（provider/*），不许中间/结尾的 *：{text!r}"
            "（magpie 的 AllowsAccount 只有 HasPrefix，没有 glob）"
        )
    return text.lower()


def narrow(
    candidates: Sequence[str],
    patterns: Sequence[str],
    *,
    provider_of: Callable[[str], str],
) -> tuple[str, ...]:
    """按 patterns 收窄候选号列表。**纯函数**（`provider_of` 是注入的，本函数不读文件）。

    三支逐字照抄 magpie `AllowsAccount`：
      1. `not patterns` ⇒ `tuple(candidates)`；
      2. 逐字命中（大小写不敏感）⇒ 保留；
      3. 该候选的 provider 被 patterns **点名过**（有任意一条同前缀）⇒ **删掉**；
         没被点名过 ⇒ 保留。
    ★ 结果 ⊆ candidates，且顺序保持 candidates 原序（便于对账）。
    ★ `provider_of` **必须注入**：号 id 的形状是 `<platform>-<n>`（`codearts-1`、
      `codebuddy-tongxue3`），**不是** `platform/id` —— 本函数里**不许**猜「减号
      前面就是 platform」（`codearts-doer-1` 会猜错）。实现侧读 `accounts.toml` 的
      `platform` 字段（见 `load_providers`）。
    ★ 候选的 provider 这么定（**不猜**）：
      · 候选本身已经是 `provider/id` 形态（含 `/`）⇒ 取 `/` 前面那段
        —— 这是 magpie `pid + "/" + ref` 的**原形**，不是启发式；
      · 否则（裸 id，如 `codearts-1`）⇒ 一律问注入的 `provider_of`
        ——**不许**看减号前面。
    ★ `provider_of` 说不出来（返回空）的候选：**保留**（判不动 ≠ 有罪；真实调用里
      候选全部取自 `accounts.toml`，`load_providers()` 一定答得上来）。
    """
    if not patterns:
        return tuple(candidates)
    exact: set[str] = set()
    wildcard: set[str] = set()
    named: set[str] = set()
    for raw in patterns:
        text = _check_pattern(raw)
        provider, _, rest = text.partition("/")
        named.add(provider)
        if rest == "*":
            wildcard.add(provider)
        else:
            exact.add(text)
    kept: list[str] = []
    for cand in candidates:
        item = str(cand).strip()
        if "/" in item:
            provider, _, name = item.partition("/")
            provider = provider.strip().lower()
            name = name.strip().lower()
        else:
            provider = str(provider_of(item) or "").strip().lower()
            name = item.lower()
        key = f"{provider}/{name}" if provider else name
        # 第 2 支：整串逐字命中（大小写不敏感）⇒ 留
        keep_it = item.lower() in exact or key in exact
        # `provider/*` 是「这个 provider 整个被点名」，也走第 2 支
        keep_it = keep_it or bool(provider) and provider in wildcard
        # 第 3 支：provider 被点名过、又不是上面两支 ⇒ 删；没点名过 ⇒ 留
        if keep_it or provider not in named:
            kept.append(cand)
    return tuple(kept)


def load_scopes(path: Path | str | None = None) -> dict[tuple[str, str], Scope]:
    """读 `infra/pool/account-scopes.toml`（仓外，与 `accounts.toml` 同目录）。

    ★ 默认路径下的文件**不存在** ⇒ `{}`（= 一条都不收窄 = 今天的行为）。
    ★ 显式给了 `path` 却不存在 ⇒ `ScopeError`：那是笔误，静默当「不收窄」就是
      悄悄放宽（与「响亮拒绝」相反）。
    ★ 坏 TOML / 越界（顶层不认识 caller 种类、条目不是 `accounts = [...]`）/
      单个 caller 超过 `MAX_SCOPES` 条 / 单条超过 `MAX_SCOPE_CHARS` ⇒ `ScopeError`。
    ★ `accounts.toml` 读不到也 `ScopeError`（**不许**当成「空名单」= 不收窄）——
      靠 `default_path()` 里那次锚点查找把它判出来。
    """
    explicit = path is not None
    target = Path(str(path)).expanduser() if explicit else default_path()
    if not target.is_file():
        if explicit:
            raise ScopeError(f"给的账号白名单文件不存在：{target}")
        return {}
    try:
        with open(target, "rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ScopeError(f"账号白名单读不了 / 不是合法 TOML：{target}（{exc}）") from exc
    out: dict[tuple[str, str], Scope] = {}
    for kind, table in data.items():
        if kind not in CALLER_KINDS:
            raise ScopeError(
                f"账号白名单里有不认识的 caller 种类：{kind!r}"
                f"（只认：{'、'.join(CALLER_KINDS)}）"
            )
        if not isinstance(table, dict):
            raise ScopeError(f"[{kind}] 必须是一张表（形状：`[{kind}.\"<id>\"]`）")
        for caller_id, body in table.items():
            cid = str(caller_id).strip()
            if not cid:
                raise ScopeError(f"[{kind}] 里有空的 caller id")
            if not isinstance(body, dict):
                raise ScopeError(f"[{kind}.{cid}] 必须是一张表")
            extra = sorted(set(body) - {"accounts"})
            if extra:
                raise ScopeError(
                    f"[{kind}.{cid}] 有不认识的键：{'、'.join(extra)}（只认 accounts）"
                )
            raw = body.get("accounts")
            if not isinstance(raw, list):
                raise ScopeError(f"[{kind}.{cid}] 缺 `accounts = [...]`（形状照设计原件）")
            if len(raw) > MAX_SCOPES:
                raise ScopeError(
                    f"[{kind}.{cid}] 列了 {len(raw)} 个号，超过上限 {MAX_SCOPES}"
                    "（magpie accounts.go:58）"
                )
            patterns = tuple(_check_pattern(item) for item in raw)
            out[(kind, cid)] = Scope(caller_kind=kind, caller_id=cid, patterns=patterns)
    return out


def load_providers(path: Path | str | None = None) -> dict[str, str]:
    """号 id → provider（读 `accounts.toml` 的 `platform` 字段，**不许猜「减号前」**）。

    这就是 `narrow(..., provider_of=...)` 的实现侧注入：

        providers = load_providers()
        keep = narrow(cands, patterns, provider_of=lambda cid: providers.get(cid, ""))

    ★ 账本读不到 ⇒ `ScopeError`（与 `load_scopes` 同一口径，不许当成「空名单」）。
    ★ 校验一律走 `tools/pool_accounts.load_ledger`（**不另写一份账本校验**）。
    """
    try:
        import pool_accounts
    except ImportError as exc:  # pragma: no cover —— tools/ 不在 sys.path 上
        raise ScopeError(f"读不到 tools/pool_accounts.py，账号白名单判不了：{exc}") from exc
    try:
        ledger = pool_accounts.find_ledger(str(path) if path is not None else None)
        data = pool_accounts.load_ledger(ledger)
    except pool_accounts.LedgerError as exc:
        raise ScopeError(f"账号账本读不了（账号白名单判不了）：{exc}") from exc
    return {str(acc["id"]): str(acc["platform"]) for acc in data["account"]}


__all__ = [
    "MAX_SCOPE_CHARS",
    "MAX_SCOPES",
    "Scope",
    "ScopeError",
    "default_path",
    "ledger_path",
    "load_providers",
    "load_scopes",
    "narrow",
]
