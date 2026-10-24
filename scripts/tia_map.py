r"""TIA（测试影响分析）：按**覆盖映射**选测，判不出就退回全量。

卡 E2（T-AG444）。目标：pytest 从「全量 2955 条 / 427 s」变成「改动面相关子集 / ≤90 s」，
且**宁可多跑不许漏跑**。

三条口径（写在最前面，改代码前先读）：

1. **只认覆盖映射**，不按目录猜 —— 映射来自真跑一遍测试采到的覆盖率（`--cov-context=test`），
   谁覆盖了谁有据可查；目录名不构成判据。
2. **fail closed**：映射缺失 / 映射过期 / 映射里判不出某个被改文件 ⇒ 一律打印原因并**退回全量**，
   绝不用"少跑几个"换一句好看的数字。
3. **pinned 兜底不许缩**：判据钉子（`PINNED_TESTS`）、上次失败过的用例、
   本卡改过的测试文件，每次都跑。

产物 `gates/tia.json`（gitignored，由卡 E3 补 `.gitignore`）：
`{<test_nodeid>: [被覆盖的源文件…], "rev": <HEAD>, "generated_at": <iso>, "total": <n>}`。

用法：

```bash
python -X utf8 scripts/tia_map.py --build                 # 真跑一遍全量并采覆盖率（慢）
python -X utf8 scripts/tia_map.py --select src/timeflow/x.py [更多改动…]
python -X utf8 scripts/tia_map.py --check                 # 映射格式 + 是否过期
```

门禁侧：`TF_TIA=1 python -X utf8 scripts/run_gates.py --quick` ⇒ pytest 门只跑选集，
`gates/last.json` 里多记 `tests_run` / `tests_total`（不设这个开关时形状逐字不变）。
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

TOOL_ROOT = Path(__file__).resolve().parent.parent
_TOOLS = TOOL_ROOT / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from pipe_root import data_root  # noqa: E402 —— 数据根的唯一实现（卡 A326）
from pool.no_window import NO_WINDOW  # noqa: E402 —— 起子进程一律不弹窗（卡 148）

#: 映射文件名（相对数据根 `gates/`）。
MAPPING_NAME = "tia.json"
#: 记账/文档改动不参与选测（与 `run_gates.TEST_SELECTION_IGNORE_PREFIXES` 同一口径）：
#: 落地链每一笔都会写它们，算进去选集永远用不上；它们的用例在收口链 ④ 全量照跑。
IGNORE_PREFIXES: tuple[str, ...] = ("docs/", "复盘/", "gates/", ".wt/")

#: 判据钉子（**逐字照卡 E2**）：改哪个源文件都要跑。★ 不许为了让数字好看缩小这一集。
PINNED_TESTS: tuple[str, ...] = (
    "tests/test_wb_review.py",
    "tests/test_check_layers.py",
    "tests/test_card_specs_tracked.py",
    "tests/test_check_skills.py",
    "tests/test_run_gates_profiles.py",
)
#: 卡的钉子在本树里落在别处时的**等价路径**（不删钉子，换成真文件）：
#: `tests/test_check_layers.py` 在本仓实际是 `scripts/test_check_layers.py`。
PINNED_ALIASES: dict[str, str] = {
    "tests/test_check_layers.py": "scripts/test_check_layers.py",
}

#: `plan(payload=…)` 的默认值哨兵：不传 ⇒ 去读 `gates/tia.json`。
_AUTO = object()

#: 映射 payload 里的元键（其余键都是 test nodeid）。
META_KEYS: tuple[str, ...] = ("rev", "generated_at", "total")
#: 覆盖率只认这些目录下的源文件（测试自己与被测对象同commit时不互相污染）。
SOURCE_DIRS: tuple[str, ...] = ("src/", "tools/", "scripts/")


@dataclasses.dataclass(frozen=True)
class TiaPlan:
    """一整套选测结论（**纯数据**：给门禁用，也给人看）。

    `full=True` ⇒ 调用方**必须**退回全量；`note` 里一定写清为什么（不许静默少跑）。
    """

    tests: tuple[str, ...]
    full: bool
    note: str
    total: int
    pinned: tuple[str, ...] = ()

    @property
    def run_count(self) -> int:
        """这一趟**跑多少条**（全量兜底时 = 映射里的全量条数）。"""
        return self.total if self.full else len(self.tests)


# ---------------------------------------------------------------- 映射的存与读
def mapping_path(root: Path | None = None) -> Path:
    """映射文件位置：`<数据根>/gates/tia.json`。"""
    base = _root(root)
    return base / "gates" / MAPPING_NAME


def _root(root: Path | None) -> Path:
    return Path(root).resolve() if root is not None else data_root()


def make_payload(
    mapping: dict[str, list[str]], rev: str | None = None, generated_at: str | None = None
) -> dict[str, object]:
    """把 `{nodeid: [源文件…]}` 包成落盘形状（排序，便于逐字节复核）。"""
    payload: dict[str, object] = {
        key: sorted(value) for key, value in sorted(mapping.items())
    }
    payload["rev"] = _head_rev() if rev is None else rev
    payload["generated_at"] = (
        datetime.now().isoformat(timespec="seconds") if generated_at is None else generated_at
    )
    payload["total"] = len(mapping)
    return payload


def mapping_from_payload(payload: object) -> dict[str, list[str]]:
    """校验并取出映射；形状不对 ⇒ `ValueError`（**不许**静默当成"没有映射"）。"""
    if not isinstance(payload, dict):
        raise ValueError(f"映射不是对象：{type(payload).__name__}")
    rev = payload.get("rev")
    if not isinstance(rev, str) or not rev.strip():
        raise ValueError("映射缺 rev（无法判过期）")
    out: dict[str, list[str]] = {}
    for key, files in payload.items():
        if key in META_KEYS:
            continue
        if not isinstance(key, str) or "::" not in key:
            raise ValueError(f"映射的键不是 test nodeid：{key!r}")
        if not isinstance(files, list) or not all(isinstance(f, str) for f in files):
            raise ValueError(f"{key} 的值不是「字符串列表」：{files!r}")
        out[key] = list(files)
    return out


def test_count(payload: object) -> int:
    """全量用例条数（映射里记的 `total`；旧笔没有这个键就数 nodeid）。"""
    if isinstance(payload, dict) and isinstance(payload.get("total"), int):
        return int(payload["total"])
    try:
        return len(mapping_from_payload(payload))
    except ValueError:
        return 0


def save_mapping(payload: dict[str, object], path: Path | None = None) -> Path:
    target = path if path is not None else mapping_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return target


def load_mapping(path: Path | None = None) -> dict[str, object] | None:
    """读落盘映射；不存在 ⇒ None（调用方按"判不出 ⇒ 全量"处理）。"""
    target = path if path is not None else mapping_path()
    if not target.is_file():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"映射读不出来：{target}（{exc}）") from exc
    if not isinstance(data, dict):
        raise ValueError(f"映射不是对象：{target}")
    return data


# ---------------------------------------------------------------- 映射过期判定
def _git(args: list[str], root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 —— 参数写死，无 shell
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        **NO_WINDOW,
    )


def _head_rev(root: Path | None = None) -> str:
    probe = _git(["rev-parse", "HEAD"], _root(root))
    return (probe.stdout or "").strip() if probe.returncode == 0 else ""


def is_ancestor(rev: str, root: Path | None = None) -> bool:
    """`rev` 是不是当前 HEAD 的祖先（含等于）。读不到 git ⇒ False（**fail closed**）。"""
    base = _root(root)
    head = _head_rev(base)
    if not rev or not head:
        return False
    if rev == head:
        return True
    probe = _git(["merge-base", "--is-ancestor", rev, "HEAD"], base)
    return probe.returncode == 0


# ---------------------------------------------------------------- 选测
def _norm(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def resolved_pinned(root: Path | None = None) -> tuple[str, ...]:
    """钉子解析成本树里**真存在**的路径（别名替换；都没有就跳过，但不删钉子条目）。"""
    base = _root(root)
    out: list[str] = []
    for rel in PINNED_TESTS:
        if (base / rel).is_file():
            out.append(rel)
            continue
        alias = PINNED_ALIASES.get(rel)
        if alias and (base / alias).is_file():
            out.append(alias)
    return tuple(out)


def read_last_failed(root: Path | None = None) -> tuple[str, ...]:
    """`.pytest_cache/v/cache/lastfailed` 里上次失败过的 nodeid（没有缓存 ⇒ 空）。"""
    cache = _root(root) / ".pytest_cache" / "v" / "cache" / "lastfailed"
    if not cache.is_file():
        return ()
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    return tuple(sorted(k for k in data if isinstance(k, str))) if isinstance(data, dict) else ()


def _is_test_file(path: str) -> bool:
    return path.startswith("tests/") and path.endswith(".py")


def select(
    changed: list[str] | tuple[str, ...],
    mapping: dict[str, list[str]],
    root: Path | None = None,
    pinned: tuple[str, ...] | None = None,
    last_failed: tuple[str, ...] = (),
) -> TiaPlan:
    """按映射选测（`changed` = 改动文件，仓库相对路径）。

    - 映射里**没有**任何用例覆盖某个被改的代码文件 ⇒ `full=True`（判不出 ⇒ 全量）；
    - 文档/记账改动不算代码；**只有**这类改动时同样退回全量（用例也读文档，判不出）；
    - pinned + 上次失败 + 本卡改过的测试文件一律并入；
    - 一个文件的用例全被选中 ⇒ 收成文件名（命令行更短，语义等价）。
    """
    base = _root(root)
    pinned = resolved_pinned(base) if pinned is None else pinned
    files = [_norm(p) for p in changed if p.strip()]
    code = [p for p in files if not p.startswith(IGNORE_PREFIXES)]

    if not files:
        return TiaPlan((), True, "没有改动 ⇒ 判不出 ⇒ 全量", test_count({"total": len(mapping)}))
    if not code:
        return TiaPlan((), True, "只有文档/记账改动 ⇒ 判不出 ⇒ 全量",
                       len(mapping))

    chosen: list[str] = []
    unseen: list[str] = []

    def _add(test: str) -> None:
        if test not in chosen:
            chosen.append(test)

    for path in code:
        if _is_test_file(path):
            if (base / path).is_file():
                _add(path)
            else:
                return TiaPlan((), True, f"判不出 ⇒ 全量：改动的测试文件不存在 {path}",
                               len(mapping))
            continue
        covering = [nodeid for nodeid, covered in mapping.items() if path in covered]
        if not covering:
            unseen.append(path)
            continue
        for nodeid in covering:
            _add(nodeid)

    if unseen:
        return TiaPlan((), True, "判不出 ⇒ 全量：这些文件没有任何映射到它的用例："
                       + "、".join(unseen), len(mapping))

    for nodeid in last_failed:
        if "::" in nodeid and (base / nodeid.split("::", 1)[0]).is_file():
            _add(nodeid)
    for rel in pinned:
        _add(rel)

    return TiaPlan(
        tuple(sorted(_collapse(chosen, mapping, base))),
        False,
        f"选中 {len(_collapse(chosen, mapping, base))} 条用例（映射 + pinned 兜底）",
        len(mapping),
        pinned=pinned,
    )


def _collapse(chosen: list[str], mapping: dict[str, list[str]], base: Path) -> list[str]:
    """把"整个文件的用例都被选中"收成文件名。"""
    selected = set(chosen)
    by_file: dict[str, set[str]] = {}
    for nodeid in mapping:
        if "::" not in nodeid:
            continue
        by_file.setdefault(nodeid.split("::", 1)[0], set()).add(nodeid)
    out: list[str] = []
    for item in chosen:
        if "::" in item:
            rel = item.split("::", 1)[0]
            whole = by_file.get(rel, set())
            if whole and whole <= selected and (base / rel).is_file():
                if rel not in out:
                    out.append(rel)
                continue
        if item not in out:
            out.append(item)
    return out


def plan(
    changed: list[str] | tuple[str, ...],
    root: Path | None = None,
    payload: object = _AUTO,
    fresh: Callable[[str, Path], bool] | None = None,
    mapping_file: Path | None = None,
) -> TiaPlan:
    """完整流程：读映射 → 判过期 → 选测；任何一步判不出 ⇒ 全量（fail closed）。"""
    base = _root(root)
    if payload is _AUTO:
        try:
            payload = load_mapping(mapping_file if mapping_file is not None
                                   else mapping_path(base))
        except ValueError as exc:
            return TiaPlan((), True, f"判不出 ⇒ 全量：{exc}", 0)
    if payload is None:
        return TiaPlan((), True,
                       "判不出 ⇒ 全量：没有映射（先跑 `scripts/tia_map.py --build`）", 0)
    try:
        mapping = mapping_from_payload(payload)
    except ValueError as exc:
        return TiaPlan((), True, f"判不出 ⇒ 全量：映射损坏（{exc}）", 0)

    rev = str(payload["rev"]) if isinstance(payload, dict) else ""
    check = fresh if fresh is not None else is_ancestor
    if not check(rev, base):
        return TiaPlan((), True, f"映射过期，退回全量（映射 rev={rev[:12]} 不是 HEAD 的祖先）",
                       test_count(payload))

    if not any(p.strip() for p in changed):
        return TiaPlan((), True, "没有改动 ⇒ 判不出 ⇒ 全量", test_count(payload))

    return select(changed, mapping, base, last_failed=read_last_failed(base))


# ---------------------------------------------------------------- 生成映射
def build(
    root: Path | None = None, pytest_args: list[str] | None = None
) -> dict[str, object]:
    """真跑一遍测试并采覆盖率（`--cov-context=test`）→ 落盘 `gates/tia.json`。

    ★ 为什么用 `--cov-context=test` 而不是每条用例起一次 `coverage run`：前者一趟采完
      （xdist 下各 worker 的上下文由 pytest-cov 合并），后者要起 2955 次解释器。
    """
    base = _root(root)
    data_file = base / ".coverage"  # 与 pytest-cov 默认一致（.gitignore 已忽略）
    workers = _workers()
    cmd = [
        sys.executable, "-X", "utf8", "-m", "pytest", "-q",
        *(["-n", str(workers)] if workers > 1 else []),
        "--cov=timeflow", "--cov=tools", "--cov=scripts",
        "--cov-context=test", "--cov-report=",
        "-p", "no:cacheprovider",
        *(pytest_args or []),
    ]
    env = dict(os.environ)
    env["COVERAGE_FILE"] = str(data_file)
    # ★ Python 3.14 的 coverage 默认 core=sysmon，**动态上下文不生效**
    #   （`Dynamic contexts aren't supported with core=sysmon`）—— 那样采到的映射是空的；
    #   `pytrace` 能记上下文但慢十倍，用 `ctrace`（C 追踪器；xdist 各 worker 的上下文由
    #   pytest-cov 合并）。
    env["COVERAGE_CORE"] = "ctrace"
    env.setdefault("PYTHONPATH", os.pathsep.join(
        [str(base / "src"), str(base / "tools" / "sandbox_shim")]))
    log_path = base / "gates" / "logs" / "tia-build.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # ★ 输出**逐行落盘**（不 capture_output）：全量要跑好几分钟，中途要能 `tail` 看进度
    #   —— 这条是 AGENTS.md 的长命令口径，别改成管道/静默。
    with log_path.open("w", encoding="utf-8", newline="\n") as log:
        proc = subprocess.run(  # noqa: S603 —— 参数写死，无 shell
            cmd, cwd=base, env=env, stdout=log, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", check=False, **NO_WINDOW,
        )
    if proc.returncode not in (0, 1):  # 1 = 有用例失败，覆盖率数据照样可用
        raise SystemExit(f"pytest 起不来/中途崩溃（exit={proc.returncode}），详见 {log_path}")

    import coverage  # 延迟 import：只有 --build 才需要它

    cov = coverage.Coverage(data_file=str(data_file))
    cov.load()
    data = cov.get_data()
    mapping: dict[str, set[str]] = {}
    for measured in data.measured_files():
        rel = _rel_source(measured, base)
        if rel is None:
            continue
        # `contexts_by_lineno` = {行号: [上下文…]}；上下文形如
        # `tests/test_x.py::test_y|run`（pytest-cov 在每行上记"哪个用例跑到这一行"）。
        for _lineno, contexts in data.contexts_by_lineno(measured).items():
            for context in contexts:
                name = str(context).split("|", 1)[0]
                if "::" not in name:     # 会话级上下文（"" / "crawl"）不算某条用例
                    continue
                mapping.setdefault(name, set()).add(rel)
    payload = make_payload({k: sorted(v) for k, v in mapping.items()})
    save_mapping(payload, mapping_path(base))
    print(f"映射已生成：{len(mapping)} 条用例、rev={str(payload['rev'] or '')[:12]} → "
          f"{mapping_path(base)}")
    return payload


def _workers() -> int:
    """并行 worker 数：`TF_TIA_WORKERS` 优先；默认 4（全量串行要十几分钟）。"""
    try:
        return max(1, int(os.environ.get("TF_TIA_WORKERS", "4")))
    except ValueError:
        return 4


def _rel_source(path: str, base: Path) -> str | None:
    """绝对路径 → 仓库相对路径（只收 `SOURCE_DIRS` 下的 `.py`；测试自己不算）。"""
    try:
        rel = Path(path).resolve().relative_to(base).as_posix()
    except (OSError, ValueError):
        return None
    if not rel.endswith(".py") or rel.startswith(("tests/", "tools/sandbox_shim/")):
        return None
    return rel if rel.startswith(SOURCE_DIRS) else None


# ---------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="TIA：按覆盖映射选测（判不出 ⇒ 全量）")
    ap.add_argument("--build", nargs="*", metavar="TEST",
                    help="真跑一遍测试并重新生成映射（可只给几个测试文件，诊断用）")
    ap.add_argument("--select", nargs="+", metavar="FILE", help="按改动文件选测")
    ap.add_argument("--check", action="store_true", help="校验映射格式与是否过期")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出（给脚本用）")
    args = ap.parse_args(argv)

    if args.build is not None:
        build(pytest_args=args.build or None)
        return 0

    if args.check:
        try:
            payload = load_mapping()
        except ValueError as exc:
            print(f"[FAIL] {exc}")
            return 1
        if payload is None:
            print(f"[FAIL] 没有映射：{mapping_path()}")
            return 1
        try:
            mapping = mapping_from_payload(payload)
        except ValueError as exc:
            print(f"[FAIL] 映射格式不对：{exc}")
            return 1
        rev = str(payload["rev"])
        fresh = is_ancestor(rev)
        print(f"映射：{len(mapping)} 条用例 · rev={rev[:12]} · "
              f"{'新鲜' if fresh else '★ 过期（不是 HEAD 的祖先）'}")
        return 0 if fresh else 1

    if args.select:
        result = plan(args.select)
        if args.json:
            print(json.dumps(dataclasses.asdict(result), ensure_ascii=False, indent=2))
        else:
            print(result.note)
            for test in result.tests:
                print(f"  {test}")
            if result.full:
                print("  （全量：run_gates 的 pytest 门不带选集参数）")
        return 0

    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
