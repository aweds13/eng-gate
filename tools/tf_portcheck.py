"""端口段体检（铁律 37）—— 检查 `BASE..BASE+span-1` 整段是否空闲。

★ 这个文件是 `gates/diag/_portcheck.py`（51 行、已在用、逻辑是对的）的**提升版**：
`gates/diag/` 是 gitignore 的，所以真身必须进版本库 —— 老入口留着只当门牌。

为什么是 `BASE..BASE+16`（默认 span=17）：行为流 ㉒ 要起「另一台设备」当对端，
对端走 `BASE+16`；实测 9197 被外来常驻服务 `vivoesService_x64.exe` 占着 → ㉒ 稳定报
`fetch failed`。所以派活前要**逐段**看 base..base+16 有没有被占，占用就点名 `端口 ← pid 进程名`。

用法：
    python -X utf8 tools/tf_portcheck.py --base 9191 --base 9221
    python -X utf8 tools/tf_portcheck.py 9191 9211 9221 9231   # 位置参数（兼容老入口）
    python -X utf8 tools/tf_portcheck.py --base 9191 --json      # 机器可读，给派活器调

退出码：全空闲 0；任一段内有占用 1。
★ 依赖：`psutil`（老入口 `_portcheck.py` 就在 import 它）。
"""
from __future__ import annotations

import argparse
import json
import sys

DEFAULT_SPAN = 17  # BASE..BASE+16：㉒ 的对端用 BASE+16
DEFAULT_BASES = [9191, 9211, 9221, 9231]  # 不给任何段时的候选段（与老入口一致）


def busy_ports() -> dict[int, str]:
    """本机监听中的 TCP 端口 → `pid=<pid> <进程名>`（进程名取不到就写 `?`）。"""
    import psutil

    out: dict[int, str] = {}
    for conn in psutil.net_connections(kind="tcp"):
        if conn.status != "LISTEN" or not conn.laddr:
            continue
        port = conn.laddr.port
        try:
            name = psutil.Process(conn.pid).name()
        except Exception:
            name = "?"
        out[port] = f"pid={conn.pid} {name}"
    return out


def segment_hits(base: int, span: int, busy: dict[int, str]) -> list[tuple[int, str]]:
    """`base..base+span-1` 里被占的端口（按端口升序），空列表 = 整段空闲。"""
    return [(p, busy[p]) for p in range(base, base + span) if p in busy]


def check_segments(bases: list[int], *, span: int = DEFAULT_SPAN,
                   busy: dict[int, str] | None = None) -> list[dict]:
    """逐段体检，返回每段一条的结构化结果（`busy` 可注入，测试用假端口表）。"""
    if busy is None:
        busy = busy_ports()
    results: list[dict] = []
    for base in bases:
        hits = segment_hits(base, span, busy)
        results.append({
            "base": base,
            "start": base,
            "end": base + span - 1,
            "busy": [{"port": port, "who": who} for port, who in hits],
        })
    return results


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="端口段体检（铁律 37）：逐段看 BASE..BASE+span-1 有没有被占")
    parser.add_argument("--base", action="append", type=int, default=None,
                        help="端口段起点（可重复给多段）")
    parser.add_argument("--span", type=int, default=DEFAULT_SPAN,
                        help=f"每段多少个端口（默认 {DEFAULT_SPAN}，不许写死）")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="机器可读输出（给派活器调）")
    parser.add_argument("bases", nargs="*", type=int,
                        help="位置参数的端口段起点（兼容老入口 _portcheck.py）")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    span = args.span
    if span <= 0:
        print(f"[FAIL] --span 必须是正数，收到 {span}", file=sys.stderr)
        return 2
    bases = list(args.base or []) + list(args.bases)
    if not bases:
        bases = list(DEFAULT_BASES)

    results = check_segments(bases, span=span)

    if args.as_json:
        print(json.dumps({"span": span, "segments": results,
                          "busy": any(seg["busy"] for seg in results)},
                         ensure_ascii=False), flush=True)
        return 1 if any(seg["busy"] for seg in results) else 0

    rc = 0
    for seg in results:
        base = seg["base"]
        if seg["busy"]:
            rc = 1
            print(f"  BASE={base}  ✗ 段内有占用：")
            for hit in seg["busy"]:
                print(f"      {hit['port']} ← {hit['who']}")
        else:
            print(f"  BASE={base}  ✅ {base}..{seg['end']} 全空闲")
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
