r"""「判不了就不动手」具名拒绝族（卡 A336 · T-AG538 · 设计原件 F70）的钉子。

## 钉什么（§4 那张表逐条落地，用例名照抄表里那一列）

| 用例 | 类型 | 钉的是 |
|---|---|---|
| `test_refuse_requires_what_and_where` | 正向 | 少给一个 ⇒ `TypeError`；文案含 `what` 与 `where` |
| `test_notlimited_is_a_notserving` | 正向 | 继承链 `NotLimited ⊂ NotServing ⊂ RuntimeError` |
| `test_no_requirement_never_raises` | 边界 | 没声明 + 表不存在 ⇒ **不抛**（`gwbudget.go:102`） |
| `test_declared_but_missing_table_raises` | 正向 | 声明了 + 表读不出 ⇒ `NotLimited`，文案含表路径 |
| `test_default_section_counts_as_requirement` | 边界 | 表里只有 `[default]` 也算「有要求」 |
| `test_refusal_words_never_say_relaxed` | 边界 | 文案里没有「跳过 / 放宽 / 当作没有 / 默认放行」 |
| `test_existing_guard_verdicts_unchanged` | 边界 | 五条既有判据**行为一字不变**（只加 doc） |
| `test_reverse_notlimited_becomes_empty_list` | **反向** | 静默 `return` 那版必须被这条咬红 |

## 两条纪律（写在这里，免得后来人踩）

1. **判据只许一份**：本文件**不重写**任何判据 —— 每条断言都调用被测实现
   （`pool.failclosed.refuse` / `pool.limits.assert_serving` / 既有五条判据本身），
   不在这里另抄一遍 `if`。黄金值（`test_existing_guard_verdicts_unchanged` 里的那几条
   字符串）是**改 docstring 之前实测录下来的读数**，不是判据的第二份实现。
2. **每条断言先断言前提成立**：反向钉子先证明「同一输入今天抛」，
   再谈「改成静默 return 就不抛」—— 前提不成立时用例要给的是「前提坏了」，不是「反向没咬住」。

★ 导入口径照既有测试（`tests/test_pool_registry.py:26-30`）：把 `tools/` 挂上 `sys.path` 再 import。
★ 一律 `tmp_path`，**不碰**仓外那份 `infra/pool/limits.toml`（它今天本来也不存在）。
"""

from __future__ import annotations

import ast
import copy
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import pool_accounts  # noqa: E402 —— tools/ 已在 sys.path 上
import pytest  # noqa: E402
from pool import failclosed, guards, model_registry, registry  # noqa: E402
from pool import limits as pool_limits  # noqa: E402
from pool.failclosed import NotLimited, NotServing, refuse  # noqa: E402

#: 禁词（§3 边界条件；出现任一个就说明这条「拒绝」被写成了「放行」）。
BANNED = ("跳过", "放宽", "当作没有", "默认放行")

#: 改 docstring **之前**实测录下来的守卫读数（黄金值，不是判据的第二份实现）。
GOLDEN_TREE_HIT = "树被占：.wt/a 上已有活租约（卡 108，owner=w1）—— 一棵树同时只能一个写者"
GOLDEN_DOMAIN_HIT = ("冲突域相交：与活租约卡 108（树 .wt/a）相交文件 ['a.py']"
                     " —— 同一文件不许两个写者")
GOLDEN_TREE_DOC = "一棵树同时只能有一个活租约（主树尤其）—— 空列表 = 没被咬。"

#: 卡 A336 落地的那一笔（`git log --grep T-AG538`）。「只加 docstring」的比对锚在这笔身上，
#: **不是** `HEAD` —— 拿 `HEAD` 比会把后来每一张正常改这四个文件的卡都判红。
CARD_COMMIT = os.environ.get("TF_CARD_A336_COMMIT", "e3641bb9aa150e660b3b771a34b0116fd3736250")
#: 卡 A336 只加 docstring 的四个文件。
CARD_FILES = ("tools/pool/guards.py", "tools/pool/registry.py",
              "tools/pool/model_registry.py", "tools/pool_accounts.py")
NOW = 1_700_000_000.0


def _iso(ts: float) -> str:
    import datetime

    return datetime.datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def _res(card: str = "108", tree: str = ".wt/a", files: tuple[str, ...] = ("a.py",), *,
         at: float = NOW, ttl: float = 21600.0, owner: str = "w1") -> dict:
    """造一条像 `registry` 落盘那样的租约（字段与它逐个对齐）。"""
    return {"card": card, "task": "", "tree": tree, "files": list(files), "pool": "",
            "model": "", "log": "", "owner": owner, "at": _iso(at),
            "ttl_seconds": ttl, "note": ""}


# ================================================================ ① 正向：refuse 的三个参数
def test_refuse_requires_what_and_where() -> None:
    """少给 `what` 或 `where` ⇒ `TypeError`；三个都给时文案**同时**含两者（正向）。"""
    # ① 先断言前提：三个都给是能造的，且类型对
    exc = refuse("卡 A1 要求按限额派活", what="这张卡声明的限额", where="infra/pool/limits.toml")
    assert isinstance(exc, NotServing), f"refuse 要回 NotServing；实际 {type(exc)!r}"
    assert isinstance(exc, RuntimeError), "NotServing 必须是 RuntimeError 的子类"
    text = str(exc)
    assert "这张卡声明的限额" in text, f"文案缺 what；实际 {text!r}"
    assert "infra/pool/limits.toml" in text, f"文案缺 where；实际 {text!r}"

    # ② 少给任何一个 ⇒ TypeError（不许有默认值兜着）
    with pytest.raises(TypeError):
        refuse("卡 A1 要求按限额派活", where="infra/pool/limits.toml")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        refuse("卡 A1 要求按限额派活", what="这张卡声明的限额")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        refuse("卡 A1 要求按限额派活")  # type: ignore[call-arg]


def test_signature_has_no_defaults() -> None:
    """`what` / `where` 在**签名**上就没有默认值（TypeError 的静态口径，不只靠调用一次）。"""
    import inspect

    params = inspect.signature(refuse).parameters
    for name in ("what", "where"):
        assert name in params, f"refuse 缺参数 {name}"
        assert params[name].default is inspect.Parameter.empty, (
            f"refuse 的 {name} 不许有默认值（§3：三个参数强制都要给）")
        assert params[name].kind is inspect.Parameter.KEYWORD_ONLY, (
            f"refuse 的 {name} 必须是 keyword-only")


# ================================================================ ② 正向：继承链
def test_notlimited_is_a_notserving() -> None:
    """`NotLimited ⊂ NotServing ⊂ RuntimeError`（正向）—— `except NotServing` 要能一网打尽。"""
    assert issubclass(NotLimited, NotServing), "NotLimited 必须是 NotServing 的子类"
    assert issubclass(NotServing, RuntimeError), "NotServing 必须是 RuntimeError 的子类"
    # ★ 反方向：**不许**继承 ValueError（那是「你给的配置坏了」，与「服务不在」是两件事）
    assert not issubclass(NotServing, ValueError), (
        "NotServing 不许继承 ValueError（§3 边界条件：参数坏 ≠ 服务不在）")
    # 两个名字都真的能抛出并被 except NotServing 抓住
    with pytest.raises(NotServing):
        raise NotLimited("有要求、没服务")


# ================================================================ ③ 边界：没要求 ⇒ 不抛
def test_no_requirement_never_raises(tmp_path: Path) -> None:
    """卡没声明限额 + 表不存在 ⇒ `assert_serving` **不抛**（边界；magpie `gwbudget.go:102`）。"""
    missing = tmp_path / "limits.toml"
    assert not missing.exists(), "前提：这份表必须不存在"

    # ① 空表
    pool_limits.assert_serving("A1", {}, path=missing)          # 不抛 = 过
    # ② 表里有别人的段，但这张卡不受管（「有要求」必须是显式声明，不许从「表非空」推）
    pool_limits.assert_serving("A1", {"B2": {"tokens": 10}}, path=missing)
    # ③ 表里真有一份、文件路径也确实存在 ⇒ 服务在，不抛
    present = tmp_path / "present.toml"
    present.write_bytes(b'[A1]\r\ntokens = 10\r\n')
    pool_limits.assert_serving("A1", {"A1": {"tokens": 10}}, path=present)


# ================================================================ ④ 正向：声明了但表读不出
def test_declared_but_missing_table_raises(tmp_path: Path) -> None:
    """卡声明了限额 + 表读不出 ⇒ `NotLimited`，文案含表路径（正向）。"""
    missing = tmp_path / "limits.toml"
    assert not missing.exists(), "前提：这份表必须不存在"

    with pytest.raises(NotLimited) as excinfo:
        pool_limits.assert_serving("A1", {"A1": {"tokens": 10}}, path=missing)
    assert isinstance(excinfo.value, NotServing), "NotLimited 也要能被 except NotServing 抓住"
    text = str(excinfo.value)
    assert str(missing) in text, f"文案要含表路径（人得知道去看哪）；实际 {text!r}"
    assert "A1" in text, f"文案要点名是哪张卡；实际 {text!r}"

    # 表在、但内容读不出（坏 TOML）同样算「不在服务」
    broken = tmp_path / "broken.toml"
    broken.write_bytes(b"[A1\r\ntokens = = 10\r\n")
    assert pool_limits.load_limits(broken) == {}, "前提：坏表在 load_limits 那边读成 {}"
    with pytest.raises(NotLimited):
        pool_limits.assert_serving("A1", {"A1": {"tokens": 10}}, path=broken)

    # 表在、但**是目录**（路径存在却读不出一份表）同样算「不在服务」
    with pytest.raises(NotLimited):
        pool_limits.assert_serving("A1", {"A1": {"tokens": 10}}, path=tmp_path)


# ================================================================ ⑤ 边界：default 也算有要求
def test_default_section_counts_as_requirement(tmp_path: Path) -> None:
    """表里只有 `[default]` ⇒ 也算「有要求」⇒ 读不出就抛（边界）。"""
    missing = tmp_path / "limits.toml"
    assert not missing.exists(), "前提：这份表必须不存在"

    table = {"default": {"tokens": 10}}
    with pytest.raises(NotLimited):
        pool_limits.assert_serving("A1", table, path=missing)

    # ★ 对照：同样一张表、同样不存在的路径，但如果卡被显式声明了 ⇒ 也必须抛——
    #   这条不是重复，是把「default 兜底」与「显式声明」两条判据分开钉住。
    with pytest.raises(NotLimited):
        pool_limits.assert_serving("A1", {"A1": {"tokens": 1}}, path=missing)

    # 反过来：`default` 段在、表也在 ⇒ 不抛（服务在）
    present = tmp_path / "present.toml"
    present.write_bytes(b'[default]\r\ntokens = 10\r\n')
    assert pool_limits.load_limits(present) == {"default": {"tokens": 10}}, "前提：表读得出来"
    pool_limits.assert_serving("A1", table, path=present)


# ================================================================ ⑥ 边界：禁词静态检查
def _refusal_texts() -> list[tuple[str, str]]:
    """所有**造 `NotServing` 的地方**的文案：真跑一遍，把异常文案收下来。

    ★ 不扫源码找字符串（那会漏掉 f-string 拼出来的），而是**真造**：这才是
      「现场那句文案」的样子。另外把 `failclosed.py` 的 docstring 也扫一遍（它是模板的说明书）。
    """
    out: list[tuple[str, str]] = []
    out.append(("refuse()", str(refuse("卡 A1 要求按限额派活", what="这张卡声明的限额",
                                       where="infra/pool/limits.toml"))))
    try:
        pool_limits.assert_serving("A1", {"A1": {"tokens": 1}},
                                   path=Path("D:/definitely/not/here/limits.toml"))
    except NotServing as exc:
        out.append(("assert_serving()", str(exc)))
    out.append(("NotServing.__doc__", failclosed.NotServing.__doc__ or ""))
    out.append(("NotLimited.__doc__", failclosed.NotLimited.__doc__ or ""))
    return out


def test_refusal_words_never_say_relaxed() -> None:
    """静态断言：拒绝文案里**没有**「跳过 / 放宽 / 当作没有 / 默认放行」（边界）。"""
    texts = _refusal_texts()
    assert len(texts) >= 4, f"前提：要收到至少 4 段文案；实际 {len(texts)}"
    assert any(n == "assert_serving()" for n, _ in texts), "前提：真跑出了 assert_serving 的拒绝"
    for name, text in texts:
        for word in BANNED:
            assert word not in text, f"{name} 的文案含禁词 {word!r} —— 这是拒绝，不是放行：{text!r}"


def _without_docstrings(tree: ast.AST) -> str:
    """把 AST 里所有 docstring 抹掉再 dump —— 「只加 docstring」的机器口径（只此一份）。"""
    clone = copy.deepcopy(tree)
    for node in ast.walk(clone):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = node.body
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            node.body = body[1:] or [ast.Pass()]
    return ast.dump(clone, include_attributes=False)


# ================================================================ ⑦ 边界：五条既有判据行为不变
def test_existing_guard_verdicts_unchanged(tmp_path: Path) -> None:
    """五条既有判据**行为一字不变**（本卡只加 docstring）—— 边界。

    黄金值来自本卡**改 docstring 之前**实测录下的读数
    （`gates/diag/_gold_A336.py` 的输出）。
    """
    # ① guards.tree_guard —— 占着的树 / 空着的树
    assert guards.tree_guard(".wt/a", [_res()], NOW) == [GOLDEN_TREE_HIT], (
        "tree_guard 判据变了")
    assert guards.tree_guard(".wt/b", [_res()], NOW) == [], "tree_guard 误伤空树"
    assert guards.tree_guard(".wt/a", [_res(at=NOW - 99999.0)], NOW) == [], "死租约不该拦"

    # ② guards.domain_guard —— 相交 / 不相交 / **空域**
    assert guards.domain_guard(["a.py"], [_res()], NOW) == [GOLDEN_DOMAIN_HIT], (
        "domain_guard 判据变了")
    assert guards.domain_guard(["b.py"], [_res()], NOW) == [], "domain_guard 误伤不相交"
    assert guards.domain_guard([], [_res()], NOW) == [], (
        "domain_guard 对空域今天回 []（零值双关 —— F70 记的就是这个坑，本卡不改行为）")

    # ③ pool.registry.load —— 文件不存在回 []，坏文件抛且不清空
    missing = tmp_path / "reg.json"
    assert registry.load(missing) == [], "registry.load 对缺失文件必须回 []"
    broken = tmp_path / "broken.json"
    broken.write_bytes(b"{ not json")
    with pytest.raises(registry.RegistryError):
        registry.load(broken)
    assert broken.read_bytes() == b"{ not json", "坏文件**不许**被清空/改写"

    # ④ model_registry.PoolNotWiredError —— codearts 未接 ⇒ 响亮拒
    adapter = model_registry.get_adapter("codearts")
    assert not adapter.wired, "前提：codearts 池今天还是没接"
    with pytest.raises(model_registry.PoolNotWiredError) as excinfo:
        adapter.assert_wired()
    assert "还没接" in str(excinfo.value), "PoolNotWiredError 的文案变了"

    # ⑤ pool_accounts._check_account —— 「没探测过就不许填数」照旧抛
    acc = {"id": "a1", "label": "L", "platform": "codebuddy", "state": "active",
           "added_at": "2026-01-01", "approved_models": [],
           "credential": {"kind": "none"}, "quota": {"source": "unknown", "amount": 5}}
    with pytest.raises(pool_accounts.LedgerError) as excinfo:
        pool_accounts._check_account(0, acc, {"codebuddy": {}})
    assert "没探测过就不许填数" in str(excinfo.value), "_check_account 的文案变了"

    # ⑥ 「只加 docstring」的**机器口径**：把那一笔的父子两端各解一遍 AST，
    #    **去掉 docstring 之后逐节点比对**。判的是「那一笔改了什么」，所以
    #    后续任何卡怎么改这些文件都与它无关（改坏了有各自的钉子）。
    # ★ 这条判的是**卡 A336 那一笔自己的形状**（那笔 vs 它的父提交），不是「工作区 vs 那笔」。
    #   写成后者等于断言「此后再没有任何卡碰过这四个文件」—— 后来每张正常改动它们
    #   （比如加一个函数）的卡都会被判红，那是过期前提，不是判据。
    #   一笔的判据要锚在那一笔的两个端点之间（同 `audit_progress` 用父提交判门禁产物的口径）。
    for rel in CARD_FILES:
        before = subprocess.run(["git", "show", f"{CARD_COMMIT}^:{rel}"], cwd=ROOT,
                                capture_output=True, check=False)
        after = subprocess.run(["git", "show", f"{CARD_COMMIT}:{rel}"], cwd=ROOT,
                               capture_output=True, check=False)
        assert before.returncode == 0, (
            f"前提：取不到 {rel} 的 {CARD_COMMIT[:8]}^ 版本："
            f"{before.stderr.decode('utf-8', 'replace')}")
        assert after.returncode == 0, (
            f"前提：取不到 {rel} 的 {CARD_COMMIT[:8]} 版本："
            f"{after.stderr.decode('utf-8', 'replace')}")
        if before.stdout == after.stdout:  # 那笔根本没动这个文件 ⇒ 无可判，如实跳过
            continue
        before_tree = ast.parse(before.stdout.decode("utf-8"))
        after_tree = ast.parse(after.stdout.decode("utf-8"))
        assert _without_docstrings(before_tree) == _without_docstrings(after_tree), (
            f"{rel} 在 {CARD_COMMIT[:8]} 那笔里除 docstring 之外还有别的改动 —— "
            "卡 A336 只许加 docstring")
    assert guards.tree_guard.__doc__.startswith(GOLDEN_TREE_DOC), (
        "tree_guard 的原 docstring 首句必须原样保留（本卡只往后追加）")


# ================================================================ ⑧ 反向钉子
def _needs_notlimited(fn, card: str, limits: dict, *, path: Path) -> None:
    """「有要求、表读不出 ⇒ 必须抛 `NotLimited`」这条断言本身（**只写一次**）。

    ★ 它既是正向钉子（真实现必须过），也是反向钉子的**探针**：
      拿一个坏掉的实现来跑它，它必须抛 `Failed` —— 那才叫「钉子咬得住」。
    """
    with pytest.raises(NotLimited):
        fn(card, limits, path=path)


def test_reverse_notlimited_becomes_empty_list() -> None:
    """**反向验证**：`assert_serving` 从「抛 `NotLimited`」改成「静默 `return`」⇒ 探针必须变红。

    §4 那条反向钉子逐字：「卡声明限额 + 表不存在，断言 `pytest.raises(NotServing)`；
    改坏后不抛 ⇒ 红」。**理由**：magpie 的 `ErrUnlimited` 之所以存在（`gwbudget.go:97-99`
    一整条具名错误），就是因为「读不到就放行」这个默认行为**看起来完全正常** ——
    只有钉子能发现它悄悄把限额关掉了。

    ★ 三步，每步先断言前提：
      ① **前提**：真实现对「声明了 + 表不存在」是抛的（不然下面全都在钉空气）；
      ② **坏版本**：「读不出就静默 `return`」对同一输入**不抛** —— 这就是坏掉的样子；
      ③ **探针**：拿坏版本跑第 ① 步那条断言，必须抛 `Failed` ⇒ 钉子咬得住。
    `gates/diag/_rev_A336.py` 的变异 ① 就是把这 ③ 步换成**真的改源码**再跑本文件。
    """
    missing = Path("D:/definitely/not/here/limits.toml")
    table = {"A1": {"tokens": 10}}
    assert not missing.exists(), "前提：这份表必须不存在（否则哪一版都不会抛）"

    # ① 前提：真实现是抛的
    _needs_notlimited(pool_limits.assert_serving, "A1", table, path=missing)

    # ② 坏掉的版本：读不出就静默 return（= 被 ErrUnlimited 拦下的那个「看起来正常」的默认行为）
    def broken_assert_serving(card: str, limits: object, *, path: object) -> None:
        if card not in (limits or {}):
            return
        return  # ★ 静默当「没要求」—— 正是被反向针对的方向

    broken_assert_serving("A1", table, path=missing)  # 不抛（坏的样子，先证明它确实是坏的）

    # ③ 探针：同一条断言套到坏版本上 ⇒ 必须失败（钉子咬住了）
    with pytest.raises(pytest.fail.Exception) as excinfo:
        _needs_notlimited(broken_assert_serving, "A1", table, path=missing)
    assert "NotLimited" in str(excinfo.value), (
        f"探针变红的理由要对（应是「没抛 NotLimited」）；实际 {str(excinfo.value)!r}")
