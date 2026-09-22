"""局域网访问 + 配对码（SR-NF17 / G 批 · T-G10b = 跨端场景 ②）。

**口径**（用户 2026-09-21 定，见 `复盘/口径定案-待定清单.md` §3）：
> **② 最后**：服务支持**显式开启**局域网访问（默认关，口径同 N16「默认收严、用户再放宽」）
> + **配对码**；开启时明确提示「同一 WiFi 下其他设备也可能访问到」。
> **边界**：局域网方案**只在同一个 WiFi 里管用**；不涉及公网（"出门实时"原文列为后置）。

三件事，都是"一处口径"：

1. **开关**：`[net] allow_lan`（默认 false）或 `python tools/serve.py --lan`。
   开 = 服务绑 `0.0.0.0` + 装配对门。**默认关时这里的一切都是空操作**（跟以前一模一样）。
2. **配对码**：非本机设备必须带 `X-Timeflow-Pair` 头才能读数据。
   6 位数字，存在本机库（`app_settings`），重启不变、可换一个。
   **只在本机（回环）的接口响应里出现** —— 不发给局域网设备（否则这道门等于没有）。
3. **门**：本机（回环）免检；静态壳（页面/CSS/JS/图标）免检（不然手机连"输配对码"那一页都打不开）；
   `/api/lan/pair` 免检（它就是拿来做配对的）；其余一律要码。

**为什么用"配对码"而不是账号密码**：这是单机个人工具，没有账号体系，也不想引入一个
（N16 本地优先、隐私最小）。配对码解决的是"同一 WiFi 下别人也能扫到这个地址"这一件事，
**它不是加密、也不挡同 WiFi 的抓包** —— 这句话写在界面与文档里，不装作它是别的东西。
`hmac.compare_digest` 只是别让比较耗时泄漏信息；真正防爆破的是失败节流（连续错太多次锁一会儿）。
"""

from __future__ import annotations

import hmac
import secrets
import time
from typing import TYPE_CHECKING, Any

from timeflow import logs

if TYPE_CHECKING:
    import sqlite3

    from starlette.requests import Request

# 设置键（`app_settings` 通用表，与 syncpack / ai 同一套机制）
KEY_CODE = "net.pairing_code"

# 配对码：6 位数字（手机上敲得动）；请求头名字
CODE_DIGITS = 6
HEADER = "X-Timeflow-Pair"

# 默认关时这段代码不参与任何判断；开着时这些路径**免检**
STATIC_SHELL: frozenset[str] = frozenset({
    "/", "/index.html", "/app.css", "/offline.js", "/sw.js", "/manifest.json",
    "/icon-192.png", "/icon-512.png", "/favicon.ico",
})
PAIR_PATH = "/api/lan/pair"

# 失败节流（进程内）：连续错 MAX_FAILS 次 → 锁 LOCK_SECONDS 秒。
# 为什么要有它：6 位数字只有 100 万种，没有节流的话同 WiFi 的人可以慢慢试。
MAX_FAILS = 20
LOCK_SECONDS = 300

_fails: dict[str, list[float]] = {}


def _now() -> float:
    return time.monotonic()


# ---------------------------------------------------------------- 开关与地址
def is_loopback(host: str | None) -> bool:
    """本机来源判定：`127.0.0.0/8` 与 `::1`（以及字面 `localhost`）。

    刻意**不**把 `0.0.0.0` 当本机：那是"监听所有网卡"的地址，不是来源地址。
    """
    if not host:
        return False
    h = host.strip().lower()
    if h in ("localhost", "::1", "::ffff:127.0.0.1"):
        return True
    return h.startswith("127.")


def is_static(path: str) -> bool:
    return path in STATIC_SHELL


def local_addresses(port: int = 8520) -> list[str]:
    """本机在局域网里的地址（给手机敲的那串）。

    拿法：起一个 UDP socket "连"一个外网地址 —— **不发任何包**，只是让系统挑出默认出口网卡，
    于是拿到它的 IP。拿不到就返回空列表（界面如实说"没查到"，不编一个地址出来）。
    """
    import socket

    found: list[str] = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("10.255.255.255", 1))
            found.append(str(s.getsockname()[0]))
        finally:
            s.close()
    except OSError:
        pass
    # 再列一遍本机网卡（可能有多个：有线 + 无线 + 虚拟网卡），去重且排除回环
    try:
        host = socket.gethostname()
        for info in socket.getaddrinfo(host, None, socket.AF_INET):
            addr = str(info[4][0])
            if not is_loopback(addr) and not addr.startswith("169.254.") and addr not in found:
                found.append(addr)
    except OSError:
        pass
    return [f"http://{a}:{port}" for a in found]


# ---------------------------------------------------------------- 配对码
def _get_raw(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return None if row is None else str(row["value"])


def _put_raw(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO app_settings (key, value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def new_code() -> str:
    """随机 6 位数字（密码学随机：`secrets` 只用于"猜不到"，不作别用）。"""
    return f"{secrets.randbelow(10 ** CODE_DIGITS):0{CODE_DIGITS}d}"


def peek_code(conn: sqlite3.Connection) -> str | None:
    """只看配对码，不生成、不落库（预览/只读接口用）。"""
    return _get_raw(conn, KEY_CODE)


def code(conn: sqlite3.Connection) -> str:
    """取本机配对码；没有就生成一个并记住（重启不变，所以手机不用每次重敲）。"""
    existing = peek_code(conn)
    if existing:
        return existing
    return rotate(conn)


def rotate(conn: sqlite3.Connection, value: str | None = None) -> str:
    """换一个配对码（或写入指定值）。返回生效的那个。"""
    fresh = normalize(value) if value is not None else new_code()
    _put_raw(conn, KEY_CODE, fresh)
    conn.commit()
    logs.log_event("lan_code_rotated", length=len(fresh))
    return fresh


def normalize(value: str) -> str:
    """规整并校验用户手填的配对码：只允许 4~16 位字母/数字（拒绝空、拒绝奇怪字符）。"""
    got = str(value or "").strip()
    if not 4 <= len(got) <= 16 or not got.isalnum():
        raise ValueError("配对码要 4~16 位字母或数字（别带空格和符号）")
    return got


def verify(conn: sqlite3.Connection, value: str | None) -> bool:
    """比对配对码（常数时间比较，别让耗时泄漏信息）。"""
    expected = peek_code(conn)
    if not expected or not value:
        return False
    return hmac.compare_digest(str(value), expected)


# ---------------------------------------------------------------- 失败节流
def locked(host: str) -> float:
    """这个来源还要锁多少秒（0 = 没锁）。"""
    hits = [t for t in _fails.get(host, []) if _now() - t < LOCK_SECONDS]
    _fails[host] = hits
    if len(hits) < MAX_FAILS:
        return 0.0
    remain = LOCK_SECONDS - (_now() - hits[0])
    return max(0.0, remain)


def note_failure(host: str) -> None:
    hits = [t for t in _fails.get(host, []) if _now() - t < LOCK_SECONDS]
    hits.append(_now())
    _fails[host] = hits
    logs.log_event("lan_pair_failed", fails=len(hits))


def reset_failures(host: str | None = None) -> None:
    """清掉失败计数（配对成功时清；测试也要能清）。"""
    if host is None:
        _fails.clear()
    else:
        _fails.pop(host, None)


# ---------------------------------------------------------------- 门（请求判定）
def gate(
    conn: sqlite3.Connection, host: str | None, path: str, provided: str | None
) -> dict[str, Any]:
    """判断一个请求能不能过。返回 `{"ok": bool, "reason": str, "paired": bool, "status": int}`。

    **纯函数式的判定**（不碰 request 对象），于是能用真值表一条条测：
    - 本机（回环）→ 永远放行（桌面自己用不该被自己的门挡住），`paired=False`
      —— 但**本机也不是"已配对设备"**：配对码的可见性靠这个区分（见 `status`）。
    - 静态壳 → 放行（否则手机连"输入配对码"那一页都打不开）；
    - `/api/lan/pair` → 放行（它就是拿来做配对的）；
    - 其余 → 必须带对的码；锁着的时候连对的码也先拒（防爆破）。
    """
    if is_loopback(host):
        return {"ok": True, "reason": "loopback", "paired": False, "status": 200}
    if is_static(path) or path == PAIR_PATH:
        return {"ok": True, "reason": "static_or_pair", "paired": False, "status": 200}
    remain = locked(host or "?")
    if remain > 0:
        return {
            "ok": False, "reason": "locked", "paired": False, "status": 429,
            "detail": f"配对码连续输错太多次了 —— 等 {int(remain)} 秒再试"
                      "（也可以在那台电脑上换一个配对码）",
        }
    if verify(conn, provided):
        return {"ok": True, "reason": "paired", "paired": True, "status": 200}
    return {
        "ok": False, "reason": "no_code", "paired": False, "status": 401,
        "detail": "这台设备还没和电脑配对：请在那台电脑的「设置 → 局域网访问」里看配对码，"
                  "在这台设备上输入一次（只在本机显示，不通过网络发送）。",
    }


def check_pair(conn: sqlite3.Connection, host: str | None, value: str | None) -> dict[str, Any]:
    """`POST /api/lan/pair` 的判定：对的码 → 清掉失败计数；错的码 → 记一次失败。"""
    remain = locked(host or "?")
    if remain > 0:
        return {"ok": False, "status": 429,
                "detail": f"配对码连续输错太多次了 —— 等 {int(remain)} 秒再试"}
    if verify(conn, value):
        reset_failures(host or "?")
        logs.log_event("lan_paired", host=str(host))
        return {"ok": True, "status": 200, "detail": "配对成功"}
    note_failure(host or "?")
    return {"ok": False, "status": 401, "detail": "配对码不对 —— 以那台电脑上显示的为准"}


# ---------------------------------------------------------------- 给界面的现状
def status(
    conn: sqlite3.Connection,
    *,
    lan_open: bool,
    config_allow_lan: bool,
    port: int,
    loopback: bool,
) -> dict[str, Any]:
    """局域网现状（**只报事实**）。

    ★ **配对码只在回环请求里出现**（`code`）：这是这道门的底线 ——
    局域网设备能看数据，但看不到"钥匙"本身。
    """
    return {
        "lan_open": lan_open,                 # 这台服务真的对局域网开着吗
        "config_allow_lan": config_allow_lan,  # 配置里怎么写的
        "pairing_required": lan_open,          # 开着才需要配对码
        "addresses": local_addresses(port) if lan_open else [],
        "code": code(conn) if loopback else "",   # ← 非本机请求永远是空串
        "code_visible": bool(loopback),
        "header": HEADER,
        "note": "局域网访问只在**同一个 WiFi 里**管用，不涉及公网；"
                "开着的时候，同一 WiFi 下的其他设备也可能扫到这个地址 —— 配对码是那道门。"
                "它是防「随手连一下」的，**不是加密、也不挡同 WiFi 抓包**。"
                "要开/关：改 config.toml 的 `[net] allow_lan` 后重启服务，"
                "或临时用 `python tools/serve.py --lan` 起一次。",
        "how_to_change": "改 config.toml 的 [net] allow_lan 后重启；或 python tools/serve.py --lan",
    }


def read_code_from(request: Request) -> str | None:
    """从请求里取配对码（头优先，其次查询串 —— 后者方便手工 curl 试一次）。"""
    got = request.headers.get(HEADER)
    if got:
        return got
    return request.query_params.get("pair")


def banner(port: int, code: str) -> list[str]:
    """开局域网时打印的那几行（**纯函数**：说什么、怎么说，一处；测试直接断言它）。

    为什么要打印这么多话：**"同一 WiFi 下别人也可能访问到"必须当着用户的面说一次** ——
    这叫"显式放宽"，和 N16 的口径一致（默认收严、用户再放宽，但放宽时要说明代价）。
    """
    addrs = local_addresses(port)
    lines = ["[局域网] 已开启：同一 WiFi 下的手机 / 平板可以打开下面这个地址"]
    lines += [f"         {a}" for a in addrs] or [
        "         （没查到局域网地址：确认这台电脑连着 WiFi / 网线）"
    ]
    lines += [
        f"[配对码] {code}   （那台设备第一次打开会问它；"
        "这台电脑的「设置 → 局域网访问」里也能看到）",
        "[提醒] 同一 WiFi 下的其他设备也可能访问到这个地址 —— 配对码是那道门，别念给别人；",
        "       它防的是「随手连一下」，**不是加密、也不挡同 WiFi 抓包**。",
        "       只在同一个 WiFi 里管用，不涉及公网。",
        "[关闭] 去掉 --lan（或把 config.toml 的 [net] allow_lan 改成 false）后重启即可。",
    ]
    return lines
