"""地址判词：这个 IP 在不在公网。

magpie ``internal/netguard/netguard.go`` 的 Python 版（卡 A374 · F58）。

## 为什么有它

``web_fetch`` 的 URL 来自用户或模型。要读它，先得答一个问题：**这个地址是不是公网**。
答错的两种表现都不可接受 —— 放过内网地址（云元数据 ``169.254.169.254``、本机 ``127.0.0.1``、
用户的 ``192.168.x.x``）等于把「用户给的字符串」变成「内网的读权限」；把公网地址判成内网，
则整件事不成立（什么都读不到）。原件包注释把边界写得最清楚：它只判地址，名字怎么用由调用方定。
本模块逐字照这条边界：**只说地址**，不解析名字、不出网、不读盘、不读钟、不 print。

## 为什么不能一句标准库了事

``ipaddress`` 的 ``is_global`` / ``is_private`` 判不了原件的规则。本卡实测（Python 3.14.6）：

| 地址 | is_private | is_global | 本模块 |
|---|---|---|---|
| ``100.64.0.1`` | False | False | **False**（CGNAT，``100.64.0.0/10``） |
| ``64:ff9b::7f00:1`` | False | **True** | **False**（NAT64 里包着 127.0.0.1） |
| ``fec0::1`` | False | **True** | **False**（deprecated site-local，``fec0::/10``） |

所以 ``SPECIAL_NETS`` 十四项逐字照抄、NAT64 / 6to4 递归判内嵌 v4 —— **表就是判据**，
少一行就是放过一类地址（删 ``100.64.0.0/10`` 那一行正是本卡反向变异 M1）。

## 与 Go 原件的差异（如实，不是逐字相同）

1. ``IsPrivate`` 按 **Go 的口径**自己写（RFC 1918 三段 + ``fc00::/7``），**不用** Python 的
   ``is_private`` —— 后者把 ``2002:808:808::``（6to4 里包着 8.8.8.8）、``198.18.0.0/15`` 等一大批
   都算 private，会让「6to4 递归判内嵌 v4」这条失去意义（公网 6to4 地址会被误判成私网）。
   ``IsLoopback`` / ``IsLinkLocal*`` / ``IsMulticast`` / ``IsInterfaceLocalMulticast`` /
   ``IsUnspecified`` 同理，逐条写成前缀表（``_VETO_NETS``）。
2. 前缀包含用「整数 + 掩码」自己算。``ipaddress`` **只用来解析字符串**，不用它的判词语义。
3. 原件先 ``Unmap()`` 再判；这里用 ``IPv6Address.ipv4_mapped`` 做同一件事。
4. 只移植判词。原件第二层的 socket 钉地址与 fake-IP / Loon 的**放行路径**
   （``image_fetch_guard.go`` 的 ``publicTransport`` / ``guardDialer``）没有移植 —— 本仓不出网，
   那两条今天无处可验（卡规格未坐实项 3）。``fake_ip()`` / ``loon_paired()`` 回答的是
   「是不是那个形状」，**不是「能不能连」**。

## 用法

    from pool.netguard import fake_ip, loon_paired, public

    for answer in resolve(host):     # 名字回回来的每一个地址都要过这一关
        if not public(answer):
            raise ...

作者：T-AG662（卡 A374）
"""

from __future__ import annotations

import ipaddress
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

#: ``net/netip`` 自己判的那八类之外，**永不外连**的前缀（``netguard.go:10-33``）。
#: 顺序与注释照抄：这张表就是判据。已被别的判定覆盖的行（如 ``0.0.0.0/8`` 与 ``240.0.0.0/4``）
#: 也不省略 —— 省略会让下一个改表的人以为那行不重要。
SPECIAL_NETS: tuple[str, ...] = (
    "0.0.0.0/8",  # "this" network
    "100.64.0.0/10",  # CGNAT / Tailscale
    "192.0.0.0/24",  # IETF protocol assignments
    "192.0.2.0/24",  # documentation
    "198.18.0.0/15",  # benchmarking; a fake-IP resolver's range
    "198.51.100.0/24",  # documentation
    "203.0.113.0/24",  # documentation
    "240.0.0.0/4",  # reserved, broadcast
    "::/96",  # IPv4-compatible (deprecated)
    "100::/64",  # discard
    "2001::/32",  # Teredo
    "2001:db8::/32",  # documentation
    "fec0::/10",  # site-local (deprecated)
    "64:ff9b:1::/48",  # local-use NAT64
)

#: 原件单独取名的三个前缀（``netguard.go:35-39``）。
NAT64_NET = "64:ff9b::/96"
FAKE_NET = "198.18.0.0/15"
LOON_NET = "fd27:712::/96"

#: netip 自己判的那八类，一条前缀一行，注释点名它对应哪个 Go 判词（``netguard.go:48-51``）。
#: ★ 不借 ``ipaddress`` 的同名判词：口径不同会改变行为（见模块 docstring 第 1 条）。
_VETO_NETS: tuple[str, ...] = (
    "127.0.0.0/8",  # IsLoopback
    "::1/128",
    "10.0.0.0/8",  # IsPrivate（RFC 1918）
    "172.16.0.0/12",
    "192.168.0.0/16",
    "fc00::/7",
    "0.0.0.0/32",  # IsUnspecified
    "::/128",
    "169.254.0.0/16",  # IsLinkLocalUnicast（云元数据就在这一段）
    "fe80::/10",
    "224.0.0.0/24",  # IsLinkLocalMulticast
    "ff02::/16",
    "ff01::/16",  # IsInterfaceLocalMulticast
    "224.0.0.0/4",  # IsMulticast
    "ff00::/8",
)


def _ranges(nets: tuple[str, ...]) -> tuple[tuple[int, int, int], ...]:
    """前缀表 -> ``(网络号, 掩码, 位宽)``；``ipaddress`` 只负责解析字面量。"""
    out: list[tuple[int, int, int]] = []
    for spec in nets:
        base, _, bits = spec.partition("/")
        addr = ipaddress.ip_address(base)
        width = addr.max_prefixlen
        keep = int(bits)
        mask = 0 if keep == 0 else ((1 << width) - 1) ^ ((1 << (width - keep)) - 1)
        out.append((int(addr) & mask, mask, width))
    return tuple(out)


_SPECIAL_RANGES = _ranges(SPECIAL_NETS)
_VETO_RANGES = _ranges(_VETO_NETS)
_NAT64_RANGE = _ranges((NAT64_NET,))
_FAKE_RANGE = _ranges((FAKE_NET,))
_LOON_RANGE = _ranges((LOON_NET,))


def _parse(addr: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """解析成地址对象；先摘掉 v4-mapped 外壳（原件的 ``Unmap()``）。

    解析不了（空串、带端口、带空白、半截地址）⇒ ``None`` —— 调用方当「不公共」处理，**绝不抛**。
    """
    try:
        parsed = ipaddress.ip_address(addr)
    except ValueError:
        return None
    if isinstance(parsed, ipaddress.IPv6Address):
        mapped = parsed.ipv4_mapped
        if mapped is not None:
            return mapped
    return parsed


def _within(
    addr: ipaddress.IPv4Address | ipaddress.IPv6Address,
    ranges: tuple[tuple[int, int, int], ...],
) -> bool:
    """地址是否落在其中一段里（位宽不同的段直接跳过）。"""
    value = int(addr)
    width = addr.max_prefixlen
    return any(bits == width and (value & mask) == base for base, mask, bits in ranges)


def public(addr: str) -> bool:
    """``addr`` 在不在公网（``netguard.go:46-68`` 的逐条搬运）。

    八连判（无效 / 回环 / 私有 / 未指定 / link-local 单播 / link-local 组播 / 接口本地组播 /
    组播）-> ``SPECIAL_NETS`` 十四项 -> IPv6 的 NAT64（``64:ff9b::/96``，取第 12-15 字节）与
    6to4（``2002::/16``，取第 2-5 字节）**递归**判内嵌 v4。
    """
    parsed = _parse(addr)
    if parsed is None:
        return False
    if _within(parsed, _VETO_RANGES) or _within(parsed, _SPECIAL_RANGES):
        return False
    if isinstance(parsed, ipaddress.IPv6Address):
        packed = parsed.packed
        if _within(parsed, _NAT64_RANGE):
            return public(str(ipaddress.IPv4Address(packed[12:16])))
        if packed[0] == 0x20 and packed[1] == 0x02:  # 2002::/16
            return public(str(ipaddress.IPv4Address(packed[2:6])))
    return True


def fake_ip(addr: str) -> bool:
    """``addr`` 是不是 fake-IP resolver 的答案（``198.18.0.0/15``，``netguard.go:78``）。

    只答「是不是这个形状」。**放行路径没有移植**：原件在 ``publicTransport.RoundTrip`` 里对
    fake-IP 放行并钉住真名（卡规格未坐实项 3），本仓不出网，今天无处可验。
    """
    parsed = _parse(addr)
    return parsed is not None and _within(parsed, _FAKE_RANGE)


def loon_paired(addr: str, answers: Sequence[str]) -> bool:
    """``addr`` 是不是 Loon 为某个 A 记录合成的 AAAA，且那个 A 在 ``answers`` 里（``:85-96``）。

    形状：``fd27:712::/96``，内嵌 v4 在第 12-15 字节。``answers`` 里的地址先摘 v4-mapped 外壳再比
    （原件的 ``o.Unmap() == v4``）。不成对 ⇒ False；别的 ``fc00::/7`` 地址照样是私网。
    """
    parsed = _parse(addr)
    if parsed is None or not _within(parsed, _LOON_RANGE):
        return False
    target = ipaddress.IPv4Address(parsed.packed[12:16])
    return any(_parse(answer) == target for answer in answers)
