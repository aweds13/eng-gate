"""口径开关与影子对比（SR-NF8 / N37；D 批 · T-D11）。

规格原话（`docs/specification/nonfunctional.md`）：
> 敏感改动（改基线/排序）**shadow + 一键回退**（开关默认不改变现状）。

本模块落地三件事：

1. **口径注册表**：每条"改了就该能回头"的判断写成一条 `Rule` —— 它问的问题、
   两种（或多种）做法、以及**哪个是「现状位」**。
2. **开关**：选择存 `app_settings`（与附件打开方式 / 专注白名单 / 归档天数同一套机制，
   不另造配置）。**默认位 = 现状位** —— 没写过设置就等同于"什么都没变"，
   这就是规格里「开关默认不改变现状」的字面落地。
3. **影子对比（shadow）**：拿**另一套口径**把同一份数据重算一遍，只报告"会变的地方"，
   **不改任何数据、不改任何显示** —— 先看到差异，再决定要不要切。

★ 边界（2026-09-21 用户选 B 案时一并定的口径，见 `复盘/口径定案-待定清单.md` §9）：
**只有"可重算的派生口径"能进这张表**。"天数怎么算""谁排前面""什么算基线"这类口径是
纯读的，换个算法就能重算，所以能一键回退；而 **schema 迁移 / 改状态 / 删数据**一旦落库，
旧口径**根本算不回来** —— 那些走既有的整库**备份与恢复**（`storage/backup.py`，
设置页「数据与同步」里就有），**不假装能一键回退**（把不可逆说成可回退，就是谎报）。

对比实现放**领域侧**（谁懂那套口径谁写），通过 `register_compare()` 注册进来 ——
于是加一条新口径 = 一条 `Rule` + 一个 compare 函数 + 一行注册。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import sqlite3

# `app_settings` 是通用 key/value 表（附件 / 专注 / 提醒 / 归档天数都用它），
# 口径开关靠这个前缀与它们区分 —— 将来要清理也认得出是谁写的。
SETTING_PREFIX = "behavior."

# ---- 口径 1：无截止日的 My Day 老账算不算债（F 批 · T-F8 定案 A；T-D11 的样板口径）----
KEY_DEBT_UNDATED_MYDAY = "tasks.debt_undated_myday"
VARIANT_FROM_CREATED = "from_created"
VARIANT_UNCOUNTED = "uncounted"

# 唯一允许进表的种类：**可重算的派生口径**（见模块开头的边界）。
DERIVED = "derived"


@dataclass(frozen=True)
class Variant:
    """一条口径下的一种做法。`label` 给界面看，`note` 说明它的来历。"""

    id: str
    label: str
    note: str = ""


@dataclass(frozen=True)
class Rule:
    """一条"可回退的口径"。

    `default` **必须是「现状位」**：这条口径被引入时**正在生效**的那一侧。
    对已经上线的口径（如 T-F8），现状位就是"新做法" —— 因为此刻库里跑的就是它；
    默认位若放旧做法，开关一落地就等于偷偷改了数字（那是另一种谎报）。
    新生效的口径则相反：默认放旧做法，你不切它就不变（规格里那句话的本意）。
    """

    key: str
    title: str
    question: str
    variants: tuple[Variant, ...]
    default: str
    kind: str = DERIVED

    def variant(self, variant_id: Any) -> Variant:
        """按 id 取一种做法；不认识就 ValueError（**不静默落默认值**）。"""
        if not isinstance(variant_id, str):
            raise ValueError("口径做法必须是字符串")
        for item in self.variants:
            if item.id == variant_id:
                return item
        known = "/".join(v.id for v in self.variants)
        raise ValueError(f"「{self.title}」没有这种做法：{variant_id}（只能是 {known}）")

    def other(self, current_id: str) -> Variant | None:
        """影子要跑的那一侧 = **第一个不是当前值的做法**（两条口径就是"另一侧"）。"""
        for item in self.variants:
            if item.id != current_id:
                return item
        return None


RULES: tuple[Rule, ...] = (
    Rule(
        key=KEY_DEBT_UNDATED_MYDAY,
        title="债务：无截止日的 My Day 老账",
        question="「昨天没做完、又没有截止日」的 My Day 任务，算不算一笔债？",
        variants=(
            Variant(
                VARIANT_FROM_CREATED,
                "算：天数从创建日算起",
                "现在的做法（F 批 · T-F8 定案 A：计数和明细都是它）",
            ),
            Variant(
                VARIANT_UNCOUNTED,
                "不算：不进债务卡",
                "T-F8 之前的表现（列在逾期栏里，但天数是 0）",
            ),
        ),
        default=VARIANT_FROM_CREATED,
    ),
)


@dataclass
class DiffRow:
    """影子里"会变的一处"：当前是什么、另一套口径下会变成什么。

    `current` 一律指**你现在用的那一侧**（不一定是默认位）：开关翻过之后，
    "当前"与"影子"跟着对调 —— 否则界面会把两侧说反。
    """

    label: str
    current: str
    shadow: str


# 对比实现签名：`(连接, 当前做法 id)`。第二个参数是必须的 —— 对比实现要据此决定
# 哪一侧摆在"当前"那一列（见上方 `DiffRow` 的说明）。
CompareFn = Callable[["sqlite3.Connection", str], list[DiffRow]]
_COMPARE: dict[str, CompareFn] = {}

# 影子最多报几条明细：够看清"变了什么"即可，别把界面变成表格软件。
MAX_SAMPLES = 3


# ---------------------------------------------------------------- 状态读写（app_settings）
def _get_raw(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return None if row is None else str(row["value"])


def _put_raw(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO app_settings (key, value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def _del_raw(conn: sqlite3.Connection, key: str) -> None:
    conn.execute("DELETE FROM app_settings WHERE key = ?", (key,))


def rule_by_key(key: Any) -> Rule:
    """按 key 取口径；没有这条就 ValueError（界面拿到的永远是后端原话）。"""
    if not isinstance(key, str):
        raise ValueError("口径标识必须是字符串")
    for rule in RULES:
        if rule.key == key:
            return rule
    known = "/".join(r.key for r in RULES)
    raise ValueError(f"没有这条口径：{key}（现有：{known}）")


def current_variant(conn: sqlite3.Connection, rule: Rule) -> str:
    """这条口径现在用的是哪种做法：没写过设置 = **默认位**（现状位）。

    库里的值不认识（手改过库 / 老版本留下的）时退回默认位 —— 与附件打开方式同样的处理：
    宁可跑默认口径，也不能因为一条脏设置让整个账本读不出来。
    """
    raw = _get_raw(conn, SETTING_PREFIX + rule.key)
    return raw if raw in {v.id for v in rule.variants} else rule.default


def is_default(conn: sqlite3.Connection, rule: Rule) -> bool:
    """是否还停在默认位（"没动过"）。"""
    return current_variant(conn, rule) == rule.default


def set_variant(conn: sqlite3.Connection, key: Any, variant: Any) -> Rule:
    """切换一条口径的做法。非法 key / 非法做法 → ValueError（不静默落默认值）。"""
    rule = rule_by_key(key)
    rule.variant(variant)
    _put_raw(conn, SETTING_PREFIX + rule.key, str(variant))
    conn.commit()
    return rule


def reset_variant(conn: sqlite3.Connection, key: Any) -> Rule:
    """一键回退：**删掉本机那条设置**，回到默认位（不是"把当前值再写一遍"）。

    区别是有意义的：默认位将来若变了（新版本把某条口径的现状位翻面），
    "回到默认位"会跟着走，而"写死当前值"会把人钉在旧做法上。
    """
    rule = rule_by_key(key)
    _del_raw(conn, SETTING_PREFIX + rule.key)
    conn.commit()
    return rule


# ---------------------------------------------------------------- 领域侧注册对比实现
def register_compare(key: str, fn: CompareFn) -> None:
    """登记某条口径的**影子对比**实现（在领域模块里调用，见 `tasks/manager.py`）。"""
    rule_by_key(key)  # 认不出就当场炸掉，别等界面点开才发现
    _COMPARE[key] = fn


def undated_myday_counted(conn: sqlite3.Connection) -> bool:
    """领域侧读法：无截止日的 My Day 老账**现在还计不计债**（债务卡 / 周结算 / 洞察 /
    自检都走这一条判断，所以只有一处真相）。"""
    rule = rule_by_key(KEY_DEBT_UNDATED_MYDAY)
    return current_variant(conn, rule) != VARIANT_UNCOUNTED


# ---------------------------------------------------------------- 影子对比 / 报告
def shadow(conn: sqlite3.Connection, rule: Rule) -> dict[str, Any]:
    """跑影子：拿**另一侧**的做法重算一遍，只报差异（**纯读**，不写任何东西）。"""
    current_id = current_variant(conn, rule)
    other = rule.other(current_id)
    if other is None:  # 只有一种做法的口径：没有"另一侧"可比
        return {
            "available": False,
            "variant": None,
            "label": "",
            "diff_count": 0,
            "samples": [],
            "summary": "这条口径只有一种做法，没有可对比的另一侧。",
        }
    fn = _COMPARE.get(rule.key)
    if fn is None:
        return {
            "available": False,
            "variant": other.id,
            "label": other.label,
            "diff_count": 0,
            "samples": [],
            "summary": f"「{other.label}」还没有接对比实现（影子不凭空造差异）。",
        }
    rows = fn(conn, current_id)
    samples = [{"label": r.label, "current": r.current, "shadow": r.shadow} for r in rows]
    if not rows:
        summary = f"影子跑「{other.label}」：没有区别（切过去数字不变）。"
    else:
        head = f"影子跑「{other.label}」：{len(rows)} 处不同"
        more = f"，下面列前 {len(samples)} 条" if len(samples) > MAX_SAMPLES else ""
        summary = head + more + "。"
    return {
        "available": True,
        "variant": other.id,
        "label": other.label,
        "diff_count": len(rows),
        "samples": samples[:MAX_SAMPLES],
        "summary": summary,
    }


def report(conn: sqlite3.Connection) -> dict[str, Any]:
    """给设置页的整表：每条口径的当前做法 / 默认位 / 可选做法 / 影子差异。"""
    items: list[dict[str, Any]] = []
    for rule in RULES:
        current_id = current_variant(conn, rule)
        current = rule.variant(current_id)
        items.append(
            {
                "key": rule.key,
                "title": rule.title,
                "question": rule.question,
                "kind": rule.kind,
                "current": current_id,
                "current_label": current.label,
                "current_note": current.note,
                "default": rule.default,
                "is_default": current_id == rule.default,
                "variants": [
                    {
                        "id": v.id,
                        "label": v.label,
                        "note": v.note,
                        "is_default": v.id == rule.default,
                    }
                    for v in rule.variants
                ],
                "shadow": shadow(conn, rule),
            }
        )
    return {
        "items": items,
        "max_samples": MAX_SAMPLES,
        "note": "这里只有**可重算的派生口径**（天数怎么算、谁排前面这类）：换一套算法重算一遍就行，"
                "所以能一键回退。**改数据的事**（换 schema、改状态、删东西）旧口径算不回来 —— "
                "那些走上面的「备份与恢复」，不假装能一键回退。",
        "switch_note": "开关默认停在**现状位**（没动过 = 什么都没变）；"
                       "「影子」只是拿另一套口径**试算**，不改任何数据、也不改你现在看到的数字。",
    }
