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
  ④ 拿门禁锁（段由 --port-base 给）→ 跑门禁（★ 带 1800s 硬超时）→ 红了就 release + 退出
  ⑤ --seal
  ⑥ 白名单核对（卡的文件 + 文档三件 + gates/last.json + gates/reuse.json）
     → 显式 git add → commit（四 trailer）
  ⑦ audit_progress.py → 释放锁 → 主树 ff 合流

用法：
  python -X utf8 tools/wb_land.py --card 096 --tree .wt/mech2 --task T-G191 \
      --title "机器替代 ③+④：台账归类建议器 + 卡/样板生成" --type feat --group ENGINEERING \
      --evidence tools/tf_group.py tests/test_tf_group.py \
      --allow tools/tf_group.py tests/test_tf_group.py \
      --port-base 9034 --refs "T-G182"
"""
from __future__ import annotations

import argparse
import contextlib
import os
import pathlib
import subprocess
import sys

# ★ 2026-10-02：ROOT 原来是硬编码绝对路径（换机器即碎）。本位置 `tools/pool/` 上两级 = 仓库根，
#   与旧位置 `gates/diag/` 的 `parents[2]` 结果一致 ⇒ 这一行搬过来不用改（已核对）。
ROOT = pathlib.Path(__file__).resolve().parents[2]
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
    ap.add_argument("--refs", default="")
    ap.add_argument("--no-gate", action="store_true", help="★ 只在文档件/白名单上试跑时用")
    ap.add_argument("--no-reset", action="store_true",
                    help="关掉开跑时的「⓪ 回退派生物」；★ **默认会回退**"
                         "（把上一趟残留的派生物/记账产物退回 HEAD，幂等重跑用）")
    ap.add_argument("--commit-only", action="store_true",
                    help="⑥ 起接着走：门禁已绿、封存没变时用（跳过 ①②③④⑤）")
    a = ap.parse_args(argv)
    if bool(a.card) == bool(a.batch):
        print("★ `--card` 与 `--batch` 必须**恰好给一个**")
        return 2
    lock_label = a.card or a.batch   # 门禁锁的标签（批号也行）

    wt = ROOT / a.tree
    text = pathlib.Path(str(TEXT).format(task=a.task.replace("-", "")))
    assert text.is_file(), f"缺文档件：{text}"

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
                return 3
            run(["git", "checkout", main_head], cwd=wt)
        print("  树内 HEAD =", git("rev-parse", "--short", "HEAD", cwd=wt))
        print("  改动：")
        print("   ", git("status", "--porcelain", cwd=wt).replace("\n", "\n    "))

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

        if not a.no_gate:
            print(f"=== ④ 锁（段 {a.port_base}）→ 门禁（硬超时 1800s）===")
            r = subprocess.run([sys.executable, "-X", "utf8", "gates/diag/gate_lock.py",
                                "acquire", "--card", lock_label, "--wait", "5400",
                                "--stale-after", "3600"],
                               cwd=str(wt), env={**os.environ, **env},
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
            print(r.stdout.strip()[-400:])
            try:
                r = subprocess.run([sys.executable, "-X", "utf8", "scripts/run_gates.py"],
                                   cwd=str(wt), env={**os.environ, **env},
                                   capture_output=True, text=True,
                                   encoding="utf-8", errors="replace",
                                   timeout=1800)
                out, rc = (r.stdout or ""), r.returncode
            except subprocess.TimeoutExpired as exc:   # ★ 门禁卡死：硬超时当红，别把锁留着
                out = (exc.stdout or b"").decode("utf-8", "replace") \
                    if isinstance(exc.stdout, bytes) else (exc.stdout or "")
                rc = 124
            tail = out.strip().splitlines()[-22:]
            print("\n".join(tail))
            print(f"★★ 门禁退出码 = {rc}（124 = 硬超时掐的）")
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
            print("=== ⑤ seal ===")
            sealed = run([sys.executable, "-X", "utf8", "scripts/run_gates.py", "--seal"], cwd=wt)
            print(sealed.stdout.strip()[-300:])

    if a.commit_only:
        print("=== ①~⑤ 跳过（--commit-only：门禁已绿、封存没变）===")
    print("=== ⑥ 白名单 → add → commit ===")
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

    # ★ 2026-10-02 修（来路：GLM-5.3 审查卡 124 的 **2.4**）：这一行原来**无条件**写
    #   「全量门禁绿 + seal」，而本脚本有 `--no-gate`（跳过 ④⑤）与 `--commit-only`（跳过 ①~⑤）
    #   两个模式 ⇒ **工具自己在伪造门禁结论**（违反铁律 4「不许伪造完成」，且 `audit` 只查 trailer
    #   存在性、查不出真伪）。现在按**实际模式**写：跳过门禁的那两条路，谁都不许借这行冒充跑过。
    if a.no_gate:
        gates_line = "Gates: ★ 本笔**没跑门禁**（--no-gate）—— 这行不是门禁结论，别当证据用"
    elif a.commit_only:
        gates_line = "Gates: 复用已绿的那一趟（--commit-only，封存未变）；真读数见 gates/last.json"
    else:
        gates_line = "Gates: 全量门禁绿 + seal（跑前先拿门禁锁；★ 提交之后再跑 audit）"
    msg = (f"{a.type}({a.scope}): {a.title}（{a.task}）\n\n"
           + changelog_body(text)
           + f"\n\nTask: {a.task}\n"
           + (f"Refs: {a.refs}\n" if a.refs else "")
           + f"Ledger: 新增 {a.task}（{a.group}/done，{len(a.evidence)} 条证据）；"
           + "done 的数字以 sync_counts.py 的实测输出为准\n"
           + gates_line + "\n")
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
        return 2
    print("  ff 合流完成：主树 →", git("rev-parse", "--short", "HEAD"))
    print("  主树 HEAD =", git("rev-parse", "--short", "HEAD"), "| -uno =",
          len([x for x in git("status", "--porcelain", "-uno").splitlines() if x.strip()]), "行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
