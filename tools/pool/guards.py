r"""自家守卫 —— **纯函数**：吃数据 → 回 `list[str]` 问题。

**防什么**：写面（派活 / 取消）动手前要能回答「这棵树 / 这个冲突域 / 这趟门禁 / **这个项目**，
现在能不能碰」。这里守卫只吃**已经读好的数据**（租约表 / 锁的原文 / 只读项目索引），
回一串人话问题：**不写文件、不 print、不起进程** —— 所以既好测，也能被写面（卡 110）直接复用，
不会变成第二份真源。

**哪几条是我判的**：
- `tree_guard`   —— 一棵树同时只能有一个活租约（主树尤其）。
- `domain_guard` —— 冲突域与任何活租约**相交**就拒，并**点名相交的文件**（相交判据直接用
  `pool.plan.files_intersect`，不另写一份 —— 本仓最忌两份真源）。
- `lock_guard`   —— 门禁锁的原文里，若有锁的 `card` = 本卡 **或** `cwd` 指向本树 ⇒ 拒
  （"这趟门禁还在跑，别动手"）。解析在 `pool.locks.parse_entries`。
- `project_guard` —— **项目守卫（卡 120 · T-G232）**：没登记过的项目 / 树不落在该项目
  `tree_prefixes` 里 / 反查不到 ⇒ 拒。数据来自**只读**的 `pool.projects` 索引。
- `lane_guard`   —— **每账号并发闸（卡 A339）**：同一个号同时在跑的活租约到上限 ⇒ 拒
  （`limit` / `queue` 由调用方从 `pool.lanes` 读好传进来 —— 本模块**不碰 TOML**，不然就破了
  下面那条"不写文件"的规矩）。

**哪三条是别人判的（本模块明确"委托"，重写就是第三份真源）**：
- **内存闸** —— `tools/wb_dispatch.py` 的前置检查（`TF_GATE_MIN_FREE_GB`）是唯一实现；
  本模块**没有**任何内存闸函数（测试 `test_pool_guards.py` 钉住这一点）。
- **日志不许覆盖** —— `wb_dispatch` 自己会挑 `wb-<卡>.r2.jsonl` 这种新名字，且写面**不许**给
  `--force`；本模块只加一条最朴素的 `log_guard(path)`：目标已存在 ⇒ 拒。
- **模型白名单** —— `wb_dispatch.MODEL_WHITELIST` 的硬闸门 + `pool.models` 的批准集。

★ 关于时间：`now` 是"现在"（epoch 秒）。守卫只按**租约**判活（`now - at > ttl_seconds` 算死）；
  日志层面的"断了 / 已判决"由 `registry`（有 IO 的那一层）先清一遍再把活的租约递进来 ——
  所以守卫**不 import registry**（不然成环），也不做任何 IO。
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import TYPE_CHECKING

# ★ 卡 188（T-G288）交的**符号级**冲突判据 —— 本模块是它的**接线处**
#   （2026-10-03，用户令「把符号级那半接上」）。
#   分层：`files_intersect` 当**粗筛**（一个字没改），相交的**再细判到符号**。
#   ★ 不写 `::` 的声明恒判 `WHOLE_FILE` ⇒ **行为与今天逐字相同**（向后兼容是硬要求）。
from domain_symbols import overlap as _symbol_overlap

from pool import locks as pool_locks
from pool import projects as pool_projects
from pool.plan import Card, files_intersect

if TYPE_CHECKING:
    from collections.abc import Iterable


def _norm(path: object) -> str:
    """路径归一：反斜杠 → 正斜杠、去首尾空白与尾部斜杠（比较用，不碰文件系统）。"""
    return str(path or "").strip().replace("\\", "/").rstrip("/")


def _started_at(value: object) -> float | None:
    """把租约的 `at`（ISO8601）转成 epoch 秒；认不出 → `None`（**保守当活**）。"""
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def _is_live(reservation: dict, now: float | None) -> bool:
    """这条租约还算活吗 —— 只按 TTL（日志层面的死租约由 registry 先清）。

    ★ 认不出来的输入一律**保守当活**：宁可多拦一次（人会再 release），也别默默放行一个占着树
      的写者。`now is None` 或 `ttl_seconds` 缺失/非数 → 不当死。
    """
    if now is None:
        return True
    ttl = reservation.get("ttl_seconds")
    started = _started_at(reservation.get("at"))
    if not isinstance(ttl, (int, float)) or started is None:
        return True
    return (now - started) <= float(ttl)


def _as_card(card_id: object, files: object) -> Card:
    """把"一串冲突域"包成 `plan.Card`，好把相交判据交给现成的 `files_intersect`。"""
    rows = [str(item) for item in files] if isinstance(files, (list, tuple)) else []
    return Card(id=str(card_id), task="", title="", tree="", spec="", files=tuple(rows))


def _tree_label(tree: object) -> str:
    return _norm(tree) or "（主树）"


# ================================================================ 守卫① 树


def tree_guard(tree: object, reservations: Iterable[dict], now: float | None = None) -> list[str]:
    """一棵树同时只能有一个活租约（主树尤其）—— 空列表 = 没被咬。

    失败方向：fail closed —— 读不到租约会话（`reservations` 给 None）今天抛 `TypeError`，
    **不回 `[]`**；F70 的类型化出口（`pool.failclosed.NotServing`）留给调用方包一层
    （本卡 A336 只加这一行 docstring，`if` 一个字没改）。
    """
    want = _norm(tree)
    problems: list[str] = []
    for res in reservations:
        if not _is_live(res, now):
            continue
        if _norm(res.get("tree")) == want:
            problems.append(
                f"树被占：{_tree_label(tree)} 上已有活租约（卡 {res.get('card')}，"
                f"owner={res.get('owner') or '?'}）—— 一棵树同时只能一个写者")
    return problems


# ================================================================ 守卫② 冲突域


def _file_part(decl: str) -> str:
    """声明里的**文件部分**（`X.py::sym` → `X.py`；没有 `::` 就是它自己）。

    ★ 只做字符串切分，不做任何判定 —— 判定一律交给 `domain_symbols`（不另写一份真源）。
    """
    return _norm(decl).split("::", 1)[0]


def _pair_verdict(a: str, b: str, root: object = None) -> tuple[bool, str]:
    """**同一个文件**上的两份声明能不能并行 —— 交给 `domain_symbols.overlap()`。

    ★ 四种判定里：`DISJOINT` / `SAME_FILE_DIFFERENT_SYMBOL` ⇒ 放行；
      `SAME_FILE_SAME_SYMBOL` / `WHOLE_FILE` ⇒ 拒（= 今天的行为）。
    ★ 边界（如实）：只有同路径的 `.py` 才问符号级；非 Python（`.md` / `.toml` / `src/web/…`）
      与目录 / 通配声明一律退回**文件级**；符号级**判不出来**（文件不在 / 符号名不存在 / 解析失败）
      ⇒ **保守拒**并把原因带出来 —— 不静默当成"能并行"。
    """
    pa, pb = _norm(a), _norm(b)
    if _file_part(pa) != _file_part(pb) or not _file_part(pa).endswith(".py"):
        return False, "按文件级判（不是同一个 .py 文件）"
    try:
        got = _symbol_overlap(pa, pb, root=root)
    except Exception as exc:  # noqa: BLE001 —— 判不出来 ⇒ 保守拒，且如实说
        return False, f"符号级判定失败（{type(exc).__name__}: {exc}）⇒ 按文件级判"
    return got.parallel, got.message()


def _domain_pairs(mine: list[str], theirs: list[str],
                  root: object = None) -> tuple[list[str], list[str]]:
    """两串声明里的**同文件声明对** —— 返回 `(拒的理由, 放行但要提醒的, 有没有真符号声明)`。

    ★★ 为什么不能只看 `files_intersect`：它是**字符串精确相交** ⇒ `X.py::sym` 与 `X.py`
      **永不相交** —— 于是「一边声明整个文件、一边声明某个符号」这种**最危险的组合粗筛看不见**
      （今天会被放过去）。这里按**文件部分**成对，正好把这个洞补上（宁可多拦一次）。
    """
    bad: list[str] = []
    notes: list[str] = []
    # ★ 只有当**某一方真的声明了符号**（含 `::`）时，才让新文案生效；
    #   两边都是裸路径（= `WHOLE_FILE`）⇒ 文案与接线前**逐字相同** ——
    #   两条既有测试钉着旧话（`test_pool_registry` / `test_wb_dispatch`），这是向后兼容的硬要求。
    symbol_level = False
    for a in mine:
        for b in theirs:
            if _file_part(a) != _file_part(b):
                continue
            ok, why = _pair_verdict(a, b, root)
            if not ok and ("::" in a or "::" in b):
                symbol_level = True
            (notes if ok else bad).append(f"{a} × {b} —— {why}")
    return bad, notes, symbol_level


def domain_guard(files: Iterable[str], reservations: Iterable[dict],
                 now: float | None = None, *, root: object = None) -> list[str]:
    """冲突域与任何活租约**相交**就拒，并**点名相交的文件**（空列表 = 没被咬）。

    ★ 判据分两层（2026-10-03 接线，零件是卡 188 的）：
      ① **粗筛**：`pool.plan.files_intersect`（字符串精确相交）—— 一个字没改；
      ② **细判**：**同一个文件**的每一对再问 `domain_symbols.overlap()` ——
         「同文件**不同符号**」**放行**（`domain_notes()` 会给 rebase 提醒），
         「同文件**同符号**」与「整个文件（不写 `::`）」照旧**拒**。
      ★ 细判按**文件部分**成对，所以连「`X.py` × `X.py::sym`」也拦得住（粗筛看不见它）。
    ★ 空域 = 不与任何东西相交 = 绕过这条守卫 —— 所以调用方（CLI）**不许把查不到的卡猜成空域**。
    失败方向：fail closed —— **空域不是「过了」而是「没东西可判」**（上面那句已有注释）；
    符号级判不出来时走 `_pair_verdict` 的**保守拒**（拒的理由带在返回值里），今天仍回 `list[str]`。
    F70 的类型化出口是 `pool.failclosed.NotServing`，留给调用方（本卡只加这几行 docstring，
    `if` 一个字没改）。
    """
    mine = [str(item) for item in files] if isinstance(files, (list, tuple, set)) else []
    request = _as_card("?", mine)
    problems: list[str] = []
    for res in reservations:
        if not _is_live(res, now):
            continue
        theirs = [str(item) for item in (res.get("files") or [])]
        hit = files_intersect(request, _as_card(res.get("card"), theirs))
        bad, _notes, symbol_level = _domain_pairs(mine, theirs, root)
        if not hit and not bad:
            continue
        label = (f"与活租约卡 {res.get('card')}（树 {_tree_label(res.get('tree'))}）")
        if bad:
            # ★ 兼容钉住的旧契约：**非 Python / 文件级**的相交，文案与接线前**逐字相同**
            #   （`tests/test_wb_dispatch.py::test_guard_refuses_a_domain_intersection`
            #   钉着「冲突域相交」+ 文件名）。只有真做了符号级细判，才用新文案。
            if not symbol_level:
                problems.append(
                    f"冲突域相交：{label}相交文件 {sorted(hit)} —— 同一文件不许两个写者")
            else:
                problems.append(
                    f"冲突域**同文件同符号**：{label} —— " + "；".join(bad[:3])
                    + " ⇒ 同一符号不许两个写者（★ 同文件**不同**符号是放行的：声明写成 "
                      "`<路径>::<符号>` 即可并行）")
        elif hit:
            problems.append(
                f"冲突域相交：{label}相交文件 {sorted(hit)} —— 同一文件不许两个写者")
    return problems


def domain_notes(files: Iterable[str], reservations: Iterable[dict],
                 now: float | None = None, *, root: object = None) -> list[str]:
    """**放行但要提醒**的那些（同文件不同符号 ⇒ 撞了就 rebase）—— 只提醒，**不拒**。

    ★ 与 `domain_guard()` 同源（都走 `_domain_pairs`）；调用方拿它打一行提醒即可。
    """
    mine = [str(item) for item in files] if isinstance(files, (list, tuple, set)) else []
    out: list[str] = []
    for res in reservations:
        if not _is_live(res, now):
            continue
        _bad, notes, _sym = _domain_pairs(mine, [str(x) for x in (res.get("files") or [])], root)
        out.extend(notes)
    return out



# ================================================================ 守卫③ 门禁锁


def _cwd_is_tree(cwd: object, tree: object, root: object) -> bool:
    """锁的 `cwd` 是不是指向要占的那棵树。"""
    got = _norm(cwd)
    if not got:
        return False
    if root is not None:
        want = _norm(str(Path(str(root)) / str(tree))) if _norm(tree) else _norm(root)
        return bool(want) and got == want
    # 没有 root 时退化成后缀匹配（保守：只在树名非空时才可能命中）
    name = _norm(tree)
    return bool(name) and (got == name or got.endswith("/" + name))


def lock_guard(card: object, tree: object, lock_body: str,
               *, root: object = None) -> list[str]:
    """门禁锁在跑吗 —— 锁的 `card` = 本卡，**或** `cwd` 指向本树 ⇒ 拒。

    `root` 给定时，`tree` 按"相对 root"解析后与 `cwd` **精确**比较（推荐）；
    不给 `root` 则退化成后缀匹配。`lock_body` 就是 `gate_lock.py status` 的原文
    （`pool.locks.status_argv()` 跑出来的那段）。
    """
    problems: list[str] = []
    for entry in pool_locks.parse_entries(lock_body or ""):
        base, held, pid = entry["base"], entry["card"], entry["pid"]
        if held == str(card):
            problems.append(
                f"这趟门禁还在跑：锁的 card={held}（段 base={base}，pid={pid}）就是本卡 —— 别动手")
            continue
        if _cwd_is_tree(entry.get("cwd"), tree, root):
            problems.append(
                f"这趟门禁还在跑：锁的 cwd={entry.get('cwd')} 指向本树（段 base={base}，"
                f"card={held}）—— 别动手")
    return problems


# ================================================================ 守卫④（最朴素的一条）日志


def log_guard(path: object) -> list[str]:
    """日志不许覆盖：目标已存在 ⇒ 拒（写面**不许**给 `--force`）。

    ★ 真正的"每轮换个新名字"（`wb-<卡>.r2.jsonl`）是 `wb_dispatch` 自己判的（委托），
      这里只把最朴素的那条（"不许盖"）摆出来。
    """
    if not str(path or "").strip():
        return []
    if Path(str(path)).exists():
        return [f"日志不许覆盖：{path} 已存在 —— 换一个新名字（写面不给 --force）"]
    return []


# ================================================================ 守卫⑤ 项目（卡 120 · T-G232）


def project_guard(tree_rel: object, project: object = None) -> list[str]:
    """项目守卫：**没登记的项目 / 树越界 / 反查不到 ⇒ 拒**（空列表 = 没被咬）。

    ★ 与 `pool.projects` 的三条硬判据配套（存在性即授权，和 MCP 写面同一个思路）：
      ① **没登记过的项目不许派活**（点名已登记的有哪些）；
      ② `tree` 必须落在该项目 `tree_prefixes` 里，越界 ⇒ 拒并**点名允许哪些前缀**；
      ③ 不给 `project` ⇒ 用 `projects.find_by_tree` **反查**；反查不到 ⇒ 拒
         （"这棵树不属于任何已登记项目"）。
    ★ 主树（`tree_rel == ""`）= **项目根本身** ⇒ 放行 —— 它就是这个项目；"越界"的定义是
      "落在本项目的树前缀之外"，不是"不是主树"。
    ★ 索引读不了（找不到 / 本身违规）⇒ **拒**（不猜、不放过）。
    ★ 该函数只**读**只读索引（不写 / 不 print / 不起进程）：问题是返回值，不是异常；
      与同模块另三条同一风格（吃数据 / 回 `list[str]`，只是这条的数据在只读索引里）。
    """
    try:
        entries = pool_projects.load()
    except pool_projects.ProjectsError as exc:
        return [f"项目索引读不了（项目守卫判不了）：{exc}"]
    tree = _norm(tree_rel)
    name = str(project).strip() if project is not None else ""
    if not name:
        found = pool_projects.find_by_tree(tree, rows=entries)
        if not found:
            return [f"这棵树不属于任何已登记项目：{_tree_label(tree)}"
                    f" —— 没登记的树不许派活（先把它登记进项目索引）"]
        name = found
    entry = pool_projects.get(name, rows=entries)
    if entry is None:
        known = "、".join(row["id"] for row in entries) or "（一个都没登记）"
        return [f"没登记过的项目不许派活：{name}（已登记：{known}）"]
    if tree == "":
        owner = pool_projects.find_by_tree("", rows=entries)
        if owner is None or owner == name:
            return []
        return [f"树越界：主树属于项目 {owner}，不是 {name}"]
    if pool_projects.under_prefix(tree, entry["tree_prefixes"]):
        return []
    return [f"树越界：{_tree_label(tree)} 不落在项目 {name} 的树前缀里"
            f"（允许：{'、'.join(entry['tree_prefixes'])}）"]


# ================================================================ 守卫⑥ 每账号并发闸（卡 A339）


def lane_guard(account: object, reservations: Iterable[dict], *, limit: int,
               queue: int = 0, now: float | None = None) -> list[str]:
    """每账号并发闸：这个号**同时在跑的活租约**已经到上限了吗 ⇒ 回 1 条问题。

    **防什么**：同一个号（`accounts.toml` 的稳定 id）同时派好几张卡，会一起撞 vendor 的限流，
    也会一起抢本机的内存与端口。★ 移植的是 magpie 每账号并发闸（`concurrency.go`）的
    **形状与判据，不是它的理由**：magpie 防的是"同一个 key 打太多 → 429"；pool 这边若不设限，
    真正的瓶颈是**本机内存**（`gates/diag/gate_lock.py` 原文：一趟 17 门要 15–30 个无头 Edge）。

    判据（三条，缺一条就有洞）：
      - ★ `limit <= 0` ⇒ 永远 `[]`。照抄 magpie `concurrency.go:82`：**0 = 关掉闸**，
        **不是**"一个都不许"（写成 `>= 0` 会让所有派活都派不出去）。
      - `account` 空 / 非字符串 ⇒ `[]`：没点名账号 = 没闸（老租约里没有 `account` 键，
        也不该因此把它们算到某个号头上）。
      - 数 `res["account"] == account` 的条数，`>= limit` ⇒ 回 1 条问题（**不是** `>`：
        "上限 2"的意思是同账号最多 2 张，第 3 张才该被拒，而 `>= limit` 判的是**派这张之前**
        已经在跑的条数 —— 已经有 2 张在跑就轮到它排队了）。

    ★ `now` 收下但**不在这里判活**：入参 `reservations` 必须是调用方（`registry.reserve`）
      已经过 `registry.is_dead()` 的 `live`。在这里重判一遍 = 造第二份"死租约"真源，
      而且会让"忘了清死租约"这个真 bug 测不出来（本卡的 `test_reverse_lane_guard_*` 就钉这个）。
      收下 `now` 只为本模块四条守卫签名同形，便于调用方统一传参。

    ★ `queue` 的语义**说实话**：magpie 的 QueueLimit 是**真队列**（进不去就排队等）；pool 的派活
      是同步的，**没有"在等"这个状态** ⇒ 本函数里 `queue` 只能表达"允许多少个派活进程在闸门口等"，
      `queue == 0` = 不排队、直接拒。本卡**不实现等待**（`wait` 留给下一张卡），所以
      `queue > 0` 时判据与 `queue == 0` **完全相同**（都按 `limit` 判），只在文案里多一句
      "队列上限 q 张" —— 绝不写 `while True: sleep`。

    ★ 纯函数：不读文件 / 不读环境 / 不 `print` / 不起进程（同模块另四条的规矩）。
      `limit` / `queue` 是调用方从 `pool.lanes` 读好之后传进来的整数 —— 本模块不碰 TOML。
    """
    name = str(account).strip() if isinstance(account, str) else ""
    if not name:
        return []
    if limit <= 0:
        return []
    running = sum(1 for res in reservations if str(res.get("account") or "").strip() == name)
    if running < limit:
        return []
    tail = f"，队列上限 {queue} 张" if queue > 0 else ""
    return [f"这个号已经占满：账号 {name} 同时在跑 {running} 张，上限 {limit} 张{tail}"
            f" —— 等它收工（或换个号）再派"]


__all__ = [
    "domain_guard", "lane_guard", "lock_guard", "log_guard", "project_guard", "tree_guard",
]
