"""卡 A347 / T-AG550：外面报来的用量也得进账（magpie 用量上报判据层移植进 pool）。

钉子表（照卡规格 §测试钉子表；一条一行，名字逐字不动）：

  ① ``test_parse_batch_accepts_a_single_record``
     单个 JSON 对象进得去，``accepted == 1``、``records[0]["status"] == "accepted"``。
  ② ``test_parse_batch_accepts_exactly_5000_records``
     恰好 5000 条通过（``MAX_RECORDS`` 的边界值，4999/5000 两个数都钉）。
  ③ ``test_parse_batch_refuses_5001_records``
     5001 条整包拒，``Fault.index == -1``，文案 ``"5001 records: send at most 5000 a post"``。
  ④ ``test_parse_batch_refuses_empty_array``
     ``[]`` ⇒ ``"the array has no records"``。
  ⑤ ``test_one_bad_record_refuses_the_whole_batch``
     20 条里第 3 条 ``in = -1`` ⇒ 恰好 1 个 ``Fault``，``index == 3``、``field == "in"``、
     ``error_text() == "record 3: in: must not be negative"``。
  ⑥ ``test_refused_batch_writes_nothing``
     拒单后目标文件行数与 mtime 都不变。
  ⑦ ``test_quoted_number_is_refused``
     ``"in": "5"`` ⇒ ``"must be a number"``。
  ⑧ ``test_err_is_exempt_from_256_and_control``
     ``err`` 长 5000 字符通过；同长度放 ``agent`` 上 ⇒ ``"longer than 256 characters"``。
  ⑨ ``test_time_one_hour_ahead_passes_one_second_more_is_refused``
     ``now+3600s`` 通过；``now+3601s`` ⇒ ``"is in the future"``。
  ⑩ ``test_rid_is_skipped_on_second_post``
     同一条 ``rid`` 报两次 ⇒ 第二次 ``skipped``，文件只多一行。
  ⑪ ``test_rid_duplicate_within_one_batch_is_skipped``
     同一批里两条同 ``rid`` ⇒ 第二条 ``skipped``。
  ⑫ ``test_reported_rows_do_not_count_by_default``
     上报 1000 token 后 ``merged_tokens(..., include_reported=False)`` 不变；``True`` 时多 1000。

另加两条（卡规格 §测试钉子表末注：「并入相应用例或另立，总数 ≥12」—— 这里另立，只加不减）：

  ⑬ ``test_time_before_2000_is_refused``
     ``t < 2000-01-01T00:00:00Z`` 拒，文案逐字；同时钉住 ``EARLIEST`` 是**含**下界的
     （正好等于 2000-01-01T00:00:00Z 的那一刻必须通过，否则「早于」就被读成了「不晚于」）。
  ⑭ ``test_reported_rows_never_carry_caller``
     上报行的 ``caller`` / ``key`` / ``account`` / ``caller_key_id`` / ``caller_key_name``
     五个身份栏位一律剥掉 —— 这张卡的账里不记「谁报的」，只记「报了什么」。

★ 零接线：本文件**不 import** ``tools/wb_dispatch.py``、不碰任何既有账本，全部落在 ``tmp_path``。

★ 导入口径：一律走包路径 ``from tools.pool import usage_ingest``，不往 ``sys.path`` 里塞
  ``tools/`` —— 塞了就得给 ``noqa: E402``，本仓不许 ``noqa``（同 ``tests/test_pool_due.py:36``）。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest

from tools.pool import usage_ingest as ui

if TYPE_CHECKING:  # 只在注解里出现（本文件有 `from __future__ import annotations`）
    from pathlib import Path

#: 钉死的「现在」—— 卡规格 §判据表第 104 行那份文案里的时刻就是它，别改。
NOW = datetime(2026, 10, 13, 8, 0, 0, tzinfo=timezone.utc)

#: 派活器侧的时区（``wb_dispatch.usage_in()`` 里也是 ``timezone(timedelta(hours=8))``）。
TZ = timezone(timedelta(hours=8))

#: 上报账的相对路径 —— 目标文件必须落在 ``<root>/gates/diag/usage-reported.jsonl``。
REPORTED_REL = ("gates", "diag", "usage-reported.jsonl")


def _record(**override: object) -> dict[str, object]:
    """一条最小的、必然通过的上报记录；``override`` 覆盖任意栏位（也用来加表外字段）。"""
    base: dict[str, object] = {
        "rid": "r1",
        "agent": "a",
        "provider": "p",
        "model": "m",
        "status": 200,
        "t": "2026-10-13T08:00:00Z",
    }
    base.update(override)
    return base


def _body(*records: dict[str, object]) -> str:
    """若干条记录 → 一段上报体（单条走对象形态，多条走数组形态）。"""
    if len(records) == 1:
        return json.dumps(records[0])
    return json.dumps(list(records))


def _faults_of(text: str, *, now: datetime = NOW) -> list[ui.Fault]:
    """跑 ``parse_batch`` 并把它抛出的 ``IngestRefused`` 里的 faults 取出来。

    ★ 这里**只**接 ``IngestRefused``：若实现改成回一个空列表 / 静默跳过，
      用例会在 ``pytest.raises`` 那里红，而不是被一句 ``or []`` 洗成绿。
    """
    with pytest.raises(ui.IngestRefused) as caught:
        ui.parse_batch(text, now=now)
    return caught.value.faults


def _reported_file(root: Path) -> Path:
    """上报账落在哪 —— 逐段拼，不写死斜杠，Windows 上也是同一条路径。"""
    return root.joinpath(*REPORTED_REL)


def _rows(root: Path) -> list[str]:
    """上报账的每一行（文件不存在 ⇒ 空列表，不当 0 行以外的任何东西）。"""
    path = _reported_file(root)
    if not path.is_file():
        return []
    return path.read_text(encoding="utf-8").splitlines()


# ---------------------------------------------------------------- ① 单条进得去


def test_parse_batch_accepts_a_single_record(tmp_path: Path) -> None:
    """单个 JSON 对象（不是数组）也能进；缺省栏位回填成空串 / 0 / ``None``。"""
    rows = ui.parse_batch(_body(_record()), now=NOW)

    assert len(rows) == 1
    row = rows[0]
    # 必填四个字符串原样留着
    assert (row["rid"], row["agent"], row["provider"], row["model"]) == ("r1", "a", "p", "m")
    # 可空三个字符串回填空串，不是 None
    assert (row["effort"], row["session"], row["err"]) == ("", "", "")
    # 六个计数栏位、四个毫秒栏位回填 0
    assert [row[key] for key in ui.COUNTS] == [0] * len(ui.COUNTS)
    assert [row[key] for key in ui.MILLIS] == [0] * len(ui.MILLIS)
    # status 原样、cost 缺省是 None（不是 0.0 —— 0.0 会被读成「花了 0 块钱」）
    assert row["status"] == 200
    assert row["cost"] is None
    # t 原样留成传进来的那份 RFC 3339 文本
    assert row["t"] == "2026-10-13T08:00:00Z"

    # 走 ingest 才算「进账」：accepted 1 条、写盘一行
    verdict = ui.ingest(_body(_record()), now=NOW, root=tmp_path)
    assert verdict["accepted"] == 1
    assert verdict["skipped"] == 0
    assert verdict["records"][0]["status"] == "accepted"
    assert len(_rows(tmp_path)) == 1


# ------------------------------------------------------- ② 恰好 5000 条是边界内


def test_parse_batch_accepts_exactly_5000_records() -> None:
    """``MAX_RECORDS`` 是**含**上界的：4999 与 5000 都过，一条不少地回。"""
    assert ui.MAX_RECORDS == 5000
    body = _body(*[_record(rid=f"r{i}") for i in range(5000)])

    rows = ui.parse_batch(body, now=NOW)
    assert len(rows) == 5000
    assert rows[0]["rid"] == "r0"
    assert rows[-1]["rid"] == "r4999"

    # 少一条当然也过（证明上面那条不是「只有 5000 特殊」）
    assert len(ui.parse_batch(_body(*[_record(rid=f"r{i}") for i in range(4999)]), now=NOW)) == 4999


# ------------------------------------------------------------- ③ 5001 条整包拒


def test_parse_batch_refuses_5001_records() -> None:
    """5001 条整包拒，``index == -1``（这是「包」的错，不是哪一条的错）。"""
    faults = _faults_of(_body(*[_record(rid=f"r{i}") for i in range(5001)]))

    assert len(faults) == 1
    assert faults[0].index == -1
    assert faults[0].field == "body"
    assert faults[0].error_text() == "body: 5001 records: send at most 5000 a post"


# --------------------------------------------------------------- ④ 空数组要拒


def test_parse_batch_refuses_empty_array() -> None:
    """``[]`` 不是「零条成功」，是「你发了个空包」。"""
    faults = _faults_of("[]")

    assert len(faults) == 1
    assert faults[0].index == -1
    assert faults[0].error_text() == "body: the array has no records"


# ------------------------------------------------------- ⑤ 一条坏 ⇒ 整包全有或全无


def test_one_bad_record_refuses_the_whole_batch() -> None:
    """20 条里第 3 条坏 ⇒ 恰好 1 个 Fault 指向第 3 条，整包一条都不进。"""
    records = [_record(rid=f"r{i}") for i in range(20)]
    records[3] = _record(rid="r3", **{"in": -1})

    faults = _faults_of(_body(*records))

    # 不是「攒够 20 个错」，是「攒到第一个错就停」—— 恰好 1 个
    assert len(faults) == 1
    assert faults[0].index == 3
    assert faults[0].field == "in"
    assert faults[0].error_text() == "record 3: in: must not be negative"


# ----------------------------------------------------------- ⑥ 拒单一个字节不写


def test_refused_batch_writes_nothing(tmp_path: Path) -> None:
    """先成功落一行，再发一个坏包：行数与 mtime 都不许变。"""
    ui.ingest(_body(_record(rid="ok1")), now=NOW, root=tmp_path)
    path = _reported_file(tmp_path)
    before_lines = len(_rows(tmp_path))
    before_mtime = path.stat().st_mtime_ns

    bad = _body(_record(rid="ok1"), _record(rid="bad", **{"in": -1}))
    with pytest.raises(ui.IngestRefused) as caught:
        ui.ingest(bad, now=NOW, root=tmp_path)

    assert [f.error_text() for f in caught.value.faults] == [
        "record 1: in: must not be negative"
    ]
    assert len(_rows(tmp_path)) == before_lines, "拒单之后行数不许变"
    assert path.stat().st_mtime_ns == before_mtime, "拒单之后连 mtime 都不许动"


# ------------------------------------------------------------- ⑦ 带引号的数字


def test_quoted_number_is_refused() -> None:
    """``"in": "5"`` 是字符串不是数 —— 不做隐式转数字（会把 ``"5 apples"`` 一起放进来）。"""
    faults = _faults_of(_body(_record(**{"in": "5"})))

    assert len(faults) == 1
    assert faults[0].field == "in"
    assert faults[0].error_text() == "record 0: in: must be a number"


# --------------------------------------------------------- ⑧ err 的两条豁免


def test_err_is_exempt_from_256_and_control() -> None:
    """``err`` 豁免「≤256」与「无控制字符」两条；同一份内容放 ``agent`` 上必须被拒。"""
    long_text = "x" * 5000

    # 长 5000 的 err 通过，并被截到 4096（``MAX_ERR``，卡规格 §判据表）
    row = ui.parse_batch(_body(_record(err=long_text)), now=NOW)[0]
    assert len(row["err"]) == 4096

    # 同一份长度放 agent 上 ⇒ 被 256 那条拦住
    faults = _faults_of(_body(_record(agent=long_text)))
    assert len(faults) == 1
    assert faults[0].error_text() == "record 0: agent: longer than 256 characters"

    # 控制字符：err 里过得去（stderr 里带颜色码是常态）
    assert ui.parse_batch(_body(_record(err="a\x01b")), now=NOW)[0]["err"] == "a\x01b"
    # 同样一个字节放 agent 上 ⇒ 被控制字符那条拦住
    faults = _faults_of(_body(_record(agent="a\x01b")))
    assert len(faults) == 1
    assert faults[0].error_text() == "record 0: agent: has a control character"


# ------------------------------------------------------- ⑨ 未来容差的边界值


def test_time_one_hour_ahead_passes_one_second_more_is_refused() -> None:
    """``FUTURE_S`` 是**含**上界的：正好 3600s 通过，3601s 拒。"""
    assert ui.FUTURE_S == 3600

    at_edge = (NOW + timedelta(seconds=3600)).isoformat().replace("+00:00", "Z")
    assert ui.parse_batch(_body(_record(t=at_edge)), now=NOW)[0]["t"] == at_edge

    over_edge = (NOW + timedelta(seconds=3601)).isoformat().replace("+00:00", "Z")
    faults = _faults_of(_body(_record(t=over_edge)))
    assert len(faults) == 1
    assert faults[0].field == "t"
    assert faults[0].error_text() == "record 0: t: is in the future"

    # 顺带钉住「不是 RFC 3339 的一律拒」：纯日期 ``fromisoformat`` 吃得下，
    # 但正则先把它拦住了 —— 否则 ``t`` 会静默变成当天零点。
    faults = _faults_of(_body(_record(t="2026-10-13")))
    assert faults[0].error_text() == (
        "record 0: t: must be an RFC 3339 time (2026-10-13T08:00:00Z)"
    )


# -------------------------------------------------------- ⑬ 下界 2000-01-01 真在判


def test_time_before_2000_is_refused() -> None:
    """``t`` 早于 2000-01-01T00:00:00Z 拒；正好等于那一刻**通过**（下界是含的）。"""
    faults = _faults_of(_body(_record(t="1999-12-31T23:59:59Z")))
    assert len(faults) == 1
    assert faults[0].field == "t"
    assert faults[0].error_text() == (
        "record 0: t: is before 2000-01-01T00:00:00Z, the earliest a call may be dated"
    )

    # 下界含：2000-01-01T00:00:00Z 那一刻必须过 —— 这条是「早于」不是「不晚于」的反证
    assert ui.parse_batch(_body(_record(t="2000-01-01T00:00:00Z")), now=NOW)[0]["t"] == (
        "2000-01-01T00:00:00Z"
    )


# ------------------------------------------------------------- ⑩ rid 幂等（跨批）


def test_rid_is_skipped_on_second_post(tmp_path: Path) -> None:
    """同一条 ``rid`` 报两次 ⇒ 第二次 ``skipped``，文件只多一行。"""
    first = ui.ingest(_body(_record(rid="dup")), now=NOW, root=tmp_path)
    assert (first["accepted"], first["skipped"]) == (1, 0)
    assert len(_rows(tmp_path)) == 1

    second = ui.ingest(_body(_record(rid="dup")), now=NOW, root=tmp_path)
    assert (second["accepted"], second["skipped"]) == (0, 1)
    assert second["records"][0]["status"] == "skipped"
    assert second["records"][0]["rid"] == "dup"
    # 文件仍然只有那一行 —— 不是「又写一行然后不计数」
    rows = _rows(tmp_path)
    assert len(rows) == 1
    assert json.loads(rows[0])["rid"] == "dup"


# --------------------------------------------------------- ⑪ rid 幂等（批内）


def test_rid_duplicate_within_one_batch_is_skipped(tmp_path: Path) -> None:
    """同一批里两条同 ``rid`` ⇒ 第一条进，第二条 ``skipped``（批内也要去重）。"""
    verdict = ui.ingest(
        _body(_record(rid="x1"), _record(rid="x1")), now=NOW, root=tmp_path
    )

    assert (verdict["accepted"], verdict["skipped"]) == (1, 1)
    assert [r["status"] for r in verdict["records"]] == ["accepted", "skipped"]
    assert [r["index"] for r in verdict["records"]] == [0, 1]
    assert len(_rows(tmp_path)) == 1


# ------------------------------------------------- ⑭ 上报行不带 caller 五个栏位


#: 五个身份栏位 —— magpie 判「谁报的」用，pool 的账一个都不许留。
BANNED = ("caller", "key", "account", "caller_key_id", "caller_key_name")


def test_reported_rows_never_carry_caller(tmp_path: Path) -> None:
    """``caller`` / ``key`` / ``account`` / ``caller_key_id`` / ``caller_key_name`` 一律剥掉。

    这五个是 magpie 判「谁报的」用的身份栏位；pool 的账只记「报了什么」，
    记下身份等于在一份 gitignored 的账本里留人名 —— 这条钉住「不记」。

    ★ 两道闸，这道用例两道都钉：

      1. **外闸**：表外字段在 ``_parse_one`` 就被拒（``is not a field a call has``）——
         所以正常走 ``ingest()`` 的包里根本带不进这五个；
      2. **内闸**：``_reported_row()`` 落盘前再剥一次 —— 万一以后有人把某个身份栏位
         加进 ``FIELDS``（比如为了兼容旧上报方），这层仍然保证它落不了盘。
    """
    # ── 外闸：真走 ingest，五个身份栏位逐个撞「表外字段」，且整包拒、一行不写
    for banned in BANNED:
        faults = _faults_of(_body(_record(**{banned: "x"})))
        assert len(faults) == 1, banned
        assert faults[0].field == banned
        assert faults[0].error_text() == f"record 0: {banned}: is not a field a call has"
    with pytest.raises(ui.IngestRefused):
        ui.ingest(_body(_record(**{banned: "x" for banned in BANNED})), now=NOW, root=tmp_path)
    assert _rows(tmp_path) == [], "带身份栏位的包一条都不许落地"

    # ── 内闸：落盘前那一层剥（直接把带身份的记录喂给它，绕开外闸单测这一层）
    stripped = ui._reported_row(dict(_record(**{banned: "x" for banned in BANNED})))
    for banned in BANNED:
        assert banned not in stripped, f"{banned} 不许进上报账"

    # 剥的是「身份」，报的内容一个不少
    assert stripped["rid"] == "r1"
    assert stripped["model"] == "m"
    assert stripped["status"] == 200
    # 并且打上「这是上报来的行」这个标记 —— 读端靠它区分两本账
    assert stripped["source"] == ui.SOURCE_REPORTED == "reported"

    # 真实落盘那一行同样干净（走正规路径，五个身份栏位一个都不带）
    ui.ingest(_body(_record()), now=NOW, root=tmp_path)
    on_disk = json.loads(_rows(tmp_path)[0])
    assert not [banned for banned in BANNED if banned in on_disk]
    assert on_disk["source"] == "reported"


# --------------------------------------------- ⑫ 上报行默认不计入 merged_tokens


def _write_dispatch_usage(root: Path, *, model: str = "m") -> None:
    """造一行派活器账（``gates/diag/wb-usage.jsonl``）。

    ``开始`` 用**无时区**的本地串 —— 这正是 ``append_usage_line()`` 的真实写法，
    ``_local()`` 靠 ``replace(tzinfo=USAGE_TZ)`` 把 ``+08:00`` 补上。
    """
    diag = root / "gates" / "diag"
    diag.mkdir(parents=True, exist_ok=True)
    line = {
        "模型": model,
        "开始": "2026-10-13T09:00:00",
        "input_tokens": 10,
        "output_tokens": 20,
        "cache_read": 30,
        "判决": "ok",
    }
    (diag / "wb-usage.jsonl").write_text(
        json.dumps(line, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def test_reported_rows_do_not_count_by_default(tmp_path: Path) -> None:
    """上报 1000 token 后默认口径**不变**；显式 ``include_reported=True`` 才多 1000。"""
    _write_dispatch_usage(tmp_path)
    start = datetime(2026, 10, 13, 0, 0, 0, tzinfo=TZ)
    end = datetime(2026, 10, 14, 0, 0, 0, tzinfo=TZ)

    # 派活器那本账：10 + 20 + 30，三栏全加、不做减法
    assert ui.merged_tokens("m", start, end, root=tmp_path) == 60

    # 外面报来 400 + 300 + 300 = 1000
    ui.ingest(
        _body(_record(**{"in": 400, "out": 300, "cache_read": 300})),
        now=NOW,
        root=tmp_path,
    )

    # 默认口径纹丝不动 —— 上报行单列，不许悄悄混进派活器那本账
    assert ui.merged_tokens("m", start, end, root=tmp_path) == 60
    assert ui.merged_tokens("m", start, end, root=tmp_path, include_reported=False) == 60
    # 只有显式要的时候才加上
    assert ui.merged_tokens("m", start, end, root=tmp_path, include_reported=True) == 1060
    # 模型对不上的行哪本账都不算
    assert ui.merged_tokens("zzz", start, end, root=tmp_path, include_reported=True) == 0
