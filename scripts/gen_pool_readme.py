r"""pool 项目书的「代码边际 / 度量」两段由机器生成（卡 F11 · `T-AG559`）。

## 它治什么

`docs/subsystems/pool/README.md` 的 §1 体量表与 §2 度量表原先手抄：记的是文件系统的
事实（模块个数、行数、队列卡数、批目录份数、日志份数），却由人维护 —— 手抄的失败模式
不是「抄错一个字」，是**必然过期**。卡 F11 实测：表里写 17 个 py / 7143 行，实为
36 个 py / 13817 行；40 个文件里 21 个一个都没进表。所以数字改成现算。

## 它改哪里、不改哪里

只重写一个文件里两处标记**之间**的内容：

    <!-- pool-margin:begin -->
    ……（表头句 + §1 模块表 + 两张账段 + §2 度量表：本脚本生成）……
    <!-- pool-margin:end -->

标记之外的字节一个都不动（文件头、§3 决策、§4 卡表、§5 边界与表 A/B/C、
`## 2. 度量` 后面那两条口径）。所以可以放心跑：不计数的地方它不碰。

## 两个真源

- `tools/pool/` 的**文件与行数**：现读盘，口径 `path.read_bytes().count(b"\n")`
  （与本仓既有实测一致：36 个 py / 13817 行）。
- **职责 / 命令壳**：`docs/subsystems/pool/modules.toml`（人写 —— 机器算不出来那两列）。

仓里有、清单里没有的模块 ⇒ 退 1 并**点名**（不许静默跳过：漏一个模块，读者就以为
它不存在）；清单里有、仓里没有的 ⇒ 同样退 1（清单自己成了死指针）；`duty` 空串 ⇒
退 1（空职责等于没写）。

## 日期为什么不是「今天」

表头句要写生成日期，但**日期每天变会让 `--check` 每天假红**（本仓的老毛病：拿可漂移量
当阈值）。所以口径是「**这块内容最后一次变化的那天**」：把现有块里的日期抹掉后与现算块
逐字比对 —— 一致就沿用现有日期（没改动的仓永远是绿的），不一致才取今天。

## 用法

    python -X utf8 scripts/gen_pool_readme.py            # 写回 README（只写这一个文件）
    python -X utf8 scripts/gen_pool_readme.py --check    # 只判：一致退 0，不一致退 1 逐行点名
    python -X utf8 scripts/gen_pool_readme.py --root <树>  # 换一棵树（自检用）

退码：0 一致 / 1 不一致或清单有问题 / 2 目标里没有标记（不知道该往哪儿写）。

★ 判据不在本文件：每个模块管什么的真源是它自己的 docstring，本脚本只把
`modules.toml` 里那句话搬进表里。
"""

from __future__ import annotations

import argparse
import datetime
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parent.parent
README_REL = "docs/subsystems/pool/README.md"
MODULES_REL = "docs/subsystems/pool/modules.toml"
BACKLOG_REL = "docs/workbacklog.toml"
POOL_REL = "tools/pool"
DIAG_REL = "gates/diag"
BEGIN = "<!-- pool-margin:begin -->"
END = "<!-- pool-margin:end -->"
ALLOWED_KEYS = frozenset({"name", "duty", "cli"})
DATE_TOKEN = "<生成日期>"
_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2}) 现算")
DIFF_LIMIT = 8

#: 两处标记之间那段**不随数字漂**的文字。它本来在 README 里手写；因为落在标记内，
#: 一次重写就会丢，所以必须由本脚本原样吐出来 —— **要改这段话就改这里**（改 README 无效）。
LEDGERS: tuple[str, ...] = (
    "两张**账**分开住，这是理解本子系统的关键：",
    "",
    "| 账 | 文件 | 记什么 | 真源模块 |",
    "|---|---|---|---|",
    "| 租约账 | 主树的 `gates/diag/pool-registry.json` | 谁占了哪棵树、哪个冲突域"
    " | `tools/pool/registry.py` |",
    "| 任务账 | 主树的 `gates/diag/batch/<任务>.toml` + `<任务>.json` | 这个任务要哪些卡、"
    "谁交了申请 | `tools/pool/task.py` |",
    "| 账号账 | **仓外** `infra/pool/accounts.toml`（`TF_ACCOUNTS_TOML` 可覆盖） | "
    "我有哪些号、每号批了哪些模型、额度最后观测是什么时候 | `tools/pool_accounts.py` |",
    "",
    "> 前两张都锚在**主工作树**（`git rev-parse --git-common-dir` 的父目录），不在卡树 ——",
    "> 卡树里的 `gates/diag/` 是 gitignore 的，写进去等于没写"
    "（`tools/pool/registry.py:72`、`tools/pool/task.py:119`）。",
    "> 账号账**故意在仓外**：只存凭据指针（`~/.codeartsdoer/pool.env` 之类），不存凭据本身；",
    "> 没有 git 兜底，所以写入一律原子替换，删号打墓碑（`tools/pool_accounts.py` 的"
    " `save_ledger()`）。",
)


def count_lines(path: Path) -> int:
    """行数口径：数 `\\n`（与本仓既有实测一致，不看文件末尾有没有换行）。"""
    return path.read_bytes().count(b"\n")


def scan_pool(pool_dir: Path) -> dict[str, int]:
    """`tools/pool/` 下每个 py / toml 文件的行数（键 = 文件名，不含目录）。"""
    found: dict[str, int] = {}
    for suffix in (".py", ".toml"):
        for path in sorted(pool_dir.glob(f"*{suffix}")):
            if path.is_file():
                found[path.name] = count_lines(path)
    return found


def load_manifest(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    """读职责真源；返回 (条目, 问题)。问题不是异常 —— 要全部报出来再退 1。"""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return [], [f"读不了 {MODULES_REL}：{exc}"]
    except tomllib.TOMLDecodeError as exc:
        return [], [f"{MODULES_REL} 不是合法 TOML：{exc}"]
    raw_items = data.get("module")
    if not isinstance(raw_items, list) or not raw_items:
        return [], [f"{MODULES_REL} 里没有任何 [[module]] —— 职责真源是空的"]
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    problems: list[str] = []
    for position, raw in enumerate(raw_items, start=1):
        if not isinstance(raw, dict):
            problems.append(f"{MODULES_REL} 第 {position} 条不是表，读不出 name/duty/cli")
            continue
        extra = sorted(set(raw) - ALLOWED_KEYS)
        missing = sorted(ALLOWED_KEYS - set(raw))
        if extra or missing:
            problems.append(
                f"{MODULES_REL} 第 {position} 条的键不对：多 {extra or '无'}，缺 {missing or '无'}"
            )
        name = str(raw.get("name", "")).strip()
        duty = str(raw.get("duty", "")).strip()
        cli = str(raw.get("cli", "")).strip()
        if not name:
            problems.append(f"{MODULES_REL} 第 {position} 条没有 name")
            continue
        if name in seen:
            problems.append(f"{MODULES_REL}: {name} 出现了两次 —— 一条模块只该有一行职责")
        seen.add(name)
        if not duty:
            problems.append(
                f"{MODULES_REL}: {name} 的 duty 是空串 —— 空职责等于没写"
                "（读者没法据此判断该不该改它）"
            )
        elif "|" in duty:
            problems.append(f"{MODULES_REL}: {name} 的 duty 里有 '|'，会把表格撑坏")
        if not cli:
            problems.append(f'{MODULES_REL}: {name} 的 cli 是空串 —— 没有命令壳就写 "无"')
        elif "|" in cli:
            problems.append(f"{MODULES_REL}: {name} 的 cli 里有 '|'，会把表格撑坏")
        entries.append({"name": name, "duty": duty, "cli": cli})
    return entries, problems


def cross_check(entries: list[dict[str, str]], found: dict[str, int]) -> list[str]:
    """清单 ↔ 盘子两向对账：漏的、多的都点名。"""
    listed = {entry["name"] for entry in entries}
    problems = [
        f"{POOL_REL}/{name} 在仓里，但 {MODULES_REL} 没写它"
        " —— 漏一个模块，读者就以为它不存在"
        for name in sorted(set(found) - listed)
    ]
    problems += [
        f"{MODULES_REL} 写了 {name}，但 {POOL_REL}/ 里没有这个文件 —— 清单自己成了死指针"
        for name in sorted(listed - set(found))
    ]
    return problems


def main_tree_root(tree_root: Path) -> tuple[Path, str | None]:
    """主工作树（`git rev-parse --git-common-dir` 的父目录）；算不出就退回本树 + 一句原因。

    为什么不用本树：卡树里的 `gates/diag/` 是 gitignore 的，度量会读成 0。
    与 `tools/pool/registry.py::main_tree_root()` 同口径（相对路径按 git 的 cwd 解析）。
    """
    try:
        done = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=str(tree_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as exc:
        return tree_root, f"git 起不来（{exc.__class__.__name__}）"
    if done.returncode != 0:
        return tree_root, "git rev-parse 非零（这棵树不是 git 工作树）"
    out = done.stdout.strip()
    if not out:
        return tree_root, "git rev-parse 没吐路径"
    common = Path(out)
    if not common.is_absolute():
        common = tree_root / common
    try:
        return common.resolve().parent, None
    except OSError as exc:
        return tree_root, f"解析不出主工作树（{exc.__class__.__name__}）"


def diag_metrics(main_root: Path) -> tuple[int, int, list[str]]:
    """批预声明份数 + 派活日志份数（都在主工作树的 `gates/diag/` 下）。"""
    diag = main_root / DIAG_REL
    if not diag.is_dir():
        return 0, 0, [f"{DIAG_REL}/ 不存在 —— 批预声明与派活日志都读成 0"]
    batch_dir = diag / "batch"
    batch = len(list(batch_dir.glob("*.toml"))) if batch_dir.is_dir() else 0
    logs = [path for path in diag.glob("wb-*.jsonl") if path.name != "wb-usage.jsonl"]
    return batch, len(logs), []


def backlog_metrics(root: Path, main_root: Path) -> tuple[int, int, int, list[str]]:
    """队列卡数：读 `docs/workbacklog.toml` 的 `cards`，按 `status` 分 done / pending。"""
    for base in (root, main_root):
        path = base / BACKLOG_REL
        if not path.is_file():
            continue
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            return 0, 0, 0, [f"读不了 {BACKLOG_REL}：{exc}"]
        cards = data.get("cards") or []
        counter = Counter(
            str(card.get("status", "")).strip() for card in cards if isinstance(card, dict)
        )
        done = counter.get("done", 0)
        pending = counter.get("pending", 0)
        warns = [] if base == root else [f"本树没有 {BACKLOG_REL}，读的是主树那份"]
        if done + pending != len(cards):
            warns.append(
                f"{BACKLOG_REL} 里有 {len(cards) - done - pending} 张卡的状态不是 done/pending"
            )
        return len(cards), done, pending, warns
    return 0, 0, 0, [f"两棵树都没有 {BACKLOG_REL} —— 队列卡数读不出来"]


def render_block(
    entries: list[dict[str, str]],
    found: dict[str, int],
    batch: int,
    cards: tuple[int, int, int],
    logs: int,
) -> list[str]:
    """两处标记之间的全部行（日期处留 `DATE_TOKEN`，最后由 `resolve_date` 定）。"""
    py_files = sorted(name for name in found if name.endswith(".py"))
    total = sum(found[name] for name in py_files)
    lines = [
        f"`{POOL_REL}/` = {len(py_files)} 个 py（{len(py_files) - 1} 个模块 + `__init__.py`）、"
        f"**{total} 行**（`wc -l {POOL_REL}/*.py`，{DATE_TOKEN} 现算）。",
        "",
        "每个模块都可 import（判据在库里），每个 CLI 都是**薄壳**（只解析参数 + 打印）。",
        "",
        f"| 模块（`{POOL_REL}/`） | 行 | 职责 | 命令壳 |",
        "|---|---|---|---|",
    ]
    duty_by_name = {entry["name"]: entry for entry in entries}
    for name in sorted(found, key=lambda item: (item != "__init__.py", item)):
        entry = duty_by_name[name]
        lines.append(f"| `{name}` | {found[name]} | {entry['duty']} | {entry['cli']} |")
    lines += ["", *LEDGERS, "", f"## 2. 度量（{DATE_TOKEN} 现算）", ""]
    lines += [
        "| 指标 | 读数 | 怎么取 |",
        "|---|---|---|",
        f"| 实现体量 | **{total} 行** / **{len(py_files)} 个文件**"
        f"（{len(py_files) - 1} 个模块 + `__init__.py`）"
        f" | `wc -l {POOL_REL}/*.py`（与 §1 同源，一次现算） |",
        f"| 队列卡数 | {cards[0]} 张（{cards[1]} done / {cards[2]} pending）"
        f" | 读 `{BACKLOG_REL}` 的 `cards`，按 `status` 分 |",
        f"| 批预声明 | {batch} 份"
        f" | 主工作树 `{DIAG_REL}/batch/*.toml` 的份数（卡树里读成 0） |",
        f"| 派活日志 | {logs} 份（不含 `wb-usage.jsonl`）"
        f" | 主工作树 `{DIAG_REL}/wb-*.jsonl` 减 `wb-usage.jsonl` |",
        "| 单次派活墙钟 | 不写死：见右列 | 每份日志首个/末个 `__timestamp` 之差；"
        "只统计**有 ≥2 个** `__timestamp` 的日志 |",
        "| 最近一份跑完的 | 不写死：见右列 | 同上；取 "
        f"`{DIAG_REL}/wb-*.jsonl` 里 mtime 最新、且 ≥2 个 `__timestamp` 的那份 |",
    ]
    return lines


def _blank_dates(text: str) -> tuple[str, list[str]]:
    """把 `YYYY-MM-DD 现算` 抹成同一个令牌，并收集原日期（用来判「除日期外是否一致」）。"""
    dates = [match.group(1) for match in _DATE_RE.finditer(text)]
    return _DATE_RE.sub(f"{DATE_TOKEN} 现算", text), dates


def resolve_date(existing: str, template: str, today: str) -> str:
    """沿用现有日期当且仅当「除日期外逐字一致」；否则取今天（内容变了，就该换日期）。"""
    old_norm, old_dates = _blank_dates(existing)
    new_norm, _ = _blank_dates(template)
    if old_norm != new_norm or not old_dates:
        return today
    candidate = old_dates[0]
    try:
        parsed = datetime.date.fromisoformat(candidate)
    except ValueError:
        return today
    if parsed > datetime.date.fromisoformat(today):
        return today
    return candidate


def region_bounds(lines: list[str]) -> tuple[int, int] | str:
    """两处标记的行下标；个数不对或顺序反了 ⇒ 返回一句原因。"""
    begins = [index for index, line in enumerate(lines) if line.strip() == BEGIN]
    ends = [index for index, line in enumerate(lines) if line.strip() == END]
    if len(begins) != 1 or len(ends) != 1:
        return f"标记个数不对：`{BEGIN}` {len(begins)} 个 / `{END}` {len(ends)} 个（各要正好 1 个）"
    if ends[0] < begins[0]:
        return f"`{END}` 出现在 `{BEGIN}` 前面"
    return begins[0], ends[0]


def diff_lines(expected: list[str], actual: list[str], offset: int = 0) -> list[str]:
    """逐行点名（文件里 1 基行号 + 应为/实际）。

    只比**标记内**的内容：`offset` 是这块内容在文件里前面的行数。标记外的行不看 ——
    那些字不是本脚本的（§3 决策、§5 边界），改了它们不该让 `--check` 红。
    """
    diffs: list[str] = []
    for index in range(max(len(expected), len(actual))):
        left = expected[index] if index < len(expected) else "<没有这一行>"
        right = actual[index] if index < len(actual) else "<没有这一行>"
        if left != right:
            diffs.append(f"第 {offset + index + 1} 行：应为 {left!r}，实际 {right!r}")
    return diffs


def newline_of(raw: bytes) -> str:
    """跟随目标文件现状：只看第一个行尾（读不到/空文件按 CRLF，与本仓一致）。"""
    index = raw.find(b"\n")
    if index <= 0:
        return "\r\n"
    return "\r\n" if raw[index - 1] == 0x0D else "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="生成 docs/subsystems/pool/README.md 的代码边际与度量两段"
    )
    parser.add_argument("--check", action="store_true", help="只判：不一致退 1 并逐行点名")
    parser.add_argument("--root", default=None, help="换一棵树（自检用）；默认本仓")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve() if args.root else ROOT
    readme = root / README_REL
    try:
        raw = readme.read_bytes()
    except OSError as exc:
        print(f"[FAIL] 读不了 {README_REL}：{exc}")
        return 2
    newline = newline_of(raw)
    actual = raw.decode("utf-8").replace("\r\n", "\n")
    actual_lines = actual.split("\n")
    bounds = region_bounds(actual_lines)
    if isinstance(bounds, str):
        print(f"[FAIL] {README_REL} 没有可写的区域：{bounds}")
        return 2

    pool_dir = root / POOL_REL
    found = scan_pool(pool_dir) if pool_dir.is_dir() else {}
    entries, problems = load_manifest(root / MODULES_REL)
    if not found:
        problems.append(f"{POOL_REL}/ 里读不到任何 py / toml —— 这棵树里没有 pool 子系统")
    elif entries:
        problems += cross_check(entries, found)
    main_root, note = main_tree_root(root)
    if note:
        print(f"[warn] 算不出主工作树（{note}），按本树计：{DIAG_REL} 的度量会读成 0")
    batch, logs, diag_warns = diag_metrics(main_root)
    cards = backlog_metrics(root, main_root)
    problems += cards[3]
    for warn in (*diag_warns,):
        print(f"[warn] {warn}")
    if problems:
        for problem in problems:
            print(f"[FAIL] {problem}")
        return 1

    template = render_block(entries, found, batch, (cards[0], cards[1], cards[2]), logs)
    begin, end = bounds
    existing = "\n".join(actual_lines[begin + 1 : end])
    date_text = resolve_date(existing, "\n".join(template), datetime.date.today().isoformat())
    block = [line.replace(DATE_TOKEN, date_text) for line in template]
    expected_lines = actual_lines[: begin + 1] + block + actual_lines[end:]
    total = sum(found[name] for name in found if name.endswith(".py"))
    summary = f"{len(found)} 个文件 / {total} 行 / {date_text}"

    if args.check:
        diffs = diff_lines(block, actual_lines[begin + 1 : end], offset=begin + 1)
        if not diffs:
            print(f"[OK  ] {README_REL} 与现算一致（{summary}）")
            return 0
        print(f"[FAIL] {README_REL} 与现算不一致：{len(diffs)} 行")
        for line in diffs[:DIFF_LIMIT]:
            print(f"[FAIL] {line}")
        if len(diffs) > DIFF_LIMIT:
            print(f"[FAIL] 还有 {len(diffs) - DIFF_LIMIT} 行不同（只列前 {DIFF_LIMIT} 行）")
        return 1

    data = "\n".join(expected_lines).replace("\n", newline).encode("utf-8")
    if data == raw:
        print(f"[OK  ] {README_REL} 已是最新，未写盘（{summary}）")
        return 0
    readme.write_bytes(data)
    print(f"[OK  ] 写了 {README_REL}（{summary}；行尾 {newline!r}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
