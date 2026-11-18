r"""工作台状态注入（卡 224 · T-G338）—— 一处把工作台状态拼成给工人看的一段文字。

为什么有它：工人一进树就得知道四件事 —— **我在哪张卡 / 谁在飞 / 我的域有没有被别人占 /
该看哪个产物**。从前每个工人各自读队列 + 租约 + 判决（`wb_dispatch` 的开场白就是现拼的），
口径必漂。本工具把这段收成**一处**：派活器（`wb_dispatch`）与「面」都调它
（本仓「一份读数」的教义 —— 一处改、处处对）。

★ **数据只来自既有真源** `tools/pipeline_view.py`（卡 207）—— 本工具**不**自己再读
  `docs/workbacklog.toml`（那是第二份真源，两份一漂就出事）。
★ **幂等**：同样输入连跑两次**逐字节相同**（不写时间戳、不靠文件遍历顺序 —— 一律排序）。
★ **缺什么说什么**：来源缺 / 坏 ⇒ 那一段**省略**并写清原因，**不许编**（不拿空对象冒充）。

用法：
    python -X utf8 tools/workbench_bridge.py --card 224 --tree .wt/wbridge --batch B-20261016
    python -X utf8 tools/workbench_bridge.py --card 224 --root D:/path/to/main/tree
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import pipeline_view  # noqa: E402 —— 唯一真源（卡 207）：本工具只调它、不另读 backlog

TITLE = "【工作台状态 · 一处真源（卡 224；来源 tools/pipeline_view.py）】"
LEASE_SRC = "gates/diag/pool-registry.json"
BATCH_SRC = "gates/diag/batch/*.toml"
VERDICT_REL = "gates/diag"
OMIT = "（省略）"


# ================================================================ 读数（只调 pipeline_view）


def collect_reading(root: Path | None = None) -> dict:
    """只取本工具要用的**五块** —— 故意**不**调 `read_worktrees`。

    为什么：`read_worktrees` 会对**每一棵树**跑一次 `git status`（本仓 ~190 棵树）⇒ 派活时太贵；
    它给的路径信息对「我在哪 / 谁在飞 / 我的域 / 该看哪个产物」四件事都用不上。

    ★ 数据全部来自 `pipeline_view`（卡 207）的**公开只读函数**；本工具不另读 backlog。
    """
    base = Path(root) if root is not None else ROOT
    reading: dict = {}
    reading.update(pipeline_view.read_cards(base))
    reading.update(pipeline_view.read_gates(base))
    reading.update(pipeline_view.read_verdicts(base))
    reading.update(pipeline_view.read_leases(base))
    reading.update(pipeline_view.read_fences(base))
    return reading


def _find_card(reading: dict, card: str) -> tuple[dict | None, str]:
    """在队列里找这张卡 —— 返回 `(行, 说明)`；查不到 / 读不到 ⇒ 行是 `None` 且说明非空。"""
    cards = reading.get("cards")
    if cards is None:
        return None, f"读不到队列：{reading.get('cards_note', '（没有说明）')}"
    if not card:
        return None, "没给卡号（--card）"
    hit = next((c for c in cards if str(c.get("id", "")) == str(card)), None)
    if hit is None:
        return None, f"队列 {len(cards)} 张里查不到卡 {card}"
    return hit, ""


def _lease_rows(reading: dict) -> list[dict] | None:
    """活租约行，**排序后**返回（幂等：不靠文件遍历顺序）；文件坏 / 结构不对 ⇒ `None`。"""
    rows = reading.get("leases")
    if rows is None:
        return None
    return sorted(rows, key=lambda r: (str(r.get("card", "")), str(r.get("tree", "")),
                                       str(r.get("owner", ""))))


# ================================================================ 六段（每段可省略并说明）


def _dead_split(rows: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """把租约行按 dead 列分三组：活的 / 死的 / 判不出的。

    ★ 读数只有一份（tools/pipeline_view.py 的 dead 列，卡 E115）—— 这里**不重算** TTL、不读日志。
    ★ dead 是 None（判不出）同时算进「活」：认不出来就**保守当活**
      （与 tools/pool/guards.py 的派活守卫同口径）。
    """
    live = [lc for lc in rows if not lc.get("dead")]
    dead = [lc for lc in rows if lc.get("dead")]
    unknown = [lc for lc in rows if lc.get("dead") is None]
    return live, dead, unknown


def _lease_mark(lc: dict) -> str:
    """行尾的死活标记（字面量与 tools/pipeline_view.py 的租约报告一致）。"""
    if lc.get("dead") is None:
        return "  （判不出）"
    return "  ★ 已死" if lc.get("dead") else ""


def _section_card(reading: dict, card: str) -> list[str]:
    """① 我在哪张卡。"""
    head = "我在哪张卡："
    row, why = _find_card(reading, card)
    if row is None:
        return [f"{head}{OMIT}{why} —— 不许编"]
    files = "、".join(row.get("files") or []) or "（没写域）"
    return [
        f"{head}{row['id']}（{row['task']}）{row['title']}",
        f"  · 树 tree={row['tree'] or '（主树）'}  status={row['status']}  risk={row['risk']}",
        f"  · 规格 spec={row['spec'] or '（没写）'}",
        f"  · 我的域（files）：{files}",
    ]


def _section_lease(reading: dict, card: str, tree: str) -> list[str]:
    """② 谁在飞（租约；**行内** dead 标死活 —— 死的不抹掉，活的不冒充）。"""
    head = "谁在飞："
    rows = _lease_rows(reading)
    if rows is None:
        return [f"{head}{OMIT}{reading.get('leases_note', '读不到租约')} —— 不许编"]
    if not rows:
        return [f"{head}没有活租约（来源 {LEASE_SRC}；缺 / 空同义）⇒ 现在没有别人占树"]
    live, dead, unknown = _dead_split(rows)
    tail = f"，其中 {len(dead)} 条已死" if dead else ""
    if unknown:
        tail += f"，{len(unknown)} 条判不出"
    out = [f"{head}{len(live)} 条活租约{tail}（来源 {LEASE_SRC}）："]
    # ★ 先念活、后念死；两组各自保序（_lease_rows 已按 (card, tree, owner) 排好）。
    for lc in (*live, *dead):
        mine = " ★本卡" if str(lc.get("card", "")) == str(card) and card else ""
        out.append(f"  · 卡 {lc['card']} @ 树 {lc['tree'] or '（主树）'}"
                   f"  owner={lc['owner']}  at={lc['at']}  ttl={lc['ttl_seconds']}s"
                   f"{mine}{_lease_mark(lc)}")
    return out


def _section_conflict(reading: dict, card: str, tree: str) -> list[str]:
    """③ 我的域有没有被别人占（按**域文件相交**判；域查不到就退回按**树**判）。"""
    head = "我的域有没有被别人占："
    rows = _lease_rows(reading)
    if rows is None:
        return [f"{head}{OMIT}{reading.get('leases_note', '读不到租约')} —— 不许编"]
    row, why = _find_card(reading, card)
    mine = list(row.get("files") or []) if row is not None else []
    live, _dead, _unknown = _dead_split(rows)
    # ★ 死租约不是占用者；判不出的保守当活（并在行尾标「（判不出）」）。
    others = [lc for lc in live if str(lc.get("card", "")) != str(card)]
    hits: list[str] = []
    if mine:
        for lc in others:
            shared = sorted(set(mine) & set(lc.get("files") or []))
            if shared:
                where = lc["tree"] or "（主树）"
                hits.append(f"卡 {lc['card']} @ {where} 占着 {'、'.join(shared)}"
                            f"{_lease_mark(lc)}")
    elif tree:
        for lc in others:
            if str(lc.get("tree", "")) == str(tree):
                hits.append(f"卡 {lc['card']} 占着我这棵树 {tree}{_lease_mark(lc)}")
        if not hits:
            mine_note = "本卡自己占着" if any(
                str(lc.get("card", "")) == str(card) and str(lc.get("tree", "")) == str(tree)
                for lc in live) else "没人占"
            return [f"{head}没有 ★ 按**树**判（域查不到：{why}）；我的树 {tree}：{mine_note}"]
    else:
        return [f"{head}{OMIT}域与树都查不到（{why}）—— 不许编"]
    if hits:
        return [f"{head}★ 有 ——", *(f"  · {h}" for h in hits)]
    scope = f"域 {len(mine)} 个文件" if mine else f"树 {tree}"
    return [f"{head}没有（{scope}；活租约里没人踩）"]


def _section_artifacts(reading: dict, card: str) -> list[str]:
    """④ 该看哪个产物（判决 / 摘要）。"""
    head = "该看哪个产物："
    verdicts = reading.get("verdicts")
    note = reading.get("verdicts_note", "")
    where = f"{VERDICT_REL}/wb-{card}.verdict.txt（判决）/ wb-{card}.report.md（摘要）"
    if verdicts is None or note:
        return [f"{head}{OMIT}{note or '读不到判决'}（该落的位置：{where}）—— 不许编"]
    row = next((v for v in verdicts if str(v.get("card", "")) == str(card)), None)
    if row is None:
        return [f"{head}还没有判决 / 摘要（队列里没有卡 {card} 的产物）；该落的位置：{where}"]
    tags = []
    if row.get("has_verdict"):
        tags.append("有判决")
    if row.get("has_report"):
        tags.append("有摘要")
    first = row.get("verdict_first_line") or ""
    suffix = f"  首行：{first}" if first else ""
    return [f"{head}{'、'.join(tags) or '无'}{suffix}；位置：{where}"]


def _section_gates(reading: dict) -> list[str]:
    """附：最近一次门禁（工人该知道的现状）。"""
    head = "最近门禁："
    gates = reading.get("gates")
    if gates is None:
        return [f"{head}{OMIT}{reading.get('gates_note', '读不到 gates/last.json')} —— 不许编"]
    return [f"{head}（来源 gates/last.json）rev={gates.get('rev')} ok={gates.get('ok')}"
            f"  共 {len(gates.get('items') or [])} 道"]


def _section_batch(reading: dict, batch: str) -> list[str]:
    """附：批号（给了才出）—— 该批次的收口条件与成员数。"""
    gate = "批次："
    if not batch:
        return []
    fences = reading.get("fences")
    if fences is None:
        return [f"{gate}{OMIT}读不到栅栏：{reading.get('fences_note', '')} —— 不许编"]
    row = next((f for f in fences if str(f.get("id", "")) == str(batch)), None)
    if row is None:
        return [f"{gate}{OMIT}栅栏里查不到批次 {batch}（来源 {BATCH_SRC}）—— 不许编"]
    return [f"{gate}{batch}  on_complete={row.get('on_complete')}  成员 {row.get('members')} 个"
            f"（来源 {BATCH_SRC}）"]


# ================================================================ 纯函数（读数 ⇒ 一段文字）


def render(reading: dict, *, card: str = "", tree: str = "", batch: str = "") -> str:
    """**纯函数**：一份读数（`pipeline_view` 的产物）⇒ 给工人看的一段文字。

    ★ 同样输入两次 ⇒ 逐字节相同：所有聚合都排序、不掺时间戳 / 随机数。
    ★ 缺哪一块就**省略那一段并说明**，绝不用空对象冒充（承诺在每一段里）。
    """
    lines = [TITLE]
    if card or tree:
        lines.append(f"（卡号 {card or '（没给）'} · 树 {tree or '（没给）'}）")
    lines += _section_card(reading, card)
    lines += _section_lease(reading, card, tree)
    lines += _section_conflict(reading, card, tree)
    lines += _section_artifacts(reading, card)
    lines += _section_gates(reading)
    lines += _section_batch(reading, batch)
    return "\n".join(lines)


def bridge_text(*, card: str = "", tree: str = "", batch: str = "",
                reading: dict | None = None, root: Path | str | None = None) -> str:
    """入参（卡号 / 树 / 批号，可选）⇒ 给工人看的一段文字。

    `reading` 给了就直接用它（测试注入用）；不给就 `collect_reading(root)` 现读
    （数据只来自 `pipeline_view`）。
    """
    if reading is None:
        reading = collect_reading(Path(root) if root is not None else None)
    return render(reading, card=card, tree=tree, batch=batch)


# ================================================================ CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="把工作台状态拼成给工人看的一段文字（纯函数；数据只来自 pipeline_view）")
    parser.add_argument("--card", default="", help="卡号（如 224）")
    parser.add_argument("--tree", default="", help="我这棵树（登记用的标签，如 .wt/wbridge）")
    parser.add_argument("--batch", default="", help="批号（任务栅栏 id，如 B-20261016）")
    parser.add_argument("--root", default="", help="读数根（默认本文件推出来的仓库根）")
    args = parser.parse_args(argv)
    print(bridge_text(card=args.card, tree=args.tree, batch=args.batch,
                      root=args.root or None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
