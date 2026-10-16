r"""钉 `tools/pool/landing.py` 的 ⑨ 盖章判据 —— 盖章**不许代写申请**（卡 248 · T-G369）。

## 为什么有这张测试

2026-10-15 主控实测的事故：主控把卡 244 单独落地（`--card 244`）时，⑨ 顺着
「paths 相交」把**卡 247 的批**（B-20261034，成员只有 247，`need=1`）也匹配上了
—— 卡 247 与卡 244 都要改 `tools/dsh_panel.py`（真实且必要的域重叠）。于是：

- ⑨ 替**从没开工**的卡 247 写了成功申请（`claims={'247': 'success'}`）✗✗；
- 栅栏「齐了」⇒ 拿**卡 244 的提交**（5e4f3d9…）把 B-20261034 标成 landed ✗。

根因：`_stamp_refusals()` 的判据只有一条 —— 成员的 `paths` ∩ 这笔提交真改过的
文件非空（卡 238 的判据，本身没错）；**同域兄弟卡**的 paths 与本笔提交相交
并不说明它做完了 —— **成员自己交没交申请**才是判别器。

## 钉子（六组，先红后绿）

| # | 钉子 | 旧码红在哪 |
|---|---|---|
| ① | 卡模式：paths 顺带匹配上的**兄弟成员**没自己的申请 ⇒ 不代写、不推它 | 旧码照样推（代写） |
| ② | ①的反例：兄弟**预置了**自己的申请 ⇒ 照旧推（证明①真的在拦） | 旧码就绿 |
| ③ | 卡模式 landed：全员**各自的申请**必须都在，缺一个 ⇒ 不标 landed 并点名 | 旧码按产物交集就标 |
| ④ | ③的反例：人人都有申请 ⇒ 照旧盖章（既有行为一字不变） | 旧码就绿 |
| ⑤ | 批模式：栅栏没集齐（有人没交申请）⇒ 一个申请都不推、不盖章、点名 | 旧码逐成员代写 |
| ⑥ | 卡 238 判据不许降级：产物不在提交里 ⇒ 照旧拒（先验产物、后验申请） | 旧码就绿 |

## 怎么跑（★ 不碰真仓库、不跑真门禁）

与 `tests/test_wb_land.py` 的卡 238 钉子同款夹具：`tmp_path` 里 `git init` 假仓库
（`ROOT` 指过去）、`TF_BATCH_DIR` 指到临时批目录、`_run_task_sub` 换成记录桩
（数「⑨ 推了几次 claim / landed」，**不真起子进程**）。

## 边界（如实写，未覆盖）

- 不覆盖真子进程路径（`wb_task.py claim/landed` 的落盘由 `tests/test_wb_land.py`
  与 `pool.task` 自证钉住；这里只钉 ⑨ 的**判据**与「推不推」的决定）。
- `waived`（显式豁免）与申请等价 —— 沿用 `pool.task._missing` 的口径
  （`_ok ∪ waived`），本文件不单独造豁免钉子。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"

sys.path.insert(0, str(TOOLS))
import json as _json248  # noqa: E402

from pool import landing as _landing  # noqa: E402

_ENV = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}


# ================================================================ 夹具

def _mk_gate(bd: Path, gate_id: str, state: str,
             members: list[dict[str, object]],
             claims: dict[str, str] | None = None,
             ) -> None:
    """在 `bd` 下造一个栅栏（toml + json）。

    与 test_wb_land 的 `_mk_gate212` 同构，多一个 `claims` 入参 —— 卡 248 的
    判据读的就是这个字段（state JSON 的 `claims`）。
    """
    bd.mkdir(parents=True, exist_ok=True)
    member_text = "".join(
        f'\n[[member]]\nid = "{m["id"]}"\nlayer = "工具层"\n'
        + ('read_only = true\n' if m.get("read_only") else "")
        + f'paths = {_json248.dumps(m.get("paths", []))}\n'
        for m in members)
    (bd / f"{gate_id}.toml").write_text(
        f'id = "{gate_id}"\nwhy = "test"\non_complete = ["draft"]\n{member_text}',
        encoding="utf-8")
    declared = [str(m["id"]) for m in members]
    read_only = [str(m["id"]) for m in members if m.get("read_only")]
    st = {
        "id": gate_id, "why": "test", "layers": ["工具层"], "declared": declared,
        "read_only": read_only, "need": len(declared) - len(read_only),
        "claims": claims or {}, "waived": [], "state": state, "auto": ["draft"],
        "gate_cmd": None, "deadline": None, "gate": None, "draft": None,
        "landed": None, "history": [],
    }
    (bd / f"{gate_id}.json").write_text(
        _json248.dumps(st, ensure_ascii=False) + "\n", encoding="utf-8")


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=str(repo),
                          env=_ENV, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=False)


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.encode("utf-8"))


def _mk_repo(tmp_path: Path) -> tuple[Path, str]:
    """造一个带**一笔真提交**的假仓（提交只改 tools/dsh_panel.py），返回 (repo, sha)。

    用事故同款文件名（卡 244 与卡 247 都要改的那个）—— 同域重叠就是这次的事故现场。
    """
    repo = tmp_path / "repo248"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "nail@example.invalid")
    _git(repo, "config", "user.name", "nail")
    _git(repo, "config", "core.autocrlf", "false")
    _git(repo, "config", "commit.gpgsign", "false")
    _write(repo, "tools/dsh_panel.py", "PANEL = 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init for 248")
    sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
    return repo, sha


def _stamp_recorder(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """把 ⑨ 的盖章函数换成记录桩（**不真起子进程**），返回调用记录。"""
    calls: list[list[str]] = []
    monkeypatch.setattr(_landing, "_run_task_sub", lambda cmd: calls.append(cmd) or 0)
    return calls


def _claims_of(calls: list[list[str]], batch_id: str) -> list[str]:
    """从记录里抽出「推了谁的申请」（按 argv 元素判，不 join 成串）。"""
    return [c[c.index("claim") + 2] for c in calls
            if "claim" in c and batch_id in c]


def _landed_of(calls: list[list[str]], batch_id: str) -> list[list[str]]:
    return [c for c in calls if "landed" in c and batch_id in c]


# ================================================================ ① 卡模式：兄弟没申请 ⇒ 不代写

def test_card_gate_refuses_sibling_claim_when_sibling_has_no_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
) -> None:
    """★★ 事故原样回放（本卡核心）：`--card 244` 顺着 paths 相交匹配上卡 247 的批
    （成员只有 247、没开工、没申请）⇒ **不许替 247 写申请**（盖章函数 0 次调用），
    且点名 247、说出「同域/未开工」。旧码会推 247 的申请 ⇒ 旧码必红。"""
    bd = tmp_path / "batch"
    monkeypatch.setenv("TF_BATCH_DIR", str(bd))
    _mk_gate(bd, "B-248A", "collecting",
             [{"id": "247", "paths": ["tools/dsh_panel.py"]}])
    repo, sha = _mk_repo(tmp_path)
    monkeypatch.setattr(_landing, "ROOT", repo)
    calls = _stamp_recorder(monkeypatch)

    _landing._advance_card_gate("244", sha, "T-G999", ["tools/dsh_panel.py"])

    out = capsys.readouterr().out
    assert _claims_of(calls, "B-248A") == [], f"★ 不许代写 247 的申请：{calls!r}"
    assert _landed_of(calls, "B-248A") == [], f"★ 不许盖章：{calls!r}"
    assert "247" in out, out
    assert "同域" in out, out
    assert "未开工" in out, out
    assert "不许代写" in out, out


def test_card_gate_pushes_sibling_claim_when_sibling_has_own_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
) -> None:
    """①的反例：兄弟成员**自己交过**成功申请（claims 预置 success）⇒ 照旧推
    （既有行为一字不变）—— 证明①的判据真的在拦，不是永远为真的空判据。"""
    bd = tmp_path / "batch"
    monkeypatch.setenv("TF_BATCH_DIR", str(bd))
    _mk_gate(bd, "B-248B", "awaiting-commit",
             [{"id": "247", "paths": ["tools/dsh_panel.py"]}],
             claims={"247": "success"})
    repo, sha = _mk_repo(tmp_path)
    monkeypatch.setattr(_landing, "ROOT", repo)
    calls = _stamp_recorder(monkeypatch)

    _landing._advance_card_gate("244", sha, "T-G999", ["tools/dsh_panel.py"])

    out = capsys.readouterr().out
    assert _claims_of(calls, "B-248B") == ["247"], f"照旧推兄弟的申请：{calls!r}"
    assert len(_landed_of(calls, "B-248B")) == 1, f"need=1 齐了 ⇒ 照旧标 landed：{calls!r}"
    assert "不许代写" not in out, out


# ================================================================ ③ 卡模式 landed：全员申请核验

def test_card_gate_refuses_landed_when_member_lacks_own_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
) -> None:
    """★★ 卡 248 第 4a 条：两成员 paths **相同**、只有甲（301）有申请、乙（302）没有
    ⇒ 本卡的申请照推（那是 --card 点名要落的卡）、**landed 不许标**、**不给乙写申请**、
    点名乙并说出「同域/未开工」。旧码按产物交集就把整个批标 landed ⇒ 旧码必红。"""
    bd = tmp_path / "batch"
    monkeypatch.setenv("TF_BATCH_DIR", str(bd))
    _mk_gate(bd, "B-248C", "awaiting-commit",
             [{"id": "301", "paths": ["tools/dsh_panel.py"]},
              {"id": "302", "paths": ["tools/dsh_panel.py"]}],
             claims={"301": "success"})
    repo, sha = _mk_repo(tmp_path)
    monkeypatch.setattr(_landing, "ROOT", repo)
    calls = _stamp_recorder(monkeypatch)

    _landing._advance_card_gate("301", sha, "T-G999", ["tools/dsh_panel.py"])

    out = capsys.readouterr().out
    assert _claims_of(calls, "B-248C") == ["301"], f"只许推甲的申请：{calls!r}"
    assert _landed_of(calls, "B-248C") == [], f"★ 乙没申请 ⇒ 不许标 landed：{calls!r}"
    assert "不标 landed" in out, out
    assert "302" in out, out
    assert "未开工" in out, out


def test_card_gate_stamps_when_all_members_have_own_claims(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
) -> None:
    """③的反例（卡 248 第 4b 条）：两成员**都有**自己的申请且产物都在 ⇒ 照旧盖章
    （1 个申请 + 1 个 landed，既有行为一字不变）。"""
    bd = tmp_path / "batch"
    monkeypatch.setenv("TF_BATCH_DIR", str(bd))
    _mk_gate(bd, "B-248D", "awaiting-commit",
             [{"id": "301", "paths": ["tools/dsh_panel.py"]},
              {"id": "302", "paths": ["tools/dsh_panel.py"]}],
             claims={"301": "success", "302": "success"})
    repo, sha = _mk_repo(tmp_path)
    monkeypatch.setattr(_landing, "ROOT", repo)
    calls = _stamp_recorder(monkeypatch)

    _landing._advance_card_gate("301", sha, "T-G999", ["tools/dsh_panel.py"])

    out = capsys.readouterr().out
    assert _claims_of(calls, "B-248D") == ["301"], calls
    assert len(_landed_of(calls, "B-248D")) == 1, calls
    assert "不标 landed" not in out, out


# ================================================================ ⑤ 批模式：没集齐 ⇒ 不代写、不盖章

def test_batch_gate_refuses_when_member_lacks_own_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
) -> None:
    """★★ 卡 248 第 1/2 条落在批模式：栅栏**没集齐**（乙 302 没交申请）⇒
    **一个申请都不推**（不许代写）、不标 landed、点名乙。旧码逐成员代写 ⇒ 旧码必红。"""
    bd = tmp_path / "batch"
    monkeypatch.setenv("TF_BATCH_DIR", str(bd))
    _mk_gate(bd, "B-248E", "collecting",
             [{"id": "301", "paths": ["tools/dsh_panel.py"]},
              {"id": "302", "paths": ["tools/dsh_panel.py"]}],
             claims={"301": "success"})
    repo, sha = _mk_repo(tmp_path)
    monkeypatch.setattr(_landing, "ROOT", repo)
    calls = _stamp_recorder(monkeypatch)

    _landing._advance_batch_gate("B-248E", sha, "T-G999")

    out = capsys.readouterr().out
    assert calls == [], f"★ 没集齐 ⇒ 一个申请都不推：{calls!r}"
    assert "302" in out, out
    assert "未开工" in out, out
    assert "不盖章" in out, out


def test_batch_gate_stamps_when_all_members_have_own_claims(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
) -> None:
    """⑤的反例（卡 248 第 4b 条，批模式）：人人都有申请且产物都在 ⇒ 照旧盖章
    （2 个申请 + 1 个 landed）。"""
    bd = tmp_path / "batch"
    monkeypatch.setenv("TF_BATCH_DIR", str(bd))
    _mk_gate(bd, "B-248F", "awaiting-commit",
             [{"id": "301", "paths": ["tools/dsh_panel.py"]},
              {"id": "302", "paths": ["tools/dsh_panel.py"]}],
             claims={"301": "success", "302": "success"})
    repo, sha = _mk_repo(tmp_path)
    monkeypatch.setattr(_landing, "ROOT", repo)
    calls = _stamp_recorder(monkeypatch)

    _landing._advance_batch_gate("B-248F", sha, "T-G999")

    out = capsys.readouterr().out
    assert sorted(_claims_of(calls, "B-248F")) == ["301", "302"], calls
    assert len(_landed_of(calls, "B-248F")) == 1, calls
    assert "不盖章" not in out, out


# ================================================================ ⑥ 卡 238 判据不许降级

def test_batch_gate_refuses_when_artifacts_absent_even_if_gate_full(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
) -> None:
    """卡 248 第 4c 条：**人人都交了申请**、但成员 302 的产物不在这笔提交里 ⇒
    照旧拒盖章（卡 238 的判据不许删/降级；且**先验产物、后验申请** —— 报的是
    产物那条原话，不是申请那条）。"""
    bd = tmp_path / "batch"
    monkeypatch.setenv("TF_BATCH_DIR", str(bd))
    _mk_gate(bd, "B-248G", "awaiting-commit",
             [{"id": "301", "paths": ["tools/dsh_panel.py"]},
              {"id": "302", "paths": ["tools/other.py"]}],
             claims={"301": "success", "302": "success"})
    repo, sha = _mk_repo(tmp_path)                  # 这笔提交只改 tools/dsh_panel.py
    monkeypatch.setattr(_landing, "ROOT", repo)
    calls = _stamp_recorder(monkeypatch)

    _landing._advance_batch_gate("B-248G", sha, "T-G999")

    out = capsys.readouterr().out
    assert calls == [], f"★ 卡 238 判据照旧拦：{calls!r}"
    assert "302 的产物不在这笔提交里" in out, out
    assert "未开工" not in out, out


def test_batch_gate_artifacts_gate_runs_before_claims_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
) -> None:
    """次序钉：成员 302 **既没申请、产物也不在** ⇒ 报的是卡 238 的产物原话
    （产物判据在前、申请判据在后 —— 两道闸都在，谁先谁后不许漂）。"""
    bd = tmp_path / "batch"
    monkeypatch.setenv("TF_BATCH_DIR", str(bd))
    _mk_gate(bd, "B-248H", "collecting",
             [{"id": "301", "paths": ["tools/dsh_panel.py"]},
              {"id": "302", "paths": ["tools/other.py"]}],
             claims={"301": "success"})
    repo, sha = _mk_repo(tmp_path)
    monkeypatch.setattr(_landing, "ROOT", repo)
    calls = _stamp_recorder(monkeypatch)

    _landing._advance_batch_gate("B-248H", sha, "T-G999")

    out = capsys.readouterr().out
    assert calls == [], calls
    assert "302 的产物不在这笔提交里" in out, out


# ================================================================ 判据本体（直达单测）

def test_stamp_refusals_names_member_without_own_claim(
    capsys: pytest.CaptureFixture,
) -> None:
    """`_stamp_refusals` 直达：产物有交集、但成员自己没有成功申请 ⇒ 拒盖章清单
    里有它，打印点名（成员号 / paths / 相交的提交文件 / 未开工或未交申请）；
    把乙的申请预置成 success ⇒ 空清单（判据真的在读 claims，不是摆设）。"""
    members = [{"id": "302", "paths": ["tools/dsh_panel.py"]}]
    commit_files = ["tools/dsh_panel.py"]

    refused = _landing._stamp_refusals(members, commit_files, claims={})
    out1 = capsys.readouterr().out
    assert refused == ["302"], refused
    assert "302" in out1 and "未开工" in out1 and "不许代写" in out1, out1
    assert "paths=['tools/dsh_panel.py']" in out1, out1
    assert "tools/dsh_panel.py" in out1, out1      # 相交的提交文件也要点名

    refused2 = _landing._stamp_refusals(members, commit_files,
                                        claims={"302": "success"})
    capsys.readouterr()
    assert refused2 == [], refused2                # 反例：预置申请 ⇒ 放行


def test_stamp_refusals_without_claims_keeps_card238_behavior() -> None:
    """向后兼容：不传 claims（卡 238 的老调用形状）⇒ 行为与卡 238 一字不变
    （只验产物；传了 claims 才多验申请）。"""
    members = [{"id": "302", "paths": ["tools/dsh_panel.py"]}]
    assert _landing._stamp_refusals(members, ["tools/dsh_panel.py"]) == []
    assert _landing._stamp_refusals(members, ["tools/other.py"]) == ["302"]
