r"""谁在花谁的钱（卡 A348 · `T-AG551`；移植 magpie F32 的「调用方名册」）。

★ 三条边界（逐字，别越）：

1. **本模块不持有凭据**：不生成任何密钥、不做常量时间比较、不写 `0600` 权限。
   理由：pool 的写面是本地 stdio 的 MCP，对手是「同一台机器上的另一个进程」——
   密钥与文件权限都挡不住同一个用户；把凭据搬进来只会让人**误以为**「有它就安全」。
2. `off` 是**唯一**可撤语义：撤一个人 = 把 `off` 改成 `true`，**不删行**。删行会让
   「谁曾经能派活」这段历史消失，也让下一次核对误以为他从没存在过。
3. 本模块**只读**名册；写入由人改 TOML。不做 `.bak` 兜底 —— 撤掉的行从备份复活是最坏的回归。

## 名册在哪（三段，与 `tools/pool/limits.py` 的 `limits_path` 同形状）

`TF_POOL_CALLERS` 覆盖 > 号池目录（从仓库根逐级向上找 `infra/pool/`）下的 `callers.toml`
> 仓根下同一条相对路径。**锚点从仓库根找，不跟 cwd 走**。

## 「空」的两种意思 —— 与既有两处**方向相反**，别统一

- 本模块：`models` / `accounts` 为空或没写 ⇒ **全允许**（逐字照 magpie `access.go:111`）。
  名册是**加法**：没登记的人不是「被拒」，只是「没被点名收窄」。
- `tools/pool/plan.py` 的 `WILDCARD_CHARS`：`files` 里见通配字符就**拒单**。
- `tools/pool/guards.py` 的 `domain_guard`：**空域 = 全拒**
  （「空域不是『过了』，而是没东西可判」）。
  后两处判的是**冲突域**（「这批活与别人的活有没有相交」）：空 = 判不出来 ⇒ fail closed；
  本模块判的是**白名单**（「这个人有没有被点名收窄」）：空 = 没人收窄他 ⇒ 放行。
  同名的「空」在两个方向上都是对的，所以**不许**把它抽成一个共用函数。

## 名册形状（`callers.toml`，人改）

    # 撤一个人 = 改这一行，不删这一段
    [caller."alice"]
    label = "外包 A"
    off = false
    models = []            # 空 = 全允许
    accounts = []          # 空 = 全允许

★ 文件不存在 ⇒ `{}`（没配 = 没闸，这是「没要求」）；文件**在但读不懂** ⇒ 抛
  `CallersError`。这两件事**必须分开** —— 把坏的当空 = 悄悄松开一条判据。
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from pathlib import Path

import tomllib

#: 本树根（`tools/pool/callers.py` 往上三层）—— 与 `tools/pool/limits.py` 的 `TOOL_ROOT` 同口径
TOOL_ROOT = Path(__file__).resolve().parent.parent.parent
#: 号池目录锚点 —— 与 `tools/pool/limits.py` 的 `POOL_ANCHOR` 逐字同形状
POOL_ANCHOR = ("infra", "pool")
#: 名册文件名
CALLERS_NAME = "callers.toml"
#: 覆盖位点（多树并存与测试用；不给就按锚点推）
ENV_CALLERS = "TF_POOL_CALLERS"
#: 名册里每个人的段名（`[caller."<id>"]`）
_SECTION = "caller"
#: 每段只认这四个键 —— 多一个都算写坏了（`deleted` / `revoked` / `removed` 一律拒）
_KNOWN_KEYS = frozenset({"label", "off", "models", "accounts"})


class CallersError(ValueError):
    """名册损坏 / 写坏 —— 响亮拒绝，**绝不**回落到 `{}`（回落 = 悄悄松开判据）。"""


@dataclass(frozen=True, slots=True)
class Caller:
    """一个调用方：**恰五个字段**，没有一个跟凭据有关。

    `models` / `accounts` 为空元组 = **全允许**（名册是加法，见模块 docstring）。
    """

    id: str
    label: str = ""
    off: bool = False
    models: tuple[str, ...] = ()
    accounts: tuple[str, ...] = ()


def pool_dir(start: Path | None = None) -> Path | None:
    """号池目录（含 `infra/pool/` 的那一层）；找不到回 `None`。

    ★ **不跟 cwd 走**：从 `TOOL_ROOT`（或显式 `start`）逐级向上找。`Path.cwd()` 版本会跟着
    进程的工作目录跑 —— 换个 cwd 就换一个号池目录，判据被绑在宿主目录形状上。
    """
    base = (start or TOOL_ROOT).resolve()
    for cand in (base, *base.parents):
        target = cand.joinpath(*POOL_ANCHOR)
        if target.is_dir():
            return target
    return None


def callers_path() -> Path:
    """名册路径：`TF_POOL_CALLERS` 覆盖 > 号池目录 > 仓根下的同一条相对路径。"""
    override = os.environ.get(ENV_CALLERS, "").strip()
    if override:
        return Path(override).expanduser()
    found = pool_dir()
    base = found if found is not None else TOOL_ROOT.joinpath(*POOL_ANCHOR)
    return base / CALLERS_NAME


def _as_names(value: object, *, where: str) -> tuple[str, ...]:
    """`models` / `accounts`：字符串数组 ⇒ 元组；空数组**原样收成空元组**（= 全允许）。"""
    if not isinstance(value, list):
        raise CallersError(
            f"{where} 必须是字符串数组，读到的是 {type(value).__name__}：{value!r}"
        )
    names: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise CallersError(f"{where} 里有写坏了的条目：{item!r}（空串或非字符串）")
        names.append(item.strip())
    return tuple(names)


def _as_caller(section: object, *, cid: str, where: str) -> Caller:
    """把一段 `[caller."<id>"]` 校验成一个 `Caller`；**任何写坏都抛**，不猜、不补默认。"""
    if not isinstance(section, dict):
        raise CallersError(f"{where} 必须是一段表，读到的是 {type(section).__name__}")
    unknown = sorted(str(key) for key in section if key not in _KNOWN_KEYS)
    if unknown:
        raise CallersError(
            f"{where} 有认不识的键：{'、'.join(unknown)}"
            f"（只认 {'、'.join(sorted(_KNOWN_KEYS))}；撤一个人改 `off`，"
            "不许拿删行 / 改名 / 加一个 `deleted` 当撤）"
        )
    label = section.get("label", "")
    if not isinstance(label, str):
        raise CallersError(f"{where} 的 label 必须是字符串，读到的是 {type(label).__name__}")
    off = section.get("off", False)
    if not isinstance(off, bool):
        raise CallersError(f"{where} 的 off 必须是布尔，读到的是 {type(off).__name__}：{off!r}")
    return Caller(
        id=cid,
        label=label,
        off=off,
        models=_as_names(section.get("models", []), where=f"{where} 的 models"),
        accounts=_as_names(section.get("accounts", []), where=f"{where} 的 accounts"),
    )


def load_callers(path: Path | str | None = None) -> dict[str, Caller]:
    """读名册。文件不存在 ⇒ `{}`；文件**在但读不懂** ⇒ `CallersError`（**别当没配**）。

    ★ 纪律逐字照 `tools/pool/lanes.py` 的 `load_lanes`：把坏的当空 = 悄悄松开一条判据，
    正是本仓最忌的那种「判不出来就放行」。
    """
    target = Path(path) if path is not None else callers_path()
    if not target.exists():
        return {}
    try:
        with target.open("rb") as handle:
            raw = tomllib.load(handle)
    except (tomllib.TOMLDecodeError, OSError) as exc:
        raise CallersError(f"调用方名册读不了（{target}）：{exc} —— 修好它，别当没配") from exc
    unknown_sections = sorted(str(key) for key in raw if key != _SECTION)
    if unknown_sections:
        raise CallersError(
            f"名册里认不识的段：{'、'.join(unknown_sections)}"
            f"（只认 [{_SECTION}.\"<id>\"] —— 段名就是 id，不许另起一层）"
        )
    section = raw.get(_SECTION, {})
    if not isinstance(section, dict):
        raise CallersError(f"[{_SECTION}] 必须是一段表，读到的是 {type(section).__name__}")
    roster: dict[str, Caller] = {}
    for key, body in section.items():
        cid = str(key).strip()
        if not cid:
            raise CallersError(f"[{_SECTION}] 里有一段的调用方 id 是空的")
        where = f'[{_SECTION}."{cid}"]'
        roster[cid] = _as_caller(body, cid=cid, where=where)
    return roster


def resolve(explicit: str = "", *, env_window: str = "") -> Caller:
    """这个人是名册里的谁：显式 > 窗口 > `<hostname>:<pid>`（前两级与 `default_owner()` 同口径）。

    ★ 本模块**自己不读环境**：`TF_WINDOW_ID` 由调用方取好传进来（只有 `TF_POOL_CALLERS`
    那段算例外 —— 那是**定位**文件，不是**认**人）。
    ★ 名册里查不到 ⇒ 回一个只有 `id` 的 `Caller`，**不报错** —— 名册是**加法**：
    没登记的人只是「没被点名」，不是「被拒」。
    """
    chosen = str(explicit or "").strip()
    if not chosen:
        chosen = str(env_window or "").strip()
    if not chosen:
        chosen = f"{socket.gethostname()}:{os.getpid()}"
    known = load_callers().get(chosen)
    if known is not None:
        return known
    return Caller(id=chosen)


def is_off(caller: Caller) -> bool:
    """这个人被撤了吗（`off = true`）—— 「撤」唯一的形态。"""
    return bool(caller.off)


__all__ = [
    "CALLERS_NAME",
    "ENV_CALLERS",
    "POOL_ANCHOR",
    "TOOL_ROOT",
    "Caller",
    "CallersError",
    "callers_path",
    "is_off",
    "load_callers",
    "pool_dir",
    "resolve",
]
