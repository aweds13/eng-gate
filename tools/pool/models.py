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
from typing import Any

import tomllib

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
