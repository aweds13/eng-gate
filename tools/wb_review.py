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
     ★ 卡 210（T-G320）：收口链自己造的**派生物**（三份本台片段 + 三份共享文档 +
     两个门禁产物 —— 见 `DERIVED_GLOBS`）是**预期内**：放行集 = `allow` ∪ 派生物清单，
     **只有**两边都不在的改动才报（报告分「派生物（预期）」/「越界」两栏，让人一眼看出该有哪栏）；
  ⑤ **工作区干不干净**：复核时 `git status --porcelain -uno` 必须空
     （工人不许留没提交的改动）。

★ 另有一条**分支判据**（T-G158）分三态：附着且 = `--branch` 不报 / 附着但不匹配仍报 /
**分离头指针（detached HEAD）跳过并如实记一行** —— 外包链路的每张卡都在 detached worktree 里
干活，老判据那一条**永远**为假（见 `check_branch()`）。

★★ 第 ⑥ 档（卡 131 · T-G228，治外部审查 GLM-5.3「三.1」）—— 只有给 `--card` 时才跑：

  ⑥ **实际改动 vs 权威域**：拿**卡树里真的改了什么**（`git status --porcelain -uall --no-renames`，
     **含未跟踪**）与**权威域**比对，域外即**拒并逐个点名**。「权威域」按序读：① 任务栅栏的
     预声明（`gates/diag/batch/<任务>.toml` 里该成员的 `paths`）；② 队列 `docs/workbacklog.toml`
     里该卡的 `files`；**两个都查不到 ⇒ 拒**（空域会骗过一切守卫）。手打的 `--allow` **降级**为
     「只在没有权威域时才用」、且**用了会打印一行"手打白名单"**（治"手打接力"）；`--waive` 显式
     豁免并**留痕**（打印 + 进 `--json`）。
     ★ 老判据的缺口正在这：第 ④ 条只对**自报的**改动列表做 fnmatch（`check_files`），
     "卡树里真的改了什么"从不参与 —— 现在补上，越界不再靠人手对眼。

★★ `Gates:` trailer 的**真伪**（卡 133 · T-G230，治外部审查 GLM-5.3「三.2」）—— 只在 `--rev` 里跑：

   ★ **分工（别把这条做成第二份真源）**：`Gates:` **在不在**归 `scripts/audit_progress.py`
     （存在性判据，**保留**）；**真伪**归这里 —— 拿 trailer 的内容与 `gates/last.json` 的
     `ok`/`rev` **对账**。判据见 `check_gates_trailer_truth()`：真绿必须声称绿；非真绿不许声称绿
     （= 伪造）；`--no-gate` / `--commit-only` 形态若主动披露"没跑门禁"，**放行**但在输出与
     `--json` 里标一行「这一笔**没有**本轮门禁结论」，**不许**当成"门禁绿"混过去。

★★ 第 ③′ 档（卡 147 · T-G247）—— **门禁必须是"全量那一趟"**：部分跑的门禁**不许冒充全量**：

   ★ 来路：卡 140 自己发现的后门 —— `tools/wb_verify.py` 原来写死 `EXPECT_GATES=17`、能拦"部分
     跑的 `last.json`"，但 `wb_review.py` 原来只查 `ok` / `rev` / 每门 `exit_code`，**不查门数** ⇒
     若有人把 `--affected` 那一趟的 `last.json` 提交上去，**复核主链可能不拦**（正是本仓最该防的
     "看着绿其实没查全"）。判据见 `check_full_gate_run()`：① 门数 = 该仓**当前应有**的门数
     （从 `scripts/run_gates.py` 的 `build_jobs` **现读** —— ★ **不写死 17、不造第二份门表**）；
     ② `last.json` 里出现 `affected` 块（`--affected` 部分跑的记账）⇒ 判红并贴原文。
   ★ **只对"门禁自己写出来的产物"判红**（`tree_scope` 是 `run_gates.py` 必写的字段）：合成夹具
     （无 `tree_scope`）**只标注不判红** —— 详见 `check_full_gate_run()` 的 docstring。

★★ 第 ③″ 档（卡 160 · T-G260）—— **封存树 vs 提交树的正面对账**（消费掉那个"没人查"的封存指纹）：

   ★ 来路：INV-26 / INV-29 / INV-34 —— 封存指纹**生成了、没人查**（谁在提交前拿它比对，没有判据）。
     判据见 `check_seal_tree()`：拿 `last.json.tree`（封存那一刻"去 `gates/**`、即将提交"的 tree）
     与本笔提交**去掉 `gates/**` 的 tree** 比；**不等就点名差在哪几个路径**。原来只有一屏核实器
     `wb_verify.py::check_fingerprint` 查它，**复核主链一条都不查** —— 现在接进主链。
   ★ 同一口径：只对真产物（带 `tree_scope`）判红；旧笔（无 `tree_scope`）**只标注不判红**。

用法：
    python -X utf8 tools/wb_review.py --rev HEAD --read-only
    python -X utf8 tools/wb_review.py --rev HEAD --allow "src/**" --allow "tests/**"
    python -X utf8 tools/wb_review.py --rev HEAD --allow "**" --json
    python -X utf8 tools/wb_review.py --card M-1 --task B-FIX3     # 第 ⑥ 档：真卡树 vs 权威域
    python -X utf8 tools/wb_review.py --card M-1 --task B-FIX3 --waive 某文件 --json

★ `--card` 模式下**不跑** ②③④⑤ 那几条：它们是"针对某一笔**提交**"的判据，而卡树在被复核时
  通常**还没提交**（工人不许 commit）；第 ⑥ 档只看**工作区实际改动**，所以是独立的一档。

退出码：0 全过 / 1 有不过的（逐条打印为什么）/ 2 参数或 git 取不到。

★ 边界（如实写）：`gates/last.json` 的 `tree` 字段**故意不查** —— 它自己也在那棵树里（自指悖论），
`scripts/run_gates.py` 里写明"审计不看它"；这里只查 `rev`（父提交）与各门结论。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import gate_base
import tomllib
from pool.plan import BacklogError, load_backlog
from pool.review import changed_paths, domain_of_manifest_text, outside_allow, outside_domain

ROOT = Path(__file__).resolve().parent.parent


def _wb_plan() -> object | None:
    """`tools/wb_plan.py`（台账分片的唯一实现）—— 取不到就返 `None`。

    真仓里它总在（卡 E89 自己就改它）；假仓库/最小树里没有，那时**分片口径不可用
    ⇒ 退回总表**（本卡之前的行为一字不变）。
    """
    try:
        import wb_plan  # noqa: PLC0415 —— 只在用到分片口径时才加载
    except ImportError:
        return None
    return wb_plan
TASK_RE = re.compile(r"^Task:\s*(\S+)\s*$", re.M)
#: `Gates:` trailer 里声称"跑过门禁**且绿**"的字样 —— 真绿那一笔**必须**含其中之一（卡 133）。
GREEN_CLAIM_RE = re.compile(r"门禁绿|全绿|seal")
#: 声称"这一笔没跑门禁 / 复用已绿的旧结论"的字样（`--no-gate` / `--commit-only` 的**主动披露**）。
NO_GATE_CLAIM_RE = re.compile(r"没跑|未跑|no-gate|commit-only|复用|跳过")
#: 期望分支的默认值（就是集成分支）。`check_branch()` 的 detached 跳过只对它生效（T-G158）。
DEFAULT_BRANCH = "line/impl-v1"

#: ★ 卡 210（T-G320）：收口链第 ⑥ 步（`tools/pool/landing.py`）**无条件**并进 `allow` 才提交的
#: **派生物清单** —— 复核侧必须把它们认成**预期内**，否则每一笔都被自己的派生物判成"越界"（噪声，
#: 连着 6 笔报同一条）。**凭什么预期**（真源是 `landing.py`）：
#:   · 三份**本台片段**（`docs/changelog.d/{task}.md` / `docs/traceability.d/{task}.toml` /
#:     `复盘/交接.d/{task}.md`）—— 第 ⑥ 步「白名单 → add → commit」里**自动补进** `allow` 的循环
#:     （`landing.py:851`）；片段名里带任务号，复核这侧不查任务号（提交的 `Task:` 未必等于片段名），
#:     故按**目录 glob** 认；
#:   · 三份**共享文档** `DOCS`（`landing.py:66`）与两个**门禁产物** `GATES`（`landing.py:67`）——
#:     第 ⑥ 步 `allow += list(DOCS) + list(GATES)` **无条件**并入（`landing.py:856`）。
#: ★ 这只是「预期内」的**边界**、**不是"什么都不报"**：`allow` ∪ 本清单**之外**的改动照报、照红
#:   （判据在 `check_files()` / `classify_changes()`）。
DERIVED_GLOBS: tuple[str, ...] = (
    "docs/changelog.d/*.md",        # 片段：changelog
    "docs/traceability.d/*.toml",   # 片段：traceability
    "复盘/交接.d/*.md",             # 片段：交接
    "docs/changelog.md",            # DOCS：changelog 汇总
    "docs/traceability.toml",       # DOCS：traceability 汇总
    "复盘/交接-重构进度.md",         # DOCS：交接 CHECKPOINT
    "gates/last.json",              # GATES：门禁结论
    "gates/reuse.json",             # GATES：复用记账
    # ★ 卡 E93（T-AG601）：收口链**还会**造这四个 —— 上面 8 条之外的来路：
    #   · `docs/INDEX.md` / `docs/subsystems/pool/README.md` —— `landing.RECOUNT_DOCS`
    #     （`tools/pool/landing.py:102`），`recount_derived()` 用 `scripts/gen_doc_index.py` /
    #     `scripts/gen_pool_readme.py` **重算**（落在盘点口径里的派生物，不是本卡的交付面）；
    #   · `docs/workbacklog.toml` —— `flip_card_status()`（`landing.py:579`）翻账时写；
    #   · `docs/backlog/*.toml` —— 台账**分片**（`landing.py::_shard_paths` /
    #     `ledger.target_path`）：
    #     分片启用后总表**靠它生成**；与 `docs/changelog.d/*.md` 同风格按目录 glob 认
    #     （分片名里带分区，复核这侧不该逐个点名）。
    # ★ 证据（实测，不是推测）：`gates/review/T-AG600.json` 的 problems[1] =
    #   「有 3 个改动不在白名单里：['docs/INDEX.md', 'docs/subsystems/pool/README.md',
    #   'docs/workbacklog.toml']」—— 那三件**正是这一笔自己的收口链产物**，却不在 `allow` 里；
    #   全仓同型 26 条（15 条是 ['docs/workbacklog.toml']、1 条是这个三件套）。
    # ★ 边界照旧：这里只把「收口链自己造的」认成**预期内**，不放松任何判据 ——
    #   `docs/` 下**不是**收口链产物的（如 `docs/rogue.md`）照样报、照样红。
    "docs/INDEX.md",                    # RECOUNT_DOCS：文档总索引（重算）
    "docs/subsystems/pool/README.md",   # RECOUNT_DOCS：号池子系统索引（重算）
    "docs/workbacklog.toml",            # 台账总表：flip_card_status 翻账
    "docs/backlog/*.toml",              # 台账分片（ledger.target_path）
)


def git(*args: str) -> str:
    """跑一条 git 命令。★ `-c core.quotepath=false`：中文路径不许被转义成 `\\345\\244...`，
    否则第 ④ 条的白名单会**把中文路径全判成越界**（T-G84 实测踩到）。"""
    done = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args], cwd=str(ROOT), capture_output=True,
        text=True, encoding="utf-8", errors="replace",
    )
    return (done.stdout or "").strip()


def git_raw(*args: str) -> str:
    """同 `git()`，但**不 strip 前导空白** —— `--porcelain` 的状态列可能是空格（` M src/a.py`），
    一 strip 就错位（`changed_paths` 会读到 `rc/a.py` 这种缺一个字符的路径；实测踩到）。
    只把行尾换行去掉，行首原样。"""
    done = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args], cwd=str(ROOT), capture_output=True,
        text=True, encoding="utf-8", errors="replace",
    )
    return (done.stdout or "").rstrip("\r\n")


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


def _resolve_commit(short: str) -> str:
    """把短 sha 解析成完整 sha；解析不出来就返回空串。

    ★ 判据比的是**提交**，不是字符串长度：git 的 `--short` 会随仓库变大而变长
    （实测同一笔这里给 7 位、那里给 8 位），直接比字面量会把「同一笔提交」判成两笔。
    """
    if not short:
        return ""
    done = subprocess.run(
        ["git", "rev-parse", "--verify", f"{short}^{{commit}}"],
        cwd=str(ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
    )
    return done.stdout.strip() if done.returncode == 0 else ""


# ★ 卡 E123（T-AG632）：门禁基点与父提交差在哪 —— **分类器只有一份**（`tools/gate_base.py`），
#   复核器这两处（③ 与 ⓖ）都调它；另三处（`wb_verify` / `gate_pool` / `framework`）也调同一份。
MATCH = gate_base.MATCH
LEDGER_ONLY = gate_base.LEDGER_ONLY
DRIFT = gate_base.DRIFT
# ★ 卡 E137：封存树这一档的两档分类（真源同在上面的分类器里）。
BASIS_DRIFT = gate_base.BASIS_DRIFT
TRUE_MISMATCH = gate_base.TRUE_MISMATCH


def gate_base_drift(
    payload_rev: str,
    parent_short: str,
    *,
    sealed_at: str = "",
    root: Path | str | None = None,
    **providers: object,
) -> tuple[str, list[str], str]:
    """分类器这一侧的口子：取数默认跑在 `ROOT` 上（测试与别的树可传 `root` 或直接注入）。

    返回 `(分类, 差异文件, 读数)` —— 分类 ∈ `MATCH` / `LEDGER_ONLY` / `DRIFT`。
    """
    base = Path(root) if root is not None else ROOT
    taken: dict[str, object] = dict(gate_base.providers(base))
    taken.update(providers)
    return gate_base.gate_base_drift(payload_rev, parent_short, sealed_at=sealed_at, **taken)  # type: ignore[arg-type]



def gate_basis_verdict(
    payload_rev: str,
    parent_short: str,
    recorded_tree: str,
    commit_sha: str,
    files: list[str],
    *,
    root: Path | str | None = None,
    **providers: object,
) -> tuple[str, list[str], str]:
    """判据 1 的公开口子 —— 分类器**只有一份**（tools/gate_base.py），这里只转发。

    返回 (档, 差异路径, 读数)，档 ∈ BASIS_DRIFT / TRUE_MISMATCH。
    """
    base = Path(root) if root is not None else ROOT
    taken: dict[str, object] = dict(gate_base.basis_providers(base))
    taken.update(providers)
    return gate_base.gate_basis_verdict(
        payload_rev, parent_short, recorded_tree, commit_sha, files, **taken)  # type: ignore[arg-type]


# ★ 卡 E137：判**不了**（对象库缺 tree / 两个 sha 解析不出 / 复算失败）时返回 None，
#   调用方退回本文件原来的那几支口径 —— 旧笔与合成 sha 的钉子都靠这条活。
_BASIS_UNPROVABLE = (
    "不是两个都解析得出的提交",
    "不在对象库里",
    "复算本笔提交",
    "差在哪取不到",
    "没给本笔提交",
)


def basis_check(
    payload: dict,
    sha: str,
    parent_short: str = "",
    files: list[str] | None = None,
    **providers: object,
) -> dict | None:
    """判据 3 的取数口：封存树与本笔提交树的差异该算谁的。

    返回 {tier, rows, reading, record, parent}；record 只在 BASIS_DRIFT 时非空
    （= 进 --json 的 waived_basis）。**只判定，不 print、不判红。**
    """
    if payload.get("tree_scope") != _expected_scope():
        return None
    recorded = str(payload.get("tree") or "")
    gates_rev = str(payload.get("rev") or "")
    if not recorded or not gates_rev:
        return None
    parent = parent_short or git("rev-parse", "--short", f"{sha}^")
    if not parent:
        return None
    try:
        tier, rows, reading = gate_basis_verdict(
            gates_rev, parent, recorded, sha, list(files or []), **providers)
    except Exception:  # noqa: BLE001 —— 取数出任何岔子都退回旧口径，不许把判不了洗成放行
        return None
    if tier == TRUE_MISMATCH and any(s in reading for s in _BASIS_UNPROVABLE):
        return None
    record: dict | None = None
    if tier == BASIS_DRIFT:
        middle: object = None
        profiles: list[str] = []
        try:
            taken: dict[str, object] = dict(gate_base.basis_providers(ROOT))
            taken.update(providers)
            res = taken["resolve"]
            cnt = taken["count_between"]
            req = taken["required_profiles"]
            a = str(res(gates_rev) or "")  # type: ignore[operator]
            b = str(res(parent) or "")  # type: ignore[operator]
            middle = cnt(a, b) if callable(cnt) else None  # type: ignore[operator]
            profiles = sorted(str(x) for x in req(list(rows))) if callable(req) else []  # type: ignore[operator]
        except Exception:  # noqa: BLE001
            middle, profiles = None, []
        record = {
            "gates_rev": gates_rev,
            "parent": parent,
            "middle_commits": middle,
            "diff_paths": list(rows),
            "profiles_affected": profiles,
            "note": reading,
        }
    return {"tier": tier, "rows": list(rows), "reading": reading,
            "record": record, "parent": parent}


def check_gate_evidence(
    payload: dict, parent_short: str, notes: list[str] | None = None
) -> list[str]:
    """③ 门禁是不是**为这一笔**跑的 —— 三档：同提交 / 基点是真祖先且只差台账 / 其余。

    ★ 卡 E123：`rev` 落后**台账**几笔（现场 89cd4deb：门禁在 f833d006 跑、父提交 ebd39871）
      不再报「门禁不是为这一笔跑的」；但结论**未经复验**（pytest / docs 属永远跑），
      读数进 `notes`（CLI 落到 `gate_base_drift_note`）—— 如实标注，不是放行。
    """
    problems: list[str] = []
    # ★ A324：封存里记了 `profile`（≠ all）⇒ 这是**只跑了一档**，不能当提交闸用。
    #   这条堵的是「挑一档跑绿冒充全量」—— 档位是给人做内循环的，不是给提交用的。
    # ★ 卡 A327：档不再"必须全量"，改按 `gates/defs/domains.py` 的同一张表判
    #   「这次改动**必需**的档 ⊆ 产物里**真跑全了**的档」。拿不准（没有 required_profiles /
    #   没有 profiles_run）仍按老口径拦 —— 宁可多跑，不许漏跑。
    ran = payload.get("profiles_run")
    if ran is None:
        ran_profile = payload.get("profile")
        if ran_profile not in (None, "all"):
            problems.append(
                f"门禁只跑了 --profile {ran_profile} 这一档，且没有 profiles_run 记账 —— "
                "分不清是自查还是提交闸（重跑一次带 --profiles 的门禁）"
            )
    else:
        ran_list = [str(x) for x in ran] if isinstance(ran, list) else [str(ran)]
        required = [str(x) for x in (payload.get("required_profiles") or [])]
        if "all" not in ran_list:
            if not required:
                problems.append(
                    f"门禁只跑全了 {ran_list} 档，而 last.json 里没有 required_profiles —— "
                    "没法证明够用（重跑时带 --profiles / --changed-from，让产物自己记账）"
                )
            else:
                missing = [x for x in required if x not in ran_list]
                if missing:
                    problems.append(
                        f"这次改动需要 {'+'.join(required)} 档，产物里只跑全了 "
                        f"{'+'.join(ran_list)}（缺 {'+'.join(missing)}）—— 缺档不许当提交证据"
                    )
    if payload.get("ok") is not True:
        problems.append(f"gates/last.json 的 ok 不是 true：{payload.get('ok')!r}")
    state, _rows, reading = gate_base_drift(
        str(payload.get("rev") or ""), parent_short,
        sealed_at=str(payload.get("sealed_at") or ""))
    if state == LEDGER_ONLY:
        if notes is not None:
            notes.append(reading)
    elif gate_base.category_is_red(state):
        # ★ 判据 2：升级文案（逐条点出改了哪些源码）+ **保留**原句作兜底。
        problems.append(
            f"门禁不是为这一笔跑的：last.json 的 rev={payload.get('rev')!r}"
            f"，而这一笔的父提交是 {parent_short!r}"
            f"（★ 门禁跑在更早的提交上，那次结论没有为这一笔复验过）—— {reading}"
        )
    if payload.get("docs_sync_ok") is not True or payload.get("docs_sync_missing"):
        problems.append(
            f"台账/交接数字没同步：docs_sync_ok={payload.get('docs_sync_ok')!r}，"
            f"missing={payload.get('docs_sync_missing')!r}"
        )
    # ★ T-AG518：口径必须与门禁自己那份 `gates_ok()` **逐字一致** —— 只数 `blocking` 门。
    #   病根：这里原先无条件 `exit_code != 0` ⇒ 把 NOT RUN（`exit_code=3, blocking=false`，
    #   环境没 node 的渲染层）判成"有门没过"，而同一份 `last.json` 在门禁侧是 `ok=true`。
    #   实测 5885f28f：门禁 `ok=True`、`gates_ok()` 返回 True，复核却报"有门没过：['web_live']"
    #   ⇒ 同一份产物两个结论，复核会把合法提交判成"不算数"。
    #   NOT RUN 不是 PASS，但**也不是红** —— 它在 `gates_ok` 里不计，这里同样不计；
    #   真值（"这一层没验证"）由 `status`/`note` 照原样留在 `last.json` 里，不靠复核来记。
    bad = [
        g
        for g in payload.get("gates", [])
        if g.get("exit_code") != 0 and g.get("blocking", True)
    ]
    if bad:
        problems.append(f"有门没过：{[g.get('name') for g in bad]}")
    if not payload.get("gates"):
        problems.append("gates/last.json 里没有任何门的结果（不是真跑过的产物）")
    return problems


def _run_gates_module() -> object:
    """按**本树** `scripts/` 现读门禁模块 —— 门清单的**唯一真源**。

    ★ 卡 147 的硬要求（别越界）：门数是会变的（今天 17，明天加一道就是 18）——
      **不许在本文件里再造第二份门表**（写死一个数字就是一份会漂的第二真源）。
      延迟到运行时 `import run_gates`，用它的门表现读。
    """
    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import run_gates  # 延迟 import：避免 wb_review 被 import 时就依赖 scripts/ 的运行时
    return run_gates


def _profile_doors(profiles: list[str]) -> list[str]:
    """档名 → 门名（从 `run_gates.GATE_PROFILES` 现读，**不在这里造第二份门表**）。"""
    try:
        table = _run_gates_module().GATE_PROFILES
    except Exception:  # 读不到就回空 —— 调用方据此退回"按全量比对"
        return []
    doors: list[str] = []
    for one in profiles:
        doors += [str(n) for n in table.get(one, ())]
    return doors


def expected_gate_names() -> tuple[list[str], str]:
    """该仓**当前应有**的门清单：`run_gates.build_jobs(quick=False, fast=False)`（全量那一趟）。

    返回 `(名字清单, 来源标签)`；读不到（import 失败 / 门表坏了）→ `([], 原因)` ——
    调用方据此**判红**（拿不准不放过），不静默当成"没有约束"。
    """
    try:
        names = [str(n) for n, _ in _run_gates_module().build_jobs(False, False)]
    except Exception as exc:  # 读不到就如实说，别猜（"无法判断"优于猜）
        return [], f"读不到门表（{type(exc).__name__}: {exc}）"
    return names, f"run_gates.build_jobs(quick=False, fast=False)（{len(names)} 道）"


def _affected_marks_partial_run(payload: dict) -> bool:
    """`last.json` 里的 `affected` 块是不是"部分跑"的标记（卡 147）。

    ★ 现行 `AffectedPlan.to_payload()`（`scripts/run_gates.py` 的 `--affected` 记账）**没有**
      `enabled` 字段 —— `--affected` 那一趟只要用了就写这个块，块的**出现**即是标记。
      若将来真加了 `enabled`，这里尊重显式的 `False`（= 作者声明它不是部分跑）。
    """
    block = payload.get("affected")
    if block is None:
        return False
    return not (isinstance(block, dict) and block.get("enabled") is False)


def check_full_gate_run(payload: dict) -> tuple[list[str], str, str]:
    """③′ 门禁必须是"**全量那一趟**"（卡 147 · T-G247）—— 部分跑的门禁不许冒充全量。

    判据（**两条**，任一命中即**判红**）：
      ① 门数 = 该仓**当前应有**的门数（从 `build_jobs` **现读**，见 `expected_gate_names()`）；
         不等就**点名**"少了哪几道 / 多了哪几道"（照现行实现，门名是稳定字面）；
      ② `last.json` 里出现 `affected` 块（`--affected` 部分跑的记账）⇒ 判红并贴原文片段。

    ★ **一条红线：判据只对"门禁自己写出来的产物"生效**（`run_gates.py` 写 `last.json` 时**必写**
      `tree_scope`，见 `scripts/run_gates.py:1664`）。没有 `tree_scope` 的 `last.json`（测试夹具 /
      T-G179 之前的旧笔）**不当真产物** ⇒ **只标注、不判红**（拿不准就如实记一行让人瞥一眼）。
      为什么要有这条：本仓的两个既有测试（`tests/test_wb_review_branch.py` 等）用的是 1 道门的
      **合成** `last.json`；若不区分，它们会被这条新判据当场判红，而那张卡的白名单里**没有**它们
      （改它们 = 越界）。区分之后：真·`--affected` 产物 **照判红**（带 `tree_scope`），夹具只留一条
      标注。

    ★ **口径选了"判红"而不是一律"只标注"**（卡 147 给了两种，选一种）：对真产物，
      本工具的语义是"这一笔**算不算数**"的闸 —— 只标注不判红 = 把"部分跑"放进"算数"，正是本卡要堵的
      假绿；卡也明写"宁可误报……不许放过"。"读不到门表"同样**判红**（读不到就不敢确认是全量那一趟）。

    ★ 返回 `(problems, note, 如实读数行)`：
      - `reading` **无条件**给（门数=多少、应有=多少、affected 有无）——
        复核报告那一行一眼看出查的是什么；
      - `note` 非空 = 一条"标注"（不是红），进 `--json` 的 `full_gate_note`。
    """
    gates = payload.get("gates") or []
    got = [str(g.get("name")) for g in gates if isinstance(g, dict)]
    expected, source = expected_gate_names()
    # ★ 卡 A327：产物自己记了「跑全了哪几档」时，"应有"就按那几档算（不再要求 19 道全到）；
    #   没记（老产物 / 全量那趟）仍按全量比对 —— 老口径逐字不变。
    ran = payload.get("profiles_run")
    if ran and isinstance(ran, list) and [str(x) for x in ran] != ["all"]:
        profile_doors = _profile_doors([str(x) for x in ran])
        if profile_doors:
            expected, source = profile_doors, f"profiles_run={[str(x) for x in ran]}"
    partial = _affected_marks_partial_run(payload)
    reading = (f"门数={len(got)}，应有={len(expected) if expected else '?'}（{source}）；"
               f"affected 块={'有' if partial else '无'}")
    missing = [n for n in expected if n not in got]
    extra = [n for n in got if n not in expected]
    mismatch = bool(expected) and (len(got) != len(expected) or set(got) != set(expected))

    def _dump() -> str:
        return json.dumps(payload.get("affected"), ensure_ascii=False)[:200]

    # 非真产物（没有 `tree_scope`）：只标注、不判红（见 docstring 的红线）。
    if not payload.get("tree_scope") and (not expected or mismatch or partial):
        why = ("读不到门表" if not expected
               else (f"不是全量那一趟：{_shortfall(missing, extra)}" if mismatch
                     else f"带 affected 块：{_dump()}"))
        note = (f"{reading} —— 这份 last.json **没有 tree_scope**，不是门禁跑出来的产物"
                f"（{why}）；拿不准就不敢确认它是全量那一趟，**如实标注、不判红**")
        return [], note, reading

    problems: list[str] = []
    if not expected:
        problems.append(f"③′ 全量门禁：{reading} —— 读不到应有的门数，无法确认这是全量那一趟"
                        "（拿不准不放过）")
    elif mismatch:
        problems.append(f"③′ 全量门禁：{reading} —— 不是全量那一趟：{_shortfall(missing, extra)}"
                        "（部分跑的门禁不许冒充全量）")
    if partial:
        problems.append(f"③′ 全量门禁：{reading} —— last.json 里有 affected 块"
                        f"（--affected 部分跑的记账）：{_dump()}；部分跑不许冒充全量")
    return problems, "", reading


def _shortfall(missing: list[str], extra: list[str]) -> str:
    """把"差在哪"说成人话：少了几道（点名）/ 多了几道（点名）。"""
    detail = []
    if missing:
        detail.append(f"少 {len(missing)} 道：{missing}")
    if extra:
        detail.append(f"多 {len(extra)} 道：{extra}")
    return "；".join(detail) or "门数不等"


def _expected_scope() -> str:
    """封存指纹口径自述值的**唯一真源**：`scripts/run_gates.py::TREE_SCOPE`（现读）。

    读不到（import 炸了）→ 回退字面量 —— 那时 `check_seal_tree` 反正会因复算失败判红，
    这个回退只影响"是不是旧笔"的判定，不静默放过。
    """
    try:
        return str(_run_gates_module().TREE_SCOPE)
    except Exception:
        return "worktree-minus-gates"


def _tree_without_gates(rev: str) -> str:
    """按**本树** `scripts/run_gates.py` 的实现复算 `<rev>` 去掉 `gates/**` 的 tree 哈希。

    ★ 共用门禁自己那份实现（`run_gates.tree_without_gates`），**不在这里另写一套切法**
      —— 手写第二套切法就是 080 那个假护栏的病根（见 `wb_verify.py::_tree_without_gates`）。
    复算失败（取不到索引 / write-tree 失败）→ 空串：调用方如实报"复算失败"，**不假装对上**。
    """
    try:
        return _run_gates_module().tree_without_gates(ROOT, rev) or ""
    except Exception:  # import / 复算炸了都算"拿不到"——"无法判断"优于猜
        return ""


def _diff_tree_paths(old_tree: str, new_tree: str) -> list[str]:
    """两个 tree 之间**内容不同**的路径（点名用）：`git diff --name-only <t1> <t2>`。

    两个 tree 对象都在对象库里（`write-tree` 写下的那个是悬空的，但在 GC 之前一直在），
    所以按 tree 哈希直接 diff 是可行的。拿不到（命令失败）→ 空列表（调用方如实说"拿不到"）。
    """
    if not (old_tree and new_tree):
        return []
    return [ln.strip() for ln in git("diff", "--name-only", old_tree, new_tree).splitlines()
            if ln.strip()]


# ★ 卡 E137：found 由 basis_check() 算好传进来（main 只算一次）；
#   缺省哨兵 = 这个函数自己算 —— 算不出东西时照样退回旧口径。
_BASIS_UNSET = object()


def check_seal_tree(
    payload: dict, sha: str, *, found: dict | None | object = _BASIS_UNSET
) -> tuple[list[str], str, str]:
    """③″ **封存树 vs 提交树的正面对账**（卡 160 · T-G260）。

    `last.json.tree`（口径见 `tree_scope`）是封存那一刻「**除 `gates/**` 外**、即将提交的内容」
    的 tree 哈希（`scripts/run_gates.py::tree_without_gates` 的固定点口径）。提交之后，
    这一笔提交**去掉 `gates/**` 的 tree 必须与它逐字节相同** —— 不等就**点名差在哪几个路径**。
    这补的是那条"判据生成了、没人消费"的缝（INV-26 / INV-29 / INV-34）：原来只有一屏核实器
    `wb_verify.py::check_fingerprint` 查它，**复核主链一条都不查**。

    ★ 只对**真产物**（`tree_scope == run_gates.TREE_SCOPE`）生效：旧笔没 `tree_scope`，那一列记的是
      "底座那棵树的哈希"（worktree 回退 + 自指两个洞），核不了 ⇒ **只如实记一行、不判红**
      （既不假装 OK、也不算 FAIL）—— 与 `wb_verify.py::check_fingerprint` 同一口径。

    返回 `(problems, note, reading)`：
      - `reading` **无条件**给（两边的 tree 短哈希 + 相同 / 不同 / 未核）；
      - `note` 非空 = 一条"标注"（不是红），进 `--json` 的 `seal_tree_note`；
      - `problems` = 该红的那几条（提交树 ≠ 封存树、或复算失败）。
    """
    scope = payload.get("tree_scope")
    recorded = str(payload.get("tree") or "")
    if scope != _expected_scope():
        reading = f"tree_scope={scope!r}（非「去 gates/**」口径）→ 不核"
        note = (f"{reading} —— 旧笔那一列是「底座那棵树的哈希」（worktree 回退 + 自指两个洞），"
                "核不了；**只标注、不判红**（既不假装核过、也不算 FAIL）")
        return [], note, reading
    calc = _tree_without_gates(sha)
    reading = (f"last.json.tree={recorded[:12] or '?'}；本笔提交去 gates/** 的 tree="
               f"{calc[:12] if calc else '(复算失败)'}"
               f" → {'相同' if calc and calc == recorded else '不同'}")
    if not calc:
        return ([f"封存树 vs 提交树：复算 {sha[:12]}（去 gates/**）失败"
                 f" —— 拿不准不放过"], "", reading)
    if calc == recorded:
        return [], "", reading
    paths = _diff_tree_paths(recorded, calc)
    where = (f"差在这些路径：{paths}" if paths
             else "拿不到差在哪几个路径（git diff 没回东西）")
    seen = basis_check(payload, sha) if found is _BASIS_UNSET else found
    if isinstance(seen, dict):
        tier = str(seen.get("tier") or "")
        rows = list(seen.get("rows") or []) or paths
        if tier == BASIS_DRIFT:
            # ★ 卡 E137：差异全由**中间提交**带入、且只落台账/文档档 ⇒ 如实留痕，不判红。
            return [], (f"封存树与本笔提交树差的 {len(rows)} 条全由中间提交带入"
                        f"（门禁基点漂移，**未经复验**）：{seen.get('reading')}"), reading
        if tier == TRUE_MISMATCH:
            return [f"封存树 vs 提交树：last.json.tree={recorded[:12]}"
                    f" ≠ 本笔提交去 gates/** 的 tree="
                    f"{calc[:12]} —— 差异**不能**归给中间提交：{seen.get('reading')}"
                    f"；差在这些路径：{rows}"], "", reading
    return [f"封存树 vs 提交树：last.json.tree={recorded[:12]} ≠ 本笔提交去 gates/** 的 tree="
            f"{calc[:12]} —— 提交树 ≠ 封存树（封存之后又动了文件？）；{where}"], "", reading


def check_gates_trailer_truth(
    gates_line: str,
    payload: dict,
    parent_short: str,
    *,
    found: dict | None | object = _BASIS_UNSET,
) -> tuple[list[str], str]:
    """`Gates:` trailer 的**真伪**（卡 133 · T-G230，治外部审查 GLM-5.3「三.2」）。

    ★ **分工（别把这条做成第二份真源）**：`scripts/audit_progress.py` 只管 `Gates:`
    trailer **在不在**（存在性判据，保留）；**真伪**归这里 —— 拿 trailer 的内容与
    `gates/last.json` 的**实际结论**对账。

    判据（照卡写，别自己发明方向）：
      (a) `last.json.ok==true` 且基点是父提交（或只差台账，见 `gate_base_drift`）
          ⇒ trailer **必须**声称跑过门禁（含「门禁绿」/「全绿」/「seal」这类字样），
          否则 ⇒ 拒（声称与事实不符）；
      (b) `ok==false`，**或**基点是 DRIFT（源码差异 / 非祖先 / 解析不出）⇒ trailer **不许**
          声称"全量门禁绿 + seal"，否则 ⇒ 拒（这就是"伪造门禁结论"的机器版）；
      (c) `--no-gate` / `--commit-only` 形态：trailer 主动披露"没跑门禁"（或"复用已绿的那一趟"）
          ⇒ **放行**，但如实标一行「这一笔**没有**本轮门禁结论」，并且进 `--json` ——
          **不许**把它当成"门禁绿"混过去。

    ★ 返回 `(problems, 如实信息行)`：真绿对得上时信息行为空串。
    """
    line = (gates_line or "").strip()
    ok = payload.get("ok")
    rev = payload.get("rev")
    # ★ 卡 E123 判据 4：与 ③ **同源**（同一个分类器），不再比字面量。
    state, _rows, base_reading = gate_base_drift(
        str(rev or ""), parent_short, sealed_at=str(payload.get("sealed_at") or ""))
    matched = ok is True and not gate_base.category_is_red(state)
    claims_green = bool(GREEN_CLAIM_RE.search(line))
    claims_no_gate = bool(NO_GATE_CLAIM_RE.search(line))
    reading = (f"`Gates:` 原文=「{line}」 / last.json ok={ok!r} rev={rev!r}"
               f"（本提交父提交 {parent_short!r}）")
    # ★ 卡 E137：found 给了就按它判（真祖先 + 差异全归中间提交 ⇒ 不叫伪造）；
    #   没给（或给了 None = 判不出）⇒ 走下面原来的几支。
    if isinstance(found, dict):
        tier = str(found.get("tier") or "")
        if tier == BASIS_DRIFT:
            if claims_green:
                return [], f"这一笔的门禁结论**未复验** —— {found.get('reading')}"
            return [], ("这一笔**没有**本轮门禁结论（门禁基点漂移："
                        f"{found.get('reading')}）")
        if tier == TRUE_MISMATCH and claims_green:
            return [f"{reading} —— last.json 不是这一笔的门禁结论，trailer 却声称"
                    f"「全量门禁绿 + seal」：伪造门禁结论（{found.get('reading')}）"], ""
    if matched and not claims_green:
        return [f"{reading} —— 这一笔真跑过全量门禁，trailer 却没声称跑过"
                f"（缺「门禁绿/全绿/seal」这类字样）：声称与事实不符"], ""
    if not matched and claims_green:
        return [f"{reading} —— last.json 不是这一笔的门禁结论，trailer 却声称"
                f"「全量门禁绿 + seal」：伪造门禁结论"], ""
    if matched:
        if state == LEDGER_ONLY:
            # 台账前移：不是伪造，但**不许**空手说「全量门禁绿」。
            return [], f"这一笔的门禁结论**未复验** —— {base_reading}"
        return [], ""
    why = ("（--no-gate / --commit-only 形态：trailer 已披露，放行）" if claims_no_gate
           else "（trailer 未主动披露「没跑门禁」—— 如实标一行，不当门禁绿）")
    return [], f"这一笔**没有**本轮门禁结论{why}"


def check_branch(branch: str, expected: str) -> tuple[list[str], str]:
    """分支判据分**三态** —— 返回 `(problems, 如实信息行)`。

    ★ 为什么是三态（T-G158）：`git rev-parse --abbrev-ref HEAD` 在**分离头指针**
    （detached HEAD）下返回的就是**字面量** `"HEAD"`，而外包链路的每张卡都在
    `.wt/<卡>` 的 detached worktree 里干活（卡规格明令"不许切分支"）—— 老判据拿它
    跟 `--branch` 默认值（`line/impl-v1`）比，**必然**报「分支不对」，把干净的提交
    判成 4/5 不过。代价不是"多一条噪音"：**复核器（防漏活的工具）自己在说假话，
    说假话的次数一多，人就学会无视它，那它就废了**。

      ① 附着分支且 = `expected`  → **不报**（保持原样）
      ② 附着分支但 ≠ `expected`  → **必须仍报**「分支不对」（★ 判据不许一起废掉）
      ③ detached（`"HEAD"`）且 `expected` 是**默认分支** → **跳过** + 如实记一行

    ★ 口径：detached 时**没有分支可比**，所以**跳过**是对的；**不许**把它当成
    「通过了一个分支检查」。信息行进 `--json`（`branch_note` 字段），机器也读得到。

    ## 为什么不是无条件的跳过（卡内两处口径的对齐）

    卡 §2.1 第三行写"detached → 不报「分支不对」"，而卡 §5 的反证 C 要求**在本树
    （detached）里** `--branch main` **仍报**「分支不对」（原话："这是本卡的核心：
    别把有用的判据一起废掉"）。两条要同时成立，只可能是：**跳过只针对"期望 = 默认
    分支"这个假阳性**（每张外包卡都撞到的那一下）；一旦显式指定了**别的**期望分支
    （`--branch main`），那就是一条**真要求** —— detached 的树**确实不是** `main`，
    照报。否则在 detached 树里这条判据等于被删掉，反证 C 就永远失败。
    `--branch HEAD` 两种读法下都过（`"HEAD" == "HEAD"`），与卡 §7 第 3 条一致。
    """
    if branch == "HEAD" and expected == DEFAULT_BRANCH:
        return [], "分离头指针（detached HEAD）→ 跳过分支判据（没有分支可比，不等于通过了分支检查）"
    if branch != expected:
        return [f"分支不对：现在在 {branch!r}，期望 {expected!r}"], ""
    return [], ""


def classify_changes(
    files: list[str], allow: list[str], derived: tuple[str, ...] | None = None,
) -> tuple[list[str], list[str]]:
    """把这一笔改动的文件分成**两栏**：`(派生物（预期）, 越界)`（卡 210）。

    ★ 判据与 `check_files()` **同源**（同一份 `allow` ∪ `derived`，走同一个 `outside_allow()`）：
      · **派生物（预期）** = 命中 `derived`（默认 `DERIVED_GLOBS`，收口链自己造的）的那些；
      · **越界** = 落在「`allow` ∪ `derived`」**之外**的那些 —— 这些才该报、才该红。
    两栏互斥：派生物先认，越界是剩下的（派生物绝不出现在越界栏里）。
    """
    listed = list(DERIVED_GLOBS if derived is None else derived)
    derived_hits = [f for f in files if not outside_allow([f], listed)]
    outside = outside_allow(files, list(allow) + listed)
    return derived_hits, outside


def check_files(
    files: list[str], *, read_only: bool, allow: list[str],
    derived: tuple[str, ...] | None = None,
) -> list[str]:
    """④ 改动越界没有：只读卡 = 一个被跟踪文件都不许改；否则按白名单。

    ★ 白名单判据走 `pool.review.outside_allow()` —— **唯一实现**（卡 106 把原先三处收敛成一处：
    本函数、`wb_dispatch._outside_allow`、`tf_stage_guard.outside_allow`）。

    ★ 卡 210（T-G320）：放行集 = `allow` ∪ `derived`（默认 `DERIVED_GLOBS`）—— 收口链第 ⑥ 步
      自己造的**派生物是预期内**，不报。**只有**两边都不在的改动才报。
      ★ 这不是"什么都不报"：`allow ∪ derived` 之外的照报、照红（见 `test_rogue_...` 反例）。
      ★ `--read-only` 那一条**不动**（只读卡仍旧一个被跟踪文件都不许改）—— 收口链从不以只读模式调它
        （见 `pool/landing.py::_run_review`，一律传 `--allow`），本卡只治白名单这一侧。
    """
    if read_only:
        return [f"只读卡不许改被跟踪文件，但它改了 {len(files)} 个：{files[:8]}"] if files else []
    if not allow:
        return ["没有给白名单：复核改动范围请加 `--allow <glob>`（或声明 `--read-only`）"]
    _, outside = classify_changes(files, allow, derived)
    return [f"有 {len(outside)} 个改动不在白名单里：{outside[:8]}"] if outside else []


def audit_verdict_from_output(returncode: int, body: str) -> list[str]:
    """① 的判据（从 audit 的退出码与输出判）—— 单独拆出来是为了能**喂假数据测试**
    （同 `scripts/audit_progress.py::parse_task_trailers` 的做法）。

    ★ 卡 159（T-G259 / INV-12）：台账 `[exceptions]` 的豁免**不许当通过** ——
    audit 自己对豁免条目只打 WARN、退出码仍是 0，所以这里必须**另查**「豁免 0 项已知欠账」
    这行读数：只要不是 0，复核就红（反例钉子：tests/test_wb_review.py）。
    """
    problems: list[str] = []
    if returncode != 0:
        tail = [ln for ln in body.splitlines() if ln.strip()][-4:]
        problems.append("audit 没过：" + " | ".join(tail))
        # ★ 卡 E137 判据 4：没过就是没过 —— 不许再叠一条"有豁免项"的二次计数
        #   （两句话指的是同一份读不懂的输出，读者会以为是两个毛病）。
        return problems
    if "豁免 0 项已知欠账" not in body:
        problems.append("audit 里有豁免项（本项目要求 [exceptions] 保持 0）")
    return problems


def audit_verdict(rev: str | None = None) -> tuple[list[str], str]:
    """① audit 真跑一遍（它是唯一能判"证据对不上"的东西）。

    ★ 卡 E137 判据 4：rev 给了就带 --rev <sha> —— 审的必须是**这一笔**的产物；
      不看 HEAD 现在那份（否则"审的是别的提交"这件事会被洗成绿）。
      **判绿只由退出码决定**：正文里出现那四个字不算数（别处也有这句）。
    """
    cmd = [sys.executable, "-X", "utf8", str(ROOT / "scripts" / "audit_progress.py")]
    if rev:
        cmd += ["--rev", str(rev)]
    done = subprocess.run(
        cmd, cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
    )
    body = f"{done.stdout or ''}\n{done.stderr or ''}"
    problems = audit_verdict_from_output(done.returncode, body)
    return problems, ("审计通过 ✅" if done.returncode == 0 else "审计**未通过**")


def fence_dir() -> Path:
    """任务预声明目录 `gates/diag/batch/` —— 卡树里没有就回**主树**那一份。

    ★ 预声明住在**主树**（`gates/diag/*` 被 gitignore，不进 worktree）；复核器常在 `.wt/<卡>`
      的卡树里跑，要能跨回主树。先认本树 `ROOT/gates/diag/batch`（主树自己 / 夹具命中），
      没有再用 `git rev-parse --git-common-dir` 的父目录拼主树批次目录。
    """
    local = ROOT / "gates" / "diag" / "batch"
    if local.is_dir():
        return local
    common = git("rev-parse", "--git-common-dir")
    if common:
        base = Path(common)
        if not base.is_absolute():
            base = (ROOT / base).resolve()
        return base.resolve().parent / "gates" / "diag" / "batch"
    return local


def _rel(path: Path) -> str:
    """尽量给仓库相对路径，给不了（在主树里、不在本树 ROOT 下）就原样。"""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def resolve_domain(card: str, task: str | None) -> tuple[list[str] | None, str]:
    """权威域：**优先栅栏预声明**（`gates/diag/batch/<任务>.toml` 该成员的 `paths`），
    **否则队列**（`docs/workbacklog.toml` 该卡的 `files`）；两个都查不到 → `(None, 原因)`。

    返回 `(域, 来源标签)`：域为 `None` 时第二个元素是**为什么查不到**（直接进拒单理由）。
    """
    fdir = fence_dir()
    if task:
        path = fdir / f"{task}.toml"
        if path.exists():
            got = domain_of_manifest_text(path.read_text(encoding="utf-8"), card)
            if got is not None:
                return got, f"栅栏预声明 {_rel(path)}"
            return None, f"栅栏预声明里没有成员「{card}」：{_rel(path)}"
        return None, f"没有这个任务的预声明：{_rel(path)}"
    # 没给任务号：先在栅栏里扫同名成员（命中恰好一个才敢用；多个 = 歧义，拒）
    hits: list[tuple[Path, list[str]]] = []
    if fdir.is_dir():
        for path in sorted(fdir.glob("*.toml")):
            try:
                got = domain_of_manifest_text(path.read_text(encoding="utf-8"), card)
            except (tomllib.TOMLDecodeError, OSError):
                continue
            if got is not None:
                hits.append((path, got))
    if len(hits) == 1:
        return hits[0][1], f"栅栏预声明 {_rel(hits[0][0])}"
    if len(hits) > 1:
        names = "、".join(_rel(p) for p, _ in hits)
        return None, f"栅栏里有多个同名成员「{card}」（{names}）—— 请用 `--task` 指定任务号"
    bpath = ROOT / "docs" / "workbacklog.toml"
    shard_dir = ROOT / "docs" / "backlog"
    wb = _wb_plan()
    # 卡 E89：分片也算权威域 —— 只有分片、总表还没合出来时不许落到「查不到」。
    if bpath.exists() or (wb is not None and wb.shards_present(shard_dir)):
        try:
            if wb is None:
                backlog = load_backlog(bpath)
            else:
                backlog = wb.load_sharded_backlog(bpath, shard_dir)
        except BacklogError as exc:
            return None, f"队列读不了（{exc}），栅栏里也没有「{card}」"
        found = backlog.by_id().get(card)
        if found is not None and found.files:
            where = _rel(bpath) if bpath.exists() else f"{_rel(shard_dir)}/*.toml"
            return list(found.files), f"队列 {where}（卡 {card}）"
    return None, (f"权威域查不到「{card}」：栅栏预声明与队列都没有"
                  f"（空域会骗过一切守卫，故拒 —— 补声明，或给 `--allow` 并留痕）")


def run_card_mode(args: argparse.Namespace) -> int:
    """第 ⑥ 档：卡树**实际改动** vs **权威域**（本档独立 —— ②③④⑤ 是"针对某笔提交"的判据，
    卡树未提交时不适用）。"""
    actual = changed_paths(git_raw("status", "--porcelain", "-uall", "--no-renames"))
    domain, source = resolve_domain(args.card, args.task)
    hand_typed = False
    if domain is None and args.allow:
        domain = list(args.allow)
        source = "手打白名单 --allow"
        hand_typed = True

    want = {w.replace("\\", "/").strip() for w in args.waive}
    outside: list[str] = []
    waived: list[str] = []
    problems: list[str] = []
    if domain is None:
        problems.append(f"权威域查不到或读不了（{source}）—— 没有权威域就是拒，不许当成"
                        f"「没有约束」")
    else:
        for path in outside_domain(actual, domain):
            if path.replace("\\", "/").strip() in want:
                waived.append(path)
            else:
                outside.append(path)
        for path in outside:
            problems.append(
                f"卡树实际改了域外文件：{path}（卡「{args.card}」的域来自 {source}：{domain}）")

    verdict = {
        "mode": "card", "card": args.card, "task": args.task or "",
        "domain_source": source, "hand_typed": hand_typed,
        "domain": domain, "actual": actual, "outside": outside, "waived": waived,
        "problems": problems,
    }
    if args.json:
        print(json.dumps(verdict, ensure_ascii=False, indent=2))
        return 0 if not problems else 1

    print(f"=== 卡树实际改动 vs 权威域（卡 {args.card}"
          + (f" · 任务 {args.task}" if args.task else "") + "）===")
    print(f"  域来源：{source}")
    if hand_typed:
        print("  ★ 这一趟用的是**手打白名单（--allow）**，不是权威域 —— 只在没有权威域时才允许")
    print(f"  实际改动 {len(actual)} 个：" + ("、".join(actual[:8]) or "（没有改动）"))
    print("  豁免（留痕）：" + ("、".join(waived) if waived else "（无）"))
    if problems:
        print(f"\n[FAIL] {len(problems)} 条不过 —— **有域外改动**：")
        for item in problems:
            print(f"  · {item}")
        return 1
    print("\n[OK ] 卡树实际改动全部落在权威域内（域外 0 个）")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="主控复核：这一笔提交算不算数")
    parser.add_argument("--rev", default="HEAD", help="要复核的提交（默认 HEAD）")
    parser.add_argument("--read-only", action="store_true", help="只读卡：一个被跟踪文件都不许改")
    parser.add_argument("--allow", action="append", default=[], help="允许改动的 glob（可重复）")
    parser.add_argument("--branch", default=DEFAULT_BRANCH, help="期望所在分支")
    parser.add_argument("--dirty-ok", action="store_true", help="允许工作区有未提交改动")
    parser.add_argument("--card", help="★ 第 ⑥ 档：卡号 / 栅栏成员号 —— 用它的**权威域**与卡树"
                                      "实际改动（含未跟踪）比对，域外即拒并点名")
    parser.add_argument("--task", help="任务号（给栅栏成员定位；不给则先在栅栏里扫同名成员、"
                                       "再查队列）")
    parser.add_argument("--waive", action="append", default=[],
                        help="显式豁免某个域外文件（可重复，留痕：打印 + 进 --json）")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.card:
        return run_card_mode(args)

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
    try:
        audit_problems, audit_line = audit_verdict(sha)
    except TypeError:
        # 历史钉子把 audit_verdict 替成零参 lambda（tests/test_wb_review*.py）——
        # 替身也是"说清了这一笔"的一种，退回零参形态即可，别把替身打红。
        audit_problems, audit_line = audit_verdict()
    problems += audit_problems
    trailer_problems, trailers = check_trailers(body)
    problems += trailer_problems
    try:
        payload = json.loads(git("show", f"{sha}:gates/last.json"))
    except json.JSONDecodeError:
        payload = {}
        problems.append("这一笔里没有 gates/last.json（门禁产物没跟着提交）")
    gate_notes: list[str] = []
    problems += check_gate_evidence(payload, parent, notes=gate_notes)
    # ★ 卡 E137 判据 3：封存树 vs 提交树到底差在哪 —— **只算一次**，③″ 与 ⓖ 共用；
    #   判不出（旧笔 / 合成 sha / 对象库缺 tree）时回 None，两个调用点各自退回旧口径。
    basis = basis_check(payload, sha, parent, files)
    gate_base_note = "；".join(gate_notes)
    full_gate_problems, full_gate_note, full_gate_reading = check_full_gate_run(payload)
    problems += full_gate_problems
    seal_problems, seal_note, seal_reading = check_seal_tree(payload, sha, found=basis)
    problems += seal_problems
    truth_problems, truth_note = check_gates_trailer_truth(
        trailers.get("Gates") or "", payload, parent, found=basis,
    )
    problems += truth_problems
    problems += check_files(files, read_only=args.read_only, allow=args.allow)
    # ★ 卡 210：报告分两栏 —— 「派生物（预期）」与「越界」（只读卡的判据不同，不列这两栏）。
    derived_files, outside_files = (
        ([], []) if args.read_only else classify_changes(files, args.allow))
    branch_problems, branch_note = check_branch(branch, args.branch)
    problems += branch_problems
    if dirty and not args.dirty_ok:
        problems.append(f"工作区有没提交的改动（{len(dirty)} 个）：{dirty[:5]}")

    verdict = {
        "rev": sha, "parent": parent, "branch": branch, "branch_note": branch_note,
        "files": files, "trailers": trailers, "audit": audit_line,
        "derived_files": derived_files, "outside_files": outside_files,
        "gates_ok": payload.get("ok"), "gates_rev": payload.get("rev"),
        "gates_trailer": trailers.get("Gates"),
        "gate_base_drift_note": gate_base_note,
        "gates_trailer_note": truth_note,
        "no_round_gate_verdict": bool(truth_note),
        "full_gate_reading": full_gate_reading,
        "full_gate_note": full_gate_note,
        "full_gate_problems": full_gate_problems,
        "seal_tree_reading": seal_reading,
        "seal_tree_note": seal_note,
        "seal_tree_problems": seal_problems,
        # ★ 卡 E137 判据 3：基点漂移的留痕。**非漂移也必须有这个键、值为 null**
        #   （缺键 = 读的人分不清"没漂"和"没判"）。
        "waived_basis": (basis or {}).get("record"),
        "problems": problems,
    }
    if args.json:
        print(json.dumps(verdict, ensure_ascii=False, indent=2))
        return 0 if not problems else 1

    print(f"=== 复核 {sha}（父提交 {parent}，分支 {branch}）===")
    if branch_note:
        print(f"  ★ 分支判据：{branch_note}")
    print(f"  ① audit：{audit_line}")
    print(f"  ② trailer：{trailers.get('Task', '(缺)')}")
    print(f"  ③ 门禁：ok={payload.get('ok')} rev={payload.get('rev')}"
          f"（这一笔的父提交 {parent}）+ {len(payload.get('gates', []))} 道门")
    if gate_base_note:
        print(f"     ★ 门禁基点（不判红，但结论未复验）：{gate_base_note}")
    print(f"  ③′ 全量门禁（门数 / affected 标记）：{full_gate_reading}")
    if full_gate_note:
        print(f"     ★ 标注（不判红）：{full_gate_note}")
    print(f"  ③″ 封存树 vs 提交树：{seal_reading}")
    waived = (basis or {}).get("record")
    if isinstance(waived, dict):
        print(f"     ★ 基点漂移（未复验）：门禁跑在 {waived.get('gates_rev')}，"
              f"父提交已前进到 {waived.get('parent')}（中间 {waived.get('middle_commits')} 笔），"
              f"差异 {len(waived.get('diff_paths') or [])} 条全由中间提交带入；"
              "门禁结论**未经复验**")
        print(f"       只落 {'/'.join(waived.get('profiles_affected') or []) or '?'} 档；"
              f"差异路径：{(waived.get('diff_paths') or [])[:6]}")
    elif isinstance(basis, dict) and str(basis.get("tier")) == TRUE_MISMATCH:
        print(f"     ★ 差异不能归给中间提交（{basis.get('reading')}）")
    if seal_note:
        print(f"     ★ 标注（不判红）：{seal_note}")
    print(f"  ⓖ `Gates:` 真伪：{truth_note or '与 gates/last.json 对得上（真绿，已核）'}")
    print(f"  ④ 这一笔改了 {len(files)} 个文件：" + ("、".join(files[:6]) or "（一个都没改）"))
    if not args.read_only:
        print("     ★ 派生物（预期）：" + ("、".join(derived_files) or "（无）"))
        print("     ★ 越界（allow ∪ 派生物之外 —— 该栏应为空）："
              + ("、".join(outside_files) or "（无）"))
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
