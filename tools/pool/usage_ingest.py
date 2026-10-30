r"""外部用量上报：整批校验 + `rid` 幂等 + 上报行不计入限额（卡 A347 · 台账号 T-AG550）。

**移植自** magpie `usage_ingest.go` 与 `reported.go`（设计原件 `## F43` 一节，逐行对齐）。

要解决的问题：**不经过派活器的调用，今天完全不进账。** `gates/diag/wb-usage.jsonl` 只由
`tools/wb_dispatch.py` 的 `append_usage_line()` 在派活收工时写，于是有人直接拿供应商的 key
调一次模型，那笔 token 一个字节都没有。本模块给出「收外部记录」的判据层。

★ 三条边界（如实写，别当承诺读）：

  ① **入口是函数，不是 HTTP。** magpie 的入口是 `POST /v1/magpie/usage/requests`；pool 没有
     HTTP 面，所以入口是 `ingest(text, now=…, root=…)` 这个纯函数（body 由调用方读成 `str`
     交进来）。⇒ 属于传输层的那三条判据 —— 415（Content-Type 不是 `application/json`）、
     413（HTTP 体超 32 MiB，由 `http.MaxBytesReader` 掐）、403（浏览器页无 key / key 被限额住）——
     **未落地，仅设计**。本模块只保留其中与传输无关的那一半：「字节数超 32 MiB」（`MAX_BODY`），
     在 `parse_batch()` 里对 `text` 的 UTF-8 字节数自己量一次。
  ② **上报行进 `gates/diag/usage-reported.jsonl`，不进 `gates/diag/wb-usage.jsonl`。**
     后者是**派活器自己写的**账：`tools/pool/jobs.py:250` 的 `USAGE_LOG_RE` 按名字认它、
     `tools/wt_prune.py:514` 按「累积台账，逐行追加合并、绝不许覆盖」修剪它。混进去之后
     「这一行是派活器写的还是外面报的」就永久不可判 —— 而 magpie 的设计核心恰恰是
     `source: "reported"` **单列**。所以另开一本，读端用 `merged_tokens()` 合并。
  ③ **本模块不算钱。** pool 里没有价目表（`tools/wb_dispatch.py::usage_in()` 已如实写「金额恒
     0.0」），上报方给的 `cost` 原样存、不重定价、也不参与任何判据。为了对齐 magpie 而内置一份
     单价常量 = 在仓里埋一个会过期的外部事实，本模块不做。

★ 与 magpie 的另外几处**有意分歧**（都是「没有那一层」造成的，逐条写清）：

  · magpie 的 `parseIngest`（`usage_ingest.go:189`）**遇到第一条坏记录就返回**；本模块按卡规格
    把**每条**记录的判据都跑完再一起抛（`IngestRefused.faults` 是 `list[Fault]`），因为纯函数
    没有「一次请求一次回包」的约束，攒全了更好定位。单条记录内部仍然只报**第一条**违规
    （顺序即优先级，照 `usage_ingest.go:200 parseReported`）。
  · JSON 解不开（`[` 或 `{` 开头但内容坏）时用 `"send a JSON record, or an array of them"` 这句，
    不搬 magpie 的 `"not a JSON array of records: " + err`：卡规格判据 3 只给了这一句，不另造文案。
  · `t` 不是字符串（例如给了数字）时也用 `"must be an RFC 3339 time (2026-10-13T08:00:00Z)"`，
    不搬 magpie 的 `"must be an RFC 3339 time, as a string"` —— 同理，判据表里只有前一句。
  · 表外字段的文案按卡规格判据表取 `"is not a field a call has"`（magpie 原文更长，带字段清单）。
  · **不做浏览器页 / heldKey 这两条准入**：pool 既没有浏览器面读用量，也没有 key 级限额面。
  · **`rid` 去重不建索引文件**：每次从日志本身读回（`reported.go:37 catchUpReported` 的原设计），
    也没有 magpie 的 `info`/`off` 增量位点 —— 本卡不做增量，见 `_known_rids()` 的 docstring。
  · **不加锁**：magpie 的两段式是在网关的 `mu` 里做的；pool 本卡不引第三种锁，
    并发下两条同 `rid` 的批可能都写进去（如实记在缺口里，不假装解决了）。

★ **本卡零接线**：`tools/wb_dispatch.py` 一个字节都没改。`merged_tokens()` 今天**零生产调用方**，
`usage_in()` 还没有 `include_reported` 参数 —— 那是下一张卡。
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Any

#: 仓库根（`tools/pool/usage_ingest.py` 往上三层）。测试一律显式给 `root=`，不靠它。
TOOL_ROOT = Path(__file__).resolve().parent.parent.parent

#: 上报账位址（相对 `root`）。★ 另开一本，**不改** `wb-usage.jsonl` 的形状（它有三个读者）。
REPORTED_REL: tuple[str, ...] = ("gates", "diag", "usage-reported.jsonl")

#: 覆写上报账位置的 env（照 `tools/pool/sink.py` 的 `ENV_SINK` 同一手法）。
ENV_REPORTED = "TF_POOL_REPORTED"

#: ★ 以下九个常量**逐字**抄 magpie，数值一个不许改；行号是 magpie 源码里的行号。
MAX_BODY = 32 << 20            # :46 ingestMaxBody —— 一批的字节上限（32 MiB）
MAX_RECORDS = 5000             # :50 ingestMaxRecords —— 一次最多几条
MAX_TOKENS = 100_000_000       # :53 ingestMaxTokens —— 任何一个 token 数的上限
MAX_MILLIS = 86_400_000        # :55 ingestMaxMillis = int64(24h / ms) —— 一次调用最久多久
MAX_COST = 10_000.0            # :57 ingestMaxCost —— 一次调用最多花多少 USD
MAX_TEXT = 256                 # :60 ingestMaxText —— 名字类字段最长多少（`err` 例外）
FUTURE_S = 3600                # :63 ingestFuture = time.Hour —— 调用时间最多超前多久
#: :69 var ingestEarliest = time.Date(2000, 1, 1, 0, 0, 0, 0, time.UTC)
#: 早于它的只可能是打错的年份（补录历史时间本身是**允许**的，见 `usage_ingest.go:66-69`）。
EARLIEST = datetime(2000, 1, 1, tzinfo=timezone.utc)

#: :77 ingestFields —— 20 个字段，**任何**表外字段 ⇒ 整包拒。
FIELDS: tuple[str, ...] = (
    "t", "agent", "provider", "model", "in", "out", "cache_read",
    "cache_write", "cache_write_1h", "reasoning", "ms", "ttft_ms",
    "first_text_ms", "flow_ms", "status", "rid", "cost", "effort",
    "session", "err",
)

#: 必填的字符串字段。逐字照 `usage_ingest.go:265-276`（还有 `status`，它走整数、单独校验）。
REQUIRED_TEXT: tuple[str, ...] = ("rid", "agent", "provider", "model")

#: 六个计数栏位。逐字照 `usage_ingest.go:308-318`。
COUNTS: tuple[str, ...] = ("in", "out", "cache_read", "cache_write", "cache_write_1h", "reasoning")

#: 四个毫秒栏位。逐字照 `usage_ingest.go:322-351`。
MILLIS: tuple[str, ...] = ("ms", "ttft_ms", "first_text_ms", "flow_ms")

#: 来源标记的取值。逐字照 magpie `ledger.go:99 SourceReported = "reported"`。
SOURCE_REPORTED = "reported"

#: ★ 落盘行的 `source` 与扫描用的字节标记**同一个常量**生成，不许两处各写一遍字符串。
#: 照 `reported.go:31 reportedMark`：先按字节找标记再 parse（日志会长到几十万行，
#: 「这一行是不是上报行」一个子串就够判，不用整份 unmarshal）。空格口径与 `json.dumps` 的默认一致。
REPORTED_MARK = f'"source": "{SOURCE_REPORTED}"'

#: `wb-usage.jsonl` 的时区：`+08:00` 钉死，与 `tools/wb_dispatch.py::usage_in()` 同一条。
USAGE_TZ = timezone(timedelta(hours=8))

#: RFC 3339 —— magpie 用 `time.Parse(time.RFC3339Nano, …)`，它**要求**带偏移量或 `Z`。
#: `datetime.fromisoformat` 比它宽松（吃 `2026-10-13` 与裸本地时间），所以先过一遍这个正则。
_RFC3339_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})$"
)


@dataclass(frozen=True)
class Fault:
    """一条坏记录的定位 —— 逐字照 magpie 的 `type ingestFault struct`（三个字段：
    `index` / `field` / `msg`）。

    `index = -1` 表示「整包」级错误（空数组、超 5000 条、body 不是记录也不像数组、超 32 MiB），
    此时错误体**不带** `index` 键（照 `usage_ingest.go:130-134`）。
    """

    index: int
    field: str
    msg: str

    def error_text(self) -> str:
        """逐字照 `func (f *ingestFault) Error() string`（`usage_ingest.go:86`）。"""
        if self.index < 0:
            return f"{self.field}: {self.msg}"
        return f"record {self.index}: {self.field}: {self.msg}"


class IngestRefusedError(Exception):
    """整包拒。`faults` 非空，且**目标文件一个字节都没写**（照 `tools/pool_accounts.py:867`）。"""

    def __init__(self, faults: list[Fault]) -> None:
        self.faults: list[Fault] = faults
        super().__init__("; ".join(f.error_text() for f in faults))


#: 卡规格逐字点名的公开名（「抛 `IngestRefused(faults)`」）—— 调用方照这个名字抓异常。
#:
#: ★ 本名**带** `Error` 后缀是被 ruff `N818` 逼的（异常名必须带 `Error` 后缀），而卡规格同时
#:   不许加豁免注释、又把 `IngestRefused` 写进了判据表 ⇒ 三条约束不可能同时满足。取的路子是
#:   「本名合规 + 别名保留判据名」：判据里点名的 `IngestRefused` 仍然逐字可用（`raise` 与
#:   `pytest.raises` 都照它写），告警也不是被豁免注释蒙掉的。**行为完全相同**，只有一个名字。
IngestRefused = IngestRefusedError


def reported_path(root: Path | str | None = None) -> Path:
    """上报账位址：`TF_POOL_REPORTED` 覆盖 > `root` 下 `gates/diag/usage-reported.jsonl`。"""
    override = os.environ.get(ENV_REPORTED, "").strip()
    if override:
        return Path(override).expanduser()
    base = Path(root) if root is not None else TOOL_ROOT
    return base.joinpath(*REPORTED_REL)


# ============================================ 整批解析 + 全量校验（先校验，一个字节都不写）

def parse_batch(text: str, *, now: datetime) -> list[dict[str, Any]]:
    """解析 + **全量**校验。任何一条坏 ⇒ 抛 `IngestRefused`，调用方一个字节都不许写。

    逐字照 `usage_ingest.go:168 parseIngest`：trim 后看首字节 —— `[` 走数组、`{` 走单条、
    其余 ⇒ `"send a JSON record, or an array of them"`。空数组、超 `MAX_RECORDS` 条、
    超 `MAX_BODY` 字节都是**整包级**错误（`index = -1`）。

    ★ `now` 必须显式给（测试注入固定值）—— 本模块**不读系统钟**，否则「未来 1 小时」那条判据
      在测试里就是一条会随真实时间漂的断言。
    """
    raw = text.strip()
    if not raw:
        raise IngestRefused([Fault(-1, "body", "send a JSON record, or an array of them")])
    if len(raw.encode("utf-8")) > MAX_BODY:
        # magpie 由 http.MaxBytesReader 在 HTTP 层掐（:118-123），pool 没有传输层 ⇒ 这里自己量。
        raise IngestRefused([Fault(-1, "body", f"the body is over {MAX_BODY} bytes: "
                                              f"send at most {MAX_RECORDS} records a post")])
    head = raw[0]
    if head == "[":
        try:
            raws = json.loads(raw)
        except json.JSONDecodeError:
            raise IngestRefused(
                [Fault(-1, "body", "send a JSON record, or an array of them")]
            ) from None
        if not isinstance(raws, list):
            raise IngestRefused([Fault(-1, "body", "send a JSON record, or an array of them")])
        items: list[Any] = raws
        if not items:
            raise IngestRefused([Fault(-1, "body", "the array has no records")])
        if len(items) > MAX_RECORDS:
            raise IngestRefused([Fault(-1, "body",
                                       f"{len(items)} records: send at most {MAX_RECORDS} a post")])
    elif head == "{":
        try:
            one = json.loads(raw)
        except json.JSONDecodeError:
            raise IngestRefused(
                [Fault(-1, "body", "send a JSON record, or an array of them")]
            ) from None
        items = [one]
    else:
        raise IngestRefused([Fault(-1, "body", "send a JSON record, or an array of them")])

    out: list[dict[str, Any]] = []
    faults: list[Fault] = []
    for index, one in enumerate(items):
        row, fault = _parse_one(index, one, now=now)
        if fault is not None:
            faults.append(fault)
            continue
        out.append(cast("dict[str, Any]", row))
    if faults:  # ★ 全有或全无：一条坏 ⇒ 整包拒，且**在写之前**
        raise IngestRefused(faults)
    return out


def _rune_count(text: str) -> int:
    """Go 的 `utf8.RuneCountInString` —— Python 的 `str` 已是码点序列，`len` 同义。"""
    return len(text)


def _has_control(text: str) -> bool:
    """含 `< 0x20` 或 `0x7f`。逐字照 `usage_ingest.go:234`。"""
    return any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in text)


def _text_field(
    fields: dict[str, Any], key: str, index: int, *, need: bool
) -> tuple[str, Fault | None]:
    """字符串字段——逐字照 `usage_ingest.go:216-238` 的 `text(k, need)` 闭包。

    ★ `err` 是唯一两个例外的字段：不校 256 字符、不校控制字符
      （照 `:232` / `:234` 的 `k != "err"`）。
    """
    if key not in fields or fields[key] is None:
        if need:
            return "", Fault(index, key, "required")
        return "", None
    value = fields[key]
    if not isinstance(value, str):
        return "", Fault(index, key, "must be a string")
    trimmed = value.strip()
    if need and trimmed == "":
        return "", Fault(index, key, "required")
    if key != "err" and _rune_count(trimmed) > MAX_TEXT:
        return "", Fault(index, key, f"longer than {MAX_TEXT} characters")
    if key != "err" and _has_control(trimmed):
        return "", Fault(index, key, "has a control character")
    return trimmed, None


def _whole_field(
    fields: dict[str, Any], key: str, index: int, *, top: int, need: bool
) -> tuple[int, Fault | None]:
    """整数栏位——逐字照 `usage_ingest.go:239-263` 的 `whole(k, max, need)` 闭包。"""
    if key not in fields or fields[key] is None:
        if need:
            return 0, Fault(index, key, "required")
        return 0, None
    value = fields[key]
    if isinstance(value, str):
        # 带引号的数：Go 的 `json.Number` 也吃 `"5"`，所以 `:249` 先看 `v[0] == '"'`。
        return 0, Fault(index, key, "must be a number")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0, Fault(index, key, "must be a number")
    number = float(value) if isinstance(value, float) else value
    if isinstance(number, float):
        if not number.is_integer():
            return 0, Fault(index, key, "must be a whole number")
        whole = int(number)
    else:
        whole = number
    if whole < 0:
        return 0, Fault(index, key, "must not be negative")
    if whole > top:
        return 0, Fault(index, key, f"over {top}, more than one call can be")
    return whole, None


def _parse_time(
    fields: dict[str, Any], index: int, *, now: datetime
) -> tuple[datetime, Fault | None]:
    """`t` 的四条判据，顺序即优先级。逐字照 `usage_ingest.go:289-307`。"""
    if "t" not in fields or fields["t"] is None:
        return now, Fault(index, "t", "required")
    value = fields["t"]
    if not isinstance(value, str) or not _RFC3339_RE.match(value.strip()):
        return now, Fault(index, "t", "must be an RFC 3339 time (2026-10-13T08:00:00Z)")
    try:
        when = datetime.fromisoformat(value.strip().replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError:
        return now, Fault(index, "t", "must be an RFC 3339 time (2026-10-13T08:00:00Z)")
    if when.tzinfo is None:  # 正则已经要求偏移量，兜底不猜时区
        return now, Fault(index, "t", "must be an RFC 3339 time (2026-10-13T08:00:00Z)")
    if when > now + timedelta(seconds=FUTURE_S):
        return when, Fault(index, "t", "is in the future")
    if when < EARLIEST:
        return when, Fault(index, "t", "is before 2000-01-01T00:00:00Z, "
                                       "the earliest a call may be dated")
    return when, None


def _parse_one(
    index: int, one: object, *, now: datetime
) -> tuple[dict[str, Any] | None, Fault | None]:
    """单条记录，逐字照 `usage_ingest.go:200 parseReported`。

    ★ **字段名先排序再报错**（照 `:206-215` 的 `slices.Sort(keys)`）—— 同一个坏 body 永远得到
      同一个 `index`/`field`。这是 magpie 明写的设计目标：「the same field is named for the same
      body every time」。所以「表外字段」这一条**先于**所有字段级校验。
    ★ 顺序即优先级：文本四件 → 三个可空文本 → `t` → 六个计数 → `cache_write_1h` →
      四个毫秒（含三条交叉判据）→ `status` → `cost`。
    """
    if not isinstance(one, dict):
        return None, Fault(index, "record", "not a JSON object")
    fields = cast("dict[str, Any]", one)
    for key in sorted(fields):
        if key not in FIELDS:
            return None, Fault(index, key, "is not a field a call has")

    row: dict[str, Any] = {}
    for key in REQUIRED_TEXT:
        text, fault = _text_field(fields, key, index, need=True)
        if fault is not None:
            return None, fault
        row[key] = text
    for key in ("effort", "session", "err"):
        text, fault = _text_field(fields, key, index, need=False)
        if fault is not None:
            return None, fault
        row[key] = text
    if len(row["err"]) > 4096:  # 照 :286-288 截到 4096（ToValidUTF8 在 str 上无对应动作）
        row["err"] = cast("str", row["err"])[:4096]

    when, fault = _parse_time(fields, index, now=now)
    if fault is not None:
        return None, fault
    row["t"] = when.isoformat().replace("+00:00", "Z")

    for key in COUNTS:
        count, fault = _whole_field(fields, key, index, top=MAX_TOKENS, need=False)
        if fault is not None:
            return None, fault
        row[key] = count
    if row["cache_write_1h"] > row["cache_write"]:  # 照 :319-321
        return None, Fault(index, "cache_write_1h", "more than cache_write, which counts it")

    for key in MILLIS:
        millis, fault = _whole_field(fields, key, index, top=MAX_MILLIS, need=False)
        if fault is not None:
            return None, fault
        row[key] = millis
    # `ms` 缺席（或为 null）时三条交叉判据不成立 —— 照 :336 的 `hasMs`。
    has_ms = fields.get("ms") is not None
    if has_ms and row["first_text_ms"] > row["ms"]:  # 照 :337-339
        return None, Fault(index, "first_text_ms", "after ms, the end of the call it is in")
    if row["ttft_ms"] > 0 and row["first_text_ms"] > 0 and row["first_text_ms"] < row["ttft_ms"]:
        return None, Fault(index, "first_text_ms",
                           "before ttft_ms: the first text is content too, "
                           "so it can't come before the first content")
    if has_ms and row["flow_ms"] > row["ms"] * 10 // 8 + 1:  # 照 :352-354
        return None, Fault(index, "flow_ms",
                           "over ms×10/8: the content took longer to come than the call took")

    status, fault = _whole_field(fields, "status", index, top=599, need=True)
    if fault is not None:
        return None, fault
    if status < 100:  # 照 :359-361
        return None, Fault(index, "status", "must be an HTTP status, 100 to 599")
    row["status"] = status

    cost = fields.get("cost")
    if cost is not None:
        row["cost"] = _cost_field(cost, index)
    else:
        row["cost"] = None
    if isinstance(row["cost"], Fault):
        return None, row["cost"]
    return row, None


def _cost_field(value: object, index: int) -> float | Fault:
    """`cost` 的三条判据。逐字照 `usage_ingest.go:363-374`。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return Fault(index, "cost", "must be a number of USD")
    amount = float(value)
    if math.isnan(amount) or math.isinf(amount) or amount < 0:
        return Fault(index, "cost", "must not be negative")
    if amount > MAX_COST:
        return Fault(index, "cost", "over 10000 USD, more than one call can cost")
    return amount


# ============================================ 落盘与 `rid` 幂等（从日志本身读回，不建索引文件）

def _known_rids(path: Path) -> set[str]:
    """从**日志本身**读回已报过的 `rid` —— 逐字照 `reported.go:37 catchUpReported` 的扫描口径。

    ★ 先按字节找 `REPORTED_MARK` 再 parse（照 `:65 if !bytes.Contains(line, reportedMark)`）：
      日志会长到几十万行，「这一行是不是上报行」一个子串就够判，不用整份 unmarshal。
    ★ 坏行 / 半行 / `rid` 为空的**跳过**，不许当「没报过」（`tools/pool/ledger_spend.py` 的
      「坏行跳过不当 0」是同一条纪律）。半行的容忍也是照 `:60-63`：末行没写完就留到下次。
    ★ 文件不存在 ⇒ 空集（照 `:39-42`）。**不另立索引文件**：两个真源，删一份就让已报过的行复活。
    ★ 每次**全扫**，没有 magpie 的 `info`/`off` 增量位点（`:51`）—— 本卡不做增量，如实记在缺口里。
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    known: set[str] = set()
    for line in text.splitlines():
        if REPORTED_MARK not in line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        record = cast("dict[str, Any]", row)
        if record.get("source") != SOURCE_REPORTED:
            continue
        rid = record.get("rid")
        if isinstance(rid, str) and rid:
            known.add(rid)
    return known


def _reported_row(record: dict[str, Any]) -> dict[str, Any]:
    """把校验过的记录变成落盘行：强制 `source: "reported"`，且**不带**任何 caller 归因。

    照 `reported.go:111-112` 的 `r.Source = SourceReported` 与
    `r.CallerKeyID, r.CallerKeyName = "", ""`。
    ★ 本仓的上报行**没有** caller 字段（`FIELDS` 白名单里就没有 `caller`/`key`/`account`），
      所以「恒为空」在这里落成「一栏都不写」—— 写一个空 `""` 与「没有这一栏」在下游读者眼里
      是两种东西，前者会让人以为「有 caller，只是空的」。
    """
    row = dict(record)
    row["source"] = SOURCE_REPORTED
    for banned in ("caller", "key", "account", "caller_key_id", "caller_key_name"):
        row.pop(banned, None)
    return row


def _append_rows(path: Path, lines: list[str]) -> None:
    """**只追加**（`open("a")`，与 `tools/pool/ledger_spend.py` 的 append 同款）。

    这是只追加的账，不是覆盖式状态文件 —— 所以**不用** `write_atomic()`（同目录 tmp +
    `os.replace`），那会把并发写进来的行整份盖掉。
    """
    if not lines:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as out:
        for line in lines:
            out.write(line + "\n")


def _plan(
    rows: list[dict[str, Any]], known: set[str]
) -> tuple[list[str], list[tuple[int, str, str]]]:
    """决定每一行是 `accepted` 还是 `skipped`（同一批内重复的 `rid` 也跳过）。"""
    seen: set[str] = set()
    lines: list[str] = []
    verdicts: list[tuple[int, str, str]] = []
    for index, row in enumerate(rows):
        rid = cast("str", row["rid"])
        if rid in known or rid in seen:  # 照 :108 的 `reported.rids[rid] || batch[rid]`
            verdicts.append((index, rid, "skipped"))
            continue
        seen.add(rid)
        lines.append(json.dumps(_reported_row(row), ensure_ascii=False))
        verdicts.append((index, rid, "accepted"))
    return lines, verdicts


def ingest(text: str, *, now: datetime | None = None,
           root: Path | str | None = None) -> dict[str, Any]:
    """整批收下。回 `{"accepted": n, "skipped": m, "records": [{"index", "rid", "status"}]}`。

    `status ∈ {"accepted", "skipped"}`，字段名与 magpie 的回包逐字一致（`usage_ingest.go:142-162`）
    —— 将来谁写了个转发壳，字段不用翻译。

    ★ **全有或全无**：`parse_batch()` 在**任何**写动作之前跑完；拒单时目标文件的行数与 mtime
      都不变（照 `tools/pool_accounts.py:867`「先校验（拒写时账本一个字节不变），再统一写」）。
    ★ **`rid` 幂等**：从日志本身读回（`_known_rids`），同一批内重复的也跳过（`_plan`）。
    ★ **两段式**照 `reported.go:96` / `:99-103`：锁外读一遍，落盘前再读一遍补齐。pool 这里不加锁
      （本卡不引第三种锁），所以第二段只是「尽量缩小窗口」，不是互斥 —— 如实记，不假装。
    """
    when = datetime.now(timezone.utc) if now is None else now
    rows = parse_batch(text, now=when)
    path = reported_path(root)
    known = _known_rids(path)
    lines, verdicts = _plan(rows, known)
    if lines:
        again = _known_rids(path)
        if again != known:  # 别人刚写进来过 ⇒ 按新读数重算（第二段）
            lines, verdicts = _plan(rows, again)
    _append_rows(path, lines)
    accepted = sum(1 for _, _, status in verdicts if status == "accepted")
    return {
        "accepted": accepted,
        "skipped": len(verdicts) - accepted,
        "records": [{"index": i, "rid": rid, "status": status} for i, rid, status in verdicts],
    }


# ============================================ 读端合并（`include_reported` 的默认值是唯一一处规则）

def _number(value: object) -> int:
    """JSONL 里的 token 数：只认 `int`/`float`，别的（缺字段 / 字符串）当 0 —— 不猜。"""
    if isinstance(value, (int, float)):
        return int(value)
    return 0


def _local(raw: object) -> datetime | None:
    """无时区的本地串 → 带 `+08:00` 的时刻；解不开 ⇒ `None`（跳过这一行）。"""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw).replace(tzinfo=USAGE_TZ)
    except ValueError:
        return None


def _moment(raw: object) -> datetime | None:
    """**带时区**的 RFC 3339 串 → 带时区的时刻；解不开 / 没时区 ⇒ `None`（跳过这一行）。

    ★ 上报行的 `t` 是自己写的 RFC 3339（`:343` 落的 `isoformat()`，UTC 落成 `Z`），它**自带**
      偏移量 —— 所以**不能**复用 `_local()`：那个把 `tzinfo` 强行覆盖成 `+08:00`，会把一条
      `09:00Z` 的行挪成 `09:00+08:00`，凭空错开八小时。两本账的时间口径不同，两个解析器。
    """
    if not isinstance(raw, str) or not raw:
        return None
    text = raw.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        return None
    if when.tzinfo is None:  # 没有偏移量就没法与 aware 的 start/end 比，跳过不猜
        return None
    return when


def _dispatch_tokens(model: str, start: datetime, end: datetime, root: Path) -> int:
    """只读 `wb-usage.jsonl` 的汇总 —— 与 `tools/wb_dispatch.py::usage_in()` 逐条同口径。"""
    path = root / "gates" / "diag" / "wb-usage.jsonl"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return 0
    total = 0
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        record = cast("dict[str, Any]", row)
        if record.get("模型") != model:
            continue
        verdict = f"{record.get('判决') or ''} {record.get('退出码') or ''}".lower()
        if "dry" in verdict:
            continue
        began = _local(record.get("开始"))
        if began is None:
            continue
        if not start <= began < end:
            continue
        total += _number(record.get("input_tokens"))
        total += _number(record.get("output_tokens"))
        total += _number(record.get("cache_read"))
    return total


def _reported_tokens(model: str, start: datetime, end: datetime, root: Path) -> int:
    """上报账里同模型、同窗口的 token 之和（`in + out + cache_read`，同样不做减法）。

    ★ 上报行**没有** `判决`/`退出码`，所以「`dry` 行跳过」这条在它们身上没有对应物：
      上报的是「外面真调了一次」，不是一个 dry run。如实写。
    """
    path = root.joinpath(*REPORTED_REL)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    total = 0
    for line in text.splitlines():
        if REPORTED_MARK not in line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        record = cast("dict[str, Any]", row)
        if record.get("source") != SOURCE_REPORTED or record.get("model") != model:
            continue
        when = _moment(record.get("t"))
        if when is None or not start <= when < end:
            continue
        total += _number(record.get("in"))
        total += _number(record.get("out"))
        total += _number(record.get("cache_read"))
    return total


def merged_tokens(model: str, start: datetime, end: datetime, *, root: Path | str | None = None,
                  include_reported: bool = False) -> int:
    """按**模型**与时间区间 `[start, end)` 汇总 `gates/diag/wb-usage.jsonl`，可选并入上报账。

    这是 magpie「上报行单列、**默认不计入任何限额**」在 pool 侧的**唯一一处**落点：
    magpie 用七处分别排除（`budget.counts()` 加五处 `IsReported()` 加 `SourceOf()`），pool 只有
    `include_reported` 这一个默认值能守。★ **这个方法不许被限额判据调用**，调用时必须让
    `include_reported` 保持默认 `False`。

    ★ ★ `include_reported=False` 时**逐字等于** `tools/wb_dispatch.py::usage_in()` 只读
    `wb-usage.jsonl` 的口径，逐条复述如下（改口径必须两边一起改，或者把 `usage_in()` 改成调本函数
    —— 那是下一张卡，本卡零接线）：

    * **时区钉死 `+08:00`**：行里的 `开始` / `结束` 是秒级、**无时区**的本地串
      （`append_usage_line()` 用 `datetime.fromtimestamp().isoformat()` 写）。这里按
      `tools/pool_accounts.py` 的同一口径 `UTC+8` 补上 `tzinfo` 再比，**不用 `astimezone()` 猜**、
      不读系统时区。入参 `start` / `end` 必须自带 `tzinfo`；给 naive 的会抛 `TypeError`
      （故意不兜底 —— 猜时区比报错糟）。
    * **区间** `[start, end)`，按 `开始` 落点算（与 `append_usage_line()` 写的那个字段一致）。
    * **dry run 不计入**：`判决` / `退出码` 里带 `dry` 字样的行跳过。如实写：现行
      `append_usage_line()` 只在真跑完时调用，落盘行**没有** dry-run 字段，所以这条现在是
      防御性的（照 `window_holds.go:100`/`:108` 的 `dryRun`/`dryRuns` 口径先把闸门留好）。
    * **token 口径**：`input_tokens + output_tokens + cache_read` 三个字段全加。为什么不去重：
      本机没有权威说明 `cache_read` 是否已含在 `input_tokens` 里（两种 API 口径都存在），
      猜错会系统性少算或多算 ⇒ **不做减法**，原样相加并在文档里说清。
    * **金额恒 0.0**：仓里没有计价表，第二档不编单价。（所以本函数只回 token 数，不回金额。）
    * 读不出来 / 没有这个文件 / 某行 JSON 坏 / `开始` 解不开 ⇒ **跳过或回 0**，不猜、不抛。

    `include_reported=True` 时把上报账里同模型、同窗口的 token 也加进来 —— 上报行的 `t` 是
    RFC 3339（带时区），按同一区间 `[start, end)` 比；token 同样是 `in + out + cache_read` 全加。
    """
    base = Path(root) if root is not None else TOOL_ROOT
    total = _dispatch_tokens(model, start, end, base)
    if include_reported:
        total += _reported_tokens(model, start, end, base)
    return total
