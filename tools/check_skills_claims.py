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
import ast
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
    args: str = ""
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
                    args=args,
                )
                _judge(claim, root, exempt, hit)
                report.claims.append(claim)
    report.unused_exempt = sorted(set(exempt) - hit)
    return report


# ---------------------------------------------------------------- 判据 2/3/4（卡 E117）


@dataclass
class ParserFacts:
    """一支 parser 在这份源码里能判出来的东西。

    ★ 只有 required=True **字面量**算必填；required=FLAG 这种取不到的进
    unknown_required，由调用方记「判不出」—— 静默跳过就是把「没判」洗成「判过了」。
    ★ 位置参数**不算**必填（卡 E117 实测）：真仓按位置参数算会多红 27 条正确写法，
    例如 tools/pipeline_view.py --json —— 那个 command 来自它 import 的
    tools/wb_plan.py，跨文件 parser 归属一错就冤枉一片。
    ★ 必填参数要按子命令分账（sub_required）：tools/pool/task.py 里 --reason 属于 waive、
    --to 属于 extend、--commit 属于 landed；合成一张全局表会把每条子命令都判成缺三个参数。
    """

    flags: set[str] = field(default_factory=set)
    required: set[str] = field(default_factory=set)
    sub_required: dict[str, set[str]] = field(default_factory=dict)
    unknown_required: list[str] = field(default_factory=list)
    sub_unknown: dict[str, list[str]] = field(default_factory=dict)
    unknown_flags: bool = False
    subcommands: set[str] | None = None
    has_subparsers: bool = False

    @property
    def judges_anything(self) -> bool:
        """这支 scope 里到底有没有 parser 可判（没有就别拿它判人）。"""
        return bool(self.flags or self.required or self.has_subparsers or self.unknown_flags)

    def required_for(self, subcommand: str | None) -> tuple[set[str], list[str]]:
        """这条命令该满足的必填：子命令自己那份 + 全局那份；取不到的单独回。"""
        need = set(self.required)
        unknown = list(self.unknown_required)
        if subcommand is not None and subcommand in self.sub_required:
            need |= self.sub_required[subcommand]
            unknown += self.sub_unknown.get(subcommand, [])
        return need, unknown


_SKIP_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


def _walk_ordered(node: ast.AST) -> list[ast.AST]:
    """按源码顺序铺平：**不进**嵌套的函数/类/lambda。

    ★ 分作用域是判据的一部分：把 tools/pool/task.py 里各函数复用的 p = sub.add_parser
    合成一张表，实测会多出 181 条假红；把所有 add_parser 并进一张词表，会把
    tools/wb_plan.py 的 22 条引用判成「子命令不存在」。顺序也是判据：
    「p = sub.add_parser(某名字)」之后那些 p.add_argument 才属于那条子命令。
    """
    out: list[ast.AST] = []
    stack: list[ast.AST] = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, _SKIP_NODES) and current is not node:
            continue
        out.append(current)
        stack.extend(reversed(list(ast.iter_child_nodes(current))))
    return out


def _literal_str(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _str_seq(node: ast.AST | None) -> list[str]:
    """(“a”, “b”) / [“a”] 这种字面量序列 ⇒ 名字表；取不全就回空。"""
    if not isinstance(node, ast.Tuple | ast.List | ast.Set):
        return []
    out: list[str] = []
    for item in node.elts:
        text = _literal_str(item)
        if text is None:
            return []
        out.append(text)
    return out


def _keyword(call: ast.Call, name: str) -> ast.AST | None:
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _add_subcommand(
    node: ast.AST, loop_vars: dict[str, list[str]], facts: ParserFacts
) -> str | None:
    """读一条 sub.add_parser(...)：登记词表，并回它绑定的子命令名字（取不全 ⇒ None）。"""
    facts.has_subparsers = True
    names: list[str] = []
    if isinstance(node, ast.Call) and node.args:
        single = _literal_str(node.args[0])
        names = [single] if single else _str_seq(node.args[0])
        if not names and isinstance(node.args[0], ast.Name):
            names = loop_vars.get(node.args[0].id, [])
    if facts.subcommands is None:
        facts.subcommands = set()
    if not names:
        facts.subcommands = None  # 词表取不全 ⇒ 这支 scope 不判子命令
        return None
    facts.subcommands |= set(names)
    return names[0] if len(names) == 1 else None


def _read_add_argument(call: ast.Call, facts: ParserFacts, sub: str | None) -> None:
    """读一条 add_argument(...)：flag / 必填 / 取不到 required / 位置参数的 choices。"""
    if not call.args:
        facts.unknown_flags = True
        return
    name = _literal_str(call.args[0])
    if name is None:
        facts.unknown_flags = True
        return
    facts.flags.add(name)
    if not name.startswith("-"):
        choices = _str_seq(_keyword(call, "choices"))
        if choices:
            facts.has_subparsers = True
            bucket = set(choices)
            facts.subcommands = bucket if facts.subcommands is None else facts.subcommands | bucket
        return
    for kw in call.keywords:
        if kw.arg != "required":
            continue
        if isinstance(kw.value, ast.Constant) and kw.value.value is False:
            continue
        mandatory = isinstance(kw.value, ast.Constant) and kw.value.value is True
        if sub is None:
            if mandatory:
                facts.required.add(name)
            else:
                facts.unknown_required.append(name)
        elif mandatory:
            facts.sub_required.setdefault(sub, set()).add(name)
        else:
            facts.sub_unknown.setdefault(sub, []).append(name)


def _scope_facts(stmts: list[ast.stmt]) -> ParserFacts:
    """读一个作用域（模块体 / 某个顶层函数的 body）里的 parser 形状。"""
    facts = ParserFacts()
    nodes = _walk_ordered(ast.Module(body=stmts, type_ignores=[]))
    loop_vars: dict[str, list[str]] = {}
    sub_vars: dict[str, str] = {}
    for node in nodes:
        if isinstance(node, ast.For) and isinstance(node.target, ast.Name):
            names = _str_seq(node.iter)
            if names:
                loop_vars[node.target.id] = names
    for node in nodes:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            attr = getattr(node.value.func, "attr", "")
            if attr == "add_parser":
                sub = _add_subcommand(node.value, loop_vars, facts)
                for target in node.targets:
                    if isinstance(target, ast.Name) and sub is not None:
                        sub_vars[target.id] = sub
            continue
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        attr = node.func.attr
        owner = node.func.value
        sub = sub_vars.get(owner.id) if isinstance(owner, ast.Name) else None
        if attr == "add_argument":
            _read_add_argument(node, facts, sub)
        elif attr == "add_subparsers":
            facts.has_subparsers = True
        elif attr == "add_parser":
            _add_subcommand(node, loop_vars, facts)
    return facts


def _ordered_sources(sources: dict[Path, str], main: Path) -> list[tuple[Path, str]]:
    """主文件在前，转发模块在后（子命令词表优先取主文件那份）。"""
    out: list[tuple[Path, str]] = []
    if main in sources:
        out.append((main, sources[main]))
    out.extend((p, s) for p, s in sources.items() if p != main)
    return out


def _parser_candidates(sources: dict[Path, str], main: Path) -> list[ParserFacts]:
    """所有可判的 parser 候选：模块体 + 每个**顶层**函数各算一支。

    「任一候选能接受这条命令」就算结构上站得住 —— 宁可少报，也不许冤枉正确写法。
    ★ 主文件一支都判不出时才退到转发模块（tools/wb_task.py 自己不建 parser，
    但它 import 了 wb_plan.py 与 pool/task.py 两支；只取第一支会把 13 条正确子命令判红）。
    """
    out: list[ParserFacts] = []
    for path, src in _ordered_sources(sources, main):
        try:
            tree = ast.parse(src)
        except SyntaxError:  # 读不懂的源码不拿它判人
            continue
        funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]
        found: list[ParserFacts] = []
        for scope in [tree.body] + [n.body for n in funcs]:
            facts = _scope_facts(scope)
            if facts.judges_anything:
                found.append(facts)
        out.extend(found)
        if path == main:
            continue
    return out


def _positionals(args: str) -> list[str]:
    """命令里的位置 token（跳过 --flag 与它后面那个值；--flag=value 整个跳过）。"""
    tokens = args.split()
    out: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index].strip(chr(96) + chr(39) + chr(34))
        index += 1
        if token.startswith("-") and len(token) > 1:
            if "=" not in token and index < len(tokens) and not tokens[index].startswith("-"):
                index += 1
            continue
        if token:
            out.append(token)
    return out


#: 这几种命令不拿 parser 判（判据 2 的四条红线）。
_HELP_RE = re.compile(r"(?:^|\s)(?:--help|-h|--preflight|--precheck)(?:\s|$)")


def _skip_parser_judging(claim: Claim) -> bool:
    """裸工具名 / 问帮助 / 含占位符 ⇒ 不判必填与子命令（这些命令本来就不是要跑的那条）。"""
    if not claim.args.strip():
        return True
    if _HELP_RE.search(claim.args):
        return True
    return PLACEHOLDER.search(claim.command) is not None


def _judge_parsers(claim: Claim, candidates: list[ParserFacts]) -> None:
    """判必填参数与子命令：任一候选接受就算过；全都不接受才红，全都不敢判才算判不出。"""
    if not candidates:
        return
    positionals = _positionals(claim.args)
    first = positionals[0] if positionals else None
    missing: list[str] = []
    unknown: list[str] = []
    bad_sub: list[str] = []
    for facts in candidates:
        knows_subs = facts.has_subparsers and facts.subcommands and first is not None
        if knows_subs and first not in facts.subcommands:
            bad_sub.append(first)
            continue
        sub = first if knows_subs else None
        need, unsure = facts.required_for(sub)
        cand_missing = sorted(f for f in need if f not in claim.flags)
        # ★ 判据 4：required 非字面 ⇒ 就算这条命令把那个 flag 写上了，也证明不了它还缺别的
        #   —— 记判不出，不许因为「看起来写全了」就当判过了。
        cand_unknown = sorted(unsure)
        missing.extend(cand_missing)
        unknown.extend(cand_unknown)
        if not cand_missing and not cand_unknown:
            return
    if missing:
        claim.problems.append("缺必填参数：" + "、".join(sorted(set(missing))))
    if bad_sub:
        claim.problems.append("子命令不存在：" + "、".join(sorted(set(bad_sub))))
    if not missing and not bad_sub and unknown:
        claim.unverifiable.append("取不到 required：" + "、".join(sorted(set(unknown))))



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
        if not _skip_parser_judging(claim):
            _judge_parsers(claim, _parser_candidates(sources, root / "tools" / claim.tool))

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
