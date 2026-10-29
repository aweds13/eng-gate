r"""判不出来的时候，pool 该拒还是该放（卡 A336 · 台账号 T-AG538 · 设计原件 F70）。

★ 逐字移植 magpie 的两条 fail-closed，并**明确不移植**它的 fail-open：

  · Masker fail closed  → 本模块 `NotServing`
      magpie `internal/gwmw/gwmw.go:250-252` 的 `ErrUnmasked`：遮蔽器不在 ⇒ 请求一个字节都不发
      （`gwmw.go:279-288` 的 `Safely[T]` 逐字 "masking failed, so nothing was sent"）。
  · budget fail closed  → 本模块 `NotLimited`
      magpie `internal/gwbudget/gwbudget.go:97-99` 的 `ErrUnlimited`：有 key 且该 key 有 limit、
      却拿不到 limiter ⇒ 什么都不发。
  · Agent fail open     → **不移植**。pool 没有「可选扩展点」这种架构；
      在 pool 里造一个 fail-open 点等于主动放松判据
      （`_pool_capability_map.md` D5：只有用户能放松判据）。

★ 本模块**不含任何判据**：它只定义「判不了」的**类型与文案**。
  判据仍在 `guards` / `registry` / `model_registry` / `pool_accounts` / `limits` 里，
  一份不多、一份不少。

★ **不 import 任何 pool 模块**（只 `from __future__`）：`tools/pool/guards.py` 是纯函数模块，
  文件头逐字「不 import registry（不然成环）」；本模块若反向依赖它，那条边就成环了。

★ 语义差别（照 F70 §2 记在这里，别当成同一件事）：magpie 的 fail-closed 保护的是**用户的隐私
  与钱**（遮蔽、限额），pool 的 fail-closed 保护的是**仓的完整性与别人的活**（域、树、锁、账本）。
  被保护对象不同，但「判不了 ⇒ 不动手」完全相同 —— 这才是可以逐字移植的那部分。
"""

from __future__ import annotations


class NotServing(RuntimeError):  # noqa: N818 —— 名字就是设计原件 F70 §3 的判据原文（沿用 gate_pool.CloudUnreachable 的口径）
    """某个判据的**服务方**不在（读不到源文件 / 池没接 / 表缺失）。

    文案模板逐字抄 magpie `gwmw.ErrUnmasked` 与 `gwbudget.ErrUnlimited` 的**结构**：
    「<要求是什么>，但 <谁> 不在服务，所以 <什么都没做>；<去看哪个文件>」。
    ★ 文案必须读得出是**拒绝**：不许写成「已经过 / 已不受限」这类**放行**的说法
      （禁词清单与静态钉子见 `tests/test_pool_failclosed.py::BANNED`）。

    ★ 继承链是 `RuntimeError`，**不是** `ValueError`：`ValueError` 在本仓表示「你给的配置坏了」
      （`LanesError` / `RpmError` / `ScopeError` 都继承它），与「服务不在」是两件事。
    """


class NotLimited(NotServing):
    """有额度要求，但没有任何限额判据在服务 ⇒ **不派活**。

    逐字对应 magpie `gwbudget.ErrUnlimited`（`internal/gwbudget/gwbudget.go:97-99`）：
    有 key 且该 key 有 limit、却拿不到 limiter ⇒ 什么都不发。
    pool 侧的对等物：这张卡**声明了** `limits.toml` 的限额，但 `limits.toml` 读不出来 /
    条目坏掉 ⇒ 不派活（判据在 `tools/pool/limits.py::assert_serving`）。
    """


def refuse(problem: str, *, what: str, where: str) -> NotServing:
    """造一条「判不了，所以不做」的拒绝。三个参数强制都要给，缺一个就是 TypeError。

    `problem` = 要求是什么（例：「卡 A1 要求按限额派活」）；
    `what`    = 哪个服务没在服务（例：「这张卡声明的限额」）；
    `where`   = 人该去看哪里（例：「infra/pool/limits.toml 第 3 条」）。

    ★ 不许只给一句话：magpie 的三条具名错误**每条都带了「该怎么办」**
      （turn the plugin on in Settings → Plugins）。只说「失败」的错误，在现场等于没有信息。
    ★ `what` / `where` 是 **keyword-only 且无默认值** —— 这是「强制都要给」的可执行口径：
      少给一个直接 TypeError，而不是悄悄生成一条没头没尾的文案。
    """
    text = f"{problem}，但「{what}」不在服务，所以什么都没做；去看 {where}"
    return NotServing(text)
