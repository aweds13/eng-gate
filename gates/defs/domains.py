"""改动面 → **必需档** 的唯一映射表（卡 A327 · T-AG442）。

为什么只有这一份：提交闸（`tools/wb_review.py` 第 ③′ 条）与门禁（`scripts/run_gates.py`
的 `--profile / --profiles`）必须**问同一张表**，否则两边一漂就会「门禁觉得够了、提交闸
觉得不够」——那正是卡 147 当初要拦的事。

口径（三条，别改语义）：

1. **并集**：改动面里每一个文件都按表查一遍，必需档取**并集**（改了 `src/` 与 `docs/`
   就要 lang + product + audit）。
2. **fail closed**：任何一个文件落不进表里 ⇒ 直接返回**全量三档**。宁可多跑，不许漏跑。
3. **表里只有"哪几档"，没有"跑哪道门"**：档的组成在 `run_gates.GATE_PROFILES`（卡 A321），
   这里只回答"这次改动最少要跑哪几档"。
"""

from __future__ import annotations

import pathlib
import subprocess
from typing import Final

# 档名与 `scripts/run_gates.py` 的 `GATE_PROFILES` 一致（那边有钉子保证每道门恰好一档）
ALL_PROFILES: Final[frozenset[str]] = frozenset({"lang", "audit", "product"})

# (前缀, 必需档)。**顺序无关**，一律取并集；前缀按 POSIX 分隔符写（git 的路径就是 POSIX）。
REQUIRED_PROFILES: Final[tuple[tuple[str, frozenset[str]], ...]] = (
    # 被判的那个产品：跑起来 + 真浏览器渲染
    ("src/", frozenset({"lang", "product"})),
    ("examples/", frozenset({"lang", "product"})),
    ("harness/", frozenset({"lang", "product"})),
    # 框架自己的实现与测试：语言门 + 契约门（台账/封存/Task: 都在 audit 里）
    ("tools/", frozenset({"lang", "audit"})),
    ("scripts/", frozenset({"lang", "audit"})),
    ("tests/", frozenset({"lang", "audit"})),
    ("gates/", frozenset({"lang", "audit"})),
    # 纯文本层：不碰代码，契约门就够
    ("docs/", frozenset({"audit"})),
    ("复盘/", frozenset({"audit"})),
    ("skills/", frozenset({"audit"})),
)

# 根目录那几个"散落的文本文件"（不带目录前缀）
_ROOT_FILES: Final[tuple[str, ...]] = (
    "README.md",
    "AGENTS.md",
    "harness.toml",
    "pipeline.toml",
    "pyproject.toml",
)


def _profiles_for_path(path: str) -> frozenset[str] | None:
    """单个文件落在哪一档；落不进表就回 None（调用方据此退回全量）。"""
    p = path.replace("\\", "/").lstrip("./")
    if not p:
        return None
    for prefix, profiles in REQUIRED_PROFILES:
        if p.startswith(prefix):
            return profiles
    if "/" not in p and (p in _ROOT_FILES or p.endswith(".md")):
        return frozenset({"audit"})
    return None


#: ★ 卡 E3（T-AG445）：算档用的**改动面来源**，只有这两个合法值。
#: `committed` = 提交面（父提交..HEAD + 暂存 ⇒ 这一笔**真要提交**的东西）；
#: `worktree`  = 工作区（含残留/未跟踪 ⇒ 手工跑门禁时的老口径）。
PROFILE_SOURCES: Final[frozenset[str]] = frozenset({"committed", "worktree"})

#: 不指定来源时的口径 = 工作区（**行为一字不变**：手工跑门禁的老用法）。
DEFAULT_SOURCE: Final[str] = "worktree"

#: ★ 卡 E3（T-AG445）：问「派生 / 残留」时用的仓库根（`gates/defs/domains.py` 上两级）。
_REPO_ROOT: Final[pathlib.Path] = pathlib.Path(__file__).resolve().parents[2]


def _norm_path(path: str) -> str:
    """POSIX 化 + 去掉 `./` 前缀（**不动**开头的点：`.dsh-probe/` 是目录名，不是前缀）。"""
    p = str(path).replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p


def _git_ignored(paths: list[str]) -> frozenset[str]:
    r"""问 git：这些路径里哪些被忽略（= **派生 / 残留**，不随树分发，也不算改动面）。

    ★ 卡 E3（`T-AG445`）：`--profiles auto` 的病灶是「`blobs/`、`.dsh-probe/` 这类**残留**
      挂在改动面里 ⇒ 判不出档 ⇒ 三档全量」。`.gitignore` 收掉它们是第一层；这一层保证
      **即使调用方把派生路径塞进来**，它们也不许把算档拖成全量 —— 而派生目录**之外**的
      改动照常算（那才是这一笔真改了的东西）。
    ★ 判据问 **git 自己**（`check-ignore --stdin`），不在这里抄一份 .gitignore 的目录名：
      `gates/diag/` 整目录被忽略但 `!gates/diag/gate_lock.py` 是例外，硬编码前缀会误判。
    ★ 问不到（没有 git / 不在仓库里 / 退出码不认识）⇒ 空集 ⇒ 调用方照旧 fail closed（从严）。
    """
    rel = sorted({p for p in (_norm_path(x) for x in paths) if p})
    if not rel:
        return frozenset()
    # ★ 用**字节**喂 stdin：`text=True` 在 Windows 上会把 `\n` 翻成 `\r\n`，git 于是把
    #   `\r` 当路径的一部分、输出带引号的怪名字（实测踩过）⇒ 判据静默失效。
    data = ("\n".join(rel) + "\n").encode("utf-8")
    try:
        done = subprocess.run(  # noqa: S603 —— 参数写死，无 shell
            ["git", "check-ignore", "--stdin"], cwd=str(_REPO_ROOT),
            input=data, capture_output=True, check=False)
    except OSError:
        return frozenset()
    if done.returncode not in (0, 1):          # 0 = 有被忽略的 / 1 = 一个都没有
        return frozenset()
    text = (done.stdout or b"").decode("utf-8", "replace")
    return frozenset(_norm_path(x) for x in text.splitlines() if x.strip())


def required_profiles(paths: list[str] | tuple[str, ...], *,
                      source: str = DEFAULT_SOURCE) -> frozenset[str]:
    r"""这次改动**最少**要跑哪几档。空清单 ⇒ 全量（没证据就别省）。

    ★ 卡 E3（`T-AG445`）：多了 `source` —— **算档依据的是哪一份改动面**。
      它不改变「哪几档」的映射（表还是这张表），只把**来源**变成显式参数，
      免得「被工作区残留（`blobs/`、`.dsh-probe/`）拖成全量」这件事**看不出来**。
      · `committed`：提交面（父提交..HEAD + 暂存）—— 落地链该用这个；
      · `worktree` ：工作区（含未跟踪）—— **默认**，手工跑门禁的老口径（行为不变）。
      ★ 值非法 ⇒ `ValueError`（**不许**猜成 worktree：trailer 要如实写来源）。
      ★ 卡 E3（`T-AG445`）第二处：判不出档的路径里，**被 `.gitignore` 收掉的派生 / 残留**
        （`blobs/`、`.dsh-probe/` …）不算改动面 —— 但派生目录**之外**判不出的路径
        仍然 fail closed 到全量（宁可多跑，不许漏跑）。
    """
    if source not in PROFILE_SOURCES:
        raise ValueError(
            f"source 只能是 {' / '.join(sorted(PROFILE_SOURCES))}，收到 {source!r}"
            "（来源要如实写进 payload 的 profiles_source，不许猜）")
    if not paths:
        return ALL_PROFILES
    need: frozenset[str] = frozenset()
    unmapped: list[str] = []
    for path in paths:
        one = _profiles_for_path(str(path))
        if one is None:
            unmapped.append(str(path))
        else:
            need |= one
    if unmapped:
        ignored = _git_ignored(unmapped)
        if any(_norm_path(p) not in ignored for p in unmapped):
            return ALL_PROFILES
    return need or ALL_PROFILES


def profiles_payload(paths: list[str] | tuple[str, ...], *,
                     source: str = DEFAULT_SOURCE) -> dict[str, object]:
    r"""写进 `gates/last.json` 的那两个键（卡 E3 判据 1）：必需档 + **来源**。

    形状与 `scripts/run_gates.py` 现在的产物一致（`required_profiles` 是排序后的列表），
    多出来的 `profiles_source` 就是「这次按哪份改动面算的」——复核/trailer 据此如实标注，
    不再靠人记「这一趟是按提交面还是按工作区算的」。
    """
    return {
        "required_profiles": sorted(required_profiles(paths, source=source)),
        "profiles_source": source,
    }


def explain(paths: list[str] | tuple[str, ...], *, source: str = DEFAULT_SOURCE) -> str:
    """给 trailer / 报错用的一句话：`必需 lang+audit（判不出 ⇒ 全量就别省）`。"""
    need = required_profiles(paths, source=source)
    if need == ALL_PROFILES:
        return "必需 lang+audit+product（全量：有路径判不出档）"
    return "必需 " + "+".join(sorted(need))
