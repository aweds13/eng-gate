r"""会话身份（F48，卡 A382 · T-AG670）—— 只认宿主注入的指纹，绝不编 id。

## 为什么值当测

magpie 的 F48 是一条**禁令**，不是一个开关（权威原文 `../_ext/_magpie_features.md:421`）：
「会话身份 = `AgentOf(record.Agent) + record.Session`；**绝不为没带 id 的请求编 id**，
prompt 文本、调用方 key、网络地址**永不**用来猜归属。」

本仓没有网关会话概念，能自报的只有宿主注入的 `DSH_SESSION_ID`。今天这条禁令**已经成立**
（缺指纹 ⇒ 放行且不写账本；网关只认四类入站头；`--resume auto` 拿不到会话文件就退 2），
但**没有一条测试钉得住「它成立」**—— `tests/test_pool_gateway.py` 今天零条入站头闭集钉子。
将来「照着 magpie 补全」的人第一步就会把 `conversationID` 那套 hash 派生抽过来，
而那时候没有任何一条测试会红。这份文件补的就是那几个空位。

| 钉子 | 钉哪一位 |
|---|---|
| `test_gateway_inbound_headers_are_exactly_four` | 入站头闭集恰好四类（见下） |
| `test_gateway_inbound_headers_name_no_session` | 四类里没有一类名字含 session / conversation |
| `test_session_id_derives_nothing` | `wb_session.session_id` 只读环境变量，不生成任何 id |
| `test_gateway_never_hashes_or_derives_identity` | 没有派生身份的调用形态 |
| `test_post_body_keys_carry_no_identity` | `_post` 从请求体取的键只有 model / stream |
| `test_gateway_paths_are_four_and_sessionless` | `PATHS` 恰好四条，没有一条名字含 session |

闭集是 Origin / Authorization / Content-Length / X-Pool-Caller 四类。

★ 全部只读源码（AST / 文本），不起进程、不写盘。

★ 「缺指纹 = 工人口径」的**行为**那一半不在这里重复钉 —— `tests/test_wb_session.py` 的
  `test_no_session_id_always_allowed` 已经逐字钉了 `claim("A1") == (True, "")` 与
  「工人口径不该写租约」。复制一遍就是第二份判据。
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

GATEWAY = ROOT / "tools" / "pool" / "gateway.py"
WB_SESSION = ROOT / "tools" / "wb_session.py"

#: 网关入站头闭集。加第五类必须先改卡规格并说明「会话从哪来、谁保证不编」。
ALLOWED_HEADERS = {"Origin", "Authorization", "Content-Length", "X-Pool-Caller"}
#: 名字里带这些词的头/键，一个都不许有（大小写无关）。
SESSION_WORDS = ("session", "conversation", "chat-id", "chat_id", "chatid")
#: 派生 id 的调用形态（★ 不含裸词 `sha256`：`:880` 的「sdk-hmac-sha256」是平台 auth_kind
#: 的错误文案，把它算进来会让这条钉子假红）。
DERIVATION_TOKENS = ("hashlib", "conversation_id", "conversationID", "conversationId",
                     "md5(", "sha256(", "sha1(", "blake2")
#: `session_id()` 里一个都不许出现的生成器。
ID_MAKERS = ("uuid4", "uuid1", "uuid", "random", "hashlib", "token_hex", "token_urlsafe",
             "secrets", "time", "monotonic")


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _func(tree: ast.Module, name: str) -> ast.FunctionDef:
    """按名字取函数；找不到就点名报错（锚点被改名/删了，不许静默跳过）。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"没找到函数 {name}（锚点被改名/删了）")


def _inbound_header_names() -> set[str]:
    """gateway.py 里所有 `self.headers.get("...")` 的常量 —— 入站头闭集。"""
    source = _source(GATEWAY)
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "get":
            continue
        # self.headers.get(...) —— 只认这一种形态，别的 Attribute 链不算
        if not isinstance(func.value, ast.Attribute) or func.value.attr != "headers":
            continue
        if not isinstance(func.value.value, ast.Name) or func.value.value.id != "self":
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                names.add(arg.value)
    return names


# ================================================================ ① 入站头闭集


def test_gateway_inbound_headers_are_exactly_four() -> None:
    """网关的入站头**恰好**四类：多一类就红（`X-Magpie-Session` 进不来）。

    今天：Origin（`:1052`）/ Authorization（`:1056`）/ Content-Length（`:1105`）/
    X-Pool-Caller（`:1132`）。
    """
    got = _inbound_header_names()

    assert got == ALLOWED_HEADERS, (
        f"网关入站头闭集变了：{sorted(got)}；"
        f"卡的规格写死的是 {sorted(ALLOWED_HEADERS)} —— 加第五类要先改卡规格"
    )
    # 反向自证：扫描器真的看见东西了（不是扫空了才"相等"）
    assert len(got) == 4


def test_gateway_inbound_headers_name_no_session() -> None:
    """四类里头没有一类叫「会话」—— 换名字也躲不过（大小写无关的子串查）。"""
    for name in _inbound_header_names():
        low = name.lower()
        for word in SESSION_WORDS:
            assert word not in low, f"入站头 {name!r} 的名字里含 {word!r}：网关不该有会话身份"


# ================================================================ ② 缺指纹不编


def test_session_id_derives_nothing() -> None:
    """`wb_session.session_id` 的函数体里只有 `os.environ.get`，没有 uuid/random/hashlib。

    ★ 钉的是「**派生**」不是「行数」：`os.environ.get` 恰好一次，且生成器一个都不出现。
      把 `:38` 改成 `... .strip() or uuid4().hex` 会红，而 `os.environ.get` 仍只一次。
    """
    source = _source(WB_SESSION)
    tree = ast.parse(source)
    func = _func(tree, "session_id")

    body = ast.get_source_segment(source, func) or ""
    assert len(re.findall(r"os\.environ\.get", body)) == 1, (
        f"session_id 里 os.environ.get 该恰好一次，实际正文：{body!r}"
    )

    seen: set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Name):
            seen.add(node.id)
        elif isinstance(node, ast.Attribute):
            seen.add(node.attr)
        elif isinstance(node, ast.alias):
            seen.add(node.name)
    made = sorted(set(ID_MAKERS) & seen)
    assert made == [], f"session_id 里出现了 id 生成器 {made}：缺指纹时**不许**编一个"

    # 反向自证：拿到的确实是那个函数（不是同名空壳）
    assert "DSH_SESSION_ID" in body, f"取到的 session_id 正文里没有 DSH_SESSION_ID：{body!r}"


# ================================================================ ⑤ 反向禁令


def test_gateway_never_hashes_or_derives_identity() -> None:
    """网关源码里**没有**从正文/地址派生归属的调用形态。

    ★ 被杀的是**调用形态**（`hashlib` / `conversationID` / `md5(` / `sha256(` …），
      **不是**裸词 `sha256`：`:880` 的「（sdk-hmac-sha256 / cookie / file / dir / none
      一条都不搬）⇒ 先别登记它的 chat 端点。」是平台 `auth_kind` 的错误文案，与派生 id
      无关 —— 断言裸词会让这条钉子假红，那是噪音不是判据。
    """
    source = _source(GATEWAY)

    hit = [token for token in DERIVATION_TOKENS if token in source]
    assert hit == [], (
        f"网关里出现了派生归属的调用形态 {hit}：F48 禁止从 prompt 文本 / 调用方 key / "
        f"网络地址推会话归属（magpie 的 conversationID 正是这条禁令的反例）"
    )


def test_post_body_keys_carry_no_identity() -> None:
    """`_post` 从请求体取的键只有 model / stream —— 不许从 body 里读会话归属。"""
    source = _source(GATEWAY)
    tree = ast.parse(source)
    func = _func(tree, "_post")

    keys: set[str] = set()
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        f2 = node.func
        if not isinstance(f2, ast.Attribute) or f2.attr != "get":
            continue
        if not isinstance(f2.value, ast.Name) or f2.value.id != "obj":
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                keys.add(arg.value)

    assert keys == {"model", "stream"}, (
        f"_post 从 body 取的键变了：{sorted(keys)}；今天只该是 model / stream"
    )
    for key in keys:
        for word in SESSION_WORDS:
            assert word not in key.lower(), f"body 键 {key!r} 里含 {word!r}：不许从 body 派生归属"


def test_gateway_paths_are_four_and_sessionless() -> None:
    """`PATHS` 恰好四条路径，且没有一条名字含 session —— 网关没有会话面。"""
    from pool import gateway  # noqa: PLC0415 —— 只读常量，不起服务

    paths = set(gateway.PATHS)
    assert len(paths) == 4, f"PATHS 该恰好四条，实际 {len(paths)} 条：{sorted(paths)}"
    assert paths == {"/v1/chat/completions", "/v1/messages", "/v1/models", "/v1/pool/routes"}
    for path in paths:
        for word in SESSION_WORDS:
            assert word not in path.lower(), f"路径 {path!r} 含 {word!r}：网关不该有会话面"
