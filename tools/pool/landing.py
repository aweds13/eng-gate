r"""主控的通用集成器（实现层）：把一张外包卡（工人已在某棵树里改好、未提交）收成一笔提交。

★ 已进 git（卡 139 · `T-G237`）—— **权威副本就是本文件**（`tools/pool/landing.py`，
  模块 `pool.landing`）。命令行壳是 `tools/wb_land.py`；旧的 `gates/diag/_integrate.py`
  保留成临时转发壳（免得旧调用点当夜断掉）。
★ **本文件由 `gates/diag/_integrate.py` 逐字搬来**（卡 139），除下面三处外**行为一字不变**
  （七步链顺序、每步打印与退出码、`--card/--batch` 恰好给一个、`--tree/--task/…` 参数语义、
  fail-fast 钉子、`atexit` 还锁、`--allow` 目录展开、计划外暂存停手、`DOCS/GATES` 自动补、
  三个片段自动补）：
  ① `ROOT` 仍写 `Path(__file__).resolve().parents[2]` —— 旧位置 `gates/diag/` 与本位置
     `tools/pool/` **都是上两级到仓库根**，所以这一行**搬过来不用改**（已核对）；
  ② 第②步调用的文书生成器从 `gates/diag/_stage_card.py` 改指 **`tools/wb_stage_card.py`**
     （那是它搬进 git 后的新家；旧的 scratch 壳转发到同一份实现）；
  ③ 只**按 ruff 的 line-length（100 列，CJK 算 2）折行** —— 折行只在**源码**层面，
     打印文本、退出码、判据一个字符都没动（`print` 的折行一律用隐式字符串拼接）。
另为可测性把三处**纯搬运**抽成模块级函数（`expand_allow` / `staged_and_extra` /
`release_lock`）—— 它们与旧内联代码逐字等价，只是搬出来了。

做什么（顺序固定，任一步失败就停，**绝不**带着红门禁提交）：
  ⓪ 回退派生物（卡 150：上一趟残留的共享文档/门禁产物/本台片段 → HEAD 干净态；
     幂等重跑 —— `--no-reset` 可关，`--commit-only` 一律不回退）
  ① 把卡树迁到**当时的主树 HEAD**（工人只新增/改自己的文件 → untracked 不会冲突）
  ② 生成文档件（台账条目 / changelog / 交接 CHECKPOINT）—— 复用 `tools/wb_stage_card.py`
  ③ tools/sync_counts.py
  ③′ fail-fast 钉子（卡规格都要在索引里）→ ③″ 快门禁预检（卡 226/236：run_gates.py
     --fast，十几秒，不落盘；★ 次序钉死：参数互斥检查最先（非法退 6，不碰预检）
     → ③′ → ③″ → ④ 全量；预检红退 7，`--no-preflight` 可跳过）
  ④ 拿门禁锁（段由 --port-base 给）→ 跑门禁（★ 带 1800s 硬超时）→ 红了就 release + 退出
     ★ 卡 184：`--affected` / `--changed-from` 透传给 `run_gates.py`（默认关，给了才少跑）；
     三条强制全量（碰 scripts/**/tools/**/gates/** / 空计划 / 今天没跑过全量）任何一条命中就跑全量
  ⑤′ 白名单核对（卡的文件 + 文档三件 + gates/last.json + gates/reuse.json）
     → 落地即翻 status（卡 204 单卡 / 卡 228 批成员）→ 显式 git add
     ★ 卡 228（T-G344）：翻账/暂存必须排在封存**之前** —— 封存算的才是最终树
  ⑤ --seal（封存算最终树）→ ⑤″ 兜底重封存（幂等，不重跑门禁）→ 重暂存 GATES
     （★ 全量那一趟落盘 gates/diag/_daily_full.json：今天跑过全量没有，机器可判）
  ⑥ commit（四 trailer；★ 增量那一趟 trailer 写「非全量」字样）
  ⑦ audit_progress.py → 释放锁 → 主树 ff 合流
  ⑧ 复核落盘（卡 184 · 追加三）：wb_review.py --rev <新提交> --json → gates/review/<task>.json
     ★ 异步、不挡提交；但 wb_task.py landed 之前必须存在一条复核记录（机器判据）

用法：
  python -X utf8 tools/wb_land.py --card 096 --tree .wt/mech2 --task T-G191 \
      --title "机器替代 ③+④：台账归类建议器 + 卡/样板生成" --type feat --group ENGINEERING \
      --evidence tools/tf_group.py tests/test_tf_group.py \
      --allow tools/tf_group.py tests/test_tf_group.py \
      --port-base 9034 --refs "T-G182"
  # 卡 184：增量门禁（默认全量；只在显式给开关时才少跑，三条强制全量照咬）
  python -X utf8 tools/wb_land.py --card 184 --tree .wt/incgate --task T-G284 \
      --title "收口链支持增量门禁 + 三条强制全量" --evidence tools/pool/landing.py \
      --allow tools/pool/landing.py tools/wb_land.py tests/test_wb_land.py \
      --affected tools/pool/landing.py  # ★ 默认关；给了才少跑，碰 tools/** 会强制全量"""
from __future__ import annotations

import argparse
import contextlib
import datetime
import importlib.util
import json
import os
import pathlib
import re
import subprocess
import sys
import threading
import time

# ★ 2026-10-02：ROOT 原来是硬编码绝对路径（换机器即碎）。本位置 `tools/pool/` 上两级 = 仓库根，
#   与旧位置 `gates/diag/` 的 `parents[2]` 结果一致 ⇒ 这一行搬过来不用改（已核对）。
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from pool.snapshot import take_snapshot  # noqa: E402 —— 卡 192：快照挂 ref（唯一实现）

TEXT = ROOT / "gates" / "diag" / "_text_{task}.md"
DOCS = ("docs/traceability.toml", "docs/changelog.md", "复盘/交接-重构进度.md")
GATES = ("gates/last.json", "gates/reuse.json")

#: 文书生成器的**新家**：旧的是 `gates/diag/_stage_card.py`（scratch，已留转发壳）。
STAGE_CARD = ROOT / "tools" / "wb_stage_card.py"

#: rebase 冲突里**可以自动解决**的那批：三个**派生**共享文档（按片段重汇总即可）
#: + 两个门禁产物（取本笔的）。
#: ★ 别的任何文件冲突一律**停手**（代码冲突永远人来判）。
#: 见 `gates/diag/_todo_pending.md` 坑 32 / 33。
DERIVED = DOCS
GATE_ARTIFACTS = GATES

#: 卡 150（`T-G250`）：⓪ 要回退的**本台账号三个片段**（`{task}` 占位，
#: 与 ⑥ 自动补片段是同一组路径）。
RESET_FRAGMENTS = ("docs/changelog.d/{task}.md", "docs/traceability.d/{task}.toml",
                   "复盘/交接.d/{task}.md")


def reset_derived(wt: pathlib.Path, task: str) -> None:
    """⓪ 把上一趟残留的派生物回退到 HEAD 干净态（卡 150 · 幂等重跑）。

    回退名单 = 三个派生共享文档（DOCS）+ 两个门禁产物（GATES）+ 本台的三个片段。
    ★ 名单里**只有**派生物/记账产物，**绝不**含白名单里的源文件（那是要提交的东西）。
      每一样都打印「回退了什么 + 是否真的变过」，不许静默。
    · 在 HEAD 里且有改动 ⇒ `git checkout HEAD -- <路径>`；本来就干净 ⇒ 只报一句；
    · 不在 HEAD 里（新文件残留）⇒ 删掉（进了暂存区就 `git rm -f`，否则直接删）；
    · 拿不到 HEAD（不是 git 仓 / 空仓）⇒ **警告并跳过**（幂等是加分项，不是新闸）；
    · 单个文件回退失败 ⇒ 也警告并继续。
    """
    if not wt.is_dir():
        print(f"  ★ 回退派生物：卡树 {wt} 不存在 ⇒ 警告并跳过，不因此停手")
        return
    r = run(["git", "rev-parse", "--verify", "HEAD"], cwd=wt, check=False)
    if r.returncode != 0:
        first_err = ((r.stderr or "").strip().splitlines() or ["不是 git 仓"])[-1]
        print(f"  ★ 回退派生物：**拿不到 HEAD**（{first_err[:120]}）⇒ 警告并跳过，不因此停手")
        return
    for rel in (*DOCS, *GATES, *(f.format(task=task) for f in RESET_FRAGMENTS)):
        st = run(["git", "-c", "core.quotepath=false", "status", "--porcelain", "--", rel],
                 cwd=wt, check=False)
        if not [x for x in (st.stdout or "").splitlines() if x.strip()]:
            print(f"  · {rel} —— 本来就干净，不用回退")
            continue
        if run(["git", "cat-file", "-e", f"HEAD:{rel}"], cwd=wt, check=False).returncode == 0:
            rc = run(["git", "checkout", "HEAD", "--", rel], cwd=wt, check=False).returncode
            print(f"  · {rel} —— 有改动 ⇒ "
                  + ("**已回到 HEAD 干净态**" if rc == 0
                     else f"★ 回退失败（checkout 退 {rc}）⇒ 警告并继续"))
            continue
        if run(["git", "ls-files", "--error-unmatch", "--", rel],
               cwd=wt, check=False).returncode == 0:
            run(["git", "rm", "-f", "-q", "--", rel], cwd=wt, check=False)
        else:
            (wt / rel).unlink(missing_ok=True)
        print(f"  · {rel} —— HEAD 里没有（新文件残留）⇒ **已删除**")


def is_ancestor(commit: str, maybe_descendant: str, cwd: pathlib.Path) -> bool:
    """`commit` 是不是 `maybe_descendant` 的祖先（用来判"checkout 会不会抹掉已提交的改动"）。"""
    r = subprocess.run(["git", "merge-base", "--is-ancestor", commit, maybe_descendant],
                       cwd=str(cwd), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode == 0


def resolve_derived_conflicts(wt: pathlib.Path) -> tuple[bool, list[str]]:
    """rebase 冲突里**只有派生物**时自动解决；返回 `(解决了吗, 解决不了的原因)`。

    解法（2026-10-02 卡 113 那次真冲突逼出来的）：
      · 三个派生共享文档 ⇒ 取**基线版本**（rebase 里 `--ours` 就是被 rebase 到的那个 HEAD，
        也就是主树那版），再跑一遍 `tools/sync_docs.py` **按片段重汇总**把本笔那一节插回去
        （汇总器只插入、幂等）；
      · `gates/last.json` / `gates/reuse.json` ⇒ 取**本笔的**（`--theirs`）：那是这一笔门禁的产物。
    """
    conflicted = [x for x in git("diff", "--name-only", "--diff-filter=U", cwd=wt).splitlines()
                  if x.strip()]
    if not conflicted:
        return False, ["冲突表是空的，说不清发生了什么"]
    extra = [x for x in conflicted if x not in DERIVED and x not in GATE_ARTIFACTS]
    if extra:
        return False, [f"冲突里有**非派生物**（必须人来判）：{extra}"]
    for path in DERIVED:
        if path in conflicted:
            run(["git", "checkout", "--ours", "--", path], cwd=wt)
    for path in GATE_ARTIFACTS:
        if path in conflicted:
            run(["git", "checkout", "--theirs", "--", path], cwd=wt)
    r = run([sys.executable, "-X", "utf8", "tools/sync_docs.py"], cwd=wt, check=False)
    print("   ↳ 按片段重汇总：", ((r.stdout or "") + (r.stderr or "")).strip().splitlines()[-1:])
    chk = run([sys.executable, "-X", "utf8", "tools/sync_docs.py", "--check"], cwd=wt, check=False)
    print("   ↳ 重汇总后 --check 退出码 =", chk.returncode)
    if chk.returncode != 0:
        return False, ["重汇总之后 `sync_docs.py --check` 仍不通过"]
    add = [p for p in (*DERIVED, *GATE_ARTIFACTS) if p in conflicted]
    run(["git", "add", "--", *add], cwd=wt)
    return True, add


def run(cmd: list[str], cwd: pathlib.Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", check=False)
    if check and r.returncode != 0:
        print(f"★ 命令失败（{r.returncode}）：{' '.join(cmd[:6])} …")
        print((r.stdout or "")[-2000:])
        print((r.stderr or "")[-1000:])
        sys.exit(2)
    return r


def git(*args: str, cwd: pathlib.Path | None = None, check: bool = True) -> str:
    r = run(["git", "-c", "core.quotepath=false", *args], cwd or ROOT, check=check)
    return (r.stdout or "").strip()


def changelog_body(text: pathlib.Path) -> str:
    raw = text.read_text(encoding="utf-8")
    sec = raw.split("=== changelog ===")[1].split("=== checkpoint ===")[0].strip("\n")
    lines = sec.splitlines()[1:]          # 去掉 "## …" 那一行（标题进 commit 首行）
    return "\n".join(lines).strip()


def effective_refs(task: str, refs: str) -> str:
    r"""`Refs:` 这一行的**实际取值**（卡 E38 · T-AG492）。

    病（一天里踩了四次）：单卡笔不给 `--refs` ⇒ 消息里**没有** `Refs:` 行 ⇒
    `wb_verify` 报 `trailer 不是各一条：['Refs']`，每次都要 `git commit --amend` 手补。

    口径（**二者选一，写死在这里**）：落地链不放开 `wb_verify` 的"四行各一条"（那是提交骨架的
    硬判据），改成**单卡笔默认写本笔台账号** —— 没给 `--refs` 就退回 `task`；给了就原样用。
    这样"单卡笔不带 `--refs`"的实际产物也是四行齐，`wb_verify` 与落地链**同一口径**。
    """
    return (refs or "").strip() or task.strip()


def expand_allow(wt: pathlib.Path, allow: list[str]) -> list[str]:
    """把 `--allow` 里的**目录**用 `git ls-files` 展开；文件原样留着。

    ★ 别用 os.walk（它不看 .gitignore，会把 `__pycache__/*.pyc` 也收进来 ⇒ git add 直接报错）。
      用 git 自己列"已跟踪 + 未跟踪但未被忽略"的文件。
    （旧脚本里这段内联在 `main`；卡 139 搬出来只为可测，逐字等价。）
    """
    out: list[str] = []
    for _a in allow:
        _p = wt / _a
        if _p.is_dir():
            _listed = git("ls-files", "-c", "-o", "--exclude-standard", "--", _a, cwd=wt)
            out.extend([x for x in _listed.splitlines() if x.strip()])
        else:
            out.append(_a)
    return out


def staged_and_extra(wt: pathlib.Path, allow: list[str]) -> tuple[list[str], list[str]]:
    """`git add -- <allow>` 之后取暂存清单 + **计划外**那些（旧脚本里内联在 `main`；逐字等价）。"""
    run(["git", "add", "--", *allow], cwd=wt)
    staged = [x for x in git("diff", "--cached", "--name-only", cwd=wt).splitlines() if x.strip()]
    extra = [f for f in staged if f not in allow]
    return staged, extra


def release_lock(lock_label: str, wt: pathlib.Path, env: dict) -> None:
    """释放门禁锁（任何退出路径都调它 —— 无锁时 `release` 是空操作、退 0）。"""
    with contextlib.suppress(Exception):
        subprocess.run(
            [sys.executable, "-X", "utf8", "gates/diag/gate_lock.py",
             "release", "--card", lock_label],
            cwd=str(wt), env={**os.environ, **env},
            capture_output=True, text=True,
        )


def acquire_gate_lock(lock_label: str, wt: pathlib.Path, env: dict, *,
                      wait: int = 5400) -> int:
    r"""④ 拿门禁锁 —— **流式**：`gate_lock.py` 打印的每一行都出现在落地日志里。

    ★ 卡 E16（T-AG467）的缺陷现场：原来是 `subprocess.run(capture_output=True)` 再
      `print(stdout[-400:])` ⇒ `gate_lock` 每 60s 打的 `[锁] 等门禁锁 Ns…` 全被吞在返回值里，
      落地日志从「起跑」直接空白 28 分钟，人只能当它卡死。
    ★ 现在 `Popen` + 逐行转发到**本进程的 stdout**（落地日志就是它）⇒ 等锁时**有进度**。
      ★ 注意这是**同步阻塞**的流式读（不是开线程）：「拿锁」这一步本来就要等出结果；
        超时判据在 `gate_lock` 自己（`--wait`），本函数不另设超时（免得造第二份判据）。
    ★ 返回值 = `gate_lock acquire` 的退出码（0 = 拿到；3 = 等超时）。
    """
    cmd = [sys.executable, "-X", "utf8", "gates/diag/gate_lock.py",
           "acquire", "--card", lock_label, "--wait", str(wait)]
    proc = subprocess.Popen(
        cmd, cwd=str(wt), env={**os.environ, **env},
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert proc.stdout is not None
    for line in proc.stdout:
        print(line.rstrip("\r\n"), flush=True)
    return proc.wait()


def _gate_lock_module():
    r"""按**路径**加载卡树里的 `gates/diag/gate_lock.py`（拿锁/看锁同一份实现）。

    不 `import gate_lock`：`gates/diag/` 不是包，而且铁律 24 要求 `python -P` 跑它
    （同目录里的同名脚本会顶掉标准库）。读不到 / 不是那一份（缺读数接口）⇒ `None`。
    """
    p = ROOT / "gates" / "diag" / "gate_lock.py"
    if not p.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location("_wb_gate_lock_for_readout", p)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except SystemExit:
        # ★ 沙箱/桩里的 `gate_lock.py` 可能在**import 期**就 `sys.exit`（它会跑一遍全文件）
        #   —— 那不是"读锁失败"，是"这不是那一份实现"⇒ 老实说 not verified，不许把
        #   体检整趟带退出（真踩过：桩一 import 就把 --preflight 变成 `stub-gate_lock …`）。
        return None
    except Exception:      # noqa: BLE001 —— 读数失败**不许**挡住体检（那是只读附加信息）
        return None
    need = ("all_lock_paths", "_read", "_age", "_lease_of", "_pid_alive",
            "liveness_text", "DEFAULT_STALE_AFTER")
    return mod if all(hasattr(mod, n) for n in need) else None


def lock_readout() -> list[str]:
    r"""卡 E16 · 体检**先说锁**：本端口段（以及全局各段）当前锁的读数。

    每条打印 `card / pid / 已持有秒数 / 持有者进程是否还活着 / 剩余租约`；
    判断不了就明说 `not verified`（**不许**猜、也不许把「读不到」当成「没锁」）。
    ★ 只读：不建锁、不清锁、不写任何文件（`all_lock_paths` 只 glob）。
    """
    mod = _gate_lock_module()
    if mod is None:
        return ["[锁] 本树没有可用的 gates/diag/gate_lock.py ⇒ 锁状态 not verified"]
    try:
        paths = mod.all_lock_paths()
    except Exception as exc:      # noqa: BLE001
        return [f"[锁] 读锁目录失败（{type(exc).__name__}: {exc}）⇒ 锁状态 not verified"]
    base = os.environ.get("TF_GATE_PORT_BASE", "").strip() or "(默认段)"
    if not paths:
        return [f"[锁] 本段 base={base}：空着（没有任何段的锁）"]
    lines: list[str] = []
    for p in paths:
        info = mod._read(p)
        age = int(mod._age(p))
        lease = int(mod._lease_of(p, info, mod.DEFAULT_STALE_AFTER))
        mine = "★ 本段" if str(info.get("base")) == base else ""
        lines.append(
            f"[锁] 段 base={info.get('base')} 文件={p.name}{mine}："
            f"card={info.get('card')} pid={info.get('pid')}"
            f" 已持有 {age}s / 剩余租约 {lease - age}s"
            f" / 持有者进程 {mod.liveness_text(info)}")
    lines.append(f"[锁] 全局：{len(paths)} 把锁文件（租约内的才算占名额；"
                 f"上限看 TF_GATE_MAX_CONCURRENT，默认 2）")
    return lines


# ---------------------------------------------------------------- 卡 204（T-G311）：落地即翻 status
def flip_card_status(wt: pathlib.Path, card_id: str | None, task: str, *,
                     require_task_match: bool = True) -> bool:
    r"""把队列里那张卡的 `status` 翻成 `done`（当且仅当这是它自己的落地）。

    判据（安全边界）：队列 `docs/workbacklog.toml` 里 `card_id` 那张卡的
    `task` 字段 == 给的 `task` ⇒ 这是**这张卡自己的落地** ⇒ 翻 `status → done`。

    · `card_id is None` ⇒ 遍历所有卡，找 `task` 匹配的那张。
    · ★ 卡 228（T-G344）：`require_task_match=False` 时**跳过**「task 字段比对」
      这一条 —— 只给**批成员翻账**用：批模式的 `--task` 是**批台账号**（T-G340），
      永远比不中成员卡自己的 task（T-G333…）；批成员的「是不是它自己的落地」
      改由 `flip_batch_member_statuses` 用「产物 ∩ 暂存清单」判定（见那边）。
      **单卡路径（`--card`）保持默认 `True`，行为一字不变。**
    · ★ **为什么不能只看 `--card`**：本仓的登记/收尾提交也用 `--card <号>`
      （现场：登记卡 203 那笔用 `--card 203 --task T-G307`，而卡的号是 `T-G308`）
      ⇒ 只看 `--card` 会把**还没干的卡标成 done**。`--task == 卡的 task` 这条
      把两者天然分开。
    · ★ **CRLF 感知**：那份文件是纯 CRLF；用 `\n` 匹配会静默不生效
      （主控本轮真踩过）⇒ 按字节读写、按原始行尾分割。
    · 找不到卡 / 找不到 `status` 行 / 那行已经是 `done` / `task` 不匹配
      ⇒ 打印一句并**跳过**（不许崩、不许猜、不许新建卡）。

    返回 `True` ⇒ 翻了（调用方应把 `docs/workbacklog.toml` 加进 `allow`）。
    返回 `False` ⇒ 没翻。
    """
    backlog_rel = "docs/workbacklog.toml"
    backlog_path = wt / backlog_rel
    if not backlog_path.is_file():
        print(f"  [队列] 找不到 {backlog_rel} ⇒ 跳过翻 status")
        return False
    raw = backlog_path.read_bytes()
    sep = b"\r\n" if b"\r\n" in raw else b"\n"
    lines = raw.split(sep)
    # ★ 卡 E1（T-AG443）：逐块解析抽成 `_scan_blocks` —— `--preflight` 的
    #   「队列卡块有 status 行」用的是**同一套**口径（不许复制第二份，卡 E1 判据 5）。
    for _start, _end, fields in _scan_blocks(lines):
        cid_val = fields["id"]
        task_val = fields["task"]
        is_target = ((cid_val == card_id) if card_id is not None
                     else (task_val == task))
        if not is_target:
            continue
        if require_task_match and task_val != task:
            print(f"  [队列] 卡 {cid_val}：--task={task} ≠ 卡.task={task_val}"
                  f"（登记型提交）⇒ 不翻 status")
            return False
        status_idx = fields["status_idx"]
        status_val = fields["status"]
        if status_idx is None or status_val is None:
            print(f"  [队列] 卡 {cid_val}：找不到 status 行 ⇒ 跳过")
            return False
        if status_val == "done":
            print(f"  [队列] 卡 {cid_val}：已是 done ⇒ 跳过")
            return False
        old_line = lines[status_idx].decode("utf-8", "replace")
        new_line = re.sub(r'(status\s*=\s*)"[^"]*"', r'\1"done"', old_line)
        lines[status_idx] = new_line.encode("utf-8")
        backlog_path.write_bytes(sep.join(lines))
        print(f"  [队列] 卡 {cid_val}：{status_val} → done"
              f"（这一笔是它的落地）")
        return True
    if card_id is not None:
        print(f"  [队列] 找不到卡 {card_id} ⇒ 跳过翻 status")
    else:
        print(f"  [队列] 找不到 task={task} 的卡 ⇒ 跳过翻 status")
    return False


# -------------------------------------------------- 卡 228（T-G344）：批模式按栅栏成员翻
def flip_batch_member_statuses(wt: pathlib.Path, batch_id: str,
                               staged: list[str]) -> bool:
    r"""★ 卡 228：`--batch` 落地即翻**成员卡**的 status —— 按批清单逐个成员判定。

    ★ 来路（缺陷）：老链里批模式走 `flip_card_status(wt, None, a.task)`，而批模式的
      `--task` 是**批台账号**（如 T-G340），成员卡自己的 task 是 T-G333… ⇒
      `task_val != task` 永远命中 ⇒ **一张都翻不中**（能力在、判据错位）。
    ★ 修法：读批清单 `gates/diag/batch/<批号>.toml` 的 `[[member]]`，逐成员判
      「**这是它自己的落地**」—— 判据与单卡同源：**成员的产物确实进了这一笔**
      （队列 `files` 域为准、清单 `paths` 兜底，与**暂存清单**求交；空交 ⇒ 不翻）。
      命中 ⇒ `flip_card_status(..., require_task_match=False)` 翻那张卡。
    · `read_only = true` 的审计型成员**跳过**（它不改文件，没有"自己的落地"）。
    · 清单读不到 ⇒ 打印一句并跳过（不崩、不猜——批状态只活在主树，
      假仓/无清单环境优雅跳过）。

    返回 `True` ⇒ 至少翻了一张（调用方应把 `docs/workbacklog.toml` 加进 allow）。
    """
    from pool.task import load_manifest  # 延迟 import：单卡路径不背这个依赖
    try:
        man = load_manifest(batch_id)
    except Exception as exc:
        print(f"  [队列] 批 {batch_id}：读不到批清单 ⇒ 跳过翻成员 status"
              f"（{type(exc).__name__}: {exc}）")
        return False
    flipped_any = False
    for m in man.get("member") or []:
        mid = str(m.get("id", ""))
        if m.get("read_only"):
            print(f"  [队列] 成员卡 {mid}：read_only（审计型）⇒ 跳过")
            continue
        own = _card_files_from_backlog(wt, mid, None) or [str(p) for p in m.get("paths") or []]
        hits = [f for f in own if f in staged]
        if not hits:
            print(f"  [队列] 成员卡 {mid}：产物不在这一笔的暂存里 ⇒ 不翻 status")
            continue
        if flip_card_status(wt, mid, "", require_task_match=False):
            flipped_any = True
    return flipped_any


# ---------------------------------------------------------------- 卡 184（T-G284）：增量门禁
# ★ 三条硬要求：① 不改门判据（只改「跑哪几道」）；② 反例钉子四条（空计划⇒全量 /
#   trailer 含「非全量」/ 碰 tools/**⇒强制全量 / 卡 147 护栏仍咬）；③ 不动 wb_impact /
#   run_gates 门清单 / .wt/**；不许 commit。
# ★ 全量分支的 gates_line 字面「全量门禁绿 + seal」**一字不动** —— 卡 133 的 6 个钉子
#   钉着它（伪造门禁结论那条判据）。增量分支用**不同**字面（含「非全量」）。

#: ★ ②.1 判据本体：碰了这些目录里**任何**文件 ⇒ 强制全量（判据/门/收口链自己）。
#: 判据按本笔的改动路径现算，**不许**由人记（卡 184 §②.1）。
JUDGE_BODY_GLOBS = ("scripts/**", "tools/**", "gates/**")

#: ★ ②.3 每日一次全量兜底：`gates/diag/_daily_full.json`（gitignored，运行时产物）。
#: 谁读它：landing.py ④ 步前读 —— 决定「今天跑过全量没有」；
#: 谁写它：landing.py ⑤ 步后写 —— 全量那一趟落盘 {date, rev, time}。
DAILY_FULL = ROOT / "gates" / "diag" / "_daily_full.json"

#: ★ ⑧ 复核落盘目录（追加三）：`gates/review/<task>.json`（gitignored，运行时产物）。
REVIEW_DIR = ROOT / "gates" / "review"


def _today_iso() -> str:
    """本地日期（YYYY-MM-DD）—— 「今天跑过全量没有」的判据单位是「天」（卡 184 §②.3）。"""
    return datetime.date.today().isoformat()


def _touched_paths(wt: pathlib.Path) -> list[str]:
    """本笔卡树改动路径（含未跟踪）—— ②.1 判据本体检查的输入。

    ★ 复用 `pool.review.changed_paths`（**唯一实现**，卡 106）：从 `git status --porcelain
    -uall --no-renames` 取路径。`-c core.quotepath=false` 钉死，中文路径不被八进制转义。
    ★ 排运行时产物（gates/** / .wt/** / __pycache__/**）—— 与 `_changed_paths_from` 同口径：
      它们不是源文件改动，不该触发 ②.1「判据本体改了」。gates/** 在真仓里是 gitignored，
      本来就不进 `git status`；假仓库里 .gitignore 没盖到，这里显式排掉。
    """
    from pool.review import changed_paths
    raw = subprocess.run(
        ["git", "-c", "core.quotepath=false", "status", "--porcelain", "-uall",
         "--no-renames"],
        cwd=str(wt), capture_output=True, text=True, encoding="utf-8", errors="replace",
        # ★ 防窗旗（卡 184 补）：`landing.py` 在本卡域里，能加旗就加旗 ——
        #   别再往 `tests/test_no_window.py` 的 EXEMPT 里加欠账。
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    paths = changed_paths((raw.stdout or "").rstrip("\r\n"))
    return [p for p in paths
            if not p.startswith(("gates/", ".wt/", "__pycache__/"))]


def _touched_judge_body(paths: list[str]) -> list[str]:
    """②.1 碰了 `scripts/**` / `tools/**` / `gates/**` 里**任何**文件 ⇒ 返回命中清单（空 = 没碰）。

    ★ 用 `pool.review.outside_allow` 的反义：把「白名单 = JUDGE_BODY_GLOBS」反着读 ——
      「在白名单里」=「碰了判据本体」。复用同一套 fnmatch 语义，不另写第三套匹配。
    """
    from pool.review import outside_allow
    # outside_allow 返回**不在** glob 里的；这里要**在** glob 里的 ⇒ 全集减去 outside
    outside = set(outside_allow(paths, list(JUDGE_BODY_GLOBS)))
    return [p for p in paths if p not in outside]


def _today_full_done() -> tuple[bool, str]:
    """②.3 今天跑过全量没有 —— 读 `gates/diag/_daily_full.json`。

    返回 `(done, info)`：done=True ⇒ 今天已经跑过一次全量，可以跑增量；
    done=False ⇒ 还没跑 ⇒ 强制全量（每日一次兜底）。读不到/坏文件 ⇒ False（宁多勿漏）。
    """
    if not DAILY_FULL.is_file():
        return False, f"没有每日全量记录（{DAILY_FULL} 不存在）⇒ 强制全量"
    try:
        data = json.loads(DAILY_FULL.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return False, f"每日全量记录读不了（{type(exc).__name__}: {exc}）⇒ 强制全量"
    date = str(data.get("date", ""))
    rev = str(data.get("rev", ""))[:12]
    if date == _today_iso():
        return True, f"今天（{date}）已跑过全量（rev={rev}）⇒ 可跑增量"
    return False, (f"上一次全量是 {date or '（空）'}（rev={rev}），"
                   f"今天 {_today_iso()} 还没跑 ⇒ 强制全量")


def _mark_today_full(rev: str) -> None:
    """②.3 全量那一趟落盘：写 `{date, rev, time}` 进 `gates/diag/_daily_full.json`。

    ★ 落盘要能从产物里一眼看出「今天跑过全量没有」（机器可判，不许靠人记）。
    ★ 失败 ⇒ 警告并继续（每日全量是兜底，不是新闸；写不了不挡提交）。
    """
    try:
        DAILY_FULL.parent.mkdir(parents=True, exist_ok=True)
        payload = {"date": _today_iso(), "rev": rev[:12],
                   "time": datetime.datetime.now().isoformat(timespec="seconds")}
        DAILY_FULL.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8", newline="\n")
        print(f"  ★ 每日全量已落盘：{DAILY_FULL}（{payload['date']} / {payload['rev']}）")
    except OSError as exc:
        print(f"  ★ 每日全量落盘失败（{type(exc).__name__}: {exc}）⇒ 警告并继续（不挡提交）")


def _affected_plan(paths: list[str]) -> tuple[object | None, str]:
    """②.2 算 `--affected` 的计划（不真跑门）—— 空计划 ⇒ 退全量，绝不许空集绿灯。

    返回 `(plan, note)`：
      - `plan is None` ⇒ **不要**传 `--affected`（跑全量）。原因可能是：没给路径 / 空计划
        （一条都命不中任何门的输入）/ 读不到门表；
      - `plan` 非 None ⇒ 可以传 `--affected`（`plan.ran` 是要跑的门清单）。
    ★ 复用 `scripts/run_gates.py` 的 `build_jobs` + `plan_affected`（**唯一真源**），
      不在本文件里造第二份门表（卡 147 硬要求）。读不到 ⇒ None（宁多勿漏：跑全量）。
    """
    if not paths:
        return None, "没给路径（空）⇒ 退全量，不传 --affected"
    try:
        scripts = str(ROOT / "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        import run_gates  # 延迟 import：避免 landing 被 import 时就依赖 scripts/
        doors = [n for n, _ in run_gates.build_jobs(False, False)]
        plan = run_gates.plan_affected(paths, doors)
        if plan.full_fallback:
            return None, f"空计划（{plan.note}）⇒ 退全量，不传 --affected"
        return plan, plan.note
    except Exception as exc:
        return None, f"读不到门表（{type(exc).__name__}: {exc}）⇒ 退全量（拿不准不放过）"


def _changed_paths_from(rev: str, wt: pathlib.Path) -> list[str]:
    """`--changed-from <REV>`：让 git 现算改了哪些路径（与 run_gates 同口径）。

    = `git diff --name-only <REV>`（已跟踪改动）∪ 未跟踪且未被忽略的文件
    （排 `gates/**` 与 `.wt/**`，与封存指纹同口径）。
    """
    tracked = [p.strip() for p in git("diff", "--name-only", rev, cwd=wt).splitlines()
               if p.strip()]
    untracked = [p.strip() for p in
                 git("ls-files", "-o", "--exclude-standard", cwd=wt).splitlines()
                 if p.strip()]
    out: list[str] = []
    seen: set[str] = set()
    for p in tracked + untracked:
        if p in seen or p.startswith(("gates/", ".wt/")):
            continue
        seen.add(p)
        out.append(p)
    return out


def _run_review(task: str, rev: str, allow: list[str]) -> tuple[int, str, pathlib.Path]:
    """⑧ 复核落盘（追加三）：wb_review.py --rev <新提交> --json → gates/review/<task>.json。

    ★ 口径照卡 143：「提交之后 · 异步 · 不挡提交」—— 复核失败不回滚已提交的那笔；
      但 `wb_task.py landed` 之前必须存在一条复核记录（那是 landed 的机器判据，不在这条链上）。
    ★ 复核发现问题 ⇒ 立卡或在文书里写明为什么不立卡（不许"跑完看一眼就丢"）。
    ★ 卡 198（T-G298）：把收口链**自己那份** `--allow` 原样传给复核
      （不许另造一份、不许改成 `--read-only` 消红字）。
    ★ 返回 `(exit_code, summary, path)`：exit_code 非 0 ⇒ 复核有问题（不挡提交，只警告）。
    """
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    review_file = REVIEW_DIR / f"{task}.json"
    cmd = [sys.executable, "-X", "utf8", str(ROOT / "tools" / "wb_review.py"),
           "--rev", rev, "--json"]
    for _g in allow:
        cmd += ["--allow", _g]
    print("  复核命令：", " ".join(cmd))
    r = subprocess.run(
        cmd,
        cwd=str(ROOT), capture_output=True, text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        encoding="utf-8", errors="replace")
    body = (r.stdout or "").strip()
    review_file.write_text(body or "{}\n", encoding="utf-8", newline="\n")
    n_problems = -1
    try:
        verdict = json.loads(body) if body else {}
        n_problems = len(verdict.get("problems", []))
    except json.JSONDecodeError:
        n_problems = -1
    summary = (f"exit={r.returncode}，problems={'?' if n_problems < 0 else n_problems}"
               f"，落盘 {review_file}")
    return r.returncode, summary, review_file
def _renewer_loop(lock_label: str, wt: pathlib.Path, env: dict,
                  stop: threading.Event, interval: float) -> None:
    r"""后台续租门禁锁（卡 163 INV-28）—— 定期调 `gate_lock.py renew`，直到 `stop` 被设。

    ★ 不许把租约时长写第二份：这里只刷 mtime，租约时长仍由
      `gate_lock.DEFAULT_STALE_AFTER` 唯一决定（acquire 不再传 --stale-after）。
      续租失败不崩主流程（只吞异常）—— 续租是**保命**的，不是门禁通过的判据。
    """
    while not stop.wait(interval):
        with contextlib.suppress(Exception):
            subprocess.run(
                [sys.executable, "-X", "utf8", "gates/diag/gate_lock.py",
                 "renew", "--card", lock_label],
                cwd=str(wt), env={**os.environ, **env},
                capture_output=True, text=True, timeout=30,
                # ★ 防窗旗（卡 163）：续租每 5 分钟起一次进程，Windows 上不许弹窗。
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
def mirror_remote() -> pathlib.Path | None:
    r"""镜像路径（卡 192 · T-G292）：**不许写死**。

    优先级：① 环境变量 `TF_MIRROR_REMOTE`；② 相对 ROOT 探测默认位置
    `ROOT.parent.parent / "backup-engineering.git"`（engineering 上两级 = jelly_ware，
    镜像与仓平级 —— 换机器只要目录结构一样就通，不写死绝对路径）；③ 都没有 ⇒ None（跳过 push）。
    """
    env = os.environ.get("TF_MIRROR_REMOTE", "").strip()
    if env:
        p = pathlib.Path(env)
        return p if p.exists() else None
    default = ROOT.parent.parent / "backup-engineering.git"
    return default if default.is_dir() else None


def _main_tree_root() -> pathlib.Path:
    """**主工作树**的根。

    卡树里 `.git` 是文件（`gitdir: <主>/.git/worktrees/<名>`）⇒ `parents[2]` 即主树根。
        #

    ★ 纯 stdlib、不调 git（守卫是纯函数那一层的口径）。
    """
    marker = ROOT / ".git"
    if marker.is_file():
        try:
            text = marker.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return ROOT
        if text.startswith("gitdir:"):
            target = pathlib.Path(text.split(":", 1)[1].strip())
            shared = target.parents[2]
            if shared.is_dir():
                return shared
    return ROOT


def main_tree_offenders(allow: list[str], pen: pathlib.Path | None = None) -> list[str]:
    r"""★ 卡 192（T-G292）主干保护：主树**跟踪文件**的改动且不在白名单 ⇒ 列出来（拒）。

    判据：`git status --porcelain -uno`（只看跟踪文件，未跟踪的用户笔记不算）里，
    去掉白名单（`--allow` + DOCS + GATES，收口链本就要动的）后仍非空 ⇒ 主控在主干直接改了
    不该改的东西 ⇒ 违反"主干只接受合并、不接受直接改"。★ `--tree .` 时工人的产物在主树、
    且在 `--allow` 里 ⇒ 不算 offender（放行）。
    """
    # ★ 2026-10-12（主控）：**笔就是主树时不触发** —— 那时「改笔」与「改主干」是同一件事，
    #   守卫无从区分、也没有意义（它要防的是「改动从卡树漏进主干」）。真流程里笔是
    #   `.wt/<卡树>`，所以这条豁免既保住老用法（`--tree .`），又不放松真正的保护。
    if pen is not None:
        try:
            if pen.resolve() == _main_tree_root().resolve():
                return []
        except OSError:
            pass
    # ★ 2026-10-12 修（主控）：这里原来用 `ROOT` —— 而 `ROOT` 是**本模块所在的那棵树**（卡树！），
    #   ⇒ 真流程里它查的是卡树、**从没保护过主干**。改成查**主工作树**
    #   （卡树里 `.git` 是文件，内容 `gitdir: <主树>/.git/worktrees/<名>` ⇒ parents[2] 即主树根）。
    raw = run(["git", "-c", "core.quotepath=false", "status", "--porcelain", "-uno"],
              cwd=_main_tree_root(), check=False).stdout or ""
    dirty = [x for x in raw.splitlines() if x.strip()]
    allow_set = set(allow) | set(DOCS) | set(GATES)
    offenders: list[str] = []
    for line in dirty:
        path = line[3:].split(" -> ")[-1].strip().strip('"')
        if not _allow_hits(path, allow_set):
            offenders.append(line)
    return offenders


def _allow_hits(path: str, allow: set[str]) -> bool:
    """`--allow` 的一项是否**盖住**这个路径。

    ★ 2026-10-12（主控）：原来是**逐字相等** ⇒ `--allow code` **管不到** `code/a.py`，
    于是守则把自己的测试（`allow=("code",)` + 改 `code/a.py`）也拦了。而 `wb_land` 的
    `--allow` 语义本来就是 **glob**（复核那侧写着 `--allow <glob>`）⇒ 这里对齐：
    逐字相等 / `fnmatch` / **目录前缀**（`code` 盖 `code/a.py`）三选一。
    """
    import fnmatch

    for pat in allow:
        if not pat:
            continue
        if path == pat or fnmatch.fnmatch(path, pat):
            return True
        if path.startswith(pat.rstrip("/") + "/"):
            return True
    return False


# -------------------------------------------------- 卡 E1（T-AG443）：判据前置
# ★ 卖点：一趟只读体检把「这一趟会踩的线」**一次说全**（不 fail-fast、不碰任何文件）；
#   别等到第 12 分钟才红。（耗时大头是 audit --all 自己，见 `preflight` 的实测记录。）
# ★ 判据不另写一份：文书断言 / 队列 status 扫描 / 主树 offender / `Gates:` 模板
#   都是本文件里落地链**正在用**的同一批函数（卡 E1 判据 5）。

#: 文书的三个段（`wb_stage_card.py --text-file` 的解析口径，顺序固定）。
TEXT_SECTIONS = ("gaps", "changelog", "checkpoint")

#: preflight 里两条子进程检查的硬超时（audit 实测 10~15 s、ruff ~1.3 s）。
PF_TIMEOUT = 300

#: ruff 快检扫的目录（与 `gates/defs/lang_python.py` 的 ruff 门同款；只扫存在的）。
RUFF_DIRS = ("src", "tests", "scripts", "tools", "examples", "harness")

_BACKLOG_KV = re.compile(r'(\w+)\s*=\s*"([^"]*)"')
_BACKLOG_FILES = re.compile(r"files\s*=\s*\[(.*?)\]", re.S)
_BACKLOG_KEYS = ("id", "task", "spec", "status")


def _scan_blocks(lines: list[bytes]) -> list[tuple[int, int, dict[str, object]]]:
    r"""把队列按 `[[cards]]` 切成块，返回 `[(起行, 止行, 字段)]`（**只读**）。

    ★ CRLF 感知 + 逐块解析：`flip_card_status`（要改写 status 行，用得上行号）与
      `--preflight`（只读体检）共用这一份 —— 两边口径不可能分叉（卡 E1 判据 5）。
    """
    out: list[tuple[int, int, dict[str, object]]] = []
    n = len(lines)
    i = 0
    while i < n:
        if lines[i].decode("utf-8", "replace").strip() != "[[cards]]":
            i += 1
            continue
        fields: dict[str, object] = {"id": None, "task": None, "spec": None,
                                     "status": None, "status_idx": None, "files": []}
        j = i + 1
        while j < n:
            t = lines[j].decode("utf-8", "replace").strip()
            if t == "[[cards]]" or (t.startswith("[") and not t.startswith("[[")):
                break
            m = _BACKLOG_KV.match(t)
            if m:
                key, val = m.group(1), m.group(2)
                if key in _BACKLOG_KEYS:
                    fields[key] = val
                if key == "status":
                    fields["status_idx"] = j
            j += 1
        body = b"\n".join(lines[i:j]).decode("utf-8", "replace")
        fm = _BACKLOG_FILES.search(body)
        fields["files"] = re.findall(r'"([^"]*)"', fm.group(1)) if fm else []
        out.append((i, j, fields))
        i = j
    return out


def backlog_blocks(wt: pathlib.Path) -> list[dict[str, object]] | None:
    r"""读取卡树队列的全部卡块（**只读**）；树里没有队列 ⇒ `None`（假仓/沙箱）。"""
    path = wt / "docs" / "workbacklog.toml"
    if not path.is_file():
        return None
    raw = path.read_bytes()
    sep = b"\r\n" if b"\r\n" in raw else b"\n"
    return [f for _s, _e, f in _scan_blocks(raw.split(sep))]


def parse_text_doc(text: pathlib.Path) -> tuple[dict[str, str], str]:
    r"""读 `_text_<台账号>.md` 的三段 —— 返回 `(段字典, 问题一句)`（空串 = 合规）。

    ★ 只有这一份实现：`main()` 的「缺文档件」断言与 `--preflight` 的
      「存在 + 三段齐」都调它（卡 E1 判据 5）。
    """
    if not text.is_file():
        # ★ 卡 E49（T-AG499）：报**仓库相对**路径。理由是真踩过的坑 —— `--preflight`
        #   打印时 `detail[:150]` 会截断，云机/长临时目录下绝对路径一长，`_text_TG999.md`
        #   的 `.md` 正好被切掉，日志上看着像「工具要的是没有后缀的文件」。相对路径短、
        #   换机器不变，且与同一份体检里 ② 的成功话术（`shown`）同口径。
        return {}, f"缺文档件：{_rel_short(text, ROOT)}"
    parts: dict[str, str] = {}
    cur: str | None = None
    for line in text.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if s.startswith("=== ") and s.endswith(" ==="):
            cur = s.strip("= ").strip()
            parts[cur] = ""
            continue
        if cur:
            parts[cur] += line + "\n"
    missing = [k for k in TEXT_SECTIONS if not parts.get(k, "").strip()]
    if missing:
        return parts, (f"文书 {text} 缺 {' / '.join(missing)} 段"
                       "（三段：gaps / changelog / checkpoint）")
    return parts, ""


def queue_status_problems(blocks: list[dict[str, object]] | None,
                          card: str | None = None) -> list[str]:
    r"""**全队列**每个卡块都必须有 `status` 行（没有它，翻账会静默跳过 —— A 表第 9 条）。

    ★ 卡 E9（T-AG455）：从前只判**这一趟要落的那张卡**（别的卡缺 status 是它们的欠账）——
      于是这条判据长期半瞎：队列里 11 块缺 status 也照绿。数据补齐之后**全判**：
      判据不该为了迁就数据而降级。缺的每块都点名。
    ★ 入参是 `backlog_blocks()` 已经读出来的 `blocks`（内部就是 `_scan_blocks()` 的结果）——
      与 `flip_card_status` 同一份解析口径，**不额外读文件**（卡 E9 §判据 2）。
    """
    if blocks is None:
        return ["这棵树没有 docs/workbacklog.toml ⇒ 落地后翻账会静默跳过"]
    problems = [f"卡 {b['id']} 的块里没有 status 行" for b in blocks if b["status"] is None]
    if card and not any(b["id"] == card for b in blocks):
        problems.append(f"队列里没有卡 {card} 的块（翻账会静默跳过）")
    return problems


def _tracked_paths(wt: pathlib.Path) -> set[str]:
    r"""`git ls-files -z` 一次取全部已跟踪路径（别一卡起一个进程）。"""
    r0 = run(["git", "-c", "core.quotepath=false", "ls-files", "-z"], cwd=wt, check=False)
    return {p.replace("\\", "/") for p in (r0.stdout or "").split("\0") if p}


def queue_spec_problems(wt: pathlib.Path) -> list[str]:
    r"""队列里每条 `spec=` 必须**存在且已进 git**（卡 116 的判据，只读版）。"""
    blocks = backlog_blocks(wt)
    if blocks is None:
        return ["这棵树没有 docs/workbacklog.toml ⇒ 核不了 spec"]
    tracked = _tracked_paths(wt)
    bad: list[str] = []
    for b in blocks:
        spec = str(b["spec"] or "")
        if not spec:
            bad.append(f"卡 {b['id']}：spec 是空的")
        elif not (wt / spec).is_file():
            bad.append(f"卡 {b['id']}：spec 文件不存在 {spec}")
        elif spec.replace("\\", "/") not in tracked:
            bad.append(f"卡 {b['id']}：spec 未进 git（git ls-files 不认）{spec}")
    return bad


def card_domain_changes(
    wt: pathlib.Path, allow: list[str]
) -> tuple[list[str], list[str], list[str]]:
    r"""卡树里被 `--allow`（卡域）覆盖的改动：`(暂存, 未暂存, 未跟踪)`。

    ★ 只读：**不跑 `git add`**（那是 ⑤′ 的事）。判的是「卡域里有没有东西可落」——
      空卡域走到 ⑥ 一定 `return 2`，这一条把它提前到 10 秒内说。
    """
    raw = run(["git", "-c", "core.quotepath=false", "status", "--porcelain", "-uall",
               "--no-renames"], cwd=wt, check=False).stdout or ""
    allow_set = set(allow)
    staged: list[str] = []
    unstaged: list[str] = []
    untracked: list[str] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        path = line[3:].split(" -> ")[-1].strip().strip('"')
        if path.startswith(("gates/", ".wt/", "__pycache__/")):
            continue
        if not _allow_hits(path, allow_set):
            continue
        if line.startswith("??"):
            untracked.append(path)
            continue
        if line[0] not in " ?":
            staged.append(path)
        if line[1] not in " ":
            unstaged.append(path)
    return staged, unstaged, untracked


def _budget_problems(parts: dict[str, str], wt: pathlib.Path) -> list[str]:
    r"""文书结构预算 + 指针 —— 判据真源是 `tools/card_doc_budget.py`（卡 164/193）。"""
    import card_doc_budget

    gaps = parts.get("gaps", "")
    bad = card_doc_budget.check_budget(
        checkpoint=parts.get("checkpoint", ""),
        gaps=gaps,
        changelog=parts.get("changelog", ""),
    )
    if gaps.strip():
        bad += card_doc_budget.check_pointers(gaps, root=wt)
    return bad


def _pf_run(cmd: list[str], wt: pathlib.Path) -> subprocess.CompletedProcess[str]:
    r"""preflight 的子进程跑法：显式 utf-8、硬超时、**不弹窗**（卡 148）。"""
    return subprocess.run(
        cmd, cwd=str(wt), capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=PF_TIMEOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def audit_problems(wt: pathlib.Path) -> list[str]:
    r"""`scripts/audit_progress.py --all` 只读跑一趟；红 ⇒ 它点名的前两条原话。"""
    if not (wt / "scripts" / "audit_progress.py").is_file():
        return ["这棵树没有 scripts/audit_progress.py ⇒ 核不了台账"]
    try:
        r0 = _pf_run([sys.executable, "-X", "utf8", "scripts/audit_progress.py", "--all"], wt)
    except subprocess.TimeoutExpired:
        return [f"audit --all 超时（{PF_TIMEOUT}s）⇒ 当红"]
    if r0.returncode == 0:
        return []
    bad = [ln.strip() for ln in (r0.stdout or "").splitlines() if "[FAIL" in ln]
    return bad[:2] or [f"audit --all 退出码 {r0.returncode}"]


def ruff_problems(wt: pathlib.Path) -> list[str]:
    r"""ruff 快检（`--no-cache`：preflight 要零副作用）；只扫**存在**的那些目录。"""
    dirs = [d for d in RUFF_DIRS if (wt / d).is_dir()]
    if not dirs:
        return []
    try:
        r0 = _pf_run([sys.executable, "-m", "ruff", "check", "--no-cache", *dirs], wt)
    except subprocess.TimeoutExpired:
        return [f"ruff 超时（{PF_TIMEOUT}s）⇒ 当红"]
    if r0.returncode == 0:
        return []
    keep = [ln.strip() for ln in (r0.stdout or "").splitlines()
            if ln.strip() and not ln.startswith(("Found ", "All checks"))]
    return keep[:2] or [f"ruff 退出码 {r0.returncode}"]


def gates_trailer_template(*, no_gate: bool = False, commit_only: bool = False,
                           incremental: bool = False) -> str:
    r"""⑥ 的 `Gates:` trailer **模板**（落地链与 `--preflight` 共用这一份字面）。

    ★ 全量分支的字面「全量门禁绿 + seal」**一字不动** —— 卡 133 的 6 个钉子钉着它
      （伪造门禁结论那条判据的机器版）；增量分支用**不同**字面（含「非全量」）。
    """
    if no_gate:
        return "Gates: ★ 本笔**没跑门禁**（--no-gate）—— 这行不是门禁结论，别当证据用"
    if commit_only:
        return "Gates: 复用已绿的那一趟（--commit-only，封存未变）；真读数见 gates/last.json"
    if incremental:
        return ("Gates: 增量门禁（--affected，非全量；"
                "真读数见 gates/last.json 的 affected 块）"
                "+ seal —— 卡 147 护栏会咬：把增量产物当全量交 ⇒ 红")
    return "Gates: 全量门禁绿 + seal（跑前先拿门禁锁；★ 提交之后再跑 audit）"


def gates_trailer_problem(line: str, *, runs_gates: bool) -> str:
    r"""`Gates:` 模板必须与「这一趟到底跑没跑门禁」对得上（卡 133 同向，提前到 10 秒）。

    会跑门禁 ⇒ 模板**必须**声称跑过（含「门禁绿 / 全绿 / seal」）；
    `--no-gate` / `--commit-only` ⇒ 模板**必须**主动披露（含「没跑 / 复用」）。
    """
    green = any(w in line for w in ("门禁绿", "全绿", "seal"))
    skip = any(w in line for w in ("没跑", "复用"))
    if runs_gates and not green:
        return "模板没声称跑过门禁（缺「门禁绿 / 全绿 / seal」）⇒ 复核会判「声称与事实不符」"
    if not runs_gates and not skip:
        return "模板没披露「没跑门禁」⇒ 复核会当它冒充门禁绿（卡 133）"
    return ""


def _rel_short(p: pathlib.Path, base: pathlib.Path) -> str:
    r"""报错里的路径 —— 能相对仓库根就相对（绝对路径在 11 行体检里太占地方）。"""
    try:
        return pathlib.Path(p).resolve().relative_to(base.resolve()).as_posix()
    except (ValueError, OSError):
        return pathlib.Path(p).as_posix()


# ---------------------------------------------------------------- 卡 E15（T-AG466）
#: 反引号里的 `.md` token —— 与 `scripts/check_layers.check_link_integrity` 的
#: `re.compile(r"`([^\s`]*?\.md)`")` **逐字同一个口径**（那边不在本卡域内，只能同口径照抄；
#: 两条实现是否一致由 `tests/test_wb_land.py` 的交叉钉子对着真 `check_layers` 验）。
_MD_REF = re.compile(r"`([^\s`]*?\.md)`")

#: 与 `check_layers.check_link_integrity` 同一份「文档里已声明待建」豁免。
_DOC_REF_KNOWN_MISSING = frozenset({"DESIGN.md", "LEARN.md"})


def _git_ignored(wt: pathlib.Path, p: pathlib.Path) -> bool:
    r"""问 git 这条路径是否被忽略（口径同 `check_layers.is_git_ignored`）。

    gitignored 的产物（`gates/diag/**` 这类）**不随树分发** ⇒ worktree 里必然找不到，
    那不是断链。问的是**卡树**（这一趟要提交的就是这棵树）。
    """
    return run(["git", "check-ignore", "-q", "--", _rel_short(p, wt)],
               cwd=wt, check=False).returncode == 0


def md_ref_resolves(wt: pathlib.Path, doc: pathlib.Path, token: str) -> bool:
    r"""这个 `.md` token 解析得到吗 —— 三基准与 `check_layers` **完全相同**。

    依次试 ① 相对当前文档目录 ② 相对 `docs/` 根 ③ 相对仓库根；
    裸文件名（无目录分隔）再加一条：在 `docs/` 下递归找同名文件。
    被 gitignore 的候选不算断链（同 `check_layers` 的 T-G127 豁免）。
    """
    cands = [doc.parent / token, wt / "docs" / token, wt / token]
    if "/" not in token and "\\" not in token:
        cands += list((wt / "docs").rglob(token))
    if any(c.exists() for c in cands):
        return True
    # 存在性没命中：若候选落在 gitignored 的产物里（不随树分发）⇒ 也不算断链
    return any(_git_ignored(wt, c) for c in cands)


def _ref_fix_hint(wt: pathlib.Path, token: str) -> str:
    r"""可照抄的修法：`skills/` 前缀能解析时就直说（卡 E15 判据 2 要求的形状）。"""
    if (wt / "skills" / token).exists():
        return f"说成 skills/{token} 才对"
    return "改成能解析的相对路径（相对当前文档 / docs 根 / 仓库根之一），或去掉反引号"


def doc_ref_problems(wt: pathlib.Path, task: str,
                     parts: dict[str, str] | None = None) -> tuple[list[str], int]:
    r"""卡 E15 · 体检第 12 条：**本次要提交的三份文书**里反引号包住的 `.md` 必须解析得到。

    三份 = `gates/diag/_text_<任务>.md`（按段扫：gaps / changelog / checkpoint）
    + `docs/changelog.d/<任务>.md` + `docs/traceability.d/<任务>.toml`。
    ★ 没给 `task` 时**照样跑**（判据 5：这条不依赖卡号）—— 扫 `docs/changelog.d/*.md`
      与 `docs/traceability.d/*.toml` 的全部片段。`gates/diag/_text_*.md` 是 gitignored
      的 scratch（不随树分发、也进不了提交），它的内容会**原文照搬**进 changelog 片段 ⇒
      扫片段就够，不必去扫一目录别人的 `_text_*.md`（那会拿别人的欠账咬这一趟）。
    返回 `(problems, checked)`：`problems` 每条都带**段名 + token + 可照抄的修法**；
    `checked` 是实际核对过的引用条数（`0` ⇒ 调用方打 `[skip]`，不算错）。
    """
    text_doc = pathlib.Path(str(TEXT).format(task=task.replace("-", ""))) if task else None
    docs: list[tuple[str, pathlib.Path, str]] = []

    def _text(p: pathlib.Path) -> str:
        try:
            return p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    if task:
        secs = parts if parts is not None else parse_text_doc(text_doc)[0]
        for sec in TEXT_SECTIONS:
            body = secs.get(sec, "")
            if body and body.strip():
                docs.append((f"{sec} 段", text_doc, body))
        for label, rel in (("changelog 段", f"docs/changelog.d/{task}.md"),
                           ("traceability 段", f"docs/traceability.d/{task}.toml")):
            p = wt / rel
            if p.is_file():
                docs.append((label, p, _text(p)))
    else:
        for label, pat in (("changelog 段", "docs/changelog.d/*.md"),
                           ("traceability 段", "docs/traceability.d/*.toml")):
            for p in sorted(wt.glob(pat)):
                docs.append((label, p, _text(p)))

    problems: list[str] = []
    checked = 0
    seen: set[tuple[str, str]] = set()
    for label, doc, body in docs:
        for m in _MD_REF.finditer(body):
            token = m.group(1)
            if token.startswith(("http", "/")) or re.match(r"^[A-Za-z]:[\\/]", token):
                continue                      # 项目外引用，不属这条（同 check_layers）
            if pathlib.Path(token).name in _DOC_REF_KNOWN_MISSING:
                continue
            if (label, token) in seen:
                continue                      # 同一段里重复写同一个 token 只报一次
            seen.add((label, token))
            checked += 1
            if not md_ref_resolves(wt, doc, token):
                problems.append(f"{label} `{token}`（{_ref_fix_hint(wt, token)}）")
    return problems, checked


def preflight(wt: pathlib.Path, *, task: str = "", card: str | None = None,
              batch: str | None = None, allow: list[str] | None = None,
              no_gate: bool = False, commit_only: bool = False,
              incremental: bool = False, out=None) -> int:
    r"""落地前置体检（卡 E1 + 卡 E15）：12 条判据**全部跑完再说**，全程只读、不 fail-fast。

    退出码：`0` 全绿（可以直接落地）/ `1` 有 ❌（修完重跑 `--preflight`）。
    ★ 只读的判据：不跑 `git add`、不建索引、不写 `gates/**`（ruff 带 `--no-cache`）。
    ★ `card` 给了且没给 `task` ⇒ 拿队列里那张卡的 `task`；`allow` 没给 ⇒ 用它的 `files`。
    ★ `batch` 给了 ⇒ 第 ⑧ 条不逐卡判（批成员翻账走 `flip_batch_member_statuses`）。
    """
    say = out or (lambda line: print(line, flush=True))
    t0 = time.monotonic()
    blocks = backlog_blocks(wt)
    block = next((b for b in (blocks or []) if card is not None and b["id"] == card), None)
    if block is None and task and blocks:
        block = next((b for b in blocks if b["task"] == task), None)
    if not task and block is not None:
        task = str(block["task"] or "")
    domain = list(allow or [])
    if not domain and block is not None:
        domain = [str(x) for x in (block["files"] or [])]

    items: list[tuple[str, bool, str, str]] = []

    # ① 卡树 HEAD 是主树 HEAD 的祖先（否则 ① 的 checkout 会抹掉已提交的改动）
    cur = git("rev-parse", "HEAD", cwd=wt, check=False) if wt.is_dir() else ""
    main_head = git("rev-parse", "HEAD", cwd=_main_tree_root(), check=False)
    if not cur or not main_head:
        items.append(("卡树 HEAD 是主树祖先", False, "读不到 HEAD（卡树不存在或不是 git 仓）",
                      f"确认 {_rel_short(wt, ROOT)} 是 worktree"))
    elif cur == main_head:
        items.append(("卡树 HEAD 是主树祖先", True, f"两边都是 {cur[:8]}", ""))
    elif is_ancestor(cur, main_head, wt):
        items.append(("卡树 HEAD 是主树祖先", True, f"{cur[:8]} 是 {main_head[:8]} 的祖先", ""))
    else:
        items.append(("卡树 HEAD 是主树祖先", False,
                      f"卡树 {cur[:8]} 不是主树 {main_head[:8]} 的祖先（checkout 会抹掉改动）",
                      "在卡树里 rebase 到主树 HEAD（坑 33 的姿势）"))

    # ②③④ 文书：存在 + 三段齐 / changelog 首行 / 预算与指针
    if task:
        text = pathlib.Path(str(TEXT).format(task=task.replace("-", "")))
        parts, bad = parse_text_doc(text)
        shown = _rel_short(text, ROOT)
    else:
        parts, bad, shown = {}, "没给 --task，队列里也查不到这张卡的 task", "（未知）"
    items.append(("文书三段齐", not bad,
                  bad or f"{shown} 的 gaps/changelog/checkpoint 都在",
                  "照三段写好那份文书再重跑（段名：gaps / changelog / checkpoint）"))
    first = next((ln.strip() for ln in parts.get("changelog", "").splitlines()
                  if ln.strip()), "")
    ok3 = first.startswith("## ")
    items.append(("changelog 段首行是 ##", ok3,
                  f"首行 = {first[:36]}" if first else "changelog 段是空的",
                  "首行写成「## 2026-… · 一句话」（坑 23：bullet 插到标题之上会卡死下一张卡）"))
    budget = _budget_problems(parts, wt) if parts else ["文书没读到，预算无从核"]
    items.append(("文书预算与指针", not budget,
                  "；".join(budget[:2]) if budget else "结构预算与指针全过",
                  "按它点名的节 / 指针改（判据真源 tools/card_doc_budget.py）"))

    # ⑤ 队列 spec= 存在且已进 git
    spec_bad = queue_spec_problems(wt)
    items.append(("队列 spec 已进 git", not spec_bad,
                  (spec_bad[0] + (f"（另有 {len(spec_bad) - 1} 条）" if len(spec_bad) > 1 else ""))
                  if spec_bad else f"{len(blocks or [])} 条 spec 都在且已跟踪",
                  "把卡规格搬进 复盘/卡/ 并 git add（卡 116）"))

    # ⑥ 卡域内有产物可落地（暂存 / 未暂存 / 未跟踪都算）
    staged, unstaged, untracked = (card_domain_changes(wt, domain) if wt.is_dir()
                                   else ([], [], []))
    n_domain = len(set(staged) | set(unstaged) | set(untracked))
    if not domain:
        items.append(("卡域内有产物", False, "没有卡域（--allow 与队列 files 都空）",
                      "给 --allow，或让队列那张卡有 files"))
    else:
        items.append(("卡域内有产物", n_domain > 0,
                      f"暂存 {len(staged)} / 未暂存 {len(unstaged)} / 未跟踪 {len(untracked)}"
                      f"（卡域 {len(domain)} 条）",
                      "卡域里没有产物 ⇒ 没东西可落地（核对 --allow 与卡文件域）"))

    # ⑦ 主树 offender 为空（与 ④ 之前那道守卫**同一个函数**）
    offenders = main_tree_offenders(domain, wt) if wt.is_dir() else []
    items.append(("主树 offender 为空", not offenders,
                  "；".join(o.strip() for o in offenders[:2]) if offenders
                  else "主树没有白名单外的跟踪改动",
                  "把那些改动挪进卡分支（git stash / 卡树里重做）"))

    # ⑧ 队列卡块有 status 行（★ 卡 E9：**全队列**扫描 —— 任何一块缺都 ❌ 并点名）
    if batch:
        # 批模式：成员翻账走 `flip_batch_member_statuses`（按产物 ∩ 暂存判）⇒ 不逐卡判
        items.append(("队列卡块有 status 行", True,
                      "批模式：成员翻账按产物走（不逐卡判）", ""))
    else:
        st_bad = queue_status_problems(blocks, card or (str(block["id"]) if block else None))
        if not st_bad:
            detail = f"队列 {len(blocks or [])} 块都有 status 行"
        elif len(st_bad) == 1:
            detail = st_bad[0]
        else:
            detail = f"{st_bad[0]}（另有 {len(st_bad) - 1} 条）"
        items.append(("队列卡块有 status 行", not st_bad, detail,
                      "给缺的那块补一行 status（没有它，落地后翻账会静默跳过）"))

    # ⑨⑩ 两条子进程检查
    audit_bad = audit_problems(wt) if wt.is_dir() else ["卡树不存在"]
    items.append(("audit --all 绿", not audit_bad, audit_bad[0] if audit_bad else "审计通过",
                  "跑 `python -X utf8 scripts/audit_progress.py --all` 看它点名的那条"))
    ruff_bad = ruff_problems(wt) if wt.is_dir() else ["卡树不存在"]
    items.append(("ruff 快检绿", not ruff_bad, ruff_bad[0] if ruff_bad else "All checks passed",
                  "按行号修（E501 按显示宽度算，CJK 算 2 列）"))

    # ⑪ `Gates:` trailer 模板合规（与 ⑥ 共用 `gates_trailer_template`）
    line = gates_trailer_template(no_gate=no_gate, commit_only=commit_only,
                                  incremental=incremental)
    tpl_bad = gates_trailer_problem(line, runs_gates=not (no_gate or commit_only))
    items.append(("Gates: trailer 模板合规", not tpl_bad,
                  tpl_bad or f"这一趟会写「{line[:30]}…」",
                  "改 gates_trailer_template 的措辞（全量那支必须含「全量门禁绿 + seal」）"))

    # ⑫ 文书引用体检（卡 E15 · T-AG466）：本次三份文书里反引号包住的 `.md` 必须解析得到
    #   ★ 为什么要提前到体检：`check_layers` 的「引用完整性」只扫 `docs/**/*.md`，
    #     一条写错的短路径要等**全量门禁**（≈15 分钟）才红，而且同时打红两道门
    #     （`check_layers` + `check_layers_selftest`）。这一条在文书写下后 10 秒内说。
    if not wt.is_dir():
        items.append(("文书引用解析得到", False, "卡树不存在", "确认卡树路径"))
    else:
        ref_bad, ref_checked = doc_ref_problems(wt, task, parts or None)
        if ref_bad:
            items.append(("文书引用解析得到", False,
                          "文书引用解析不到：" + "；".join(ref_bad[:2])
                          + (f"（另有 {len(ref_bad) - 2} 处）" if len(ref_bad) > 2 else ""),
                          "按报行点名的 token 改（`skills/` 前缀能解析就补前缀；"
                          "或去掉反引号）⇒ 改完重跑 --preflight"))
        elif ref_checked == 0:
            items.append(("文书引用解析得到", True, "[skip] 文书里没有 .md 引用", ""))
        else:
            items.append(("文书引用解析得到", True,
                          f"{ref_checked} 条 .md 引用全部解析得到 "
                          f"（三基准同 check_layers）", ""))

    # ★ 卡 E16（T-AG467）：**先说锁** —— 等锁 28 分钟才被发现的代价太大，
    #   体检第一屏就把「这一趟会不会排在别人后面」说出来（只读：不清锁、不写文件）。
    for _ln in lock_readout():
        say(_ln)
    say("=== 落地前置体检（--preflight · 只读 · 12 条一次说全，不 fail-fast）===")
    for name, ok, detail, fix in items:
        flat = detail.replace("\n", " ")[:150]
        if ok:
            say(f"  ✅ {name}：{flat}")
        else:
            say(f"  ❌ {name}：{flat} —— 修：{fix}")
    n_bad = sum(1 for _n, ok, _d, _f in items if not ok)
    secs = time.monotonic() - t0
    if n_bad:
        say(f"★ 有 {n_bad} 条 ❌ ⇒ 修完重跑 `--preflight`"
            f"（这一趟没碰任何文件；{secs:.1f}s）")
        return 1
    say(f"✓ {len(items)} 条全绿（{secs:.1f}s，只读）⇒ 可以直接落地")
    return 0


# -------------------------------------------------- 卡 212（T-G323）：攒批收口固定进工作流

def _card_files_from_backlog(wt: pathlib.Path, card_id: str | None, task: str) -> list[str]:
    r"""从 backlog 读这张卡的 `files`（用来匹配栅栏成员的 `paths`）。

    ★ 复用 `flip_card_status` 的读法口径（CRLF 感知、逐块解析），但只读不写。
    找不到 ⇒ 空列表（不崩、不猜）。
    """
    import re
    backlog_path = wt / "docs" / "workbacklog.toml"
    if not backlog_path.is_file():
        return []
    raw = backlog_path.read_bytes()
    sep = b"\r\n" if b"\r\n" in raw else b"\n"
    lines = raw.split(sep)
    kv = re.compile(r'(\w+)\s*=\s*"([^"]*)"')
    n = len(lines)
    i = 0
    while i < n:
        if lines[i].decode("utf-8", "replace").strip() != "[[cards]]":
            i += 1
            continue
        cid_val: str | None = None
        task_val: str | None = None
        files_start: int | None = None
        j = i + 1
        while j < n:
            t = lines[j].decode("utf-8", "replace").strip()
            if t == "[[cards]]" or (t.startswith("[") and not t.startswith("[[")):
                break
            m = kv.match(t)
            if m:
                if m.group(1) == "id":
                    cid_val = m.group(2)
                elif m.group(1) == "task":
                    task_val = m.group(2)
            if t.startswith("files"):
                files_start = j
            j += 1
        is_target = ((cid_val == card_id) if card_id is not None
                     else (task_val == task))
        if is_target and files_start is not None:
            out: list[str] = []
            for k in range(files_start + 1, j):
                ln = lines[k].decode("utf-8", "replace").strip()
                if ln.startswith("]"):
                    break
                fm = re.match(r'"([^"]*)"', ln)
                if fm:
                    out.append(fm.group(1))
            return out
        i = j
    return []


def _warn_if_card_in_batch(card_id: str, match_files: list[str]) -> None:
    r"""★ 卡 212：单张落地时**警告** —— 这张卡属于某栅栏且该栅栏还有别的成员。

    选了**警告**而非拒绝（理由写进打印）：① 不破坏既有单张落地的工作流（有些卡确实
    需要单独收口，如登记卡）；② 警告已把「它属于批」这个信息摆出来，消除了「静默」这个病根；
    ③ 拒绝需加 `--force-single` 开关，增加复杂度且可能卡住紧急修复。
    ★ 不许静默继续（那正是今天的毛病）。
    """
    from pool.task import find_gates_for_member, other_members_in_gate
    gates = find_gates_for_member(card_id, match_files)
    for gate_id, member_id in gates:
        others = other_members_in_gate(gate_id, member_id)
        if others:
            print(f"★★ 警告：卡 {card_id} 属于批 {gate_id}（还有 {len(others)} 个成员："
                  f"{'、'.join(others)}）—— 攒批该走 `--batch {gate_id}`。")
            print("  本笔将单独落地这张卡（选了警告而非拒绝：有时确实需要单独收口，"
                  "如登记卡；警告已把信息摆出来，消除静默）。")


def _run_task_sub(cmd: list[str]) -> int:
    """起 `wb_task.py` 子进程（带 NO_WINDOW），打印退出码与摘要。"""
    r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                       encoding="utf-8", errors="replace",
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    for line in (r.stdout or "").strip().splitlines()[-3:]:
        print(f"    {line}")
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip()
        if err:
            print(f"    ★ {err[:200]}")
    return r.returncode


def _changed_in_commit(commit_sha: str) -> list[str]:
    """★ 卡 238（T-G356）：该笔提交**真改过**的文件（`git show --name-only`，主树视角）。

    查不到（sha 不存在 / 不是普通提交）⇒ 返回**空表** —— 空表谁也过不了核验 ⇒ 宁可拒盖。
    """
    r = run(["git", "-c", "core.quotepath=false", "show", "--name-only", "--format=",
             commit_sha], cwd=ROOT, check=False)
    if r.returncode != 0:
        print(f"  ★ `git show --name-only {commit_sha[:12]}` 失败 ⇒ 按空表核验（谁也盖不了）")
        return []
    return [x.strip() for x in (r.stdout or "").splitlines() if x.strip()]


def _stamp_refusals(
    members: list[dict], commit_files: list[str],
    claims: dict | None = None, waived: set[str] | None = None,
) -> list[str]:
    r"""⑨ 盖章前的核验（卡 238 + 卡 248）—— 产物**真在**这笔提交里 + **自己交过申请**。

    逐个成员取 `[[member]].paths` ∩ 该笔提交真改过的文件；fnmatch 语义与
    `pool.task.check_domain` 同规（成员的域就是它的 paths，不另写第二套匹配）：
    · 成员声明的 paths 为空 ⇒ 如实说「无法核验」，照样拒盖（宁可漏盖不可假盖）；
    · 交集为空 ⇒ **拒盖章**并点名："成员 X 的产物不在这笔提交里（paths=… / 该笔改了=…）"
      （卡 238 · T-G356 的判据，不许删/降级）；
    · ★ 交集**非空**、但成员自己没有成功申请（`claims[mid] != "success"` 且没被豁免）
      ⇒ **拒盖章**并点名："…该卡可能未开工或未交申请；⑨ 不许代写申请、不许盖章"
      （卡 248 · T-G369。动机：2026-10-15 主控实测 —— `--card 244` 顺着 paths 相交
      匹配上**从没开工**的卡 247 的批 B-20261034，⑨ 替它写了 success 申请、还把
      那个批标成 landed（landed.commit 记的是卡 244 的提交）。同域兄弟卡的产物
      相交并不说明它做完了 —— **成员自己交没交申请**才是判别器）。
    `claims` 传 None ⇒ 只验产物（卡 238 的老调用形状，行为一字不变）；
    `waived` 是显式豁免名单（`pool.task._missing` 口径：`_ok ∪ waived` 算齐）。
    返回拒盖章的成员号清单（空 = 全体核验通过 ⇒ 照旧盖章）。
    """
    import fnmatch
    refused: list[str] = []
    waived = waived or set()
    for m in members:
        mid = str(m.get("id", ""))
        paths = [str(p) for p in (m.get("paths") or [])]
        if not paths:
            print(f"  ★★ 拒盖章：成员 {mid} 声明的 paths 为空 ⇒ 无法核验"
                  f"（宁可漏盖不可假盖）")
            refused.append(mid)
            continue
        hits = [f for f in commit_files if any(fnmatch.fnmatch(f, p) for p in paths)]
        if not hits:
            print(f"  ★★ 拒盖章：成员 {mid} 的产物不在这笔提交里"
                  f"（paths={paths} / 该笔改了={commit_files[:8]}）")
            refused.append(mid)
            continue
        if claims is not None and claims.get(mid) != "success" and mid not in waived:
            print(f"  ★★ 拒盖章：成员 {mid} 的产物虽然在这笔提交里（{hits[:8]}），"
                  f"但它自己没有成功申请（claims 里没有它的 success）—— "
                  f"paths={paths} 与这笔提交相交的同域兄弟卡，产物相交不说明它做完了："
                  f"该卡可能未开工或未交申请；⑨ 不许代写申请、不许盖章（卡 248）")
            refused.append(mid)
    return refused


def _advance_batch_gate(batch_id: str, commit_sha: str, task: str) -> None:
    r"""`--batch` 模式：逐成员推 `claim success`，然后 `landed`（记这笔的真实 sha）。

    ★ 卡 238（T-G356）：盖章前先核验 —— 每个**非只读**成员的 `paths` ∩ 这笔提交
      真改过的文件必须非空；有一个成员的产物不在这笔提交里 ⇒ **全体不盖**
      （一个申请都不推、不标 landed），并点名拒盖章的成员。
    ★ 卡 248（T-G369）：产物核验之外还要核**成员自己的申请** —— 栅栏没集齐
      （state 不在 ready/awaiting-commit，即还有成员没交成功申请也没被豁免）⇒
      逐成员核 `claims`，缺谁的就不许替谁代写、全体不盖章、点名
      （"该卡可能未开工或未交申请"）。栅栏已集齐（这两个状态只有人人交了
      申请或被豁免才可达）⇒ 集体标记可信，逐成员只验产物（卡 238 既有判据）。
      产物真在 + 判据全过 ⇒ 照旧盖章（既有行为一字不变）。
    """
    from pool.task import load_manifest, read_json, state_path
    try:
        man = load_manifest(batch_id)
    except Exception as exc:
        print(f"  ★ 读不到栅栏 {batch_id}（{type(exc).__name__}: {exc}）⇒ 跳过推栅栏")
        return
    members = [m for m in man.get("member", []) if not m.get("read_only")]
    # ★ 卡 248：claims 从栅栏状态来（state_path 的 .json 的 `claims` 字段）。
    try:
        st = read_json(state_path(batch_id))
    except Exception:
        st = {}                       # 读不到状态 ⇒ 视为人人都没申请 ⇒ 宁可漏盖
    claims: dict = st.get("claims") or {}
    waived: set[str] = set(st.get("waived") or [])
    gate_full = st.get("state") in ("ready", "awaiting-commit")
    refused = _stamp_refusals(
        members, _changed_in_commit(commit_sha),
        None if gate_full else claims, waived)
    if refused:
        print(f"  ★★ 栅栏 {batch_id} **不盖章**：{'、'.join(refused)} "
              f"（⑨ 核验 · 卡 238/248：产物不在这笔提交里，或自己没有成功申请）")
        return
    for m in members:
        mid = m["id"]
        ev = f"landing.py 提交 {commit_sha[:12]}（task={task}，--batch {batch_id}）"
        print(f"  推栅栏 {batch_id} 成员 {mid}：")
        _run_task_sub([sys.executable, "-X", "utf8", str(ROOT / "tools" / "wb_task.py"),
                       "claim", batch_id, mid, "--claim", "success",
                       "--evidence", ev, "--why", f"批 {batch_id} 收口（landing.py 自动推）"])
    print(f"  标 landed {batch_id}（{commit_sha[:12]}）：")
    _run_task_sub([sys.executable, "-X", "utf8", str(ROOT / "tools" / "wb_task.py"),
                   "landed", batch_id, "--commit", commit_sha])


def _advance_card_gate(card_id: str, commit_sha: str, task: str,
                        match_files: list[str]) -> None:
    r"""`--card` 模式：找卡属于哪个栅栏，推 `claim success`。

    ★ 只推 `claim`（单张落地不等于整个批收口）。若推完后栅栏齐了（到 `awaiting-commit`），
      也推 `landed`（need=1 的批就是这样）。
    ★ 读不到栅栏（卡不在任何栅栏里）⇒ 跳过并打印一句（不崩、不猜、不新建栅栏）。
    ★ 卡 238（T-G356）：推申请前核验**这个成员**的产物真在这笔提交里（不在 ⇒ 不推，
      免得证据写着一笔没带它产物的提交号）；要标 landed 前核验**全体成员** ——
      有人产物不在 ⇒ 不标 landed 并点名（f4d4626 假账：236 的提交号盖了三个别的批）。
    ★ 卡 248（T-G369）：**本卡自己**（成员号 == card_id，按 id 匹配上的）的申请由
      这次落地来交（既有行为不变）；**别的成员**（paths 相交顺带匹配上的同域
      兄弟卡）必须已有自己的成功申请 —— 没有就**不许代写**（2026-10-15 事故：
      `--card 244` 顺带匹配上从没开工的 247 的批，⑨ 替它写了 success 申请）。
      推 landed 前核验**全体成员各自的申请**：有人没交 ⇒ 不标 landed 并点名。
    """
    from pool.task import find_gates_for_member, load_manifest, member_of, read_json, state_path
    gates = find_gates_for_member(card_id, match_files)
    if not gates:
        print(f"  ★ 卡 {card_id} 不属于任何栅栏 ⇒ 跳过推栅栏")
        return
    commit_files = _changed_in_commit(commit_sha)
    for gate_id, member_id in gates:
        try:
            man = load_manifest(gate_id)
        except Exception as exc:
            print(f"  ★ 读不到栅栏 {gate_id}（{type(exc).__name__}: {exc}）⇒ 跳过推栅栏")
            continue
        if member_id == card_id:
            # 本卡自己的申请：这次落地就是来交它的 —— 只验产物（卡 238 既有形状）。
            if _stamp_refusals([member_of(man, member_id)], commit_files):
                continue
        else:
            # ★ 卡 248：同域兄弟卡 —— 它的申请必须它自己交过，⑨ 不许代写。
            try:
                st_pre = read_json(state_path(gate_id))
            except Exception:
                st_pre = {}
            mem_claims: dict = st_pre.get("claims") or {}
            mem_waived: set[str] = set(st_pre.get("waived") or [])
            if _stamp_refusals([member_of(man, member_id)], commit_files,
                               mem_claims, mem_waived):
                continue   # 点名已由 _stamp_refusals 打印；这个成员的申请不许推
        ev = f"landing.py 提交 {commit_sha[:12]}（task={task}，--card {card_id}）"
        print(f"  推栅栏 {gate_id} 成员 {member_id}：")
        _run_task_sub([sys.executable, "-X", "utf8", str(ROOT / "tools" / "wb_task.py"),
                       "claim", gate_id, member_id, "--claim", "success",
                       "--evidence", ev,
                       "--why", f"卡 {card_id}（{task}）落地（landing.py 自动推）"])
        with contextlib.suppress(Exception):
            st = read_json(state_path(gate_id))
            if st.get("state") == "awaiting-commit":
                need_stamp = [m for m in man.get("member", []) if not m.get("read_only")]
                refused = _stamp_refusals(
                    need_stamp, commit_files,
                    st.get("claims") or {}, set(st.get("waived") or []))
                if refused:
                    print(f"  ★★ 栅栏 {gate_id} 齐了也**不标 landed**："
                          f"{'、'.join(refused)} "
                          f"（⑨ 核验 · 卡 238/248：产物不在这笔提交里，"
                          f"或自己没有成功申请）")
                    continue
                print(f"  栅栏 {gate_id} 齐了 ⇒ 标 landed（{commit_sha[:12]}）：")
                _run_task_sub([sys.executable, "-X", "utf8", str(ROOT / "tools" / "wb_task.py"),
                               "landed", gate_id, "--commit", commit_sha])


def _integrate_multi_tree(into_wt: pathlib.Path, batch_id: str,
                          task: str) -> bool:
    r"""★ 卡 212：`--batch` 收口时，若批成员的产物**不在同一棵树**里，
    把各棵树的改动合进集成树 `into_wt` 再落。

    ★ 冲突要当场咬：两棵树改了**同一个文件** ⇒ **停手并点名**（不许自动择一、不许静默覆盖）。
    ★ 合的方式与顺序**可复现**：按栅栏 declared 顺序逐棵树复制文件。
    ★ 都在同一棵树（或都是主树）⇒ 不做集成，返回 True（现有逻辑不变）。

    返回 False ⇒ 冲突停手（调用方 return 3）。
    """
    from pool.task import load_manifest
    try:
        man = load_manifest(batch_id)
    except Exception:
        return True  # 读不到栅栏 ⇒ 不做集成（现有逻辑不变）
    # 读 backlog 找各成员卡的 tree
    card_files_map: dict[str, tuple[str, ...]] = {}
    member_by_id: dict[str, dict] = {}
    for m in man.get("member", []):
        mid = m["id"]
        cfiles = _card_files_from_backlog(into_wt, mid, None) or (m.get("paths") or [])
        card_files_map[mid] = tuple(cfiles)
        member_by_id[mid] = m
    # 找各成员卡的 tree（从 backlog）
    backlog_path = into_wt / "docs" / "workbacklog.toml"
    if not backlog_path.is_file():
        return True
    import re
    raw = backlog_path.read_bytes()
    sep = b"\r\n" if b"\r\n" in raw else b"\n"
    lines = raw.split(sep)
    kv = re.compile(r'(\w+)\s*=\s*"([^"]*)"')
    blocks: list[tuple[str, str]] = []   # backlog 里的 (卡号, 声明的树)
    n = len(lines)
    i = 0
    while i < n:
        if lines[i].decode("utf-8", "replace").strip() != "[[cards]]":
            i += 1
            continue
        cid_val: str | None = None
        tree_val: str | None = None
        j = i + 1
        while j < n:
            t = lines[j].decode("utf-8", "replace").strip()
            if t == "[[cards]]" or (t.startswith("[") and not t.startswith("[[")):
                break
            m2 = kv.match(t)
            if m2:
                if m2.group(1) == "id":
                    cid_val = m2.group(2)
                elif m2.group(1) == "tree":
                    tree_val = m2.group(2)
            j += 1
        if cid_val and tree_val:
            blocks.append((cid_val, tree_val))
        i = j

    # ★ 卡 E13（T-AG464）：匹配**不许猜**。本函数的历史口径是「卡号里的数字相等就算同一个成员」，
    #   而 `G1` / `F1` / `E1` / `B1` / `D1` 的数字键**都是 1** ⇒ 批里只有成员 G1 时，
    #   backlog 里别的 `*1` 卡也被认成 G1，把 `.wt/F1` 的改动合进批树（第五处机制那次事故）。
    #   现在三层口径，逐层收紧：
    #     ① 精确优先：卡号 == 成员号 ⇒ 命中，**不做任何模糊匹配**；
    #     ② 数字回退只兜**没精确命中的成员**（别人的卡不再有机会冒充），且必须**唯一**：
    #        同一数字键对上不止一个成员 ⇒ 点名「数字键撞车」并**停手**（不许只打印继续）；
    #     ③ 树必须是这位成员自己的树：`f".wt/{mid}"`，或栅栏里给该成员写的 `tree`；
    #        对不上 ⇒ 点名并**停手**（说明匹配到的其实是别人的卡块）。
    def _digits(s: str) -> str:
        return re.sub(r"\D", "", s)

    def _own_tree(mid: str) -> str:
        return str(member_by_id[mid].get("tree") or f".wt/{mid}")

    member_trees: list[tuple[str, pathlib.Path]] = []
    matched: set[str] = set()
    used: set[int] = set()
    # ① 精确优先（按 backlog 顺序 ⇒ 可复现）
    for idx, (cid_val, tree_val) in enumerate(blocks):
        if cid_val not in card_files_map or cid_val in matched:
            continue
        if tree_val != _own_tree(cid_val):
            print(f"  ★ {cid_val} 声明的树是 {tree_val}，但成员 {cid_val} 的树是 "
                  f"{_own_tree(cid_val)} ⇒ 停手")
            return False
        member_trees.append((cid_val, ROOT / tree_val))
        matched.add(cid_val)
        used.add(idx)
    # ② 数字回退：只给还没精确命中的成员兜底
    for idx, (cid_val, tree_val) in enumerate(blocks):
        if idx in used:
            continue
        key = _digits(cid_val)
        if not key:
            continue
        cands = [mid for mid in card_files_map if mid not in matched and _digits(mid) == key]
        if not cands:
            continue            # 这张卡不是任何（还没命中的）成员 ⇒ 与批无关，跳过
        if len(cands) > 1:
            print(f"  ★ 数字键撞车：卡 {cid_val} 的数字键 {key} 同时对上成员 "
                  f"{'、'.join(cands)} ⇒ **停手**（不许猜、不许跳过静默继续）")
            return False
        mid = cands[0]
        if tree_val != _own_tree(mid):
            print(f"  ★ {cid_val} 声明的树是 {tree_val}，但成员 {mid} 的树是 "
                  f"{_own_tree(mid)} ⇒ 停手")
            return False
        member_trees.append((mid, ROOT / tree_val))
        matched.add(mid)
        used.add(idx)
    # 去重：同一棵树只取一次
    seen_trees: set[pathlib.Path] = set()
    unique: list[tuple[str, pathlib.Path]] = []
    for mid, src in member_trees:
        if src not in seen_trees:
            seen_trees.add(src)
            unique.append((mid, src))
    if len(unique) <= 1:
        return True  # 只有一棵树（或都是主树）⇒ 不需要集成
    print(f"=== ①′ 多棵树集成（{len(unique)} 棵 → {into_wt}）===")
    print(f"  参加集成的树：{'、'.join(str(src) for _mid, src in unique)}")
    seen_files: dict[str, str] = {}
    total = 0
    for member_id, src_wt in unique:
        if not src_wt.is_dir():
            print(f"  ★ {member_id}：树 {src_wt} 不存在 ⇒ 跳过")
            continue
        base = git("rev-parse", "--short", "HEAD", cwd=src_wt, check=False) or "?"
        tracked = [p for p in git("diff", "--name-only", "HEAD", cwd=src_wt,
                                  check=False).splitlines() if p.strip()]
        untracked = [p for p in git("ls-files", "-o", "--exclude-standard",
                                    cwd=src_wt, check=False).splitlines() if p.strip()]
        changed = tracked + untracked
        print(f"  {member_id}：树 {src_wt}（基点 {base}，{len(changed)} 个改动文件）")
        for f in changed:
            if f in seen_files:
                print(f"  ★★ 冲突：文件 {f} 被 {seen_files[f]} 和 {member_id} 都改了"
                      f" ⇒ **停手**（不许自动择一、不许静默覆盖）")
                return False
            seen_files[f] = member_id
            src = src_wt / f
            dst = into_wt / f
            if src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(src.read_bytes())
                total += 1
            else:
                dst.unlink(missing_ok=True)
    print(f"  合了 {total} 个文件，来自 {len(unique)} 棵树")
    return True


def fast_preflight(wt: pathlib.Path, env: dict) -> bool:
    """③″ 快门禁预检（卡 226 · `T-G342`；次序钉在卡 236 · `T-G354`）：
    卡树里跑 `scripts/run_gates.py --fast`（十几秒；★ **不落盘**）。

    · 红 ⇒ 停手（调用方退 7）：把红的门连**原话输出**带出来，并说清「还没跑全量」；
    · 绿 ⇒ 打一行「快门禁全过」后照常走 ④ 全量（动机不变：秒级失败别烧那 3~4 分钟）；
    · ★ 次序：必须在「--card/--batch 恰好给一个」的参数合法性检查**之后**
      （参数非法 ⇒ 立刻退 6，预检一次都不许跑 —— 否则预检的话会顶掉那句原话），
      且仍在全量门禁 ④ **之前**。
    · 内存闸不绕：`--fast` 那一趟照样先过 `run_gates.py` 的内存闸（卡 102）。
    """
    print("=== ③″ 快门禁预检（run_gates.py --fast；十几秒；★ 不落盘）===")
    r = subprocess.run(
        [sys.executable, "-X", "utf8", "scripts/run_gates.py", "--fast"],
        cwd=str(wt), env={**os.environ, **env},
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0:
        print((r.stdout or "").strip()[-1200:])
        print(f"  ★ 快门禁预检不绿（退出码 {r.returncode}）⇒ **停手**（还没跑全量）")
        return False
    print("  ✓ 快门禁全过（十几秒）⇒ 继续全量")
    return True


def _join_merge_queue(a, wt: pathlib.Path, env: dict) -> int:
    r"""卡 E5（`T-AG447`）：进**合并队列**，等到自己成为队首（单写者 ④–⑦）。

    次序是判据的一部分：①②③（迁树 / 文书 / sync_counts）与 ③″ 快预检**已经在队外**做完
    ⇒ 排队的那些不是空等；到了 ④ 之前才来抢单写者段。

    返回 `0` 继续 / `8` 等队首超时（已从队列里摘掉）。

    ★ 投机预检**不许复用**（判据 3）：入队时记下当时的**主树 HEAD**；轮到队首时主树若已
      前进（前一笔刚 ff 合流），`respec_required()` ⇒ 重跑一次 ③″，再往下走。
    ★ 边界（如实）：**不替别人 rebase 脏卡树** —— 卡树里是工人未提交的改动，
      `git rebase` 会拒绝（`cannot rebase: You have unstaged changes`），强来就是丢活。
      所以「下一个的卡树 rebase 到新 HEAD」这一步做成**尽力而为**（干净才 rebase），
      失败就留给它自己落地时的 ①（迁树）——两边都不静默（都打印）。
    """
    from pool import queue as merge_queue

    base = git("rev-parse", "HEAD")
    mine = tuple(getattr(a, "allow", ()) or ())
    pos = merge_queue.enqueue(a.tree, a.task, base=base, files=mine)
    print("=== ④′ 合并队列（单写者：④–⑦ 同时只许一笔在跑）===")
    # ★ 卡 E5：**同文件卡不许同批** —— 域相交的那几笔各自占一个批，不许并排（单据在 queue.py）。
    peers = merge_queue.same_file_conflicts(a.task)
    if peers:
        print(f"  ★ 同文件卡不许同批：{a.task} 的域（{'、'.join(mine) or '未记'}）与 "
              f"{'、'.join(peers)} 相交 ⇒ 排在它们后面（不并行进同一批）")
    print(f"  [队列] {a.task} 位置 {pos['position']}/{pos['total']}"
          f"（队首 {pos['head']}；基点 {base[:8]}）")
    if not merge_queue.wait_turn(a.task, timeout=a.queue_wait, say=print):
        merge_queue.drop(a.task)
        return 8
    main_now = git("rev-parse", "HEAD")
    if merge_queue.respec_required(a.task, base=main_now):
        print(f"  [队列] ★ 主树在排队期间前进到 {main_now[:8]}（入队时 {base[:8]}）"
              f"⇒ **投机预检作废**，重跑 ③″（结果不复用）")
        if not fast_preflight(wt, env):
            return 7
    return 0


def _prepare_next_member(entry: dict | None) -> None:
    r"""卡 E5 判据 3：队首 ff 合流后，把**下一个**的卡树 rebase 到新 HEAD（尽力而为）。

    ★ 只在卡树**干净**时真 rebase。工人改到一半的卡树（未提交改动）rebase 会被 git 拒绝，
      强来 = 丢活（坑 33 同族）⇒ 跳过并打印「由它自己 ① 迁树」。
    ★ 不管 rebase 成没成，**都不许**替它"重跑门禁"：门禁只能在它自己的进程里跑（锁 / 端口 /
      卡树 cwd 都在那边）。它变队首时 `respec_required()` 会咬 ⇒ 它自己重跑 ③″–④。
    """
    if not entry:
        print("  [队列] 没人排队了（单写者段归还）")
        return
    from pool import queue as merge_queue

    task = str(entry.get("task") or "")
    wt = ROOT / str(entry.get("tree") or "")
    new_head = git("rev-parse", "HEAD")
    print(f"=== ④″ 交接：下一个是 {task}（树 {entry.get('tree')}）===")
    if not wt.is_dir():
        print(f"  ★ 卡树 {wt} 不存在 ⇒ 摘掉它（它要落地得先建树）")
        merge_queue.drop(task)
        return
    dirty = [x for x in git("status", "--porcelain", "-uno", cwd=wt,
                            check=False).splitlines() if x.strip()]
    if dirty:
        print(f"  · 卡树有 {len(dirty)} 个未提交改动 ⇒ **不替它 rebase**"
              f"（那会丢工作区改动）⇒ 由它自己落地时 ① 迁树")
        return
    r = run(["git", "rebase", new_head], cwd=wt, check=False)
    if r.returncode != 0:
        print(f"  ★ rebase 失败（{(r.stderr or '').strip()[:160]}）⇒ **需人工**"
              f"（不自动择一）；它的 ③″ 结论已作废，变队首时会重跑")
        run(["git", "rebase", "--abort"], cwd=wt, check=False)
        return
    print(f"  ✓ {task} 的卡树已 rebase 到 {new_head[:8]}（它的投机预检作废 ⇒ 变队首时重跑）")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser()
    # ★ `--card` 与 `--batch` 二选一：前者是"一张卡一笔提交"，后者是**攒批通道**
    #   （同一个板块的若干小改攒成一批 ⇒ 一笔提交 / 一段文书 / 一趟门禁）。
    #   `--card` 在本脚本里只当**门禁锁的标签**用（不查卡、不读卡规格），所以批号也能当标签。
    ap.add_argument("--card")
    ap.add_argument("--batch", help="批次号（`gates/diag/batch/<批号>.json` 那个）")
    ap.add_argument("--tree", required=True)
    ap.add_argument("--task", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--type", default="feat")
    ap.add_argument("--scope", default="tools")
    ap.add_argument("--group", default="ENGINEERING")
    ap.add_argument("--evidence", nargs="+", required=True)
    ap.add_argument("--allow", nargs="+", required=True)
    ap.add_argument("--port-base", type=int, default=9034)
    ap.add_argument("--refs", default="",
                    help="其它台账号（牵扯到的别的卡）；★ 不给时单卡笔默认写本笔台账号（卡 E38）")
    ap.add_argument("--no-gate", action="store_true", help="★ 只在文档件/白名单上试跑时用")
    ap.add_argument("--no-reset", action="store_true",
                    help="关掉开跑时的「⓪ 回退派生物」；★ **默认会回退**"
                         "（把上一趟残留的派生物/记账产物退回 HEAD，幂等重跑用）")
    ap.add_argument("--commit-only", action="store_true",
                    help="⑥ 起接着走：门禁已绿、封存没变时用（跳过 ①②③④⑤）")
    # ★ 卡 184（T-G284）：增量门禁开关 —— **默认关**（今天的行为一字不变）。
    #   只在显式给开关时才少跑几道门；判据方向 = 宁多勿漏
    #   （碰判据本体 / 空计划 / 今天没跑过全量 ⇒ 强制全量）。
    ap.add_argument("--affected", nargs="+", metavar="路径",
                    help="★ 卡 184：只跑「被这些路径影响」的门"
                         "（透传给 run_gates.py 的 --affected）。"
                         "判据方向 = 宁多勿漏：① 碰 scripts/**/tools/**/gates/** ⇒ 强制全量；"
                         "② 空计划 ⇒ 退全量；③ 今天还没跑过全量 ⇒ 强制全量（每日一次兜底）。"
                         "★ 默认（不给）跑全量；增量那一趟的 trailer 会写「非全量」字样。")
    ap.add_argument("--changed-from", metavar="REV",
                    help="★ 卡 184：同 --affected，但路径由 git 现算"
                         "（git diff --name-only <REV> + 未跟踪）。"
                         "与 --affected 同样受三条强制全量约束。")
    ap.add_argument("--no-review", action="store_true",
                    help="★ 卡 184：跳过 ⑧ 复核落盘（默认会跑 wb_review.py --rev <新提交> --json "
                         "并落盘 gates/review/<task>.json；★ 复核异步、不挡提交）")
    # ★ 卡 G3（T-AG458）：`preflight` 两个词根**必须分层**，不许同名不同义 ——
    #   · `--preflight`（**壳层**，`tools/wb_land.py`）= 落地前的只读体检（卡 E1，11 条判据）
    #   · `--skip-preflight`（**本脚本**）= 跳过 ③″ 那一趟快门禁预检（run_gates.py --fast）
    #   旧写法 `--no-preflight` 仍收（已发布过），但只在帮助里留一行「已改名」并当场提示。
    ap.add_argument("--skip-preflight", action="store_true",
                    help="★ 卡 G3：跳过 ③″ 快门禁预检（run_gates.py --fast，不落盘）—— "
                         "这是**落地链内层**的旗标；壳层的 `--preflight` 是只读体检，"
                         "两者不是一个东西。给「已经知道全量要跑」的场景；"
                         "默认会先预检（参数检查之后、④ 全量之前）")
    ap.add_argument("--no-preflight", action="store_true",
                    help="（已改名）旧写法，等价 `--skip-preflight`；保留只为不打断既有脚本")
    ap.add_argument("--queue-wait", type=float, default=3600.0,
                    help="★ 卡 E5：合并队列里最多等多久轮到自己（秒，默认 3600）；"
                         "超时 ⇒ 从队列摘掉并退 8（不白占着单写者段）")
    a = ap.parse_args(argv)
    if a.no_preflight:
        print("  ★ `--no-preflight` 已改名 `--skip-preflight`（它跳过的是③″快门禁预检，"
              "不是卡 E1 的 `--preflight` 只读体检）；这次照旧生效。")
    a = ap.parse_args(argv)
    if bool(a.card) == bool(a.batch):
        # ★ 卡 236（T-G354）：参数合法性检查必须**最先**跑 —— 非法 ⇒ 立刻退 6 + 原话，
        #   **不碰门禁、不碰预检**（③″ 若跑到这前面，预检的话会顶掉这句 ⇒ 既有判据红）。
        print("★ `--card` 与 `--batch` 必须**恰好给一个**")
        return 6
    lock_label = a.card or a.batch   # 门禁锁的标签（批号也行）
    incremental_run = False          # 卡 184：--affected 那一趟 = True（gates_line 用）

    # ★ 卡 212（T-G323）：单张落地时警告 —— 这张卡属于某栅栏且该栅栏还有别的成员。
    #   选了警告而非拒绝（理由见 _warn_if_card_in_batch docstring）。
    if a.card:
        _warn_if_card_in_batch(a.card, list(a.evidence) + list(a.allow))

    wt = ROOT / a.tree
    text = pathlib.Path(str(TEXT).format(task=a.task.replace("-", "")))
    # ★ 卡 E1（T-AG443）：存在性 + 三段齐与 `--preflight` 是**同一份**判据
    #   （`parse_text_doc`）；缺件/缺段都停在这里，话术仍是「缺文档件：<路径>」。
    _text_bad = parse_text_doc(text)[1]
    assert not _text_bad, _text_bad

    env = {"TF_GATE_PORT_BASE": str(a.port_base), "PATH": os.environ.get("PATH", "")}
    # ★ 卡 118（T-G216）：**任何**退出路径都要还锁 —— 今晚收 B-DOC1 那趟失败后，`card=B-DOC1`
    #   的锁还挂着（365s，主控手工 `release` 才还掉）。逐条 `return` 补 release 治不完
    #   （提交失败那条 return 2 就漏着，异常路径更没人管）⇒ 用 **atexit 兜底**：
    #   进程怎么退都会还一次锁；已经还过就是空操作
    #   （实测 `release` 无锁时打印「没有锁，无需释放」、退 0）。
    def _release_lock_on_exit() -> None:
        release_lock(lock_label, wt, env)
    if not a.commit_only and not a.no_gate:
        __import__("atexit").register(_release_lock_on_exit)

    # ★★ 卡 192（T-G292）主干保护：主树跟踪文件的改动且不在白名单 ⇒ 拒（主干只接受合并）
    #   现在坑 41 有判据但没强制 —— 这里把它**前置**到收口最前面（任何写之前）。
    offenders = main_tree_offenders(a.allow, wt)
    if offenders:
        print("★★ 主干保护：主树有跟踪文件的改动且不在白名单 ⇒ **拒**"
              "（主干只接受合并、不接受直接改）")
        for o in offenders[:10]:
            print(f"   {o}")
        print("  处置：把那些改动挪进卡分支（`git stash` / 卡树里重做），别在主干上直接改。")
        return 5

    # ★★ 卡 192（T-G292）落地前打快照：卡树 + 主树（stash create + 挂 ref ⇒ 镜像带得走）
    #   为什么必须在**任何写之前**：今晚卡 160 的工人成果被覆盖，靠 fsck 悬空对象才救回 ——
    #   那是运气。挂 ref 后变成可达对象 ⇒ gc 不清 ⇒ 镜像带得走 ⇒ 才算真备份。
    print("=== ⓪′ 快照（落地前；stash create + 挂 ref）===")
    seg = a.tree.replace("/", "-").lstrip(".") or "root"
    snap_wt = take_snapshot(wt, why=f"落地前/{a.task}", name=seg)
    snap_root = take_snapshot(ROOT, why=f"落地前/{a.task}", name="root")
    print(f"  快照[卡树 {seg}] = {snap_wt or '(干净，无需快照)'}")
    print(f"  快照[主树 root]  = {snap_root or '(干净，无需快照)'}")

    if not a.commit_only:
        # ★ 卡 150（T-G250）：幂等重跑 —— 开跑先把**上一趟残留的派生物**退回 HEAD 干净态
        #   （放在拿锁之前，越早越好；2026-10-02 同一笔连吃三趟 11 分钟门禁，全死在这层）。
        #   ★ 只退派生物（DOCS+GATES+本台三片段），白名单源文件绝不碰；每一样都打印。
        #   --commit-only 不回退：它要提交的就是上一趟写好的文书，退了就没东西可提交。
        if a.no_reset:
            print("=== ⓪ 回退派生物：**跳过**（--no-reset）===")
        else:
            print("=== ⓪ 回退派生物（上一趟残留 → HEAD 干净态；幂等重跑）===")
            reset_derived(wt, a.task)
        main_head = git("rev-parse", "HEAD")
        print(f"=== ① 卡树迁到主树 HEAD {main_head[:12]} ===")
        cur = git("rev-parse", "HEAD", cwd=wt)
        if cur != main_head:
            # ★ 2026-10-02 加的守卫（差点静默丢代码）：卡树 HEAD 若**不是**主树 HEAD 的祖先，
            #   `git checkout main_head` 会把**那笔提交里的代码改动从工作树抹掉**
            #   （改动只在旧提交里），随后门禁照跑、`git add` 发现文件没变
            #   ⇒ 静默提交一个"只有文档"的笔，代码就丢了。
            #   这时**停手**，让主控按 `_todo_pending.md` 坑 33 的手工姿势摆树。
            if not is_ancestor(cur, main_head, wt):
                print("  ★★ 卡树 HEAD **不是**主树 HEAD 的祖先 ⇒ **停手**"
                      "（checkout 会抹掉已提交的改动）：")
                print(f"     卡树 HEAD = {cur[:12]}；主树 HEAD = {main_head[:12]}")
                print("     处置（坑 33）：`git checkout -q <主树 HEAD>` → "
                      "`git checkout <那笔提交> -- <本卡的代码/测试文件…>` → "
                      "`git reset -q` → 再重跑本脚本。")
                # ★ 卡 E6（T-AG448）：卡上的活本该留在工作区 —— 有人先 commit 了就成了这条。
                #   给一句能照抄的还原姿势（**只打印，不自动改树**：写操作必须人确认）。
                print("     如果你已经提交了：`git cherry-pick -n <那笔 sha>` 后 "
                      "`git reset` 还原成工作区改动，再重跑本脚本。")
                return 3
            run(["git", "checkout", main_head], cwd=wt)
        print("  树内 HEAD =", git("rev-parse", "--short", "HEAD", cwd=wt))
        print("  改动：")
        print("   ", git("status", "--porcelain", cwd=wt).replace("\n", "\n    "))

        # ★★ 卡 212（T-G323）：`--batch` 多棵树集成 —— 若批成员的产物不在同一棵树里，
        #   把各棵树的改动合进集成树 `wt` 再落。冲突（同一文件被多棵树改）⇒ 停手。
        if a.batch and not _integrate_multi_tree(wt, a.batch, a.task):
            print("  ★★ 多棵树集成冲突 ⇒ 停手（不许自动择一、不许静默覆盖）")
            return 3

        print("=== ② 文档件 ===")
        run([sys.executable, "-X", "utf8", str(STAGE_CARD),
             "--tree", a.tree, "--id", a.task, "--title", a.title, "--group", a.group,
             "--evidence", *a.evidence, "--text-file", str(text)], cwd=ROOT)

        print("=== ③ sync_counts ===")
        print(run([sys.executable, "-X", "utf8", "tools/sync_counts.py"], cwd=wt).stdout.strip())
        print(run([sys.executable, "-X", "utf8", "scripts/check_toml.py"], cwd=wt).stdout.strip())

        if not a.no_gate:
            # ★ 2026-10-02 加（本主控**第二次**被它咬：登记了队列条目却没在门禁前
            #   `git add` 卡规格 ⇒ 白跑 9 分钟全量门禁，口径坑第 41 条）。
            #   **fail fast**：门禁之前先跑那条**权威钉子**本身（不另写一份判据，
            #   免得变成第二份真源）。红了就停手并印出修法，
            #   **不拿 9 分钟去发现 2 秒钟的事**。
            print("=== ③′ fail fast：先跑那条「卡规格都要在索引里」的钉子 ===")
            pre = subprocess.run(
                [sys.executable, "-X", "utf8", "-m", "pytest", "tests/test_card_specs_tracked.py",
                 "-q", "--no-cov", "-p", "no:cacheprovider"],
                cwd=str(wt),
                env={**os.environ, "PYTHONPATH": str(wt / "tools" / "sandbox_shim")},
                capture_output=True, text=True, encoding="utf-8", errors="replace")
            if pre.returncode != 0:
                print("  ★ 这条钉子红了 ⇒ **停手**（全量门禁还没跑，省下 9 分钟）。")
                print("     多半是：**队列里登记的卡规格没有进索引** —— 派活时不许先 "
                      "`git add`（守卫要求工人树干净），")
                print("     但**收口时、门禁之前**必须把它 `git add` 进去："
                      "`git add -- <那几张卡规格>` 后再重跑本脚本。")
                print("     （这就是口径坑第 41 条；本脚本从今天起替你挡在门禁前面。）")
                print("  ", (pre.stdout or "").strip()[-600:])
                return 4
            print("  ✓ 卡规格都在索引里（正式门禁 ④ 仍会再跑一遍全量）")

        # ★ 卡 236（T-G354）：③″ 快门禁预检的**次序** —— 必须在参数合法性检查
        #   （--card/--batch 恰好给一个 ⇒ 退 6）**之后**、全量门禁 ④ **之前**
        #   （卡 226 的动机不变：秒级失败别烧全量那 3~4 分钟）。
        if (not a.no_gate and not a.skip_preflight and not a.no_preflight
                and not fast_preflight(wt, env)):
            return 7    # ★ 预检红 ⇒ 停手（全量门禁 ④ 一步没跑、锁也没拿）

        if not a.no_gate:
            # ★ 卡 E5（T-AG447）：**进合并队列**（单写者 = ④–⑦）。①②③ 与 ③″ 已在队外做完
            #   ⇒ 排队的不空等；轮到队首才发现主树前进 ⇒ 重跑 ③″（投机预检不许复用）。
            _q = _join_merge_queue(a, wt, env)
            if _q != 0:
                return _q

        if not a.no_gate:
            # ★ 卡 184（T-G284）：算要不要跑增量 —— 默认全量；只有显式给 --affected /
            #   --changed-from 才考虑增量，且三条强制全量任何一条命中就跑全量：
            #   ②.1 判据本体改了（scripts/**/tools/**/gates/**）/ ②.2 空计划 / ②.3 今天还没跑过全量
            gate_cmd = [sys.executable, "-X", "utf8", "scripts/run_gates.py"]
            force_full_reason = ""
            # ★ 卡 A327：默认不再"一律全量"—— 按本笔改动面查表（`gates/defs/domains.py`，
            #   由 run_gates 自己算，落地链不造第二份规则）。判据本体（scripts/**、tools/**、
            #   gates/**）改了 ⇒ 仍走下面的 ②.1 强制全量；判不出档 ⇒ run_gates 自己退全量。
            auto_profiles = False
            if a.affected is not None or a.changed_from:
                aff_paths = list(a.affected or [])
                if a.changed_from:
                    aff_paths += _changed_paths_from(a.changed_from, wt)
                # ②.1 判据本体改了 ⇒ 强制全量（按本笔改动路径现算，不许由人记）
                touched = _touched_paths(wt)
                judge_hits = _touched_judge_body(touched)
                if judge_hits:
                    force_full_reason = (f"②.1 判据本体改了：碰了 {len(judge_hits)} 个"
                                         f" scripts/**/tools/**/gates/** 文件：{judge_hits[:5]}")
                else:
                    # ②.2 空计划 ⇒ 退全量（绝不许空集绿灯）
                    plan, plan_note = _affected_plan(aff_paths)
                    if plan is None:
                        force_full_reason = f"②.2 空计划/读不到门表：{plan_note}"
                    else:
                        # ②.3 今天还没跑过全量 ⇒ 强制全量（每日一次兜底，不按笔数）
                        today_done, daily_info = _today_full_done()
                        if not today_done:
                            force_full_reason = f"②.3 每日一次兜底：{daily_info}"
                        else:
                            # 可以跑增量
                            incremental_run = True
                            print(f"  ★ 跑增量（{plan_note}）；{daily_info}")
                            if a.affected:
                                gate_cmd += ["--affected", *a.affected]
                            if a.changed_from:
                                gate_cmd += ["--changed-from", a.changed_from]
            has_domains = (wt / "gates" / "defs" / "domains.py").is_file()
            if not force_full_reason and a.affected is None and not a.changed_from and has_domains:
                # 没人显式要增量 ⇒ 走按域选档（A327）。判据本体那三条 ②.1 仍在上面拦着。
                # ★ 只在映射表真存在时启用（老仓 / 测试假仓没有 domains.py ⇒ 照旧全量）。
                judge_now = _touched_judge_body(_touched_paths(wt))
                if judge_now:
                    force_full_reason = (f"②.1 判据本体改了：碰了 {len(judge_now)} 个"
                                         f" scripts/**/tools/**/gates/** 文件：{judge_now[:5]}")
                else:
                    gate_cmd += ["--profiles", "auto"]
                    auto_profiles = True
            if force_full_reason:
                print(f"  ★ 强制全量（不传 --affected）：{force_full_reason}")
            print(f"=== ④ 锁（段 {a.port_base}）→ 门禁（硬超时 1800s；"
                  f"{'增量' if incremental_run else '全量'}）===")
            # ★ 卡 E16（T-AG467）：拿锁改成**流式**（`acquire_gate_lock`）—— `gate_lock`
            #   每 60s 的「等门禁锁 Ns…」必须出现在落地日志里；`capture_output` 会全吞掉。
            lock_rc = acquire_gate_lock(lock_label, wt, env, wait=5400)
            # ★ 卡 163 INV-28：拿锁后起续租线程 —— 门禁跑期间锁不会被判陈旧。
            #   不传 --stale-after ⇒ 用 gate_lock.DEFAULT_STALE_AFTER（唯一真源，不写第二份）。
            renew_stop = threading.Event()
            if lock_rc == 0:
                _interval = float(os.environ.get("TF_GATE_RENEW_INTERVAL", "300"))
                threading.Thread(
                    target=_renewer_loop,
                    args=(lock_label, wt, env, renew_stop, _interval),
                    daemon=True,
                ).start()
            try:
                r = subprocess.run(gate_cmd,
                                   cwd=str(wt), env={**os.environ, **env},
                                   capture_output=True, text=True,
                                   encoding="utf-8", errors="replace",
                                   creationflags=getattr(__import__("subprocess"),
                                                         "CREATE_NO_WINDOW", 0),
                                   timeout=1800)
                out, rc = (r.stdout or ""), r.returncode
            except subprocess.TimeoutExpired as exc:   # ★ 门禁卡死：硬超时当红，别把锁留着
                out = (exc.stdout or b"").decode("utf-8", "replace") \
                    if isinstance(exc.stdout, bytes) else (exc.stdout or "")
                rc = 124
            finally:
                renew_stop.set()
            tail = out.strip().splitlines()[-22:]
            print("\n".join(tail))
            mode = "按域" if auto_profiles else ("增量" if incremental_run else "全量")
            print(f"★★ 门禁退出码 = {rc}（124 = 硬超时掐的）【{mode}】")
            if rc != 0:
                print("★ 不绿 ⇒ 不提交")
                for lg in ("gates/logs/pytest.log", "gates/logs/ui_flow.log"):
                    f = wt / lg
                    if f.is_file():
                        text_log = f.read_text(encoding="utf-8", errors="replace")
                        bad = [x for x in text_log.splitlines()
                               if "FAIL" in x]
                        if bad:
                            print(f"  {lg}:")
                            for x in bad[:5]:
                                print("   ", x.strip()[:150])
                subprocess.run([sys.executable, "-X", "utf8", "gates/diag/gate_lock.py",
                                "release", "--card", lock_label],
                               cwd=str(wt), env={**os.environ, **env},
                               capture_output=True, text=True)
                return 1
            # ★ 卡 228（T-G344）：⑤ seal 从这里**挪走** —— 原来封存在翻账/暂存**之前**
            #   算树指纹，⑥ 提交前才翻 status ⇒ 只要这笔翻了账，封存树与提交树
            #   **必然**不一致（收卡 218 那笔复核就报了「封存树 vs 提交树」）。
            #   现在封存挪到「⑤′ 白名单 → 翻账 → 暂存」**之后**（见下面 ⑥ 块前），
            #   封存算的就是**最终树**。此处只保留全量记账。


    if a.commit_only:
        print("=== ①~⑤ 跳过（--commit-only：门禁已绿、封存没变）===")
    # ★ 卡 228（T-G344）：⑥ 拆成两段 —— ⑤′（白名单 → 翻账 → 暂存）在前、封存在后、
    #   ⑥ commit 收尾。为什么这个顺序：**翻账是本笔对跟踪文件的最后一笔改动**，
    #   封存必须等它定型，封存算的才是最终树（⇒ 与提交树严格可比，卡 218 的病根）。
    print("=== ⑤′ 白名单 → 翻账 → 暂存 ===")
    allow: list[str] = expand_allow(wt, a.allow)
    if any((wt / x).is_dir() for x in a.allow):
        print("  --allow 里的目录展开成：", [x for x in allow if x not in a.allow])
    # ★ 片段**必须**进提交（2026-10-02 真踩）：108 / 109 / 111 三笔的片段全都没进提交 ——
    #   共享文档里有内容、`docs/changelog.d/` 里却没有对应文件；而 `sync_docs.py --check`
    #   只查"现有片段在不在汇总里"，**抓不到这种单向缺失**（少了一些文件它照样 PASS）。
    #   ⇒ 集成器自己补，不靠我记得写进 --allow。
    for frag in (f"docs/changelog.d/{a.task}.md", f"docs/traceability.d/{a.task}.toml",
                 f"复盘/交接.d/{a.task}.md"):
        if (wt / frag).is_file() and frag not in allow:
            allow.append(frag)
            print(f"  ★ 自动补上片段：{frag}")
    allow += list(DOCS) + list(GATES)
    # ★ 卡 204（T-G311）：落地即翻 status —— 当且仅当这是它自己的落地时，
    #   把那张卡的 status 翻成 done，并把 docs/workbacklog.toml 加进 allow（随这一笔进提交）。
    #   ★ 单卡：不能只看 --card（登记/收尾提交也用 --card <号>）⇒ 用 --task == 卡.task
    #     把「自己的落地」与「登记型提交」天然分开；必须在 staged_and_extra 之前完成，
    #     否则翻出来的改动会被当成「计划外暂存」而停手。
    #   ★ 卡 228（T-G344）：--batch 不再拿**批台账号**去比成员卡的 task（永远比不中，
    #     一张都翻不了）—— 改为：先暂存拿清单，按批清单 `[[member]]` 逐成员判
    #     「产物 ∩ 暂存」，命中才翻；翻了账重暂存一次（workbacklog 进这一笔）。
    if a.batch:
        staged, extra = staged_and_extra(wt, allow)
        if flip_batch_member_statuses(wt, a.batch, staged):
            if "docs/workbacklog.toml" not in allow:
                allow.append("docs/workbacklog.toml")
            staged, extra = staged_and_extra(wt, allow)  # 翻了账 ⇒ 重暂存、重列清单
    else:
        if flip_card_status(wt, a.card, a.task) and "docs/workbacklog.toml" not in allow:
            allow.append("docs/workbacklog.toml")
        staged, extra = staged_and_extra(wt, allow)
    print("  staged =", staged)
    print("  extra  =", extra)
    if extra or not staged:
        print("★ 计划外或空暂存区 ⇒ 停手")
        git("reset", cwd=wt, check=False)
        # ★ 拿了锁就要还 —— 这条早退路径原来**直接 return**，把锁留在那儿
        #   （今天真漏过一次：卡 106 白名单失败后 9034 的锁挂了 5 分钟）。
        #   release 必须给**同一段**（TF_GATE_PORT_BASE）。
        if not a.commit_only and not a.no_gate:
            subprocess.run([sys.executable, "-X", "utf8", "gates/diag/gate_lock.py", "release",
                            "--card", lock_label], cwd=str(wt),
                           env={**os.environ, "TF_GATE_PORT_BASE": str(a.port_base)},
                           capture_output=True, text=True)
            print("  （已顺手释放门禁锁）")
        return 2

    # ★★ 卡 228（T-G344）：⑤ 封存 —— 链序重排后的新位置。每步为什么这么排：
    #   ⓪~④（回退派生物 → 迁树 → 文档件 → 同步 → 门禁）：产内容、验内容；
    #   ⑤′（白名单 → 翻账 → 暂存）：本笔对跟踪文件的**最后一笔改动**在此定型；
    #   ⑤  封存：此刻算树指纹 = **即将提交的最终树** ⇒ 与提交树严格可比
    #       （原来封存在翻账之前 ⇒ 只要翻账，封存树 ≠ 提交树**必然**红 —— 卡 218 病根）；
    #   ⑤″ 兜底重封存：封存之后**理应**无人再动被跟踪文件；万一后面有步骤改了，
    #       重跑一次 `--seal`（**幂等**：只重算 tree 指纹、**不重跑门禁**）即可抓住，
    #       以第二次为准；两次相等 ⇒ 固定点成立（实证一行）。
    #   最后**重暂存 GATES**：封存改写了 gates/last.json，不重暂存则提交里那份是
    #   旧的，复核拿它对账必红（gates/** 本就不进指纹，重暂存不动「去 gates」固定点）。
    if not a.no_gate and not a.commit_only:
        print("=== ⑤ seal（翻账/暂存已就绪 ⇒ 封存算的是最终树）===")
        sealed = run([sys.executable, "-X", "utf8", "scripts/run_gates.py", "--seal"], cwd=wt)
        print(sealed.stdout.strip()[-300:])
        # ★ 卡 184：全量那一趟落盘每日记录（增量不落盘——它不是全量兜底）。
        #   「今天跑过全量没有」必须机器可判，不许靠人记。
        if not incremental_run:
            _mark_today_full(git("rev-parse", "--short", "HEAD", cwd=wt))

        def _sealed_tree() -> str:
            try:
                return str(json.loads((wt / "gates" / "last.json")
                                      .read_text(encoding="utf-8")).get("tree") or "")
            except Exception:
                return ""
        t1 = _sealed_tree()
        print("=== ⑤″ 兜底重封存（幂等；不重跑门禁）===")
        resealed = run([sys.executable, "-X", "utf8", "scripts/run_gates.py", "--seal"], cwd=wt)
        print(resealed.stdout.strip()[-300:])
        t2 = _sealed_tree()
        if t1 and t2 and t2 != t1:
            print(f"  ★ 兜底抓住漂移：第一次封存 tree={t1} ≠ 重封存 tree={t2}"
                  f" —— 以第二次为准（说明封存后确有被跟踪文件被改）")
        else:
            print(f"  ✓ 重封存 tree 与第一次一致（{t2 or '读不到'}）⇒ 封存后没再变")
        run(["git", "add", "--", *GATES], cwd=wt)  # 封存产物进这一笔（树指纹不含它）

    # ★ 2026-10-02 修（来路：GLM-5.3 审查卡 124 的 **2.4**）：这一行原来**无条件**写
    #   「全量门禁绿 + seal」，而本脚本有 `--no-gate`（跳过 ④⑤）与 `--commit-only`（跳过 ①~⑤）
    #   两个模式 ⇒ **工具自己在伪造门禁结论**（违反铁律 4「不许伪造完成」，且 `audit` 只查 trailer
    #   存在性、查不出真伪）。现在按**实际模式**写：跳过门禁的那两条路，谁都不许借这行冒充跑过。
    # ★ 卡 184（T-G284）：第四种形态 —— 增量门禁（--affected）。trailer 必须**如实披露「非全量」**
    #   （跑了几道 / 哪些被跳），复用卡 147 的判据（last.json 的 affected 块照写）。
    #   ★ 全量分支字面「全量门禁绿 + seal」**一字不动** —— 卡 133 的 6 个钉子钉着它（伪造门禁
    #   结论那条判据的机器版）。增量分支用**不同**字面（含「非全量」），不撞那 6 个钉子。
    # ★ 卡 E1（T-AG443）：四种形态的字面搬进 `gates_trailer_template` ——
    #   `--preflight` 判「这一趟会写的 trailer 合不合规」用的是**同一份**字面，
    #   改措辞只有一处可改（不复制第二份）。字面本身一字未动（卡 133 的 6 个钉子）。
    gates_line = gates_trailer_template(
        no_gate=a.no_gate, commit_only=a.commit_only, incremental=incremental_run)
    # ★ 卡 184 边界纪律：降级跑法必须机器可读地留痕 —— 写进 trailer 并点名。
    #   判据（wb_review.py 那半属卡 161）：跑法字段缺失、或与默认不同却没有 trailer 声明 ⇒ 红。
    #   这里只做"声明"那一半：环境变量被设了（非默认）⇒ 在 trailer 里点名。
    #   ★ 宁多勿漏：只要环境变量被设了就声明（不硬编码默认值，不造第二套）。
    run_degraded: list[str] = []
    if os.environ.get("TF_PYTEST_WORKERS") is not None:
        run_degraded.append(f"TF_PYTEST_WORKERS={os.environ['TF_PYTEST_WORKERS']}")
    if os.environ.get("TF_GATE_MIN_FREE_GB") is not None:
        run_degraded.append(f"TF_GATE_MIN_FREE_GB={os.environ['TF_GATE_MIN_FREE_GB']}")
    msg = (f"{a.type}({a.scope}): {a.title}（{a.task}）\n\n"
           + changelog_body(text)
           + f"\n\nTask: {a.task}\n"
           # ★ 卡 E38（T-AG492）：单卡笔不给 --refs 也**必写**这一行（默认 = 本笔台账号），
           #   否则 wb_verify 的「四行各一条」当场红（E38 一天里踩了四次，每次手补 --amend）。
           + f"Refs: {effective_refs(a.task, a.refs)}\n"
           + f"Ledger: 新增 {a.task}（{a.group}/done，{len(a.evidence)} 条证据）；"
           + "done 的数字以 sync_counts.py 的实测输出为准\n"
           + gates_line + "\n")
    if run_degraded:
        msg += f"Run: 降级跑法（{'; '.join(run_degraded)}）—— 非默认，卡 184 咬\n"
    msgfile = ROOT / "gates" / "diag" / f"_msg_{a.task}.txt"
    msgfile.write_text(msg, encoding="utf-8", newline="\n")
    r = subprocess.run(["git", "-c", "core.quotepath=false", "commit", "-q", "-F", str(msgfile)],
                       cwd=str(wt), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    print("  提交：", r.returncode, (r.stderr or "").strip()[:200])
    if r.returncode != 0:
        return 2
    print("  HEAD =", git("rev-parse", "--short", "HEAD", cwd=wt),
          "|", git("log", "-1", "--format=%s", cwd=wt))

    print("=== ⑦ audit → release → ff 合流 ===")
    audit = run([sys.executable, "-X", "utf8", "scripts/audit_progress.py"], cwd=wt)
    print(audit.stdout.strip()[-260:])
    if not a.no_gate:
        subprocess.run([sys.executable, "-X", "utf8", "gates/diag/gate_lock.py",
                        "release", "--card", lock_label],
                       cwd=str(wt), env={**os.environ, **env}, capture_output=True, text=True)
    new = git("rev-parse", "HEAD", cwd=wt)
    # ★ ff 守卫（2026-10-01 加）：主树可能已经被**另一笔**推进过（并发/插队）。
    #   原来这里是 `check=False` + `or 兜底` ⇒ git 报 fatal 时照样打印"ff 合流完成"，
    #   日志像成功、主树却没有这笔提交 —— 最危险的一种假绿。
    main_now = git("rev-parse", "HEAD")
    if new != main_now:
        print("  卡树提交不在主树 HEAD 上 → 先 rebase 到主树新 HEAD（并发/插队）")
        rb = subprocess.run(["git", "rebase", main_now], cwd=str(wt), capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
        if rb.returncode != 0:
            conflict = git("diff", "--name-only", "--diff-filter=U", cwd=wt).strip()
            print("  rebase 冲突（并发两笔都动了共享文档 / 门禁产物）：",
                  conflict.replace("\n", " · ") or "(没列出文件)")
            ok, detail = resolve_derived_conflicts(wt)
            if not ok:
                print("  ★★ 自动解决不了 ⇒ **停手**：", detail)
                print("  ", (rb.stdout or "")[-400:].strip())
                print("  ", (rb.stderr or "")[-400:].strip())
                return 3
            cont = subprocess.run(["git", "rebase", "--continue"], cwd=str(wt),
                                  capture_output=True, text=True, encoding="utf-8",
                                  errors="replace",
                                  env={**os.environ, "GIT_EDITOR": "true"})
            if cont.returncode != 0:
                print("  ★★ `rebase --continue` 也失败 ⇒ **停手**：")
                print("  ", (cont.stdout or "")[-400:].strip())
                print("  ", (cont.stderr or "")[-400:].strip())
                # ★ 卡 E5 判据 4：自动 rebase（含派生物自动解决）一次仍失败 ⇒ **出队 + 需人工**
                if not a.no_gate and not a.commit_only:
                    from pool import queue as _mq
                    _mq.drop(a.task)
                    print(f"  ★ 卡 E5：{a.task} 已从合并队列出队 ⇒ **需人工**"
                          f"（下一笔可以接着跑，但它自己得人来判冲突）")
                return 3
            print("  ★ 派生物冲突已**自动解决**：三个共享文档取基线版 + **按片段重汇总**；"
                  "门禁产物取本笔的")
            print("    ★ 注意：那三个文档是**门禁之后**才重汇总的"
                  "（并行落地的有意宽松 —— 见卡 115 的口径）")
        new = git("rev-parse", "HEAD", cwd=wt)
        print("  rebase 后 HEAD =", git("rev-parse", "--short", "HEAD", cwd=wt))
    # ★ 2026-10-02 修：原来这里只打印 `git()` 的 stdout（= `Updating …`），
    #   而 git **把真原因写在 stderr**
    #   ⇒ 卡 114 那次 ff 失败时只看到一行 "Updating 93c79ae..5fac774"，真原因
    #   （`error: Your local changes to the following files would be overwritten by merge:
    #   docs/workbacklog.toml`）被吞了，白查一轮。
    #   现在两边都打，并给出**最可能的处置**。
    r = run(["git", "-c", "core.quotepath=false", "merge", "--ff-only", new], cwd=ROOT, check=False)
    if git("rev-parse", "HEAD") != new:
        print("  ★★ ff 合流**没成功** ⇒ 停手：")
        print("   stdout:", (r.stdout or "").strip()[:300] or "（空）")
        print("   stderr:", (r.stderr or "").strip()[:600] or "（空）")
        dirty = [x for x in git("status", "--porcelain", cwd=ROOT).splitlines() if x.strip()]
        if dirty:
            print("   ★ 主树还有这些改动：", dirty[:8])
            print("   ★ 多半是本地改动挡住了 ff（git 不许覆盖本地改动）"
                  "——若那内容**已经在提交里**，")
            print("     就 `git -C <主树> checkout -- <那个文件>` 丢掉它，"
                  "再手工 `git merge --ff-only "
                  f"{new[:12]}`。")
        # ★ 卡 E5 判据 4：主树前进导致 ff 失败 ⇒ 上面已自动 rebase 过一次；这次 ff 仍失败
        #   ⇒ **出队 + 打印需人工**（不许让它永远占着队首，把后面所有卡一起堵死）。
        if not a.no_gate and not a.commit_only:
            from pool import queue as _mq
            _mq.drop(a.task)
            print(f"  ★ 卡 E5：{a.task} 已从合并队列出队 ⇒ **需人工**")
        return 2
    print("  ff 合流完成：主树 →", git("rev-parse", "--short", "HEAD"))
    print("  主树 HEAD =", git("rev-parse", "--short", "HEAD"), "| -uno =",
          len([x for x in git("status", "--porcelain", "-uno").splitlines() if x.strip()]), "行")
    # ★ 卡 E5 判据 3：队首 ff 成功 ⇒ **出队**，下一个自动变队首；把它的卡树
    #   尽力 rebase 到新 HEAD（脏树不碰），它的投机预检由它自己变队首时重跑。
    if not a.no_gate and not a.commit_only:
        from pool import queue as _mq
        _next = _mq.advance()
        _prepare_next_member(_next)

    # ★ 卡 184（T-G284）⑧ 复核落盘（追加三）：跑 wb_review.py --rev <新提交> --json，
    #   写 gates/review/<task>.json。★ 口径照卡 143：「提交之后 · 异步 · 不挡提交」——
    #   复核失败不回滚已提交的那笔；但 wb_task.py landed 之前必须存在一条复核记录（机器判据）。
    #   复核有问题 ⇒ 立卡或在文书里写明为什么不立卡（不许"跑完看一眼就丢"）。
    #   --no-review 跳过（默认会跑）。--commit-only / --no-gate 也跳过（没新提交可复核）。
    if not a.no_review and not a.commit_only:
        print("=== ⑧ 复核落盘（gates/review/<task>.json；异步、不挡提交）===")
        new_rev = git("rev-parse", "--short", "HEAD")
        rv_rc, rv_summary, rv_path = _run_review(a.task, new_rev, a.allow)
        print(f"  {rv_summary}")
        if rv_rc != 0:
            print("  ★ 复核有问题（不挡提交）⇒ 立卡或在文书里写明为什么不立卡")
        else:
            print(f"  ✓ 复核落盘完成：{rv_path}")
    # ★★ 卡 192（T-G292）落地后推镜像：每次落地之后 git push --mirror <镜像>
    #   镜像路径不许写死（见 mirror_remote）—— 环境变量优先，否则相对 ROOT 探测默认位置。
    #   push 失败不阻断收口（收口已成功，备份是附加），但会打印一行（不许静默）。
    mirror = mirror_remote()
    if mirror:
        r = subprocess.run(["git", "push", "--mirror", str(mirror)], cwd=str(ROOT),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        print(f"=== ⑧ 镜像 push --mirror {mirror}：退出码 {r.returncode} ===")
        if r.returncode != 0:
            print(f"  ★ push 失败（不阻断收口，但备份没更新）：{(r.stderr or '').strip()[:200]}")
        else:
            print("  ✓ 镜像已更新（卡分支 + 快照 ref 都带得走）")
    else:
        print("=== ⑧ 镜像：未配置 TF_MIRROR_REMOTE 且默认位置不存在 ⇒ 跳过 push --mirror ===")

    # ★★ 卡 212（T-G323）：提交成功后**自动**推栅栏（人不该是状态机的一部分）。
    #   推送内容取自这一笔的真实产物（--task、--card/--batch、提交 sha）。
    #   读不到栅栏 ⇒ 跳过并打印一句（不崩、不猜、不新建栅栏）。
    #   landed 记这一笔的真实 sha（wb_task.py landed 的现有口径照用）。
    print("=== ⑨ 自动推栅栏（卡 212）===")
    _commit_sha = git("rev-parse", "HEAD")
    if a.batch:
        _advance_batch_gate(a.batch, _commit_sha, a.task)
    elif a.card:
        _advance_card_gate(a.card, _commit_sha, a.task,
                            list(a.evidence) + list(a.allow))
    return 0


if __name__ == "__main__":
    sys.exit(main())
