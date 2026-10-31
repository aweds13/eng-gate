#!/usr/bin/env python
"""派生文档一致性检查（卡 E77 · T-AG580）：只当「跑生成器 + 跑 --check」的壳。

本脚本**不含任何现算口径**。现算口径仍只在 `scripts/gen_pool_readme.py`（它从 `tools/pool/`
的现读盘与那份模块清单里现算）。本脚本是**调用方**，只做两件事：按需真跑一次生成器写盘，
再跑一次它自己的 `--check` 复核 —— 判决权全在生成器。

两种模式：
  · 默认（写模式）：先真跑生成器（真写盘），再 `--check` 复核 ⇒ 给「能在提交前修好」的腿用；
  · `--check`：只跑生成器的 `--check`，绝不写盘 ⇒ 给「复核」的腿用。

退码：0 一致 / 1 不一致（生成器逐行点名）/ 2 证明不了（树里没有生成器，或生成器自己失败）。

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

★★ 结构边界（可证，不是疏漏）：本脚本与 `wb_land.py` 壳层、`tools/pool/landing.py` 互为备份；
若一笔提交同时改这三处宿主，三条腿都走的是改动前的代码 ⇒ 覆盖不到。这不是疏漏，是可证的结构
边界。同一条边界还有
第二面：`--commit-only` 的提交发生在 `pool.landing.main()` **内部**，而它又跳过 ①~⑤（含 ⑤ seal
与全量门禁）⇒ 腿①哑掉时，腿②只能在**提交之后**抓住（响亮失败 + 把 README 修回一致 + 让重落
一条命令），而不是提交之前。要真正「提交前」覆盖 `--commit-only`，得让提交动作搬到落地链外面，
那是另一张卡的量（`复盘/卡/卡E77-…md` §缺口）。
"""

from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
GEN_REL = "scripts/gen_pool_readme.py"
DOC_REL = "docs/subsystems/pool/README.md"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def run_gen(root: pathlib.Path, *args: str) -> subprocess.CompletedProcess[str]:
    """跑一次真生成器（判决权全在它那儿；本函数只转发参数与输出）。"""
    return subprocess.run(
        [sys.executable, "-X", "utf8", GEN_REL, *args],
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


def check(root: pathlib.Path, *, write: bool) -> int:
    """`write=True` ⇒ 写模式（写盘 + 复核）；`write=False` ⇒ 只复核。退码见模块 docstring。"""
    if not (root / DOC_REL).is_file() and not (root / GEN_REL).is_file():
        print(
            f"· 派生文档检查：这棵树里既没有 {DOC_REL} 也没有 {GEN_REL}"
            f" ⇒ 没有会过期的派生文档（跳过）",
            flush=True,
        )
        return 0
    if not (root / GEN_REL).is_file():
        print(
            f"★ 派生文档检查失败：这棵树里没有 {GEN_REL}"
            f" ⇒ 证明不了 {DOC_REL} 是最新的 ⇒ 停手",
            flush=True,
        )
        return 2
    if not write:
        done = run_gen(root, "--check")
        echo(done)
        return 0 if done.returncode == 0 else 1
    made = run_gen(root)
    echo(made)
    if made.returncode != 0:
        print(
            f"★ 派生文档检查失败（生成器 rc={made.returncode}）：{GEN_REL} 写盘就没成功 ⇒ 停手",
            flush=True,
        )
        return 2
    verify = run_gen(root, "--check")
    if verify.returncode != 0:
        echo(verify)
        print(
            f"★ 派生文档检查失败：刚写完复核仍不一致（{GEN_REL} rc={verify.returncode}）⇒ 停手",
            flush=True,
        )
        return 1 if verify.returncode == 1 else 2
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
