r"""文档门禁（卡 F3 / T-AG451）：死指针 / drift 债 / superseded 未标注 —— **判不出就报 skip**。

## 为什么有它

`gates/defs/` 里 19 道门没有一道看文档：死链没人查、代码改了文档没改没人知道、
正文写着"已废弃"却没有状态标注也照样被后来的人当权威读（调研 §Q10 / §Q11）。

## 四条判据（口径写死在这里，改口径先改这段）

1. **死指针**：`docs/**`、`复盘/**`、`skills/**`、`AGENTS.md` 里出现的**仓内相对路径**
   （反引号里的、或 markdown 链接目标）必须存在。逐条报「文件:行 → 指到哪」。
   - 基准目录：先仓库根，再该文档所在目录，最后 `docs/`；命中其一即算过
     （本仓两种写法都有：`docs/x.md` 与 `docs/contracts/domains/x.md` 里的 `../interactions.md`）。
   - 证据写法先剥壳再判（`file:` / `text:` / `test:` 前缀、`::标记`、`:行号`）——
     否则 changelog 与台账里每一条 `file:tools/x.py` 都会被报成断链。
   - 指向 `gates/diag/**` 的过程产物 → **skip**；其余 gitignore 产物（问 git 的
     `check-ignore`，一次问完、不硬编码目录名）→ **skip**。
   - ★ **不算指针**（既不判，也不记 skip —— 记了只会把 skip 数字灌成噪声）：
     外链（http/https/mailto/www）、路由（`/api/tasks`）、命令与壳输出
     （`tools/serve.py --window` 只取第一段判；`tools/list`、`tools/call` 这种**子命令**
     没有扩展名也不是目录 ⇒ 不判）、裸文件名（`manager.py`，判不出相对哪个目录）、
     第一段在仓库根上不存在的相对路径（`lib/client.js`、`infra/pool`、`~/x`——
     那不是**仓内**路径）。
2. **drift 债**：台账**同一条**里，`file:` 证据指向的**文档** × `file:` / `text:` 证据指向的
   **源文件** 配对；源文件最近提交晚于该文档最近提交 ⇒ 记一条债（同一文档的多处并成一条）。
   **只报告，不参与 ratchet**（每一笔代码提交都会动这个数，拿它做阈值必然假红）。
   判据取 `git log --name-only` 一次全历史（517 条提交 ≈ 0.3 秒），不比祖先关系——
   提交时间戳同秒时 ADDA 的"祖先后代"判法会判不出，这里退化成"谁的时间戳更晚"。
3. **superseded 未标注**：正文命中「已废弃 / 被取代 / 不再适用」却没有 frontmatter
   `status: superseded` + `supersedes:` ⇒ 报一条。词表就是卡里点名的三个（`等词` 没扩——
   扩词等于自己加产品口径，卡里没写）。
4. **判不出来就报 skip**：仓外绝对路径（`D:\…`）、模板占位（含 `<…>` `*` `{…}` `…`）、
   `..` 逃逸、`gates/diag/**` 产物、gitignored 产物、反引号不成对的行 —— 全部记 `skip`
   并**计数打印**（按原因分组）。`skip > 0` 时输出**不许**给干净结论（照 ADDA：
   「a green check that was structurally blind is worse than no check」）。

## 基线 ratchet（`docs/doc-debt-baseline.toml`）

`dead_refs` / `superseded` 记当前欠账条数，**只能降不能升**：现在比基线多 ⇒ 红
（**report 档也红** —— ratchet 是"只许降"，与档位无关）。
`drift` / `skip` **不写进基线**（一个随每笔提交变、一个跟本机环境变，记下来第二天就是假数字），
只每次打印 —— 理由见判据 2 / 判据 4。
基线文件本身不存在 ⇒ **skip 一条**（"没有基线"），不给通过结论。

## 用法

```
python -X utf8 scripts/check_docs.py --doctor      # 自证这道门真在跑（四类计数都打印）
python -X utf8 scripts/check_docs.py --mode report # 默认：只报告（有债不红，基线被顶破才红）
python -X utf8 scripts/check_docs.py --mode block  # 判出东西就非零退出（第一版**不挂**这个档）
python -X utf8 scripts/check_docs.py --json        # 机器可读
```

退出码：`0` 报告完毕 / `1` 红（基线被顶破；`block` 档下还有死指针等也算）/
`3` **没判完**（`block` 档下 skip > 0 —— 不许让"没判"冒充"通过"）。
`--root <路径>` 换一棵树（自检拿它喂合成坏样例，**真实仓库一个字节都不写**）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import tomllib

#: 真仓库根：这份脚本所在仓库的根。
ROOT = Path(__file__).resolve().parent.parent

#: ★ 卡 148：起子进程一律不弹窗（口径与 `tools/pipeline_view.py` 同款）。
NO_WINDOW: dict[str, int] = {"creationflags": 0x08000000} if sys.platform == "win32" else {}

#: 扫哪些地方（判据 1 的原话：`docs/**`、`复盘/**`、`AGENTS.md`、`skills/**`）。
SCAN_DIRS = ("docs", "复盘", "skills")
SCAN_FILES = ("AGENTS.md",)

#: 基线（相对仓库根）。
BASELINE_REL = "docs/doc-debt-baseline.toml"

#: 过程产物目录：卡里点名要记 skip 的那一族。
DIAG_PREFIX = "gates/diag/"

#: 判据 3 的词表（卡里点名的三个；要扩词先改卡）。
SUPERSEDED_WORDS = ("已废弃", "被取代", "不再适用")

#: 证据前缀（台账 / changelog 里那一族写法）：先剥掉再当路径判。
EVIDENCE_PREFIXES = ("file:", "text:", "test:", "route:", "ui:", "column:", "table:")

#: 模板占位 / 通配：判不了（`<卡号>`、`*.md`、`{a,b}`）。
PLACEHOLDER_CHARS = ("<", ">", "*", "{", "}", "…", "$", "|")

#: 外链前缀：**不是**仓内指针（不判、不记 skip —— 记了只会把 skip 灌成噪声）。
URL_PREFIXES = ("http://", "https://", "ftp://", "mailto:", "www.")

BACKTICK = re.compile(r"`([^`\n]+)`")
MD_LINK = re.compile(r"\[[^\]\n]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
FENCE = re.compile(r"^\s*(```+|~~~+)")
DRIVE = re.compile(r"^[A-Za-z]:[\\/]")
FM_DELIM = re.compile(r"^---\s*$")

#: 每条判据打印多少条明细（全量数字另打在标题上，别把门禁日志刷爆）。
SHOW = 20


@dataclass(frozen=True)
class Finding:
    """一条判出来的债。"""

    kind: str      # dead_ref / drift / superseded
    where: str     # `文件:行`
    detail: str    # 「指到哪」/「命中了什么词」

    def line(self) -> str:
        return f"{self.where} → {self.detail}"


@dataclass(frozen=True)
class Skip:
    """一条**判不出**的东西（不许当通过）。"""

    where: str
    token: str
    reason: str


@dataclass
class Report:
    """一次扫描的全部读数。"""

    root: Path
    scanned: dict[str, int] = field(default_factory=dict)
    dead_refs: list[Finding] = field(default_factory=list)
    drift: list[Finding] = field(default_factory=list)
    superseded: list[Finding] = field(default_factory=list)
    skips: list[Skip] = field(default_factory=list)
    ratchet: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def findings(self) -> list[Finding]:
        return self.dead_refs + self.drift + self.superseded

    def counts(self) -> dict[str, int]:
        return {
            "dead_refs": len(self.dead_refs),
            "drift": len(self.drift),
            "superseded": len(self.superseded),
            "skip": len(self.skips),
        }


# --------------------------------------------------------------------------- 零件
def read_text(path: Path) -> str:
    """读文档（坏字节不炸：宁可少判一条，也别让整道门挂在编码上）。"""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def iter_docs(root: Path) -> list[Path]:
    """判据 1 的扫描面：三个目录下的 `.md` + 根上的 `AGENTS.md`。"""
    docs: list[Path] = []
    for name in SCAN_DIRS:
        base = root / name
        if base.is_dir():
            docs.extend(sorted(base.rglob("*.md")))
    for name in SCAN_FILES:
        path = root / name
        if path.is_file():
            docs.append(path)
    return docs


def rel(path: Path, root: Path) -> str:
    """仓内相对路径（posix 分隔符）；不在根下就原样给绝对路径。"""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def normalize(token: str) -> str:
    """把「命令 / 证据写法」剥成纯路径。

    台账 / changelog 里同一族写法都要认（否则每条都是假断链）：
    `file:docs/x.md` / `text:src/y.py::def f` / `tests/t.py::test_a` / `tools/z.py:294`
    / `tools/serve.py --window`（命令行：只取第一段）。
    """
    text = token.strip()
    for prefix in EVIDENCE_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            break
    text = text.split("::", 1)[0].strip()
    text = text.split()[0] if text else ""
    text = re.sub(r":\d+(-\d+)?$", "", text)
    text = text.split("#", 1)[0].strip()
    if text.startswith("./"):
        text = text[2:]
    return "" if text in (".", "..") else text


def is_path_shaped(token: str) -> bool:
    """像「文件」（末段带扩展名）或「目录」（以 `/` 结尾）才算路径。

    ★ 边界：`tools/list`、`tools/call` 这种是**子命令/壳输出**，不是仓内路径 ——
      判了只会把一条真命令报成断链（判据要能站得住，先得少冤枉人）。
    """
    if token.endswith(("/", "\\")):
        return True
    last = token.replace("\\", "/").rsplit("/", 1)[-1]
    return "." in last and not last.startswith(".")


def _norm(path: Path | str) -> str:
    """绝对化 + 归一（**纯字符串**：不碰文件系统）。

    ★ 别换成 `Path.resolve()`：它在 Windows 上会对每一段路径调 `_getfinalpathname`
      （实测 6 万次调用 = 15 秒，整道门被它拖到 24 秒）。判据只需要"词法上在不在根下"，
      符号链接解析对这里没有意义。
    """
    return os.path.normpath(os.path.abspath(str(path)))


def _inside(candidate: str, root_nc: str) -> bool:
    """词法判断：这个绝对路径在不在根下（大小写按平台归一）。"""
    value = os.path.normcase(candidate)
    return value == root_nc or value.startswith(root_nc + os.sep)


def is_repo_relative(token: str, root: Path, heads: dict[str, bool] | None = None) -> bool:
    """是不是**仓内**相对路径：第一段就在仓库根上（`docs/` `src/` `复盘/` …）。

    ★ 这是判据 1 的边界：`lib/client.js`、`infra/pool`、`~/x` 这种第一段在根上不存在的，
      不属于「仓内相对路径」—— **不是指针**，不判也不记 skip（记了只会把 skip 数字灌成噪声）。
      `./x` `../x` 这类显式相对写法另算（相对本文档，见 `resolve`）。
    """
    head = token.replace("\\", "/").split("/", 1)[0]
    if not head:
        return False
    cache = heads if heads is not None else {}
    if head not in cache:
        cache[head] = os.path.exists(os.path.join(str(root), head))
    return cache[head]


def is_pointer(token: str, root: Path, heads: dict[str, bool] | None = None) -> bool:
    """这个反引号记号算不算一条「仓内相对路径」（不算的既不是引用，也不是 skip）。"""
    if not token or " " in token or "\t" in token:
        return False
    if token.startswith(URL_PREFIXES) or DRIVE.match(token):
        return True  # 外链 / 盘符绝对路径：交给调用方分类（不判 / skip）
    if token.startswith("/"):
        return is_path_shaped(token)  # `/api/tasks` 是路由不是文件 ⇒ 不是指针
    if not is_path_shaped(token):
        return False
    if token.startswith((".", "~")):
        return True
    return is_repo_relative(token, root, heads)


def split_frontmatter(text: str) -> tuple[dict[str, str], str, int]:
    """切出 frontmatter（只认 `key: value` 一种写法）、正文、以及正文起始行号。"""
    lines = text.splitlines()
    if not lines or not FM_DELIM.match(lines[0]):
        return {}, text, 0
    meta: dict[str, str] = {}
    for i, line in enumerate(lines[1:], 1):
        if FM_DELIM.match(line):
            return meta, "\n".join(lines[i + 1:]), i + 1
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip().lower()] = value.strip()
    return {}, text, 0


def body_lines(text: str):
    """正文的 `(行号, 行)`；fenced code block 里的不算引用（也不是 skip）。

    行号按**整份文件**算（报给人的是编辑器里那一行）。
    """
    _, body, offset = split_frontmatter(text)
    fenced = False
    for i, line in enumerate(body.splitlines(), offset + 1):
        if FENCE.match(line):
            fenced = not fenced
            continue
        if not fenced:
            yield i, line


def refs_in_line(
    line: str, root: Path, heads: dict[str, bool] | None = None
) -> tuple[list[tuple[str, str]], bool]:
    """一行里的候选引用 `(记号, backtick|link)`；第二项 = 这行判不了（反引号不成对）。"""
    if line.count("`") % 2:
        return [], True
    refs: list[tuple[str, str]] = []
    for match in BACKTICK.finditer(line):
        token = normalize(match.group(1))
        if is_pointer(token, root, heads):
            refs.append((token, "backtick"))
    for match in MD_LINK.finditer(line):
        token = normalize(match.group(1))
        if token:
            refs.append((token, "link"))
    return refs, False


def _bases(md: Path, root: Path, kind: str) -> list[str]:
    """按口径给出这条引用该拿哪些目录当基准（先命中的算过）。"""
    if kind == "link":
        return [str(md.parent), str(root), str(root / "docs")]
    return [str(root), str(md.parent), str(root / "docs")]


def resolve(
    token: str, md: Path, root: Path, kind: str, *, root_nc: str | None = None
) -> Path | None:
    """把一条相对路径落到具体文件/目录上（命中其一即算过）。

    反引号（`backtick`）先当仓内相对（仓库根），再退一步按本文档目录算 ——
    两种写法本仓都在用（`docs/contracts/domains/x.md` 里写 `../interactions.md`）。
    markdown 链接（`link`）= 相对本文档（链接语义），再退仓库根、`docs/`。
    """
    clean = normalize(token)
    if not clean:
        return None
    nc = root_nc if root_nc is not None else os.path.normcase(_norm(root))
    for base in _bases(md, root, kind):
        candidate = _norm(os.path.join(base, clean))
        if _inside(candidate, nc) and os.path.exists(candidate):
            return Path(candidate)
    return None


def outside_repo(token: str, md: Path, root: Path, *, root_nc: str | None = None) -> bool:
    """这条路径是不是**只在**仓库外面（`..` 逃逸且哪个基准都落回不来）。"""
    clean = normalize(token)
    if not clean:
        return False
    nc = root_nc if root_nc is not None else os.path.normcase(_norm(root))
    for base in (str(md.parent), str(root)):
        if _inside(_norm(os.path.join(base, clean)), nc):
            return False
    return True


def git(root: Path, *args: str) -> tuple[int, str]:
    """跑一条 git（不弹窗、显式 utf-8、路径不转八进制）。返回 `(退出码, stdout)`。"""
    try:
        proc = subprocess.run(
            ["git", "-c", "core.quotePath=false", *args],
            cwd=str(root), capture_output=True, text=True,
            encoding="utf-8", errors="replace", **NO_WINDOW,
        )
    except OSError:
        return 127, ""
    return proc.returncode, proc.stdout


def last_commits(root: Path) -> tuple[dict[str, int], str]:
    """一次 `git log` 拿到**每个文件**的最近提交时间；第二项 = 判不了时的原因。"""
    code, out = git(root, "log", "--format=C%ct", "--name-only", "--no-merges")
    if code != 0:
        return {}, "git log 跑不起来（不是 git 仓库？）"
    stamps: dict[str, int] = {}
    current: int | None = None
    for line in out.splitlines():
        if line.startswith("C") and line[1:].isdigit():
            current = int(line[1:])
            continue
        if not line.strip() or current is None:
            continue
        stamps.setdefault(line.strip(), current)
    return stamps, ""


def ignored(root: Path, rels: list[str]) -> set[str]:
    """问 git：这些仓库相对路径里哪些被忽略（一次问完，别每个文件起一个进程）。"""
    if not rels:
        return set()
    try:
        proc = subprocess.run(
            ["git", "-c", "core.quotePath=false", "check-ignore", "--stdin", "-z"],
            cwd=str(root), input="\0".join(rels).encode("utf-8"),
            capture_output=True, **NO_WINDOW,
        )
    except OSError:
        return set()
    if proc.returncode not in (0, 1):
        return set()  # 出错按「没被忽略」从严：宁可多报一条断链
    text = proc.stdout.decode("utf-8", "replace")
    return {p for p in text.split("\0") if p}


def repo_rel(token: str, md: Path, root: Path, kind: str) -> str:
    """一条引用化成的仓库相对路径（给 `check-ignore` 用）。

    ★ 目录要**留着结尾的 `/`**：gitignore 里 `gates/logs/` 这种目录规则，
      拿 `gates/logs` 去问是问不出匹配的（实测 `check-ignore` 两种写法一个中一个不中）。
    """
    clean = normalize(token)
    is_dir = token.endswith(("/", "\\"))
    root_nc = os.path.normcase(_norm(root))
    for base in _bases(md, root, kind):
        candidate = _norm(os.path.join(base, clean))
        if not _inside(candidate, root_nc):
            continue
        out = os.path.relpath(candidate, _norm(root)).replace("\\", "/")
        return out + "/" if is_dir and not out.endswith("/") else out
    return clean.replace("\\", "/")


# --------------------------------------------------------------------------- 判据
def check_dead_refs(root: Path, docs: list[Path]) -> tuple[list[Finding], list[Skip]]:
    """判据 1：死指针（判不出的地方如实记 skip）。

    ★ 边界（与文件头一致）：外链 / 路由 / 子命令 / 裸文件名 / 第一段不在仓根的相对路径
      **不是指针**（不判也不记 skip）；绝对路径 / 模板占位 / `..` 逃逸 / `gates/diag`
      产物 / gitignored 产物 / 反引号不成对的行 ⇒ **skip**（判不出）。
    """
    findings: list[Finding] = []
    skips: list[Skip] = []
    missing: list[tuple[str, str, str]] = []  # (where, token, derived rel)
    root_nc = os.path.normcase(_norm(root))
    heads: dict[str, bool] = {}

    for md in docs:
        text = read_text(md)
        where_file = rel(md, root)
        for lineno, line in body_lines(text):
            refs, unparsable = refs_in_line(line, root, heads)
            if unparsable:
                skips.append(Skip(f"{where_file}:{lineno}", line.strip()[:40],
                                  "行内反引号不成对，这一行判不了"))
                continue
            for token, kind in refs:
                where = f"{where_file}:{lineno}"
                if token.startswith(URL_PREFIXES):
                    continue  # 外链不在判据 1 的范围里（不判，也不冒充 skip）
                if DRIVE.match(token) or token.startswith(("/", "~")):
                    skips.append(Skip(where, token, "仓外/绝对路径，判不了"))
                    continue
                if any(ch in token for ch in PLACEHOLDER_CHARS):
                    skips.append(Skip(where, token, "模板占位/通配，判不了"))
                    continue
                if outside_repo(token, md, root, root_nc=root_nc):
                    skips.append(Skip(where, token, "指到仓库外面去了"))
                    continue
                if resolve(token, md, root, kind, root_nc=root_nc) is not None:
                    continue
                if token.replace("\\", "/").startswith(DIAG_PREFIX):
                    skips.append(Skip(where, token, "gates/diag 产物（不随 worktree 分发）"))
                    continue
                missing.append((where, token, repo_rel(token, md, root, kind)))

    # 一次问 git：这些不存在的路径里，哪些是 gitignored 产物（跳过，不算断链）
    ignored_set = ignored(root, sorted({derived for _, _, derived in missing}))
    ignored_flat = {path.rstrip("/") for path in ignored_set}
    for where, token, derived in missing:
        if derived in ignored_set or derived.rstrip("/") in ignored_flat:
            skips.append(Skip(where, token, "gitignored 产物（不随树分发）"))
            continue
        findings.append(Finding("dead_ref", where, token))
    return findings, skips


def check_superseded(root: Path, docs: list[Path]) -> list[Finding]:
    """判据 3：正文说"已废弃"却没有 `status: superseded` + `supersedes:`。"""
    findings: list[Finding] = []
    for md in docs:
        text = read_text(md)
        meta, body, _ = split_frontmatter(text)
        hits = [word for word in SUPERSEDED_WORDS if word in body]
        if not hits:
            continue
        labeled = meta.get("status", "").strip().lower() == "superseded" and bool(
            meta.get("supersedes", "").strip()
        )
        if labeled:
            continue
        where = rel(md, root)
        findings.append(Finding(
            "superseded", where,
            f"正文命中「{'/'.join(hits)}」，但没有 frontmatter status: superseded + supersedes:",
        ))
    return findings


def ledger_pairs(root: Path) -> tuple[list[tuple[str, str, str]], str]:
    """从台账里取「(条目, 文档, 源文件)」三元组；第二项 = 取不到时的原因。"""
    path = root / "docs" / "traceability.toml"
    if not path.is_file():
        return [], "没有 docs/traceability.toml"
    try:
        data = tomllib.loads(read_text(path))
    except tomllib.TOMLDecodeError as exc:
        return [], f"台账解析不了：{exc}"
    entries = data.get("entries") or {}
    if not isinstance(entries, dict):
        return [], "台账没有 [entries] 表"
    pairs: list[tuple[str, str, str]] = []
    for eid, entry in entries.items():
        evidence = entry.get("evidence") or []
        if isinstance(evidence, str):
            evidence = [evidence]
        docs = [x[5:] for x in evidence
                if x.startswith("file:") and x[5:].lower().endswith((".md", ".markdown"))]
        codes = [x[5:] for x in evidence
                 if x.startswith("file:") and not x[5:].lower().endswith((".md", ".markdown"))]
        codes += [x[5:].split("::", 1)[0] for x in evidence if x.startswith("text:")]
        docs = sorted({d for d in docs if "/" in d and (root / d).is_file()})
        codes = sorted({
            c for c in codes
            if "/" in c and (root / c).is_file()
            and not c.lower().endswith((".md", ".markdown"))
        })
        for doc in docs:
            for code in codes:
                pairs.append((eid, doc, code))
    return pairs, ""


def check_drift(root: Path) -> tuple[list[Finding], list[Skip]]:
    """判据 2：源文件比它对应的文档新 ⇒ 一条 drift 债（只报告）。"""
    pairs, why = ledger_pairs(root)
    if why:
        return [], [Skip("docs/traceability.toml", "-", why)]
    stamps, why = last_commits(root)
    if why:
        return [], [Skip("(git)", "-", f"{why} ⇒ drift 判不了")]
    findings: list[Finding] = []
    grouped: dict[tuple[str, str], list[tuple[str, int]]] = {}
    for eid, doc, code in pairs:
        doc_ts, code_ts = stamps.get(doc), stamps.get(code)
        if doc_ts is None or code_ts is None:
            continue  # 有一头没提交过：历史上判不了（不计 skip，避免把首次提交前的东西算债）
        if code_ts > doc_ts:
            grouped.setdefault((eid, doc), []).append((code, code_ts - doc_ts))
    for (eid, doc), items in sorted(grouped.items()):
        items.sort(key=lambda pair: -pair[1])
        newest, delta = items[0]
        findings.append(Finding(
            "drift", f"{eid} {doc}",
            f"{len(items)} 处依据的源文件比它新（最新：{newest}，差 {delta // 86400} 天）",
        ))
    return findings, []


def load_baseline(path: Path) -> tuple[dict[str, int], str]:
    """读基线；读不了 ⇒ 第二项给原因（调用方记 skip，不给干净结论）。"""
    if not path.is_file():
        return {}, f"没有基线 {path.name}"
    try:
        data = tomllib.loads(read_text(path))
    except tomllib.TOMLDecodeError as exc:
        return {}, f"基线解析不了：{exc}"
    section = data.get("baseline") or {}
    if not isinstance(section, dict):
        return {}, "基线没有 [baseline] 表"
    counts: dict[str, int] = {}
    for key in ("dead_refs", "superseded", "drift", "skip"):
        value = section.get(key)
        if isinstance(value, int):
            counts[key] = value
    if "dead_refs" not in counts or "superseded" not in counts:
        return {}, "基线缺 dead_refs / superseded 两项"
    return counts, ""


def ratchet(counts: dict[str, int], baseline: dict[str, int]) -> list[str]:
    """基线 ratchet：`dead_refs` / `superseded` **只能降不能升**。"""
    out: list[str] = []
    for key in ("dead_refs", "superseded"):
        now, was = counts.get(key, 0), baseline.get(key, 0)
        if now > was:
            out.append(f"{key} 从 {was} 涨到 {now}（基线只能降不能升）")
        elif now < was:
            out.append(f"{key} 从 {was} 降到 {now}（可以把基线调低到 {now}）")
    return out


# --------------------------------------------------------------------------- 汇合
def scan(root: Path) -> Report:
    """跑完四条判据，收成一份读数（纯读：一个字节都不写）。"""
    report = Report(root=root)
    docs = iter_docs(root)
    report.scanned["文件"] = len(docs)
    for name in SCAN_DIRS:
        report.scanned[name] = sum(1 for d in docs if rel(d, root).startswith(f"{name}/"))
    report.scanned["根文件"] = len(docs) - sum(
        report.scanned[name] for name in SCAN_DIRS
    )

    dead, dead_skips = check_dead_refs(root, docs)
    report.dead_refs = dead
    report.skips.extend(dead_skips)
    report.superseded = check_superseded(root, docs)
    drift, drift_skips = check_drift(root)
    report.drift = drift
    report.skips.extend(drift_skips)

    baseline, why = load_baseline(root / BASELINE_REL)
    if why:
        report.skips.append(Skip(BASELINE_REL, "-", f"{why} ⇒ ratchet 判不了"))
    else:
        report.ratchet = ratchet(report.counts(), baseline)
    return report


def print_report(report: Report, mode: str = "report", out=None) -> None:
    """人读输出。★ `skip > 0` 时**不许**给干净结论。"""
    say = out or (lambda line: print(line, flush=True))
    root = report.root
    say("=== check_docs（文档门禁 · 卡 F3 / T-AG451）===")
    say(f"[info] 树：{root}")
    say(f"[info] 死指针 {len(report.dead_refs)} 条 / drift 债 {len(report.drift)} 条"
        f" / superseded 未标注 {len(report.superseded)} 条 / 判不出 {len(report.skips)} 条")

    for title, items in (
        ("死指针（判据 1）", report.dead_refs),
        ("drift 债（判据 2 · 只报告，不参与 ratchet）", report.drift),
        ("superseded 未标注（判据 3）", report.superseded),
    ):
        if not items:
            continue
        say(f"[{title}] {len(items)} 条")
        for item in items[:SHOW]:
            say(f"  {item.line()}")
        if len(items) > SHOW:
            say(f"  …另有 {len(items) - SHOW} 条（`--json` 看全量）")

    if report.skips:
        by_reason: dict[str, list[Skip]] = {}
        for item in report.skips:
            by_reason.setdefault(item.reason, []).append(item)
        say(f"[skip] 判不出 {len(report.skips)} 条（按原因分组）：")
        for reason, items in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
            say(f"  - {reason}：{len(items)} 条")
            for item in items[:3]:
                say(f"      {item.where}  {item.token}")
        say(f"★ 上面这 {len(report.skips)} 条我判不出 —— 它们**不是**通过（结构上看不见，"
            f"比没有门更糟）。")
    for note in report.notes:
        say(f"[note] {note}")
    for line in report.ratchet:
        say(f"[ratchet] {line}")

    code = exit_code(report, mode)
    over = any("涨到" in line for line in report.ratchet)
    total = len(report.dead_refs) + len(report.superseded) + len(report.drift)
    if code == 1 and over:
        say("CHECK_DOCS: FAIL ❌（基线被顶破：只许降不许升）")
    elif code == 1:
        say(f"CHECK_DOCS: FAIL ❌（--mode block：上面 {total} 条债逐条列了）")
    elif code == 3:
        say(f"CHECK_DOCS: 没判完 ❌（有 {len(report.skips)} 条 skip，block 档退 3）")
    elif report.skips:
        say("CHECK_DOCS: 没判完（有 skip）—— 不许当 PASS")
    elif report.findings:
        say(f"CHECK_DOCS: report 档（判出 {total} 条债，本档不红；`--mode block` 会红）")
    else:
        say("CHECK_DOCS: PASS ✅（判完了，且一条都没判出）")


def print_doctor(report: Report, out=None) -> None:
    """`--doctor`：自证这道门**真在跑**、真扫到了东西（照 `adda doctor`）。"""
    say = out or (lambda line: print(line, flush=True))
    scanned = report.scanned
    say("=== --doctor（自证这道门真在跑）===")
    say(f"我在跑：scripts/check_docs.py（树 {report.root}，python {sys.version.split()[0]}）")
    detail = " / ".join(f"{key} {value}" for key, value in scanned.items() if key != "文件")
    say(f"我扫了 {scanned.get('文件', 0)} 个文件：{detail}")
    counts = report.counts()
    say(f"判出 {counts['dead_refs'] + counts['drift'] + counts['superseded']} 条："
        f"死指针 {counts['dead_refs']} / drift {counts['drift']}"
        f" / superseded {counts['superseded']}")
    by_reason: dict[str, int] = {}
    for item in report.skips:
        by_reason[item.reason] = by_reason.get(item.reason, 0) + 1
    tail = " / ".join(f"{reason} {n}" for reason, n in sorted(by_reason.items())) or "无"
    say(f"判不出 {counts['skip']} 条：{tail}")
    if not scanned.get("文件"):
        say("★ 一个文件都没扫到 ⇒ 这道门等于没跑（红）。")


def as_json(report: Report) -> dict:
    """机器可读（`--json`）。"""
    return {
        "root": str(report.root),
        "scanned": report.scanned,
        "counts": report.counts(),
        "dead_refs": [item.line() for item in report.dead_refs],
        "drift": [item.line() for item in report.drift],
        "superseded": [item.line() for item in report.superseded],
        "skips": [
            {"where": item.where, "token": item.token, "reason": item.reason}
            for item in report.skips
        ],
        "ratchet": report.ratchet,
        "notes": report.notes,
    }


def exit_code(report: Report, mode: str) -> int:
    """退出码：`0` 判完且干净 / `1` 红 / `3` 没判完（只在 block 档区分）。

    ★ `report` 档**不因"有债"而红**（第一版就挂 block 会被骂，卡里写明先跑一周）；
      它只为**基线被顶破**而红 —— ratchet 的意思是「只许降不许升」，与档位无关。
    """
    if any("涨到" in line for line in report.ratchet):
        return 1
    if not report.scanned.get("文件"):
        return 1  # 一个文件都没扫到 ⇒ 这道门等于没跑（卡 159 的教训：判据要能证明它看得见）
    if mode == "report":
        return 0
    if report.dead_refs or report.superseded or report.drift:
        return 1
    if report.skips:
        return 3
    return 0


def main(
    root: Path | str | None = None,
    mode: str = "report",
    doctor: bool = False,
    json_out: bool = False,
    out=None,
) -> int:
    """跑一遍；`root` 不给 = 真仓库根（自检拿合成小树喂坏样例）。"""
    base = Path(root).resolve() if root is not None else ROOT.resolve()
    report = scan(base)
    if json_out:
        print(json.dumps(as_json(report), ensure_ascii=False, indent=2))
    else:
        if doctor:
            print_doctor(report, out=out)
        print_report(report, mode, out=out)
    return exit_code(report, mode)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """命令行：`--mode report|block` / `--doctor` / `--json` / `--root`。"""
    parser = argparse.ArgumentParser(
        description="文档门禁：死指针 / drift 债 / superseded 未标注（判不出就报 skip）"
    )
    parser.add_argument(
        "--mode", choices=("report", "block"), default="report",
        help="report（默认，只报告）或 block（判出东西就非零退出）",
    )
    parser.add_argument("--doctor", action="store_true",
                        help="自证这道门真在跑：打印我在跑 / 扫了几个文件 / 判出几条 / 判不出几条")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--root", default=None,
                        help="查哪棵树（默认 = 本脚本所在仓库根）")
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    sys.exit(main(args.root, args.mode, args.doctor, args.json))
