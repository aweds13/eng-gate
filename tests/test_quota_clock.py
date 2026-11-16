r"""额度状态按钟表算（卡 201 · T-G303）的测试 —— 四态 + 反向 + 防回归 + 解析失败。

为什么值当测：用户原话「429 了不要凭记忆确定是否 429，要根据记录时间和现实时间对比」。
旧坑是 `wb_dispatch.quota_error()` 抠出重置时间只当字符串、等待写死 300 秒 ——
记录写 5 分钟后还是 5 小时后都一样睡。本卡改成「记录时间 vs 现实时间」四态，
每态都不猜：`未记录` 不当可用、`已过期` 不当可用 —— 只有探测才是证据。

★ 测试不许靠真实钟表：`now` 一律注入固定值 `NOW`。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import pool_quota  # noqa: E402 —— 需要先用 sys.path 把 tools/ 挂上

#: 固定「现在」（2026-10-12 23:28，主控真探那条卡的时间）—— 测试不许靠真实钟表。
NOW = "2026-10-12T23:28:00+08:00"


def _record(tmp_path: Path, *, reset_raw: str, kind: str = "限流",
            card: str = "201", model: str = "deepseek-v4.1-flash") -> tuple[str, str]:
    """落一条记录到沙箱（不碰真实仓库的 gates/diag/）。"""
    pool_quota.record(
        card=card, model=model, pool="codebuddy", kind=kind,
        reset_raw=reset_raw, source_log="wb-201.jsonl", root=tmp_path,
    )
    return card, model


# ================================================================ 四态各一条


def test_state_rate_limited(tmp_path: Path) -> None:
    """四态①：`reset_at > now` ⇒ 限流中 + 剩余时间 + 不需探测。"""
    card, model = _record(tmp_path, reset_raw="2026-10-12 23:58:00 UTC+8")  # 30 分钟后
    st = pool_quota.status(card=card, model=model, now=NOW, root=tmp_path)
    assert st["state"] == "限流中"
    assert st["remaining_seconds"] == 1800  # 30 分钟
    assert st["can_dispatch"] is False
    assert st["need_probe"] is False
    text = pool_quota.render(st)
    assert "限流中" in text
    assert "00:30:00" in text
    assert "判据" in text  # 每态都要打印判据


def test_state_expired_requires_probe(tmp_path: Path) -> None:
    """四态② + ★ 反向测试（最值钱的一条）：`reset_at <= now` ⇒ 已过期，需重新探测。

    ★ **不许**报「可用」—— 过期 ≠ 可用，只有探测才是证据。
    真现场：记录写着 16:52 重置，23:28 现探 —— 两个模型都通，但那是探出来的，不是算出来的。
    """
    card, model = _record(tmp_path, reset_raw="2026-10-12 16:52:45 UTC+8")  # 6 小时前
    st = pool_quota.status(card=card, model=model, now=NOW, root=tmp_path)
    assert st["state"] == "已过期，需重新探测"
    assert st["expired_seconds"] > 0
    assert st["can_dispatch"] is None
    assert st["need_probe"] is True
    text = pool_quota.render(st)
    assert "已过期" in text
    assert "过期 ≠ 可用" in text
    assert "要探" in text
    assert "判据" in text


def test_state_balance_exhausted(tmp_path: Path) -> None:
    """四态③：有记录但无 `reset_at`（解析失败）⇒ 余额耗尽 ⇒ 不自动等，只能探。"""
    card, model = _record(tmp_path, reset_raw="解析不出来的字符串", kind="余额耗尽")
    st = pool_quota.status(card=card, model=model, now=NOW, root=tmp_path)
    assert st["state"] == "余额耗尽"
    assert st["can_dispatch"] is None
    assert st["need_probe"] is True
    text = pool_quota.render(st)
    assert "余额耗尽" in text
    assert "不自动等" in text
    assert "判据" in text


def test_state_unrecorded(tmp_path: Path) -> None:
    """四态④：没有记录 ⇒ 未记录 ⇒ 不猜（★ 不许默认当可用）。"""
    st = pool_quota.status(card="999", model="no-such-model", now=NOW, root=tmp_path)
    assert st["state"] == "未记录"
    assert st["can_dispatch"] is None
    assert st["need_probe"] is True
    text = pool_quota.render(st)
    assert "未记录" in text
    assert "不猜" in text
    assert "判据" in text


# ================================================================ ★ 防回归


def test_wait_follows_record_not_fixed_300(tmp_path: Path) -> None:
    """★ 防回归：重置时间在 2 小时后 ⇒ status 报剩余 7200 秒，**不许**报 300 秒。

    旧坑：等待写死 `DEFAULT_QUOTA_WAIT = 300` —— 记录写 5 分钟后还是 5 小时后都睡 300 秒。
    现在按钟表算：剩余 7200 秒就报 7200，不报 300。
    """
    card, model = _record(tmp_path, reset_raw="2026-10-13T01:28:00+08:00")  # 2 小时后
    st = pool_quota.status(card=card, model=model, now=NOW, root=tmp_path)
    assert st["state"] == "限流中"
    assert st["remaining_seconds"] == 7200  # 2 小时
    assert st["remaining_seconds"] != 300  # 不许睡 300 秒
    text = pool_quota.render(st)
    assert "02:00:00" in text  # 报的是剩余 2 小时，不是 5 分钟


# ================================================================ 解析失败不许冒充


def test_unparsed_reset_falls_to_balance_exhausted(tmp_path: Path) -> None:
    """解析失败的 `reset_raw` ⇒ `reset_at` 为 `null`，走余额耗尽路线，**不许冒充**已知状态。"""
    card, model = _record(tmp_path, reset_raw="这不是时间")
    rec = pool_quota.read_record(card, model, root=tmp_path)
    assert rec["reset_raw"] == "这不是时间"
    assert rec["reset_at"] is None  # 不许拿别的数冒充
    st = pool_quota.status(card=card, model=model, now=NOW, root=tmp_path)
    assert st["state"] == "余额耗尽"  # 不许冒充限流中或已过期


# ================================================================ parse_reset 认三种形状


def test_parse_reset_three_shapes_and_failure() -> None:
    """`parse_reset` 认 ISO / `UTC+N` / 无时区；解析不出回 `None`。"""
    iso = pool_quota.parse_reset("2026-10-12T16:52:45+08:00")
    assert iso is not None and iso.year == 2026 and iso.hour == 16
    utc = pool_quota.parse_reset("2026-10-12 16:52:45 UTC+8")
    assert utc is not None and utc.utcoffset() is not None
    naive = pool_quota.parse_reset("2026-10-12 16:52:45")
    assert naive is not None and naive.tzinfo is None
    assert pool_quota.parse_reset("不是时间") is None
    assert pool_quota.parse_reset("") is None
    assert pool_quota.parse_reset(None) is None


# ================================================================ wait_seconds 按记录算


def test_wait_seconds_derived_from_record() -> None:
    """`wait_seconds`：reset_at 在 1 分钟后 ⇒ 等 60 秒（不睡满 300）。"""
    now = "2026-10-12T23:28:00+08:00"
    soon = "2026-10-12T23:29:00+08:00"  # 1 分钟后
    assert pool_quota.wait_seconds(soon, 300, now=now) == 60
    # reset_at 解析不出 ⇒ 退回 fallback
    assert pool_quota.wait_seconds(None, 300, now=now) == 300
    assert pool_quota.wait_seconds("不是时间", 300, now=now) == 300
    # reset_at 在过去 ⇒ 等 0 秒（已经过期，不等）
    past = "2026-10-12T16:00:00+08:00"
    assert pool_quota.wait_seconds(past, 300, now=now) == 0
    # reset_at 在 2 小时后 ⇒ clamp 到上限 300（不让坏记录冻几小时）
    far = "2026-10-13T01:28:00+08:00"
    assert pool_quota.wait_seconds(far, 300, now=now) == 300


# ================================================================ record 覆盖语义


def test_record_overwrites_same_card_model(tmp_path: Path) -> None:
    """同卡同模型再记一条 ⇒ 覆盖旧的（不许堆积两条）。"""
    pool_quota.record(card="201", model="m1", pool="p", kind="限流",
                      reset_raw="2026-10-12 23:58:00 UTC+8", root=tmp_path)
    pool_quota.record(card="201", model="m1", pool="p", kind="余额耗尽",
                      reset_raw="不解析", root=tmp_path)
    rec = pool_quota.read_record("201", "m1", root=tmp_path)
    assert rec is not None
    assert rec["kind"] == "余额耗尽"  # 第二条覆盖第一条
    assert rec["reset_at"] is None


# ==================================================== 卡 E112（T-AG621）：说要探，就得给那条命令


def test_every_needs_probe_state_hands_out_the_command(tmp_path: Path) -> None:
    """三态都说「要探」⇒ 人话段里必须逐字给出那条命令；限流中不许给。

    ★ 卡 E112 的问题：四行里「要探」出现两次，没有一处是可执行的命令 ⇒
      读者拿到的是一句愿望，不是一个动作。命令只有一份实现（`probe_command`），
      render 只是把它念出来 —— 不许各拼一句。
    """
    cases = [
        # (记录, 期望平台)
        (dict(reset_raw="2026-10-12 16:52:45 UTC+8", kind="限流"), "codebuddy"),  # 已过期
        (dict(reset_raw="解析不出来的字符串", kind="余额耗尽"), "codebuddy"),
    ]
    for rec, platform in cases:
        card, model = _record(tmp_path, **rec)
        st = pool_quota.status(card=card, model=model, now=NOW, root=tmp_path)
        assert st["need_probe"] is True, rec
        text = pool_quota.render(st)
        cmd = pool_quota.probe_command(platform)
        assert cmd in text, f"{st['state']} 的读数要人去探，却没给命令：\n{text}"
        assert "tools/pool_accounts.py probe" in text

    # 未记录态（没有记录 ⇒ 没有平台）
    st = pool_quota.status(card="999", model="no-such-model", now=NOW, root=tmp_path)
    assert st["need_probe"] is True
    text = pool_quota.render(st)
    assert pool_quota.probe_command(None) in text
    # 不知道是哪个池 ⇒ 不许编一个平台名（hint 里说的是「不带 --platform」这件事本身）
    assert re.search(r"--platform\s+\S", text) is None, text

    # 限流中：确定不能派 ⇒ 不叫人去探（探了也不会变成能派）
    card, model = _record(tmp_path, reset_raw="2026-10-12 23:58:00 UTC+8")
    st = pool_quota.status(card=card, model=model, now=NOW, root=tmp_path)
    assert st["state"] == "限流中"
    assert "tools/pool_accounts.py probe" not in pool_quota.render(st)


def test_probe_hint_says_what_it_does_not_do() -> None:
    """hint 必须说清「它不改四态」—— 探会写仓外账本，quota-state.json 只由 429 派生。

    ★ 反向断言比正向更要紧：一句「探完就能派活」的承诺会让读者跳过判据本身。
    """
    hint = pool_quota.probe_hint("codebuddy")
    assert "quota-state.json" in hint
    assert "未必变" in hint
    assert "就会" not in hint  # 不许承诺「探完就会变」
    assert "即可派活" not in hint
    assert "就能派活" not in hint
    assert pool_quota.probe_command("codebuddy") in hint


def test_probe_command_carries_the_recorded_pool() -> None:
    """给了平台才带 `--platform`；`None` 时**不带**（跑全量），不许编平台名。"""
    cmd = pool_quota.probe_command("codebuddy")
    assert "--platform codebuddy" in cmd
    assert cmd.startswith("python -X utf8 ")
    assert pool_quota.PROBE_SCRIPT in cmd

    full = pool_quota.probe_command(None)
    assert "--platform" not in full
    assert pool_quota.PROBE_SCRIPT in full
    assert "None" not in full  # 不许把 None 拼进命令


def test_unrecorded_state_does_not_invent_a_platform(tmp_path: Path) -> None:
    """未记录态没有记录 ⇒ probe["platform"] 是 None，hint 明说「不带 --platform」。"""
    st = pool_quota.status(card="nope", model="nope", now=NOW, root=tmp_path)
    assert st["state"] == "未记录"
    probe = st["probe"]
    assert probe["platform"] is None
    assert "--platform" in probe["hint"]  # 说的是「不带 --platform」这件事本身
    assert probe["command"] == pool_quota.probe_command(None)
    assert probe["hint"] == pool_quota.probe_hint(None)


def test_recorded_state_passes_its_pool_to_the_probe(tmp_path: Path) -> None:
    """有记录 ⇒ platform 取记录里的 pool 字段（真数据今天只有 codebuddy）。"""
    card, model = _record(tmp_path, reset_raw="2026-10-12 16:52:45 UTC+8")
    st = pool_quota.status(card=card, model=model, now=NOW, root=tmp_path)
    assert st["probe"]["platform"] == "codebuddy"
    assert "--platform codebuddy" in st["probe"]["command"]


def test_can_dispatch_none_is_not_false(tmp_path: Path) -> None:
    """★ None is not False：Python 里两样都是假值，但判词一个是「不知道」、一个是「不能」。

    ★ 卡 E112 的问题：四态恒 False ⇒ 读面把「不知道」说成「确定不能派」。
    """
    # 不能派：限流中（有钟表读数）
    card, model = _record(tmp_path, reset_raw="2026-10-12 23:58:00 UTC+8")
    st = pool_quota.status(card=card, model=model, now=NOW, root=tmp_path)
    assert st["can_dispatch"] is False
    assert "不知道" not in st["can_dispatch_reason"]
    assert "确定不能派" in st["can_dispatch_reason"]

    # 不知道：其余三态
    for rec in (dict(reset_raw="2026-10-12 16:52:45 UTC+8"),
                dict(reset_raw="解析不出来", kind="余额耗尽")):
        card, model = _record(tmp_path, **rec)
        st = pool_quota.status(card=card, model=model, now=NOW, root=tmp_path)
        assert st["can_dispatch"] is None, rec
        assert st["can_dispatch"] is not False
        assert bool(st["can_dispatch"]) is False  # 假值 ≠ 判词
        assert "不知道" in st["can_dispatch_reason"], rec
        assert "确定不能派" not in st["can_dispatch_reason"]

    st = pool_quota.status(card="nope", model="nope", now=NOW, root=tmp_path)
    assert st["can_dispatch"] is None
    assert st["can_dispatch"] is not False
    assert "不知道" in st["can_dispatch_reason"]
