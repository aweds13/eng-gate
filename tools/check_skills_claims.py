"""技能正文里的命令引用 ↔ `tools/` 源码对账（卡 G1 / T-AG456）。

**为什么要有它**：`tests/test_check_skills.py` 只查技能目录的**结构**（行数、流程数、
结果项指针、NOTES 三节），正文里那些 `python -X utf8 tools/<x>.py --flag` 从没被机器核过。
工具改名 / 参数退役时技能照旧写着旧写法，只有人照着敲、被 argparse 拒单才发现。

**只造尺子**：本模块**不改**任何技能正文（那是卡 G2 的活）。

## 扫描口径

- 只扫 `skills/**/*.md` 里**围栏代码块**与**行内反引号**中的内容，正文散文不算。
- 只认 `python -X utf8 tools/<x>.py <args>`；`<x>` 必须落在 `tools/` 下
  （`scripts/` / `framework/` 的引用不在本尺子的域内）。
- 围栏块里行尾 `\\` 是续行，续行拼成同一条命令再核；`#` 之后是注释，不算参数。

## 两项核对

1. `tools/<x>.py` **存在**；
2. 每个 `--flag`（`--flag=value` 取等号前）在该工具源码里以 `"--flag"` / `'--flag'`
   或 `--flag=` 的形式出现过（即它真被 `add_argument` 之类注册过）。

★ 「该工具源码」= `tools/<x>.py` **加上它真正转发的本地模块**（`from pool import landing`
这类壳：真 argparse 在 `tools/pool/landing.py`）。跟着 import 走一层两层，不然薄壳会全判红。

## 判不出来要明说（不许猜成通过）

一条命令里出现占位/重定向 —— `<卡号>`、`$VAR`、`|`、`>`、`...`、`*` —— 时，
仍然核工具存在性与 flag 名，**但整条记 `not verified`** 并计入汇总；它**不算**「对得上」。

## 豁免

要放行的条目写进下面 `EXEMPT`（`"skills/x.md:12" -> 理由`）。**空理由算红** ——
豁免是给人看的账，不是让门变绿的开关。

## 两个档位（`--mode`，与 `scripts/check_docs.py` 同一惯例）

`--mode` 只改**退码**，不改判据：`scan()` 与 `Report` 的口径一个字都没动 ——
「判不出」永远不算「对得上」。

- `--mode block`（**默认**，三态）：`0` 判完且干净 / `1` 有对不上 / `3` 没判完；
- `--mode report`：**只有真「对不上」才退 `1`**；判不出退 `0`，但读数照打
  （`对不上 N / 判不出 M`），末行打 `[DEBT]` 而**不是** `[OK  ]` —— 有债不红，但债看得见。
  为什么需要这一档：技能正文里 `<卡号>` / `<文件>` / `...` / `tools/wb_*.py` 这类占位符与
  通配名是**指令文档的固有形态**，压不到 0 条；block 档会让每趟门禁都红。

## 退出码（三态，与 `scripts/check_docs.py` 同一惯例）

- `0` —— 判完且干净：每条引用都对得上；
- `1` —— 有「对不上」：逐条点 `文件:行` 与工具/参数名。**压过 `3`**（红比没判完更急）；
- `3` —— 没有对不上，但有条目**判不出**（`not verified`）。★ 它**不是**通过：
  这些条目在结构上看不见，比没有门更糟。门禁侧 `exit 3` 记「没判完」，
  既不算绿也不算红 —— 于是「判不出」不会被悄悄洗成「对得上」。
  （只有 `--mode block` 会退 `3`；`--mode report` 下这个数照样出现在汇总行与 `[DEBT]` 行里，
  一条都不许省略。）

改前这里只分两态（`1` / `0`），72 条 `not verified` 与全绿退同一个 `0`，
等于把「我没判」和「我判过了、没问题」写进同一个码里。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: 需要放行的条目：`"skills/<路径>:<行号>" -> 理由`。空理由算红。
EXEMPT: dict[str, str] = {}

#: `python -X utf8 tools/<x>.py`，`<x>` 允许带 `*`（通配的命令只能记 not verified）。
PY_REF = re.compile(r"python(?:\.exe)?\s+-X\s+utf8\s+tools/(?P<name>[^\s`]+?\.py)")

#: 占位 / 重定向：出现即「这条命令有一半判不出来」。
PLACEHOLDER = re.compile(r"<[^<>\n]+>|\$[A-Za-z_]\w*|\||>|\.\.\.|…|\*")

#: flag 名允许的字符（`--json`。这种后面粘着标点的写法要截断）。
FLAG_CHARS = re.compile(r"[A-Za-z0-9_-]+")

#: `from a.b import c, d` / `import a.b` —— 用来跟到薄壳背后真正的 argparse。
IMPORT_RE = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import\s+([^#\n]+)|import\s+([\w.]+))", re.M)

#: 跟 import 的最大深度（壳 → `pool.landing` → `pool.xxx`）。
IMPORT_DEPTH = 2

STATUS_OK = "ok"
STATUS_FAIL = "fail"
STATUS_NOT_VERIFIED = "not verified"


@dataclass
class Claim:
    """一处引用：`文件:行` + 工具 + 该命令上的 flag + 判定结果。"""

    path: str
    line: int
    tool: str
    command: str
    flags: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    unverifiable: list[str] = field(default_factory=list)
    exempt_reason: str = ""

    @property
    def status(self) -> str:
        if self.problems and not self.exempt_reason:
            return STATUS_FAIL
        if self.exempt_reason:
            return STATUS_OK
        if self.unverifiable:
            return STATUS_NOT_VERIFIED
        return STATUS_OK

    @property
    def key(self) -> str:
        return f"{self.path}:{self.line}"


@dataclass
class Report:
    """一次扫描的账：引用总数 / 对得上 / 对不上 / 判不出 / 豁免 / 逐条明细。"""

    claims: list[Claim] = field(default_factory=list)
    unused_exempt: list[str] = field(default_factory=list)

    def _by(self, status: str) -> list[Claim]:
        return [c for c in self.claims if c.status == status]

    @property
    def total(self) -> int:
        return len(self.claims)

    @property
    def ok(self) -> int:
        return len(self._by(STATUS_OK))

    @property
    def failed(self) -> list[Claim]:
        return self._by(STATUS_FAIL)

    @property
    def not_verified(self) -> list[Claim]:
        return self._by(STATUS_NOT_VERIFIED)

    @property
    def exempted(self) -> int:
        return sum(1 for c in self.claims if c.exempt_reason)

    def counts(self) -> dict[str, int]:
        return {
            "total": self.total,
            "ok": self.ok,
            "failed": len(self.failed),
            "not_verified": len(self.not_verified),
            "exempted": self.exempted,
        }

    def summary_line(self) -> str:
        c = self.counts()
        return (
            f"引用 {c['total']} 处 / 对得上 {c['ok']} / 对不上 {c['failed']}"
            f" / 判不出 {c['not_verified']} / 豁免 {c['exempted']}"
        )

    def to_json(self) -> dict[str, object]:
        return {
            **self.counts(),
            "unused_exempt": self.unused_exempt,
            "items": [
                {
                    "path": c.path,
                    "line": c.line,
                    "tool": c.tool,
                    "command": c.command,
                    "flags": c.flags,
                    "status": c.status,
                    "problems": c.problems,
                    "unverifiable": c.unverifiable,
                    "exempt_reason": c.exempt_reason,
                }
                for c in self.claims
            ],
        }


def iter_regions(text: str) -> list[tuple[int, str]]:
    """切出「可执行文本」：围栏代码块整块一条，其余按行内反引号一段一段。

    返回 `(首行行号, 文本)`；散文（非反引号、非围栏）一律不返回 —— 那是描述，不是命令。
    首行行号是 `文本` 第一行在文件里的行号（围栏块 = 开栏那行的**下一行**）。
    """
    regions: list[tuple[int, str]] = []
    fence: list[str] | None = None
    fence_start = 0
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            if fence is None:
                fence = []
                fence_start = lineno + 1
            else:
                regions.append((fence_start, "\n".join(fence)))
                fence = None
            continue
        if fence is not None:
            fence.append(line)
            continue
        for span in re.findall(r"`([^`]+)`", line):
            regions.append((lineno, span))
    if fence is not None:  # 未闭合的围栏：照样核，别静默丢
        regions.append((fence_start, "\n".join(fence)))
    return regions


def _cut_command(args: str) -> str:
    """截到这条命令的末尾：围栏里的续行拼起来，非续行的换行与 `#` 注释都截断。"""
    parts: list[str] = []
    for raw in args.split("\n"):
        body = raw.split(" #")[0].strip()
        continued = body.endswith("\\")
        parts.append(body[:-1].strip() if continued else body)
        if not continued:
            break
    return " ".join(p for p in parts if p)


def _flags_of(command: str) -> list[str]:
    """取命令里的 `--flag` 名（去重、保序、`--flag=value` 取等号前）。"""
    out: list[str] = []
    for token in command.split():
        token = token.strip("`'\"")
        if not token.startswith("--") or len(token) <= 2:
            continue
        body = token.split("=", 1)[0]
        match = FLAG_CHARS.match(body[2:])
        name = "--" + match.group(0) if match else ""
        if len(name) > 2 and name not in out:
            out.append(name)
    return out


def _flag_registered(source: str, flag: str) -> bool:
    """该 flag 是否在源码里注册过（`"--flag"` / `'--flag'` / `--flag=` 三种形态）。"""
    pattern = r"""["']""" + re.escape(flag) + r"""(?:=|["'])"""
    return re.search(pattern, source) is not None


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _resolve_module(tools_root: Path, module: str) -> Path | None:
    """`pool.landing` → `tools/pool/landing.py`（或包目录的 `__init__.py`）。"""
    base = tools_root / Path(*module.split("."))
    for cand in (base.with_suffix(".py"), base / "__init__.py"):
        if cand.is_file():
            return cand
    return None


def _imported_modules(source: str, tools_root: Path) -> list[Path]:
    """源码里 import 到的**本地**模块（落在 `tools/` 下的才算），解析成文件路径。"""
    found: list[Path] = []
    for match in IMPORT_RE.finditer(source):
        base, names, plain = match.group(1), match.group(2), match.group(3)
        candidates = [plain.strip()] if plain else [base]
        if names:
            candidates += [f"{base}.{n.strip().split(' as ')[0]}" for n in names.split(",")]
        for module in candidates:
            if not module or " " in module:
                continue
            path = _resolve_module(tools_root, module)
            if path is not None and path not in found:
                found.append(path)
    return found


def tool_sources(root: Path, name: str) -> dict[Path, str] | None:
    """`tools/<x>.py` 及其转发的本地模块的源码；工具文件不存在 ⇒ `None`。

    薄壳（`from pool import landing as _landing`）把 argparse 放在别处，只看壳会**整行假红**，
    所以按 import 跟 `IMPORT_DEPTH` 层。★ 只跟 `tools/` 下的模块，不跟第三方库。
    """
    tools_root = root / "tools"
    first = tools_root / name
    if not first.is_file():
        return None
    sources: dict[Path, str] = {}
    frontier: list[tuple[Path, int]] = [(first, 0)]
    while frontier:
        path, depth = frontier.pop()
        if path in sources:
            continue
        sources[path] = _read(path)
        if depth >= IMPORT_DEPTH:
            continue
        frontier += [(p, depth + 1) for p in _imported_modules(sources[path], tools_root)]
    return sources


def scan(root: Path, exempt: dict[str, str] | None = None) -> Report:
    """扫 `root/skills/**/*.md`，逐条核对 `root/tools/<x>.py`。"""
    exempt = EXEMPT if exempt is None else exempt
    report = Report()
    hit: set[str] = set()
    skill_files = sorted((root / "skills").rglob("*.md"))
    for md in skill_files:
        rel = md.relative_to(root).as_posix()
        for start_line, text in iter_regions(_read(md)):
            matches = list(PY_REF.finditer(text))
            for idx, match in enumerate(matches):
                end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
                args = _cut_command(text[match.end() : end])
                claim = Claim(
                    path=rel,
                    line=start_line + text[: match.start()].count("\n"),
                    tool=match.group("name"),
                    command=f"python -X utf8 tools/{match.group('name')} {args}".strip(),
                    flags=_flags_of(args),
                )
                _judge(claim, root, exempt, hit)
                report.claims.append(claim)
    report.unused_exempt = sorted(set(exempt) - hit)
    return report


def _judge(claim: Claim, root: Path, exempt: dict[str, str], hit: set[str]) -> None:
    """判一条：工具在不在 → flag 注册没注册 → 有没有判不出的部分 → 有没有豁免。"""
    wildcard = "*" in claim.tool or "…" in claim.tool
    sources = None if wildcard else tool_sources(root, claim.tool)
    if wildcard:
        claim.unverifiable.append(f"工具名是通配（tools/{claim.tool}），点不出是哪个脚本")
    elif sources is None:
        claim.problems.append(f"工具不存在：tools/{claim.tool}")
    else:
        for flag in claim.flags:
            if not any(_flag_registered(src, flag) for src in sources.values()):
                claim.problems.append(f"参数不存在：{flag}（tools/{claim.tool} 里没注册）")

    marker = PLACEHOLDER.search(claim.command)
    if marker:
        claim.unverifiable.append(f"含占位/重定向「{marker.group(0)}」，只核了能核的部分")

    if claim.key in exempt:
        hit.add(claim.key)
        reason = exempt[claim.key].strip()
        if not reason:
            claim.problems.append("豁免没写理由（空理由算红）")
        else:
            claim.exempt_reason = reason


def _label(report: Report, mode: str = "block") -> str:
    """末行前缀：`1` 红 ⇒ FAIL，`3` 没判完 ⇒ WARN，`0` ⇒ OK；report 档有债 ⇒ DEBT。

    ★ 判不出时不许打 `[OK  ]` —— 那行会被当成「这门过了」抄进回话，
    而同一趟的退出码是 3（没判完），自相矛盾。
    ★ `--mode report` 下判不出退 `0`，但**更不许**打 `[OK  ]`（同一个自相矛盾，
    只是换到另一个档位）：有 `not verified` 就打 `[DEBT]` —— 不红，但看得见。
    """
    code = exit_code(report, mode)
    if code == 1:
        return "FAIL"
    if code == 3:
        return "WARN"
    if report.not_verified:
        return "DEBT"
    return "OK  "


def _print_report(report: Report, mode: str = "block") -> None:
    for claim in report.failed:
        print(f"[FAIL] {claim.key}  {claim.command}")
        for problem in claim.problems:
            print(f"       ↳ {problem}")
    for claim in report.not_verified:
        print(f"[WARN] {claim.key}  not verified  {claim.command}")
        for note in claim.unverifiable:
            print(f"       ↳ {note}")
    for claim in report.claims:
        if claim.exempt_reason:
            print(f"[SKIP] {claim.key}  豁免：{claim.exempt_reason}")
    for key in report.unused_exempt:
        print(f"[WARN] 豁免没命中任何引用：{key}（删掉或改对行号）")
    print(f"[{_label(report, mode)}] {report.summary_line()}")
    if mode == "report":
        # ★ 这一行是 report 档的全部理由：不红，但「欠着多少」必须写在脸上。
        print(
            f"report 档读数：对不上 {len(report.failed)} / 判不出 {len(report.not_verified)}"
            " —— 判不出本档不红（技能正文里的占位符/通配名是指令的固有形态），"
            "**这不是 PASS**；`--mode block` 会按三态退码。"
        )
    if report.not_verified and not report.failed:
        tail = (
            "本次退 3「没判完」。"
            if mode != "report"
            else "本次 --mode report 退 0（不阻门），`--mode block` 会退 3「没判完」。"
        )
        print(
            f"★ 上面这 {len(report.not_verified)} 条我判不出 —— 它们**不是**通过"
            f"（结构上看不见，比没有门更糟）；{tail}"
        )


def exit_code(report: Report, mode: str = "block") -> int:
    """三态退出码，与 `scripts/check_docs.py` 同一惯例。

    `1` 压过 `3`：有真漂移就先修漂移，再谈「判不出」。

    `--mode block`（**默认**）：`1` 对不上 / `3` 判不出 / `0` 全绿 —— 三态一个都不少。
    `--mode report`：**只有真「对不上」才退 `1`**；判不出退 `0`。这一档是为门禁开的：
    技能正文里那 73 条 `<卡号>` / `...` / `tools/wb_*.py` 是指令文档的固有形态，
    压不到 0 条，block 档会让每趟门禁都红。★ 退 `0` **不是** PASS ——
    `_print_report` 会把「判不出 N」与 `[DEBT]` 行照打，口径一个字没改。
    """
    if report.failed:
        return 1
    if mode == "report":
        return 0
    if report.not_verified:
        return 3
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="check_skills_claims.py",
        description="技能正文里的 python 命令 ↔ tools/ 源码对账（只读，不改技能）",
    )
    parser.add_argument("--check", action="store_true", help="跑一遍并给判决（默认就是这个行为）")
    parser.add_argument("--json", action="store_true", help="机器可读输出")
    parser.add_argument("--root", default=None, help="仓库根（默认本文件上一级）")
    parser.add_argument(
        "--mode",
        choices=("report", "block"),
        default="block",
        help=(
            "block（默认，三态：1 对不上 / 3 判不出 / 0 全绿）或 "
            "report（只有对不上才退 1；判不出退 0，但读数照打、末行打 [DEBT] 而非 [OK  ]）"
        ),
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve() if args.root else REPO_ROOT
    report = scan(root)
    if args.json:
        print(json.dumps(report.to_json(), ensure_ascii=False, indent=2))
    else:
        _print_report(report, args.mode)
    return exit_code(report, args.mode)


if __name__ == "__main__":
    sys.exit(main())
