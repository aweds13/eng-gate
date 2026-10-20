r"""子进程「不弹窗」钉子（卡 148 · T-G248）—— 防回归，不靠人记。

## 为什么有它（用户现场反馈）

用户 2026-10-02：*「为什么我一直在蹦命令行窗口？」* —— Windows 11 会把**没有控制台的父进程**
起的控制台子进程（`git` / `python` / `node` / `taskkill` …）转交给**默认终端宿主**，
于是每起一个子进程就**闪一个命令行窗口**。带上 `CREATE_NO_WINDOW`（真源
`tools/pool/no_window.py` 的 `NO_WINDOW`）就压住它。

## 钉子判什么

扫 `tools/**` + `scripts/**`（**只扫这两个目录** —— 免得误伤测试自己，`tests/` 里的调用
不归它管）：凡 `subprocess.Popen(` / `subprocess.run(` / `subprocess.call(` 而**同一个调用里
没带** `NO_WINDOW` / `creationflags` / `windowsHide` ⇒ **判红**，逐条点名（文件:行 + 原文）。
扫描走 **AST**（不是正则）：文档字符串里提一句 `subprocess.run(…)` 不会被误判。

## 例外名单（`EXEMPT`）

- ★ **不许按整个文件放水** —— 每条都指名到**哪一次调用**，且**必带一句理由**（空理由 = 不算数）。
- 条目的 key = `(相对路径, callee, 规范化调用原文的 sha1 前 12 位)`。**用指纹不用行号**：
  行号会随无关改动漂移 → 造出一堆假红；指纹只随「这一次调用本身」变。
  一条红信息里会把要粘进 `EXEMPT` 的 key **原样印出来**，照抄即可。
- 名单里绝大多数是**本卡白名单外的既有缺口**（卡 148 只许改 `tools/pool_mcp.py` /
  `tools/pool/no_window.py` / `tests/test_no_window.py` / `gates/diag/gate_lock.py`）——
  它们是**债，不是无罪**（见回报 §6）；逐条列出正是为了「不许整文件放水」。
- `test_exempt_register_has_no_stale_entries` 会把**已经修好、却还挂在名单上**的条目咬出来
  ⇒ 债还清了条目必须删，名单不会烂在原地。
"""
from __future__ import annotations

import ast
import hashlib
import os
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parent.parent

#: 只扫这两个目录（★ 别扩到 `tests/`，否则钉子会咬到测试自己）。
SCAN_DIRS = ("tools", "scripts")
#: 认这三族调用。
CALLEES = ("Popen", "run", "call")
#: 同一个调用里出现任一 token 就算「带上了不弹窗」。
FLAG_TOKENS = ("NO_WINDOW", "creationflags", "windowsHide")


class Hit(NamedTuple):
    """一处未带 flag 的子进程调用。"""

    relpath: str
    callee: str
    lineno: int
    source: str      # `ast.unparse` 后的规范化原文（算指纹用）
    line: str        # 原文件那一行的原文（人工点名用）

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.relpath, self.callee, _digest(self.relpath, self.callee, self.source))

    def where(self) -> str:
        return f"{self.relpath}:{self.lineno} [{self.callee}] {self.line}"


def _digest(relpath: str, callee: str, source: str) -> str:
    raw = f"{relpath}|{callee}|{source}".encode()
    return hashlib.sha1(raw).hexdigest()[:12]


def scan_text(relpath: str, text: str) -> list[Hit]:
    """一个文件里的未带 flag 调用（AST ⇒ 字符串里的假调用不算）。"""
    lines = text.splitlines()
    hits: list[Hit] = []
    for node in ast.walk(ast.parse(text)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr in CALLEES):
            continue
        owner = func.value
        if not (isinstance(owner, ast.Name) and owner.id == "subprocess"):
            continue
        source = ast.unparse(node)
        if any(token in source for token in FLAG_TOKENS):
            continue
        line = lines[node.lineno - 1].strip() if 0 < node.lineno <= len(lines) else ""
        hits.append(Hit(relpath, func.attr, node.lineno, source, line))
    return hits


def iter_sources(root: Path = ROOT):
    """`(相对路径, 文本)` —— 只吐 `SCAN_DIRS` 下的 `.py`。"""
    for name in SCAN_DIRS:
        for path in sorted((root / name).rglob("*.py")):
            yield path.relative_to(root).as_posix(), path.read_text(encoding="utf-8")


def scan_tree(root: Path = ROOT) -> list[Hit]:
    hits: list[Hit] = []
    for relpath, text in iter_sources(root):
        hits.extend(scan_text(relpath, text))
    return hits


def unexempted(hits: list[Hit], exempt: dict[tuple[str, str, str], str]) -> list[Hit]:
    """名单里**带理由**的条目才算数（空理由 = 没豁免）。"""
    ok = {key for key, reason in exempt.items() if reason.strip()}
    return [hit for hit in hits if hit.key not in ok]


# --------------------------------------------------------------------------- 例外名单
#
# key = (相对路径, callee, `ast.unparse(调用)` 的 sha1 前 12 位)；每条必带理由。
# ★ 生成口径见本文件头：新增缺口时，红信息里会印出可直接粘贴的 key。

EXEMPT: dict[tuple[str, str, str], str] = {
    # —— 白名单外的既有债：应加 NO_WINDOW，但卡 148 不许改这些文件（回报 §6）——
    ("tools/mcp_client.py", "Popen", "de8b0495af84"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("tools/pin_check.py", "run", "1e50b1de18e7"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("tools/pool/jobs.py", "run", "316500711f67"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("tools/pool/landing.py", "run", "60a8681000fb"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("tools/pool/landing.py", "run", "60176c7a4edd"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("tools/pool/landing.py", "run", "26e0a544b96a"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("tools/pool/landing.py", "run", "23188a3f9713"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("tools/pool/landing.py", "run", "e00e6c3091d9"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("tools/pool/landing.py", "run", "3cec796c7340"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",

    # ★ 2026-10-04：卡 163 给 landing.py 的 acquire/renew 加了防窗旗（原登记已删）。
    ("tools/pool/landing.py", "run", "c28ff8284e2a"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("tools/pool/landing.py", "run", "501976f736bb"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    # ★ 2026-10-04：卡 184 给 `landing.py` 的三处调用加了防窗旗 ⇒ 这条登记**失效**（已删）。
    ("tools/pool/registry.py", "run", "325756f58717"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("tools/pool/registry.py", "run", "d2ddb40431c0"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("tools/pool/stage_card.py", "run", "6e6b7476dc20"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("tools/pool/stage_card.py", "run", "686d0791bf0d"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("tools/pool/task.py", "run", "47091fece521"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("tools/pool/task.py", "run", "67b85a82924c"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("tools/run_bg.py", "Popen", "7182934a8d1c"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("tools/seam_check.py", "run", "2e4ae9241c16"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("tools/snapshot.py", "run", "5d69180c8917"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("tools/tf_commit.py", "run", "b001b3975a74"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("tools/tf_stage_guard.py", "run", "6cae17568f1c"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("tools/ui_ab.py", "run", "0e5cbdd03ffd"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("tools/wb_advcard.py", "run", "e0454e22cd35"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("tools/wb_advcard.py", "run", "2bb2d1d6ab95"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("tools/wb_brief.py", "run", "880c555fa73c"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("tools/wb_brief.py", "run", "d60e8e54b40f"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("tools/wb_dash.py", "run", "03a78542b2da"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("tools/wb_dash.py", "run", "c178bf3f94af"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("tools/wb_diag.py", "run", "401d1382229c"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("tools/wb_review.py", "run", "645821f8c85e"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("tools/wb_review.py", "run", "15c8d719abe8"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("tools/wb_verify.py", "run", "7c82a5ee1484"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("tools/web_live_check.py", "run", "f39b18593973"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("tools/web_live_check.py", "run", "31aafa514c56"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("tools/web_live_check.py", "run", "39d263567b40"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("tools/wt_prune.py", "run", "d24399250819"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("scripts/audit_progress.py", "run", "5c4acac0d2b2"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("scripts/audit_progress.py", "run", "91bf5b614da9"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("scripts/check_layers.py", "run", "40528a732194"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("scripts/check_toml.py", "run", "0f5a39dfab46"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("scripts/run_gates.py", "run", "6bedb702c1c1"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("scripts/run_gates.py", "run", "dbf3b5aee387"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("scripts/run_gates.py", "run", "e3912547e912"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("scripts/run_gates.py", "run", "95d887907f1e"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("scripts/run_gates.py", "run", "47b8c3182682"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("scripts/run_gates.py", "run", "923ba1926a48"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("scripts/run_gates.py", "run", "7a9a113f7203"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("scripts/run_gates.py", "run", "101a0fb0a0e8"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("scripts/run_gates.py", "run", "2b778b5b3c78"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("scripts/run_gates.py", "Popen", "af1f19f56107"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("scripts/run_gates.py", "run", "f505b7780efd"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("scripts/run_gates.py", "run", "5f428634055b"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    ("scripts/test_check_layers.py", "run", "bee01e0c70df"):
        "★ 需加 NO_WINDOW（起 console 子进程）；本卡白名单外 → 回报 §6",
    # —— 真相不是「缺 flag」：flag 经间接通道传入，字面量看不到（不算债）——
    ("tools/wb_dispatch.py", "Popen", "4deca24157fe"):
        "flags 经 **kwargs 间接传入（spawn_detached 内含 CREATE_NO_WINDOW）→ 已带上",
    ("tools/run_bg.py", "Popen", "2eaae04d7283"):
        "creationflags 经 **_detach_kwargs()（DETACHED_PROCESS）传入 → 无字面 flag",
}


# --------------------------------------------------------------------------- 钉子
def test_no_unflagged_subprocess_calls() -> None:
    """★ 命门：`tools/**` + `scripts/**` 里不许有「没带不弹窗 flag」的子进程调用。"""
    hits = scan_tree(ROOT)
    bad = unexempted(hits, EXEMPT)
    assert not bad, "以下调用没带 NO_WINDOW/creationflags/windowsHide（红）：\n" + "\n".join(
        f"  {hit.where()}\n      粘进 EXEMPT 的 key = {hit.key!r}" for hit in bad
    )


def test_every_exempt_entry_has_a_reason() -> None:
    """例外必须带一句理由；空理由 ⇒ 钉子自己红（不许用整文件/空话放水）。"""
    missing = sorted(key for key, reason in EXEMPT.items() if not reason.strip())
    assert not missing, f"这些例外条目没有理由：{missing}"


def test_exempt_register_has_no_stale_entries() -> None:
    """名单里不许留**已经不存在**的条目（债还清了就得删，名单不会烂在原地）。"""
    live = {hit.key for hit in scan_tree(ROOT)}
    stale = sorted(key for key in EXEMPT if key not in live)
    assert not stale, f"这些例外条目已经匹配不到真实调用了（删掉它们）：{stale}"


def test_exempt_suppresses_but_needs_reason() -> None:
    """★ 反例钉子②：进了名单就不再被点名；**没理由**的例外等于没进名单。"""
    hit = scan_text(
        "tools/demo.py", "import subprocess\nsubprocess.run(['x'], capture_output=True)\n"
    )[0]
    assert unexempted([hit], {}) == [hit]
    assert unexempted([hit], {hit.key: "演示理由"}) == []
    assert unexempted([hit], {hit.key: "   "}) == [hit]


def test_scope_is_only_tools_and_scripts() -> None:
    """★ 反例钉子③：只扫 `tools/` + `scripts/` —— 范围外的调用不归它管（免得自伤）。"""
    # 扫描器本身**会**认出范围外的未带 flag 调用（否则这条判据是空转）
    outside = scan_text(
        "tests/demo.py", "import subprocess\nsubprocess.run(['git'], capture_output=True)\n"
    )
    assert len(outside) == 1 and outside[0].callee == "run"
    # 但遍历器只吐 SCAN_DIRS 下的文件
    rels = [relpath for relpath, _ in iter_sources(ROOT)]
    assert rels, "没扫到任何文件 —— 判据空了"
    assert all(rel.startswith(("tools/", "scripts/")) for rel in rels), rels


def test_scanner_ignores_strings_and_accepts_flags() -> None:
    """AST 扫描：字符串里的 `subprocess.run(…)` 不算；带任一 flag 的调用不算。"""
    assert scan_text("x.py", "DOC = 'subprocess.run([\"git\"])'\n") == []
    for good in (
        "import subprocess\nfrom pool.no_window import NO_WINDOW\n"
        "subprocess.run(['git'], **NO_WINDOW)\n",
        "import subprocess\nsubprocess.run(['git'], creationflags=0x08000000)\n",
        "import subprocess\nsubprocess.Popen(['x'], windowsHide=True)\n",
    ):
        assert scan_text("x.py", good) == [], good


def test_shared_flag_is_platform_correct() -> None:
    """`tools/pool/no_window.py` 的 flag 在 Windows 上就是 `CREATE_NO_WINDOW`。"""
    sys.path.insert(0, str(ROOT / "tools"))
    from pool.no_window import NO_WINDOW

    expected = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    assert expected == NO_WINDOW


def test_pool_mcp_uses_the_shared_flag() -> None:
    """结构钉：`tools/pool_mcp.py` 用的就是那一份真源（不是自己又抄一遍字面量）。"""
    sys.path.insert(0, str(ROOT / "tools"))
    import pool_mcp
    from pool.no_window import NO_WINDOW

    assert pool_mcp.NO_WINDOW is NO_WINDOW


if __name__ == "__main__":  # pragma: no cover —— 人工对账用：列出名单里每条的现场
    for entry in scan_tree(ROOT):
        if entry.key in EXEMPT:
            print(f"[豁免] {entry.key}\n    {entry.where()}")
