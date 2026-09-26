"""工人状态面板（`tools/wb_dash.py`，台账号 T-G93）—— 原型 `gates/diag/wb_dash.proto.py` 转正。

一句话：把 `gates/diag/wb-*` 那堆状态文件读成一块**会自动刷新的表**，让主控/用户一眼看到
"每个工人在不在动、跑到哪了、有没有被掐"。读的全是文件，**不碰工人、不改任何被提交的东西**。

    python -X utf8 tools/wb_dash.py                 # 默认 http://127.0.0.1:8787
    python -X utf8 tools/wb_dash.py --port 8899 --host 127.0.0.1

**只读**：只读 `gates/diag/wb-*.jsonl` / `*.heartbeat.txt` / `*.verdict.txt` / `*.session.txt`，
绝不调用或杀工人、绝不写仓库里任何被跟踪的文件。

**边界（如实写）**：它只报"在不在动、动到哪了"，**不判断内容对不对**（那是主控复核的事）；
状态文件本身在 gitignored 目录里。多树只扫 `<仓库根>/gates/diag/` 与本仓库根下的
`<仓库根>/.wt/*/gates/diag/`；从**某棵 worktree 内部**运行时，根是那棵 worktree，
找得到它自己的 `gates/diag/`、找**不到**兄弟 worktree（面板的常规跑法是从主工作区起）。
续跑日志（`wb-<卡>.r2.jsonl`）**一行一轮，同卡各轮相邻**（T-G113 定的一行一轮/相邻合并口径
不变）；★ 整体行序**最新在前**（T-G123）：组的次序按组内最后一次活动的时间**降序** ——
刚动过的卡在最上面，不用往下翻；同一张卡的各轮**轮次新的在前**（与整体同一个「新在前」方向）。
行模型不变（不做跨轮合并/累加 —— 面板是状态面板，不是统计）。

★ 判卡死的阈值**不再硬写**（T-G97）：有工具在飞时静默是**预期**的（全量门禁 ~4 分钟、
冷缓存 worktree 里 `ui_flow` 十几分钟），旧写法会把正常的长调用误标成「可能卡死」。
现在**复用派活器**（`wb_dispatch`）的 `inflight_tool()` / `tool_durations()` /
`stall_threshold_seconds()` —— **不在面板里写第二份口径**；行里多显示"在跑什么 / 本次阈值"。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# 根路径从**本文件位置**推出来（tools/ 的上一级），不硬编码盘符。
TOOLS = Path(__file__).resolve().parent
# 复用 `wb_status.py` 的时间线/摘要解析器 —— 不写第二份（卡 §2.5）。
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import wb_dispatch  # noqa: E402 —— 判卡死复用派活器的口径（同一个 tools/ 目录）
import wb_status  # noqa: E402 —— 需要先把 tools/ 挂到 sys.path

ROOT = TOOLS.parent

QUIET = 60           # 静默 ≥ 这么久 = "安静一下"（可能在长思考，也可能要出事，秒）
# ★ 判卡死的**底线**不再在面板里写死 —— 取派活器那个数（480）。
#   真正的"本次阈值"由 `wb_dispatch.stall_threshold_seconds()` 算：有工具在飞 → 上抬到 30 分钟；
#   再按 `max(底线, 2.5 × 历史最长一次已完成调用)` 自适应（T-G94）。面板不抄公式，只调它。
STALL_BASE = wb_dispatch.STALL_SECONDS


def _state(age: float, finished: bool, *,
           threshold: float = float(STALL_BASE)) -> tuple[str, str]:
    """（状态字, 颜色）—— 顺序：有收工证据 = 结束；否则按日志静默多久分档。

    `threshold` = **本次阈值**（分钟数不写死）：有工具在飞或历史调用很长时会被上抬，
    这样"正在跑一个长命令"不会被误标成"可能卡死"。
    """
    if finished:
        return "收工·结束", "done"
    if age < QUIET:
        return "在跑", "run"
    if age < threshold:
        return "安静", "quiet"
    return f"静默 {age / 60:.1f} 分钟（可能卡死）", "stall"


def _inflight_label(inflight: tuple[str, float] | None) -> str:
    """在飞的那一次报成人话：`在跑：<工具>（已跑 X 分钟）`；没有在飞 → 空串。"""
    if not inflight:
        return ""
    sig, ran = inflight
    return f"在跑：{sig}（已跑 {ran / 60:.1f} 分钟）"


def _turns(lines: list[str]) -> int:
    """回合数 = `assistant` 事件的 `message.id` 去重（与派活器同一口径）。"""
    ids: set[str] = set()
    for ln in lines:
        try:
            event = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("type") == "assistant":
            mid = (event.get("message") or {}).get("id")
            if mid:
                ids.add(str(mid))
    return len(ids)


def _tree_dirs(root: Path) -> list[tuple[str, Path]]:
    """要扫的 (树名, gates/diag 目录) —— 主树 + 每个 worktree（`.wt/*`）。

    树名 `""` = 本仓库；`.wt/004` = 那一棵 worktree。并发跑多个工人时每棵树各有自己的
    `gates/diag/`，少扫一棵就少一个工人（这正是做这块表的原因）。
    """
    trees: list[tuple[str, Path]] = [("", root / "gates" / "diag")]
    wt = root / ".wt"
    if wt.is_dir():
        for child in sorted(wt.iterdir()):
            if child.is_dir():
                trees.append((f".wt/{child.name}", child / "gates" / "diag"))
    return trees


_ROUND_SUFFIX = re.compile(r"^(?P<card>.+?)\.r(?P<n>\d+)$")


# ★ T-G137（卡 046）：`gates/diag/` 里这些文件**不是卡** —— 派活器（T-G114）每棵树落一份
#   用量账本 `wb-usage.jsonl`（只有 token 计数、没有事件流），`wb-*.jsonl` 通配会把它当成
#   一张叫 `usage` 的假卡：账本永远没有事件流 → 永远「静默 N 分钟（可能卡死）」
#   （9 棵树 9 行幻影，把真卡挤下去 —— 用户 2026-09-26 就是这么被吓到的）。
#   ★ 判据收拢在这一个具名常量 + `is_card_log()`，别散落成难找的字符串；
#   ★ 账本不改名、`wb_dispatch.py` 的落账逻辑不动 —— 面板适配账本，不是账本适配面板。
NON_CARD_LOGS = frozenset({"wb-usage.jsonl"})


def is_card_log(name: str) -> bool:
    """`gates/diag/` 里这个文件名算不算一张卡的 log —— 用量账本等非卡文件排除。"""
    return name not in NON_CARD_LOGS


def _read_log_lines(log: Path) -> list[str]:
    """读 log 的行，带容错（T-G137）：

    - 真 UTF-8 → 与从前一字不差（`read_text(utf-8)` 的行）；
    - 混进坏行（PowerShell `*>` 会写出 UTF-16 / 含 NUL 字节的行）→ **跳过那一条**，
      好行照常解析 —— 不许把「读不懂」显示成 `? 非 JSON 行：\\x00`；
    - 整份解不出 → 返回空列表，调用方如实标「日志不可解析」，**不许**判成「可能卡死」。
    """
    data = log.read_bytes()
    if b"\x00" not in data:
        try:
            return data.decode("utf-8").splitlines()
        except UnicodeDecodeError:
            pass                                    # 非 UTF-8 → 退到按行救
    lines: list[str] = []
    for chunk in data.split(b"\n"):
        try:
            text = chunk.decode("utf-8")
        except UnicodeDecodeError:
            continue                                # 非 UTF-8 的行 → 跳过
        if "\x00" in text:
            continue                                # 含 NUL 的行 → 跳过
        lines.append(text.rstrip("\r"))
    return lines


def _split_card(name: str) -> tuple[str, int]:
    """文件名里的卡标识拆成 (卡号, 第几轮)：`004.r2` → (`004`, 2)；`004` → (`004`, 1)。

    轮次只认文件名后缀（`r2`/`r3` 本来就是单调的）—— ★ 不拿 `st_ctime` 当"第几轮"：
    Windows 上 ctime 是创建时间、复制/覆盖会重置（卡 §7-1）。
    """
    m = _ROUND_SUFFIX.match(name)
    if m:
        return m.group("card"), int(m.group("n"))
    return name, 1


def discover_logs(root: Path) -> list[tuple[str, str, Path]]:
    """(树名, 卡标识, log 路径) —— 多卡多树一次找齐。

    卡标识 = 文件名里的卡号（含 `.r2` 这类续跑后缀）。
    ★ 行序（T-G123，卡 030）：**最新在前** —— 按「卡组」（同树 + 同卡）分组，
    组的次序 = 组内最后一次活动的时间（mtime）**降序**，刚动过的卡在最上面；
    同一张卡的各轮**仍相邻**（T-G113 的一行一轮/相邻口径不破）且**轮次新的在前**
    （r2 在第 1 轮上面 —— 与整体同一个「新在前」方向，不另搞一套）；
    等值行再按（树名, 卡号）定**稳定**次序，刷新时不许跳。
    """
    found: list[tuple[str, str, Path]] = []
    for tree, diag in _tree_dirs(root):
        if not diag.is_dir():
            continue
        for log in diag.glob("wb-*.jsonl"):
            if not is_card_log(log.name):           # ★ T-G137：用量账本等非卡文件排除
                continue
            card = log.name.removeprefix("wb-").removesuffix(".jsonl")
            found.append((tree, card, log))
    # ★ T-G123：组键 = (树名, 卡号)，组时间 = 组内最新的 mtime；组按它降序。
    latest: dict[tuple[str, str], float] = {}
    for tree, card, log in found:
        key = (tree, _split_card(card)[0])
        latest[key] = max(latest.get(key, float("-inf")), log.stat().st_mtime)
    found.sort(key=lambda e: (
        -latest[(e[0], _split_card(e[1])[0])],      # 组最新活动降序 → 最新在最上面
        e[0], _split_card(e[1])[0],                 # 等值 →（树名, 卡号）的稳定次序
        -_split_card(e[1])[1],                      # 同卡各轮相邻，轮次新的在前
    ))
    return found


def card_state(root: Path | None = None) -> list[dict]:
    """每张卡一行 —— 多卡并发时就是多行。`root` 默认本文件推出来的仓库根。"""
    root = Path(root) if root is not None else ROOT
    now = time.time()
    rows: list[dict] = []
    for tree, card, log in discover_logs(root):
        _base, rnd = _split_card(card)
        st = log.stat()
        verdict = log.with_suffix(".verdict.txt")
        heartbeat = log.with_suffix(".heartbeat.txt")
        session = log.with_suffix(".session.txt")
        age = now - st.st_mtime
        lines = _read_log_lines(log)
        # ★ T-G137：整份解不出（有内容但一行都读不进来，如 PowerShell `*>` 写出的 UTF-16）
        #   → 如实标「日志不可解析」，不许按静默时长把它判成「可能卡死」。
        unparseable = not lines and st.st_size > 0
        timeline, summary = wb_status.parse_events(lines)
        shown = [ln for ln in timeline if ln.strip()]
        # ★ 判卡死的阈值**复用派活器**（T-G97）：有工具在飞 → 静默是预期的（底线上抬到 30 分钟）；
        #   再按"历史最长一次已完成调用 × 2.5"自适应 —— 面板不自己算，只调它。
        inflight = wb_dispatch.inflight_tool(lines, now=now)
        threshold = wb_dispatch.stall_threshold_seconds(
            stall_seconds=STALL_BASE, inflight=inflight,
            durations=wb_dispatch.tool_durations(lines))
        # ★ "收工"有两个来源：**判决文件**，**或日志里已经出现了 `result` 事件** ——
        #   老卡没有判决文件，少了第二条就会把早已收工的卡误报成"静默 N 分钟（可能卡死）"。
        #   日志整份解不出 →「日志不可解析」（T-G137），如实优先于推断。
        state, color = (("日志不可解析", "quiet") if unparseable else
                        _state(age, verdict.exists() or bool(summary["final"]),
                               threshold=threshold))
        models = list(dict.fromkeys(summary["models"]))
        rows.append({
            # 跨树时带上树名（如 `004@.wt/004`），免得两张卡同号时看串。
            "card": f"{card}@{tree}" if tree else card,
            "tree": tree,
            # ★ T-G113（口径 B）：续跑第几轮（无 `.rN` 后缀 = 第 1 轮）；「第 N 轮」标识靠它。
            "round": rnd,
            "log": log.name,
            "state": state,
            "color": color,
            "elapsed_min": round((now - st.st_ctime) / 60, 1),
            "silent_s": round(age),
            "events": len(lines),
            "turns": _turns(lines),
            "tool_calls": summary["tool_calls"],
            "tools": summary["tools"],
            "errors": summary["tool_errors"],
            "files_total": summary["files_total"],
            "model": ", ".join(models) or "（还没 init）",
            "session": (session.read_text(encoding="utf-8").strip()[:8]
                        if session.exists() else ""),
            "heartbeat": (heartbeat.read_text(encoding="utf-8").strip()
                          if heartbeat.exists() else ""),
            "verdict": (verdict.read_text(encoding="utf-8").strip()
                        if verdict.exists() else ""),
            "last": shown[-1].strip() if shown else "",
            "final": summary["final"] or "",
            "size_kb": round(st.st_size / 1024, 1),
            # ★ T-G97 新增两字段（既有字段名一个没改）：让主控一眼看出"真卡死 vs 正在跑长命令"。
            "inflight": _inflight_label(inflight),
            "threshold_min": round(threshold / 60, 1),
        })
    return rows


def api_state(root: Path | None = None) -> dict:
    """/api/state 的机器可读正文 —— 抽出来是为了能在测试里直接验结构（不起服务）。"""
    return {"now": time.strftime("%H:%M:%S"), "cards": card_state(root)}


PAGE = """<!doctype html><meta charset="utf-8"><title>工人状态</title>
<style>
 body{font:14px/1.5 ui-monospace,Consolas,monospace;background:#0f1117;
      color:#e6e6e6;margin:0;padding:18px}
 h1{font-size:16px;margin:0 0 12px;font-weight:600}
 table{border-collapse:collapse;width:100%}
 th,td{border-bottom:1px solid #23262f;padding:7px 9px;text-align:left;vertical-align:top}
 th{color:#8b93a7;font-weight:600;font-size:12px}
 .run{color:#3fb950}.done{color:#58a6ff}.quiet{color:#d29922}.stall{color:#f85149}
 .pill{border-radius:10px;padding:1px 8px;background:#1b1f27}
 .dim{color:#8b93a7}.small{font-size:12px}
 pre{white-space:pre-wrap;margin:0;color:#c9d1d9}
</style>
<h1>工人状态 <span class="dim small" id="at"></span></h1>
<div id="tbl">加载中…</div>
<script>
async function tick(){
  const r = await fetch('/api/state'); const d = await r.json();
  document.getElementById('at').textContent = '· ' + d.now;
  if(!d.cards.length){document.getElementById('tbl').textContent='还没有任何 wb-*.jsonl';return}
  let h='<table><tr><th>卡</th><th>状态</th><th>已跑</th><th>回合</th><th>工具</th><th>报错</th>'+
        '<th>文件</th><th>静默</th><th>在跑 / 阈值</th><th>模型</th><th>最后一步</th></tr>';
  for(const c of d.cards){
    h += `<tr><td><b>${c.card}</b> <span class="pill small">第 ${c.round} 轮</span>`+
         `<div class="dim small">${c.log} · ${c.size_kb} KB`+
         `${c.session?' · 会话 '+c.session:''}</div></td>`+
         `<td class="${c.color}">${c.state}</td><td>${c.elapsed_min} 分</td><td>${c.turns}</td>`+
         `<td>${c.tool_calls}</td><td>${c.errors}</td><td>${c.files_total}</td>`+
         `<td>${c.silent_s} 秒</td>`+
         `<td class="small">${c.inflight?'<div>'+c.inflight+'</div>':''}`+
         `<div class="dim">阈值 ${c.threshold_min} 分</div></td>`+
         `<td class="small">${c.model}</td>`+
         `<td class="small"><pre>${c.last}</pre>`+
         `${c.heartbeat?'<div class="dim small">'+c.heartbeat+'</div>':''}`+
         `${c.verdict?'<div class="small">'+c.verdict.split('\\n')[0]+'</div>':''}</td></tr>`;
  }
  document.getElementById('tbl').innerHTML = h+'</table>';
}
tick(); setInterval(tick, 2000);
</script>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:                       # noqa: N802 —— BaseHTTPRequestHandler 的约定
        if self.path.startswith("/api/state"):
            body = json.dumps(api_state(), ensure_ascii=False).encode("utf-8")
            ctype = "application/json; charset=utf-8"
        else:
            body = PAGE.encode("utf-8")
            ctype = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass                                        # 别把每条请求都打到控制台


def main() -> int:
    ap = argparse.ArgumentParser(description="工人状态面板（只读 gates/diag 里的状态文件）")
    ap.add_argument("--port", type=int, default=8787, help="监听端口（默认 8787）")
    ap.add_argument("--host", default="127.0.0.1", help="监听地址（默认只绑回环）")
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"工人状态面板：http://{args.host}:{args.port}  （Ctrl+C 停）", flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
