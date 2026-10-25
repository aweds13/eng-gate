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
    python -X utf8 tools/pool_accounts.py --selftest

退出码：0 = 正常（含「未探测」）；2 = 用法/账本缺失/账本格式错。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import tomllib

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
CRED_KINDS = ("file", "dir", "keychain", "cookie_jar", "env", "none")
SECRET_RE = re.compile(r"(?i)(bearer\s+)?(sk-|ak-|ghp_|xoxb-)[A-Za-z0-9_\-]{8,}")

EXIT_OK, EXIT_USAGE = 0, 2
#: 有号需要人看（uncertain/failed）—— 与「用法错」分开，脚本能分辨
EXIT_NEEDS_HUMAN = 1


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

    start = Path.cwd().resolve()
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
    """逐字段校验，报错要点名「第几个 + 哪个字段」，不许只说格式错。"""
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
    plat = platforms if platforms is not None else load_platforms()
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
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


def save_ledger(path: Path, data: dict) -> None:
    """原子替换写回（E48 用；E45 只读面不调它，但格式必须与读的一模一样）。

    `samples` 只留最近 SAMPLES_CAP 条；写坏半个文件比不写更糟 ⇒ 同目录临时文件 + os.replace。
    """
    for acc in data.get("account", []):
        quota = acc.get("quota")
        if isinstance(quota, dict) and isinstance(quota.get("samples"), list):
            quota["samples"] = quota["samples"][-SAMPLES_CAP:]
    payload = _dump_toml(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".accounts-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(payload)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


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
]


def discover(ledger_locators: list[str], extra_dirs: list[str] | None = None) -> list[dict]:
    """只 stat，绝不读内容：把「本机有的凭据位点」与「账本里登记过的」对一遍。

    `ledger_locators` 只放账本里真实声明过的 locator；常量清单 DECLARED_DIRS 是**待查**的位点，
    不是「已登记」—— 否则每行都会显示已登记，等于没查。
    """
    declared = set(ledger_locators)
    seen: set[str] = set()
    out = []
    for raw in list(ledger_locators) + DECLARED_DIRS + list(extra_dirs or []):
        if raw in seen:
            continue
        seen.add(raw)
        path = Path(os.path.expanduser(raw))
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


def _token_for(plat: dict) -> tuple[str, str]:
    """返回 (token, 用的环境变量名)。多个用 / 分隔，取第一个非空的。"""
    names = [n for n in str(plat.get("token_env", "")).split("/") if n]
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value, name
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


def probe_account(acc: dict, plat: dict, fetch=None, offline: bool = False) -> dict:
    """单账号只读探测。

    结论码只许这六个：ok / skipped / uncertain / failed / not-supported / unknown-platform。
    """
    fetch = fetch or _get_json
    base = {"id": acc["id"], "platform": acc["platform"]}

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
    amount = _extract_amount(body)
    if amount is None:
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


# --------------------------------------------------------------------------
# 命令
# --------------------------------------------------------------------------


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
    stamp = _iso(_now())
    if args.json:
        print(
            json.dumps(
                {"ledger": str(ledger), "observed_at": stamp, "results": rows},
                ensure_ascii=False,
                indent=2,
            )
        )
        return EXIT_OK
    print(f"账本：{ledger}   观测时刻：{stamp}")
    _print_table(
        rows,
        [
            ("id", "账号"),
            ("platform", "平台"),
            ("kind", "结论"),
            ("amount", "额度"),
            ("detail", "说明"),
        ],
    )
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["kind"]] = counts.get(row["kind"], 0) + 1
    print("\n小计：" + " · ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return EXIT_OK


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
        _record_checkin(acc, row, stamp)
        # 平台之间留间隔（串行、不连环打）；最后一个不空等
        if apply and index + 1 < len(todo) and spacing:
            nap(spacing)
    return rows


def _record_checkin(acc: dict, row: dict, stamp: str) -> None:
    """回写账本：健康态 + 额度样本。**不碰 amount**（amount 是余额，不是本次发放）。"""
    health = acc.setdefault("health", {})
    previous = health.get("last_checkin")
    health["last_probe"] = stamp
    health["last_checkin"] = row["kind"]
    if row["kind"] in ("uncertain", "failed"):
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
