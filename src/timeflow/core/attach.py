"""附件 / 要求链接（SR-F1.4「附件」+ SR-F5.3「跳转本地文件/网站」+ N20）。

一次做成"**能点开**"的能力：任务与学业考核项共用同一套字段与打开规则
（`tasks.attach` / `course_assessments.attach`，JSON 数组）。

## 数据形状
```json
[{"target": "https://example.com/作业要求", "title": "要求页"},
 {"target": "D:\\课件\\高数\\第3章.pdf", "title": "讲义"}]
```
只存 `target`（网址或本地路径）+ 可选 `title`；**类型由 target 现场判定**（不存冗余的 kind，
免得出现"标着网页、其实是路径"这种自相矛盾的数据）。

## 打开规则（`复盘/段2设计决策-提醒与附件打开方式.md` §三，三层逐层收窄）
1. **网址**（http/https）→ 交给浏览器开新标签（后端只解析，不代开）。
2. **目录** → 打开该目录。
3. **本地文件** → 按模式：
   - 在**直接打开白名单**里 → 直接打开（白名单压过模式，见 4）；
   - 模式 = `folder`（**默认**）→ 只打开所在文件夹；
   - 模式 = `direct`（用户显式选）→ 用默认程序打开；
   - 模式 = `auto`（按格式）→ 文档类**定位**到该文件（`explorer /select`），其它只开文件夹。
4. **白名单**（用户维护的扩展名）与**安全底线**：可执行/脚本类（`.exe/.bat/.cmd/.ps1/.lnk/.msi`…）
   **一律不直接打开、也不许进白名单**（点开本地文件等于从文档里启动程序，这条底线不能靠用户配置绕过）；
   这类文件只到文件夹。

## 原则
**默认保守 + 显式放行 + 失败必提示**：打不开就返回 `action="copy"` + 路径，让界面复制路径并出声，
**不允许静默失败**。

## 实施记录（2026-09-18，T-B4）
设计文档原估"靠本地服务返回 `file://` 链接让浏览器导航，需真机验证"。
实施时改用**后端直接执行**（Windows `explorer` / `os.startfile`，其它平台 `xdg-open`/`open`）——
理由：① 浏览器不会替网页开资源管理器，`file://` 从 http 页面跳转在 Chrome/Edge 默认被拦，
"跳转文件夹"这个诉求只有本机进程能可靠做到；② 打开模式与白名单**存在服务端设置里**，
不由请求参数决定（否则任何网页都能要求"直接打开"）；③ 该接口加**来源守卫**
（只接受本机页面调用，见 api 层）。`file://` 链接仍随响应返回（`file_url`），用于兜底展示。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

if TYPE_CHECKING:
    import sqlite3

# ---------------------------------------------------------------- 打开模式（设置项）
MODE_FOLDER = "folder"  # 只打开所在文件夹（**默认**：最保守）
MODE_DIRECT = "direct"  # 直接用默认程序打开
MODE_AUTO = "auto"  # 按格式自动（= 设计文档 §三① 的规则）
VALID_MODES = (MODE_FOLDER, MODE_DIRECT, MODE_AUTO)
DEFAULT_MODE = MODE_FOLDER
MODE_LABELS = {
    MODE_FOLDER: "打开所在文件夹",
    MODE_DIRECT: "直接用默认程序打开",
    MODE_AUTO: "按格式自动",
}

# 设置表的键（app_settings 是通用 key/value 表）
KEY_MODE = "attach.mode"
KEY_WHITELIST = "attach.whitelist"

# 「文档类」：`auto` 模式下会**定位到该文件**（explorer /select）；其余只开文件夹。
DOC_EXTENSIONS = (
    ".pdf", ".doc", ".docx", ".md", ".txt", ".rtf", ".odt", ".pages",
    ".ppt", ".pptx", ".key", ".xls", ".xlsx", ".csv", ".numbers", ".ipynb",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".heic",
    ".mp3", ".wav", ".m4a", ".mp4", ".mov", ".mkv",
)

# 安全底线：可执行 / 脚本 / 快捷方式类 —— 永远不直接打开，也不许进白名单。
DANGEROUS_EXTENSIONS = (
    ".exe", ".bat", ".cmd", ".com", ".scr", ".msi", ".ps1", ".psm1", ".vbs", ".vbe",
    ".js", ".jse", ".wsf", ".wsh", ".lnk", ".url", ".reg", ".jar", ".app", ".sh",
    ".bash", ".zsh", ".py", ".pyw", ".hta", ".cpl", ".dll", ".sys", ".inf",
)

ACTION_BROWSER = "browser"  # 交给浏览器开新标签
ACTION_FOLDER = "folder"  # 打开所在文件夹
ACTION_SELECT = "select"  # 打开文件夹并定位到该文件
ACTION_DIRECT = "direct"  # 用默认程序打开
ACTION_COPY = "copy"  # 打不开：复制路径（失败必提示的兜底）


# ---------------------------------------------------------- 列表读写（tasks / assessments 共用）
def load_attach(raw: object) -> list[dict[str, str | None]]:
    """把数据库里的 JSON 文本读成列表。

    容错（用户手改过库 / 老数据）：非字符串、坏 JSON、不是数组、元素不是对象 ——
    一律**当成空/跳过**，绝不抛异常（否则一个坏字段会让整个任务列表打不开）。
    跳过时不猜内容，只保证不崩。
    """
    if not raw:
        return []
    if isinstance(raw, (list, tuple)):
        data: object = list(raw)
    else:
        try:
            data = json.loads(str(raw))
        except (TypeError, ValueError):
            return []
    if not isinstance(data, list):
        return []
    out: list[dict[str, str | None]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        target = item.get("target")
        if not isinstance(target, str) or not target.strip():
            continue
        title = item.get("title")
        out.append({
            "target": target.strip(),
            "title": title.strip() if isinstance(title, str) and title.strip() else None,
        })
    return out


def dump_attach(items: list[dict[str, str | None]]) -> str:
    return json.dumps(items, ensure_ascii=False)


def normalize_target(target: object) -> str:
    """校验并规整 target：非空字符串（网址或本地路径）。"""
    if not isinstance(target, str) or not target.strip():
        raise ValueError("附件的网址/路径不能为空")
    return target.strip()


def add_attachment_item(
    items: list[dict[str, str | None]], target: object, title: object = None
) -> list[dict[str, str | None]]:
    """加一条（**按 target 去重**：同一个路径/网址加两次是误操作，幂等返回原列表）。"""
    t = normalize_target(target)
    name = title.strip() if isinstance(title, str) and title.strip() else None
    if any(i["target"] == t for i in items):
        return list(items)
    return [*items, {"target": t, "title": name}]


def remove_attachment_item(
    items: list[dict[str, str | None]], index: int
) -> list[dict[str, str | None]]:
    """按下标删一条；下标越界 → ValueError（不静默无操作）。"""
    if not 0 <= index < len(items):
        raise ValueError(f"附件下标越界: {index}")
    return [i for n, i in enumerate(items) if n != index]


# ---------------------------------------------------------------- 判定与解析
def _ext_of(name: str) -> str:
    return Path(name).suffix.lower()


def is_url(target: str) -> bool:
    parts = urlsplit(target)
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def normalize_ext(value: object) -> str:
    """白名单条目规整为 `.pdf` 这种形式（大小写、缺点的都收进来）。"""
    ext = str(value or "").strip().lower()
    if not ext:
        raise ValueError("扩展名不能为空")
    if not ext.startswith("."):
        ext = "." + ext
    if not ext[1:].isalnum():
        raise ValueError(f"扩展名只能由字母数字组成: {value}")
    return ext


def check_whitelist_entry(value: object) -> str:
    """白名单条目的**入口校验**：可执行/脚本类直接拒绝（别让配置绕过安全底线）。"""
    ext = normalize_ext(value)
    if ext in DANGEROUS_EXTENSIONS:
        raise ValueError(f"{ext} 属于可执行/脚本类，出于安全不提供直接打开（只到文件夹）")
    return ext


def parse_whitelist(values: object) -> list[str]:
    """把用户给的扩展名列表规整成去重后的白名单（保序）。"""
    if values is None:
        return []
    if isinstance(values, str):
        raw = [p for p in values.replace("，", ",").split(",")]
    elif isinstance(values, (list, tuple)):
        raw = list(values)
    else:
        raise ValueError("白名单需要是扩展名数组")
    out: list[str] = []
    for item in raw:
        if not str(item or "").strip():
            continue
        ext = check_whitelist_entry(item)
        if ext not in out:
            out.append(ext)
    return out


def classify(target: str) -> str:
    """`url` / `dir` / `file` / `missing`。

    本地存在性用真实文件系统判定（本软件就是本机应用，后端与文件在同一台机器上）——
    不猜、不假设，**不存在就如实说"路径不存在"**（失败必提示）。
    """
    if is_url(target):
        return "url"
    path = Path(target)
    if path.is_dir():
        return "dir"
    if path.is_file():
        return "file"
    return "missing"


def file_url(target: str) -> str | None:
    """本地路径 → `file://` 链接（兜底展示用；不依赖浏览器能打开它）。"""
    try:
        return Path(target).resolve().as_uri()
    except (ValueError, OSError):
        return None


def resolve(target: object, mode: str, whitelist: list[str]) -> dict[str, Any]:
    """按三层规则算出"该做什么"（**纯函数**：不执行任何动作，便于测试与解释）。

    返回：`{target, kind, ext, action, reason, folder, file_url, whitelisted}`
    """
    t = normalize_target(target)
    if mode not in VALID_MODES:
        raise ValueError(f"未知打开方式: {mode}（只能是 {'/'.join(VALID_MODES)}）")
    kind = classify(t)
    ext = "" if kind == "url" else _ext_of(t)
    folder = None if kind in ("url", "missing") else str(Path(t).parent)
    base: dict[str, Any] = {
        "target": t,
        "kind": kind,
        "ext": ext,
        "action": ACTION_COPY,
        "reason": "",
        "folder": folder,
        "file_url": None if kind == "url" else file_url(t),
        "whitelisted": bool(ext and ext in whitelist),
    }
    if kind == "url":
        base.update(action=ACTION_BROWSER, reason="网页链接：交给浏览器开新标签")
        return base
    if kind == "missing":
        base.update(action=ACTION_COPY, reason="这个路径在本机不存在：复制路径给你（不静默失败）")
        return base

    parent = Path(t).parent if kind == "file" else Path(t)
    base["folder"] = str(parent)
    if kind == "dir":
        base.update(action=ACTION_FOLDER, reason="目录：打开这个目录")
        return base

    # 本地文件：安全底线 → 白名单 → 模式
    if ext in DANGEROUS_EXTENSIONS:
        base.update(
            action=ACTION_FOLDER,
            reason=f"{ext} 属于可执行/脚本类：只打开所在文件夹（不直接运行）",
        )
        return base
    if base["whitelisted"]:
        base.update(action=ACTION_DIRECT, reason=f"{ext} 在直接打开白名单里：直接用默认程序打开")
        return base
    if mode == MODE_DIRECT:
        base.update(action=ACTION_DIRECT, reason="按你选的「直接用默认程序打开」")
        return base
    if mode == MODE_AUTO and ext in DOC_EXTENSIONS:
        base.update(action=ACTION_SELECT, reason="文档类：打开所在文件夹并定位到该文件")
        return base
    base.update(action=ACTION_FOLDER, reason="只打开所在文件夹（默认保守）")
    return base


# ---------------------------------------------------------------- 执行（本机动作）
def run_open(action: str, path: str) -> tuple[bool, str]:
    """执行本机打开动作，返回 `(是否执行成功, 说明)`。

    - `folder` → 打开目录；`select` → 打开目录并选中文件；`direct` → 用默认程序打开。
    - 其它 action（`browser` / `copy`）不在本机执行，由界面处理。
    - **只有 Windows 行为经过实测**（本项目主目标平台）；其它平台尽力用 `xdg-open`/`open`，
      做不到就返回失败 —— 失败会走到"复制路径 + 提示"，不会静默。
    """
    if action not in (ACTION_FOLDER, ACTION_SELECT, ACTION_DIRECT):
        return False, f"该动作不由本机执行：{action}"
    win = sys.platform.startswith("win")
    try:
        if win:
            if action == ACTION_FOLDER:
                os.startfile(path)  # noqa: S606 —— 本机应用打开自己的文件，路径来自用户自己填的附件
                return True, "已打开所在文件夹"
            if action == ACTION_SELECT:
                # explorer 的退出码不可靠（成功也可能返回 1），因此不检查返回码
                subprocess.Popen(["explorer", f"/select,{os.path.normpath(path)}"])  # noqa: S603,S607
                return True, "已打开文件夹并定位到该文件"
            os.startfile(path)  # noqa: S606
            return True, "已用默认程序打开"
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        if action == ACTION_DIRECT:
            subprocess.Popen([opener, path])  # noqa: S603,S607
            return True, "已用默认程序打开"
        folder = path if action == ACTION_FOLDER else str(Path(path).parent)
        subprocess.Popen([opener, folder])  # noqa: S603,S607
        return True, "已打开所在文件夹"
    except OSError as e:
        return False, f"打不开：{e}"


def open_target(
    target: object,
    mode: str,
    whitelist: list[str],
    *,
    dry_run: bool = False,
    runner: Any = None,
) -> dict[str, Any]:
    """解析 + 执行。返回解析结果，外加 `executed` / `executed_detail`。

    `dry_run=True` 只解析不执行（测试与"先看看会发生什么"用；界面正常调用不走它）。
    `runner` 可注入（测试里替换掉真实打开动作，避免测试弹窗）。
    """
    result = resolve(target, mode, whitelist)
    result["executed"] = False
    result["executed_detail"] = ""
    result["dry_run"] = bool(dry_run)
    if result["action"] in (ACTION_BROWSER, ACTION_COPY):
        result["executed_detail"] = (
            "由浏览器打开" if result["action"] == ACTION_BROWSER else "无法打开，已给出路径"
        )
        return result
    if dry_run:
        result["executed_detail"] = "（演练：未真正打开）"
        return result
    ok, detail = (runner or run_open)(result["action"], result["target"])
    result["executed"] = bool(ok)
    result["executed_detail"] = detail
    if not ok:
        # 失败 → 退化为"复制路径 + 提示"（不许静默）
        result["action"] = ACTION_COPY
        result["reason"] = f"{result['reason']}；{detail}"
    return result


# ---------------------------------------------------------------- 设置（服务端持久化）
def _get_raw(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return None if row is None else str(row["value"])


def get_settings(conn: sqlite3.Connection) -> dict[str, Any]:
    """打开方式设置（服务端持有：**不能由请求参数决定**，否则任何网页都能要求"直接打开"）。"""
    raw_mode = _get_raw(conn, KEY_MODE) or DEFAULT_MODE
    mode = raw_mode if raw_mode in VALID_MODES else DEFAULT_MODE
    raw_wl = _get_raw(conn, KEY_WHITELIST)
    whitelist = parse_whitelist(raw_wl.split(",") if raw_wl else [])
    return {"mode": mode, "whitelist": whitelist}


def set_settings(
    conn: sqlite3.Connection,
    mode: object = None,
    whitelist: object = None,
) -> dict[str, Any]:
    """改设置（两种都可单独改）。非法值一律 ValueError（不静默落默认值）。"""
    if mode is not None:
        if str(mode) not in VALID_MODES:
            raise ValueError(f"未知打开方式: {mode}（只能是 {'/'.join(VALID_MODES)}）")
        _put(conn, KEY_MODE, str(mode))
    if whitelist is not None:
        items = parse_whitelist(whitelist)
        _put(conn, KEY_WHITELIST, ",".join(items))
    conn.commit()
    return get_settings(conn)


def _put(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO app_settings (key, value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def describe_rules() -> dict[str, Any]:
    """给界面用的规则说明（口径只有一份，界面不自己复述）。"""
    return {
        "modes": [{"value": m, "label": MODE_LABELS[m]} for m in VALID_MODES],
        "default_mode": DEFAULT_MODE,
        "doc_extensions": list(DOC_EXTENSIONS),
        "blocked_extensions": list(DANGEROUS_EXTENSIONS),
    }
