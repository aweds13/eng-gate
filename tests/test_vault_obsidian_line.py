"""G 批 · T-G5：Obsidian Vault 根路径 + `obsidian://` 打开引用句柄（SR-F8.2 / 约定层第 11 行）。

**口径（2026-09-21 用户定，见 `复盘/口径定案-待定清单.md` §7）**：
- 备忘录 / 温故知新产出的引用句柄要能**直接调出 Obsidian**；
- **只读跳转**（红线 `SR-F8.2`）：软件**绝不往 Vault 里写任何东西**，也不替你在里面建目录；
- Vault **名字**是跳转的前提（`obsidian://open?vault=…&file=…`）；**根目录**可选 ——
  它只干一件事：把**绝对路径**句柄换算成 Vault 内的相对位置（顺带能校验"在不在库里"）。

覆盖：
- 拼 URL：逐段编码（空格/中文/`&`/`#` 不许跑成额外协议参数）；
- 句柄换算：Vault 相对路径直接用；绝对路径要填根目录、且必须在 Vault 里；`..` 一律拒绝；
- 跳转：`dry_run` 只算不开；runner 可注入；调不起来时给原话（不许静默）；
- 红线机器化：导出目录落在 Vault 里 → ① 保存目录 400 ② 保存 Vault 根 400 ③ 真写文件前也拒；
- **只读证据**：跳转前后 Vault 目录的文件清单与字节数**一模一样**（我们连碰都没碰）；
- 设置：三层默认（本机设置 → config → 空）、根目录必须真实存在、`describe` 报出重叠告警；
- API：`PUT /api/settings/vault`、`POST /api/vault/open`、复习卡/备忘录带出 `ref_url`。
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core import facts as facts_mod
from timeflow.core import vault
from timeflow.storage import db as db_mod

if TYPE_CHECKING:
    from pathlib import Path

DAY = "2026-09-21"
HANDLE = "notes/数学.md"
# 逐段编码：中文与 `/` 之外的分隔符 —— `notes/%E6%95%B0%E5%AD%A6.md`
HANDLE_ENCODED = "notes/%E6%95%B0%E5%AD%A6.md"


@pytest.fixture()
def conn(tmp_path):  # type: ignore[no-untyped-def]
    c = db_mod.connect(str(tmp_path / "vault.db"))
    facts_mod.clear()
    yield c
    c.close()
    facts_mod.clear()


@pytest.fixture()
def vaultdir(tmp_path) -> Path:  # type: ignore[no-untyped-def]
    """一个假 Obsidian 库：里面有既有笔记（用来证明"我们没碰它"）。"""
    root = tmp_path / "MyVault"
    (root / "notes").mkdir(parents=True)
    (root / "notes" / "数学.md").write_text("# 我自己的笔记\n", encoding="utf-8")
    (root / ".obsidian").mkdir()
    (root / ".obsidian" / "app.json").write_text("{}\n", encoding="utf-8")
    return root


def _snapshot(root: Path) -> dict[str, int]:
    """目录清单 + 每个文件的字节数（用来证明跳转是**只读**的）。"""
    return {
        str(p.relative_to(root)): p.stat().st_size
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def _client(tmp_path, name: str = "obsidian_api.db") -> TestClient:  # type: ignore[no-untyped-def]
    return TestClient(create_app(str(tmp_path / name)))


# ---------------------------------------------------------------- 拼 URL


def test_no_vault_name_means_no_jump(conn) -> None:
    """没填 Vault 名字 = 跳转关着：不给 URL，给一句人话（界面据此不摆按钮）。"""
    info = vault.link(conn, HANDLE)
    assert info["url"] == "" and info["vault"] == ""
    assert "Vault 名字" in str(info["reason"])


def test_relative_handle_becomes_obsidian_url(conn) -> None:
    """Vault 相对路径的句柄直接用（不需要根目录）。"""
    vault.set_vault(conn, "MyVault")
    info = vault.link(conn, HANDLE)
    assert info["url"] == f"obsidian://open?vault=MyVault&file={HANDLE_ENCODED}"
    assert info["file"] == HANDLE and info["reason"] == ""


def test_url_encodes_so_handles_cannot_smuggle_parameters(conn) -> None:
    """句柄里的 `&`/`#`/空格被编码 —— **不许**跑成额外的协议参数（否则等于换了目标）。"""
    vault.set_vault(conn, "My Vault&co")
    info = vault.link(conn, "notes/a&file=b#c d.md")
    assert info["url"] == (
        "obsidian://open?vault=My%20Vault%26co&file=notes/a%26file%3Db%23c%20d.md"
    )
    assert info["url"].count("&file=") == 1
    assert info["url"].count("?") == 1


def test_obsidian_url_keeps_path_separators(conn) -> None:
    """分隔符保留成 `/`（段内才编码）—— Obsidian 认的是库内路径，不是一长串 `%2F`。"""
    assert vault.obsidian_url("V", "a/b/c.md") == "obsidian://open?vault=V&file=a/b/c.md"


def test_backslash_handle_is_normalized(conn) -> None:
    """Windows 风格的句柄照样认（换成 `/`）。"""
    vault.set_vault(conn, "MyVault")
    assert vault.link(conn, "notes\\数学.md")["file"] == HANDLE


# ---------------------------------------------------------------- 句柄换算


def test_absolute_handle_needs_the_vault_dir(conn, vaultdir) -> None:
    """绝对路径句柄：没填根目录就算不出来 —— 如实说原因，不猜。"""
    vault.set_vault(conn, "MyVault")
    info = vault.link(conn, str(vaultdir / "notes" / "数学.md"))
    assert info["url"] == ""
    assert "Vault 根目录" in str(info["reason"])


def test_absolute_handle_inside_the_vault_is_relative(conn, vaultdir) -> None:
    """填了根目录 → 绝对路径换算成 Vault 内的位置。"""
    vault.set_vault(conn, "MyVault", str(vaultdir))
    info = vault.link(conn, str(vaultdir / "notes" / "数学.md"))
    assert info["file"] == HANDLE
    assert info["url"] == f"obsidian://open?vault=MyVault&file={HANDLE_ENCODED}"


def test_absolute_handle_outside_the_vault_is_refused(conn, vaultdir, tmp_path) -> None:
    """**不在 Vault 里就不跳** —— 否则 Obsidian 会打开一个同名的别的东西（等于指错路）。"""
    outside = tmp_path / "别处" / "数学.md"
    outside.parent.mkdir()
    outside.write_text("x\n", encoding="utf-8")
    vault.set_vault(conn, "MyVault", str(vaultdir))
    info = vault.link(conn, str(outside))
    assert info["url"] == "" and "不在 Vault 里" in str(info["reason"])


@pytest.mark.skipif(os.name != "nt", reason="大小写不敏感是 Windows 的事")
def test_vault_membership_ignores_case_on_windows(conn, vaultdir) -> None:
    """Windows 上 `D:\\Notes\\Vault` 与 `d:\\notes\\vault\\out` 是同一个地方 —— 红线也要拦得住。

    这里钉的是**行为**（大小写不同的写法照样算"在 Vault 里"），不是某一步实现
    （`core/vault.py` 的 `_rel_to` 显式做了归一，于是不依赖解释器版本）。
    POSIX 上大小写是两回事，所以这条只在 Windows 跑。
    """
    lower = str(vaultdir).lower()
    with pytest.raises(ValueError, match="不能放在 Obsidian 的 Vault 里"):
        vault.set_dir(conn, lower + "\\out", "export", default_vault_dir=lower)
    assert vault.describe(conn, "export")["configured"] is False


def test_handle_with_dotdot_is_refused(conn, vaultdir) -> None:
    """`..` 一律拒绝（相对句柄不许借道跳出 Vault）。"""
    vault.set_vault(conn, "MyVault", str(vaultdir))
    for handle in ("../外面.md", "notes/../../外面.md"):
        info = vault.link(conn, handle)
        assert info["url"] == "" and "跳出" in str(info["reason"])


def test_vault_root_itself_is_not_a_file(conn, vaultdir) -> None:
    vault.set_vault(conn, "MyVault", str(vaultdir))
    info = vault.link(conn, str(vaultdir))
    assert info["url"] == "" and "Vault 根目录本身" in str(info["reason"])


# ---------------------------------------------------------------- 跳（只读）


def test_dry_run_never_launches(conn) -> None:
    vault.set_vault(conn, "MyVault")
    called: list[str] = []

    def fake(url: str) -> tuple[bool, str]:
        called.append(url)
        return True, "已在 Obsidian 打开"

    result = vault.open_handle(conn, HANDLE, dry_run=True, runner=fake)
    assert result["executed"] is False and result["ok"] is True
    assert result["url"].startswith("obsidian://open?") and called == []


def test_open_handle_hands_the_url_to_the_system(conn) -> None:
    vault.set_vault(conn, "MyVault")
    seen: list[str] = []

    def fake(url: str) -> tuple[bool, str]:
        seen.append(url)
        return True, "已在 Obsidian 打开"

    result = vault.open_handle(conn, HANDLE, runner=fake)
    assert seen == [f"obsidian://open?vault=MyVault&file={HANDLE_ENCODED}"]
    assert result["executed"] is True and result["ok"] is True


def test_open_handle_failure_speaks_up(conn) -> None:
    """调不起来（没装 Obsidian / 协议没注册）→ `ok=false` + 原话（界面退回"复制链接 + 提示"）。"""
    vault.set_vault(conn, "MyVault")

    def fake(url: str) -> tuple[bool, str]:
        return False, "调不起 Obsidian（拒绝访问）"

    result = vault.open_handle(conn, HANDLE, runner=fake)
    assert result["ok"] is False and result["executed"] is False
    assert "调不起 Obsidian" in str(result["reason"])
    assert result["url"]          # 链接照样给出来（让用户自己粘）


def test_open_handle_without_vault_does_not_launch(conn) -> None:
    called: list[str] = []

    def fake(url: str) -> tuple[bool, str]:
        called.append(url)
        return True, "不该走到这里"

    result = vault.open_handle(conn, HANDLE, runner=fake)
    assert result["ok"] is False and called == []
    assert "Vault 名字" in str(result["reason"])


def test_jump_does_not_touch_the_vault(conn, vaultdir) -> None:
    """**只读的证据**：跳转（含各种失败路径）前后，Vault 里的文件与字节数**一模一样**。"""

    def fake(url: str) -> tuple[bool, str]:
        return True, "已在 Obsidian 打开"

    vault.set_vault(conn, "MyVault", str(vaultdir))
    before = _snapshot(vaultdir)
    for handle in (HANDLE, str(vaultdir / "notes" / "数学.md"), "../外面.md", "不存在的.md"):
        vault.open_handle(conn, handle, runner=fake)
    assert _snapshot(vaultdir) == before
    assert not list(vaultdir.rglob("*.tmp"))          # 也没落任何半截文件


# ---------------------------------------------------------------- 红线（导出不许进 Vault）


def test_export_dir_inside_vault_is_refused(conn, vaultdir) -> None:
    """① 保存导出目录：落在 Vault 里 → 拒绝（带原话），**配置一个字节都不改**。"""
    vault.set_vault(conn, "MyVault", str(vaultdir))
    with pytest.raises(ValueError, match="不能放在 Obsidian 的 Vault 里"):
        vault.set_dir(conn, str(vaultdir / "notes"), "export", default_vault_dir=str(vaultdir))
    assert vault.describe(conn, "export")["configured"] is False


def test_vault_dir_covering_the_export_dir_is_refused(conn, tmp_path) -> None:
    """② 保存 Vault 根目录：把**现在的导出目录**包进去 → 拒绝（顺序反过来也拦得住）。"""
    vault.set_dir(conn, str(tmp_path / "notes"), "export")
    with pytest.raises(ValueError, match="把现在的导出目录包进去了"):
        vault.set_vault(conn, "MyVault", str(tmp_path))


def test_export_day_refuses_to_write_into_the_vault(conn, vaultdir) -> None:
    """③ 真写文件前再拒一次 —— 配置文件里把两个目录写重叠也拦得住（**不许静默**）。"""
    with pytest.raises(ValueError, match="不能放在 Obsidian 的 Vault 里"):
        vault.export_day(conn, DAY, str(vaultdir), default_vault_dir=str(vaultdir))
    assert not (vaultdir / f"{DAY}.md").exists()

    # 自动导出：只记错、不抛（md 是产物，不许把"完成一个任务"带崩）
    assert vault.try_export(conn, DAY, str(vaultdir), default_vault_dir=str(vaultdir)) is None
    assert "Vault" in vault.status(conn, str(vaultdir))["last_error"]


def test_set_dir_outside_the_vault_is_fine(conn, vaultdir, tmp_path) -> None:
    """Vault **外面**的目录照常（红线只拦"写进库里"，不是"不许同时用 Obsidian"）。"""
    vault.set_vault(conn, "MyVault", str(vaultdir))
    body = vault.set_dir(
        conn, str(tmp_path / "out"), "export", default_vault_dir=str(vaultdir)
    )
    assert body["configured"] is True and body["vault_overlap"] == ""
    assert vault.export_day(conn, DAY, str(tmp_path / "out"), default_vault_dir=str(vaultdir))


# ---------------------------------------------------------------- 设置（三层默认 + 校验）


def test_vault_settings_are_three_layered(conn, vaultdir, tmp_path) -> None:
    """本机设置 → config → 空：本机没设就用配置里的。"""
    assert vault.resolve_vault_name(conn) == ""
    assert vault.resolve_vault_name(conn, "ConfigVault") == "ConfigVault"
    vault.set_vault(conn, "MyVault", str(vaultdir))
    assert vault.resolve_vault_name(conn, "ConfigVault") == "MyVault"
    assert vault.resolve_vault_dir(conn) == vaultdir


def test_set_vault_rejects_a_dir_that_is_not_there(conn, tmp_path) -> None:
    """根目录必须真实存在 —— **软件不会替你在 Vault 里建目录**（那本身就是动知识资产库）。"""
    missing = tmp_path / "不存在"
    with pytest.raises(ValueError, match="不存在"):
        vault.set_vault(conn, "MyVault", str(missing))
    assert not missing.exists()
    assert vault.resolve_vault_name(conn) == ""       # 校验不过 → 什么都没落

    blocker = tmp_path / "blocker"
    blocker.write_text("我是文件", encoding="utf-8")
    with pytest.raises(ValueError, match="不是一个目录"):
        vault.set_vault(conn, "MyVault", str(blocker))


def test_empty_name_turns_the_jump_off(conn, vaultdir) -> None:
    vault.set_vault(conn, "MyVault", str(vaultdir))
    body = vault.set_vault(conn, "", "")
    assert body["vault_configured"] is False
    assert vault.link(conn, HANDLE)["url"] == ""


def test_describe_reports_overlap_that_came_from_the_config(conn, vaultdir) -> None:
    """配置里就重叠（不是从界面设的）→ **报出告警**（界面标红），而不是装作没事。"""
    body = vault.describe(conn, str(vaultdir / "notes"), default_vault_dir=str(vaultdir))
    assert "在 Vault 里面" in str(body["vault_overlap"])
    assert body["vault_dir"] == str(vaultdir)


def test_describe_states_the_read_only_note(conn) -> None:
    """「只读跳转」这句口径写在**界面数据**里（不只是代码注释）。"""
    body = vault.describe(conn, "export")
    assert "只读跳转" in str(body["vault_note"])
    assert "不往 Vault 里写任何东西" in str(body["vault_note"])
    assert "不写进 Obsidian 的笔记目录" in str(body["where"])


# ---------------------------------------------------------------- API


def test_api_vault_settings_and_open(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """`PUT /api/settings/vault`（非法 400）+ `POST /api/vault/open`（**不真开 Obsidian**）。"""
    client = _client(tmp_path)
    root = tmp_path / "MyVault"
    root.mkdir()

    body = client.put(
        "/api/settings/vault", json={"vault": "MyVault", "vault_dir": str(root)}
    ).json()
    assert body["vault_configured"] is True and body["vault"] == "MyVault"

    bad = client.put("/api/settings/vault", json={"vault": "V", "vault_dir": str(tmp_path / "x")})
    assert bad.status_code == 400 and "不存在" in bad.json()["detail"]

    # 把"交给系统打开"换掉：**测试绝不弹用户的 Obsidian**（真实链路由真机自检兜）
    launched: list[str] = []

    def fake_start(url: str) -> tuple[bool, str]:
        launched.append(url)
        return True, "已在 Obsidian 打开"

    monkeypatch.setattr(vault, "_start", fake_start)
    opened = client.post("/api/vault/open", json={"handle": HANDLE}).json()
    assert opened["url"] == f"obsidian://open?vault=MyVault&file={HANDLE_ENCODED}"
    assert opened["executed"] is True and launched == [opened["url"]]


def test_api_open_can_report_failure(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """调不起来时接口照样 200，但 `ok=false` + 原话（界面退回"复制链接 + 提示"）。"""
    client = _client(tmp_path, "failopen.db")
    client.put("/api/settings/vault", json={"vault": "MyVault"})
    monkeypatch.setattr(vault, "_start", lambda url: (False, "调不起 Obsidian（拒绝访问）"))
    body = client.post("/api/vault/open", json={"handle": HANDLE}).json()
    assert body["ok"] is False and "调不起 Obsidian" in body["reason"]


def test_api_open_without_vault_explains(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = _client(tmp_path, "novault.db")
    body = client.post("/api/vault/open", json={"handle": HANDLE}).json()
    assert body["ok"] is False and body["executed"] is False
    assert "Vault 名字" in body["reason"]


def test_api_cards_carry_a_jump_link(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """复习卡与备忘录**带出** `ref_url`（界面据此摆「在 Obsidian 打开」按钮）；没配就没有。"""
    client = _client(tmp_path, "cards.db")
    card = client.post(
        "/api/review/items", json={"title": "一张卡", "ref_handle": HANDLE}
    ).json()
    memo = client.post("/api/memos", json={"text": "一条备忘", "ref_handle": HANDLE}).json()

    due = [c for c in client.get("/api/review/due").json() if c["id"] == card["id"]]
    assert due and due[0]["ref_url"] == ""           # 还没配 Vault → 不给链接
    assert "Vault 名字" in due[0]["ref_reason"]
    assert client.get("/api/memos").json()[0]["ref_url"] == ""
    assert client.get(f"/api/review/items/{card['id']}").json()["ref_url"] == ""

    client.put("/api/settings/vault", json={"vault": "MyVault"})
    due = [c for c in client.get("/api/review/due").json() if c["id"] == card["id"]]
    expected = f"obsidian://open?vault=MyVault&file={HANDLE_ENCODED}"
    assert due[0]["ref_url"] == expected
    assert client.get("/api/memos").json()[0]["ref_url"] == expected
    assert client.get(f"/api/review/items/{card['id']}").json()["ref_url"] == expected
    assert memo["id"]


def test_api_export_dir_inside_vault_is_rejected(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """红线在**接口上**也是 400（不是只有领域函数拦得住）。"""
    client = _client(tmp_path, "redline.db")
    root = tmp_path / "MyVault"
    (root / "notes").mkdir(parents=True)
    client.put("/api/settings/vault", json={"vault": "MyVault", "vault_dir": str(root)})

    resp = client.put("/api/settings/export", json={"dir": str(root / "notes")})
    assert resp.status_code == 400 and "Vault" in resp.json()["detail"]
    assert client.get("/api/settings/export").json()["configured"] is False
