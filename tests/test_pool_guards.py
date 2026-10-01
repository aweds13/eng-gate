r"""三条自家守卫（`tools/pool/guards.py`，卡 108 · T-G205）的测试。

为什么值当测：写面的地基就靠这三条守卫拦下"同一棵树两个写者 / 同一文件两个写者 / 门禁还在跑
就动手"。守卫是**纯函数**，所以既要**正例**（该拦的一个不漏），也要**反例**（不该拦的一个不误伤）
—— 误伤会让人干脆绕过守卫，比没有守卫更糟。

| 判据 | 判什么 |
|---|---|
| ① 正/反例 | 树冲突 / 域相交 / 门禁锁 / 日志覆盖 各一组 |
| ② 复用同一真源 | 相交判据就是 `pool.plan.files_intersect`（不另写一份） |
| ③ 三条"委托"钉住 | 内存闸 / 日志换名 / 模型白名单**不**在 guards 里重写 |

★ 导入口径照既有测试：把 `tools/` 挂上 `sys.path` 再 `import`。
"""

from __future__ import annotations

import datetime
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import wb_dispatch  # noqa: E402 —— tools/ 已在 sys.path 上
from pool import guards, locks, plan  # noqa: E402

NOW = 1_700_000_000.0


def _iso(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def _res(card: str = "108", tree: str = ".wt/a", files: tuple[str, ...] = ("a.py",), *,
         at: float = NOW, ttl: float = 21600.0, owner: str = "w1", log: str = "") -> dict:
    """造一条像 `registry` 落盘那样的租约（字段与它逐个对齐）。"""
    return {"card": card, "task": "", "tree": tree, "files": list(files), "pool": "",
            "model": "", "log": log, "owner": owner, "at": _iso(at),
            "ttl_seconds": ttl, "note": ""}


def _lock_line(card: str = "999", *, cwd: str = "D:/elsewhere", base: str = "9034") -> str:
    return (f"[锁] 段 base={base} 文件=gate.lock: card={card} pid=999 "
            f"起于 2026-10-01 23:37:00（已 12s / 租约剩 10788s；租约内） cwd={cwd}")


# ================================================================ ① locks.parse_entries


def test_parse_entries_reads_lock_lines_only() -> None:
    body = "\n".join([
        _lock_line("108"),
        _lock_line("109", base="8531"),
        "[锁] ★ 别看 pid 判活：acquire 与 run_gates 是两次进程调用，pid 正常就会是死的。",
        "[锁] 全局并发上限 TF_GATE_MAX_CONCURRENT=4，当前租约内 2 把在跑",
    ])
    rows = locks.parse_entries(body)
    assert [r["card"] for r in rows] == ["108", "109"]
    assert rows[0]["base"] == "9034" and rows[1]["base"] == "8531"
    assert rows[0]["age"] == 12 and rows[0]["remain"] == 10788


def test_parse_entries_empty_body_says_nothing() -> None:
    assert locks.parse_entries("[锁] 空着（没有任何段的锁）") == []
    assert locks.is_empty("[锁] 空着（没有任何段的锁）") is True   # 既有判据行为没变


# ================================================================ ① 守卫：正例 / 反例


def test_tree_guard_bites_same_tree_but_not_other() -> None:
    held = [_res("108", ".wt/a")]
    assert guards.tree_guard(".wt/a", held, NOW)          # 正例：同一棵树 → 咬
    assert guards.tree_guard(".wt/b", held, NOW) == []    # 反例：别的树 → 不咬


def test_tree_guard_covers_main_tree() -> None:
    assert guards.tree_guard("", [_res("108", "")], NOW)  # "" = 主树，同样只能一个


def test_tree_guard_ignores_expired_lease() -> None:
    held = [_res("108", ".wt/a", at=NOW - 30000, ttl=21600)]
    assert guards.tree_guard(".wt/a", held, NOW) == []     # 过期 → 自动腾位


def test_domain_guard_bites_and_names_the_intersection() -> None:
    held = [_res("108", ".wt/a", ("a.py", "b.py"))]
    problems = guards.domain_guard(["b.py", "c.py"], held, NOW)   # 正例：b.py 相交
    assert len(problems) == 1 and "b.py" in problems[0]
    assert guards.domain_guard(["c.py", "d.py"], held, NOW) == []  # 反例：不相交


def test_domain_guard_reuses_plan_files_intersect() -> None:
    """★ 相交判据是**现成的那份**，不是本模块另写的一份（本仓最忌两份真源）。"""
    assert guards.files_intersect is plan.files_intersect


def test_lock_guard_bites_own_card() -> None:
    problems = guards.lock_guard("108", ".wt/a", _lock_line("108"))
    assert problems and "108" in problems[0]


def test_lock_guard_bites_cwd_pointing_at_this_tree() -> None:
    root = Path("D:/eng")
    body = _lock_line("999", cwd="D:/eng/.wt/poolreg")
    assert guards.lock_guard("108", ".wt/poolreg", body, root=root)       # 正例
    assert guards.lock_guard("108", ".wt/other", body, root=root) == []   # 反例


def test_lock_guard_passes_unrelated_running_lock() -> None:
    body = _lock_line("999", cwd="D:/eng/.wt/somewhere-else")
    assert guards.lock_guard("108", ".wt/a", body, root=Path("D:/eng")) == []


def test_log_guard_bites_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "wb-108.jsonl"
    assert guards.log_guard(target) == []          # 反例：还没有
    target.write_text("{}", encoding="utf-8")
    problems = guards.log_guard(target)            # 正例：已存在 → 不许覆盖
    assert problems and "不许覆盖" in problems[0]
    assert guards.log_guard("") == []              # 没给路径 → 不咬


# ================================================================ ③ 三条"委托"钉住


def test_memory_gate_is_not_reimplemented_in_guards() -> None:
    names = [n.lower() for n in dir(guards)]
    assert not any("free_gb" in n or "membar" in n or n.startswith("mem_") for n in names)
    assert callable(wb_dispatch.gate_min_free_gb)          # 唯一实现在 wb_dispatch


def test_model_whitelist_is_not_reimplemented_in_guards() -> None:
    assert not any("whitelist" in n.lower() for n in dir(guards))
    assert wb_dispatch.MODEL_WHITELIST                     # 唯一实现在 wb_dispatch


def test_wb_dispatch_still_picks_rn_log_names(tmp_path: Path) -> None:
    """★ "日志不许覆盖"是委托给 wb_dispatch 的：它还按轮挑新名字（`.r2`…）。"""
    source = inspect.getsource(wb_dispatch)
    assert '.r{attempts}.jsonl' in source
    diag = tmp_path / "gates" / "diag"
    diag.mkdir(parents=True)
    (diag / "wb-108.jsonl").write_text("{}", encoding="utf-8")
    (diag / "wb-108.r2.jsonl").write_text("{}", encoding="utf-8")
    names = {p.name for p in wb_dispatch.card_artifacts(diag, "108", ".jsonl")}
    assert names == {"wb-108.jsonl", "wb-108.r2.jsonl"}


def test_guards_are_importable_without_registry() -> None:
    """守卫不依赖 registry（不 import 它）—— 有 IO 的清死租约由 registry 那层做。"""
    lines = [ln.strip() for ln in inspect.getsource(guards).splitlines()]
    assert not any(ln.startswith(("import registry", "from pool import registry"))
                   for ln in lines)
