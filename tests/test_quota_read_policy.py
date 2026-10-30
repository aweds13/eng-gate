"""读额度要有读取纪律（卡 A333 · magpie F25）—— 八条钉子。

| # | 钉子 | 咬住什么 |
|---|------|----------|
| ① | `read_policy` 三值 | 首次等、过期重读、其余用缓存 —— 只回这三个字符串 |
| ② | 两常量照 magpie | `FIRST_WAIT_S = 3.0`、`REREAD_AFTER_S = 60.0`<br>（routing.go:191 / :589） |
| ③ | `REFRESH_GAP_S` 沿用 | 30 秒 = 手动刷新抑制，**不是**后台重读阈值<br>不许重定义或写成倍数 |
| ④ | 时钟倒流按缓存 | `now - last_read_at < 0` ⇒ `use_cached`，但**不是**永久缓存 |
| ⑤ | `mark_stale` 只作废一条 | 删记录 + 既有 refresh 文件里留 `stale`<br>别的卡/模型不受牵连 |
| ⑥ | `mark_stale` 原子且不新增文件 | `tmp` + `os.replace`，无 `.tmp` 残留；文件清单不多一个 |
| ⑦ | `merge_latest` 晚到不盖新的 | 新的才替换；旧的保留 + stderr 说一行<br>缺 `read_seq` 不替换 |
| ⑧ | 反向：`status()` 零网络 | monkeypatch 替 `_get_json` / `probe_account` 计数，断言 **0** |

★ 全部 `now` 注入、`tmp_path` 当 root —— 一条真实钟表都不碰（判据只认注入值）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import pool_accounts as pa  # noqa: E402 —— tools/ 已在 sys.path 上
import pool_quota  # noqa: E402 —— 同上

NOW = "2026-10-12T23:28:00+08:00"
#: 一个**晚于 `NOW`** 的重置时刻 —— `status()` 才会判「限流中」（早于 now 就是「已过期」）。
RESET_LATER = "2026-10-13 06:00:00 UTC+8"


def _quota_source() -> str:
    return (ROOT / "tools" / "pool_quota.py").read_text(encoding="utf-8")


def _quota_code() -> str:
    """去掉整行注释后的源码 —— 注释里可以拿「坏写法」当反例讲，代码里不许真那么写。"""
    lines = _quota_source().splitlines()
    return "\n".join(line for line in lines if not line.lstrip().startswith("#"))


# ---------------------------------------------------------------- ① 三值


def test_read_policy_returns_three_values():
    """★ 钉子①：只许这三个返回值，四个分支一个都不能少。"""
    assert pool_quota.read_policy(first=True, last_read_at=None, now=0.0) == "wait"
    assert pool_quota.read_policy(first=False, last_read_at=None, now=0.0) == "reread"
    assert pool_quota.read_policy(first=False, last_read_at=100.0, now=130.0) == "use_cached"
    assert pool_quota.read_policy(first=False, last_read_at=100.0, now=200.0) == "reread"
    # 首次但已有读数 ⇒ 不 wait（wait 只给「第一次、手上什么都没有」）
    assert pool_quota.read_policy(first=True, last_read_at=100.0, now=130.0) == "use_cached"
    # 恰好到阈值就算旧（`>=`，不是 `>`）
    edge = 100.0 + pool_quota.REREAD_AFTER_S
    assert pool_quota.read_policy(first=False, last_read_at=100.0, now=edge) == "reread"
    assert pool_quota.read_policy(first=False, last_read_at=100.0, now=edge - 0.001) == "use_cached"


# ---------------------------------------------------------------- ② 两常量


def test_read_policy_constants_match_magpie():
    """★ 钉子②：`3s` / `60s` 照 magpie —— 且必须是**字面量**，不许由别的常量推出来。"""
    assert pool_quota.FIRST_WAIT_S == 3.0
    assert pool_quota.REREAD_AFTER_S == 60.0
    assert isinstance(pool_quota.FIRST_WAIT_S, float)
    assert isinstance(pool_quota.REREAD_AFTER_S, float)
    src = _quota_source()
    assert src.count("FIRST_WAIT_S = 3.0") == 1
    assert src.count("REREAD_AFTER_S = 60.0") == 1


# ---------------------------------------------------------------- ③ 两套语义


def test_refresh_gap_is_kept_not_redefined():
    """★ 钉子③：30 秒抑制（用户手动刷新）与 60 秒重读阈值（后台）是两套语义。

    混用会重演 magpie `#1295` —— 所以 `REFRESH_GAP_S` 只许有一处定义、值 30，
    `REREAD_AFTER_S` 不许写成它的倍数（写成倍数就把两套语义焊死了）。
    """
    assert pool_quota.REFRESH_GAP_S == 30
    src = _quota_source()
    assert src.count("REFRESH_GAP_S = 30") == 1, "REFRESH_GAP_S 被重定义或改值了"
    assert "REFRESH_GAP_S *" not in _quota_code(), "REREAD_AFTER_S 不许是 REFRESH_GAP_S 的倍数"
    # 注释必须把两套语义说清楚，且两个名字都点名
    comment = "\n".join(line for line in src.splitlines() if line.startswith("#"))
    assert "REFRESH_GAP_S" in comment and "REREAD_AFTER_S" in comment
    assert "手动" in comment and "后台" in comment


# ---------------------------------------------------------------- ④ 时钟倒流


def test_read_policy_clock_backwards_uses_cache():
    """★ 钉子④：倒流按缓存 —— 不当 reread（会打穿速率限制），也不当永久缓存。"""
    assert pool_quota.read_policy(first=False, last_read_at=200.0, now=100.0) == "use_cached"
    assert pool_quota.read_policy(first=True, last_read_at=200.0, now=100.0) == "use_cached"
    # 倒流只影响这一次：时间恢复正常之后照样会 reread
    assert pool_quota.read_policy(first=False, last_read_at=200.0, now=201.0) == "use_cached"
    assert pool_quota.read_policy(first=False, last_read_at=200.0, now=300.0) == "reread"


# ---------------------------------------------------------------- ⑤ 作废一条


def test_mark_stale_drops_one_record_and_leaves_trace(tmp_path):
    """★ 钉子⑤：只作废 `cards[card][model]` 这一条，删完必须回 `None`；留痕落既有 refresh 文件。"""
    for card, model in (("A1", "m-one"), ("A1", "m-two"), ("A2", "m-one")):
        pool_quota.record(
            card=card,
            model=model,
            pool="p",
            kind="quota",
            reset_raw="2026-10-12 16:52:45 UTC+8",
            root=tmp_path,
        )
    assert pool_quota.read_record("A1", "m-one", root=tmp_path) is not None

    pool_quota.mark_stale("A1", "m-one", now=NOW, root=tmp_path)

    assert pool_quota.read_record("A1", "m-one", root=tmp_path) is None
    # 同卡的别的模型、别的卡的同名模型都不许被牵连
    assert pool_quota.read_record("A1", "m-two", root=tmp_path) is not None
    assert pool_quota.read_record("A2", "m-one", root=tmp_path) is not None
    # 空掉的卡目录也收掉（不留 `"A1": {}` 这种残渣）
    data = json.loads((tmp_path / pool_quota.STATE_REL).read_text(encoding="utf-8"))
    assert "A1" in data["cards"] and "m-two" in data["cards"]["A1"]

    # 留痕：既有 refresh 文件、既有 key 命名空间、值是 `{"stale": <iso>}`
    stamps = json.loads((tmp_path / pool_quota.REFRESH_REL).read_text(encoding="utf-8"))
    key = pool_quota.refresh_key("A1", "m-one")
    assert isinstance(stamps[key], dict) and "stale" in stamps[key]
    assert stamps[key]["stale"].startswith("2026-10-12T23:28:00")
    # `refreshed_within` 读不懂这个值 ⇒ 按既有口径「立刻可问」（作废之后不许留着抑制）
    assert pool_quota.refreshed_within(key, now=NOW, root=tmp_path) is None


# ---------------------------------------------------------------- ⑥ 原子 / 不新增文件


def test_mark_stale_is_atomic_and_adds_no_file(tmp_path):
    """★ 钉子⑥：`tmp` + `os.replace`，不留 `.tmp` 残留；不新增第三种文件。"""
    pool_quota.record(
        card="A1", model="m", pool="p", kind="quota", reset_raw="2026-10-12 16:52:45 UTC+8",
        root=tmp_path,
    )
    before = {p.name for p in tmp_path.rglob("*") if p.is_file()}
    pool_quota.mark_stale("A1", "m", now=NOW, root=tmp_path)
    after = {p.name for p in tmp_path.rglob("*") if p.is_file()}

    assert after - before == {"quota-refresh.json"}
    assert [p.name for p in tmp_path.rglob("*.tmp")] == []
    # 没有那条记录时也不许炸、不许凭空造 state 文件
    empty = tmp_path / "empty"
    empty.mkdir()
    pool_quota.mark_stale("no", "such", now=NOW, root=empty)
    assert not (empty / pool_quota.STATE_REL).exists()


# ---------------------------------------------------------------- ⑦ 晚到不盖新的


def test_merge_latest_drops_late_reading_with_a_word_on_stderr(capsys):
    """★ 钉子⑦：`got.read_seq >= kept.read_seq` 才替换；旧的保留 + stderr 说一行。

    两边 `read_seq` 任一缺失都按「`got` 无序号 ⇒ 不替换」处理 —— 缺证据不许改事实。
    """
    kept = {"amount": 12, "read_seq": 5, "at": "kept"}
    newer = {"amount": 30, "read_seq": 6, "at": "newer"}
    same = {"amount": 30, "read_seq": 5, "at": "same"}
    older = {"amount": 99, "read_seq": 4, "at": "older"}

    got = pool_quota.merge_latest(kept, newer, 7)
    assert got["at"] == "newer" and got["amount"] == 30
    assert got["read_seq"] == 7, "read_seq 取 got 与本次 seq 的较大者（只能往上抬）"

    assert pool_quota.merge_latest(kept, same, 5)["at"] == "same"
    assert "晚到" not in capsys.readouterr().err

    assert pool_quota.merge_latest(kept, older, 9) is kept, "旧的必须原样保留（不是拷贝）"
    err = capsys.readouterr().err
    assert "晚到的读数被丢弃" in err

    # 任一侧缺 read_seq ⇒ 不替换，而且要说出来
    assert pool_quota.merge_latest(kept, {"amount": 1}, 9) is kept
    assert "晚到的读数被丢弃" in capsys.readouterr().err
    assert pool_quota.merge_latest({"amount": 1}, newer, 9).get("at") is None
    assert "晚到的读数被丢弃" in capsys.readouterr().err


# ---------------------------------------------------------------- ⑧ 反向钉子


def test_reverse_status_never_touches_network(tmp_path, monkeypatch):
    """★ 钉子⑧（反向）：`status()` 零网络零等待 —— 谁顺手让它「去探一下」这条就红。

    口径照卡规格：monkeypatch 替 `pool_accounts._get_json` **计数并断言 0**。
    另加一道：`probe_account` 也不许被 `status()` 碰到（那是「探一次」的入口）。
    """
    hits = {"_get_json": 0, "probe_account": 0}

    def counted_get_json(*args, **kwargs):
        hits["_get_json"] += 1
        raise AssertionError("status() 里发起了网络请求")

    def counted_probe(*args, **kwargs):
        hits["probe_account"] += 1
        raise AssertionError("status() 里跑了一次探测")

    monkeypatch.setattr(pa, "_get_json", counted_get_json)
    monkeypatch.setattr(pa, "probe_account", counted_probe)

    pool_quota.record(
        card="A1", model="m", pool="p", kind="quota", reset_raw=RESET_LATER,
        root=tmp_path,
    )
    st = pool_quota.status(card="A1", model="m", now=NOW, root=tmp_path)
    assert st["state"] == "限流中"
    st_missing = pool_quota.status(card="no", model="such", now=NOW, root=tmp_path)
    assert st_missing["state"] == "未记录"

    assert hits == {"_get_json": 0, "probe_account": 0}, f"status() 碰了网络/探测：{hits}"


@pytest.mark.parametrize("forbidden", ["urllib", "requests", "httpx", "socket", "http.client"])
def test_quota_module_still_has_no_network_library(forbidden):
    """★ 钉子⑧（另一半）：新加的代码不许把网络库带进 `pool_quota.py`（连注释都不许）。"""
    assert forbidden not in _quota_source()
