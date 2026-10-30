r"""账号账本与只读探测（卡 E45 · T-AG496）的判据钉子。

为什么值当测：账本一旦写坏，没有 git 能把它 checkout 回来（它在仓外）；
`discover` 与「凭据泄漏」只隔一层 `stat` vs `open`；`probe` 的四种坏响应
（429 / 5xx / 401 / 形状变了）最容易被写成「假装成功」或「假装 0」。

| 钉子 | 判什么 | 会红在哪 |
|---|---|---|
| ① 账本定位三档 | 显式 > 环境变量 > 向上走 | 少一档就会「换个目录就找不到」 |
| ② 定位失败退 2 | 找不到要说明三种修法 | 若静默造一个空账本 |
| ③ 字段校验点名 | 平台不在表 / 缺 approved_models / id 重复 | 若只报「格式错」 |
| ④ 墓碑 | 默认不列，`--all` 列 | 若删除后又被列进待派 |
| ⑤ 凭据打码 | 输出的 locator 不许带 token 形状 | 若原样回显 |
| ⑥ 能力表不含凭据 | `platforms.toml` 的值里没 token 形状 | 若有人把 cookie 粘进去 |
| ⑦ discover 只 stat | 把 `open` 换成抛异常的桩仍要能跑 | 若偷读文件 |
| ⑧ discover 标「未声明」 | 不在账本里的位点要被点名 | 若默默忽略 |
| ⑨ offline 确定 | 不发请求、结论稳定 | 若 offline 还去连 |
| ⑩ 缺凭据 ⇒ uncertain | 说明要设哪个环境变量 | 若判成 failed 或 0 |
| ⑪ 坏响应的四个结论码 | 429/5xx⇒uncertain、401⇒failed、404⇒not-supported | 若一律 ok/failed |
| ⑫ 额度不写死 | 桩返回 7 和 999 就分别得 7 和 999 | 若把读到的数写成常量 |
| ⑬ 停用号跳过 | `state=disabled` ⇒ skipped | 若照探 |
| ⑭ 未知平台 | 结论码 unknown-platform | 若 KeyError |
| ⑮ 本卡不写 | 源码里没有领取端点、没有带 data= 的请求 | 若把 E48 的动作偷跑进 E45 |
| ⑯ samples 上限与原子写 | 25 条只留 20、无 .tmp 残留、还可读回 | 若截断成「全丢」或留半个文件 |
| ⑰ 只读命令不联网 | list/show/discover 期间 urlopen 抛异常也不受影响 | 若「查个列表也去 ping」 |
| ⑱ 账本在仓外 | 真账本路径不在工具根下 | 若把凭据位点写进仓里 |

★ 导入口径照既有测试：把 `tools/` 挂上 `sys.path` 再 `import`。
"""

from __future__ import annotations

import builtins
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import pool_accounts as pa  # noqa: E402 —— tools/ 已在 sys.path 上

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
approved_models = ["hunyuan/x"]

[account.credential]
kind = "dir"
locator = "~/.workbuddy"

[account.quota]
unit = "点"

[account.health]
state = "unknown"
"""

TOMBSTONE = """
[[account]]
id = "old-1"
label = "已删的号"
platform = "minimax"
state = "disabled"
added_at = "2026-08-01"
deleted_at = "2026-09-01"
approved_models = ["abab/x"]

[account.credential]
kind = "file"
locator = "~/minimax/token"
"""


@pytest.fixture()
def ledger(tmp_path, monkeypatch):
    p = tmp_path / "infra" / "pool" / "accounts.toml"
    p.parent.mkdir(parents=True)
    p.write_text(LEDGER, encoding="utf-8")
    monkeypatch.delenv("TF_ACCOUNTS_TOML", raising=False)
    # ★ 卡 E49：`find_ledger()` 从**cwd** 逐级向上找 `infra/pool/accounts.toml`。
    # 不 chdir 的话它会走到真仓的祖父目录，于是在开发机上"恰好"找到
    # D:/repo/infra/pool/ —— 换个机器（云门禁机 C:/eng）就找不到
    # ⇒ 这批钉子其实钉的是「本机有这份账本」。chdir 到 tmp（里面已有
    # tmp/infra/pool/accounts.toml）后，"向上找"这件事本身仍被钉住，但不再依赖宿主机。
    monkeypatch.chdir(tmp_path)
    # ★ 卡 E49：判据从**仓库根**向上找锚点（不跟 cwd 走）⇒ 夹具把仓库根也钉到 tmp，
    #   这样钉子不再依赖宿主机上「恰好」存在的 infra/pool。
    monkeypatch.setattr(pa, "TOOL_ROOT", tmp_path)
    return p


@pytest.fixture()
def patched(ledger, monkeypatch):
    """把工具根指到 tmp（platforms.toml 用真的仓里那份）。"""
    real = ROOT / "tools" / "pool" / "platforms.toml"
    monkeypatch.setattr(pa, "_platforms_path", lambda: real)
    # 白名单判据单独用 test_model_outside_whitelist_rejected 钉；其余用例不依赖本机 approved 表
    monkeypatch.setattr(pa, "_approved_models_from_whitelist", lambda: None)
    return ledger


# ---------------------------------------------------------------- ① ~ ② 定位


def test_find_ledger_prefers_explicit(ledger):
    assert pa.find_ledger(str(ledger)) == ledger.resolve()


def test_find_ledger_walks_up_from_repo_root(ledger, monkeypatch):
    """锚点从**仓库根**向上找，与 cwd 无关（卡 E49）。

    坏掉的写法（改回 `Path.cwd()` 起点）：在 chdir 到别处之后仍会命中
    宿主机上任何一层的 infra/pool/accounts.toml —— 云机上 `C:/infra/pool` 就是这种层。
    """
    sub = ledger.parent.parent.parent / "deep" / "sub"
    sub.mkdir(parents=True)
    monkeypatch.chdir(sub)
    assert pa.find_ledger() == ledger.resolve()
    assert pa.find_ledger() == ledger.resolve()  # 再调一次：cwd 变了结果不变


def test_find_ledger_env(ledger, monkeypatch):
    monkeypatch.setenv("TF_ACCOUNTS_TOML", str(ledger))
    monkeypatch.chdir(Path("/"))
    assert pa.find_ledger() == ledger.resolve()


def test_find_ledger_missing_explains(monkeypatch, tmp_path):
    monkeypatch.delenv("TF_ACCOUNTS_TOML", raising=False)
    monkeypatch.setattr(pa, "TOOL_ROOT", tmp_path)  # 判据只看仓库根，不看 cwd
    monkeypatch.chdir(tmp_path)
    with pytest.raises(pa.LedgerError) as ei:
        pa.find_ledger()
    assert "TF_ACCOUNTS_TOML" in str(ei.value)


def test_main_exit_2_when_ledger_missing(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("TF_ACCOUNTS_TOML", raising=False)
    monkeypatch.setattr(pa, "TOOL_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path)
    assert pa.main(["list"]) == pa.EXIT_USAGE
    assert "账号账本" in capsys.readouterr().err


# ---------------------------------------------------------------- ③ 校验


def _write(tmp_path, text) -> Path:
    p = tmp_path / "accounts.toml"
    p.write_text(text, encoding="utf-8")
    return p


def test_unknown_platform_names_account_and_known(patched, tmp_path):
    p = _write(tmp_path, LEDGER.replace('platform = "workbuddy"', 'platform = "nope"'))
    with pytest.raises(pa.LedgerError) as ei:
        pa.load_ledger(p)
    msg = str(ei.value)
    assert "wb-1" in msg and "codearts" in msg


def test_missing_approved_models_rejected(patched, tmp_path):
    p = _write(tmp_path, LEDGER.replace('approved_models = ["hunyuan/x"]', "note = 'no models'"))
    with pytest.raises(pa.LedgerError) as ei:
        pa.load_ledger(p)
    assert "approved_models" in str(ei.value)


def test_empty_approved_models_means_no_dispatch(patched, tmp_path):
    """空数组是合法值 = 「这个号不许派活」；缺字段才拒。"""
    p = _write(tmp_path, LEDGER.replace('approved_models = ["hunyuan/x"]', "approved_models = []"))
    data = pa.load_ledger(p)
    assert data["account"][1]["approved_models"] == []


def test_model_outside_whitelist_rejected(patched, tmp_path, monkeypatch):
    monkeypatch.setattr(pa, "_approved_models_from_whitelist", lambda: {"huaweicloud-maas/GLM-5.2"})
    p = _write(tmp_path, LEDGER)
    with pytest.raises(pa.LedgerError) as ei:
        pa.load_ledger(p)
    assert "未批准" in str(ei.value)


def test_duplicate_id_rejected(patched, tmp_path):
    p = _write(tmp_path, LEDGER + LEDGER.split("[[account]]")[1].join(["[[account]]", ""]))
    text = LEDGER + "\n" + LEDGER.strip() + "\n"
    p.write_text(text, encoding="utf-8")
    with pytest.raises(pa.LedgerError) as ei:
        pa.load_ledger(p)
    assert "重复" in str(ei.value)


def test_bad_state_rejected(patched, tmp_path):
    p = _write(tmp_path, LEDGER.replace('state = "active"', 'state = "alive"', 1))
    with pytest.raises(pa.LedgerError) as ei:
        pa.load_ledger(p)
    assert "state" in str(ei.value)


# ---------------------------------------------------------------- ④ ~ ⑥ 展示


def test_tombstone_hidden_by_default(patched):
    data = pa.load_ledger(patched)
    data["account"].append(
        {
            "id": "old-1",
            "label": "已删",
            "platform": "minimax",
            "state": "disabled",
            "added_at": "2026-08-01",
            "deleted_at": "2026-09-01",
            "approved_models": ["abab/x"],
            "credential": {"kind": "file", "locator": "~/minimax/token"},
        }
    )
    ids = [row["id"] for row in pa.list_rows(data, None, False)]
    assert "old-1" not in ids
    ids_all = [row["id"] for row in pa.list_rows(data, None, True)]
    assert "old-1" in ids_all


def test_list_redacts_token_like_locator(patched, capsys):
    data = pa.load_ledger(patched)
    data["account"][0]["credential"]["locator"] = "Bearer sk-abcdefgh12345678"
    rows = pa.list_rows(data, None, False)
    assert "sk-abcdefgh" not in json.dumps(rows, ensure_ascii=False)


def test_platform_table_holds_no_credentials():
    with open(ROOT / "tools" / "pool" / "platforms.toml", encoding="utf-8") as fh:
        text = fh.read()
    assert "Bearer " not in text
    assert not pa.SECRET_RE.search(text.replace("sha256", ""))


# ---------------------------------------------------------------- ⑦ ~ ⑧ discover


def test_discover_only_stats(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    opened: list[str] = []
    real_open = builtins.open

    def spy(file, *a, **kw):
        opened.append(str(file))
        return real_open(file, *a, **kw)

    monkeypatch.setattr(builtins, "open", spy)
    rows = pa.discover(["~/.codeartsdoer"], extra_dirs=["~/elsewhere"])
    pointers = [r["pointer"] for r in rows]
    assert pointers[0] == "~/.codeartsdoer"  # 账本 locator 在最前
    assert "~/elsewhere" in pointers
    assert opened == []


def test_discover_marks_undeclared(tmp_path, monkeypatch):
    """账本里没声明的位点一律「未声明」；只有 locator 才配「已登记」。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / ".declared").mkdir()
    rows = pa.discover(["~/.declared"], extra_dirs=["~/elsewhere"])
    by_pointer = {r["pointer"]: r for r in rows}
    assert by_pointer["~/elsewhere"]["status"] == "未声明"
    assert by_pointer["~/elsewhere"]["exists"] is True
    assert by_pointer["~/.declared"]["status"] == "已登记"
    assert by_pointer["~/.declared"]["entries"] == 0


def test_discover_dedupes_and_covers_candidates(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    rows = pa.discover(["~/.workbuddy"], extra_dirs=["~/.workbuddy", "~/.nope"])
    pointers = [r["pointer"] for r in rows]
    assert pointers.count("~/.workbuddy") == 1
    assert "~/.nope" in pointers


# ---------------------------------------------------------------- ⑨ ~ ⑭ 探测


def _acc(platform="workbuddy", state="active"):
    return {
        "id": f"{platform}-1",
        "label": "x",
        "platform": platform,
        "state": state,
        "added_at": "2026-10-20",
        "approved_models": ["m"],
        "credential": {"kind": "file", "locator": "~/.x"},
    }


def test_offline_sends_nothing(monkeypatch):
    plat = {
        "probe": "http",
        "probe_url": "https://example.invalid",
        "base_urls": ["https://example.invalid"],
        "token_env": "TF_DEMO_TOKEN",
    }
    monkeypatch.setenv("TF_DEMO_TOKEN", "t")

    def boom(url, token):
        raise AssertionError("offline 不许发请求")

    out = pa.probe_account(_acc(), plat, fetch=boom, offline=True)
    assert out["kind"] == "skipped"


def test_missing_token_is_uncertain_with_env_name(monkeypatch):
    monkeypatch.delenv("TF_DEMO_TOKEN", raising=False)
    plat = {
        "probe": "http",
        "probe_url": "https://example.invalid",
        "base_urls": ["https://example.invalid"],
        "token_env": "TF_DEMO_TOKEN",
    }
    out = pa.probe_account(_acc(), plat, fetch=lambda u, t: (200, {"total": 1}, ""))
    assert out["kind"] == "uncertain"
    assert "TF_DEMO_TOKEN" in out["detail"]


@pytest.mark.parametrize(
    ("status", "body", "expect"),
    [
        (429, None, "uncertain"),
        (500, None, "uncertain"),
        (0, None, "uncertain"),
        (401, None, "failed"),
        (403, None, "failed"),
        (404, None, "not-supported"),
        (200, {"nope": "shape changed"}, "uncertain"),
    ],
)
def test_bad_responses_map_to_expected_codes(monkeypatch, status, body, expect):
    monkeypatch.setenv("TF_DEMO_TOKEN", "t")
    plat = {
        "probe": "http",
        "probe_url": "https://example.invalid",
        "base_urls": ["https://example.invalid"],
        "token_env": "TF_DEMO_TOKEN",
    }
    out = pa.probe_account(_acc(), plat, fetch=lambda u, t: (status, body, f"HTTP {status}"))
    assert out["kind"] == expect


def test_amount_comes_from_response_not_constant(monkeypatch):
    monkeypatch.setenv("TF_DEMO_TOKEN", "t")
    plat = {
        "probe": "http",
        "probe_url": "https://example.invalid",
        "base_urls": ["https://example.invalid"],
        "token_env": "TF_DEMO_TOKEN",
        "unit": "credits",
    }
    seven = pa.probe_account(_acc(), plat, fetch=lambda u, t: (200, {"data": {"credits": 7}}, ""))
    nine = pa.probe_account(_acc(), plat, fetch=lambda u, t: (200, {"data": {"credits": 999}}, ""))
    assert seven["amount"] == 7.0 and nine["amount"] == 999.0


def test_disabled_account_is_skipped():
    out = pa.probe_account(
        _acc(state="disabled"), {"probe": "http"}, fetch=lambda u, t: (200, {}, "")
    )
    assert out["kind"] == "skipped"


def test_unknown_platform_code():
    out = pa.probe_all({"account": [_acc("ghost")]}, {})
    assert out[0]["kind"] == "unknown-platform"


def test_codearts_probe_is_honest_uncertain():
    platforms = pa.load_platforms()
    out = pa.probe_account(
        _acc("codearts"), platforms["codearts"], fetch=lambda u, t: (200, {"total": 1}, "")
    )
    assert out["kind"] == "uncertain"
    assert "签名" in out["detail"]


# ---------------------------------------------------------------- ⑮ 本卡不写


def test_module_contains_no_write_endpoints():
    """E45 的「本模块只读」判据。

    ★ E48 改判据：原来拿 `/checkin` 当写动作的标记，但 E48 给本模块加了 `checkin`
    子命令（写动作在 `tools/pool/checkin.py`），那个字符串会命中**模块路径**而不是端点。
    改成点名真端点数 —— 判据的意思没变松：本模块里一条写端点、一个 POST 都不许有。
    """
    src = (ROOT / "tools" / "pool_accounts.py").read_text(encoding="utf-8")
    for needle in (
        "/v1/ops/claim",
        "/daily-checkin",
        "checkin_credits/claim",
        "/signin/claim",
        'method="POST"',
        "method='POST'",
    ):
        assert needle not in src, f"E45 不许出现写动作：{needle}"


# ---------------------------------------------------------------- ⑯ 保存


def test_save_caps_samples_and_is_atomic(patched, tmp_path):
    data = pa.load_ledger(patched)
    data["account"][0]["quota"]["samples"] = [
        {"observed_at": f"2026-10-{d:02d}", "amount": d} for d in range(1, 26)
    ]
    target = tmp_path / "out" / "accounts.toml"
    pa.save_ledger(target, data)
    assert not list(target.parent.glob("*.tmp"))
    reload = pa.load_ledger(target)
    assert len(reload["account"][0]["quota"]["samples"]) == pa.SAMPLES_CAP
    assert reload["account"][0]["quota"]["samples"][-1]["amount"] == 25


# ---------------------------------------------------------------- ⑰ ~ ⑱ 只读


def test_readonly_commands_never_hit_network(patched, monkeypatch, capsys):
    def boom(*a, **kw):
        raise AssertionError("只读命令不许联网")

    monkeypatch.setattr(pa.urllib.request, "urlopen", boom)
    monkeypatch.chdir(patched.parent.parent.parent)
    assert pa.main(["list"]) == pa.EXIT_OK
    assert pa.main(["show", "codearts-1"]) == pa.EXIT_OK
    assert pa.main(["discover"]) == pa.EXIT_OK
    capsys.readouterr()


def test_ledger_lives_outside_tool_root():
    """真账本必须落在工具根之外（否则凭据位点会进 git）。"""
    try:
        path = pa.find_ledger()
    except pa.LedgerError:
        pytest.skip("本机没有真账本，跳过")
    assert ROOT.resolve() not in path.parents


def test_unknown_source_must_not_carry_amount(patched, tmp_path):
    """没探测过就填数 = 编数据；TOML 没有 null，要表达未观测就省掉 amount。"""
    bad = LEDGER.replace('unit = "点"', 'unit = "点"\namount = 0\nsource = "unknown"', 1)
    p = _write(tmp_path, bad)
    with pytest.raises(pa.LedgerError) as ei:
        pa.load_ledger(p)
    assert "amount" in str(ei.value)


# ---------------------------------------------------------------- ⑲ ~ ㉓ 补 §5 未覆盖的四条


def test_list_json_is_sorted_and_shaped(patched, capsys):
    """① `list --json` 稳定排序（platform, id）且字段集与 schema 一致。"""
    assert pa.main(["list", "--json"]) == pa.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    rows = payload["accounts"]
    keys = [(r["platform"], r["id"]) for r in rows]
    assert keys == sorted(keys), keys
    assert set(rows[0]) >= {
        "id",
        "platform",
        "platform_known",
        "label",
        "state",
        "quota",
        "models",
        "credential",
    }


def test_platform_sources_are_traceable():
    """③ `source` 必须可追溯：`github:<owner>/<repo>/<path>:<lines>` 或 `local:<path>:<line>`。"""
    platforms = pa.load_platforms()
    assert platforms
    for pid, plat in platforms.items():
        src = plat.get("source") or ""
        assert src, f"{pid} 没写 source"
        assert re.match(r"^(github:[\w.-]+/[\w.-]+/\S+:\S+|local:\S+:\d+)$", src), (pid, src)


def test_platform_local_archive_matches_source_when_present():
    """`local_archive` 是本机存档（gates/diag 是 gitignored）：在树里就要非空，不在就别写。"""
    repo = ROOT / "gates" / "diag" / "repos"
    for pid, plat in pa.load_platforms().items():
        archive = plat.get("local_archive")
        if not archive:
            continue
        assert archive.startswith("gates/diag/repos/"), (pid, archive)
        path = ROOT / archive
        if not repo.is_dir():
            continue  # 卡树里没有这份存档（gitignored），不假红
        assert path.is_file(), (pid, archive)
        assert path.stat().st_size > 0


def test_unknown_platform_still_listed_but_not_dispatchable(
    patched, tmp_path, capsys, monkeypatch
):
    """⑪ 反向：能力表里删掉 codearts ⇒ list 仍列出并示警；probe/派活仍拒绝（strict）。"""
    src = (ROOT / "tools" / "pool" / "platforms.toml").read_text(encoding="utf-8")
    head, rest = src.split("[platform.codearts]", 1)
    tail = rest.split("[platform.", 1)[1]
    alt = tmp_path / "platforms.toml"
    alt.write_text(head + "[platform." + tail, encoding="utf-8")
    monkeypatch.setattr(pa, "_platforms_path", lambda: alt)

    assert pa.main(["list"]) == pa.EXIT_OK
    assert "能力表里没有" in capsys.readouterr().out
    data = pa.load_ledger(patched, strict=False)
    assert data["unknown_platforms"] == ["codearts-1"]
    with pytest.raises(pa.LedgerError) as ei:
        pa.load_ledger(patched, strict=True)
    assert "不在 tools/pool/platforms.toml 里" in str(ei.value)


def test_record_probe_result_only_touches_observed_at_and_samples(patched, tmp_path):
    """⑲ `record_probe_result` 只写 `[account.quota]` 的 `observed_at` 与 `samples`。

    ★ 卡 A333 判据 6：`state` 是人工判定的（`STATES` 五行），`approved_models` 是派活
    白名单 —— 探测一次读数**都不许**碰它们。六结论码原样进 `samples`，一条都不许压平。
    """
    before = pa.load_ledger(patched)
    raw_before = patched.read_bytes()
    stamp_now = datetime(2026, 10, 26, 12, 0, 0, tzinfo=pa.TZ)
    # ★ `record_probe_result` 原地改传进去的 `data`（跟 `_record_checkin` 一样），
    #   所以旧值必须在调用**之前**快照下来，否则拿到的就是被改过的自己。
    old = {
        acc["id"]: {
            "observed_at": acc.get("quota", {}).get("observed_at"),
            "state": acc.get("state"),
            "approved_models": acc.get("approved_models"),
            "amount": acc.get("quota", {}).get("amount"),
        }
        for acc in before["account"]
    }

    rows = [
        {"id": "codearts-1", "platform": "codearts", "kind": "ok", "amount": 99},
        {"id": "wb-1", "platform": "workbuddy", "kind": "uncertain", "detail": "HTTP 429"},
    ]
    pa.record_probe_result(patched, before, rows, now=stamp_now)

    after = pa.load_ledger(patched)
    by_id = {acc["id"]: acc for acc in after["account"]}

    # ① observed_at 变了
    assert by_id["codearts-1"]["quota"]["observed_at"] == "2026-10-26T12:00:00+08:00"
    assert by_id["codearts-1"]["quota"]["observed_at"] != old["codearts-1"]["observed_at"]
    assert by_id["wb-1"]["quota"]["observed_at"] == "2026-10-26T12:00:00+08:00"

    # ② samples 各多一条，形状只有 at/kind（没有 reset_at，也不许塞 amount）
    for aid, kind in (("codearts-1", "ok"), ("wb-1", "uncertain")):
        samples = by_id[aid]["quota"]["samples"]
        assert len(samples) == 1, f"{aid} 的 samples 应该只多一条，实际 {samples}"
        assert samples[-1] == {"at": "2026-10-26T12:00:00+08:00", "kind": kind}

    # ③ state / approved_models / amount 一个都不许被探测结果改写
    for aid in ("codearts-1", "wb-1"):
        assert by_id[aid]["state"] == old[aid]["state"]
        assert by_id[aid].get("approved_models") == old[aid]["approved_models"]
    assert by_id["codearts-1"]["quota"]["amount"] == old["codearts-1"]["amount"] == 12

    # ④ 账本确实落盘了（不是只改内存）
    assert patched.read_bytes() != raw_before


def test_record_probe_result_refuses_unknown_source_with_amount(patched, tmp_path):
    """⑳ `source=unknown` 却带 `amount` ⇒ `LedgerError`，账本**一个字节都不变**。

    ★ 卡 A333 判据 7：照 `_check_account():166-170` 的口径 —— 没探测过就不许填数。
    """
    before = pa.load_ledger(patched)
    raw_before = patched.read_bytes()
    stamp_now = datetime(2026, 10, 26, 12, 0, 0, tzinfo=pa.TZ)

    rows = [
        {
            "id": "codearts-1",
            "platform": "codearts",
            "kind": "ok",
            "amount": 0,
            "source": "unknown",
        }
    ]
    with pytest.raises(pa.LedgerError) as ei:
        pa.record_probe_result(patched, before, rows, now=stamp_now)
    assert "amount" in str(ei.value)

    assert patched.read_bytes() == raw_before, "拒写时账本不许有半个字节的改动"


def test_mcp_account_status_is_offline(patched, monkeypatch):
    """⑩ MCP 面也只读账本：把网络层打成会炸，工具照样回读数。"""
    import pool_mcp

    def boom(*a, **kw):
        raise AssertionError("account_status 不许联网")

    monkeypatch.setattr(pa.urllib.request, "urlopen", boom)
    monkeypatch.setattr(pa, "find_ledger", lambda explicit=None: patched)
    text, data, is_error = pool_mcp.tool_account_status({})
    assert is_error is False
    assert data["found"] is True
    assert data["accounts"]
    assert "账号账本" in text

