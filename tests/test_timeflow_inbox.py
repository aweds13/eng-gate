r"""`tools/timeflow_inbox.py`（卡 222 · T-G336）的测试 —— 只读收件箱：批 / 复核 / 翻 status。

为什么值当测：它是「该我做的事」那一份视图的**唯一出口** —— 读错口径就会把「还缺卡」看成
「齐了该收口」（提前收口）或反过来（永远等）。所以三桶各钉一条，外加四条边界
（缺批目录 / 缺队列 / 批没状态文件 / 判决在但队列无条目）与**只读 + 幂等**两条硬判据。

★ 只造**纯数据**（`tmp_path` 下的最小假仓），**不连网、不碰真仓**。
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import pipeline_view  # noqa: E402,I001 —— 需要先把 tools/ 挂上
import timeflow_inbox  # noqa: E402,I001

TOOL = ROOT / "tools" / "timeflow_inbox.py"


# ------------------------------------------------------------------ 最小假仓


def _git(*a: str, cwd: Path) -> None:
    done = subprocess.run(["git", *a], cwd=str(cwd), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", **pipeline_view.NO_WINDOW)
    assert done.returncode == 0, done.stderr


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
    """两张卡的队列：001 还 pending，002 已 done（= 已翻篇，桶 B/C 都不该收它）。"""
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "workbacklog.toml").write_text(
        '[base]\nreviewed = "abc1234"\n\n'
        '[[cards]]\nid = "001"\ntask = "T-G1"\ntitle = "样卡一"\ntree = ".wt/a"\n'
        'spec = "复盘/卡/卡001.md"\nfiles = ["src/a.py"]\ndepends = []\n'
        'risk = "low"\nstatus = "pending"\n\n'
        '[[cards]]\nid = "002"\ntask = "T-G2"\ntitle = "样卡二"\ntree = ".wt/b"\n'
        'spec = "复盘/卡/卡002.md"\nfiles = ["src/b.py"]\ndepends = []\n'
        'risk = "low"\nstatus = "done"\n',
        encoding="utf-8")


def _write_gates_last(root: Path) -> None:
    (root / "gates").mkdir(parents=True, exist_ok=True)
    (root / "gates" / "last.json").write_text(json.dumps({
        "ok": True, "rev": "deadbee",
        "gates": [{"name": "pytest", "exit_code": 0, "seconds": 1.5}],
    }, ensure_ascii=False), encoding="utf-8")


def _write_verdict(root: Path, card: str, first: str = "card=%s 第=1 次 退出码=0\n") -> None:
    diag = root / "gates" / "diag"
    diag.mkdir(parents=True, exist_ok=True)
    (diag / f"wb-{card}.verdict.txt").write_text(first % card, encoding="utf-8")
    (diag / f"wb-{card}.report.md").write_text("# 摘要\n", encoding="utf-8")


def _write_fence(root: Path, batch_id: str) -> None:
    batch = root / "gates" / "diag" / "batch"
    batch.mkdir(parents=True, exist_ok=True)
    (batch / f"{batch_id}.toml").write_text(
        f'id = "{batch_id}"\nwhy = "测试"\non_complete = ["draft"]\n\n'
        '[[member]]\nid = "M-1"\nlayer = "工具层"\npaths = ["tools/x.py"]\n\n'
        '[[member]]\nid = "M-2"\nlayer = "工具层"\npaths = ["tools/y.py"]\n',
        encoding="utf-8")


def _write_state(root: Path, batch_id: str, *, state: str, claims: dict | None = None,
                 declared: list | None = None, need: int | None = None) -> None:
    declared = declared if declared is not None else ["M-1", "M-2"]
    batch = root / "gates" / "diag" / "batch"
    batch.mkdir(parents=True, exist_ok=True)
    (batch / f"{batch_id}.json").write_text(json.dumps({
        "id": batch_id, "why": "测试批", "declared": declared, "read_only": [],
        "need": need if need is not None else len(declared),
        "claims": claims or {}, "waived": [], "state": state,
    }, ensure_ascii=False), encoding="utf-8")


def _full_fake_repo(tmp_path: Path) -> Path:
    """一份队列 + 一份 last.json + 两条判决 + 一个栅栏（还缺 M-2）。"""
    root = tmp_path / "repo"
    root.mkdir()
    _make_repo(root)
    _write_backlog(root)
    _write_gates_last(root)
    _write_verdict(root, "001")     # 001 还 pending
    _write_verdict(root, "002")     # 002 已 done ⇒ 桶 B 不该收它
    _write_fence(root, "B-TEST")
    _write_state(root, "B-TEST", state="collecting", claims={"M-1": "success"})
    return root


def _snapshot(root: Path) -> dict[str, bytes]:
    """工作区里每个文件的字节（**排除 `.git/`** —— git 自己会刷索引，那不是我们的写）。"""
    out: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and ".git" not in path.relative_to(root).parts:
            out[path.relative_to(root).as_posix()] = path.read_bytes()
    return out


# ------------------------------------------------------------------ 1. 三桶都读得出来


def test_three_buckets_on_fake_repo(tmp_path: Path) -> None:
    """最小假仓 ⇒ 三桶各就各位：批还缺 M-2、待复核只有 001、待翻只有 001。"""
    root = _full_fake_repo(tmp_path)
    inbox = timeflow_inbox.build_inbox(root)

    batches = inbox["batches"]["open"]
    assert [b["id"] for b in batches] == ["B-TEST"]
    row = batches[0]
    assert row["state"] == "collecting"
    assert row["awaiting"] is False
    assert row["need"] == 2 and row["done"] == 1
    assert row["missing"] == ["M-2"]

    assert [r["card"] for r in inbox["review"]["cards"]] == ["001"]
    assert inbox["review"]["cards"][0]["has_report"] is True

    assert [r["card"] for r in inbox["status_flip"]["cards"]] == ["001"]


# ------------------------------------------------------------------ 2. 批「齐了」要标出来


def test_awaiting_batch_is_flagged_with_action(tmp_path: Path) -> None:
    """状态 `awaiting-commit` ⇒ awaiting=True 且给「跑 wb_land --batch」这句动作。"""
    root = _full_fake_repo(tmp_path)
    _write_state(root, "B-TEST", state="awaiting-commit",
                 claims={"M-1": "success", "M-2": "success"})
    inbox = timeflow_inbox.build_inbox(root)
    row = inbox["batches"]["open"][0]
    assert row["awaiting"] is True
    assert row["missing"] == []
    assert "wb_land.py --batch B-TEST" in row["action"]


# ------------------------------------------------------------------ 3. 已 landed 的批不算待办


def test_landed_batch_is_not_open(tmp_path: Path) -> None:
    """`landed` 的批不进桶 A 的 open，只记进 landed 计数。"""
    root = _full_fake_repo(tmp_path)
    _write_state(root, "B-TEST", state="landed", claims={"M-1": "success", "M-2": "success"})
    inbox = timeflow_inbox.build_inbox(root)
    assert inbox["batches"]["open"] == []
    assert inbox["batches"]["landed"] == 1


# ------------------------------------------------------------------ 4. 缺批目录 ⇒ 如实报


def test_missing_batch_dir_is_reported(tmp_path: Path) -> None:
    """没有 `gates/diag/batch` ⇒ 桶 A 空 + 带说明（不许编一个「齐了」）。"""
    root = tmp_path / "repo"
    root.mkdir()
    _make_repo(root)
    _write_backlog(root)
    _write_gates_last(root)
    _write_verdict(root, "001")
    # ★ 故意不建 gates/diag/batch
    inbox = timeflow_inbox.build_inbox(root)
    assert inbox["batches"]["open"] == []
    assert "batch" in inbox["batches"]["note"]


# ------------------------------------------------------------------ 5. 批没有状态文件 ⇒ 点名不猜


def test_batch_without_state_is_named(tmp_path: Path) -> None:
    """栅栏在、状态文件缺 ⇒ 点名进 without_state（不猜它齐没齐）。"""
    root = _full_fake_repo(tmp_path)
    (root / "gates" / "diag" / "batch" / "B-TEST.json").unlink()
    inbox = timeflow_inbox.build_inbox(root)
    assert inbox["batches"]["open"] == []
    assert inbox["batches"]["without_state"] == ["B-TEST"]


# ------------------------------------------------------------------ 6. 缺队列 ⇒ 如实报


def test_missing_backlog_is_reported(tmp_path: Path) -> None:
    """没有 `docs/workbacklog.toml` ⇒ 桶 B/C 空 + 各自带说明。"""
    root = tmp_path / "repo"
    root.mkdir()
    _make_repo(root)
    _write_gates_last(root)
    _write_verdict(root, "001")
    _write_fence(root, "B-TEST")
    _write_state(root, "B-TEST", state="collecting")
    # ★ 故意不写 backlog
    inbox = timeflow_inbox.build_inbox(root)
    assert inbox["status_flip"]["cards"] == []
    assert "workbacklog" in inbox["status_flip"]["note"]
    assert inbox["review"]["cards"] == []
    assert "队列" in inbox["review"]["note"]


# ------------------------------------------------------------------ 7. 判决在、队列无条目 ⇒ 只报数


def test_orphan_verdict_is_counted_not_listed(tmp_path: Path) -> None:
    """判决在、队列里没有这张卡 ⇒ 只进 orphans 计数（不冒充「待复核」）。"""
    root = _full_fake_repo(tmp_path)
    _write_verdict(root, "999")
    inbox = timeflow_inbox.build_inbox(root)
    assert [r["card"] for r in inbox["review"]["cards"]] == ["001"]
    assert inbox["review"]["orphans"] == 1


# ------------------------------------------------------------------ 8. 幂等（函数级）


def test_json_idempotent(tmp_path: Path) -> None:
    """同输入连跑两次，JSON 逐字节相同（不许写时间戳 / 随机序）。"""
    root = _full_fake_repo(tmp_path)
    a = timeflow_inbox.build_inbox(root)
    b = timeflow_inbox.build_inbox(root)
    assert json.dumps(a, ensure_ascii=False, indent=2, sort_keys=True) == \
        json.dumps(b, ensure_ascii=False, indent=2, sort_keys=True)


# ------------------------------------------------------------------ 9. 幂等（CLI 级）


def test_json_idempotent_via_cli(tmp_path: Path) -> None:
    """CLI 连跑两次 `--json` 逐字节相同。"""
    root = _full_fake_repo(tmp_path)
    argv = [sys.executable, "-X", "utf8", str(TOOL), "--json", "--root", str(root)]
    out1 = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                          **pipeline_view.NO_WINDOW).stdout
    out2 = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                          **pipeline_view.NO_WINDOW).stdout
    assert out1 == out2
    assert json.loads(out1)["root"] == root.as_posix()


# ------------------------------------------------------------------ 10. --report 三桶都在


def test_report_has_three_buckets(tmp_path: Path) -> None:
    """`--report` 输出里三桶都在，且点明了来源。"""
    root = _full_fake_repo(tmp_path)
    done = subprocess.run(
        [sys.executable, "-X", "utf8", str(TOOL), "--report", "--root", str(root)],
        capture_output=True, text=True, encoding="utf-8", **pipeline_view.NO_WINDOW)
    assert done.returncode == 0
    for tag in ("[待收口的批]", "[待复核的卡]", "[待翻 status 的卡]"):
        assert tag in done.stdout, f"报告里缺 {tag}"
    assert "pipeline_view" in done.stdout


# ------------------------------------------------------------------ 11. 只读：不写任何文件


def test_read_only_leaves_worktree_untouched(tmp_path: Path) -> None:
    """跑一遍收件箱，工作区里每个文件的字节都不变（**只读**硬判据）。"""
    root = _full_fake_repo(tmp_path)
    before = _snapshot(root)
    timeflow_inbox.build_inbox(root)
    assert _snapshot(root) == before


# ------------------------------------------------------------------ 12. 不 import 业务代码


def test_does_not_import_timeflow() -> None:
    """工具**不许** import `src/timeflow/**`（跨层：pip 包不读仓库状态）。"""
    tree = ast.parse(TOOL.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert not [name for name in imported if name == "timeflow" or name.startswith("timeflow.")]
