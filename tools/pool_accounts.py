#!/usr/bin/env python
"""账号账本与只读探测（卡 E45 / T-AG496）。

回答三个问题，一个动作都不许写（本卡是纯只读面）：
  * 哪些平台能自动签到、要什么凭据、走哪个端点 —— 见 tools/pool/platforms.toml；
  * 我本机有哪些号、状态如何、额度多少 —— 见仓外账本 infra/pool/accounts.toml；
  * 账本里声明的凭据位点还在不在（**只 stat，绝不读内容**）。

用法：
    python -X utf8 tools/pool_accounts.py list [--json] [--all]
    python -X utf8 tools/pool_accounts.py show <账号 id> [--json]
    python -X utf8 tools/pool_accounts.py discover [--json]
    python -X utf8 tools/pool_accounts.py probe [--json] [--offline] [--platform X]
    python -X utf8 tools/pool_accounts.py due [--json] [--now ISO] [--platform X]
    python -X utf8 tools/pool_accounts.py --selftest

退出码：0 = 正常（含「未探测」）；2 = 用法/账本缺失/账本格式错。

★ 账本写入只有一处例外：`saved_refresh_failed()`（卡 A335 —— **供应商拒绝刷新**才打吊销标记，
  其余一律一个字节都不写）；`probe` **也写** —— 只写 `[account.health]` 的 `state` /
  `consecutive_failures` / `last_probe` 三键（卡 E121），别的一个字节都不写。
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import importlib.util
import json
import math
import os
import re
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import tomllib

if TYPE_CHECKING:  # 只在注解里用（本文件已开 `from __future__ import annotations`）
    from collections.abc import Iterator

try:  # 与 tools/pool/*.py 同一套降级：落地桩只拷部分文件，缺 pipe_root 也不许炸
    import pipe_root
except ImportError:
    try:
        from tools import pipe_root  # type: ignore[no-redef]
    except ImportError:  # pragma: no cover —— 独立拷贝的树
        pipe_root = None  # type: ignore[assignment]

TOOL_ROOT = Path(__file__).resolve().parent.parent
#: 留档与日志落**数据根**（门禁在卡树跑时数据根就是卡树，见 tools/pipe_root.py）——
#: 不许用 `__file__` 推，那样门禁在卡树跑会把留档写回主树。
DATA_ROOT = pipe_root.data_root() if pipe_root is not None else TOOL_ROOT
ANCHOR = ("infra", "pool", "accounts.toml")
TZ = timezone(timedelta(hours=8))
SAMPLES_CAP = 20
STATES = ("active", "limited", "exhausted", "expired", "disabled")
#: `[account.health].state` 的五值（卡 E45 枚举，卡 E121 把它搬到写路径上校验）。
#: ★ 与顶层 `STATES` **不是**一套：那五个是人判定的「这个号还能不能用」，
#:   这五个是「最近一次探测/签到看到的健康态」。加值要同卡改本常量 + 文档三处。
HEALTH_STATES: frozenset[str] = frozenset(
    {"ok", "degraded", "quota-exhausted", "auth-expired", "unknown"}
)
CRED_KINDS = ("file", "dir", "keychain", "cookie_jar", "env", "none")
SECRET_RE = re.compile(r"(?i)(bearer\s+)?(sk-|ak-|ghp_|xoxb-)[A-Za-z0-9_\-]{8,}")

EXIT_OK, EXIT_USAGE = 0, 2
#: 有号需要人看（uncertain/failed）—— 与「用法错」分开，脚本能分辨
EXIT_NEEDS_HUMAN = 1

#: 闸：关掉「账号发现」。照 `internal/provider/discovery.go:29` 的形状 ——
#: magpie 那边问的是 `settings.AccountDiscoveryOff()`，pool 的设置面在号池目录，
#: 但「关掉发现」比读号池文件更早：读 accounts.toml 就已经在发现账号了。所以只能是 env。
ACCOUNT_DISCOVERY_ENV = "TF_NO_ACCOUNT_DISCOVERY"
#: 只有这四个算「关」。`""`（空串等于没设）/ `"0"` / `"false"` / `"no"` / `"off"`
#: 与认不出来的取值一律当「没关」—— 默认必须不关，写成关会让 7 个位点凭空消失。
DISCOVERY_OFF_VALUES: frozenset[str] = frozenset({"1", "true", "yes", "on"})
#: 闸文案：照 `discovery.go:29` 的形状，但只留一句、**不带任何路径**（判据 7）。
DISCOVERY_OFF_MESSAGE = (
    "account discovery is off（TF_NO_ACCOUNT_DISCOVERY 取真值 ⇒ 不碰任何账号位点）"
)


class DiscoveryOffError(RuntimeError):
    """闸关掉了：不许碰任何账号位点（照 `internal/provider/discovery.go:29` 的形状）。

    设计原件里叫 `DiscoveryOff`；ruff `N818` 要求异常名带 `Error` 后缀，而本卡禁令不许写
    `# noqa`（先例 `RefreshRefused` 是靠 noqa 过的，本卡不抄）。
    """

    def __init__(self, message: str = DISCOVERY_OFF_MESSAGE) -> None:
        super().__init__(message)


def discovery_off() -> bool:
    """闸：`TF_NO_ACCOUNT_DISCOVERY` 取真值 ⇒ 关掉发现。**默认不关**。

    空串等于没设（与 `tools/pool/models.py` 的 `SWITCH_PATH_ENV` 同体例）。
    判据只问一次，而且问在「碰位点」之前 —— 不是「碰了再过滤」。
    """
    raw = os.environ.get(ACCOUNT_DISCOVERY_ENV, "")
    return raw.strip().lower() in DISCOVERY_OFF_VALUES


class LedgerError(Exception):
    """账本缺失或格式不对 —— 一律退 2，不许猜。"""


# --------------------------------------------------------------------------
# 账本定位与读写
# --------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(TZ)


def _iso(dt: datetime) -> str:
    return dt.astimezone(TZ).replace(microsecond=0).isoformat()


def find_ledger(explicit: str | None = None) -> Path:
    """按约定找账本：显式 > 环境变量 > 本目录向上走 > 退 2。"""
    if explicit:
        p = Path(explicit).expanduser()
        if not p.is_file():
            raise LedgerError(f"给的账本不存在：{p}")
        return p.resolve()

    env = os.environ.get("TF_ACCOUNTS_TOML", "").strip()
    if env:
        p = Path(env).expanduser()
        if not p.is_file():
            raise LedgerError(f"TF_ACCOUNTS_TOML 指向的文件不存在：{p}")
        return p.resolve()

    # ★ 卡 E49：锚点从**仓库根**向上找，不跟 cwd 走 —— 曾经的 `Path.cwd()` 版本
    #   在云机上会一路走到 `C:\infra\pool\accounts.toml`（那是给门禁推配置的宿主机路径），
    #   于是「账本不存在」的用例在云机必红、本机却绿。判据不许跟宿主目录形状绑定。
    start = TOOL_ROOT.resolve()
    for base in (start, *start.parents):
        cand = base.joinpath(*ANCHOR)
        if cand.is_file():
            return cand
    raise LedgerError(
        "没找到账号账本。三种修法任一：\n"
        "  1) 在仓库根的子目录里跑（会向上找 infra/pool/accounts.toml）；\n"
        "  2) 设 TF_ACCOUNTS_TOML=<账本绝对路径>；\n"
        "  3) 显式 --ledger <路径>。\n"
        "账本本体在仓外：D:/repo/infra/pool/accounts.toml"
    )


def _platforms_path() -> Path:
    return TOOL_ROOT / "tools" / "pool" / "platforms.toml"


def load_platforms(path: Path | None = None) -> dict:
    p = path or _platforms_path()
    with open(p, "rb") as fh:
        data = tomllib.load(fh)
    return data.get("platform", {})


def _check_account(
    idx: int,
    acc: dict,
    platforms: dict,
    base_whitelist: set[str] | None = None,
    strict: bool = True,
) -> None:
    """逐字段校验，报错要点名「第几个 + 哪个字段」，不许只说格式错。

    失败方向：已 fail closed（「没探测过就不许填数」，见下方 `[account.quota]` 那条）——
    这是 F70 的**数据面**：抛 `LedgerError` 而不是当「未观测」放行（卡 A336 只加这一行）。
    """
    where = f"第 {idx + 1} 个账号"
    if not isinstance(acc.get("id"), str) or not acc.get("id"):
        raise LedgerError(f"{where} 缺 id")
    where = f"账号 {acc['id']}"
    for key in ("label", "platform", "state", "added_at"):
        if not isinstance(acc.get(key), str) or not acc.get(key):
            raise LedgerError(f"{where} 缺字段 {key}")
    if acc["platform"] not in platforms:
        if strict:
            raise LedgerError(
                f"{where} 的平台 {acc['platform']!r} 不在 tools/pool/platforms.toml 里"
                f"（已知：{', '.join(sorted(platforms))}）"
            )
        # 非 strict（list/show）：如实列出，但标成「能力表里没有」——
        # 不许静默跳过（等于这个号凭空消失），也不许当成能用（probe/派活读 strict）。
        acc["_platform_known"] = False
        return
    acc.setdefault("_platform_known", True)
    if acc["state"] not in STATES:
        raise LedgerError(f"{where} 的 state={acc['state']!r} 不合法（只认 {', '.join(STATES)}）")
    models = acc.get("approved_models")
    if not isinstance(models, list):
        raise LedgerError(
            f"{where} 缺 approved_models（必须是数组；一个都没批就写空数组 —— "
            "空数组的含义是「这个号不许派活」，不是「随便用」）"
        )
    if base_whitelist and any(m not in base_whitelist for m in models):
        bad = [m for m in models if m not in base_whitelist]
        raise LedgerError(f"{where} 的 approved_models 含未批准模型：{bad}（批准权只在用户）")
    cred = acc.get("credential")
    if not isinstance(cred, dict):
        raise LedgerError(f"{where} 缺 [account.credential] 表")
    if cred.get("kind") not in CRED_KINDS:
        raise LedgerError(
            f"{where} 的 credential.kind={cred.get('kind')!r} 不合法"
            f"（只认 {', '.join(CRED_KINDS)}）"
        )
    if cred["kind"] != "none" and not cred.get("locator"):
        raise LedgerError(f"{where} 的 credential 没给 locator（只存位置指针）")
    quota = acc.get("quota")
    if isinstance(quota, dict) and quota.get("source") == "unknown" and "amount" in quota:
        raise LedgerError(
            f"{where} 的 [account.quota].source=unknown 却写了 amount —— 没探测过就不许填数"
            "（TOML 没有 null：要表达「未观测」就把 amount 整个省掉）"
        )

    # 卡 A334 · T-AG536：`used_percent` 是整窗估算的**唯一**分母（tools/pool/holds.py）。
    # 越界不是「数据脏」而是「口径坏了」：0 会让 scale 变成 100/0，>100 会估出比整窗还大的数。
    # 校验只有一份（下面那个函数），读账本与写账本共用 —— 写方只有一处：
    # `record_probe_result()` 对 codearts 的 ok 读数写它（卡 E97）；其它平台仍无写方，
    # 缺键仍是「未观测」。
    if isinstance(quota, dict):
        _check_used_percent(where, quota.get("used_percent"))


def _check_used_percent(where: str, percent: object) -> None:
    """`[account.quota].used_percent` 的**唯一**校验（读账本与写账本共用，卡 A334 / E97）。

    `None` = 「未观测」，合法。其余必须是 0~100 的有限数：0 会让整窗估算除以零，
    >100 会估出比整窗还大的数 —— 这不是「数据脏」，是「口径坏了」，所以抛。
    """
    if percent is None:
        return
    if isinstance(percent, bool) or not isinstance(percent, (int, float)):
        raise LedgerError(
            f"{where} 的 [account.quota].used_percent={percent!r} 不是数"
            "（要么整个省掉表示「未观测」，要么填 0~100 的数）"
        )
    if not math.isfinite(percent):
        raise LedgerError(
            f"{where} 的 [account.quota].used_percent={percent!r} 不是有限数"
            "（NaN / Infinity 都不能当读数）"
        )
    if not 0 <= percent <= 100:
        raise LedgerError(
            f"{where} 的 [account.quota].used_percent={percent!r} 越界"
            "（必须在 [0, 100]：0 会让整窗估算除以零，>100 会估出比整窗还大的数）"
        )


def _approved_models_from_whitelist() -> set[str] | None:
    """号池白名单（仓外 models.whitelist.toml）里的模型名。

    读不到就返回 None —— 只跳过「批准集」这条判据，不拦。
    """
    for cand in (
        TOOL_ROOT.parent / "infra" / "pool" / "models.whitelist.toml",
        Path("D:/repo/infra/pool/models.whitelist.toml"),
    ):
        try:
            with open(cand, "rb") as fh:
                data = tomllib.load(fh)
        except (OSError, tomllib.TOMLDecodeError):
            continue
        names = {str(row.get("model")) for row in data.get("approved", []) if row.get("model")}
        return names or None
    return None


def load_ledger(path: Path, platforms: dict | None = None, strict: bool = True) -> dict:
    """读账本。**凭据账本不许从 `.bak` 复活（照 F77 的 caller-keys 纪律）**。

    只读正式文件：若允许从 `.bak` 兜底，一次写坏就能把**已撤的凭据**顶回来 ——
    「撤过的凭据不许复活」比「读不到就停」更重要 ⇒ 走 `lastgood.read_strict`（永不看 `.bak`），
    读不了就抛（文件不存在仍是 `FileNotFoundError`，行为与从前一致）。
    """
    plat = platforms if platforms is not None else load_platforms()
    try:
        text = _lastgood().read_strict(path, validate=_validate_ledger_toml)
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise LedgerError(f"账本 TOML 解析失败（{path}）：{exc}") from exc
    accounts = data.get("account")
    if not isinstance(accounts, list) or not accounts:
        raise LedgerError(f"账本里没有 [[account]] 表（{path}）")
    whitelist = _approved_models_from_whitelist()
    seen: set[str] = set()
    for idx, acc in enumerate(accounts):
        acc.setdefault("_platform_known", True)
        _check_account(idx, acc, plat, whitelist, strict)
        if acc["id"] in seen:
            raise LedgerError(f"账号 id 重复：{acc['id']}")
        seen.add(acc["id"])
    data["unknown_platforms"] = sorted(
        a["id"] for a in accounts if not a.get("_platform_known", True)
    )
    return data


def ledger_would_lose_comments(path: Path) -> list[int]:
    """账本里哪些行是**行首注释**（`_dump_toml` 整份重生成会把这些抹掉），返回 1 起的行号。

    ★ 只看**行首（允许前置空白）的 `#`**：行尾注释**不算**。`_dump_toml` 连行尾注释也会丢，
      但那是「整份重生成」避免不了的事 —— 管不了就明说管不了（卡 A356 缺口 1），
      不在这里假装能管（否则今天真实账本里任何一个 `key = 1  # 说明` 都会被误报成「会丢」）。
    文件不存在 / 读不出来 ⇒ 空列表（没有会丢的东西，写盘照常）。
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    return [
        lineno
        for lineno, line in enumerate(text.splitlines(), start=1)
        if line.lstrip().startswith("#")
    ]


def save_ledger(path: Path, data: dict) -> None:
    """原子替换写回（E48 用；E45 只读面不调它，但格式必须与读的一模一样）。

    `samples` 只留最近 SAMPLES_CAP 条；写坏半个文件比不写更糟 ⇒ 同目录临时文件 + os.replace。

    ★ 卡 A356：写之前先看账本里有没有**行首注释** —— `_dump_toml` 是整份重生成，
      有注释就把它抹掉。抹掉是不可逆的数据损失（账本在仓外，没有 git 能 checkout 回来），
      所以这里**拒绝**而不是「先备份再写」：**一个字节都不写**，让人自己决定怎么搬走注释。
      （`lastgood` 的 `.bak` 救不了这件事 —— `.bak` 也是上一次「已经没有注释」的那一份。）
    """
    losing = ledger_would_lose_comments(path)
    if losing:
        shown = "、".join(str(n) for n in losing[:3])
        raise LedgerError(
            f"账本里有注释，`_dump_toml` 会整份重生成把它抹掉（{path}）："
            f"行 {shown}（共 {len(losing)} 行）—— 先把注释挪走或删掉再写；**一个字节都没写**。"
        )
    for acc in data.get("account", []):
        quota = acc.get("quota")
        if isinstance(quota, dict) and isinstance(quota.get("samples"), list):
            quota["samples"] = quota["samples"][-SAMPLES_CAP:]
    payload = _dump_toml(data)
    # ★ 卡 E121：`lastgood.write_atomic()` 的 validate 只判**旧文件**能不能进 `.bak`
    #   （`tools/pool/lastgood.py:280` 判旧、`:300` 直接 os.replace），新 payload 一次都不验。
    #   所以写侧在这里自己收口：坏值（如 `health.state = "healthy"`）当场抛，
    #   `write_atomic()` 根本没被调用 ⇒ 盘上一个字节不变。
    _validate_ledger_toml(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    # 写走 lastgood（`.bak` 落后一次写）；**读**却用 read_strict（见 load_ledger）。
    _lastgood().write_atomic(path, payload, validate=_validate_ledger_toml)


def _q(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    return json.dumps(str(value), ensure_ascii=False)


def _dump_toml(data: dict) -> str:
    lines: list[str] = []
    for acc in data.get("account", []):
        lines.append("[[account]]")
        for key, value in acc.items():
            if key.startswith("_") or isinstance(value, dict):
                continue  # `_platform_known` 之类是**读侧**临时字段，绝不写回账本
            if isinstance(value, list):
                inner = ", ".join(_q(v) for v in value)
                lines.append(f"{key} = [{inner}]")
            else:
                lines.append(f"{key} = {_q(value)}")
        for sub in ("credential", "quota", "health"):
            block = acc.get(sub)
            if not isinstance(block, dict):
                continue
            lines.append(f"[account.{sub}]")
            for key, value in block.items():
                if key.startswith("_"):
                    continue
                if isinstance(value, list):
                    lines.append(f"{key} = [")
                    for item in value:
                        if isinstance(item, dict):
                            inner = ", ".join(f"{k} = {_q(v)}" for k, v in item.items())
                            lines.append(f"  {{ {inner} }},")
                        else:
                            lines.append(f"  {_q(item)},")
                    lines.append("]")
                else:
                    lines.append(f"{key} = {_q(value)}")
        lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# 刷新令牌：单持有者、吊销判定、标记（卡 A335 / T-AG537）
#
# 依据 magpie 的刷新单持有者（internal/provider/logins_on.go:22-26 逐字：
# "the second would spend a refresh token the first just rotated"）——
# 供应商的 refresh token 是**轮换**的，第二次拿旧的去刷会把第一次刚拿到的作废。
# 本段只做**判定函数 + 锁**，不做真正的 HTTP 刷新调用（谁要接刷新，另开卡）。
# --------------------------------------------------------------------------

#: 到期前多久才刷（照 logins_on.go:275 的 `5*time.Minute`）。
RENEW_MARGIN_S: int = 5 * 60
#: SIWC 那条口径的余量（照 chatgpt_api.go:68 的 `3*time.Minute`）。
SIWC_MARGIN_S: int = 3 * 60
#: 拿不到锁时最多等多久（照 filelock.go:20 的 `10*time.Second`）。
LOCK_WAIT_S: float = 10.0
#: 锁的租约（秒）：超时就按陈旧接管 —— **只按时间判，绝不按 pid 探活**。
RENEW_LOCK_TTL_S: float = 120.0


class RefreshRefused(Exception):  # noqa: N818 —— 名字就是判据原文（照 gate_pool.CloudUnreachable 的口径）
    """供应商**答复并拒绝**了这个 refresh token（400 invalid_grant / 401）。

    与「这一次没成」（403 / 5xx / 网络错）分开：照 `internal/provider/account.go:860-872`，
    只有这两个码算「这个号得重新登录」。判据标识：**只有**本类能让调用方去写吊销标记。
    """


def jwt_exp(token: str) -> float | None:
    """读 JWT 第二段的 `exp`（秒）。**读不出来一律回 None —— 不抛、不打印 token 片段。**

    非三段式 / base64 解不开 / 没有 `exp` / `exp` 不是数 —— 四条都回 None（卡 §判据 2）。
    """
    if not isinstance(token, str):
        return None
    parts = token.split(".")
    if len(parts) != 3 or not parts[1]:
        return None
    seg = parts[1]
    try:
        raw = base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4))
        claims = json.loads(raw.decode("utf-8"))
    except ValueError:  # 含 binascii.Error / UnicodeDecodeError / JSONDecodeError
        return None
    if not isinstance(claims, dict):
        return None
    exp = claims.get("exp")
    if isinstance(exp, bool) or not isinstance(exp, (int, float)):
        return None
    return float(exp)


def needs_renew(
    access_token: str,
    *,
    force: bool = False,
    now: datetime | None = None,
    margin_s: float = RENEW_MARGIN_S,
) -> bool:
    """现在该不该去刷？ —— 照 `logins_on.go:275` 的 `!force && (exp == 0 || Until(exp) > 5m)`。

    `force` 恒 True；**读不出 `exp` 恒 True**（宁可多刷一次，也别拿着过期 token 去撞供应商）。
    """
    if force:
        return True
    exp = jwt_exp(access_token)
    if exp is None:
        # 读不出来 ⇒ 一律当该刷（卡 §判据 2：宁可多刷，不许拿着过期 token 去撞供应商）
        return True
    current = now if now is not None else _now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=TZ)
    return (exp - current.timestamp()) <= margin_s


def refresh_failed(status: int, agent: str, msg: str) -> Exception:
    """这一次刷新没成 —— 是「号死了」还是「这一次没成」？照 `account.go:867-872`。

    只有 **400 / 401**（供应商答复并拒绝）回 `RefreshRefused`；403 / 5xx / 0（超时、连不上）
    一律只是「这一次没成」—— 403 更可能是代理或风控挡了一道，不是供应商对 token 的答复。
    """
    if status in (400, 401):
        return RefreshRefused(msg)
    return RuntimeError(f"{agent} token refresh failed (HTTP {status})：{msg}")


def revoked_mark(reason: str, *, salt: str = "") -> str:
    """吊销标记：**只存 sha256 前 8 字节 hex**（照 `quota_last.go:52-55 keyTag()`），永不存明文。"""
    digest = hashlib.sha256((salt + reason).encode("utf-8")).hexdigest()[:16]
    return "revoked " + digest


def mask_token(token: str) -> str:
    """JWT 打码：三段式只留 `header.payload` 的前 6 字符 + `…`，其余一律 `"<token>"`。

    既有 `mask()` 只认 `sk-/ak-/ghp-/xoxb-` 前缀，**管不到 JWT** —— 日志出口一律走本函数。
    """
    if not isinstance(token, str) or not token:
        return "<token>"
    parts = token.split(".")
    if len(parts) != 3 or not parts[0] or not parts[1]:
        return "<token>"
    return (parts[0] + "." + parts[1])[:6] + "…"


def saved_refresh_failed(
    ledger_path: Path,
    *,
    account_id: str,
    agent: str,
    exc: Exception,
    now: datetime | None = None,
) -> bool:
    """刷新失败了要不要在账本上留痕？—— 照 `logins_on.go:318` 逐字：

    「A refresh that never got an answer marks nothing.」⇒ **只有 `RefreshRefused`** 才写吊销标记
    并回 True；网络错 / 403 / 5xx 回 False 且**账本一个字节都不变**（连读都不读）。
    """
    if not isinstance(exc, RefreshRefused):
        return False
    ledger = Path(ledger_path)
    data = load_ledger(ledger)
    stamp = _iso(now or _now())
    reason = f"refresh refused: {agent}/{account_id}: {exc}"[:200]
    mark = revoked_mark(reason)
    for acc in data.get("account", []):
        if acc.get("id") != account_id:
            continue
        health = acc.setdefault("health", {})
        health["revoked"] = mark
        health["revoked_at"] = stamp
        save_ledger(ledger, data)
        return True
    raise LedgerError(f"账本里没有账号 {account_id}：{ledger}")


#: 进程内互斥：**按账本路径**取锁（不是按号 —— 两个号并发写同一份账本一样要串行）。
_RENEW_LOCKS: dict[str, threading.Lock] = {}
_RENEW_LOCKS_GUARD = threading.Lock()


def _renew_thread_lock(key: str) -> threading.Lock:
    with _RENEW_LOCKS_GUARD:
        lock = _RENEW_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _RENEW_LOCKS[key] = lock
        return lock


def _renew_ledger(root: Path | None) -> Path:
    """账本路径：`root` 给了就按锚点拼（测试/自证用），否则走 `find_ledger()`。"""
    if root is None:
        return find_ledger(None)
    return Path(root).joinpath(*ANCHOR)


def renew_lock_file(root: Path | None = None) -> Path:
    """锁文件：**吸附在账本自己旁边**（`<账本>.renew.lock`）。

    与 magpie `loginsPath()+`.renew.lock`` 同构。

    按号加锁不够：两个号并发刷新会互相覆盖 `save_ledger()` 的原子写。
    """
    ledger = _renew_ledger(root)
    return ledger.with_name(ledger.name + ".renew.lock")


def _whoami() -> str:
    window = os.environ.get("TF_WINDOW_ID", "").strip()
    return window or f"{socket.gethostname()}:{os.getpid()}"


def _renew_lock_payload(lock: Path) -> dict[str, object]:
    """读锁里写的「谁拿的 / 什么时候拿的」（读不了或坏了当空 —— 那种锁按 mtime 判陈旧）。"""
    try:
        raw = json.loads(lock.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _renew_lock_age(lock: Path, payload: dict[str, object]) -> float:
    """锁多久没动了 —— ★ 优先锁里写的 `at`（ISO），**退化到锁文件 mtime**。

    照 `tools/pool/task.py:231 _lock_age()` 的口径：**按时间判陈旧**，不做 pid 探活
    （`tools/pool/registry.py:18-30` 是硬禁令）。
    """
    raw = payload.get("at")
    at: datetime | None = None
    if isinstance(raw, str) and raw:
        try:
            at = datetime.fromisoformat(raw)
        except ValueError:
            at = None
    if at is not None:
        now = datetime.now(at.tzinfo) if at.tzinfo is not None else datetime.now()
        return max(0.0, (now - at).total_seconds())
    try:
        return max(0.0, time.time() - lock.stat().st_mtime)
    except OSError:
        return 0.0


def _warn_without_lock(wait_s: float, payload: dict[str, object]) -> None:
    """fail-open 的那一行（照 `filelock.go:57`：打一行然后照样往下走）。"""
    holder = payload.get("owner") or "（未知）"
    print(f"另一个持有者占了 {wait_s:g} 秒，无锁继续（{holder}）", file=sys.stderr)


def _spin_renew_file_lock(lock: Path, *, account_id: str, wait_s: float) -> bool:
    """`O_CREAT|O_EXCL` 自旋拿跨进程锁；**拿不到就 fail-open 回 False，绝不抛**。"""
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + max(0.0, float(wait_s))
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            holder: dict[str, object] = _renew_lock_payload(lock)
            if _renew_lock_age(lock, holder) <= RENEW_LOCK_TTL_S:
                if time.monotonic() > deadline:
                    _warn_without_lock(wait_s, holder)
                    return False
                time.sleep(0.05)
                continue
            # 陈旧（**只按时间判**）⇒ 接管：清掉重拿。清不掉也要认超时，否则会自旋到天荒地老
            with contextlib.suppress(OSError):
                lock.unlink()
            if time.monotonic() > deadline:
                _warn_without_lock(wait_s, holder)
                return False
            continue
        payload: dict[str, object] = {
            "owner": _whoami(),
            "pid": os.getpid(),
            "task": account_id,
            "at": _iso(_now()),
        }
        try:
            os.write(fd, (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        finally:
            os.close(fd)
        return True


@contextlib.contextmanager
def renew_lock(
    account_id: str,
    *,
    root: Path | None = None,
    wait_s: float = LOCK_WAIT_S,
) -> Iterator[bool]:
    """同一个账本的刷新**只能有一个持有者**：先进程内互斥，再跨进程 `O_EXCL`。

    yield 的值就是 `held`：拿到双锁 ⇒ True；`wait_s` 内没拿到 ⇒ **fail-open 回 False**
    （照 `filelock.go:57`：打一行然后照样往下走 —— 超时抛错会把一次可用的刷新变成硬失败）。

    ★ `yield` 必须在**取到锁之后、循环之外**：放进 `while` 里，上下文正常退出后生成器会绕回
    循环再 yield 一次，`contextlib` 直接报 `RuntimeError: generator didn't stop`。
    """
    lock = renew_lock_file(root)
    tlock = _renew_thread_lock(str(lock))
    got_thread = tlock.acquire(timeout=max(0.0, float(wait_s)))
    held = False
    try:
        if got_thread:
            held = _spin_renew_file_lock(lock, account_id=account_id, wait_s=wait_s)
        else:
            _warn_without_lock(wait_s, {})
        yield held
    finally:
        try:
            if held:
                with contextlib.suppress(OSError):
                    lock.unlink()
        finally:
            if got_thread:
                tlock.release()


# --------------------------------------------------------------------------
# 展示与静态盘点
# --------------------------------------------------------------------------


def mask(value: str) -> str:
    """任何看起来像凭据的串一律打码 —— 输出属于通知通道。"""
    if not isinstance(value, str) or not value:
        return ""
    masked = SECRET_RE.sub("***", value)
    return masked


def _tombstoned(acc: dict) -> bool:
    return bool(acc.get("deleted_at")) or acc.get("state") == "disabled"


def visible_accounts(data: dict, include_deleted: bool = False) -> list[dict]:
    out = []
    for acc in data.get("account", []):
        if _tombstoned(acc) and not include_deleted:
            continue
        out.append(acc)
    return out


def _quota_text(acc: dict) -> str:
    quota = acc.get("quota") or {}
    amount = quota.get("amount")
    observed = quota.get("observed_at") or ""
    if amount is None:
        return "未观测" + (f"（{observed}）" if observed else "")
    return f"{amount} {quota.get('unit', '')}".strip() + (f"（{observed}）" if observed else "")


def list_rows(data: dict, platform: str | None, include_deleted: bool) -> list[dict]:
    rows = []
    for acc in visible_accounts(data, include_deleted):
        if platform and acc["platform"] != platform:
            continue
        rows.append(
            {
                "id": acc["id"],
                "platform": acc["platform"],
                "platform_known": bool(acc.get("_platform_known", True)),
                "label": mask(acc["label"]),
                "state": acc["state"],
                "quota": _quota_text(acc),
                "models": [mask(m) for m in acc["approved_models"]],
                "credential": mask(acc.get("credential", {}).get("locator", "")),
            }
        )
    # 稳定排序：platform, id —— 读数要能直接对账（顺序随账本行序变会让人怀疑数据在变）
    rows.sort(key=lambda r: (r["platform"], r["id"]))
    return rows


DECLARED_DIRS = [
    "~/codebuddy-accounts",
    "~/.codebuddy",
    "~/.workbuddy",
    "~/.codeartsdoer",
    "~/.trae",
    "~/.qoder",
    "~/minimax",
    "~/.meoo",
]


def discover(
    ledger_locators: list[str],
    extra_dirs: list[str] | None = None,
    *,
    root: Path | None = None,
) -> list[dict]:
    """只 stat，绝不读内容：把「本机有的凭据位点」与「账本里登记过的」对一遍。

    `ledger_locators` 只放账本里真实声明过的 locator；常量清单 DECLARED_DIRS 是**待查**的位点，
    不是「已登记」—— 否则每行都会显示已登记，等于没查。

    **闸关 ⇒ 直接返回 `[]`，一个位点都不 stat**（判据 1）：判据问在循环之前，所以不存在
    「stat 了再过滤」。`root` 只给测试注入：给了就按它解析相对位点，不传就用今天的行为。
    """
    if discovery_off():
        return []
    declared = set(ledger_locators)
    seen: set[str] = set()
    out = []
    for raw in list(ledger_locators) + DECLARED_DIRS + list(extra_dirs or []):
        if raw in seen:
            continue
        seen.add(raw)
        path = Path(root, raw) if root is not None else Path(os.path.expanduser(raw))
        exists = path.exists()
        row = {
            "pointer": raw,
            "resolved": str(path),
            "exists": bool(exists),
            "declared": raw in declared,
            "status": "已登记" if raw in declared else "未声明",
        }
        if exists:
            row["entries"] = _count(path)
        out.append(row)
    return out


def _count(path: Path) -> int | None:
    try:
        with os.scandir(path) as it:
            return sum(1 for _ in it)
    except OSError:
        return None


# --------------------------------------------------------------------------
# 只读探测
# --------------------------------------------------------------------------


def _token_from_file(plat: dict) -> tuple[str, str]:
    """从文件型凭据里读一个 token（`token_file` + `token_key`，默认 `accessToken`）。

    为什么要有这一支：meoo 的凭据是 CLI 的 OAuth 结果（`~/.meoo/credentials.json`），
    不是环境变量 —— 而本表的铁律是「绝不放凭据」，所以只能放**位点**，值现读。

    读不出来一律回 `("", "位点 + 键名")`，让调用方把「该去哪儿找」说给人听；
    **不抛、不打印文件内容**（只报路径与键名）。
    """
    rel = str(plat.get("token_file") or "").strip()
    if not rel:
        return "", ""
    key = str(plat.get("token_key") or "accessToken").strip() or "accessToken"
    where = f"{rel} 的 {key}"
    try:
        text = Path(rel).expanduser().read_text(encoding="utf-8")
        data = json.loads(text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return "", where
    if isinstance(data, dict):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip(), where
    return "", where


def _token_for(plat: dict) -> tuple[str, str]:
    """返回 (token, 来源说明)。环境变量多个用 / 分隔取第一个非空的；都没有再看 `token_file`。

    **闸关 ⇒ `("", "")`，且一个 token 变量都不读、一个凭据文件都不开**（判据 2）：
    闸在循环之前问 —— 文件这一支同样在闸后面。
    """
    if discovery_off():
        return "", ""
    names = [n for n in str(plat.get("token_env", "")).split("/") if n]
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value, name
    if plat.get("token_file"):
        token, where = _token_from_file(plat)
        if token:
            return token, where
        return "", where
    return "", "/".join(names)


def _get_json(url: str, token: str, timeout: float = 8.0) -> tuple[int, dict | None, str]:
    req = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - 固定 https 端点
            body = resp.read()
            status = resp.status
    except urllib.error.HTTPError as exc:
        return exc.code, None, f"HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return 0, None, f"网络错误：{mask(str(exc))}"
    try:
        return status, json.loads(body.decode("utf-8", "replace")), ""
    except json.JSONDecodeError:
        return status, None, "响应不是 JSON"


AMOUNT_KEYS = ("total", "points", "credits", "credit", "balance", "quota", "amount", "remain")


def _amount_at_path(obj, path: str) -> float | None:
    """按平台显式声明的点分路径取值（`amount_path = "data.account.availableBalance"`）。

    为什么需要它：`_extract_amount` 是**猜**（找第一个名字像额度的键），而 meoo 的响应里
    `totalGranted: 61000` 比真值 `availableBalance: 56958` 更容易被猜到 —— 猜错不是 0，
    是一个**看起来合理**的错数。表里写清路径，就不猜。

    路径走不通 / 取到的不是数 ⇒ None（→ uncertain，绝不回 0）。
    """
    cur = obj
    for part in path.split("."):
        if not part:
            return None
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    if isinstance(cur, bool) or not isinstance(cur, (int, float)):
        return None
    return float(cur)


def _extract_amount(obj) -> float | None:
    """在响应里找第一个「名字像额度」的数字；找不到就 None（→ uncertain）。"""
    if isinstance(obj, dict):
        for key in AMOUNT_KEYS:
            value = obj.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
        for value in obj.values():
            found = _extract_amount(value)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _extract_amount(item)
            if found is not None:
                return found
    return None


def _codearts_credential(plat: dict):
    """从 `token_env` 取 AK/SK —— 返回 `(CodeArtsCredential, 缺凭据时该点名的名字)`。

    ★ 为什么不是「取第一个非空的就完事」：`token_env` 是一条 `/` 分隔的**有序名单**
      （`CODEARTS_CLI_AK/CODEARTS_CLI_SK/TF_CODEARTS_AK/TF_CODEARTS_SK`），位置不代表角色 ——
      第三位 `TF_CODEARTS_AK` 又是一个 **AK**，不是 security token。所以按名字后缀分角色：
      `*_AK` 里第一个非空的是 AK，`*_SK` 里第一个非空的是 SK，其余非空值当 security token。
    ★ 闸：走 `checkin.tokens_from_env()`，它自己先问 `discovery_off()`（闸关 ⇒ 回空列表，
      一个 token 变量都不读）。这里再判一次空列表 ⇒ 回「缺凭据」。
    """
    ck = _ck()
    tokens = ck.tokens_from_env(plat, os.environ)
    names = [n.strip() for n in str(plat.get("token_env") or "").split("/") if n.strip()]
    if not tokens:
        return None, " / ".join(names)
    ak = sk = secret = ""
    for name, value in zip(names, tokens, strict=True):
        if not value:
            continue
        upper = name.upper()
        if upper.endswith("_AK"):
            ak = ak or value
        elif upper.endswith("_SK"):
            sk = sk or value
        else:
            secret = secret or value
    if not ak or not sk:
        return None, " / ".join(names)
    return ck.CodeArtsCredential(ak, sk, secret), ""


def _probe_codearts(base: dict, plat: dict, fetch=None) -> dict:
    """codearts 的只读额度读数：用 `checkin` 的签名请求读一次 `statistics/plugin`（卡 E97）。

    结论码与口径：
    * 成功且 total 那条 metric 能算出百分比 ⇒ `ok`，带 `used_percent`（两位小数）与
      `amount`（**余额口径** = total 那条的 `package_credit_remain`；与
      `record_probe_result()` 的「amount 是余额」一致，不塞套餐总额）；
    * 缺 AK/SK ⇒ `uncertain` 并点名 `token_env`（没料必须说不知道，不许给 0）；
    * 401/403 ⇒ `failed`；404 ⇒ `not-supported`；429 / 5xx / 网络不明 ⇒ `uncertain`，
      **不重放**（重放会把限流窗口里的猜测当成读数）；
    * 读到了但没有 total 那条 metric（形状变了）⇒ `uncertain`，**不当 0**。
    """
    ck = _ck()
    credential, need = _codearts_credential(plat)
    if credential is None:
        return {
            **base,
            "kind": "uncertain",
            "detail": f"账本只存指针，没凭据可发；要真探请设 {need or '（该平台无 token_env）'}",
        }
    fetcher = fetch if fetch is not None else ck.http_fetch
    try:
        package, failure = ck.codearts_account(credential, fetcher)
    except ck.NetworkError as exc:
        return {**base, "kind": "uncertain", "detail": f"网络不明：{mask(str(exc))}（不重放）"}
    if failure is not None:
        status = failure.code if isinstance(failure.code, int) else 0
        if status in (401, 403):
            return {
                **base,
                "kind": "failed",
                "detail": f"HTTP {status}：AK/SK 无效或过期（改凭据位点，别改这里）",
            }
        if status == 404:
            return {**base, "kind": "not-supported", "detail": "HTTP 404：上游没这个只读端点"}
        if status == 429 or status >= 500 or status == 0:
            return {**base, "kind": "uncertain", "detail": f"{failure.message}（不重放）"}
        return {**base, "kind": "uncertain", "detail": failure.message or "读数不可信"}
    used = ck.codearts_package_used(package)
    if used is None:
        return {
            **base,
            "kind": "uncertain",
            "detail": "响应里没有 usageTotalPackageCredit 的 used/amount（形状变了，别当 0）",
        }
    row = {
        **base,
        "kind": "ok",
        "used_percent": round(used, 2),
        "detail": f"读自 {ck.CODEARTS_BASE}{ck.CODEARTS_PACKAGE_PATH}",
    }
    remain = ck.codearts_package_remain(package)
    if remain is not None:
        row["amount"] = remain
        row["unit"] = str(plat.get("unit", plat.get("quota_unit", "")) or "credits")
    return row


def probe_account(acc: dict, plat: dict, fetch=None, offline: bool = False) -> dict:
    """单账号只读探测。

    结论码只许这六个：ok / skipped / uncertain / failed / not-supported / unknown-platform。
    """
    # codearts 那支吃 checkin 的 4 参签名 fetcher；其余平台吃 2 参的 (url, token) ⇒ 先留住原值。
    given_fetch = fetch
    fetch = fetch or _get_json
    base = {"id": acc["id"], "platform": acc["platform"]}
    # 闸在最前面：连「state 是不是 disabled」都不问 —— 那是「已经有账号」之后的事。
    if discovery_off():
        return {**base, "kind": "skipped", "detail": DISCOVERY_OFF_MESSAGE}

    if acc["state"] in ("disabled", "expired"):
        return {**base, "kind": "skipped", "detail": f"state={acc['state']}，不探测"}

    mode = plat.get("probe")
    if mode == "unsupported":
        return {
            **base,
            "kind": "uncertain",
            "detail": "读取也需 SDK-HMAC-SHA256 签名（E48 的 checkin 一并实现），本卡不猜读数",
        }
    if mode == "manual":
        return {**base, "kind": "uncertain", "detail": "参考实现里没有只读额度入口 ⇒ 未探测"}
    if offline:
        return {**base, "kind": "skipped", "detail": "--offline：不发网络请求"}
    if mode == "codearts-credits":
        return _probe_codearts(base, plat, given_fetch)

    token, env_name = _token_for(plat)
    if not token:
        need = env_name or "（该平台无 token_env）"
        return {
            **base,
            "kind": "uncertain",
            "detail": f"账本只存指针，没凭据可发；要真探请设 {need}",
        }

    url = str(plat.get("probe_url", "")).strip()
    if not url:
        return {**base, "kind": "uncertain", "detail": "platforms.toml 没写 probe_url ⇒ 未探测"}
    url = url.replace("{base}", str((plat.get("base_urls") or [""])[0]).rstrip("/"))

    status, body, err = fetch(url, token)
    if status in (401, 403):
        return {
            **base,
            "kind": "failed",
            "detail": f"HTTP {status}：凭据无效或过期（刷新后改账本的 locator，别改这里）",
        }
    if status == 404:
        return {**base, "kind": "not-supported", "detail": "HTTP 404：上游没这个只读端点"}
    if status == 429:
        return {**base, "kind": "uncertain", "detail": "HTTP 429：限流，读数不可信（不重放）"}
    if status == 0 or status >= 500:
        return {**base, "kind": "uncertain", "detail": err or f"HTTP {status}"}
    if body is None:
        return {**base, "kind": "uncertain", "detail": err or "响应解析不了"}
    amount_path = str(plat.get("amount_path") or "").strip()
    amount = _amount_at_path(body, amount_path) if amount_path else _extract_amount(body)
    if amount is None:
        if amount_path:
            return {
                **base,
                "kind": "uncertain",
                "detail": f"响应里没有 {amount_path}（形状变了，别当 0）",
            }
        return {**base, "kind": "uncertain", "detail": "响应里找不到额度字段（形状变了，别当 0）"}
    return {
        **base,
        "kind": "ok",
        "amount": amount,
        "unit": str(plat.get("unit", plat.get("quota_unit", ""))),
        "detail": f"读自 {url}",
    }


def probe_all(
    data: dict, platforms: dict, fetch=None, offline: bool = False, platform: str | None = None
) -> list[dict]:
    if discovery_off():
        # 判据 3：闸关时**每一条都给 skipped**，而且连平台能力表都不查
        # （`unknown-platform` 是「查过了、表里没有」，闸关时连查都不该查）。
        return [
            {
                "id": acc["id"],
                "platform": acc["platform"],
                "kind": "skipped",
                "detail": DISCOVERY_OFF_MESSAGE,
            }
            for acc in visible_accounts(data)
            if not platform or acc["platform"] == platform
        ]
    out = []
    for acc in visible_accounts(data):
        if platform and acc["platform"] != platform:
            continue
        plat = platforms.get(acc["platform"])
        if plat is None:
            out.append(
                {
                    "id": acc["id"],
                    "platform": acc["platform"],
                    "kind": "unknown-platform",
                    "detail": "平台不在 platforms.toml",
                }
            )
            continue
        out.append(probe_account(acc, plat, fetch=fetch, offline=offline))
    return out


def derive_health_state(kind: str | None) -> str | None:
    """一次探测的结论码 → `[account.health].state`（卡 E121 判据 1）。

    **一张显式表**，不是 if 链：

    | 输入 `kind` | 返回 |
    |---|---|
    | `ok` | `ok` |
    | `failed` | `auth-expired` |
    | `uncertain` / `skipped` / `not-supported` / `unknown-platform` / `None` |
      `None`（**不编 state**）|

    表外的码一律回 `None`：「没看出来」既不等于「健康」，也不等于「过期」。
    纯函数：不读不写账本、不读钟；返回值要么是 `None`，要么落在卡 E45 的五值枚举
    （`HEALTH_STATES`）里。
    """
    return {"ok": "ok", "failed": "auth-expired"}.get(kind or "")


def _apply_probe_health(acc: dict, kind: str | None, stamp: str) -> bool:
    """探测结论 → `[account.health]`（卡 E121 判据 2）：**唯一写这三键的地方**。

    逐键写，**绝不整块替换** `acc["health"]` —— 那会冲掉 `revoked` / `revoked_at`
    （卡 A335 的吊销标记，`tests/test_renew_lock.py:192-193` 钉着）。

    三键各自独立：
      · `last_probe` 每次都写（字面语义 = 「最后一次探测的时刻」）；
      · `state` **只有 `derive_health_state()` 给出值时**才写 —— 其余结论一律不写（不编
        state），旧值保留；
      · `consecutive_failures` 与 `state` **无关**，每次都归零或 +1：口径是
        `checkin.NEEDS_HUMAN`，与 `_record_checkin()` 同一份（判据 4，全仓不许有第二份
        字面量）。把归零挂在 `state is None` 的早退上就是错的：`uncertain` 不给 state，
        可它恰恰是要计连败的那一类结论。

    返回「这次真写了 health 没有」（调用方拿它决定要不要落盘）。
    """
    health = acc.setdefault("health", {})
    if not isinstance(health, dict):
        health = acc["health"] = {}
    health["last_probe"] = stamp
    state = derive_health_state(kind)
    if state is not None:
        health["state"] = state
    if kind in _ck().NEEDS_HUMAN:
        health["consecutive_failures"] = int(health.get("consecutive_failures", 0) or 0) + 1
    else:
        health["consecutive_failures"] = 0
    return True


# --------------------------------------------------------------------------
# 命令
# --------------------------------------------------------------------------


def record_probe_result(
    ledger_path: Path, data: dict, rows: list[dict], *, now: datetime | None = None
) -> None:
    """把一次探测的结论留进账本 —— 写 `[account.quota]` 的 `observed_at` / `samples` /
    `used_percent`（最后一条只对 codearts 的 `ok` 读数，卡 E97），以及 `[account.health]`
    的三键（卡 E121，唯一写点 `_apply_probe_health()`）。

    ★ 不写**顶层** `[[account]].state`：`STATES` 那五行（`active/limited/exhausted/expired/
      disabled`）是**人**判定「这个号还能不能用」的，一次探测读到的数字不许把它改掉。
    ★ 写 `[account.health]` 的三键（卡 E121 判据 2，唯一写点 `_apply_probe_health()`）：
      `last_probe`（探测时刻，每次都写）、`state`（**只按** `derive_health_state()` 的显式表写；
      `uncertain` / `skipped` / `not-supported` / `unknown-platform` / 缺 kind 一律**不写、不编
      state**，旧值保留）、`consecutive_failures`（口径 = `checkin.NEEDS_HUMAN`，与
      `_record_checkin()` 同一份；**归零/加一与 state 写不写无关** —— 把归零挂在
      `state is None` 的早退上，`uncertain` 这类「不给 state 但要计连败」的号就永远卡在旧值）。
      `last_checkin` / `last_checkin_at` 仍只由签到写。
    ★ 不写 `approved_models`：能不能派活是白名单的事，不是额度读数的事。
    ★ 不写 `amount`：探测读到多少就写在 `samples` 里；`amount` 是余额口径，由探针之外的人/流程填。
    ★ `used_percent` 只对 `kind == "ok"` **且**带 `used_percent` 的行写（今天只有 codearts 会带）。
      `failed` / `uncertain` / `skipped` / `not-supported` / 其它平台一律**不写、也不删旧值** ——
      缺键的含义是「未观测」，抹掉旧值等于把上一次真读数也一起丢了。写前走
      `_check_used_percent()`（与读账本同一份判据，0~100），越界就抛 `LedgerError` 且账本不落地。
    ★ `samples` 项只有 `{"at": stamp, "kind": <六结论码之一>}`，**没有 `reset_at`**；上限继续由
      `save_ledger()` 的 `SAMPLES_CAP` 截。六结论码原样落账，一条都不许压平。
    ★ `source == "unknown"` 的读数带 `amount` ⇒ 拒写并抛 `LedgerError`（照 `_check_account()` 的
      「没探测过就不许填数」）—— 这种情况下**一个字节都不写**，先全量校验再动手。
    """
    stamp = _iso(now if now is not None else _now())
    by_id: dict[str, dict] = {}
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("id"), str):
            by_id[row["id"]] = row

    accounts = data.get("account", [])
    if not isinstance(accounts, list):
        raise LedgerError(f"账本里没有 [[account]] 表（{ledger_path}）")

    # ---- 先校验（拒写时账本一个字节不变），再统一写
    for acc in accounts:
        if not isinstance(acc, dict):
            continue
        row = by_id.get(acc.get("id"))
        if row is None:
            continue
        if row.get("source") == "unknown" and "amount" in row:
            raise LedgerError(
                f"账号 {acc.get('id')} 的探测结论 source=unknown 却带了 amount"
                " —— 没探测过就不许填数"
            )
        if row.get("kind") == "ok" and "used_percent" in row:
            _check_used_percent(f"账号 {acc.get('id')}", row.get("used_percent"))

    touched = False
    for acc in accounts:
        if not isinstance(acc, dict):
            continue
        row = by_id.get(acc.get("id"))
        if row is None or not row.get("kind"):
            continue
        quota = acc.setdefault("quota", {})
        if not isinstance(quota, dict):
            quota = acc["quota"] = {}
        quota["observed_at"] = stamp
        quota.setdefault("samples", []).append({"at": stamp, "kind": row["kind"]})
        # 只有「真读到百分比」的 ok 行才写它；其余结论不写也不删 —— 旧值仍是上一次的真读数。
        if row.get("kind") == "ok" and "used_percent" in row:
            quota["used_percent"] = row["used_percent"]
        # 健康态三键的唯一写点（卡 E121 判据 2）；逐键写，绝不整块替换（会冲掉 revoked）。
        touched = _apply_probe_health(acc, row["kind"], stamp) or touched

    note_quota_history(accounts, by_id, at=_stamp_unix(stamp))

    if touched:
        save_ledger(ledger_path, data)


def _qh():
    """取 `tools/pool/quota_history.py`（曲线的判据模块，卡 A346）。

    两种跑法都要能 import：直跑脚本 / `import pool_accounts`（`tools/` 在 sys.path 上）与被
    `import tools.pool_accounts`（包路径）。懒加载：曲线缺席时账本照样能写。
    """
    try:
        from pool import quota_history as mod
    except ImportError:  # pragma: no cover —— 以包形式 import 时
        from tools.pool import quota_history as mod
    return mod


def _stamp_unix(stamp: str) -> int:
    """账本里那个 ISO 时刻 → unix 秒（曲线的 `at` 与 `samples` 的 `at` 是同一刻）。"""
    return int(datetime.fromisoformat(stamp).timestamp())


def note_quota_history(
    accounts: list, by_id: dict[str, dict], *, at: int, root: Path | None = None
) -> Path | None:
    """把这次探测里**画得出点**的窗口记进曲线；画不出（今天全部）一个字节都不写。

    * 只有 `row` 同时有窗口百分比（`used`）与已解析的时刻才记：`used` 能不能画交给
      `quota_history.point_of()`（判据只写一次）。今天的四个真账号没有 `used` ⇒ 文件不生成。
    * `at` 是本次探测的时刻（unix 秒），与 `samples` 项的 `at` 同一刻。
    * **fail-open**：曲线读不出当空、写不进去就回 `None` —— `OSError` 一律吞掉，绝不许抛到
      `record_probe_result()` 的调用方之外（账本是主）。
    """
    qh = _qh()
    base = DATA_ROOT if root is None else root
    try:
        hist = qh.load_history(root=base)
        noted = False
        for acc in accounts:
            if not isinstance(acc, dict):
                continue
            row = by_id.get(acc.get("id"))
            if row is None or not row.get("kind"):
                continue
            window = dict(row)
            if not window.get("name"):
                window["name"] = acc.get("id")
            point = qh.point_of(window, at=int(at))
            if point is None:
                continue
            scope = str(acc.get("platform") or row.get("platform") or "")
            key = qh.hist_key(scope, str(acc.get("id")))
            hist[key] = qh.prune(qh.add_point(hist.get(key, []), point), now=int(at))
            noted = True
        if not noted:
            return None
        return qh.save_history(hist, root=base)
    except Exception:  # 曲线是旁路：任何毛病都不许拦住账本那一笔
        return None


def _print_table(rows: list[dict], columns: list[tuple[str, str]]) -> None:
    widths = {key: len(title) for key, title in columns}
    for row in rows:
        for key, _ in columns:
            widths[key] = max(widths[key], min(48, len(str(row.get(key, "")))))
    head = "  ".join(title.ljust(widths[key]) for key, title in columns)
    print(head)
    print("-" * len(head))
    for row in rows:
        print(
            "  ".join(str(row.get(key, ""))[: widths[key]].ljust(widths[key]) for key, _ in columns)
        )


def cmd_list(args) -> int:
    ledger = find_ledger(args.ledger)
    data = load_ledger(ledger, strict=False)  # list 只报读数：能力表里没有的平台也如实列出
    rows = list_rows(data, args.platform, args.all)
    if args.json:
        print(json.dumps({"ledger": str(ledger), "accounts": rows}, ensure_ascii=False, indent=2))
        return EXIT_OK
    print(f"账本：{ledger}（{len(rows)} 个账号）")
    unknown = data.get("unknown_platforms") or []
    if unknown:
        print(f"⚠ 能力表里没有的平台（不许派活、probe 会拒）：{', '.join(unknown)}")
    _print_table(
        rows,
        [
            ("id", "账号"),
            ("platform", "平台"),
            ("state", "状态"),
            ("quota", "额度"),
            ("credential", "凭据位点"),
        ],
    )
    return EXIT_OK


def cmd_show(args) -> int:
    ledger = find_ledger(args.ledger)
    data = load_ledger(ledger)
    for acc in data.get("account", []):
        if acc["id"] != args.account_id:
            continue
        payload = {
            "id": acc["id"],
            "platform": acc["platform"],
            "label": mask(acc["label"]),
            "state": acc["state"],
            "approved_models": [mask(m) for m in acc["approved_models"]],
            "credential": {
                "kind": acc["credential"].get("kind"),
                "locator": mask(acc["credential"].get("locator", "")),
            },
            "quota": acc.get("quota", {}),
            "health": acc.get("health", {}),
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            for key, value in payload.items():
                print(
                    f"{key:16} {json.dumps(value, ensure_ascii=False)}"
                    if isinstance(value, (dict, list))
                    else f"{key:16} {value}"
                )
        return EXIT_OK
    raise LedgerError(f"账本里没有账号 {args.account_id!r}（先 list 看有哪些）")


def cmd_discover(args) -> int:
    if discovery_off():
        # 连账本都不读：读 accounts.toml 就已经在发现账号了（禁令 §2.2）。
        if args.json:
            print(json.dumps({"rows": []}, ensure_ascii=False, indent=2))
        print(DISCOVERY_OFF_MESSAGE, file=sys.stderr)
        return EXIT_OK
    ledger = find_ledger(args.ledger)
    data = load_ledger(ledger)
    declared = [
        a["credential"].get("locator", "") for a in data.get("account", []) if a.get("credential")
    ]
    rows = discover([d for d in declared if d], extra_dirs=args.path)
    if args.json:
        print(json.dumps({"rows": rows}, ensure_ascii=False, indent=2))
        return EXIT_OK
    _print_table(
        rows, [("pointer", "位点"), ("exists", "在"), ("status", "账本"), ("entries", "条目数")]
    )
    return EXIT_OK


def cmd_probe(args) -> int:
    ledger = find_ledger(args.ledger)
    platforms = load_platforms()
    data = load_ledger(ledger, platforms)
    rows = probe_all(data, platforms, offline=args.offline, platform=args.platform)
    now_dt = _now()
    stamp = _iso(now_dt)
    if args.json:
        record_probe_result(ledger, data, rows, now=now_dt)
        print(
            json.dumps(
                {"ledger": str(ledger), "observed_at": stamp, "results": rows},
                ensure_ascii=False,
                indent=2,
            )
        )
        return EXIT_OK
    record_probe_result(ledger, data, rows, now=now_dt)
    print(f"账本：{ledger}   观测时刻：{stamp}")
    _print_table(
        rows,
        [
            ("id", "账号"),
            ("platform", "平台"),
            ("kind", "结论"),
            ("amount", "额度"),
            ("used_percent", "已用%"),
            ("detail", "说明"),
        ],
    )
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["kind"]] = counts.get(row["kind"], 0) + 1
    print("\n小计：" + " · ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return EXIT_OK


#: `lastgood` 的模块句柄（懒加载；`None` = 还没加载过）。
_LASTGOOD = None


def _lastgood():
    """懒加载 `lastgood`（卡 A330 的写盘纪律）：包导入 / 裸模块导入 / 按路径 exec 都要能用。"""
    global _LASTGOOD
    if _LASTGOOD is not None:
        return _LASTGOOD
    try:
        from pool import lastgood as mod
    except ImportError:  # pragma: no cover —— 以包形式 import 时
        try:
            from tools.pool import lastgood as mod
        except ImportError:
            here = Path(__file__).resolve().with_name("lastgood.py")
            spec = importlib.util.spec_from_file_location("pool_lastgood_by_path", here)
            if spec is None or spec.loader is None:  # pragma: no cover —— 文件被搬走才会到这
                raise
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
    _LASTGOOD = mod
    return mod


def _validate_ledger_toml(text: str) -> None:
    """判「这份账本还能不能当 lastgood」：TOML 解得开（卡 A330），**且**每号的
    `[account.health].state` 是卡 E45 的五值之一（卡 E121 判据 5）。

    为什么校验在这里而不在 `_check_account()`：后者只在 `load_ledger()` 里跑，管不到写；
    这一份同时是**读**（`read_strict(validate=…)`）与**写**（`save_ledger()` 显式调一次）
    的口子 —— 写一个 `state = "healthy"` 不能顺利落盘。

    `health` 缺、`state` 缺都合法（老账本 / 没探过的号）；只有「出现了且不在五值里」才抛，
    并点名账号 id 与坏值。
    """
    data = tomllib.loads(text)
    accounts = data.get("account", [])
    if not isinstance(accounts, list):
        return
    for idx, acc in enumerate(accounts, start=1):
        if not isinstance(acc, dict):
            continue
        health = acc.get("health")
        if not isinstance(health, dict) or "state" not in health:
            continue
        state = health["state"]
        if state in HEALTH_STATES:
            continue
        where = acc.get("id") or f"第 {idx} 个 [[account]]"
        choices = "、".join(sorted(HEALTH_STATES))
        raise LedgerError(f"账号 {where} 的 health.state={state!r} 不合法（只认 {choices}）")


def _ck():
    """取 `tools/pool/checkin.py`（写动作的唯一所在地）。

    两种跑法都要能 import：直跑脚本 / 测试里 `import pool_accounts`（`tools/` 在
    sys.path 上 ⇒ `from pool import checkin`）与被 `import tools.pool_accounts`（⇒ 包路径）。
    懒加载：落地桩只拷部分 tools 文件，顶层 import 会让整套炸成 ModuleNotFoundError。
    """
    try:
        from pool import checkin as mod
    except ImportError:  # pragma: no cover —— 以包形式 import 时
        from tools.pool import checkin as mod
    return mod


def _checkin_archive(date: str) -> Path:
    """留档：`gates/diag/checkin-<YYYYMMDD>.json`（gitignored，进不了库）。"""
    return DATA_ROOT / "gates" / "diag" / f"checkin-{date}.json"


def run_checkin(
    data: dict,
    platforms: dict,
    *,
    apply: bool = True,
    platform: str | None = None,
    environ: dict | None = None,
    fetcher=None,
    now: datetime | None = None,
    sleep=None,
    spacing: float = 2.0,
) -> list[dict]:
    """串行跑一遍签到（卡 §3 三条硬规矩）。

    * **串行**、每号**一次**、平台间 ``spacing`` 秒 —— 拿并发换取「429 更少」不值得；
    * ``apply=False`` 即 ``--probe``：只读状态，一条写请求都不发；
    * 结论码原样上抛，`uncertain` 不重放。
    """
    import time as _time

    ck = _ck()

    environ = dict(os.environ if environ is None else environ)
    fetch = fetcher or ck.http_fetch
    nap = sleep or _time.sleep
    rows: list[dict] = []
    todo = [acc for acc in visible_accounts(data) if not platform or acc["platform"] == platform]
    for index, acc in enumerate(todo):
        plat = platforms.get(acc["platform"])
        if plat is None:
            outcome = ck.Outcome(
                ck.NOT_SUPPORTED, message=f"平台 {acc['platform']!r} 不在能力表（不许猜）"
            )
        else:
            outcome = ck.claim_for_platform(
                acc["platform"],
                plat,
                ck.tokens_from_env(plat, environ),
                fetch,
                apply=apply,
            )
        row = {
            "id": acc["id"],
            "platform": acc["platform"],
            "kind": outcome.kind,
            "credit": outcome.credit,
            "unit": outcome.unit or str(plat.get("unit", "") if plat else ""),
            "detail": outcome.summary,
        }
        rows.append(row)
        stamp = _iso(now or _now())
        _record_checkin(acc, row, stamp, apply=apply)
        # 平台之间留间隔（串行、不连环打）；最后一个不空等
        if apply and index + 1 < len(todo) and spacing:
            nap(spacing)
    return rows


def _record_checkin(acc: dict, row: dict, stamp: str, *, apply: bool = True) -> None:
    """回写账本：健康态 + 额度样本。**不碰 amount**（amount 是余额，不是本次发放）。"""
    health = acc.setdefault("health", {})
    previous = health.get("last_checkin")
    health["last_probe"] = stamp
    # ★ `--probe` 只探不领（卡 E48 §4.3）：留档 JSON 与 `last_probe` 是它许写的全部，
    #   `last_checkin` 不在授权里。写了会把「今天问过了」烙进账本 —— `recheck_rows()`
    #   拿 `last_checkin` 当结论码判 `due`，于是探一次就把当天真正的签到机会判成
    #   「当日已定案」，再也不会去领。只读探针一个判断位都不许动。
    if not apply:
        return
    health["last_checkin"] = row["kind"]
    # ★ 签到时刻另开一键（卡 E121 判据 3）：`last_probe` 是「最后一次探测」的时刻，签到也刷
    #   它，于是 `recheck_rows()` 拿 `last_probe` 当签到时刻会被下午的一次探测骗到 ——
    #   上午 09:00 签的就被读成「刚签过」⇒ `due_for_recheck()` 判「当日已定案」。
    #   这一行在 `--probe` 的早退**之后**，所以 `--probe` 仍然不会让账本看起来像
    #   「今天签过」（理由同上面那四条）。
    health["last_checkin_at"] = stamp
    # ★ 「哪些码算失败」只有一份真源（卡 E121 判据 4）：`checkin.NEEDS_HUMAN`。
    #   本文件不许再写第二份字面量 —— 两套词表已经漂过一次。
    if row["kind"] in _ck().NEEDS_HUMAN:
        health["consecutive_failures"] = int(health.get("consecutive_failures", 0) or 0) + 1
    else:
        health["consecutive_failures"] = 0
    # `samples` 记的是**额度发放**，不是「跑过一次」：只有真领到才追加（卡 §6 判据 7）。
    # `uncertain` 只涨 `consecutive_failures`，不许在额度账上留下 0 —— 那会被读成「今天发 0 个」。
    if row["kind"] != "claimed" and not row.get("credit"):
        return
    quota = acc.setdefault("quota", {})
    samples = quota.setdefault("samples", [])
    entry = {"at": stamp, "kind": row["kind"]}
    if row.get("credit"):
        entry["credit"] = row["credit"]
    if previous and previous != row["kind"]:
        entry["was"] = previous
    samples.append(entry)


def _stamp_or_none(raw: object) -> datetime | None:
    """账本里的 ISO 时刻 → aware `datetime`；认不出 ⇒ `None`（**当没有**，不猜）。

    不带时区的那种按 `TZ` 解释：这份账本只由本工具写，口径就是 `TZ`（卡 A343 §判据 5）。
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw.strip())
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=TZ)


def recheck_rows(
    data: dict, platforms: dict, *, now: datetime | None = None, platform: str | None = None
) -> list[dict]:
    """哪些号此刻该再问一次签到（**只读**：不签到、不写账本、不写留档）。

    判据全在 `tools/pool/checkin.py`（`due_for_recheck()` / `provisional()`）；这里只做
    「把账本里的历史形状读成判据要的输入」+ 稳定排序 `(platform, id)`。

    ★ 本函数（整张卡）**唯一**的 fail-open：`health["last_checkin"]` 认不出、或时刻坏了，
    一律当「从没问过」⇒ 会去复查。方向是对的 —— 复查签到是**幂等**动作（再问一次只是重新
    读一遍「签没签」），比「时间戳坏了就永远不复查」安全得多。

    读得懂的历史形状（账本在仓外、跨版本累计，必须容忍）：
      · `last_checkin = "claimed"` 这类**结论码字符串**（今天唯一在写的形状）⇒ 结论码有了，
        时刻取 `health["last_checkin_at"]`（卡 E121 起签到自己写这一键），**缺失才回落**
        `health["last_probe"]`（老账本没有新键；兼容分支不许删）；
      · `last_checkin = "2026-10-25T18:30:46+08:00"` 这类**ISO 时刻**（老账本）⇒ 只知道
        「什么时候问过」、不知道结论 ⇒ 按 `uncertain` 算（没定论比「当成签过了」诚实）；
      · 时刻不带时区 ⇒ 按 `TZ` 解释。

    ★ 为什么不能拿 `last_probe` 当签到时刻（卡 E121 判据 3）：签到**也**刷 `last_probe`
    （`_record_checkin()`），探测同样刷它。下午探一次，上午 09:00 的签到就被读成
    「刚签过」⇒ `due_for_recheck()` 判「当日已定案」，当天真正的复查机会就没了。
    所以时刻分键：探测写 `last_probe`（字面语义），签到写 `last_checkin_at`。

    「平台压根没有签到接口」不算从没问过：能力表 `claim_flow` 为空 ⇒ 结论码补
    `not-supported`，`due_for_recheck()` 那边直接给「平台不支持签到」（不问）。
    """
    ck = _ck()
    moment = now if now is not None else _now()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=TZ)
    rows: list[dict] = []
    for acc in visible_accounts(data):
        name = str(acc.get("platform", ""))
        if platform and name != platform:
            continue
        health = acc.get("health") or {}
        raw = health.get("last_checkin")
        at: datetime | None = None
        kind = ""
        if isinstance(raw, str) and raw.strip():
            text = raw.strip()
            if text in ck.KINDS:
                kind = text
                at = _stamp_or_none(health.get("last_checkin_at"))
                if at is None:  # 老账本没有新键 ⇒ 回落（兼容分支；主线仍是新键）
                    at = _stamp_or_none(health.get("last_probe"))
            else:
                at = _stamp_or_none(text)
                if at is not None:
                    kind = ck.UNCERTAIN
        if not kind and name in platforms and not ck.platform_supports_claim(platforms[name]):
            kind = ck.NOT_SUPPORTED
        outcome = ck.Outcome(kind) if kind else None
        # ★ 为什么不传 `offline=`/`tries=`（两个形参在 `checkin.due_for_recheck` 上）：
        #   本仓**不存在**「离线造成的 FAILED」。`claim_for_platform` 撞 `NetworkError`
        #   一律出 `UNCERTAIN`（`tools/pool/checkin.py:815-817`），FAILED 只来自
        #   「服务器答复了但内容不对」（HTTP≥400 或 JSON 形状坏）。于是这里没有任何
        #   真实值可传 —— 传 `offline=True` 等于替上游撒一个它没说的谎，指数退避会开始
        #   按一个**从没发生过**的状态计时（`retry_after_s(tries=9)` 与 `tries=0` 差 30 倍）。
        #   宁可不接，也不接假数。要接的前提是先让「离线」在结论码里可表达（那是另一张卡）。
        need, why = ck.due_for_recheck(outcome, at=at, now=moment, timezone=TZ, platform=name)
        if not need:
            continue
        morning = bool(
            outcome is not None
            and at is not None
            and ck.provisional(outcome, at=at, now=moment, timezone=TZ)
        )
        rows.append(
            {"id": str(acc.get("id", "")), "platform": name, "why": why, "provisional": morning}
        )
    rows.sort(key=lambda row: (row["platform"], row["id"]))
    return rows


def write_checkin_archive(date: str, payload: dict) -> Path:
    path = _checkin_archive(date)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".checkin-", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


def cmd_checkin(args) -> int:
    """`checkin`：用户开口才跑一次（拉取式，无后台定时）。"""
    ck = _ck()

    ledger = find_ledger(args.ledger)
    platforms = load_platforms()
    data = load_ledger(ledger, platforms, strict=not args.all)
    apply = not args.probe
    now = _now()
    rows = run_checkin(
        data,
        platforms,
        apply=apply,
        platform=args.platform,
        spacing=args.spacing,
    )
    stamp = _iso(now)
    date = now.strftime("%Y-%m-%d")
    needs_human = [r for r in rows if r["kind"] in ck.NEEDS_HUMAN]
    payload = {
        "date": date,
        "generated_at": stamp,
        "ledger": str(ledger),
        "applied": apply,
        "results": rows,
    }
    archive = write_checkin_archive(date, payload)
    save_ledger(ledger, data)

    if args.json:
        print(json.dumps({**payload, "archive": str(archive)}, ensure_ascii=False, indent=2))
    else:
        head = "签到（已领取）" if apply else "签到探针（只读，不发写请求）"
        print(f"{head}   {stamp}   账本：{ledger}")
        _print_table(
            rows,
            [
                ("id", "账号"),
                ("platform", "平台"),
                ("kind", "结论"),
                ("credit", "本次"),
                ("detail", "说明"),
            ],
        )
        counts: dict[str, int] = {}
        for row in rows:
            counts[row["kind"]] = counts.get(row["kind"], 0) + 1
        print("\n小计：" + " · ".join(f"{k}={v}" for k, v in sorted(counts.items())))
        print(f"留档：{archive}")
    return EXIT_NEEDS_HUMAN if needs_human else EXIT_OK


def cmd_due(args) -> int:
    """`due`：哪些号现在该再问一次签到（**只读**；不签到、不写账本、不写留档）。"""
    ledger = find_ledger(args.ledger)
    platforms = load_platforms()
    data = load_ledger(ledger, platforms)
    now: datetime | None = None
    if args.now:
        try:
            now = datetime.fromisoformat(args.now)
        except ValueError:
            print(f"--now 认不出：{args.now!r}（要 ISO-8601）", file=sys.stderr)
            return EXIT_USAGE
        if now.tzinfo is None:
            now = now.replace(tzinfo=TZ)
    rows = recheck_rows(data, platforms, now=now, platform=args.platform)
    moment = _iso(now or _now())
    if args.json:
        print(
            json.dumps(
                {"ledger": str(ledger), "now": moment, "results": rows},
                ensure_ascii=False,
                indent=2,
            )
        )
        return EXIT_OK
    print(f"账本：{ledger}   现在：{moment}   该复查：{len(rows)} 个")
    if rows:
        _print_table(
            rows,
            [
                ("id", "账号"),
                ("platform", "平台"),
                ("provisional", "上午那句"),
                ("why", "为什么"),
            ],
        )
    return EXIT_OK


def selftest() -> int:
    """不碰真实账本/网络的自检：证据用。"""
    sample = {
        "platform": {
            "demo": {
                "label": "Demo",
                "probe": "http",
                "token_env": "TF_DEMO_TOKEN",
                "probe_url": "https://example.invalid/x",
                "base_urls": ["https://example.invalid"],
            }
        }
    }
    acc = {
        "id": "demo-1",
        "label": "演示",
        "platform": "demo",
        "state": "active",
        "added_at": "2026-10-25",
        "approved_models": ["m1"],
        "credential": {"kind": "file", "locator": "~/.demo/token"},
    }
    calls: list[str] = []

    def fake_fetch(url, token):
        calls.append(url)
        return 200, {"data": {"total": 42}}, ""

    os.environ.setdefault("TF_DEMO_TOKEN", "selftest-token")
    ok = probe_account(acc, sample["platform"]["demo"], fetch=fake_fetch)
    offline_calls: list[str] = []
    probe_account(
        acc,
        sample["platform"]["demo"],
        fetch=lambda u, t: offline_calls.append(u) or (0, None, ""),
        offline=True,
    )
    checks = [
        ("ok 结论码", ok["kind"] == "ok"),
        ("额度 42", ok.get("amount") == 42.0),
        ("--offline 不发请求", offline_calls == []),
        (
            "未记录的沙箱平台不猜",
            probe_account(acc, {"probe": "manual"}, fetch=fake_fetch)["kind"] == "uncertain",
        ),
        (
            "token 缺失报 uncertain",
            probe_account(
                {**acc},
                {
                    "probe": "http",
                    "token_env": "TF_NOPE_MISSING",
                    "probe_url": "https://example.invalid/x",
                },
                fetch=fake_fetch,
            )["kind"]
            == "uncertain",
        ),
        ("打码", mask("Bearer sk-abcdefgh12345678").count("sk-") == 0),
    ]
    for name, good in checks:
        print(f"[{'OK ' if good else 'FAIL'}] {name}")
    return EXIT_OK if all(good for _, good in checks) else 1


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="pool_accounts", description="账号账本与只读探测（卡 E45）")
    ap.add_argument("--ledger", help="账本路径；默认向上找 infra/pool/accounts.toml")
    ap.add_argument("--selftest", action="store_true", help="自检（不碰真账本/网络）")
    sub = ap.add_subparsers(dest="cmd")

    p_list = sub.add_parser("list", help="列账号（默认不列墓碑）")
    p_list.add_argument("--json", action="store_true")
    p_list.add_argument("--all", action="store_true", help="含墓碑/停用")
    p_list.add_argument("--platform")

    p_show = sub.add_parser("show", help="看一个账号")
    p_show.add_argument("account_id")
    p_show.add_argument("--json", action="store_true")

    p_disc = sub.add_parser("discover", help="静态盘点凭据位点（只 stat）")
    p_disc.add_argument("--json", action="store_true")
    p_disc.add_argument("--path", action="append", help="额外位点，可重复")

    p_ck = sub.add_parser("checkin", help="签到（用户开口才跑；--probe 只读）")
    p_ck.add_argument("--json", action="store_true")
    p_ck.add_argument(
        "--all", action="store_true", help="含能力表里没有的平台（如实报 not-supported）"
    )
    p_ck.add_argument("--probe", action="store_true", help="只探不领：一条写请求都不发")
    p_ck.add_argument("--platform")
    p_ck.add_argument("--spacing", type=float, default=2.0, help="平台间隔秒数（默认 2）")

    p_probe = sub.add_parser("probe", help="只读探测（额度）")
    p_probe.add_argument("--json", action="store_true")
    p_probe.add_argument("--offline", action="store_true", help="不发网络请求")
    p_probe.add_argument("--platform")
    p_due = sub.add_parser("due", help="哪些号现在该再问一次签到（只读；不签到）")
    p_due.add_argument("--json", action="store_true")
    p_due.add_argument("--now", default=None, help="注入『现在』（ISO-8601；测试不许靠真实钟表）")
    p_due.add_argument("--platform")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.selftest:
        return selftest()
    handlers = {
        "list": cmd_list,
        "show": cmd_show,
        "discover": cmd_discover,
        "probe": cmd_probe,
        "checkin": cmd_checkin,
        "due": cmd_due,
    }
    handler = handlers.get(args.cmd or "")
    if handler is None:
        build_parser().print_help()
        return EXIT_USAGE
    try:
        return handler(args)
    except LedgerError as exc:
        print(f"账号账本：{exc}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
