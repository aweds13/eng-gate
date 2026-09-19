"""到点提醒的通知通道（SR-F1.4「Remind me」/ T-B5 后半）—— 用户选的 **B′：计划任务 + 系统通知**。

## 为什么是计划任务
需求是"**关掉应用也响**"。本机可选的可靠做法只有系统层调度：
- 浏览器/应用内轮询都要求进程活着（用户不接受"关掉就不响"作为唯一形态）；
- 微软文档也建议「需要保证送达就用带时间触发器的后台任务」
  （见 `复盘/段2设计决策-提醒与附件打开方式.md` §八）；
- **不引第三方依赖**：用系统自带的 `schtasks` 注册一个每分钟跑一次的任务，
  任务是 `pythonw src/timeflow/app/remind.py`（无控制台窗口，不会每分钟闪一下黑框）。
- 想到"直接调用系统闹钟 App"做不到：微软没有开放往「闹钟和时钟」里建闹钟的接口（只能打开它），
  所以那条路只能作为「打开闹钟 App」的便利按钮，不能当通知通道。

## 诚实边界（写清楚，不假装）
- **默认关闭**：不启用就只做界面标注，不注册任何系统任务（默认保守 + 显式放行）。
- 计划任务以**当前用户、交互式**运行 → **应用关掉也响**；但**注销/关机时不响**
  （要做到"注销也响"得用 SYSTEM 或带密码的 `/RU`，属于多要权限的事，不擅自做）。
- 同一提醒（同 `remind_at`）**只弹一次**（改时间后会重新弹）；不需要"提醒已读"这种额外状态。
- 弹不出来时**不许静默**：失败原因写进 `app_settings`，设置页能看到（`last_error`）。
"""

from __future__ import annotations

import base64
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from timeflow.core import tasks as tm

if TYPE_CHECKING:
    import sqlite3

# 计划任务名（卸载时按这个名字删；改名字要记得同时改这里和文档）
TASK_NAME = "timeflow-reminders"
# 设置键（app_settings 是通用 key/value 表）
KEY_ENABLED = "reminder.notify_enabled"
KEY_STYLE = "reminder.style"
KEY_LAST_AT = "reminder.last_notify_at"
KEY_LAST_RESULT = "reminder.last_result"
KEY_LAST_ERROR = "reminder.last_error"
KEY_FIRED_PREFIX = "reminder.fired."
# 检查间隔（分钟）：1 分钟足够准，且脚本是"查一下就走"，代价极小
INTERVAL_MINUTES = 1

# 提醒强度（用户反馈"普通通知效果很差"后加的）：
#   gentle = 普通系统通知（右下角浮一下、几秒消失、有无声音看系统设置）；
#   alarm  = **闹钟式**（`scenario="alarm"`：预先展开、**留在屏幕上直到手动关掉**、
#            默认**循环播放闹钟音**，并且能突破「专注助手/免打扰」）——
#            这是 Windows 官方 toast schema 支持的方案，比第三方库更稳、也不需要额外依赖
#            （见 MS Learn：toast 元素 scenario / audio）。
STYLE_GENTLE = "gentle"
STYLE_ALARM = "alarm"
VALID_STYLES = (STYLE_ALARM, STYLE_GENTLE)
DEFAULT_STYLE = STYLE_ALARM  # 默认闹钟式：普通通知"提不住人"，等于没提醒
STYLE_LABELS = {
    STYLE_ALARM: "闹钟式（留在屏幕上 + 循环响铃）",
    STYLE_GENTLE: "温和通知（几秒后消失）",
}

# 项目里的脚本入口（计划任务直接跑它，不依赖 PYTHONPATH）
REMIND_SCRIPT = Path(__file__).resolve().parent.parent / "app" / "remind.py"


# ---------------------------------------------------------------- 计划任务（schtasks）
def schtasks_exe() -> str:
    return shutil.which("schtasks") or "schtasks"


def build_run_command(python_exe: str, script: Path, db_path: str) -> str:
    """计划任务要执行的命令行。

    用**无控制台的解释器**（`pythonw.exe`）—— 否则每分钟闪一次黑框，比没有提醒更烦。
    `pythonw` 找不到时退回 `python.exe`（能响，但会闪窗；这种取舍写在返回值里由调用方说明）。
    """
    exe = python_exe
    if sys.platform.startswith("win"):
        candidate = Path(python_exe).with_name("pythonw.exe")
        if candidate.exists():
            exe = str(candidate)
    return f'"{exe}" "{script}" --db "{db_path}"'


def create_task_command(
    python_exe: str, script: Path, db_path: str, task_name: str = TASK_NAME
) -> list[str]:
    """`schtasks /Create` 的参数（纯函数：**只拼参数、不执行** —— 便于测试，也不会误改系统）。"""
    return [
        schtasks_exe(), "/Create", "/TN", task_name,
        "/SC", "MINUTE", "/MO", str(INTERVAL_MINUTES),
        "/TR", build_run_command(python_exe, script, db_path),
        "/F",
    ]


def delete_task_command(task_name: str = TASK_NAME) -> list[str]:
    return [schtasks_exe(), "/Delete", "/TN", task_name, "/F"]


def query_task_command(task_name: str = TASK_NAME) -> list[str]:
    return [schtasks_exe(), "/Query", "/TN", task_name]


def _run(args: list[str]) -> tuple[bool, str]:
    """跑一条系统命令；返回 (成功?, 输出摘要)。异常一律收敛成 False（由调用方报给用户）。"""
    try:
        proc = subprocess.run(  # noqa: S603 —— 参数是白名单里的固定命令，不含用户输入拼接
            args, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"无法执行 {args[0]}：{e}"
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return proc.returncode == 0, out[-400:]


def install_task(
    python_exe: str, script: Path, db_path: str, run: Any = None
) -> tuple[bool, str]:
    """注册（或覆盖）计划任务。**会改系统状态**：只在用户显式打开开关时调用。"""
    return (run or _run)(create_task_command(python_exe, script, db_path))


def uninstall_task(run: Any = None, task_name: str = TASK_NAME) -> tuple[bool, str]:
    """删除计划任务（关闭开关 / 卸载时调用）。

    先查后删（**不做字符串匹配**）：任务本来就不存在 → 幂等成功；存在才删，并如实回报删除结果。
    字符串匹配踩过的坑：环境本身访问不了任务计划程序时（如受限沙箱），错误文案里也有
    "cannot find" —— 那样会把"删不掉"误报成"本来就不存在"。
    """
    if not task_installed(run, task_name):
        return True, "任务本来就不存在"
    return (run or _run)(delete_task_command(task_name))


def task_installed(run: Any = None, task_name: str = TASK_NAME) -> bool:
    ok, _ = (run or _run)(query_task_command(task_name))
    return ok


# ---------------------------------------------------------------- 设置（服务端持久化）
def _get(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return None if row is None else str(row["value"])


def _put(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO app_settings (key, value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def is_enabled(conn: sqlite3.Connection) -> bool:
    return (_get(conn, KEY_ENABLED) or "0") == "1"


def get_style(conn: sqlite3.Connection) -> str:
    """当前提醒强度（默认**闹钟式** —— 普通通知"提不住人"，等于没提醒）。"""
    raw = _get(conn, KEY_STYLE) or DEFAULT_STYLE
    return raw if raw in VALID_STYLES else DEFAULT_STYLE


def set_style(conn: sqlite3.Connection, style: object) -> str:
    """改提醒强度。非法值拒绝（不静默回落默认值）。"""
    if str(style) not in VALID_STYLES:
        raise ValueError(f"未知提醒方式: {style}（只能是 {'/'.join(VALID_STYLES)}）")
    _put(conn, KEY_STYLE, str(style))
    conn.commit()
    return get_style(conn)


def record_result(conn: sqlite3.Connection, ok: bool, detail: str) -> None:
    """把一次通知尝试的结果写进设置（设置页据此显示；失败必提示，不静默）。"""
    if ok:
        _put(conn, KEY_LAST_RESULT, detail)
        _put(conn, KEY_LAST_ERROR, "")
    else:
        _put(conn, KEY_LAST_ERROR, detail)
    conn.commit()


def status(conn: sqlite3.Connection, run: Any = None) -> dict[str, Any]:
    """设置页要显示的状态（都是**事实**，不含猜测）。"""
    return {
        "enabled": is_enabled(conn),
        "style": get_style(conn),
        "styles": [{"value": s, "label": STYLE_LABELS[s]} for s in VALID_STYLES],
        "task_name": TASK_NAME,
        "installed": task_installed(run),
        "interval_minutes": INTERVAL_MINUTES,
        "last_notify_at": _get(conn, KEY_LAST_AT),
        "last_result": _get(conn, KEY_LAST_RESULT),
        "last_error": _get(conn, KEY_LAST_ERROR),
    }


def set_enabled(
    conn: sqlite3.Connection,
    enabled: bool,
    python_exe: str | None = None,
    script: Path | None = None,
    db_path: str | None = None,
    run: Any = None,
) -> dict[str, Any]:
    """打开/关闭到点通知。

    打开 = 写设置 + 注册计划任务；关闭 = 写设置 + 删除计划任务（**可逆、不留痕**）。
    注册失败 → 设置**不落库**（保持"以为开了其实没开"这种事不发生），并把错误如实抛给界面。
    """
    if enabled:
        exe = python_exe or sys.executable
        sc = script or REMIND_SCRIPT
        db = db_path or _default_db_path()
        ok, detail = install_task(exe, sc, db, run)
        if not ok:
            raise RuntimeError(f"注册计划任务失败：{detail}")
        _put(conn, KEY_ENABLED, "1")
        _put(conn, KEY_LAST_RESULT, f"已注册计划任务（每 {INTERVAL_MINUTES} 分钟检查一次）")
    else:
        ok, detail = uninstall_task(run)
        if not ok:
            raise RuntimeError(f"删除计划任务失败：{detail}")
        _put(conn, KEY_ENABLED, "0")
        _put(conn, KEY_LAST_RESULT, "已关闭（计划任务已删除）")
    conn.commit()
    return status(conn, run)


def _default_db_path() -> str:
    from timeflow.config import load_settings

    settings = load_settings()
    path = Path(settings.database.path)
    if not path.is_absolute():
        from timeflow.config import ROOT

        path = ROOT / path
    return str(path)


# ---------------------------------------------------------------- 弹系统通知
def _xml_escape(text: str) -> str:
    return (
        str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        .replace('"', "&quot;").replace("'", "&apos;")
    )


def build_toast_xml(title: str, body: str, style: str = DEFAULT_STYLE) -> str:
    """生成 toast XML（**纯函数**，可单测）。

    - `alarm`（闹钟式）：`scenario="alarm" duration="long"` → 预先展开、**留在屏幕上直到手动关掉**、
      并带 `Notification.Looping.Alarm` **循环闹钟音**（微软文档：alarm 方案默认循环且用警报音频）。
    - `gentle`（温和）：普通通知，几秒后自动消失。
    """
    t, b = _xml_escape(title), _xml_escape(body)
    if style == STYLE_ALARM:
        return (
            '<toast duration="long" scenario="alarm">'
            '<visual><binding template="ToastGeneric">'
            f"<text>{t}</text><text>{b}</text>"
            "</binding></visual>"
            '<audio src="ms-winsoundevent:Notification.Looping.Alarm" loop="true"/>'
            "</toast>"
        )
    return (
        '<toast duration="short">'
        '<visual><binding template="ToastGeneric">'
        f"<text>{t}</text><text>{b}</text>"
        "</binding></visual>"
        "</toast>"
    )


def powershell_toast_script(title: str, body: str, style: str = DEFAULT_STYLE) -> str:
    """生成弹通知的 PowerShell 脚本（XML 与环境变量传入，避免转义地狱）。

    注意：`title`/`body` 在这里只用于**校验参数**（真正的 XML 由调用方放进 `TF_XML`），
    所以这里不重复拼 XML。
    """
    return (
        "$ErrorActionPreference='Stop'\n"
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
        "ContentType=WindowsRuntime] > $null\n"
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, "
        "ContentType=WindowsRuntime] > $null\n"
        "$doc=[Windows.Data.Xml.Dom.XmlDocument]::new()\n"
        "$doc.LoadXml($env:TF_XML)\n"
        # AppId 用 Windows PowerShell 已注册的 AUMID：未打包程序没有自己的 AUMID 时，
        # 这是"不额外注册系统组件也能弹通知"的通行做法。
        "$id='{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe'\n"
        "$toast=[Windows.UI.Notifications.ToastNotification]::new($doc)\n"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($id).Show($toast)\n"
    )


def _encode_ps(script: str) -> str:
    """PowerShell `-EncodedCommand` 需要 UTF-16LE + base64（这样中文不会乱码）。"""
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def show_notification(
    title: str, body: str, style: str = DEFAULT_STYLE, run: Any = None
) -> tuple[bool, str]:
    """弹一条系统通知。Windows 走 WinRT toast（按 `style` 决定闹钟式/温和），失败再退 `msg`。

    `run` 是注入点，签名固定为 `(args, env) -> (ok, detail)`（默认 `_run_env`）——
    测试里替换它就不会真的弹窗。
    """
    if not sys.platform.startswith("win"):
        return False, "当前平台未实现系统通知（Windows 之外的平台请用界面标注）"
    if style not in VALID_STYLES:
        style = DEFAULT_STYLE
    runner: Any = run or _run_env
    ps = shutil.which("powershell") or shutil.which("pwsh")
    if ps:
        xml = build_toast_xml(title, body, style)
        cmd = [
            ps, "-NoProfile", "-NonInteractive",
            "-EncodedCommand", _encode_ps(powershell_toast_script(title, body, style)),
        ]
        ok, detail = runner(cmd, {"TF_XML": xml})
        if ok:
            return True, ("已弹出闹钟式提醒（留在屏幕上直到你关掉）" if style == STYLE_ALARM
                          else "已弹出温和通知")
        toast_error = detail
    else:
        toast_error = "找不到 powershell"
    msg = shutil.which("msg")
    if msg:
        # msg 是模态弹窗：比 toast 更"提得住人"，作为闹钟式的兜底反而合适
        ok, detail = runner([msg, "*", "/TIME:60", f"{title}：{body}"], {})
        if ok:
            return True, "已用 msg 弹出提醒（toast 不可用）"
    return False, f"通知弹不出来：{toast_error}"


def _run_env(args: list[str], env_extra: dict[str, str] | None = None) -> tuple[bool, str]:
    """跑一条系统命令（可带额外环境变量）；返回 (成功?, 输出摘要)。"""
    import os

    env = dict(os.environ)
    env.update(env_extra or {})
    try:
        proc = subprocess.run(  # noqa: S603
            args, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30, env=env,
        )
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"无法执行 {args[0]}：{e}"
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return proc.returncode == 0, out[-400:]


# ---------------------------------------------------------------- 到点提醒（任务脚本用）
def _fired_mark(conn: sqlite3.Connection, task_id: str) -> str | None:
    return _get(conn, KEY_FIRED_PREFIX + task_id)


# 一次最多弹几条：关机/离线几天后回来，一下弹 20 条比不提醒还烦 ——
# 超过就合并成一条汇总（温和口径：说清有几条、让人自己去看，而不是轰炸）。
MAX_NOTIFICATIONS_PER_RUN = 3


def notify_due(
    conn: sqlite3.Connection,
    now: datetime | None = None,
    sender: Any = None,
    style: str | None = None,
) -> list[dict[str, Any]]:
    """把"到点该提醒"的任务弹系统通知（**同一条提醒只弹一次**；太多则合并成一条汇总）。

    返回本次尝试的明细（`{task_id, title, remind_at, sent, detail}`），供设置页/日志核对。
    - 失败**不抛异常**、也**不标记已弹**：写进 `last_error` 并由返回值如实报告，
      下一次检查会重试（不许静默失败）。
    - 成功才标记（键 = 该条的 `remind_at`）→ 用户改了提醒时间会重新弹。
    - `style` 缺省用当前设置（闹钟式 / 温和）。
    """
    moment = now or datetime.now()
    use_style = style or get_style(conn)
    pending = [
        t for t in tm.due_reminders(conn, moment)
        if _fired_mark(conn, t.id) != str(t.remind_at)
    ]
    if not pending:
        return []
    results: list[dict[str, Any]] = []
    send = sender or (lambda title, body: show_notification(title, body, use_style))

    if len(pending) > MAX_NOTIFICATIONS_PER_RUN:
        names = "、".join(t.title for t in pending[:3])
        ok, detail = send(
            f"timeflow：有 {len(pending)} 条提醒到点了",
            f"{names} 等（打开 timeflow 看全部）",
        )
        records = [{
            "task_id": t.id, "title": t.title, "remind_at": t.remind_at,
            "sent": ok, "detail": detail,
        } for t in pending]
        if ok:
            for t in pending:
                _put(conn, KEY_FIRED_PREFIX + t.id, str(t.remind_at))
            _put(conn, KEY_LAST_AT, moment.strftime("%Y-%m-%dT%H:%M"))
            _put(conn, KEY_LAST_RESULT, f"已合并提醒 {len(pending)} 条")
            _put(conn, KEY_LAST_ERROR, "")
        else:
            _put(conn, KEY_LAST_ERROR, f"合并提醒失败：{detail}")
        conn.commit()
        return records

    for task in pending:
        when = str(task.remind_at).replace("T", " ")
        body = f"提醒时间 {when}" + (f" · 截止 {task.due_date}" if task.due_date else "")
        ok, detail = send(task.title, body)
        results.append({
            "task_id": task.id, "title": task.title, "remind_at": task.remind_at,
            "sent": ok, "detail": detail,
        })
        if ok:
            _put(conn, KEY_FIRED_PREFIX + task.id, str(task.remind_at))
            _put(conn, KEY_LAST_AT, moment.strftime("%Y-%m-%dT%H:%M"))
            _put(conn, KEY_LAST_RESULT, f"已提醒「{task.title}」")
            _put(conn, KEY_LAST_ERROR, "")
        else:
            _put(conn, KEY_LAST_ERROR, f"「{task.title}」{detail}")
    conn.commit()
    return results
