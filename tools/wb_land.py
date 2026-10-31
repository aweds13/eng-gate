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
★ 卡 A318（`T-AG432`）：壳层自带**台账条目守卫** —— `--card` 的卡必须在卡树台账
  （`docs/backlog/*.toml` 分片或 `docs/workbacklog.toml`）里有条目，否则**拒绝落地、
  退 2**。这是 A315/A316 事故的直接钉子：那两张卡落地时台账里根本没有条目，旧链
  「找不到卡就跳过翻 status」⇒ 提交挂了 Task、台账却没记，下一轮全量门禁转红。
  ★ 边界（如实写）：卡树里**没有台账文件** ⇒ 无法核对，打印一句并放行（假仓/沙箱
    没有台账；真仓台账永远在）。`--batch` / `--precheck` 不走这条守卫。
  ★ 守卫在壳层而不在 `pool.landing`：逻辑层不在卡 A318 的 files 域里。
★ 卡 E1（`T-AG443`）：`--preflight` —— 落地**前**的一次零副作用只读体检：
  把「这一趟会踩的线」**全部**说出来（不 fail-fast），11 条判据逐条 ✅/❌ + 一句怎么修，
  0=全绿 / 1=有 ❌。判据本体在 `pool.landing.preflight`（与落地链**同一批函数**，
  不复制第二份）；本壳只做「取参数 → 转发」。`--preflight` 单独给 = 体检完就退；
  与 `--card` / `--batch` 一起给 = 体检绿后**接着落地**（体检只跑这一趟，不重复）。
  判据清单见 `docs/subsystems/ci/事后判据清单.md` A 表。
  ★ 耗时边界（如实）：本仓 `audit_progress.py --all` 自己就要 9~15 s（它的
    封存未跟踪清单逐个文件起 git 进程），所以整趟体检在**本机实测 20 s 上下**；
    卡 §判据 3 写的 15 s 是按 audit 0.6 s 估的，那条**没达标**（见复盘）。
★ 卡 E51 · 段 1（E36）：落地链**默认走台账选测**（壳层给落地链设 `TF_SELECT=1`，
  `scripts/run_gates.py --select` 认同一个开关）。两条硬边界：
  ① **碰判据本体 ⇒ 全量**：本笔改动里出现 `scripts/run_gates.py` / `gates/defs/**` /
     选测工具自身 / pytest 配置 ⇒ 不设开关（判据来源在 `tools/pytest_select.py`，
     壳层只问它，不写第二份规则）；
  ② **读不到 git 改动 ⇒ 全量**（判不出就不省）。
  `--no-select` 关掉这一层（命令行为回到改动前的全量口径）。选测只裁 pytest 的用例集，
  `exit_code` 语义与其余门一个字不动。
"""

from __future__ import annotationsimport argparseimport osimport pathlibimport reimport subprocessimport sysimport tomllibfrom pool import landing as _landing__all__ = [
    "BARE_SUFFIXES",
    "ROOT",
    "bare_names",
    "docs_for_task",
    "guard_card_in_ledger",
    "ledger_card_ids",
    "main",
    "precheck_docs",
    "precheck_main",
    "preflight_main",
    "run_precheck",
    "select_env",
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
    "（文书裸文件名 + check_layers + test_check_skills；红了不进全量门禁）\n"
    "                  --preflight  落地前置体检（11 条判据一次说全；只读；"
    "0=全绿 1=有 ❌）\n"
    "                  --no-select  关掉台账选测（落地链默认走选测；碰判据本体仍强制全量）",
    "★ 卡 E42：`--gate-on cloud|local`（**默认 cloud**；云机不可达 ⇒ 退 2 且"
    "**没有**继续落地，绝不静默回落本机；要本机跑必须显式 `--gate-on local`）"
    " —— 这个开关在落地链的 parser 里，本壳只负责把 `--help` 补全。"
)

#: 落地链给 `scripts/run_gates.py` 的选测开关（与 `--select` 同一个判据，见卡 E51）。
SELECT_ENV = "TF_SELECT"

#: ★ 卡 E77（`T-AG580`）：三条腿要的东西（相对**卡树**根）。本壳只**转发**给检查器，
#: 不含任何现算口径 —— 口径仍只在两个生成器里，检查器是它们的调用方。
#: ★ 卡 E78（`T-AG581`）：目标从一个变两个 —— `docs/INDEX.md` 是同一个病的第二个面
#: （落地链每笔自动补 `docs/changelog.d/{task}.md`，而它按目录数篇数）。这里只用这张表
#: 判「文件在不在」，篇数/行数一概不碰；顺序与 `scripts/check_derived_docs.py` 的
#: `TARGETS` 一致。
DERIVED_CHECKER = "scripts/check_derived_docs.py"
DERIVED_TARGETS = (
    ("docs/subsystems/pool/README.md", "scripts/gen_pool_readme.py"),
    ("docs/INDEX.md", "scripts/gen_doc_index.py"),
)
_DERIVED_DOCS = " / ".join(doc for doc, _ in DERIVED_TARGETS)
_DERIVED_GENS = " / ".join(gen for _, gen in DERIVED_TARGETS)

#: `--precheck` 的 argparse 描述（help 里能看到判据在干什么）。
_PRECHECK_DESC = (
    "落地前置快检：文书里的裸文件名 + scripts/check_layers.py + "
    "tests/test_check_skills.py（红了不进全量门禁；只读，不写任何文件）"
)

#: `--preflight` 的 argparse 描述（卡 E1：11 条判据一次说全）。
_PREFLIGHT_DESC = (
    "落地前置体检（卡 E1）：卡树 HEAD 祖先 / 文书三段齐 / changelog 首行 / 文书预算与指针 / "
    "队列 spec 已进 git / 卡域有产物 / 主树 offender / 队列卡块 status / audit --all / "
    "ruff 快检 / Gates: trailer 模板。★ 只读（不碰任何文件）；0=全绿 1=有 ❌"
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


def _argv_value(argv: list[str], flag: str) -> str | None:
    """`--flag 值` 与 `--flag=值` 两种写法都认；找不到 / 值缺 ⇒ None。"""
    for i, tok in enumerate(argv):
        if tok == flag:
            return argv[i + 1] if i + 1 < len(argv) else None
        if tok.startswith(flag + "="):
            return tok.split("=", 1)[1]
    return None


def preflight_main(argv: list[str]) -> int:
    r"""`--preflight` 的入口（卡 E1）—— 只体检；给了 `--card` / `--batch` 就体检完继续落地。

    用 `parse_known_args`：落地链自己的参数（`--title` / `--evidence` / `--type` …）
    一起给也**不报错** —— 这一趟既体检又落地是常规用法。判据全在
    `pool.landing.preflight`（壳层不重复一份）。
    """
    ap = argparse.ArgumentParser(prog="wb_land.py --preflight", description=_PREFLIGHT_DESC)
    ap.add_argument("--card", help="队列卡号（也用来查它的 task / files）")
    ap.add_argument("--batch", help="批号（与 --card 二选一；体检口径同）")
    ap.add_argument("--tree", default=".", help="卡树（默认当前树）")
    ap.add_argument("--task", default="", help="台账号；不给就查队列里那张卡的 task")
    ap.add_argument("--allow", nargs="*", default=None, help="卡域；不给就用队列 files")
    a, _rest = ap.parse_known_args(argv)
    return _landing.preflight(
        _landing.ROOT / a.tree, task=a.task, card=a.card, batch=a.batch, allow=a.allow,
        no_gate="--no-gate" in argv, commit_only="--commit-only" in argv,
        incremental=("--affected" in argv
                     or any(x.startswith("--changed-from") for x in argv)),
    )


def ledger_card_ids(tree: pathlib.Path) -> set[str] | None:
    """卡树台账里的全部卡号。树里**没有台账** ⇒ None（调用方据此跳过守卫）。

    分片（`docs/backlog/*.toml`）优先，与 `wb_task.py` / `wb_status.py` 同口径。
    台账在但**解析不了** ⇒ 抛 `tomllib.TOMLDecodeError`（守卫把它当「证明不了已登记」，
    同样拒落 —— 台账坏了不该带着它落地）。
    """
    shards_dir = tree / "docs" / "backlog"
    shards = sorted(shards_dir.glob("*.toml")) if shards_dir.is_dir() else []
    single = tree / "docs" / "workbacklog.toml"
    files = shards or ([single] if single.is_file() else [])
    if not files:
        return None
    ids: set[str] = set()
    for f in files:
        data = tomllib.loads(f.read_text(encoding="utf-8"))
        for c in data.get("cards") or []:
            ids.add(str(c.get("id") or ""))
    return ids


def guard_card_in_ledger(argv: list[str], cwd: pathlib.Path | None = None) -> int:
    """卡 A318 钉子：`--card` 的卡不在卡树台账里 ⇒ **拒落退 2**（落地一步没跑）。

    返回 0 = 放行（卡已登记 / 树里没台账无法核对 / 不是单卡模式）。守卫只看
    `--card` 与 `--tree`，不碰落地链的其余参数（解析全权仍在 `pool.landing`）。
    """
    if _argv_value(argv, "--batch") is not None or "--batch" in argv:
        return 0
    card = _argv_value(argv, "--card")
    if not card:
        return 0
    base = pathlib.Path(cwd) if cwd is not None else pathlib.Path.cwd()
    tree_raw = pathlib.Path(_argv_value(argv, "--tree") or ".")
    tree = tree_raw if tree_raw.is_absolute() else base / tree_raw
    try:
        ids = ledger_card_ids(tree)
    except (OSError, tomllib.TOMLDecodeError) as e:
        print(f"[拒落] 台账读不了（{e}）⇒ 证明不了卡 {card} 已登记，停手",
              file=sys.stderr, flush=True)
        return 2
    if ids is None:
        print(f"  [守卫] {tree} 里没有台账 ⇒ 跳过「卡须在台账里有条目」核对", flush=True)
        return 0
    if card not in ids:
        print(f"[拒落] 台账里没有卡 {card} 的条目 —— 先登记（wb_task）再落地。"
              "（卡 A318：A315/A316 落地时台账无条目、提交却挂了 Task 的事故钉子）",
              file=sys.stderr, flush=True)
        return 2
    return 0


def select_env(argv: list[str], cwd: pathlib.Path | None = None) -> tuple[dict[str, str], str]:
    """落地链的选测口径：默认打开，**碰判据本体 / 读不到 git 改动 ⇒ 全量**。

    返回 `({环境变量: 值}, 一句话原因)`；空 dict = 这一趟不启用选测（命令逐字不变）。
    判据来源是 `tools/pytest_select.judge_body_hits`（与 `run_gates --select` 同一张表）。
    """
    if "--no-select" in argv:
        return {}, "--no-select：这一趟跑全量"
    if "--no-gate" in argv or "--commit-only" in argv:
        return {}, "这一趟不跑门禁 ⇒ 选测不适用"
    tree_raw = pathlib.Path(_argv_value(argv, "--tree") or ".")
    base = pathlib.Path(cwd) if cwd is not None else pathlib.Path.cwd()
    tree = tree_raw if tree_raw.is_absolute() else base / tree_raw
    paths = worktree_paths(tree)
    if paths is None:
        return {}, "读不到 git 改动 ⇒ 全量（判不出就不省）"
    try:
        import pytest_select
    except ModuleNotFoundError:  # `python tools/wb_land.py` 时 sys.path[0] 是 tools/
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
        try:
            import pytest_select  # type: ignore[no-redef]
        except ModuleNotFoundError:
            # ★ 半棵树/桩仓库里没有选测工具：判不出就不省（与本函数上面几条同口径），
            #   不许把落地链崩成 traceback —— 那会让『缺一个可选模块』变成『落不了地』。
            return {}, "缺 tools/pytest_select.py ⇒ 退回全量（判不出就不省）"
    hits = pytest_select.judge_body_hits(paths)
    if hits:
        return {}, f"碰判据本体 {hits[:5]} ⇒ 全量（改判据的人要把判据自己检一遍）"
    return {SELECT_ENV: "1"}, f"默认走台账选测（改动 {len(paths)} 条）"


def worktree_paths(tree: pathlib.Path) -> list[str] | None:
    """卡树里**已跟踪改动 + 未跟踪文件**（POSIX 化）；读不到 git ⇒ None。"""
    if not tree.is_dir():
        return None
    done = subprocess.run(  # noqa: S603 —— 参数写死，无 shell
        ["git", "-c", "core.quotepath=false", "status", "--porcelain", "-uall", "--no-renames"],
        cwd=str(tree), capture_output=True, text=True, encoding="utf-8", errors="replace",
        check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if done.returncode != 0:
        return None
    paths: list[str] = []
    for line in (done.stdout or "").splitlines():
        if len(line) < 4:
            continue
        p = line[3:]
        if " -> " in p:
            p = p.split(" -> ", 1)[1]
        p = p.strip().strip('"')
        if p:
            paths.append(p.replace("\\", "/"))
    return paths


def _session_gate(argv: list[str]) -> tuple[int, list[str]]:
    """卡归窗口：别的窗口的卡要 `--take-over` 才让落；没有指纹（工人/CLI）一律放行。"""
    try:
        from tools import wb_session
    except ModuleNotFoundError:  # `python tools/wb_land.py` 时 sys.path[0] 是 tools/
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
        try:
            import wb_session  # type: ignore[no-redef]
        except ModuleNotFoundError:
            # 临时仓 / 只拷了 wb_land.py 的落地桩：这棵树没有会话模块 ⇒ 不设闸，但明说
            print("  [卡归窗口] 这棵树没有 wb_session 模块 ⇒ 跳过会话闸", flush=True)
            return 0, [a for a in argv if a != "--take-over"]

    take_over = "--take-over" in argv
    rest = [a for a in argv if a != "--take-over"]
    card = ""
    for i, token in enumerate(rest):
        if token in {"--card"} and i + 1 < len(rest):
            card = rest[i + 1]
            break
        if token.startswith("--card="):
            card = token.split("=", 1)[1]
            break
    if not card:
        return 0, rest
    ok, msg = wb_session.claim(card, take_over=take_over)
    if not ok:
        print(f"  ★ {msg}", file=sys.stderr)
        return 2, rest
    if msg:
        print(f"  [窗口] {msg}")
    return 0, rest

def _derived_no_checker(root: pathlib.Path, leg: str) -> int:
    """检查器不在时的口径（卡 E77 立、卡 E78 扩成**多目标**）：只看文件在不在，不现算。

    · 这棵树里一个派生目标都没有 ⇒ 没有会过期的派生文档，跳过（退 0）。
    · 有文档却没有配对的生成器 ⇒ **响亮失败**（退 2）：证明不了它是最新的。
    · 文档与生成器都在、只缺检查器 ⇒ 也退 2：**不许**绕过检查器直跑生成器
      （那正是卡 E76 的病 —— 直跑生成器只能证明「生成器跑得动」，证明不了「口径没被绕过」）。
    """
    alive = [(doc, gen) for doc, gen in DERIVED_TARGETS if (root / doc).is_file()]
    if not alive:
        print(f"  [派生文档] {leg}：这棵树里既没有 {_DERIVED_DOCS} 也没有 {_DERIVED_GENS}"
              " ⇒ 没有会过期的派生文档（跳过）", flush=True)
        return 0
    bare = [(doc, gen) for doc, gen in alive if not (root / gen).is_file()]
    if bare:
        for doc, gen in bare:
            print(f"  ★ 派生文档检查失败（{leg}）：这棵树里有 {doc} 却没有 {gen}"
                  " ⇒ 证明不了它是最新的 ⇒ 停手", flush=True)
        return 2
    print(f"  ★ 派生文档检查失败（{leg}）：这棵树里没有 {DERIVED_CHECKER}"
          f" ⇒ 证明不了 {_DERIVED_DOCS} 是最新的 ⇒ 停手", flush=True)
    return 2


def derived_before_land(argv: list[str]) -> int:
    """前置腿（卡 E77）：**开跑前**复核派生文档 —— **只读**，绝不写盘。

    ★ 它解决的是「别在脏树上开跑」：树上已经和现算不一致 ⇒ 拒绝开跑（退 3）、一步都不动。
      下一笔开跑时立刻拦住 E76 那种「落地后才发现脏」的局（那一笔的脏留到下一趟就被看见）。

    ★ 为什么这里**不**写盘：替人改他没让你改的东西不是这条腿的职责；写盘会顺手留下未提交
      改动，反而更脏。要修就由人（或腿① / 腿②）在明确的地方修。

    ★ 位置：`guard_card_in_ledger()` 之后、`_session_gate()` 之前 —— 还没认领窗口、还没改
      环境变量、还没动任何文件，退出去是干净的（不留窗口、不留锁、不留脏）。

    ★ 结构边界（与腿①/腿② 同一条，可证）：本函数与本仓另外两条腿都走**磁盘上的当前代码**
      （子进程调 `scripts/check_derived_docs.py`）；一笔提交若同时改这三处宿主，三条腿都走
      改动前的代码 ⇒ 覆盖不到。不是疏漏，是结构边界。
    """
    tree = _argv_value(argv, "--tree") or "."
    root = (_landing.ROOT / tree).resolve()
    checker = root / DERIVED_CHECKER
    if not checker.is_file():
        return _derived_no_checker(root, "前置腿")
    rc, tail = _run_step((DERIVED_CHECKER, "--check"), root)
    for line in tail.splitlines():
        print(f"  {line}", flush=True)
    if rc == 0:
        return 0
    print("  ★ 落地链开跑前派生文档已与现算不一致 ⇒ 先修好再落"
          "（`python -X utf8 scripts/check_derived_docs.py`；本腿只读，不替你改）。", flush=True)
    return 3


def derived_after_land(argv: list[str]) -> int:
    """腿②（卡 E77）：`pool.landing.main()` **返回之后**再复核一遍派生文档。

    ★ 为什么这一条不在落地链里：卡 E76 落地那一笔改的正是 `tools/pool/landing.py`，
      运行时加载的是**改动前**的代码 ⇒ 落地链的 ⑤′.5 整段没跑，过期文档被一起提交了。
      本壳不 import 任何重算逻辑，只以**子进程**方式调 `scripts/check_derived_docs.py`
      （它自己再调生成器）⇒ 走的是磁盘上的当前代码。

    ★ 触发点（与腿①不同）：只在 `_landing.main()` 返回 **0** 时才跑 —— 那一笔已经提交，
      所以它**抓不住提交之前**；它抓的是「提交之后发现自己过期了」：响亮失败（退 4）
      + 就地把文档修回一致 + 说明重落一条命令即可（提交内容本身就是对的，只是少了这一行）。

    ★ 代价（如实：这是权衡，不是免费）：它跑在提交之后 ⇒ 就地修回只能把修好的 README
      留在**工作区**（未提交改动）。这跟本仓那条硬纪律「落地后主树
      `git status --porcelain -uno` 必须是 0 行」**冲突**。选它的理由只有一条：把一个
      「已经脏了」的局变成**可见的失败 + 一条命令就能补齐**，而不是静默地把错文档留在库里。
      真空口径上的干净要靠前置腿（`derived_before_land`，脏树上根本不开跑）。

    ★ 结构边界（可证）：本函数与 `pool.landing.recount_derived()`、`derived_before_land()`
      互为备份；一笔提交若同时改这三处宿主，三条腿都走改动前的代码 ⇒ 覆盖不到。不是疏漏，
      是结构边界。
    """
    tree = _argv_value(argv, "--tree") or "."
    root = (_landing.ROOT / tree).resolve()
    checker = root / DERIVED_CHECKER
    if not checker.is_file():
        return _derived_no_checker(root, "腿②")
    rc, tail = _run_step((DERIVED_CHECKER, "--check"), root)
    for line in tail.splitlines():
        print(f"  {line}", flush=True)
    if rc == 0:
        return 0
    print("  ★ 派生文档检查失败（腿②/壳层）：这一笔**已经提交**，而派生文档与现算不一致"
          " —— 腿①（落地链 ⑤′.5）没跑到，多半因为这一笔改的正是它自己。", flush=True)
    fix_rc, fix_tail = _run_step((DERIVED_CHECKER,), root)
    for line in fix_tail.splitlines():
        print(f"  {line}", flush=True)
    if fix_rc == 0:
        print("  ✓ 已就地把它修回一致（工作区里是未提交的改动）⇒ 重落一条命令把它带上即可。",
              flush=True)
    else:
        print(f"  ★ 就地修回也失败了（rc={fix_rc}）⇒ 这也是一处要人看的地方。", flush=True)
    return 4


def main(argv: list[str] | None = None) -> int:
    """把 argv 交给 `pool.landing.main`（逻辑全在那边，本壳只多三条壳层分支）。"""
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--preflight" in argv:
        # ★ 卡 E1（T-AG443）：先体检（只读）；红了**不落地**（退 1、一步都没动）。
        #   给了 --card / --batch ⇒ 体检绿后接着落地（判据 5：体检只跑这一趟，不重复）。
        rest = [x for x in argv if x != "--preflight"]
        rc = preflight_main(rest)
        if rc != 0:
            return rc
        if _argv_value(rest, "--card") is None and _argv_value(rest, "--batch") is None:
            return 0  # 只体检、早退
        argv = rest
    if "--precheck" in argv:
        return precheck_main([x for x in argv if x != "--precheck"])
    if "-h" in argv or "--help" in argv:
        # landing 的 parser 打完 help 就 SystemExit(0) —— 壳层参数只能补在它后面。
        try:
            return _landing.main(argv)
        except SystemExit:
            print(_HELP_TAIL)
            return 0
    rc = guard_card_in_ledger(argv)
    if rc:
        return rc
    # ★ 卡 E77：前置腿 —— **开跑前**复核派生文档（只读）。脏树上不落地：一步都不动。
    rc = derived_before_land(argv)
    if rc:
        return rc
    rc, argv = _session_gate(argv)
    if rc:
        return rc
    # ★ 卡 E51 · 段 1（E36）：落地链默认走台账选测；碰判据本体 / 读不到 git ⇒ 不设开关（全量）。
    extra, why = select_env(argv)
    print(f"  [选测] {why}", flush=True)
    argv = [x for x in argv if x != "--no-select"]
    saved = {k: os.environ.get(k) for k in extra}
    os.environ.update(extra)
    try:
        rc = _landing.main(argv)
    finally:
        for key, old in saved.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old
    # ★ 卡 E77：腿② 只在「这一笔落成了（rc == 0）」时才跑 —— 见 derived_after_land 的 docstring。
    if rc == 0:
        rc = derived_after_land(argv)
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
