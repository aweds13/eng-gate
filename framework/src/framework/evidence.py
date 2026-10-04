"""证据读数：假红率 / 漏检率 / 重跑率三字段分开报（卡 186 · G8）。

> 依据 [arXiv:2302.10594]：Chromium 的 flaky 预测器**精确率 99.2%**，却把
> **76.2%** 的真回归误判成 flaky；改用失败级特征后 MCC 0.20→0.42。
> 教训：**假红与漏检必须分开度量**，一个「绿」不能代替三个数。

本模块把 G8 落成**代码 + 产物字段**：

- 三个数**成对给**（分子 + 分母，不只给一个比例 —— 比例会藏住分母太小的问题）；
- 产物里三个字段齐全（`to_dict()` 保证 `false_positive_rate` / `false_negative_rate`
  / `rerun_rate` 都在），**不许**用一个 `ok: true` 代替；
- 一个 `metrics_complete()` 守卫：三个字段缺一即红。

本模块是**纯库**：不 print、不 `sys.exit`、不读全局状态。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .gates import Verdict


# ---------------------------------------------------------------------------
# 成对给的率（分子 + 分母）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Rate:
    """一个率：**成对给**（分子 / 分母），不只给一个 float。

    ★ 为什么成对：`0/0` 与 `0/100` 都是 0.0，但含义天差地别（前者「没数据」、
    后者「100 次全没假红」）。只给比例会藏住分母太小的问题。
    """

    numerator: int
    denominator: int

    @property
    def ratio(self) -> float | None:
        """比例；分母为 0 → None（没数据，不许当成 0.0 = 完美）。"""
        if self.denominator == 0:
            return None
        return self.numerator / self.denominator

    def to_dict(self) -> dict:
        r = self.ratio
        return {
            "numerator": self.numerator,
            "denominator": self.denominator,
            "ratio": round(r, 4) if r is not None else None,
        }


# ---------------------------------------------------------------------------
# 一次门的运行读数（事后知道真实状态）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RunRecord:
    """一道门一次运行的读数 + 事后真实状态。

    `actual_ok`：**事后**知道这次运行**实际上**有没有问题（来自人工复核 / 更慢的对照门）。
    没有这个字段，假红与漏检就分不开 —— 这正是 [2302.10594] 踩的坑（只看预测器输出）。
    `attempts`：这道门这一轮跑了多少次（>1 = 重跑，flaky 的代理读数）。
    """

    name: str
    verdict: str          # pass / fail / inconclusive（照 gates.Verdict）
    actual_ok: bool       # 事后真实状态：这门这次实际上有没有问题
    attempts: int = 1     # 跑了几次（1 = 没重跑）


# ---------------------------------------------------------------------------
# G8 · 三个数
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Metrics:
    """G8 三个数分开报：假红率 / 漏检率 / 重跑率。

    - **假红率**（false positive rate）：门红了但实际没问题（flaky / 环境抖动）。
      分母 = 判红的总次数。
    - **漏检率**（false negative rate）：门绿了但实际有问题（真回归被漏）。
      分母 = 判绿的总次数。★ [2302.10594] 的 76.2% 就是这个。
    - **重跑率**（rerun rate）：同一门跑了一次以上（flaky 的代理读数）。
      分母 = 总运行条数。
    """

    false_positive_rate: Rate
    false_negative_rate: Rate
    rerun_rate: Rate

    def to_dict(self) -> dict:
        """产物字段：三个齐全（`metrics_complete()` 钉住这一点）。"""
        return {
            "false_positive_rate": self.false_positive_rate.to_dict(),
            "false_negative_rate": self.false_negative_rate.to_dict(),
            "rerun_rate": self.rerun_rate.to_dict(),
        }

    def is_green(self) -> bool:
        """三个数都为 0（且分母 > 0）才算「干净绿」。

        ★ 不许用 `True` 代替三个数 —— `to_dict()` 才是产物，`is_green` 只是便利。
        分母为 0（没数据）⇒ 不算绿（没数据不许当绿，照三值判决的 inconclusive 口径）。
        """
        fp = self.false_positive_rate
        fn = self.false_negative_rate
        rr = self.rerun_rate
        return (fp.denominator > 0 and fp.numerator == 0
                and fn.denominator > 0 and fn.numerator == 0
                and rr.denominator > 0 and rr.numerator == 0)


def metrics_from_runs(runs: list[RunRecord]) -> Metrics:
    """从一组运行读数算 G8 三个数。

    ★ 假红 = 判红且实际 ok；漏检 = 判绿且实际不 ok；重跑 = attempts > 1 的条数。
    分母各自：假红率的分母 = 判红总数；漏检率的分母 = 判绿总数；重跑率的分母 = 总条数。
    """
    fp_num = sum(1 for r in runs if r.verdict == Verdict.FAIL.value and r.actual_ok)
    fp_den = sum(1 for r in runs if r.verdict == Verdict.FAIL.value)
    fn_num = sum(1 for r in runs if r.verdict == Verdict.PASS.value and not r.actual_ok)
    fn_den = sum(1 for r in runs if r.verdict == Verdict.PASS.value)
    rr_num = sum(1 for r in runs if r.attempts > 1)
    rr_den = len(runs)
    return Metrics(
        false_positive_rate=Rate(fp_num, fp_den),
        false_negative_rate=Rate(fn_num, fn_den),
        rerun_rate=Rate(rr_num, rr_den),
    )


# ---------------------------------------------------------------------------
# 守卫：三个字段必须齐全（不许用一个「绿」代替）
# ---------------------------------------------------------------------------


def metrics_complete(metrics: Metrics) -> list[dict]:
    """G8 守卫：产物里三个字段齐全。缺一即红（返回非空 = 有缺）。

    ★ 这条钉的是「用一个 `ok: true` 代替三个数」的退化 —— [2302.10594] 的教训：
    只报一个「精确率 99.2%」就把 76.2% 的漏检藏住了。
    """
    d = metrics.to_dict()
    missing = [k for k in ("false_positive_rate", "false_negative_rate", "rerun_rate") if k not in d]
    if missing:
        return [{"constraint": "G8·三字段不全", "detail": f"缺 {missing}"}]
    # 每个字段必须有 numerator + denominator（成对给）
    for k, v in d.items():
        if not isinstance(v, dict) or "numerator" not in v or "denominator" not in v:
            return [{"constraint": "G8·不成对", "detail": f"{k} 不是成对的 (numerator, denominator)"}]
    return []


# ---------------------------------------------------------------------------
# 一个「只报绿」的退化产物（反例钉子用）
# ---------------------------------------------------------------------------


def green_only_degenerate(runs: list[RunRecord]) -> dict:
    """★ 退化产物（反例钉子用）：只报一个 `ok: true`，把三个数藏起来。

    这正是 [2302.10594] 踩的坑：只报一个「精确率 99.2%」就把 76.2% 的漏检藏住了。
    `metrics_complete()` 要咬住它 —— 钉子在 tests/test_evidence.py。
    """
    m = metrics_from_runs(runs)
    return {"ok": m.is_green()}
