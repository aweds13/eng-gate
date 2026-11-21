"""核「红门不许配绿摘要」与「detail 必须有人写」会不会咬（卡 E67 · T-AG528）。

## 为什么有这张测试

两个病根，同一条链上：

1. **缺陷 A**：`scripts/run_gates.py:summarize(out)` 从后往前找第一条命中 `summary_re` 的行
   —— 那条正则里含 `OK \\]`。于是**红门也可能挑出一行绿的当摘要**。实测：云机 `web_live`
   `exit_code=1`、日志尾是 `TimeoutError: timed out`，而 `gates/last.json` 里这一行写的是
   `[OK ] JS 语法：node --check 通过（app_extract.mjs / offline_check.mjs / sw_check.mjs）`。
   产物在骗人：人看 trailer 会以为这道门没事。

2. **缺陷 B**：`mark_suspect_rows()` 判「等不到东西」时读 `row['detail']`，但**全仓没有
   任何地方写它**（`grep -n '"detail"' scripts/run_gates.py` 只有 `:1607` 一处只读）。
   ⇒ 判据只剩 `summary` 一个字段可看；`summary` 一旦被挑成绿的那一行（缺陷 A），
   `TimeoutError: timed out` 这条形状就**整条失明**，`web_live` 也标不上 `SUSPECT`。

## 怎么验

- 缺陷 A 的钉子直接喂**实测过的那份日志的尾部**（`_CLOUD_TAIL`），断 `summarize(out, 1)`
  不许以 `[OK` 开头、不许等于那条绿的。反向：把 `summarize` 改回单参版本 ⇒ 红。
- 缺陷 A 的另一半走**真路径**：`start_gate()` + `finish_gate()` 跑一道**真的会失败**的门，
  断 `finish_gate()` 记下来的 `summary` 不是绿的形状。
- 缺陷 B 断 `finish_gate()` 在**红门**上写出了 `detail`（含原始 traceback 的一半），
  且体积守口径（≤2000 字符 / ≤20 行）；**绿门不写**（`last.json` 是入库产物，不许撑肥）。
- 缺陷 B 与判据的**联动**：拿 `finish_gate()` 真产出的行喂 `mark_suspect_rows()`，
  断 `web_live` 那种形状能被标成 `SUSPECT` —— 这条不用桩替判据本体。

## 边界（如实写，未覆盖）

- **不跑 `main()` 全量**（改门禁自己时跑全量会自相矛盾，同卡 E44/100 的口径）。
- 假门是 `python -c`（card E44：云上 Windows Server 没有 PATH `sleep`）。
- 真机 `web_live` 的**超时**行为不在这里（要云机），见 `tests/test_web_live_timeout.py`。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import run_gates as rg  # noqa: E402 —— 需要先用 sys.path 把 scripts/ 挂上

#: 云机 `web_live` 红门那一趟日志的尾部（实测原文，`gates/diag/_cloud_web_live.log`）。
#: 关键是：前面还留着一条 `[OK ]`，尾部才是真症状 —— 这正是缺陷 A 的现场。
_CLOUD_TAIL = (
    "[OK ] JS 语法：node --check 通过（app_extract.mjs / offline_check.mjs / sw_check.mjs）\n"
    "[OK ] 页面能挂载\n"
    "Traceback (most recent call last):\n"
    '  File "tools/web_live_check.py", line 283, in main\n'
    '    turned_on = _json_call(base, "/api/settings/ai", "PUT", {"enabled": True})[0]\n'
    "  File \"C:\\Python311\\Lib\\socket.py\", line 706, in recv_into\n"
    "    return self._sock.recv_into(b)\n"
    "TimeoutError: timed out\n"
)

#: 一条**失败形状都挑不出来**的红门输出（用来钉 `[FAIL]` 兜底）。
_NO_SHAPE = "第一步跑完了\n第二步也跑完了\n就这些\n"


def _py_cmd(code: str) -> list[str]:
    """假门：跑一段 python 然后退出（card E44：不依赖 PATH `sleep`）。"""
    return [sys.executable, "-c", code]


def _run_fake(name: str, code: str) -> dict[str, object]:
    """把一道假门真跑完（`start_gate()` → `finish_gate()`，走判据的真路径）。"""
    proc, t0, err = rg.start_gate(name, _py_cmd(code))
    assert proc is not None, f"假门没起起来：{err}"
    return rg.finish_gate(name, proc, t0)


@pytest.fixture(autouse=True)
def _logs_into_tmp(monkeypatch, tmp_path):
    """假的日志别落进仓库（同 `tests/test_run_gates_timeout.py` 的口径）。"""
    monkeypatch.setattr(rg, "LOG_DIR", tmp_path / "logs")


# ==================================================================== 缺陷 A


def test_red_gate_summary_is_never_green():
    """★ 缺陷 A 的主钉子：红门的摘要不许以 `[OK` 开头（云机那一趟的原文）。"""
    got = rg.summarize(_CLOUD_TAIL, 1)
    assert not got.startswith("[OK"), f"红门配了绿摘要：{got!r}"
    assert "JS 语法" not in got, f"挑中了那条绿的：{got!r}"
    assert "timed out" in got or "Timeout" in got, f"没挑中真症状：{got!r}"


def test_red_gate_summary_is_never_green_through_the_real_path():
    """红门走 `start_gate()`/`finish_gate()` 的真路径，摘要同样不许是绿的。"""
    row = _run_fake("fake_red", "import sys; print('[OK ] 假的绿'); sys.exit(1)")
    assert row["exit_code"] == 1
    summary = str(row["summary"])
    assert not summary.startswith("[OK"), f"红门配了绿摘要：{summary!r}"


def test_red_gate_without_any_failure_shape_gets_fail_prefix():
    """一条失败形状都挑不出来时，也要显式加 `[FAIL] ` 前缀（不许退回成绿的那一行）。"""
    got = rg.summarize(_NO_SHAPE, 2)
    assert got.startswith("[FAIL] "), f"没加前缀：{got!r}"
    assert "就这些" in got, f"没退回最后一行：{got!r}"


def test_red_gate_never_keeps_a_green_marker_on_the_chosen_line():
    """选中的那一行若自己带 `[OK ]` 前缀，也要摘掉 —— 绿标记一律不许留下来。"""
    got = rg.summarize("[OK ] 这一步过了\n[OK ] 超时了但带绿标记\n", 1)
    assert not got.startswith("[OK"), f"绿标记没摘：{got!r}"


def test_green_gate_summary_still_prefers_the_framework_summary_line():
    """**反例**：绿门行为不变 —— 仍然优先挑测试框架的汇总行。"""
    out = "collected 3 items\n3 passed in 0.11s\n"
    assert rg.summarize(out, 0) == "3 passed in 0.11s"


def test_green_gate_summary_still_skips_warnings():
    """**反例**：绿门仍跳过 Warning 行（第一版抓错 ResourceWarning 的老病根）。"""
    out = "checks passed\nResourceWarning: unclosed socket\n"
    assert rg.summarize(out, 0) == "checks passed"


# ==================================================================== 缺陷 B


def test_red_gate_row_carries_the_output_tail_in_detail():
    """★ 缺陷 B 的主钉子：红门的行里必须写出 `detail`，且原始 traceback 要在里面。"""
    row = _run_fake("fake_traceback", "raise TimeoutError('timed out')")
    assert row["exit_code"] != 0
    detail = str(row.get("detail") or "")
    assert detail, "红门的 detail 是空的 —— 判据没有任何东西可看"
    assert "TimeoutError" in detail, f"原始异常不在 detail 里：{detail!r}"
    assert "Traceback" in detail, f"traceback 不在 detail 里：{detail!r}"


def test_detail_respects_the_size_budget():
    """`detail` 的体积守口径：≤2000 字符 / ≤20 行（`gates/last.json` 是入库产物）。"""
    noisy = "\n".join(f"第 {i} 行进度日志" for i in range(400))
    got = rg.gate_detail(noisy)
    assert len(got) <= rg.DETAIL_MAX_CHARS, f"字符数超了：{len(got)}"
    assert len(got.splitlines()) <= rg.DETAIL_TAIL_LINES, f"行数超了：{got.count(chr(10)) + 1}"


def test_green_gate_row_does_not_carry_detail():
    """**反例**：绿门不写 `detail` —— 别把入库产物撑肥。"""
    row = _run_fake("fake_green", "print('all good')")
    assert row["exit_code"] == 0
    assert not row.get("detail"), f"绿门也写了 detail：{row['detail']!r}"


def test_detail_makes_the_suspect_shape_visible_again():
    """★ 缺陷 A + B 的联动：`detail` 一写上，`SUSPECT` 判据才看得见「等不到」。

    现场形状照 **E65 那一类红门**摆：pytest 把 `FAILED …` 打在**最后一行**，于是
    `summarize()`（倒序找第一条失败形状行）挑中的是它 —— 而 `FAILED` 这一行里**没有**
    `SUSPECT_SHAPES` 的任何一条（`没等到` / `超时` / `timeout` / `timed out` / `等了约`）。
    症状「等了约 12 秒」留在**更前面**那行，只有 `detail` 会把尾部整段带上。
    ⇒ 这就是缺陷 B 的现场：`detail` 不写，这条症状**整条失明**。
    """
    code = (
        "import sys\n"
        "print('[FAIL] 没等到响应，等了约 12 秒')\n"
        "print('FAILED tests/test_live.py::test_x')\n"
        "sys.exit(1)\n"
    )
    row = _run_fake("web_live", code)
    assert row["exit_code"] == 1
    # 先自证前提成立：摘要确实挑中了那条**不带症状**的 FAILED 行。
    summary = str(row["summary"])
    assert "FAILED" in summary, f"前提不成立，摘要没挑中 FAILED 行：{summary!r}"
    assert not any(s in summary for s in rg.SUSPECT_SHAPES), f"摘要自己就带了症状：{summary!r}"

    rows = [row]
    rg.mark_suspect_rows(rows, {"co": "占 cpu 的同行"})
    assert rows[0].get("status") == "SUSPECT", f"没标上 SUSPECT：{rows[0]!r}"
    reason = str(rows[0].get("suspect_reason") or "")
    # 命中的那条形状必须**只在 detail 里**（摘要里没有）—— 这才证明确实靠 detail 才看见。
    hit = next((s for s in rg.SUSPECT_SHAPES if s in reason), None)
    assert hit is not None, f"理由里没写命中的形状：{reason!r}"
    assert hit not in summary, f"这条形状摘要里本来就有，证明不了 detail 的作用：{hit!r}"
    assert hit in str(row.get("detail") or ""), f"形状不在 detail 里：{hit!r}"
    # 判据本体不许被这条标记改判：`SUSPECT` 只标注症状，红还是红。
    assert rg.gates_ok(rows) is False


# ============================================================ 判据 8：exit 3 不是红


def test_not_run_gate_is_skip_not_fail_not_green():
    """★ 判据 8：`exit_code == 3`（NOT RUN，卡 E59）既不是绿也不是红。

    这条是**本轮 `--only pytest` 实测红出来的**：第一版把 `exit_code != 0` 一律当红，
    于是「这一层没验证」被写成 `[FAIL] [SKIP] …` —— 未验证说成了失败，两个结论都不对。
    判据本体（`gates_ok()`）从不把 3 当红，摘要也必须说同一句话。
    """
    out = "[OK ] JS 语法：node --check 通过\n[SKIP] 环境里没有 node\n"
    got = rg.summarize(out, 3)
    assert got.startswith("[SKIP] "), f"NOT RUN 没标成 [SKIP]：{got!r}"
    assert not got.startswith("[OK"), f"NOT RUN 被写成了绿：{got!r}"
    assert not got.startswith("[FAIL]"), f"NOT RUN 被写成了红：{got!r}"
    # 不许叠成 `[SKIP] [SKIP] …`
    assert got.count("[SKIP]") == 1, f"标记叠了：{got!r}"


def test_not_run_gate_row_does_not_carry_detail():
    """**反例**：NOT RUN 不是红 ⇒ 不该往入库产物里塞 detail（体积口径）。

    只留尾部 20 行 / 2000 字是给**红门**排障用的；3 是「没验证」，
    再塞一份输出尾巴只会撑肥 `gates/last.json`。
    """
    code = "print('[SKIP] 这一层没跑')\nraise SystemExit(3)\n"
    row = _run_fake("not_run_door", code)
    assert row["exit_code"] == 3
    assert row.get("detail") == "", f"NOT RUN 不该有 detail：{row.get('detail')!r}"

def test_detail_keeps_the_symptom_outside_the_tail_window():
    """★ 卡 E152：症状行被几十条 `[OK ]` 挤出尾部窗口时，`detail` 仍必须带上它。

    现场形状照 GHA 上 head `3a5bc8cc` 那两趟红门摆：症状（`没等到` / `timed out`）打在最前面，
    接着 60 条 `[OK ]` 子检查，末行才是那条**不带症状**的 `[FAIL]`（收口重打的同名行）。
    尾部 20 行窗口里一条症状都没有 ⇒ 旧口径下 `mark_suspect_rows()` 永远标不上 `SUSPECT`。
    """
    symptom = (
        "[FAIL] 真机自检没跑完：PUT http://127.0.0.1:1/api/settings/ai  ★ PUT 等了 60 秒没等到"
        "（TimeoutError: timed out）"
    )
    lines = ["import sys", f"print({symptom!r})"]
    lines += [f"print('[OK ] 子检查 {i}')" for i in range(60)]
    lines += [
        "print('[FAIL] 真机自检没跑完：PUT http://127.0.0.1:1/api/settings/ai')",
        "sys.exit(1)",
    ]
    row = _run_fake("web_live", "\n".join(lines))
    assert row["exit_code"] == 1

    # 前提成立：尾部窗口里没有症状，所以摘要也挑不到它。
    summary = str(row["summary"])
    assert not any(s in summary for s in rg.SUSPECT_SHAPES), f"摘要自己就带了症状：{summary!r}"

    detail = str(row.get("detail") or "")
    assert "没等到" in detail, f"症状没进 detail，SUSPECT 判据会整条失明：{detail[:300]!r}"
    assert detail.splitlines()[0] == symptom, f"症状行不在最前面，随时会被截掉：{detail[:200]!r}"
    # 体积口径一个字没放宽。
    assert len(detail) <= rg.DETAIL_MAX_CHARS, f"字符数超了：{len(detail)}"
    lines_used = detail.count(chr(10)) + 1
    assert len(detail.splitlines()) <= rg.DETAIL_TAIL_LINES, f"行数超了：{lines_used}"

    rows = [row]
    rg.mark_suspect_rows(rows, {"co": "占 cpu 的同行"})
    assert rows[0].get("status") == "SUSPECT", f"还是没标上 SUSPECT：{rows[0]!r}"
    assert rg.gates_ok(rows) is False, "SUSPECT 只标注症状，红还是红"
