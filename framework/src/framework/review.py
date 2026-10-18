"""复核面：把本仓 `tools/pool/review.py` + `tools/wb_review.py` 的检查面抽空进库
（卡 186 · G10）。

> ★ 为什么放本卡：它和 G7（拒绝点活性扫描）**同族** —— 都是「**谁来验验证器**」。
> ★ 别重复造：本仓的 `tools/wb_review.py` + `tools/pool/review.py` 已经是那个零件，
> 本卡是**把它搬进框架并接上线**（照「抽空进配置」那一套，**不在库里写死本仓路径**）。

本模块把 G10 落成**代码 + 产物字段 + 钉子**：

1. **检查面**（纯函数，抽空本仓实现）：域比对 / 门数现算 / `affected` 标记 /
   trailer 真伪 / 分支 / 脏树 —— 所有路径 / 常量由调用方传，库里**不写死**。
2. **`ReviewConfig`**：`pipeline.toml` 复核面字段（谁复核 / 复核什么 / 结论落哪 /
   复核失败怎么办）—— schema 接线由后续卡做（本卡白名单不含 schema）。
3. **`run_review`**：一条命令的库实现 —— 输入「一次集成的结果 + 卡的权威域」，
   输出「能不能算这一笔」+ 稳定 `--json` + 退出码（照卡 177 的表）。
4. **反例钉子**（在 tests/test_review.py）：① 没有复核记录 ⇒ 不许标 landed；
   ② rev 对不上 ⇒ 红；③ 部分跑（有 `affected` 块）⇒ 判红并贴原文。

本模块是**纯库**：不 print、不 `sys.exit`、不读全局状态、不 import 本仓模块。
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import tomllib

from .exit_codes import ExitCode

if TYPE_CHECKING:
    from collections.abc import Callable

# ---------------------------------------------------------------------------
# 检查面 ①：白名单越界（抽空 `tools/pool/review.py`）
# ---------------------------------------------------------------------------


def outside_allow(paths: list[str], allow: list[str]) -> list[str]:
    """`paths` 里**不在**允许列表（fnmatch）里的那些 —— 越界项，顺序保持原样。

    路径与 glob 都先把 `\\` 规范成 `/` 再比（Windows 下 git 偶尔给反斜杠也不误判）；
    空 `allow` = 全越界。
    """
    normalized_allow = [a.replace("\\", "/") for a in allow]
    out: list[str] = []
    for path in paths:
        rel = path.replace("\\", "/")
        if not any(fnmatch.fnmatch(rel, pat) for pat in normalized_allow):
            out.append(path)
    return out


def changed_paths(status_text: str) -> list[str]:
    """从 `git status --porcelain -uall --no-renames` 原文取改动路径集合（含未跟踪 `??`）。

    每行形状 `XY <path>`：状态恰好 2 列 + 1 个空格 ⇒ 取 `line[3:]`。
    """
    out: list[str] = []
    for line in status_text.splitlines():
        if len(line) < 4:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path:
            out.append(path)
    return out


def domain_of_manifest_text(text: str, member_id: str) -> list[str] | None:
    """任务预声明 TOML 原文里某成员的 `paths`（＝这张卡的域）。

    没有这个成员 → `None`（区分「查不到」与「域就是空的」—— 空域会骗过一切守卫）。
    """
    data = tomllib.loads(text)
    for member in data.get("member") or []:
        if str(member.get("id", "")) == member_id:
            return [str(p) for p in (member.get("paths") or [])]
    return None


def outside_domain(paths: list[str], domain: list[str]) -> list[str]:
    """`paths` 里**不在权威域**里的那些 —— 就是 `outside_allow()`，换了个语义标签。"""
    return outside_allow(paths, domain)


# ---------------------------------------------------------------------------
# 检查面 ②：trailer 规矩（抽空 `wb_review.check_trailers`）
# ---------------------------------------------------------------------------

_TASK_RE = re.compile(r"^Task:\s*(\S+)\s*$", re.M)


def check_trailers(body: str) -> tuple[list[str], dict[str, str]]:
    """trailer 规矩：`Task:` 恰好一个 + `Ledger:`/`Gates:` 必须在（`Refs:` 可选）。"""
    problems: list[str] = []
    tasks = _TASK_RE.findall(body)
    found: dict[str, str] = {"Task": ", ".join(tasks)}
    if len(tasks) != 1:
        problems.append(f"`Task:` 必须恰好一个台账编号，现在是 {len(tasks)} 个：{tasks}")
    for key in ("Ledger", "Gates"):
        m = re.search(rf"^{key}:\s*(\S.*)$", body, re.M)
        if not m:
            problems.append(f"缺 `{key}:` trailer（提交信息末尾那几行之一）")
        else:
            found[key] = m.group(1).strip()
    return problems, found


# ---------------------------------------------------------------------------
# 检查面 ③：门禁是不是为这一笔跑的（抽空 `wb_review.check_gate_evidence`）
# ---------------------------------------------------------------------------


def check_gate_evidence(payload: dict, parent_short: str) -> list[str]:
    """门禁是不是**为这一笔**跑的 —— `rev` 必须等于这一笔的父提交。

    ★ G10 反例钉子②：rev 对不上 ⇒ 红（一次门禁跑完提交两笔，第二笔没验过）。
    """
    problems: list[str] = []
    if payload.get("ok") is not True:
        problems.append(f"gates/last.json 的 ok 不是 true：{payload.get('ok')!r}")
    if payload.get("rev") != parent_short:
        problems.append(
            f"门禁不是为这一笔跑的：last.json 的 rev={payload.get('rev')!r}，"
            f"而这一笔的父提交是 {parent_short!r}（★ 一次门禁跑完提交两笔？第二笔没验过）"
        )
    bad = [g for g in payload.get("gates", []) if g.get("exit_code") != 0]
    if bad:
        problems.append(f"有门没过：{[g.get('name') for g in bad]}")
    if not payload.get("gates"):
        problems.append("gates/last.json 里没有任何门的结果（不是真跑过的产物）")
    return problems


# ---------------------------------------------------------------------------
# 检查面 ③′：全量门禁（抽空 `wb_review.check_full_gate_run`，参数化门表）
# ---------------------------------------------------------------------------


def _affected_marks_partial_run(payload: dict) -> bool:
    """`last.json` 里的 `affected` 块是不是「部分跑」的标记。"""
    block = payload.get("affected")
    if block is None:
        return False
    return not (isinstance(block, dict) and block.get("enabled") is False)


def _shortfall(missing: list[str], extra: list[str]) -> str:
    detail = []
    if missing:
        detail.append(f"少 {len(missing)} 道：{missing}")
    if extra:
        detail.append(f"多 {len(extra)} 道：{extra}")
    return "；".join(detail) or "门数不等"


def check_full_gate_run(
    payload: dict,
    *,
    expected_gate_names: list[str],
    expected_source: str = "(调用方提供)",
) -> tuple[list[str], str, str]:
    """门禁必须是「**全量那一趟**」—— 部分跑的门禁不许冒充全量。

    ★ 参数化（本仓版从 `run_gates.build_jobs` 读门表；框架版由调用方传 `expected_gate_names`）。
    ★ G10 反例钉子③：`last.json` 里有 `affected` 块 ⇒ 判红并贴原文（不许只报「通过」）。
    ★ 只对真产物（带 `tree_scope`）判红；合成夹具只标注不判红（照本仓口径）。

    返回 `(problems, note, reading)`：`reading` 无条件给；`note` 非空 = 标注（不是红）。
    """
    gates = payload.get("gates") or []
    got = [str(g.get("name")) for g in gates if isinstance(g, dict)]
    partial = _affected_marks_partial_run(payload)
    reading = (f"门数={len(got)}，应有={len(expected_gate_names)}（{expected_source}）；"
               f"affected 块={'有' if partial else '无'}")
    missing = [n for n in expected_gate_names if n not in got]
    extra = [n for n in got if n not in expected_gate_names]
    same_len = len(got) == len(expected_gate_names)
    same_set = set(got) == set(expected_gate_names)
    mismatch = bool(expected_gate_names) and not (same_len and same_set)

    def _dump() -> str:
        return _json_dumps_compact(payload.get("affected"))[:200]

    if not payload.get("tree_scope") and (not expected_gate_names or mismatch or partial):
        why = ("读不到门表" if not expected_gate_names
               else (f"不是全量那一趟：{_shortfall(missing, extra)}" if mismatch
                     else f"带 affected 块：{_dump()}"))
        note = (f"{reading} —— 这份 last.json **没有 tree_scope**，不是门禁跑出来的产物"
                f"（{why}）；**如实标注、不判红**")
        return [], note, reading

    problems: list[str] = []
    if not expected_gate_names:
        problems.append(f"全量门禁：{reading} —— 读不到应有的门数，无法确认这是全量那一趟"
                        "（拿不准不放过）")
    elif mismatch:
        problems.append(f"全量门禁：{reading} —— 不是全量那一趟：{_shortfall(missing, extra)}"
                        "（部分跑的门禁不许冒充全量）")
    if partial:
        problems.append(f"全量门禁：{reading} —— last.json 里有 affected 块"
                        f"（--affected 部分跑的记账）：{_dump()}；部分跑不许冒充全量")
    return problems, "", reading


def _json_dumps_compact(obj: Any) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 检查面 ⓖ：Gates: trailer 真伪（抽空 `wb_review.check_gates_trailer_truth`）
# ---------------------------------------------------------------------------

_GREEN_CLAIM_RE = re.compile(r"门禁绿|全绿|seal")
_NO_GATE_CLAIM_RE = re.compile(r"没跑|未跑|no-gate|commit-only|复用|跳过")


def check_gates_trailer_truth(
    gates_line: str, payload: dict, parent_short: str,
) -> tuple[list[str], str]:
    """`Gates:` trailer 的**真伪**：拿 trailer 内容与 `gates/last.json` 的实际结论对账。

    (a) 真绿（ok 且 rev 对得上）⇒ trailer 必须声称跑过门禁；
    (b) 非真绿 ⇒ trailer 不许声称「全量门禁绿 + seal」（伪造）；
    (c) 主动披露「没跑门禁」⇒ 放行但标一行（不许当门禁绿混过去）。
    """
    line = (gates_line or "").strip()
    ok = payload.get("ok")
    rev = payload.get("rev")
    matched = ok is True and rev == parent_short
    claims_green = bool(_GREEN_CLAIM_RE.search(line))
    claims_no_gate = bool(_NO_GATE_CLAIM_RE.search(line))
    reading = (f"`Gates:` 原文=「{line}」 / last.json ok={ok!r} rev={rev!r}"
               f"（本提交父提交 {parent_short!r}）")
    if matched and not claims_green:
        return [f"{reading} —— 这一笔真跑过全量门禁，trailer 却没声称跑过"
                f"（缺「门禁绿/全绿/seal」这类字样）：声称与事实不符"], ""
    if not matched and claims_green:
        return [f"{reading} —— last.json 不是这一笔的门禁结论，trailer 却声称"
                f"「全量门禁绿 + seal」：伪造门禁结论"], ""
    if matched:
        return [], ""
    why = ("（trailer 已披露，放行）" if claims_no_gate
           else "（trailer 未主动披露「没跑门禁」—— 如实标一行，不当门禁绿）")
    return [], f"这一笔**没有**本轮门禁结论{why}"


# ---------------------------------------------------------------------------
# 检查面：分支（抽空 `wb_review.check_branch`，参数化 default_branch）
# ---------------------------------------------------------------------------


def check_branch(
    branch: str, expected: str, *, default_branch: str,
) -> tuple[list[str], str]:
    """分支判据分**三态**：附着且=expected 不报 / 附着但≠expected 仍报 /
    detached 且 expected==default_branch 跳过并如实记一行。

    ★ 参数化 `default_branch`（本仓版写死 `line/impl-v1`；框架版由调用方传）。
    """
    if branch == "HEAD" and expected == default_branch:
        return [], "分离头指针（detached HEAD）→ 跳过分支判据（没有分支可比，不等于通过了分支检查）"
    if branch != expected:
        return [f"分支不对：现在在 {branch!r}，期望 {expected!r}"], ""
    return [], ""


# ---------------------------------------------------------------------------
# 检查面 ④：改动越界（抽空 `wb_review.check_files`）
# ---------------------------------------------------------------------------


def check_files(files: list[str], *, read_only: bool, allow: list[str]) -> list[str]:
    """改动越界没有：只读卡 = 一个被跟踪文件都不许改；否则按白名单。"""
    if read_only:
        return [f"只读卡不许改被跟踪文件，但它改了 {len(files)} 个：{files[:8]}"] if files else []
    if not allow:
        return ["没有给白名单：复核改动范围请加 `--allow <glob>`（或声明 `--read-only`）"]
    outside = outside_allow(files, allow)
    return [f"有 {len(outside)} 个改动不在白名单里：{outside[:8]}"] if outside else []


# ---------------------------------------------------------------------------
# 检查面 ③″：封存树 vs 提交树（抽空 `wb_review.check_seal_tree`，参数化复算函数）
# ---------------------------------------------------------------------------


def check_seal_tree(
    payload: dict, sha: str, *,
    tree_without_gates_fn: Callable[[str], str],
    expected_scope: str,
    diff_paths_fn: Callable[[str, str], list[str]] | None = None,
) -> tuple[list[str], str, str]:
    """封存树 vs 提交树的正面对账。

    ★ 参数化（本仓版从 `run_gates.tree_without_gates` 读；
      框架版由调用方传 `tree_without_gates_fn`）。
    只对真产物（`tree_scope == expected_scope`）生效；旧笔只标注不判红。
    """
    scope = payload.get("tree_scope")
    recorded = str(payload.get("tree") or "")
    if scope != expected_scope:
        reading = f"tree_scope={scope!r}（非「去 gates/**」口径）→ 不核"
        note = (f"{reading} —— 旧笔那一列核不了；**只标注、不判红**")
        return [], note, reading
    calc = tree_without_gates_fn(sha) or ""
    reading = (f"last.json.tree={recorded[:12] or '?'}；本笔提交去 gates/** 的 tree="
               f"{calc[:12] if calc else '(复算失败)'}"
               f" → {'相同' if calc and calc == recorded else '不同'}")
    if not calc:
        return ([f"封存树 vs 提交树：复算 {sha[:12]}（去 gates/**）失败"
                 f" —— 拿不准不放过"], "", reading)
    if calc == recorded:
        return [], "", reading
    paths = diff_paths_fn(recorded, calc) if diff_paths_fn else []
    where = (f"差在这些路径：{paths}" if paths
             else "拿不到差在哪几个路径")
    return [f"封存树 vs 提交树：last.json.tree={recorded[:12]} ≠ 本笔提交去 gates/** 的 tree="
            f"{calc[:12]} —— 提交树 ≠ 封存树；{where}"], "", reading


# ---------------------------------------------------------------------------
# G10.2 · pipeline.toml 的复核面字段（ReviewConfig）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReviewConfig:
    """`pipeline.toml` 里 `[review]` 段的复核面字段（G10.2）。

    ★ schema 接线（加到 `pipeline.schema.json` + `config.py`）由后续卡做 ——
    本卡白名单不含 schema。本 dataclass 是字段定义 + 严格解析，代码先落。
    """

    who: str                   # 谁复核：人或机器 / 哪条命令
    what: tuple[str, ...]      # 复核什么：域 / 门数 / trailer / 分支 / 脏树
    where: str                 # 结论落哪：gates/review/<task>.json 的路径模板
    # 复核失败怎么办（照本仓口径：不挡提交，但不许把「没复核」写成「复核通过」）
    on_fail: str

    def to_dict(self) -> dict:
        return {
            "who": self.who,
            "what": list(self.what),
            "where": self.where,
            "on_fail": self.on_fail,
        }


class ReviewConfigError(Exception):
    """复核面配置读不了 / 缺键 / 未知键 —— 明确报错，不静默。"""


_REVIEW_WHAT_ALLOWED = frozenset(
    {"domain", "gate_count", "trailer", "branch", "dirty_tree", "seal_tree"}
)
_REVIEW_ON_FAIL_ALLOWED = frozenset({"warn", "block", "mark_only"})


def load_review_config(d: dict[str, Any]) -> ReviewConfig:
    """从 dict 严格解析 `ReviewConfig`（缺键 / 未知键 / 取值错都抛 `ReviewConfigError`）。"""
    legal = {"who", "what", "where", "on_fail"}
    unknown = sorted(set(d) - legal)
    if unknown:
        raise ReviewConfigError(f"[review] 出现未知键 {unknown}（合法键：{sorted(legal)}）")
    for k in ("who", "what", "where", "on_fail"):
        if k not in d:
            raise ReviewConfigError(f"[review] 缺键 {k}")
    who = d["who"]
    what = d["what"]
    where = d["where"]
    on_fail = d["on_fail"]
    if not isinstance(who, str) or not who.strip():
        raise ReviewConfigError("[review].who 必须是非空字符串（谁复核）")
    if not isinstance(what, list) or not what:
        raise ReviewConfigError("[review].what 必须是非空数组（复核什么）")
    bad_what = [w for w in what if w not in _REVIEW_WHAT_ALLOWED]
    if bad_what:
        raise ReviewConfigError(
            f"[review].what 出现未知项 {bad_what}（合法：{sorted(_REVIEW_WHAT_ALLOWED)}）"
        )
    if not isinstance(where, str) or not where.strip():
        raise ReviewConfigError("[review].where 必须是非空字符串（结论落哪）")
    if on_fail not in _REVIEW_ON_FAIL_ALLOWED:
        raise ReviewConfigError(f"[review].on_fail 必须是 {sorted(_REVIEW_ON_FAIL_ALLOWED)} 之一"
                                f"（拿到 {on_fail!r}）")
    return ReviewConfig(who=who, what=tuple(what), where=where, on_fail=on_fail)


# ---------------------------------------------------------------------------
# G10.1 · run_review：一条命令的库实现
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IntegrationResult:
    """一次集成的结果（`pipe review` 的输入之一）。"""

    sha: str                          # 这一笔的提交
    parent_short: str                 # 这一笔的父提交（门禁 rev 要对得上）
    commit_body: str                  # 提交信息（含 trailers）
    changed_files: list[str]          # 这一笔改的文件
    branch: str                       # 当前分支
    dirty: list[str]                  # 工作区未提交改动
    gates_payload: dict               # gates/last.json 的内容（{} = 没有复核记录）


@dataclass(frozen=True)
class AuthorityDomain:
    """卡的权威域（`pipe review` 的输入之二）。"""

    domain: list[str]
    source: str                       # 域来源标签（栅栏预声明 / 队列 / 手打）


@dataclass(frozen=True)
class ReviewVerdict:
    """`pipe review` 的输出：能不能算这一笔。"""

    sha: str
    landed: bool                      # ★ 能不能算这一笔（全过 = True）
    problems: list[str]
    notes: list[str]
    readings: dict[str, Any]          # 各检查面的如实读数（进 --json）

    def to_dict(self) -> dict:
        return {
            "sha": self.sha, "landed": self.landed,
            "problems": self.problems, "notes": self.notes,
            "readings": self.readings,
        }

    def exit_code(self) -> int:
        """退出码照卡 177 的表：全过 0 / 有不过 1 / 没有复核记录 5（前置缺失）。"""
        if not self.readings.get("has_review_record", True):
            return int(ExitCode.PRECONDITION)
        return int(ExitCode.OK) if self.landed else int(ExitCode.GATE_FAIL)


def run_review(
    result: IntegrationResult,
    domain: AuthorityDomain,
    *,
    expected_gate_names: list[str],
    expected_branch: str,
    default_branch: str,
    read_only: bool = False,
    allow: list[str] | None = None,
    dirty_ok: bool = False,
    expected_gate_source: str = "(调用方提供)",
) -> ReviewVerdict:
    """`pipe review` 的库实现：把检查面组合起来，判「这一笔算不算数」。

    ★ G10 反例钉子①：没有复核记录（`gates_payload={}`）⇒ `landed=False`，不许标 landed。
    ★ G10 反例钉子②：rev 对不上 ⇒ `check_gate_evidence` 红。
    ★ G10 反例钉子③：部分跑（有 `affected` 块）⇒ `check_full_gate_run` 红并贴原文。
    """
    payload = result.gates_payload
    has_record = bool(payload)
    problems: list[str] = []
    notes: list[str] = []

    if not has_record:
        problems.append("没有复核记录（gates/last.json 缺失或为空）—— 不许标 landed")

    # ② trailer
    trailer_problems, trailers = check_trailers(result.commit_body)
    problems += trailer_problems

    # ③ 门禁证据
    problems += check_gate_evidence(payload, result.parent_short)

    # ③′ 全量门禁
    full_problems, full_note, full_reading = check_full_gate_run(
        payload, expected_gate_names=expected_gate_names, expected_source=expected_gate_source,
    )
    problems += full_problems
    if full_note:
        notes.append(full_note)

    # ⓖ Gates: trailer 真伪
    truth_problems, truth_note = check_gates_trailer_truth(
        trailers.get("Gates") or "", payload, result.parent_short,
    )
    problems += truth_problems
    if truth_note:
        notes.append(truth_note)

    # ④ 改动越界
    problems += check_files(result.changed_files, read_only=read_only, allow=allow or [])

    # ⑥ 实际改动 vs 权威域
    outside = outside_domain(result.changed_files, domain.domain)
    if outside:
        problems.append(f"卡树实际改了域外文件 {len(outside)} 个：{outside[:8]}"
                        f"（域来自 {domain.source}：{domain.domain}）")

    # 分支
    branch_problems, branch_note = check_branch(
        result.branch, expected_branch, default_branch=default_branch,
    )
    problems += branch_problems
    if branch_note:
        notes.append(branch_note)

    # ⑤ 脏树
    if result.dirty and not dirty_ok:
        problems.append(f"工作区有没提交的改动（{len(result.dirty)} 个）：{result.dirty[:5]}")

    readings = {
        "has_review_record": has_record,
        "gates_ok": payload.get("ok") if has_record else None,
        "gates_rev": payload.get("rev") if has_record else None,
        "full_gate_reading": full_reading,
        "branch": result.branch,
        "domain_source": domain.source,
    }
    landed = has_record and not problems
    return ReviewVerdict(
        sha=result.sha, landed=landed,
        problems=problems, notes=notes, readings=readings,
    )
