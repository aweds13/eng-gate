r"""禅道迭代甘特 `tools/zentao_gantt.py`（卡 223 · T-G337）—— 只标准库。

为什么有它：用户 2026-10-13 令「关键是怎么把禅道融进去，我很想利用禅道**尽量多的功能**」。
第一半（**只读桥**，卡 211）已把 项目/迭代/任务 拉成一份读数；而**禅道自己的甘特在企业版里**，
用户不打算为这个升企业版 —— 本工具在**那份读数之上自写**一张迭代甘特。

输入：卡 211 的读数（`tools/zentao_bridge.py --json` 输出的那份 JSON）。字段名与映射的**真源**
是 `docs/zentao-bridge.toml`（卡 211 交付）—— 本工具**逐字照它的 `[[mapping]]` 与
`[required_fields]` 读**，不另立字段。

★ 本工具**不连禅道、不碰授权/破解**（卡 211 的硬边界照旧）：它只读一份 JSON 文件，
  一个字节都不往禅道写。起子进程那条铁律与本工具无关：只用标准库，不起子进程。

★ 离线可用：没有禅道实例时，用**内置的存档样例读数**（`SAMPLE_BUNDLE`，形状照卡 211 的
  测试 fixture 抄）也能出一张图 —— 这正是本机能验的那条路（见模块末尾「诚实边界」）。

★ 如实报：起止缺失 / 起止坏掉 / 任务缺必需字段 —— **逐条点名**（不沉默、也不拿空图冒充
  「拉到了、是空的」）；坏 JSON ⇒ 退 5。

用法：
    python -X utf8 tools/zentao_gantt.py                          # 内置样例 → HTML 打到 stdout
    python -X utf8 tools/zentao_gantt.py --input 读数.json --html out.html
    python -X utf8 tools/zentao_gantt.py --input 读数.json --json

退出码：0 成功 / 5 输入不是 JSON / 6 结构缺字段 / 7 起止日期坏。

诚实边界（★ 不假装）：本机**没有在跑的禅道**（见 `docs/zentao-bridge.toml` 的 `[runtime]`）。
所以本工具拿内置样例跑得通，**不代表**真禅道数据下长什么样 —— 真数据要等有活体时再补。
样例里的日期/状态是**照叶子形状编的**，不是第 1 步真拉到的响应。
"""

from __future__ import annotations

import argparse
import datetime
import html as html_escape
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

#: 执行（迭代）与任务的 canonical 字段 —— 真源：`docs/zentao-bridge.toml` 的 `[[mapping]]`。
#: ★ 照抄，不另立；只挑甘特用得上的那几个（其余字段原样留在读数里，不在这里再抄一遍）。
EXECUTION_FIELDS: tuple[str, ...] = (
    "id", "name", "project", "code", "type", "parent",
    "begin", "end", "status", "progress", "isParent",
)
TASK_FIELDS: tuple[str, ...] = (
    "id", "name", "execution", "project", "status", "pri",
    "assignedTo", "estimate", "consumed", "left", "deadline",
)

#: 每个读数条目**必须**有的字段 —— 真源：`docs/zentao-bridge.toml` 的 `[required_fields]`。
REQUIRED_ITEM_FIELDS: tuple[str, ...] = ("id", "name")

#: 错误种类 → 退出码（口径照卡 211 的桥：坏 JSON / 缺字段 分开报）。
EXIT_CODES: dict[str, int] = {
    "badjson": 5,
    "badshape": 6,
    "baddate": 7,
}

#: 内置存档样例读数 —— 形状照卡 211 测试 fixture 抄（字段名逐字对齐 `[[mapping]]`）。
#: ★ 没有禅道实例时用它出图（本机能验的路）；它不是「真拉到的响应」，见模块头「诚实边界」。
SAMPLE_BUNDLE: dict[str, Any] = {
    "ok": True,
    "source": "sample: 存档样例读数（非真禅道）",
    "projects": [
        {"id": 1, "name": "示例项目", "code": "demo", "model": "scrum", "type": "project",
         "status": "doing", "PM": "admin", "begin": "2026-01-01", "end": "2026-03-31",
         "progress": 40},
    ],
    "executions": [
        {"id": 11, "name": "迭代一", "project": 1, "code": "s1", "type": "sprint", "parent": 0,
         "begin": "2026-01-01", "end": "2026-01-14", "status": "closed", "progress": 100,
         "isParent": False},
        {"id": 12, "name": "迭代二", "project": 1, "code": "s2", "type": "sprint", "parent": 0,
         "begin": "2026-01-15", "end": "2026-02-11", "status": "doing", "progress": 40,
         "isParent": False},
        {"id": 13, "name": "迭代三", "project": 1, "code": "s3", "type": "sprint", "parent": 0,
         "begin": "2026-02-12", "end": "2026-03-11", "status": "wait", "progress": 0,
         "isParent": False},
    ],
    "tasks": [
        {"id": 101, "name": "搭脚手架", "execution": 11, "project": 1, "status": "done",
         "pri": 3, "assignedTo": "admin", "estimate": 8, "consumed": 8, "left": 0,
         "deadline": "2026-01-05"},
        {"id": 102, "name": "接口草案", "execution": 11, "project": 1, "status": "done",
         "pri": 2, "assignedTo": "dev1", "estimate": 5, "consumed": 5, "left": 0,
         "deadline": "2026-01-10"},
        {"id": 103, "name": "数据模型", "execution": 12, "project": 1, "status": "doing",
         "pri": 3, "assignedTo": "dev1", "estimate": 8, "consumed": 3, "left": 5,
         "deadline": "2026-01-22"},
        {"id": 104, "name": "鉴权", "execution": 12, "project": 1, "status": "doing",
         "pri": 2, "assignedTo": "dev2", "estimate": 3, "consumed": 1, "left": 2,
         "deadline": "2026-02-05"},
        {"id": 105, "name": "联调", "execution": 12, "project": 1, "status": "wait",
         "pri": 1, "assignedTo": "dev2", "estimate": 5, "consumed": 0, "left": 5,
         "deadline": None},
        {"id": 106, "name": "验收脚本", "execution": 13, "project": 1, "status": "wait",
         "pri": 2, "assignedTo": "admin", "estimate": 3, "consumed": 0, "left": 3,
         "deadline": "2026-03-05"},
    ],
}


class GanttError(Exception):
    """按「哪一步 + 哪种错」报出的甘特错（kind 决定退出码）。"""

    def __init__(self, kind: str, step: str, detail: str) -> None:
        super().__init__(f"{kind}: {step}: {detail}")
        self.kind = kind
        self.step = step
        self.detail = detail

    @property
    def exit_code(self) -> int:
        return EXIT_CODES[self.kind]


# ---------------------------------------------------------------- 读数 → 模型


def _label(item: dict[str, Any]) -> str:
    """一条读数条目的点名（`#<id> <name>`）—— 出错时报它，让人知道是哪一条。"""
    return f"#{item.get('id')} {item.get('name')}"


def _require_item(item: object, section: str, index: int) -> dict[str, Any]:
    """条目必须是非空对象且带必需字段（真源 `[required_fields]`）；否则点名。"""
    if not isinstance(item, dict):
        got = type(item).__name__
        raise GanttError("badshape", section, f"{section}[{index}] 不是对象（实为 {got}）")
    for field in REQUIRED_ITEM_FIELDS:
        if field not in item:
            raise GanttError("badshape", section, f"{section}[{index}] 缺必需字段 {field!r}")
    return item


def _parse_date(raw: object, label: str, field: str, step: str) -> datetime.date:
    """起止/截止日期：缺了 ⇒ 如实报（badshape）；坏格式 ⇒ bad… 点名。"""
    if raw is None or raw == "":
        raise GanttError(
            "badshape", step, f"{label} 缺字段 {field!r}（甘特要起止，如实报，不用空值冒充）")
    text = str(raw)
    try:
        return datetime.date.fromisoformat(text)
    except ValueError as exc:
        raise GanttError(
            "baddate", step, f"{label} 的 {field}={text!r} 不是 ISO 日期（YYYY-MM-DD）") from exc


def _offer_date(raw: object, label: str) -> tuple[datetime.date | None, str | None]:
    """任务截止这种**可缺**字段：有就解析（坏格式仍算错），没有就回一条**如实报**的警告。"""
    if raw is None or raw == "":
        return None, f"任务 {label} 没有 deadline ⇒ 不画在时间轴上（如实报，不是没有它）"
    try:
        return datetime.date.fromisoformat(str(raw)), None
    except ValueError:
        raise GanttError(
            "baddate", "tasks", f"任务 {label} 的 deadline={raw!r} 不是 ISO 日期") from None


def build_model(bundle: object, origin: str) -> dict[str, Any]:
    """把一份读数变成甘特模型（行 = 迭代，行内挂它的任务）。坏输入逐条点名。"""
    if not isinstance(bundle, dict):
        raise GanttError("badshape", "bundle", f"读数顶层不是对象（实为 {type(bundle).__name__}）")

    raw_executions = bundle.get("executions")
    if not isinstance(raw_executions, list):
        got = type(raw_executions).__name__ if "executions" in bundle else "字段不存在"
        raise GanttError("badshape", "bundle", f"读数里没有数组 'executions'（实为 {got}）")

    warnings: list[str] = []
    executions = [_require_item(item, "executions", i) for i, item in enumerate(raw_executions)]

    # 任务按所属迭代分组（没有 tasks 段 = 如实报，不当成「迭代下没任务」）
    raw_tasks = bundle.get("tasks")
    if not isinstance(raw_tasks, list):
        if "tasks" in bundle:
            got_tasks = type(raw_tasks).__name__
            raise GanttError("badshape", "bundle", f"读数里 'tasks' 不是数组（实为 {got_tasks}）")
        raw_tasks = []
        warnings.append("读数没有 'tasks' 段 ⇒ 迭代下不挂任务（如实报）")

    by_execution: dict[Any, list[dict[str, Any]]] = {}
    for i, raw_task in enumerate(raw_tasks):
        task = _require_item(raw_task, "tasks", i)
        deadline, note = _offer_date(task.get("deadline"), _label(task))
        if note:
            warnings.append(note)
        record: dict[str, Any] = {
            "id": task.get("id"),
            "name": task.get("name"),
            "status": task.get("status"),
            "assignedTo": task.get("assignedTo"),
            "deadline": deadline.isoformat() if deadline else None,
        }
        by_execution.setdefault(task.get("execution"), []).append(record)

    rows: list[dict[str, Any]] = []
    for item in executions:
        label = _label(item)
        begin = _parse_date(item.get("begin"), label, "begin", "executions")
        end = _parse_date(item.get("end"), label, "end", "executions")
        if end < begin:
            raise GanttError(
                "baddate", "executions",
                f"{label} 起止倒挂：begin={item.get('begin')} 晚于 end={item.get('end')}",
            )
        rows.append({
            "id": item.get("id"),
            "name": item.get("name"),
            "status": item.get("status"),
            "progress": item.get("progress"),
            "project": item.get("project"),
            "begin": begin.isoformat(),
            "end": end.isoformat(),
            "days": (end - begin).days + 1,
            "tasks": by_execution.get(item.get("id"), []),
        })

    if not rows:
        warnings.append("读数里 executions 为空 ⇒ 没有可画的迭代（如实报，不拿空图冒充拉到）")

    span_begin: datetime.date | None = None
    span_end: datetime.date | None = None
    if rows:
        span_begin = min(datetime.date.fromisoformat(str(row["begin"])) for row in rows)
        span_end = max(datetime.date.fromisoformat(str(row["end"])) for row in rows)

    task_count = sum(len(row["tasks"]) for row in rows)
    model: dict[str, Any] = {
        "ok": True,
        "origin": origin,
        "source": bundle.get("source"),
        "range": {
            "begin": span_begin.isoformat() if span_begin else None,
            "end": span_end.isoformat() if span_end else None,
            "days": ((span_end - span_begin).days + 1) if span_begin and span_end else 0,
        },
        "executions": len(rows),
        "tasks": task_count,
        "rows": rows,
        "warnings": warnings,
    }
    return model


def load_bundle(text: str, origin: str) -> object:
    """读一份读数文本 → Python 对象；不是 JSON 就退 5 报清。"""
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise GanttError("badjson", origin, f"输入不是 JSON：{exc}") from exc


# ---------------------------------------------------------------- 渲染


def render_json(model: dict[str, Any]) -> str:
    """机器可读的甘特模型（确定性：同一输入 ⇒ 逐字节相同）。"""
    return json.dumps(model, ensure_ascii=False, indent=2, sort_keys=True)


def _month_ticks(begin: datetime.date, end: datetime.date) -> list[tuple[str, float]]:
    """时间轴上按月画刻度：`(标签, 左偏移百分比)`。"""
    total = (end - begin).days + 1
    ticks: list[tuple[str, float]] = []
    cursor = begin.replace(day=1)
    while cursor <= end:
        left = max(0.0, (cursor - begin).days / total * 100.0)
        ticks.append((f"{cursor.year}-{cursor.month:02d}", left))
        cursor = (cursor.replace(day=28) + datetime.timedelta(days=7)).replace(day=1)
    return ticks


def _bar(row: dict[str, Any], span_begin: datetime.date, total: int) -> str:
    """一条迭代的横条（含进度填充）+ 它的任务截止标记。"""
    begin = datetime.date.fromisoformat(str(row["begin"]))
    end = datetime.date.fromisoformat(str(row["end"]))
    left = (begin - span_begin).days / total * 100.0
    width = ((end - begin).days + 1) / total * 100.0
    progress = row.get("progress")
    fill = 0.0
    if isinstance(progress, (int, float)):
        fill = max(0.0, min(100.0, float(progress)))
    label = html_escape.escape(f"{row['name']}（{row['begin']}→{row['end']}）")
    bar = (
        f'<div class="bar" style="left:{left:.3f}%;width:{width:.3f}%" '
        f'title="{label} · {row.get("days")} 天 · {row.get("status")}">'
        f'<span class="fill" style="width:{fill:.1f}%"></span></div>'
    )
    marks = []
    for task in row["tasks"]:
        deadline = task.get("deadline")
        if not deadline:
            continue
        day = datetime.date.fromisoformat(str(deadline))
        at = (day - span_begin).days / total * 100.0
        raw_tip = f"任务 #{task['id']} {task['name']} · 截止 {deadline} · {task.get('status')}"
        tip = html_escape.escape(raw_tip)
        marks.append(f'<div class="tick" style="left:{at:.3f}%" title="{tip}"></div>')
    return bar + "".join(marks)


_CSS = """
:root{--ink:#1a2233;--mut:#6b7690;--line:#e3e7ef;--bar:#4a6cf7;
      --fill:#9db1ff;--tick:#f0913a;--bg:#f7f8fb}
*{box-sizing:border-box}
body{margin:0;padding:28px 32px;
     font:14px/1.5 "Segoe UI","Microsoft YaHei",system-ui,sans-serif;
     color:var(--ink);background:var(--bg)}
h1{font-size:20px;margin:0 0 6px}
.meta{color:var(--mut);font-size:13px;margin:0 0 16px}
.legend{display:flex;gap:18px;flex-wrap:wrap;color:var(--mut);font-size:12px;margin:0 0 10px}
.legend i{display:inline-block;width:22px;height:9px;border-radius:2px;
          vertical-align:middle;margin-right:5px}
.legend .b{background:var(--bar)}
.legend .f{background:var(--fill)}
.legend .t{background:var(--tick);height:12px;width:3px}
table.gantt{width:100%;border-collapse:collapse;background:#fff;
            border:1px solid var(--line);border-radius:8px;overflow:hidden}
table.gantt th,table.gantt td{border-bottom:1px solid var(--line);
            padding:9px 12px;text-align:left;vertical-align:middle}
table.gantt thead th{background:#eef1f8;color:var(--mut);font-weight:600;font-size:12px}
.lab .nm{font-weight:600}
.lab .sub{display:block;color:var(--mut);font-size:12px}
.tl{position:relative;height:26px;padding:0;
    background-image:linear-gradient(90deg,var(--line) 0 1px,transparent 1px);
    background-repeat:repeat-x;background-size:8.33% 100%}
.bar{position:absolute;top:5px;height:16px;background:var(--bar);border-radius:4px;
     box-shadow:0 1px 2px rgba(26,34,51,.18);min-width:3px}
.bar .fill{display:block;height:100%;background:var(--fill);border-radius:4px}
.tick{position:absolute;top:2px;width:3px;height:22px;background:var(--tick);border-radius:2px}
.tick-lbl{position:absolute;color:var(--mut);font-size:11px}
.warn{margin:16px 0 0;padding:12px 14px;background:#fff7ec;
      border:1px solid #f4d9ab;border-radius:6px;color:#8a5a12;font-size:13px}
.warn h2{font-size:13px;margin:0 0 6px}
.warn ul{margin:0;padding-left:20px}
.empty{color:var(--mut);font-size:13px;padding:16px;background:#fff;
       border:1px dashed var(--line);border-radius:8px}
footer{margin-top:18px;color:var(--mut);font-size:12px}
"""


def render_html(model: dict[str, Any]) -> str:
    """自包含 HTML（无外链、无脚本）—— 直接双击就能看的迭代甘特。"""
    rng = model["range"]
    assert isinstance(rng, dict)
    head = (
        f"禅道迭代甘特（自写） ｜ {model['executions']} 个迭代 · {model['tasks']} 个任务")
    if rng["begin"] and rng["end"]:
        sub = (f"来源：{model.get('source') or '（读数未标 source）'} ｜ "
               f"范围：{rng['begin']} → {rng['end']}（{rng['days']} 天）")
    else:
        sub = f"来源：{model.get('source') or '（读数未标 source）'} ｜ 范围：无（没有可画的迭代）"

    body_rows: list[str] = []
    if rng["begin"] and rng["end"]:
        span_begin = datetime.date.fromisoformat(str(rng["begin"]))
        total = int(rng["days"])
        ticks = _month_ticks(span_begin, datetime.date.fromisoformat(str(rng["end"])))
        head_ticks = "".join(
            '<th class="tl-h" style="position:relative;height:0;border:0;padding:0">'
            f'<span class="tick-lbl" style="left:{left:.3f}%">{tag}</span></th>'
            for tag, left in ticks
        )
        for row in model["rows"]:
            assert isinstance(row, dict)
            tasks = row["tasks"]
            assert isinstance(tasks, list)
            no_deadline = sum(1 for t in tasks if not t.get("deadline"))
            sub2 = (f"#{row['id']} · {row['begin']}→{row['end']} · {row['days']} 天 · "
                    f"{row['status']} · 进度 {row['progress']}% · 任务 {len(tasks)} 个"
                    + (f"（{no_deadline} 个无截止）" if no_deadline else ""))
            body_rows.append(
                "<tr>"
                f'<td class="lab"><span class="nm">{html_escape.escape(str(row["name"]))}</span>'
                f'<span class="sub">{html_escape.escape(sub2)}</span></td>'
                f'<td class="tl">{_bar(row, span_begin, total)}</td>'
                "</tr>"
            )
        body = (
            '<table class="gantt"><thead><tr>'
            f'<th class="lab">迭代</th>{head_ticks}</tr></thead>'
            f'<tbody>{"".join(body_rows)}</tbody></table>'
        )
    else:
        body = '<div class="empty">没有可画的迭代（读数里 executions 为空）</div>'

    warn = ""
    warnings = model["warnings"]
    assert isinstance(warnings, list)
    if warnings:
        items = "".join(f"<li>{html_escape.escape(str(w))}</li>" for w in warnings)
        warn = ('<div class="warn">'
                "<h2>如实报（缺的/坏的都在这里，不沉默）</h2>"
                f"<ul>{items}</ul></div>")

    return (
        "<!DOCTYPE html>\n"
        '<html lang="zh-CN">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{head}</title>\n<style>{_CSS}</style>\n</head>\n<body>\n"
        f'<h1>禅道迭代甘特</h1>\n<p class="meta">{html_escape.escape(sub)}</p>\n'
        '<div class="legend"><span><i class="b"></i>迭代区间</span>'
        '<span><i class="f"></i>进度</span>'
        '<span><i class="t"></i>任务截止</span></div>\n'
        f"{body}\n{warn}\n"
        "<footer>本页由 <code>tools/zentao_gantt.py</code> 从卡 211 的读数渲染；"
        "离线、自包含、无脚本。字段口径真源：<code>docs/zentao-bridge.toml</code>。</footer>\n"
        "</body>\n</html>\n"
    )


def render_error_json(exc: GanttError) -> str:
    payload = {"ok": False, "error": {"kind": exc.kind, "step": exc.step, "detail": exc.detail}}
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def render_error_report(exc: GanttError) -> str:
    labels = {"badjson": "输入不是 JSON", "badshape": "结构缺字段", "baddate": "起止日期坏"}
    return f"[{labels[exc.kind]}] 步骤：{exc.step}\n  详情：{exc.detail}"


# ---------------------------------------------------------------- 入口


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zentao_gantt.py",
        description="禅道迭代甘特（自写）：在卡 211 的只读读数之上出一张自包含甘特。",
    )
    parser.add_argument("--input", default=None,
                        help="卡 211 的读数 JSON 文件（默认用内置存档样例读数）")
    parser.add_argument("--html", default=None,
                        help="把自包含 HTML 写到这个路径；不给就看下面默认")
    parser.add_argument("--json", action="store_true", help="把甘特模型 JSON 打到 stdout")
    return parser


def collect_input(args: argparse.Namespace) -> tuple[object, str]:
    """取输入：`--input` 文件优先，否则内置样例。返回（bundle, 来源标签）。"""
    if args.input:
        try:
            text = (sys.stdin.read() if args.input == "-"
                    else Path(args.input).read_text(encoding="utf-8"))
        except OSError as exc:
            raise GanttError("badjson", args.input, f"读不了输入文件：{exc}") from exc
        return load_bundle(text, args.input), args.input
    return SAMPLE_BUNDLE, "sample（内置存档样例读数）"


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        bundle, origin = collect_input(args)
        model = build_model(bundle, origin)
    except GanttError as exc:
        out = render_error_json(exc) if args.json else render_error_report(exc)
        print(out, file=sys.stdout if args.json else sys.stderr)
        return exc.exit_code

    if args.html:
        with open(args.html, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(render_html(model))
        print(f"[写] {args.html}")
    if args.json:
        print(render_json(model))
    elif not args.html:
        print(render_html(model))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
