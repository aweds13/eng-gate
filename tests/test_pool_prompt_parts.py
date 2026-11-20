"""卡 A380 · T-AG668 —— 分段账的钉子（tools/pool/prompt_parts.py，判据 1 / 2 / 5）。

判据原文见 `复盘/卡/卡A380-F96Context页分段账-只留名字与大小不搬面板与读回原文.md`：
账里只留**名字与大小**，正文一个字都不进（判据 2 用哨兵串实测），且本模块是**纯函数**
（不缓存 body、不 import threading / time —— 判据 5 的 AST 钉）。

★ 三条最容易做成假牙的地方：

1. `parts_of` 的四段**空着也要占位**（`tokens: 0, items: []`），顺序固定
   `system → tools → results → chat`；只断言「某一非空段在」会漏掉「顺序 / 占位」这两件事。
2. `tokens_of` 是**估算**不是分词器：只钉 `"abcd" == 1` 挡不住
   `return len(text) // 4` 这种「差不多但错了」的实现（`"abcdefgh"` 会变成 1），
   所以 ASCII 要同时钉 4 字符与 8 字符（变异 M1 咬的就是这颗）。
3. 哨兵串必须**两个方向**都断：`SECRET not in json.dumps(parts)`（没漏出去）**和**
   `SECRET in body_text`（它确实在 body 里 —— 否则前一条是空转）。
"""

from __future__ import annotations

import ast
import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

# ★ 走 import_module 而不是顶层 `from pool import …`：上面的 sys.path.insert 让 ruff 的 E402
#   与「导入必须在路径设置之后」天然冲突；这里不挂 lint 豁免（体例照 tests/test_pool_pricing.py）。
prompt_parts = importlib.import_module("pool.prompt_parts")

SECRET = "<SECRET-2f9a>"
MODULE_REL = ("tools", "pool", "prompt_parts.py")


def _body(**extra: object) -> bytes:
    """造一份 chat 形状的 body（四个段**都有**，才钉得住顺序与切法）。"""
    payload: dict[str, object] = {
        "model": "huaweicloud-maas/GLM-5.2",
        "system": "你是派活器：只回一句话。",
        "tools": [
            {"name": "read_file", "description": "读一个文件", "input_schema": {"type": "object"}},
            {"name": "run_gate", "description": "跑一道门", "input_schema": {"type": "object"}},
        ],
        "messages": [
            {"role": "user", "content": "跑一下 gates/pool.toml 的门"},
            {"role": "assistant", "content": "好",
             "tool_calls": [{"id": "c1", "function": {"name": "run_gate", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "PASS 门 3 道"},
            {"role": "user", "content": "再看看"},
        ],
    }
    payload.update(extra)
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _kinds(parts: list[dict]) -> list[str]:
    return [str(part["kind"]) for part in parts]


# ---------------------------------------------------------------- 判据 1：形状与切法


def test_tokens_of_is_the_documented_estimate() -> None:
    """ASCII 四字符一 token、其余一字符一 token（照 `prompt.go:76-78`）。

    ★ 4 字符与 8 字符**都要钉**：只钉 4 字符时 `return len(text) // 4` 也过得了
      （`"abcd"` 两种写法都给 1），8 字符才分得开（对的给 2、错的给 2？—— 见下）。
    """
    assert prompt_parts.tokens_of("abcd") == 1
    # `(ascii + 3) // 4` 向上取整：8 字符 ⇒ 2；`len(text) // 4` 也给 2 —— 但 5 字符就分开了
    # （对的 2、错的 1），所以三个读数一起钉。
    assert prompt_parts.tokens_of("abcdefgh") == 2
    assert prompt_parts.tokens_of("abcde") == 2
    assert prompt_parts.tokens_of("") == 0
    # 非 ASCII 一字符一 token（CJK 为主）；`"中文"` 只有 2 个字符，却给 2 个 token。
    assert prompt_parts.tokens_of("中文") == 2


def test_prompt_items_is_twenty_four() -> None:
    """每段最多 24 项（照 `prompt.go:73-74` `const promptItems = 24`）。"""
    assert prompt_parts.PROMPT_ITEMS == 24


def test_parts_has_four_kinds_in_fixed_order() -> None:
    """四段**按固定顺序**交出来（`prompt.go:41` partOrder 的子序列）。"""
    parts = prompt_parts.parts_of("chat", _body())
    assert parts is not None
    assert _kinds(parts) == ["system", "tools", "results", "chat"]


def test_empty_parts_still_take_a_slot() -> None:
    """★ 本仓认得的那四类**空着也占位**（`tokens: 0, items: []`），不是被跳过。

    与 magpie 原件的差异（原件 `prompt.go:190-244` 是 `len(m)==0 { continue }` 跳过）已在
    卡规格里明说：本仓要的是「每次都是四行」，读的人不必猜「少的那一行是零还是没有」。
    """
    body = json.dumps({"model": "x", "messages": [{"role": "user", "content": "hi"}]}).encode()
    parts = prompt_parts.parts_of("chat", body)
    assert parts is not None
    assert _kinds(parts) == ["system", "tools", "results", "chat"]
    by_kind = {part["kind"]: part for part in parts}
    for kind in ("system", "tools", "results"):
        assert by_kind[kind] == {"kind": kind, "tokens": 0, "items": []}
    assert by_kind["chat"]["tokens"] > 0


def test_system_part_takes_top_level_and_system_messages() -> None:
    """`system` = 顶层 `system` **加上** `messages` 里 role 为 system / developer 的。"""
    body = json.dumps({
        "system": "顶层的一段",
        "messages": [
            {"role": "system", "content": "消息里的一段"},
            {"role": "developer", "content": "开发者的那段"},
            {"role": "user", "content": "问题"},
        ],
    }, ensure_ascii=False).encode("utf-8")
    parts = prompt_parts.parts_of("chat", body)
    assert parts is not None
    system = parts[0]
    assert system["kind"] == "system"
    names = [item["name"] for item in system["items"]]
    assert "system" in names  # 顶层那段的名字固定叫 system（tag="prompt"）
    assert "turn 1" in names and "turn 2" in names
    tags = {item["tag"] for item in system["items"]}
    assert "prompt" in tags and "system" in tags and "developer" in tags


def test_tools_part_one_item_per_tool() -> None:
    """`tools` = 顶层 `tools`，**每个工具一项**，`name` 当 PromptItem.Name。"""
    parts = prompt_parts.parts_of("chat", _body())
    assert parts is not None
    tools = parts[1]
    assert tools["kind"] == "tools"
    assert sorted(item["name"] for item in tools["items"]) == ["read_file", "run_gate"]
    assert {item["tag"] for item in tools["items"]} == {"tool"}


def test_openai_shaped_tool_name_is_read_from_function() -> None:
    """OpenAI 形状的 `{"type": "function", "function": {"name": …}}` 也认得出名字。"""
    body = json.dumps({
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [{"type": "function",
                   "function": {"name": "run_gate", "description": "跑门", "parameters": {}}}],
    }, ensure_ascii=False).encode("utf-8")
    parts = prompt_parts.parts_of("chat", body)
    assert parts is not None
    assert [item["name"] for item in parts[1]["items"]] == ["run_gate"]


def test_results_part_is_tool_roles_and_chat_is_the_rest() -> None:
    """`results` = `role == "tool"`；`chat` = 剩下那些（含带 tool_calls 的 assistant）。"""
    parts = prompt_parts.parts_of("chat", _body())
    assert parts is not None
    results = parts[2]
    chat = parts[3]
    assert results["kind"] == "results" and chat["kind"] == "chat"
    assert [item["name"] for item in results["items"]] == ["turn 3"]
    assert {item["tag"] for item in results["items"]} == {"tool"}
    # 段内次序按 token 降序（卡 A380 判据 1 的逐字口径）—— 所以这里只钉**集合**，不钉次序：
    # 钉次序会把「排序」这件事换个方向重复一遍，反而挡不住切法错误。
    assert {item["name"] for item in chat["items"]} == {"turn 1", "turn 2", "turn 4"}
    assert {item["tag"] for item in chat["items"]} == {"user", "assistant"}


def test_thirty_tools_collapse_to_twenty_four_with_a_rest_item() -> None:
    """★ 超 24 项时**合并成一项**：24 项 = 前 23 项 + 一项「其余 7 项」。"""
    tools = [{"name": f"tool-{index:02d}", "description": "读一个文件",
              "input_schema": {"type": "object"}} for index in range(30)]
    body = json.dumps({"messages": [{"role": "user", "content": "hi"}], "tools": tools},
                      ensure_ascii=False).encode("utf-8")
    parts = prompt_parts.parts_of("chat", body)
    assert parts is not None
    items = parts[1]["items"]
    assert len(items) == 24
    assert items[-1]["tag"] == "rest"
    assert items[-1]["n"] == 7
    assert len(items[:-1]) == 23


def test_rest_item_sums_the_collapsed_tokens() -> None:
    """被并掉那 7 项的大小记在 rest 的 `tokens` 里（不是丢掉、也不是记成项数）。"""
    tools = [{"name": f"tool-{index:02d}", "description": "x" * (4 * (index + 1)),
              "input_schema": {"type": "object"}} for index in range(30)]
    body = json.dumps({"messages": [{"role": "user", "content": "hi"}], "tools": tools},
                      ensure_ascii=False).encode("utf-8")
    parts = prompt_parts.parts_of("chat", body)
    assert parts is not None
    items = parts[1]["items"]
    assert items[-1]["tag"] == "rest" and items[-1]["n"] == 7
    # 被留下的是最大的 23 个（tool-07 … tool-29），并掉的是最小的 7 个（tool-00 … tool-06）。
    kept = sum(item["tokens"] for item in items[:-1])
    assert items[-1]["tokens"] > 0
    assert parts[1]["tokens"] == kept + items[-1]["tokens"]


def test_items_are_sorted_by_tokens_then_name() -> None:
    """非 chat 段按 token **降序**、同量按名字升序（照 `prompt.go:228-231`）。"""
    tools = [{"name": "small", "description": "x", "input_schema": {}},
             {"name": "big", "description": "x" * 400, "input_schema": {}}]
    body = json.dumps({"messages": [{"role": "user", "content": "hi"}], "tools": tools},
                      ensure_ascii=False).encode("utf-8")
    parts = prompt_parts.parts_of("chat", body)
    assert parts is not None
    assert [item["name"] for item in parts[1]["items"]] == ["big", "small"]


def test_messages_protocol_is_accepted_too() -> None:
    """两条协议都认：`chat` 与 `messages`。"""
    assert prompt_parts.parts_of("messages", _body()) is not None
    assert prompt_parts.parts_of("chat", _body()) is not None


def test_bad_inputs_give_none_not_empty_list() -> None:
    """★ 坏输入 ⇒ `None`（说不出来），**不是** `[]`（量过，一类都没有）。"""
    assert prompt_parts.parts_of("chat", b"not json") is None
    assert prompt_parts.parts_of("gemini", b"{}") is None
    assert prompt_parts.parts_of("chat", b"[1, 2, 3]") is None  # 是 JSON，但不是对象
    assert prompt_parts.parts_of("chat", b"") is None
    assert prompt_parts.parts_of("chat", b"\xff\xfe") is None  # 不是 UTF-8


# ---------------------------------------------------------------- 判据 2：正文一个字都不进账


def test_secret_never_reaches_the_parts() -> None:
    """★ 哨兵串放进正文，账里**一个字都不许出现**；反向自证它确实在 body 里。"""
    body = json.dumps({
        "model": "huaweicloud-maas/GLM-5.2",
        "system": "系统提示",
        "tools": [{"name": "read_file", "description": f"读一个文件 {SECRET}",
                   "input_schema": {"type": "object"}}],
        "messages": [{"role": "user", "content": f"帮我看看 {SECRET} 这个文件"},
                     {"role": "tool", "tool_call_id": "c1", "content": f"内容里有 {SECRET}"}],
    }, ensure_ascii=False).encode("utf-8")
    body_text = body.decode("utf-8")
    assert SECRET in body_text, "哨兵串必须在 body 里 —— 否则下一条断言是空转"

    parts = prompt_parts.parts_of("chat", body)
    assert parts is not None
    dumped = json.dumps(parts, ensure_ascii=False)
    assert SECRET not in dumped
    # 连片段都不许漏（描述被截断 80 字那种「漏一半」也算漏）。
    assert SECRET[1:-1] not in dumped


def test_parts_keys_are_the_only_documented_ones() -> None:
    """每一项的键就是文档写的那四个：`name / tag / n / tokens` —— 没有第五个装正文的键。"""
    parts = prompt_parts.parts_of("chat", _body())
    assert parts is not None
    for part in parts:
        assert set(part) == {"kind", "tokens", "items"}
        for item in part["items"]:
            assert set(item) == {"name", "tag", "n", "tokens"}


# ---------------------------------------------------------------- 判据 5：纯函数（AST 扫）


def _module_source() -> str:
    return (ROOT.joinpath(*MODULE_REL)).read_text(encoding="utf-8")


def _is_container(value: ast.AST) -> bool:
    """这个表达式是不是「容器字面量 / 容器构造」（list / dict / deque，含注解形式）。"""
    if isinstance(value, (ast.List, ast.Dict, ast.ListComp, ast.DictComp)):
        return True
    if isinstance(value, ast.Call):
        func = value.func
        name = ""
        if isinstance(func, ast.Name):
            name = func.id
        elif isinstance(func, ast.Attribute):
            name = func.attr
        return name in {"list", "dict", "deque", "OrderedDict", "defaultdict", "Counter"}
    return False


def test_module_holds_no_module_level_container() -> None:
    """★ 模块级不许有容器 —— 有容器就是在缓存 body（判据 5）。"""
    tree = ast.parse(_module_source())
    offenders = []
    for node in tree.body:
        if isinstance(node, ast.AugAssign):
            offenders.append(node.lineno)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            if value is not None and _is_container(value):
                offenders.append(node.lineno)
    assert offenders == [], f"模块级容器（会被读成缓存）：行 {offenders}"


def test_module_imports_no_threading_and_no_time() -> None:
    """★ 不 import `threading` / `time`（同 `gateway.py:11` 「不做定时器」那条纪律）。"""
    tree = ast.parse(_module_source())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "threading" not in imported
    assert "time" not in imported
    assert imported <= {"__future__", "json"}, f"只许这两个 import，实际 {sorted(imported)}"
