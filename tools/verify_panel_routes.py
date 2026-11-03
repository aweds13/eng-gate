"""DSH 全局面板：运行时路由体检（重启后再跑这个）。

用法：`python -X utf8 gates/diag/verify_panel_routes.py`

判据（全绿才算面板宿主半真的加载了）：
- 本机在听的 GUI 端口上，`/dsh-panel/stack-status` 返回 200 且 JSON 里 `ok == true`；
- `/dsh-panel/skills` 返回 200 且 `items` 是列表；
- `/dsh-panel/workbench-board` 返回 200（`ok` 字段存在）；
- `/dsh-panel/pool-daily` 返回 200 且 `reading` 里有 `to_dispatch`（卡 A366）；
- `/dsh-panel/pool-jobs` 返回 200 且 `reading.jobs` 是列表（卡 A366）；
- `/dsh-panel/pool-locks` 返回 200 且 `reading.locks` 是列表（卡 A366）。
任何一条不是 200 就打印红 + 说明「宿主半没加载或路由没挂上」。
"""

from __future__ import annotations

import contextlib
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request


def listening_ports() -> list[int]:
    """本机上处于 LISTENING 的端口（按 netstat 输出）。"""
    out = subprocess.run(
        ["netstat", "-ano"], capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    ).stdout
    ports = set()
    for line in out.splitlines():
        hit = re.search(r"LISTENING\s+\d+$", line.strip())
        if not hit:
            continue
        addr = line.split()[1]
        if ":" in addr:
            with contextlib.suppress(ValueError):
                ports.add(int(addr.rsplit(":", 1)[1]))
    return sorted(ports)


def probe(port: int, path: str) -> tuple[int, str]:
    url = f"http://127.0.0.1:{port}{path}"
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")
    except Exception as error:  # noqa: BLE001 - 探测失败要如实报
        return 0, f"{type(error).__name__}: {error}"


def _reading(body: str) -> dict:
    """取转发回来的工具读数（`{ok, route, reading}`）；形状不对给空 dict。"""
    payload = json.loads(body)
    reading = payload.get("reading") if isinstance(payload, dict) else None
    return reading if isinstance(reading, dict) else {}


CHECKS = (
    ("/dsh-panel/stack-status", lambda body: json.loads(body).get("ok") is True),
    ("/dsh-panel/skills", lambda body: isinstance(json.loads(body).get("items"), list)),
    ("/dsh-panel/workbench-board", lambda body: "ok" in json.loads(body)),
    ("/dsh-panel/pool-daily",
     lambda body: json.loads(body).get("ok") is True and "to_dispatch" in _reading(body)),
    ("/dsh-panel/pool-jobs",
     lambda body: json.loads(body).get("ok") is True
     and isinstance(_reading(body).get("jobs"), list)),
    ("/dsh-panel/pool-locks",
     lambda body: json.loads(body).get("ok") is True
     and isinstance(_reading(body).get("locks"), list)),
)


def main(argv: list[str]) -> int:
    """显式给端口就只探它；否则扫本机所有 LISTENING 端口，找**真正回面板读数**的那个。"""
    explicit = len(argv) > 1
    ports = [int(argv[1])] if explicit else listening_ports()
    failures: list[str] = []
    hit_port = 0
    for port in ports:
        status, body = probe(port, "/dsh-panel/stack-status")
        if status != 200:
            continue
        try:
            if json.loads(body).get("ok") is not True:
                continue
        except Exception:  # noqa: BLE001 - 200 但非 JSON ⇒ 不是面板，接着扫
            continue
        hit_port = port
        break

    if not hit_port:
        if explicit:
            failures.append(f"端口 {ports[0]} 没回 200 /dsh-panel/stack-status（宿主半没加载）")
        else:
            failures.append("没有任何端口回 200 /dsh-panel/stack-status（宿主半没加载）")
        print("  ✗ 没找到能回面板读数的端口")
    else:
        print(f"  命中 GUI 端口 {hit_port}")
        for path, accept in CHECKS:
            code, payload = probe(hit_port, path)
            ok = code == 200
            reason = ""
            if ok:
                try:
                    ok = bool(accept(payload))
                    reason = "" if ok else "200 但不是面板读数（JSON 断言不成立）"
                except Exception as error:  # noqa: BLE001 - 解析失败按红算
                    ok = False
                    reason = f"200 但解不出 JSON（{type(error).__name__}）"
            print(f"  {'✓' if ok else '✗'} {path} → HTTP {code} {reason or payload[:120]!r}")
            if not ok:
                failures.append(f"{hit_port}{path}: HTTP {code} {reason}")

    if failures:
        print()
        print("[FAIL] 运行时路由未全绿：")
        for item in failures:
            print("  -", item)
        print("  ⇒ 先完全退出 DSH（含托盘）再重开，然后重跑本脚本。")
        return 1
    print()
    print("[OK ] 运行时路由全绿：宿主半已加载。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
