r"""逐部分拆 prompt：**只留名字与大小**，正文一个字都不进账（卡 A380 · F96）。

对等 magpie `internal/gateway/prompt.go` 的**前半根支柱**：把一次请求的 prompt 拆成几类，
每类报「估算的 token 数」与「里面有哪些东西」。magpie 包注释逐字：*The Prompt keeps only
names — the instruction files' and read files' paths, the tools' names, "turn 3" — never the
prompt's text, and it is what goes in the routing history on disk.*（`prompt.go:1-16`）
本模块照这条纪律：交出去的每一项只有 `{"kind", "tokens", "items": [{"name", "tag", "n",
"tokens"}]}` —— **没有一个字段装正文**。

## 只认四类（七类里另外三类的缺席理由）

magpie 分七类：`system / tools / skills / memory / files / results / chat`（`prompt.go:30-41`）。
`skills` / `memory`（CLAUDE.md、AGENTS.md 这类 instruction files）/ `files`（工具读进来的
文件与图）都是 **agent harness 的语义**，靠解析「agent 原样发来的 body」得到（`prompt.go:1-16`
逐字 *Read from the body the agent sent, as it sent it*）。本仓的 body 是消费方发来的
chat / messages JSON，**没有这层语义** ⇒ 这三类**恒定不出现**。

★ 是「不出现」，**不是**空数组占位：写一条 `{"kind": "skills", "tokens": 0, "items": []}`
会被读成「量过，这一类是零」，而事实是「本仓没有这个概念」——「不知道」不许写成 0
（口径同 `docs/subsystems/pool/模型与号池.md:161-163`）。反过来，**本仓认得的那四类空着也占位**
（`tokens: 0, items: []`）：那确实是「这次这一类是零」，与「不存在」不是一回事。

## 估算不是分词器

`tokens_of` 逐字复刻 `prompt.go:76-78`：*tokensOf estimates the tokens of a text: about four
characters a token for ASCII, a token a character for the rest (CJK, mostly).*
⇒ 给的是**可复算的估算**，不是 vendor 计的 token（本仓没有分词器，见 `gateway.py:16-17`）。
账里因此**不出现** `counted` / `window` 这类「看着像真数」的键。

## 边界（如实写，别抹平）

- 输入坏（`protocol` 不是 `chat` / `messages`、body 不是 UTF-8 JSON、JSON 不是对象）⇒
  **`None`**，不抛、不给 `[]`：调用方据此写 `null`（「说不出来」），而不是写 0。
- 本模块是**纯函数**：不缓存 body、不 import `threading` / `time`、没有模块级容器 ——
  与 `gateway.py:11`「不做定时器：没有后台线程」同一条纪律（判据 5 的 AST 钉就是这条）。
"""

from __future__ import annotations

import json

#: 本仓认得的四类，**顺序固定**（照 `prompt.go:41` 的 `partOrder` 取子序列）。
PART_SYSTEM = "system"
PART_TOOLS = "tools"
PART_RESULTS = "results"
PART_CHAT = "chat"
PART_ORDER: tuple[str, ...] = (PART_SYSTEM, PART_TOOLS, PART_RESULTS, PART_CHAT)

#: 每段最多几项（照 `prompt.go:73-74` `const promptItems = 24`）；超出的并成一项。
PROMPT_ITEMS = 24

#: 本仓认得的两种协议（body 的两种形状）；别的协议 ⇒ `parts_of` 给 `None`。
PROTOCOL_CHAT = "chat"
PROTOCOL_MESSAGES = "messages"
PROTOCOLS: tuple[str, ...] = (PROTOCOL_CHAT, PROTOCOL_MESSAGES)

#: ASCII 的边界：`ord(char) < _ASCII_LIMIT` 即 magpie 的 `s[i] < utf8.RuneSelf`。
_ASCII_LIMIT = 128


def tokens_of(text: str) -> int:
    """一段文本的**估算** token 数：ASCII 四字符一 token，其余（CJK 为主）一字符一 token。

    逐字复刻 magpie `magpie-main/internal/gateway/prompt.go:76-78` 的 `func tokensOf`
    （末行 `return (ascii+3)/4 + other`）—— **不是分词器**，别拿它当 vendor 计数用。
    """
    ascii = 0
    other = 0
    for char in text:
        if ord(char) < _ASCII_LIMIT:
            ascii += 1
        else:
            other += 1
    return (ascii + 3) // 4 + other


def _raw_tokens(value: object) -> int:
    """一段 JSON 的估算：`(字节数 + 3) // 4`（照 `prompt.go:93` `func rawTokens`）。"""
    return (len(json.dumps(value, ensure_ascii=False).encode("utf-8")) + 3) // 4


def _content_tokens(value: object) -> int:
    """一段 `content` 的估算：字符串走 `tokens_of`，块数组 / 对象摊平后再估。

    ★ 只**数**、不**留**：返回值是整数，正文到这里为止，不进任何返回值。
    """
    if isinstance(value, str):
        return tokens_of(value)
    if isinstance(value, list):
        return sum(_content_tokens(item) for item in value)
    if isinstance(value, dict):
        text = value.get("text")
        return tokens_of(text) if isinstance(text, str) else _raw_tokens(value)
    if value is None:
        return 0
    return _raw_tokens(value)


def _tool_name(raw: object) -> str:
    """工具的名字：Anthropic 形状 `{"name": …}`；OpenAI 形状 `{"function": {"name": …}}`。"""
    if not isinstance(raw, dict):
        return ""
    name = raw.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    function = raw.get("function")
    if isinstance(function, dict):
        inner = function.get("name")
        if isinstance(inner, str) and inner.strip():
            return inner.strip()
    return ""


def _merge(items: list[dict], tag: str, name: str, tokens: int) -> None:
    """按 `(tag, name)` 合并（照 `prompt.go:158-178` `add`）；`tokens <= 0` 的不记。"""
    if tokens <= 0:
        return
    for item in items:
        if item["tag"] == tag and item["name"] == name:
            item["n"] = int(item["n"]) + 1
            item["tokens"] = int(item["tokens"]) + tokens
            return
    items.append({"name": name, "tag": tag, "n": 1, "tokens": tokens})


def _collapse(items: list[dict]) -> list[dict]:
    """按 token 降序（同量按名字升序）；超出 `PROMPT_ITEMS` 的并成一项。

    合并的形状照 `prompt.go:236-243`：留前 `PROMPT_ITEMS - 1` 项，末尾一项记「其余 N 项」
    与它们的 token 和（`n` 是被并掉的**项数**，不是 token 数）。
    """
    ordered = sorted(items, key=lambda item: (-int(item["tokens"]), str(item["name"])))
    if len(ordered) > PROMPT_ITEMS:
        tail = ordered[PROMPT_ITEMS - 1:]
        rest = {"name": f"（其余 {len(tail)} 项）", "tag": "rest", "n": len(tail),
                "tokens": sum(int(item["tokens"]) for item in tail)}
        return ordered[: PROMPT_ITEMS - 1] + [rest]
    return ordered


def parts_of(protocol: str, body: bytes) -> list[dict] | None:
    """把一次请求的 body 拆成四段（`system → tools → results → chat`）；说不出来 ⇒ `None`。

    四类的切法（本仓能认的全文，照卡 A380 缺口径 3）：

    | 段 | 从 body 的哪里切 |
    |---|---|
    | `system` | 顶层 `system`；`messages` 里 `role` 为 `system` / `developer` |
    | `tools` | 顶层 `tools`（每个工具一项，`name` 当 `PromptItem.Name`） |
    | `results` | `messages` 里 `role == "tool"`（工具输出） |
    | `chat` | 剩下的 `messages`（user / assistant，含 `tool_calls`） |

    ★ 每条消息的 `name` 是轮次标签 `"turn 3"`（照 magpie 的 `PromptItem.Name`），`tag` 是
      `role` —— 都只是**标签**，不含正文。
    ★ 坏输入给 `None`：调用方写 `null`（没人量过），**不许**写 `[]`（量过，一点都没有）。
    """
    if protocol not in PROTOCOLS:
        return None
    try:
        parsed = json.loads(body)
    except (TypeError, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None

    buckets: dict[str, list[dict]] = {kind: [] for kind in PART_ORDER}

    system = parsed.get("system")
    if system:
        _merge(buckets[PART_SYSTEM], "prompt", "system", _content_tokens(system))

    tools = parsed.get("tools")
    if isinstance(tools, list):
        for raw in tools:
            name = _tool_name(raw)
            _merge(buckets[PART_TOOLS], "tool", name or "(无名)", _raw_tokens(raw))

    messages = parsed.get("messages")
    if isinstance(messages, list):
        for index, message in enumerate(messages, start=1):
            if not isinstance(message, dict):
                continue
            role = str(message.get("role") or "")
            tokens = _content_tokens(message.get("content"))
            calls = message.get("tool_calls")
            if calls:
                tokens += _raw_tokens(calls)
            kind = PART_CHAT
            if role == "tool":
                kind = PART_RESULTS
            elif role in ("system", "developer"):
                kind = PART_SYSTEM
            _merge(buckets[kind], role or "?", f"turn {index}", tokens)

    out: list[dict] = []
    for kind in PART_ORDER:
        items = _collapse(buckets[kind])
        out.append({"kind": kind,
                    "tokens": sum(int(item["tokens"]) for item in items),
                    "items": items})
    return out
