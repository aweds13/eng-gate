r"""Trae 道进账（`tools/pool/trae_dispatch.py`，卡 218 · T-G331）的测试。

为什么值当测：这条道从前是**零接线** —— 它的日志叫 `trae-<卡>.jsonl`，而整仓的账
（`pool.registry` 的租约、`pool.jobs` 的三态判据、卡 215 的 `wb_watch`）认的是
`gates/diag/wb-<卡>.jsonl` + `wb-<卡>.verdict.txt`。转写错了，卡 215 就**永远等不到收工信号**
（"建了却零接线"换了个地方再犯）。

| 判据 | 判什么 |
|---|---|
| ① 占树 + 开场 | `start` 真的 `registry.reserve` 了租约，工人日志有 `parse_events` 认得的 `init` |
| ② 不重占 | 本卡已有活租约 ⇒ `start` 沿用，不再 `reserve`（否则撞上 `tree_guard` 判自己占自己） |
| ③ 守卫照咬 | 树被**别人**占了 ⇒ `start` 退 2、**不写日志** |
| ④ 日志不许覆盖 | 目标日志已存在 ⇒ 退 2（与 `pool.guards.log_guard` 同口径） |
| ⑤ 判决被现有账认出来 | `finish` 落的判决 `scan_jobs` 判「已判决」、日志 `summary["final"]` 非空 |
| ⑥ 只读 | `status` 一个字节都不写 |

★ 一律用 `TF_POOL_REGISTRY` + `--root` 指临时目录 —— **不往真的 `gates/diag/` 里写**。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from pool import jobs, registry, trae_dispatch  # noqa: E402 —— tools/ 已在 sys.path 上

CARD = "218"


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """登记文件指到临时目录；门禁锁一律当"空着"；根 = 临时根。返回那个根。"""
    monkeypatch.setenv("TF_POOL_REGISTRY", str(tmp_path / "reg.json"))
    monkeypatch.setattr(registry, "read_lock_body", lambda *a, **k: "")
    monkeypatch.setenv("TF_WINDOW_ID", "test-window")
    return tmp_path / "root"


def _diag(root: Path) -> Path:
    return jobs.diag_dir(root)


def _lines(path: Path) -> list[str]:
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ================================================================ ① start：占树 + 开场


def test_start_reserves_and_writes_init(env: Path) -> None:
    code, text = trae_dispatch.start(card=CARD, tree=".wt/traecli", files=[".trae/mcp.json"],
                                     task="T-G331", pool="trae", model="M", root=env)
    assert code == 0, text
    rows = registry.load()
    assert [r["card"] for r in rows] == [CARD]
    assert rows[0]["tree"] == ".wt/traecli" and rows[0]["files"] == [".trae/mcp.json"]
    assert rows[0]["owner"] == "test-window" and rows[0]["pool"] == "trae"
    log = _diag(env) / f"wb-{CARD}.jsonl"
    timeline, summary = jobs.parse_events(_lines(log))
    assert summary["models"] == ["M"]
    assert any("开  init" in ln for ln in timeline), timeline


# ================================================================ ② 不重占


def test_start_reuses_own_live_lease(env: Path) -> None:
    trae_dispatch.start(card=CARD, tree=".wt/traecli", files=[".trae/mcp.json"], root=env)
    code, text = trae_dispatch.start(
        card=CARD, tree=".wt/traecli", files=[".trae/mcp.json"], root=env,
        log=_diag(env) / f"wb-{CARD}.r2.jsonl")
    assert code == 0, text
    assert "沿用已有活租约" in text
    assert len(registry.load()) == 1          # 没有第二次 reserve（否则会自己占自己）


# ================================================================ ③ 守卫照咬


def test_start_refuses_when_tree_held_by_another_card(env: Path) -> None:
    registry.reserve("999", tree=".wt/traecli", files=["other.py"], pool="codebuddy")
    code, text = trae_dispatch.start(card=CARD, tree=".wt/traecli", files=[".trae/mcp.json"],
                                     root=env)
    assert code == 2
    assert "树被占" in text
    assert not (_diag(env) / f"wb-{CARD}.jsonl").exists()   # 被咬 ⇒ 一个字不写
    assert [r["card"] for r in registry.load()] == ["999"]


# ================================================================ ④ 日志不许覆盖


def test_start_refuses_when_log_exists(env: Path) -> None:
    log = _diag(env) / f"wb-{CARD}.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text('{"type":"system","subtype":"init"}\n', encoding="utf-8")
    code, text = trae_dispatch.start(card=CARD, tree=".wt/traecli", files=[".trae/mcp.json"],
                                     root=env)
    assert code == 2
    assert "日志不许覆盖" in text


# ================================================================ ⑤ finish：判决被现有账认出来


def test_finish_writes_verdict_scan_jobs_and_final(env: Path) -> None:
    trae_dispatch.start(card=CARD, tree=".wt/traecli", files=[".trae/mcp.json"],
                        task="T-G331", pool="trae", model="M", root=env)
    answer = env / "answer.md"
    answer.write_text("PORT", encoding="utf-8")
    code, text = trae_dispatch.finish(card=CARD, log=None, exit_code=0, root=env,
                                      answer_file=answer, session_id="s-1",
                                      disconnects=1, reconnects=1, release=True)
    assert code == 0, text
    log = _diag(env) / f"wb-{CARD}.jsonl"
    verdict = _diag(env) / f"wb-{CARD}.verdict.txt"
    assert verdict.exists()
    body = verdict.read_text(encoding="utf-8")
    assert "正常收工" in body and "退出码=0" in body and "断线 1 次" in body
    _timeline, summary = jobs.parse_events(_lines(log))
    assert summary["final"] is not None                      # ★ wb_dispatch --status 看的就是它
    assert any(row["log"] == log.name and row["state"] == "已判决"
               for row in jobs.scan_jobs(_diag(env)))
    assert registry.load() == []                             # --release 放掉了


def test_finish_without_start_is_refused(env: Path) -> None:
    code, text = trae_dispatch.finish(card=CARD, log=None, exit_code=0, root=env)
    assert code == 2
    assert "先跑 start" in text


# ================================================================ ⑥ 只读


def test_status_writes_nothing(env: Path) -> None:
    trae_dispatch.start(card=CARD, tree=".wt/traecli", files=[".trae/mcp.json"], root=env)
    reg = Path(os.environ["TF_POOL_REGISTRY"])
    before = reg.read_bytes()
    code, text = trae_dispatch.status(card=CARD, root=env)
    assert code == 0, text
    assert "活租约：1 条" in text and f"wb-{CARD}.jsonl" in text
    assert reg.read_bytes() == before
