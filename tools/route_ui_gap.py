"""界面可达性核对：**后端有路由、前端一个字都没提**的接口有哪些（报告工具，不进质量门）。

为什么需要它：台账里有一条元卡 `DELIVERY.READY`「后端能力都要有界面入口（可达性）」——
它的 gaps 一直靠**人眼**写（"白名单/子任务还没有入口"），于是写过就漂了：那两处界面早就接上，
gaps 还留着老话（2026-09-23 T-G18 更正）。机器能查的别靠人眼。

判定方式（三段都在实测里踩过，才写成现在这样）：
  ① 后端 `{task_id}` 与前端模板 `${id}` 都收敛成通配段 `*`，**按段**比对；
     只做字符串包含会把 `/api/tasks/${id}/complete` 判成"没人用"。
  ② 前端路径先切掉 `?query`，否则 `/api/gpa?scale=${s}` 的最后一段变成 `gpa?scale=*`，永远匹配不上。
  ③ 前端的末段也可能是变量（状态动作 `/api/tasks/${id}/${verb}`）→ 通配段对通配段也算命中。

用法：
    python -X utf8 tools/route_ui_gap.py            # 列出没人用的路由（人读）
    python -X utf8 tools/route_ui_gap.py --ack ai,health
                                                     # 把"按设计就不给界面"的排除掉

注意：本工具**只报告、不做判定**（退出码永远 0）。要把它做成门禁第 12 项，
得先把"哪些路由允许没有界面"写成受维护的白名单 —— 属门禁口径变更，需用户拍板。
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "src" / "timeflow" / "api" / "app.py"
WEB = ROOT / "src" / "web"

ROUTE_RE = re.compile(r'@app\.(get|post|patch|delete|put)\("([^"]+)"')
FE_RE = re.compile(r"/api/[^\s\"'`)]*")

# 已裁定的路由：后端**留着**、但按裁定不接界面 —— 每条都带出处，别再当"未声明的尾巴"报。
# （T-G125：这两条早就裁定过，只是没进这张表，于是每跑一次都当新尾巴报一遍。）
DECIDED: dict[tuple[str, str], str] = {
    ("GET", "/api/team/assignments"):
        "保持现状（已被 /api/team/board 取代）—— 复盘/口径落档-T-G19.md",
    ("POST", "/api/sync/tasks"):
        "已弃用（deprecated，2026-09-25 用户确认）—— src/timeflow/api/app.py 注释",
}


def backend_routes() -> set[tuple[str, str]]:
    src = APP.read_text(encoding="utf-8")
    return {(m.group(1).upper(), m.group(2)) for m in ROUTE_RE.finditer(src)}


def frontend_source() -> str:
    out = ""
    for path in sorted(WEB.glob("*")):
        if path.suffix in {".html", ".js"}:
            out += path.read_text(encoding="utf-8", errors="ignore")
    return out


def segments(path: str) -> list[str]:
    """路径 → 段（`{task_id}` / `${id}` 都成 `*`；`?query` 丢掉）。"""
    path = path.split("?")[0]
    path = re.sub(r"\$\{[^}]*\}", "*", path)
    path = re.sub(r"\{[^}]*\}", "*", path)
    return [s for s in path.split("/") if s]


def matches(caller: list[str], route: list[str]) -> bool:
    if len(caller) != len(route):
        return False
    return all(a == "*" or b == "*" or a == b for a, b in zip(caller, route, strict=True))


def main() -> int:
    ap = argparse.ArgumentParser(description="列出没有前端入口的后端路由")
    ap.add_argument(
        "--ack", default="", help="逗号分隔的关键字：命中的路由不计入结论文本（如 ai,health）"
    )
    args = ap.parse_args()
    ack = [x.strip() for x in args.ack.split(",") if x.strip()]

    routes = backend_routes()
    callers = [segments(m.group(0)) for m in FE_RE.finditer(frontend_source())]
    missing = sorted(
        (meth, path)
        for meth, path in routes
        if not any(matches(c, segments(path)) for c in callers)
    )
    declared = [m for m in missing if (m[0], m[1]) in DECIDED or any(a in m[1] for a in ack)]
    print(f"后端路由 {len(routes)} 条 / 前端没提到 {len(missing)} 条"
          f"（已声明 {len(declared)} / 未声明 {len(missing) - len(declared)}）")
    for meth, path in missing:
        reason = DECIDED.get((meth, path))
        if reason:
            tag = f"（已声明：{reason}）"
        else:
            tag = "（已声明按设计不给界面）" if any(a in path for a in ack) else ""
        print(f"  {meth:6} {path} {tag}".rstrip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
