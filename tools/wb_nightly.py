r"""夜间全量的**记录**与「最近一次全量绿 ≤24 小时」判定（卡 E51 · 段 1 / E36）。

## 它做什么 / 不做什么

- **做**：在**独立 worktree**（`git worktree add --detach`）里跑一趟全量门禁，把结果写成
  `gates/diag/nightly/nightly-<时间戳>.json`，并在 `gates/diag/notifications.jsonl` 追加一行；
  再给 `tools/pytest_select.py` 提供闸二要问的那一句：**最近一次全量绿是不是 ≤24 小时**。
- **不做**：不装系统计划任务（用户 2026-10-25 明说：只写「可被计划任务调用的入口」）。
  计划任务那边只要调 `python -X utf8 tools/wb_nightly.py --run` 这一句。

## 为什么必须在独立 worktree 里跑

全量门禁会写 `gates/last.json`、`gates/logs/`、渲染截图、临时库…… 在主树里跑会把工作区弄脏
（"门禁产物与提交一致"那条审计立刻失效）。`git worktree add --detach <目录> HEAD` 拿到的是
**同一个 HEAD 的干净副本**，跑完 `git worktree remove --force` 收掉，主树的 `git status` 不动。

## 产物（都 gitignored：`gates/diag/*` 在 `.gitignore` 里）

    gates/diag/nightly/nightly-YYYYmmdd-HHMMSS.json   # 记录（ok / rev / 秒数 / 日志路径）
    gates/diag/nightly/nightly-YYYYmmdd-HHMMSS.log    # 门禁全量输出
    gates/diag/notifications.jsonl                    # 每趟一行（jsonl）

## 口径

- `ok` **只认 `scripts/run_gates.py` 的退出码 0**；超时/起不来一律 `ok=false` 并写原因
  —— 没跑成的趟**绝不当绿**（把「没跑成」写成绿，等于把闸二废掉）。
- 记录读不懂 / 没有记录 ⇒ 闸二返回 `False`（fail closed：退回全量）。
- 时间戳一律本机 naive 时间（与 `gates/last.json` 的 `at` 同口径）。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

#: 记录 / 日志目录（`gates/diag/*` 已被 `.gitignore` 忽略，产物不入库）。
RUNS_REL = Path("gates") / "diag" / "nightly"
#: 通知流（每趟一行）。
NOTIFY_REL = Path("gates") / "diag" / "notifications.jsonl"
#: 闸二的时效上限。
MAX_AGE_HOURS = 24.0
#: 一趟全量的硬超时（秒）—— 云机实测约 13 min，给足余量；超时当红。
DEFAULT_TIMEOUT = 7200


def runs_dir(root: Path | None = None) -> Path:
    """记录目录（不存在就建）。"""
    base = Path(root) if root is not None else ROOT
    path = base / RUNS_REL
    path.mkdir(parents=True, exist_ok=True)
    return path


def record_name(now: dt.datetime | None = None) -> str:
    at = now or dt.datetime.now()
    return f"nightly-{at.strftime('%Y%m%d-%H%M%S')}.json"


def record_paths(root: Path | None = None) -> list[Path]:
    """现有记录（按文件名排序 = 按时间排序）。"""
    base = Path(root) if root is not None else ROOT
    return sorted((base / RUNS_REL).glob("nightly-*.json"))


def write_record(record: dict[str, Any], root: Path | None = None) -> Path:
    """写一条记录（`nightly-*.json`）；返回落盘路径。"""
    name = str(record.get("record") or "") or record_name()
    path = runs_dir(root) / Path(name).name
    path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return path


def append_notification(record: dict[str, Any], root: Path | None = None) -> Path:
    """追加一行通知（jsonl）；返回文件路径。"""
    base = Path(root) if root is not None else ROOT
    path = base / NOTIFY_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    line = {
        "at": record.get("at"),
        "kind": "nightly",
        "ok": bool(record.get("ok")),
        "rev": record.get("rev", ""),
        "exit_code": record.get("exit_code"),
        "record": record.get("record", ""),
        "note": record.get("note", ""),
    }
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    return path


def _parse_at(raw: Any) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None


def latest_record(root: Path | None = None) -> dict[str, Any] | None:
    """最近一次记录（按 `at` 取最大；读不懂的条目跳过，但不把它们当绿）。"""
    best: dict[str, Any] | None = None
    best_at: dt.datetime | None = None
    for path in record_paths(root):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        at = _parse_at(data.get("at"))
        if at is None:
            continue
        if best_at is None or at > best_at:
            best, best_at = data, at
    return best


def _same_tree(a: str, b: str) -> bool:
    """两个路径是不是同一棵树（Windows 上大小写不敏感、正反斜杠都算同一棵树）。"""

    def norm(raw: object) -> str:
        return str(raw or "").replace(chr(92), "/").rstrip("/").lower()

    na, nb = norm(a), norm(b)
    return bool(na) and na == nb


def _head_and_tree(base: Path) -> tuple[str, str]:
    """当前 HEAD 短提交 + 本树根（读不到就给空串，调用方 fail closed）。"""
    rc, out = _git(["rev-parse", "--short", "HEAD"], base)
    head = out.strip() if rc == 0 else ""
    rc, out = _git(["rev-parse", "--show-toplevel"], base)
    top = out.strip() if rc == 0 else ""
    return head, top


def recent_full_ok(
    root: Path | None = None, *, now: dt.datetime | None = None, hours: float = MAX_AGE_HOURS
) -> tuple[bool, str]:
    """闸二：最近一次夜间全量**绿**是否在 `hours` 小时以内。返回 `(够不够, 一句话原因)`。"""
    moment = now or dt.datetime.now()
    record = latest_record(root)
    if record is None:
        return False, "没有夜间全量记录（gates/diag/nightly/nightly-*.json 一份都没有）"
    at = _parse_at(record.get("at"))
    if at is None:
        return False, f"最近一份夜间记录的时间戳读不懂：{record.get('at')!r}"
    age = (moment - at).total_seconds() / 3600.0
    if age < 0:
        age = 0.0
    if not record.get("ok"):
        return False, (
            f"最近一次夜间全量是**红的**（at={record.get('at')}，"
            f"exit={record.get('exit_code')}，{age:.1f} 小时前）"
        )
    if age > hours:
        return False, f"最近一次夜间全量绿是 {age:.1f} 小时前（上限 {hours:g}h）"
    # ★ 卡 E63（T-AG521）判据 4：记录必须说清「哪棵树的哪个提交」——
    #   老闸二只看 at / ok，于是三天前旧提交上跑绿的记录、甚至从云机 scp 回来的记录，
    #   都能给今天这棵新树开绿灯。判不出来源就**当没有记录**（fail closed），不许猜。
    base = Path(root) if root is not None else ROOT
    head, top = _head_and_tree(base)
    rev = str(record.get("rev") or "").strip()
    if not rev:
        return False, (
            f"最近一份夜间记录没有 rev（判不出是哪一笔的读数 ⇒ 当没有记录；"
            f"at={record.get('at')}）"
        )
    if not head:
        return False, f"读不到当前 HEAD（{base}）⇒ 没法核对夜间记录的 rev={rev}（fail closed）"
    if rev != head:
        return False, (
            f"最近一次夜间全量的 rev 对不上：记录 rev={rev}，当前 HEAD={head}"
            "（旧提交上跑绿的记录不许给新树开绿灯）"
        )
    tree = str(record.get("tree") or "").strip()
    if not tree:
        return False, (
            f"最近一份夜间记录没有 tree（判不出是哪棵树跑的 ⇒ 当没有记录；"
            f"at={record.get('at')}）"
        )
    if not top:
        return False, f"读不到本树根（{base}）⇒ 没法核对夜间记录的 tree={tree}（fail closed）"
    if not _same_tree(tree, top):
        return False, (
            f"最近一次夜间全量是**别的树**跑的（记录 tree={tree}，本树 {top}）"
            "—— 跨树结论不算本树全量"
        )
    return True, f"最近一次夜间全量绿于 {record.get('at')}（{age:.1f} 小时前）"


def _git(args: list[str], cwd: Path) -> tuple[int, str]:
    done = subprocess.run(  # noqa: S603 —— 参数写死，无 shell
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def run_once(
    root: Path | None = None,
    *,
    now: dt.datetime | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """在**独立 worktree** 里真跑一趟全量，写记录 + 通知，返回记录（不删记录）。

    ★ 起不来 / 超时 ⇒ `ok=false`、`note` 写清原因 —— 没跑成的趟绝不当绿。
    """
    base = Path(root) if root is not None else ROOT
    at = now or dt.datetime.now()
    name = record_name(at)
    slug = name[:-5].replace("nightly-", "")
    folder = runs_dir(base)
    wt = folder / f"wt-{slug}"
    log = folder / f"{name[:-5]}.log"
    record: dict[str, Any] = {
        "at": at.isoformat(timespec="seconds"),
        "record": name,
        "rev": "",
        "tree": "",
        "ok": False,
        "exit_code": None,
        "seconds": 0.0,
        "worktree": str(wt),
        "log": str(log),
        "note": "",
    }
    rc, _ = _git(["rev-parse", "--verify", "HEAD"], base)
    if rc != 0:
        record["note"] = "读不到 git HEAD"
        write_record(record, base)
        append_notification(record, base)
        return record
    record["rev"] = _git(["rev-parse", "--short", "HEAD"], base)[1].strip()
    # ★ 卡 E63：记录里必须写明**是哪棵树**跑的（闸二 `recent_full_ok()` 要核这一条）。
    record["tree"] = _git(["rev-parse", "--show-toplevel"], base)[1].strip() or str(base)

    if wt.exists():
        _git(["worktree", "remove", "--force", str(wt)], base)
    rc, out = _git(["worktree", "add", "--detach", str(wt), "HEAD"], base)
    if rc != 0:
        record["note"] = f"建独立 worktree 失败（{out.strip()[:200]}）"
        write_record(record, base)
        append_notification(record, base)
        return record

    started = dt.datetime.now()
    try:
        env = {**os.environ, "PYTHONUTF8": "1"}
        with log.open("w", encoding="utf-8", newline="\n") as fh:
            try:
                done = subprocess.run(  # noqa: S603 —— 参数写死，无 shell
                    [sys.executable, "-X", "utf8", "scripts/run_gates.py"],
                    cwd=str(wt),
                    env=env,
                    stdout=fh,
                    stderr=subprocess.STDOUT,
                    check=False,
                    timeout=timeout,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                record["exit_code"] = int(done.returncode)
                record["ok"] = done.returncode == 0
                record["note"] = "全量门禁绿" if record["ok"] else "全量门禁红"
            except subprocess.TimeoutExpired:
                record["exit_code"] = 124
                record["note"] = f"超时 {timeout:.0f}s 被掐（ok=false，绝不当绿）"
    finally:
        record["seconds"] = round((dt.datetime.now() - started).total_seconds(), 2)
        _git(["worktree", "remove", "--force", str(wt)], base)
        write_record(record, base)
        append_notification(record, base)
    return record


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="夜间全量记录（卡 E51 / E36；不做系统计划任务）")
    ap.add_argument("--run", action="store_true", help="真跑一趟全量（默认动作）")
    ap.add_argument("--status", action="store_true", help="只打印闸二判定（不跑门禁）")
    ap.add_argument("--root", default=None, help="仓库根（默认本文件上一级）")
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="门禁硬超时（秒）")
    a = ap.parse_args(argv)
    base = Path(a.root) if a.root else ROOT
    if a.status:
        ok, why = recent_full_ok(base)
        print(("[OK ] " if ok else "[FAIL] ") + why)
        return 0 if ok else 1
    record = run_once(base, timeout=a.timeout)
    print(
        f"[夜间] {record['record']}  ok={record['ok']}  exit={record['exit_code']}  "
        f"{record['seconds']}s  rev={record['rev']}"
    )
    print(f"  记录：{record['record']}  日志：{record['log']}")
    if record["note"]:
        print(f"  {record['note']}")
    return 0 if record["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
