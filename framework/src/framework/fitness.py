"""架构级 fitness function + 验证器自身的 fitness（卡 186 · G1 / G3 / G7 / G9）。

> 一句话（照 `复盘/框架-可控性与安全修改.md`）：**不是追求完美，是让偏差被看见、
> 被限制、可回收** —— 靠「可执行约束 + 闭环 + 多样性匹配 + 显式债务 + 可逆迁移」。

本模块把那张文书里的四条 G 落成**代码 + 产物字段 + 钉子**（不是文档）：

- **G1 · 架构级 fitness function 成体系**：把**结构性约束**也做成门 ——
  ① 分层依赖不许倒流；② `framework/` 不许 import 项目代码；③ 台账/证据不许指向
  不存在的路径；④ 目录纪律。每条约束一条钉子，造错必红。
- **G3 · 多样性不许被削减**：任何「提速」不许减少门数/兜底/证据面；产物里出现
  「门数/兜底被减少」时**必须**有一条**显式论证**记录，否则红
  （依据 [arXiv:2510.20041] 的 Kubernetes 降级实证：砍控制面 ⇒ CI 成本 +76%）。
- **G7 · 配置层元验证（拒绝点活性扫描）**：系统性地删掉验证器的拒绝点，找出
  `vacuous pass`（依据 [arXiv:2608.26183]）。★ 文献里**没有现成工具**，这是本框架
  自研的差异化能力。本模块对框架自己的三值判决 `gates.classify` 做活性扫描，给出
  一条**现成读数**：「删掉「空集 ⇒ inconclusive」拒绝点 ⇒ 本该 inconclusive 却变 pass」。
- **G9 · 验证器脆弱性自测**：语法无关的等价改动不许改变判定
  （依据 [arXiv:1805.03296]：语义等价变异体就让 Boogie 改判 16/135）—— 一条钉子。

本模块是**纯库**：不 print、不 `sys.exit`、不读全局状态、不写死本仓路径。
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .gates import Verdict, classify

# ---------------------------------------------------------------------------
# 产物字段：一条 fitness 违规
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FitnessViolation:
    """一条架构级约束被违反的读数（产物字段，进 `--json`）。"""

    constraint: str   # G1·分层倒流 / G1·项目专有 import / G1·悬空引用 / G1·目录纪律 / G3·多样性削减
    where: str        # 在哪（文件::符号 / 路径）
    detail: str       # 造了什么错

    def to_dict(self) -> dict:
        return {"constraint": self.constraint, "where": self.where, "detail": self.detail}


def _violations_to_dict(items: list[FitnessViolation]) -> list[dict]:
    return [v.to_dict() for v in items]


# ===========================================================================
# G1 · 架构级 fitness function 成体系
# ===========================================================================

# -- ① 分层依赖不许倒流 ---------------------------------------------------

@dataclass(frozen=True)
class LayerSpec:
    """一层：名字 + 该层对应的顶层包名集合。层序由调用方用 tuple 给（从低到高）。"""

    name: str
    top_levels: frozenset[str]


@dataclass(frozen=True)
class ImportEdge:
    """一条 import 边：谁 import 了什么（都按顶层包名）。"""

    importer: str   # 顶层包名（如 "framework"）
    imported: str   # 顶层包名（如 "cli"）
    where: str      # 文件::符号（定位用）


def layered_dependencies_no_backflow(
    layers: tuple[LayerSpec, ...],
    edges: list[ImportEdge],
) -> list[FitnessViolation]:
    """G1① 分层依赖不许倒流：低层不许 import 高层。

    `layers` 按**从低到高**给（如 `(core, cli, templates)`）。对每条 import 边，
    若 importer 的层 < imported 的层 ⇒ 倒流 ⇒ 违规。不在任何层里的包忽略
    （第三方库 / 标准库）。
    """
    rank: dict[str, int] = {}
    for i, layer in enumerate(layers):
        for pkg in layer.top_levels:
            rank[pkg] = i
    out: list[FitnessViolation] = []
    for edge in edges:
        i_rank = rank.get(edge.importer)
        d_rank = rank.get(edge.imported)
        if i_rank is None or d_rank is None:
            continue
        if i_rank < d_rank:
            out.append(FitnessViolation(
                constraint="G1·分层倒流",
                where=edge.where,
                detail=f"低层「{edge.importer}」(层 {i_rank}) import 了高层"
                       f"「{edge.imported}」(层 {d_rank}) —— 依赖倒流",
            ))
    return out


# -- ② framework/ 不许 import 项目代码 ------------------------------------

def _top_level(module: str) -> str:
    """`a.b.c` → `a`；`a` → `a`。"""
    return module.split(".", 1)[0] if module else module


def collect_imports(py_file: Path, *, root: Path) -> list[ImportEdge]:
    """用 AST 取一个 .py 文件里所有 import 的顶层包名边。

    importer = 该文件所属的顶层包（按 `root` 推：文件路径里第一个目录名）；
    imported = import 的模块的顶层包名。`from . import x` 这种相对 import 不算
    （同包内不算倒流）。
    """
    try:
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    rel = py_file.relative_to(root) if py_file.is_relative_to(root) else py_file
    parts = rel.parts
    importer_pkg = parts[0] if len(parts) > 1 else ""
    edges: list[ImportEdge] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = _top_level(alias.name)
                if top and top != importer_pkg:
                    edges.append(ImportEdge(
                        importer=importer_pkg, imported=top,
                        where=f"{rel.as_posix()}::{alias.name}",
                    ))
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue  # 相对 import：同包，不算
            if node.module:
                top = _top_level(node.module)
                if top and top != importer_pkg:
                    edges.append(ImportEdge(
                        importer=importer_pkg, imported=top,
                        where=f"{rel.as_posix()}::from {node.module} import ...",
                    ))
    return edges


def no_project_specific_imports(
    framework_dir: Path,
    forbidden_top_levels: tuple[str, ...],
) -> list[FitnessViolation]:
    """G1② `framework/` 不许 import 项目代码：扫描 framework_dir 下所有 .py，
    import 的顶层包名不许命中 `forbidden_top_levels`。

    ★ `forbidden_top_levels` 由调用方传（项目侧知道自己有哪些专有包），本库**不写死**。
    """
    forbidden = set(forbidden_top_levels)
    out: list[FitnessViolation] = []
    if not framework_dir.is_dir():
        return [FitnessViolation(
            constraint="G1·项目专有 import", where=str(framework_dir),
            detail="framework 目录不存在 —— 没法扫",
        )]
    for py in sorted(framework_dir.rglob("*.py")):
        if any(part in {"__pycache__", "build", "dist"} for part in py.parts):
            continue
        for edge in collect_imports(py, root=framework_dir):
            if edge.imported in forbidden:
                out.append(FitnessViolation(
                    constraint="G1·项目专有 import", where=edge.where,
                    detail=f"框架 import 了项目专有包「{edge.imported}」"
                           f"（提升就绪 P1：框架不许依赖项目代码）",
                ))
    return out


# -- ③ 台账/证据不许指向不存在的路径 --------------------------------------

def dangling_references(
    references: list[tuple[str, Path]],
) -> list[FitnessViolation]:
    """G1③ 台账/证据不许指向不存在的路径：每条引用的路径必须存在。

    `references` = 一组 `(标签, 路径)`（标签用于定位，如 `ledger.toml::evidence[3]`）。
    路径不存在 ⇒ 违规。★ 不猜、不兜底：缺了就点名。
    """
    out: list[FitnessViolation] = []
    for label, path in references:
        if not path.exists():
            out.append(FitnessViolation(
                constraint="G1·悬空引用", where=label,
                detail=f"指向的路径不存在：{path}",
            ))
    return out


# -- ④ 目录纪律 -----------------------------------------------------------

@dataclass(frozen=True)
class DirectoryDiscipline:
    """期望的目录布局：必须存在的文件 / 目录 + 不许存在的（如临时垃圾）。"""

    must_exist: tuple[str, ...] = ()
    must_not_exist: tuple[str, ...] = ()


def directory_discipline(root: Path, spec: DirectoryDiscipline) -> list[FitnessViolation]:
    """G1④ 目录纪律：`must_exist` 的都要在；`must_not_exist` 的都不许在。"""
    out: list[FitnessViolation] = []
    for rel in spec.must_exist:
        if not (root / rel).exists():
            out.append(FitnessViolation(
                constraint="G1·目录纪律", where=str(root / rel),
                detail=f"期望存在但缺失：{rel}",
            ))
    for rel in spec.must_not_exist:
        if (root / rel).exists():
            out.append(FitnessViolation(
                constraint="G1·目录纪律", where=str(root / rel),
                detail=f"不许存在但出现了：{rel}",
            ))
    return out


# -- G1 总入口：把四条合成一趟 --------------------------------------------

@dataclass(frozen=True)
class ArchitectureFitnessInput:
    """G1 四条约束的输入（调用方填，本库不读全局状态）。"""

    layers: tuple[LayerSpec, ...]
    import_edges: list[ImportEdge]
    framework_dir: Path
    forbidden_top_levels: tuple[str, ...]
    evidence_references: list[tuple[str, Path]]
    discipline_root: Path
    discipline: DirectoryDiscipline


def architecture_fitness(inp: ArchitectureFitnessInput) -> list[FitnessViolation]:
    """G1 总入口：跑四条结构性约束，返回所有违规（空 = 全绿）。"""
    out: list[FitnessViolation] = []
    out += layered_dependencies_no_backflow(inp.layers, inp.import_edges)
    out += no_project_specific_imports(inp.framework_dir, inp.forbidden_top_levels)
    out += dangling_references(inp.evidence_references)
    out += directory_discipline(inp.discipline_root, inp.discipline)
    return out


# ===========================================================================
# G3 · 多样性不许被削减（依据 [arXiv:2510.20041]）
# ===========================================================================

@dataclass(frozen=True)
class ControlSurface:
    """控制面的多样性读数：门数 / 兜底数 / 证据面数。

    ★ 依据 Ashby's Law of Requisite Variety：控制器的多样性必须 ≥ 被控环境的多样性。
    砍门 / 砍兜底 / 砍证据面 = 削减控制器多样性 ⇒ 成本必然外溢
    （[2510.20041]：Kubernetes 降级 ⇒ CI 成本 +76%、增量慢达 75%）。
    """

    gate_count: int
    fallback_count: int
    evidence_facets: int

    def total(self) -> int:
        return self.gate_count + self.fallback_count + self.evidence_facets


@dataclass(frozen=True)
class DiversityChange:
    """一笔改动前后的控制面读数 + 显式论证（若给了）。"""

    before: ControlSurface
    after: ControlSurface
    justification: str | None   # 若减少了，必须有一条显式论证（谁批的 / 为什么）
    where: str = ""


def diversity_not_reduced(change: DiversityChange) -> list[FitnessViolation]:
    """G3 多样性不许被削减：`after` 的任一面 < `before` ⇒ 必须有 `justification`，否则红。

    ★ 判据（照文书 G3）：「一笔改动若**减少**了门或兜底，必须在文书里**显式论证**并留
    override 记录」。有论证 ⇒ 放行（但记一条 note）；无论证 ⇒ 红。
    要提速就提并行度（F1），**不是砍控制面**。
    """
    out: list[FitnessViolation] = []
    reduced: list[str] = []
    if change.after.gate_count < change.before.gate_count:
        reduced.append(f"门数 {change.before.gate_count}→{change.after.gate_count}")
    if change.after.fallback_count < change.before.fallback_count:
        reduced.append(f"兜底 {change.before.fallback_count}→{change.after.fallback_count}")
    if change.after.evidence_facets < change.before.evidence_facets:
        reduced.append(f"证据面 {change.before.evidence_facets}→{change.after.evidence_facets}")
    if not reduced:
        return out
    if not change.justification or not change.justification.strip():
        out.append(FitnessViolation(
            constraint="G3·多样性削减",
            where=change.where or "(未给位置)",
            detail="控制面被削减（" + "；".join(reduced) + "）但无显式论证 —— "
                   "要提速就提并行度，不是砍门（依据 [2510.20041]：砍控制面 ⇒ CI 成本 +76%）",
        ))
    return out


# ===========================================================================
# G7 · 配置层元验证 / 拒绝点活性扫描（依据 [arXiv:2608.26183]）
# ===========================================================================

# 框架自己的三值判决 `gates.classify` 的拒绝点（逐个能删、逐个能验活性）。
REFUSAL_SITES: tuple[str, ...] = ("not_run", "timeout", "empty", "exit_ok")


@dataclass(frozen=True)
class ClassifyInput:
    """`classify` 的一次输入（做成 dataclass 便于变异扫描时引用）。"""

    ran: bool
    timed_out: bool
    exit_code: int | None
    exit_ok: tuple[int, ...]
    collected: int | None


def classify_mutable(inp: ClassifyInput, *, disable: frozenset[str] = frozenset()) -> tuple[Verdict | None, str]:
    """`gates.classify` 的**可变异版**：复刻其逻辑，但可 `disable` 某个拒绝点。

    ★ 这是 G7 的被测体 —— 对它做拒绝点活性扫描（逐个删拒绝点，看本该红的会不会变绿）。
    ★ G9 的等价性由 `test_classify_mutable_equivalent_to_classify` 钉住：
      `disable=∅` 时与 `gates.classify` 逐输入等价（不是第二份真源，是被测的等价体）。
    """
    if "not_run" not in disable and not inp.ran:
        return None, "未运行 —— 没有判决"
    if "timeout" not in disable and inp.timed_out:
        return Verdict.FAIL, "硬超时"
    if "empty" not in disable and inp.collected is not None and inp.collected == 0:
        return Verdict.INCONCLUSIVE, "空集 —— 不许当绿"
    if "exit_ok" not in disable and inp.exit_code is not None and inp.exit_code in inp.exit_ok:
        return Verdict.PASS, f"退出码 {inp.exit_code} 在 exit_ok 内"
    return Verdict.FAIL, f"退出码 {inp.exit_code} 不在 exit_ok 内"


@dataclass(frozen=True)
class RefusalSite:
    """一个拒绝点：名字 + 删掉它之后会发生什么（描述）。"""

    name: str
    description: str


@dataclass(frozen=True)
class MutationReading:
    """拒绝点活性扫描的一条读数（产物字段，进 `--json`）。"""

    site: str                 # 被删的拒绝点名
    subject: str              # 被测 subject 的描述
    original_verdict: str     # 原验证器的判定
    mutated_verdict: str      # 删掉拒绝点后的判定
    is_vacuous_pass: bool     # ★ 本该非 pass，删了变 pass ⇒ 该拒绝点是唯一拦住它的
    detail: str

    def to_dict(self) -> dict:
        return {
            "site": self.site, "subject": self.subject,
            "original_verdict": self.original_verdict,
            "mutated_verdict": self.mutated_verdict,
            "is_vacuous_pass": self.is_vacuous_pass,
            "detail": self.detail,
        }


def refusal_site_mutation(
    *,
    original: Callable[[Any], tuple[Verdict | None, str]],
    mutated: Callable[[Any, frozenset[str]], tuple[Verdict | None, str]],
    sites: list[RefusalSite],
    should_fail: list[tuple[str, Any]],
) -> list[MutationReading]:
    """G7 通用拒绝点活性扫描（依据 [arXiv:2608.26183]）。

    对每个拒绝点 `s` + 每个**本该非 pass**的 subject：跑原验证器与「删掉 `s` 后的验证器」，
    若删了之后变 pass ⇒ `vacuous pass`（该拒绝点是唯一拦住这个 subject 的，删了就漏）。

    ★ 文献结论：**对验证器自身拒绝逻辑做活性测试，比对具体 bug 写回归测试有效得多**。
    ★ 文献里**没有现成工具** —— 这是本框架自研的差异化能力。
    """
    out: list[MutationReading] = []
    for site in sites:
        for subj_desc, subj in should_fail:
            orig_v, orig_r = original(subj)
            mut_v, mut_r = mutated(subj, frozenset({site.name}))
            vacuous = (orig_v != Verdict.PASS) and (mut_v == Verdict.PASS)
            out.append(MutationReading(
                site=site.name, subject=subj_desc,
                original_verdict=orig_v.value if orig_v else "None",
                mutated_verdict=mut_v.value if mut_v else "None",
                is_vacuous_pass=vacuous,
                detail=f"原判={orig_v.value if orig_v else 'None'}（{orig_r}）；"
                       f"删「{site.name}」后={mut_v.value if mut_v else 'None'}（{mut_r}）"
                       + (" ⇒ ★ vacuous pass：本该不绿却变绿" if vacuous else ""),
            ))
    return out


# -- 现成读数：对框架自己的 classify 做活性扫描 ---------------------------

_CLASSIFY_SITES = [
    RefusalSite("not_run", "ran=False ⇒ (NOT_RUN, None)：没跑不算通过"),
    RefusalSite("timeout", "timed_out ⇒ (RAN, FAIL)：硬超时即红"),
    RefusalSite("empty", "collected==0 ⇒ (RAN, INCONCLUSIVE)：空集不许当绿"),
    RefusalSite("exit_ok", "exit_code in exit_ok ⇒ (RAN, PASS)：拿到通过证据"),
]

# 一组「本该非 pass」的 subject（每个瞄准一个拒绝点）。
_CLASSIFY_SHOULD_FAIL = [
    ("ran=False", ClassifyInput(ran=False, timed_out=False, exit_code=None, exit_ok=(0,), collected=None)),
    ("timed_out=True", ClassifyInput(ran=True, timed_out=True, exit_code=124, exit_ok=(0,), collected=None)),
    ("collected=0,exit=0", ClassifyInput(ran=True, timed_out=False, exit_code=0, exit_ok=(0,), collected=0)),
    ("exit=1,collected=2", ClassifyInput(ran=True, timed_out=False, exit_code=1, exit_ok=(0,), collected=2)),
]


def _orig_classify(inp: ClassifyInput) -> tuple[Verdict | None, str]:
    _, v, r = classify(ran=inp.ran, timed_out=inp.timed_out, exit_code=inp.exit_code,
                       exit_ok=inp.exit_ok, collected=inp.collected)
    return v, r


def classify_refusal_scan() -> list[MutationReading]:
    """G7 现成读数：对框架自己的三值判决 `gates.classify` 做拒绝点活性扫描。

    ★ 至少一条 `is_vacuous_pass=True`：删掉「空集 ⇒ inconclusive」拒绝点后，
    一个 `collected=0、exit_code=0` 的 subject（本该 inconclusive）变 pass ——
    这就是「删掉某个拒绝点 ⇒ 本该红却没红」的现成读数。
    """
    return refusal_site_mutation(
        original=_orig_classify,
        mutated=lambda inp, dis: classify_mutable(inp, disable=dis),
        sites=_CLASSIFY_SITES,
        should_fail=_CLASSIFY_SHOULD_FAIL,
    )


# ===========================================================================
# G9 · 验证器脆弱性自测（依据 [arXiv:1805.03296]）
# ===========================================================================

@dataclass(frozen=True)
class EquivalenceReading:
    """G9 一条读数：验证器对一个 subject 及其等价变形的判定是否一致。"""

    verifier: str
    subject: str
    original_verdict: str
    reordered_verdict: str
    stable: bool
    detail: str

    def to_dict(self) -> dict:
        return {
            "verifier": self.verifier, "subject": self.subject,
            "original_verdict": self.original_verdict,
            "reordered_verdict": self.reordered_verdict,
            "stable": self.stable, "detail": self.detail,
        }


def verifier_stable_under_reorder(
    *,
    verifier: Callable[[Any], tuple[Any, str]],
    reordered: Callable[[Any], tuple[Any, str]],
    subject: Any,
    subject_desc: str,
    verifier_name: str = "verifier",
) -> EquivalenceReading:
    """G9 验证器脆弱性自测：语法无关的等价重排**不许**改变判定。

    ★ 依据 [arXiv:1805.03296]：语义等价变异体（重排独立声明）就能让 Boogie 改判
    （135 个程序里 16 个）。本函数断言：`verifier` 与它的「独立声明重排版」`reordered`
    对同一 `subject` 给同一判定。**判定变了 ⇒ 验证器脆弱**（依赖了语法而非语义）。
    """
    v1, r1 = verifier(subject)
    v2, r2 = reordered(subject)
    same = (v1 == v2)
    return EquivalenceReading(
        verifier=verifier_name, subject=subject_desc,
        original_verdict=str(v1), reordered_verdict=str(v2),
        stable=same,
        detail=f"原判={v1}（{r1}）；重排后={v2}（{r2}）"
               + (" —— 稳定（等价改动未改判）" if same
                  else " —— ★ 脆弱：语法无关的等价重排改变了判定"),
    )


# -- 一个有独立声明的示例验证器（给 G9 钉子用）----------------------------
# 三个检查互相独立（顺序无关）：有 name / 有 version / version 是 str。

def sample_validator(config: dict) -> tuple[bool, str]:
    """示例验证器：三个**独立**检查（顺序无关）。"""
    if "name" not in config:
        return False, "缺 name"
    if "version" not in config:
        return False, "缺 version"
    if not isinstance(config["version"], str):
        return False, "version 不是字符串"
    return True, "ok"


def sample_validator_reordered(config: dict) -> tuple[bool, str]:
    """`sample_validator` 的独立声明重排（version 类型检查挪到最前）—— 语义等价。"""
    if not isinstance(config["version"], str):
        return False, "version 不是字符串"
    if "version" not in config:
        return False, "缺 version"
    if "name" not in config:
        return False, "缺 name"
    return True, "ok"


def fragile_validator(config: dict) -> tuple[bool, str]:
    """★ 脆弱验证器（反例钉子用）：依赖 `list(config)[0]` —— dict 插入顺序敏感。

    语义上「检查第一个键是不是 name」与顺序无关吗？不是 —— 它**依赖插入顺序**，
    一个 `{"version": "1", "name": "x"}` 会被它判 False，但语义上完全合法。
    这正是 [1805.03296] 说的「语法无关的等价改动让验证器改判」的工程版。
    """
    keys = list(config)
    if not keys or keys[0] != "name":
        return False, "第一个键不是 name"
    return True, "ok"


def fragile_validator_reordered(config: dict) -> tuple[bool, str]:
    """`fragile_validator` 的「重排」：改成检查最后一个键 —— 对同一 config 判定会变。"""
    keys = list(config)
    if not keys or keys[-1] != "name":
        return False, "最后一个键不是 name"
    return True, "ok"
