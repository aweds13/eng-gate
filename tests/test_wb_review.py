"""主控复核器（`tools/wb_review.py`，T-G84）的测试 —— 给"这一笔算不算数"的判据上护栏。

这个工具的价值全在**判据**上：漏一条的代价是把没验过的东西当验过了。
所以零件层逐条喂**该失败的输入**（缺 trailer / 门禁 rev 对不上 / 越界改动 / 只读卡改了文件），
数据层拿**真仓库的 HEAD** 验一次（本项目的提交流程应当让它通过）。

真跑的 audit 那一步很慢（~4 秒），所以零件层不碰它；CLI 层用 `--json` 走一遍读真实结果。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import wb_review as wr  # noqa: E402 —— 需要先用 sys.path 把 tools/ 挂上


def _body(**trailers: str) -> str:
    lines = ["feat(x): 干了一件事（T-999）", "", "正文随便写点。", ""]
    order = ["Task", "Refs", "Ledger", "Gates"]
    for key in order:
        if key in trailers:
            lines.append(f"{key}: {trailers[key]}")
    return "\n".join(lines) + "\n"


GOOD_TRAILERS = {"Task": "T-999", "Ledger": "215 条", "Gates": "pytest 全绿"}


# ------------------------------------------------------------------ ② trailer


def test_trailers_pass_on_a_well_formed_message() -> None:
    problems, found = wr.check_trailers(_body(**GOOD_TRAILERS))
    assert problems == []
    assert found["Task"] == "T-999"


def test_trailers_catch_two_task_ids() -> None:
    """`Task:` 只能有一个台账编号（多出来的写 `Refs:`）—— 这是门禁⑧的同一件事。"""
    body = _body(**GOOD_TRAILERS) + "Task: T-998\n"
    problems, _ = wr.check_trailers(body)
    assert any("恰好一个" in p for p in problems)


def test_trailers_catch_a_missing_gates_line() -> None:
    problems, _ = wr.check_trailers(_body(Task="T-999", Ledger="215 条"))
    assert any("缺 `Gates:`" in p for p in problems)


# ------------------------------------------------------------------ ③ 门禁为谁而跑


def _payload(**over: object) -> dict:
    base: dict = {
        "rev": "abc1234", "ok": True, "docs_sync_ok": True, "docs_sync_missing": [],
        "gates": [{"name": "pytest", "exit_code": 0}, {"name": "audit", "exit_code": 0}],
    }
    base.update(over)
    return base


def test_gate_evidence_passes_when_run_for_this_commit() -> None:
    assert wr.check_gate_evidence(_payload(), "abc1234") == []


def test_gate_evidence_catches_a_stale_run() -> None:
    """★ 最要紧的一条：一次门禁跑完提交**两笔**，第二笔就是"没验过"。"""
    problems = wr.check_gate_evidence(_payload(rev="oldc0de"), "abc1234")
    assert any("不是为这一笔跑的" in p for p in problems)


def test_gate_evidence_catches_a_failed_gate_or_unsynced_docs() -> None:
    gates = [{"name": "pytest", "exit_code": 0}, {"name": "audit", "exit_code": 1}]
    problems = wr.check_gate_evidence(_payload(gates=gates, docs_sync_ok=False), "abc1234")
    assert any("有门没过" in p and "audit" in p for p in problems)
    assert any("没同步" in p for p in problems)


def test_gate_evidence_catches_an_empty_or_failed_artifact() -> None:
    assert any("没有任何门" in p for p in wr.check_gate_evidence(_payload(gates=[]), "abc1234"))
    assert any("ok 不是 true" in p for p in wr.check_gate_evidence(_payload(ok=False), "abc1234"))


# ------------------------------------------------------------------ ④ 改动范围


def test_read_only_card_may_not_touch_any_tracked_file() -> None:
    problems = wr.check_files(["src/a.py"], read_only=True, allow=[])
    assert any("只读卡不许改" in p for p in problems)
    assert wr.check_files([], read_only=True, allow=[]) == []


def test_allowlist_flags_files_outside_it() -> None:
    problems = wr.check_files(["src/a.py", "docs/x.md"], read_only=False, allow=["src/**"])
    assert any("不在白名单里" in p and "docs/x.md" in p for p in problems)
    assert wr.check_files(["src/a.py"], read_only=False, allow=["src/**"]) == []


def test_missing_allowlist_is_refused_not_silently_passed() -> None:
    """不给白名单又不说只读 → **拒绝**，别默认放行（默认放行等于没查）。"""
    problems = wr.check_files(["src/a.py"], read_only=False, allow=[])
    assert any("没有给白名单" in p for p in problems)


# ------------------------------------------------------------------ 数据层：真仓库


def test_current_head_passes_the_gate_evidence_check() -> None:
    """本项目的提交流程应当让 HEAD 通过第 ③ 条 —— 拿真仓库验一次（假的会被这里抓到）。"""
    sha = wr.git("rev-parse", "--short", "HEAD")
    parent = wr.git("rev-parse", "--short", f"{sha}^")
    payload = json.loads(wr.git("show", f"{sha}:gates/last.json"))
    assert payload.get("ok") is True
    assert payload.get("rev") == parent, "gates/last.json 的 rev 应当等于这一笔的父提交"
    assert wr.check_gate_evidence(payload, parent) == []


def test_chinese_paths_are_not_escaped() -> None:
    """★ 中文路径必须原样出来：被转义成 `\\345\\244...` 会让白名单把中文路径全判成越界。"""
    names = wr.git("show", "--name-only", "--format=", "HEAD").splitlines()
    assert names, "HEAD 应当至少改了一个文件"
    assert not [n for n in names if n.startswith('"')], f"有被转义的路径：{names[:3]}"
    folded = [n for n in names if "复盘" in n]
    assert folded, "这一笔里有中文路径（复盘/…），它必须原样出现在清单里"
