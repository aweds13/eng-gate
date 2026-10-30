r"""卡 A342（`T-AG544`）：谁可以用哪些号 —— 移植 magpie F35 的每 caller 账号白名单。

钉子（名字逐字照卡规格的钉子表）：

- `test_empty_patterns_never_narrows` —— `patterns=()` ⇒ 原样返回。
  写成「白名单放行」（空 = 全拒）⇒ 今天的派活全挂。
- `test_named_provider_closes_its_other_accounts` —— 点名一个号 ⇒ 同 provider
  的其它号关掉。写成「只挑不删」⇒ 这条红。
- `test_naming_a_nonexistent_account_closes_the_provider` —— 点一个**不存在**的号
  ⇒ 该 provider 全关。把 `named` 判据写成「号必须真存在」⇒ 这条红。
- `test_unnamed_provider_is_untouched` —— 没点名的 provider 逐字原样保留。
  收窄误伤别的 provider ⇒ 这条红。
- `test_narrow_keeps_candidate_order` —— 顺序 == 入参顺序。
  中途用 `set` 收结果 ⇒ 顺序漂。
- `test_provider_of_is_injected_not_guessed` —— provider 只来自注入。
  拿 `-` 猜 provider（`codearts-doer-1` 会猜错）⇒ 这条红。
- `test_account_guard_prefers_card_over_project` —— 三层都给 ⇒ 只按 card 判。
  判序写成 pool > project > card ⇒ 这条红。
- `test_reverse_narrow_never_adds` —— 名单**只删不加**（判据 8 的现场）。
  出现「保留被点名的、删没点名的」反向语义 ⇒ 这条红。

★ 导入用 `importlib`：`tools/` 不在 `sys.path` 上，且本仓禁 `# noqa`，所以不能像别的
  测试那样在 `sys.path.insert` 之后写 import 语句 —— 那会踩 E402。
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

accounts_scope = importlib.import_module("pool.accounts_scope")
guards = importlib.import_module("pool.guards")

Scope = accounts_scope.Scope
ScopeError = accounts_scope.ScopeError
narrow = accounts_scope.narrow
load_scopes = accounts_scope.load_scopes
account_guard = guards.account_guard

#: 真账本里的四个号（`D:/repo/infra/pool/accounts.toml`）—— 判据不许跟
#: 「减号前面就是 platform」对齐，所以这张表故意写成注入的函数。
PROVIDERS = {
    "codearts-1": "codearts",
    "codebuddy-tongxue3": "codebuddy",
    "codebuddy-tongxue4": "codebuddy",
    "workbuddy-1": "workbuddy",
}


def provider_of(account: str) -> str:
    """测试用的注入实现（真实实现是读账本的 `platform` 字段）。"""
    return PROVIDERS.get(account, "")


CANDIDATES = ("codebuddy-tongxue3", "codebuddy-tongxue4", "codearts-1")


def _scope(patterns: tuple[str, ...], *, kind: str = "card", cid: str = "A1") -> Scope:
    return Scope(caller_kind=kind, caller_id=cid, patterns=patterns)


# ================================================================ 钉子 1


def test_empty_patterns_never_narrows() -> None:
    """`patterns=()` ⇒ 逐字等于 `tuple(candidates)`（**这一支保证今天的派活不会全挂**）。

    ★ 这是本卡最容易被「顺手改对」的一支：magpie 的空名单是「没设防」，
      写成「白名单放行」（空 = 全拒）会让今天**所有**派活立刻停掉。
    """
    assert narrow(CANDIDATES, (), provider_of=provider_of) == CANDIDATES
    assert narrow(CANDIDATES, [], provider_of=provider_of) == CANDIDATES
    assert narrow((), ("codebuddy/*",), provider_of=provider_of) == ()


# ================================================================ 钉子 2


def test_named_provider_closes_its_other_accounts() -> None:
    """点名 `codebuddy/codebuddy-tongxue3` ⇒ 同 provider 的 `tongxue4` 关掉，`codearts` 留。"""
    got = narrow(
        CANDIDATES, ("codebuddy/codebuddy-tongxue3",), provider_of=provider_of
    )
    assert got == ("codebuddy-tongxue3", "codearts-1")
    assert "codebuddy-tongxue4" not in got


# ================================================================ 钉子 3


def test_naming_a_nonexistent_account_closes_the_provider() -> None:
    """★ 最反直觉的一支：`patterns=("codebuddy/不存在的号",)` ⇒ **所有** `codebuddy/*` 被删。

    magpie 的 `named` 判据是 `strings.HasPrefix(a, pid+"/")`（`accounts.go:76`），
    **不看那个号是否真在账本里** —— 所以「点名一个不存在的号」= 把整个 provider 关掉。
    把 `named` 写成「号必须存在才算点名」⇒ 这条红。
    """
    got = narrow(CANDIDATES, ("codebuddy/不存在的号",), provider_of=provider_of)
    assert got == ("codearts-1",)
    assert not any(item.startswith("codebuddy-") for item in got)


# ================================================================ 钉子 4


def test_unnamed_provider_is_untouched() -> None:
    """只提 codebuddy ⇒ codearts 的号**逐字原样**保留（收窄不许误伤别的 provider）。"""
    codes = ("codearts-1", "codearts-doer-1")
    got = narrow(
        ("codebuddy-tongxue3", *codes), ("codebuddy/*",), provider_of=provider_of
    )
    assert tuple(item for item in got if item in codes) == codes


# ================================================================ 钉子 5


def test_narrow_keeps_candidate_order() -> None:
    """结果顺序 == 入参顺序（不重排，便于对账）。"""
    cands = ("codearts-1", "codebuddy-tongxue4", "codebuddy-tongxue3", "workbuddy-1")
    got = narrow(cands, ("codebuddy/codebuddy-tongxue3",), provider_of=provider_of)
    assert got == ("codearts-1", "codebuddy-tongxue3", "workbuddy-1")
    # 顺序必须是入参的子序列，不许被排序
    assert [cands.index(item) for item in got] == sorted(cands.index(item) for item in got)


# ================================================================ 钉子 6


def test_provider_of_is_injected_not_guessed() -> None:
    """provider **只来自注入**：`codearts-doer-1` 的真实 platform 不是 `codearts`。

    「减号前面就是 platform」这条启发式在 `codebuddy-tongxue3` 上看着是对的，
    到 `codearts-doer-1` 就错（设计原件点名的「最容易写错的一处」）。
    """

    def real(account: str) -> str:
        return "doer" if account == "codearts-doer-1" else provider_of(account)

    got = narrow(
        ("codearts-doer-1", "codearts-1"), ("doer/x",), provider_of=real
    )
    # `doer` 被点名 ⇒ `codearts-doer-1` 关掉；`codearts-1` 的 provider 是 codearts，动不到
    assert got == ("codearts-1",)

    # 同一批候选，换「减号前」启发式（= 猜）就会给出不同答案 ⇒ 证明 provider_of 真的被用了
    def guessed(account: str) -> str:
        return account.split("-")[0]

    assert narrow(("codearts-doer-1", "codearts-1"), ("doer/x",),
                  provider_of=guessed) == ("codearts-doer-1", "codearts-1")


# ================================================================ 钉子 7


def test_account_guard_prefers_card_over_project() -> None:
    """三层名单都给了、card 层收窄 ⇒ **只按 card 判**（窄的优先，不落到 project / pool）。"""
    scopes = {
        ("card", "A342"): _scope(("codebuddy/*",), cid="A342"),
        ("project", "OpenMAIC"): _scope(("codearts/*",), kind="project", cid="OpenMAIC"),
        ("pool", "main"): _scope((), kind="pool", cid="main"),
    }
    got = account_guard(
        "codearts-1", scopes, card="A342", project="OpenMAIC", pool="main"
    )
    assert got, "card 层只许 codebuddy，codearts-1 必须被拒"
    assert "A342" in got[0]

    # card 层收窄但放行 ⇒ 不许再拿 project 层（更宽）去二次判
    # ★ 传 `provider/id`（magpie 原形）：裸 id 若名单里没逐字点名，守卫判不动 provider
    #   ⇒ fail-closed（不猜「减号前面就是 provider」，见钉子 6）
    assert account_guard(
        "codebuddy/codebuddy-tongxue3",
        scopes,
        card="A342",
        project="OpenMAIC",
        pool="main",
    ) == []
    # 裸 id + 只有 `provider/*` 的名单 ⇒ 判不动 ⇒ 拒（宁可拒，不许猜）
    blocked = account_guard(
        "codebuddy-tongxue3", scopes, card="A342", project="OpenMAIC", pool="main"
    )
    assert blocked and "判不动" in blocked[0]

    # 三层都不收窄 ⇒ 放行（= 今天的行为）
    only_empty = {("card", "A342"): _scope(())}
    assert account_guard("codearts-1", only_empty, card="A342") == []

    # 没点名账号 / 根本没这张表 ⇒ 放行
    assert account_guard("", scopes, card="A342") == []
    assert account_guard("codearts-1", {}, card="A342") == []


# ================================================================ 钉子 8


def test_reverse_narrow_never_adds() -> None:
    """★ 反向验证（判据 8 的现场）：名单**只删不加**。

    `candidates=("codebuddy/a","codebuddy/b")`、`patterns=("codebuddy/a",)`
    ⇒ 只剩 `("codebuddy/a",)`。把第 3 支从「被点名的 provider ⇒ 删」改成
    「被点名的 provider ⇒ 保留」（整条收窄失效），`b` 就会留下 ⇒ 这条红。
    """
    cands = ("codebuddy/a", "codebuddy/b")
    got = narrow(cands, ("codebuddy/a",), provider_of=lambda _a: "codebuddy")
    assert got == ("codebuddy/a",)
    # 「只删不加」还包含：结果永远是 candidates 的子集，且不会冒出名单里的新号
    assert set(got) <= set(cands)
    assert narrow(cands, ("codebuddy/zzz", "codearts/*"),
                  provider_of=lambda _a: "codebuddy") == ()


# ================================================================ 附：文件面（判据 4/5）

BAD_PATTERNS = ("codebuddy/tongxue*", "codebuddy/*x", "*/a", "codebuddy", "", "a/b/c")


def test_bad_pattern_shapes_raise_scope_error() -> None:
    """只认 `provider/*` 与 `provider/id`；中间/结尾 `*` 与裸串 ⇒ `ScopeError`。

    不许静默跳过：非法形态要么响亮拒绝，要么整条规则悄悄失效。
    """
    for bad in BAD_PATTERNS:
        try:
            narrow(CANDIDATES, (bad,), provider_of=provider_of)
        except ScopeError:
            continue
        raise AssertionError(f"非法 pattern 没抛 ScopeError：{bad!r}")
    # 合法的两种形态一个都不许抛
    assert narrow(CANDIDATES, ("codebuddy/*",), provider_of=provider_of)
    assert narrow(CANDIDATES, ("codebuddy/codebuddy-tongxue3",), provider_of=provider_of)


def test_narrow_does_not_use_fnmatch_or_dash_heuristics() -> None:
    """静态断言：`narrow` 里没有 `fnmatch`，也没有拿减号猜 platform 的写法。"""
    import inspect

    src = inspect.getsource(accounts_scope)
    assert "import fnmatch" not in src and "fnmatch." not in src
    body = inspect.getsource(narrow)
    for bad in ('split("-")', "rpartition(\"-\")", "rsplit(\"-\")", "partition(\"-\")"):
        assert bad not in body, f"narrow() 里出现了按减号拆 id 的写法：{bad}"


def test_load_scopes_reads_toml_and_bounds(tmp_path: Path) -> None:
    """策略文件：正常读 / 不存在回 `{}` / 坏 TOML、越界、超条数、超长都抛 `ScopeError`。"""
    good = tmp_path / "account-scopes.toml"
    good.write_text(
        '[card."A302"]\naccounts = ["codebuddy/codebuddy-tongxue3"]\n'
        '[project."OpenMAIC"]\naccounts = ["codebuddy/*"]\n'
        '[pool."main"]\naccounts = []\n',
        encoding="utf-8",
        newline="\n",
    )
    scopes = load_scopes(good)
    assert scopes[("card", "A302")].patterns == ("codebuddy/codebuddy-tongxue3",)
    assert scopes[("project", "OpenMAIC")].patterns == ("codebuddy/*",)
    # ★ 空数组也是「不收窄」，不是「不许派活」（与 approved_models=[] 是两种意思）
    assert scopes[("pool", "main")].patterns == ()
    assert account_guard("codearts-1", scopes, pool="main") == []

    missing = tmp_path / "nope.toml"
    try:
        load_scopes(missing)
    except ScopeError:
        pass
    else:
        raise AssertionError("显式给的策略文件不存在，必须抛 ScopeError（不许当「不收窄」）")

    bad = tmp_path / "bad.toml"
    bad.write_text("[card.\"A1\"\naccounts = [", encoding="utf-8", newline="\n")
    for path in (bad,):
        try:
            load_scopes(path)
        except ScopeError:
            continue
        raise AssertionError(f"坏 TOML 没抛 ScopeError：{path}")

    cases = {
        "unknown-kind": '[robot."x"]\naccounts = ["codebuddy/*"]\n',
        "not-a-list": '[card."A1"]\naccounts = "codebuddy/*"\n',
        "extra-key": '[card."A1"]\naccounts = ["codebuddy/*"]\nnote = "x"\n',
        "no-accounts": '[card."A1"]\n',
    }
    for label, body in cases.items():
        target = tmp_path / f"{label}.toml"
        target.write_text(body, encoding="utf-8", newline="\n")
        try:
            load_scopes(target)
        except ScopeError:
            continue
        raise AssertionError(f"{label} 没抛 ScopeError")

    too_many = tmp_path / "too-many.toml"
    rows = ", ".join(f'"codebuddy/n{i}"' for i in range(accounts_scope.MAX_SCOPES + 1))
    too_many.write_text(f'[card."A1"]\naccounts = [{rows}]\n',
                        encoding="utf-8", newline="\n")
    too_long = tmp_path / "too-long.toml"
    long_id = "c" * (accounts_scope.MAX_SCOPE_CHARS + 1)
    too_long.write_text(f'[card."A1"]\naccounts = ["codebuddy/{long_id}"]\n',
                        encoding="utf-8", newline="\n")
    for path in (too_many, too_long):
        try:
            load_scopes(path)
        except ScopeError:
            continue
        raise AssertionError(f"越界没抛 ScopeError：{path}")


def test_account_guard_is_pure_and_does_not_read_files() -> None:
    """`guards.py` 里本卡新增的那一段不许出现 `open(` / `Path(` / `print(` / `subprocess`。

    ★ 只断言**本卡新增段**：`guards.py` 既有代码里本来就有 `Path(`（`log_guard`），
      判据 6 那句话对既有代码早已不成立（回执里如实写了）。
    """
    import inspect

    src = inspect.getsource(accounts_scope)
    for bad in ("print(", "subprocess"):
        assert bad not in src, f"accounts_scope.py 里出现了 {bad}"
    segment = inspect.getsource(account_guard) + inspect.getsource(
        guards._scope_provider_of
    )
    for bad in ("open(", "Path(", "print(", "subprocess", "os.environ"):
        assert bad not in segment, f"account_guard 新增段里出现了 {bad}"


# ================================================================ 附加：接线（判据 7）


def test_wiring_calls_the_same_guard_before_reserving() -> None:
    """两处接入都调**同一个** `account_guard`，且都在 `reserve()` **之前**（判据 7）。

    ★ 判据 7 的「同一个函数」不是靠人看代码，是靠这里：两处的调用名逐字出现，
      而且行号顺序钉死「先判账号、后占树」。整段删掉（模拟没接线）⇒ 这条红。
    """
    dispatch = (ROOT / "tools" / "wb_dispatch.py").read_text(encoding="utf-8")
    mcp = (ROOT / "tools" / "pool_mcp.py").read_text(encoding="utf-8")

    call_d = dispatch.index("pool_guards.account_guard(")
    reserve_d = dispatch.index("pool_registry.reserve(")
    assert call_d < reserve_d, "wb_dispatch：账号判据必须在占树之前"
    # ★ 逐字比对整行（子串 `"if args.account:"` 会被 `if False and args.account:` 骗过）
    wired = (
        "    if args.account:\n"
        "        from pool import accounts_scope as pool_accounts_scope\n"
    )
    assert wired in dispatch, "wb_dispatch：接在 --account 分支里（整行逐字）"
    assert "pool_accounts_scope.load_scopes()" in dispatch[:call_d]
    assert "return 2" in dispatch[call_d:reserve_d], "wb_dispatch：非空就必须退 2（零副作用）"

    call_m = mcp.index("guards.account_guard(")
    reserve_m = mcp.index("lease = registry.reserve(")
    assert call_m < reserve_m, "pool_mcp：账号判据必须在 reserve 之前"
    assert "accounts_scope.load_scopes()" in mcp[:call_m], "pool_mcp：白名单要真读"
    assert 'arguments.get("account")' in mcp[:call_m], "pool_mcp：从 arguments 里读 account"
    # ★ 同样逐字比对（子串会被 `if False and account:` 骗过）
    guard_head = '    account = str(arguments.get("account") or "").strip()' + "\n"
    guard_head += "    if account:\n"
    assert guard_head in mcp, "pool_mcp：账号判据要真接上（整行逐字）"
