r"""`tools/auto_land.py` —— 把收口器做成**确定的程序**（卡 233 · `T-G350` · 零 LLM）。

为什么有它：用户 2026-10-14 令「自动收口」⇒ 主控当场的做法是把「什么时候该落哪一批」写成
**一段自然语言提示词**挂进 DSH 定时任务（每 5 分钟投一次，**由一个 agent 回合读懂再执行**）。
★ 那能用，但不是本仓该有的形态 ✗ —— 本仓的教义是**「用确定的程序验收 AI 的输出」**：
「该不该落」判据能写成代码，就不该交给模型读自然语言。本程序把收口器做成纯程序。

## 四态（各自明确，不许含糊）

| 态 | 判据 | 行为 |
|---|---|---|
| 无批 | 没有 `awaiting-commit` 的批 | **退 0、一行不打印**（每 5 分钟一次，别刷屏）|
| 内存紧 | `wb_dispatch.memory_gate_problem()` 咬 | **什么都不落**、非零退、点名"内存紧" |
| 门禁红 | 链子里门禁退出码 ≠ 0 | **什么都不落**、非零退、**原话带出来**；后续批不再试 |
| 该落 | 批齐了且没有"停下来问"的东西 | 走**既定收口链**落掉；打印批号 + 提交号 |

外加一条**停下来问**（非零退出 + 点名，绝不自作主张）：批里若混着
**用户决策项**（deferred 台账号：`SR-F1.9` / `SR-F2.8` / `SR-F8.4b` 出现在批的注册 why /
成员申请 / 文书里），或**要动用户资产**（申请的文件落在 `data/` 下 —— `docs/归置地图.md`
的硬编码禁区），或**树的解析烂了**（卡不在队列 / 没写 tree / 树不在磁盘 / 要动多棵树）。

## 落的动作（别另写一套）

`--batch <批号>` 调 `tools/wb_land.py`（既定八步链：快照 → 迁树 → 文书 → 门禁 → 封存 →
提交 → audit/合流 → 复核落盘）。`landed` 标记与镜像 push **链子自己会做**
（`pool/landing.py` 的 `_advance_batch_gate` + ⑧ 镜像段）—— 与手工口径一致，本程序不重复做。
参数的确定性来源：`--title` = 批注册的 `why`；`--evidence`/`--allow` = 各成员成功申请里报的
`files` 并集；`--tree` = 成员卡在队列里的 `tree`（恰一棵才落，多棵 ⇒ 停下来问）；
`--task` = 单成员批用队列里预登记的台账号（`wb_task.py` 卡 204 翻 status 靠它），多成员批
按台账现算 `T-G<最大号+1>`（与手工攒批口径一致）。

## 挂法（「程序跑程序」——由主控执行；★ 本程序不碰 `~/.dsh`）

· DSH（现有那条每 5 分钟的 schedule）：把提示词缩成**一句命令**，不经模型判断：
      python -X utf8 tools/auto_land.py
· Windows 计划任务（连 DSH 都不需要）—— 示意（主控按本机路径与 Python 入口校一遍再挂）：
      schtasks /Create /TN "jelly-auto-land" /SC MINUTE /MO 5 /TR ^
        "cmd /c cd /d <仓库根> && python -X utf8 tools\auto_land.py"
  （`/SC MINUTE /MO 5` = 每 5 分钟；并发安全：本程序自己带自旋锁，上一趟没跑完 ⇒ 本趟
  打一行就退，不叠加落。）

## 边界（如实写）

- ★ **不许绕内存闸**：本程序不设、不覆盖 `TF_GATE_MIN_FREE_GB`，内存判据直接委托
  `wb_dispatch` 的唯一实现（`pool/guards.py` 头注释点名的委托关系，不写第二份）。
- **必须在主树跑**（落 = 动主树）；在卡树里跑 ⇒ 扫描照扫、`--dry-run` 照说、真落前拒（退 2）。
- 门禁红只有**跑了链子才可知**（`gates/last.json` 是上一趟的旧判决，本仓咬过
  「旧判决冒充当前状态」，不许拿它预筛）—— 所以"落函数被调用 0 次"在门禁红态指的是
  **落成动作**（`_record_landed`）0 次、后续批 0 次；链子那 1 次是发现红的唯一途径。
- 退出码：0 = 落成 / 无批 / dry-run；2 = 环境（不在主树 / 队列读不了）；3 = 内存紧；
  4 = 停下来问；5 = 上一趟还在跑；**链子失败原码透传**（1 = 门禁红，其余见 `wb_land.py`）。

用法：
    python -X utf8 tools/auto_land.py             # 有批就落（调度器挂的就是这一句）
    python -X utf8 tools/auto_land.py --dry-run   # 只说"会落哪几批"，一行都不改
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parent.parent
_TOOLS = Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:  # 直跑脚本时 tools/ 已在 sys.path；被 import 时补上
    sys.path.insert(0, str(_TOOLS))

import wb_dispatch  # noqa: E402 —— 内存闸**唯一实现**（pool/guards.py 头注释点名的委托）
from pool import task as pool_task  # noqa: E402 —— 批目录 / 收件箱 / 自旋锁唯一实现
from wb_state import NO_WINDOW  # noqa: E402 —— 起子进程不弹窗（卡 148）

#: 用户决策项（deferred 台账号）：出现在批的任何文字里 ⇒ 停下来问（卡 233 点名这三个）。
DEFERRED_SRS = ("SR-F1.9", "SR-F2.8", "SR-F8.4b")

#: 用户资产目录（`docs/归置地图.md`：`data/` 是硬编码禁区）—— 申请的文件碰它 ⇒ 停下来问。
USER_ASSET_PREFIX = "data/"

#: 链子子进程的硬超时（秒）：链内门禁自己有 1800s 硬超时，这里再兜一层（超了当红、透传 124）。
CHAIN_TIMEOUT_S = 2400.0

_TASK_ID = re.compile(r"T-G(\d+)")


class StopAndAskError(Exception):
    """批里混着不能自动决定的东西 —— `reasons` 逐条点名（停下来问，绝不自作主张）。"""

    def __init__(self, reasons: list[str]) -> None:
        self.reasons = list(reasons)
        super().__init__("；".join(self.reasons))


def _norm_rel(path: object) -> str:
    """申请里报的路径 → 纯仓库相对 posix 路径（比较用，不碰文件系统）。"""
    return str(path or "").strip().replace("\\", "/").lstrip("./").rstrip("/")


# ================================================================ 读数（只读）


def scan_awaiting(bdir: Path) -> list[dict]:
    """扫 `gates/diag/batch/*.json`，取 `state == "awaiting-commit"` 的批（按批号排序）。

    读不了 / 顶层不是对象的文件：打一行点名后跳过（`pool.json` 之类的住户不是批，静默略过）。
    """
    out: list[dict] = []
    if not bdir.is_dir():
        return out
    for p in sorted(bdir.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"★ 跳过（状态文件读不了，不猜）：{p.name}（{type(exc).__name__}）")
            continue
        if not isinstance(data, dict) or data.get("state") != "awaiting-commit":
            continue
        out.append(data)
    return out


def load_backlog() -> dict[str, dict]:
    """队列 `docs/workbacklog.toml` → {纯数字卡号: 行}（树 / 台账号的确定性来源）。"""
    root = pool_task.main_tree_root()
    raw = (root / "docs" / "workbacklog.toml").read_text(encoding="utf-8")
    data = tomllib.loads(raw)
    out: dict[str, dict] = {}
    for row in data.get("cards") or []:
        key = re.sub(r"\D", "", str(row.get("id") or ""))
        if key:
            out[key] = row
    return out


def read_claim(bid: str, mid: str) -> dict | None:
    """成员的成功申请收件（`<批>.d/<卡>.json`）；不在 / 坏了 ⇒ None（不猜）。"""
    p = pool_task.inbox_dir(bid) / f"{mid}.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _draft_texts(state: dict) -> list[tuple[str, str]]:
    """批文书两份（骨架 + 人写的 why）的原文 —— 用户决策项的扫描面之一。"""
    out: list[tuple[str, str]] = []
    draft = state.get("draft") or {}
    for key, label in (("path", "文书骨架"), ("why", "人写的 why")):
        t = str(draft.get(key) or "").strip()
        if not t:
            continue
        try:
            p = Path(t)
            if p.is_file():
                out.append((label, p.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue
    return out


def next_task_id() -> str:
    """台账现算下一个台账号 `T-G<最大号+1>`（多成员批用；与手工攒批口径一致）。

    号只从**台账**来（`docs/traceability.toml` 的 id + `docs/traceability.d/T-G*.toml`）；
    读不到一条 ⇒ 拒（不许猜号、不许用批号顶替）。
    """
    root = pool_task.main_tree_root()
    nums: list[int] = []
    ledger = root / "docs" / "traceability.toml"
    data = tomllib.loads(ledger.read_text(encoding="utf-8"))
    for e in data.get("entries") or []:
        m = _TASK_ID.fullmatch(str(e.get("id") or ""))
        if m:
            nums.append(int(m.group(1)))
    frag = root / "docs" / "traceability.d"
    if frag.is_dir():
        for p in frag.glob("T-G*.toml"):
            m = _TASK_ID.fullmatch(p.stem)
            if m:
                nums.append(int(m.group(1)))
    if not nums:
        raise StopAndAskError([f"台账里一条 T-G 都读不到（{ledger}）—— 下一个台账号不许猜"])
    return f"T-G{max(nums) + 1}"


# ================================================================ 判据（纯函数，好测）


def plan_batch(entry: dict, backlog: dict) -> dict:
    """一个 awaiting 批 → 落的**完整计划**；不能自动决定的 ⇒ `stop` 逐条点名。

    返回 `{"bid", "stop": [人话…], "tree", "task", "title", "files": [...]}`；
    `stop` 非空时其余键**可能缺**（前置读数烂了就不往下推，不编）。
    """
    bid = str(entry.get("id") or "?")
    stop: list[str] = []
    declared = [str(m) for m in entry.get("declared") or []]
    read_only = {str(m) for m in (entry.get("read_only") or [])}
    members = [m for m in declared if m not in read_only]

    # ---- 成员申请（证据 / 白名单的唯一来源；缺收件 = 齐了却说不出改了什么 ⇒ 停）
    claims: dict[str, dict] = {}
    for mid in members:
        got = read_claim(bid, mid)
        if got is None:
            stop.append(f"卡 {mid} 没有成功申请的收件（{bid}.d/{mid}.json 不在或坏了）")
        else:
            claims[mid] = got

    # ---- 用户决策项（deferred SR）：批的注册 why / 成员申请 / 批文书里出现 ⇒ 停下来问
    texts: list[tuple[str, str]] = [("批注册的 why", str(entry.get("why") or ""))]
    for mid, c in claims.items():
        texts.append((f"卡 {mid} 的申请", " ".join(
            str(c.get(k) or "") for k in ("why", "evidence", "log"))))
    texts += _draft_texts(entry)
    hits: dict[str, str] = {}
    for label, t in texts:
        for sr in DEFERRED_SRS:
            if sr in t and sr not in hits:
                hits[sr] = label
    if hits:
        stop.append("用户决策项（deferred，只该人来定）：" + "、".join(
            f"{sr}（出现在{label}）" for sr, label in hits.items()))

    # ---- 用户资产：申请的文件落在 data/ 下 ⇒ 停下来问
    files: list[str] = []
    for mid in members:
        for f in claims.get(mid, {}).get("files") or []:
            n = _norm_rel(f)
            if n and n not in files:
                files.append(n)
    assets = [f for f in files if f == "data" or f.startswith(USER_ASSET_PREFIX)]
    if assets:
        stop.append(f"要动用户资产（{USER_ASSET_PREFIX} 是硬编码禁区）：{'、'.join(assets)}")

    # ---- 树：恰一棵且在磁盘上才落
    rows: list[tuple[str, dict]] = []
    for mid in members:
        row = backlog.get(re.sub(r"\D", "", mid))
        if row is None:
            stop.append(f"卡 {mid} 不在队列 docs/workbacklog.toml 里（解析不了它落在哪棵树）")
        else:
            rows.append((mid, row))
    no_tree = [mid for mid, row in rows if not str(row.get("tree") or "").strip()]
    if no_tree:
        stop.append(f"队列里没写 tree：{'、'.join(no_tree)}（主树直接做的批要人来收）")
    trees: list[str] = []
    for _mid, row in rows:
        t = str(row.get("tree") or "").strip()
        if t and t not in trees:
            trees.append(t)
    if len(trees) > 1:
        stop.append(f"批要动 {len(trees)} 棵树（{'、'.join(trees)}）—— 多树集成要人合"
                    "（本版不自动建集成树），先人跑 `git worktree add --detach "
                    ".wt/autoland-int HEAD` 再手工收，或拆批")
    elif len(trees) == 1 and not _tree_exists(trees[0]):
        stop.append(f"树 {trees[0]} 不在磁盘上（被清了？）—— 不猜，人来定")
    if members and not files:
        stop.append("成员申请里一个文件都没报 —— 没证据的东西不叫落（--evidence 会是空的）")

    # ---- 台账号：单成员批用队列预登记的（卡 204 翻 status 靠它）；多成员批按台账现算
    task = ""
    if not stop:
        try:
            if len(rows) == 1:
                task = str(rows[0][1].get("task") or "")
                if not _TASK_ID.fullmatch(task):
                    stop.append(f"卡 {rows[0][0]} 队列里的 task 不是台账号（{task!r}）"
                                "—— 台账号由登记定，不许现造")
            else:
                task = next_task_id()
        except StopAndAskError as exc:
            stop.extend(exc.reasons)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            stop.append(f"台账读不了（算不出下一个台账号）：{type(exc).__name__}: {exc}")

    plan: dict = {"bid": bid, "stop": stop}
    if stop:
        return plan
    plan.update({
        "tree": trees[0],
        "task": task,
        "title": str(entry.get("why") or "").strip() or f"批 {bid} 自动收口（auto_land）",
        "files": files,
    })
    return plan


def _tree_exists(rel: str) -> bool:
    """树目录在不在磁盘上（独立小缝：测试换桩，生产查主树下的真实目录）。"""
    return (pool_task.main_tree_root() / rel).is_dir()


# ================================================================ 动作


def run_chain(argv: list[str]) -> tuple[int, str]:
    """跑收口链子（`wb_land.py`，NO_WINDOW），回 `(退出码, 原样输出)`。门禁原话就在里面。"""
    try:
        done = subprocess.run(argv, cwd=str(ROOT), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=CHAIN_TIMEOUT_S,
                              **NO_WINDOW)
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        note = f"★ auto_land：链子 {CHAIN_TIMEOUT_S:.0f}s 没跑完 ⇒ 掐掉（124，同门禁超时）"
        return 124, f"{(out or '').rstrip()}\n{note}"
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def _record_landed(bid: str, main_root: Path) -> str:
    """落成动作：读主树 HEAD 当提交号并打印「批号 + 提交号」。

    ★ `landed` 标记与镜像 push 是链子自己做的（`--batch` 模式），这里只**报**，
      不重复做（别另写一套）。拿不到提交号就如实说"不知道"，不编。
    """
    done = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(main_root),
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", **NO_WINDOW)
    sha = (done.stdout or "").strip()
    if done.returncode != 0 or not sha:
        print(f"★ 落了 {bid} → 提交号（不知道：git rev-parse 退 {done.returncode}，"
              f"{(done.stderr or '').strip()[:120]}）")
        return ""
    print(f"★ 落了 {bid} → {sha[:12]}（landed 与镜像由收口链自己标/推 —— 与手工口径一致）")
    return sha


def land_batch(plan: dict, port_base: int, main_root: Path) -> int:
    """把一个批交给既定收口链（`wb_land.py --batch`）；红了**原样带出**门禁原话。"""
    bid = plan["bid"]
    argv = [sys.executable, "-X", "utf8", str(ROOT / "tools" / "wb_land.py"),
            "--batch", bid, "--tree", plan["tree"], "--task", plan["task"],
            "--title", plan["title"], "--group", "ENGINEERING",
            "--evidence", *plan["files"], "--allow", *plan["files"],
            "--port-base", str(port_base)]
    print(f"== auto_land：落 {bid}（tree={plan['tree']}，task={plan['task']}，"
          f"evidence {len(plan['files'])} 个文件）==")
    rc, out = run_chain(argv)
    if out.strip():
        print(out.rstrip())  # ★ 链子的原话（含门禁读数）一字不改带出来
    if rc != 0:
        print(f"★★ 批 {bid} 没落成（链子退 {rc}）—— 后面的批不再试，等下个 5 分钟再看")
        return rc
    _record_landed(bid, main_root)
    return 0


# ================================================================ 主入口


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(description="零 LLM 的确定性收口器（卡 233）")
    ap.add_argument("--dry-run", action="store_true",
                    help="只说「会落哪几批 / 会停在哪」，一行都不改")
    ap.add_argument("--port-base", type=int, default=9034,
                    help="门禁锁的端口段（透传给 wb_land.py --port-base；默认 9034）")
    a = ap.parse_args(argv)

    awaiting = scan_awaiting(pool_task.batch_dir())
    if not awaiting:
        return 0  # ★ 无批：退 0、一行不打印（每 5 分钟一次，别刷屏）

    try:
        main_root = pool_task.main_tree_root()
        backlog = load_backlog()
    except (OSError, tomllib.TOMLDecodeError, pool_task.BatchError) as exc:
        print(f"★ 环境读不了（队列 / 主树）：{type(exc).__name__}: {exc}")
        return 2

    plans = [plan_batch(entry, backlog) for entry in awaiting]

    if a.dry_run:
        for p in plans:
            if p["stop"]:
                print(f"会停：{p['bid']} —— {'；'.join(p['stop'])}")
            else:
                print(f"会落：{p['bid']}（tree={p['tree']}，task={p['task']}，"
                      f"evidence {len(p['files'])} 个文件）")
        return 0

    if ROOT.resolve() != main_root.resolve():
        print(f"★ auto_land 必须在主树跑（本文件在 {ROOT}，主树是 {main_root}）"
              "—— 落 = 动主树，卡树里不许落")
        return 2

    # ---- 内存紧（四态之二）：委托 wb_dispatch 的唯一实现；紧 ⇒ 什么都不落
    problem = wb_dispatch.memory_gate_problem()
    if problem:
        ids = "、".join(p["bid"] for p in plans)
        print(f"★ 内存紧 ⇒ 什么都不做（{len(plans)} 个批等着：{ids}）")
        print(f"  {problem}")
        return 3

    try:  # ★ 自旋锁：上一趟没跑完 ⇒ 本趟打一行就退，不叠加落
        with pool_task.spin_lock(pool_task.batch_dir() / "auto-land", timeout=0.5):
            for p in plans:
                if p["stop"]:
                    print(f"★★ 停下来问：批 {p['bid']} 混着不能自动决定的东西 ⇒ 什么都不落：")
                    for r in p["stop"]:
                        print(f"  · {r}")
                    return 4
                rc = land_batch(p, a.port_base, main_root)
                if rc != 0:
                    return rc
            return 0
    except pool_task.BatchError as exc:
        print(f"★ 上一趟 auto_land 还在跑 ⇒ 本趟不落（{exc}）")
        return 5


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
