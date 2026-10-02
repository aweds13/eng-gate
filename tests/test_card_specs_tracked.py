r"""卡规格要「进 git」：队列自洽 + 向后兼容 + 逐字（卡 116 · T-G213）。

用户问：「用 pool 工具处理任务 —— 为什么会处理你的任务，不是另一个 AI 的任务？」
查实的缺口：队列 `docs/workbacklog.toml` 在 git 里，但每张卡登记的 `spec` 指向
`gates/diag/…` —— 那个目录是 `.gitignore` 的 ⇒ 换个窗口 / 换台机器拿到这份仓库，
看得到队列、却读不到"这张卡要干什么"。本卡把队列登记的那几份卡规格**逐字**搬进
`复盘/卡/`（git 寻得到），并钉三条判据：

| 钉子 | 判什么 |
|---|---|
| ① 队列自洽 | 队列里**每一条** `spec` 必须**存在**且被 `git ls-files` 认（= 已进 git） |
| ② 向后兼容 | `find_spec` 先在 `复盘/卡/` 找、找不到退回 `gates/diag/` —— 老卡照样解析 |
| ③ 逐字 | `复盘/卡/<名>` 与主仓 `gates/diag/<名>` sha256 相等（源不在则**跳过并说明**） |

① 用的命令是 `git ls-files --error-unmatch <path>`（`--error-unmatch` 让"没被跟踪"直接非 0）。

★ 导入口径照既有测试（`tests/test_pool_lib.py`）：把 `tools/` 挂上 `sys.path` 再 import。
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from pool import plan as pool_plan  # noqa: E402 —— tools/ 已在 sys.path 上

SPEC_DIR = "复盘/卡"

# 本卡搬进 git 的那 11 份 + 卡 116 自己那份（逐字对照用）。
SPEC_NAMES = (
    "卡022-myday稀疏序号.md",
    "卡024-看门狗独立化.md",
    "卡029-派活器三合一.md",
    "卡108-号池写面①作业登记与守卫.md",
    "卡109-号池去重收口.md",
    "卡110-文档落地七条坑与清单.md",
    "卡111-号池写面②MCP写工具.md",
    "卡112-切片两处误报.md",
    "卡113-pool_cancel证据编码.md",
    "卡114-main_tree_root不许依赖cwd.md",
    "卡115-封存未跟踪清单判据.md",
    "卡116-卡规格搬进git.md",
)


def _run_git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=root, capture_output=True)


def _is_tracked(root: Path, rel: str) -> bool:
    """`git ls-files --error-unmatch <rel>` 认不认它（= 已进 git 索引 / 提交）。"""
    return _run_git(root, "ls-files", "--error-unmatch", "--", rel).returncode == 0


def _git_blob(root: Path, rel: str) -> bytes | None:
    """索引里那份 `rel` 的**规范字节**（autocrlf 下是 LF）；不在索引里 → `None`。"""
    done = _run_git(root, "cat-file", "blob", f":{rel}")
    return done.stdout if done.returncode == 0 else None


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source_diag_dir() -> Path | None:
    """主仓 `gates/diag/`（卡规格的存档目录）。

    ★ 卡树（`.wt/cardgit`）里**没有**那批源文件 —— 它们只在主仓。
    工作树若是 `…/.wt/<名>` 这种形态，主仓就在它的上两级；否则退回本树（主树自己跑时）。
    找到且真含卡规格才算数（本树的 `gates/diag/` 只有 `gate_lock.py`）。
    """
    cands: list[Path] = []
    if ROOT.parent.name == ".wt":
        cands.append(ROOT.parent.parent / "gates" / "diag")
    cands.append(ROOT / "gates" / "diag")
    for cand in cands:
        if cand.is_dir() and any((cand / name).exists() for name in SPEC_NAMES):
            return cand
    return None


# ================================================================ ① 队列自洽


def test_every_registered_spec_exists_and_is_tracked() -> None:
    """核心判据：队列里每一条 `spec` 都必须**存在**且**已进 git**。

    这是本卡真正要"咬"的那条 —— 以后再加卡、忘了把规格搬进 git，这里就红并**点名**卡号 + 路径。
    """
    backlog = pool_plan.load_backlog()
    problems: list[str] = []
    for card in backlog.cards:
        rel = card.spec
        if not rel:
            problems.append(f"卡 {card.id}：`spec` 是空的")
        elif not (ROOT / rel).exists():
            problems.append(f"卡 {card.id}：spec 文件不存在：{rel}")
        elif not _is_tracked(ROOT, rel):
            problems.append(f"卡 {card.id}：spec 未进 git（`git ls-files` 不认）：{rel}")
    assert not problems, (
        "队列不自洽 —— 每条 spec 必须存在且进了 git：\n  · " + "\n  · ".join(problems)
    )


# ================================================================ ② 向后兼容


def test_find_spec_prefers_repo_card_dir_then_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`find_spec`：先在 `复盘/卡/` 找；找不到退回 `gates/diag/`（老卡解析不坏）。

    ★ 不在真 `gates/diag/` 里造文件（那是禁区）—— 退回分支用 `tmp_path` + `monkeypatch` 证明。
    """
    # 真仓库：卡 108 的规格已经搬进 `复盘/卡/`（不是老的 `gates/diag/`）
    assert pool_plan.find_spec("108") == "复盘/卡/卡108-号池写面①作业登记与守卫.md"

    # 临时树：两处都有 → 必须选 `复盘/卡/`（新家优先）；只在 `gates/diag/` → 退回分支照样解析
    monkeypatch.setattr(pool_plan, "ROOT", tmp_path)
    monkeypatch.setattr(pool_plan, "DIAG", tmp_path / "gates" / "diag")
    (tmp_path / SPEC_DIR).mkdir(parents=True)
    (tmp_path / "gates" / "diag").mkdir(parents=True)
    (tmp_path / SPEC_DIR / "卡108-新家.md").write_text("x", encoding="utf-8")
    (tmp_path / "gates" / "diag" / "卡108-旧家.md").write_text("x", encoding="utf-8")
    (tmp_path / "gates" / "diag" / "卡777-老家.md").write_text("x", encoding="utf-8")

    assert pool_plan.find_spec("108") == "复盘/卡/卡108-新家.md"
    assert pool_plan.find_spec("777") == "gates/diag/卡777-老家.md"


# ================================================================ ③ 逐字


def test_card_specs_copied_verbatim() -> None:
    """`复盘/卡/<名>` 与主仓 `gates/diag/<名>` **逐字**（sha256 相等）。

    ★ autocrlf：仓库 `core.autocrlf=true`（见 `.gitattributes` 说明）—— 源文件是 **LF**，
    git 索引里存的也是 **LF**，可工作区 checkout 出来会变 **CRLF**。所以工作区那份一旦
    与源不同，就再比一次**索引里的规范字节**（那才代表"进了 git 的那份"）。
    ★ 主仓 `gates/diag/` 不可达（如在别处跑）→ **跳过并说明**（卡树里没有该目录）。
    """
    src_dir = _source_diag_dir()
    if src_dir is None:
        pytest.skip("找不到主仓 gates/diag/ 存档（卡树里没有该目录）—— 逐字对照跳过")

    missing: list[str] = []
    for name in SPEC_NAMES:
        src = src_dir / name
        if not src.exists():
            missing.append(name)
            continue
        src_bytes = src.read_bytes()
        worktree = (ROOT / SPEC_DIR / name).read_bytes()
        same = _sha256(worktree) == _sha256(src_bytes)
        if not same:
            blob = _git_blob(ROOT, f"{SPEC_DIR}/{name}")
            same = blob is not None and _sha256(blob) == _sha256(src_bytes)
        assert same, f"{name}：不止是换目录 —— 内容与源文件不逐字"
    assert not missing, f"源存档里缺这些卡规格，无法对照：{missing}"
