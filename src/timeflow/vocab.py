"""可配置词表（SR-NF7 / G 批 · T-G1）—— SR-NF7 要的"不改核心就能加"到底能加什么。

**能加的是什么**：`SR-NF7`（N36）原话是"用户能加功能/字段/复习形式/可视化/集成，不改核心"。
逐项看下来，真正**不改核心**就能加的只有**词表**这一类东西 —— 一串 `id → 中文标签`：

- 复习形式（挖空 / 问答卡 / 真题 / 你自己起的名字）；
- 时间热力图的维度（专注 / 手动投入 / 复习 / 产出 / 债务，以及要不要显示、怎么叫）；

而 **加字段**要动 schema 迁移、**加功能**要写领域函数 + 路由 + 界面 —— 这两件**做不到不改核心**，
如实写在 `docs/EXTENDING.md`（口径见 `复盘/口径定案-待定清单.md` §6）。

**这个模块是"扩展点"本身**：词表在这里**声明一处**，配置校验（`config.py`）、默认值来源、
非法值拒绝、界面的增删、API 的读写**全都自动跟着走** —— 加一张新词表 = 在这里加一条 `Vocabulary`，
不改路由、不改界面（设置页是通用渲染的）。

**三层默认值**（与附件打开方式 / 专注白名单 / 归档天数同一套机制，不另造一套）：

1. `config.toml`（文件级，写 `[review] forms = {...}` 这种；**改了要重启**）；
2. `app_settings` 里的 JSON（本机在设置页改过的，**优先**）；
3. 内置兜底（本模块 `builtin`，= 未配置时的现状，保证新库开箱可用）。

**非法值一律拒绝**（不静默回落）：id 必须是 `[a-z][a-z0-9_-]{0,31}`、标签非空且 ≤40 字、
条数 1~`max_items`；`allowed` 不为空时 id 还必须在名单内（例如热力图维度必须对应真的存在的
数据字段）。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import sqlite3

# `app_settings` 是通用 key/value 表（附件 / 专注 / 提醒 / 归档天数 / 口径开关都用它），
# 词表靠这个前缀与它们区分。
SETTING_PREFIX = "vocab."

# id 只用 ASCII 小写：它会进 URL/配置/事实，越无聊越好（中文只出现在标签里）。
_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
MAX_LABEL = 40
DEFAULT_MAX_ITEMS = 20


@dataclass(frozen=True)
class Vocabulary:
    """一张可配置词表。

    `allowed` 为空 = id 由用户自由起（复习形式就是这种：它只是个标签）；
    不为空 = id 必须落在名单里（热力图维度必须对应真的存在的数据字段，否则画出来是空的）。
    """

    key: str
    title: str
    question: str
    builtin: tuple[tuple[str, str], ...]
    allowed: tuple[str, ...] | None = None
    max_items: int = DEFAULT_MAX_ITEMS
    note: str = ""

    @property
    def setting_key(self) -> str:
        return SETTING_PREFIX + self.key

    def default_items(self, defaults: Mapping[str, str] | None = None) -> dict[str, str]:
        """文件级默认（config.toml）优先于内置兜底 —— 都没有就用内置。"""
        if defaults:
            return dict(defaults)
        return dict(self.builtin)


REVIEW_FORMS = Vocabulary(
    key="review_forms",
    title="复习形式",
    question="建复习卡时「形式」这一栏有哪几种？",
    builtin=(("cloze", "挖空"), ("qa", "问答卡"), ("exam", "真题")),
    note="形式只是标签（不改调度、不改卡片长相），所以你想起什么名字都行 —— "
         "中文标签随你写，id 用小写英文（它进 URL 与配置）。",
)

HEATMAP_DIMENSIONS = Vocabulary(
    key="heatmap_dimensions",
    title="时间热力图的维度",
    question="统计页那张年历热力图，可以按哪些维度看、分别叫什么？",
    builtin=(
        ("focus_minutes", "专注"),
        ("manual_minutes", "手动投入"),
        ("review_count", "复习"),
        ("output_count", "产出"),
        ("debt_count", "债务（欠多少）"),
    ),
    # 维度必须对应**真的算得出来的数据字段**（见 `core/insights.HEATMAP_FIELDS`）——
    # 换句话说：**换一个维度看已有的数**能配置，**算一个新维度**仍要改核心（如实写进 EXTENDING）。
    allowed=(
        "focus_minutes",
        "manual_minutes",
        "review_count",
        "output_count",
        "debt_count",
    ),
    max_items=8,
    note="这里能改的是「用哪些维度看、它们排第几、叫什么」；**要算一个全新的维度仍需改核心代码**"
         "（新字段/新算法不是词表能变出来的）。",
)

ALL: tuple[Vocabulary, ...] = (REVIEW_FORMS, HEATMAP_DIMENSIONS)


def by_key(key: Any) -> Vocabulary:
    """按 key 取词表；没有这张就 ValueError（界面拿到的永远是后端原话）。"""
    if not isinstance(key, str):
        raise ValueError("词表标识必须是字符串")
    for vocab in ALL:
        if vocab.key == key:
            return vocab
    known = "/".join(v.key for v in ALL)
    raise ValueError(f"没有这张词表：{key}（现有：{known}）")


# ---------------------------------------------------------------- 校验 / 解析
def _check_id(item_id: Any, vocab: Vocabulary) -> str:
    text = str(item_id).strip()
    if not _ID_RE.match(text):
        raise ValueError(
            f"「{vocab.title}」的 id 只能用小写英文/数字/下划线/短横"
            f"（如 my_form），收到：{item_id!r}"
        )
    if vocab.allowed is not None and text not in vocab.allowed:
        raise ValueError(
            f"「{vocab.title}」不认识这个 id：{text}（只能是 {'/'.join(vocab.allowed)}）"
        )
    return text


def _check_label(label: Any, vocab: Vocabulary) -> str:
    text = str(label).strip()
    if not text:
        raise ValueError(f"「{vocab.title}」的标签不能为空")
    if len(text) > MAX_LABEL:
        raise ValueError(f"「{vocab.title}」的标签最多 {MAX_LABEL} 字")
    return text


def parse(value: object, vocab: Vocabulary) -> dict[str, str]:
    """把 `{id: 标签}` 校验成规范形式（保持顺序）。非法值一律 ValueError（不静默回落）。

    接受 dict（TOML inline table / JSON 对象）；**不接受**列表 —— 顺序由 dict 的键序表达，
    少一种形状就少一处能写错的地方。
    """
    if not isinstance(value, Mapping):
        raise ValueError(f"「{vocab.title}」要写成 {{id = \"标签\", …}} 这样的表，收到：{value!r}")
    items: dict[str, str] = {}
    for raw_id, raw_label in value.items():
        item_id = _check_id(raw_id, vocab)
        if item_id in items:  # dict 本身不会重复键，但 " qa" / "qa" 这种会出现
            raise ValueError(f"「{vocab.title}」里 {item_id} 重复了")
        items[item_id] = _check_label(raw_label, vocab)
    if not items:
        raise ValueError(f"「{vocab.title}」至少要留一项（全删掉就没得选了）")
    if len(items) > vocab.max_items:
        raise ValueError(f"「{vocab.title}」最多 {vocab.max_items} 项（现在 {len(items)} 项）")
    return items


# ---------------------------------------------------------------- 读写（app_settings + 配置默认）
def _get_raw(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return None if row is None else str(row["value"])


def _put_raw(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO app_settings (key, value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def get(
    conn: sqlite3.Connection, vocab: Vocabulary, defaults: Mapping[str, str] | None = None
) -> dict[str, str]:
    """这张词表**现在生效**的样子：本机改过的 → 配置 → 内置兜底。

    库里存的值坏了（手改过库/老版本）时退回配置/内置 —— 与附件打开方式同样的处理：
    宁可跑默认，也不能因为一条脏设置让整个页面读不出来。
    """
    fallback = vocab.default_items(defaults)
    raw = _get_raw(conn, vocab.setting_key)
    if raw is None:
        return fallback
    try:
        loaded = json.loads(raw)
    except ValueError:
        return fallback
    try:
        return parse(loaded, vocab)
    except ValueError:
        return fallback


def is_default(
    conn: sqlite3.Connection, vocab: Vocabulary, defaults: Mapping[str, str] | None = None
) -> bool:
    """是否还停在"没改过"的样子（等于配置/内置默认）。"""
    return get(conn, vocab, defaults) == vocab.default_items(defaults)


def set_items(
    conn: sqlite3.Connection,
    vocab: Vocabulary,
    value: object,
    defaults: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """改这张词表（整张替换）。校验通过才落库；非法值 ValueError。"""
    items = parse(value, vocab)
    _put_raw(conn, vocab.setting_key, json.dumps(items, ensure_ascii=False))
    conn.commit()
    return items


def reset(conn: sqlite3.Connection, vocab: Vocabulary) -> dict[str, str]:
    """回到配置/内置默认（删掉本机那条设置，而不是把当前值再写一遍）。"""
    conn.execute("DELETE FROM app_settings WHERE key = ?", (vocab.setting_key,))
    conn.commit()
    return vocab.default_items()


def describe(
    conn: sqlite3.Connection,
    vocab: Vocabulary,
    defaults: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """给界面的整张描述：现在长什么样 + 能怎么改（中文词表**只在后端一处**）。"""
    fallback = vocab.default_items(defaults)
    return {
        "key": vocab.key,
        "title": vocab.title,
        "question": vocab.question,
        "items": [{"id": k, "label": v} for k, v in get(conn, vocab, defaults).items()],
        "defaults": [{"id": k, "label": v} for k, v in fallback.items()],
        "is_default": get(conn, vocab, defaults) == fallback,
        "allowed": list(vocab.allowed or []),
        "free_id": vocab.allowed is None,
        "max_items": vocab.max_items,
        "note": vocab.note,
    }


def report(
    conn: sqlite3.Connection,
    defaults: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    """所有词表一次给全（设置页通用渲染 —— 加新词表不用改界面）。"""
    tables = defaults or {}
    return {
        "items": [describe(conn, vocab, tables.get(vocab.key)) for vocab in ALL],
        "note": "词表只决定「能选什么 / 叫什么」，不改计算；"
                "配置文件里的默认值在这里改过之后以本机为准。",
    }
