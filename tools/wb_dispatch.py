r"""派活给 WorkBuddy / CodeBuddy CLI（外包链路的第 ② 步）—— 带四道前置检查。

为什么要有它（2026-09-26，T-G82）：派活是**别人替我改工作区**的动作，手工敲命令有三个坑，
三个都真发生过或真会咬：
  ① 在**脏工作区**里派活 → 工人和我的未提交改动混在一起分不清（"一写一读"当场失效）；
  ② **没登录**就派 → 白等一轮，只拿到一句 `Authentication required`（T-G80 实测）；
  ③ 派活不留痕 / 覆盖上一轮的 log → 之后没人说得清它到底干了什么。

所以这个脚本把四道检查放在**真跑之前**，任何一道不过就**不派活**并说清原因：
  ① `--spec` 指的卡规格文件必须存在（不许凭记忆派活）；
  ② `git status --porcelain -uno` 必须**空**（未跟踪文件不算，那两个是别的窗口放的）；
  ③ 轻量登录自检（真发一条极短请求，认出 `Authentication required`）；
  ④ `gates/diag/wb-<卡号>.jsonl` 不存在（要覆盖得显式 `--force`，证据不许被悄悄盖掉）。

用法（默认 **dry-run**：只打印将要执行的命令，不派活）：
    python -X utf8 tools/wb_dispatch.py --card 001 --spec 复盘/外包卡-001-独立复核T-G79.md
    # 真想派活加 --execute；跑完会自动用 tools/wb_status.py 渲染时间线
    # --model 默认 deepseek-v4.1-flash（用户 2026-09-26 要的那一档；★ CLI 2.158.0 的可用列表里
    # 已经没有 deepseek-v3-2-volc 了 —— 默认模型是 hy4-preview，实测 JSON 里回的是 hy4-preview-f）
    # --cli 覆盖 CLI 入口；--permission-mode 默认 bypassPermissions（见下）
    # --no-preflight 跳过登录自检（省 10 秒，接口不改）

★ 2026-09-26 实测两条（都写进 复盘/外包-卡表与规矩.md §10）：
  · **CLI 入口优先独立安装的那份**（`%APPDATA%` 下 npm 装的 `@tencent-ai/codebuddy-code`）——
    WorkBuddy 自带那份是**无头版**：缺 `dist/codebuddy.js`（TUI），`config`/`doctor`/`install`
    全报 `Cannot find module '../dist/codebuddy'`，也没有 `/login` 可敲；
  · **`-y` 不够**：工人要用 `python …` 跑测试时会被"非交互无法确认"挡回来（它自己提示改用
    `--permission-mode bypassPermissions`）→ 这是默认值；想收紧就显式给别的模式。

★ 边界（如实写）：`--execute` 那条路**还没在真登录下跑过**（CLI 未登录，T-G80/T-G82 如实记）——
现在被验证过的是四道前置检查与命令拼装（`tests/test_wb_dispatch.py`）。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import wb_status  # noqa: E402 —— 同一个目录，渲染复用状态器（别写第二份）

DEFAULT_MODEL = "deepseek-v4.1-flash"
NODE_REL = r".workbuddy\binaries\node\versions\22.22.2-3\node.exe"
# ★ 优先用**独立安装**的 CodeBuddy CLI（官方 npm 包，带 TUI、能登录）：
#   WorkBuddy 自带那份是**无头版**（缺 dist/codebuddy.js，`config`/`doctor`/`install` 全废、
#   也没有 `/login` 可敲）—— 2026-09-26 实测，见 复盘/外包-卡表与规矩.md §10。
NPM_CLI_PARTS = ("npm", "node_modules", "@tencent-ai", "codebuddy-code", "bin", "codebuddy")
FALLBACK_CLI_REL = r"workbuddy\resources\app.asar.unpacked\cli\bin\codebuddy"
# 工人要跑 pytest / 脚本，`-y` 不够（实测 `python …` 会被"非交互无法确认"挡回来）
DEFAULT_PERMISSION_MODE = "bypassPermissions"
AUTH_NEEDLE = "Authentication required"

OPENING = (
    "读 复盘/交接-重构进度.md + 复盘/长任务执行协议.md + 复盘/新窗口交接卡.md + "
    "复盘/外包-卡表与规矩.md + {spec}（这一张卡的规格）。你有完整 CLI、工具链与主控相同。"
    "★ **以卡规格为准**：它写了这一轮能改哪些文件、能不能提交、要不要跑全量门禁、禁区是什么；"
    "规格与本句冲突时，按规格执行。干完按规格要求回报。卡号 {card}。"
)


def paths(cli_override: str | None = None) -> tuple[Path, Path]:
    """（内置 node, CLI 入口）—— 默认优先独立安装的那份，找不到才退回 WorkBuddy 自带的。"""
    home = Path(os.environ.get("USERPROFILE", str(Path.home())))
    node = home / NODE_REL
    if cli_override:
        return node, Path(cli_override)
    appdata = Path(os.environ.get("APPDATA", str(home / "AppData" / "Roaming")))
    npm_cli = appdata.joinpath(*NPM_CLI_PARTS)
    if npm_cli.exists():
        return node, npm_cli
    return node, Path("D:/") / FALLBACK_CLI_REL


def git_dirty() -> list[str]:
    """被跟踪文件里有没有未提交改动（未跟踪文件不算：那两个是别的窗口放的）。"""
    done = subprocess.run(
        ["git", "status", "--porcelain", "-uno"],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return [ln for ln in (done.stdout or "").splitlines() if ln.strip()]


def auth_ok(node: Path, cli: Path, timeout: int = 180) -> tuple[bool, str]:
    """真发一条极短请求 —— 登录没通就当场认出来（别把一轮白等当成"工人在想"）。"""
    done = subprocess.run(
        [str(node), str(cli), "-p", "只回复四个字：连接成功", "--output-format", "text",
         "--no-session-persistence", "-y"],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=timeout,
    )
    body = f"{done.stdout or ''}\n{done.stderr or ''}"
    if AUTH_NEEDLE in body:
        return False, "登录没通（Authentication required）→ 先在 TUI 里敲 /login（T-G80）"
    if "连接成功" in body:
        return True, "登录自检通过"
    return False, f"自检没拿到预期回话（退出码 {done.returncode}）：{wb_status._clip(body, 200)}"


def build_command(node: Path, cli: Path, card: str, spec: str, model: str,
                  permission_mode: str = DEFAULT_PERMISSION_MODE) -> list[str]:
    return [
        str(node), str(cli), "-p", OPENING.format(spec=spec, card=card),
        "--model", model, "--output-format", "stream-json",
        "--permission-mode", permission_mode,
        "--no-session-persistence", "-y",
    ]


def preflight(card: str, spec: str, *, force: bool, check_auth: bool,
              cli_override: str | None = None) -> tuple[list[str], Path]:
    """四道检查 —— 返回（问题清单, 日志路径）。问题非空就不许派活。"""
    problems: list[str] = []
    node, cli = paths(cli_override)
    log = ROOT / "gates" / "diag" / f"wb-{card}.jsonl"
    if not (ROOT / spec).exists():
        problems.append(f"卡规格文件不存在：{spec}（不许凭记忆派活）")
    if not node.exists():
        problems.append(f"找不到内置 node：{node}")
    if not cli.exists():
        problems.append(f"找不到 CLI：{cli}")
    dirty = git_dirty()
    if dirty:
        problems.append(f"工作区不干净（{len(dirty)} 个被跟踪文件有改动）→ 一写一读："
                        f"先提交或收起它们：{', '.join(dirty[:5])}")
    if log.exists() and not force:
        problems.append(f"这一轮的 log 已存在：{log}（要覆盖请 --force —— 证据不许被悄悄盖掉）")
    if check_auth and not problems:
        ok, why = auth_ok(node, cli)
        if not ok:
            problems.append(why)
    return problems, log


def main() -> int:
    parser = argparse.ArgumentParser(description="派活给 CodeBuddy CLI（默认 dry-run）")
    parser.add_argument("--card", required=True, help="卡号（用来命名 log，如 001）")
    parser.add_argument("--spec", required=True, help="卡规格文件（相对仓库根）")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--cli", default=None,
                        help="CLI 入口覆盖（默认优先用独立安装的那份）")
    parser.add_argument("--permission-mode", default=DEFAULT_PERMISSION_MODE,
                        help="工人的权限模式（默认 bypassPermissions：否则 python 会被挡回来）")
    parser.add_argument("--execute", action="store_true",
                        help="真派活（默认只做前置检查 + 打印命令）")
    parser.add_argument("--force", action="store_true", help="允许覆盖已有 log")
    parser.add_argument("--no-preflight", action="store_true", help="跳过登录自检")
    parser.add_argument("--timeout", type=int, default=3600, help="工人最长跑多久（秒）")
    args = parser.parse_args()

    problems, log = preflight(
        args.card, args.spec, force=args.force, check_auth=not args.no_preflight,
        cli_override=args.cli,
    )
    node, cli = paths(args.cli)
    cmd = build_command(node, cli, args.card, args.spec, args.model, args.permission_mode)

    if problems:
        print("[FAIL] 不派活 —— 前置检查没过：", file=sys.stderr)
        for item in problems:
            print(f"  · {item}", file=sys.stderr)
        return 2

    done_checks = "规格在 / 工作区干净 / log 未占用"
    if args.no_preflight:
        done_checks += " / **登录没查**（--no-preflight）"
    else:
        done_checks += " / 登录通"
    print(f"[OK ] 前置检查全过（{done_checks}）")
    print(f"[log ] {log}")
    print(f"[cmd ] {' '.join(cmd[:4])} … --model {args.model} --output-format stream-json "
          f"--permission-mode {args.permission_mode}")
    if not args.execute:
        print("[dry ] 这是 dry-run；真想派活加 --execute")
        return 0

    errlog = log.with_suffix(".stderr.txt")
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as out, errlog.open("w", encoding="utf-8") as err:
        done = subprocess.run(cmd, cwd=str(ROOT), stdout=out, stderr=err, timeout=args.timeout)
    print(f"[done] 工人退出码 {done.returncode}；stderr 见 {errlog.name}")
    lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    timeline, summary = wb_status.parse_events(lines)
    for line in timeline:
        print(line)
    print(f"[摘要] 工具调用 {summary['tool_calls']} 次；"
          f"碰过的文件 {summary['files_total']} 个；"
          f"认不出的行 {summary['unknown_events']} 条")
    print(f"[复核] 主控现在去看报告与 git status：python -X utf8 tools/wb_status.py {log} --repo")
    return 0 if done.returncode == 0 else 4


if __name__ == "__main__":
    raise SystemExit(main())
