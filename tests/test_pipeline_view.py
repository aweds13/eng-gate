r"""`tools/pipeline_view.py`（卡 207 · T-G316）的测试 —— 一份只读读数。

为什么值当测：这个工具是「四个面集中到一个点」的那个**点** —— 判错的代价是口径漂
（同一件事各读各的）。所以六块各钉一条（字段名就是卡上写的那套），外加四条反例
（缺 `last.json` / 缺租约 / 坏栅栏 / 空判决）与幂等。

★ 只造**纯数据**（`tmp_path` 下的最小假仓），**不连网、不碰真仓**。
★ 卡 249（T-G370）追加：BLOCKS 声明表对账、缺源标注语、连续块（gates/leases）的
  STALE-WHILE-ERROR（last-good + error_code + stale_for_s）与坏态幂等反例。
★ 卡 255（T-G376）追加：内容哈希缓存（命中不重算 / 改一个字节就重算 / 坏源不被缓存
  掩盖）、冷跑热跑逐字节幂等、git 调用次数不随卡树数量增长（固定 2 次）。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import pipeline_view  # noqa: E402,I001 —— 需要先把 tools/ 挂上


# ------------------------------------------------------------------ 最小假仓


def _git(*a: str, cwd: Path) -> None:
    r = subprocess.run(["git", *a], cwd=str(cwd), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    assert r.returncode == 0, r.stderr


def _make_repo(tmp_path: Path) -> Path:
    """在 tmp_path 里建一个最小 git 仓（让 worktrees 块能读出来）。"""
    _git("init", "-q", cwd=tmp_path)
    _git("config", "user.email", "t@t", cwd=tmp_path)
    _git("config", "user.name", "t", cwd=tmp_path)
    (tmp_path / ".gitignore").write_text("*.tmp\n", encoding="utf-8")
    _git("add", ".gitignore", cwd=tmp_path)
    _git("commit", "-q", "-m", "init", cwd=tmp_path)
    return tmp_path


def _write_backlog(root: Path) -> None:
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "workbacklog.toml").write_text(
        '[base]\nreviewed = "abc1234"\n\n'
        '[[cards]]\n'
        'id = "001"\n'
        'task = "T-G1"\n'
        'title = "样卡一"\n'
        'tree = ".wt/a"\n'
        'spec = "复盘/卡/卡001.md"\n'
        'files = ["src/a.py"]\n'
        'depends = []\n'
        'risk = "low"\n'
        'status = "pending"\n',
        encoding="utf-8")


def _write_gates_last(root: Path, *, rev: str = "deadbee", at: str | None = None,
                      dirty: bool | None = None, branch: str | None = None) -> None:
    """★ 卡 E115：at / dirty / branch 是生产者（scripts/run_gates.py）一直在写的三项。"""
    (root / "gates").mkdir(parents=True, exist_ok=True)
    data: dict = {"ok": True, "rev": rev,
                  "gates": [{"name": "pytest", "exit_code": 0, "seconds": 1.5}]}
    if at is not None:
        data["at"] = at
    if dirty is not None:
        data["dirty"] = dirty
    if branch is not None:
        data["branch"] = branch
    (root / "gates" / "last.json").write_text(json.dumps(data, ensure_ascii=False),
                                              encoding="utf-8")


def _write_verdict(root: Path, card: str = "001", text: str = "card=001 通过\n") -> None:
    diag = root / "gates" / "diag"
    diag.mkdir(parents=True, exist_ok=True)
    (diag / f"wb-{card}.verdict.txt").write_text(text, encoding="utf-8")
    (diag / f"wb-{card}.report.md").write_text("# 摘要\n", encoding="utf-8")


def _write_artifact(root: Path, name: str, text: str) -> None:
    """★ 卡 E115：按**文件名**写产物（wb-120.killed.verdict.txt 这种带尝试标记的）。"""
    diag = root / "gates" / "diag"
    diag.mkdir(parents=True, exist_ok=True)
    (diag / name).write_text(text, encoding="utf-8")


def _commit(root: Path, name: str) -> str:
    """再落一笔提交并回它的 sha（判据 1 要「门禁 rev 落后 HEAD 几个提交」）。"""
    (root / name).write_text(name, encoding="utf-8")
    _git("add", name, cwd=root)
    _git("commit", "-q", "-m", name, cwd=root)
    done = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(root), capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def _now_naive_iso(hours_ago: float) -> str:
    """gates/last.json 的 at 口径：naive 本地时间（生产者就是这么写的）。"""
    stamp = datetime.now().astimezone() - timedelta(hours=hours_ago)
    return stamp.replace(tzinfo=None).isoformat(timespec="seconds")


def _registry_row(card: str, *, at: str, ttl: float | None = 21600.0,
                  log: str | None = None) -> dict:
    row: dict = {"card": card, "tree": f".wt/{card}", "files": ["src/a.py"],
                 "owner": "host:1", "at": at, "ttl_seconds": ttl}
    if log is not None:
        row["log"] = log
    return row


def _write_registry(root: Path, rows: list[dict] | None = None) -> None:
    diag = root / "gates" / "diag"
    diag.mkdir(parents=True, exist_ok=True)
    if rows is None:
        rows = [{"card": "001", "tree": ".wt/a", "files": ["src/a.py"],
                 "owner": "host:1", "at": "2026-10-13T12:00:00", "ttl_seconds": 21600.0}]
    (diag / "pool-registry.json").write_text(json.dumps(rows, ensure_ascii=False),
                                             encoding="utf-8")


def _write_fence(root: Path, task_id: str = "B-TEST") -> None:
    batch = root / "gates" / "diag" / "batch"
    batch.mkdir(parents=True, exist_ok=True)
    (batch / f"{task_id}.toml").write_text(
        f'id = "{task_id}"\nwhy = "测试"\non_complete = ["draft"]\n\n'
        '[[member]]\nid = "M-1"\nlayer = "工具层"\npaths = ["tools/x.py"]\n',
        encoding="utf-8")


def _full_fake_repo(tmp_path: Path) -> Path:
    """一份队列 + 一份 last.json + 一条判决 + 一份租约 + 一个栅栏 + git 仓。"""
    root = tmp_path / "repo"
    root.mkdir()
    _make_repo(root)
    _write_backlog(root)
    _write_gates_last(root)
    _write_verdict(root)
    _write_registry(root)
    _write_fence(root)
    return root


# ------------------------------------------------------------------ 1. 六块都读得出来


def test_six_blocks_all_present(tmp_path: Path) -> None:
    """最小假仓 ⇒ 六块都读得出来，且字段名就是卡上写的那套。"""
    root = _full_fake_repo(tmp_path)
    r = pipeline_view.build_reading(root)

    # 1. cards
    assert r["cards"] is not None
    assert len(r["cards"]) == 1
    c = r["cards"][0]
    assert c["id"] == "001"
    assert c["task"] == "T-G1"
    assert c["title"] == "样卡一"
    assert c["tree"] == ".wt/a"
    assert c["spec"] == "复盘/卡/卡001.md"
    assert c["files"] == ["src/a.py"]
    assert c["depends"] == []
    assert c["risk"] == "low"
    assert c["status"] == "pending"

    # 2. gates
    assert r["gates"] is not None
    assert r["gates"]["ok"] is True
    assert r["gates"]["rev"] == "deadbee"
    assert len(r["gates"]["items"]) == 1
    assert r["gates"]["items"][0]["name"] == "pytest"
    assert r["gates"]["items"][0]["exit_code"] == 0
    assert r["gates"]["items"][0]["seconds"] == 1.5

    # 3. verdicts
    assert len(r["verdicts"]) == 1
    v = r["verdicts"][0]
    assert v["card"] == "001"
    assert v["has_verdict"] is True
    assert v["verdict_first_line"] == "card=001 通过"
    assert v["has_report"] is True

    # 4. leases
    assert r["leases"] is not None
    assert len(r["leases"]) == 1
    lc = r["leases"][0]
    assert lc["card"] == "001"
    assert lc["tree"] == ".wt/a"
    assert lc["files"] == ["src/a.py"]
    assert lc["owner"] == "host:1"
    assert lc["at"] == "2026-10-13T12:00:00"
    assert lc["ttl_seconds"] == 21600.0

    # 5. fences
    assert len(r["fences"]) == 1
    f = r["fences"][0]
    assert f["id"] == "B-TEST"
    assert f["on_complete"] == ["draft"]
    assert f["members"] == 1

    # 6. worktrees
    assert r["worktrees"] is not None
    assert len(r["worktrees"]) >= 1
    w = r["worktrees"][0]
    assert "path" in w
    assert "head" in w
    assert "branch" in w
    assert "dirty" in w


# ------------------------------------------------------------------ 2. 反例①：缺 gates/last.json


def test_missing_gates_last_is_null_with_note(tmp_path: Path) -> None:
    """没有 gates/last.json ⇒ gates 是 null 且带说明（不许编一个绿）。"""
    root = tmp_path / "repo"
    root.mkdir()
    _make_repo(root)
    _write_backlog(root)
    # ★ 故意不写 gates/last.json
    _write_verdict(root)
    _write_registry(root)
    _write_fence(root)

    r = pipeline_view.build_reading(root)
    assert r["gates"] is None
    assert "gates_note" in r
    assert "last.json" in r["gates_note"]


# ------------------------------------------------------------------ 3. 反例②：缺租约文件


def test_missing_registry_is_empty_list(tmp_path: Path) -> None:
    """没有租约文件 ⇒ leases 是空表（不许报错）。"""
    root = tmp_path / "repo"
    root.mkdir()
    _make_repo(root)
    _write_backlog(root)
    _write_gates_last(root)
    _write_verdict(root)
    # ★ 故意不写 pool-registry.json
    _write_fence(root)

    r = pipeline_view.build_reading(root)
    assert r["leases"] == []


# ------------------------------------------------------------------ 4. 反例③：坏栅栏


def test_broken_fence_is_named_and_others_remain(tmp_path: Path) -> None:
    """坏掉的 B-*.toml ⇒ 点名且其余仍在。"""
    root = _full_fake_repo(tmp_path)
    batch = root / "gates" / "diag" / "batch"
    # 写一个坏 TOML
    (batch / "B-BROKEN.toml").write_text("this is not = valid = toml =\n", encoding="utf-8")

    r = pipeline_view.build_reading(root)
    # 好的仍在
    ids = [f["id"] for f in r["fences"]]
    assert "B-TEST" in ids
    # 坏的被点名
    broken = r.get("fences_broken") or []
    names = [b["file"] for b in broken]
    assert "B-BROKEN.toml" in names


# ------------------------------------------------------------------ 5. 反例④：空判决


def test_empty_verdict_is_reported_as_empty(tmp_path: Path) -> None:
    """判决文件是空的 ⇒ 如实说「空」，不许当「没跑」也不许当「通过」。"""
    root = _full_fake_repo(tmp_path)
    # 把判决文件写成空的
    (root / "gates" / "diag" / "wb-001.verdict.txt").write_text("", encoding="utf-8")

    r = pipeline_view.build_reading(root)
    v = r["verdicts"][0]
    assert v["card"] == "001"
    assert v["has_verdict"] is True          # 文件在 ⇒ 有判决
    assert v["verdict_first_line"] == ""     # 但首行是空 ⇒ 如实说空


# ------------------------------------------------------------------ 6. 幂等


def test_json_idempotent(tmp_path: Path) -> None:
    """连跑两次 --json 逐字节相同（不许写时间戳/随机序）。"""
    root = _full_fake_repo(tmp_path)
    a = pipeline_view.build_reading(root)
    b = pipeline_view.build_reading(root)
    ja = json.dumps(a, ensure_ascii=False, indent=2, sort_keys=True)
    jb = json.dumps(b, ensure_ascii=False, indent=2, sort_keys=True)
    assert ja == jb


def test_json_idempotent_via_cli(tmp_path: Path) -> None:
    """CLI 连跑两次 --json 逐字节相同。"""
    root = _full_fake_repo(tmp_path)
    out1 = subprocess.run(
        [sys.executable, "-X", "utf8", str(ROOT / "tools" / "pipeline_view.py"),
         "--json", "--root", str(root)],
        capture_output=True, text=True,
        encoding="utf-8", errors="replace", **pipeline_view.NO_WINDOW,
    ).stdout
    out2 = subprocess.run(
        [sys.executable, "-X", "utf8", str(ROOT / "tools" / "pipeline_view.py"),
         "--json", "--root", str(root)],
        capture_output=True, text=True,
        encoding="utf-8", errors="replace", **pipeline_view.NO_WINDOW,
    ).stdout
    assert out1 == out2


# ------------------------------------------------------------------ 7. 缺 backlog


def test_missing_backlog_is_null_with_note(tmp_path: Path) -> None:
    """没有 backlog ⇒ cards 是 null 且带说明。"""
    root = tmp_path / "repo"
    root.mkdir()
    _make_repo(root)
    # ★ 故意不写 backlog
    _write_gates_last(root)
    _write_verdict(root)
    _write_registry(root)
    _write_fence(root)

    r = pipeline_view.build_reading(root)
    assert r["cards"] is None
    assert "cards_note" in r


# ------------------------------------------------------------------ 8. 坏 last.json


def test_broken_gates_last_is_null_with_note(tmp_path: Path) -> None:
    """gates/last.json 坏了 ⇒ gates 是 null 且带说明。"""
    root = _full_fake_repo(tmp_path)
    (root / "gates" / "last.json").write_text("{not json", encoding="utf-8")

    r = pipeline_view.build_reading(root)
    assert r["gates"] is None
    assert "gates_note" in r


# ------------------------------------------------------------------ 9. report 有六块


def test_report_has_six_blocks(tmp_path: Path) -> None:
    """--report 输出六块都在，且能看出各自的来源。"""
    root = _full_fake_repo(tmp_path)
    out = _run_cli(root, "--report")
    for tag in ("[cards]", "[gates]", "[verdicts]", "[leases]", "[fences]", "[worktrees]"):
        assert tag in out, f"报告里缺 {tag}"
    assert "docs/workbacklog.toml" in out
    assert "gates/last.json" in out


# ======================================================================
# 卡 249（T-G370）：BLOCKS 声明表 + 连续块的 STALE-WHILE-ERROR
# ======================================================================


def _spec(bid: str) -> dict:
    """从 BLOCKS 声明表里取一块的口径。"""
    for b in pipeline_view.BLOCKS:
        if b["id"] == bid:
            return b
    raise AssertionError(f"BLOCKS 里没有 {bid}")


def _json_bytes(reading: dict) -> str:
    """与 CLI --json 同一把序列化口径（幂等比对用）。"""
    return json.dumps(reading, ensure_ascii=False, indent=2, sort_keys=True)


def _run_cli(root: Path, flag: str) -> str:
    """跑一次 CLI（带 NO_WINDOW），回 stdout。"""
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(ROOT / "tools" / "pipeline_view.py"),
         flag, "--root", str(root)],
        capture_output=True, text=True,
        encoding="utf-8", errors="replace", **pipeline_view.NO_WINDOW,
    ).stdout


def test_blocks_table_declares_six_blocks() -> None:
    """声明表六块齐全；每块都有 id/来源/缺源标注语/字段清单；连续块只有 gates+leases。"""
    ids = [b["id"] for b in pipeline_view.BLOCKS]
    assert ids == ["cards", "gates", "verdicts", "leases", "fences", "worktrees"]
    for b in pipeline_view.BLOCKS:
        for key in ("id", "source", "missing_note", "continuous", "fields", "row_fields"):
            assert key in b and b[key] != "", f"BLOCKS[{b.get('id')}] 缺 {key}"
        assert isinstance(b["fields"], tuple) and b["fields"]
        assert isinstance(b["row_fields"], tuple) and b["row_fields"]
    # 静态块与连续块的分界：continuous=True 的只有 gates / leases
    cont = [b["id"] for b in pipeline_view.BLOCKS if b["continuous"]]
    assert cont == ["gates", "leases"]


def test_json_rows_match_blocks_row_fields(tmp_path: Path) -> None:
    """--json 里每块的行字段与声明表的 row_fields 逐一对上（不许各写各的）。"""
    root = _full_fake_repo(tmp_path)
    r = pipeline_view.build_reading(root)
    payloads = {
        "cards": r["cards"][0], "gates": r["gates"], "verdicts": r["verdicts"][0],
        "leases": r["leases"][0], "fences": r["fences"][0],
        "worktrees": r["worktrees"][0],
    }
    for bid, payload in payloads.items():
        assert set(payload) == set(_spec(bid)["row_fields"]), f"{bid} 行字段与声明表不符"


def test_json_sources_and_fields_come_from_blocks(tmp_path: Path) -> None:
    """--json 每块都带 *_source 回声且等于声明表；块字段都在声明表 fields 里。"""
    root = _full_fake_repo(tmp_path)
    r = pipeline_view.build_reading(root)
    for b in pipeline_view.BLOCKS:
        bid = b["id"]
        assert r[f"{bid}_source"] == b["source"], f"{bid} 的来源回声与声明表不符"
        for f in b["fields"]:
            assert f in r, f"--json 缺 {bid} 的字段 {f}"


def test_missing_source_yields_null_with_blocks_note(tmp_path: Path) -> None:
    """判据 b：来源文件改名 ⇒ 该块 null + 声明表那句标注语（不是空对象/空串）。"""
    root = _full_fake_repo(tmp_path)
    (root / "docs" / "workbacklog.toml").rename(root / "docs" / "workbacklog.toml.bak")
    (root / "gates" / "last.json").rename(root / "gates" / "last.json.bak")
    try:
        r = pipeline_view.build_reading(root)
        assert r["cards"] is None
        assert r["cards_note"] == _spec("cards")["missing_note"]
        assert r["cards_note"].strip() != ""
        # gates 没有上一份好读数（没跑过成功读数）⇒ 退回「缺什么说什么」
        assert r["gates"] is None
        assert r["gates_note"] == _spec("gates")["missing_note"]
    finally:
        (root / "docs" / "workbacklog.toml.bak").rename(root / "docs" / "workbacklog.toml")
        (root / "gates" / "last.json.bak").rename(root / "gates" / "last.json")
    r2 = pipeline_view.build_reading(root)
    assert r2["cards"] is not None
    assert r2["gates"] is not None


def test_continuous_blocks_keep_last_good_on_failure(tmp_path: Path, monkeypatch) -> None:
    """判据 c：连续块改名来源 ⇒ 仍是上一份好值 + error_code；坏态幂等；恢复后仍逐字节幂等。"""
    root = _full_fake_repo(tmp_path)
    monkeypatch.setattr(pipeline_view, "_REMEMBER", True)  # ★ 监测路径才落快照
    r1 = pipeline_view.build_reading(root)
    good_gates = r1["gates"]
    good_leases = r1["leases"]
    lastgood = root / "gates" / "diag" / "pipeline-view-lastgood.json"
    assert lastgood.exists(), "成功读数后应落 last-good 快照"
    (root / "gates" / "last.json").rename(root / "gates" / "last.json.bak")
    # leases 的「文件不在」是合法空表（既有判据钉着）——连续块的「失败」用坏文件触发
    (root / "gates" / "diag" / "pool-registry.json").write_text("{not json", encoding="utf-8")
    try:
        r2 = pipeline_view.build_reading(root)
        # gates：改名 ⇒ 仍是上一份好值 + error_code=source_missing
        assert r2["gates"] == good_gates
        assert r2["gates_stale"]["error_code"] == "source_missing"
        assert r2["gates_stale"]["captured_at"], "stale 必须带快照的 captured_at"
        # leases：坏文件 ⇒ 仍是上一份好值 + error_code=source_broken
        assert r2["leases"] == good_leases
        assert r2["leases_stale"]["error_code"] == "source_broken"
        # 判据 a 的反例钩子：坏态连跑两次 --json 仍逐字节相同
        # （谁把墙钟写进 --json 的 stale 字段，这里就红）
        assert _json_bytes(r2) == _json_bytes(pipeline_view.build_reading(root))
        # stale_for_s 只进人读出口（--report），不进 --json
        out = _run_cli(root, "--report")
        assert "stale_for_s=" in out
        assert "stale_for_s" not in _json_bytes(r2)
    finally:
        (root / "gates" / "last.json.bak").rename(root / "gates" / "last.json")
        _write_registry(root)  # 把写成坏 JSON 的租约文件恢复原状
    r3 = pipeline_view.build_reading(root)
    assert r3["gates"] == good_gates
    assert "gates_stale" not in r3 and "leases_stale" not in r3
    # ★ 恢复原状后 --json 仍逐字节幂等（与坏掉之前那份一致）
    assert _json_bytes(r3) == _json_bytes(r1)


def test_broken_continuous_source_uses_last_good(tmp_path: Path, monkeypatch) -> None:
    """判据 c 的坏文件变体：连续块来源坏了 ⇒ 上一份好值 + error_code=source_broken。"""
    root = _full_fake_repo(tmp_path)
    monkeypatch.setattr(pipeline_view, "_REMEMBER", True)  # ★ 监测路径才落快照
    r1 = pipeline_view.build_reading(root)
    good_gates = r1["gates"]
    good_leases = r1["leases"]
    (root / "gates" / "diag" / "pool-registry.json").write_text("{not json", encoding="utf-8")
    (root / "gates" / "last.json").write_text("{not json", encoding="utf-8")
    r2 = pipeline_view.build_reading(root)
    assert r2["leases"] == good_leases
    assert r2["leases_stale"]["error_code"] == "source_broken"
    assert r2["gates"] == good_gates
    assert r2["gates_stale"]["error_code"] == "source_broken"
    # 没有快照的坏块仍走「缺什么说什么」：换一个没跑过成功读数的新仓
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    _make_repo(fresh)
    _write_gates_last(fresh)
    (fresh / "gates" / "last.json").write_text("{not json", encoding="utf-8")
    r3 = pipeline_view.build_reading(fresh)
    assert r3["gates"] is None
    assert r3["gates_note"].strip() != ""


def test_report_block_sources_match_blocks_and_json(tmp_path: Path) -> None:
    """判据 d：--report 每块的名字与来源 == 声明表 == --json 的 *_source 回声。"""
    root = _full_fake_repo(tmp_path)
    out = _run_cli(root, "--report")
    r = pipeline_view.build_reading(root)
    for b in pipeline_view.BLOCKS:
        bid = b["id"]
        tag = f"[{bid}]"
        line = next((ln for ln in out.splitlines() if ln.startswith(tag)), None)
        assert line is not None, f"--report 缺 {tag}"
        # 只取「（来源 X）」/「（来源 X，…」里的 X 整段比（子串比对会放过 .bak 这类突变）
        assert "（来源 " in line, f"{tag} 报告头没有标来源：{line}"
        seg = line.split("（来源 ", 1)[1].split("）", 1)[0].split("，", 1)[0]
        assert seg == b["source"], f"{tag} 的来源与声明表不符：{line!r}"
        assert r[f"{bid}_source"] == b["source"], f"--json 的 {bid}_source 与声明表不符"


def test_report_missing_block_still_names_source(tmp_path: Path) -> None:
    """判据 d 的缺源变体：块缺失时 report 头仍带声明表那句来源（两个出口照样对得上）。"""
    root = _full_fake_repo(tmp_path)
    batch = root / "gates" / "diag" / "batch"
    batch.rename(root / "gates" / "diag" / "batch.bak")
    out = _run_cli(root, "--report")
    line = next(ln for ln in out.splitlines() if ln.startswith("[fences]"))
    assert "没有 gates/diag/batch 目录" in line, line
    assert "（来源 " in line, f"[fences] 缺源时报告头没有标来源：{line}"
    seg = line.split("（来源 ", 1)[1].split("）", 1)[0]
    assert seg == _spec("fences")["source"], f"[fences] 缺源时的来源与声明表不符：{line!r}"
    # --json 那一侧同一块仍是 null + 同一句标注语
    r = pipeline_view.build_reading(root)
    assert r["fences"] == []
    assert r["fences_note"] == _spec("fences")["missing_note"]


# ======================================================================
# 卡 255（T-G376）：内容哈希缓存 + 只读首行 + git 固定两次
# ======================================================================


def _write_big_backlog(root: Path, n: int = 5000) -> None:
    """写一份**大**队列（让「命中就不解析」能用耗时看出来，而不是靠嘴说）。"""
    parts = ['[base]\nreviewed = "abc1234"\n']
    for i in range(n):
        parts.append(
            "\n[[cards]]\n"
            f'id = "{i:05d}"\n'
            f'task = "T-X{i}"\n'
            f'title = "样卡 {i}"\n'
            'tree = ".wt/a"\n'
            'spec = "复盘/卡/卡001.md"\n'
            'files = ["src/a.py"]\n'
            'depends = []\n'
            'risk = "low"\n'
            'status = "pending"\n')
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "workbacklog.toml").write_text("".join(parts), encoding="utf-8")


def _cache_file(root: Path, bid: str) -> Path:
    return root / "gates" / "diag" / "readcache" / f"{bid}.json"


def test_cache_hit_skips_recompute_and_is_faster(tmp_path: Path, monkeypatch) -> None:
    """判据 a：连跑两次，第二次命中缓存 ⇒ 不重算、耗时明显更短（贴两次耗时）。

    反例：把缓存短路（每次都比对失败/直接 compute）⇒ `_CACHE_HITS` 断言当场红。
    """
    root = _full_fake_repo(tmp_path)
    _write_big_backlog(root, 5000)
    monkeypatch.setattr(pipeline_view, "_REMEMBER", True)  # ★ 会写缓存；跑完自动还原

    t0 = time.perf_counter()
    r1 = pipeline_view.build_reading(root)
    cold = time.perf_counter() - t0
    assert "cards" in pipeline_view._CACHE_MISSES, "第一次应是冷跑（重算）"
    assert "cards" not in pipeline_view._CACHE_HITS

    # ★ 卡 E26：判「命中就不许重算」不许比墙钟 —— 4 worker 全量门禁下 hot 会被邻居抢核
    # 拖慢（实测 cold=0.4870s hot=0.6039s、0.4938s vs 0.6910s 两次假红），比的是机器忙不忙，
    # 不是缓存灵不灵。改成数「重算路径被调了几次」：命中就必须是 0 次。
    calls = {"cards": 0}
    real_read_cards = pipeline_view._read_cards

    def _counting_read_cards(path):
        calls["cards"] += 1
        return real_read_cards(path)

    monkeypatch.setattr(pipeline_view, "_read_cards", _counting_read_cards)
    t0 = time.perf_counter()
    r2 = pipeline_view.build_reading(root)
    hot = time.perf_counter() - t0
    print(f"\n[卡255-a] cold={cold:.4f}s hot={hot:.4f}s（{len(r1['cards'])} 张卡）")
    assert "cards" in pipeline_view._CACHE_HITS, "第二次应命中缓存"
    assert "cards" not in pipeline_view._CACHE_MISSES, "命中就不许重算"
    assert calls["cards"] == 0, f"命中还重算了解析路径：{calls['cards']} 次"
    assert _json_bytes(r1) == _json_bytes(r2), "冷/热读数必须逐字节相同"
    assert len(r2["cards"]) == 5000


def test_cache_recomputes_when_content_changes(tmp_path: Path, monkeypatch) -> None:
    """判据 b：改一个字节就必须重算 —— 连 mtime 与 size 都保持原样也要认出来。

    反例：缓存键只算 mtime（或 mtime+size）⇒ 同秒同长度改内容 ⇒ 命中旧值 ⇒ 断言红。
    """
    root = _full_fake_repo(tmp_path)
    monkeypatch.setattr(pipeline_view, "_REMEMBER", True)
    backlog = root / "docs" / "workbacklog.toml"
    before = backlog.stat()
    r1 = pipeline_view.build_reading(root)
    assert r1["cards"][0]["title"] == "样卡一"

    text = backlog.read_text(encoding="utf-8")
    changed = text.replace("样卡一", "样卡二")
    assert changed != text and len(changed.encode()) == len(text.encode())
    backlog.write_text(changed, encoding="utf-8")
    # ★ 把 mtime 还原到改动前：只有内容 sha256 能认出这次变化。
    os.utime(backlog, ns=(before.st_atime_ns, before.st_mtime_ns))

    r2 = pipeline_view.build_reading(root)
    print(f"\n[卡255-b] 命中={pipeline_view._CACHE_HITS} 重算={pipeline_view._CACHE_MISSES}")
    assert "cards" in pipeline_view._CACHE_MISSES, "内容变了必须重算"
    assert r2["cards"][0]["title"] == "样卡二", "读数必须跟着变"


def test_cache_never_masks_broken_or_missing_source(tmp_path: Path, monkeypatch) -> None:
    """缓存命中 ≠ 数据对：来源坏了/缺失时仍走 STALE-WHILE-ERROR（不拿旧缓存冒充）。"""
    root = _full_fake_repo(tmp_path)
    monkeypatch.setattr(pipeline_view, "_REMEMBER", True)
    good = pipeline_view.build_reading(root)
    good_gates = good["gates"]
    assert _cache_file(root, "gates").is_file(), "成功读数应写缓存"

    (root / "gates" / "last.json").write_text("{not json", encoding="utf-8")
    broken = pipeline_view.build_reading(root)
    assert broken["gates"] == good_gates
    assert broken["gates_stale"]["error_code"] == "source_broken"

    (root / "gates" / "last.json").unlink()
    missing = pipeline_view.build_reading(root)
    assert missing["gates"] == good_gates
    assert missing["gates_stale"]["error_code"] == "source_missing"


def test_json_identical_cold_then_hot_and_cache_location(tmp_path: Path) -> None:
    """判据 c：`--json` 冷跑/热跑逐字节相同；缓存落在 gates/diag/readcache/（不是 docs/）。"""
    root = _full_fake_repo(tmp_path)
    out1 = _run_cli(root, "--json")
    assert _cache_file(root, "cards").is_file(), "冷跑应写缓存"
    assert _cache_file(root, "gates").is_file()
    assert not (root / "docs" / "readcache").exists(), "缓存不许放 docs/"
    out2 = _run_cli(root, "--json")
    assert out1 == out2, "冷跑与热跑必须逐字节相同"
    report = _run_cli(root, "--report")
    assert "重算 0 块" in report, f"热跑之后应全命中：\n{report[-400:]}"


def test_git_calls_do_not_scale_with_worktrees(tmp_path: Path) -> None:
    """判据 d：git 调用固定 2 次（worktree list + status），不随卡树数量增长。

    反例：回到「每棵树各起一次 git status」⇒ 两棵树时是 3 次 ⇒ 断言红。
    """
    root = _full_fake_repo(tmp_path)
    extra = tmp_path / "wt-extra"
    _git("worktree", "add", "-q", str(extra), "-b", "wt-extra", cwd=root)

    r = pipeline_view.build_reading(root)
    print(f"\n[卡255-d] git 调用={pipeline_view._GIT_CALLS} 卡树={len(r['worktrees'])} 棵")
    assert pipeline_view._GIT_CALLS == 2, "一次读数固定两条 git 命令"
    assert len(r["worktrees"]) == 2, "两棵树都要列出来"
    root_row = next(w for w in r["worktrees"]
                    if Path(w["path"]).resolve() == root.resolve())
    extra_row = next(w for w in r["worktrees"]
                     if Path(w["path"]).resolve() == extra.resolve())
    assert root_row["dirty"] is True, "读数根有未跟踪文件 ⇒ 脏"
    assert extra_row["dirty"] is None, "其余树没起 git ⇒ dirty=null（未知），不许冒充 false"
    assert "worktrees_dirty_note" in r
    report = _run_cli(root, "--report")
    # ★ 卡 E115：--report 多一条 git rev-list（算「落后几个提交」）⇒ 这里是 3；
    #   上面的 _GIT_CALLS == 2 一个字不动（读数本身仍只调两条 git 命令）。
    assert "[git] 本次调用 3 次" in report


# ---------------------------------------------------------------- 卡 E115（T-AG626）
# ★ 口径（判据 1）：小时数与落后提交数**只许出现在 --report**；--json 里只准有 at/dirty/
#   branch 三个静态值。拿 JSON 字段冒充「念出来了」在这三条钉子上会假绿，所以分开判。


def test_report_gates_says_age_and_commits_behind(tmp_path: Path) -> None:
    """判据 1：--report 的 [gates] 段念出「X 小时前」与「落后 N 个提交」，两个数都是现算的。

    ★ 仓里两笔提交：gates/last.json 的 rev 指向第 1 笔 ⇒ 落后 1 个；at 是 5h30m 前。
    """
    root = _full_fake_repo(tmp_path)
    first = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(root), capture_output=True,
                           text=True, encoding="utf-8", errors="replace").stdout.strip()
    assert _commit(root, "second.txt") != first, "第二笔提交必须换 HEAD"
    at = _now_naive_iso(5.5)
    _write_gates_last(root, rev=first, at=at, dirty=True, branch="card/E115")

    r = pipeline_view.build_reading(root)
    assert r["gates"]["at"] == at, "at 必须逐字搬进 --json（它是静态值，不是墙钟）"
    assert r["gates"]["dirty"] is True
    assert r["gates"]["branch"] == "card/E115"
    raw = _json_bytes(r)
    assert "小时前" not in raw and "落后" not in raw, "墙钟与 git 计数一个都不许进 --json"

    report = _run_cli(root, "--report")
    head = report.split("[gates]", 1)[1].splitlines()[0]
    hours = re.search(r"(\d+(?:\.\d+)?)\s*小时前", head)
    assert hours is not None, f"没念「X 小时前」：{head}"
    assert 4.9 <= float(hours.group(1)) <= 6.1, f"小时数不是现算的：{head}"
    behind = re.search(r"落后\s*(\d+)\s*个提交", head)
    assert behind is not None, f"没念「落后 N 个提交」：{head}"
    assert int(behind.group(1)) == 1, f"落后数不对：{head}"
    assert "card/E115" in report and "树 脏" in report, "那趟跑在哪条分支、树脏不脏也要念"
    assert "认不出 rev=" not in report, "认得出的 rev 不该报认不出"


def test_report_gates_says_unknown_when_rev_is_unreadable(tmp_path: Path) -> None:
    """判据 1 的失败分支：认不出的 rev 必须如实说，不许抛异常（既有夹具就是 deadbee）。"""
    root = _full_fake_repo(tmp_path)
    report = _run_cli(root, "--report")   # 默认夹具 rev="deadbee"
    assert "[gates]" in report, "整份报告不许因为 git rc=128 就崩"
    seg = report.split("[gates]", 1)[1].split("[verdicts]", 1)[0]
    assert "认不出 rev=deadbee" in seg
    # 只判 [gates] 段：--report 尾巴的实测账里本来就有「落后几个提交」这串字
    assert "落后" not in seg, "认不出就不许编一个数字"


def test_leases_mark_dead_without_dropping(tmp_path: Path) -> None:
    """判据 2：死租约只标 dead，**不许过滤**（行数不变），也不许另写一份判据。

    三条理由（写进代码注释的那三条）：过滤抹掉「曾有人占过树」的证据 / 会改既有夹具口径 /
    落盘清死租约是 registry.prune 的职责。
    """
    root = _full_fake_repo(tmp_path)
    _write_registry(root, [
        _registry_row("901", at=_now_naive_iso(7.0)),   # 7h 前 + ttl 6h ⇒ 死
        _registry_row("902", at=_now_naive_iso(1.0)),   # 1h 前 ⇒ 活
    ])

    r = pipeline_view.build_reading(root)
    assert len(r["leases"]) == 2, "死的不许从表里抹掉（行数必须还是 2）"
    dead = {row["card"]: row["dead"] for row in r["leases"]}
    assert dead == {"901": True, "902": False}, dead

    report = _run_cli(root, "--report")
    assert "其中 1 条已死" in report, "人话段必须念出死了几条（否则读者以为都活着）"


def test_leases_log_only_death_is_honoured(tmp_path: Path) -> None:
    """判据 2 第二支：TTL 远没到、但日志已被判死 ⇒ 仍要点成死（这一支只有 _log_dead 能判）。"""
    root = _full_fake_repo(tmp_path)
    diag = root / "gates" / "diag"
    (diag / "wb-009.jsonl").write_text("{}\n", encoding="utf-8")
    (diag / "wb-009.verdict.txt").write_text("card=009 结束于=2026-10-01T10:00:00\n",
                                             encoding="utf-8")
    _write_registry(root, [
        _registry_row("009", at=_now_naive_iso(1.0), ttl=10 ** 9,
                      log="gates/diag/wb-009.jsonl"),
    ])

    r = pipeline_view.build_reading(root)
    row = next(x for x in r["leases"] if x["card"] == "009")
    assert row["ttl_seconds"] == 10 ** 9, "TTL 这一支一定判不了它（没到）"
    assert row["dead"] is True, "日志已判死 ⇒ 必须点成死（复用 registry.is_dead，不另写判据）"


def test_verdicts_one_row_per_card_with_attempts(tmp_path: Path) -> None:
    """判据 3：一卡一行 + attempts —— 120 与 120.killed 不许并列成两行。"""
    root = _full_fake_repo(tmp_path)
    _write_artifact(root, "wb-007.verdict.txt", "card=007 结束于=2026-10-02T20:00:00\n")
    _write_artifact(root, "wb-007.r2.verdict.txt", "card=007 结束于=2026-10-02T19:00:00\n")
    _write_artifact(root, "wb-120.killed.verdict.txt", "card=120 结束于=2026-10-03T08:00:00\n")
    _write_artifact(root, "wb-120.verdict.txt", "card=120 结束于=2026-10-03T09:00:00\n")

    r = pipeline_view.build_reading(root)
    rows = {row["card"]: row for row in r["verdicts"]}
    assert set(rows) == {"001", "007", "120"}, f"不该多出带点的假卡号：{sorted(rows)}"
    assert len({row["card"] for row in r["verdicts"]}) == len(r["verdicts"]), "一卡只许一行"
    assert "120.killed" not in rows and "007.r2" not in rows
    assert {a["att"] for a in rows["120"]["attempts"]} == {"", "killed"}
    assert len(rows["007"]["attempts"]) == 2
    assert rows["007"]["selected"] == "", "基名那次更晚（20:00 > 19:00）⇒ 现行的必须是无后缀那次"
    assert rows["120"]["selected"] == "", "120 那次也更晚"
    assert rows["007"]["verdict_first_line"] == "card=007 结束于=2026-10-02T20:00:00", \
        "verdict_first_line 仍是 selected 那一次的首行（老字段语义不变）"
    assert rows["007"]["has_verdict"] is True and rows["007"]["has_report"] is False


def test_verdicts_selected_is_latest_by_ended_at(tmp_path: Path) -> None:
    """判据 3 第二支：selected 按「结束于=」取最新；认不出时刻就回落，不许按文件名排序。"""
    root = _full_fake_repo(tmp_path)
    _write_artifact(root, "wb-008.verdict.txt", "card=008 结束于=2026-10-02T19:00:00\n")
    _write_artifact(root, "wb-008.r2.verdict.txt", "card=008 结束于=2026-10-02T20:00:00\n")
    _write_artifact(root, "wb-260.report.md", "# 卡 260 的交接摘要\n")   # 只有摘要、没有结束于=

    r = pipeline_view.build_reading(root)
    rows = {row["card"]: row for row in r["verdicts"]}
    assert rows["008"]["selected"] == "r2", "r2 确实更晚 ⇒ 按文件名挑 base 是错的"
    assert rows["260"]["selected"] == "", "认不出时刻 ⇒ 回落到唯一那个无后缀尝试"
    assert rows["260"]["has_verdict"] is False and rows["260"]["has_report"] is True


def test_report_verdicts_says_attempts(tmp_path: Path) -> None:
    """判据 3 的人话面：跑过几次说几次，现行是哪一个也念出来。"""
    root = _full_fake_repo(tmp_path)
    _write_artifact(root, "wb-007.verdict.txt", "card=007 结束于=2026-10-02T20:00:00\n")
    _write_artifact(root, "wb-007.killed.verdict.txt", "card=007 结束于=2026-10-02T10:00:00\n")

    report = _run_cli(root, "--report")
    seg = report.split("[verdicts]", 1)[1].split("[leases]", 1)[0]
    assert "共 2 张卡有产物" in seg, f"一卡一行之后是 2 张（001 与 007）：{seg}"
    assert "2 次尝试" in seg, f"007 跑过两次必须念出来：{seg}"
    assert "现行=无后缀那次" in seg, f"现行是哪一个也要念：{seg}"
