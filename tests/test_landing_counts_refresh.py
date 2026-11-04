r"""钉「交接文档里那行台账分布不许停在翻账前」（卡 E87 · `T-AG594`）。

## 为什么这张测试

`复盘/交接-重构进度.md` 里有一行「台账进度：done a / partial b / todo c / deferred d（共 N 条」，
`tools/sync_counts.py` 负责把它刷成 `docs/traceability.toml` 算出来的值，
`scripts/audit_progress.py` 负责核对它。落地链的 ⑤′ 会把卡从 `pending` 翻成 `done`。

正常路（`② sync_docs` → `③ sync_counts` → ⑤′ 翻账）数字是对的。但 `--commit-only`
把 ②③ **整段跳过**（两者都在 `if not a.commit_only:` 里），而卡树里的
`docs/traceability.toml` 作者早已汇总过 ⇒ 这一笔提交照样让条目 +1、那行数字**一次都没刷**
⇒ 交接文档停在落笔前的值，审计当场判红。

现场（实测，不是推测）：卡 E85 落地笔 `10875e82` 的 `复盘/交接-重构进度.md` 写
`done=640 … 共 681 条`，而同一棵树 `docs/traceability.toml` 实算是 `641 … 682`；
`scripts/audit_progress.py --all --no-git` 报
`复盘/交接-重构进度.md 里写的分布对不上台账`。事后补一笔（`5f562922`）能擦干净，
但每落一张卡就欠一格。

## 七条钉子

| # | 钉子 | 坏掉会红在哪 |
|---|---|---|
| 1 | 翻账之后、提交之前把数字刷掉（提交里那行是新的） | 提交里仍是旧分布 |
| 2 | 顺序：翻账 → 刷数字 → 重算现算文档（两份读的是同一个分布） | 刷在翻账之前 ⇒ 写完又过期 |
| 3 | 数字本来就对 ⇒ 安静（不改字节、不夹带文件） | 每次都覆盖 / 每笔都多带一份 |
| 4 | 树里没有 `tools/sync_counts.py` ⇒ 明说一句后跳过 | 只拷了 `landing.py` 的树全红 |
| 5 | 写盘失败 ⇒ 停手，不提交 | 拿着旧数字提交 |
| 6 | 刷完复核仍不过 ⇒ 停手，不提交 | 写盘"成功"了但没真改，也照提交 |
| 7 | 刷出来的文件进这一笔提交，不是「计划外暂存」 | `extra` 非空 ⇒ 停手 |

## 怎么跑（★ 不碰真仓库、不跑真门禁）

- 假仓库、`wb_land.py` 入口、`--no-gate --no-review`，与
  `tests/test_pool_landing.py` **同一套夹具**（这里直接复用它的 `_mk_repo`，
  免得两份夹具各长各的）；
- ★ **`tools/sync_counts.py` 用真件**（本卡治的正是「落地链与刷数字工具之间那条接缝」，
  用桩会把接缝测没）—— 所以这里要把它和它依赖的 `tools/pipe_root.py` 一起换成真件，
  并把交接文档铺成**真有那行数字**的样子（原夹具里那份只有 `# 交接` 一行）；
- 外部命令（`sync_docs` / `check_toml` / `audit_progress` / `gate_lock` / `run_gates`）
  仍是桩。

## 边界（如实写，未覆盖）

- 只钉单卡路径；批模式（`--batch`）走的是**同一行**（两分支汇合之后），由
  `tests/test_pool_landing.py` 的批 e2e 与变异脚本覆盖。
- 不跑真全量门禁（贵且与本卡无关），门禁整段用 `--no-gate` 跳过。
- 只在 Windows（本仓主力）跑过。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HANDOFF_REL = "复盘/交接-重构进度.md"
LEDGER_REL = "docs/traceability.toml"
COUNTS_REL = "tools/sync_counts.py"
README_REL = "docs/subsystems/pool/README.md"

#: 台账：done=2 / todo=1（共 3 条）—— 刷数字的**目标**。
_LEDGER = """[entries."T-G998"]
id = "T-G998"
status = "done"

[entries."T-G999"]
id = "T-G999"
status = "done"

[entries."T-AG999"]
id = "T-AG999"
status = "todo"
"""

#: 交接文档：写的是 done=1 / todo=2 —— **与台账对不上**（就是被翻账落在后面的那种现场）。
_HANDOFF_STALE = """# 交接

## 现在在哪

- 台账进度：done 1 / partial 0 / todo 2 / deferred 0（共 3 条）
"""

#: 交接文档：写的**正好**是台账算出来的值（钉子 3 用）。
_HANDOFF_FRESH = """# 交接

## 现在在哪

- 台账进度：done 2 / partial 0 / todo 1 / deferred 0（共 3 条）
"""

#: 桩：写盘就失败（钉子 5）。
_STUB_WRITE_FAILS = "import sys\n\nprint('stub-write-fails')\nsys.exit(3)\n"

#: 桩：写盘退 0 却什么都没改，`--check` 如实退 1（钉子 6）。
_STUB_WRITE_OK_CHECK_FAILS = (
    "import sys\n\nprint('stub')\nsys.exit(1 if '--check' in sys.argv else 0)\n"
)


def _load_base():
    """按路径装 `tests/test_pool_landing.py`：借它的假仓库夹具，免得两份各长各的。"""
    path = ROOT / "tests" / "test_pool_landing.py"
    spec = importlib.util.spec_from_file_location("tpl_for_e87", path)
    assert spec is not None and spec.loader is not None, f"装不上夹具：{path}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_TPL = _load_base()


def _mk_repo(tmp_path: Path, handoff: str = _HANDOFF_STALE) -> Path:
    """假仓库 + **真件** `tools/sync_counts.py` + 一行真数字的交接文档。

    ★ 为什么必须换真件：`tests/test_pool_landing.py` 的夹具把 `tools/sync_counts.py`
      铺成 `print('stub')` 的桩 —— 那能测「调用过没」，测不出「数字真被刷对没」。
      本卡治的是接缝，就用真件（与那份夹具用真 `gen_pool_readme.py` 同一个理由）。
    """
    repo = _TPL._mk_repo(tmp_path)
    _TPL._write(repo, "tools/pipe_root.py",
                (ROOT / "tools" / "pipe_root.py").read_text(encoding="utf-8"))
    _TPL._write(repo, COUNTS_REL,
                (ROOT / "tools" / "sync_counts.py").read_text(encoding="utf-8"))
    _TPL._write(repo, LEDGER_REL, _LEDGER, crlf=True)
    _TPL._write(repo, HANDOFF_REL, handoff, crlf=True)
    _TPL._git(repo, "add", "-A")
    _TPL._git(repo, "commit", "-q", "-m", "counts")
    return repo


def _wand(repo: Path, *extra: str):
    """跑一次 `wb_land.py`（假仓库、`--tree .`），门禁与复核都跳过。

    ★ **走 `--commit-only`**：这才是漂移现场。正常路会先跑 ③ `tools/sync_counts.py`
      （那一步本来就把数字刷对了），拿它测 ⑤′.5 等于测了个空 —— 实测第一版就是这样：
      `③ sync_counts` 先输出 `已更新：复盘/交接-重构进度.md`，到 ⑤′.5 时已经是「最新的」。
      丢的那一侧正是 `--commit-only`：它把 ②③ 整段跳过，可卡树里的
      `docs/traceability.toml` 早已汇总过。
    """
    return _TPL._wand(repo, "--no-gate", "--commit-only", "--no-reset", "--no-review", *extra)


def _out(done) -> str:
    return _TPL._out(done)


def _head_text(repo: Path, rel: str) -> str:
    return _TPL._head_text(repo, rel)


def _head(repo: Path) -> str:
    got = _TPL._git(repo, "rev-parse", "HEAD")
    assert got.returncode == 0, got.stderr
    return got.stdout.strip()


# ================================================================ 判据 1
def test_the_handoff_line_is_refreshed_before_the_commit(tmp_path: Path) -> None:
    """判据 1：翻账之后、提交之前，把「台账进度」那行刷成台账算出来的值。

    坏掉的写法：⑤′.5 只重算现算文档（本卡开工前就是这样）⇒ 提交里那行仍是
    `done 1 / todo 2`，`scripts/audit_progress.py` 当场判红。
    """
    repo = _mk_repo(tmp_path)
    _TPL._write(repo, "code/a.py", "X = 2\n")

    done = _wand(repo)
    out = _out(done)

    assert done.returncode == 0, out
    assert "[队列] 卡 T-G999：pending → done" in out, out
    assert "★ 台账分布改了它 ⇒ 随这一笔提交：" + HANDOFF_REL in out, out
    head = _head_text(repo, HANDOFF_REL)
    assert "done 2 / partial 0 / todo 1 / deferred 0（共 3 条）" in head, head
    assert "done 1 / partial 0 / todo 2 / deferred 0" not in head, head


# ================================================================ 判据 2
def test_the_refresh_runs_after_the_flip_and_before_the_recount(tmp_path: Path) -> None:
    """判据 2（**顺序钉子**）：翻账 → 刷数字 → 重算现算文档 → 暂存 → 提交。

    为什么顺序不能反：那行数字数的是 `docs/traceability.toml` 的分布，而两份现算文档
    （README 的「队列卡数」、`docs/INDEX.md`）读的正是同一个分布 —— 刷在翻账之前，
    写完立刻又过期；刷在重算之后，两份文档记的是刷之前的分布。
    """
    repo = _mk_repo(tmp_path)
    _TPL._write(repo, "code/a.py", "X = 2\n")

    done = _wand(repo)
    out = _out(done)

    assert done.returncode == 0, out
    flip_at = out.find("[队列] 卡 T-G999：pending → done")
    refresh_at = out.find("★ 台账分布改了它 ⇒ 随这一笔提交：" + HANDOFF_REL)
    recount_at = out.find("[OK  ] 写了 " + README_REL)
    assert flip_at >= 0, out
    assert refresh_at >= 0, out
    assert recount_at >= 0, out
    why = f"顺序不对（flip@{flip_at} / refresh@{refresh_at} / recount@{recount_at}）：\n{out}"
    assert flip_at < refresh_at < recount_at, why


# ================================================================ 判据 3
def test_it_is_quiet_when_the_numbers_already_agree(tmp_path: Path) -> None:
    """判据 3：数字本来就对 ⇒ 安静（不改字节、不夹带文件）。

    ★ 为什么要这一条：「每次都覆盖」也能让判据 1 绿，但那会无谓改动交接文档
      （行尾/日期/别的段落都可能被重写），且每笔提交都多带一份文件。
    """
    repo = _mk_repo(tmp_path, handoff=_HANDOFF_FRESH)
    _TPL._write(repo, "code/a.py", "X = 2\n")

    done = _wand(repo)
    out = _out(done)

    assert done.returncode == 0, out
    assert "交接文档里的台账分布是最新的" in out, out
    assert "★ 台账分布改了它 ⇒ 随这一笔提交：" + HANDOFF_REL not in out, out
    assert HANDOFF_REL not in _TPL._head_files(repo), _TPL._head_files(repo)


# ================================================================ 判据 4
def test_a_missing_counts_tool_is_skipped_loudly(tmp_path: Path) -> None:
    """判据 4：这棵树里没有 `tools/sync_counts.py` ⇒ 明说一句后跳过。

    不许静默（人得知道这一笔**没有**核数字），也不许退 2（否则所有只拷了
    `landing.py` 的树、以及本仓自己的老树全红）。
    """
    repo = _mk_repo(tmp_path)
    (repo / COUNTS_REL).unlink()
    _TPL._git(repo, "add", "-A")
    _TPL._git(repo, "commit", "-q", "-m", "drop-counts")
    _TPL._write(repo, "code/a.py", "X = 2\n")

    done = _wand(repo)
    out = _out(done)

    assert done.returncode == 0, out
    assert f"· 刷台账分布：这棵树里没有 {COUNTS_REL}（跳过）" in out, out
    assert "[队列] 卡 T-G999：pending → done" in out, out


# ================================================================ 判据 5
def test_a_failing_counts_tool_stops_the_landing(tmp_path: Path) -> None:
    """判据 5：刷数字的命令失败 ⇒ 停手，不提交（不许拿着旧数字提交）。"""
    repo = _mk_repo(tmp_path)
    _TPL._write(repo, COUNTS_REL, _STUB_WRITE_FAILS)
    _TPL._git(repo, "add", "-A")
    _TPL._git(repo, "commit", "-q", "-m", "stub-fail")
    _TPL._write(repo, "code/a.py", "X = 2\n")
    before = _head(repo)

    done = _wand(repo)
    out = _out(done)

    assert done.returncode != 0, out
    assert "★ 刷台账分布失败" in out, out
    assert _head(repo) == before, "停手之后不许留下提交"


# ================================================================ 判据 6
def test_a_tool_that_writes_nothing_still_stops_the_landing(tmp_path: Path) -> None:
    """判据 6：写盘"成功"（退 0）但没真改 ⇒ `--check` 复核不过 ⇒ 停手。

    ★ 这一条是判据 5 的补集：只信退出码就会被「退 0 但什么都没写」骗过去。
      所以刷完必须紧接着跑一次 `--check` —— 复核是**独立的一次读**，不是同一个返回值。
    """
    repo = _mk_repo(tmp_path)
    _TPL._write(repo, COUNTS_REL, _STUB_WRITE_OK_CHECK_FAILS)
    _TPL._git(repo, "add", "-A")
    _TPL._git(repo, "commit", "-q", "-m", "stub-noop")
    _TPL._write(repo, "code/a.py", "X = 2\n")
    before = _head(repo)

    done = _wand(repo)
    out = _out(done)

    assert done.returncode != 0, out
    assert "★ 刷完复核仍不通过" in out, out
    assert _head(repo) == before, "停手之后不许留下提交"


# ================================================================ 判据 7
def test_the_refreshed_file_joins_the_commit_instead_of_being_stray(
    tmp_path: Path,
) -> None:
    """判据 7：刷出来的文件随这一笔提交，且当场点名说「改了它」。

    ★ 两层事实（实测，别写过头）：
      1. **今天**这两份交接文档本来就在 `landing.DOCS` 白名单里，所以「不补进 `allow`」
         不会当场变成 extra —— 补 `allow` 那一支是为**将来新增第三份交接文档**留的
         （那时不在 DOCS 里，不补就真会停手）。这一层本卡测不到，别假装测到了。
      2. 能测的是：真被写盘的文件确实进了这一笔的提交树，而且链条当场点名。
         `★ M1`（把 ⑤′.5 那一段整块删掉）就是靠这两条咬住的。
    """
    repo = _mk_repo(tmp_path)
    _TPL._write(repo, "code/a.py", "X = 2\n")

    done = _wand(repo)
    out = _out(done)

    assert done.returncode == 0, out
    assert "  extra  = []" in out, out
    assert "★ 计划外或空暂存区 ⇒ 停手" not in out, out
    assert f"★ 台账分布改了它 ⇒ 随这一笔提交：{HANDOFF_REL}" in out, out
    assert HANDOFF_REL in _TPL._head_files(repo), _TPL._head_files(repo)
