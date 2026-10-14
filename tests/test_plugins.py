r"""插件注册路径判据（卡 229 / T-G346）：装 / 卸 / 坏插件 / 不改核心，全部真读数。

对应卡规格「判据」节，四类：

- **装**：样例插件（`examples/05_plugin_demo/plugin.py`）装上 ⇒ 新路由
  `/api/plugins/reading/today` 真的能调（贴真读数），新口径 `reading.counts_today`
  真的出现在 `/api/settings/behavior`（与核心口径**同一张表**，可切、可影子）；
  装配是声明式的：同一份输入两次装配，报告**逐字节相同**。
- **卸**：卸下 ⇒ 一切回到原样（路由 404、口径表逐字节还原、模块缓存清空）。
- **反例①（先红后绿）**：插件写坏（导入即炸 / 语法错）⇒ 旧世界是"起服务就炸"
  （子进程真红读数）；新路径把它原样报进报告与 `/api/plugins`，服务本体照常健康。
- **反例②（先红后绿）**：「不改核心」机器证明 —— 装配 + 卸载全程 `src/timeflow/**`
  逐文件 SHA256 不变；并拿"改一个字符哈希必变"证明这把尺子不是空转；
  「只改注册那一处」也钉成判据（src 里 import 插件包的只有 `api/app.py`）。

跑法：`python -X utf8 -m pytest tests/test_plugins.py --no-cov -q`
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core import behavior, facts
from timeflow.plugins import ENV_KEY, STATUS_ROUTE, add_rule, apply, uninstall
from timeflow.storage import db as db_mod

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "examples" / "05_plugin_demo" / "plugin.py"
PLUGIN_ROUTE = "/api/plugins/reading/today"
RULE_KEY = "reading.counts_today"
CORE_KEY = behavior.KEY_DEBT_UNDATED_MYDAY
#: 起子进程带 NO_WINDOW（本仓口径，见 tools/pool/no_window.py）
NO_WINDOW = {"creationflags": 0x08000000} if os.name == "nt" else {}


def _dumps(body: Any) -> str:
    """报告序列化成字节串：两次装配"逐字节相同"就比它。"""
    return json.dumps(body, sort_keys=True, ensure_ascii=False)


def _seed_reading(conn: Any, minutes: int = 35, title: str = "《深度工作》") -> None:
    """记一条阅读事实（facts 只读层允许插件补记，口径见 examples/01）。"""
    facts.record(
        conn,
        kind="reading.logged",
        subject_type="book",
        subject_id="book-1",
        value_num=minutes,
        value_text=title,
        extra={"minutes": minutes, "book": title},
        source="desktop",
    )


def _rule_item(client: TestClient, key: str) -> dict[str, Any]:
    items = client.get("/api/settings/behavior").json()["items"]
    return next(i for i in items if i["key"] == key)


# ---------------------------------------------------------------- 装：新路由 + 新读数都是真的


def test_sample_plugin_declares_both_hooks() -> None:
    """样例插件必须同时声明两个扩展点的钩子（卡规格点名的两条真需求）。"""
    src = PLUGIN.read_text(encoding="utf-8")
    assert "def register_routes(" in src, "缺扩展点①（加 API 路由）"
    assert "def register_rules(" in src, "缺扩展点②（加口径）"


def test_install_makes_new_route_and_new_rule_real(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """装上 ⇒ 新路由真的可调（真读数）+ 新口径真的进 behavior 那张表（同列、可切、可影子）。"""
    monkeypatch.setenv(ENV_KEY, str(PLUGIN))
    app = create_app(str(tmp_path / "p1.db"))  # ★ 走的就是生产装配路径（create_app）
    client = TestClient(app)
    conn = db_mod.connect(str(tmp_path / "p1.db"))
    try:
        # 状态墙：装了什么、有没有坏 —— 先看得见
        status = client.get(STATUS_ROUTE).json()
        assert status["errors"] == []
        assert [Path(p).resolve() for p in status["loaded"]] == [PLUGIN.resolve()]
        assert status["routes"] == [PLUGIN_ROUTE]
        assert status["rules"] == [RULE_KEY]

        # ① 新路由真的可调：记 35 分钟 → 读回 35（真读数）
        _seed_reading(conn)
        got = client.get(PLUGIN_ROUTE).json()
        assert got == {"kind": "reading.logged", "entries": 1, "minutes": 35}, got

        # ② 新口径真的出现，且与核心口径**同一张表**（同列，不是第二张表）
        assert RULE_KEY in {r.key for r in behavior.RULES}
        assert behavior.rule_by_key(RULE_KEY) is not None  # 既有取表函数认得它
        item = _rule_item(client, RULE_KEY)
        assert item["is_default"] is True and item["current"] == "count"
        assert [v["id"] for v in item["variants"]] == ["count", "skip"]

        # 影子对比真的能跑（插件的 compare 被 core 那张表调到）
        shadow = item["shadow"]
        assert shadow["available"] is True and shadow["diff_count"] == 1
        assert shadow["samples"] == [{
            "label": "「《深度工作》」35 分钟", "current": "算 1 份产出", "shadow": "不算产出",
        }], shadow["samples"]

        # 切换也走既有路由（插件口径是一等公民，可一键回）
        switched = client.put(
            "/api/settings/behavior", json={"key": RULE_KEY, "variant": "skip"}
        ).json()
        assert next(i for i in switched["items"] if i["key"] == RULE_KEY)["current"] == "skip"
        back = client.post("/api/settings/behavior/reset", json={"key": RULE_KEY}).json()
        assert next(i for i in back["items"] if i["key"] == RULE_KEY)["is_default"] is True
    finally:
        uninstall(app)
        conn.close()


# ---------------------------------------------------------------- 卸：一切回到原样（逐字节）


def test_uninstall_restores_everything_and_reapply_is_byte_identical(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """卸下 ⇒ 路由 404、口径表逐字节还原；同一份输入第二次装配 ⇒ 报告逐字节相同。"""
    baseline_client = TestClient(create_app(str(tmp_path / "base.db")))  # 从没装过插件的样子
    baseline = _dumps(baseline_client.get("/api/settings/behavior").json())

    db_path = str(tmp_path / "p2.db")
    monkeypatch.setenv(ENV_KEY, str(PLUGIN))
    app = create_app(db_path)  # 第 1 次装配
    client = TestClient(app)
    applied = _dumps(client.get("/api/settings/behavior").json())
    assert client.get(PLUGIN_ROUTE).status_code == 200

    uninstall(app)  # 卸载
    assert client.get(PLUGIN_ROUTE).status_code == 404
    assert _dumps(client.get("/api/settings/behavior").json()) == baseline  # ★ 逐字节还原
    st = client.get(STATUS_ROUTE).json()
    assert st["loaded"] == [] and st["errors"] == [] and st["rules"] == []

    conn = db_mod.connect(db_path)
    try:
        apply(app, conn, [str(PLUGIN)])  # 第 2 次装配（同一份输入）
        assert client.get(PLUGIN_ROUTE).status_code == 200
        assert _dumps(client.get("/api/settings/behavior").json()) == applied  # ★ 逐字节相同
    finally:
        uninstall(app)
        conn.close()


def test_double_apply_does_not_duplicate(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """同一个 app 重复装配（声明式：先卸干净再装）⇒ 路由不翻倍、报告不重复。"""
    monkeypatch.setenv(ENV_KEY, str(PLUGIN))
    app = create_app(str(tmp_path / "p3.db"))
    conn = db_mod.connect(str(tmp_path / "p3.db"))
    try:
        report = apply(app, conn, [str(PLUGIN)])
        assert report["errors"] == [] and report["loaded"]
        hits = [r for r in app.routes if getattr(r, "path", "") == PLUGIN_ROUTE]
        assert len(hits) == 1, hits
        assert TestClient(app).get(PLUGIN_ROUTE).status_code == 200
    finally:
        uninstall(app)
        conn.close()


# ------------------------------------------------ 反例①：坏插件必须看得见（先红后绿）


def test_broken_plugin_is_reported_not_swallowed(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """导入即炸的插件：旧世界"起服务就炸"（真红）；新路径原样报出，服务照常健康（绿）。"""
    broken = tmp_path / "broken_plugin.py"
    broken.write_text("import no_such_module_xyz_229\n", encoding="utf-8")

    # 先红：旧世界（没有注册路径时你只能 import 它）—— 子进程真读数：启动即炸
    red = subprocess.run(  # noqa: S603
        [sys.executable, "-X", "utf8", str(broken)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120, check=False, **NO_WINDOW,
    )
    assert red.returncode != 0, red.stdout
    assert "no_such_module_xyz_229" in red.stderr, red.stderr[-800:]

    # 后绿：走注册路径 —— 坏插件原样报出来（阶段 import + 原话），服务本体不受牵连
    app = create_app(str(tmp_path / "p4.db"))
    client = TestClient(app)
    conn = db_mod.connect(str(tmp_path / "p4.db"))
    try:
        report = apply(app, conn, [str(broken)])
        assert report["loaded"] == []
        assert len(report["errors"]) == 1, report["errors"]
        err = report["errors"][0]
        assert err["plugin"] == str(broken) and err["stage"] == "import", err
        assert "no_such_module_xyz_229" in err["detail"], err

        # 状态墙上也能看到（不静默吞），且服务照常健康
        assert client.get(STATUS_ROUTE).json()["errors"] == report["errors"]
        assert client.get("/api/health").json()["status"] == "ok"
        # 坏插件一个钩子都没留下
        assert client.get(PLUGIN_ROUTE).status_code == 404
        keys = [i["key"] for i in client.get("/api/settings/behavior").json()["items"]]
        assert keys == [CORE_KEY]

        # 语法错也一样：报 stage=import，不静默、不牵连
        ugly = tmp_path / "ugly_plugin.py"
        ugly.write_text("def _broken(:\n", encoding="utf-8")
        report2 = apply(app, conn, [str(ugly)])
        assert report2["loaded"] == [] and report2["errors"][0]["stage"] == "import"
        assert "SyntaxError" in report2["errors"][0]["detail"], report2["errors"]
        assert client.get("/api/health").json()["status"] == "ok"
    finally:
        uninstall(app)
        conn.close()


def test_hook_failure_and_route_clash_are_visible(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """钩子抛错 / 路由撞已有接口：拆干净 + 报出来（不许遮挡老行为，也不许静默）。"""
    app = create_app(str(tmp_path / "p5.db"))
    client = TestClient(app)
    conn = db_mod.connect(str(tmp_path / "p5.db"))
    try:
        clash = tmp_path / "clash_plugin.py"
        clash.write_text(
            "def register_routes(app, conn):\n"
            "    @app.get('/api/health')\n"
            "    def fake_health():\n"
            "        return {}\n",
            encoding="utf-8",
        )
        report = apply(app, conn, [str(clash)])
        assert report["loaded"] == []
        assert report["errors"][0]["stage"] == "routes"
        assert "撞了已有接口" in report["errors"][0]["detail"], report["errors"]
        assert client.get("/api/health").json()["status"] == "ok"  # 老接口原样

        angry = tmp_path / "angry_plugin.py"
        angry.write_text(
            "def register_rules(add_rule):\n"
            "    raise RuntimeError('注册到一半炸了')\n",
            encoding="utf-8",
        )
        report2 = apply(app, conn, [str(angry)])
        assert report2["errors"][0]["stage"] == "rules"
        assert "注册到一半炸了" in report2["errors"][0]["detail"]
        assert client.get("/api/health").json()["status"] == "ok"
    finally:
        uninstall(app)
        conn.close()


# ---------------------------------------------------------------- 反例②：「不改核心」机器证明


def _snapshot_src() -> dict[str, str]:
    """`src/timeflow/**.py` 逐文件 SHA256（装配/卸载前后对比的尺子）。"""
    return {
        p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((ROOT / "src").rglob("*.py"))
    }


def test_assembly_touches_no_core_file(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """装配 + 卸载全程，核心文件逐字节不动（SHA256 全等）—— 口号做成判据。"""
    before = _snapshot_src()
    monkeypatch.setenv(ENV_KEY, str(PLUGIN))
    app = create_app(str(tmp_path / "p6.db"))
    conn = db_mod.connect(str(tmp_path / "p6.db"))
    try:
        client = TestClient(app)
        _seed_reading(conn)
        assert client.get(PLUGIN_ROUTE).status_code == 200  # 装上：真的在跑插件
        client.put("/api/settings/behavior", json={"key": RULE_KEY, "variant": "skip"})
        uninstall(app)
    finally:
        conn.close()
    after = _snapshot_src()
    assert after == before, (
        "装配/卸载改动了核心文件："
        + str([k for k in after if after[k] != before.get(k)])
    )
    # 尺子不是空转：同样的哈希函数对"改一个字符"必报差异（临时副本上验，不碰真文件）
    probe = tmp_path / "probe.py"
    probe.write_text("x = 1\n", encoding="utf-8")
    h1 = hashlib.sha256(probe.read_bytes()).hexdigest()
    probe.write_text("x = 2\n", encoding="utf-8")
    assert hashlib.sha256(probe.read_bytes()).hexdigest() != h1


def test_core_contact_is_only_the_registration_spot() -> None:
    """「只改注册那一处」也钉成判据：src/timeflow 里碰插件包的只有 api/app.py（白名单）。"""
    hits = []
    for p in sorted((ROOT / "src" / "timeflow").rglob("*.py")):
        text = p.read_text(encoding="utf-8")
        if "plugins.apply" in text or re.search(r"from timeflow import [^\n]*plugins", text):
            hits.append(p.relative_to(ROOT).as_posix())
    assert hits == ["src/timeflow/api/app.py"], hits


# ---------------------------------------------------------------- 口径护栏与核心同款


def test_rules_share_the_one_registry_with_core_guards() -> None:
    """插件口径进的就是 behavior 那张表：护栏同款（非 derived / 撞 key → 当场炸），卸载即还原。"""
    bad_kind = behavior.Rule(
        key="reading.bad_kind", title="坏口径", question="q",
        variants=(behavior.Variant("a", "a"), behavior.Variant("b", "b")),
        default="a", kind="irreversible",
    )
    with pytest.raises(ValueError, match="派生"):
        add_rule(bad_kind)

    dup = behavior.Rule(
        key=CORE_KEY, title="撞核心", question="q",
        variants=(behavior.Variant("a", "a"), behavior.Variant("b", "b")), default="a",
    )
    with pytest.raises(ValueError, match="撞了已有的"):
        add_rule(dup)

    bad_default = behavior.Rule(
        key="reading.bad_default", title="默认位不合法", question="q",
        variants=(behavior.Variant("a", "a"), behavior.Variant("b", "b")), default="c",
    )
    with pytest.raises(ValueError, match="默认位"):
        add_rule(bad_default)

    # 护栏拦下的三条一条都没进表
    assert [r.key for r in behavior.RULES] == [CORE_KEY]


def test_plugin_rule_removed_on_uninstall_restores_legacy_error(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """卸载后：插件口径从表里消失，既有的「没有这条口径」原话照旧（不是静默残留）。"""
    monkeypatch.setenv(ENV_KEY, str(PLUGIN))
    app = create_app(str(tmp_path / "p7.db"))
    conn = db_mod.connect(str(tmp_path / "p7.db"))
    try:
        assert RULE_KEY in {r.key for r in behavior.RULES}
        client = TestClient(app)
        assert _rule_item(client, RULE_KEY)["key"] == RULE_KEY
    finally:
        uninstall(app)
        conn.close()
    assert [r.key for r in behavior.RULES] == [CORE_KEY]
    with pytest.raises(ValueError, match="没有这条口径"):
        behavior.rule_by_key(RULE_KEY)
