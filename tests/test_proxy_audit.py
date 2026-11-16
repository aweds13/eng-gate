"""钉子测试：代理指标登记表 + 过期对账 `tools/proxy_audit.py`（卡 202 / 台账号 T-G304）。

判据（先红后绿）：
- 全新鲜 ⇒ `--check` 退 0；
- 有一条过期 ⇒ 退非零，且输出里能读到**那个 id 与过期天数**；
- 登记表缺失 / TOML 坏 ⇒ 退非零并**点名**（不许当通过）；
- `--days` 覆盖生效（同一条记录在 `--days 0` 下必须红，`--days 30` 下绿）。

★ 造过期用**合成登记表**（写在 `tmp_path`）—— 工具是只读的，绝不去改真登记表；
  日期现算（相对 `date.today()`），不写死，免得这张测试自己过几天变成假红。
"""

from __future__ import annotations

import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import proxy_audit as pa  # noqa: E402 —— 需要先用 sys.path 把 tools/ 挂上

REAL_MAP = ROOT / "docs" / "proxy-map.toml"


def _entry(pid: str, verified: str, *, mode: str = "因果", note: str = "未发现") -> str:
    """一条最小合规模板（字段齐，值简单，不含引号）。"""
    return (
        "\n[[proxy]]\n"
        f'id = "{pid}"\n'
        'metric = "m"\n'
        'real_goal = "g"\n'
        'evidence = "e"\n'
        f'last_verified = "{verified}"\n'
        f'failure_mode = "{mode}"\n'
        f'note = "{note}"\n'
    )


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "proxy-map.toml"
    p.write_text(body, encoding="utf-8")
    return p


# ---------------------------------------------------------- 全新鲜 ⇒ 退 0


def test_all_fresh_returns_zero(tmp_path, capsys) -> None:
    """今天验证过的登记表 ⇒ `--check` 退 0，且逐条念了判据。"""
    today = date.today().isoformat()
    p = _write(tmp_path, _entry("a", today) + _entry("b", today, mode="对抗"))
    rc = pa.main(["--check", "--map", str(p)])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "[OK  ]" in out and "全新鲜" in out
    assert "a" in out and "b" in out, "逐条念判据：每条 id 都要出现"


# ---------------------------------------------------------- 有一条过期 ⇒ 退非零


def test_one_expired_returns_nonzero_and_names_id_and_days(tmp_path, capsys) -> None:
    """一条 40 天前的记录（阈值 30）⇒ 退非零，输出里能读到 id 与过期天数（40-30=10）。"""
    old = (date.today() - timedelta(days=40)).isoformat()
    today = date.today().isoformat()
    p = _write(tmp_path, _entry("fresh-one", today) + _entry("stale-one", old))
    rc = pa.main(["--check", "--map", str(p)])
    out = capsys.readouterr().out
    assert rc != 0, out
    assert "stale-one" in out, "必须点名过期的那条 id"
    assert "过期 10 天" in out, f"必须念出过期天数：{out}"


# ---------------------------------------------------------- 登记表缺失 / TOML 坏


def test_missing_map_returns_nonzero_and_names(tmp_path, capsys) -> None:
    """登记表读不到 ⇒ 退非零并点名（不许静默当通过）。"""
    missing = tmp_path / "nope.toml"
    rc = pa.main(["--check", "--map", str(missing)])
    err = capsys.readouterr().err
    assert rc != 0, err
    assert "读不到" in err and "nope.toml" in err, err


def test_broken_toml_returns_nonzero_and_names(tmp_path, capsys) -> None:
    """TOML 坏掉 ⇒ 退非零并点名（这里故意少一个右引号）。"""
    p = _write(tmp_path, '[[proxy]]\nid = "broken\n')
    rc = pa.main(["--check", "--map", str(p)])
    err = capsys.readouterr().err
    assert rc != 0, err
    assert "TOML 坏了" in err and "proxy-map.toml" in err, err


def test_missing_field_returns_nonzero_and_names(tmp_path, capsys) -> None:
    """字段缺失 ⇒ 退非零并点名缺哪个字段。"""
    p = _write(tmp_path, '[[proxy]]\nid = "x"\nmetric = "m"\n')
    rc = pa.main(["--check", "--map", str(p)])
    err = capsys.readouterr().err
    assert rc != 0, err
    assert "缺字段" in err, err


# ---------------------------------------------------------- --days 覆盖


def test_days_override_flips_the_same_record(tmp_path, capsys) -> None:
    """同一条记录（5 天前）：阈值 30 ⇒ 绿；阈值 0 ⇒ 红。这就是「--days 覆盖生效」。"""
    past = (date.today() - timedelta(days=5)).isoformat()
    p = _write(tmp_path, _entry("mid", past))
    assert pa.main(["--check", "--map", str(p), "--days", "30"]) == 0
    capsys.readouterr()
    rc0 = pa.main(["--check", "--map", str(p), "--days", "0"])
    out0 = capsys.readouterr().out
    assert rc0 != 0, out0
    assert "mid" in out0 and "过期 5 天" in out0, out0


# ---------------------------------------------------------- 真登记表（数据层）


def test_real_map_loads_and_has_the_five_proxies() -> None:
    """真 `docs/proxy-map.toml`：5 条、id 唯一、failure_mode 合法、字段齐。"""
    entries = pa.load_map(REAL_MAP)
    assert len(entries) == 5, [e.id for e in entries]
    assert len({e.id for e in entries}) == 5
    assert all(e.failure_mode in pa.VALID_FAILURE for e in entries)
    assert all(e.metric and e.real_goal and e.evidence and e.note for e in entries)


def test_real_map_carries_both_live_scenarios() -> None:
    """★ 首版必须把两个真现场写进去：对抗型（文书行数）+ 因果型（额度记录）。"""
    entries = {e.id: e for e in pa.load_map(REAL_MAP)}
    doc = entries["doc-lines"]
    assert doc.failure_mode == "对抗"
    assert "文书行数" in doc.note and "6 行" in doc.note, "对抗型现场（文书行数）必须写进案"
    dispatch = entries["dispatch-rate"]
    assert dispatch.failure_mode == "因果"
    assert "16:52:45" in dispatch.note, "额度记录这个因果型现场必须写进登记表"


def test_report_and_json_are_readable(tmp_path, capsys) -> None:
    """`--report` 与 `--json` 都退 0，且列数/条数对得上（换的是真登记表）。"""
    assert pa.main(["--report"]) == 0
    report = capsys.readouterr().out
    assert report.count("evidence:") == 5 and report.count("note:") == 5

    assert pa.main(["--json"]) == 0
    payload = capsys.readouterr().out
    assert '"count": 5' in payload and '"expired_count": 0' in payload

# ---------------------------------------------------------- 卡 E113 · 重验读数（T-AG622）


def test_every_note_carries_the_reverification_reading() -> None:
    """★ 卡 E113 判据 1：五条 note 必须带**当天真跑过**的读数，而不只是把日期改成今天。

    背景（真现场）：docs/proxy-map.toml 自登记那天（2026-10-12）起 35 天没重验，
    五个 last_verified 一直是「登记日」。只把日期改成今天，proxy_audit.py 会照单全收
    （它只比日期）—— 那条路等于把「有日期」当「验过」，正是这张表当初要防的病。

    所以这里钉的是**文本**：每条 note 里要有一句带日期的重验读数，且句子里有具体数字。
    """
    entries = pa.load_map(REAL_MAP)
    missing = [e.id for e in entries if "重验读数" not in e.note]
    assert not missing, f"这些条目的 note 里没有重验读数（只改了日期？）：{missing}"
    undated = [e.id for e in entries if "2026-11-16" not in e.note]
    assert not undated, f"重验读数必须写明验证日 2026-11-16：{undated}"
    no_number = [e.id for e in entries if not re.search(r"\d", e.note.split("重验读数", 1)[1])]
    assert not no_number, f"重验读数里必须有具体数字（否则就是一句话，不是读数）：{no_number}"


def test_dispatch_rate_metric_points_at_the_real_logs() -> None:
    """★ 卡 E113 判据 2：dispatch-rate 的 metric 必须指向**仓里真在写**的日志。

    原来那句写的是「.meta.json 落盘 + 工人出 result 事件」，但实测量到三件事对不上：
    仓内 find -name '*.meta.json' 是 **0 个**、grep meta tools/wb_dispatch.py 是 **0 处**，
    真身只有仓外号池目录的 45 个（生产者是仓外的 infra/pool/dispatch.py）。
    ⇒ 读者按 metric 去找，在仓里一个都找不到。这条钉子把「metric 说的地方真有东西」钉住。
    """
    entry = {e.id: e for e in pa.load_map(REAL_MAP)}["dispatch-rate"]
    for token in ("wb-", "card-", "result"):
        assert token in entry.metric, f"metric 没点名两头的真日志（缺 {token}）：{entry.metric}"
    assert ".meta.json" not in entry.metric, (
        "metric 里又开始指 .meta.json 了 —— 本仓派活器从不写它"
        "（grep meta tools/wb_dispatch.py 是 0 处）"
    )
    assert "infra/pool" in entry.evidence, (
        ".meta.json 的真身要写进 evidence（仓外号池目录），否则读者仍会去仓里找："
        f"{entry.evidence}"
    )
    assert "wb_dispatch.py" in entry.metric, (
        "metric 应点名本仓派活器（它才是写 wb-<卡>.jsonl 的那个）"
    )
