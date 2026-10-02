r"""号池模型的**只读**读取（从 `tools/pool_mcp.py` 抽，卡 106 · T-G202）。

**防什么**：派活前要能回答"这个号池现在批准了哪些模型、哪些真能用"—— 判错会派一个不存在的
模型（必失败）或擅自启用一个用户没批的模型。这里把"批准集（`models.whitelist.toml`，只有用户能改）
∩ 可用集（快照 `models.live.json`）"做成**只读、不联网、不写快照**的纯函数。

★ 边界（如实写）：这里读的是**快照**（带 `at` 时间戳），**不是现场拉取** —— 现场拉取
（`pool_models.py --check`）既要联网又会写快照文件，两样都不在这里做。号池目录**不在本仓**
（在 `jelly_ware/` 下、跨项目复用），所以从 `root` 起**逐级向上**找。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import tomllib

if TYPE_CHECKING:
    from collections.abc import Iterable

#: 号池内的锚点文件（用它定位号池目录）。
POOL_ANCHOR = ("infra", "pool", "pool_models.py")


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
    }


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
