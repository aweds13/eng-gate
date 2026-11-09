r"""整窗估算与「五因」（卡 A334 · T-AG536）的判据钉子。

为什么值当测：这套判据的价值全在「估不出来时**说出为什么**」——`low`（量太小，厂商给的
百分比四舍五入太粗）/ `clock`（没有重置时间）/ `log`（日志起点晚于窗口起点）/ `none`（分子是 0）/
`credits`（这段有按 credits 另付的调用），以及 `"-"`（不估）。这三处最容易被写成「凑个数」：

① `used` 缺失当成 0（⇒ `scale = 100 / 0`，或者假出一个天文数字）；
② 判定顺序里把 `low` 与 `clock` 对调（⇒ 两种「不估」混成一因，日志里再也分不清）；
③ 区间读取按 UTC 猜时区（⇒ 整窗分子系统性错位 8 小时，还查不出来）。

前两条在下面各有一条**反向**钉子（`tests/` 之外由 `gates/diag/_rev_A334.py` 逐条变异验证）。

| 钉子 | 判什么 | 会红在哪 |
|---|---|---|
| ① 五因原串 | 五个因串 + `HOLDS_FLOOR = 5.0` 逐字 | 若翻成中文或把下限调小 |
| ② 边界三档 | `resets_at` > `reset_secs` > 不估 | 若把优先序写反 |
| ③ 整月窗 | 30 天窗 `start` 按日历减一月（3/31 → 2/28） | 若减 30×86400 秒 |
| ④ `low` 先于 `clock` | `used=3.0` 无重置 ⇒ `low`；`used=10.0` 无重置 ⇒ `clock` | 对调就红 |
| ⑤ `used` 缺失 ⇒ `"-"` | `used=None` / NaN 不许当 0 | **反向**：改成 `used = 0` 就红 |
| ⑥ 估算式 | `used=25.0` + 1000 tokens ⇒ 4000 | 若漏乘或除反 |
| ⑦ 后三因 | `log` / `none` / `credits` 按 magpie 赋值顺序（后写覆盖先写） | 若自创优先级 |
| ⑧ 区间读取 | `+08:00`、`[start, end)`、按模型、排除 dry run | 若按 UTC 猜或右闭 |
| ⑨ 前挡与成功 | 无限额度 / 溢出池无名 / 家庭号 / 池不符 / 区间不含此刻 ⇒ `"-"` | 不估被判成功 |
| ⑩ 模型名归一 | 注册表写法与日志写法算同一个模型 | 若只比字面 ⇒ 带斜杠的名字恒 0 |

⑩ 的具体两种写法：注册表 `huaweicloud-maas/GLM-5.2`，日志 `glm-5.2`（大小写也不一定一样）。

★ 一条真实钟表都不碰：`read_at` / `first_log_at` / 区间端点全是写死的常数（固定 `NOW`）。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import wb_dispatch  # noqa: E402 —— tools/ 已在 sys.path 上
from pool import holds  # noqa: E402

#: 与 `tools/pool_accounts.py:47` 同一口径：本仓的「本地时间」是 +08:00。
TZ = timezone(timedelta(hours=8))

#: 写死的「此刻」—— 判据里任何一条都不许读真实钟表。
NOW = datetime(2026, 10, 12, 12, 0, tzinfo=TZ)

#: 判据 2 里那个「整月窗」跨度。
MONTH = holds.MONTH_SPAN_S


# ---------------------------------------------------------------- ① 五因原串


def test_holds_causes_are_verbatim_strings():
    """① 五个因串原样存盘、`HOLDS_FLOOR` 就是 5.0 —— 判据标识不许翻译、不许调小。"""
    assert holds.HOLDS_FLOOR == 5.0
    assert isinstance(holds.HOLDS_FLOOR, float)
    causes = [
        holds.HOLDS_LOW,
        holds.HOLDS_NO_CLOCK,
        holds.HOLDS_BEFORE_LOG,
        holds.HOLDS_NONE_ROUTED,
        holds.HOLDS_CREDITS,
    ]
    assert causes == ["low", "clock", "log", "none", "credits"]
    assert holds.HOLDS_CAUSES == ("low", "clock", "log", "none", "credits")
    # 「不估」与「估出来了没有因」是两回事
    assert holds.HOLDS_UNKNOWN == "-"
    assert holds.HOLDS_OK == ""
    # 原串里不许有中文（人话在 why_text）；每一因的人话都要有，且与原串不同
    for cause in holds.HOLDS_CAUSES:
        assert not any("\u4e00" <= ch <= "\u9fff" for ch in cause), cause
        assert holds.why_text(cause) != cause
    texts = {holds.why_text(c) for c in (*holds.HOLDS_CAUSES, holds.HOLDS_UNKNOWN, holds.HOLDS_OK)}
    assert len(texts) == 7
    # 少键不许兜底编话
    with pytest.raises(KeyError):
        holds.why_text("Low")
    # dataclass 冻住：判据对象不许被就地改
    with pytest.raises(AttributeError):
        holds.Window(used=25.0).used = 30.0  # type: ignore[misc]


# ---------------------------------------------------------------- ② 边界三档


def test_bounds_resets_at_wins_over_reset_secs():
    """② `resets_at` > `reset_secs > 0` > 不估；`start` 从 `end` 往回退 `span_s`。"""
    end = datetime(2026, 11, 3, 0, 0, tzinfo=TZ)
    both = holds.Window(span_s=7 * 24 * 3600, used=40.0, resets_at=end, reset_secs=3600)
    assert holds.bounds(both, NOW) == (end - timedelta(days=7), end)
    # 只有 reset_secs ⇒ end = read_at + reset_secs
    secs = holds.Window(span_s=3600, used=40.0, reset_secs=1800)
    assert holds.bounds(secs, NOW) == (NOW - timedelta(minutes=30), NOW + timedelta(minutes=30))
    # 都没有 ⇒ None（不估），不编一个边界出来
    assert holds.bounds(holds.Window(span_s=3600, used=40.0), NOW) is None
    assert holds.bounds(holds.Window(span_s=3600, used=40.0, reset_secs=0), NOW) is None


# ---------------------------------------------------------------- ③ 整月窗


def test_bounds_month_window_uses_calendar_month():
    """③ 30 天窗按**日历**减一月：3/31 退到 2/28（2026 非闰年），不是 3/1。"""
    end = datetime(2026, 3, 31, 0, 0, tzinfo=TZ)
    start, got_end = holds.bounds(holds.Window(span_s=MONTH, used=40.0, resets_at=end), NOW)
    assert got_end == end
    assert start == datetime(2026, 2, 28, 0, 0, tzinfo=TZ)
    assert start != end - timedelta(seconds=MONTH)  # 减固定秒数会落到 3/1
    # 跨年：1 月退到上一年 12 月
    jan = holds.Window(span_s=MONTH, used=40.0, resets_at=datetime(2026, 1, 15, 0, 0, tzinfo=TZ))
    assert holds.bounds(jan, NOW)[0] == datetime(2025, 12, 15, 0, 0, tzinfo=TZ)
    # 非整月窗仍按秒退（别把日历逻辑用到 7 天窗上）
    week = holds.Window(span_s=7 * 24 * 3600, used=40.0, resets_at=end)
    assert holds.bounds(week, NOW)[0] == end - timedelta(days=7)


# ---------------------------------------------------------------- ④ low 先于 clock（反向钉子 2）


def test_holds_low_when_used_under_floor():
    """④ `used < HOLDS_FLOOR` ⇒ `low`，**先于**「拿不到边界」（`clock`）。

    反向验证：把 `holds.py` 里 `low` 那段与 `clock` 那段对调 ⇒ 本用例第一条断言必红
    （`used=3.0` 且无重置时间的窗口会变成 `clock`）。
    """
    # 连边界都没有，但量太小 ⇒ low 先命中
    assert holds.holds_bounds(holds.Window(used=3.0), NOW) == (None, None, "low")
    assert holds.holds_bounds(holds.Window(span_s=MONTH, used=4.999), NOW)[2] == holds.HOLDS_LOW
    # 刚好到下限 ⇒ 不是 low（是「边界拿不到」）
    assert holds.holds_bounds(holds.Window(used=holds.HOLDS_FLOOR), NOW)[2] == holds.HOLDS_NO_CLOCK
    # 量够、边界没有 ⇒ clock
    assert holds.holds_bounds(holds.Window(used=10.0), NOW)[2] == holds.HOLDS_NO_CLOCK


# ---------------------------------------------------------------- ⑤ used 缺失 ⇒ "-"（反向钉子 1）


def test_holds_unmeasured_used_is_dash_not_low():
    """⑤ 没有 `used` ⇒ `"-"`，**绝不**当代 0。

    反向验证：把 `holds.py` 里 `if used is None or not math.isfinite(used): return …
    HOLDS_UNKNOWN` 改成 `used = 0` ⇒ 本用例必红（`"-"` 会变成 `low`）。
    """
    end = datetime(2026, 10, 15, 0, 0, tzinfo=TZ)
    assert holds.holds_bounds(holds.Window(used=None, resets_at=end), NOW) == (None, None, "-")
    # NaN / inf 不算「有值」—— 它们会让除法算出垃圾
    for bad in (float("nan"), float("inf"), float("-inf")):
        assert holds.holds_bounds(holds.Window(used=bad, resets_at=end), NOW)[2] == "-"
    # 边界齐、量也够，但就是没这个数 ⇒ 不估，也不报数
    out = holds.estimate(
        [holds.Window(model="m", span_s=7 * 24 * 3600, used=None, resets_at=end)],
        routed_tokens=1000,
        routed_cost=0.5,
        first_log_at=end - timedelta(days=7),
        read_at=NOW,
    )
    assert (out[0].why, out[0].tokens, out[0].cost) == ("-", 0, 0.0)


# ---------------------------------------------------------------- ⑥ 估算式


def test_estimate_scales_by_used_share():
    """⑥ 算式逐字：`scale = 100 / used`；`tokens = round(routed_tokens * scale)`；
    `cost = routed_cost * scale`。
    """
    end = datetime(2026, 10, 15, 0, 0, tzinfo=TZ)
    start = end - timedelta(days=7)
    w = holds.Window(model="glm-5.3-flash", span_s=7 * 24 * 3600, used=25.0, resets_at=end)
    out = holds.estimate(
        [w],
        routed_tokens=1000,
        routed_cost=0.5,
        first_log_at=start,  # 正好等于窗口起点 ⇒ 不算「日志太晚」
        read_at=NOW,
    )
    assert len(out) == 1
    h = out[0]
    assert h.why == holds.HOLDS_OK
    assert h.why_text == holds.why_text(holds.HOLDS_OK)
    assert h.tokens == 4000  # 1000 × (100 / 25)
    assert h.cost == 2.0  # 0.5 × 4
    assert h.since == start
    # 换算不是「乘 used」也不是「除 used/100」这类反写
    assert h.tokens != 250
    assert h.tokens != 10


# ---------------------------------------------------------------- ⑦ 后三因（顺序照 magpie）


def test_estimate_last_three_causes_follow_magpie_order():
    """⑦ `log`（`:201`）→ `none`（`:274`）→ `credits`（`:276`）：后写覆盖先写，不自创优先级。"""
    end = datetime(2026, 10, 15, 0, 0, tzinfo=TZ)
    start = end - timedelta(days=7)
    w = holds.Window(model="m", span_s=7 * 24 * 3600, used=25.0, resets_at=end)

    def why_of(*, routed_tokens=1000, first_log_at=start, paid_otherwise=False):
        h = holds.estimate(
            [w],
            routed_tokens=routed_tokens,
            routed_cost=0.5,
            first_log_at=first_log_at,
            read_at=NOW,
            paid_otherwise=paid_otherwise,
        )[0]
        if h.why != holds.HOLDS_OK:  # 命中任一因 ⇒ 一个数都不报
            assert (h.tokens, h.cost) == (0, 0.0)
        return h.why

    assert why_of(first_log_at=None) == "log"
    assert why_of(first_log_at=start + timedelta(seconds=1)) == "log"
    assert why_of(routed_tokens=0) == "none"
    assert why_of(routed_tokens=-5) == "none"
    assert why_of(paid_otherwise=True) == "credits"
    # 后写覆盖先写（不是「先命中先停」）
    assert why_of(routed_tokens=0, first_log_at=None) == "none"
    assert why_of(routed_tokens=0, first_log_at=None, paid_otherwise=True) == "credits"
    assert why_of(first_log_at=None, paid_otherwise=True) == "credits"


# ---------------------------------------------------------------- ⑧ 区间读取


def _usage_rows() -> list[dict]:
    """手工 JSONL：行键与 `append_usage_line()` 落盘的一致（时间秒级、无时区后缀）。"""
    base = {
        "卡": "A334",
        "模型": "glm-5.3-flash",
        "轮次": 1,
        "结束": "2026-09-26T21:05:00",
        "用时分钟": 5.0,
        "input_tokens": 10,
        "output_tokens": 20,
        "cache_read": 5,
        "退出码": 0,
        "判决": "正常收工",
    }
    #: 被排除的四行都调成「恰好 1000 tokens」：这样每个断言数出来的差就只可能来自一行，
    #: 不会因为 base 里那 25 个 output/cache token 把差额搅浑。
    loud = {"input_tokens": 1000, "output_tokens": 0, "cache_read": 0}
    rows = [dict(base, **{"开始": "2026-09-26T21:00:00"})]  # ✅ 区间内，合计 35
    rows.append(dict(base, **loud, **{"开始": "2026-09-26T22:00:00"}))  # ❌ 右端开
    rows.append(dict(base, **loud, **{"开始": "2026-09-26T19:59:59"}))  # ❌ 左端
    rows.append(
        dict(base, **loud, **{"开始": "2026-09-26T21:00:00", "模型": "other-model"})
    )  # ❌ 换了模型
    rows.append(dict(base, **loud, **{"开始": "2026-09-26T21:00:00", "判决": "dry run"}))  # ❌ dry
    return rows


def test_usage_in_reads_local_time_and_half_open_range(tmp_path):
    """⑧ 行里的无时区串一律按 **+08:00** 解析、区间 `[start, end)`、按模型、排除 dry run。"""
    diag = tmp_path / "gates" / "diag"
    diag.mkdir(parents=True)
    text = "\n".join(json.dumps(r, ensure_ascii=False) for r in _usage_rows())
    # 夹一行坏 JSON：读不出来就跳过，不许整份作废、也不许抛
    (diag / "wb-usage.jsonl").write_text(f"{text}\n{{坏行\n", encoding="utf-8")

    start = datetime(2026, 9, 26, 20, 0, tzinfo=TZ)
    end = datetime(2026, 9, 26, 22, 0, tzinfo=TZ)
    assert wb_dispatch.usage_in("glm-5.3-flash", start, end, root=tmp_path) == (35, 0.0)
    # 同一个瞬时换个写法（UTC）必须得到同一份读数 —— 按绝对时刻比，不按字面比
    utc = timezone.utc
    assert wb_dispatch.usage_in(
        "glm-5.3-flash", start.astimezone(utc), end.astimezone(utc), root=tmp_path
    ) == (35, 0.0)
    # 区间只有右端开：把 end 挪后 1 秒就会把那一行吃进来
    assert wb_dispatch.usage_in(
        "glm-5.3-flash", start, end + timedelta(seconds=1), root=tmp_path
    ) == (1035, 0.0)
    # 没有这份文件 ⇒ (0, 0.0)，不抛
    assert wb_dispatch.usage_in("glm-5.3-flash", start, end, root=tmp_path / "nope") == (0, 0.0)
    # 入参没时区 ⇒ 直接 TypeError（猜时区比报错糟）
    with pytest.raises(TypeError):
        wb_dispatch.usage_in("glm-5.3-flash", datetime(2026, 9, 26, 20, 0), end, root=tmp_path)


def test_usage_in_counts_registry_name_and_log_name_as_one_model(tmp_path):
    """⑩ 日志写小写裸名、注册表写 `provider/Model`：两种写法必须回同一份 tokens。

    这是卡 E97 的真实缺口：`gates/diag/wb-usage.jsonl` 的行写 `glm-5.2`，
    而调用方（整窗估算）拿的是注册表里的 `huaweicloud-maas/GLM-5.2` ——
    只比字面的话分子恒 0，看上去像「这个模型没用量」。
    """
    diag = tmp_path / "gates" / "diag"
    diag.mkdir(parents=True)
    rows = [
        dict(_usage_rows()[0], **{"模型": "glm-5.2"}),  # 日志的写法（小写裸名）
        dict(_usage_rows()[0], **{"模型": "GLM-5.2"}),  # 别人手改过的写法
        dict(_usage_rows()[0], **{"模型": "huaweicloud-maas/GLM-5.2"}),  # 注册表的写法
        dict(_usage_rows()[3]),  # other-model：一个 token 都不许算进来
    ]
    text = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
    (diag / "wb-usage.jsonl").write_text(f"{text}\n", encoding="utf-8")

    start = datetime(2026, 9, 26, 20, 0, tzinfo=TZ)
    end = datetime(2026, 9, 26, 22, 0, tzinfo=TZ)
    want = (3 * 35, 0.0)
    for name in ("glm-5.2", "GLM-5.2", "huaweicloud-maas/GLM-5.2"):
        assert wb_dispatch.usage_in(name, start, end, root=tmp_path) == want, name
    # 归一不是模糊匹配：名字只差一段的不算同一个模型
    assert wb_dispatch.usage_in("glm-5.3", start, end, root=tmp_path) == (0, 0.0)


# ---------------------------------------------------------------- ⑨ 前挡与成功


def test_holds_ok_and_the_front_gates():
    """⑨ 齐了 ⇒ `why == ""`；前挡（无限额度 / 溢出池无名 / 家庭号 / 池不符 /
    区间不含此刻）⇒ `"-"`。
    """
    end = datetime(2026, 10, 15, 0, 0, tzinfo=TZ)
    good = holds.Window(span_s=7 * 24 * 3600, used=40.0, resets_at=end)
    start, got_end, why = holds.holds_bounds(good, NOW)
    assert why == holds.HOLDS_OK
    assert (start, got_end) == (end - timedelta(days=7), end)
    # end == at ⇒ 区间不含此刻（`not end > at`）
    assert holds.holds_bounds(holds.Window(used=40.0, resets_at=NOW), NOW) == (None, None, "-")
    # start == at ⇒ 同样不含（`not start < at`）
    at_start = holds.Window(span_s=3600, used=40.0, resets_at=NOW + timedelta(hours=1))
    assert holds.holds_bounds(at_start, NOW)[2] == "-"
    # 前挡四条：无线额度 / 溢出池无名 / 家庭号 / 池不符
    for w in (
        holds.Window(used=40.0, resets_at=end, unlimited=True),
        holds.Window(used=40.0, resets_at=end, aside=True),
        holds.Window(used=40.0, resets_at=end, family="family-1"),
    ):
        assert holds.holds_bounds(w, NOW)[2] == "-"
    span = 7 * 24 * 3600
    pooled = holds.Window(span_s=span, used=40.0, resets_at=end, pool="p-a")
    assert holds.holds_bounds(pooled, NOW, pool="p-b")[2] == "-"
    assert holds.holds_bounds(pooled, NOW, pool="p-a")[2] == holds.HOLDS_OK
    # 溢出池但声明了池名 ⇒ 不算「归不到窗口」
    assert holds.holds_bounds(
        holds.Window(span_s=span, used=40.0, resets_at=end, aside=True, pool="p-a"), NOW
    )[2] == holds.HOLDS_OK
