r"""F60 MCP hub **不移植**的反向钉子（卡 A379 · 台账号 T-AG667）—— 五条判据逐条钉「不在」。

★ 本文件钉的是**不移植**：F60 判 SKIP_NOT_APPLICABLE（不是 PORT、不是 SKIP_BY_REDLINE）——
  本仓**没有 hub 要替代的那个对象**（不写任何 agent 的 MCP 配置、不按 agent 分可见性），
  所以「实现 hub」这件事永远不做，五条判据全部是**反向钉子**：今天全绿，谁把 hub 的前提
  引进本仓，它们先红。判据表与论证见 复盘/卡/卡A379-F60-MCP-hub-判SKIP_NOT_APPLICABLE.md。

| 钉子 | 钉哪一位 |
|---|---|
| test_no_hub_concept_in_sources | 判据 1：hub 词表在 tools/、src/、scripts/ 源码里零命中 |
| — | 词表带词边界（光秃秃的 hub 会撞 github），文件名也不许叫这个 |
| test_transport_has_no_agent_dimension | 判据 2：build_server / serve_http 没有 agent 形参 |
| — | mcp_http 上也没有 HubMCPPath（静态路径表 ≠ per-agent 路由） |
| test_mcp_face_never_spawns_a_process | 判据 3：MCP 承载面两层不起子进程 |
| — | 那两层是 tools/pool/mcp_http.py 与 src/timeflow/mcp/server.py |
| test_no_idle_reclaim_timer | 判据 4：tools/ 与 src/ 没有空闲回收定时器 |
| — | hub 的 10 分钟空闲回收在本仓无落脚点 |
| test_no_agent_config_writer | 判据 5：不写任何 agent 的 MCP 配置、不产 deeplink |
| — | 含模块清单 docs/subsystems/pool/modules.toml 里也不许出现 mcpServers |

★ 本文件**只读源码与签名**：不起服务、不开 socket、不写盘 —— **一个字节都不出网**。
★ 词表只收**代码形状**（threading.Timer / subprocess / mcpServers 这种）；中文注释里写
  「定时器」「子进程」不算命中 —— 判据咬的是形状不是文字（安静对照 N1 就是钉这一条）。
"""

from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from pool import mcp_http  # noqa: E402 —— 需要先用 sys.path 把 tools/ 挂上

#: 判据 1 扫描的三根（**不含 tests/**：本文件自己就写着这些词）。
HUB_SCAN_ROOTS = ("tools", "src", "scripts")
#: 判据 4 / 5 扫描的两根。
PRODUCT_SCAN_ROOTS = ("tools", "src")

#: 判据 1 的词表。★ 必须带词边界：光秃秃的 hub 会撞上 github / .github/ 字样。
HUB_WORDS = re.compile(r"\b(MCPHub|mcp_hub|hubSep|hubIdle)\b")

#: 判据 3 的词表：MCP 面里出现任何一个 ⇒ 有人开始把 server 当子进程拉了。
FORBIDDEN_SPAWN = ("subprocess", "Popen", "os.system", "os.exec", "multiprocessing")

#: 判据 4 的词表：hub 的空闲回收（hubIdle = 10 * time.Minute + time.AfterFunc）那套机制。
FORBIDDEN_TIMER = ("threading.Timer", "Timer(", "AfterFunc")

#: 判据 5 的词表：写 agent 的 MCP 配置 / 产 deeplink 才会出现的字样。
FORBIDDEN_CONFIG = ("mcpServers", "mcp_servers", "cursor://", "vscode:mcp")


def _py_files(roots: tuple[str, ...]) -> list[Path]:
    """roots 下所有 *.py（跳过 __pycache__）。★ 根扫空了就**当场报错**：

    否则不存在的目录会让判据 1/4/5 空扫描通过 —— 那种绿是假的。
    """
    found: list[Path] = []
    for name in roots:
        base = ROOT / name
        assert base.is_dir(), f"扫描根不存在：{name}（判据会空扫通过，不许静默跳过）"
        files = [p for p in sorted(base.rglob("*.py")) if "__pycache__" not in p.parts]
        assert files, f"{name}/ 下一个 *.py 都没扫到（判据会空扫通过）"
        found.extend(files)
    return found


def _scan_texts(roots: tuple[str, ...]) -> list[tuple[str, str]]:
    return [
        (p.relative_to(ROOT).as_posix(), p.read_text(encoding="utf-8")) for p in _py_files(roots)
    ]


# ---------------------------------------------------------------- 判据 1：hub 概念零命中


def test_no_hub_concept_in_sources() -> None:
    """★ 反向钉子：谁加了 MCPHub 类 / hubIdle 常量 / hubSep 命名，这条必须变红。"""
    hits: list[str] = []
    for rel, text in _scan_texts(HUB_SCAN_ROOTS):
        for lineno, line in enumerate(text.splitlines(), start=1):
            if HUB_WORDS.search(line):
                hits.append(f"{rel}:{lineno}: {line.strip()}")
    assert hits == [], f"源码里出现了 hub 概念（F60 判 SKIP_NOT_APPLICABLE）：{hits}"

    named = [
        p.relative_to(ROOT).as_posix()
        for p in _py_files(HUB_SCAN_ROOTS)
        if HUB_WORDS.search(p.stem)
    ]
    assert named == [], f"有人建了以 hub 命名的模块（判据 1 盯的正是这件事）：{named}"


# ---------------------------------------------------------------- 判据 2：没有 per-agent 维度


def test_transport_has_no_agent_dimension() -> None:
    """★ 反向钉子：给 build_server / serve_http 加一个 agent 形参，这条必须变红。"""
    for func in (mcp_http.build_server, mcp_http.serve_http):
        sig = inspect.signature(func)
        names = {name.lower() for name in sig.parameters}
        assert "agent" not in names, (
            f"{func.__name__}() 出现 per-agent 维度（{sorted(names)}）—— "
            "hub 的入口形状是 /mcp/magpie/hub/{agent}，本仓不做"
        )
    assert not hasattr(mcp_http, "HubMCPPath"), (
        "mcp_http 上出现了 HubMCPPath —— hub 的协议面正在被搬进来"
    )


# ---------------------------------------------------------------- 判据 3：MCP 面不起子进程


def test_mcp_face_never_spawns_a_process() -> None:
    """★ 反向钉子：在 MCP 承载面里 import subprocess（或 Popen / os.system），这条必须变红。

    ★ 不扫 tools/pool_mcp.py：它今天有 20 处 subprocess|Popen，全是 CLI 子进程
      （门禁锁 / 起工人 / task claim），拿它当对象这条判据今天就是红的 —— 那是断言写错。
      要钉的是「MCP server 不被当子进程拉起」，承载面就是下面这两个文件。
    """
    sources = {
        "tools/pool/mcp_http.py": inspect.getsource(mcp_http),
        "src/timeflow/mcp/server.py": (ROOT / "src" / "timeflow" / "mcp" / "server.py").read_text(
            encoding="utf-8"
        ),
    }
    for rel, text in sources.items():
        hits = [word for word in FORBIDDEN_SPAWN if word in text]
        assert hits == [], f"MCP 面开始拉进程了：{rel} 命中 {hits}"

    assert len(sources) == 2  # 两个承载面，少一个就是扫漏（防改成空字典）
    assert all(text.strip() for text in sources.values()), "承载面源码读空了"


# ---------------------------------------------------------------- 判据 4：没有空闲回收定时器


def test_no_idle_reclaim_timer() -> None:
    """★ 反向钉子：谁写一行 threading.Timer(...) / time.AfterFunc，这条必须变红。

    注释里写中文「定时器」不算（词表只收代码形状）—— 与安静对照 N1 配套。
    """
    hits = [
        f"{rel}: {word}"
        for rel, text in _scan_texts(PRODUCT_SCAN_ROOTS)
        for word in FORBIDDEN_TIMER
        if word in text
    ]
    assert hits == [], f"出现了空闲回收定时器（hub 的 10 分钟机制）：{hits}"


# ---------------------------------------------------------------- 判据 5：不写 agent 配置


def test_no_agent_config_writer() -> None:
    """★ 反向钉子：谁开始写 mcpServers / 产 cursor:// 与 vscode:mcp deeplink，这条必须变红。"""
    hits = [
        f"{rel}: {word}"
        for rel, text in _scan_texts(PRODUCT_SCAN_ROOTS)
        for word in FORBIDDEN_CONFIG
        if word in text
    ]
    assert hits == [], f"本仓开始写 agent 的 MCP 配置 / 产 deeplink 了：{hits}"

    modules = (ROOT / "docs" / "subsystems" / "pool" / "modules.toml").read_text(encoding="utf-8")
    assert "mcpServers" not in modules, "模块清单里冒出了一个「写 agent 配置」的模块"
