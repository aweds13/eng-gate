r"""主控复核器（外包链路的第 ④ 步）：一条命令把"这一笔提交算不算数"的判据全过一遍。

为什么要有它（2026-09-26，T-G84）：外包之后，主控每轮都要复核工人的提交。手工复核有五件事
（audit 过不过 / 四个 trailer 全不全 / 门禁是不是**为这一笔**真跑过 / 改动越界没有 /
工作区干不干净），每次现查既慢又容易漏 —— 而"漏一条"的代价是**把没验过的东西当验过了**。

它判的五条（每条都对应本项目已写明的规矩）：

  ① **audit**：`scripts/audit_progress.py` 真跑一遍，退出码 0，且 **豁免 0**
     （`[exceptions]` 保持空）；
  ② **trailers**：`Task:` **恰好一个**台账编号；`Ledger:` 与 `Gates:` 必须在；`Refs:` 可选；
  ③ **门禁是不是为这一笔跑的**：`gates/last.json`（取**这一笔提交里的那一份**）要求
     `ok=true`、`docs_sync_ok=true`、`docs_sync_missing=[]`、每道门 `exit_code=0`，
     且它的 `rev` **等于这一笔的父提交**（★ 最要紧的一条：一次门禁跑完提交两笔，
     第二笔就是"没验过"）；
  ④ **改动越界没有**：`--read-only`（只读卡：**一个被跟踪文件都不许改**）或
     `--allow <glob>` 白名单；
  ⑤ **工作区干不干净**：复核时 `git status --porcelain -uno` 必须空
     （工人不许留没提交的改动）。

用法：
    python -X utf8 tools/wb_review.py --rev HEAD --read-only
    python -X utf8 tools/wb_review.py --rev HEAD --allow "src/**" --allow "tests/**"
    python -X utf8 tools/wb_review.py --rev HEAD --allow "**" --json

退出码：0 全过 / 1 有不过的（逐条打印为什么）/ 2 参数或 git 取不到。

★ 边界（如实写）：`gates/last.json` 的 `tree` 字段**故意不查** —— 它自己也在那棵树里（自指悖论），
`scripts/run_gates.py` 里写明"审计不看它"；这里只查 `rev`（父提交）与各门结论。
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASK_RE = re.compile(r"^Task:\s*(\S+)\s*$", re.M)


def git(*args: str) -> str:
    """跑一条 git 命令。★ `-c core.quotepath=false`：中文路径不许被转义成 `\\345\\244...`，
    否则第 ④ 条的白名单会**把中文路径全判成越界**（T-G84 实测踩到）。"""
    done = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args], cwd=str(ROOT), capture_output=True,
        text=True, encoding="utf-8", errors="replace",
    )
    return (done.stdout or "").strip()


def check_trailers(body: str) -> tuple[list[str], dict[str, str]]:
    """② trailer 规矩：`Task:` 恰好一个 + `Ledger:`/`Gates:` 必须在（`Refs:` 可选）。"""
    problems: list[str] = []
    tasks = TASK_RE.findall(body)
    found: dict[str, str] = {"Task": ", ".join(tasks)}
    if len(tasks) != 1:
        problems.append(f"`Task:` 必须恰好一个台账编号，现在是 {len(tasks)} 个：{tasks}")
    for key in ("Ledger", "Gates"):
        m = re.search(rf"^{key}:\s*(\S.*)$", body, re.M)
        if not m:
            problems.append(f"缺 `{key}:` trailer（提交信息末尾那四行之一）")
        else:
            found[key] = m.group(1).strip()
    return problems, found


def check_gate_evidence(payload: dict, parent_short: str) -> list[str]:
    """③ 门禁是不是**为这一笔**跑的 —— `rev` 必须等于这一笔的父提交。"""
    problems: list[str] = []
    if payload.get("ok") is not True:
        problems.append(f"gates/last.json 的 ok 不是 true：{payload.get('ok')!r}")
    if payload.get("rev") != parent_short:
        problems.append(
            f"门禁不是为这一笔跑的：last.json 的 rev={payload.get('rev')!r}，"
            f"而这一笔的父提交是 {parent_short!r}（★ 一次门禁跑完提交两笔？第二笔没验过）"
        )
    if payload.get("docs_sync_ok") is not True or payload.get("docs_sync_missing"):
        problems.append(
            f"台账/交接数字没同步：docs_sync_ok={payload.get('docs_sync_ok')!r}，"
            f"missing={payload.get('docs_sync_missing')!r}"
        )
    bad = [g for g in payload.get("gates", []) if g.get("exit_code") != 0]
    if bad:
        problems.append(f"有门没过：{[g.get('name') for g in bad]}")
    if not payload.get("gates"):
        problems.append("gates/last.json 里没有任何门的结果（不是真跑过的产物）")
    return problems


def check_files(files: list[str], *, read_only: bool, allow: list[str]) -> list[str]:
    """④ 改动越界没有：只读卡 = 一个被跟踪文件都不许改；否则按白名单。"""
    if read_only:
        return [f"只读卡不许改被跟踪文件，但它改了 {len(files)} 个：{files[:8]}"] if files else []
    if not allow:
        return ["没有给白名单：复核改动范围请加 `--allow <glob>`（或声明 `--read-only`）"]
    outside = [f for f in files if not any(fnmatch.fnmatch(f, pat) for pat in allow)]
    return [f"有 {len(outside)} 个改动不在白名单里：{outside[:8]}"] if outside else []


def audit_verdict() -> tuple[list[str], str]:
    """① audit 真跑一遍（它是唯一能判"证据对不上"的东西）。"""
    done = subprocess.run(
        [sys.executable, "-X", "utf8", str(ROOT / "scripts" / "audit_progress.py")],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    body = f"{done.stdout or ''}\n{done.stderr or ''}"
    problems: list[str] = []
    if done.returncode != 0:
        tail = [ln for ln in body.splitlines() if ln.strip()][-4:]
        problems.append("audit 没过：" + " | ".join(tail))
    if "豁免 0 项已知欠账" not in body:
        problems.append("audit 里有豁免项（本项目要求 [exceptions] 保持 0）")
    wait = re.search(r"审计通过", body)
    return problems, ("审计通过 ✅" if wait else "审计**未通过**")


def main() -> int:
    parser = argparse.ArgumentParser(description="主控复核：这一笔提交算不算数")
    parser.add_argument("--rev", default="HEAD", help="要复核的提交（默认 HEAD）")
    parser.add_argument("--read-only", action="store_true", help="只读卡：一个被跟踪文件都不许改")
    parser.add_argument("--allow", action="append", default=[], help="允许改动的 glob（可重复）")
    parser.add_argument("--branch", default="line/impl-v1", help="期望所在分支")
    parser.add_argument("--dirty-ok", action="store_true", help="允许工作区有未提交改动")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    sha = git("rev-parse", "--short", args.rev)
    if not sha:
        print(f"[FAIL] 取不到提交：{args.rev}", file=sys.stderr)
        return 2
    parent = git("rev-parse", "--short", f"{sha}^")
    body = git("log", "-1", "--format=%B", sha)
    files = [f for f in git("show", "--name-only", "--format=", sha).splitlines() if f.strip()]
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    dirty = [ln for ln in git("status", "--porcelain", "-uno").splitlines() if ln.strip()]

    problems: list[str] = []
    audit_problems, audit_line = audit_verdict()
    problems += audit_problems
    trailer_problems, trailers = check_trailers(body)
    problems += trailer_problems
    try:
        payload = json.loads(git("show", f"{sha}:gates/last.json"))
    except json.JSONDecodeError:
        payload = {}
        problems.append("这一笔里没有 gates/last.json（门禁产物没跟着提交）")
    problems += check_gate_evidence(payload, parent)
    problems += check_files(files, read_only=args.read_only, allow=args.allow)
    if branch != args.branch:
        problems.append(f"分支不对：现在在 {branch!r}，期望 {args.branch!r}")
    if dirty and not args.dirty_ok:
        problems.append(f"工作区有没提交的改动（{len(dirty)} 个）：{dirty[:5]}")

    verdict = {
        "rev": sha, "parent": parent, "branch": branch,
        "files": files, "trailers": trailers, "audit": audit_line,
        "gates_ok": payload.get("ok"), "gates_rev": payload.get("rev"),
        "problems": problems,
    }
    if args.json:
        print(json.dumps(verdict, ensure_ascii=False, indent=2))
        return 0 if not problems else 1

    print(f"=== 复核 {sha}（父提交 {parent}，分支 {branch}）===")
    print(f"  ① audit：{audit_line}")
    print(f"  ② trailer：{trailers.get('Task', '(缺)')}")
    print(f"  ③ 门禁：ok={payload.get('ok')} rev={payload.get('rev')}"
          f"（这一笔的父提交 {parent}）+ {len(payload.get('gates', []))} 道门")
    print(f"  ④ 这一笔改了 {len(files)} 个文件：" + ("、".join(files[:6]) or "（一个都没改）"))
    print(f"  ⑤ 工作区未提交改动：{len(dirty)} 个")
    if problems:
        print(f"\n[FAIL] {len(problems)} 条不过 —— **这一笔不算数**：")
        for item in problems:
            print(f"  · {item}")
        return 1
    print("\n[OK ] 五条全过：这一笔算数（台账证据对得上、门禁是为它跑的、改动没越界）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
