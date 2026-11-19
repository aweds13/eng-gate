"""卡 A371（T-AG656）的钉子 —— 账号导入：认多种工具导出的文件形状，读不懂的点名交出来.

13 条判据（J1~J13）各对应本文件一个 test_；判据原文见
复盘/卡/卡A371-F30账号导入多工具格式-读不懂的点名交出来.md 的「判据」一节。
夹具一律假 token（sk-TESTTOKEN…），账本一律在 tmp_path 里现造：既不碰仓外真账本，也不联网。
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import pool_accounts as pa  # noqa: E402  —— tools/ 已在 sys.path 上
from pool import account_id  # noqa: E402
from pool import accounts_import as ai  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "import"
CLIPROXY = FIX / "cliproxy_single.json"
CODEX_AUTH = FIX / "codex_auth.json"
CLAUDE_CRED = FIX / "claude_credentials.json"
SUB2API = FIX / "sub2api_accounts.json"
BARE = FIX / "bare_tokens.txt"

#: 五份样本里的 token 原串 —— J12 拿它们反过来查账本全文。
TOKENS = (
    "sk-TESTTOKEN0001a2b3c4d5e6f708192a3b4c",
    "sk-TESTTOKEN0002b3c4d5e6f708192a3b4c5d",
    "sk-TESTTOKEN0003c4d5e6f708192a3b4c5d6e",
    "sk-TESTTOKEN0004d5e6f708192a3b4c5d6e7f",
    "sk-TESTTOKEN0005e6f708192a3b4c5d6e7f8a",
    "sk-TESTTOKEN0006f708192a3b4c5d6e7f8a9b",
)

#: 账本底子（与 tests/test_pool_accounts.py 同一份口径：一条 file 型、一条 dir 型）。
LEDGER = """
[[account]]
id = "codearts-1"
label = "备用号 codearts"
platform = "codearts"
state = "active"
added_at = "2026-09-30"
approved_models = ["huaweicloud-maas/deepseek-v4.1-flash"]

[account.credential]
kind = "file"
locator = "~/.codeartsdoer/pool.env"

[account.quota]
unit = "credits"
amount = 12
observed_at = "2026-10-25T09:00:00+08:00"
source = "codearts-credits"

[account.health]
state = "ok"
consecutive_failures = 0

[[account]]
id = "wb-1"
label = "WorkBuddy 主号"
platform = "workbuddy"
state = "active"
added_at = "2026-10-20"
approved_models = []

[account.credential]
kind = "dir"
locator = "~/.workbuddy"

[account.quota]
source = "unknown"

[account.health]
state = "unknown"
"""


def _keep_row(mark: str) -> str:
    """J5 用：账本里已经有一行，凭据指纹与样本里第一条 token 相同。"""
    return f"""
[[account]]
id = "keep-1"
label = "已经在账本里的号"
profile = "keep@example.invalid"
platform = "codearts"
state = "active"
added_at = "2026-01-02"
approved_models = ["keep/x"]

[account.credential]
kind = "file"
locator = "~/.keep/one"
fingerprint = "{mark}"

[account.quota]
source = "unknown"

[account.health]
state = "unknown"
"""


#: J11 用：再加一条 kind="dir" 的行，locator 末段与 wb-1 相同 ⇒ 解析器必须响亮。
DUP_DIR_ROW = """
[[account]]
id = "wb-2"
label = "另一个目录里的同一个号"
platform = "workbuddy"
state = "active"
added_at = "2026-02-02"
approved_models = []

[account.credential]
kind = "dir"
locator = "/opt/copy/.workbuddy"

[account.quota]
source = "unknown"

[account.health]
state = "unknown"
"""

_SUMMARY_RE = re.compile(r"新增 (\d+).*?已存在 (\d+).*?跳过 (\d+).*?失败 (\d+).*?共 (\d+) 条")


@pytest.fixture()
def make_ledger(tmp_path, monkeypatch):
    """造账本 + 把工具根钉到 tmp（platforms.toml 用仓里真的那份）。

    卡 E49：find_ledger() 从仓库根向上找锚点（不跟 cwd 走）⇒ TOOL_ROOT 也钉到 tmp；
    chdir 让测试里写的相对路径落在 tmp 里，不碰宿主机上的真账本。
    """

    def _make(extra: str = "") -> Path:
        p = tmp_path / "infra" / "pool" / "accounts.toml"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(LEDGER + extra, encoding="utf-8")
        return p

    monkeypatch.delenv("TF_ACCOUNTS_TOML", raising=False)
    monkeypatch.delenv(pa.ACCOUNT_DISCOVERY_ENV, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(pa, "TOOL_ROOT", tmp_path)
    monkeypatch.setattr(pa, "_platforms_path", lambda: ROOT / "tools" / "pool" / "platforms.toml")
    monkeypatch.setattr(pa, "_approved_models_from_whitelist", lambda: None)
    return _make


def _argv(ledger, *files, agent="codex", platform="codearts", yes=False, dry_run=False):
    argv = ["import", "--agent", agent, "--platform", platform, "--ledger", str(ledger)]
    if yes:
        argv.append("--yes")
    if dry_run:
        argv.append("--dry-run")
    argv.extend(str(p) for p in files)
    return argv


def _run(capsys, argv):
    code = pa.main(argv)
    cap = capsys.readouterr()
    return code, cap.out, cap.err


def _counts(out: str) -> tuple[int, ...]:
    found = _SUMMARY_RE.search(out)
    assert found, out
    return tuple(int(g) for g in found.groups())


def _rows(path: Path) -> list[dict]:
    return pa.load_ledger(path, platforms=pa.load_platforms(), strict=True)["account"]


def _digest(path: Path) -> tuple[str, int]:
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_size


def _watch(path: Path) -> dict[str, tuple]:
    """J6 用：这三样东西导入前后必须一模一样（导入不探测 ⇒ 一个都不许动）。"""
    out = {}
    for acc in _rows(path):
        quota = acc.get("quota") or {}
        health = acc.get("health") or {}
        out[acc["id"]] = (quota.get("observed_at"), quota.get("samples"), health.get("last_probe"))
    return out


# ---------------------------------------------------------------- J1 入口


def test_cli_import_help(capsys):
    """J1：import --help 退 0 且列出 --agent/文件位置参数/--dry-run/--yes/--ledger。"""
    with pytest.raises(SystemExit) as caught:
        pa.main(["import", "--help"])
    assert caught.value.code == 0
    out = capsys.readouterr().out
    for word in (
        "--agent",
        "codex",
        "claude",
        "antigravity",
        "files",
        "--dry-run",
        "--yes",
        "--ledger",
    ):
        assert word in out, word
    # factory 明确拒绝，并指向 accounts add（magpie 原件 accounts_cli.go:544）
    code = pa.main(["import", "--agent", "factory", "x.json"])
    assert code == pa.EXIT_USAGE
    err = capsys.readouterr().err
    assert "accounts add" in err


# ---------------------------------------------------------------- J2 源文件只读


def test_source_files_untouched(make_ledger, capsys, tmp_path):
    """J2：导入前后每个源文件的 sha256 与 st_size 都不变（含失败路径）。"""
    ledger = make_ledger()
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    samples = [CLIPROXY, CODEX_AUTH, CLAUDE_CRED, SUB2API, BARE, broken]
    before = {p: _digest(p) for p in samples}
    code, out, err = _run(capsys, _argv(ledger, *samples, yes=True))
    after = {p: _digest(p) for p in samples}
    assert before == after
    # 坏的那份进了 skipped，整体要说话（退 1），但源文件一个字节都没动
    assert code == pa.EXIT_NEEDS_HUMAN
    assert _counts(out)[2] == 1
    # 表里那格放不下整句（_COL_MAX=64），原话必须还在别处说一遍
    assert "not valid JSON" in err


# ---------------------------------------------------------------- J3 读不懂的点名


def test_unparsed_entries_are_named(make_ledger, capsys, tmp_path):
    """J3：三好一坏 ⇒ 坏条进 skipped 且 reason 含 not an account，四类计数和 == 4。"""
    ledger = make_ledger()
    good = [
        "sk-TESTTOKEN0011aaaaaaaaaaaaaaaa",
        "sk-TESTTOKEN0012bbbbbbbbbbbbbbbb",
        "sk-TESTTOKEN0013cccccccccccccccc",
    ]
    sample = tmp_path / "three_good_one_bad.json"
    sample.write_text(json.dumps([*good, {"foo": "bar"}]), encoding="utf-8")
    entries, file_err = ai.parse_file("codex", sample.name, sample.read_text(encoding="utf-8"))
    assert file_err == ""
    data = pa.load_ledger(ledger, platforms=pa.load_platforms(), strict=True)
    planned = ai.plan_entries(entries, "codearts", data, {}, pa._now())
    rows = [{"where": e.where, "status": e.status, "reason": e.reason} for e in planned]
    assert len(rows) == 4
    for row in rows:
        assert row["where"] and row["where"] != "?"
        assert row["status"] in ("added", "exists", "skipped", "failed")
    skipped = [r for r in rows if r["status"] == "skipped"]
    assert len(skipped) == 1
    assert "not an account" in skipped[0]["reason"]
    assert [r["status"] for r in rows].count("added") == 3
    assert len([r for r in rows if r["status"] in ("added", "exists", "skipped", "failed")]) == 4
    # 走 CLI 也一样：表里点得出名字，汇总四类加起来就是 4
    code, out, err = _run(capsys, _argv(ledger, sample))
    assert code == pa.EXIT_NEEDS_HUMAN
    assert "not an account" in out
    assert _counts(out) == (3, 0, 1, 0, 4)


# ---------------------------------------------------------------- J4 空与整体认不出


def test_empty_and_unknown_exports_fail_loudly(make_ledger, capsys, tmp_path):
    """J4：空文件 / 全认不出都退非 0 且响亮；多文件里一个空只记一行 skipped。"""
    ledger = make_ledger()
    empty = tmp_path / "empty.txt"
    empty.write_text("", encoding="utf-8")
    code, out, err = _run(capsys, _argv(ledger, empty))
    assert code != 0
    assert "nothing to import" in out + err

    only_comments = tmp_path / "only_comments.txt"
    only_comments.write_text("# 里面什么都没有\n\n", encoding="utf-8")
    code, out, err = _run(capsys, _argv(ledger, only_comments))
    assert code != 0
    assert "no accounts in it" in out + err

    empty_list = tmp_path / "empty_list.json"
    empty_list.write_text("[]", encoding="utf-8")
    code, out, err = _run(capsys, _argv(ledger, empty_list))
    assert code != 0
    assert "no accounts in it" in out + err

    # 多文件里一个空：不中止整次 —— 其余文件照常进 added，空的那份留一行 skipped
    code, out, err = _run(capsys, _argv(ledger, BARE, empty, yes=True))
    assert "one file of several that holds none" in out
    assert _counts(out) == (2, 0, 1, 0, 3)
    assert len(_rows(ledger)) == 4


# ---------------------------------------------------------------- J5 不覆盖已有


def test_existing_account_not_overwritten(make_ledger, capsys):
    """J5：指纹已在账本 ⇒ exists，那一行的字段逐字节不变。"""
    ledger = make_ledger(_keep_row(ai._fingerprint(TOKENS[4])))
    before = {row["id"]: row for row in _rows(ledger)}
    before_n = ledger.read_text(encoding="utf-8").count("[[account]]")
    code, out, err = _run(capsys, _argv(ledger, BARE, yes=True))
    assert code == pa.EXIT_OK
    assert _counts(out) == (1, 1, 0, 0, 2)
    after = {row["id"]: row for row in _rows(ledger)}
    assert before["keep-1"] == after["keep-1"]
    text = ledger.read_text(encoding="utf-8")
    assert text.count("[[account]]") == before_n + 1
    for line in (
        'added_at = "2026-01-02"',
        'approved_models = ["keep/x"]',
        'locator = "~/.keep/one"',
        ai._fingerprint(TOKENS[4]),
    ):
        assert line in text, line


# ---------------------------------------------------------------- J6 不联网不探测


def test_import_makes_no_network_call(make_ledger, capsys, monkeypatch):
    """J6：导入路径不许出现联网/探测符号，三个函数一个都不许被调用。"""
    src = (ROOT / "tools" / "pool" / "accounts_import.py").read_text(encoding="utf-8")
    for word in ("_get_json", "urllib", "socket"):
        assert word not in src, word

    def bomb(*args, **kwargs):
        raise AssertionError("导入不许联网、不许探测")

    for name in ("probe_account", "_get_json", "_token_for"):
        monkeypatch.setattr(pa, name, bomb)
    ledger = make_ledger()
    before = _watch(ledger)
    code, out, err = _run(capsys, _argv(ledger, CLIPROXY, yes=True))
    assert code == pa.EXIT_OK
    after = _watch(ledger)
    for ident, triple in before.items():
        assert after[ident] == triple


# ---------------------------------------------------------------- J7 闸门同构


def test_import_respects_discovery_off(make_ledger, capsys, tmp_path, monkeypatch):
    """J7：闸关了直接拒绝，连账本都不读（--ledger 指不存在路径也报「闸关了」）。"""
    ledger = make_ledger()
    monkeypatch.setenv(pa.ACCOUNT_DISCOVERY_ENV, "1")
    code, out, err = _run(capsys, _argv(ledger, CLIPROXY, yes=True))
    assert code != 0
    assert pa.DISCOVERY_OFF_MESSAGE in err
    assert _rows(ledger)  # 账本没被动过（还能读，且还是原来那两行）

    code2, out2, err2 = _run(capsys, _argv(tmp_path / "nope.toml", CLIPROXY, yes=True))
    assert code2 == code
    assert pa.DISCOVERY_OFF_MESSAGE in err2
    assert "不存在" not in err2


# ---------------------------------------------------------------- J8 写前过注释闸


def test_import_never_clobbers_comments(make_ledger, capsys):
    """J8：有行首注释 ⇒ LedgerError、账本 sha256 不变、行号进 stderr；干净的写成功。"""
    ledger = make_ledger()
    ledger.write_text("# touched\n" + ledger.read_text(encoding="utf-8"), encoding="utf-8")
    before = hashlib.sha256(ledger.read_bytes()).hexdigest()
    with pytest.raises(pa.LedgerError):
        pa.save_ledger(ledger, pa.load_ledger(ledger, platforms=pa.load_platforms()))
    assert hashlib.sha256(ledger.read_bytes()).hexdigest() == before

    code, out, err = _run(capsys, _argv(ledger, CLIPROXY, yes=True))
    assert code != 0
    assert "行 1" in err
    # 行号要人一眼看见：撞上闸时不许甩一段 traceback 把行号埋在最后一行。
    assert "Traceback" not in err
    assert hashlib.sha256(ledger.read_bytes()).hexdigest() == before

    # 写路径只走既有闸：模块里没有自己开文件写账本
    src = (ROOT / "tools" / "pool" / "accounts_import.py").read_text(encoding="utf-8")
    assert "save_ledger(" in src
    assert "write_text" not in src
    assert "os.replace" not in src

    clean = make_ledger()
    code2, out2, err2 = _run(capsys, _argv(clean, CLIPROXY, yes=True))
    assert code2 == pa.EXIT_OK
    assert hashlib.sha256(clean.read_bytes()).hexdigest() != before


# ---------------------------------------------------------------- J9 默认只算不写


def test_dry_run_is_default(make_ledger, capsys):
    """J9：不带 --yes 只打印计划，账本 mtime 与 sha256 都不变；--yes 才写。"""
    ledger = make_ledger()
    before = (ledger.stat().st_mtime_ns, hashlib.sha256(ledger.read_bytes()).hexdigest())
    code, out, err = _run(capsys, _argv(ledger, BARE))
    assert code == pa.EXIT_OK
    assert "将新增的 id：" in out
    assert "一个字节没动" in out
    assert _counts(out) == (2, 0, 0, 0, 2)
    assert (ledger.stat().st_mtime_ns, hashlib.sha256(ledger.read_bytes()).hexdigest()) == before

    code2, out2, err2 = _run(capsys, _argv(ledger, BARE, dry_run=True))
    assert code2 == pa.EXIT_OK
    assert (ledger.stat().st_mtime_ns, hashlib.sha256(ledger.read_bytes()).hexdigest()) == before

    code3, out3, err3 = _run(capsys, _argv(ledger, BARE, yes=True))
    assert code3 == pa.EXIT_OK
    assert hashlib.sha256(ledger.read_bytes()).hexdigest() != before[1]
    assert len(_rows(ledger)) == 4


# ---------------------------------------------------------------- J10 写完能过校验


def test_imported_rows_pass_check_account(make_ledger, capsys):
    """J10：导入完立刻 load_ledger(strict=True) 不抛；每行字段都在合法取值里。"""
    ledger = make_ledger()
    code, out, err = _run(capsys, _argv(ledger, CLIPROXY, CODEX_AUTH, BARE, yes=True))
    assert code == pa.EXIT_OK
    platforms = pa.load_platforms()
    data = pa.load_ledger(ledger, platforms=platforms, strict=True)  # 抛了就是红
    ids = [acc["id"] for acc in data["account"]]
    assert len(ids) == len(set(ids))
    new = [acc for acc in data["account"] if acc["id"] not in ("codearts-1", "wb-1")]
    assert len(new) == 4
    for acc in new:
        assert acc["platform"] in platforms
        assert acc["state"] in pa.STATES
        assert isinstance(acc["approved_models"], list)
        assert acc["credential"]["kind"] in pa.CRED_KINDS
        quota = acc["quota"]
        assert quota.get("source") == "unknown"
        assert "amount" not in quota


# ---------------------------------------------------------------- J11 id 能被解析


def test_imported_ids_resolve(make_ledger, capsys):
    """J11：每条新行的 profile 与 id 都指回自己；file 型末段不猜；同末段两行要响亮。"""
    ledger = make_ledger()
    code, out, err = _run(capsys, _argv(ledger, BARE, yes=True))
    assert code == pa.EXIT_OK
    rows = _rows(ledger)
    new = [row for row in rows if row["id"] not in ("codearts-1", "wb-1")]
    assert len(new) == 2
    for row in new:
        assert account_id.resolve_account_id(row["profile"], rows) == (row["id"], "")
        assert account_id.resolve_account_id(row["id"], rows) == (row["id"], "")
        tail = Path(row["credential"]["locator"]).name
        assert account_id.resolve_account_id(tail, rows) == (tail, account_id.NO_STABLE_ID)

    # dir 型一例：末段认得出，且明说凭的是哪条规矩
    got, note = account_id.resolve_account_id(".workbuddy", rows)
    assert got == "wb-1"
    assert "credential.locator 末段" in note

    # 同一个末段两行 ⇒ 指名要人判断，不许取第一条
    dup_rows = _rows(make_ledger(DUP_DIR_ROW))
    with pytest.raises(account_id.AccountMapError):
        account_id.resolve_account_id(".workbuddy", dup_rows)


# ---------------------------------------------------------------- J12 不许落明文


def test_no_secret_in_ledger(make_ledger, capsys):
    """J12：账本全文不出现 SECRET_RE 命中，也不出现样本 token 原串或其 8 字子串。"""
    ledger = make_ledger()
    code, out, err = _run(
        capsys, _argv(ledger, CLIPROXY, CODEX_AUTH, CLAUDE_CRED, SUB2API, BARE, yes=True)
    )
    assert code == pa.EXIT_NEEDS_HUMAN  # 只有 claude 那份（agent=codex）不认
    text = ledger.read_text(encoding="utf-8")
    assert pa.SECRET_RE.findall(text) == []
    rows = _rows(ledger)
    for token in TOKENS:
        assert token not in text
        windows = {token[i : i + 8] for i in range(len(token) - 7)}
        for row in rows:
            locator = row["credential"]["locator"]
            assert not [w for w in windows if w in locator], row["id"]
    # 存的是指纹不是明文
    assert 'fingerprint = "sha256:' in text


# ---------------------------------------------------------------- J13 单条不拖累


def test_one_bad_entry_does_not_abort(make_ledger, capsys, tmp_path):
    """J13：三好一坏 ⇒ 3 added / 1 skipped / 退 1 / stderr 头一行「N 条未导入」。"""
    ledger = make_ledger()
    good = [
        "sk-TESTTOKEN0021aaaaaaaaaaaaaaaa",
        "sk-TESTTOKEN0022bbbbbbbbbbbbbbbb",
        "sk-TESTTOKEN0023cccccccccccccccc",
    ]
    sample = tmp_path / "three_good_one_bad.json"
    sample.write_text(json.dumps([*good, {"foo": "bar"}]), encoding="utf-8")
    code, out, err = _run(capsys, _argv(ledger, sample, yes=True))
    assert code == pa.EXIT_NEEDS_HUMAN
    assert err.splitlines()[0] == "1 条未导入"
    assert _counts(out) == (3, 0, 1, 0, 4)
    assert len([r for r in _rows(ledger) if r["id"].startswith("codex-")]) == 3

    # 同一批里同一个 token 出现两次：第二条 failed，第一条不被牵连
    # （账本重置回底子，否则第一条会被判 exists —— 那是 J5 的事，不是 J13 的）
    fresh = make_ledger()
    dup = tmp_path / "twice.txt"
    dup.write_text(good[0] + "\n" + good[0] + "\n", encoding="utf-8")
    code2, out2, err2 = _run(capsys, _argv(fresh, dup))
    assert code2 == pa.EXIT_NEEDS_HUMAN
    assert "in the files twice" in out2
    assert _counts(out2) == (1, 0, 0, 1, 2)
