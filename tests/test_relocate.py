"""归置机械码执行器的安全不变量（卡 087 / 台账号 T-G182）。

只钉**会咬人的那几条**（都在 tmp 假树上做，绝不动真仓库）：

1. ★ `[allow]` 为空 → `apply` **零搬动**且退 0；
2. ★ `[lock]` **永远优先于 `[allow]`**（同一条同时进两处 → 不搬）；
3. `[allow]` 有一条 → 搬 1 个；`undo` 后**目录树复原**（且幂等）；
4. ★ 幽灵条目（策略里写了、盘上找不到）→ `check` **退非 0** 且点名；
5. ★ 禁区硬编码：`src/**` / `pyproject.toml` / `.wt/**` / `gates*.lock` / `data/` 一律不搬；
6. ★ `index` **现算不落盘**，且 `exact` 盖过 `rules`（唯一一套优先级）。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import relocate  # noqa: E402  —— 需要先用 sys.path 挂上 tools/

LOCK_DIR = '"锁定/*" = "工具契约：测试用（整目录锁死）"'
LOCK_LOCKFILE = '"gates/diag/gates*.lock" = "禁区：门禁锁"'


def write_code(tmp_path: Path, allow: str = "", lock: str = "",
               rules: str = "", exact: str = "") -> Path:
    code = tmp_path / "code.toml"
    code.write_text(
        "[meta]\nversion = 1\n\n"
        f"[lock]\n{lock}\n\n"
        f"[allow]\n{allow}\n\n"
        f"[regroup.rules]\n{rules}\n\n"
        f"[regroup.exact]\n{exact}\n",
        encoding="utf-8",
    )
    return code


def build_tree(tmp_path: Path) -> Path:
    root = tmp_path / "tree"
    (root / "报告").mkdir(parents=True)
    (root / "报告" / "甲.md").write_text("甲", encoding="utf-8")
    (root / "报告" / "乙.md").write_text("乙", encoding="utf-8")
    (root / "锁定").mkdir()
    (root / "锁定" / "钉.md").write_text("钉", encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("pass", encoding="utf-8")
    (root / "data").mkdir()
    (root / "data" / "x.md").write_text("x", encoding="utf-8")
    (root / ".wt").mkdir()
    (root / ".wt" / "y.md").write_text("y", encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (root / "gates" / "diag").mkdir(parents=True)
    (root / "gates" / "diag" / "gates.lock").write_text("lock", encoding="utf-8")
    return root


def run(root: Path, code: Path, cmd: str, *extra: str) -> int:
    """跑一次工具；搬动记录放树外（免得它自己出现在快照里）。"""
    journal = root.parent / "journal.json"
    return relocate.main(["--code", str(code), "--root", str(root),
                          "--journal", str(journal), cmd, *extra])


def snapshot(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))


def test_allow_empty_moves_nothing(tmp_path: Path) -> None:
    """★ 不变量 1：[allow] 为空 → apply 零搬动、退 0、不留搬动记录。"""
    root = build_tree(tmp_path)
    code = write_code(tmp_path, lock=LOCK_DIR)
    before = snapshot(root)
    assert run(root, code, "apply") == 0
    assert snapshot(root) == before, "allow 为空却动了盘"
    assert not (root.parent / "journal.json").exists(), "空 allow 不该留记录"


def test_lock_beats_allow(tmp_path: Path) -> None:
    """★ 不变量 2：同一条同时进 [lock] 与 [allow] → 不搬（lock 优先）。"""
    root = build_tree(tmp_path)
    code = write_code(tmp_path, lock=LOCK_DIR,
                      allow='"锁定/钉.md" = { to = "报告/", why = "test" }')
    assert run(root, code, "apply") == 0
    assert (root / "锁定" / "钉.md").exists(), "被 lock 命中的文件不该被搬"
    assert not (root / "报告" / "钉.md").exists()


def test_allow_one_moves_and_undo_restores(tmp_path: Path) -> None:
    """不变量 3：[allow] 有一条 → 搬 1 个；undo 复原，再 undo 是空操作（幂等）。"""
    root = build_tree(tmp_path)
    code = write_code(tmp_path, lock=LOCK_DIR,
                      allow='"报告/甲.md" = { to = "报告/产品线/", why = "test" }')
    before = snapshot(root)
    assert run(root, code, "apply") == 0
    assert (root / "报告" / "产品线" / "甲.md").exists()
    assert not (root / "报告" / "甲.md").exists()
    assert run(root, code, "undo") == 0
    assert snapshot(root) == before, "undo 没把树复原"
    assert run(root, code, "undo") == 0  # 幂等：没有记录的再跑一次是空操作


def test_ghost_entry_fails_check(tmp_path: Path, capsys) -> None:
    """★ 不变量 4：[allow] 里写个盘上没有的路径 → check 退 2 且**点名**。"""
    root = build_tree(tmp_path)
    code = write_code(tmp_path, lock=LOCK_DIR,
                      allow='"报告/不存在.md" = { to = "报告/", why = "test" }')
    rc = run(root, code, "check")
    out = capsys.readouterr().out
    assert rc == 2, "幽灵条目必须退非 0"
    assert "报告/不存在.md" in out, "幽灵条目要点名"


def test_forbidden_paths_never_move(tmp_path: Path) -> None:
    """★ 不变量 5：硬编码禁区一律不搬（哪怕机械码放行、也不在 [lock]）。"""
    root = build_tree(tmp_path)
    allow = "\n".join([
        '"src/app.py" = { to = "报告/", why = "t" }',
        '"pyproject.toml" = { to = "报告/", why = "t" }',
        '".wt/y.md" = { to = "报告/", why = "t" }',
        '"data/x.md" = { to = "报告/", why = "t" }',
        '"gates/diag/gates.lock" = { to = "报告/", why = "t" }',
    ])
    code = write_code(tmp_path, lock=LOCK_LOCKFILE, allow=allow)
    assert run(root, code, "apply") == 0
    for rel in ("src/app.py", "pyproject.toml", ".wt/y.md", "data/x.md",
                "gates/diag/gates.lock"):
        assert (root / rel).exists(), f"禁区被搬了：{rel}"


def test_index_is_computed_not_persisted_and_exact_wins(tmp_path: Path) -> None:
    """★ 不变量 6：index 现算不落盘；exact 盖过 rules（唯一一套优先级）。"""
    root = build_tree(tmp_path)
    code = write_code(tmp_path, rules='"报告/*" = "外包卡"', exact='"报告/甲.md" = "产品线"')
    before = snapshot(root)
    assert run(root, code, "index") == 0
    assert snapshot(root) == before, "index 落盘了（应当只打印）"
    idx = relocate.compute_index(root, relocate.load_code(code))
    assert idx["报告/甲.md"] == "产品线", "exact 应当盖过 rules"
    assert idx["报告/乙.md"] == "外包卡", "没进 exact 的按 rules 走"


def test_pending_excludes_locked_and_forbidden(tmp_path: Path) -> None:
    """待搬表：在 [allow]、盘上有、但**不在** [lock]、也不在禁区。"""
    root = build_tree(tmp_path)
    allow = "\n".join([
        '"报告/甲.md" = { to = "报告/产品线/", why = "t" }',
        '"锁定/钉.md" = { to = "报告/", why = "t" }',
        '"src/app.py" = { to = "报告/", why = "t" }',
    ])
    code = write_code(tmp_path, lock=LOCK_DIR, allow=allow)
    rows = relocate.pending(root, relocate.load_code(code))
    assert [r[0] for r in rows] == ["报告/甲.md"]
