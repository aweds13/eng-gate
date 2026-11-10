r"""号池模型的**只读**读取（从 `tools/pool_mcp.py` 抽，卡 106 · T-G202）。

**防什么**：派活前要能回答"这个号池现在批准了哪些模型、哪些真能用"—— 判错会派一个不存在的
模型（必失败）或擅自启用一个用户没批的模型。这里把"批准集（`models.whitelist.toml`，只有用户能改）
∩ 可用集（快照 `models.live.json`）"做成**只读、不联网、不写快照**的纯函数。

★ 边界（如实写）：这里读的是**快照**（带 `at` 时间戳），**不是现场拉取** —— 现场拉取
（`pool_models.py --check`）既要联网又会写快照文件，两样都不在这里做。号池目录**不在本仓**
（在 `jelly_ware/` 下、跨项目复用），所以从 `root` 起**逐级向上**找。
"""

from __future__ import annotations

try:
    import pipe_root
except ImportError:
    try:
        from tools import pipe_root
    except ImportError:  # pragma: no cover —— 落地桩/独立拷贝的树里没有 pipe_root
        pipe_root = None  # type: ignore[assignment]

import json
import os
import pathlib
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import tomllib

if TYPE_CHECKING:
    from collections.abc import Iterable

#: 号池内的锚点文件（用它定位号池目录）。
POOL_ANCHOR = ("infra", "pool", "pool_models.py")

#: 模型开关文件名（与号池**同目录**；跨项目共用、**只有用户能改**、UI 也是改它 —— 卡 138）。
SWITCH_FILE_NAME = "model-switches.toml"
#: 覆盖开关文件路径的环境变量（★ **只给测试用** —— 免得测试去改 infra 那份真文件）。
SWITCH_PATH_ENV = "TF_MODEL_SWITCHES"


#: 快照超过这么多小时就算**过期**（要重新探测，不许拿它当权威）。
STALE_HOURS = 24

#: 号池侧的探测入口（**仓外**，与号池同目录）：跑它才能把快照刷成今天。
PROBE_SCRIPT_NAME = "pool_models.py"
#: 探测参数（`--check` = 现拉一次并写快照；联网、写盘，两样都不在这里做）。
PROBE_ARGS = ("--check",)


def snapshot_age_hours(at: str | None, *, now: datetime | None = None) -> float | None:
    """快照距今多少小时；读不出时间戳 ⇒ ``None``（不猜）。"""
    if not at:
        return None
    try:
        stamp = datetime.strptime(str(at).strip(), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    base = now or datetime.now()
    return round((base - stamp).total_seconds() / 3600.0, 1)


def probe_command(pool: Path) -> str | None:
    """重新探测那条命令；目录里**没有**那份脚本 ⇒ ``None``（不造一条假命令）。

    路径**现算**（号池目录可以在任何祖先层级下，写死 `infra/pool/` 换台机器就废）。
    """
    script = pool / PROBE_SCRIPT_NAME
    if not script.is_file():
        return None
    return f"python -X utf8 {script.as_posix()} {' '.join(PROBE_ARGS)}"


def probe_hint(pool: Path) -> str:
    """「怎么让它变新」的一句话：有脚本给命令，没有就明说没有。

    ★ 读面三处（models / gateway / pool_mcp）都调这一份，不各自拼一句。
    """
    cmd = probe_command(pool)
    if cmd is None:
        return (
            f"重新探测：这个号池目录里没有 {PROBE_SCRIPT_NAME}"
            " ⇒ 没有可给的命令（先把它放回来）"
        )
    return f"重新探测：{cmd}"


def find_pool_dir(root: Path) -> Path | None:
    """从 `root` 逐级向上找号池目录（含 `<祖先>/infra/pool/pool_models.py` 的那个）。

    号池**不在本仓**（跨项目复用），所以不能写死相对层级 —— 逐级向上找最稳。
    """
    anchor = Path(*POOL_ANCHOR)
    for base in (root, *root.parents):
        candidate = base / "infra" / "pool"
        if (candidate / anchor.name).exists():
            return candidate
    return None


def load_pool_models(pool: Path) -> dict[str, Any]:
    """读号池的**静态产物**并求交（只读；**不联网、不写快照**）。"""
    whitelist = pool / "models.whitelist.toml"
    snapshot = pool / "models.live.json"
    approved: list[str] = []
    if whitelist.exists():
        data = tomllib.loads(whitelist.read_text(encoding="utf-8"))
        approved = [str(w["model"]) for w in (data.get("approved") or []) if w.get("model")]
    live: list[str] = []
    live_names: dict[str, str] = {}
    at = None
    if snapshot.exists():
        snap = json.loads(snapshot.read_text(encoding="utf-8"))
        live = [str(m) for m in (snap.get("live") or [])]
        live_names = {str(k): str(v) for k, v in (snap.get("live_names") or {}).items()}
        at = snap.get("at")
    in_both = [m for m in approved if m in set(live)]
    age = snapshot_age_hours(at)
    # ★ 卡 320 修：`at` **有值但读不出来** ⇒ 必须算过期（否则字段说"不过期"、文案说
    #   "当过期处理"，同一份数据两个答案）。`at` 本身为空 = 「没记录」，不等于过期。
    unreadable = bool(at) and age is None
    stale = unreadable or (age is not None and age > STALE_HOURS)
    if unreadable:
        note = (
            "快照时间戳读不出来 ⇒ 当过期处理（先重新探测再派活）；"
            + probe_hint(pool)
        )
    elif stale:
        note = (
            f"快照已过期 {age} 小时（上限 {STALE_HOURS}h）⇒ 先重新探测再派活；"
            + probe_hint(pool)
        )
    else:
        note = ""
    return {
        "pool_dir": pool.as_posix(),
        "whitelist": whitelist.name,
        "whitelist_exists": whitelist.exists(),
        "snapshot": snapshot.name,
        "snapshot_exists": snapshot.exists(),
        "snapshot_at": at,
        "approved": approved,
        "live": live,
        "live_names": live_names,
        "in_both": in_both,
        "approved_but_missing": [m for m in approved if m not in set(live)],
        "live_but_unapproved": [m for m in live if m not in set(approved)],
        # ★ 快照是**静态产物**：过期就得重新探测，不许拿几天前的名单当权威（卡 320）
        "snapshot_age_hours": age,
        "snapshot_stale": stale,
        "snapshot_stale_hours": STALE_HOURS,
        "snapshot_note": note,
    }


# ---------------------------------------------------------------- 模型开关文件（卡 138 · T-G236）
# 用户要「按一下就 true/false」的开关 ⇒ 开关必须是**数据、不是代码**（改源码 + 跑门禁太贵）。
# 形态：`[switch]` 段里 `"<模型裸名>" = true|false`；`true` = 额外放行（**只做加法**，不进轮换链）。


class SwitchFileError(ValueError):
    """模型开关文件**坏了**（TOML 解析失败 / 值不是布尔）—— 带**路径与行号**。

    ★ 为什么单独一个异常类、且**绝不静默当空**：静默当空会让「我明明开了」变成「实际没开」
      —— 正是本仓反复吃过的「看着绿其实没查」。坏文件必须**响亮地**失败并**点名**哪份、哪一行。
    """


def _line_of(exc: BaseException) -> int | None:
    """TOML 解析错的行号（3.13+ 有 lineno 属性；3.12 只能从消息里取）。

    ★ 卡 E49：`getattr(exc, "lineno", None)` 在 3.12 上恒为 None ⇒ 「点名哪一行」的判据在云机
      退化成「没有行号」，钉子当场红。两路都取：先属性，再从 `at line N, column M` 里抓。
    """
    attr = getattr(exc, "lineno", None)
    if isinstance(attr, int):
        return attr
    m = re.search(r"at line (\d+)", str(exc))
    return int(m.group(1)) if m else None


def switch_file_path(pool_dir: Path | None = None) -> Path | None:
    """开关文件路径：`TF_MODEL_SWITCHES` 覆盖 > 显式 `pool_dir` > `find_pool_dir()`。

    池目录都找不到 ⇒ `None`（调用方按「没有开关文件」处理 —— **不报错**）。
    ★ 复用 `find_pool_dir()`，**不另写一份路径查找**（起点 = 本模块所在仓库根）。
    """
    override = os.environ.get(SWITCH_PATH_ENV)
    if override:
        return Path(override)
    if pool_dir is not None:
        return Path(pool_dir) / SWITCH_FILE_NAME
    root = (pipe_root.data_root() if pipe_root is not None
            else pathlib.Path(__file__).resolve().parents[2])
    pool = find_pool_dir(root)
    return None if pool is None else pool / SWITCH_FILE_NAME


def _switch_line(text: str, key: str) -> int | None:
    """在原文里找 `"<key>" = …` 那一行（1 起）；找不到 → None。只用于**报错点名行号**。"""
    forms = (f'"{key}"', f"'{key}'", key)
    pattern = re.compile(r"^\s*(?:" + "|".join(re.escape(f) for f in forms) + r")\s*=")
    for lineno, line in enumerate(text.splitlines(), start=1):
        if pattern.match(line):
            return lineno
    return None


def _validate_switch_pairs(path: Path, text: str,
                           pairs: list[tuple[str, Any]]) -> dict[str, bool]:
    """验证一批 ``(key, value)`` 都是布尔 → 收成字典；非布尔 ⇒ `SwitchFileError` 点名行号。"""
    out: dict[str, bool] = {}
    for key, value in pairs:
        if not isinstance(value, bool):
            line = _switch_line(text, key)
            where = f"{path}（第 {line} 行）" if line else str(path)
            raise SwitchFileError(f"模型开关文件坏：{where} 的「{key}」必须是布尔"
                                  f"（true / false），实际是 {type(value).__name__}（{value!r}）")
        out[str(key)] = value
    return out


def load_switches(pool_dir: Path | None = None, *, pool: str | None = None) -> dict[str, bool]:
    """读**外部开关文件**（按池分段；**只读**、不写、不联网）。

    语义（卡 138 / 卡 166 按池）：
      · ``pool=None`` 或 ``"codebuddy"``：读 ``[switch]`` 顶层布尔键（向后兼容）
        **外加** ``[switch.codebuddy]`` 子表；
      · ``pool="codearts"`` / 其他：只读 ``[switch.<pool>]`` 子表；
      · 文件**不存在**（或池目录都找不到）⇒ **空字典**、**不报错**；
      · 文件**坏**（TOML 解析失败 / 值不是布尔）⇒ `SwitchFileError` **点名路径与行号**
        —— ★ **不许静默当空**。
    ★ 只回答「哪些模型被开关打开」，**不碰任何名单常量**（名单是下限，开关是加法）。
    ★ 向后兼容：旧文件只有 ``[switch]`` 段（无子表）⇒ ``pool="codebuddy"`` 仍读到它
      （卡 166 判据 ⑥：今天 CodeBuddy 池行为一字不变）。
    ★ ``pool_dir`` 仍是第一个位置参数（向后兼容旧调用 ``load_switches(tmp_path)``）；
      ``pool`` 是关键字参数。
    """
    path = switch_file_path(pool_dir)
    if path is None or not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        line = _line_of(exc)
        where = f"{path}（第 {line} 行）" if line else str(path)
        raise SwitchFileError(f"模型开关文件解析失败：{where} —— {exc}") from exc
    switch = data.get("switch")
    if switch is None:
        return {}
    if not isinstance(switch, dict):
        raise SwitchFileError(f"模型开关文件坏：{path} 的 `[switch]` 必须是表，"
                              f"实际是 {type(switch).__name__}")
    effective_pool = pool or "codebuddy"
    if effective_pool == "codebuddy":
        pairs: list[tuple[str, Any]] = []
        for key, value in switch.items():
            if isinstance(value, dict):
                continue
            pairs.append((str(key), value))
        sub = switch.get("codebuddy")
        if isinstance(sub, dict):
            for key, value in sub.items():
                pairs.append((str(key), value))
        return _validate_switch_pairs(path, text, pairs)
    sub = switch.get(effective_pool)
    if not isinstance(sub, dict):
        return {}
    return _validate_switch_pairs(path, text, list(sub.items()))


def _names(items: Iterable[str] | None) -> list[str]:
    """把任意可迭代的名字收成**去重、保序、去空白**的字符串列表。"""
    out: list[str] = []
    for item in items or []:
        name = str(item).strip()
        if name and name not in out:
            out.append(name)
    return out


def _provider_form(names: list[str]) -> bool:
    """这份名单是不是 `provider/model` 形式（含 `/`）—— 「id 体系一眼判据」。"""
    return any("/" in name for name in names)


def compare_rosters(local_names: Iterable[str] | None,
                    pool_models: dict[str, Any] | None = None) -> list[str]:
    """对账两份模型白名单 —— 回**人话问题列表**（空列表 = 没漂）。

    为什么有它（卡 132 · T-G229）：本仓那份（`wb_dispatch.MODEL_WHITELIST` +
    `ONE_OFF_MODELS`，**裸名**）与号池那份（`models.whitelist.toml` 的 `approved`，
    `provider/model` 形式）**已经实际发散**，同一个问题「现在能用什么模型」两个工具会给
    **不同答案**，且此前**没有对账判据**。这里就是那条判据。

    - `local_names`：本仓名单（★ 由调用方传进来，**不**在这里 import `wb_dispatch` ——
      那是 CLI 层，反向依赖会分层倒置/成环）。
    - `pool_models`：`load_pool_models()` 的返回值（仓外那份批准集）。

    返回三类问题：① 只在**本仓**有、② 只在**池**有、③ 两边**id 体系不同**
    （`deepseek-v4.1-flash` 这种裸名与 `huaweicloud-maas/GLM-5.2` 这种 `provider/model`
    **不能**硬对成同一件事 —— 所以第 ③ 类会点明「要合并的话得先定一套 id 口径」）。

    ★ **只报告，绝不自动改名单**（白名单只有用户能改；池里新增模型只报告、不自动启用）——
      真要合并成一处是**用户的决定**。纯函数：吃数据、回问题，**不读文件、不联网、不 print**。
    """
    local = _names(local_names)
    approved = pool_models.get("approved") if isinstance(pool_models, dict) else None
    pool = _names(approved)
    pool_set, local_set = set(pool), set(local)
    only_local = [n for n in local if n not in pool_set]
    only_pool = [n for n in pool if n not in local_set]
    if not only_local and not only_pool:
        return []
    problems: list[str] = []
    if local and pool and _provider_form(local) != _provider_form(pool):
        problems.append(
            f"id 体系 / 口径不同：本仓用裸名（如 {local[0]}），池用 provider/model"
            f"（如 {pool[0]}）—— 两份名单不能逐字对成同一件事；要合并的话得先定一套 id 口径")
    if only_local:
        problems.append(f"只在本仓白名单（池的批准集里没有）：{'、'.join(only_local)}")
    if only_pool:
        problems.append(f"只在池批准集（本仓白名单里没有）：{'、'.join(only_pool)}")
    return problems
