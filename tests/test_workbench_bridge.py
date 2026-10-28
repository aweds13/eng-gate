r"""`tools/workbench_bridge.py`（卡 224 · T-G338）的测试 —— 工作台状态一处真源。

为什么值当测：派活器的开场白要用它、面也要用它 ⇒ 它错了就是**所有工人一起看错**
（「我在哪 / 谁在飞 / 我的域有没有被别人占 / 该看哪个产物」）。所以钉四条：
① 四件事都读得出来；② 缺数据源 ⇒ 那一段**省略并说明**（不许编）；③ **幂等**（逐字节相同）；
④ ★ **反例**：同一输入喂两次结果不同 ⇒ 红。

★ 只造**纯数据**（`tmp_path` 下的最小假仓），不连网、不碰真仓。
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import pipeline_view  # noqa: E402,I001 —— 需要先把 tools/ 挂上
import workbench_bridge  # noqa: E402,I001


# ------------------------------------------------------------------ 最小假仓


def _git(*a: str, cwd: Path) -> None:
    r = subprocess.run(["git", *a], cwd=str(cwd), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    assert r.returncode == 0, r.stderr


def _make_repo(tmp_path: Path) -> Path:
    _git("init", "-q", cwd=tmp_path)
    _git("config", "user.email", "t@t", cwd=tmp_path)
    _git("config", "user.name", "t", cwd=tmp_path)
    (tmp_path / ".gitignore").write_text("*.tmp\n", encoding="utf-8")
    _git("add", ".gitignore", cwd=tmp_path)
    _git("commit", "-q", "-m", "init", cwd=tmp_path)
    return tmp_path


def _write_backlog(root: Path, card_id: str = "001") -> None:
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "workbacklog.toml").write_text(
        '[base]\nreviewed = "abc1234"\n\n'
        '[[cards]]\n'
        f'id = "{card_id}"\n'
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


def _write_verdict(root: Path, card: str = "001") -> None:
    diag = root / "gates" / "diag"
    diag.mkdir(parents=True, exist_ok=True)
    (diag / f"wb-{card}.verdict.txt").write_text(f"card={card} 通过\n", encoding="utf-8")
    (diag / f"wb-{card}.report.md").write_text("# 摘要\n", encoding="utf-8")


def _lease(card: str, tree: str, files: list[str], owner: str = "host:1") -> dict:
    return {"card": card, "tree": tree, "files": files, "owner": owner,
            "at": "2026-10-13T12:00:00", "ttl_seconds": 21600.0}


def _write_registry(root: Path, rows: list[dict]) -> None:
    diag = root / "gates" / "diag"
    diag.mkdir(parents=True, exist_ok=True)
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
    """队列 + 最近门禁 + 一条判决 + 一条本卡租约 + 一个栅栏 + git 仓。"""
    root = tmp_path / "repo"
    root.mkdir()
    _make_repo(root)
    _write_backlog(root)
    _write_gates_last(root)
    _write_verdict(root)
    _write_registry(root, [_lease("001", ".wt/a", ["src/a.py"])])
    _write_fence(root)
    return root


# ------------------------------------------------------------------ 1. 四件事都读得出来


def test_bridge_reads_the_four_facts(tmp_path: Path) -> None:
    """我在哪张卡 / 谁在飞 / 我的域 / 该看哪个产物 —— 四件都从 pipeline_view 读出来。"""
    root = _full_fake_repo(tmp_path)
    text = workbench_bridge.bridge_text(card="001", tree=".wt/a", batch="B-TEST", root=root)

    assert "我在哪张卡：001（T-G1）样卡一" in text
    assert "树 tree=.wt/a" in text and "status=pending" in text
    assert "我的域（files）：src/a.py" in text
    assert "谁在飞：1 条活租约" in text and "卡 001 @ 树 .wt/a" in text
    assert "★本卡" in text                       # 自己那条标出来
    assert "我的域有没有被别人占：没有" in text
    assert "有判决、有摘要" in text
    assert "gates/diag/wb-001.verdict.txt" in text
    assert "最近门禁：" in text and "rev=deadbee ok=True" in text
    assert "批次：B-TEST" in text and "on_complete=['draft']" in text


# ------------------------------------------------------------------ 2. 域冲突


def test_bridge_flags_domain_conflict_with_another_card(tmp_path: Path) -> None:
    """别人的活租约踩到我的域 ⇒ 如实报「★ 有」并点名卡与文件。"""
    root = _full_fake_repo(tmp_path)
    _write_registry(root, [
        _lease("001", ".wt/a", ["src/a.py"], owner="host:1"),
        _lease("099", ".wt/b", ["src/a.py", "src/z.py"], owner="host:2"),
    ])
    text = workbench_bridge.bridge_text(card="001", tree=".wt/a", root=root)
    assert "我的域有没有被别人占：★ 有" in text
    assert "卡 099 @ .wt/b 占着 src/a.py" in text


def test_conflict_falls_back_to_tree_when_domain_unknown(tmp_path: Path) -> None:
    """域查不到（队列里没有这张卡）⇒ 退回按**树**判，别的卡占着我这棵树就报出来。"""
    root = _full_fake_repo(tmp_path)
    _write_backlog(root, card_id="777")          # ★ 队列里没有 001 ⇒ 域查不到
    _write_registry(root, [_lease("099", ".wt/a", ["src/z.py"])])
    text = workbench_bridge.bridge_text(card="001", tree=".wt/a", root=root)
    assert "我的域有没有被别人占：★ 有" in text
    assert "卡 099 占着我这棵树 .wt/a" in text


def test_conflict_by_tree_says_clear_when_nobody_holds_it(tmp_path: Path) -> None:
    """退回按树判、且没人占我树 ⇒ 也要说清「是**按树**判的」（别让人以为查过域了）。"""
    root = _full_fake_repo(tmp_path)
    _write_backlog(root, card_id="777")
    _write_registry(root, [_lease("099", ".wt/b", ["src/z.py"])])
    text = workbench_bridge.bridge_text(card="001", tree=".wt/a", root=root)
    assert "我的域有没有被别人占：没有 ★ 按**树**判" in text
    assert "我的树 .wt/a：没人占" in text


# ------------------------------------------------------------------ 3. 缺数据源 ⇒ 省略并说明


def test_missing_backlog_omits_card_and_says_why(tmp_path: Path) -> None:
    """没有队列 ⇒ 「我在哪张卡」那一段省略**并写清原因**，不许编一张卡出来。"""
    root = tmp_path / "repo"
    root.mkdir()
    _make_repo(root)
    # ★ 故意不写 backlog
    text = workbench_bridge.bridge_text(card="001", tree=".wt/a", root=root)
    assert "我在哪张卡：（省略）" in text
    assert "读不到队列" in text
    assert "样卡一" not in text                  # 不许编


def test_missing_verdicts_source_omits_and_says_why(tmp_path: Path) -> None:
    """没有 gates/diag 目录 ⇒ 「该看哪个产物」省略，说明原因并给出该落的位置。"""
    root = tmp_path / "repo"
    root.mkdir()
    _make_repo(root)
    _write_backlog(root)
    # ★ 故意不建 gates/diag
    text = workbench_bridge.bridge_text(card="001", root=root)
    assert "该看哪个产物：（省略）" in text
    assert "没有 gates/diag 目录" in text
    assert "gates/diag/wb-001.verdict.txt" in text


def test_broken_registry_omits_lease_section_and_says_why(tmp_path: Path) -> None:
    """租约文件坏了 ⇒ 「谁在飞」省略**并说明**（不许拿空当没有）。"""
    root = _full_fake_repo(tmp_path)
    (root / "gates" / "diag" / "pool-registry.json").write_text("{not json", encoding="utf-8")
    text = workbench_bridge.bridge_text(card="001", tree=".wt/a", root=root)
    assert "谁在飞：（省略）" in text
    assert "pool-registry.json 坏了" in text


def test_unknown_batch_is_omitted_with_reason(tmp_path: Path) -> None:
    """批次查不到 ⇒ 省略并点名（来源 gates/diag/batch/*.toml）。"""
    root = _full_fake_repo(tmp_path)
    text = workbench_bridge.bridge_text(card="001", batch="B-NOPE", root=root)
    assert "批次：（省略）栅栏里查不到批次 B-NOPE" in text
    assert "gates/diag/batch/*.toml" in text


# ------------------------------------------------------------------ 4. 幂等


def test_idempotent_collect_and_render(tmp_path: Path) -> None:
    """连跑两次：读数逐字节相同、渲染逐字节相同（不许写时间戳 / 随机序）。"""
    root = _full_fake_repo(tmp_path)
    a = workbench_bridge.bridge_text(card="001", tree=".wt/a", batch="B-TEST", root=root)
    b = workbench_bridge.bridge_text(card="001", tree=".wt/a", batch="B-TEST", root=root)
    assert a == b
    ra = json.dumps(workbench_bridge.collect_reading(root), ensure_ascii=False, sort_keys=True)
    rb = json.dumps(workbench_bridge.collect_reading(root), ensure_ascii=False, sort_keys=True)
    assert ra == rb


def test_idempotent_via_cli(tmp_path: Path) -> None:
    """CLI 连跑两次逐字节相同。"""
    root = _full_fake_repo(tmp_path)
    argv = [sys.executable, "-X", "utf8", str(ROOT / "tools" / "workbench_bridge.py"),
            "--card", "001", "--tree", ".wt/a", "--batch", "B-TEST", "--root", str(root)]
    out1 = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          **pipeline_view.NO_WINDOW).stdout
    out2 = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          **pipeline_view.NO_WINDOW).stdout
    assert out1 == out2
    assert "我在哪张卡" in out1


def test_reordering_semantically_same_reading_does_not_change_bytes(tmp_path: Path) -> None:
    r"""★ **反例钉子**：同一输入喂两次结果**不同** ⇒ 红。

    「同一输入」= 语义相同的一份读数，只把列表**换了遍历顺序**（租约行序反转、域文件序反转）。
    实现若把文件遍历顺序当真（不排序）⇒ 这两次逐字节不同 ⇒ 本条红 —— 正是「不幂等」的判据。
    """
    root = _full_fake_repo(tmp_path)
    _write_registry(root, [
        _lease("001", ".wt/a", ["src/a.py", "src/aa.py"], owner="host:1"),
        _lease("099", ".wt/b", ["src/z.py"], owner="host:2"),
    ])
    reading = workbench_bridge.collect_reading(root)
    a = workbench_bridge.render(reading, card="001", tree=".wt/a", batch="B-TEST")

    shuffled = copy.deepcopy(reading)
    shuffled["leases"] = list(reversed(shuffled["leases"]))
    shuffled["cards"][0]["files"] = list(reversed(shuffled["cards"][0]["files"]))
    b = workbench_bridge.render(shuffled, card="001", tree=".wt/a", batch="B-TEST")

    assert a == b, "同一输入（只换了顺序）两次不同 ⇒ 不幂等"
