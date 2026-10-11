r"""号池只读逻辑包（`tools/pool/`，卡 106 · 台账号 T-G202）的测试。

为什么值当测：这一包把**散在 6 个脚本里的只读逻辑**收成一处，并且要求 CLI 与号池 MCP **共用同一批
函数**、"输出逐字不变"。所以三类判据都要机器形态：

| 判据 | 判什么 |
|---|---|
| ① 直测 | 抽出来的每个函数**不经过 CLI**也能测（纯函数、无副作用） |
| ② CLI 与库同一结论 | 同一输入下，CLI 输出与直接调库**逐字一致**（`wb_plan plan`/`wb_status`） |
| ③ 白名单收敛 | 三处入口对同一组暂存/脏文件给出**同一个**越界清单（含**中文路径**） |

★ 导入口径照既有测试：把 `tools/` 挂上 `sys.path` 再 `import`。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import tf_stage_guard  # noqa: E402 —— tools/ 已在 sys.path 上
import wb_dispatch  # noqa: E402
import wb_plan  # noqa: E402
import wb_review  # noqa: E402
import wb_status  # noqa: E402
from pool import jobs, locks, models, review  # noqa: E402
from pool import plan as pool_plan  # noqa: E402

# ================================================================ 夹具


_BACKLOG = """\
[base]
reviewed = "abc1234"

[[cards]]
id = "001"
task = "T-G9x"
title = "样卡一"
tree = ".wt/a"
spec = "复盘/卡/卡160-台账接进门.md"   # ★ 卡 157 起：validate 会查
#      "队列指向的规格在不在" ⇒ 合成队列也要指向真文件
files = ["a.py"]
status = "pending"

[[cards]]
id = "002"
task = "T-G9x"
title = "样卡二"
tree = ".wt/b"
spec = "复盘/卡/卡160-台账接进门.md"   # ★ 卡 157 起：validate 会查
#      "队列指向的规格在不在" ⇒ 合成队列也要指向真文件
files = ["b.py"]
status = "pending"

[[cards]]
id = "003"
task = "T-G9x"
title = "已完成的样卡"
tree = ".wt/c"
spec = "复盘/卡/卡160-台账接进门.md"   # ★ 卡 157 起：validate 会查
#      "队列指向的规格在不在" ⇒ 合成队列也要指向真文件
files = ["c.py"]
status = "done"
"""


def _write_backlog(tmp_path: Path, body: str = _BACKLOG) -> Path:
    path = tmp_path / "workbacklog.toml"
    path.write_text(body, encoding="utf-8")
    return path


# ================================================================ ① 直测：pool.plan


def test_plan_load_validate_and_batches(tmp_path: Path) -> None:
    backlog = pool_plan.load_backlog(_write_backlog(tmp_path))
    assert [c.id for c in backlog.cards] == ["001", "002", "003"]
    assert pool_plan.validate(backlog) == []
    batches = pool_plan.plan_batches(backlog, 2)
    assert [[c.id for c in b] for b in batches] == [["001", "002"]]  # done 的 003 不进批次


def test_plan_validate_rejects_intersection(tmp_path: Path) -> None:
    body = _BACKLOG.replace('files = ["b.py"]', 'files = ["a.py"]')
    problems = pool_plan.validate(pool_plan.load_backlog(_write_backlog(tmp_path, body)))
    assert any("相交" in p for p in problems), problems


def test_plan_report_is_a_pure_function(tmp_path: Path) -> None:
    backlog = pool_plan.load_backlog(_write_backlog(tmp_path))
    code, out, err = pool_plan.plan_report(backlog, 2)
    assert code == 0 and err == ""
    assert out.startswith("[计划] 并发上限 2；3 张卡 → 1 批")
    assert "第 1 批（2 张，可同时跑）" in out


def test_plan_find_spec(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pool_plan, "ROOT", tmp_path)
    monkeypatch.setattr(pool_plan, "DIAG", tmp_path)
    (tmp_path / "卡777-某卡.md").write_text("x", encoding="utf-8")
    assert pool_plan.find_spec("777") == "卡777-某卡.md"
    assert pool_plan.find_spec("888") == ""


# ================================================================ ① 直测：pool.jobs


def _log_lines() -> list[str]:
    return [
        json.dumps({"type": "system", "subtype": "init", "model": "m1", "tools": ["Bash"]},
                   ensure_ascii=False),
        json.dumps({"type": "assistant",
                    "message": {"content": [{"type": "tool_use", "name": "Bash",
                                             "input": {"command": "git status"}}]}},
                   ensure_ascii=False),
        json.dumps({"type": "result", "subtype": "success", "result": "改完了"},
                   ensure_ascii=False),
    ]


def test_jobs_parse_events_summary() -> None:
    timeline, summary = jobs.parse_events(_log_lines())
    assert summary["tool_calls"] == 1 and summary["final"] == "改完了"
    assert any("Bash(command=git status)" in line for line in timeline)


def test_jobs_card_artifacts_does_not_cross_cards(tmp_path: Path) -> None:
    """精确匹配：卡 42 的产物不许命中卡 421（卡 029 §2.9 的串卡 bug）。"""
    diag = tmp_path / "gates" / "diag"
    diag.mkdir(parents=True)
    (diag / "wb-42.jsonl").write_text("{}", encoding="utf-8")
    (diag / "wb-421.jsonl").write_text("{}", encoding="utf-8")
    (diag / "wb-42.r2.jsonl").write_text("{}", encoding="utf-8")
    names = {p.name for p in jobs.card_artifacts(diag, "42", ".jsonl")}
    assert names == {"wb-42.jsonl", "wb-42.r2.jsonl"}


def test_jobs_classify_and_scan_by_evidence(tmp_path: Path) -> None:
    diag = tmp_path / "gates" / "diag"
    diag.mkdir(parents=True)
    (diag / "wb-101.jsonl").write_text("{}", encoding="utf-8")            # 新 → 在跑
    (diag / "wb-102.jsonl").write_text("{}", encoding="utf-8")            # 静默 → 断了
    (diag / "wb-103.jsonl").write_text("{}", encoding="utf-8")            # 有判决 → 已判决
    (diag / "wb-103.verdict.txt").write_text("ok", encoding="utf-8")
    now = 1_700_000_000.0
    import os
    old = now - jobs.STALL_SECONDS - 60
    os.utime(diag / "wb-102.jsonl", (old, old))
    rows = {r["card"]: r["state"] for r in jobs.scan_jobs(diag, now=now)}
    assert rows == {"101": "在跑", "102": "断了", "103": "已判决"}


def test_jobs_render_timeline_and_json() -> None:
    timeline, summary = jobs.parse_events(_log_lines())
    text = jobs.render_timeline("wb-1.jsonl", timeline, summary)
    assert text.startswith("=== WorkBuddy 状态器：wb-1.jsonl（事件 3 条）===")
    assert text.endswith("\n")
    assert json.loads(jobs.render_json("wb-1.jsonl", summary))["log"] == "wb-1.jsonl"


def test_jobs_diag_dir() -> None:
    assert jobs.diag_dir(Path("X")) == Path("X") / "gates" / "diag"


# ================================================================ ① 直测：pool.locks / pool.models


def test_locks_status_argv_and_is_empty() -> None:
    argv = locks.status_argv()
    assert argv[-2:] == ["gates/diag/gate_lock.py", "status"]
    assert "-P" in argv  # 铁律 24
    assert locks.is_empty("[锁] 空着（没有任何段的锁）") is True
    assert locks.is_empty("[锁] 段 base=8531 ...") is False


def test_models_find_and_load(tmp_path: Path) -> None:
    pool = tmp_path / "infra" / "pool"
    pool.mkdir(parents=True)
    (pool / "pool_models.py").write_text("", encoding="utf-8")
    (pool / "models.whitelist.toml").write_text(
        '[[approved]]\nmodel = "p/GLM-5.2"\n', encoding="utf-8")
    (pool / "models.live.json").write_text(json.dumps(
        {"at": "2026-10-01 00:00:00", "live": ["p/GLM-5.2", "p/other"],
         "live_names": {"p/GLM-5.2": "GLM-5.2"}}, ensure_ascii=False), encoding="utf-8")

    assert models.find_pool_dir(tmp_path) == pool
    info = models.load_pool_models(pool)
    assert info["approved"] == ["p/GLM-5.2"]
    assert info["in_both"] == ["p/GLM-5.2"]
    assert info["live_but_unapproved"] == ["p/other"]


# ================================================================ ② CLI 与库同一结论


def test_wb_plan_cli_and_library_agree(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """`wb_plan plan` 的 CLI 输出 == 直接调 `pool.plan.plan_report` 的 stdout（逐字）。"""
    path = _write_backlog(tmp_path)
    code = wb_plan.main(["plan", "--concurrency", "2", "--backlog", str(path)])
    cli_out = capsys.readouterr().out
    lib_code, lib_out, _ = pool_plan.plan_report(pool_plan.load_backlog(path), 2)
    assert code == lib_code == 0
    assert cli_out == lib_out


def test_wb_status_cli_and_library_agree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                         capsys: pytest.CaptureFixture) -> None:
    """`wb_status <log>` 的 CLI 输出 == 直接调 `pool.jobs` 渲染的同一段（逐字）。"""
    log = tmp_path / "wb-9.jsonl"
    log.write_text("\n".join(_log_lines()) + "\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["wb_status.py", str(log)])
    assert wb_status.main() == 0
    cli_out = capsys.readouterr().out

    lines = log.read_text(encoding="utf-8").splitlines()
    timeline, summary = jobs.parse_events(lines)
    assert cli_out == jobs.render_timeline(str(log), timeline, summary)


def test_wb_review_check_files_uses_the_library() -> None:
    """`wb_review.check_files()` 的越界判据就是 `pool.review.outside_allow()` 的结论。"""
    files = ["src/a.py", "docs/x.md"]
    assert wb_review.check_files(files, read_only=False, allow=["src/**"]) == \
        [f"有 {len(review.outside_allow(files, ['src/**']))} 个改动不在白名单里："
         f"{review.outside_allow(files, ['src/**'])[:8]}"]
    assert wb_review.check_files(["src/a.py"], read_only=False, allow=["src/**"]) == []


# ================================================================ ③ 白名单三处收敛：同一越界清单


def _porcelain_paths(lines: list[str]) -> list[str]:
    """porcelain 行（`XY path`）→ 纯仓库相对路径（posix 风格）。

    ★ 卡 109：`outside_allow` 的唯一实现只吃**纯路径**，porcelain → 纯路径的还原在调用点做
    （`wb_dispatch._porcelain_path()` 与这里同一口径）。
    """
    return [(ln[3:].strip() if len(ln) > 3 else ln).replace("\\", "/") for ln in lines]


def test_whitelist_three_entries_agree_including_chinese() -> None:
    """三处入口（`pool.review` / `tf_stage_guard` / `wb_dispatch`）对同一组暂存/脏文件给出
    **同一个**越界清单 —— 含**中文路径**（曾经被 git 八进制转义坑过）。

    ★ 卡 109 起三处是**同一个对象**（`outside_allow` 只有 `pool.review` 一份实现）。"""
    paths = ["tools/pool/plan.py", "复盘/中文卡.md", "src/越界的.py"]
    allow = ["tools/**", "复盘/中文卡.md"]
    expected = ["src/越界的.py"]

    review_outside = review.outside_allow(paths, allow)
    stage_outside = tf_stage_guard.outside_allow(paths, allow)
    dirty = [f" M {p}" for p in paths]   # 真 porcelain：`XY ` 三字符前缀
    dispatch_outside = wb_dispatch.outside_allow(_porcelain_paths(dirty), allow)
    assert review_outside == stage_outside == dispatch_outside == expected
