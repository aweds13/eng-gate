"""学校通知的**合作接口**（SR-F10.1 / G 批 · T-G14）。

**规格要什么**（`docs/specification/domains/F10-notify.md`，原文是"后置，不阻塞第一版"）：
> 学校通知监测（网站/公众号/群聊/考试网站 → 抓取/集成/通知）由**独立脚本/软件**实现。
> 主工具只提供**合作接口**，不让主软件膨胀。……主工具**不直接抓取**外部网站；
> 不新增对用户数据的外部依赖。……外部监测结果可通过合作接口转成任务/提醒（只读或新增，待定）。
> 外部脚本不可用：主工具不崩、不报错；只提示未接入。非法/重复通知：去重、来源标记。
> 接口契约未定：字段保持扩展位，不写死。

**这一版做了什么、没做什么**（用户 2026-09-23「全做」把这件后置项提前，判断都在这里写清）：

- 做：**收件箱**（`school_notices`，schema v18）+ 投递接口 + 去重 + 来源标记 + 看
  + **转成任务/提醒**；
- 不做：**抓取**。主工具不会去连学校网站 —— 规格把它划给独立脚本，主工具越界抓取
  就等于"新增对外依赖 + 帮用户做了他没同意的事"。设置页里那句实话就是"我们不去网上拿"。
- **"只读或新增，待定"怎么定的**：投递进来的通知先只**落在收件箱**（等于"新增"这个动作由脚本做，
  主工具只接收）；**转成任务/提醒是你点一下才发生**（`to_task`），不是自动建。
  理由：自动把外部内容变成你的任务清单，是在替你决定"什么算我的事"——那是产品口径，
  这一版不擅自定（要点一下才转，人始终在环里）。
- **默认关**（口径同 N16「默认收严、用户再放宽」，与 AI 接口一致）：不开时投递接口一律 403 带原话，
  界面显示"未接入"。外部脚本没跑起来时主工具什么都不做 —— 不报错、不轮询、不崩。
- **去重靠数据库**：`fingerprint` 唯一索引（同一来源同一条只留一行；带了 `external_id` 的按它算）。
  重复投递不算错，返回 `duplicate=True`；内容变了就**更新那一行**（同一个来源的那条通知改标题了）。
- **接口扩展位**：认不出来的多余字段存进 `extra`（JSON），**不丢、也不写死**。

字段约定（认得的这些）：
`source`（来源标记，必填）、`title`（必填）、`external_id`（对方系统的 id，可选，给了就去重更准）、
`url`、`summary`、`at`（通知时间）、`due_date`（通知里说的截止）、`remind_at`（转任务时用）。
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import date
from typing import TYPE_CHECKING, Any, cast

from timeflow import clock

if TYPE_CHECKING:
    import sqlite3

# 设置键（`app_settings` 通用表，与 AI/附件/专注/导出同一处）
KEY_ENABLED = "notify.school_enabled"

DEFAULT_ENABLED = False

# 收件箱里一条通知的三种状态
STATUS_NEW = "new"
STATUS_CONVERTED = "converted"
STATUS_IGNORED = "ignored"
STATUSES: tuple[str, ...] = (STATUS_NEW, STATUS_CONVERTED, STATUS_IGNORED)
STATUS_LABELS: dict[str, str] = {
    STATUS_NEW: "待看",
    STATUS_CONVERTED: "已转任务",
    STATUS_IGNORED: "已忽略",
}

# 认得的字段（其余进 `extra`）；顺序固定，界面与文档按它列
KNOWN_FIELDS: tuple[str, ...] = (
    "source", "external_id", "title", "url", "summary", "at", "due_date",
)

# 长度上限（防呆，不是安全边界）：外部脚本塞一条 10MB 的正文进来，界面与库都会难受
MAX_LEN: dict[str, int] = {
    "source": 80, "external_id": 200, "title": 300, "url": 2000, "summary": 4000,
}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?$")

# 这一版对外**明确提供**的动作（写给界面与脚本看）
SURFACE: tuple[tuple[str, str, str], ...] = (
    ("GET", "/api/settings/notify", "看这个接口开着没有、认哪些字段（不读你的数据）"),
    ("PUT", "/api/settings/notify", "打开/关闭（默认关）"),
    ("GET", "/api/notify/school", "读收件箱（可选 status / limit）"),
    ("POST", "/api/notify/school", "投递一条通知（脚本用；重复投递只会更新同一行）"),
    ("POST", "/api/notify/school/{id}/to-task", "把某条通知转成任务（你点一下才发生）"),
    ("POST", "/api/notify/school/{id}/ignore", "把某条通知标成已忽略（可再改回待看）"),
)

BOUNDARY = (
    "主工具**不去网上抓**：监测由你自己的独立脚本做，这里只是**收件箱**。"
    "投递进来的通知**不会自动变成任务** —— 转任务/提醒要你点一下（人始终在环里）。"
    "**默认关**：不开时投递接口一律 403。"
)

WHY = (
    "为什么这么做：规格把抓取划给独立脚本，主工具越界抓取等于替你新增对外依赖；"
    "而\"外部内容自动变任务\"会替你决定什么算你的事 —— 那是产品口径，这一版不擅自定。"
)

EXAMPLE = (
    "# 先看接口开着没有（不读你的数据）\n"
    "curl http://127.0.0.1:8000/api/settings/notify\n"
    "# 投递一条通知（脚本里就这么调；重复投递不会产生第二行）\n"
    "curl -X POST http://127.0.0.1:8000/api/notify/school \\\n"
    '  -H "Content-Type: application/json" \\\n'
    '  -d \'{"source":"教务处网站","external_id":"2026-0917-01",'
    '"title":"期中考试安排已发布","url":"https://example.edu/x",'
    '"at":"2026-09-17T09:30","due_date":"2026-10-08"}\'\n'
    "# 把某条转成任务（也可以先到界面上看一眼再点）\n"
    "curl -X POST http://127.0.0.1:8000/api/notify/school/<通知id>/to-task \\\n"
    '  -H "Content-Type: application/json" -d \'{"is_myday":true}\''
)


def _uid() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> str:
    return clock.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------- 开关（默认关）
def _get_raw(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return None if row is None else str(row["value"])


def _put_raw(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO app_settings (key, value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def enabled(conn: sqlite3.Connection, default: bool = DEFAULT_ENABLED) -> bool:
    """合作接口开着吗（本机设置 → **默认关**）。"""
    raw = _get_raw(conn, KEY_ENABLED)
    if raw is None:
        return bool(default)
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def set_enabled(
    conn: sqlite3.Connection, value: object, default: bool = DEFAULT_ENABLED
) -> dict[str, Any]:
    """打开/关闭。**不猜**：只认布尔（`true/false`、`1/0`、`"on"/"off"`），其它一律拒绝。"""
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        on = True
    elif text in {"0", "false", "no", "off", ""}:
        on = False
    else:
        raise ValueError(f"学校通知开关只认 true/false：{value!r}")
    _put_raw(conn, KEY_ENABLED, "true" if on else "false")
    conn.commit()
    return describe(conn, default)


class NotConnectedError(ValueError):
    """**没接入**（开关关着）：与"参数写错了"分开 —— API 层据此回 403 而不是 400。

    为什么值得一个专门的类型：调这个接口的是**外部脚本**，"你还没打开这个开关"和
    "你少传了 source"是两件完全不同的事（一个要用户去点开关，一个要脚本改代码），
    靠字符串去猜这两种情况迟早会错。
    """


def require_enabled(conn: sqlite3.Connection, default: bool = DEFAULT_ENABLED) -> None:
    """没开就拒绝（带原话）。外部脚本**没接入**时主工具什么都不做 —— 这是"未接入"，不是故障。"""
    if enabled(conn, default):
        return
    raise NotConnectedError(
        "学校通知的合作接口默认是**关**的：请先在设置页「学校通知」里打开（默认收严，同 AI 接口）。"
        "没接入时主工具什么都不做 —— 不会去网上抓，也不会报错。"
    )


# ---------------------------------------------------------------- 字段校验
def _text(value: object, field: str, *, required: bool = False) -> str | None:
    """把字段规整成"非空字符串或 None"，并挡掉超长（带上限与字段名，不静默截断）。"""
    if value is None:
        if required:
            raise ValueError(f"缺少必填字段：{field}")
        return None
    text = str(value).strip()
    if not text:
        if required:
            raise ValueError(f"必填字段不能为空：{field}")
        return None
    limit = MAX_LEN.get(field)
    if limit is not None and len(text) > limit:
        raise ValueError(f"字段 {field} 太长了（{len(text)} 字，上限 {limit}）")
    return text


def _moment(value: object, field: str) -> str | None:
    """日期/时间一律**本地日历**（`specification/behaviors.md`：日界 00:00），存 `YYYY-MM-DD`
    或 `YYYY-MM-DDTHH:MM(:SS)`；非法值**拒绝**（不猜、不静默丢）。

    **日期要真的是日期**：只对 `\\d{4}-\\d{2}-\\d{2}` 做形状匹配会放过 `2026-13-40`
    （形状对、日子不存在），所以这里真解析一次 —— 外部脚本送来的脏数据必须当场被拦住。
    """
    text = _text(value, field)
    if text is None:
        return None
    m = _TIME_RE.match(text)
    if m:
        hour, minute, second = int(m.group(2)), int(m.group(3)), m.group(4) or "00"
        if hour > 23 or minute > 59 or int(second) > 59:
            raise ValueError(f"字段 {field} 的时间不合法：{text}")
        _real_date(m.group(1), field, text)
        return f"{m.group(1)}T{hour:02d}:{minute:02d}:{second}"
    if _DATE_RE.match(text):
        _real_date(text, field, text)
        return text
    raise ValueError(
        f"字段 {field} 的日期格式不对：{text}（要 2026-09-17 或 2026-09-17T09:30）"
    )


def _real_date(text: str, field: str, raw: str) -> None:
    try:
        date.fromisoformat(text)
    except ValueError:
        raise ValueError(f"字段 {field} 的日期不存在：{raw}") from None


def _url(value: object) -> str | None:
    text = _text(value, "url")
    if text is None:
        return None
    if not text.lower().startswith(("http://", "https://")):
        raise ValueError(f"url 只收 http/https 链接：{text}")
    return text


def fingerprint(source: str, external_id: str | None, title: str, at: str | None) -> str:
    """去重指纹。

    给了 `external_id` 就按 `来源 + 那条 id` 算 —— 它是"对方系统里的那一条"，
    标题改了也还是同一条（内容变化走**更新**，不新增一行）；
    没给就退化成 `来源 + 标题 + 通知时间` 的哈希（同一来源里标题与时间都相同 → 视为同一条）。
    """
    key = (
        f"{source.casefold()}|{external_id}"
        if external_id
        else f"{source.casefold()}|{title}|{at or ''}"
    )
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]


# ---------------------------------------------------------------- 投递（收件箱）
def receive(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
    *,
    default_enabled: bool = DEFAULT_ENABLED,
) -> dict[str, Any]:
    """接一条通知进收件箱（外部脚本调 `POST /api/notify/school` 就是走这里）。

    返回值：`{id, created, duplicate, updated, notice}` —— **三种情况都说清**：
    新收下（`created=True`）、重复投递但内容没变（`duplicate=True`）、
    重复投递且内容变了（`duplicate=True, updated=True`，更新的是同一行）。

    规矩：
    - `source` 与 `title` 必填；开关没开直接拒绝（带原话）；
    - 多余字段进 `extra` 不丢；
    - **重复投递只覆盖"这次真的带了"的字段** —— 脚本再投一次只带标题，不会把上次的
      链接/摘要/截止日**抹成空**（那是数据丢失，不是更新）。
    """
    require_enabled(conn, default_enabled)
    present = {k: payload[k] for k in KNOWN_FIELDS if k in payload}
    source = _text(present.get("source"), "source", required=True)
    title = _text(present.get("title"), "title", required=True)
    external_id = _text(present.get("external_id"), "external_id")
    assert source is not None and title is not None  # required=True 已保证
    url = _url(present.get("url")) if "url" in present else None
    summary = _text(present.get("summary"), "summary") if "summary" in present else None
    at = _moment(present.get("at"), "at") if "at" in present else None
    due_date = _moment(present.get("due_date"), "due_date") if "due_date" in present else None
    extra = {k: v for k, v in payload.items() if k not in KNOWN_FIELDS}
    fp = fingerprint(source, external_id, title, at)
    existing = conn.execute(
        "SELECT * FROM school_notices WHERE fingerprint = ?", (fp,)
    ).fetchone()
    if existing is not None:
        candidate: dict[str, Any] = {
            "title": title, "url": url, "summary": summary, "at": at, "due_date": due_date,
        }
        changes = {k: v for k, v in candidate.items() if k in present}
        changed = any((changes[k] or None) != (existing[k] or None) for k in changes)
        if changed or extra:
            merged_extra = {**(_json(existing["extra"]) or {}), **extra}
            sets = ", ".join(f"{k} = ?" for k in changes)
            params: list[Any] = [changes[k] for k in changes]
            if merged_extra:  # extra 是"合并"（新字段补进去，旧字段不丢）
                sets += ", extra = ?"
                params.append(json.dumps(merged_extra, ensure_ascii=False))
            conn.execute(
                f"UPDATE school_notices SET {sets}, updated_at = ? WHERE id = ?",
                (*params, _now(), existing["id"]),
            )
            conn.commit()
        return {
            "id": str(existing["id"]),
            "created": False,
            "duplicate": True,
            "updated": changed,
            "notice": _row(_find(conn, str(existing["id"]))),
        }
    notice_id = _uid()
    conn.execute(
        "INSERT INTO school_notices (id, source, external_id, fingerprint, title, url, summary, "
        "at, due_date, received_at, status, task_id, extra, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            notice_id, source, external_id, fp, title, url, summary, at, due_date, _now(),
            STATUS_NEW, None, json.dumps(extra, ensure_ascii=False) if extra else None, _now(),
        ),
    )
    conn.commit()
    return {
        "id": notice_id,
        "created": True,
        "duplicate": False,
        "updated": False,
        "notice": _row(_find(conn, notice_id)),
    }


def _json(text: object) -> dict[str, Any] | None:
    if not text:
        return None
    try:
        got = json.loads(str(text))
    except (ValueError, TypeError):
        return None
    return got if isinstance(got, dict) else None


def _find(conn: sqlite3.Connection, notice_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM school_notices WHERE id = ?", (notice_id,)).fetchone()
    if row is None:
        raise KeyError(f"通知不存在: {notice_id}")
    return cast("sqlite3.Row", row)


def _row(r: sqlite3.Row) -> dict[str, Any]:
    """一条通知 → 给界面的字典（`extra` 解成 dict，认不出的字段也照原样带出去）。"""
    return {
        "id": str(r["id"]),
        "source": r["source"],
        "external_id": r["external_id"],
        "title": r["title"],
        "url": r["url"],
        "summary": r["summary"],
        "at": r["at"],
        "due_date": r["due_date"],
        "received_at": r["received_at"],
        "status": r["status"],
        "status_label": STATUS_LABELS.get(str(r["status"]), str(r["status"])),
        "task_id": r["task_id"],
        "extra": _json(r["extra"]) or {},
    }


def notices(
    conn: sqlite3.Connection, *, status: str | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    """收件箱列表（新的在前）。`status` 只认三种（非法值拒绝，不静默当全部）。"""
    if status is not None and status not in STATUSES:
        raise ValueError(f"非法状态: {status}（能用的：{'/'.join(STATUSES)}）")
    if limit < 1 or limit > 1000:
        raise ValueError(f"limit 超出范围（1~1000）：{limit}")
    sql = "SELECT * FROM school_notices"
    params: list[Any] = []
    if status:
        sql += " WHERE status = ?"
        params.append(status)
    sql += " ORDER BY received_at DESC, rowid DESC LIMIT ?"
    params.append(int(limit))
    return [_row(r) for r in conn.execute(sql, tuple(params)).fetchall()]


def to_task(
    conn: sqlite3.Connection,
    notice_id: str,
    *,
    is_myday: bool = False,
    remind_at: str | None = None,
    due_date: str | None = None,
    priority: str | None = None,
) -> dict[str, Any]:
    """把一条通知**转成任务**（F10「外部监测结果可通过合作接口转成任务/提醒」）。

    - **人点一下才发生**（不是投递就自动建任务）：外部内容要不要变成你的事，由你决定；
    - 走的是**和人手建任务完全相同**的路径（`tasks.create_task`：校验、去重、状态都一致），
      所以"通知转来的任务"在别处看起来就是一条普通任务 —— 不搞两套；
    - 转完记 `status=converted` + `task_id`（弱关联，删任务不连坐通知）；
    - **幂等**：已经转过的再点一次，返回同一个任务并 `created=False`（不会越点越多）——
      这条路上**不再看这次传的参数**（任务已经建好了；要改就去改那条任务）；
    - `due_date` 默认用通知里带的那个（没传就取通知的 `due_date`）—— 通知说了截止日就用它。
    """
    from timeflow.core import tasks as tm

    row = _find(conn, notice_id)  # 不存在 → KeyError
    if row["status"] == STATUS_CONVERTED and row["task_id"]:
        task_id = str(row["task_id"])
        existing = conn.execute("SELECT 1 FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if existing is not None:
            return {"task_id": task_id, "created": False, "notice": _row(row)}
        # 任务被彻底删掉了 → 允许重新转（否则这条通知就永远转不出任务了）
    # **转任务不要求接口开着**：开关管的是"外部脚本能不能投递"，收件箱里收到的东西
    # 已经是你的数据了 —— 关掉接口不应该让你连自己的收件箱都处理不了。
    task = tm.create_task(
        conn,
        str(row["title"]),
        due_date=due_date or (str(row["due_date"]) if row["due_date"] else None),
        is_myday=bool(is_myday),
        note=_task_note(row),
        remind_at=remind_at,
        priority=priority if priority is not None else tm.DEFAULT_PRIORITY,
    )
    conn.execute(
        "UPDATE school_notices SET status=?, task_id=?, updated_at=? WHERE id=?",
        (STATUS_CONVERTED, task.id, _now(), notice_id),
    )
    conn.commit()
    return {"task_id": task.id, "created": True, "notice": _row(_find(conn, notice_id))}


def _task_note(row: sqlite3.Row) -> str:
    """转出来的任务要**看得出从哪来**（来源 + 原文链接 + 通知时间），否则以后没人知道它是哪来的。"""
    bits = [f"来自学校通知：{row['source']}"]
    if row["at"]:
        bits.append(f"通知时间 {row['at']}")
    if row["url"]:
        bits.append(str(row["url"]))
    if row["summary"]:
        bits.append(str(row["summary"]))
    return " · ".join(bits)


def ignore(
    conn: sqlite3.Connection,
    notice_id: str,
    *,
    ignored: bool = True,
) -> dict[str, Any]:
    """标成已忽略 / 再改回待看（**不删行**：删了下次投递又回来，反而像"没收到过"）。

    已转成任务的不动（否则任务还挂着、通知却说自己被忽略了 —— 两处说法打架）。
    与 `to_task` 同理：**不要求接口开着**（收件箱里的东西是你的数据）。
    """
    row = _find(conn, notice_id)
    if row["status"] == STATUS_CONVERTED:
        raise ValueError("这条已经转成任务了 —— 要处理就去任务那边（通知这里只标状态）")
    conn.execute(
        "UPDATE school_notices SET status=?, updated_at=? WHERE id=?",
        (STATUS_IGNORED if ignored else STATUS_NEW, _now(), notice_id),
    )
    conn.commit()
    return _row(_find(conn, notice_id))


def describe(
    conn: sqlite3.Connection, default: bool = DEFAULT_ENABLED
) -> dict[str, Any]:
    """设置页与脚本共用的自述（说明由后端给，界面与文档都不复述规则）。"""
    rows = conn.execute(
        "SELECT status, COUNT(*) AS n FROM school_notices GROUP BY status"
    ).fetchall()
    counts = {s: 0 for s in STATUSES}
    for r in rows:
        key = str(r["status"])
        if key in counts:
            counts[key] = int(r["n"])
    total = conn.execute("SELECT COUNT(*) AS n FROM school_notices").fetchone()
    return {
        "enabled": enabled(conn, default),
        "default_enabled": bool(default),
        "configured": _get_raw(conn, KEY_ENABLED) is not None,
        "surface": [{"method": m, "path": p, "what": w} for m, p, w in SURFACE],
        "fields": [
            {"name": "source", "required": True, "what": "来源标记（哪个网站/群）"},
            {"name": "title", "required": True, "what": "标题（任务就用它当标题）"},
            {"name": "external_id", "required": False, "what": "对方系统的 id（给了去重更准）"},
            {"name": "url", "required": False, "what": "原文链接（http/https）"},
            {"name": "summary", "required": False, "what": "摘要（转任务时进备注）"},
            {"name": "at", "required": False, "what": "通知时间（2026-09-17 或 2026-09-17T09:30）"},
            {"name": "due_date", "required": False, "what": "通知里说的截止（转任务时用它）"},
            {"name": "(其它)", "required": False, "what": "不认识的字段会原样存下来，不丢"},
        ],
        "statuses": [
            {"value": s, "label": STATUS_LABELS[s], "count": counts[s]} for s in STATUSES
        ],
        "total": int(total["n"]) if total else 0,
        "boundary": BOUNDARY,
        "why": WHY,
        "example": EXAMPLE,
        "note": "监测由**你自己的脚本**做，这里只是收件箱：投递进来不会自动建任务，"
                "转任务要你点一下。默认关，没接入时主工具什么都不做（不抓取、不报错）；"
                "关掉接口不影响你处理收件箱里已有的通知。",
    }
