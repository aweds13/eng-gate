r"""写盘纪律（卡 A330 · `T-AG532`）：`tools/pool/lastgood.py` + 五处写盘接线的判据钉子。

为什么值当测：`.bak` 与「从 `.bak` 读」是**数据救命的最后一层**，但两处最容易写反 ——
①备份**新**的（等于没备份）；②把**坏**文件也备份（等于把 lastgood 顶掉）。
再加上「凭据账本不许从 `.bak` 复活」这条 **fail-closed** 纪律：写反了就是
「撤过的凭据自己回来了」。所以每条都打在真判据上，不测实现细节。

| 钉子 | 判什么 | 会红在哪 |
|---|---|---|
| ① 写完不留渣 | 新内容、无 `*.tmp` 残留、首写不造 `.bak` | 若 tmp 没被 `os.replace` 消掉 |
| ② `.bak` 落后一次写 | 写 A 再写 B ⇒ `.bak` 是 **A** | 若备份的是新内容 |
| ③ 坏文件不许当 lastgood | target 坏 ⇒ 写新值后 `.bak` **不存在** | 若去掉 validate |
| ④ 从 `.bak` 恢复 | target 坏、`.bak` 好 ⇒ `(好内容, True)` 且 log 一次 | 若默默返回空 / 抛错 |
| ⑤ 两边都坏要说清 | 抛出且消息含「`.bak` 也坏了」 | 若把 `.bak` 的实情吞掉 |
| ⑥ 凭据 fail-closed | `read_strict` 永不看 `.bak` | 若做成兜底 |
| ⑦ 登记冷启动能救 | 坏文件 + 好 `.bak` ⇒ 读回、stderr 留痕、坏文件一字不动 | 若直接抛 / 不记日志 |
| ⑧ 登记两边都坏照抛 | 仍 `RegistryError`，消息含「`.bak` 也坏了」 | 若静默清空 |
| ⑨ 账本不许复活 | 正式文件坏、`.bak` 好 ⇒ `load_ledger` **必须抛** | 若从 `.bak` 读回旧凭据 |
| ⑩ 队列快照往返 | `_save` 两次 ⇒ 文件新、`.bak` 旧、`load()` 读到新的 | 若漏了 `.bak` |
| ⑪ target 缺失也能救 | 正式文件**不存在**、`.bak` 好 ⇒ 恢复 | 若「target 存在才读 `.bak`」 |

★ 导入口径照既有测试：把 `tools/` 挂上 `sys.path` 再 `import`；全程 `tmp_path`，不碰真仓。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import pool_accounts as pa  # noqa: E402 —— tools/ 已在 sys.path 上
from pool import lastgood, queue, registry  # noqa: E402

GOOD_A = [{"task": "T-A", "tree": ".wt/a"}]
GOOD_B = [{"task": "T-B", "tree": ".wt/b"}]
CORRUPT = "{坏掉的 JSON"
#: 「`.bak` 也坏了」这个短语 —— 两边都坏时必须出现在消息里（光有路径不算，路径本来就带 `.bak`）。
BAK_ALSO_BAD = ".bak 也坏了"

#: 最小合法账本（一个号、空批准集 = 「不许派活」、凭据 kind=none）—— 判据见 `_check_account`。
LEDGER_MIN = """
[[account]]
id = "codearts-1"
label = "备用号 codearts"
platform = "codearts"
state = "active"
added_at = "2026-09-30"
approved_models = []

[account.credential]
kind = "none"
"""


def _need_list(text: str) -> None:
    """本文件的判据替身：能解析且顶层是数组（与 `registry._validate_registry_text` 同口径）。

    ★ 坏 JSON 归一成 `ValueError`（单参可复刻）—— 兜底失败时才拼得出「`.bak` 也坏了」。
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 解析失败：{exc}") from exc
    if not isinstance(data, list):
        raise ValueError("顶层应是数组")


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------- write_atomic


def test_write_atomic_writes_and_leaves_no_tmp(tmp_path):
    target = tmp_path / "reg.json"
    body = json.dumps(GOOD_A, ensure_ascii=False) + "\n"
    lastgood.write_atomic(target, body, validate=_need_list)
    assert target.read_text(encoding="utf-8") == body
    assert list(tmp_path.glob("*.tmp")) == []  # 临时文件必须被 os.replace 消掉
    assert not lastgood.backup_path(target).exists()  # 首次写没有「旧的」可备份


def test_write_atomic_keeps_previous_good_as_bak(tmp_path):
    target = tmp_path / "reg.json"
    body_a = json.dumps(GOOD_A, ensure_ascii=False) + "\n"
    body_b = json.dumps(GOOD_B, ensure_ascii=False) + "\n"
    lastgood.write_atomic(target, body_a, validate=_need_list)
    lastgood.write_atomic(target, body_b, validate=_need_list)
    assert target.read_text(encoding="utf-8") == body_b
    bak = lastgood.backup_path(target)
    assert bak.exists()
    assert bak.read_text(encoding="utf-8") == body_a  # ★ .bak 落后一次写：是 A 不是 B
    assert list(tmp_path.glob("*.tmp")) == []


def test_write_atomic_does_not_bak_a_corrupt_file(tmp_path):
    target = _write(tmp_path / "reg.json", CORRUPT)
    body_b = json.dumps(GOOD_B, ensure_ascii=False) + "\n"
    lastgood.write_atomic(target, body_b, validate=_need_list)
    assert target.read_text(encoding="utf-8") == body_b
    # ★ 坏字节不许顶成 lastgood：坏了就等于「没有上一份好的」，宁可不造 .bak
    assert not lastgood.backup_path(target).exists()


# ------------------------------------------------------------- read_with_fallback


def test_read_with_fallback_recovers_from_bak(tmp_path):
    target = tmp_path / "reg.json"
    body_a = json.dumps(GOOD_A, ensure_ascii=False) + "\n"
    body_b = json.dumps(GOOD_B, ensure_ascii=False) + "\n"
    lastgood.write_atomic(target, body_a, validate=_need_list)
    lastgood.write_atomic(target, body_b, validate=_need_list)
    target.write_text(CORRUPT, encoding="utf-8")  # 模拟「写到一半 / 被人手改坏」

    logs: list[str] = []
    text, recovered = lastgood.read_with_fallback(target, validate=_need_list, log=logs.append)
    assert (text, recovered) == (body_a, True)
    assert len(logs) == 1  # ★ 恢复必须留痕，且只留一次
    assert "从 .bak 恢复" in logs[0]
    assert str(target) in logs[0]


def test_read_with_fallback_recovers_when_target_is_missing(tmp_path):
    """target **不存在**、`.bak` 好 ⇒ 也要救得回来（不是「存在才看 `.bak`」）。"""
    target = tmp_path / "reg.json"
    body_a = json.dumps(GOOD_A, ensure_ascii=False) + "\n"
    lastgood.write_atomic(target, body_a, validate=_need_list)
    lastgood.write_atomic(target, json.dumps(GOOD_B) + "\n", validate=_need_list)
    target.unlink()  # 只剩 .bak

    logs: list[str] = []
    text, recovered = lastgood.read_with_fallback(target, validate=_need_list, log=logs.append)
    assert (text, recovered) == (body_a, True)
    assert len(logs) == 1


def test_read_with_fallback_raises_when_both_bad(tmp_path):
    target = _write(tmp_path / "reg.json", CORRUPT)
    lastgood.backup_path(target).write_text(CORRUPT, encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        lastgood.read_with_fallback(target, validate=_need_list, log=lambda _m: None)
    assert BAK_ALSO_BAD in str(excinfo.value)  # ★ 两边都坏必须说清，不许只报第一条


def test_read_strict_never_reads_bak(tmp_path):
    target = _write(tmp_path / "accounts.toml", "{不是合法 TOML")
    lastgood.backup_path(target).write_text(LEDGER_MIN, encoding="utf-8")
    with pytest.raises(ValueError):  # ★ 有好的 .bak 也不许救（TOMLDecodeError 是 ValueError）
        lastgood.read_strict(target, validate=pa._validate_ledger_toml)
    ok = _write(tmp_path / "ok.toml", LEDGER_MIN)
    assert lastgood.read_strict(ok, validate=pa._validate_ledger_toml) == LEDGER_MIN


# -------------------------------------------------------------------- registry


@pytest.fixture()
def reg_path(tmp_path, monkeypatch):
    p = tmp_path / "pool-registry.json"
    monkeypatch.setenv("TF_POOL_REGISTRY", str(p))
    return p


def test_registry_load_survives_a_corrupt_file(reg_path, capsys):
    registry.save(GOOD_A)
    registry.save(GOOD_B)  # ⇒ .bak 是 A
    reg_path.write_text(CORRUPT, encoding="utf-8")
    rows = registry.load()  # ★ 冷启动读到坏文件：能救就不许停摆
    assert rows == GOOD_A
    assert "从 .bak 恢复" in capsys.readouterr().err  # ★ 恢复要留痕（stderr）
    # 坏文件本身一个字都没动（既有语义：不清空、不自作主张删）
    assert reg_path.read_text(encoding="utf-8") == CORRUPT


def test_registry_load_still_raises_when_nothing_good(reg_path):
    reg_path.write_text(CORRUPT, encoding="utf-8")
    lastgood.backup_path(reg_path).write_text(CORRUPT, encoding="utf-8")
    with pytest.raises(registry.RegistryError) as excinfo:
        registry.load()
    message = str(excinfo.value)
    assert "登记文件坏了" in message
    assert BAK_ALSO_BAD in message  # ★ 「.bak 也坏了」这句不许丢


# --------------------------------------------------------------- pool_accounts


def test_pool_accounts_ledger_does_not_resurrect_from_bak(tmp_path, monkeypatch):
    monkeypatch.setattr(pa, "TOOL_ROOT", tmp_path)  # 不去读宿主机上的 infra/pool
    target = _write(tmp_path / "infra" / "pool" / "accounts.toml", LEDGER_MIN)
    lastgood.backup_path(target).write_text(LEDGER_MIN, encoding="utf-8")
    target.write_text("{不是合法 TOML", encoding="utf-8")
    with pytest.raises(pa.LedgerError):  # ★ 凭据不许从 .bak 复活 ⇒ fail-closed
        pa.load_ledger(target, platforms={"codearts": {}})
    # 正式文件修好就正常（fail-closed 不等于永久坏）
    _write(target, LEDGER_MIN)
    data = pa.load_ledger(target, platforms={"codearts": {}})
    assert [a["id"] for a in data["account"]] == ["codearts-1"]


# ----------------------------------------------------------------------- queue


def test_queue_save_and_load_roundtrip_with_bak(tmp_path, monkeypatch):
    p = tmp_path / "merge-queue.json"
    monkeypatch.setenv("TF_MERGE_QUEUE", str(p))
    state_a = {"head": None, "waiting": [{"task": "T-A", "tree": ".wt/a"}]}
    state_b = {"head": None, "waiting": [{"task": "T-B", "tree": ".wt/b"}]}
    queue._save(state_a)
    queue._save(state_b)
    assert queue.load()["waiting"] == [{"task": "T-B", "tree": ".wt/b"}]
    bak = lastgood.backup_path(p)
    assert bak.exists()
    assert json.loads(bak.read_text(encoding="utf-8"))["waiting"] == [
        {"task": "T-A", "tree": ".wt/a"}]
    assert list(tmp_path.glob("*.tmp")) == []
