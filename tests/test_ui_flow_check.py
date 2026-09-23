"""行为流层（T-G34）的测试 —— **不用浏览器**也能钉住的那几条纪律。

为什么只测这几条：这一层的主体是"真浏览器 + 真点击 + 真按键"，那件事由**门禁里跑它本身**来证明
（而且它每轮默认把整套流**跑两遍**、比对断言指纹 —— 两遍不一致就退 4，那是比单元测试更硬的证据）。
这里测的是**不需要浏览器就能测的规矩**，尤其是两条最容易悄悄退化成"假绿灯"的：

1. **`--only` 写错一个字**：一条流都不跑，却打印"通过 ✅ 0 条流" —— 空集永远满足"所有流都通过"，
   这种绿灯比红灯更坏（红灯你会去看，假绿灯你不会）；
2. **每条流都得声明它替掉哪一条人工项**：不然"搬走了哪几条"就只剩口头说法，
   而这一层存在的全部意义就是**把人工项搬给机器**（搬了哪几条必须能逐条对上）。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "ui_flow_check.mjs"
LIB = ROOT / "tools" / "tf_browser.mjs"
HANDOVER = ROOT / "复盘" / "交接-重构进度.md"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="环境里没有 node（这一层本来就跑不了）")


def run_tool(*args: str) -> subprocess.CompletedProcess[str]:
    assert NODE is not None
    return subprocess.run(
        [NODE, str(TOOL), *args],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )


def test_unknown_argument_is_refused() -> None:
    """打错的参数要当场说，不许被当成"没传"静默吞掉。"""
    proc = run_tool("--no-such-flag")
    assert proc.returncode == 1
    assert "未知参数" in proc.stdout + proc.stderr


def test_only_without_match_is_refused() -> None:
    """★ `--only 不存在的名字` 必须**报错**，而不是"0 条流全部通过"。
    （这条在起浏览器之前就该拒掉 —— 否则它要花两分钟才"通过"。）"""
    proc = run_tool("--only", "这条流不存在")
    assert proc.returncode == 1
    out = proc.stdout + proc.stderr
    assert "一条流都没匹配上" in out
    assert "通过 ✅" not in out


def test_list_declares_every_flow_and_its_item() -> None:
    """`--list` 里每条流都要有：编号 / 名字 / **它替掉的人工项**（三列，逐条可对）。"""
    proc = run_tool("--list")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    rows = [ln for ln in proc.stdout.splitlines() if "\t" in ln]
    assert len(rows) >= 5, f"流太少了（{len(rows)} 条），像是登记丢了"
    ids = []
    for row in rows:
        parts = row.split("\t")
        assert len(parts) == 3, f"这一行不是三列：{row!r}"
        flow_id, name, item = parts
        assert flow_id and name, f"编号或名字是空的：{row!r}"
        # 第三列必须指回"待人工确认"那份清单（`← …`），不能只写一句自说自话
        assert item.startswith("← ") and len(item) > 6, f"这一条没声明它替掉哪条人工项：{row!r}"
        ids.append(flow_id)
    assert len(set(ids)) == len(ids), f"有重复的流编号：{ids}"


def test_every_declared_item_still_exists_in_handover() -> None:
    """★ 流声明的那些人工项，**必须真的还在交接文档的清单里** ——
    否则就是"我搬走了一条它自己编的项"，而这种漂移没人会当场发现。

    口径：人工项清单散在 `§二 待人工确认` 那一段（编号 ①…㉘ 与 `T-G11 ㉑`）。
    这里只断言"编号在这个文档里出现过"（宽松但够用：它拦的是**凭空编号**）。
    """
    proc = run_tool("--list")
    assert proc.returncode == 0
    text = HANDOVER.read_text(encoding="utf-8")
    for row in proc.stdout.splitlines():
        if "\t" not in row:
            continue
        item = row.split("\t")[2].removeprefix("← ")
        # 声明形如「前端批次③ ⑦ 今日页新手引导卡片」——取其中的编号/关键词去文档里找
        for token in ("⑦", "⑧", "⑨", "⑩", "①", "③", "⑥", "④", "⑬", "⑯", "㉔", "㉑"):
            if token in item:
                assert token in text, f"交接文档里已经没有人工项 {token} 了（{item}）"
                break


def test_lib_and_tool_are_syntactically_valid() -> None:
    """两个文件都要能被 node 解析（这一层没有别的语法检查会碰到 tools/*.mjs）。"""
    for path in (TOOL, LIB):
        proc = subprocess.run(
            [NODE, "--check", str(path)], cwd=ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=False,
        )
        assert proc.returncode == 0, f"{path.name} 语法不过：{proc.stderr[:300]}"


def test_render_check_reuses_the_shared_harness() -> None:
    """渲染层与行为流层**必须共用同一个底座**：谁要是又抄一份起服务/起浏览器的代码，
    这份测试把它拦下来（两份调好的细节各自演化 = 迟早有一份是错的）。"""
    render = (ROOT / "tools" / "render_check.mjs").read_text(encoding="utf-8")
    assert "from './tf_browser.mjs'" in render
    for copied in ("function startServer", "class Cdp", "EDGE_CANDIDATES"):
        assert copied not in render, (
            f"渲染层里又出现了一份 {copied!r}（应该用 tf_browser.mjs 的那份）"
        )


def test_flow_metadata_is_exported_as_json() -> None:
    """`--json` 要给出机器可读的结论（门禁与将来的汇总都靠它，而不是靠解析人话）。"""
    proc = run_tool("--only", "这条流不存在", "--json")
    lines = proc.stdout.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.strip() == "{")
    payload = json.loads("\n".join(lines[start:]))
    assert payload["code"] == 1
    assert payload["not_run"] is False
