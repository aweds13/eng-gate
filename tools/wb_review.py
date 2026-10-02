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

   ★ 来路：卡 140 自己发现的后门 —— `tools/wb_verify.py` 查 `EXPECT_GATES` **会**拦"部分跑的
     `last.json`"，但 `wb_review.py` 原来只查 `ok` / `rev` / 每门 `exit_code`，**不查门数** ⇒
     若有人把 `--affected` 那一趟的 `last.json` 提交上去，**复核主链可能不拦**（正是本仓最该防的
     "看着绿其实没查全"）。判据见 `check_full_gate_run()`：① 门数 = 该仓**当前应有**的门数
     （从 `scripts/run_gates.py` 的 `build_jobs` **现读** —— ★ **不写死 17、不造第二份门表**）；
     ② `last.json` 里出现 `affected` 块（`--affected` 部分跑的记账）⇒ 判红并贴原文。
   ★ **只对"门禁自己写出来的产物"判红**（`tree_scope` 是 `run_gates.py` 必写的字段）：合成夹具
     （无 `tree_scope`）**只标注不判红** —— 详见 `check_full_gate_run()` 的 docstring。

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
import re
import subprocess
import sys
from pathlib import Path

import tomllib
from pool.plan import BacklogError, load_backlog
from pool.review import changed_paths, domain_of_manifest_text, outside_allow, outside_domain

ROOT = Path(__file__).resolve().parent.parent
TASK_RE = re.compile(r"^Task:\s*(\S+)\s*$", re.M)
#: `Gates:` trailer 里声称"跑过门禁**且绿**"的字样 —— 真绿那一笔**必须**含其中之一（卡 133）。
GREEN_CLAIM_RE = re.compile(r"门禁绿|全绿|seal")
#: 声称"这一笔没跑门禁 / 复用已绿的旧结论"的字样（`--no-gate` / `--commit-only` 的**主动披露**）。
NO_GATE_CLAIM_RE = re.compile(r"没跑|未跑|no-gate|commit-only|复用|跳过")
#: 期望分支的默认值（就是集成分支）。`check_branch()` 的 detached 跳过只对它生效（T-G158）。
DEFAULT_BRANCH = "line/impl-v1"


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


def check_gates_trailer_truth(
    gates_line: str, payload: dict, parent_short: str
) -> tuple[list[str], str]:
    """`Gates:` trailer 的**真伪**（卡 133 · T-G230，治外部审查 GLM-5.3「三.2」）。

    ★ **分工（别把这条做成第二份真源）**：`scripts/audit_progress.py` 只管 `Gates:`
    trailer **在不在**（存在性判据，保留）；**真伪**归这里 —— 拿 trailer 的内容与
    `gates/last.json` 的**实际结论**对账。

    判据（照卡写，别自己发明方向）：
      (a) `last.json.ok==true` 且 `rev==父提交`（这一笔真跑过全量门禁）⇒ trailer **必须**
          声称跑过门禁（含「门禁绿」/「全绿」/「seal」这类字样），否则 ⇒ 拒（声称与事实不符）；
      (b) `ok==false`，**或** `rev!=父提交` ⇒ trailer **不许**声称"全量门禁绿 + seal"，
          否则 ⇒ 拒（这就是"伪造门禁结论"的机器版）；
      (c) `--no-gate` / `--commit-only` 形态：trailer 主动披露"没跑门禁"（或"复用已绿的那一趟"）
          ⇒ **放行**，但如实标一行「这一笔**没有**本轮门禁结论」，并且进 `--json` ——
          **不许**把它当成"门禁绿"混过去。

    ★ 返回 `(problems, 如实信息行)`：真绿对得上时信息行为空串。
    """
    line = (gates_line or "").strip()
    ok = payload.get("ok")
    rev = payload.get("rev")
    matched = ok is True and rev == parent_short
    claims_green = bool(GREEN_CLAIM_RE.search(line))
    claims_no_gate = bool(NO_GATE_CLAIM_RE.search(line))
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


def check_files(files: list[str], *, read_only: bool, allow: list[str]) -> list[str]:
    """④ 改动越界没有：只读卡 = 一个被跟踪文件都不许改；否则按白名单。

    ★ 白名单判据走 `pool.review.outside_allow()` —— **唯一实现**（卡 106 把原先三处收敛成一处：
    本函数、`wb_dispatch._outside_allow`、`tf_stage_guard.outside_allow`）。
    """
    if read_only:
        return [f"只读卡不许改被跟踪文件，但它改了 {len(files)} 个：{files[:8]}"] if files else []
    if not allow:
        return ["没有给白名单：复核改动范围请加 `--allow <glob>`（或声明 `--read-only`）"]
    outside = outside_allow(files, allow)
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
    if bpath.exists():
        try:
            backlog = load_backlog(bpath)
        except BacklogError as exc:
            return None, f"队列读不了（{exc}），栅栏里也没有「{card}」"
        found = backlog.by_id().get(card)
        if found is not None and found.files:
            return list(found.files), f"队列 {_rel(bpath)}（卡 {card}）"
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
    full_gate_problems, full_gate_note, full_gate_reading = check_full_gate_run(payload)
    problems += full_gate_problems
    truth_problems, truth_note = check_gates_trailer_truth(
        trailers.get("Gates") or "", payload, parent,
    )
    problems += truth_problems
    problems += check_files(files, read_only=args.read_only, allow=args.allow)
    branch_problems, branch_note = check_branch(branch, args.branch)
    problems += branch_problems
    if dirty and not args.dirty_ok:
        problems.append(f"工作区有没提交的改动（{len(dirty)} 个）：{dirty[:5]}")

    verdict = {
        "rev": sha, "parent": parent, "branch": branch, "branch_note": branch_note,
        "files": files, "trailers": trailers, "audit": audit_line,
        "gates_ok": payload.get("ok"), "gates_rev": payload.get("rev"),
        "gates_trailer": trailers.get("Gates"),
        "gates_trailer_note": truth_note,
        "no_round_gate_verdict": bool(truth_note),
        "full_gate_reading": full_gate_reading,
        "full_gate_note": full_gate_note,
        "full_gate_problems": full_gate_problems,
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
    print(f"  ③′ 全量门禁（门数 / affected 标记）：{full_gate_reading}")
    if full_gate_note:
        print(f"     ★ 标注（不判红）：{full_gate_note}")
    print(f"  ⓖ `Gates:` 真伪：{truth_note or '与 gates/last.json 对得上（真绿，已核）'}")
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
