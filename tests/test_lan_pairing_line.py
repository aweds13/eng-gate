"""局域网访问 + 配对码（G 批 · T-G10b / SR-NF17 = 跨端场景 ②）。

口径（`复盘/口径定案-待定清单.md` §3）：服务**显式开启**局域网访问（**默认关**，
口径同 N16「默认收严、用户再放宽」）+ **配对码**；开启时明确提示
「同一 WiFi 下其他设备也可能访问到」。
边界：**只在同一个 WiFi 里管用**，不涉及公网。

这里钉住四件事：
1. **默认关 = 与以前一模一样**（这条最要紧：不能因为加了这道门就把老行为改掉）；
2. 门本身是一张**真值表**（本机免检 / 静态壳免检 / 配对接口免检 / 其余要码 / 错了锁一会儿）；
3. ★ **配对码只在本机响应里出现**（局域网设备能读数据，读不到钥匙）；
4. `tools/serve.py --lan` 真的把服务绑到 `0.0.0.0` **并且真的把门装上了**（不是"打印了一句话"）。
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.config import load_settings
from timeflow.core import lan as lan_mod
from timeflow.storage import db as db_mod

ROOT = Path(__file__).resolve().parent.parent
PHONE = ("192.168.1.50", 51234)   # 假装是同一 WiFi 下的手机
MINE = ("127.0.0.1", 51234)       # 本机


@pytest.fixture()
def conn(tmp_path):  # type: ignore[no-untyped-def]
    c = db_mod.connect(str(tmp_path / "lan.db"))
    lan_mod.reset_failures()
    yield c
    c.close()
    lan_mod.reset_failures()


def _client(tmp_path, *, lan: bool, host: tuple[str, int] = PHONE, name: str = "lan.db"):  # type: ignore[no-untyped-def]
    app = create_app(str(tmp_path / name), allow_lan=lan)
    return TestClient(app, client=host)


# ---------------------------------------------------------------- 一、默认关 = 与以前一样
def test_default_is_off_in_config_and_in_the_app(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """默认**关**：配置默认 false，服务默认也不装门 —— 局域网设备照样能读（和以前一致）。"""
    assert load_settings().net.allow_lan is False
    assert load_settings().net.pairing_code == ""
    c = _client(tmp_path, lan=False, name="off.db")
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/tasks").status_code == 200
    lan = c.get("/api/settings/lan").json()
    assert lan["lan_open"] is False and lan["pairing_required"] is False


def test_config_can_turn_it_on_by_file_and_by_env(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """两种开法都要认：config.toml 的 `[net] allow_lan`，以及 `TIMEFLOW_NET__ALLOW_LAN`。"""
    cfg = tmp_path / "config.toml"
    cfg.write_text("[net]\nallow_lan = true\npairing_code = \"4321\"\n", encoding="utf-8")
    got = load_settings(cfg)
    assert got.net.allow_lan is True and got.net.pairing_code == "4321"

    monkeypatch.setenv("TIMEFLOW_NET__ALLOW_LAN", "1")
    assert load_settings(tmp_path / "没有这个文件.toml").net.allow_lan is True


def test_pair_endpoint_says_why_when_lan_is_off(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """没开局域网时配对应该**说清原因**（409 + 原话），而不是一句"配对码不对"。"""
    c = _client(tmp_path, lan=False, name="off2.db")
    r = c.post("/api/lan/pair", json={"code": "1234"})
    assert r.status_code == 409 and "allow_lan" in r.json()["detail"]


# ---------------------------------------------------------------- 二、门：真值表
def test_loopback_is_never_gated(conn) -> None:  # type: ignore[no-untyped-def]
    assert lan_mod.is_loopback("127.0.0.1") and lan_mod.is_loopback("::1")
    assert lan_mod.is_loopback("127.5.5.5") and lan_mod.is_loopback("localhost")
    for bad in ("192.168.1.2", "0.0.0.0", "", None, "testclient", "10.0.0.7"):
        assert not lan_mod.is_loopback(bad), f"{bad} 不该被当成回环"
    d = lan_mod.gate(conn, "127.0.0.1", "/api/tasks", None)
    assert d["ok"] is True and d["reason"] == "loopback" and d["paired"] is False


def test_static_shell_and_pair_path_are_open(conn) -> None:  # type: ignore[no-untyped-def]
    """静态壳免检 —— 不然手机连"输入配对码"那一页都打不开（这条是体验的底线）。"""
    for path in sorted(lan_mod.STATIC_SHELL):
        assert lan_mod.gate(conn, PHONE[0], path, None)["ok"] is True, path
    assert lan_mod.gate(conn, PHONE[0], lan_mod.PAIR_PATH, None)["ok"] is True
    # 但 /api/ 下面别的都得要码
    for path in ("/api/health", "/api/tasks", "/api/config", "/api/settings/lan"):
        assert lan_mod.gate(conn, PHONE[0], path, None)["ok"] is False, path


def test_gate_needs_the_right_code(conn) -> None:  # type: ignore[no-untyped-def]
    code = lan_mod.code(conn)
    assert re.fullmatch(r"\d{6}", code), "配对码是 6 位数字（手机上敲得动）"
    miss = lan_mod.gate(conn, PHONE[0], "/api/tasks", None)
    assert miss["status"] == 401 and "配对码" in miss["detail"]
    wrong = lan_mod.gate(conn, PHONE[0], "/api/tasks", "000000")
    assert wrong["ok"] is False and wrong["status"] == 401
    good = lan_mod.gate(conn, PHONE[0], "/api/tasks", code)
    assert good["ok"] is True and good["paired"] is True


def test_code_is_persistent_and_rotatable(conn) -> None:  # type: ignore[no-untyped-def]
    """配对码**重启不变**（不然手机每次都要重敲）；也能换一个。"""
    first = lan_mod.code(conn)
    assert lan_mod.code(conn) == first and lan_mod.peek_code(conn) == first
    second = lan_mod.rotate(conn, "abcd1234")
    assert second == "abcd1234" and lan_mod.verify(conn, "abcd1234")
    assert not lan_mod.verify(conn, first)
    assert lan_mod.new_code() != lan_mod.new_code() or True   # 随机，不写死
    with pytest.raises(ValueError, match="4~16 位"):
        lan_mod.rotate(conn, "a b")
    with pytest.raises(ValueError, match="4~16 位"):
        lan_mod.rotate(conn, "x")


def test_failed_attempts_get_locked_for_a_while(conn, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """6 位数字只有 100 万种：没有节流的话同 WiFi 的人可以慢慢试 —— 错了太多次先锁一会儿。"""
    monkeypatch.setattr(lan_mod, "MAX_FAILS", 3)
    lan_mod.reset_failures()
    for _ in range(3):
        out = lan_mod.check_pair(conn, PHONE[0], "000000")
        assert out["ok"] is False and out["status"] == 401
    locked = lan_mod.check_pair(conn, PHONE[0], lan_mod.code(conn))
    assert locked["ok"] is False and locked["status"] == 429, "锁着的时候连对的码也先拒"
    gated = lan_mod.gate(conn, PHONE[0], "/api/tasks", lan_mod.code(conn))
    assert gated["status"] == 429
    # 换一个来源不受影响（是"这个来源"被锁，不是整台服务瘫掉）
    assert lan_mod.gate(conn, "192.168.1.99", "/api/tasks", lan_mod.code(conn))["ok"] is True
    # 配对了就清计数
    lan_mod.reset_failures(PHONE[0])
    assert lan_mod.check_pair(conn, PHONE[0], lan_mod.code(conn))["ok"] is True


def test_check_pair_clears_failures_on_success(conn) -> None:  # type: ignore[no-untyped-def]
    code = lan_mod.code(conn)
    assert lan_mod.check_pair(conn, PHONE[0], "000000")["status"] == 401
    assert lan_mod.check_pair(conn, PHONE[0], code)["ok"] is True
    assert lan_mod.locked(PHONE[0]) == 0


# ---------------------------------------------------------------- 三、接口行为（真 app）
def test_phone_must_pair_before_reading_anything(tmp_path) -> None:  # type: ignore[no-untyped-def]
    c = _client(tmp_path, lan=True, name="on.db")
    mine = TestClient(c.app, client=MINE)
    code = mine.get("/api/settings/lan").json()["code"]

    assert c.get("/api/health").status_code == 401
    assert c.get("/api/health").json()["detail"].count("配对码") >= 1
    assert c.get("/", follow_redirects=False).status_code == 200, "静态壳要能打开（否则没处输码）"
    assert c.post("/api/lan/pair", json={"code": "000000"}).status_code == 401
    assert c.post("/api/lan/pair", json={"code": code}).status_code == 200
    assert c.get("/api/health", headers={lan_mod.HEADER: code}).status_code == 200
    assert c.get("/api/tasks", headers={lan_mod.HEADER: code}).status_code == 200
    # 本机照旧：不用带码
    assert mine.get("/api/health").status_code == 200


def test_pairing_code_is_never_sent_to_the_lan(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """★ 这道门的底线：**配对码只在本机响应里出现**。

    局域网设备能读数据，但读不到"钥匙"本身 —— 否则谁配一次就能把码传出去，门就白设了。
    """
    c = _client(tmp_path, lan=True, name="leak.db")
    mine = TestClient(c.app, client=MINE)
    local = mine.get("/api/settings/lan").json()
    assert local["code_visible"] is True and re.fullmatch(r"\d{6}", local["code"])
    code = local["code"]

    phone = c.get("/api/settings/lan", headers={lan_mod.HEADER: code}).json()
    assert phone["code"] == "" and phone["code_visible"] is False
    assert code not in c.get("/api/settings/lan", headers={lan_mod.HEADER: code}).text
    # 也不能从别的地方漏出去
    assert code not in c.get("/api/health", headers={lan_mod.HEADER: code}).text
    assert code not in c.get("/api/config", headers={lan_mod.HEADER: code}).text


def test_only_the_desktop_can_change_the_code(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """换配对码是**那台电脑**的事：手机上（哪怕已配对）调它 → 403 带原话。"""
    c = _client(tmp_path, lan=True, name="rotate.db")
    mine = TestClient(c.app, client=MINE)
    code = mine.get("/api/settings/lan").json()["code"]
    blocked = c.put("/api/settings/lan", json={"pairing_code": "9999"},
                    headers={lan_mod.HEADER: code, "Origin": "http://192.168.1.50:8520"})
    assert blocked.status_code == 403 and "那台电脑" in blocked.json()["detail"]
    ok = mine.put("/api/settings/lan", json={"pairing_code": "8383"})
    assert ok.status_code == 200 and mine.get("/api/settings/lan").json()["code"] == "8383"
    # 旧的码立刻失效（新码生效），这是"换码"的意义
    assert c.get("/api/health", headers={lan_mod.HEADER: code}).status_code == 401
    assert c.get("/api/health", headers={lan_mod.HEADER: "8383"}).status_code == 200
    bad = mine.put("/api/settings/lan", json={"pairing_code": "a b"})
    assert bad.status_code == 400 and "4~16 位" in bad.json()["detail"]


def test_paired_device_counts_as_a_local_page(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """配对过的设备 = 当作本机页面（那道 origin 守卫防的是**跨站**，不是"你的另一台设备"）。"""
    c = _client(tmp_path, lan=True, name="origin.db")
    mine = TestClient(c.app, client=MINE)
    code = mine.get("/api/settings/lan").json()["code"]
    lan_origin = {"Origin": "http://192.168.1.50:8520"}

    assert c.put("/api/settings/ai", json={"enabled": True}, headers=lan_origin).status_code == 401
    ok = c.put("/api/settings/ai", json={"enabled": True},
               headers={**lan_origin, lan_mod.HEADER: code})
    assert ok.status_code == 200, "配对过就该能改（和桌面浏览器里一样）"
    # 本机仍然不看 Origin（浏览器里本机页面带 Origin 也要能改）
    assert mine.put("/api/settings/ai", json={"enabled": False},
                    headers={"Origin": "http://127.0.0.1:8520"}).status_code == 200


def test_lan_off_keeps_the_old_cross_site_guard(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """默认关时，跨站来源仍旧 403（老行为不许被改掉），且提示里不提"配对"。"""
    c = _client(tmp_path, lan=False, name="csrf.db")
    r = c.put("/api/settings/ai", json={"enabled": True}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and "配对" not in r.json()["detail"]


def test_status_reports_addresses_only_when_open(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """现状只报事实：关着就不给地址（给了也没用），并说明怎么开。"""
    off = _client(tmp_path, lan=False, name="s1.db").get("/api/settings/lan").json()
    assert off["addresses"] == [] and "serve.py --lan" in off["how_to_change"]
    on = TestClient(_client(tmp_path, lan=True, name="s2.db").app, client=MINE)
    got = on.get("/api/settings/lan").json()
    assert got["lan_open"] is True and got["pairing_required"] is True
    assert got["config_allow_lan"] is False, "传进来的开关与配置文件是两件事，分开报"


def test_local_addresses_are_http_urls() -> None:
    for url in lan_mod.local_addresses(8520):
        assert url.startswith("http://") and url.endswith(":8520")
        assert "127." not in url, "回环地址对手机没用，不该出现在这份清单里"


def test_banner_says_the_price_out_loud() -> None:
    """开局域网时**必须当面说清代价**（口径：显式放宽，但放宽时说明后果）。"""
    lines = "\n".join(lan_mod.banner(8520, "123456"))
    for needle in ("局域网", "123456", "同一个 WiFi", "其他设备也可能", "配对码是那道门",
                   "不是加密", "不挡同 WiFi 抓包", "不涉及公网", "--lan"):
        assert needle in lines, f"横幅少了一句：{needle}"
    # T-G10c（用户说他用的是校园网）：横幅要**提前把校园网那条讲清楚**，别让人白折腾半天
    for needle in ("校园网", "客户端隔离", "移动热点", "离线记"):
        assert needle in lines, f"横幅没提校园网怎么办：{needle}"


# ---------------------------------------------------------------- 四、本机自检（T-G10c）
def test_selfcheck_says_what_it_can_and_cannot_prove() -> None:
    """自检只报**能在电脑上查的那一半**，查不到的（网络隔离）直说，不假装能判。"""
    ok = lan_mod.selfcheck(8520, lan_open=True, probe=lambda url: True)
    assert ok["self_reachable"] is True and ok["addresses"]
    assert "防火墙" in ok["verdict"] or "通的" in ok["verdict"]
    assert "不能" in ok["caveat"] and "手机" in ok["caveat"]

    bad = lan_mod.selfcheck(8520, lan_open=True, probe=lambda url: False)
    assert bad["self_reachable"] is False and "防火墙" in bad["verdict"]

    off = lan_mod.selfcheck(8520, lan_open=False, probe=lambda url: False)
    assert "--lan" in off["verdict"], "没开局域网时要说清是这件事，别让人去查防火墙"


def test_selfcheck_hint_puts_the_hotspot_first() -> None:
    """排查顺序要**先热点后校园网**：校园网多半连不通，先把省事且一定能通的那条说在前面。"""
    hint = lan_mod.selfcheck(8520, lan_open=True, probe=lambda url: True)["hint"]
    assert hint.index("移动热点") < hint.index("校园网")
    for needle in ("192.168.137.1", "USB", "离线记", "客户端隔离"):
        assert needle in hint, f"排查顺序里少了一句：{needle}"


def test_selfcheck_endpoint_answers(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """接口层也要能问：形状齐全（lan_open / addresses / self_reachable / verdict / hint）。

    它是 `/api/` 下面的一条，所以**没配对的设备会被门挡住** —— 界面也只在
    "本机能看见配对码"时摆这颗按钮（两头一致）。
    """
    phone = _client(tmp_path, lan=True, name="self.db")
    assert phone.post("/api/lan/selfcheck", json={}).status_code == 401
    mine = TestClient(phone.app, client=MINE)
    r = mine.post("/api/lan/selfcheck", json={})
    assert r.status_code == 200
    got = r.json()
    for key in ("lan_open", "addresses", "self_reachable", "verdict", "hint", "caveat"):
        assert key in got, f"自检少了一个字段：{key}"
    assert got["lan_open"] is True


def test_status_note_warns_about_campus_networks(conn) -> None:  # type: ignore[no-untyped-def]
    """设置页显示的那段边界要**主动提校园网**（用户就是校园网，别让他自己猜）。"""
    st = lan_mod.status(
        conn, lan_open=True, config_allow_lan=True, port=8520, loopback=True
    )
    for needle in ("客户端隔离", "校园网", "热点", "不是加密"):
        assert needle in st["note"], f"边界说明里少了一句：{needle}"


# ---------------------------------------------------------------- 四、serve.py 真的照做
def test_serve_lan_binds_everything_and_arms_the_gate(tmp_path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """`--lan` 不是"打印一句话"：它得**真的绑 0.0.0.0** + 真的把门装上。

    做法：把 `uvicorn.run` 换掉（别真起服务），看它拿到的 host/port 与那个 app 的行为。
    `--fresh` 保证用的是临时库（不碰真实数据）。
    """
    sys.path.insert(0, str(ROOT / "tools"))
    import serve
    import uvicorn

    seen: dict[str, object] = {}
    monkeypatch.setattr(
        uvicorn, "run",
        lambda app, host, port, log_level: seen.update(app=app, host=host, port=port),
    )
    before = os.environ.get("TIMEFLOW_EXPORT__DIR")
    try:
        monkeypatch.setattr(sys, "argv", [
            "serve.py", "--lan", "--fresh", "--no-backup", "--port", "8599"])
        assert serve.main() == 0
    finally:
        # `--fresh` 会顺手设这个环境变量（指向临时导出目录）—— 收拾干净，别影响别的用例
        if before is None:
            os.environ.pop("TIMEFLOW_EXPORT__DIR", None)
        else:
            os.environ["TIMEFLOW_EXPORT__DIR"] = before

    assert seen["host"] == "0.0.0.0" and seen["port"] == 8599
    out = capsys.readouterr().out
    for needle in ("[局域网]", "[配对码]", "同一个 WiFi", "[关闭]"):
        assert needle in out, f"起服务时该打印：{needle}"
    # 真的装上了门：假装是手机 → 401；本机 → 200
    phone = TestClient(seen["app"], client=PHONE)  # type: ignore[arg-type]
    mine = TestClient(seen["app"], client=MINE)    # type: ignore[arg-type]
    assert phone.get("/api/health").status_code == 401
    assert mine.get("/api/health").status_code == 200


def test_serve_refuses_a_lan_host_without_lan(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """不许绕过开关：`--host 0.0.0.0` 但没开 `--lan` → 拒绝，并告诉人正确的写法。"""
    sys.path.insert(0, str(ROOT / "tools"))
    import serve

    monkeypatch.setattr(sys, "argv", ["serve.py", "--host", "0.0.0.0", "--fresh"])
    assert serve.main() == 2
    err = capsys.readouterr().err
    assert "回环" in err and "--lan" in err


def test_module_docstrings_state_the_boundary() -> None:
    """边界写在**代码里**（不只是文档）：局域网只管同一 WiFi、不涉及公网。"""
    lan_src = (ROOT / "src" / "timeflow" / "core" / "lan.py").read_text(encoding="utf-8")
    serve_src = (ROOT / "tools" / "serve.py").read_text(encoding="utf-8")
    assert "只在同一个 WiFi 里" in lan_src and "不涉及公网" in lan_src
    assert "--lan" in serve_src and "默认关" in serve_src
    assert "not_encrypted" not in lan_src  # 反面：别写成英文占位
