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
3. **superseded 未标注**：**文档自己声明自己过时**（不是正文里出现那个词）却没有 frontmatter
   `status: superseded` + `supersedes:` ⇒ 报一条。认两种声明：标题行 `# 已废弃：xxx`（标题
   整句就是这个意思），和正文里**带主语**的句子（`本/本文件/本文档/本卡片/本文 + 已废弃/…`
   或 `不再适用，请见 X`）。裸词不算——第一版按裸词判，6 条命中全是误报（自动生成文件、
   文件名带这词、文档在讨论这个词本身），卡 A308 收窄成现在这样。`GENERATED` 首行锚点的
   自动生成文件直接不判。详见 `superseded_declarations()` 的收窄史。
4. **判不出来就报 skip**：仓外绝对路径（`D:\…`）、模板占位（含 `<…>` `*` `{…}` `…`）、
   `..` 逃逸、`gates/diag/**` 产物、gitignored 产物、**行尾反引号不成对的那一段** —— 全部记 `skip`
   并**计数打印**（按原因分组）。`skip > 0` 时输出**不许**给干净结论（照 ADDA：
   「a green check that was structurally blind is worse than no check」）。

## 基线 ratchet（`docs/doc-debt-baseline.toml`）

`dead_refs` / `superseded` 记当前欠账条数，**只能降不能升**：现在比基线多 ⇒ 红
（**report 档也红** —— ratchet 是"只许降"，与档位无关）。
`drift` 也记进基线（卡 E39），但它是**可漂移量**（每一笔代码提交都会动它），
输出里只做对照、**不参与 ratchet**；`skip` **绝不写进基线**（把不确定当合格等于自欺）。
基线文件本身不存在 ⇒ **skip 一条**（"没有基线"），不给通过结论。

★ 输出口径（卡 E39）：欠账与「判不出」**分两行** —— `CHECK_DOCS: 死指针 N（基线 M，±k）`
一行、`CHECK_DOCS: 判不出 K 条（skip）—— 这不是 PASS` 一行；skip 永不并入红/绿判定。

## 用法

```
python -X utf8 scripts/check_docs.py --doctor          # 自证这道门真在跑（四类计数都打印）
python -X utf8 scripts/check_docs.py --mode report     # 默认：只报告（有债不红，超基线才红）
python -X utf8 scripts/check_docs.py --mode block      # 判出东西就非零退出（第一版**不挂**这个档）
python -X utf8 scripts/check_docs.py --json            # 机器可读
python -X utf8 scripts/check_docs.py --write-baseline  # 重刷基线（幂等：连跑两次字节不变）
```

退出码：`0` 报告完毕 / `1` 红（基线被顶破；`block` 档下还有死指针等也算）/
`3` **没判完**（`block` 档下 skip > 0 —— 不许让"没判"冒充"通过"）。
`--root <路径>` 换一棵树（自检拿它喂合成坏样例，**真实仓库一个字节都不写**）。

## 决策记录（`--decisions`，卡 F4 / T-AG452）

## 为什么有它

决策散在台账、复盘正文和脑子里：改主意时没人知道原来为什么那么定，也没人知道当时
有多大把握。ADR 的规矩是**只追加**——已 Accepted 的正文不许改，改主意就新写一条并
双向链接。这条规矩靠人记必然失效（评审时看不出来），所以用 git 做判据：

- **看得见的**：编号、文件名、五段模板、status、supersedes 成对、正文与冻结头信息是否被改。
- **看不见的**：出处是否真实、决定对不对、候选方案是否穷尽 —— 机器判不了，不编假判据。

## 四条判据（口径写死在这里，改口径先改这段）

1. **编号连续**：文件名 `NNNN-slug.md`（4 位数字 + 小写字母数字连字符）；编号从 `0001`
   起无空洞、无重号（重号会让 `Supersedes: 0003` 指向两条）。
2. **模板固定五段**：头信息 `Status:` + `## 背景与问题` / `## 候选方案` / `## 决定` /
   `## 把握程度`，顺序固定、每段非空、不许多出别的二级标题。`## 决定` 里的取舍由人看，
   机器只判这段有没有内容。
3. **status 合法**：`Proposed` / `Accepted` / `Superseded`。`Superseded` 必须带
   `Superseded-by`，非 `Superseded` 不许带；`Supersedes` / `Superseded-by` 必须**互指**
   （A 取代 B ⇔ B 的 `Superseded-by` 是 A），且不许自指。
4. **只追加**：HEAD 里已经是 `Accepted` / `Superseded` 的记录——
   - 正文（第一个二级标题之后）**一个字不许改**；
   - 头信息里只许改 `Status` 与 `Superseded-by` 两行（标题 / 来源 / `Supersedes` 冻结）；
   - status 不许倒退（`Accepted` 只能到 `Superseded`；`Superseded` 不许变回去）；
   - 记录**不许删**（HEAD 有、工作区没有 ⇒ 红）。

## 为什么不用「看文件时间」

`mtime` 会被 checkout / 拷贝改掉，`Date:` 行是人写的。唯一可信的「原来长什么样」是
git 里的那一版（`git show HEAD:<path>`），所以判据 4 的基准是 HEAD —— **不是**
暂存区，也不是上一次提交（第一版足够：正文冻结是逐版比较的）。

## 判不出就报 skip

没有 HEAD（新仓库 / 不是 git 仓库）⇒ 判据 4 没判，打 `[skip]` 并以**退出码 3** 收场：
不许让「没判」冒充「通过」。

## 用法

```
python -X utf8 scripts/check_docs.py --decisions          # 判真仓库
python -X utf8 scripts/check_docs.py --decisions --root <路径>   # 换一棵树（测试用）
```

退出码：`0` 通过 / `1` 不通过 / `3` 没判完（没有 HEAD）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
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

#: `--write-baseline` 落盘时写进文件头的重刷命令（判据 1 要的格式）。
BASELINE_REFRESH_CMD = "python -X utf8 scripts/check_docs.py --write-baseline"

#: 重刷基线记哪张卡（文件头 `task`）。
BASELINE_TASK = "T-AG493"

#: 过程产物目录：卡里点名要记 skip 的那一族。
DIAG_PREFIX = "gates/diag/"

#: 判据 3 的词表（卡里点名的三个；要扩词先改卡）。
# 判据 3 只认**「文档自己声明自己过时」**，不认裸词（卡 A308 收窄）。
#
# 第一版是「正文里出现 `已废弃 / 被取代 / 不再适用` 就报」，实测 6 条命中**全是误报**：
# 自动生成的索引、文件名里带这个词的文件、在讨论/定义这个词表的卡、讲这个概念的调研
# 文章、以及偶然写进句子里的词。判据本意是「这份文档自己声明自己过时了」，
# 而裸词出现的位置与"谁在声明"无关 —— 所以改成只认自声明句式。
SUPERSEDED_WORDS = ("已废弃", "被取代", "不再适用")

# 自声明必须有**主语**：本/此 + 文档类称谓（本文档 / 本文件 / 本卡 / 本复盘 …）。
SELF_SUBJECTS = ("本", "此")
SELF_NAMES = ("文档", "文件", "文", "篇", "页", "卡", "复盘", "索引")

_KW = r"(?P<kw>已废弃|被取代|不再适用)"
_SUBJ = r"(?P<subj>(?:本|此)(?:" + "|".join(SELF_NAMES) + r")[^，,。；;！!？?]{0,12}?)"

# 三种句式，其余一律不算（名字 + 该句式适用的守卫）：
#   ① 主语 + 关键词：`本文档已废弃` / `本文不再适用，请见 …`（关键词落在句末也算，
#      只要主语在；`本文档不再适用。` 命中）
#      守卫：主语到关键词之间点名了别的文档 ⇒ 在说别人。
#   ② 主语 + 被 X 取代：`本文件被 docs/new.md 取代`
#      ★ 这里的 X **就是**接任者，所以**不**套"点了别的文档"守卫；
#      但主语里夹了「的」就不算（`本文档的旧入口已被 … 取代` 说的是旧入口）。
#   ③ 标题即声明：`# 已废弃：xxx` / `# 被取代｜xxx`
#
# ★ 没有主语、只靠「关键词落在句末」的句子**不认**（`这条路现已废弃。`）。
#   那正是误报的入口：复盘里写 `旧路由表已废弃。` 说的是那个表，不是这份文档。
#   卡 A308 的判据是「主语 + 关键词 + 同句」三件齐备；本仓实测这种无主语句式
#   **0 条独有命中**（唯一那条真欠账靠标题句式就能判出），所以收紧没有损失。
SUPERSEDED_PATTERNS = (
    (re.compile(_SUBJ + _KW), ("object", "other_doc")),
    (re.compile(_SUBJ + r"被[^。；;！!？?]{0,24}?(?P<kw>取代)"), ("object",)),
)
SUPERSEDED_HEADING = re.compile(
    r"^ {0,3}#{1,6} *(?P<kw>已废弃|被取代|不再适用)(?= *[：:｜|—–-])", re.M
)

# 否定：「并非不再适用」「未被取代」都不是声明。看关键词**前面**那一小段。
_NEGATION = re.compile(r"(?:并非|不是|并未|未被|没有被|没被|不能算)$")

# 「被取代」说的常常是**别的**东西：`本文档的 A 已被 B 取代` 里被取代的是 A。
# 主语到关键词之间夹了「的」⇒ 主语不是被取代的那个对象，不算自声明。
_OBJECT_MARK = "的"


#: 证据前缀（台账 / changelog 里那一族写法）：先剥掉再当路径判。
EVIDENCE_PREFIXES = ("file:", "text:", "test:", "route:", "ui:", "column:", "table:")

#: 模板占位 / 通配：判不了（`<卡号>`、`*.md`、`{a,b}`）。
PLACEHOLDER_CHARS = ("<", ">", "*", "{", "}", "…", "$", "|")
#: 占位符的另一种写法：**单字母大写词干**（`X.py` / `N.md` / `卡X.md` 里那一段 `X`）。
#: 正文拿它当「示例文件名」，`:156` 那种写法本仓到处都是。实测本仓跟踪的 1964 个文件里
#: 末段是这种形状的 **0 个**，盘上（不含 `.git`/`.wt`）也是 **0 个** ⇒ 不会吃掉真文件。
PLACEHOLDER_STEM = re.compile(r"^[A-Z](?:\.[A-Za-z0-9]+)?$")

#: 外链前缀：**不是**仓内指针（不判、不记 skip —— 记了只会把 skip 灌成噪声）。
URL_PREFIXES = ("http://", "https://", "ftp://", "mailto:", "www.")

BACKTICK = re.compile(r"`([^`\n]+)`")
MD_LINK = re.compile(r"\[[^\]\n]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
FENCE = re.compile(r"^\s*(```+|~~~+)")
# 卡 F10：行尾没配对的那一段按空白/标点切词，逐个问 is_pointer()
TAIL_SPLIT = re.compile(r"[\s（）()，、；;：`]+")
PUNCT_ONLY = re.compile(r"^[^\w]+$")
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
    baseline: dict[str, int] = field(default_factory=dict)
    drift_judged: bool = True

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


def tracked_docs(root: Path) -> set[str]:
    """问 git：这些仓库相对路径里哪些**已入库**（`ls-files`，一次问完）。"""
    try:
        proc = subprocess.run(
            ["git", "-c", "core.quotePath=false", "ls-files", "-z"],
            cwd=str(root), capture_output=True, **NO_WINDOW,
        )
    except OSError:
        return set()
    if proc.returncode != 0:
        return set()
    return {p for p in proc.stdout.decode("utf-8", "replace").split("\0") if p}


def iter_docs_split(root: Path) -> tuple[list[Path], list[tuple[Path, str]]]:
    """扫源文件时**也问一遍 git**：没入库的 `.md` 不进判据，记 `skip` 点名（卡 E53 · T-AG503）。

    ── 为什么必须对称 ──
    目标侧（被引用的路径）早就用 `ignored()` 把 gitignored 的记 `skip`；源侧原来用
    `base.rglob("*.md")` 照扫不误 ⇒ **同一 HEAD 在主树与卡树读数不同**：
    `git worktree add` 只铺入库文件，主树盘上却躺着本机私有速查文档（**未跟踪**，
    不是 gitignored —— `git check-ignore` 对它退 1）⇒ 基线采自卡树、主树永远红，
    `docs/doc-debt-baseline.toml` 头部的「只许降不许升」被这种伪债顶破。

    ⇒ 判据管的是**仓库里的文档**，不是本地笔记本。两个理由分开记，别混成一个：
      · 未跟踪（`ls-files` 里没有）：本机私有速查、别的窗口的半成品；
      · gitignored：`gates/diag/**` 这类产物。
    """
    docs = iter_docs(root)
    tracked = tracked_docs(root)
    names = [rel(path, root) for path in docs]
    ign = ignored(root, [n for n in names if n and not n.startswith("/")])
    kept: list[Path] = []
    dropped: list[tuple[Path, str]] = []
    for path, name in zip(docs, names, strict=False):
        if not name or name.startswith("/") or ":" in name:
            kept.append(path)              # 仓外/绝对路径：不参与入库判定
            continue
        if name in ign or name.rstrip("/") in ign:
            dropped.append((path, "gitignored 文档（本机产物，不随树分发）"))
        elif tracked and name not in tracked:
            dropped.append((path, "未入库文档（未跟踪，不随树分发）"))
        else:
            kept.append(path)
    return kept, dropped


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

    ★ 卡 F6：行号有四种写法，旧版只认第一种，把 `:23,145` 整段当文件名 ⇒ 假断链。
      `:294`（单行）/ `:294-300`（区间）/ `:23,145` `:14,45`（多行逗号）/
      `:127-131,`（区间尾逗号）/ `：34,431`（**全角冒号**，中文正文里很常见）。
      另有 `文件.成员()`、`文件.成员` 这种「指到某个函数/常量」的写法
      （`tools/evidence_map.assertion_path()`）—— 落盘时要按 `文件.py` 找。
    """
    text = token.strip()
    for prefix in EVIDENCE_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            break
    text = text.split("::", 1)[0].strip()
    text = text.split()[0] if text else ""
    # 行号：半角/全角冒号 + 单行/区间/逗号列表 + 可能的尾逗号 + 可能的尾冒号
    # ★ 卡 F6 补：`文件.py:68:`（行号后面还跟一个冒号）实测是本仓真有的写法
    #   （`复盘/卡/卡E49-*.md:22`、`复盘/外包-卡表与规矩.md:1298`、
    #   `复盘/派活器三合一-T-G114.md:171` 三处），旧正则只认 `:68` 不认 `:68:`，
    #   于是整串 `x.py:68:` 落到「扩展名 `py:` 不在 OWN_EXTS ⇒ 别仓路径」上白跳过。
    text = re.sub(r"[:：]\d+(?:[-–,，]\d+)*[,，]?[:：]?$", "", text)
    # 裸尾冒号（`tests/t.py:`）同理：冒号不会是路径的一部分，只可能是排版残渣。
    # 只对「看起来像路径」的串剥（含 `/`，或末段含点）—— 免得把 `mailto:` 剥成 `mailto`。
    if re.search(r"[/\\.]", text):
        text = re.sub(r"[:：]$", "", text)
    text = text.split("#", 1)[0].strip()
    if text.startswith("./"):
        text = text[2:]
    return "" if text in (".", "..") else text


#: 本仓跟踪过的扩展名 —— **手写集合 + 由测试钉在 `git ls-files` 上**（不运行时现算）。
#:
#: ── 为什么不选「运行时从 `git ls-files` 现算」（实测理由，不是图省事）──
#: ① 非 git 树（`tmp_path` 合成夹具、`git archive` 导出的目录、拷来的一份）里
#:    `git ls-files` 一条不回 ⇒ 集合为空 ⇒ **凡带扩展名的引用全落进「别仓路径」skip**，
#:    真死指针被静默吞掉（skip 不是 PASS，但它确实不再进 findings）。这是**放宽**。
#: ② 集合会随「谁刚 add 过」漂 ⇒ 同一 HEAD 在两棵树上读数不同（卡 E53 踩过：判据只认
#:    仓库里的东西，读数必须可复现，否则基线 ratchet 被伪债顶破）。
#: ③ 现算出来的集合**比这里小**（实测跟踪过 19 种，这里 25 个）⇒ 正是「不许缩小」的反面。
#: ⇒ 集合留在源码里当**声明**，由
#:   `tests/test_check_docs.py::test_own_exts_covers_every_tracked_extension` 反向钉住：
#:   `git ls-files` 实测到的每个扩展名都必须在集合里（漏一个 = 把本仓文件误判成别仓）；
#:   集合里每个成员要么有跟踪样本，要么在 `OWN_EXTS_UNTRACKED_REASONS` 里有一条理由。
#:
#: ── 判据 1 怎么用它（完整顺序见 `check_dead_refs` 的 docstring）──
#: **只在「文件确实不存在」之后**才拿它兜底推「别仓路径」：`.ts` / `.php` / `.go` 这种
#: 本仓从来没有的类型，不存在时最可能是引用了别人的仓（`复盘/DSH插件-*.md` 里那批
#: `src/core/verification.ts`）。存在性优先于类型猜测 —— `.ts` 真在仓里它就是仓里的。
#:
#: ── 为什么不把 `.jsonl` / `.log` / `.db` 加进来（它们确实躺在盘上）──
#: 那些是**本机运行产物**（`.gitignore` 的 `logs/`、`gates/diag/`、`*.db-*` 各自挡着），
#: 加进来等于宣布「本仓跟踪日志/数据库」：哪天这类引用真的写错（文件没了、也没被
#: ignore），它就不再是「别仓路径」skip 而是**死指针** —— 那是收紧，会凭空顶破
#: `docs/doc-debt-baseline.toml` 的 dead_refs 基线。它们现在走存在性分支（
#: `logs/timeflow.jsonl` 存在 ⇒ 正常）或 gitignore 分支（不存在但被 ignore ⇒
#: skip「gitignored 产物」），两条理由都比「按类型猜」准。
OWN_EXTS = frozenset({
    ".md", ".markdown", ".py", ".pyw", ".toml", ".txt", ".mjs", ".json", ".js",
    ".yml", ".yaml", ".ps1", ".sh", ".cmd", ".html", ".css", ".tmpl", ".png",
    ".gitignore", ".gitattributes", ".gitkeep", ".ini", ".cfg", ".lock", ".svg",
    ".csv",
})

#: `OWN_EXTS` 里**当前没有跟踪样本**的成员 —— 每个都得有一条存在理由，否则就是"猜进去的"。
#: `tests/test_check_docs.py::test_every_own_ext_is_justified` 钉住三件事：
#: ① 没样本的成员必须在这里有理由，且理由非空；② 理由表与跟踪样本**不相交**
#: （某个成员哪天被真正跟踪了，测试会要求把理由删掉 —— 理由会腐烂，腐烂得被抓出来）；
#: ③ 理由表里不许有不在 `OWN_EXTS` 的成员。
#: ★ 它**证明不了**的一件事：有人把某个「本来就没样本」的成员从 `OWN_EXTS` 里删掉，
#:   上面三条都看不见（跟踪过的扩展名一个没少、理由也没多）。要记这里，别假装钉住了。
OWN_EXTS_UNTRACKED_REASONS = {
    ".markdown": "`README.markdown` 是正规写法，本仓目前只用 `.md`，但文档里会引到",
    ".yaml": "`yml` 的孪生写法；本仓跟踪 `.yml`，同一种格式不该按后缀二选一",
    ".svg": "`docs/` 里的矢量图；本仓跟踪 `.png`（`src/web/icon-192.png`），同类资源",
    ".ini": "`pytest.ini` / `setup.ini` 一类，删了会把这类引用误判成别仓",
    ".cfg": "`setup.cfg` / `tox.cfg` 一类 Python 打包配置，与 `.toml` 同类",
    ".lock": "锁文件（`*.lock`）；认不出它只会把依赖清单当成别仓路径",
}


def ext_of(token: str) -> str:
    """末段的扩展名（小写，含点）；没有就空串。`.gitignore` 这种算扩展名。"""
    last = token.replace("\\", "/").rsplit("/", 1)[-1]
    if last.startswith(".") and last.count(".") == 1:
        return last.lower()
    return ("." + last.rsplit(".", 1)[-1].lower()) if "." in last else ""


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
    """一行里的候选引用 `(记号, backtick|link)`；第二项 = **行尾那一段**判不了。

    卡 F10 改的口径：旧写法见到奇数个反引号就 `return [], True` 整行丢掉，于是同一行里
    **成对**的引用一条都不判 —— 判据自己制造盲区（合成树实测：一行「见 `docs/ghost.md`，
    尾 `docs/nothere.md」旧实现报 0 条死指针，真断链没人看见）。现在**成对的照判**，
    只有最后一个配对之后的尾巴里那个没配对的反引号，才让这一段记 skip；而且尾巴里
    **得像引用**（过 `is_pointer()`）才算，纯代码原文 / 纯标点不算（那本来就不含引用）。
    """
    refs: list[tuple[str, str]] = []
    last_end = 0
    for match in BACKTICK.finditer(line):
        token = normalize(match.group(1))
        last_end = match.end()
        if is_pointer(token, root, heads):
            refs.append((token, "backtick"))
    for match in MD_LINK.finditer(line):
        token = normalize(match.group(1))
        last_end = max(last_end, match.end())
        if token:
            refs.append((token, "link"))
    tail = line[last_end:]
    if "`" in tail:
        for raw in TAIL_SPLIT.split(tail[tail.index("`") + 1:]):
            if not raw or PUNCT_ONLY.match(raw):
                continue
            if is_pointer(normalize(raw), root, heads):
                return refs, True
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
def symbol_variants(token: str) -> list[str]:
    """「指到某个函数/常量」的写法 → 可能的文件路径，由近到远。

    `tools/evidence_map.assertion_path()` → `tools/evidence_map.py`、`tools/evidence_map`
    `tools/pool/queue.py:Entry.state`    → 先按上面的 `normalize` 已剥行号，落到 `.py` 本体

    ★ 卡 F6：本仓的 changelog / 卡规格大量写「`tools/wb_verify.expected_gate_names()`」
      这种「文件.成员()」—— 它指的是**存在的模块里的成员**，旧判据把它整串当文件名 ⇒ 假断链。
    """
    clean = normalize(token)
    if not clean:
        return []
    out: list[str] = []
    head, _, last = clean.replace("\\", "/").rpartition("/")
    # 末段形如 `name.member` / `name.member()`：把 `.member` 当成成员名剥掉
    bare = re.sub(r"(\(\))?$", "", last)
    m = re.match(r"^(.+?)\.[A-Za-z_][A-Za-z0-9_]*$", bare)
    if m and ext_of(bare) not in OWN_EXTS:
        stem = m.group(1)
        for suffix in ("", ".py", ".toml", ".md", ".json"):
            cand = (head + "/" if head else "") + stem + suffix
            if ext_of(cand) in OWN_EXTS or suffix == "":
                out.append(cand)
    return out


def check_dead_refs(root: Path, docs: list[Path]) -> tuple[list[Finding], list[Skip]]:
    """判据 1：死指针（判不出的地方如实记 skip）。

    ★ **判据顺序就是判据**（改这条顺序 = 改判据，不是重构）。逐条：
        外链（`URL_PREFIXES`）           ⇒ 不是指针（不判，也不记 skip）
      → 绝对路径 / `~`                   ⇒ skip「仓外/绝对路径」
      → 模板占位 / 通配                  ⇒ skip「模板占位」
      → `..` 逃逸                        ⇒ skip「指到仓库外面去了」
      → `resolve()` 命中                 ⇒ **正常**（存在就是存在，扩展名不算数）
      → `symbol_variants()` 命中         ⇒ **正常**（`文件.成员()` 的成员引用）
      → gitignore 命中                   ⇒ skip「gitignored 产物（不随树分发）」
      → `gates/diag/` 前缀               ⇒ skip「gates/diag 产物（不随 worktree 分发）」
      → 扩展名不在 `OWN_EXTS`            ⇒ skip「别仓路径」（**兜底猜测**，只在确实不存在之后）
      → 其余                             ⇒ **死指针**
    另：行尾反引号不成对 ⇒ **只**把尾巴那一段记 skip，同一行里成对的引用照判（卡 F10：
    整行丢掉会让判得了的也漏掉）。

    ★ 为什么「存在性」必须排在「扩展名猜测」前面（实测，不是审美）：
      旧顺序把扩展名启发式放在 `resolve()` 之前 ⇒ 实测 245 条「别仓类型」skip 里
      **135 条的文件就躺在磁盘上**（`gates/diag/notifications.jsonl`、`logs/timeflow.jsonl`、
      `data/timeflow.db` …），17 条其实是成员引用，25 条其实是 gitignored 产物
      （理由还写反了：记成「别仓」而不是「产物」），只有 68 条真该判别仓。
      口径因此改成：**存在就是存在**；只有「不存在 **且** 本仓从不跟踪这个类型」才推定为
      别仓引用。这样 skip 只覆盖「真判不出」，不再拿类型当先行筛子把真文件挡在外面。

    ★ 两条 F6 边界保留但不先行（都是实测出来的假阳性，不是「放宽」）：
      ① **别仓类型**：末段扩展名不在 `OWN_EXTS`（本仓从来没跟踪过 `.ts`/`.php`/`.go`…）
         ⇒ 它引的是**别人的仓**（`复盘/DSH插件-*.md` 里那批 `src/core/verification.ts`）。
         记 skip 不记 finding —— skip 不算 PASS，数字仍看得见。
      ② **成员引用**：`tools/evidence_map.assertion_path()` 这种「文件.成员()」先按
         `symbol_variants` 落到 `文件.py` 再判，落得住就不算断链。
    """
    findings: list[Finding] = []
    skips: list[Skip] = []
    # (where, token, derived rel, 扩展名)：留到最后批量判 gitignore / diag / 别仓兜底
    missing: list[tuple[str, str, str, str]] = []
    root_nc = os.path.normcase(_norm(root))
    heads: dict[str, bool] = {}

    for md in docs:
        text = read_text(md)
        where_file = rel(md, root)
        for lineno, line in body_lines(text):
            refs, unparsable = refs_in_line(line, root, heads)
            if unparsable:
                # ★ 不 continue：这一行**成对的**引用照判，只是尾巴那一段记 skip。
                #   旧写法 `continue` 会把判得了的一起丢掉（卡 F10）。
                skips.append(Skip(f"{where_file}:{lineno}", line.strip()[:40],
                                  "行尾反引号不成对，这一段判不了"))
            for token, kind in refs:
                where = f"{where_file}:{lineno}"
                if token.startswith(URL_PREFIXES):
                    continue  # 外链不在判据 1 的范围里（不判，也不冒充 skip）
                if DRIVE.match(token) or token.startswith(("/", "~")):
                    # ★ 存在性优先：盘符绝对路径**盘上真有**就说明它指向的东西在
                    #   （`D:/repo/infra/pool/projects.toml` 实测 120 条这种），
                    #   这时既不判死也不该记 skip —— skip 只能留给「真判不出」。
                    #   `/` 开头与 `~` 开头仍一律 skip：前者在 Windows 上不是真路径，
                    #   后者展开到谁的 home 取决于环境，判了也是假读数。
                    if DRIVE.match(token) and os.path.exists(os.path.normpath(token)):
                        continue
                    skips.append(Skip(where, token, "仓外/绝对路径，判不了"))
                    continue
                if any(ch in token for ch in PLACEHOLDER_CHARS) or PLACEHOLDER_STEM.match(
                    token.replace("\\", "/").rsplit("/", 1)[-1]
                ):
                    skips.append(Skip(where, token, "模板占位/通配，判不了"))
                    continue
                if outside_repo(token, md, root, root_nc=root_nc):
                    skips.append(Skip(where, token, "指到仓库外面去了"))
                    continue
                # ★ 存在性优先于类型猜测：# 命中的话它就在仓里，扩展名不算数
                if resolve(token, md, root, kind, root_nc=root_nc) is not None:
                    continue
                if any(resolve(cand, md, root, kind, root_nc=root_nc) is not None
                       for cand in symbol_variants(token)):
                    continue
                # 到这儿还不存在 ⇒ 剩下的理由要问 git / 问前缀 / 才轮到扩展名兜底，
                # 而 git 只能批量问（一次子进程问完），所以先攒着，出循环再判。
                missing.append((where, token, repo_rel(token, md, root, kind), ext_of(token)))

    # 一次问 git：这些不存在的路径里，哪些是 gitignored 产物（跳过，不算断链）
    ignored_set = ignored(root, sorted({derived for _, _, derived, _ in missing}))
    ignored_flat = {path.rstrip("/") for path in ignored_set}
    for where, token, derived, ext in missing:
        if derived in ignored_set or derived.rstrip("/") in ignored_flat:
            skips.append(Skip(where, token, "gitignored 产物（不随树分发）"))
            continue
        if token.replace("\\", "/").startswith(DIAG_PREFIX):
            skips.append(Skip(where, token, "gates/diag 产物（不随 worktree 分发）"))
            continue
        # ★ 兜底猜测排在最后：不存在 **且** 本仓从不跟踪这个类型，才推「别仓引用」
        if ext and ext not in OWN_EXTS:
            skips.append(Skip(where, token,
                              f"`{ext}` 不是本仓跟踪过的类型 ⇒ 判为别仓路径"))
            continue
        findings.append(Finding("dead_ref", where, token))
    return findings, skips


GENERATED = "<!-- generated by scripts/gen_doc_index.py; do not edit -->"

# 句子里点名了**别的**文档（卡 A272 / 0003 / docs/x.md）时，那多半在说别人过时，
# 不是在说本文档自己。只在主语与关键词之间这一段里看。
_OTHER_DOC = re.compile(r"卡[A-Za-z]*\d|[A-Z]\d{1,3}|\d{3,4}|docs/|\.md")


def superseded_declarations(body: str) -> list[str]:
    """正文里**自己声明自己过时**的句子；裸词不算。

    认的三种句式见 `SUPERSEDED_PATTERNS` / `SUPERSEDED_HEADING` 上方注释：
    带主语的句子（`本文档已废弃` / `本文档不再适用。`）、主语 + 被 X 取代、标题即声明。
    否定句（`并非不再适用`）、主语与关键词之间夹了「的」的「被取代」（说的是别的对象）、
    以及**没有主语**只靠关键词落句末的（`这条路现已废弃。`）都不算。

    返回命中的片段（去重，按出现顺序），只用于拼 finding 的说明文字。
    """
    hits: list[str] = []

    def self_claim(kw: str, gap: str, before: str, guards: tuple[str, ...]) -> bool:
        """`gap` 是主语到关键词之间那段；`before` 是原文里关键词前面那一小段。

        `guards` 由句式决定（见 `SUPERSEDED_PATTERNS`）：不是每个守卫都适用。
        """
        if chr(10) in gap:                      # 不跨行：声明必须落在同一行里
            return False
        if _NEGATION.search(before.strip()):    # `并非不再适用` / `未被取代`
            return False
        if "object" in guards and _OBJECT_MARK in gap:
            return False                        # `本文档的 A 已被 B 取代` → 说的是 A
        return not ("other_doc" in guards and _OTHER_DOC.search(gap))

    for pattern, guards in SUPERSEDED_PATTERNS:
        for match in pattern.finditer(body):
            kw = match.group("kw")
            span = match.group(0)
            gap = match.groupdict().get("gap")
            if gap is None:
                gap = span[: span.rindex(kw)]
            # 否定词常常落在**匹配起点之前**（`本文档并非|不再适用`），
            # 所以取原文里关键词前面那一小段，而不是只取命中文案自己。
            kw_at = match.start() + span.rindex(kw)
            before = body[max(0, kw_at - 8): kw_at].rsplit(chr(10), 1)[-1]
            if not self_claim(kw, gap, before, guards):
                continue
            hits.append(span.strip())
    for match in SUPERSEDED_HEADING.finditer(body):
        end = body.find(chr(10), match.start())
        line = body[match.start(): end if end >= 0 else len(body)]
        hits.append(line.strip().lstrip("#").strip())
    return list(dict.fromkeys(hits))


def check_superseded(root: Path, docs: list[Path]) -> list[Finding]:
    """判据 3：**文档自己声明自己过时**，却没有 `status: superseded` + `supersedes:`。

    收窄史（卡 A308）：第一版是「正文任意位置出现 `已废弃 / 被取代 / 不再适用` 就报」，
    实测 6 条命中全是误报 —— 自动生成的索引、文件名里带这个词、在讨论/定义词表的卡、
    讲这个概念的调研文章。**裸词与"谁在声明"无关**，所以只认自声明句式。

    不判的三类（都不算"判不出"，故不进 skips 通道）：
    - 首行是 `GENERATED` 锚点的自动生成文件（内容由 scripts/gen_doc_index.py 派生）；
    - 只搜正文与标题，**不搜文件名**（`复盘/已废弃-xxx.md` 这种是文件名，不是声明）；
    - frontmatter 已有 `status: superseded` + `supersedes:` 的，已标注，跳过。
    """
    findings: list[Finding] = []
    for md in docs:
        text = read_text(md)
        first = text.lstrip(chr(0xFEFF)).split(chr(10), 1)[0].strip()
        if first == GENERATED:
            continue  # 自动生成文件：正文不是人写的，声明与否都不算欠账
        meta, body, _ = split_frontmatter(text)
        hits = superseded_declarations(body)
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
            f"正文自声明「{hits[0]}」，但没有 frontmatter status: superseded + supersedes:",
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


def render_baseline(
    values: dict[str, int], generated_at: str, *, drift_judged: bool = True
) -> str:
    """基线文件全文：文件头写**重刷命令**与**生成时间**（卡 E39 判据 1 的格式）。

    `drift` 记下来但当"可漂移量"看；它这一次判不了（没有 git / 台账）时**不落盘** ——
    把不确定的数写成 0 等于把"判不出"当合格。
    """
    lines = [
        "# 文档门禁欠账基线（卡 F3 / T-AG451；卡 E39 / T-AG493 重刷）"
        "—— `scripts/check_docs.py` 的地板。",
        "#",
        "# 重刷命令（同一组读数连跑两次，本文件字节不变）：",
        f"#   {BASELINE_REFRESH_CMD}",
        f"# 生成时间：{generated_at}",
        "#",
        "# 口径（要改先读 `scripts/check_docs.py` 的文件头 —— 判据与边界都写在那里）：",
        "#   ① `dead_refs` / `superseded` 记**当前欠账条数**，只能降不能升：",
        "#      现在比这里多 ⇒ 那道门当场红（`--mode report` 也红）。降了之后请把这里调低。",
        "#   ② `drift` 也记下来，但它是**可漂移量**（每一笔代码提交都会动它）：",
        "#      输出里只做对照，**不参与 ratchet**。",
        "#   ③ `skip`（判不出）**绝不记在这里**：把不确定当合格等于自欺。",
        "#   ④ 这张表只许跟着**真还债**下调，不许为了让门变绿往上调（那等于把判据改软）。",
        "[baseline]",
        f'updated = "{generated_at[:10]}"',
        f'task = "{BASELINE_TASK}"',
        f"dead_refs = {values['dead_refs']}",
    ]
    if drift_judged:
        lines.append(f"drift = {values['drift']}")
    else:
        lines.append("# drift 本次判不了（见 skip），没写基线 —— 不确定的数不落盘")
    lines.append(f"superseded = {values['superseded']}")
    return "\n".join(lines) + "\n"


def write_baseline_file(root: Path, report: Report) -> tuple[Path, bool]:
    """把当前读数写成基线；**同一组读数重复跑不重写**（文件字节不变）。

    返回（基线路径, 这次有没有改文件）。第二次跑不改文件 —— 生成时间也就不会变，
    判据 1（两次跑字节相同）才成立。
    """
    path = root / BASELINE_REL
    counts = report.counts()
    values = {
        "dead_refs": counts["dead_refs"],
        "drift": counts["drift"],
        "superseded": counts["superseded"],
    }
    if path.is_file():
        old, why = load_baseline(path)
        same = (
            old.get("dead_refs") == values["dead_refs"]
            and old.get("superseded") == values["superseded"]
            and (not report.drift_judged or old.get("drift") == values["drift"])
        )
        if not why and same and "重刷命令" in read_text(path):
            return path, False
    text = render_baseline(
        values,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        drift_judged=report.drift_judged,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return path, True


# --------------------------------------------------------------------------- 汇合
def scan(root: Path) -> Report:
    """跑完四条判据，收成一份读数（纯读：一个字节都不写）。"""
    report = Report(root=root)
    docs, dropped_docs = iter_docs_split(root)
    for path, reason in dropped_docs:
        report.skips.append(Skip(rel(path, root), "-", reason))
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
    report.drift_judged = not drift_skips
    report.skips.extend(drift_skips)

    baseline, why = load_baseline(root / BASELINE_REL)
    if why:
        report.skips.append(Skip(BASELINE_REL, "-", f"{why} ⇒ ratchet 判不了"))
    else:
        report.baseline = baseline
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

    # ★ 卡 E39：欠账与「判不出」**分两行** —— 前者参与红/绿判定，后者永远是独立一行。
    counts = report.counts()
    for key, label in (("dead_refs", "死指针"), ("drift", "drift"), ("superseded", "superseded")):
        now = counts[key]
        if key in report.baseline:
            was = report.baseline[key]
            tail = " · 可漂移量，只报告" if key == "drift" else ""
            say(f"CHECK_DOCS: {label} {now}（基线 {was}，{now - was:+d}{tail}）")
        else:
            say(f"CHECK_DOCS: {label} {now}（基线未记）")
    if report.skips:
        say(f"CHECK_DOCS: 判不出 {len(report.skips)} 条（skip）—— 这不是 PASS")
    else:
        say("CHECK_DOCS: 判不出 0 条（skip）—— 判完了")

    code = exit_code(report, mode)
    over = any("涨到" in line for line in report.ratchet)
    total = len(report.dead_refs) + len(report.superseded) + len(report.drift)
    if code == 1 and over:
        say("CHECK_DOCS: FAIL ❌（超基线：只许降不许升）")
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
    write_baseline: bool = False,
) -> int:
    """跑一遍；`root` 不给 = 真仓库根（自检拿合成小树喂坏样例）。

    `write_baseline=True` 时把当前读数写成基线后退出（`--write-baseline`）；
    ★ 幂等：同一组读数第二次跑只打印「未变」，**不重写文件**。
    """
    base = Path(root).resolve() if root is not None else ROOT.resolve()
    report = scan(base)
    if write_baseline:
        say = out or (lambda line: print(line, flush=True))
        if not report.scanned.get("文件"):
            say("CHECK_DOCS: FAIL ❌（一个文件都没扫到，不写基线）")
            return 1
        path, changed = write_baseline_file(base, report)
        counts = report.counts()
        drift = f"drift {counts['drift']}" if report.drift_judged else "drift 判不了（未写）"
        say(f"[write] 基线：{rel(path, base)}（{'已更新' if changed else '未变，字节不动'}）")
        say(f"CHECK_DOCS: 基线已重刷 → dead_refs {counts['dead_refs']} / {drift}"
            f" / superseded {counts['superseded']}")
        return 0
    if json_out:
        print(json.dumps(as_json(report), ensure_ascii=False, indent=2))
    else:
        if doctor:
            print_doctor(report, out=out)
        print_report(report, mode, out=out)
    return exit_code(report, mode)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """命令行：`--mode report|block` / `--doctor` / `--json` / `--write-baseline` / `--root`。"""
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
    parser.add_argument("--write-baseline", action="store_true",
                        help="把当前 dead_refs / drift / superseded 写成基线"
                             "（幂等：连跑两次字节不变）")
    parser.add_argument("--decisions", action="store_true",
                        help="检查 docs/decisions/ 的决策记录（卡 F4；不做死指针/drift）")
    parser.add_argument("--root", default=None,
                        help="查哪棵树（默认 = 本脚本所在仓库根）")
    return parser.parse_args(argv)




# --------------------------------------------------------------------------- 决策记录（卡 F4）
# 判据 4 的基准是 git 的 HEAD；本节的函数来自卡 F4 / T-AG452 的实现，原样并入。
#: ★ 卡 148：起子进程一律不弹窗（口径与 `tools/pipeline_view.py` 同款）。
NO_WINDOW: dict[str, int] = (
    {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
)

#: 记录住哪（相对仓库根）。
DECISIONS_DIR = "docs/decisions"

#: 文件名：4 位编号 + 连字符 + slug（小写字母 / 数字 / 连字符）。
NAME_RE = re.compile(r"^([0-9]{4})-([a-z0-9]+(?:-[a-z0-9]+)*)\.md$")

#: 合法 status（大小写不敏感读入，统一成这个写法）。
STATUSES = ("Proposed", "Accepted", "Superseded")

#: 四段标题：顺序固定，一段不许少、不许空。
REQUIRED_SECTIONS = ("背景与问题", "候选方案", "决定", "把握程度")

H2_RE = re.compile(r"(?m)^##[ \t]+(.+?)[ \t]*$")
FIELD_RE = re.compile(r"(?mi)^[ \t]*(status|supersedes|superseded-by)[ \t]*:[ \t]*(.*?)[ \t]*$")
CONFIDENCE_RE = re.compile(
    r"(?m)^[ \t]*(?:[-*][ \t]+)?(?:\*\*)?(high|medium|low)(?:\*\*)?[ \t]*"
    r"(?:——|—|–|-|:|：)[ \t]*(\S.*)$",
    re.I,
)

#: `check(head=...)` 的哨兵：明确表示「这棵树没有 HEAD 可比」。
NO_HEAD = object()


@dataclass(frozen=True)
class Record:
    """一条解析出来的决策记录。"""

    number: int
    status: str
    supersedes: str | None
    superseded_by: str | None
    frozen_header: str
    body: str


@dataclass
class Result:
    """一次检查的读数。"""

    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    count: int = 0
    span: str = "-"
    links: int = 0
    incomplete: bool = False


# --------------------------------------------------------------------------- 解析
def split_header(text: str) -> tuple[str, str]:
    """切成（头信息, 正文）；正文从第一个二级标题那一行起。"""
    normal = text.replace("\r\n", "\n")
    for index, line in enumerate(normal.split("\n")):
        if re.match(r"^##[ \t]", line):
            head = "\n".join(normal.split("\n")[:index])
            body = "\n".join(normal.split("\n")[index:])
            return head, body
    return normal, ""


def _frozen_header(header: str) -> str:
    """冻结的头信息：去掉唯一允许改的两行（`Status` / `Superseded-by`）。"""
    keep = [
        line.rstrip()
        for line in header.split("\n")
        if not re.match(r"^[ \t]*(status|superseded-by)[ \t]*:", line, re.I)
    ]
    return "\n".join(keep).strip()


def _parse_ref(raw: str) -> tuple[str | None, str | None]:
    """`Supersedes: 0003` → `0003`；留空 → `(None, None)`；格式不对 → `(None, 说明)`。"""
    value = raw.strip()
    if not value:
        return None, None
    match = re.match(r"^([0-9]{4})(?:[-._ ]|$)", value)
    if not match:
        return None, f"要写 4 位编号（拿到的是 {value!r}）"
    return match.group(1), None


def _sections(body: str) -> list[tuple[str, str]]:
    """`[(标题, 正文), …]`；正文到下一个二级标题为止。"""
    hits = list(H2_RE.finditer(body))
    out: list[tuple[str, str]] = []
    for index, hit in enumerate(hits):
        start = body.find("\n", hit.end())
        start = len(body) if start < 0 else start + 1
        end = hits[index + 1].start() if index + 1 < len(hits) else len(body)
        out.append((hit.group(1), body[start:end].strip()))
    return out


def parse_record(rel: str, text: str, number: int) -> tuple[Record | None, list[str]]:
    """一条记录的结构判据；返回（记录, 问题）。结构坏到没法建记录时记录为 None。"""
    problems: list[str] = []
    head, body = split_header(text)
    fields: dict[str, str] = {}
    for match in FIELD_RE.finditer(head):
        key = match.group(1).lower()
        if key in fields:
            problems.append(f"{rel}: 头信息 `{match.group(1)}` 写了不止一次")
        fields[key] = match.group(2)

    raw_status = fields.get("status", "").strip()
    status = raw_status[:1].upper() + raw_status[1:].lower() if raw_status else ""
    if not raw_status:
        problems.append(f"{rel}: 缺 `Status:`（Proposed / Accepted / Superseded）")
    elif status not in STATUSES:
        problems.append(f"{rel}: status 不合法（{raw_status!r}；只许 {' / '.join(STATUSES)}）")

    supersedes, bad_up = _parse_ref(fields.get("supersedes", ""))
    superseded_by, bad_down = _parse_ref(fields.get("superseded-by", ""))
    for bad in (bad_up, bad_down):
        if bad:
            problems.append(f"{rel}: Supersedes / Superseded-by {bad}")

    problems += _template_problems(rel, body)

    if not raw_status or status not in STATUSES:
        return None, problems
    return (
        Record(
            number=number,
            status=status,
            supersedes=supersedes,
            superseded_by=superseded_by,
            frozen_header=_frozen_header(head),
            body=body.replace("\r\n", "\n").rstrip(),
        ),
        problems,
    )


def _template_problems(rel: str, body: str) -> list[str]:
    """五段模板：齐全 / 顺序 / 不许多 / 不许空 / 把握程度带一句为什么。"""
    problems: list[str] = []
    sections = _sections(body)
    names = [name for name, _ in sections]

    for name in REQUIRED_SECTIONS:
        if name not in names:
            problems.append(f"{rel}: 缺段落 `## {name}`")
    for name in names:
        if name not in REQUIRED_SECTIONS:
            problems.append(
                f"{rel}: 多出段落 `## {name}`"
                f"（模板只有四段：{' / '.join(REQUIRED_SECTIONS)}）"
            )
    for name in sorted({name for name in names if names.count(name) > 1}):
        problems.append(f"{rel}: 段落 `## {name}` 写了两遍")

    present = [name for name in names if name in REQUIRED_SECTIONS]
    expected = [name for name in REQUIRED_SECTIONS if name in present]
    if present != expected:
        problems.append(f"{rel}: 段落顺序不对（要 {' → '.join(REQUIRED_SECTIONS)}）")

    for name, content in sections:
        if name in REQUIRED_SECTIONS and not content:
            problems.append(f"{rel}: 段落 `## {name}` 是空的")

    confidence = dict(sections).get("把握程度", "")
    matches = CONFIDENCE_RE.findall(confidence)
    if "把握程度" in names and not matches:
        problems.append(
            f"{rel}: `## 把握程度` 要以 high / medium / low 开头并跟一句为什么"
            "（例：medium —— 只在单机验过）"
        )
    elif matches and len(matches[0][1].strip()) < 4:
        problems.append(f"{rel}: `## 把握程度` 的「为什么」太短（至少几个字）")
    return problems


# --------------------------------------------------------------------------- git
def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """跑一条 git；★ 带 NO_WINDOW，重定向走了就不会闪窗。"""
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        **NO_WINDOW,
    )


def _has_head(root: Path) -> bool:
    return _git(root, "rev-parse", "--verify", "HEAD").returncode == 0


def _head_texts(root: Path) -> dict[str, str]:
    """HEAD 里 `docs/decisions/` 下每份文件的原文（相对路径 → 文本）。"""
    listing = _git(root, "ls-tree", "-r", "--name-only", "HEAD", "--", DECISIONS_DIR + "/")
    if listing.returncode != 0:
        return {}
    out: dict[str, str] = {}
    for name in (line.strip() for line in listing.stdout.splitlines()):
        if not name or not NAME_RE.match(name.rsplit("/", 1)[-1]):
            continue
        shown = _git(root, "show", f"HEAD:{name}")
        if shown.returncode == 0:
            out[name] = shown.stdout
    return out


# --------------------------------------------------------------------------- 检查
def _load(directory: Path, res: Result) -> dict[str, Record]:
    """扫目录，返回（相对路径 → 记录）；结构问题直接记进 res。"""
    records: dict[str, Record] = {}
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.suffix != ".md" or path.name == "README.md":
            continue
        rel = f"{DECISIONS_DIR}/{path.name}"
        match = NAME_RE.match(path.name)
        if not match:
            res.problems.append(
                f"{rel}: 文件名不合规（要 0001-小写slug.md，slug 只用小写字母、数字、连字符）"
            )
            continue
        record, problems = parse_record(rel, path.read_text(encoding="utf-8"), int(match.group(1)))
        res.problems += problems
        if record is not None:
            records[rel] = record
    return records


def _numbering(records: dict[str, Record], res: Result) -> None:
    numbers = sorted(record.number for record in records.values())
    res.span = f"{numbers[0]:04d}..{numbers[-1]:04d}" if numbers else "-"
    if not numbers:
        return
    expected = list(range(1, len(numbers) + 1))
    if numbers == expected:
        return
    missing = sorted(set(expected) - set(numbers))
    dupes = sorted({number for number in numbers if numbers.count(number) > 1})
    detail = "编号必须从 0001 起连续"
    if missing:
        detail += "；缺 " + "、".join(f"{number:04d}" for number in missing)
    if dupes:
        detail += "；重号 " + "、".join(f"{number:04d}" for number in dupes)
    res.problems.append(f"{DECISIONS_DIR}/: {detail}")


def _status_links(records: dict[str, Record], res: Result) -> None:
    by_number = {record.number: record for record in records.values()}
    for rel, record in records.items():
        own = f"{record.number:04d}"
        for label, ref in (("Supersedes", record.supersedes),
                           ("Superseded-by", record.superseded_by)):
            if ref == own:
                res.problems.append(f"{rel}: {label} 指向自己")

        if record.status == "Superseded" and not record.superseded_by:
            res.problems.append(f"{rel}: status 是 Superseded，却没写 `Superseded-by:`")
        if record.status != "Superseded" and record.superseded_by:
            res.problems.append(
                f"{rel}: 写了 `Superseded-by:` 却没把 status 改成 Superseded"
                f"（现在是 {record.status}）"
            )

        if record.supersedes:
            other = by_number.get(int(record.supersedes))
            if other is None:
                res.problems.append(f"{rel}: Supersedes 指向不存在的 {record.supersedes}")
            else:
                res.links += 1
                if other.superseded_by != own:
                    res.problems.append(
                        f"{rel}: 取代了 {record.supersedes}，但它的 `Superseded-by` "
                        f"是 {other.superseded_by or '（空）'}，不是 {own}"
                    )
                if other.status != "Superseded":
                    res.problems.append(
                        f"{rel}: 取代了 {record.supersedes}，但它的 status 还是 {other.status}"
                    )
        if record.superseded_by:
            other = by_number.get(int(record.superseded_by))
            if other is None:
                res.problems.append(f"{rel}: Superseded-by 指向不存在的 {record.superseded_by}")
            elif other.supersedes != own:
                res.problems.append(
                    f"{rel}: Superseded-by 是 {record.superseded_by}，但它的 `Supersedes` "
                    f"是 {other.supersedes or '（空）'}，不是 {own}"
                )


def _append_only(records: dict[str, Record], head: dict[str, str], res: Result) -> None:
    """HEAD 里已 Accepted / Superseded 的记录：正文与冻结头信息不许改、不许删、不许倒退。"""
    head_records: dict[str, Record] = {}
    for rel, text in head.items():
        match = NAME_RE.match(rel.rsplit("/", 1)[-1])
        if not match:
            continue
        record, _ = parse_record(rel, text, int(match.group(1)))
        if record is not None:
            head_records[rel] = record

    for rel, before in head_records.items():
        after = records.get(rel)
        if after is None:
            res.problems.append(f"{rel}: HEAD 里已有、工作区不见了 —— 决策记录不许删")
            continue
        if before.status not in ("Accepted", "Superseded"):
            continue
        if after.body != before.body:
            res.problems.append(
                f"{rel}: 正文被改过（HEAD 里已是 {before.status}）—— 改主意要新写一条并双向链接"
            )
        if after.frozen_header != before.frozen_header:
            res.problems.append(
                f"{rel}: 头信息被改过（只许改 `Status` 与 `Superseded-by` 两行）"
            )
        allowed = {"Accepted": ("Accepted", "Superseded"), "Superseded": ("Superseded",)}
        if after.status not in allowed[before.status]:
            res.problems.append(
                f"{rel}: status 倒退了（HEAD={before.status} → 现在={after.status}）"
            )


def check(root: Path, head: dict[str, str] | object | None = None) -> Result:
    """检查一棵树；`head` 不给 = 问 git，`NO_HEAD` = 当作没有 HEAD，dict = 测试注入。"""
    res = Result()
    directory = root / DECISIONS_DIR
    if not directory.is_dir():
        res.problems.append(f"{DECISIONS_DIR}/ 不存在 —— 决策记录没有家")
        return res

    records = _load(directory, res)
    res.count = len(records)
    _numbering(records, res)
    _status_links(records, res)

    if head is None:
        if not _has_head(root):
            res.notes.append("只追加：没有 HEAD（新仓库 / 不是 git 仓库）—— 这一条没判")
            res.incomplete = True
            return res
        head = _head_texts(root)
    if head is NO_HEAD:
        res.notes.append("只追加：明确跳过（调用方说这棵树没有 HEAD）")
        res.incomplete = True
        return res
    _append_only(records, head, res)
    return res
def build_decisions_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check_docs.py",
        description="文档门禁：决策记录（docs/decisions）的只追加与固定五段",
    )
    parser.add_argument(
        "--decisions", action="store_true", help="检查决策记录（本卡唯一模式）",
    )
    parser.add_argument(
        "--root", default=None, help="换一棵树（测试用；默认 = 本脚本所在仓库根）",
    )
    return parser


def main_decisions(argv: list[str] | None = None) -> int:
    parser = build_decisions_parser()
    args = parser.parse_args(argv)
    if not args.decisions:
        parser.print_help()
        return 2
    root = Path(args.root).resolve() if args.root else ROOT
    res = check(root)

    print(
        f"[info] 决策记录：扫到 {res.count} 条（编号 {res.span}），"
        f"supersedes 链 {res.links} 对"
    )
    for note in res.notes:
        print(f"[skip] {note}")
    for problem in res.problems:
        print(f"[FAIL] {problem}")
    if res.problems:
        print(f"[FAIL] 共 {len(res.problems)} 处不通过")
        return 1
    if res.incomplete:
        print("[WARN] 有判据没判完（见上面的 skip）—— 这不算通过")
        return 3
    print("[OK ] 决策记录检查通过")
    return 0
if __name__ == "__main__":
    args = parse_args()
    if args.decisions:
        sys.exit(main_decisions(["--decisions", *(["--root", args.root] if args.root else [])]))
    sys.exit(main(args.root, args.mode, args.doctor, args.json, write_baseline=args.write_baseline))
