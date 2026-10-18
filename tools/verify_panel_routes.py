"""DSH 全局面板：运行时路由体检（重启后再跑这个）。

用法：`python -X utf8 gates/diag/verify_panel_routes.py`

判据（全绿才算面板宿主半真的加载了）：
- 本机在听的 GUI 端口上，`/dsh-panel/stack-status` 返回 200 且 JSON 里 `ok == true`；
- `/dsh-panel/skills` 返回 200 且 `items` 是列表；
- `/dsh-panel/workbench-board` 返回 200（`ok` 字段存在）。
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
        with urllib.request.urlopen(url, timeout=4) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")
    except Exception as error:  # noqa: BLE001 - 探测失败要如实报
        return 0, f"{type(error).__name__}: {error}"


CHECKS = (
    ("/dsh-panel/stack-status", lambda body: json.loads(body).get("ok") is True),
    ("/dsh-panel/skills", lambda body: isinstance(json.loads(body).get("items"), list)),
    ("/dsh-panel/workbench-board", lambda body: "ok" in json.loads(body)),
)


def main(argv: list[str]) -> int:
    ports = [int(argv[1])] if len(argv) > 1 else listening_ports()
    candidates = ports
    failures: list[str] = []
    for port in candidates:
        status, body = probe(port, "/dsh-panel/stack-status")
        if status != 200:
            continue
        print(f"  命中 GUI 端口 {port}")
        for path, accept in CHECKS:
            code, payload = probe(port, path)
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
                failures.append(f"{port}{path}: HTTP {code} {reason}")
        break
    else:
        failures.append("没有任何端口回 200 /dsh-panel/stack-status（宿主半没加载）")
        print("  ✗ 没找到能回 /dsh-panel/stack-status 的端口")

    if failures:
        print("\n[FAIL] 运行时路由未全绿：")
        for item in failures:
            print("  -", item)
        print("  ⇒ 先完全退出 DSH（含托盘）再重开，然后重跑本脚本。")
        return 1
    print("\n[OK ] 运行时路由全绿：宿主半已加载。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
