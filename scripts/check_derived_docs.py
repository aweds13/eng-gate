#!/usr/bin/env python
"""派生文档一致性检查（卡 E77 · T-AG580 立；卡 E78 · T-AG581 扩成**多目标**）：只当壳。

本脚本**不含任何现算口径**。现算口径仍只在两个生成器里：

  · `docs/subsystems/pool/README.md` ← `scripts/gen_pool_readme.py`
    （现算：`tools/pool/` 的读盘 + 模块清单 + 台账）
  · `docs/INDEX.md` ← `scripts/gen_doc_index.py --target docs`
    （现算：`docs/**` 的读盘 + frontmatter）

本脚本是**调用方**，只做两件事：按需真跑一次生成器写盘，再跑一次它自己的 `--check`
复核 —— 判决权全在生成器。★ 卡 E78 的变异钉子钉死这一条：在本脚本里长出
数行数、扫目录、数篇数这类现算口径 ⇒ 钉子必红（判据 2）。

两种模式：
  · 默认（写模式）：逐个目标先真跑生成器（真写盘），再 `--check` 复核 ⇒ 给「能在提交前修好」的腿用；
  · `--check`：只跑生成器的 `--check`，绝不写盘 ⇒ 给「复核」的腿用。

退码：0 一致 / 1 不一致（生成器逐行点名）/ 2 证明不了（树里缺生成器，或生成器自己失败）。
多目标合并口径：任一目标 2 ⇒ 2；否则任一 1 ⇒ 1；否则 0（**不许**把一个目标的不一致吞成跳过）。

★ `docs/INDEX.md` 为什么是**第二个面**（卡 E78）：落地链每笔都会 ⑤′ 自动补
`docs/changelog.d/{task}.md`、② 重写 `docs/changelog.md` —— 二者都在 `docs/**` 下，
`docs/INDEX.md` 是按目录数篇数 + 算总字数的**投影** ⇒ **每落一张卡它过期一次**。
跟 `README.md` 那个面**同一个病**，所以复用同一套三条腿，不另发明一套。

  目标只用 `--target docs`：`复盘/INDEX.md` 归 `scripts/retro/retro_index.py`
  （`gen_doc_index.py --check` 对它打 `[SKIP]`）—— 本脚本**不接管**它。

★ 为什么要这个脚本（卡 E76 的现场）：落地链 `tools/pool/landing.py` 的 ⑤′.5 重算现算文档，
但那一步跑在**它自己的进程**里 —— 一笔提交若改的正是 `tools/pool/landing.py`，运行时加载的
是改动前的代码，⑤′.5 整段不存在，落地就把「翻账后过期一行」的 README 一起提交了（卡 E76
落地后主树写的是 `313 张（301 done / 12 pending）`，而台账已是 302 done / 11 pending）。所以
判据不能只靠「落地链在运行时重算」—— 它自己就是被改的对象。本脚本被**三条腿**各自以
**子进程**方式调用，走的都是磁盘上的当前代码：

| 腿 | 触发点 | 只读/写盘 | 覆盖什么 | 代价 |
|---|---|---|---|---|
| 前置腿 `before_land` | 开跑前 | **只读** | 脏树上不开跑（退 3） | 多一次 `--check` |
| 腿① `landing.py` ⑤′.5 | 翻账后、暂存前 | **写盘** | 提交前就修好 | 自身被改时不跑 |
| 腿② `after_land` | 落成后 | **写盘** | 变成可见失败（退 4） | 留下未提交改动 |

三条腿的展开（表里放不下的细节都在这儿，别在表里挤）：

  · 前置腿：树上已经与现算不一致 ⇒ **拒绝开跑**、一步不动。E76 那种「落地后才发现过期」的脏，
    会拦在**下一笔**开跑时。代价：每趟落地多一次生成器 `--check`（秒级）；它挡不住
    「开跑之后才变脏」那一类 —— 那是腿①/腿② 的活。
  · 腿①：翻账之后、暂存之前 ⇒ 能在**提交前**把文档修好，这一笔是干净的。代价：落地链自己
    就是被改的对象时（卡 E76 的病）整段不跑。
  · 腿②：腿①哑掉时把它变成**可见的失败**（退 4）+ 就地修回 + 说清「重落一条命令即可」。
    ★ 代价（如实，是权衡不是免费）：它跑在提交之后 ⇒ 就地修回只能把修好的文档留在**工作区**
    （未提交改动），这跟本仓那条硬纪律「落地后主树 `git status --porcelain -uno` 必须是 0 行」
    **冲突**。选它的唯一理由：把「已经脏了」变成可见失败而不是静默把错文档留在库里。

★ 加一个目标的**代价**（如实）：每条腿从「一次 `--check`」变成「两次」，落地链 ⑤′.5 的写模式
从「两趟生成器」变成「四趟」（两个目标各写 + 各复核）。实测本仓 `docs/` 三百多篇，
单趟亚秒级 ⇒ 可以接受；要省就得让生成器支持「一次跑多个目标」，那是另一张卡的量。

★★ 结构边界（可证，不是疏漏）：本脚本与 `wb_land.py` 壳层、`tools/pool/landing.py` 互为备份；
若一笔提交同时改这三处宿主，三条腿都走的是改动前的代码 ⇒ 覆盖不到。这不是疏漏，是可证的结构
边界。同一条边界还有
第二面：`--commit-only` 的提交发生在 `pool.landing.main()` **内部**，而它又跳过 ①~⑤（含 ⑤ seal
与全量门禁）⇒ 腿①哑掉时，腿②只能在**提交之后**抓住（响亮失败 + 把文档修回一致 + 让重落
一条命令），而不是提交之前。要真正「提交前」覆盖 `--commit-only`，得让提交动作搬到落地链外面，
那是另一张卡的量（`复盘/卡/卡E77-…md` §缺口）。
"""

from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys
from dataclasses import dataclass

ROOT = pathlib.Path(__file__).resolve().parent.parent
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass(frozen=True)
class Derived:
    """一个派生目标：谁生成它、它自己是谁、生成器要不要带地址参数。"""

    gen: str
    doc: str
    gen_args: tuple[str, ...] = ()
    #: 给人看的一句话：它为什么会过期（写进输出，别让人去翻卡）。
    why: str = ""


#: 目标表（**只有表，没有算法**）。加一条 = 加一个生成器的调用点。
TARGETS: tuple[Derived, ...] = (
    Derived(
        gen="scripts/gen_pool_readme.py",
        doc="docs/subsystems/pool/README.md",
        why="翻账改了台账的 done/pending 分布",
    ),
    Derived(
        gen="scripts/gen_doc_index.py",
        doc="docs/INDEX.md",
        gen_args=("--target", "docs"),
        why="每笔自动补 docs/changelog.d/{task}.md、并重写 docs/changelog.md",
    ),
)


def run_gen(root: pathlib.Path, target: Derived, *args: str) -> subprocess.CompletedProcess[str]:
    """跑一次真生成器（判决权全在它那儿；本函数只转发参数与输出）。"""
    return subprocess.run(
        [sys.executable, "-X", "utf8", target.gen, *target.gen_args, *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        creationflags=NO_WINDOW,
    )


def echo(done: subprocess.CompletedProcess[str], *, indent: str = "  ") -> None:
    """把生成器的输出原样转出去（不加工，不另立口径）。"""
    body = ((done.stdout or "") + (done.stderr or "")).strip()
    for line in body.splitlines():
        print(f"{indent}{line}", flush=True)


def check_one(root: pathlib.Path, target: Derived, *, write: bool) -> int:
    """一个目标：`write=True` ⇒ 写盘 + 复核；`write=False` ⇒ 只复核。退码见模块 docstring。"""
    gen = root / target.gen
    doc = root / target.doc
    if not doc.is_file() and not gen.is_file():
        print(
            f"· 派生文档检查：这棵树里既没有 {target.doc} 也没有 {target.gen}"
            f" ⇒ 没有会过期的派生文档（跳过）",
            flush=True,
        )
        return 0
    if not gen.is_file():
        print(
            f"★ 派生文档检查失败：这棵树里有 {target.doc} 却没有 {target.gen}"
            f" ⇒ 证明不了 {target.doc} 是最新的 ⇒ 停手",
            flush=True,
        )
        return 2
    if not write:
        done = run_gen(root, target, "--check")
        echo(done)
        return 0 if done.returncode == 0 else 1
    made = run_gen(root, target)
    echo(made)
    if made.returncode != 0:
        print(
            f"★ 派生文档检查失败（生成器 rc={made.returncode}）：{target.gen} 写盘就没成功 ⇒ 停手",
            flush=True,
        )
        return 2
    verify = run_gen(root, target, "--check")
    if verify.returncode != 0:
        echo(verify)
        print(
            f"★ 派生文档检查失败：刚写完复核仍不一致（{target.gen} rc={verify.returncode}）⇒ 停手",
            flush=True,
        )
        return 1 if verify.returncode == 1 else 2
    return 0


def check(root: pathlib.Path, *, write: bool) -> int:
    """逐个目标过一遍，按「最坏的那个」退（0 一致 / 1 不一致 / 2 证明不了）。"""
    codes = [check_one(root, target, write=write) for target in TARGETS]
    if 2 in codes:
        return 2
    if 1 in codes:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="派生文档一致性检查（生成器的调用方）")
    parser.add_argument("--check", action="store_true",
                        help="只复核、不写盘（退 1 点名哪几行不一致）")
    parser.add_argument("--root", default=None,
                        help="换一棵树（落地链/壳层/自检用）；默认本仓")
    args = parser.parse_args(argv)
    root = pathlib.Path(args.root).resolve() if args.root else ROOT
    return check(root, write=not args.check)


if __name__ == "__main__":
    sys.exit(main())
