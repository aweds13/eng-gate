r"""卡谱系树（`tools/wb_tree.py`，卡 A302 · T-AG416）的测试。

判据分两层：

1. **纯函数层**（`area_of` / `classify` / `match_task` / `render_text`）—— 用手造的节点，
   不碰真仓库：区映射、`--area` 过滤、深度截断、JSON 形状都在这层钉死；
2. **真仓库层**（`build(ROOT)`）—— 只钉**结构不变量**，不钉具体数字（历史会长）：
   父链与 `git log %p` 一致、task 查不到时 `card is null`（不推断）、`depends` 边带
   `explicit`、窗口截断计数 == 出窗父边数。

★ 钉子（规格点名）：**删 `orphans` 必红** —— `test_shape_requires_orphans` 先把真读数
   喂给它自己的形状判据（绿），再把 `orphans` 摘掉（必须红）。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import wb_tree  # noqa: E402 —— 需要先把 tools/ 挂上

# ---------------------------------------------------------------- 夹具


def _node(
    sha: str,
    *,
    parents: tuple[str, ...] = (),
    children: tuple[str, ...] = (),
    area: str = "面板",
    card: str | None = None,
    task: str | None = None,
    title: str = "样提交",
    date: str = "2026-10-01",
    files: int = 1,
    depends: tuple[dict, ...] = (),
) -> dict:
    return {
        "sha": sha,
        "card": card,
        "task": task,
        "title": title,
        "date": date,
        "area": area,
        "parents": list(parents),
        "children": list(children),
        "files": files,
        "depends": list(depends),
    }


def _tree(nodes: list[dict], orphans: list[dict] | None = None) -> dict:
    areas: list[dict] = []
    for name in wb_tree.AREA_NAMES:
        picked = [node for node in nodes if node["area"] == name]
        if picked:
            areas.append({"name": name, "count": len(picked), "roots": len(picked)})
    return {"nodes": nodes, "areas": areas, "orphans": [] if orphans is None else orphans}


def _shape_problems(tree: dict) -> list[str]:
    """JSON 形状判据（规格 §要交付 1 的那份键表）。**缺一个键就算问题**。"""
    problems: list[str] = []
    for key in ("nodes", "areas", "orphans"):
        if key not in tree:
            problems.append(f"缺顶层键 {key}")
    if problems:
        return problems
    for index, node in enumerate(tree["nodes"]):
        for key in (
            "sha",
            "card",
            "task",
            "title",
            "date",
            "area",
            "parents",
            "children",
            "files",
            "depends",
        ):
            if key not in node:
                problems.append(f"nodes[{index}] 缺键 {key}")
    for index, area in enumerate(tree["areas"]):
        for key in ("name", "count", "roots"):
            if key not in area:
                problems.append(f"areas[{index}] 缺键 {key}")
    for index, orphan in enumerate(tree["orphans"]):
        for key in ("sha", "task", "why"):
            if key not in orphan:
                problems.append(f"orphans[{index}] 缺键 {key}")
    return problems


# ---------------------------------------------------------------- 纯函数：区映射


@pytest.mark.parametrize(
    ("path", "area"),
    [
        ("tools/dsh_panel.py", "面板"),
        ("tools/pipeline_view.py", "面板"),
        ("tools/pool/lease.py", "号池"),
        ("tools/wb_plan.py", "号池"),
        ("skills/README.md", "技能"),
        ("docs/traceability.d/T-AG387.toml", "台账"),
        ("docs/workbacklog.toml", "台账"),
        ("复盘/卡/卡A302-卡谱系树.md", "复盘"),
        ("scripts/run_gates.py", "门禁"),
        ("gates/last.json", "门禁"),
        ("src/timeflow/core/tasks/manager.py", "服务"),
        ("tests/test_api.py", "服务"),
        ("examples/demo.toml", "其它"),
    ],
)
def test_area_of_maps_by_prefix(path: str, area: str) -> None:
    assert wb_tree.area_of(path) == area


def test_classify_prefers_code_over_bookkeeping_docs() -> None:
    """每张卡都顺带改 changelog / traceability / 复盘 —— 不能因此把面板那笔判成台账。"""
    paths = [
        "tools/dsh_panel.py",
        "tests/test_dsh_panel.py",
        "docs/changelog.md",
        "docs/traceability.toml",
        "docs/workbacklog.toml",
        "docs/changelog.d/T-AG412.md",
        "复盘/交接-重构进度.md",
    ]
    assert wb_tree.classify(paths) == "面板"


def test_classify_ignores_gate_run_artifacts() -> None:
    """`gates/last.json` 每笔门禁都重写 ⇒ 它不许把提交吸进「门禁」区。"""
    paths = ["src/timeflow/app/main.py", "gates/last.json", "gates/diag/wb-A1.report.md"]
    assert wb_tree.classify(paths) == "服务"


def test_classify_doc_only_prefers_retrospective() -> None:
    assert wb_tree.classify(["复盘/卡/卡A302.md", "docs/changelog.md"]) == "复盘"
    assert wb_tree.classify(["docs/traceability.toml"]) == "台账"
    assert wb_tree.classify([]) == "其它"


def test_match_task_takes_first_and_returns_none() -> None:
    assert wb_tree.match_task("feat(x): 面板（T-AG412）") == "T-AG412"
    assert wb_tree.match_task("feat(x): 卡 T-G99 与 T-G100") == "T-G99"
    assert wb_tree.match_task("chore: 没有任务号") is None


# ---------------------------------------------------------------- 纯函数：文本树


def test_area_filter_only_keeps_selected_area() -> None:
    tree = _tree(
        [
            _node("aaa1111", area="面板", children=("bbb2222",)),
            _node("bbb2222", area="服务", parents=("aaa1111",)),
            _node("ccc3333", area="面板"),
        ]
    )
    lines = wb_tree.render_text(tree, area="面板", limit=50)
    body = [line for line in lines if not line.startswith("谱系窗口")]
    joined = "\n".join(body)
    assert "aaa1111" in joined and "ccc3333" in joined
    assert "bbb2222" not in joined  # 服务那一笔被 --area 挡掉
    assert "只看「面板」（2 笔）" in lines[0]


def test_depth_over_six_becomes_ellipsis() -> None:
    """深度 > 6 打 `…`（规格点名）：9 连链只应展开到第 6 层。"""
    nodes = []
    for index in range(9):
        sha = f"c{index:06d}"
        nodes.append(
            _node(
                sha,
                parents=() if index == 0 else (f"c{index - 1:06d}",),
                children=() if index == 8 else (f"c{index + 1:06d}",),
            )
        )
    lines = wb_tree.render_text(_tree(nodes), limit=50)
    assert any(line.strip() == "…" for line in lines)
    assert "c000008" not in "\n".join(lines)  # 第 9 笔在 `…` 之后，不再展开


def test_limit_stops_and_reports_remainder() -> None:
    nodes = [_node(f"d{index:06d}") for index in range(5)]
    lines = wb_tree.render_text(_tree(nodes), limit=2)
    joined = "\n".join(lines)
    assert "还有 3 笔未显示" in joined
    assert sum(1 for line in lines if line.startswith("d")) == 2


def test_unregistered_node_is_labelled_not_guessed() -> None:
    tree = _tree([_node("eee1111", card=None, task="T-G381")])
    joined = "\n".join(wb_tree.render_text(tree, limit=10))
    assert "未登记(T-G381)" in joined
    assert "T-G381" in joined


# ---------------------------------------------------------------- 形状钉子


def test_shape_problems_accepts_fake_tree() -> None:
    assert _shape_problems(_tree([_node("fff1111")])) == []


def test_shape_requires_orphans(live_tree: dict) -> None:
    """★ 钉子：真读数先过形状判据；把 `orphans` 摘掉必须红（规格：删 orphans 必红）。

    ★ 用**真读数**而不是假夹具：假夹具摘键只证明判据自己有牙，证明不了
      `wb_tree.build()` 还在输出 `orphans` —— 实现里删掉它这条照样绿（假钉子）。
    """
    tree = dict(live_tree)
    assert _shape_problems(tree) == []
    tree.pop("orphans")
    assert any("orphans" in item for item in _shape_problems(tree))


# ---------------------------------------------------------------- 真仓库层


@pytest.fixture(scope="module")
def live_tree() -> dict:
    return wb_tree.build(ROOT)


def test_json_shape_on_real_repo(live_tree: dict) -> None:
    assert _shape_problems(live_tree) == []
    assert live_tree["nodes"], "真仓库不可能一笔提交都没有"
    for node in live_tree["nodes"]:
        assert node["card"] is None or isinstance(node["card"], str)
        assert node["task"] is None or wb_tree.TASK_RE.fullmatch(node["task"])
        assert node["area"] in wb_tree.AREA_NAMES
        assert isinstance(node["files"], int) and node["files"] >= 0


def test_parent_chain_matches_git(live_tree: dict) -> None:
    """父链 = `git log %p`，反向 `children` 与之一一对应（不拿时间相邻冒充先后）。"""
    by_sha = {node["sha"]: node for node in live_tree["nodes"]}
    for node in live_tree["nodes"]:
        for parent in node["parents"]:
            if parent in by_sha:
                assert node["sha"] in by_sha[parent]["children"]
    for node in live_tree["nodes"]:
        for child in node["children"]:
            assert node["sha"] in by_sha[child]["parents"]


def test_task_maps_to_card_pool(live_tree: dict) -> None:
    by_task, _ = wb_tree.load_cards(ROOT)
    mapped = [node for node in live_tree["nodes"] if node["card"]]
    assert mapped, "窗口内至少应有能对上卡池的提交"
    for node in mapped:
        assert by_task.get(node["task"]) == node["card"], node


def test_unregistered_task_stays_null(live_tree: dict) -> None:
    """查不到就 `null` + 保留 task 号 —— **不推断**成某张卡。"""
    by_task, _ = wb_tree.load_cards(ROOT)
    unknown = [
        node
        for node in live_tree["nodes"]
        if node["task"] and node["task"] not in by_task
    ]
    assert unknown, "真历史上老账没登记成卡的提交（应如实留 task 号）"
    for node in unknown:
        assert node["card"] is None


def test_depends_edges_are_explicit(live_tree: dict) -> None:
    by_task, by_id = wb_tree.load_cards(ROOT)
    edges = [edge for node in live_tree["nodes"] for edge in node["depends"]]
    assert edges, "卡池里有 depends，窗口内应至少落一条显式边"
    for node in live_tree["nodes"]:
        for edge in node["depends"]:
            assert edge["kind"] == "explicit"
            if node["card"]:
                assert edge["card"] in by_id[node["card"]].depends


def test_window_truncation_is_counted() -> None:
    """`--since` 切窗后，父提交出窗 ⇒ orphans 条数 == 出窗父边数，且 why 点名父提交。"""
    since = "2026-10-15"
    tree = wb_tree.build(ROOT, since)
    in_window = {node["sha"] for node in tree["nodes"]}
    missing = [
        (node["sha"], parent)
        for node in tree["nodes"]
        for parent in node["parents"]
        if parent not in in_window
    ]
    assert missing, f"窗口 {since} 之后应至少有一处被截断"
    assert len(tree["orphans"]) == len(missing)
    assert len(tree["nodes"]) < len(wb_tree.git_log(ROOT))  # 窗口确实变短了
    for orphan in tree["orphans"]:
        assert "不在窗口内" in orphan["why"]


def test_cli_json_end_to_end() -> None:
    """验收命令口径：`--json` 能独立跑出可解析的 JSON（编码 / 断管道都不许炸）。"""
    done = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            str(ROOT / "tools" / "wb_tree.py"),
            "--json",
            "--limit",
            "5",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
        timeout=180,
    )
    assert done.returncode == 0, done.stderr
    tree = json.loads(done.stdout)
    assert set(tree) == {"nodes", "areas", "orphans"}
