r"""契约段 ↔ 判据的对账器（卡 217 · T-G330）。

## 为什么有它

本仓有一批「写在文档里的契约段」（承诺 / 不变量 / 边界，例如「删掉整个 `skills/` 框架仍完整
可用」、「`harness/` 复制体不依赖 `tools/`」、「派活产物必须落主仓」）—— 这些句子住在人能读
的地方，而**每一条都应该有一条机器判据盯着**。有的有（如 `skills/` 那条有自检钉子）；有的只有
话。本工具把对账做成机器可跑的，并把「只有话」的那几条列出来。

## 与既有工具的差异（★ 别混）

- `wb_invariants.py --check`：核**不变量台账指针**存在性（只看路径 / 用例名在不在，**不真跑判据**）
- `wb_invariants.py --clauses`：核**条款台账指针**存在性（同上，**不真跑**）
- 本工具：扫**文档里的契约段**，对每条 `judge:` 必须**真能执行**并贴读数；指到不存在的 ⇒ **红**

★ 不许把「有归属」（审计第 ⑨ 条管的）当成「有判据」（本卡管的）。

## 契约段清单

真源 = 本仓文档里那些「承诺 / 不变量 / 边界」的句子。清单写在模块级 `CONTRACTS`（下文），
每条指明 `(文件, 锚点子串)`：工具去文件里**现读**那一句，证明契约段真在文档里（不是手写第二份），
并取行号与原句。

对每条契约段，**必须**给出下面之一：
  - `judge:` 指向一条**真存在**的判据（pytest 用例 / 一个真能跑的命令），**并且当场跑一次贴读数**；
  - `no_judge:` 如实写「只有话」，并写明**为什么现在装不了**。

## 退出码

- 每条契约段都有 `judge:` 且能跑（rc=0）= 0；
- 有 `no_judge:` / `judge:` 跑红 / 源文件找不到 / 锚点找不到 = 非零
  （**如实反映「还有多少条只有话」** —— 别为了绿而放宽）。

★ 不许做成「扫一遍文档就算完」：`judge:` 指到的判据**必须真能执行**，指到不存在的 ⇒ 红。

## 表格自检（`--check-doc`，卡 E101 · T-AG610）

`复盘/契约-判据对账.md` 那张表是**人**读的当前真值，而它以前没人守：测试只核 13 / judge_ok 10 /
no_judge 3 三个总数，表里一格都不核（实测漂了 9 处）。`--check-doc` 把表逐格与**活体**比对，
**不跑判据**（秒级）：

- **源格** `path:line`：行号必须 == `find_clause()` 现读的行号，路径也逐字相同；
- **原句格**：归一（去 `**` / 反引号 / 行首 `>` / 空白压一个空格）后必须是 live 原句归一后的
  **子串**，且长度 ≥ `MIN_EXCERPT`（一个词冒充不算）；
- **判据格**：pytest ⇒ `tests/…::case`（带 `tests/` 前缀）；cmd ⇒ argv 去掉 `python -X utf8`
  前缀后的 join；允许「同 CX-0N」指向前一条（解析成那条的 live 值）；
- **条数**：`### 有判据的（N 条 · judge_ok）` / `### 只有话的（M 条 · no_judge）` / 读数块首行
  `…：K 条 ===` 分别 == 有 judge 的条数 / 有 no_judge 的条数 / `len(CONTRACTS)`。

★ **不归它核的那一格**：读数块里的 `分布：judge_ok … / judge_red …` 是**跑后**读数
（要真跑 13 条判据才算得出）—— 那是本工具默认模式的输出，不是表能静态证明的东西。

退出码：全对上 0 / 有漂 1（逐条点名 CX 与行号）/ 表读不出来 2（缺段、行列数不符）。

用法：

    python -X utf8 tools/contract_audit.py            # 对账（人读报告）
    python -X utf8 tools/contract_audit.py --json     # 结构化输出
    python -X utf8 tools/contract_audit.py --report   # 同默认（人读报告）
    python -X utf8 tools/contract_audit.py --check-doc  # 只核对账表（不跑判据）
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

ROOT = Path(__file__).resolve().parent.parent

#: Windows ⇒ `CREATE_NO_WINDOW`；其它平台 ⇒ `{}`。
#: ★ 真源在 `tools/pool/no_window.py`；这里本地定义是为了不引入 `pool` 包依赖
#:   （与 `tools/wb_state.py` / `tools/pipeline_view.py` 同款）。
NO_WINDOW: dict[str, int] = {"creationflags": 0x08000000} if os.name == "nt" else {}

#: 跑判据的硬超时（秒）—— 防一个判据卡死把整趟对账挂死。
JUDGE_TIMEOUT = 180.0

#: 人读的那张对账表（`--check-doc` 逐格核它；口径见模块 docstring）。
DOC_TABLE = "复盘/契约-判据对账.md"

#: 原句格最短长度：短于它就算「一个词冒充原句」，不承认（卡 E101）。
MIN_EXCERPT = 8


# ------------------------------------------------------------------ 契约段清单
#
# 每条 Contract：
#   id        CX-nn
#   source    (仓库相对路径, 锚点子串) —— 工具去文件里找子串，证明契约段真在文档里
#   judge     ("pytest", "tests/xxx.py::test_yyy") 或 ("cmd", ["python","-X","utf8",...])
#   no_judge  理由字符串（与 judge 二选一）
#   note      诚实说明（可选）
#
# ★ 锚点子串必须在源文件里**唯一**找到；找不到 ⇒ source_missing（红）。
# ★ judge 指到的判据**当场跑一次**；rc≠0 ⇒ judge_red（红）。


@dataclass(frozen=True)
class Contract:
    """一条写在文档里的契约段 + 它的判据（或只有话的如实标记）。"""

    cid: str
    source: tuple[str, str]
    judge: tuple[str, ...] | None = None
    no_judge: str = ""
    note: str = ""


CONTRACTS: list[Contract] = [
    # ---------------------------------------------------------- skills/ 层
    Contract(
        cid="CX-01",
        source=("skills/README.md", "删掉整个 `skills/` 目录，框架仍然完整可用"),
        judge=(
            "pytest",
            "tests/test_contract_audit.py::"
            "test_card_e124_core_skeleton_runs_without_skills",
        ),
        note=(
            "卡 E124 改指**整棵树**的判据：把全部被跟踪文件复制到临时树、删掉**整棵 skills/**、"
            "git init，再跑六条核心命令（入口 import / CLI --help / invariants / audit_titles / "
            "derived_docs / 门表构建）—— 要求全绿且输出里不出现带斜杠的 skills/。"
            "上一条（卡 E96 的合成 9 文件树）只证「门表构建不读 skills/」，证不了这句话；"
            "它保留在测试文件里，作为同族的窄判据。"
            "★ 反例对照见 tests/test_contract_audit.py::"
            "test_card_e124_core_probe_bites_on_a_known_red_command：同一套 harness 对一条"
            "已知会红的命令（scripts/audit_progress.py --all）必须报红，否则本条只是恒绿。"
            "★ 诚实边界：这句话的另一半「完整可用」**不成立** —— 删掉 skills/ 后有五道门会红"
            "（audit_progress / check_docs / contract_audit --check-doc / check_layers /"
            " pytest 收集），"
            "故本契约验的是「核心骨架可用」，不是「框架仍然完整可用」。"
        ),
    ),
    Contract(
        cid="CX-02",
        source=("skills/README.md", "里引用的每个命令名，必须能在"),
        judge=("cmd", ["python", "-X", "utf8", "skills/nails/check_commands.py"]),
        note="skills 层自检钉子①：SKILL.md 引用的命令名都能在 pipe --help 里找到",
    ),
    # ---------------------------------------------------------- harness/ 层
    Contract(
        cid="CX-03",
        source=("harness/README.md", "复制体**不依赖 `tools/`**"),
        judge=(
            "pytest",
            "tests/test_harness_manifest.py::test_card205_harness_copies_do_not_import_tools",
        ),
        note="卡 205 装的牙：复制体不挂 sys.path、不 from tools...；钉子扫 import 语句",
    ),
    Contract(
        cid="CX-04",
        source=("harness/README.md", "拿掉 `tools/` 后仍能跑"),
        judge=(
            "pytest",
            "tests/test_harness_manifest.py::test_card205_harness_copies_do_not_import_tools",
        ),
        note="CX-03 同一条钉子：不 import tools ⇒ 拿掉 tools 仍能跑",
    ),
    Contract(
        cid="CX-05",
        source=("harness/README.md", "原件/复制体输出逐字节相同"),
        judge=(
            "pytest",
            "tests/test_harness_manifest.py::test_card205_replica_renders_the_same_dispatch_as_original",
        ),
        note=(
            "卡 205 装的牙：逐字比较 render_dispatch；卡 203 改对原件、复制体没跟上正是从前"
            "没判据。★ 锚点原为「渲染的派活命令逐字节相同」，批 1（卡 214）把这句话改写成表格、"
            "措辞变成「输出逐字节相同」⇒ 集成时按现行文本更新锚点（判据本条未动）"
        ),
    ),
    Contract(
        cid="CX-06",
        source=("harness/README.md", "不登记 = 未知键，加载即报错"),
        judge=("pytest", "tests/test_harness_manifest.py::test_unknown_key_is_a_typo_not_silent"),
        note="manifest.py 的 SCHEMA 白名单：多一个键 = 拼错，当场报错而不是静默忽略",
    ),
    Contract(
        cid="CX-07",
        source=("harness/README.md", "**无静默默认值**"),
        judge=("pytest", "tests/test_harness_manifest.py::test_missing_key_named"),
        note="缺键 ⇒ ManifestError 指名道姓，不许偷偷用默认值",
    ),
    # ---------------------------------------------------------- 复盘/ 台账层
    Contract(
        cid="CX-08",
        source=("复盘/不变量台账.toml", "新能力没进这张表，就不算做完"),
        judge=("cmd", ["python", "-X", "utf8", "tools/wb_invariants.py", "--check"]),
        note="不变量台账核查器：逐条核 judge 路径与 nail 用例名真的存在（79 条）",
    ),
    Contract(
        cid="CX-09",
        source=("复盘/条款台账.toml", "每条人话条款要么有机器判据"),
        judge=("cmd", ["python", "-X", "utf8", "tools/wb_invariants.py", "--clauses"]),
        note="条款台账核查器：unjudgeable 必须带 note；covered 必须有 judge+nail（5 条）",
    ),
    # ---------------------------------------------------------- 审计层（第 ⑨ 条）
    Contract(
        cid="CX-10",
        source=("复盘/门禁收紧三条-T-G22.md", "必须挂在**一张**台账卡上"),
        judge=("cmd", ["python", "-X", "utf8", "scripts/audit_progress.py", "--all", "--no-git"]),
        note="审计第 ⑨ 条：契约 53 条操作全部有归属（本卡不动这条，只对账）",
    ),
    # ---------------------------------------------------------- 框架契约层（只有话）
    Contract(
        cid="CX-11",
        source=("复盘/框架-术语表与契约.md", "退出码表公开稳定"),
        no_judge=(
            "文档自标 ❌ 不满足：四套退出码表互不兼容（门禁 0/1/2/3/124 · CLI 0/1/2/3/4 · "
            "派活器 0/2/4/6/7 · run_bg 0/2/3），§3 泛用性 ① 现状不满足。要变 covered "
            "需要先统一退出码表（一张真源），属另一条卡的范围。"
        ),
        note="目标态，非已守住",
    ),
    Contract(
        cid="CX-12",
        source=("复盘/框架-术语表与契约.md", "项目相关值全部外置"),
        no_judge=(
            "文档自标 ❌ 不满足：硬编码 MODEL_WHITELIST（tools/wb_dispatch.py:132）/ "
            "FALLBACK_CLI_REL（:172）/ 端口 8531/8541（scripts/run_gates.py），§3 泛用性 "
            "③ 现状不满足。harness/ 是朝这个方向的现有尝试，但 tools/scripts 主体仍硬编码。"
        ),
        note="目标态，非已守住",
    ),
    Contract(
        cid="CX-13",
        source=("复盘/框架-术语表与契约.md", "只调用 → CLI；要扩展 → 库"),
        no_judge=(
            "文档自标缺口：tools/ 与 scripts/ 是顶级脚本，彼此 import 但没抽成可安装的库"
            "（§4 现状缺口）；src/timeflow/** 是库 + cli/main.py 是薄壳那半已做到，但 "
            "tools/scripts 那半还是脚本。要变 covered 需要把 tools/ 抽成库，属另一条卡。"
        ),
        note="目标态，非已守住",
    ),
]


# ------------------------------------------------------------------ 对账核心


@dataclass(frozen=True)
class JudgeResult:
    """跑一次判据的读数。"""

    rc: int
    tail: str
    ran: bool = True
    error: str = ""


@dataclass(frozen=True)
class ClauseResult:
    """一条契约段的对账结果。"""

    cid: str
    source_path: str
    source_line: int | None
    source_text: str
    status: str  # judge_ok / judge_red / no_judge / source_missing
    judge_kind: str
    judge_rc: int | None
    judge_tail: str
    reason: str
    note: str

    @property
    def ok(self) -> bool:
        return self.status == "judge_ok"


def find_clause(path: Path, anchor: str) -> tuple[int, str] | None:
    """在文件里找 anchor 子串，回 (行号, anchor 所在行原文)。找不到 ⇒ None。

    ★ 行号从 1 起；原句取 anchor 起点所在行的完整内容（去掉尾换行）。
    """
    text = path.read_text(encoding="utf-8")
    idx = text.find(anchor)
    if idx < 0:
        return None
    line_no = text.count("\n", 0, idx) + 1
    line_start = text.rfind("\n", 0, idx) + 1
    line_end = text.find("\n", idx)
    if line_end < 0:
        line_end = len(text)
    return line_no, text[line_start:line_end].rstrip()


def run_judge(judge: tuple[str, ...], root: Path) -> JudgeResult:
    """当场跑一次判据，回读数。

    judge 格式：
      ("pytest", "tests/xxx.py::test_yyy")  →  pytest tests/xxx.py::test_yyy -q --no-cov
      ("cmd",    ["python","-X","utf8",...]) →  跑该命令（python 换成 sys.executable）
    """
    kind = judge[0]
    if kind == "pytest":
        test_id = judge[1]
        argv = [
            sys.executable,
            "-X",
            "utf8",
            "-m",
            "pytest",
            test_id,
            "-q",
            "--no-cov",
            "--no-header",
            "-p",
            "no:cacheprovider",
        ]
    elif kind == "cmd":
        argv = list(judge[1])
        if argv and argv[0] == "python":
            argv[0] = sys.executable
    else:
        return JudgeResult(99, "", False, f"未知 judge 类型：{kind}")

    try:
        r = subprocess.run(  # noqa: S603 —— argv 受控（本仓配置），非外部输入
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(root),
            timeout=JUDGE_TIMEOUT,
            **NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return JudgeResult(124, "", False, f"判据超时（{JUDGE_TIMEOUT:.0f}s）")
    except OSError as exc:
        return JudgeResult(99, "", False, f"起不了判据：{exc}")

    out = (r.stdout or "").strip()
    tail = out.split("\n")[-1] if out else ""
    return JudgeResult(r.returncode, tail)


def audit(contracts: Sequence[Contract], root: Path = ROOT) -> list[ClauseResult]:
    """对每条契约段做对账 —— 回一串 ClauseResult。

    步骤：
      1. 去源文件找锚点子串 ⇒ 找不到 = source_missing（红）；
      2. 有 no_judge ⇒ 如实标（不算 judge_ok，退出码非零）；
      3. 有 judge ⇒ 当场跑一次 ⇒ rc=0 是 judge_ok，rc≠0 是 judge_red（红）；
         **例外：rc=3 = 判据自报「未验证」（这台机器缺前置，比如没有 CLI）
         ⇒ 记 no_judge 如实计入：不算 judge_ok，但也不算红**（卡 E49）。
    """
    results: list[ClauseResult] = []
    for c in contracts:
        rel_path, anchor = c.source
        path = root / rel_path
        if not path.exists():
            results.append(
                ClauseResult(
                    c.cid,
                    rel_path,
                    None,
                    "",
                    "source_missing",
                    "",
                    None,
                    "",
                    "源文件不存在",
                    c.note,
                )
            )
            continue
        found = find_clause(path, anchor)
        if found is None:
            results.append(
                ClauseResult(
                    c.cid,
                    rel_path,
                    None,
                    "",
                    "source_missing",
                    "",
                    None,
                    "",
                    "锚点子串在源文件里找不到",
                    c.note,
                )
            )
            continue
        line_no, text = found
        if c.no_judge:
            results.append(
                ClauseResult(
                    c.cid,
                    rel_path,
                    line_no,
                    text,
                    "no_judge",
                    "",
                    None,
                    "",
                    c.no_judge,
                    c.note,
                )
            )
            continue
        if c.judge is None:
            results.append(
                ClauseResult(
                    c.cid,
                    rel_path,
                    line_no,
                    text,
                    "source_missing",
                    "",
                    None,
                    "",
                    "既没 judge 也没 no_judge（配置错）",
                    c.note,
                )
            )
            continue
        jr = run_judge(c.judge, root)
        if jr.rc == 3:
            # 判据自报「未验证」：环境缺前置（云机没 CLI / 没某个解释器），不是契约违约。
            # 如实落 no_judge —— 既不当绿（那会漏掉真违约），也不当红（那是假红）。
            results.append(
                ClauseResult(
                    c.cid,
                    rel_path,
                    line_no,
                    text,
                    "no_judge",
                    c.judge[0],
                    jr.rc,
                    jr.tail,
                    "判据自报未验证（rc=3）：这台机器缺前置，见读数",
                    c.note,
                )
            )
            continue
        status = "judge_ok" if jr.rc == 0 else "judge_red"
        reason = jr.error or ("" if jr.rc == 0 else f"判据退 {jr.rc}")
        results.append(
            ClauseResult(
                c.cid,
                rel_path,
                line_no,
                text,
                status,
                c.judge[0],
                jr.rc,
                jr.tail,
                reason,
                c.note,
            )
        )
    return results


# ------------------------------------------------------------------ 表格自检
#
# 口径只在模块 docstring 写一份（§表格自检）。这里是实现：不跑判据，只读表 + 现读源文档。


class TableError(Exception):
    """表本身读不出来（缺段 / 缺表头 / 行列数不符）—— 与「漂了」不是一回事。"""


@dataclass(frozen=True)
class TableRow:
    """对账表里的一行（一条契约段）。"""

    cid: str
    source: str          # 反引号里的 path:line
    excerpt: str         # 原句（节选）格
    judge: str           # 判据格；no_judge 行是「为什么现在装不了」那一格
    section: str         # "judge" | "no_judge"
    line: int            # 表里的物理行号（报错点名用）


_SECTION_RE = {
    "judge": re.compile(r"^### 有判据的（(?P<n>\d+) 条 · judge_ok）\s*$"),
    "no_judge": re.compile(r"^### 只有话的（(?P<n>\d+) 条 · no_judge）\s*$"),
}
_TOTAL_RE = re.compile(r"：\s*(?P<n>\d+)\s*条\s*===")
_CELLS = {"judge": 5, "no_judge": 4}
_SECTION_NAME = {"judge": "有判据的", "no_judge": "只有话的"}
_MARKUP_RE = re.compile(r"[*`]+")
_SPACES_RE = re.compile(r"\s+")


def _cells(line: str) -> list[str]:
    """把一行 markdown 表格切成格（去掉首尾那对空壳）。"""
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    return [c.strip() for c in body.split("|")]


def _unquote(cell: str) -> str:
    """格子里若是整格包着反引号，就去掉它（表里的路径 / 判据名都这么写）。"""
    s = cell.strip()
    if len(s) >= 2 and s[0] == "`" and s[-1] == "`":
        return s[1:-1].strip()
    return s


def parse_table(text: str) -> tuple[list[TableRow], dict[str, int], int]:
    """读那张对账表。返回 (行, {段: 标题写的条数}, 读数块首行写的总条数)。

    读不出来就抛 TableError（缺段 / 缺表头 / 行列数不符 / 缺读数块），**不猜**。
    """
    rows: list[TableRow] = []
    counts: dict[str, int] = {}
    total: int | None = None
    section: str | None = None
    header_seen = False
    for i, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        matched = ""
        for key, pat in _SECTION_RE.items():
            m = pat.match(stripped)
            if m:
                matched = key
                counts[key] = int(m.group("n"))
                section = key
                header_seen = False
                break
        if matched:
            continue
        if stripped.startswith("## "):
            section = None
            continue
        if section is not None:
            if stripped.startswith("| ID |"):
                header_seen = True
                continue
            if stripped.startswith("|---"):
                continue
            if stripped.startswith("| CX-"):
                if not header_seen:
                    raise TableError(f"第 {i} 行：这张表缺表头（应有「| ID | 源 | …」）")
                cells = _cells(stripped)
                want = _CELLS[section]
                if len(cells) != want:
                    raise TableError(
                        f"第 {i} 行：格数不对 —— 这一段应是 {want} 格，这一行切出 {len(cells)} 格"
                    )
                rows.append(
                    TableRow(
                        cid=cells[0].strip(),
                        source=_unquote(cells[1]),
                        excerpt=cells[2],
                        judge=cells[3],
                        section=section,
                        line=i,
                    )
                )
        if total is None:
            m = _TOTAL_RE.search(stripped)
            if m:
                total = int(m.group("n"))
    for key in _SECTION_RE:
        if key not in counts:
            raise TableError(f"缺段：找不到「### {_SECTION_NAME[key]}」这一段")
    if total is None:
        raise TableError("缺读数块：找不到「…：N 条 ===」那一行")
    return rows, counts, total


def norm_excerpt(text: str) -> str:
    """原句归一：去 **粗体** / 反引号，去行首 >，空白压一个空格（口径见模块 docstring）。"""
    s = _MARKUP_RE.sub("", text)
    s = s.lstrip("> ").strip()
    return _SPACES_RE.sub(" ", s).strip()


def _cmd_cell(c: Contract) -> str:
    """cmd 判据在表里应写的字样：argv 去掉 python -X utf8 前缀后 join。"""
    argv = list(c.judge[1]) if c.judge else []
    while len(argv) >= 3 and argv[0] == "python" and argv[1] == "-X" and argv[2] == "utf8":
        argv = argv[3:]
    return " ".join(argv)


def _live_label(c: Contract) -> str:
    """这条契约段在表里该写的判据字样（pytest 带 tests/ 前缀；cmd 去解释器前缀）。"""
    if c.judge is None:
        return ""
    return c.judge[1] if c.judge[0] == "pytest" else _cmd_cell(c)


def _say(cid: str, row: TableRow, what: str, want: str, got: str) -> str:
    return f"{cid} 第 {row.line} 行：{what} 应为 `{want}`，实际 `{got}`"


def check_doc(
    doc: Path | str, contracts: Sequence[Contract], root: Path | str = ROOT
) -> tuple[int, list[str]]:
    """逐格核对账表与 contracts 的现读值。返回 (退出码, 问题清单)。

    退出码：0 全对上 / 1 有漂（逐条点名）/ 2 表本身读不出来（缺段、行列数不符）。
    """
    doc_path = Path(doc)
    root_path = Path(root)
    try:
        text = doc_path.read_text(encoding="utf-8")
    except OSError as exc:
        return 2, [f"表读不出来：{doc_path}（{exc.__class__.__name__}）"]
    try:
        rows, counts, total = parse_table(text)
    except TableError as exc:
        return 2, [str(exc)]

    problems: list[str] = []
    by_id: dict[str, list[TableRow]] = {}
    for row in rows:
        by_id.setdefault(row.cid, []).append(row)
    cmap = {c.cid: c for c in contracts}

    for c in contracts:
        got_rows = by_id.get(c.cid, [])
        if not got_rows:
            where = _SECTION_NAME["judge" if c.judge else "no_judge"]
            problems.append(f"{c.cid}：表里没有这一条（该在「{where}」段）")
            continue
        if len(got_rows) > 1:
            at = "、".join(f"第 {r.line} 行" for r in got_rows)
            problems.append(f"{c.cid}：表里出现了 {len(got_rows)} 次（{at}）—— 一条只许一行")
            continue
        row = got_rows[0]
        want_section = "judge" if c.judge else "no_judge"
        if row.section != want_section:
            kind = "有判据" if c.judge else "只有话"
            problems.append(
                f"{c.cid} 第 {row.line} 行：段落不对 —— 它{kind}，"
                f"却写在「{_SECTION_NAME[row.section]}」段"
            )
        found = find_clause(root_path / c.source[0], c.source[1])
        if found is None:
            problems.append(
                f"{c.cid} 第 {row.line} 行：源锚点在 {c.source[0]} 里找不到 ⇒ 契约段本身漂了"
            )
            continue
        line_no, live_text = found
        want_src = f"{c.source[0]}:{line_no}"
        got_src = _unquote(row.source)
        if got_src != want_src:
            problems.append(_say(c.cid, row, "源", want_src, got_src))
        got_ex = norm_excerpt(row.excerpt)
        live_ex = norm_excerpt(live_text)
        if len(got_ex) < MIN_EXCERPT:
            problems.append(
                f"{c.cid} 第 {row.line} 行：原句太短（{len(got_ex)} < {MIN_EXCERPT}）"
                f"—— 一个词冒充不了原句：「{got_ex}」"
            )
        elif got_ex not in live_ex:
            problems.append(
                f"{c.cid} 第 {row.line} 行：原句不是源文档那一行的一部分（归一后比对）"
            )
        got_label = _unquote(row.judge)
        if c.judge is None:
            continue  # 只有话：那一格是理由散文，不核
        if got_label.startswith("同 "):
            ref = got_label[2:].strip()
            target = cmap.get(ref)
            if target is None or target.judge is None:
                problems.append(
                    f"{c.cid} 第 {row.line} 行：判据格写「同 {ref}」，但 {ref} 不存在或没有判据"
                )
            elif _live_label(target) != _live_label(c):
                problems.append(
                    _say(
                        c.cid,
                        row,
                        f"判据（「同 {ref}」指过去的那条对不上）",
                        _live_label(c),
                        _live_label(target),
                    )
                )
            continue
        want_label = _live_label(c)
        if got_label != want_label:
            problems.append(_say(c.cid, row, "判据", want_label, got_label))

    for row in rows:
        if row.cid not in cmap:
            problems.append(f"{row.cid} 第 {row.line} 行：CONTRACTS 里没有这一条（表多写了）")

    want_judge = sum(1 for c in contracts if c.judge is not None)
    want_no = len(contracts) - want_judge
    if counts.get("judge") != want_judge:
        problems.append(
            f"「有判据的」段标题写 {counts.get('judge')} 条，实际有 judge 的 {want_judge} 条"
        )
    if counts.get("no_judge") != want_no:
        problems.append(
            f"「只有话的」段标题写 {counts.get('no_judge')} 条，实际只有话的 {want_no} 条"
        )
    if total != len(contracts):
        problems.append(f"读数块首行写 {total} 条，实际 CONTRACTS 有 {len(contracts)} 条")
    return (1 if problems else 0), problems


def _judge_label(c: Contract) -> str:
    if c.judge is None:
        return f"no_judge: {c.no_judge}"
    if c.judge[0] == "pytest":
        return f"pytest: {c.judge[1]}"
    return f"cmd: {' '.join(c.judge[1])}"


def print_report(results: list[ClauseResult], contracts: Sequence[Contract]) -> None:
    """人读报告。"""
    n = len(results)
    by_status: dict[str, int] = {}
    for r in results:
        by_status[r.status] = by_status.get(r.status, 0) + 1
    parts = [
        f"{k} {v}"
        for k, v in (
            ("judge_ok", by_status.get("judge_ok", 0)),
            ("no_judge", by_status.get("no_judge", 0)),
            ("judge_red", by_status.get("judge_red", 0)),
            ("source_missing", by_status.get("source_missing", 0)),
        )
    ]
    print(f"=== 契约段 ↔ 判据对账（卡 217 · T-G330）：{n} 条 ===")
    print(f"分布：{' / '.join(parts)}")
    print()
    cmap = {c.cid: c for c in contracts}
    for r in results:
        c = cmap.get(r.cid)
        loc = f"{r.source_path}:{r.source_line}" if r.source_line else r.source_path
        print(f"[{r.status}] {r.cid}  {loc}")
        if r.source_text:
            print(f"  原句：{r.source_text}")
        if c is not None:
            print(f"  判据：{_judge_label(c)}")
        if r.judge_rc is not None:
            print(f"  读数：rc={r.judge_rc} | {r.judge_tail}")
        if r.reason:
            print(f"  理由：{r.reason}")
        if r.note:
            print(f"  注：{r.note}")
        print()


def print_doc_check(problems: list[str], doc: Path) -> None:
    """人读的表格自检报告。"""
    if not problems:
        print(f"[OK ] 对账表逐格对上（{doc}：源行号 / 原句子串 / 判据标签 / 段标题条数）")
        return
    print(f"[FAIL] 对账表与现读值不一致（{len(problems)} 处）：", flush=True)
    for line in problems:
        print(f"  · {line}")
    print("  ⇒ 改表，或改 CONTRACTS；别让表替工具撒谎。", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="契约段 ↔ 判据的对账器：扫文档里的契约段，对每条当场跑判据贴读数"
    )
    parser.add_argument("--json", action="store_true", help="结构化输出（JSON 数组）")
    parser.add_argument("--report", action="store_true", help="人读报告（默认）")
    parser.add_argument(
        "--check-doc",
        action="store_true",
        help="只核对账表逐格（源行号 / 原句子串 / 判据标签 / 段标题条数），**不跑判据**",
    )
    parser.add_argument(
        "--doc",
        default=DOC_TABLE,
        help=f"要对账的那份表（默认 {DOC_TABLE}；相对路径按仓库根算）",
    )
    args = parser.parse_args(argv)

    if args.check_doc:
        doc = Path(args.doc)
        if not doc.is_absolute():
            doc = ROOT / doc
        rc, problems = check_doc(doc, CONTRACTS, ROOT)
        if args.json:
            print(json.dumps({"ok": rc == 0, "doc": str(doc), "problems": problems},
                             ensure_ascii=False, indent=2))
            return rc
        print_doc_check(problems, doc)
        return rc

    results = audit(CONTRACTS, ROOT)

    if args.json:
        payload = [
            {
                "id": r.cid,
                "source": f"{r.source_path}:{r.source_line}" if r.source_line else r.source_path,
                "text": r.source_text,
                "status": r.status,
                "judge_kind": r.judge_kind,
                "judge_rc": r.judge_rc,
                "judge_tail": r.judge_tail,
                "reason": r.reason,
                "note": r.note,
            }
            for r in results
        ]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if all(r.ok for r in results) else 1

    print_report(results, CONTRACTS)
    ok = all(r.ok for r in results)
    no_judge = sum(1 for r in results if r.status == "no_judge")
    red = sum(1 for r in results if r.status in ("judge_red", "source_missing"))
    if ok:
        print(f"[OK ] {len(results)} 条契约段全部有判据且能跑")
        return 0
    print(
        f"[FAIL] {len(results)} 条里：judge_ok {sum(1 for r in results if r.ok)} / "
        f"no_judge {no_judge}（只有话）/ judge_red+source_missing {red}（红）"
        " —— 不许把「有归属」当「有判据」，也不许为了绿而放宽",
        flush=True,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
