r"""F17 七种路由策略的**接线现状**钉子（卡 A390 · T-AG678）—— 只钉现状，产品码一个字节不改。

## 病

七个策略（In order / In turn / Least used / Weekly pace / Weighted / Free first / Speed first）
的实现与判据在卡 A352 就落完了：`tools/pool/route.py` 里七条路径都在，
`tests/test_pool_route_strategies.py` 63 条钉着它们。真正的问题是**喂料** ——
生产侧（`tools/pool/gateway.py` 的 `_seat()`）只往座位上放 `key` / `account` / `known` / `used`
四项，而 `free` / `credits` / `ttft` / `tps` / `pace` / `weight` 这六个喂料字段**一个都没构造**。
于是「给 `--routing weight` 跑起来会怎样」这件事今天没有任何断言拦着：
谁顺手在 `Seat(...)` 里补一个 `pace=`，排位就会静默变化，
而既有 171 条判据（网关 108 + 策略 63）**一条都不会红**。

## 判据（七条钉子，对应卡规格的六条）

| 判据 | 钉子 | 钉哪一位 |
|---|---|---|
| 1a | `test_without_turns_only_usage_reorders` | 不传 turns：只有 `usage` 动 |
| 1b | `test_same_turns_rotates_the_starting_seat` | 同一份 turns 连传 ⇒ 轮换 |
| 2 | `test_dispatch_sink_never_names_a_speed_strategy` | speed 红线 |
| 3 | `test_gateway_recognises_seven_names_and_speed_alias` | 七名齐全 + `speed` 别名 |
| 4 | `test_apply_strategy_has_one_call_site_and_caller_holds_turns` | 调用点一处 + state 形状 |
| 5 | `test_seat_feed_fields_are_never_constructed` | 六个喂料字段零构造 |
| 6 | `test_route_module_never_writes_anything` | `route.py` 零写盘 |

## 为什么走 AST（不走正则）

「谁在构造座位」问的是**调用节点的关键字**，「谁在写盘」问的是**名字节点**，
「派活器有没有认得 speed」问的是**字符串常量**。正则分不清这三件事：

- `tools/pool/route.py` 的文档字符串里就写着 `free=` / `ttft=`（讲字段含义），
  grep 一定命中 —— 但它们**不是构造**，是散文。
- `tools/dsh_panel.py` 也有三处 `Seat(`，那是**面板条目**（裸 `Name` 形态，关键字是
  `icon` / `label_zh` / `route` / `render` 那一堆），跟号池座位不是同一个东西；
  反之 `tools/pool/search.py` 的 `pool_route.Seat(...)` 是**真的**号池座位。
- 扫描走 **AST**（不是正则）：文档字符串里提一句 `Seat(...pace=...)` 不会被误判。
  体例照 `tests/test_no_window.py` 的那句「扫描走 **AST**（不是正则）」。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import wb_dispatch  # noqa: E402 —— 判据 2 读它唯一的那个常量，不复制字面量
from pool import gateway  # noqa: E402
from pool import route as pool_route  # noqa: E402

IDENTITY = [0, 1, 2]
"""不传 turns 时九个名字的期望排位：按列出顺序。"""

UNROTATED = ["order", "rotate", "pace", "weight", "free", "fast", "smart", "manual", "speed"]
"""判据 1 前半的九个名字（七个内置 + `smart` / `manual` + 别名 `speed`）。"""

FEED_FIELDS = {"free", "credits", "ttft", "tps", "pace", "weight"}
"""判据 5：生产侧**零构造**的六个喂料字段。"""

BANNED_IN_DISPATCH = {
    "fast", "fastest", "speed", "speed-first", "rotate", "weighted", "in-turn", "round-robin",
}
"""判据 2：派活器的字符串常量里一个都不许出现的路由名（speed 红线的可执行面）。"""

FORBIDDEN_WRITES = {"open", "write_text", "write_bytes", "dump", "Popen", "run", "system"}
"""判据 6：`tools/pool/route.py` 里不许出现的名字 —— 状态只能在调用方手里。"""


def _rows() -> list[dict[str, Any]]:
    """三行账本夹具 —— ★ **必须带 `quota` 段**。

    不带 `quota` 时 `_seat()` 给 `known=False, used=None`，`usage` 也会恒等 —— 那是本卡踩过的假绿。
    `used_percent` = 30 / 10 / 20 让 `usage` 排出 `[1, 2, 0]`。行形状照 `tests/test_pool_gateway.py`
    的 `_row` 夹具（id / label / platform / state / approved_models 五键），只补一个 `quota` 段。
    """

    def row(seat: str, used: float) -> dict[str, Any]:
        return {
            "id": seat,
            "label": seat,
            "platform": "codearts",
            "state": "active",
            "approved_models": ["m"],
            "quota": {"used_percent": used},
        }

    return [row("a", 30.0), row("b", 10.0), row("c", 20.0)]


def _tool_trees() -> list[tuple[str, ast.Module]]:
    """`tools/**/*.py` 逐文件解析 —— 判据 2 / 4 / 5 共用的一份扫描面。"""
    out: list[tuple[str, ast.Module]] = []
    for path in sorted(TOOLS.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        out.append((path.relative_to(ROOT).as_posix(), ast.parse(source)))
    return out


def _callee_name(node: ast.Call) -> str:
    """调用的被调名：`pool_route.Seat(...)` 与 `Seat(...)` 都回 `Seat`。"""
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _calls_named(want: str) -> list[tuple[str, ast.Call]]:
    """扫全部 `tools/**/*.py`，取被调名为 `want` 的 `Call` 节点（带相对路径）。"""
    out: list[tuple[str, ast.Call]] = []
    for rel, tree in _tool_trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _callee_name(node) == want:
                out.append((rel, node))
    return out


def test_without_turns_only_usage_reorders() -> None:
    """判据 1 前半：不给 turns ⇒ 只有 `usage` 按额度重排，其余八个名字一律恒等。

    ★ 这一条防的是**偷偷加喂料**：谁给 `tools/pool/gateway.py` 那四条 `Seat(...)`
    补一个 `pace=` / `free=`，这里的某一行就会动 —— 而「接线」必须另开卡、另改 ADR。
    """
    rows = _rows()
    for name in UNROTATED:
        assert gateway._order(rows, name, pool="p") == IDENTITY, name
    assert gateway._order(rows, "usage", pool="p") == [1, 2, 0]


def test_same_turns_rotates_the_starting_seat() -> None:
    """判据 1 后半：**调用方持有**同一份 turns 才会转；每次新建空 dict 就退回恒等。

    后者正是卡 A372 修掉的缺口（turns 口子早就有，只是没人传）：`rotate` 先取模再自增，
    所以新 dict 的 `so_far` 恒为 0 ⇒ 三次全 `[0, 1, 2]`。两条一起钉住，
    「有人把 state 改成每次新建」这件事才会红。
    """
    turns: dict[str, int] = {}
    seen = [gateway._order(_rows(), "rotate", pool="p", turns=turns) for _ in range(3)]
    assert seen == [[0, 1, 2], [1, 2, 0], [2, 0, 1]]
    assert turns == {"p": 3}
    fresh = [gateway._order(_rows(), "rotate", pool="p", turns={}) for _ in range(3)]
    assert fresh == [IDENTITY, IDENTITY, IDENTITY]


def test_dispatch_sink_never_names_a_speed_strategy() -> None:
    """判据 2：派活器的字符串常量里不许出现 speed / fast / rotate / weighted 那一族。

    「探测」在号池里等于**真花一次额度**（`PROBE_EVERY = 5` 的 `fastest` 会拿最快的那个
    去试一次）；派活链是按 pending 卡顺序干活的，把 speed 接进去等于让排序器决定去花谁的钱。
    这条规矩今天仓内**没有成文条款**（只散见任务书），这条断言就是它的机检面。
    """
    source = (TOOLS / "wb_dispatch.py").read_text(encoding="utf-8")
    hits = [
        (node.lineno, node.value)
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.lower() in BANNED_IN_DISPATCH
    ]
    assert hits == [], hits
    assert wb_dispatch.SINK_ROUTING == "order"


def test_gateway_recognises_seven_names_and_speed_alias() -> None:
    """判据 3：七个名字是外部契约；`speed` / `Fast` 折成 `fast`；`smart` 在表外。

    与 `tests/test_pool_route_strategies.py` 的 `test_builtin_is_exactly_seven_in_magpie_order`
    **不重复**：那条对的是 magpie 的名字与顺序，这条钉的是「网关拿到 `--routing speed` 时
    认得出并折成 `fast`」。删掉别名表里那一条，那条绿、这条红。
    """
    assert pool_route.BUILTIN == ("order", "rotate", "usage", "pace", "weight", "free", "fast")
    assert pool_route.parse_routing("speed") == pool_route.FASTEST == "fast"
    assert pool_route.parse_routing("Fast") == "fast"
    assert pool_route.parse_routing("") == pool_route.SMART
    assert pool_route.SMART not in pool_route.BUILTIN
    assert pool_route.MANUAL not in pool_route.BUILTIN


def test_apply_strategy_has_one_call_site_and_caller_holds_turns() -> None:
    """判据 4：`apply_strategy` 的生产调用点恰一处，且 `state` 只由调用方的 turns 包出来。

    形状断言防的是「传个新空 dict 糊过去」：
    `state = None if turns is None else {"turns": turns}` —— 改成 `state={}` 的话
    rotate 会**静默**退回恒等（判据 1 后半也会红），但只有这一条能指出「是你在这里改坏的」。
    """
    calls = _calls_named("apply_strategy")
    assert [rel for rel, _ in calls] == ["tools/pool/gateway.py"], [
        (rel, node.lineno) for rel, node in calls
    ]
    assert [len(node.args) for _, node in calls] == [2]
    keyword_names = [sorted(kw.arg for kw in node.keywords if kw.arg) for _, node in calls]
    assert keyword_names == [["pool", "state"]]

    gateway_source = (TOOLS / "pool" / "gateway.py").read_text(encoding="utf-8")
    assignments = [
        node
        for node in ast.walk(ast.parse(gateway_source))
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "state" for t in node.targets)
        and isinstance(node.value, ast.IfExp)
    ]
    assert len(assignments) == 1, [node.lineno for node in assignments]
    conditional = assignments[0].value
    assert ast.unparse(conditional.test) == "turns is None"
    assert ast.unparse(conditional.body) == "None"
    assert ast.unparse(conditional.orelse) == "{'turns': turns}"


def test_seat_feed_fields_are_never_constructed() -> None:
    """判据 5：六个喂料字段在**号池座位**的构造里零出现（今天全是 `known` / `used`）。

    ★ 只认 `Attribute` 形态（`pool_route.Seat(...)`）：`tools/dsh_panel.py` 那三处也叫
    `Seat(`，是**裸 `Name` 形态**的面板条目，按名字扫会把它们误判成号池座位。
    另扫 `tools/pool/*.toml` 的 `weight` ⇒ 0 行（`weighted` 今天连配置来源都没有）。
    """
    attr_calls = [
        (rel, node) for rel, node in _calls_named("Seat") if isinstance(node.func, ast.Attribute)
    ]
    assert attr_calls, "扫描面空了 —— 说明 tools/ 下已经没有 Attribute 形态的 Seat 构造"
    offenders = [
        (rel, node.lineno, sorted(kw.arg for kw in node.keywords))
        for rel, node in attr_calls
        if {kw.arg for kw in node.keywords} & FEED_FIELDS
    ]
    assert offenders == [], offenders

    toml_with_weight = [
        path.relative_to(ROOT).as_posix()
        for path in sorted((TOOLS / "pool").glob("*.toml"))
        if "weight" in path.read_text(encoding="utf-8")
    ]
    assert toml_with_weight == [], toml_with_weight


def test_route_module_never_writes_anything() -> None:
    """判据 6：`tools/pool/route.py` 零写盘 —— 状态只在调用方手里，不做进程内全局。

    与 `apply_strategy` docstring 里那句「本函数不落盘」是同一件事的两个面：
    一句是散文（会漂），一条是断言（不会漂）。谁把 `turns` 改成模块级变量或
    `json.dump` 到磁盘，这条红 —— 那会把「调用方持有」偷偷变成 magpie 那个包级
    `turns` 的味道，本仓**故意**没抄。
    """
    source = (TOOLS / "pool" / "route.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    names |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert names & FORBIDDEN_WRITES == set(), sorted(names & FORBIDDEN_WRITES)
