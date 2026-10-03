"""共享文档「每笔一个片段」汇总器的测试（卡 107 · T-G203）。

被测：`tools/sync_docs.py`（把 `docs/changelog.d/` / `docs/traceability.d/` / `复盘/交接.d/`
的片段按锚点汇进三个共享文档）。

四类钉子：
1. **幂等** —— 造 3 个片段 → 汇总 → 再汇总 → **零 diff**（本卡硬判据）；
2. **既有字节不被改写** —— 汇总只**插入**，旧内容原样留在原位（sha256 只增不改）；
3. **`--check` 抓手改** —— 手改汇总里一个字 → 非零退出且**点名**是哪个片段 / 哪个文件；
4. **★ 并发零冲突（本卡的目的）** —— 用**真 git** 演示"两笔各落自己的片段"→ 第二笔 rebase
   到第一笔之上**不冲突**；并给出**对照**：两笔都改同一个**共享文档**则**必冲突**。
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import sync_docs as sd  # noqa: E402 —— 需要先用 sys.path 把 tools/ 挂上

CHANGELOG_FRAG = (
    "## 2026-10-02 —— 示例：片段 A（T-G204 / 卡 108）\n"
    "\n"
    "- 病：示例。\n"
    "- 修：示例。\n"
)
TRACE_FRAG = (
    '[entries."T-G204"]\n'
    'id = "T-G204"\n'
    'title = "示例条目 A"\n'
    'group = "OPS"\n'
    'status = "done"\n'
    'evidence = ["file:tools/sync_docs.py"]\n'
    'gaps = ""\n'
)
HANDOFF_FRAG = (
    "> **2026-10-02 · CHECKPOINT（卡 108 · `T-G204`）—— 示例 A**：\n"
    "> 一行说明。\n"
)


def _mkroot(tmp_path: Path) -> Path:
    """造一个最小仓库骨架（三个共享文档 + 三个片段目录），内容尽量贴近真文件形态。"""
    (tmp_path / "docs" / "changelog.d").mkdir(parents=True)
    (tmp_path / "docs" / "traceability.d").mkdir(parents=True)
    (tmp_path / "复盘" / "交接.d").mkdir(parents=True)
    (tmp_path / "docs" / "changelog.md").write_text(
        "## 2026-10-01 —— 旧节（T-G001）\n\n- 旧内容。\n", encoding="utf-8"
    )
    (tmp_path / "docs" / "traceability.toml").write_text(
        "# 头注释\n\n[meta]\nx = 1\n\n"
        '[entries."T-G001"]\nid = "T-G001"\nstatus = "done"\ngaps = ""\n',
        encoding="utf-8",
    )
    (tmp_path / "复盘" / "交接-重构进度.md").write_text(
        "# 交接\n\n> 引言。\n\n"
        "> **2026-10-01 · CHECKPOINT（卡 1 · `T-G001`）—— 旧**：\n> 旧一行。\n",
        encoding="utf-8",
    )
    return tmp_path


def _write_frags(root: Path, tag: str, changelog: str, trace: str, handoff: str) -> None:
    (root / "docs" / "changelog.d" / f"{tag}.md").write_text(changelog, encoding="utf-8")
    (root / "docs" / "traceability.d" / f"{tag}.toml").write_text(trace, encoding="utf-8")
    (root / "复盘" / "交接.d" / f"{tag}.md").write_text(handoff, encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _docs_hashes(root: Path) -> dict[str, str]:
    return {
        "changelog": _sha256(root / "docs" / "changelog.md"),
        "traceability": _sha256(root / "docs" / "traceability.toml"),
        "交接": _sha256(root / "复盘" / "交接-重构进度.md"),
    }


# ---------------------------------------------------------------- 1. 幂等 + 既有字节不被改写



def test_compose_preserves_crlf(tmp_path: Path) -> None:
    """★ 主控补（T-G203 集成时）：汇总**不许把行尾改成 LF** —— 三个共享文档是纯 CRLF。

    原实现写死 `newline="\n"`，一汇总整份就变纯 LF（`_stage_card.py` 的行尾断言当场抓住）。
    """
    root = _mkroot(tmp_path)
    for rel in ("docs/changelog.md", "docs/traceability.toml", "复盘/交接-重构进度.md"):
        f = root / rel
        f.write_bytes(f.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    _write_frags(root, "T-G900", CHANGELOG_FRAG, TRACE_FRAG, HANDOFF_FRAG)

    assert sd.run(root, check=False) == 0
    for rel in ("docs/changelog.md", "docs/traceability.toml", "复盘/交接-重构进度.md"):
        b = (root / rel).read_bytes()
        assert b.count(b"\n") - b.count(b"\r\n") == 0, f"{rel} 汇总后出现裸 LF"


def test_merge_is_idempotent_and_preserves_existing_bytes(tmp_path: Path) -> None:
    root = _mkroot(tmp_path)
    old_changelog = (root / "docs" / "changelog.md").read_text(encoding="utf-8")
    old_trace = (root / "docs" / "traceability.toml").read_text(encoding="utf-8")
    _write_frags(root, "T-G204", CHANGELOG_FRAG, TRACE_FRAG, HANDOFF_FRAG)

    assert sd.run(root, check=False) == 0
    first = _docs_hashes(root)
    # 第二次汇总：零 diff（幂等）
    assert sd.run(root, check=False) == 0
    assert _docs_hashes(root) == first

    # 只插入、不改写：旧内容原样在后 / 头部注释原样在前
    new_changelog = (root / "docs" / "changelog.md").read_text(encoding="utf-8")
    assert new_changelog.endswith(old_changelog)  # 旧节逐字留在后面
    assert new_changelog.startswith("## 2026-10-02")  # 新片段接在文件头，首行仍是 `## 2026-`
    new_trace = (root / "docs" / "traceability.toml").read_text(encoding="utf-8")
    assert new_trace.startswith(old_trace.split("[entries.")[0])  # [meta] 头部一字不动
    assert new_trace.endswith(TRACE_FRAG)  # 新条目追加在文件尾


def test_empty_fragment_dirs_leave_docs_untouched(tmp_path: Path) -> None:
    """没有片段 ⇒ 三个共享文档逐字不变（这是"汇总前 == 汇总后"的真身）。"""
    root = _mkroot(tmp_path)
    before = _docs_hashes(root)
    assert sd.run(root, check=False) == 0
    assert _docs_hashes(root) == before
    assert sd.run(root, check=True) == 0


# ---------------------------------------------------------------- 2. --check 抓手改


def test_check_is_green_after_merge_and_points_at_hand_edit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _mkroot(tmp_path)
    _write_frags(root, "T-G204", CHANGELOG_FRAG, TRACE_FRAG, HANDOFF_FRAG)
    sd.run(root, check=False)
    assert sd.run(root, check=True) == 0  # 汇总后一致

    # 手改汇总里一个字（片段没改）→ --check 非零且点名
    p = root / "docs" / "changelog.md"
    p.write_text(
        p.read_text(encoding="utf-8").replace("片段 A", "片段 A【手改】"), encoding="utf-8"
    )
    assert sd.run(root, check=True) == 1
    out = capsys.readouterr().out
    assert "T-G204.md" in out  # 点名片段文件
    assert "changelog.md" in out  # 点名汇总文件


# ---------------------------------------------------------------- 2b. 反方向（卡 159 / T-G259）


def test_check_catches_a_deleted_fragment(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """★ 卡 159（INV-15 的钉子）：汇总里有、**片段被删了** ⇒ --check 必须红并点名。

    红读数（实现前）：--check 只查「片段没进汇总」一个方向，删掉片段照样绿 ⇒ 本用例红。
    绿读数（实现后）：git 里跟踪过 / HEAD 里有的片段没了 ⇒ 判红，点名台账号与汇总文件。
    """
    root = _mkroot(tmp_path)
    _write_frags(root, "T-G204", CHANGELOG_FRAG, TRACE_FRAG, HANDOFF_FRAG)
    assert sd.run(root, check=False) == 0  # 先把片段汇进三个共享文档（汇总里才有 T-G204）
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    # 片段已被 git 跟踪（提交过），然后从工作区删掉 —— 汇总里那段还在
    for rel in ("docs/changelog.d/T-G204.md", "docs/traceability.d/T-G204.toml",
                "复盘/交接.d/T-G204.md"):
        (root / rel).unlink()
    assert sd.run(root, check=True) == 1
    out = capsys.readouterr().out
    assert "T-G204" in out, out
    assert "片段" in out and ("删" in out or "没了" in out), out


def test_summary_only_units_are_reported_without_red(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """「本来就是汇总独有」（片段纪元之前的老账 / 从未有片段）⇒ 如实报一行，**不判红**。"""
    root = _mkroot(tmp_path)  # T-G001 在汇总里、从未有过片段、也不是 git 仓库
    assert sd.run(root, check=True) == 0
    out = capsys.readouterr().out
    assert "T-G001" in out, out


# ---------------------------------------------------------------- 3. 真 git 并发零冲突（本卡目的）


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "GIT_EDITOR": "true", "GIT_SEQUENCE_EDITOR": "true"}
    return subprocess.run(
        ["git", "-c", "core.quotepath=false", "-c", "commit.gpgsign=false", *args],
        cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
        check=False,
    )


def _init_repo(repo: Path) -> None:
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "docs" / "changelog.d").mkdir(parents=True)
    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")


def test_two_commits_rebase_without_conflict(tmp_path: Path) -> None:
    """两笔各落**自己的片段** → 第二笔 rebase 到第一笔之上**不冲突**（真 git）。"""
    repo = tmp_path / "r"
    _init_repo(repo)

    # 第一笔：落地卡 108 的片段
    (repo / "docs" / "changelog.d" / "T-G204.md").write_text(CHANGELOG_FRAG, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "card108 fragment")
    first = _git(repo, "rev-parse", "HEAD").stdout.strip()

    # 第二笔：从 base 起分支（模拟"并发"，只动卡 109 自己的片段）
    _git(repo, "checkout", "-q", "-b", "second", "HEAD~1")
    (repo / "docs" / "changelog.d").mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "changelog.d" / "T-G205.md").write_text(
        CHANGELOG_FRAG.replace("T-G204", "T-G205").replace("卡 108", "卡 109"), encoding="utf-8"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "card109 fragment")

    rb = _git(repo, "rebase", first)
    raw = (rb.stdout + rb.stderr).strip()
    print("REBASE_OUT:\n" + raw)  # 贴原样输出给主控
    assert rb.returncode == 0, raw
    assert "CONFLICT" not in raw
    names = sorted(p.name for p in (repo / "docs" / "changelog.d").iterdir())
    assert names == ["T-G204.md", "T-G205.md"]  # 两份片段都在


def test_shared_file_two_branches_conflict(tmp_path: Path) -> None:
    """对照：两笔都改**同一个共享文档**的同一处 → rebase **必冲突**（这就是要消除的病）。"""
    repo = tmp_path / "r2"
    _init_repo(repo)
    shared = repo / "docs" / "changelog.md"
    shared.write_text("## 2026-09-30 —— 骨架\n\n- 旧的。\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add changelog")
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()

    _git(repo, "checkout", "-q", "-b", "first", base)
    shared.write_text(
        "## 2026-10-01 —— 第一笔（T-G204）\n\n- a。\n\n" + shared.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "first edits shared")

    _git(repo, "checkout", "-q", "-b", "second", base)
    shared.write_text(
        "## 2026-10-01 —— 第二笔（T-G205）\n\n- b。\n\n" + shared.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "second edits shared")

    rb = _git(repo, "rebase", "first")
    assert rb.returncode != 0  # 撞在同一个文件同一处
    assert "CONFLICT" in (rb.stdout + rb.stderr)


# ---------------------------------------------------------------- 4. 真仓库：汇总不动文档 + audit


def test_real_repo_is_in_sync_and_merge_is_noop() -> None:
    changed = [
        ch.name
        for ch in sd.build_channels(ROOT)
        if sd._collect_pending(ch, sd._norm(sd._read_target(ch)))
    ]
    assert changed == [], f"提交前应无未汇总片段，但这些通道有待汇总片段：{changed}"
    before = _docs_hashes(ROOT)
    assert sd.run(ROOT, check=False) == 0  # 空片段 → no-op
    assert _docs_hashes(ROOT) == before  # 三个共享文档逐字不变
    assert sd.run(ROOT, check=True) == 0  # 片段 ↔ 汇总一致


def test_audit_verdict_unchanged_by_sync() -> None:
    def audit() -> tuple[int, str]:
        r = subprocess.run(
            [sys.executable, "-X", "utf8", "scripts/audit_progress.py", "--all"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
            check=False,
        )
        return r.returncode, (r.stdout or "") + (r.stderr or "")

    before = audit()
    assert sd.run(ROOT, check=False) == 0
    assert audit() == before  # 汇总前后 audit 结论逐字不变
    assert before[0] == 0
