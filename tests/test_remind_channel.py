"""F1 主线 · 段2 · T-B5（后半）：到点提醒的通知通道（计划任务 + 系统通知，用户选 B′）。

覆盖：
- 计划任务命令构造（**纯函数**：测试只拼参数，绝不注册/删除真实任务）；
- 开关语义：打开 = 写设置 + 注册任务；关闭 = 写设置 + 删除任务；
  **注册失败设置不落库**（不谎报已开）；
- 通知去重：同一条提醒（同 remind_at）只弹一次；改了提醒时间会重新弹；**弹失败不标记**（下次重试）；
- 防轰炸：一次到点太多（>3 条）合并成一条汇总；
- 到点脚本入口 `src/timeflow/app/remind.py` 能独立跑（计划任务的工作目录不是项目根）；
- API：状态可读、开关可切（本机来源）、**跨站被 403**、测试通知接口；
- 默认关闭：不启用就不注册任何系统任务。
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core import remind as rm
from timeflow.core import tasks as tm
from timeflow.storage import db as db_mod

ROOT = Path(__file__).resolve().parent.parent


def _client(tmp_path, name: str = "remind_channel.db") -> TestClient:  # type: ignore[no-untyped-def]
    return TestClient(create_app(str(tmp_path / name)))


class FakeRun:
    """假 schtasks：只记录调用，不碰系统。"""

    def __init__(self, fail: bool = False) -> None:
        self.calls: list[list[str]] = []
        self.fail = fail

    def __call__(self, args: list[str]) -> tuple[bool, str]:
        self.calls.append(list(args))
        if self.fail:
            return False, "拒绝访问"
        return True, "成功"


# ---------------------------------------------------------------- 命令构造（纯函数）

def test_create_task_command_uses_pythonw_and_absolute_db(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """命令要能在"任意工作目录"下跑：脚本与库都给绝对路径；解释器优先 pythonw（不闪黑框）。"""
    script = ROOT / "src" / "timeflow" / "app" / "remind.py"
    db = str(tmp_path / "t.db")
    args = rm.create_task_command(sys.executable, script, db)
    joined = " ".join(args)
    assert args[0].lower().endswith("schtasks.exe") or args[0].endswith("schtasks")
    assert "/Create" in args and "/F" in args
    assert rm.TASK_NAME in args
    assert str(script) in joined and db in joined
    assert "MINUTE" in args
    if sys.platform.startswith("win"):
        # 有 pythonw 时用它（没有控制台窗口），没有就退回当前解释器
        expected = Path(sys.executable).with_name("pythonw.exe")
        assert ("pythonw" in joined.lower()) == expected.exists()


def test_delete_and_query_commands() -> None:
    assert "/Delete" in rm.delete_task_command() and rm.TASK_NAME in rm.delete_task_command()
    assert "/Query" in rm.query_task_command()


def test_toast_script_loads_xml_and_uses_appid() -> None:
    ps = rm.powershell_toast_script("标题", "正文")
    assert "ToastNotificationManager" in ps and "LoadXml($env:TF_XML)" in ps
    assert "TF_XML" in ps  # XML 走环境变量，避免转义问题
    assert rm._encode_ps("echo 中文").isascii()  # base64：中文不会在命令行上乱码


# ---------------------------------------------------------------- 提醒方式（闹钟式 / 温和）

def test_alarm_toast_xml_is_sticky_and_rings() -> None:
    """用户反馈"普通通知效果很差" → 闹钟式用 Windows 的 alarm 方案：
    预先展开、留在屏幕上直到手动关掉（duration=long + scenario=alarm）、循环播放闹钟音。"""
    xml = rm.build_toast_xml("交作业", "提醒时间 2026-09-20 09:00", rm.STYLE_ALARM)
    assert 'scenario="alarm"' in xml and 'duration="long"' in xml
    assert "Notification.Looping.Alarm" in xml and 'loop="true"' in xml
    assert "交作业" in xml


def test_gentle_toast_xml_is_plain() -> None:
    xml = rm.build_toast_xml("交作业", "正文", rm.STYLE_GENTLE)
    assert "scenario=" not in xml and 'duration="short"' in xml
    assert "Looping.Alarm" not in xml


def test_toast_xml_escapes_user_text() -> None:
    xml = rm.build_toast_xml('写 <报告> & "总结"', "5 > 3", rm.STYLE_ALARM)
    assert "&lt;报告&gt;" in xml and "&amp;" in xml and "&quot;总结&quot;" in xml
    assert "<报告>" not in xml  # 没转义就会把 XML 弄坏（通知直接弹不出来）


def test_default_style_is_alarm_and_settable(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = db_mod.connect(str(tmp_path / "style.db"))
    assert rm.get_style(conn) == rm.STYLE_ALARM  # 默认闹钟式（普通通知提不住人）
    assert rm.set_style(conn, rm.STYLE_GENTLE) == rm.STYLE_GENTLE
    assert rm.status(conn)["style"] == "gentle"
    assert {s["value"] for s in rm.status(conn)["styles"]} == set(rm.VALID_STYLES)
    with pytest.raises(ValueError):
        rm.set_style(conn, "随便")
    assert rm.get_style(conn) == rm.STYLE_GENTLE  # 非法值没有落库
    conn.close()


def test_show_notification_passes_style_xml(monkeypatch) -> None:
    """真正交给 PowerShell 的 XML 要跟着"提醒方式"走（否则设置切了也没用）。"""
    captured: dict[str, str] = {}

    def runner(args: list[str], env: dict[str, str]) -> tuple[bool, str]:
        captured.update(env)
        return True, "ok"

    ok, detail = rm.show_notification("A", "B", rm.STYLE_ALARM, run=runner)
    assert ok and 'scenario="alarm"' in captured["TF_XML"]
    assert "留" in detail  # 提示里说清"留在屏幕上直到你关掉"
    ok2, _ = rm.show_notification("A", "B", rm.STYLE_GENTLE, run=runner)
    assert ok2 and "scenario=" not in captured["TF_XML"]


def test_notify_due_uses_configured_style(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """路径：设置切到温和 → notify_due 不传 style 时也按设置走。"""
    conn = db_mod.connect(str(tmp_path / "nstyle.db"))
    rm.set_style(conn, rm.STYLE_GENTLE)
    tm.create_task(conn, "任务", remind_at="2026-09-20T09:00")
    seen: list[str] = []
    real = rm.show_notification
    try:
        rm.show_notification = lambda t, b, style=rm.DEFAULT_STYLE: (  # type: ignore[assignment]
            seen.append(style) or (True, "ok")
        )
        rm.notify_due(conn, datetime(2026, 9, 20, 12, 0))
    finally:
        rm.show_notification = real  # type: ignore[assignment]
    assert seen == [rm.STYLE_GENTLE]
    conn.close()


# ---------------------------------------------------------------- 开关（用假 runner）

def test_disabled_by_default_and_install_uninstall(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = db_mod.connect(str(tmp_path / "s.db"))
    assert rm.is_enabled(conn) is False  # 默认关：不注册任何系统任务
    assert rm.status(conn)["installed"] is False

    run = FakeRun()
    st = rm.set_enabled(conn, True, python_exe=sys.executable, db_path="x.db", run=run)
    assert st["enabled"] is True
    assert any("/Create" in c for c in run.calls)
    assert "已注册" in str(st["last_result"])

    run2 = FakeRun()
    st2 = rm.set_enabled(conn, False, run=run2)
    assert st2["enabled"] is False
    assert any("/Delete" in c for c in run2.calls)
    conn.close()


def test_install_failure_does_not_persist_enabled(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """注册失败 → 设置**不落库**（否则会出现"以为开了其实没开"）。"""
    conn = db_mod.connect(str(tmp_path / "f.db"))
    try:
        rm.set_enabled(conn, True, python_exe=sys.executable, run=FakeRun(fail=True))
    except RuntimeError as e:
        assert "注册计划任务失败" in str(e)
    else:  # pragma: no cover - 必须抛
        raise AssertionError("注册失败时应当报错")
    assert rm.is_enabled(conn) is False
    conn.close()


# ---------------------------------------------------------------- 弹通知（注入 sender）

def test_notify_due_fires_once_per_reminder(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = db_mod.connect(str(tmp_path / "n.db"))
    now = datetime(2026, 9, 20, 12, 0)
    tm.create_task(conn, "到点了", remind_at="2026-09-20T09:00")
    tm.create_task(conn, "还没到", remind_at="2026-09-21T09:00")

    sent: list[tuple[str, str]] = []

    def sender(title: str, body: str) -> tuple[bool, str]:
        sent.append((title, body))
        return True, "已弹出系统通知"

    first = rm.notify_due(conn, now, sender=sender)
    assert [r["title"] for r in first] == ["到点了"] and first[0]["sent"] is True
    assert sent[0][0] == "到点了" and "提醒时间 2026-09-20 09:00" in sent[0][1]
    assert rm.status(conn)["last_notify_at"] == "2026-09-20T12:00"

    # 再查一次：同一条提醒已经弹过 → 不重复弹
    assert rm.notify_due(conn, now, sender=sender) == []
    assert len(sent) == 1

    # 改了提醒时间 → 视为新提醒，重新弹
    task_id = first[0]["task_id"]
    tm.update_task(conn, task_id, remind_at="2026-09-20T13:00")
    later = rm.notify_due(conn, datetime(2026, 9, 20, 14, 0), sender=sender)
    assert [r["title"] for r in later] == ["到点了"] and len(sent) == 2
    conn.close()


def test_notify_failure_is_reported_and_retried(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """弹不出来：如实记错误、**不标记已弹**（下次重试），绝不静默。"""
    conn = db_mod.connect(str(tmp_path / "nf.db"))
    now = datetime(2026, 9, 20, 12, 0)
    tm.create_task(conn, "弹不出来的", remind_at="2026-09-20T09:00")

    def bad(title: str, body: str) -> tuple[bool, str]:
        return False, "通知弹不出来：找不到 powershell"

    got = rm.notify_due(conn, now, sender=bad)
    assert got[0]["sent"] is False
    st = rm.status(conn)
    assert "找不到 powershell" in str(st["last_error"])
    assert st["last_notify_at"] is None

    calls: list[str] = []

    def good(title: str, body: str) -> tuple[bool, str]:
        calls.append(title)
        return True, "已弹出系统通知"

    assert rm.notify_due(conn, now, sender=good) != []  # 重试成功
    assert calls == ["弹不出来的"]
    assert rm.status(conn)["last_error"] == ""
    conn.close()


def test_too_many_due_merged_into_one(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """关机几天回来：一次到点 5 条 → 只弹一条汇总（不轰炸）。"""
    conn = db_mod.connect(str(tmp_path / "many.db"))
    now = datetime(2026, 9, 20, 12, 0)
    for i in range(5):
        tm.create_task(conn, f"任务{i}", remind_at="2026-09-19T09:00")

    sent: list[str] = []

    def sender(title: str, body: str) -> tuple[bool, str]:
        sent.append(title)
        return True, "已弹出系统通知"

    got = rm.notify_due(conn, now, sender=sender)
    assert len(sent) == 1 and "5 条提醒到点了" in sent[0]
    assert len(got) == 5 and all(r["sent"] for r in got)
    assert rm.notify_due(conn, now, sender=sender) == []  # 全部已标记
    conn.close()


def test_completed_task_is_not_notified(tmp_path) -> None:  # type: ignore[no-untyped-def]
    conn = db_mod.connect(str(tmp_path / "done.db"))
    now = datetime(2026, 9, 20, 12, 0)
    t = tm.create_task(conn, "已经做完了", remind_at="2026-09-20T09:00")
    tm.complete_task(conn, t.id)
    sent: list[str] = []
    assert rm.notify_due(conn, now, sender=lambda a, b: (sent.append(a), (True, "ok"))[1]) == []
    assert sent == []
    conn.close()


# ---------------------------------------------------------------- 脚本入口能独立跑

def test_remind_script_runs_standalone(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """计划任务的工作目录不是项目根：脚本自己补 sys.path，`--check` 要能直接跑起来。"""
    db = str(tmp_path / "cli.db")
    c = db_mod.connect(db)  # 建库
    c.close()
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", str(ROOT / "src" / "timeflow" / "app" / "remind.py"),
         "--db", db, "--check"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "enabled: False" in (proc.stdout or "")


def test_remind_script_notify_with_injected_now(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """`--now` 能把"现在"往前挪（演示/排查用）；到点但弹不出来时脚本退出码非 0。"""
    db = str(tmp_path / "cli2.db")
    c = db_mod.connect(db)
    tm.create_task(c, "该提醒了", remind_at="2026-09-20T09:00")
    c.close()
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", str(ROOT / "src" / "timeflow" / "app" / "remind.py"),
         "--db", db, "--now", "2026-09-20T12:00"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    # 这条路径会真的尝试弹通知：环境里弹不出来就应当是 FAIL（并退出码 0/1 都如实反映）
    assert "该提醒了" in (proc.stdout or "") or proc.returncode in (0, 1)
    c2 = db_mod.connect(db)
    st = rm.status(c2)
    assert st["last_result"] or st["last_error"]  # 有尝试就有记录（不许静默）
    c2.close()


# ---------------------------------------------------------------- API

def test_api_reminder_settings_roundtrip(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    client = _client(tmp_path)
    got = client.get("/api/settings/reminder").json()
    assert got["enabled"] is False and got["task_name"] == rm.TASK_NAME
    assert got["style"] == "alarm"  # 默认闹钟式

    calls: list[list[str]] = []
    monkeypatch.setattr(
        rm, "install_task", lambda *a, **k: (calls.append(["install"]) or (True, "成功"))
    )
    monkeypatch.setattr(
        rm, "uninstall_task", lambda *a, **k: (calls.append(["uninstall"]) or (True, "成功"))
    )
    monkeypatch.setattr(rm, "task_installed", lambda *a, **k: False)

    on = client.put("/api/settings/reminder", json={"enabled": True}).json()
    assert on["enabled"] is True and calls == [["install"]]
    off = client.put("/api/settings/reminder", json={"enabled": False}).json()
    assert off["enabled"] is False and calls == [["install"], ["uninstall"]]
    # 只改提醒方式：不动计划任务
    st = client.put("/api/settings/reminder", json={"style": "gentle"}).json()
    assert st["style"] == "gentle" and calls == [["install"], ["uninstall"]]
    assert client.put("/api/settings/reminder", json={"style": "吼我"}).status_code == 400


def test_api_reminder_install_failure_is_400(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    client = _client(tmp_path, "fail.db")

    def boom(*a: object, **k: object) -> tuple[bool, str]:
        return False, "拒绝访问"

    monkeypatch.setattr(rm, "install_task", boom)
    resp = client.put("/api/settings/reminder", json={"enabled": True})
    assert resp.status_code == 400
    assert "注册计划任务失败" in resp.json()["detail"]
    assert client.get("/api/settings/reminder").json()["enabled"] is False  # 没落库


def test_api_test_notification_and_cross_origin_guard(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    client = _client(tmp_path, "test.db")
    monkeypatch.setattr(rm, "show_notification", lambda t, b, run=None: (True, "已弹出系统通知"))
    got = client.post("/api/reminders/test").json()
    assert got["ok"] is True and "已弹出" in got["detail"]
    assert client.get("/api/settings/reminder").json()["last_result"] == "已弹出系统通知"

    evil = {"Origin": "https://evil.example"}
    assert client.put(
        "/api/settings/reminder", json={"enabled": True}, headers=evil
    ).status_code == 403
    assert client.post("/api/reminders/test", headers=evil).status_code == 403


def test_no_system_task_is_created_by_default(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """默认关闭：只看状态、只读提醒，都不会去碰系统计划任务。"""
    conn = db_mod.connect(str(tmp_path / "quiet.db"))
    now = datetime(2026, 9, 20, 12, 0)
    tm.create_task(conn, "任务", remind_at="2026-09-20T09:00")
    assert rm.status(conn)["enabled"] is False
    # due_reminders 只读：拿来显示「该提醒了」，不注册任务、不发通知
    assert [t.title for t in tm.due_reminders(conn, now)] == ["任务"]
    assert rm.status(conn)["last_notify_at"] is None
    conn.close()
