"""核 `scripts/run_gates.py --affected` 会不会咬（T-G239 · 卡 140）。

## 为什么有这张测试

来路：`复盘/架构审议-外包与门禁.md` §二 错配① + §五「A 分档」。现在门禁**只有"全量"**、
没有"哪个文件影响哪道门"的依赖图，而**判据方向是反的**（不是"多跑安全"，是"**漏跑危险**"）。
本卡立一张「**门 × 输入**」表（`DOOR_INPUTS`）并加 `--affected <路径…>` 只跑受影响的几道。

判据（**宁多勿漏**，与 `--help` 原文一致）：
  ① 路径匹配不上任何门 ⇒ **跑全量**；② 某道门在表里**缺输入** ⇒ **那道门照跑**；③ 拿不准就多跑。

## 怎么验（把 `run_gates.py` 当模块 import，**不跑任何门**）

`plan_affected` / `build_jobs` / `build_parser` / `path_matches_glob` 都是**纯函数**：
喂合成表与合成路径，直接判"选了哪几道、跳了哪几道、为什么跳"。**不跑门禁**（重活归主控收口）。
每条判据都配**反例**（不然就是注释）：命中 vs 不命中、真表 vs 合成表、默认 vs 加开关。

## 边界（如实写，未覆盖）

- **端到端**（真跑 `main()` 写 `gates/last.json` 的 `affected` 块）本文件**没跑** —— 那要真跑门禁。
  这里钉的是"记账对象" `AffectedPlan.to_payload()`（`main()` 把它塞进 `payload["affected"]`），
  以及"默认不给 `--affected` 时形状不变"由 `build_jobs` + `plan_affected([])` 两条间接覆盖。
- `--changed-from` 的 git 现算（`changed_paths_from`）没测（要有树上的真实改动才判得了）。
- `--affected` 只裁**门名单**，门的判据一个没动 —— 这一点由"没改任何门的命令/超时/复用"保证。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import run_gates as rg  # noqa: E402 —— 需要先用 sys.path 把 scripts/ 挂上

# 全量门清单 —— **现读**门表真源 `run_gates.build_jobs(False, False)`，**不写死**数字/名单。
# ★ 卡 208 §2 的口径：写死的门数/名单是**会漂的第二真源**（同 `tools/wb_verify.py`
#   `expected_gate_names()` 的现读法）。卡 160 加 `invariants`（17→18）、卡 208 加 `proxy`
#   （18→19）都是「改一行门表」的事 —— 门数变了这条测试**不该红**，所以这里改成现算。
FULL = tuple(n for n, _ in rg.build_jobs(False, False))
# 真表里**没有**输入映射的门（= 任何改动都可能影响它 ⇒ 永远跑）= `DOOR_INPUTS` 的**补集**（现算）。
NO_INPUT = tuple(n for n in FULL if n not in rg.DOOR_INPUTS)


# ------------------------------------------------------------------ ① 只跑受影响的门


def test_only_the_affected_door_is_selected() -> None:
    """★ 判据①：给一个"只该影响某一道门"的路径 ⇒ 那一趟跑的门集合正好是它。"""
    table = {"render": ("src/**",), "ui_flow": ("tools/ui_flow_check.mjs",)}
    doors = ("render", "ui_flow")

    plan = rg.plan_affected(["src/web/app.css"], doors, door_inputs=table)
    assert plan.ran == ("render",), plan.ran
    assert [n for n, _ in plan.skipped] == ["ui_flow"]
    assert plan.full_fallback is False

    # 反例：换成只影响 ui_flow 的路径 → 反过来（证明它按输入裁、不是恒选某一道）
    flip = rg.plan_affected(["tools/ui_flow_check.mjs"], doors, door_inputs=table)
    assert flip.ran == ("ui_flow",), flip.ran
    assert [n for n, _ in flip.skipped] == ["render"]


# ------------------------------------------------------------------ ② 匹配不上 ⇒ 全量


def test_unmatched_path_falls_back_to_full() -> None:
    """★ 判据②：路径一条都命不中 ⇒ **全量**；空列表 ⇒ 也全量。有命中 ⇒ 不许退全量。"""
    table = {"render": ("src/**",), "ui_flow": ("tools/ui_flow_check.mjs",)}
    doors = ("render", "ui_flow", "audit")  # audit 无输入：不会造成"命中"

    unmatched = rg.plan_affected(["docs/notes.md"], doors, door_inputs=table)
    assert unmatched.full_fallback is True
    assert unmatched.ran == doors  # 门数 = 全量
    assert "全量" in unmatched.note

    empty = rg.plan_affected([], doors, door_inputs=table)
    assert empty.full_fallback is True
    assert empty.ran == doors

    # 反例：有命中就不该退全量（否则"只跑受影响的门"这句是假的）
    hit = rg.plan_affected(["src/a.py"], doors, door_inputs=table)
    assert hit.full_fallback is False
    assert hit.ran == ("render", "audit")
    assert "ui_flow" not in hit.ran

    # 真表也成立：走 .md 路径（谁都不吃）⇒ 全量 18 道
    assert rg.plan_affected(["复盘/随便.md"], FULL).full_fallback is True
    assert rg.plan_affected(["复盘/随便.md"], FULL).ran == FULL


# ------------------------------------------------------------------ ③ 缺输入的门永远跑


def test_door_without_input_mapping_always_runs() -> None:
    """★ 判据③：表里**缺输入**的门 ⇒ 永远跑（拿合成表与真表各钉一次）。"""
    table = {"render": ("src/**",), "ui_flow": ("tools/ui_flow_check.mjs",)}
    plan = rg.plan_affected(["src/a.py"], ("render", "ui_flow", "audit"), door_inputs=table)
    assert "audit" in plan.ran          # 表里没条目 → 照跑
    assert "ui_flow" not in plan.ran    # 有条目且没命中 → 跳

    # 真表：无输入映射的门在**每一趟**的 ran 里
    real = rg.plan_affected(["src/web/app.css"], FULL)
    for door in NO_INPUT:
        assert door in real.ran, f"{door} 没有输入映射却没跑"


# ------------------------------------------------------------------ ④ 跳过的门被记下来


def test_skipped_doors_are_recorded_with_reason() -> None:
    """★ 判据④：跳过**不静默** —— `--affected` 那一趟的记账里能看出跳了哪些、为什么跳。"""
    table = {"render": ("src/**",), "ui_flow": ("tools/ui_flow_check.mjs",)}
    doors = ("render", "ui_flow")
    payload = rg.plan_affected(["src/a.py"], doors, door_inputs=table).to_payload()

    assert payload["ran"] == ["render"]
    assert payload["inputs"] == ["src/a.py"]
    assert payload["full_fallback"] is False
    skipped = {s["name"]: s["why"] for s in payload["skipped"]}
    assert set(skipped) == {"ui_flow"}
    assert "tools/ui_flow_check.mjs" in skipped["ui_flow"], skipped  # 原因里带该门的输入

    # 反例：退全量那一趟没有"跳过"（门数=全量，别记一堆假的跳过）
    full = rg.plan_affected(["docs/x.md"], doors, door_inputs=table).to_payload()
    assert full["skipped"] == []
    assert full["ran"] == list(doors)


# ------------------------------------------------------------------ ⑤ 默认行为逐字不变


def test_default_job_list_and_table_shape_are_pinned() -> None:
    """★ 判据⑤：不给 `--affected` 时门集合 = 全量；真表形状（有输入 ∪ 无输入）自洽。

    ★ 卡 208 §2：门清单**现读门表**（不写死名字/门数）⇒ 这里把"逐字一致"换成**结构判据**
    （无重名 / 默认含真机层 / 有输入的门都在真表里），免得它变成会漂的第二真源。
    """
    # 门清单（默认 = 全量）：现读自 `build_jobs`，钉的是它**结构自洽**（不是写死的名单）
    default = tuple(n for n, _ in rg.build_jobs(False, False))
    assert len(default) == len(set(default)), "门清单出现重名门"
    assert {"render", "ui_flow", "pytest"} <= set(default), "默认全量必须含真机浏览器层与 pytest"
    # --quick / --fast 的既有口径没被碰
    quick = tuple(n for n, _ in rg.build_jobs(True, False))
    assert "render" not in quick and "pytest" in quick
    assert set(n for n, _ in rg.build_jobs(False, True)) == set(rg.FAST)

    # 真表形状：有输入的门 ∪ 无输入的门 == 全量；两边不相交；没有空条目
    assert set(rg.DOOR_INPUTS) | set(NO_INPUT) == set(FULL)
    assert set(rg.DOOR_INPUTS) & set(NO_INPUT) == set()
    assert all(rg.DOOR_INPUTS[d] for d in rg.DOOR_INPUTS)

    # 复用那 5 道真机门仍是同一批（`REUSE_INPUTS` 从 `DOOR_INPUTS` 取）；pytest 永不复用
    assert rg.REUSABLE == ("render", "ui_flow", "lf1_live", "web_live", "ui_dom_probe")
    assert tuple(rg.REUSE_INPUTS) == rg.REUSABLE
    assert "pytest" not in rg.REUSE_INPUTS

    # ★ 默认（没有路径）这一支就是"跑全量" —— 与不加开关时的门集合相同
    assert tuple(rg.plan_affected([], FULL).ran) == FULL


# ------------------------------------------------------------------ ⑥ 收口链仍走全量（防呆）


def test_landing_chain_may_use_affected_only_with_mandatory_full_runs() -> None:
    """★★ 防呆（**卡 184 起更新**；原「收口链永不许传 `--affected`」由卡 161 立）。

    161 那条的原意是：别让「自查提速」从后门变成「提交前漏门」。**卡 184 把这条前提取代了** ——
    收口链**可以**用 `--affected` 提速，但**三条强制全量**必须在：
    碰判据体（`scripts/**` / `tools/**` / `gates/**`）/ 空计划 / 每日首趟。
    ⇒ 本测试改为钉**新契约**，而不是继续禁一个已经合法的东西。
    """
    landing = (ROOT / "tools" / "pool" / "landing.py").read_text(encoding="utf-8")
    assert "--affected" in landing, "卡 184 的增量通道应当在收口链里"
    assert "JUDGE_BODY_GLOBS" in landing, "★ 强制全量的判据体（碰判据/门/收口链自己 ⇒ 全量）必须在"
    assert "全量门禁绿" in landing, "★ 全量分支的字面「全量门禁绿」一字未动（卡 133 的钉子钉着它）"


# ------------------------------------------------------------------ glob 语义（判据的地基）


def test_glob_matching_semantics() -> None:
    """`path_matches_glob` 的地基：`**` 跨目录、`*` 不跨、祖先目录算命中、反斜杠归一。"""
    assert rg.path_matches_glob("src/a/b.py", "src/**")
    assert rg.path_matches_glob("src/foo.py", "src/**")
    assert rg.path_matches_glob("src", "src/**")                      # 祖先目录（宁多勿漏）
    assert not rg.path_matches_glob("scripts/run_gates.py", "src/**")  # 别把别的目录误判进来
    assert rg.path_matches_glob("gates/render/x.txt", "gates/render/*.txt")
    assert not rg.path_matches_glob("gates/render/sub/x.txt", "gates/render/*.txt")  # `*` 不跨
    assert rg.path_matches_glob("tools/serve.py", "tools/serve.py")
    assert rg.path_matches_glob("src\\web\\app.css", "src/web/**")     # Windows 反斜杠归一


# ------------------------------------------------------------------ --help 原文（判据方向）


def test_help_states_the_ningduo_direction() -> None:
    """`--help` 必须把判据方向与分工写清（不能只留一个光秃秃的开关）。"""
    ap = rg.build_parser()
    text = ap.format_help()
    for kw in ("宁多勿漏", "跑全量", "提交闸"):
        assert kw in text, f"--help 里缺「{kw}」"
    assert "--affected" in text and "--changed-from" in text

    ns = ap.parse_args([])                  # 默认：两个开关都不开
    assert ns.affected is None and ns.changed_from is None and ns.seal is False
