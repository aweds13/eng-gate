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


#: 2026-11-09 真机 `statistics/plugin` 的响应形状（裸对象，六个 metric 里只有 total 有用）。
REAL_CODEARTS_PACKAGE = {
    "start_date": "2026-11-01",
    "end_date": "2026-11-30",
    "is_teadmin": False,
    "is_white_list": True,
    "show": True,
    "package": {"is_credit_package": True, "is_token_package": False, "status": "VALID"},
    "metrics": [
        {"name": "usageDataChatMessages", "package_credit_amount": None,
         "package_credit_used": None, "package_credit_remain": None},
        {"name": "usageTokenChatMessages", "package_credit_amount": None,
         "package_credit_used": None, "package_credit_remain": None},
        {"name": "usageTotalPackageCredit", "package_credit_amount": 9000.0,
         "package_credit_used": 4185.59, "package_credit_remain": 4814.41},
        {"name": "usageBasicPackageCredit", "package_credit_amount": 0,
         "package_credit_used": 0, "package_credit_remain": 0},
        {"name": "usageOnDemandPackageCredit", "package_credit_amount": 0,
         "package_credit_used": 0, "package_credit_remain": 0},
        {"name": "usageBonusPackageCredit", "package_credit_amount": 9000.0,
         "package_credit_used": 4185.59, "package_credit_remain": 4814.41},
    ],
}


def _codearts_env(monkeypatch):
    """把 AK/SK 放进 `token_env` 里点名的那两个变量（真跑时由 `~/.codeartsdoer/pool.env` 提供）。"""
    monkeypatch.setenv("CODEARTS_CLI_AK", "AKIDEXAMPLE")
    monkeypatch.setenv("CODEARTS_CLI_SK", "secret-key")
    monkeypatch.delenv("CODEARTS_CLI_SECRET", raising=False)
    monkeypatch.delenv("TF_CODEARTS_AK", raising=False)
    monkeypatch.delenv("TF_CODEARTS_SK", raising=False)


def test_codearts_probe_reads_real_shape_as_ok(monkeypatch):
    """卡 E97 ② 改判据：合成 fetcher 回**真形状** ⇒ `ok` + `used_percent≈46.51`。

    ★ 原来这条叫 `test_codearts_probe_is_honest_uncertain`，钉的是「`probe=unsupported`
      时永远 uncertain」。E97 把 codearts 接成真读数以后，那个断言会把**接好了**判成红。
      但它的意图不许丢：**没料时必须说不知道** —— 同一个测试的后半段（缺凭据 ⇒
      `uncertain` 且点名 `token_env`）继续钉这一条。
    """
    _codearts_env(monkeypatch)
    platforms = pa.load_platforms()
    seen: list[dict] = []

    def fetcher(method, url, headers, body):
        seen.append({"method": method, "url": url, "headers": dict(headers or {})})
        return 200, json.dumps(REAL_CODEARTS_PACKAGE)

    out = pa.probe_account(_acc("codearts"), platforms["codearts"], fetch=fetcher)
    assert out["kind"] == "ok", out
    assert out["used_percent"] == 46.51
    # amount 是**余额**口径（remain），不是套餐总额 9000
    assert out["amount"] == 4814.41
    assert out["unit"] == "credits"
    # 只读：一次 GET、带签名头、不带 body
    assert [c["method"] for c in seen] == ["GET"]
    assert seen[0]["url"].endswith("/snap-manager/v1/statistics/plugin")
    assert "Authorization" in seen[0]["headers"]
    # 签名材料不许出现在 detail 里（AK/SK 一个字都不许回显）
    assert "AKIDEXAMPLE" not in json.dumps(out, ensure_ascii=False)
    assert "secret-key" not in json.dumps(out, ensure_ascii=False)


def test_codearts_probe_without_credentials_is_uncertain(monkeypatch):
    """没凭据 ⇒ `uncertain` 且点名 `token_env`（「没料必须说不知道」的原始意图）。"""
    for name in ("CODEARTS_CLI_AK", "CODEARTS_CLI_SK", "TF_CODEARTS_AK", "TF_CODEARTS_SK"):
        monkeypatch.delenv(name, raising=False)
    platforms = pa.load_platforms()

    def boom(method, url, headers, body):
        raise AssertionError("没凭据不许发请求")

    out = pa.probe_account(_acc("codearts"), platforms["codearts"], fetch=boom)
    assert out["kind"] == "uncertain"
    assert "CODEARTS_CLI_AK" in out["detail"] and "CODEARTS_CLI_SK" in out["detail"]


@pytest.mark.parametrize(
    ("status", "text", "expect"),
    [
        (401, "unauthorized", "failed"),
        (403, "forbidden", "failed"),
        (429, "too many", "uncertain"),
        (500, "boom", "uncertain"),
        (404, "gone", "not-supported"),
    ],
)
def test_codearts_probe_maps_transport_codes(monkeypatch, status, text, expect):
    """401/403 ⇒ failed；429/5xx/网络不明 ⇒ uncertain 且**不重放**；404 ⇒ not-supported。"""
    _codearts_env(monkeypatch)
    platforms = pa.load_platforms()
    calls: list[str] = []

    def fetcher(method, url, headers, body):
        calls.append(url)
        return status, text

    out = pa.probe_account(_acc("codearts"), platforms["codearts"], fetch=fetcher)
    assert out["kind"] == expect, out
    assert len(calls) == 1, "读出坏结论也不许重放"
    if expect == "uncertain":
        assert "不重放" in out["detail"]


def test_codearts_probe_network_error_is_uncertain(monkeypatch):
    """网络不明（`NetworkError`）⇒ uncertain，不重放。"""
    _codearts_env(monkeypatch)
    platforms = pa.load_platforms()
    calls: list[str] = []

    def fetcher(method, url, headers, body):
        calls.append(url)
        raise pa._ck().NetworkError("timed out")

    out = pa.probe_account(_acc("codearts"), platforms["codearts"], fetch=fetcher)
    assert out["kind"] == "uncertain"
    assert "不重放" in out["detail"]
    assert len(calls) == 1


def test_codearts_probe_shape_changed_is_uncertain(monkeypatch):
    """读到了但没有 total 那条 metric（形状变了）⇒ uncertain，**不当 0**。"""
    _codearts_env(monkeypatch)
    platforms = pa.load_platforms()
    body = dict(REAL_CODEARTS_PACKAGE, metrics=[{"name": "usageBasicPackageCredit"}])
    out = pa.probe_account(
        _acc("codearts"), platforms["codearts"], fetch=lambda *a: (200, json.dumps(body))
    )
    assert out["kind"] == "uncertain"
    assert "usageTotalPackageCredit" in out["detail"]
    assert "used_percent" not in out


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


@pytest.mark.parametrize("value", ["0", "100", "37", "0.5"])
def test_used_percent_in_range_is_accepted(patched, tmp_path, value):
    """卡 A334：`[account.quota].used_percent` 有值且在 [0, 100] ⇒ 放行（它是整窗估算的分母）。"""
    good = LEDGER.replace('unit = "点"', f'unit = "点"\nused_percent = {value}', 1)
    assert "used_percent" in good  # 替换真命中了，否则这条断言是空的
    data = pa.load_ledger(_write(tmp_path, good))
    wb = [a for a in data["account"] if a["id"] == "wb-1"][0]
    assert wb["quota"]["used_percent"] == float(value)  # 原值原样过，不夹不截


@pytest.mark.parametrize(
    "value",
    ["-0.5", "100.5", "101", "-1", '"半窗"', "true"],
)
def test_used_percent_out_of_range_is_refused(patched, tmp_path, value):
    """卡 A334：越界/非数 ⇒ `LedgerError` 且**点名**是哪个账号 —— 口径坏了不许静默。"""
    bad = LEDGER.replace('unit = "点"', f'unit = "点"\nused_percent = {value}', 1)
    assert "used_percent" in bad
    p = _write(tmp_path, bad)
    with pytest.raises(pa.LedgerError) as ei:
        pa.load_ledger(p)
    assert "used_percent" in str(ei.value)
    assert "wb-1" in str(ei.value)  # 点名到账号，不是「某个账号」


def test_used_percent_absent_means_unmeasured(patched, tmp_path):
    """卡 A334：整个省掉 = 未观测 ⇒ 合法（不许把「没这个数」当成 0 逼着填）。"""
    data = pa.load_ledger(_write(tmp_path, LEDGER))
    wb = [a for a in data["account"] if a["id"] == "wb-1"][0]
    assert "used_percent" not in wb["quota"]


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


def test_record_probe_result_never_touches_the_verdict_bits(patched, tmp_path):
    """⑲ `record_probe_result` 不碰**顶层**判定位：`state` / `approved_models` / `amount`。

    ★ 卡 A333 判据 6：`state` 是人工判定的（`STATES` 五行），`approved_models` 是派活
    白名单 —— 探测一次读数**都不许**碰它们。六结论码原样进 `samples`，一条都不许压平。
    ★ 卡 E121 起 `record_probe_result` **也写** `[account.health]` 的三键（`state` /
      `consecutive_failures` / `last_probe`）—— 那三个键的钉子见 ㉕a~㉕g。本条断言本体
      一条没动；名字换成事实，免得它变成「探测什么都不写」的第二句谎。
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


def test_record_probe_result_writes_used_percent_for_ok(patched):
    """卡 E97 ③：`kind=="ok"` 且带 `used_percent` ⇒ 写进 `[account.quota]`，值 46.51。

    ★ 为什么值当测：`used_percent` 在 E97 之前**全仓零写方**（账本里永远是「未观测」），
      所以「写进去以后还能被 `load_ledger()` 读回来」这件事从没被验证过；写坏了账本
      在仓外，没有 git 能 checkout 回来。
    """
    before = pa.load_ledger(patched)
    stamp_now = datetime(2026, 11, 9, 12, 0, 0, tzinfo=pa.TZ)
    rows = [
        {
            "id": "codearts-1",
            "platform": "codearts",
            "kind": "ok",
            "used_percent": 46.51,
            "amount": 4814.41,
            "unit": "credits",
        }
    ]
    pa.record_probe_result(patched, before, rows, now=stamp_now)

    after = pa.load_ledger(patched)  # ① 写坏了这里就炸
    quota = {a["id"]: a for a in after["account"]}["codearts-1"]["quota"]
    assert quota["used_percent"] == 46.51
    # ② amount 仍然不许被探测结果改写（余额归人/别的闸，E97 只开 used_percent 这一格）
    assert quota["amount"] == 12

    # ③ 再跑一次不重复长键（TOML 里同键写两遍会直接读不回来）
    pa.record_probe_result(patched, after, rows, now=stamp_now)
    again = pa.load_ledger(patched)
    quota2 = {a["id"]: a for a in again["account"]}["codearts-1"]["quota"]
    assert quota2["used_percent"] == 46.51
    assert patched.read_text(encoding="utf-8").count("used_percent") == 1
    # ④ samples 只按次数加，键集合不变
    assert set(quota2) == set(quota) | {"samples", "observed_at"}
    assert [s["kind"] for s in quota2["samples"]] == ["ok", "ok"]


def test_record_probe_result_never_writes_or_deletes_used_percent_otherwise(patched):
    """不确定 / 跳过 / 读坏的行 ⇒ **不写也不删**旧值（缺键仍是「未观测」）。"""
    base = pa.load_ledger(patched)
    stamp_now = datetime(2026, 11, 9, 12, 0, 0, tzinfo=pa.TZ)
    # 先写一个真读数，再让后续的不确定行来「碰」它
    pa.record_probe_result(
        patched,
        base,
        [{"id": "codearts-1", "platform": "codearts", "kind": "ok", "used_percent": 46.51}],
        now=stamp_now,
    )
    seeded = pa.load_ledger(patched)
    assert {a["id"]: a for a in seeded["account"]}["codearts-1"]["quota"]["used_percent"] == 46.51

    for kind in ("uncertain", "skipped", "failed", "not-supported", "unknown-platform"):
        pa.record_probe_result(
            patched,
            seeded,
            [{"id": "codearts-1", "platform": "codearts", "kind": kind, "detail": "x"}],
            now=stamp_now,
        )
        kept = {a["id"]: a for a in pa.load_ledger(patched)["account"]}
        assert kept["codearts-1"]["quota"]["used_percent"] == 46.51, f"{kind} 把旧读数删了"


def test_record_probe_result_does_not_invent_used_percent_for_other_platforms(patched):
    """其它平台的 ok 行（没带 used_percent）⇒ 账本里仍然**没有**这个键。"""
    before = pa.load_ledger(patched)
    pa.record_probe_result(
        patched,
        before,
        [{"id": "wb-1", "platform": "workbuddy", "kind": "ok", "amount": 7}],
        now=datetime(2026, 11, 9, 12, 0, 0, tzinfo=pa.TZ),
    )
    after = pa.load_ledger(patched)
    assert "used_percent" not in {a["id"]: a for a in after["account"]}["wb-1"]["quota"]


@pytest.mark.parametrize("value", [100.5, -0.5, "46.5", True, float("nan")])
def test_record_probe_result_refuses_out_of_range_used_percent(patched, value):
    """写前走 `_check_account()` 的范围校验：越界 / 不是数 ⇒ `LedgerError`，账本一个字节都不变。"""
    before = pa.load_ledger(patched)
    raw = patched.read_bytes()
    rows = [{"id": "codearts-1", "platform": "codearts", "kind": "ok", "used_percent": value}]
    stamp_now = datetime(2026, 11, 9, 12, 0, 0, tzinfo=pa.TZ)
    with pytest.raises(pa.LedgerError) as ei:
        pa.record_probe_result(patched, before, rows, now=stamp_now)
    assert "used_percent" in str(ei.value)
    assert patched.read_bytes() == raw


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


# -------------------------------------------- ㉔ meoo：文件型凭据 + 显式额度路径


MEOO_BODY = {
    "success": True,
    "data": {
        "account": {
            "userId": 1278407974428800,
            "availableBalance": 56958,
            "frozenBalance": 0,
            "totalGranted": 61000,
            "totalConsumed": 42,
            "totalExpired": 4000,
        },
        "activeGrants": [{"sourceType": "BOOST_PACK", "totalRemainingAmount": 50000}],
    },
}


def test_meoo_amount_path_beats_guessing():
    """㉔a 真形状下「猜」不到额度，但表里写了路径就取到 —— 猜出来的错数比 0 更坏。

    咬法：同一条响应，`_extract_amount`（猜）取不到真值，`_amount_at_path` 取到 56958。
    只要有人把 `amount_path` 删掉、退回猜键名，这条就红。
    """
    assert pa._extract_amount(MEOO_BODY) is None  # 猜不到 availableBalance（键名不在 AMOUNT_KEYS）
    assert pa._amount_at_path(MEOO_BODY, "data.account.availableBalance") == 56958.0
    # 一旦有哪个键名落进 AMOUNT_KEYS（比如上游把它改叫 total），猜出来的就是
    # 总授信 61000 而不是真值 —— 这才是「猜」的危险之处：错得像个正常读数。
    assert pa._extract_amount({"total": 61000, "availableBalance": 56958}) == 61000.0


def test_meoo_amount_path_missing_is_uncertain_not_zero(monkeypatch):
    """㉔b 路径走不通 ⇒ uncertain（不是 0，也不是「猜一个」）。"""
    monkeypatch.setenv("TF_DEMO_TOKEN", "t")
    plat = {
        "probe": "http",
        "probe_url": "https://example.invalid",
        "base_urls": ["https://example.invalid"],
        "token_env": "TF_DEMO_TOKEN",
        "amount_path": "data.account.availableBalance",
    }
    out = pa.probe_account(_acc(), plat, fetch=lambda u, t: (200, {"data": {}}, ""))
    assert out["kind"] == "uncertain"
    assert "data.account.availableBalance" in out["detail"]
    assert "amount" not in out


def test_meoo_real_platform_uses_its_own_amount_path(monkeypatch):
    """㉔c 真能力表里 meoo 那一段要能探出 56958（桩喂真响应，不联网）。"""
    plats = pa.load_platforms()
    plat = plats["meoo"]
    assert plat["amount_path"] == "data.account.availableBalance"
    monkeypatch.setattr(pa, "_token_from_file", lambda p: ("fake-token", "桩"))
    out = pa.probe_account(_acc("meoo"), plat, fetch=lambda u, t: (200, MEOO_BODY, ""))
    assert out["kind"] == "ok"
    assert out["amount"] == 56958.0
    assert out["unit"] == "积分"
    assert "/open/v1/cli-compat/account/points" in out["detail"]


def test_meoo_token_comes_from_credentials_file(monkeypatch, tmp_path):
    """㉔d 文件型凭据：值从 JSON 的 `accessToken` 读，来源说明只报位点、不报值。"""
    cred = tmp_path / "credentials.json"
    cred.write_text(json.dumps({"accessToken": "tok-abcdefgh", "userId": "x"}), encoding="utf-8")
    plat = {"token_file": str(cred), "token_key": "accessToken"}
    token, where = pa._token_for(plat)
    assert token == "tok-abcdefgh"
    assert "accessToken" in where
    assert "tok-abcdefgh" not in where  # 来源说明里不许回显值


def test_meoo_token_file_missing_reports_where(monkeypatch, tmp_path):
    """㉔e 位点不在 / JSON 坏 / 键不在 ⇒ 都回 `("", 该去哪儿找)`，且不抛。"""
    missing = tmp_path / "nope.json"
    token, where = pa._token_for({"token_file": str(missing)})
    assert token == ""
    assert str(missing) in where

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    token, where = pa._token_for({"token_file": str(broken), "token_key": "accessToken"})
    assert token == ""
    assert "not json" not in where  # 不把文件内容带出来

    no_key = tmp_path / "nokey.json"
    no_key.write_text(json.dumps({"other": "v"}), encoding="utf-8")
    assert pa._token_for({"token_file": str(no_key)})[0] == ""


def test_meoo_credential_file_is_not_opened_when_gate_off(monkeypatch):
    """㉔f 闸关 ⇒ **一个凭据文件都不开**（文件这一支必须在闸后面）。

    咬法：把读文件那一支换成「被调用就炸」的桩，闸关时它一次都不该被碰。
    """
    monkeypatch.setenv(pa.ACCOUNT_DISCOVERY_ENV, "1")

    def boom(plat):
        raise AssertionError("闸关时不许开凭据文件")

    monkeypatch.setattr(pa, "_token_from_file", boom)
    assert pa._token_for({"token_file": "~/.meoo/credentials.json"}) == ("", "")


def test_meoo_declared_dir_is_discoverable(monkeypatch):
    """㉔g `~/.meoo` 进 DECLARED_DIRS ⇒ discover 会报出这个位点（不是「默默忽略」）。"""
    monkeypatch.setenv(pa.ACCOUNT_DISCOVERY_ENV, "")
    rows = pa.discover([])
    pointers = [r["pointer"] for r in rows]
    assert "~/.meoo" in pointers

# ------------------------------------------ ㉕ 卡 E121：`[account.health]` 的写方


def _day_at(hour: int, minute: int) -> datetime:
    """钉子里统一的「2026-10-26 的几点」（北京时区，与账本夹具同一天）。"""
    return datetime(2026, 10, 26, hour, minute, tzinfo=pa.TZ)


class _FakeFetcher:
    """按顺序回放 `(status, body)`，多问一次就炸（与 `tests/test_pool_checkin.py` 同形）。"""

    def __init__(self, responses: list[tuple[int, object]]) -> None:
        self.responses = list(responses)
        self.calls: list[str] = []

    def __call__(self, method, url, headers, body):
        self.calls.append(url)
        if not self.responses:
            raise AssertionError(f"意外多出来的请求：{method} {url}")
        status, payload = self.responses.pop(0)
        return status, payload if isinstance(payload, str) else json.dumps(payload)


def test_derive_health_state_is_a_table():
    """㉕a 判据 1：`derive_health_state` 是一张**显式表**，表外一律不编 state。

    咬法（变异 A）：把 `uncertain` 支改成返回 `degraded`，「没定论」就变成账本上
    一个没人验证过的健康态 —— 这一条当场红。
    """
    table = [
        ("ok", "ok"),
        ("failed", "auth-expired"),
        ("uncertain", None),
        ("skipped", None),
        ("not-supported", None),
        ("unknown-platform", None),
        (None, None),
    ]
    for kind, want in table:
        assert pa.derive_health_state(kind) == want, f"{kind!r} 应折成 {want!r}"

    # 返回值只有两种可能：None，或卡 E45 的五值之一（枚举外不许凭空出现新值）
    allowed = {None, "ok", "degraded", "quota-exhausted", "auth-expired", "unknown"}
    assert allowed - {None} == pa.HEALTH_STATES
    for kind in (None, *pa._ck().KINDS, "unknown-platform", ""):
        assert pa.derive_health_state(kind) in allowed


def test_probe_writes_health_through_the_single_writer(patched):
    """㉕b 判据 2：`record_probe_result` 只经 `_apply_probe_health` 写那三个键。

    咬法：① 三键都要更新（`last_probe` / `state` / `consecutive_failures`）；
    ② `revoked` / `revoked_at` 一字不动 —— 整块替换 `acc["health"]` 会把吊销标记冲掉
    （卡 A335，`tests/test_renew_lock.py:192-193` 也钉着）；③ `quota.amount` 不动；
    ④ 探测不许伪造签到：`last_checkin` / `last_checkin_at` 一个都不许出现。
    """
    data = pa.load_ledger(patched)
    acc = {a["id"]: a for a in data["account"]}["codearts-1"]
    acc["health"] = {
        "state": "unknown",
        "consecutive_failures": 7,
        "last_probe": "2026-10-01T08:00:00+08:00",
        "revoked": "revoked deadbeefdeadbeef",
        "revoked_at": "2026-10-02T08:00:00+08:00",
    }
    pa.save_ledger(patched, data)

    before = pa.load_ledger(patched)
    pa.record_probe_result(
        patched,
        before,
        [{"id": "codearts-1", "platform": "codearts", "kind": "ok", "amount": 3}],
        now=datetime(2026, 11, 17, 10, 0, 0, tzinfo=pa.TZ),
    )

    got = {a["id"]: a for a in pa.load_ledger(patched)["account"]}["codearts-1"]
    health = got["health"]
    assert health["last_probe"] == "2026-11-17T10:00:00+08:00"
    assert health["state"] == "ok"
    assert health["consecutive_failures"] == 0
    assert health["revoked"] == "revoked deadbeefdeadbeef"
    assert health["revoked_at"] == "2026-10-02T08:00:00+08:00"
    assert got["quota"]["amount"] == 12
    assert "last_checkin" not in health and "last_checkin_at" not in health


def test_probe_does_not_forge_todays_checkin(patched, monkeypatch):
    """㉕c 判据 3（正面证明）：下午探一次，**不许**把上午的签到读成「刚签过」。

    账本：`last_checkin = "claimed"`、`last_checkin_at = 09:00`（今天签的）、
    `last_probe = 昨天 18:30`。15:00 探一次（`skipped`）再探一次（`ok`）——
    探测只许推进 `last_probe`，`last_checkin_at` 必须还是 09:00；
    15:05 跑 `recheck_rows` ⇒ 该号**不在**待复查里（`due_for_recheck` 判「当日已定案」）。

    咬法：变异 C（注释掉写方）⇒ `last_probe` 停在昨天；变异 E（`at` 改回只读
    `last_probe`）⇒ 签到时刻被读成 15:00，上午那句真签到就没了（卡 E121 问题 6）。
    """
    data = pa.load_ledger(patched)
    acc = {a["id"]: a for a in data["account"]}["codearts-1"]
    acc["health"] = {
        "state": "ok",
        "consecutive_failures": 0,
        "last_checkin": "claimed",
        "last_checkin_at": "2026-10-26T09:00:00+08:00",
        "last_probe": "2026-10-25T18:30:46+08:00",
    }
    pa.save_ledger(patched, data)

    for kind in ("skipped", "ok"):
        data = pa.load_ledger(patched)
        rows = [{"id": "codearts-1", "kind": kind}]
        pa.record_probe_result(patched, data, rows, now=_day_at(15, 0))

    after = {a["id"]: a for a in pa.load_ledger(patched)["account"]}["codearts-1"]
    assert after["health"]["last_probe"] == "2026-10-26T15:00:00+08:00"
    assert after["health"]["last_checkin_at"] == "2026-10-26T09:00:00+08:00"

    # 15:05 复查：拿 09:00 那个时刻算 ⇒ 当日已定案（该号不出现）
    platforms = pa.load_platforms()
    rows = pa.recheck_rows(pa.load_ledger(patched), platforms, now=_day_at(15, 5))
    assert "codearts-1" not in [r["id"] for r in rows], rows

    # 反向：删掉新键、只留 last_probe=15:00 ⇒ 走的确实是**回落**分支（at 就是 15:00）。
    # 直接截 `due_for_recheck` 收到的 `at`：只看结论的话，claimed + 同一天在两种时刻下
    # 都会判「当日已定案」，分不出走的是哪一支。
    data = pa.load_ledger(patched)
    del {a["id"]: a for a in data["account"]}["codearts-1"]["health"]["last_checkin_at"]
    ck = pa._ck()
    seen: list[datetime | None] = []
    real = ck.due_for_recheck

    def spy(last, *, at, now, timezone, platform, offline=False, tries=0):
        seen.append(at)
        return real(
            last,
            at=at,
            now=now,
            timezone=timezone,
            platform=platform,
            offline=offline,
            tries=tries,
        )

    monkeypatch.setattr(ck, "due_for_recheck", spy)
    pa.recheck_rows(data, platforms, now=_day_at(15, 5), platform="codearts")
    assert seen == [_day_at(15, 0)], f"回落分支应把 last_probe 当签到时刻，实际 {seen}"


def test_recheck_prefers_last_checkin_at(patched):
    """㉕d 判据 3：`recheck_rows` 的 at 优先 `last_checkin_at`，缺失才回落 `last_probe`。

    同一份账本、同一个 `now`，只差一个新键：
      · 有 `last_checkin_at = 09:00`（`last_probe` 被 10:50 那次探测推到 10:50）
        ⇒ 距 11:00 已过 2 小时 ⇒ 「上午的『已签过』不可信，复查窗口到了」；
      · 没有新键、`last_probe = 10:50` ⇒ 回落，只过 10 分钟 < `RECHECK_EVERY_S`（30 分）
        ⇒ 「当日已定案」。
    两边结论**必须不同** —— 只钉一边会放过「两处都读 last_probe」的写法。
    """
    data = pa.load_ledger(patched)
    acc = {a["id"]: a for a in data["account"]}["codearts-1"]
    acc["health"] = {
        "state": "ok",
        "consecutive_failures": 0,
        "last_checkin": "already-claimed",
        "last_checkin_at": "2026-10-26T09:00:00+08:00",
        "last_probe": "2026-10-26T10:50:00+08:00",
    }
    platforms = pa.load_platforms()

    rows = pa.recheck_rows(data, platforms, now=_day_at(11, 0), platform="codearts")
    assert [r["id"] for r in rows] == ["codearts-1"], rows
    assert rows[0]["why"] == "上午的「已签过」不可信，复查窗口到了"
    assert rows[0]["provisional"] is True

    del acc["health"]["last_checkin_at"]
    rows = pa.recheck_rows(data, platforms, now=_day_at(11, 0), platform="codearts")
    assert rows == [], rows


def test_failure_policy_is_single(patched):
    """㉕e 判据 4：同一个 kind，签到路与探测路给出**同一个**连败结论。

    `uncertain` / `failed` / `not-supported` 三个码两条路都产得出（签到路：缺 token、
    `code != 0`、`claim_flow` 为空；探测路直接喂 kind）。若有人在探测路重写一份失败
    词表（比如漏掉 `uncertain`），连败读数会分叉 —— 这一条当场红。

    ★ 与卡规格的一处诚实偏差：卡规格写「断言 `(state, consecutive_failures)` 完全一致」，
      但 `_record_checkin()` **不写 `state`**（那是探测的管辖权，判据 2）。所以这里比三样：
      ① 连败计数两条路必须相等；② 签到路不许动 `state`；③ 探测路的 `state` 必须正好是
      `derive_health_state(kind)` 给的那一格（`None` 时不许动）。
    """
    cases = [
        ("uncertain", "workbuddy", {}, [(200, {"data": {"checked_in": True}})]),
        ("failed", "workbuddy", {"TF_WORKBUDDY_TOKEN": "t"}, [(200, {"code": 1})]),
        ("not-supported", "opencode", {}, []),
    ]
    platforms = pa.load_platforms()
    for kind, platform, environ, responses in cases:
        text = LEDGER.replace('platform = "workbuddy"', f'platform = "{platform}"')
        patched.write_text(text, encoding="utf-8")
        seeded = {"state": "degraded", "consecutive_failures": 5}

        # ---- 签到路
        data = pa.load_ledger(patched)
        acc = {a["id"]: a for a in data["account"]}["wb-1"]
        acc["health"] = dict(seeded)
        rows = pa.run_checkin(
            data,
            platforms,
            platform=platform,
            environ=environ,
            fetcher=_FakeFetcher(list(responses)),
            now=_day_at(12, 0),
            sleep=lambda s: None,
            spacing=0,
        )
        assert [r["kind"] for r in rows] == [kind], rows
        via_checkin = (acc["health"]["state"], acc["health"]["consecutive_failures"])

        # ---- 探测路
        data = pa.load_ledger(patched)
        acc = {a["id"]: a for a in data["account"]}["wb-1"]
        acc["health"] = dict(seeded)
        pa.record_probe_result(patched, data, [{"id": "wb-1", "kind": kind}], now=_day_at(12, 0))
        health = {a["id"]: a for a in pa.load_ledger(patched)["account"]}["wb-1"]["health"]
        via_probe = (health["state"], health["consecutive_failures"])

        assert via_checkin == ("degraded", via_probe[1]), "签到路不许动 state"
        want_state = pa.derive_health_state(kind) or "degraded"
        assert via_probe[0] == want_state, f"{kind}：探测路的 state 应是 {want_state}"
        assert via_probe[1] == via_checkin[1], f"{kind}：连败分叉 {via_checkin} ≠ {via_probe}"


def test_health_state_is_validated_on_write(patched):
    """㉕f 判据 5(a)：`health.state` 的枚举校验**在写路径上**也咬得住。

    咬法：`lastgood.write_atomic()` 的 `validate` 只判**旧文件**能不能进 `.bak`
    （`tools/pool/lastgood.py:280` 判旧、`:300` 直接 os.replace），新 payload 一次都不验。
    若 `save_ledger()` 不自己调 `_validate_ledger_toml(payload)`，把 `state` 写成
    `healthy` 会**顺利落盘** —— 这条断言当场红（写前后 `read_bytes()` 必须一模一样）。
    """
    data = pa.load_ledger(patched)
    acc = {a["id"]: a for a in data["account"]}["codearts-1"]
    acc["health"]["state"] = "healthy"
    raw_before = patched.read_bytes()

    with pytest.raises(pa.LedgerError) as ei:
        pa.save_ledger(patched, data)
    message = str(ei.value)
    assert "codearts-1" in message, message  # 点名账号
    assert "healthy" in message, message  # 点名坏值
    assert "ok" in message and "auth-expired" in message, message  # 点名合法值
    assert patched.read_bytes() == raw_before, "拒写时账本不许有半个字节的改动"

    # 合法值照写；`health` 缺、`state` 缺也都合法（老账本 / 没探过的号）
    acc["health"]["state"] = "degraded"
    pa.save_ledger(patched, data)
    assert "degraded" in patched.read_text(encoding="utf-8")
    data = pa.load_ledger(patched)
    del {a["id"]: a for a in data["account"]}["codearts-1"]["health"]["state"]
    del {a["id"]: a for a in data["account"]}["wb-1"]["health"]
    pa.save_ledger(patched, data)
    pa.load_ledger(patched)  # 读回来也不许因为「缺键」而抛


def test_read_surface_keys_unchanged(patched):
    """㉕g 判据 5(b)：只读面的键集一个都不许动（本卡不往 `list_rows` 加 health 键）。

    咬法：`health_state` / `consecutive_failures` 一旦被顺手加进 `list_rows`，
    这条红。★ 用 `>=` 不用 `==`：另一张在飞的卡（E118）已经在 `list_rows` 里追加
    了 `quota_kind` / `quota_at` / `health_state` / `consecutive_failures` 四个键，
    写 `==` 会与那张卡对撞；本卡要钉的是「health 三键没有被**本卡**带进只读面」。

    ★ 卡 E118 落地后（T-AG628）：它按自己的判据确实加了 `health_state` 这一个键，
    所以末一条断言从「整份 JSON 里不许出现 auth-expired」收紧成「**只许**出现在
    `health_state` 那一格里，别的键一个新字都不许多说」—— 钉子的意图（health 不许
    从这条只读面漏出去）不变，只是承认 E118 点名要的那一格。
    """
    eight = {
        "id",
        "platform",
        "platform_known",
        "label",
        "state",
        "quota",
        "models",
        "credential",
    }
    before = pa.list_rows(pa.load_ledger(patched), None, False)
    assert all(set(row) >= eight for row in before), [sorted(row) for row in before]

    data = pa.load_ledger(patched)
    acc = {a["id"]: a for a in data["account"]}["codearts-1"]
    acc["health"] = {"state": "auth-expired", "consecutive_failures": 9,
                     "last_probe": "2026-11-17T10:00:00+08:00"}
    pa.save_ledger(patched, data)

    after = pa.list_rows(pa.load_ledger(patched), None, False)
    assert [sorted(r) for r in after] == [sorted(r) for r in before]
    assert all(set(row) >= eight for row in after)
    spoken = [
        {k: v for k, v in row.items() if k not in {"health_state", "consecutive_failures"}}
        for row in after
    ]
    assert "auth-expired" not in json.dumps(spoken, ensure_ascii=False)
    assert [row.get("health_state") for row in after if row.get("id") == "codearts-1"] == [
        "auth-expired"
    ], after


# ------------------------------------------------------- 卡 E118：探过没探到，别洗成「未观测」

KINDS = ("ok", "skipped", "uncertain", "failed", "not-supported", "unknown-platform")

# 今日五号的形状（卡 E118 问题 1）：amount 全缺、samples 末条 skipped×3 + uncertain×1、
# health.state 全 unknown。
_PROBED_HEAD = '''
[[account]]
id = "{aid}"
label = "{aid}"
platform = "{plat}"
state = "active"
added_at = "2026-09-30"
approved_models = ["{model}"]

[account.credential]
kind = "none"
locator = ""

[account.quota]
unit = "credits"
observed_at = "{at}"
samples = [{{ at = "{at}", kind = "{kind}" }}]

[account.health]
state = "{health}"
consecutive_failures = {fails}
'''


def _probed(aid="a-1", plat="codearts", model="huaweicloud-maas/GLM-5.2", kind="skipped",
            at="2026-11-16T12:57:30+08:00", health="unknown", fails=1) -> str:
    return _PROBED_HEAD.format(aid=aid, plat=plat, model=model, kind=kind, at=at,
                              health=health, fails=fails)


def _rows(tmp_path, text: str) -> list[dict]:
    data = pa.load_ledger(_write(tmp_path, text))
    return pa.list_rows(data, None, False)


def test_unobserved_means_never_probed(patched):
    """判据 1：「未观测」只留给账本里**从没探过**的号（卡 E118）。"""
    data = pa.load_ledger(patched)
    # ① 没有 samples（wb-1 连 observed_at 都没有）⇒ 恰好「未观测」，不许凭空补一对括号
    wb = [a for a in data["account"] if a["id"] == "wb-1"][0]
    assert pa._quota_text(wb) == "未观测"
    # ② 有 amount 的号不进这一支
    ca = [a for a in data["account"] if a["id"] == "codearts-1"][0]
    assert not pa._quota_text(ca).startswith("未观测")
    # ③ samples 末条缺 kind（照非法形状那条样本）⇒ 不抛、也不编结论码
    shaped = data["account"][1]
    shaped["quota"]["samples"] = [{"observed_at": "2026-11-16", "amount": 3}]
    text = pa._quota_text(shaped)
    assert text.startswith("探过但没记结论码")
    for kind in KINDS:
        assert kind not in text, (kind, text)


def test_probe_kind_is_named_not_washed(patched, tmp_path, capsys):
    """判据 2：探过但没探到的，判词必须说出最近一次的结论码与时刻（卡 E118）。"""
    texts = {}
    for kind in ("skipped", "uncertain", "failed", "not-supported"):
        row = _rows(tmp_path, _probed(kind=kind, at="2026-11-16T13:00:08+08:00"))[0]
        got = row["quota"]
        assert got.startswith(kind), (kind, got)        # 以该 kind 打头
        assert "2026-11-16T13:00:08+08:00" in got, got   # 含末条 at
        assert "连败 1" in got, got                      # 念账本原值
        texts[kind] = got
    assert len(set(texts.values())) == 4, texts          # 四种不许洗成一句
    # 今日五号的形状复刻：没有一条能叫「未观测」
    five = (_probed(aid="c-1", kind="skipped")
            + _probed(aid="c-2", plat="codebuddy", kind="uncertain",
                      at="2026-11-16T13:00:08+08:00", fails=0)
            + _probed(aid="c-3", plat="workbuddy", model="hunyuan/x")
            + _probed(aid="c-4", plat="trae", model="trae/claude-sonnet")
            + _probed(aid="c-5", plat="meoo", model="meoo/x", fails=0))
    rows = _rows(tmp_path, five)
    assert len(rows) == 5
    for row in rows:
        assert not row["quota"].startswith("未观测"), row
    assert pa.main(["--ledger", str(_write(tmp_path, five)), "list", "--json"]) == pa.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["accounts"]) == 5
    for row in payload["accounts"]:
        assert not row["quota"].startswith("未观测"), row


def test_list_json_carries_probe_verdict(patched, tmp_path):
    """判据 3：机器块能分开四种，且只加键不改键（卡 E118）。"""
    rows = _rows(tmp_path, _probed(kind="uncertain", fails=3))
    row = rows[0]
    # 既有 8 键一个不少（test_list_json_is_sorted_and_shaped 那条钉子仍绿）
    assert set(row) >= {"id", "platform", "platform_known", "label", "state", "quota",
                        "models", "credential"}
    assert row["quota_kind"] == "uncertain"
    assert row["quota_at"] == "2026-11-16T12:57:30+08:00"
    assert row["health_state"] == "unknown"
    assert row["consecutive_failures"] == 3
    # 缺键 ⇒ None（不补 "" / "ok" / 0）
    tail = "[account.health]\nstate = \"unknown\"\nconsecutive_failures = 3\n"
    bare = _rows(tmp_path, _probed(aid="b-1", fails=3).replace(tail, ""))[0]
    assert bare["health_state"] is None
    assert bare["consecutive_failures"] is None


def test_quota_text_unchanged_when_amount_present(patched):
    """判据 4-a：amount 有值时判词逐字不变（卡 E118 不许顺手改好话）。"""
    data = pa.load_ledger(patched)
    ca = [a for a in data["account"] if a["id"] == "codearts-1"][0]
    assert pa._quota_text(ca) == "12 credits（2026-10-25T09:00:00+08:00）"


def test_health_state_is_never_invented(patched, tmp_path):
    """判据 4-b：health.state 缺键不许编成 ok（卡 E118）。"""
    tail = "[account.health]\nstate = \"unknown\"\nconsecutive_failures = 1\n"
    text = _probed(aid="h-1").replace(tail, "")
    assert "[account.health]" not in text  # 替换真命中了，否则这条断言是空的
    rows = _rows(tmp_path, text)
    assert rows[0]["health_state"] is None
    assert "健康" not in rows[0]["quota"], rows[0]["quota"]


def test_cli_list_does_not_truncate_verdict(patched, tmp_path, capsys):
    """判据 4-c：列宽上限必须容得下最坏 61 字符那条（卡 E118）。"""
    p = _write(tmp_path, _probed(aid="w-1", kind="unknown-platform", fails=12))
    assert pa.main(["--ledger", str(p), "list"]) == pa.EXIT_OK
    out = capsys.readouterr().out
    assert "健康 unknown" in out, out      # 不是「健康 unkn」
    assert "连败 12" in out, out


# ------------------------------------- ㉖ 窗口两键：探 → 登记（卡 A370）


WINDOW_PLAT = {
    "probe": "http",
    "probe_url": "https://example.invalid",
    "base_urls": ["https://example.invalid"],
    "token_env": "TF_DEMO_TOKEN",
    "amount_path": "data.quota.remaining",
    "reset_path": "data.quota.resetsAt",
    "window_hours": 5,
}

WINDOW_BODY = {
    "data": {"quota": {"remaining": 8, "resetsAt": "2026-11-19T17:00:00+08:00"}},
}


def test_probe_ok_row_registers_window_keys(patched, monkeypatch):
    """㉖a 平台表给了 `reset_path` + `window_hours`、响应里也取得出 ⇒
    ok 行带 `resets_at` / `span_s`，`record_probe_result()` 把它们写进 `[account.quota]`；
    写前全校验（半个键 / 0 跨度 / 解析不出的时刻 ⇒ `LedgerError`，账本一个字节不变）。
    """
    monkeypatch.setenv("TF_DEMO_TOKEN", "t")
    out = pa.probe_account(_acc("workbuddy"), dict(WINDOW_PLAT),
                           fetch=lambda u, t: (200, WINDOW_BODY, ""))
    assert out["kind"] == "ok"
    assert out["resets_at"] == "2026-11-19T17:00:00+08:00"
    assert out["span_s"] == 5 * 3600

    # 账本里这个号叫 `wb-1`（`_acc()` 造的是 `workbuddy-1`）；落盘那一侧只认账本里的 id。
    out["id"] = "wb-1"
    stamp_now = datetime(2026, 11, 19, 12, 0, 0, tzinfo=pa.TZ)
    before = pa.load_ledger(patched)
    pa.record_probe_result(patched, before, [out], now=stamp_now)
    quota = {a["id"]: a for a in pa.load_ledger(patched)["account"]}["wb-1"]["quota"]
    assert quota["resets_at"] == "2026-11-19T17:00:00+08:00"
    assert quota["span_s"] == 5 * 3600

    # 解析只许走 `pool_quota.parse_reset()`（唯一真源）—— 它不是只认 ISO-8601：
    # 报错文案里的 `YYYY-MM-DD HH:MM:SS UTC+N` 形状也必须认，且落盘统一成 +08:00。
    utc_row = {
        "id": "wb-1",
        "platform": "workbuddy",
        "kind": "ok",
        "amount": 7,
        "resets_at": "2026-11-19 17:00:00 UTC+8",
        "span_s": 5 * 3600,
    }
    pa.record_probe_result(patched, pa.load_ledger(patched), [utc_row], now=stamp_now)
    quota = {a["id"]: a for a in pa.load_ledger(patched)["account"]}["wb-1"]["quota"]
    assert pa._parse_reset_strict(quota["resets_at"]) == datetime(
        2026, 11, 19, 17, 0, 0, tzinfo=pa.TZ
    )

    # ★ 硬边界：与 used_percent 同款「写前全校验」—— 坏的一对必须抛，且账本一个字节不变。
    raw = patched.read_bytes()
    bad_rows = [
        {"resets_at": "2026-11-19T17:00:00+08:00"},
        {"resets_at": "2026-11-19T17:00:00+08:00", "span_s": 0},
        {"resets_at": "不是时刻", "span_s": 3600},
    ]
    for bad in bad_rows:
        row = {"id": "wb-1", "platform": "workbuddy", "kind": "ok", "amount": 7, **bad}
        with pytest.raises(pa.LedgerError):
            pa.record_probe_result(patched, pa.load_ledger(patched), [row], now=stamp_now)
        assert patched.read_bytes() == raw, bad


def test_curve_window_shape_is_not_the_ledger_window(patched):
    """㊖2 曲线那一侧的入参形状（`resets_at` 是 unix 秒整数 + `span`）不是账本窗口两键：
    照旧记账、不抛、不写账本。

    ★ 现场（卡 A370 落地门禁）：全量 pytest 红在
      `tests/test_pool_quota_history.py::test_record_probe_result_notes_a_drawable_window`——
      那条铉子给 `record_probe_result()`的行里 `resets_at` 是 **int**（给曲线用），
      而 `_check_window_keys()`把它当成账本窗口去解析字符串 ⇒ `LedgerError`。
    同一个键名两份契约，只能按**值的形状**分家（`_carries_ledger_window()`）。
    """
    stamp_now = datetime(2026, 11, 19, 12, 0, 0, tzinfo=pa.TZ)
    at = int(stamp_now.timestamp())
    before = patched.read_bytes()
    pa.record_probe_result(
        patched,
        pa.load_ledger(patched),
        [
            {
                "id": "wb-1",
                "platform": "workbuddy",
                "kind": "ok",
                "used": 40.0,
                "resets_at": at + 3600,
                "span": 86400,
            }
        ],
        now=stamp_now,
    )
    assert patched.read_bytes() != before  # 账本那一笔照落（samples / observed_at）
    quota = {a["id"]: a for a in pa.load_ledger(patched)["account"]}["wb-1"]["quota"]
    assert "resets_at" not in quota and "span_s" not in quota

    # 反向：同样是 int，但行里带了 `span_s` ⇒ 就是在声明账本窗口，必须抛。
    with pytest.raises(pa.LedgerError):
        pa.record_probe_result(
            patched,
            pa.load_ledger(patched),
            [{"id": "wb-1", "kind": "ok", "resets_at": at + 3600, "span_s": 3600}],
            now=stamp_now,
        )


def test_probe_without_window_keys_keeps_old_values(patched, monkeypatch):
    """㉖b 这一轮没带两键 ⇒ **不写也不删**，旧值逐字保留（缺键才叫「未观测」）。"""
    stamp_now = datetime(2026, 11, 19, 12, 0, 0, tzinfo=pa.TZ)
    pa.record_probe_result(
        patched,
        pa.load_ledger(patched),
        [
            {
                "id": "wb-1",
                "platform": "workbuddy",
                "kind": "ok",
                "amount": 7,
                "resets_at": "2026-11-19T17:00:00+08:00",
                "span_s": 5 * 3600,
            }
        ],
        now=stamp_now,
    )
    seeded = {a["id"]: a for a in pa.load_ledger(patched)["account"]}["wb-1"]["quota"]
    assert seeded["resets_at"] == "2026-11-19T17:00:00+08:00"
    assert seeded["span_s"] == 5 * 3600

    # 五结论码逐条来「碰」：一个都不许把旧窗口删掉（照 used_percent 那条口径）
    for kind in ("uncertain", "skipped", "failed", "not-supported", "unknown-platform"):
        pa.record_probe_result(
            patched,
            pa.load_ledger(patched),
            [{"id": "wb-1", "platform": "workbuddy", "kind": kind, "detail": "x"}],
            now=stamp_now,
        )
        kept = {a["id"]: a for a in pa.load_ledger(patched)["account"]}["wb-1"]["quota"]
        assert kept["resets_at"] == "2026-11-19T17:00:00+08:00", kind
        assert kept["span_s"] == 5 * 3600, kind


def test_platform_without_reset_path_never_writes_window(patched, monkeypatch):
    """㉖c 没写 `reset_path` 的平台（含 `probe = "manual"`）⇒ 两键**一个都不出现**。"""
    monkeypatch.setenv("TF_DEMO_TOKEN", "t")
    # ① http 平台但表里没给 reset_path：响应里就算有像重置时刻的键也不许猜
    bare = {k: v for k, v in WINDOW_PLAT.items() if k not in ("reset_path", "window_hours")}
    out = pa.probe_account(_acc("workbuddy"), bare, fetch=lambda u, t: (200, WINDOW_BODY, ""))
    assert out["kind"] == "ok"
    assert "resets_at" not in out and "span_s" not in out

    # ② manual 平台：连探测都不探，自然也没有窗口两键
    manual = pa.probe_account(_acc("lobsterai"), pa.load_platforms()["lobsterai"])
    assert manual["kind"] == "uncertain"
    assert "resets_at" not in manual and "span_s" not in manual

    # ③ 落盘那一侧：把这两行真的写进去，账本里也仍然没有这两键
    stamp_now = datetime(2026, 11, 19, 12, 0, 0, tzinfo=pa.TZ)
    pa.record_probe_result(patched, pa.load_ledger(patched), [out], now=stamp_now)
    quota = {a["id"]: a for a in pa.load_ledger(patched)["account"]}["wb-1"]["quota"]
    assert "resets_at" not in quota and "span_s" not in quota
    raw = patched.read_text(encoding="utf-8")
    assert "resets_at" not in raw and "span_s" not in raw
