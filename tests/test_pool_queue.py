r"""钉 `tools/pool/queue.py`（合并队列；卡 E5 · `T-AG447`）。

## 为什么有它

落地链 ④–⑦（拿锁 → 门禁 → 封存 → 提交 → ff 合流）是**单写者**段：两笔同时进来，
后到的那笔会在 `git merge --ff-only` 那一刻发现主树已前进 ⇒ rebase / 重跑 / 白烧门禁。
队列要保证三件事（都是卡 E5 的判据）：

1. **单写者**：同一时刻只有队首在 ④–⑦；后来者拿到位次后**继续做自己的 ①②③**（不空等）；
2. **投机预检不复用**：排队期间主树前进过 ⇒ 变队首时 `respec_required()` 必须为真（重跑 ③″）；
3. **出队**：队首干完 `advance()`；ff 失败（rebase 一次仍失败）`drop()` 并打印「需人工」。

## 怎么跑（不碰真仓库）

每个用例把状态文件指到 `tmp_path`（`TF_MERGE_QUEUE`），**不读也不写**真仓库的
`gates/diag/merge-queue.json`。
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_queue():
    spec = importlib.util.spec_from_file_location(
        "pool_queue_under_test", ROOT / "tools" / "pool" / "queue.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def q(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """把状态文件指到 tmp（`TF_MERGE_QUEUE`），并让轮询间隔足够小（测试要快）。"""
    monkeypatch.setenv("TF_MERGE_QUEUE", str(tmp_path / "merge-queue.json"))
    monkeypatch.setenv("TF_QUEUE_POLL", "0.01")
    return _load_queue()


def _raw() -> dict:
    p = Path(os.environ["TF_MERGE_QUEUE"])
    return json.loads(p.read_text(encoding="utf-8"))


def test_enqueue_first_is_head(q) -> None:
    """第一笔入队 ⇒ 位置 1（队首），状态文件落在 `gates/diag/merge-queue.json` 那个位置。"""
    pos = q.enqueue(".wt/a", "T-A", base="sha0")
    assert pos == {"position": 1, "head": "T-A", "total": 1}, pos
    st = _raw()
    assert st["head"]["task"] == "T-A" and st["waiting"] == [], st
    assert st["head"]["base"] == "sha0", st


def test_second_gets_a_slot_and_is_not_head(q) -> None:
    """★ 判据 2（单写者）：第二笔拿到 `queued` 位次，**不是**队首（它继续做自己的 ①②③）。"""
    q.enqueue(".wt/a", "T-A", base="sha0")
    pos = q.enqueue(".wt/b", "T-B", base="sha0")
    assert pos["position"] == 2, pos
    assert pos["head"] == "T-A", pos
    assert q.is_head("T-A") and not q.is_head("T-B")
    assert q.head()["task"] == "T-A"


def test_enqueue_is_idempotent(q) -> None:
    """同一笔重复入队 ⇒ 保持原位（重跑落地不许把自己排到队尾、也不许出现两条）。"""
    q.enqueue(".wt/a", "T-A")
    q.enqueue(".wt/b", "T-B")
    again = q.enqueue(".wt/b", "T-B")
    assert again["position"] == 2, again
    assert again["total"] == 2, again


def test_advance_hands_over_to_next(q) -> None:
    """★ 判据 3：队首 `advance()` 出队 ⇒ 下一个自动变队首；没人了 ⇒ None。"""
    q.enqueue(".wt/a", "T-A")
    q.enqueue(".wt/b", "T-B")
    nxt = q.advance()
    assert nxt["task"] == "T-B", nxt
    assert q.is_head("T-B")
    assert q.advance() is None, "队列空了还给出队首？"
    assert q.head() is None


def test_drop_head_promotes_next(q) -> None:
    """★ 判据 4：ff 失败要出队（队首被摘 ⇒ 下一个顶上；后面的人不被堵死）。"""
    q.enqueue(".wt/a", "T-A")
    q.enqueue(".wt/b", "T-B")
    assert q.drop("T-A") is True
    assert q.is_head("T-B")
    assert q.drop("T-NOSUCH") is False, "摘一笔不在队列里的要如实返回 False"


def test_respec_required_when_base_moves(q) -> None:
    """★ 判据 3（核心）：排队期间**主树前进** ⇒ 投机预检作废（基点一变就要重跑③″）。"""
    q.enqueue(".wt/a", "T-A", base="sha0")
    q.enqueue(".wt/b", "T-B", base="sha0")
    assert q.respec_required("T-B", base="sha0") is False, "基点没变 ⇒ 不该逼它重跑"
    assert q.respec_required("T-B", base="sha1") is True, "基点变了 ⇒ 投机结果不许复用"
    assert q.respec_required("T-NOSUCH", base="sha1") is False, "不在队列里 ⇒ 没有投机可谈"


def test_wait_turn_blocks_until_head_and_times_out(q, capsys) -> None:
    """★ 判据 2：队首在跑时，第二笔 `wait_turn` **等不到**（超时 False）；队首走后立刻轮到。"""
    q.enqueue(".wt/a", "T-A")
    q.enqueue(".wt/b", "T-B")
    assert q.wait_turn("T-B", timeout=0.2, say=print) is False
    out = capsys.readouterr().out
    assert "排队中" in out and "第 2 位" in out, out
    q.advance()                                    # 队首干完
    assert q.wait_turn("T-B", timeout=1.0, say=print) is True


def test_state_file_is_gitignored_location(q, monkeypatch: pytest.MonkeyPatch) -> None:
    """状态落在 `gates/diag/`（gitignore 的运行时目录）—— 不许进提交、不许被复核比对。"""
    assert Path(os.environ["TF_MERGE_QUEUE"]).name == "merge-queue.json"
    monkeypatch.delenv("TF_MERGE_QUEUE")           # 看**默认**落点（不覆写时）
    default = q.state_path()
    assert default.as_posix().endswith("gates/diag/merge-queue.json"), default
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "gates/diag/" in ignore, "gates/diag 必须仍在 .gitignore 里"


# ------------------------------------------------ 卡 E5：同文件卡**不许同批**
#
# 口径与 `tools/pool/plan.py::files_intersect` 同一条：`files` 是冲突域，同批两卡相交 = 冲突。
# 队列里记下这一笔的域；相交的那几笔必须**点名**出来，并落在相邻的两批（串行），不许并排。

def test_enqueue_records_the_conflict_domain(q) -> None:
    """`files` 落进状态文件（POSIX 化）：没有它，「同文件卡不许同批」无从判起。"""
    q.enqueue(".wt/a", "T-A", files=["tools\\pool\\landing.py", "./tools/pool/queue.py"])
    assert _raw()["head"]["files"] == ["tools/pool/landing.py", "tools/pool/queue.py"], _raw()


def test_same_file_conflicts_are_named(q) -> None:
    """★ 判据：与我在**同一个文件**上的那几笔必须被点名（不许静默并排）。"""
    q.enqueue(".wt/a", "T-A", files=["tools/pool/landing.py"])
    q.enqueue(".wt/b", "T-B", files=["tools/pool/landing.py", "tools/pool/queue.py"])
    q.enqueue(".wt/c", "T-C", files=["./tools/pool/queue.py"])

    assert q.same_file_conflicts("T-A") == ["T-B"], q.same_file_conflicts("T-A")
    assert q.same_file_conflicts("T-B") == ["T-A", "T-C"], q.same_file_conflicts("T-B")
    assert q.same_file_conflicts("T-C") == ["T-B"], q.same_file_conflicts("T-C")
    assert q.same_file_conflicts("T-NOSUCH") == [], "不在队列里 ⇒ 没有冲突可谈"


def test_same_file_cards_never_share_a_batch(q) -> None:
    """★ 判据（核心）：同文件卡**不许同批** —— `batches()` 里必须分成两批；域不相交的才可并排。"""
    q.enqueue(".wt/a", "T-A", files=["tools/pool/landing.py"])
    q.enqueue(".wt/b", "T-B", files=["tools/pool/landing.py"])
    q.enqueue(".wt/c", "T-C", files=["docs/x.md"])

    bs = q.batches()
    assert len(bs) == 2, f"同文件卡被并进同一批了：{bs}"
    where = {t: i for i, batch in enumerate(bs) for t in batch}
    assert where["T-A"] != where["T-B"], bs
    assert where["T-C"] == where["T-B"], f"域不相交的不该被挤到第三批：{bs}"


def test_no_files_recorded_means_no_conflict_claim(q) -> None:
    """没记 `files` ⇒ 空列表（「不知道」不等于「不冲突」，不许瞎报警）。"""
    q.enqueue(".wt/a", "T-A")
    q.enqueue(".wt/b", "T-B")
    assert q.same_file_conflicts("T-A") == [], "没记域却报了冲突"
    assert q.batches() == [["T-A", "T-B"]], q.batches()
