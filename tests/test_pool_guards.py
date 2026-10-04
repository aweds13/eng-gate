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
from typing import TYPE_CHECKING

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import wb_dispatch  # noqa: E402 —— tools/ 已在 sys.path 上
from pool import guards, locks, plan  # noqa: E402

if TYPE_CHECKING:
    import pytest

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


# ================================================================ ④ 项目守卫（卡 120 · T-G232）
#
# 为什么值当测：`project_guard` 把"哪个项目 / 允许派到哪些树"从自觉变成机器判据。三条咬法各配
# 一条正例（别的项目的树 / 未登记项目 / 反查不到），并留一条"正常树放行"当反空转；「码道」是
# 用户亲口定的反例（索引里没有 ⇒ **不许猜路径**）。临时索引一律用 `TF_PROJECTS_TOML`。


def _two_projects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """临时索引：engineering（`.wt/`）与 other（`cards/`）—— 供"别的项目的树"测试。"""
    eng, other = tmp_path / "eng", tmp_path / "other"
    eng.mkdir()
    other.mkdir()
    index = tmp_path / "projects.toml"
    index.write_text((
        "[project.engineering]\n"
        f'root = "{eng.as_posix()}"\n'
        'memory = ["a.md"]\n'
        'tree_prefixes = [".wt/"]\n'
        "\n[project.other]\n"
        f'root = "{other.as_posix()}"\n'
        'memory = ["o.md"]\n'
        'tree_prefixes = ["cards/"]\n'), encoding="utf-8")
    monkeypatch.setenv("TF_PROJECTS_TOML", str(index))


def test_project_guard_allows_a_tree_in_prefix(tmp_path: Path,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    _two_projects(tmp_path, monkeypatch)
    assert guards.project_guard(".wt/card") == []          # 反例：正常树 ⇒ 放行
    assert guards.project_guard("cards/x", project="other") == []


def test_project_guard_bites_another_projects_tree(tmp_path: Path,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    """★ 别的项目的树 ⇒ 拒，并**点名允许哪些前缀**。"""
    _two_projects(tmp_path, monkeypatch)
    problems = guards.project_guard("cards/x", project="engineering")
    assert problems and "cards/x" in problems[0] and ".wt/" in problems[0]
    assert "越界" in problems[0]


def test_project_guard_bites_unregistered_project(tmp_path: Path,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    _two_projects(tmp_path, monkeypatch)
    problems = guards.project_guard(".wt/card", project="没有这个项目")
    assert problems and "没登记过的项目" in problems[0]


def test_project_guard_bites_when_reverse_lookup_fails(tmp_path: Path,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    _two_projects(tmp_path, monkeypatch)
    problems = guards.project_guard("somewhere/else")
    assert problems and "不属于任何已登记项目" in problems[0]


def test_project_guard_bites_foreign_index_main_tree(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """临时索引里的项目根都不是本仓库树的祖先 ⇒ 主树反查不到 ⇒ 拒（不默认放行）。"""
    _two_projects(tmp_path, monkeypatch)
    problems = guards.project_guard("")
    assert problems and "不属于任何已登记项目" in problems[0]


def test_project_guard_allows_the_main_tree_of_the_real_project(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """★ 真索引（engineering）：主树 = 项目根本身 ⇒ 放行（否则默认派活全被拦）。"""
    monkeypatch.delenv("TF_PROJECTS_TOML", raising=False)
    assert guards.project_guard("") == []


def test_project_guard_bites_when_index_is_unreadable(tmp_path: Path,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TF_PROJECTS_TOML", str(tmp_path / "没有这份.toml"))
    problems = guards.project_guard(".wt/x")
    assert problems and "项目索引读不了" in problems[0]


def test_project_guard_refuses_maidao_not_guesses(monkeypatch: pytest.MonkeyPatch) -> None:
    """★ 用户亲口：索引里只有 `engineering`（「码道」是号池、不是项目）⇒ 显式点它必须被拒。"""
    monkeypatch.delenv("TF_PROJECTS_TOML", raising=False)
    problems = guards.project_guard(".wt/card", project="码道")
    assert problems and "没登记过的项目" in problems[0] and "码道" in problems[0]


# ======================================== 守卫② · 符号级细判（2026-10-03 接线，零件是卡 188 的）


def test_domain_guard_allows_same_file_different_symbol() -> None:
    """★ 正例：同文件**不同符号** ⇒ 放行 —— 这是接线（卡 188 的零件接进守卫）的全部意义。"""
    f = "tools/wb_dispatch.py"
    held = [_res("151", ".wt/verdict", (f + "::status_report",))]
    assert guards.domain_guard([f + "::auth_ok"], held, NOW) == []
    notes = guards.domain_notes([f + "::auth_ok"], held, NOW)
    assert notes and "rebase" in notes[0] and "同文件" in notes[0]


def test_domain_guard_bites_same_file_same_symbol() -> None:
    """★ 反例：同文件**同符号** ⇒ 照旧拒（放行只放"不同符号"那一类）。"""
    f = "tools/wb_dispatch.py"
    held = [_res("151", ".wt/verdict", (f + "::status_report",))]
    bad = guards.domain_guard([f + "::status_report"], held, NOW)
    assert bad and "同符号" in bad[0]


def test_domain_guard_bites_whole_file_against_a_symbol() -> None:
    """★★ **粗筛看不见的那一种**：`X.py` 与 `X.py::sym` 在 `files_intersect` 里
    **永不相交**（字符串精确相交）⇒ 今天会被放过去。接线必须按**文件部分**成对，把它拦住。
    """
    f = "tools/wb_dispatch.py"
    assert plan.files_intersect(guards._as_card("?", [f]),
                                guards._as_card("151", [f + "::status_report"])) == set()
    held = [_res("151", ".wt/verdict", (f + "::status_report",))]
    bad = guards.domain_guard([f], held, NOW)
    assert bad and "同一整个文件" in bad[0]


def test_domain_guard_backward_compatible_without_symbols() -> None:
    """★ 硬要求：**不写 `::`** 的声明 ⇒ 行为与今天**逐字相同**（同文件即拒，
    且不给「可并行」提醒）。"""
    held = [_res("108", ".wt/a", ("a.py", "b.py"))]
    bad = guards.domain_guard(["b.py"], held, NOW)
    assert bad and "b.py" in bad[0]
    assert guards.domain_notes(["b.py"], held, NOW) == []
