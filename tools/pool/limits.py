r"""限额策略的**读法与缺席判据**（卡 A336 · T-AG538 · 设计原件 F70 §3；数据文件是 F33 的活）。

**防什么**：`limits.toml`（F33 引入，仓外、与 `accounts.toml` 同目录）是一份**策略**。
策略文件的经典事故是：**声明了限额，但表读不出来 —— 于是被当成「没限额」放行**。
magpie 为这一态专门留了一整条具名错误 `ErrUnlimited`（`internal/gwbudget/gwbudget.go:97-99`）：
有 key、该 key 有 limit、却拿不到 limiter ⇒ **什么都不发**。本模块把这半条移植过来。

**两个方向都要判**（只抄一半会把没设限额的卡全停掉）：

- 有要求（本卡**显式声明**了，或表里有 `[default]` 兜底）**且**表读不出 ⇒ 抛 `NotLimited`；
- 没要求 ⇒ **一律不抛**。逐字对应 magpie `gwbudget.go:102`：
  `if who.KeyID == "" || len(who.Limits()) == 0 { return nil, nil }` —— 无 limit 的请求永不过问。

★ **本卡不引入 `limits.toml` 的真实数据文件**（那是 F33 的活）：这里只立判据与读法。
  所以今天 `LIMITS_PATH` 指的那份文件不存在是**正常态**，`assert_serving` 在真实接入点上
  恒不抛（没有声明 ⇒ 没有要求）。

★ 边界（如实写，**未核到**的部分明说）：`load_limits()` 读不出来一律回 `{}`（设计口径），
  于是「表坏了、但我不知道这张卡有没有声明」这一态**今天读不出来** —— 它与「根本没声明表」
  在 `{}` 里长得一样。这不是本卡能修的：要修得让 `load_limits` 换成「保留声明位」的形态
  （F33 建数据文件时一并定）。记录在此，不许当成已解决。

★ 本模块**不联网、不写文件、不看钟**；也不 import 任何 pool 模块（只 import `failclosed`，
  而它自己不 import 任何 pool 模块 ⇒ 不会成环，`guards.py` 那条纯函数边安全）。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import tomllib

from pool import failclosed
from pool.failclosed import NotLimited

if TYPE_CHECKING:
    from collections.abc import Mapping

TOOL_ROOT = Path(__file__).resolve().parent.parent.parent
#: 环境变量覆盖（**只给测试与换机器用**：免得测试去碰仓外那份真文件）。
LIMITS_ENV = "TF_POOL_LIMITS"
#: 策略文件名（与 `accounts.toml` 同目录）。
LIMITS_NAME = "limits.toml"
#: 与 `pool_accounts.ANCHOR` 同形状的锚点：靠它从仓库根向上定位号池目录。
POOL_ANCHOR = ("infra", "pool")


def pool_dir(start: Path | None = None) -> Path | None:
    """从 `start`（默认本文件所在仓根）向上找号池目录（含 `infra/pool/` 的那个）。

    号池**不在本仓**（跨项目复用），所以不能写死相对层级 —— 逐级向上找最稳
    （与 `tools/pool/models.py::find_pool_dir` 同一套找法，只是不要求锚点文件存在：
    `limits.toml` 今天本来就还没有）。
    """
    base = (start or TOOL_ROOT).resolve()
    for cand in (base, *base.parents):
        target = cand.joinpath(*POOL_ANCHOR)
        if target.is_dir():
            return target
    return None


def limits_path() -> Path:
    """策略文件位址：`TF_POOL_LIMITS` 覆盖 > 号池目录下的 `limits.toml` > 仓根下同路径。"""
    override = os.environ.get(LIMITS_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    found = pool_dir()
    return (found if found is not None else TOOL_ROOT.joinpath(*POOL_ANCHOR)) / LIMITS_NAME


#: `assert_serving(..., path=...)` 的默认口径来源（人该去看哪里）。**不是**判据本身。
LIMITS_PATH = limits_path()


def load_limits(path: Path | str | None = None) -> dict[str, object]:
    """读策略表：`{账号 or "default": 限额段}`；**读不出来一律回 `{}`，本函数自己不抛**。

    ★ 为什么自己不抛：「表在不在」与「这张卡有没有要求」是两件事，只有后者能决定拒不拒。
      把两者混在一个函数里，就会出现「表不存在 ⇒ 抛 ⇒ 连没声明限额的卡也派不出去」。
      判决只归 `assert_serving`（判据只许一份）。
    ★ 空表 / 空文件 / 坏 TOML / 没权限 / 是目录 ⇒ 全都回 `{}`（同一条「读不出来」）。
    """
    target = Path(path) if path is not None else LIMITS_PATH
    try:
        with open(target, "rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError, ValueError):
        return {}
    return dict(data) if isinstance(data, dict) else {}


def has_requirement(card: str, limits: Mapping[str, object]) -> bool:
    """这张卡**有没有**额度要求 —— `card` 显式声明，或表里有 `default` 兜底。

    ★ 「有要求」必须是**显式声明**的，不许从「表非空」推：表里只有别人的段，
      不等于这张卡受管（F70 §3 边界条件第一条）。
    ★ 逐字对应 magpie `gwbudget.go:102` 的**反方向**：`len(who.Limits()) == 0 ⇒ return nil, nil`。
    """
    if not limits:
        return False
    if card in limits:
        return True
    return "default" in limits


def assert_serving(card: str, limits: Mapping[str, object], *, path: Path | str) -> None:
    """这张卡**声明了**限额，但限额表读不出来 ⇒ 抛 `NotLimited`（**不许**当成「没限额」放行）。

    判据：`card in limits`，或 `limits` 非空且 `"default" in limits` ⇒ **有要求**；
          有要求且 `path` 不存在 / 读不出 ⇒ `NotLimited`（文案含 `path`，人知道去看哪）。
          没要求 ⇒ **一律不抛**。
    ★ 逐字对应 magpie `gwbudget.Limiting()`（`:101-124`）：有 limit 而无 limiter ⇒ `ErrUnlimited`。
    ★ 反方向也必须判：卡没声明、表也不存在 ⇒ 不抛（无 limit 的请求 magpie 永不过问）。
      两个方向合起来才是完整移植，只抄一半会「把没设限额的卡全停掉」。
    """
    if not has_requirement(card, limits):
        return
    target = Path(path)
    try:
        with open(target, "rb") as fh:
            raw = fh.read()
        tomllib.loads(raw.decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        # 文案一律经 `failclosed.refuse()` 造（同一个模板只此一处，不在这里另写一句）。
        raise NotLimited(str(failclosed.refuse(
            f"卡 {card} 要求按限额派活",
            what="这张卡声明的限额",
            where=str(target),
        ))) from exc
