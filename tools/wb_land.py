r"""主控的通用集成器 CLI `tools/wb_land.py`（卡 139 · `T-G237`）—— 只标准库。

为什么有它：本仓记的**最大缺口**（`复盘/外包工具-需求与架构.md` §5 第 1 条 / 外部审查 §四）
就是「**收口工具还在 scratch**」—— `gates/diag/_integrate.py` 是 **gitignore 的 scratch**，
别的窗口 / 别的机器拿得到队列、**拿不到把一笔卡收成提交的那条链**（错配③：权威与工具位置错配）。
卡 139 把它搬进 git：**权威副本**＝ `tools/pool/landing.py`（模块 `pool.landing`）。
本文件是**命令行壳**，与 `tools/wb_task.py` / `tools/wb_stage_card.py` 同款，
只做「取参数 → 转发给逻辑层」这一件事。

八步链（顺序固定，任一步失败就停，绝不带着红门禁提交）：
    ⓪ 回退派生物（卡 150：幂等重跑；`--no-reset` 可关，`--commit-only` 不回退）
    ① 卡树迁到主树 HEAD  ② 文档件  ③ sync_counts  ④ 门禁锁 + 门禁  ⑤ seal
    ⑥ 白名单 → add → commit  ⑦ audit → release → ff 合流
    ⑧ 复核落盘（卡 184 · 追加三）：wb_review.py --rev <新提交> --json → gates/review/<task>.json

用法：
    python -X utf8 tools/wb_land.py --card 139 --tree .wt/landing --task T-G237 \
        --title "…" --group ENGINEERING --evidence a.py b.py --allow a.py b.py \
        --port-base 9034

★ `--card` 与 `--batch` **必须恰好给一个**（批号也能当门禁锁的标签）；
  `--no-gate`（只在文档件/白名单上试跑）与 `--commit-only`（门禁已绿、封存没变）两个模式
  会在 trailer 里**如实写**「这一笔没跑门禁」/「复用已绿的那一趟」—— 不许借这行冒充跑过。
★ 卡 184（T-G284）：`--affected <路径…>` / `--changed-from <REV>` —— 增量门禁开关（**默认关**，
  给了才少跑）。三条强制全量照咬：① 碰 scripts/**/tools/**/gates/** ⇒ 全量；② 空计划 ⇒ 全量；
  ③ 今天没跑过全量 ⇒ 全量（每日一次兜底，不按笔数）。增量那一趟 trailer 写「非全量」字样，
  gates/last.json 的 affected 块照写 —— 卡 147 护栏会咬（把增量产物当全量交 ⇒ 红）。
  `--no-review` 跳过 ⑧ 复核落盘（默认会跑）。
★ 卡 A301（`T-AG415`）：壳层自带**落地前置快检** `--precheck`（判据在本文件 ——
  landing 那边只是转发目标，改不动它就不许在它里面塞第二套判据）。它做两件事：
  ① 扫 ② 生成的两份文书（`gates/diag/_text_<台账号>.md` 与 `docs/changelog.d/<台账号>.md`）
  里**反引号包着的裸文件名**（不含 `/` 或 `\`、以 `.md` / `.toml` / `.py` 结尾 ⇒
  `check_layers` 会把 `.md` 那种拿去找文件、找不到就判断链）；
  ② 再跑两道具级检查：`scripts/check_layers.py` 与 `tests/test_check_skills.py`。
  ①红 ⇒ 立刻退 1、②③ 一次都不跑；②③ 红 ⇒ 退 2。**不进全量门禁**是本工具的卖点
  （秒级失败别烧 4–8 分钟），**不是**放宽判据 —— 全量门禁照跑。
  ★ 边界（如实记）：把快检**接进**落地链 ② 之后、④ 之前的那个钩子在
  `tools/pool/landing.py`，不在卡 A301 的 files 域 ⇒ 本卡只交工具与入口，
  接线留给下一张卡；在此之前由落地的人先跑一句 `--precheck <台账号>`。
★ 旧的 `gates/diag/_integrate.py` 保留成**临时转发壳**（打印一行后转发到本文件）。
"""

from __future__ import annotations

import argparse
import os
import pathlib
import re
import subprocess
import sys

from pool import landing as _landing

__all__ = [
    "BARE_SUFFIXES",
    "ROOT",
    "bare_names",
    "docs_for_task",
    "main",
    "precheck_docs",
    "precheck_main",
    "run_precheck",
]

#: 仓库根（本文件在 `tools/` 下）。
ROOT = pathlib.Path(__file__).resolve().parent.parent

#: 裸文件名要认的后缀（卡 A301）。`check_layers` 只咬 `.md`；`.toml` / `.py` 是同一族毛病
#: （文书里想指「某个文件」却给不出位置 ⇒ 换个窗口就找不到），一并挡在门禁之前。
BARE_SUFFIXES = (".md", ".toml", ".py")

#: 反引号里的一段文字（与 `check_layers` 的取法同族：**空白即断**，`a.md b.md` 是两个词）。
_BACKTICK = re.compile(r"`([^`\s]+)`")

#: 第二段的两道具级检查（★ 判据本体不重写，只调用既有那两道；前置路径相对仓库根）。
PRECHECK_STEPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("check_layers", ("scripts/check_layers.py",)),
    ("check_skills", ("-m", "pytest", "tests/test_check_skills.py", "-q",
                      "--no-cov", "-p", "no:cacheprovider")),
)

#: 每道子检查的硬超时（秒）—— 快检的卖点是十几秒，卡住就当红（别把整趟挂死）。
STEP_TIMEOUT = 180

#: `--help` 末尾补的一行：壳层参数不在 landing 的 parser 里，不补就等于没入口。
_HELP_TAIL = (
    "壳层参数（不转发给落地链）：--precheck <台账号|文书路径…>  落地前置快检"
    "（文书裸文件名 + check_layers + test_check_skills；红了不进全量门禁）"
)

#: `--precheck` 的 argparse 描述（help 里能看到判据在干什么）。
_PRECHECK_DESC = (
    "落地前置快检：文书里的裸文件名 + scripts/check_layers.py + "
    "tests/test_check_skills.py（红了不进全量门禁；只读，不写任何文件）"
)


def _rel(path: pathlib.Path, root: pathlib.Path | None) -> str:
    """报告里打的路径 —— 能相对仓库根就相对（绝对路径在回报里读不出位置）。"""
    base = pathlib.Path(root) if root is not None else ROOT
    try:
        return pathlib.Path(path).resolve().relative_to(base.resolve()).as_posix()
    except (ValueError, OSError):
        return pathlib.Path(path).as_posix()


def docs_for_task(task: str, root: pathlib.Path | None = None) -> list[pathlib.Path]:
    """本次新增的**两份文书**（卡 A301 的检查面 —— 只扫这两份，不扫老文档）。

    - `gates/diag/_text_<台账号去横线>.md`：② 读的那份三段文书（人写的）；
    - `docs/changelog.d/<台账号>.md`：② 生成的 changelog 片段（`stage_card` 写的）。

    台账号照 `pool.landing` 的口径去横线（`T-AG415` → `_text_TAG415.md`）。
    """
    base = pathlib.Path(root) if root is not None else ROOT
    slug = task.replace("-", "")
    return [
        base / "gates" / "diag" / f"_text_{slug}.md",
        base / "docs" / "changelog.d" / f"{task}.md",
    ]


def bare_names(
    text: str, root: pathlib.Path | None = None
) -> list[tuple[int, str]]:
    """反引号里的**裸文件名** —— 返回 `[(行号, 词)]`（行号从 1 起，指给文书作者）。

    判据（卡 A301）：不含 `/` 或 `\\`，且以 `.md` / `.toml` / `.py` 结尾。
    ★ 为什么不查「这个文件在不在」：裸文件名**不是路径**，在任何一棵树里都可能"碰巧存在"
      （`NOTES.md`、`limits.md` 那种就是 A300 连红两轮的真凶）—— 要的是**全路径**。
    ★ 唯一的例外（`root` 给了才算）：**仓根下真有这个文件** ⇒ 它本身就是唯一合法的写法
      （根级文件的"全路径"就是裸名），这时放行 —— 早失败工具比门**还严**只会造出假红，
      违背本卡的动机。根上没有 ⇒ 照红（`limits.md` / `NOTES.md` 这一族正是如此）。
    """
    base = pathlib.Path(root) if root is not None else None
    hits: list[tuple[int, str]] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for m in _BACKTICK.finditer(line):
            word = m.group(1)
            if "/" in word or "\\" in word:
                continue
            if not word.lower().endswith(BARE_SUFFIXES):
                continue
            if base is not None and (base / word).is_file():
                continue
            hits.append((lineno, word))
    return hits


def precheck_docs(
    paths: list[pathlib.Path], root: pathlib.Path | None = None
) -> list[str]:
    """只扫文书的**第一段**快检（不跑子进程）—— 空列表 = 干净。

    ★ 文件不存在 ⇒ **跳过、不算错**：`docs/changelog.d/<台账号>.md` 要 ② 之后才有，
      快检也允许人先拿 `_text` 那份单独跑一遍。
    """
    problems: list[str] = []
    for raw in paths:
        p = pathlib.Path(raw)
        if not p.is_file():
            continue
        body = p.read_text(encoding="utf-8", errors="replace")
        for lineno, word in bare_names(body, root if root is not None else ROOT):
            problems.append(
                f"{_rel(p, root)}:{lineno} 反引号里是裸文件名 {word}"
                "（check_layers 会把它当路径引用 ⇒ 改成仓内全路径，或去掉反引号）"
            )
    return problems


def _run_step(cmd: tuple[str, ...], root: pathlib.Path) -> tuple[int, str]:
    """跑一道子检查（**不弹窗**、显式 utf-8、硬超时）。返回 `(退出码, 末尾输出)`。"""
    env = {**os.environ, "PYTHONUTF8": "1"}
    shim = root / "tools" / "sandbox_shim"
    if shim.is_dir():
        env["PYTHONPATH"] = str(shim)
    try:
        r = subprocess.run(
            [sys.executable, "-X", "utf8", *cmd], cwd=str(root), env=env,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=STEP_TIMEOUT,
            # ★ 不 import `pool.no_window`：`tests/test_wb_land.py` 的沙箱 `_NEW_TOOLS`
            #   不拷 `pool/no_window.py`（那张清单不在卡 A301 的域里）⇒ 少一份就 ImportError。
            #   口径与 `tools/pool/landing.py` 同款：`getattr(subprocess, …)`（卡 148 的不弹窗）。
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        return 124, f"超时（{STEP_TIMEOUT}s）—— 快检不该这么慢，当红"
    lines = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
    return r.returncode, "\n".join(lines[-8:])


def run_precheck(
    paths: list[pathlib.Path], root: pathlib.Path | None = None, *,
    out=None,
) -> int:
    """落地前置快检（卡 A301）：① 文书裸文件名 → ② check_layers → ③ test_check_skills。

    退出码：`0` 全绿（该去跑全量门禁）；`1` 文书里有裸文件名（**②③ 一次都不跑**）；
    `2` ②或③红。★ 没有「跳过」开关：要绕过它，只能不调用它（`--no-gate` 那一档本就不跑门）。
    """
    base = pathlib.Path(root) if root is not None else ROOT
    say = out or (lambda line: print(line, flush=True))
    files = [pathlib.Path(p) for p in paths]
    say("=== 落地前置快检（卡 A301：文书裸文件名 + 两道秒级检查）===")
    hits = precheck_docs(files, base)
    if hits:
        for line in hits:
            say(f"  [红] {line}")
        say(f"  ★ 文书里有 {len(hits)} 处裸文件名 ⇒ **停手**（全量门禁一步没跑）")
        return 1
    say(f"  ✓ 文书干净（{len(files)} 份扫过；不存在的跳过）")
    for name, cmd in PRECHECK_STEPS:
        rc, tail = _run_step(cmd, base)
        if rc != 0:
            say(f"  [红] {name} 退出码 {rc}：")
            for line in tail.splitlines():
                say(f"    {line}")
            say(f"  ★ {name} 不绿 ⇒ **停手**（全量门禁一步没跑）")
            return 2
        say(f"  ✓ {name} 绿")
    say("  ✓ 前置快检全绿（去跑全量门禁 ④；本工具**不**代替它）")
    return 0


def precheck_main(argv: list[str] | None = None) -> int:
    """`--precheck` 的入口：`wb_land.py --precheck <台账号|文书路径…> [--root <仓库根>]`。

    目标写法：**台账号**（`T-AG415`）⇒ 换成本次那两份文书；**路径**（`*.md`）⇒ 原样扫。
    """
    ap = argparse.ArgumentParser(prog="wb_land.py --precheck", description=_PRECHECK_DESC)
    ap.add_argument("targets", nargs="+", help="台账号（如 T-AG415）或文书路径（可多个）")
    ap.add_argument("--root", default=None, help="仓库根（默认本文件上一级）")
    a = ap.parse_args(argv)
    base = pathlib.Path(a.root) if a.root else ROOT
    paths: list[pathlib.Path] = []
    for t in a.targets:
        if t.lower().endswith(BARE_SUFFIXES):
            p = pathlib.Path(t)
            paths.append(p if p.is_absolute() else base / p)
        else:
            paths.extend(docs_for_task(t, base))
    return run_precheck(paths, base)


def main(argv: list[str] | None = None) -> int:
    """把 argv 交给 `pool.landing.main`（逻辑全在那边，本壳只多两条壳层分支）。"""
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--precheck" in argv:
        return precheck_main([x for x in argv if x != "--precheck"])
    if "-h" in argv or "--help" in argv:
        # landing 的 parser 打完 help 就 SystemExit(0) —— 壳层参数只能补在它后面。
        try:
            return _landing.main(argv)
        except SystemExit:
            print(_HELP_TAIL)
            return 0
    return _landing.main(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
