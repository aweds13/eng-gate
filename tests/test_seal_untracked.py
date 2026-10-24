"""核「生成了却没进提交」这条机器判据会不会咬（T-G212 · 卡 115）。

## 为什么有这张测试

2026-10-02 三笔提交（`T-G205`/`T-G206`/`T-G208`）的**片段文件根本没进提交** ——
`_stage_card.py` 在卡树里生成 `docs/changelog.d/<台账号>.md` 等片段（**未跟踪文件**），
集成时 `git add --allow` 只给了代码文件 ⇒ 提交里没有片段（实测三笔的 `.d/` 文件数 = 0/0/0）。
这门缺口**零判据**：`run_gates.py --seal` 算的封存树包含了那些未跟踪片段却没人跟提交树比，
`sync_docs.py --check` 又只查"现有片段在不在汇总里"、少文件照样 PASS。

本卡补上：`--seal` 把当时未跟踪的清单记进 `gates/last.json.untracked`；
`scripts/audit_progress.py::check_seal_untracked()` 拿全量跟踪路径点名（卡 E8 起是
**一次** `git ls-files -z`，不再是逐条 `ls-files --error-unmatch`）。

## 怎么验（临时 git 仓库，不碰真仓库）

四条钉子（卡 §3）：
  ① 会咬 —— 清单里的文件没被跟踪且还在 ⇒ 报红并点名那条路径；
  ② 不误报 —— 同一文件 `git add` 之后 ⇒ 绿；
  ③ 优雅降级 —— 老 `last.json` 没有 `untracked` 字段 ⇒ 绿（不崩、不报红）；
  ④ `--seal` 真写清单 —— 跑一次 `seal()`，新字段**恰好**是当时未跟踪的那些（已跟踪的不在、
     `gates/**` 不在）。
另加一条：文件**已不存在** ⇒ 不算缺（口径"必须已被跟踪（或者干脆不存在了）"）。

卡 E8（T-AG454）再加四条：
  ⑤ 215 条清单 ⇒ **1** 次 `subprocess.run`（旧的逐条实现是 215 次）；
  ⑥ 空清单 ⇒ **0** 次进程、返回空；
  ⑦ 中文路径的已跟踪文件要命中（一次取全量之后是**自己**解 UTF-8，坑 19）；
  ⑧ 语义不因提速而变 —— 同一次取全量下，缺片段仍点名、非片段仍不计。

★ 全部在 `tmp_path` 里 `git init` 的真临时仓库跑，**不动**本仓库的 `gates/last.json`、
不跑任何门（卡禁区：跑真门禁太贵）。

## 边界（如实写，未覆盖）

- 不跑 `main()` 全量（本卡明说跑真门禁太贵）；判据落进 `all_fails` 那条由 `main()` 收口，
  这里只钉 `check_seal_untracked()` 这一条判据本身。
- 只在 Windows（本仓主力）上跑过；路径分隔符交给 git（`git ls-files` 输出 `/`）。
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import audit_progress as ap  # noqa: E402 —— 需要先用 sys.path 把 scripts/ 挂上
import run_gates as rg  # noqa: E402

_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args], cwd=root, env=_GIT_ENV,
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    assert done.returncode == 0, f"git {args} 失败：{done.stderr}"
    return done.stdout.strip()


def _seed(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _init_repo(root: Path) -> None:
    """一个**真**临时 git 仓库（`--seal` 要真 git），已有一笔提交（`src/a.txt` 已跟踪）。"""
    _git(root, "init", "-q")
    _seed(root, "src/a.txt", "A")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")


def _write_last(root: Path, payload: dict) -> None:
    _seed(root, "gates/last.json", json.dumps(payload, ensure_ascii=False))


def _count_runs(monkeypatch) -> list[list[str]]:
    """把 `subprocess.run` 换成**计数桩**（照常真跑，只把 argv 记下来）。"""
    calls: list[list[str]] = []
    real = subprocess.run

    def counting(argv, *args, **kwargs):
        calls.append(list(argv))
        return real(argv, *args, **kwargs)

    monkeypatch.setattr(ap.subprocess, "run", counting)
    return calls


# ------------------------------------------------------------------ ① 必须咬

def test_untracked_fragment_after_seal_is_caught_and_named(tmp_path: Path) -> None:
    """★ ① 清单里的文件没被跟踪且还在 ⇒ 报红并点名那条路径（今晚那三笔的形态）。"""
    _init_repo(tmp_path)
    _seed(tmp_path, "docs/changelog.d/T-G999.md", "片段：生成了，没进提交")
    _write_last(tmp_path, {"ok": True, "untracked": ["docs/changelog.d/T-G999.md"]})

    fails = ap.check_seal_untracked(repo=tmp_path)

    assert fails, "造了未跟踪片段却不报红 —— 这条判据不会咬（等于注释）"
    assert any("docs/changelog.d/T-G999.md" in f for f in fails)   # 逐条点名
    assert any("生成了却没进提交" in f for f in fails)              # 附一句人话
    assert any("--allow" in f for f in fails)                      # 指向集成那个洞


# ------------------------------------------------------------------ ② 不许误报

def test_tracked_afterwards_is_green(tmp_path: Path) -> None:
    """★ ② 同一个文件 `git add` 之后 ⇒ 绿（别把已经进提交的也报了）。"""
    _init_repo(tmp_path)
    _seed(tmp_path, "docs/changelog.d/T-G999.md", "片段")
    _write_last(tmp_path, {"ok": True, "untracked": ["docs/changelog.d/T-G999.md"]})
    _git(tmp_path, "add", "docs/changelog.d/T-G999.md")

    assert ap.check_seal_untracked(repo=tmp_path) == []


# ------------------------------------------------------------------ ③ 优雅降级

def test_old_last_json_without_field_degrades(tmp_path: Path) -> None:
    """★ ③ 老 `last.json` 里**没有** `untracked` 字段 ⇒ 绿（不崩、不报红）。

    仓库里就躺着历史版本的 `gates/last.json`，这条不降级就会当场假红。
    """
    _init_repo(tmp_path)
    _seed(tmp_path, "docs/changelog.d/T-G999.md", "片段")
    _write_last(tmp_path, {"ok": True, "tree": "老产物没有 untracked"})

    assert ap.check_seal_untracked(repo=tmp_path) == []


def test_absent_file_is_not_a_violation(tmp_path: Path) -> None:
    """口径「必须已被跟踪（**或者干脆不存在了**）」：文件被删/改名 ⇒ 不算缺。"""
    _init_repo(tmp_path)
    _write_last(tmp_path, {"ok": True, "untracked": ["docs/changelog.d/T-G999.md"]})

    assert ap.check_seal_untracked(repo=tmp_path) == []


# ------------------------------------------------------------------ ④ --seal 真写清单

def test_seal_records_exactly_the_untracked_files(
    tmp_path: Path, monkeypatch,
) -> None:
    """★ ④ `--seal` 真写清单：新字段**恰好**是当时未跟踪的那些。

    已跟踪的（`src/a.txt`）不在、`gates/**`（`gates/reuse.json`）不在 —— 断言用**排序列表
    相等**（不只是"包含"），"恰好"才算钉住。
    """
    _init_repo(tmp_path)
    _write_last(tmp_path, {"ok": True, "tree": "old"})
    _seed(tmp_path, "docs/changelog.d/T-G999.md", "片段")  # 未跟踪 → 该进清单
    _seed(tmp_path, "notes.txt", "随手记")                  # 未跟踪 → 该进清单
    _seed(tmp_path, "gates/reuse.json", "{}")               # gates/** → 不许进清单

    monkeypatch.setattr(rg, "ROOT", tmp_path)
    monkeypatch.setattr(rg, "GATES", tmp_path / "gates" / "last.json")

    assert rg.seal() == 0

    payload = json.loads((tmp_path / "gates" / "last.json").read_text(encoding="utf-8"))
    assert sorted(payload["untracked"]) == ["docs/changelog.d/T-G999.md", "notes.txt"]
    assert "src/a.txt" not in payload["untracked"]        # 已跟踪的不列
    assert all(not p.startswith("gates/") for p in payload["untracked"])  # gates/** 不列


# --------------------------------------------------- ⑤ 卡 118：外来未跟踪文件**不算缺**

def test_foreign_untracked_file_is_not_a_violation(tmp_path: Path) -> None:
    """★ 卡 118（T-G216）：**外来未跟踪文件不算缺**（用户放在仓库根的笔记就是这种）。

    来路：收一笔文档任务时，⑪ 拿「封存时未跟踪」的**全量**清单去比 ⇒ 把用户那 4 份一直未跟踪、
    明确说过「留着」的笔记判成「生成了却没进提交」⇒ **任何主树收口都会被挡住**。
    口径收窄到三个片段目录；其它位置不算缺（但会报一行「不计」）。
    """
    _init_repo(tmp_path)
    _seed(tmp_path, "外来笔记.md", "用户自己的东西，永远不该进提交")
    _seed(tmp_path, "docs/changelog.d/T-G999.md", "真漏的片段")
    _write_last(tmp_path, {"ok": True, "untracked": ["外来笔记.md", "docs/changelog.d/T-G999.md"]})

    fails = ap.check_seal_untracked(repo=tmp_path)

    assert len(fails) == 1, fails
    assert fails[0].startswith("docs/changelog.d/T-G999.md"), fails
    assert not any("外来笔记" in f for f in fails), fails


def test_foreign_untracked_file_alone_is_green_and_reported(tmp_path: Path) -> None:
    """★ 只有外来未跟踪文件 ⇒ **绿**（今晚主树那 4 份笔记的形态），且要报一行「不计」。"""
    _init_repo(tmp_path)
    _seed(tmp_path, "DSH-窗口化方案.md", "用户的笔记")
    _write_last(tmp_path, {"ok": True, "untracked": ["DSH-窗口化方案.md"]})

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fails = ap.check_seal_untracked(repo=tmp_path)

    assert fails == []
    assert "不计" in buf.getvalue() and "无关" in buf.getvalue()


# ---------------------------------------------------- ⑤ 卡 E8：215 条清单只起 1 次进程

def test_215_paths_cost_exactly_one_git_process(tmp_path: Path, monkeypatch) -> None:
    """★ ⑤ 卡 E8：215 条清单 ⇒ **1** 次 `subprocess.run`（旧实现是 215 次）。

    来路：`_is_tracked()` 对每个路径起一次 `git ls-files --error-unmatch`，
    实测 215 条未跟踪 ⇒ 215 次进程 ⇒ `--all` 25.2 s（一次 `ls-files -z` 只要 0.10 s）。
    这里用**计数器桩**数真进程，别只靠掐表（表受机器负载影响，数不进判据）。
    """
    _init_repo(tmp_path)
    tracked = [f"src/many/f{i:03d}.txt" for i in range(214)]
    for rel in tracked:
        _seed(tmp_path, rel, "x")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "214 个已跟踪文件")
    _seed(tmp_path, "docs/changelog.d/T-G999.md", "真漏的片段")  # 唯一真缺
    _write_last(
        tmp_path, {"ok": True, "untracked": [*tracked, "docs/changelog.d/T-G999.md"]},
    )

    calls = _count_runs(monkeypatch)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fails = ap.check_seal_untracked(repo=tmp_path)

    assert len(calls) == 1, f"215 条清单起了 {len(calls)} 次进程（前三次：{calls[:3]}）"
    assert calls[0][:1] == ["git"] and "ls-files" in calls[0], calls[0]
    assert "-z" in calls[0], f"取全量要用 -z（路径带空格/中文才不会被拆）：{calls[0]}"
    # 语义不变：该点的名照样点，只有那一条
    assert fails and fails[0].startswith("docs/changelog.d/T-G999.md"), fails
    # 可观测：一行「已用一次 ls-files 取到 N 条跟踪路径」
    out = buf.getvalue()
    assert "已用一次 ls-files 取到" in out and "条跟踪路径" in out, out
    assert out.count("已用一次 ls-files 取到") == 1, out


# ------------------------------------------------------- ⑥ 卡 E8：空清单 0 次进程

def test_empty_untracked_list_starts_no_git_process(tmp_path: Path, monkeypatch) -> None:
    """★ ⑥ 清单为空 ⇒ **0** 次进程、返回空（省掉空跑）。"""
    _init_repo(tmp_path)
    _write_last(tmp_path, {"ok": True, "untracked": []})

    calls = _count_runs(monkeypatch)
    assert ap.check_seal_untracked(repo=tmp_path) == []
    assert calls == [], f"空清单也起了进程：{calls}"


# ------------------------------------------------ ⑦ 卡 E8：中文路径必须命中

def test_chinese_tracked_path_is_recognised(tmp_path: Path, monkeypatch) -> None:
    """★ ⑦ 一次取全量后**自己**解 UTF-8（坑 19）：中文路径的已跟踪文件要被认出来。

    旧实现用 `text=True` 按本机区域编码（这台机器 GBK）解 —— 中文路径会解歪甚至抛错；
    新实现显式 `decode("utf-8")`。这条钉子保证"解歪"不会把整批判成未跟踪。
    """
    _init_repo(tmp_path)
    _seed(tmp_path, "复盘/交接.d/T-G999.md", "中文路径的片段")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "中文路径")
    _write_last(tmp_path, {"ok": True, "untracked": ["复盘/交接.d/T-G999.md"]})

    caught = _count_runs(monkeypatch)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fails = ap.check_seal_untracked(repo=tmp_path)
    assert fails == [], f"中文路径的已跟踪文件被判成未跟踪：{fails}"
    assert len(caught) == 1, caught
    assert "条跟踪路径" in buf.getvalue(), buf.getvalue()
