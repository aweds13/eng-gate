"""选择面 + 兜底层 + 跃迁 + 粒度 + 无关失败 + silent failure 三族 + 外部证据纪律 + 术语常量。

把验证分层的行业要求 **F1~F11** 折进框架（卡 185 / T-G285）。
每条都带**机器判据** + **反例钉子**；依据见 `复盘/框架-验证分层的行业做法.md` §四。

本模块是**纯库**：不 print、不 `sys.exit`、不读全局状态。

★ 术语（F11，依据 [arXiv:1305.4776] 构建自动化分类学 · [arXiv:2511.02810] 回归测试形式化）：
  - 收口那一趟 = `triggered_strict_build`（受令、事件驱动）
  - 每日全量   = `scheduled_build`（周期、过渡型）
  - 增量那一趟 = `regression_test_window`（时间受限的回归测试窗口）
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

# ===========================================================================
# F11 · 术语对齐（官方词）
# ===========================================================================
TRIGGERED_STRICT_BUILD = "triggered_strict_build"
SCHEDULED_BUILD = "scheduled_build"
REGRESSION_TEST_WINDOW = "regression_test_window"
BUILD_KINDS = (TRIGGERED_STRICT_BUILD, SCHEDULED_BUILD, REGRESSION_TEST_WINDOW)


class SelectionError(Exception):
    """选择面 / 粒度 / 术语的错（F2/F5/F11）。"""


class SilentFailureError(Exception):
    """silent failure 三族任一命中（F7）。"""


class EvidenceDisciplineError(Exception):
    """外部证据声明缺检索词/范围（F10）。"""


class StateValidationError(Exception):
    """产物缺 F2/F3/F6/F8 要求的字段（反例钉子的机器判据）。"""


# ===========================================================================
# F2 · 选择面报两个数（选择率 + 跳过清单）
# 依据 [arXiv:1810.05286] Predictive Test Selection · [arXiv:2509.10279] T-TS
# 判据：产物缺 selection 节 ⇒ 红（validate_state 咬）。
# ===========================================================================
@dataclass(frozen=True)
class Selection:
    """一次门选择的结果：选了哪些、跳了哪些、属于哪趟构建。"""

    total: int
    chosen: tuple[str, ...]
    skipped: tuple[str, ...]
    build_kind: str

    def selection_rate(self) -> float:
        return len(self.chosen) / self.total if self.total else 0.0

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "chosen": list(self.chosen),
            "skipped": list(self.skipped),
            "build_kind": self.build_kind,
            "selection_rate": round(self.selection_rate(), 4),
        }


# ===========================================================================
# F5 · 粒度：按门/测试切，不许「跳过整棵树」
# 依据 [arXiv:2102.06666]：构建级（跳过整个 build）漏检风险更高。
# 判据：选择规格里出现「跳过整棵树」标志 ⇒ SelectionError。
# ===========================================================================
_TREE_SKIP_MARKERS = ("skip_tree", "skip_all", "granularity:tree", "skip_build", "skip_subtree")


def validate_granularity(only: list[str] | None, *, skip_markers: Iterable[str] = ()) -> None:
    """咬「跳过整棵树」这类粒度。★ 反例钉子喂 skip_markers=('skip_tree',) 必须抛。"""
    bad = [m for m in skip_markers if m in _TREE_SKIP_MARKERS]
    if bad:
        raise SelectionError(
            f"粒度违例：出现「跳过整棵树」类标志 {bad}（F5：选择必须按门/测试切，"
            f"不许按整棵树跳过 —— 依据 [arXiv:2102.06666]）"
        )
    if only:
        wild = [n for n in only if n in ("*", "all", "ALL", "tree")]
        if wild:
            raise SelectionError(f"粒度违例：only={wild} 是整棵树通配（F5：要逐门点名）")


def select_gates(
    all_gates: dict[str, object],
    *,
    only: list[str] | None = None,
    build_kind: str = TRIGGERED_STRICT_BUILD,
    skip_markers: Iterable[str] = (),
) -> Selection:
    """选门：only 给了就选这些，否则全选。先校验粒度（F5）与术语（F11），再算 chosen/skipped。"""
    if build_kind not in BUILD_KINDS:
        raise SelectionError(
            f"build_kind={build_kind!r} 必须是 {list(BUILD_KINDS)} 之一（F11 术语对齐）"
        )
    validate_granularity(only, skip_markers=skip_markers)
    names = sorted(all_gates)
    total = len(names)
    if only is not None:
        unknown = [n for n in only if n not in all_gates]
        if unknown:
            raise SelectionError(f"选了未声明的门 {unknown}（已声明 {names}）")
        chosen_set = set(only)
    else:
        chosen_set = set(names)
    chosen = tuple(n for n in names if n in chosen_set)
    skipped = tuple(n for n in names if n not in chosen_set)
    return Selection(total=total, chosen=chosen, skipped=skipped, build_kind=build_kind)


# ===========================================================================
# F3 · 兜底层报「捕获率」（★ 文献空白，我们自己补）
# 依据：检索面内未见直接测量兜底层检出贡献的实证（检索词与范围见
#   `复盘/框架-验证分层的行业做法.md` §三，可复核）；本框架自己量这一层。
# 判据：scheduled build 的产物缺 backstop 节 ⇒ 红（validate_state 咬）。
# ===========================================================================
@dataclass(frozen=True)
class BackstopReport:
    """每日全量那一趟的捕获率读数。"""

    failures_caught: int                 # 这一趟抓到几条失败
    from_skipped: int                    # 其中几条是增量跳过的门本该抓的
    skipped_gates: tuple[str, ...]       # 增量那一趟跳过的门

    def capture_rate(self) -> float:
        if self.failures_caught <= 0:
            return 0.0
        return self.from_skipped / self.failures_caught

    def to_dict(self) -> dict:
        return {
            "failures_caught": self.failures_caught,
            "from_skipped": self.from_skipped,
            "skipped_gates": list(self.skipped_gates),
            "capture_rate": round(self.capture_rate(), 4),
        }


def backstop_capture(scheduled_results: Iterable, skipped_gates: Iterable[str]) -> BackstopReport:
    """从 scheduled 那趟的结果算捕获率。

    scheduled_results：每条带 `.name` / `.verdict`（`fail` 即抓到一条失败）。
    skipped_gates：增量那一趟（regression test window）跳过的门名。
    """
    skipped_set = set(skipped_gates)
    caught = [r for r in scheduled_results if getattr(r, "verdict", None) == "fail"]
    from_skipped = [r for r in caught if getattr(r, "name", "") in skipped_set]
    return BackstopReport(
        failures_caught=len(caught),
        from_skipped=len(from_skipped),
        skipped_gates=tuple(sorted(skipped_set)),
    )


# ===========================================================================
# F8 · 跃迁检测：每日全量额外报「昨天绿今天红」
# 依据 [arXiv:2501.11550]：post-submit 用 pass↔fail 跃迁识别，5 个 CI 周期内 99.78% 检出。
# ===========================================================================
@dataclass(frozen=True)
class Transition:
    gate: str
    frm: str
    to: str

    def to_dict(self) -> dict:
        return {"gate": self.gate, "from": self.frm, "to": self.to}


def detect_transitions(
    today_results: Iterable, yesterday_state: dict[str, str]
) -> list[Transition]:
    """对比今天与昨天的判决，报昨天绿今天红的门（regression transition）。"""
    out: list[Transition] = []
    for r in today_results:
        y = yesterday_state.get(getattr(r, "name", ""))
        v = getattr(r, "verdict", None)
        if y == "pass" and v == "fail":
            out.append(Transition(gate=r.name, frm="pass", to="fail"))
    return out


# ===========================================================================
# F6 · 区分无关失败：失败读数必须带「是否与本次变更相关」
# 依据 [arXiv:2605.05564]：77,354 次失败里 20% 与本次推送无关。
# 判据：失败门缺 failure_attribution ⇒ 红（validate_state 咬）。
# ===========================================================================
ATTR_RELATED = "related"
ATTR_UNRELATED_ENV = "unrelated_env"
ATTR_UNRELATED_OTHERS = "unrelated_others"
ATTR_FLAKY = "flaky"
ATTR_UNKNOWN = "unknown"
ATTRIBUTION_VALUES = (
    ATTR_RELATED, ATTR_UNRELATED_ENV, ATTR_UNRELATED_OTHERS, ATTR_FLAKY, ATTR_UNKNOWN,
)


def classify_failure(
    *,
    gate_name: str,
    verdict: str | None,
    changed_files: Iterable[str] = (),
    touched_files: Iterable[str] = (),
    flaky_known: set[str] | None = None,
) -> str:
    """把一道失败的门归因，返回 ATTRIBUTION_VALUES 之一。

    - 非失败门 ⇒ unknown（不该调，但兜底）
    - 门在 flaky_known 里 ⇒ flaky
    - 门碰过的文件与本次变更无交集 ⇒ unrelated_env
    - 否则 ⇒ related
    """
    if verdict != "fail":
        return ATTR_UNKNOWN
    if flaky_known and gate_name in flaky_known:
        return ATTR_FLAKY
    changed = set(changed_files)
    touched = set(touched_files)
    if touched and not (changed & touched):
        return ATTR_UNRELATED_ENV
    return ATTR_RELATED


# ===========================================================================
# F7 · silent failure 三族列为一等风险
# 依据 [arXiv:2509.14347]：失败主题 = 制品操作错误 28% · 缓存错误 23% · 被忽略的退出码 18%。
# 三族各有判据 + 反例钉子。
# ===========================================================================
def check_ignored_exit_code(*, exit_code: int | None, exit_ok: tuple[int, ...],
                            verdict: str | None) -> None:
    """族一·被忽略的退出码：退出码不在 exit_ok 里却被当绿 ⇒ 红。"""
    if verdict == "pass" and exit_code is not None and exit_code not in exit_ok:
        raise SilentFailureError(
            f"被忽略的退出码：exit_code={exit_code} 不在 exit_ok={list(exit_ok)} 却判了 pass"
        )


def check_cache_stale(*, reused: bool, input_hash: str | None, prev_hash: str | None) -> None:
    """族二·缓存错误：复用缓存但输入面已变 ⇒ 红。"""
    if reused and input_hash is not None and prev_hash is not None and input_hash != prev_hash:
        raise SilentFailureError(
            f"缓存 stale：input_hash={input_hash} ≠ prev_hash={prev_hash}，却 reused=True"
        )


def check_artifact_op(*, emits: tuple[str, ...], committed_files: Iterable[str],
                      artifact_path: str | None = None) -> None:
    """族三·制品（派生物）操作：声明的制品没进提交/输入表 ⇒ 红。"""
    if not emits:
        return
    committed = set(committed_files)
    if artifact_path and artifact_path not in committed:
        raise SilentFailureError(
            f"制品未登记：emits={list(emits)} 的制品 {artifact_path!r} 不在提交/输入表里"
        )


# ===========================================================================
# F9 · 覆盖率不许单独当绿的理由
# 依据 [arXiv:1903.04055] 单元测试覆盖与现场崩溃无相关性 ·
#      [arXiv:2606.22475] 44% 缺陷绕过单元测试。
# 判据：门的证据里若只有 coverage 一项 ⇒ inconclusive，不许 pass。
# ===========================================================================
def is_sole_coverage(emits: tuple[str, ...]) -> bool:
    """emits 恰好只有 coverage 一项 ⇒ True（覆盖率不许单独当绿）。"""
    return emits == ("coverage",)


def coverage_must_not_be_sole_evidence(*, emits: tuple[str, ...], other_evidence: int) -> str:
    """若只有 coverage 且无其它证据 ⇒ 'inconclusive'，否则 'pass'。"""
    if is_sole_coverage(emits) and other_evidence <= 0:
        return "inconclusive"
    return "pass"


# ===========================================================================
# F10 · 外部证据纪律：凡写「文献里没有 X」必须附检索词与检索范围
# 依据：主控 2026-10-03 自我纠正（`复盘/框架-验证分层的行业做法.md` §三）。
# 判据：文本里出现「否定 + 文献」而无检索词 ⇒ 红。
# ===========================================================================
_EVIDENCE_NEGATION_RE = re.compile(
    r"(没有|不存在|未见|未检索到)[^。；;\n]{0,60}?"
    r"(文献|论文|实证|arXiv)"
)


def lint_external_evidence(text: str, *, search_terms: tuple[str, ...] = (),
                           scope: str | None = None) -> list[str]:
    """扫文本里「否定 + 文献」声明；没附检索词/范围 ⇒ 每条记一个违规。"""
    violations: list[str] = []
    for m in _EVIDENCE_NEGATION_RE.finditer(text):
        if not search_terms or not scope:
            violations.append(
                f"外部证据声明未附检索词/范围：「{m.group(0)}」—— 不可复核 = 自证清白（F10）"
            )
    return violations


def validate_external_evidence(text: str, *, search_terms: tuple[str, ...], scope: str) -> None:
    """若文本含「否定+文献」声明，必须同时给检索词与范围，否则抛。"""
    violations = lint_external_evidence(text, search_terms=search_terms, scope=scope)
    if violations:
        raise EvidenceDisciplineError("; ".join(violations))


# ===========================================================================
# 产物校验：缺字段 ⇒ 红（F2/F3/F6/F8 反例钉子的机器判据）
# ===========================================================================
def validate_state(state: dict) -> None:
    """校验一趟门禁的产物 dict。缺 F2/F3/F6/F8 要求的字段 ⇒ StateValidationError。

    ★ 反例钉子：故意造一个缺 selection / 缺 backstop / 缺 attribution 的产物 ⇒ 必须抛。
    """
    if not isinstance(state, dict):
        raise StateValidationError(f"产物必须是 dict，拿到 {type(state).__name__}")

    # F2 · 选择面
    sel = state.get("selection")
    if sel is None:
        raise StateValidationError("产物缺 selection 节（F2：选择面必须报两个数）")
    for k in ("total", "chosen", "skipped", "build_kind", "selection_rate"):
        if k not in sel:
            raise StateValidationError(f"产物 selection 缺键 {k}（F2）")
    # F11 · build_kind 必须是官方词
    if sel["build_kind"] not in BUILD_KINDS:
        raise StateValidationError(
            f"selection.build_kind={sel['build_kind']!r} 不是官方词 {list(BUILD_KINDS)}（F11）"
        )

    # F1 · 并行度留痕
    par = state.get("parallelism")
    if par is None:
        raise StateValidationError("产物缺 parallelism 节（F1：降级必须留痕）")
    for k in ("requested", "used", "degraded"):
        if k not in par:
            raise StateValidationError(f"产物 parallelism 缺键 {k}（F1）")

    # F3 · 兜底层（仅 scheduled build 要求）
    if sel["build_kind"] == SCHEDULED_BUILD and state.get("backstop") is None:
        raise StateValidationError(
            "scheduled build 的产物缺 backstop 节（F3：兜底层必须报捕获率）"
        )

    # F6 · 失败门的归因
    for g in state.get("gates", []):
        if g.get("verdict") == "fail" and "failure_attribution" not in g:
            raise StateValidationError(
                f"失败门 {g.get('name')!r} 缺 failure_attribution（F6：必须区分无关失败）"
            )

    # F8 · 跃迁（仅 scheduled build 要求）
    if sel["build_kind"] == SCHEDULED_BUILD and "transitions" not in state:
        raise StateValidationError("scheduled build 的产物缺 transitions 节（F8）")
