r"""`tools/pipeline_view.py`（卡 207 · T-G316）的测试 —— 一份只读读数。

为什么值当测：这个工具是「四个面集中到一个点」的那个**点** —— 判错的代价是口径漂
（同一件事各读各的）。所以六块各钉一条（字段名就是卡上写的那套），外加四条反例
（缺 `last.json` / 缺租约 / 坏栅栏 / 空判决）与幂等。

★ 只造**纯数据**（`tmp_path` 下的最小假仓），**不连网、不碰真仓**。
"""

from __future__ import annotations

import json
import subprocess
import sys
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


def _write_gates_last(root: Path) -> None:
    (root / "gates").mkdir(parents=True, exist_ok=True)
    (root / "gates" / "last.json").write_text(json.dumps({
        "ok": True, "rev": "deadbee",
        "gates": [{"name": "pytest", "exit_code": 0, "seconds": 1.5}],
    }, ensure_ascii=False), encoding="utf-8")


def _write_verdict(root: Path, card: str = "001", text: str = "card=001 通过\n") -> None:
    diag = root / "gates" / "diag"
    diag.mkdir(parents=True, exist_ok=True)
    (diag / f"wb-{card}.verdict.txt").write_text(text, encoding="utf-8")
    (diag / f"wb-{card}.report.md").write_text("# 摘要\n", encoding="utf-8")


def _write_registry(root: Path) -> None:
    diag = root / "gates" / "diag"
    diag.mkdir(parents=True, exist_ok=True)
    (diag / "pool-registry.json").write_text(json.dumps([{
        "card": "001", "tree": ".wt/a", "files": ["src/a.py"],
        "owner": "host:1", "at": "2026-10-13T12:00:00", "ttl_seconds": 21600.0,
    }], ensure_ascii=False), encoding="utf-8")


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
        capture_output=True, text=True, encoding="utf-8", **pipeline_view.NO_WINDOW,
    ).stdout
    out2 = subprocess.run(
        [sys.executable, "-X", "utf8", str(ROOT / "tools" / "pipeline_view.py"),
         "--json", "--root", str(root)],
        capture_output=True, text=True, encoding="utf-8", **pipeline_view.NO_WINDOW,
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
    out = subprocess.run(
        [sys.executable, "-X", "utf8", str(ROOT / "tools" / "pipeline_view.py"),
         "--report", "--root", str(root)],
        capture_output=True, text=True, encoding="utf-8", **pipeline_view.NO_WINDOW,
    ).stdout
    for tag in ("[cards]", "[gates]", "[verdicts]", "[leases]", "[fences]", "[worktrees]"):
        assert tag in out, f"报告里缺 {tag}"
    assert "docs/workbacklog.toml" in out
    assert "gates/last.json" in out
