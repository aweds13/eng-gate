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


def test_determinism_check_is_opt_in() -> None:
    """★ 最小验证法则（T-G38）：这条流**默认只跑一遍**，两遍指纹自检用 `--twice` 按需开。

    为什么要钉住"默认一遍"：它会悄悄变回两遍（改代码时顺手加回来），而两遍把门禁时间翻倍 ——
    这笔账必须是**有意花**的。这里用一条最短路径证明 `--twice` 仍然认（`--only` 没匹配到时
    在起浏览器之前就退，所以这条测试不花时间）。
    """
    proc = run_tool("--twice", "--only", "这条流不存在")
    assert proc.returncode == 1
    assert "一条流都没匹配上" in proc.stdout + proc.stderr


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

    ★ **例外（T-G61）**：新加的面（如 ⌘K 命令面板）本来就**没有**人工项可搬 ——
    那一列写「新增（不是搬移项）：…」时不做编号对账。这一列不许留空（这是本节的全部意义）：
    要么指回一条人工项，要么明说它是新增的。
    """
    proc = run_tool("--list")
    assert proc.returncode == 0
    text = HANDOVER.read_text(encoding="utf-8")
    for row in proc.stdout.splitlines():
        if "\t" not in row:
            continue
        item = row.split("\t")[2].removeprefix("← ")
        if item.startswith("新增"):
            continue
        # 声明形如「前端批次③ ⑦ 今日页新手引导卡片」——取其中的编号/关键词去文档里找
        tokens = ("⑦", "⑧", "⑨", "⑩", "①", "③", "⑥", "④", "⑬", "⑮", "⑯", "⑰",
                  "㉓", "㉔", "㉕", "㉗", "㉑", "⑭", "㉒", "㉖", "㉘", "⑪")
        for token in tokens:
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


def _method_body(src: str, name: str) -> str:
    """取出类里 `async <name>(...)` 那个方法的正文（到同级缩进的 `}` 为止）。"""
    start = src.index(f"\n  async {name}(")
    end = src.index("\n  }", start)
    return src[start:end]


def test_wait_primitives_poll_instead_of_asserting_once() -> None:
    """★ 卡 092（T-G188）：这五处「找元素 / 点」的原语必须**先轮询等就绪、再断言**。

    病（主控三趟全量门禁实测）：它们各自**只查一次**（`mark()` 一次 / `rectOf()` 一次），
    满载下抢不到时间片就报「匹配到 0 个」「元素是 0×0」——**假警报**（每趟挂的还不是同一条）。
    修法：把「等时间」换成「等就绪判据」（`this.waitFor`：存在 ∧ 可见 ∧ 尺寸非零），
    且**不许**改成更大的固定 `sleep`（那只是把概率推小，卡 092 明令禁止）。

    这条测试钉的就是「别退回去」：正文里必须有 `waitFor(`，且不许出现 `sleep(`。
    """
    src = TOOL.read_text(encoding="utf-8")
    for name in ("view", "press", "pressAction", "drag", "openSetting"):
        body = _method_body(src, name)
        assert "this.waitFor(" in body, f"{name}() 退回一次性断言了（正文里没有 waitFor）"
        assert "sleep(" not in body, (
            f"{name}() 里出现了固定 sleep —— 卡 092 明令不许用「等更久」顶替「等就绪」"
        )
    # flow ⑭ 里那个局部 press（同一个症状类，主控补齐）
    seg = src[src.index("const press = async (sel, label) =>"):][:700]
    assert "t.waitFor(" in seg, "flow ⑭ 的局部 press 又退回一次性断言了"
    assert "sleep(" not in seg


def test_no_flow_was_deleted() -> None:
    """★ 卡 092 明令：不许删流 / 删断言来把门禁弄绿。

    行为流是**搬走的人工项**（每条都在 `--list` 第三列声明它替掉哪一条），少一条就是少一块覆盖。
    这条断言把「26 条流」钉住：真要增删，就得改这条断言并在复盘里写明为什么。
    """
    proc = run_tool("--list")
    assert proc.returncode == 0
    rows = [ln for ln in proc.stdout.splitlines() if "\t" in ln]
    assert len(rows) == 26, f"行为流从 26 条变成 {len(rows)} 条 —— 删流是把覆盖丢掉（卡 092 禁止）"


def test_toast_assertions_wait_for_the_whole_predicate() -> None:
    """★ 卡 092（T-G188，主控补齐）：**值 / 文本就绪**也是一条等待原语。

    病（满载实测 ㉒）：`waitToast('已导入：')` 只等到了**前缀**，
    紧接着拿眼前那半句去断言 `删除 1` —— 提示条是**分步渲染**的，那一瞬间必然落空
    （原文：`导入报告里写了删了几行 —— 没找到「删除 1」`）。
    同族写法当时 4 处：⑯ / ㉒ 预览 / ㉒ 导入 / ㉖ 断网。

    判据：① 不许再出现「同一行里既 `t.has(` 又 `waitToast(`」的写法（先等前缀、再拿眼前文本断言）；
         ② 整条判据必须用 `waitToastWhere(pred)` 一次说完整、等到它成立。
    """
    src = TOOL.read_text(encoding="utf-8")
    bad = [ln.strip() for ln in src.splitlines() if "t.has(" in ln and "waitToast(" in ln]
    assert not bad, (
        "这几行又在「先等前缀、再拿眼前文本断言」了（改成 waitToastWhere）：\n"
        + "\n".join(bad)
    )
    assert "async waitToastWhere(" in src, "waitToastWhere 这个原语不见了（值/文本就绪就靠它）"
