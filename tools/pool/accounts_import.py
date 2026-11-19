"""卡 A371（T-AG656）：账号导入 —— 认多种工具导出的文件形状，读不懂的点名交出来.

源实现是 magpie 的 accounts import <codex|claude|antigravity|factory> <file>... [--yes]
（_ext/magpie-main/internal/cli/accounts_cli.go:33 → internal/provider/login_import.go）。
这里从头写一条新写路径，按仓规钉死五件事：

1. **源文件只读**：一个字节都不改（判据 J2）—— 全程只有 read_bytes()；
2. **不联网、不探测**（J6）：导入是「登记」不是「验证」。magpie 对 claude 那条的原话是
   "kept as it came, not tried"；本模块连探测函数的门都不认识；
3. **写账本只走 pool_accounts.save_ledger()**（J8）：它自带行首注释闸、samples 截断、
   TOML 重生成与校验、原子写。本模块没有 open(..., "w")，也不自己拼 TOML；
4. **认不出的条目逐条点名**（J3）：结果表每行 where / status / reason，四类计数之和
   必须等于输入条目总数 —— 不许静默跳过；
5. **默认只算不写**（J9）：不带 --yes 只打印计划，账本 mtime 与 sha256 都不动。

id 的生成规则（J11 要的「钉死」，由 A344 的 resolve_account_id() 反过来验）：

    id = "<agent>-<slug>"

slug 取 email 的本地部分（清洗成小写 [a-z0-9._-]）；没有 email 就用 refresh token 的
sha256 前 8 位（tok<hex>）。**绝不从 credential.locator 末段猜** —— file 型的末段是
存储名不是号名（tools/pool/account_id.py:56 只对 kind == "dir" 认末段）。
同一条行还会写 profile（email 没被占用就是 email，否则就是 id），于是 A344 的三步解析里
第 ① 步直接命中，派活的人给 email 或给 id 都能指回这一行。

账本 platform 只认 tools/pool/platforms.toml 里已有的平台：codex / claude / antigravity 是
**源格式**不是平台（那张表是平台能力表，不是源格式表 —— 卡规格缺口 2），所以 --platform
必须由人指名；不指名就点名报错，绝不硬编一个不在能力表里的值。
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:  # 与 pool_accounts / pool/account_id.py 同一套双形状导入
    import pool_accounts as pa
except ImportError:  # pragma: no cover - 只在被当成 tools.* 包导入时走到
    from tools import pool_accounts as pa

#: CLI 认这三个名字（J1）。factory 明确拒绝并指向 accounts add，见 REFUSED_AGENTS。
AGENTS = ("codex", "claude", "antigravity")
#: magpie 原件 accounts_cli.go:544 把 factory|droid 指到 accounts add <这个名字>。
REFUSED_AGENTS = ("factory", "droid")

#: 抄 magpie 原话（internal/provider/login_import.go:93 的 err: "not an account"）。
NOT_AN_ACCOUNT = "not an account"
#: 同上 :204 的 accessOnly 文案。
ACCESS_ONLY = (
    "only an access token, no refresh_token: it would stop working within days and "
    "can't be renewed; sign in to this account instead"
)
#: 同上 :204 附近的 API key 文案。
API_KEY_MSG = "an API key, not a sign-in; add it as a key instead"
#: 同上 :259 的注释原话（多文件里某一份没有东西：说出来，不许略过）。
FILE_HOLDS_NONE = "one file of several that holds none: said, not passed over"
#: 同上 :304-346 的重复条目文案。
IN_THE_FILES_TWICE = "in the files twice"
#: Sub2API 的 platform 到「源 agent」的映射（login_import.go:230）。
_PLATFORM_TO_AGENT = {"openai": "codex", "anthropic": "claude", "claude": "claude"}
#: _print_table 的列（与 pool_accounts 里那份同形）。
COLUMNS = (("where", "where"), ("status", "status"), ("reason", "reason"))


@dataclass
class Entry:
    """一条「输入条目」：认出来的带凭据，认不出的带 err（逐条点名，不丢）。"""

    where: str
    agent: str
    #: 这条条目出自哪一份源文件（credential.locator 用它；J2 要求只读，所以只存路径字符串）
    file: str = ""
    refresh: str = ""
    access: str = ""
    id_token: str = ""
    email: str = ""
    account_id: str = ""
    scopes: list[str] = field(default_factory=list)
    err: str = ""
    status: str = ""
    reason: str = ""
    ident: str = ""
    row: dict = field(default_factory=dict)


def _first(source: dict, *keys: str) -> str:
    """按顺序取第一个非空字符串（字典型凭据字段名两套拼法都认）。"""
    if not isinstance(source, dict):
        return ""
    for key in keys:
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _scopes(value: object) -> list[str]:
    """magpie importScopes：list 取字符串，string 按空白切。"""
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str) and v]
    if isinstance(value, str):
        return value.split()
    return []


def _fingerprint(token: str) -> str:
    """凭据指纹：只落 hash（J5 要能判「已在账本」，J12 不许落明文）。"""
    return "sha256:" + hashlib.sha256(token.encode("utf-8")).hexdigest()[:32]


def _slug(text: str) -> str:
    """id 里的那段：小写、只留 [a-z0-9._-]、首尾的 - 去掉。"""
    out = []
    for ch in text.strip().lower():
        out.append(ch if (ch.isalnum() or ch in "._-") else "-")
    return "".join(out).strip("-")


def ident_for(agent: str, email: str, token: str) -> str:
    """J11 钉死的 id 规则：<agent>-<email 本地部分>，无 email 用 token hash 前 8 位。"""
    slug = _slug(email.split("@", 1)[0]) if email else ""
    if not slug:
        slug = "tok" + hashlib.sha256(token.encode("utf-8")).hexdigest()[:8]
    return f"{agent}-{slug}"


# ============================================================ 源文件 → 条目
def _read_text(path: Path) -> str:
    """只读：read_bytes() + 去 BOM。整份导入里对源文件只有这一处 IO，且是读。"""
    return path.read_bytes().decode("utf-8-sig", errors="replace")


def _login_entry(agent: str, node: dict, name: str, path: str) -> Entry:
    """magpie loginEntry：Codex auth.json 的 tokens、Claude .credentials.json 的
    claudeAiOauth、以及 CliproxyAPI 的扁平形状都从这里走。"""
    sub = ""
    source: dict = node
    if agent == "codex" and isinstance(node.get("tokens"), dict):
        source, sub = node["tokens"], ".tokens"
    if agent == "claude" and isinstance(node.get("claudeAiOauth"), dict):
        source, sub = node["claudeAiOauth"], ".claudeAiOauth"
    entry = Entry(where=f"{name}#{path}{sub}", agent=agent)
    entry.id_token = _first(source, "id_token", "idToken")
    entry.access = _first(source, "access_token", "accessToken", "personal_access_token")
    entry.refresh = _first(source, "refresh_token", "refreshToken")
    entry.email = _first(source, "email")
    entry.account_id = _first(source, "account_id", "accountId")
    entry.scopes = _scopes(source.get("scopes"))
    kind = str(node.get("type") or "").strip().lower()
    if kind and kind != agent:
        entry.err = f"a {kind} sign-in, not {agent}'s"
        return entry
    if agent == "codex" and isinstance(node.get("claudeAiOauth"), dict):
        entry.err = "not a Codex sign-in"
        return entry
    if agent == "claude" and isinstance(node.get("tokens"), dict):
        entry.err = "not a Claude sign-in"
        return entry
    if not entry.refresh:
        if _first(node, "OPENAI_API_KEY", "api_key", "apiKey"):
            entry.err = API_KEY_MSG
        elif entry.access:
            entry.err = ACCESS_ONLY
        else:
            entry.err = NOT_AN_ACCOUNT
    return entry


def _sub2api_entry(agent: str, node: dict, name: str, path: str) -> Entry:
    """magpie sub2apiEntry：{accounts:[{platform, type:"oauth", credentials:{…}}]}。"""
    cred = node.get("credentials") or {}
    extra = node.get("extra") or {}
    platform = str(node.get("platform") or "").strip().lower()
    entry = Entry(where=f"{name}#{path}", agent=agent)
    entry.refresh = _first(cred, "refresh_token", "refreshToken")
    entry.access = _first(cred, "access_token", "accessToken")
    entry.id_token = _first(cred, "id_token", "idToken")
    entry.email = _first(cred, "email", "email_address") or _first(
        extra, "email_address", "email"
    )
    entry.account_id = _first(cred, "chatgpt_account_id", "account_id", "accountId")
    entry.scopes = _scopes(cred.get("scope", cred.get("scopes")))
    if not entry.email:
        label = str(node.get("name") or "")
        if "@" in label:
            entry.email = label.strip()
    kind = str(node.get("type") or "").strip().lower()
    ours = _PLATFORM_TO_AGENT.get(platform)
    if ours != agent:
        entry.err = f"a {platform or '?'} account, not {agent}'s"
    elif kind == "apikey":
        entry.err = API_KEY_MSG
    elif kind and kind != "oauth":
        entry.err = f"not a {agent} sign-in"
    elif not entry.refresh:
        entry.err = ACCESS_ONLY if entry.access else "no refresh_token in it"
    return entry


def _codexbar_entries(agent: str, node: dict, name: str, path: str) -> list[Entry] | None:
    """magpie codexbarEntries：~/.codexbar/config.json 的 providers/remoteConnection。

    不是 codexbar 形状就回 None（交给 _login_entry），认出来则回条目列表（可能为空）。
    """
    providers = node.get("providers")
    if not isinstance(providers, list):
        return None
    rows: list[dict] = []
    for provider in providers:
        if not isinstance(provider, dict):
            continue
        if provider.get("kind") != "openai_oauth":
            continue
        accounts = provider.get("accounts")
        if isinstance(accounts, list):
            rows.extend(accounts)
    remote = node.get("openAI")
    if isinstance(remote, dict) and isinstance(remote.get("remoteConnectionAccounts"), list):
        rows.extend(remote["remoteConnectionAccounts"])
    out: list[Entry] = []
    seen: set[str] = set()
    for index, item in enumerate(rows):
        where = f"{name}#{path}.providers[{index}]"
        if not isinstance(item, dict):
            out.append(Entry(where=where, agent=agent, err=NOT_AN_ACCOUNT))
            continue
        entry = Entry(where=where, agent=agent)
        entry.refresh = _first(item, "refreshToken", "refresh_token")
        entry.access = _first(item, "accessToken", "access_token")
        entry.id_token = _first(item, "idToken", "id_token")
        entry.email = _first(item, "email")
        entry.account_id = _first(item, "openAIAccountId", "openaiAccountId")
        if entry.refresh:
            if entry.refresh in seen:
                continue
            seen.add(entry.refresh)
        if agent != "codex":
            entry.err = f"a ChatGPT account, not {agent}'s"
        elif item.get("kind") == "api_key":
            entry.err = API_KEY_MSG
        elif not entry.refresh:
            entry.err = ACCESS_ONLY if entry.access else "no refresh_token in it"
        out.append(entry)
    return out


def _walk(agent: str, node: object, name: str, path: str, out: list[Entry]) -> None:
    """magpie walk：list 递归、map 按四种形状分流、string 当 refresh token。"""
    if isinstance(node, list):
        for index, item in enumerate(node):
            _walk(agent, item, name, f"{path}[{index}]", out)
        return
    if isinstance(node, str):
        token = node.strip()
        if not token:
            out.append(Entry(where=f"{name}#{path}", agent=agent, err=NOT_AN_ACCOUNT))
        else:
            out.append(Entry(where=f"{name}#{path}", agent=agent, refresh=token))
        return
    if not isinstance(node, dict):
        out.append(Entry(where=f"{name}#{path}", agent=agent, err=NOT_AN_ACCOUNT))
        return
    if isinstance(node.get("credentials"), dict) and node.get("platform"):
        out.append(_sub2api_entry(agent, node, name, path))
        return
    codexbar = _codexbar_entries(agent, node, name, path)
    if codexbar is not None:
        out.extend(codexbar)
        return
    inner = node.get("accounts")
    if isinstance(inner, list) and not (node.get("refresh_token") or node.get("refreshToken")):
        for index, item in enumerate(inner):
            _walk(agent, item, name, f"{path}.accounts[{index}]", out)
        return
    out.append(_login_entry(agent, node, name, path))


def parse_file(agent: str, name: str, text: str) -> tuple[list[Entry], str]:
    """一份文件 → (条目, 文件级错误)。空 ⇒ nothing to import；全认不出 ⇒ no accounts in it。"""
    body = text.replace("\r\n", "\n").strip()
    if not body:
        return [], "nothing to import"
    if body[0] in "[{":
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            return [], f"not valid JSON: {exc.msg}（第 {exc.lineno} 行）"
        out: list[Entry] = []
        _walk(agent, data, name, "$", out)
        if not out:
            return [], "no accounts in it"
        for entry in out:
            entry.file = name
        return out, ""
    out = []
    counted = 0
    for lineno, line in enumerate(body.split("\n"), start=1):
        token = line.strip()
        if not token or token.startswith("#"):
            continue
        counted += 1
        where = f"{name}:{lineno}（第 {counted} 条）"
        if any(ch in token for ch in " \t") or "://" in token:
            out.append(Entry(where=where, agent=agent, err="not a refresh token"))
            continue
        out.append(Entry(where=where, agent=agent, refresh=token))
    if counted == 0:
        return [], "no accounts in it"
    for entry in out:
        entry.file = name
    return out, ""


# ============================================================ 条目 → 计划
def _existing_fingerprints(data: dict) -> dict[str, str]:
    """账本里已有的凭据指纹 → id（J5 的判据来源：指纹命中就 exists，不覆盖）。"""
    out: dict[str, str] = {}
    for acc in data.get("account", []):
        cred = acc.get("credential") or {}
        mark = cred.get("fingerprint") if isinstance(cred, dict) else ""
        if isinstance(mark, str) and mark:
            out.setdefault(mark, str(acc.get("id", "")))
    return out


def _row_for(entry: Entry, ident: str, profile: str, platform: str, locator: str, now) -> dict:
    """一整行 [[account]]。字段口径照 pool_accounts._check_account()（J10）。"""
    label = f"{entry.agent} {entry.email or ident}"
    return {
        "id": ident,
        "label": label,
        "profile": profile,
        "platform": platform,
        "state": "active",
        "added_at": pa._iso(now),
        "approved_models": [],
        "credential": {
            "kind": "file",
            "locator": locator,
            "fingerprint": _fingerprint(entry.refresh),
        },
        "quota": {"source": "unknown"},
        "health": {"state": "unknown", "consecutive_failures": 0},
    }


def plan_entries(
    entries: list[Entry], platform: str, data: dict, locators: dict[str, str], now
) -> list[Entry]:
    """把条目分成 added / exists / skipped / failed 四类；四类之和 == 条目数（J3）。

    分流顺序抄 magpie login_import.go:304-346：先 parse 错误，再「没有 refresh」，
    再「账本里已经有这个指纹」，最后「这一批里出现了两次」。
    """
    taken = {str(acc.get("id", "")) for acc in data.get("account", [])}
    profiles = {str(acc.get("profile")) for acc in data.get("account", []) if acc.get("profile")}
    have = _existing_fingerprints(data)
    seen: dict[str, str] = {}
    planned: list[Entry] = []
    for entry in entries:
        if entry.err == NOT_AN_ACCOUNT:
            entry.status, entry.reason = "skipped", NOT_AN_ACCOUNT
        elif entry.err:
            entry.status, entry.reason = "failed", entry.err
        elif not entry.refresh:
            entry.status, entry.reason = "failed", "no refresh_token in it"
        else:
            mark = _fingerprint(entry.refresh)
            if mark in have:
                entry.status = "exists"
                entry.ident = have[mark]
                entry.reason = f"账本里已经有这个凭据（指纹命中 {entry.ident}）"
            elif mark in seen:
                entry.status = "failed"
                entry.reason = f"{IN_THE_FILES_TWICE}（第一次出现在 {seen[mark]}）"
            else:
                ident = ident_for(entry.agent, entry.email, entry.refresh)
                base, bump = ident, 1
                while ident in taken:
                    bump += 1
                    ident = f"{base}-{bump}"
                taken.add(ident)
                profile = entry.email.strip().lower() or ident
                if profile in profiles:
                    profile = ident
                profiles.add(profile)
                entry.ident = ident
                entry.status = "added"
                entry.reason = f"新增（profile = {profile}）"
                entry.row = _row_for(
                    entry,
                    ident,
                    profile,
                    platform,
                    locators.get(entry.file) or entry.file,
                    now,
                )
                seen[mark] = entry.where
        planned.append(entry)
    return planned


def _counts(entries: list[Entry]) -> dict[str, int]:
    out = {"added": 0, "exists": 0, "skipped": 0, "failed": 0}
    for entry in entries:
        out[entry.status] = out.get(entry.status, 0) + 1
    return out


def _factory_refusal(agent: str) -> str:
    return (
        f"{agent} 的账号不走导入：它不是 sign-in 形状，用 accounts add {agent} "
        "（magpie 原件 accounts_cli.go:544 把 factory|droid 指到 accounts add）"
    )


def _usage(message: str) -> int:
    print(message, file=sys.stderr)
    return pa.EXIT_USAGE


def cmd_import(args) -> int:
    """导入子命令的入口：账本异常在这里收口，别让 traceback 糊住行号。

    ★ 为什么不只靠 pool_accounts.main() 里那句 except LedgerError：走
    python -X utf8 tools/pool_accounts.py 时，那份文件是 __main__，而本模块里的 pa 是
    **另一个**模块对象（pool_accounts）—— 两个 LedgerError 不是同一个类，main() 抓不到。
    （实测：不加这一层，撞上注释闸时人看到的是一段 traceback，行号埋在最后一行。）
    收口放在这里之后，行号照样念出来（J8），退出码与 main() 同口径。
    """
    try:
        return _run_import(args)
    except pa.LedgerError as exc:
        print(f"账号账本：{exc}", file=sys.stderr)
        return pa.EXIT_USAGE


def _run_import(args) -> int:
    """读文件 → 归一成条目 → 生成计划 → 只在 --yes 时写账本（写只走 save_ledger）。"""
    if pa.discovery_off():
        # 与 cmd_discover 同构：**连账本都不读** —— 读 accounts.toml 就是在发现账号。
        print(pa.DISCOVERY_OFF_MESSAGE, file=sys.stderr)
        return pa.EXIT_NEEDS_HUMAN
    agent = str(getattr(args, "agent", "") or "").strip()
    if agent in REFUSED_AGENTS:
        return _usage(_factory_refusal(agent))
    if agent not in AGENTS:
        known = "/".join(AGENTS)
        refused = "/".join(REFUSED_AGENTS)
        return _usage(f"未知的 --agent {agent!r}（只认 {known}；{refused} 要用 accounts add）")
    if getattr(args, "yes", False) and getattr(args, "dry_run", False):
        return _usage("--dry-run 与 --yes 只能给一个：一个是只算不写，一个是真写")
    files = [Path(p) for p in (getattr(args, "files", None) or [])]
    if not files:
        return _usage("import 至少要一个文件")
    platform = str(getattr(args, "platform", "") or "").strip()
    if not platform:
        return _usage(
            "import 必须用 --platform 指名这批凭据属于哪个平台的账本行："
            "codex/claude/antigravity 是源格式，不是 tools/pool/platforms.toml 里的平台"
        )
    platforms = pa.load_platforms()
    if platform not in platforms:
        known = "、".join(sorted(platforms)) or "（空）"
        return _usage(
            f"--platform {platform!r} 不在 tools/pool/platforms.toml 里（已知：{known}）"
        )
    ledger_path = pa.find_ledger(getattr(args, "ledger", None))
    data = pa.load_ledger(ledger_path, platforms=platforms, strict=True)
    entries: list[Entry] = []
    file_rows: list[Entry] = []
    file_notes: list[tuple[str, str]] = []
    for path in files:
        name = str(path)
        try:
            text = _read_text(path)
        except OSError as exc:
            entries.append(
                Entry(
                    where=name,
                    agent=agent,
                    file=name,
                    err=f"读不了这个文件：{exc.strerror or exc}",
                )
            )
            continue
        got, file_err = parse_file(agent, name, text)
        if not file_err:
            entries.extend(got)
            continue
        if len(files) == 1:
            print(f"{name}：{file_err}", file=sys.stderr)
            return pa.EXIT_NEEDS_HUMAN
        # 表里那一格按 _COL_MAX 截断，放不下「这份文件为什么认不出」—— 原话再单独说一遍，
        # 免得人只看到一句「有几条没导入」却不知道是哪份文件、坏在哪。
        file_notes.append((name, file_err))
        file_rows.append(
            Entry(
                where=name,
                agent=agent,
                file=name,
                status="skipped",
                reason=f"{FILE_HOLDS_NONE}（{file_err}）",
            )
        )
    locators = {str(path): str(path) for path in files}
    planned = plan_entries(entries, platform, data, locators, pa._now())
    planned.extend(file_rows)
    counts = _counts(planned)
    missing = counts["skipped"] + counts["failed"]
    if missing:
        print(f"{missing} 条未导入", file=sys.stderr)
    for name, note in file_notes:
        print(f"{name}：{note}（{FILE_HOLDS_NONE}）", file=sys.stderr)
    pa._print_table(
        [{"where": e.where, "status": e.status, "reason": e.reason} for e in planned], COLUMNS
    )
    new_rows = [e for e in planned if e.status == "added"]
    summary = (
        f"新增 {counts['added']} · 已存在 {counts['exists']} · "
        f"跳过 {counts['skipped']} · 失败 {counts['failed']}（共 {len(planned)} 条）"
    )
    print(summary)
    if new_rows:
        print("将新增的 id：" + "、".join(e.ident for e in new_rows))
    if not getattr(args, "yes", False):
        print("没有 --yes：只算不写，账本一个字节没动")
    elif new_rows:
        data.setdefault("account", []).extend(e.row for e in new_rows)
        pa.save_ledger(ledger_path, data)
        pa.load_ledger(ledger_path, platforms=platforms, strict=True)
        print(f"已写入 {ledger_path}（{len(new_rows)} 条新增，写完立刻 load_ledger 复验通过）")
    else:
        print("没有新增行：账本没动")
    return pa.EXIT_OK if not missing else pa.EXIT_NEEDS_HUMAN


__all__ = [
    "AGENTS",
    "REFUSED_AGENTS",
    "Entry",
    "ident_for",
    "parse_file",
    "plan_entries",
    "cmd_import",
]
