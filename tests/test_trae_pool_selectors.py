r"""Trae 送任务通道的选择器 / 提交 / 并发判据（卡 E27 · T-AG481）。

## 为什么有它（用户现场反馈）

2026-10-25 实测：Trae CN 新版 solo-lite 面板改版，`tools/trae_pool.mjs` 的 `send` **静默失效** ——
报 `[trae] 找不到输入框（面板没渲染出来？）` 却**退 0**，调用方以为发出去了。三处病根：

1. 选择器全过时（旧的一个都不匹配）⇒ 集中进 `SELECTORS`，本文件**逐字**钉住五个实测值；
2. 发送键点不动（空输入带 `disabled`，`click()` 与指针序列全无效）⇒ 只走
   `focus()` → `execCommand('insertText')` → Enter 键序；★ 本文件钉「文件里没有 click 提交路径」；
3. 并发上限静默（面板弹「…并行任务上限」）⇒ 送任务前先探，命中报 `[trae] 并发已满（10）` 退 3。

## 钉什么

| # | 钉子 | 怎么钉 |
|---|---|---|
| 1 | `--help` 退 0 且列出 `list/send/switch/status` | 真跑子进程 |
| 2 | `SELECTORS` 五个值与实测**逐字相符** | 解析源文件 |
| 3 | 找不到输入框 / 发送键 disabled / 并发已满 ⇒ 退非零 | 纯函数在 `selftest`；空 prompt 真跑 |
| 4 | 没有 `button.click()` 提交路径（Enter 键序替代） | 静态扫 `submit()` 与全文 |
| 5 | `list` 带 `running` 标记 | `selftest` 的 `formatTasks` 用例 |

★ 真机那最后一步（要带调试口的 Trae）这里**没跑** —— 只钉「可离线求值」的部分（回报 §6 已写）。

跑法：`python -X utf8 -m pytest tests/test_trae_pool_selectors.py -q -o addopts=`
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
POOL = ROOT / "tools" / "trae_pool.mjs"
NODE = shutil.which("node")

#: Windows 上起 node 子进程不许弹窗（与 `tests/test_no_window.py` 同一口径）。
_NO_WINDOW = {"creationflags": 0x08000000} if os.name == "nt" else {}

#: 卡规格里写的四个实测选择器（任务项是两个：容器 + 文本）—— **逐字**，一个空格都不许漂。
MEASURED = {
    "input": "div.chat-input-v2-input-box-editable",
    "send": "button.chat-input-v2-send-button",
    "taskItem": "div.taskItem",
    "taskText": "span.taskText",
    "newTask": "span.task-list-new-task-text",
}

pytestmark = pytest.mark.skipif(NODE is None, reason="没有 node —— 这条通道本身跑不起来")


def _run(*args: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    """跑 `node tools/trae_pool.mjs <args>`（**带不弹窗旗**；异常一律落成可读的失败）。"""
    return subprocess.run(
        [str(NODE), str(POOL), *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        **_NO_WINDOW,
    )


def _src() -> str:
    return POOL.read_text(encoding="utf-8")


def _function_body(name: str) -> str:
    """从源文件里切出 `function <name>(…) { … }` 的正文（按顶层缩进收尾，够用且不引依赖）。"""
    src = _src()
    start = src.index(f"function {name}(")
    end = src.index("\n}\n", start)
    return src[start:end]


# --------------------------------------------------------------------------- ① --help
def test_help_exits_zero_and_lists_four_subcommands() -> None:
    """判据 1：`--help` 退 0，且四个子命令一个不缺（以前不带参数退 2，等于"查一下都算失败"）。"""
    r = _run("--help")
    assert r.returncode == 0, f"--help 应退 0，实际 {r.returncode}\nstderr={r.stderr}"
    out = r.stdout
    for name in ("list", "send", "switch", "status"):
        assert re.search(rf"^\s*{name}\b", out, re.M), f"--help 里没列出子命令 {name}：\n{out}"


# --------------------------------------------------------------------------- ② 选择器
def test_selectors_match_measured_values() -> None:
    """判据 2：`SELECTORS` 的五个值与实测**逐字相符**（改这里就得同步改卡与判据）。"""
    m = re.search(r"export const SELECTORS\s*=\s*\{(.*?)\n\}", _src(), re.S)
    assert m, "源文件里找不到 `export const SELECTORS = { … }` 常量"
    pairs = dict(re.findall(r"(\w+)\s*:\s*'([^']*)'", m.group(1)))
    assert pairs == MEASURED, f"选择器与实测值不符：\n  实际={pairs}\n  期望={MEASURED}"


def test_input_selector_is_the_single_source() -> None:
    """选择器只在这一个常量里定义：`SEL_INPUT` 是**引用**，不是又抄一份字面量。"""
    src = _src()
    assert "const SEL_INPUT = SELECTORS.input" in src, "SEL_INPUT 必须引用 SELECTORS.input"
    # 旧写法（只写类名、不带标签）不许再出现 —— 那就是"改版后匹配不上"的那一版。
    assert "'.chat-input-v2-input-box-editable'" not in src, "还留着旧的输入框选择器字面量"


# --------------------------------------------------------------------------- ③ 提交路径
def test_submit_uses_enter_sequence_not_click() -> None:
    """判据 4：提交路径只有 `submit()` 一条，且**不含任何点击**（click 实测点不动）。"""
    body = _function_body("submit")
    assert "execCommand('insertText'" in body, "submit() 必须用 execCommand('insertText') 打字"
    assert ".click(" not in body, "submit() 里不许有点击提交路径（发送键点击实测无效）"
    for ev in ("keyDown", "keypress", "keyUp"):
        assert f"type: '{ev}'" in body, f"submit() 的 Enter 键序缺 {ev}"
    # 全文层面：`Input.insertText` 那条老打法也不许回来
    # （它的语义在 contenteditable 上不触发输入事件链）。
    assert "Input.insertText" not in _src(), "老路径 Input.insertText 还在（要换成 execCommand）"


def test_send_button_is_never_clicked_anywhere() -> None:
    """文件里**任何** `SELECTORS.send` 附近都不许出现 `.click(`（防止换个人又「顺手点一下」）。"""
    src = _src()
    for lineno, line in enumerate(src.splitlines(), 1):
        if "SELECTORS.send" in line:
            assert ".click(" not in line, f"{POOL.name}:{lineno} 对发送键用了 click：{line.strip()}"


def test_click_submit_static_check_has_teeth() -> None:
    """★ 反空转：把「submit 里有 click」塞进字符串，判据必须能咬到（不是恒真）。"""
    fake = "async function submit(cdp) {\n  sb.click()\n  return 1\n}\n"
    body = fake[fake.index("function submit(") : fake.index("\n}\n")]
    assert ".click(" in body, "这条判据的取样方式坏了 —— 它对坏样本没反应"


# --------------------------------------------------------------------------- ④ 三种非零
def test_empty_prompt_exits_nonzero_with_one_line() -> None:
    """判据 3（空内容这一支）：`send --prompt ''` 退非零，stderr **恰好一行**原因。"""
    r = _run("send", "--prompt", "", "--port", "9333")
    assert r.returncode != 0, f"空 prompt 居然退 0 —— 又回到「以为发了」：\nstdout={r.stdout}"
    lines = [ln for ln in r.stderr.splitlines() if ln.strip()]
    assert len(lines) == 1, f"原因必须是一行，实际 {len(lines)} 行：\n{r.stderr}"
    assert "空" in lines[0], f"那行没说清「空」：{lines[0]!r}"


def test_unknown_subcommand_exits_nonzero() -> None:
    """反面：没认出的子命令退 2（打法在 stdout，但退出码不许是 0）。"""
    r = _run("no-such-subcommand")
    assert r.returncode == 2, f"未知子命令应退 2，实际 {r.returncode}"


def test_concurrency_full_reports_and_exits_three() -> None:
    """判据 3（并发已满这一支）：命中就报 `[trae] 并发已满（10）` 并**退 3**。"""
    src = _src()
    assert "[trae] 并发已满（10）" in src, "并发已满的原话不对（卡规格要求一字不差）"
    assert "export const MAX_PARALLEL = 10" in src, "并发上限常量不是 10"
    tail = src[src.index("[trae] 并发已满（10）") :]
    assert re.search(r"并发已满（10）[^\n]*\n\s*return 3", tail), "报了并发已满却没退 3"


def test_switch_without_body_says_so_instead_of_old_text() -> None:
    """判据（切任务那一支）：等不到正文就报「切过去了但读不到正文」，**不返回旧内容**。"""
    src = _src()
    assert "切过去了但读不到正文" in src, "缺少「读不到正文」的原话"
    body = _function_body("switchTask")
    assert "no-body" in body, "switchTask 没有 no-body 这条失败出口"
    assert "timeoutMs = 10000" in body, "轮询上限应为 10 s"


# --------------------------------------------------------------------------- ⑤ running 标记
def test_list_prints_running_marker() -> None:
    """判据（list）：任务项带 `running` 标记（项内有 spinner 类名），格式函数钉在 selftest 里。"""
    src = _src()
    assert "export const RUNNING_HINT" in src, "没有 running 的判据常量"
    assert "function formatTasks" in src and "'running'" in _function_body("formatTasks"), (
        "formatTasks 没打 running 标记"
    )
    body = _function_body("cmdList")
    assert "formatTasks(" in body, "list 没把任务项打出来"


# --------------------------------------------------------------------------- ⑥ selftest
def test_selftest_is_all_green() -> None:
    """纯函数判据全绿（含卡 227/245/260 的 44 条老用例 —— 一条都不许被本卡弄红）。"""
    r = _run("selftest", timeout=180)
    assert r.returncode == 0, f"selftest 红了：\nstdout={r.stdout}\nstderr={r.stderr}"
    assert "[OK] selftest 全绿" in r.stdout, f"没看到全绿结论：\n{r.stdout[-800:]}"
    assert "[红]" not in r.stdout, f"有红用例：\n{r.stdout}"
