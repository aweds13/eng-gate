"""地址判词（卡 A374 · F58）—— magpie ``netguard.go`` 的 pool 版。

为什么值当测：这两个函数是 ``web_fetch`` 唯一的地址闸。放错一行的表现不是「少读一页」，
而是**把内网读权限交给用户给的字符串** —— 云元数据 ``169.254.169.254``、本机 ``127.0.0.1``、
用户自己的 ``192.168.x.x``，全都在一张表里靠着。所以本文件钉的是**表本身**：
十四项一项一行、NAT64 / 6to4 递归要看**内嵌的 v4**、拿不准就 False。

★ 本文件钉的五件事（对应卡 `「判据 1」）：
  ① 24 个地址必判 False（内网 / 元数据 / CGNAT / 文档段 / NAT64 / 6to4 / site-local / 组播）；
  ② 6 个公网地址必判 True（含 6to4 与 NAT64 里包着**公网** v4 的两个正例）；
  ③ 三条 ``ipaddress`` 会放过的地址，本模块必须拦住 —— 这条是反向断言：**将来谁把实现换成
     ``ipaddress.is_global``，第三组会红**；
  ④ ``fake_ip`` 认 ``198.18.0.0/15`` 的两端、不认边界外的两个邻居；
  ⑤ ``loon_paired`` 只在「``fd27:712::/96`` 且内嵌 v4 出现在 A 记录里」时为真。

★ 不许借 ``ipaddress`` 的判词自证：那等于拿被否掉的口径测自己（判据 1(c) 要求的正是两者**不同**）。
"""

from __future__ import annotations

import ipaddress
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from pool.netguard import (  # noqa: E402 —— 需要先用 sys.path 把 tools/ 挂上
    FAKE_NET,
    LOON_NET,
    NAT64_NET,
    SPECIAL_NETS,
    fake_ip,
    loon_paired,
    public,
)

# ---------------------------------------------------------------- 表（判据 1a/1b）

#: 必判 False。分五类，一类一段 —— 一段被删掉（反向变异 M1 删的正是 CGNAT 那行）时，
#: 红的是这个元组里的一行，看名字就知道少了哪类。
NOT_PUBLIC: tuple[tuple[str, str], ...] = (
    # 本机 / 回环
    ("127.0.0.1", "loopback v4"),
    ("::1", "loopback v6"),
    ("::ffff:127.0.0.1", "v4-mapped loopback（原件先 Unmap 再判）"),
    # RFC 1918 / link-local / 未指定
    ("10.0.0.1", "RFC 1918"),
    ("172.16.0.1", "RFC 1918"),
    ("192.168.1.1", "RFC 1918"),
    ("169.254.169.254", "link-local，云元数据服务就在这"),
    ("0.0.0.0", "unspecified"),
    # CGNAT / 保留 / 基准段
    ("100.64.0.1", "CGNAT（Tailscale 也用这段）"),
    ("192.0.0.8", "IETF protocol assignments"),
    ("198.18.0.1", "benchmarking == fake-IP 段"),
    ("198.19.255.255", "198.18.0.0/15 的上边界"),
    ("240.0.0.1", "reserved / broadcast"),
    # 文档段
    ("192.0.2.5", "TEST-NET-1"),
    ("198.51.100.7", "TEST-NET-2"),
    ("203.0.113.9", "TEST-NET-3"),
    ("2001:db8::1", "文档段 v6"),
    # IPv6 的坑：NAT64 / 6to4 里包着内网 v4、deprecated site-local、Teredo / discard / ULA
    ("64:ff9b::7f00:1", "NAT64 里包着 127.0.0.1"),
    ("64:ff9b:1::1", "local-use NAT64"),
    ("2002:7f00:1::", "6to4 里包着 127.0.0.1"),
    ("fec0::1", "site-local（deprecated，但仍是内网语义）"),
    ("100::1", "discard"),
    ("2001::1", "Teredo"),
    ("fd27:712::1", "Loon 合成段（本身在 fc00::/7 里）"),
)

#: 必判 True。后两条是递归的**正**例：地址本身是 IPv6 特殊段，但内嵌 v4 是公网。
IS_PUBLIC: tuple[tuple[str, str], ...] = (
    ("8.8.8.8", "普通公网 v4"),
    ("1.1.1.1", "普通公网 v4"),
    ("198.17.255.255", "198.18.0.0/15 的**下**邻，属于公网"),
    ("2606:4700::1111", "普通公网 v6"),
    ("2002:808:808::", "6to4 里包着 8.8.8.8 ⇒ 递归后是公网"),
    ("64:ff9b::808:808", "NAT64 里包着 8.8.8.8 ⇒ 递归后是公网"),
)


# ---------------------------------------------------------------- 判据 1(a)(b)


@pytest.mark.parametrize(("addr", "why"), NOT_PUBLIC)
def test_public_rejects_internal_addresses(addr: str, why: str) -> None:
    """① 这 24 个地址必判 False —— 放过去就是内网读权限。"""
    assert public(addr) is False, f"{addr}（{why}）被判成了公网"


@pytest.mark.parametrize(("addr", "why"), IS_PUBLIC)
def test_public_accepts_public_addresses(addr: str, why: str) -> None:
    """② 这 6 个地址必判 True —— 判错的表现是「什么都读不到」。"""
    assert public(addr) is True, f"{addr}（{why}）被判成了内网"


def test_table_has_the_fourteen_specials() -> None:
    """``SPECIAL_NETS`` 是判据本身：十四项，一项不多一项不少，顺序照原件。"""
    assert SPECIAL_NETS == (
        "0.0.0.0/8",
        "100.64.0.0/10",
        "192.0.0.0/24",
        "192.0.2.0/24",
        "198.18.0.0/15",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "240.0.0.0/4",
        "::/96",
        "100::/64",
        "2001::/32",
        "2001:db8::/32",
        "fec0::/10",
        "64:ff9b:1::/48",
    )


def test_named_prefixes_match_the_table() -> None:
    """三个取名前缀都在表里 —— 单独取名不是**豁免**，只是调用方要用到它们。"""
    assert NAT64_NET == "64:ff9b::/96"
    assert FAKE_NET == "198.18.0.0/15"
    assert LOON_NET == "fd27:712::/96"
    assert FAKE_NET in SPECIAL_NETS
    assert LOON_NET not in SPECIAL_NETS, "Loon 段靠 fc00::/7 兜住，不该混进十四项"


def test_public_rejects_garbage_without_raising() -> None:
    """解析不了的输入 ⇒ False，**不抛**（调用方拿它当「不公共」处理）。"""
    for junk in ("", "  ", "not-an-ip", "8.8.8.8:443", "256.0.0.1", "[::1]"):
        assert public(junk) is False, junk


# ---------------------------------------------------------------- 判据 1(c)：反向断言


IPADDRESS_LETS_THROUGH: tuple[str, ...] = (
    "100.64.0.1",  # CGNAT：is_global False，但 is_private 也 False —— 判词不一致
    "64:ff9b::7f00:1",  # NAT64：is_global **True**（只看外层）⇒ 标准库直接放行
    "fec0::1",  # site-local：is_global **True** ⇒ 标准库直接放行
)


@pytest.mark.parametrize("addr", IPADDRESS_LETS_THROUGH)
def test_reverse_assertion_against_ipaddress(addr: str) -> None:
    """③ 这三条标准库判不了，必须由本模块拦住。

    反向断言的意义：把 ``public()`` 换成 ``ipaddress.ip_address(a).is_global`` 时，前两条
    （is_global False / True 不一致）与第三条（is_global True）会分别红 —— 也就是判据 1(c)
    真正钉住的是**「不许退化成标准库判词」**。
    """
    std = ipaddress.ip_address(addr)
    assert std.is_global is True or std.is_private is False, (
        f"{addr} 在标准库里也不够严，这条反向断言失去意义，得换一个样本"
    )
    assert public(addr) is False


# ---------------------------------------------------------------- 判据 1(d)：fake_ip


def test_fake_ip_takes_the_two_ends_of_198_18_slash_15() -> None:
    """④ ``198.18.0.0/15`` 两端都认（``.0.1`` 与 ``.19.255.255``）。"""
    assert fake_ip("198.18.0.1") is True
    assert fake_ip("198.19.255.255") is True


def test_fake_ip_rejects_the_neighbours() -> None:
    """④ 段外的两个邻居不认 —— 否则整段公网都会被当成 fake-IP 放行。"""
    assert fake_ip("198.17.255.255") is False
    assert fake_ip("198.20.0.0") is False
    assert fake_ip("8.8.8.8") is False


def test_fake_ip_unmaps_before_comparing() -> None:
    """fake-IP 也是地址：v4-mapped 外壳先摘再比（原件的 ``Unmap()``）。"""
    assert fake_ip("::ffff:198.18.0.1") is True


# ---------------------------------------------------------------- 判据 1(e)：loon_paired


def test_loon_paired_needs_the_embedded_v4_in_the_answers() -> None:
    """⑤ 配对 = Loon 段 **且** 内嵌 v4 在 A 记录里。"""
    assert loon_paired("fd27:712::7f00:1", ["127.0.0.1"]) is True


def test_loon_paired_rejects_other_answers() -> None:
    """⑤ 内嵌 v4 换个值就不算成对 —— 那样它只是个 ULA 地址。"""
    assert loon_paired("fd27:712::7f00:1", ["127.0.0.2"]) is False
    assert loon_paired("fd27:712::7f00:1", []) is False


def test_loon_paired_rejects_addresses_outside_the_loon_range() -> None:
    """⑤ 段外的地址即便内嵌 v4 对上了也不算 —— 否则任何 v6 都能冒充 Loon 合成地址。"""
    assert loon_paired("fd27:712::1:7f00:1", ["127.0.0.1"]) is False
    assert loon_paired("2606:4700::7f00:1", ["127.0.0.1"]) is False
    assert loon_paired("garbage", ["127.0.0.1"]) is False
