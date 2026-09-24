"""全仓唯一的「现在」出口（T-G62）—— 为的是**验证层能钉住「今天」**。

## 为什么需要它（真实事故）

2026-09-25 00:0x：渲染黄金在 23:5x 采完、跨过午夜再跑就红了 **6 份**
（`habit` / `stats` 各 3 档宽度）—— 习惯热力图窗口是「53 周、到今天为止」且未来几天不渲染，
于是同一个星期内每过一天就多一个格子；统计页的窗口首日标签也跟着滚。
再往前一点还有同族的一条：复习线的 FSRS 步长是**分钟级**而落库只存**本地日历日**，
于是「下次到期是不是今天」还会随**几点跑**变（23:57 复习的下一步落在次日 00:07）。

两件事同一个根：**每个调用点各自去问系统时钟**。所以修法是**一处出口 + 一个测试用的假时钟**：
设了 `TIMEFLOW_FAKE_TODAY=YYYY-MM-DD` 时，`today()` / `now()` / `now_utc()` 全部落在
**那一天的本地正午**（固定到 12:00:00，所以「几点跑」也不影响结果）；**不设它时行为与
`date.today()` / `datetime.now()` 完全一致**（`tests/test_clock.py` 钉着这一点）。

## 规矩（有护栏）

- `src/timeflow/**` 里**不许**再出现裸的 `date.today()` / `datetime.now()`
  （`tests/test_clock.py` 逐文件扫；要问时间就 `from timeflow import clock`）；
- 这个环境变量**只该由验证层**设（`tools/serve.py --today` ← `tools/render_check.mjs`），
  产品路径永远不设它 —— 它不是功能开关，是**采集用的假时钟**；
- 浏览器那一侧由采集工具注入 `Date` 垫片、钉到**同一天**：否则「服务器以为是 6-15、
  浏览器以为是今天」，界面里的对账会自相矛盾 —— 那不是验证，是制造一个假的界面。

★ 来历：用户 2026-09-24 说「想一个不会漂移的验证方式」（T-G32 的起点）。
这一条补的正是那套验证里**最后一块会自己动的地方**。
"""

from __future__ import annotations

import os
from datetime import date, datetime, time, timezone

FAKE_TODAY_ENV = "TIMEFLOW_FAKE_TODAY"
# 假时钟固定落在**本地正午**：离午夜最远，「今天」这件事最不容易被日界咬到；
# 而 FSRS 那种分钟级调度也需要一个具体瞬间（正午 + 步长仍在同一天内）。
_FAKE_HOUR = 12


def fake_today() -> date | None:
    """环境变量里那个假的「今天」。

    没设、或者是写坏的值都返回 `None`（**坏值当没设**：静默改成别的行为比报错更坏）。
    """
    raw = os.environ.get(FAKE_TODAY_ENV, "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def today() -> date:
    """今天（本地日历日）—— 全仓唯一的取法。"""
    return fake_today() or date.today()


def today_iso() -> str:
    """今天的 ISO 字符串（`YYYY-MM-DD`）。"""
    return today().isoformat()


def now() -> datetime:
    """现在（本地、naive）—— 时间戳用。假时钟下 = 那一天的本地正午。"""
    fake = fake_today()
    if fake is None:
        return datetime.now()
    return datetime.combine(fake, time(_FAKE_HOUR, 0, 0))


def now_utc() -> datetime:
    """现在（UTC、aware）—— 需要「哪一个瞬间」的地方用（如 FSRS 调度）。"""
    return now().astimezone(timezone.utc)
