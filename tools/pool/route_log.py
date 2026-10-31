r"""路由回放：**谁被试过、谁真答了** —— 在做决定的地方落一条（卡 A363 · T-F39）。

对等 magpie `internal/gateway/trace.go`（`const traceKeep = 60`、`type Route struct`、
`beginFor`、`begin`、`sessionFolder`）。但**真正要搬的只有它的包注释那一句**：

> It's recorded where the decisions are made, from the same values they are made with;
> nothing is worked out again afterwards.

⇒ 记录发生在**做决定的地方**、用的是**做决定时的那几个值**、事后**不重算**。
由此三条直接结果，本模块的每一行都从这里推出来：

1. **值必须是调用方传进来的事实**。所以 `append_route()` **不读任何别的账**去「补」或
   「对账」—— 一读就成了事后重算。`gates/diag/wb-usage.jsonl` 里也有「模型 / 轮次」
   两列，但它是**每轮一行**：同一轮里 `m1` 挂了换 `m2` 这件事，它记不出来。照它重算
   `tried` 就是**编数**（判据 5 的钉子 `test_recorded_where_decided` 钉的就是这一位）。
2. **`tried` 为空就不写**。空的意思是「这一轮没有可记的真实尝试顺序」；落一条空记录
   只是把「不知道」写成「知道」。要不要写由调用方定（见 `trae_dispatch.finish`）。
3. **追加，不环形**。magpie 的 `traceKeep = 60` 是**进程内环形缓冲**（它没有盘上账）；
   pool 的账一律**追加文件**（照 `wb_dispatch.append_usage_line`），修剪是
   `tools/wt_prune.py` 的事。在写入处做环形会把历史切掉 —— 那不是本模块的权力。

## 一行一条的形状

字段名与 `append_route()` 的入参**同名、不翻译**（本仓别处 `wb-usage.jsonl` 用中文键，
那是它自己的口径；这里照 `Route struct` 的英文字段名，读写一一对应，不产生第二套名字）：

    {"card": "A363", "attempt": 1, "asked": "m1",
     "tried": [{"model": "m1", "fail": "429 限流（第 1 拍）"},
               {"model": "m2", "fail": ""}],
     "served": "m2", "status": "served", "started_at": 1761900000.0, "at": 1761900123.4}

`tried` **按真实顺序**，不是按白名单顺序、不是排序后的；`fail` 是一句**原因**（不是正文，
也不是凭据），写入时按 `MAX_FAIL` 截断 —— 那是**长度闸**，不是内容判据：真正的
「不含正文与凭据」靠**调用方只传那两列**（判据 2 的钉子 `test_no_prompt_no_secret` 用
哨兵串实测：正文里有的、记录里没有）。

## `status` 是闭集（四个值，不许发明第五个）

| 值 | 什么时候 |
|---|---|
| `served` | 有答案（`served` 非空） |
| `all_failed` | 试过的全挂了（`served` 空、`tried` 非空） |
| `stopped` | `--retry` 界外退出码 7（`wb_dispatch.py` 的既有口径） |
| `quota_blocked` | 额度挡住，压根没开工 |

写入侧**严格校验**：不在这四个里 ⇒ `RouteError`（`ValueError` 的子类）。读回侧
**原样交出**，不替人改判 —— 读到第五个值说明写它的不是本模块，那是要人看的事实，
不是本模块该悄悄规整的东西。

## 坏行如实计数（不许静默当空）

`read_routes()` 的**第二个返回值**是坏行条数，口径照 `tools/pool/jobs.py::parse_events`
的 `unknown += 1`（那里把坏行也印进时间线）。空行**不算坏行**（追加文件末尾可能留空行）。
文件**不在** ⇒ `([], 0)`：空表是**合法读数**，不是错误（体例照
`tools/pipeline_view.py:458 _read_leases`）。

## ★ 缺口（如实写，别抹平）

本文件叫 `gates/diag/wb-route.jsonl`，而仓里有**三处**按 `wb-*.jsonl` 通配的读者会把它
当成**一张叫 `route` 的卡**（T-G137 当年就栽在同一个坑：`wb-usage.jsonl` 成了 9 棵树
9 行幻影）：

- `tools/wb_dash.py:159` 的 `NON_CARD_LOGS = frozenset({"wb-usage.jsonl"})` ——
  面板会把 `wb-route` 当一张卡显示成「静默 N 分钟（可能卡死）」；
- `tools/pool/jobs.py:40` 的 `USAGE_LOG_RE = re.compile(r"^wb-usage(\.r\d+)?\.jsonl$")` ——
  `scan_jobs` 会把它标成「在跑 / 断了」而不是「非派活」；
- `tools/wb_retention.py:164` 的 `diag.glob("wb-*.jsonl")` —— 会把它算进
  `no_verdict_jsonl`，于是每次巡检都报一条「有日志没判决」的**假欠账**。

本卡（A363）**不改这三处**：它们不属于本卡的域。改名（`route-<卡>.jsonl`）也不做 ——
那会和「账一律 `wb-*`」的既有口径分家。**三个读者的收口另开一张卡**；在那之前，
本模块的落盘就是这个后果，如实写在这里而不是装作没有。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:  # pragma: no cover —— 只为类型注解（ruff TCH）
    from collections.abc import Sequence

#: 仓库根（`tools/pool/route_log.py` 往上三层）；测试一律显式给 `root=`，不靠它。
TOOL_ROOT = Path(__file__).resolve().parent.parent.parent
#: 账的位址（相对 `root`）。★ 与 `wb-usage.jsonl`（用量账）**分两份**，一个字节都不混。
ROUTE_LOG_REL: tuple[str, ...] = ("gates", "diag", "wb-route.jsonl")

#: `status` 的闭集 —— 四个，一个字都不多（判据 9）。
STATUS_SERVED = "served"
STATUS_ALL_FAILED = "all_failed"
STATUS_STOPPED = "stopped"
STATUS_QUOTA_BLOCKED = "quota_blocked"
STATUSES: tuple[str, ...] = (
    STATUS_SERVED,
    STATUS_ALL_FAILED,
    STATUS_STOPPED,
    STATUS_QUOTA_BLOCKED,
)

#: `fail` 一句原因最多多少字（长度闸，不是内容判据；见模块 docstring）。
MAX_FAIL = 200


class RouteError(ValueError):
    """这条路由记录不合规（`status` 不在闭集 / `tried` 不是 `[{"model", "fail"}]`）。"""


def route_path(root: Path | str | None = None) -> Path:
    """账的路径：`root`（默认仓库根）下的 `gates/diag/wb-route.jsonl`。"""
    base = Path(root) if root is not None else TOOL_ROOT
    return base.joinpath(*ROUTE_LOG_REL)


def _fail_text(value: object) -> str:
    """那句失败原因：压成一行、按 `MAX_FAIL` 截断（`None` ⇒ 空串 = 没失败）。"""
    flat = " ".join(str(value or "").split())
    return flat if len(flat) <= MAX_FAIL else flat[: MAX_FAIL - 1] + "…"


def _one_try(raw: object, index: int) -> dict:
    """`tried` 的一条：`{"model": ..., "fail": ""}`；不合规 ⇒ `RouteError`（点第几条）。"""
    if not isinstance(raw, dict):
        raise RouteError(f"tried 第 {index} 条不是对象：{raw!r}")
    row = cast("dict[str, object]", raw)
    model = row.get("model")
    if not isinstance(model, str) or not model.strip():
        raise RouteError(f"tried 第 {index} 条没有 model（或不是非空字符串）：{raw!r}")
    return {"model": model.strip(), "fail": _fail_text(row.get("fail"))}


def append_route(
    *,
    card: str,
    attempt: int,
    asked: str,
    tried: Sequence[dict],
    served: str,
    status: str,
    started_at: float | None,
    root: Path | None = None,
) -> Path:
    """一行一轮，落在**做决定的地方**（照 `trace.go` 包注释）。

    ★ 每个参数都是**调用方传进来的事实**，本模块不读别的账、不重算、不排序
      （`tried` 的次序**就是**真实尝试次序 —— 打乱或重排等于篡改判据 3）。
    ★ `tried` 为空**不拒**（有的轮次确实没有可记的顺序，比如额度挡住压根没开工），
      但那种轮次该不该落一条由调用方定：本模块只保证**传什么写什么**。
    """
    if status not in STATUSES:
        raise RouteError(
            f"status={status!r} 不在闭集 {list(STATUSES)} 里 —— 第五个值不许发明")
    if not str(card).strip():
        raise RouteError("card 是空的：记录必须能指回一张卡（否则回放时找不到它）")
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        raise RouteError(f"attempt={attempt!r} 不是正整数（第几轮从 1 起）")
    tries = [_one_try(raw, index) for index, raw in enumerate(tried)]

    path = route_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "card": str(card).strip(),
        "attempt": attempt,
        "asked": str(asked or ""),
        "tried": tries,
        "served": str(served or ""),
        "status": status,
        "started_at": started_at,
        "at": time.time(),
    }
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def read_routes(card: str | None = None, *, root: Path | None = None) -> tuple[list[dict], int]:
    """只读；文件不在 ⇒ `([], 0)`（合法空表）。坏行跳过并**如实计数**（第二返回值）。

    `card` 不给 ⇒ 全部卡的行（按文件里的次序，**不排序**：那次序就是被记下来的次序）。
    坏行 = 解不出 JSON / 解出来不是对象；空行不算坏行（追加文件末尾可能留空行）。
    """
    path = route_path(root)
    if not path.exists():
        return [], 0
    text = path.read_text(encoding="utf-8", errors="replace")
    rows: list[dict] = []
    bad = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            parsed: object = json.loads(line)
        except json.JSONDecodeError:
            bad += 1
            continue
        if not isinstance(parsed, dict):
            bad += 1
            continue
        row = cast("dict[str, object]", parsed)
        if card is not None and str(row.get("card")) != str(card):
            continue
        rows.append(dict(row))
    return rows, bad
