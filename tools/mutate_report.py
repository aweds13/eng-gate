r"""变异驱动的用例汰换 + 参数化合并清册（卡 E51 · 段 2 / E37）。

## 一条硬边界：没有引擎就 fail closed

本工具**不自己实现变异算子**。它只读 `mutmut` / `cosmic-ray` 产出的报告，并做两件事：
1. 从「谁杀了哪个变异体」的矩阵里算出**每个用例的独有击杀**，列出**零独有击杀**清单；
2. 按删除上限（≤3%）与「删除后变异分下降 ≤0.5」判一批候选能不能删，**并且**挡住保护清单。

引擎不在（两个都没装；或平台跑不了）⇒ `EngineMissing`，CLI 退 **2** 并明说「引擎不在」。
**不许**把「没跑成」说成「0 个零独有击杀」—— 那等于把这张卡的判据反过来读。

## 为什么只认相对变化

绝对变异分在高变异密度下会**高估**套件质量（文献读数：>20%），所以删除判据只认
**同一次会话内的相对下降**（`score_before - score_after ≤ 0.5`）。

## 参数化合并：生成清册，不自动改

97 个族的合并要**逐族人工确认 `ids` 可追溯**（机械合并会把原用例名弄丢 ⇒ 回放判据、
审计 `test:` 指针全断）。`--families` 只产出清册：按「同一文件 + 归一化后的函数体」分组，
每族给出**原用例名列表**（`ids`），让人判定「这些能不能合成一个 `parametrize`」。
本工具**不写**任何测试文件。

## 用法

    python -X utf8 tools/mutate_report.py --report gates/diag/mutation.json --json
    python -X utf8 tools/mutate_report.py --families tests --json
    python -X utf8 tools/mutate_report.py --require-engine     # 引擎在不在（0/2）
"""

from __future__ import annotations

import argparse
import ast
import copy
import dataclasses
import datetime as dt
import importlib.metadata as md
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

#: 报告格式（键名是判据，别改名）。
REPORT_SCHEMA = "mutation/1"
REPORT_KEYS: frozenset[str] = frozenset(
    {
        "schema",
        "engine",
        "version",
        "created_at",
        "modules",
        "score",
        "killed",
        "survived",
        "tests",
        "zero_kill_tests",
    }
)

#: 删除上限（相对于用例**总数**）与变异分允许的下降（只认同会话内的相对变化）。
MAX_DELETE_RATIO = 0.03
MAX_SCORE_DROP = 0.5

#: 保护清单：**判据的判据**。删一条就可能让整棵树假绿（卡 §段 2「不许做」第 4 条）。
PROTECTED_TESTS: tuple[str, ...] = (
    "scripts/test_check_layers.py",   # check_layers 自检（审计/门禁的判据本体）
    "tests/test_no_window.py",        # 不弹窗（框架本身）
    "tests/test_audit_tightening.py",  # 审计 ⑫ 反向判据
    "tests/test_pytest_select.py",    # 选测的三道闸
    "tests/test_mutate_report.py",    # 本工具的钉子
    "tests/test_properties.py",       # 属性测试
)


class EngineMissingError(RuntimeError):
    """变异引擎不在（或平台跑不了）—— fail closed，绝不静默跳过。"""


@dataclasses.dataclass(frozen=True)
class TestScore:
    test: str
    kills: tuple[str, ...]
    unique: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class Report:
    engine: str
    version: str
    created_at: str
    modules: tuple[str, ...]
    score: float
    killed: int
    survived: int
    tests: dict[str, TestScore]
    zero_kill_tests: tuple[str, ...]

    @property
    def total(self) -> int:
        return self.killed + self.survived

    def payload(self) -> dict[str, object]:
        """固定键（`--json` 与 `mutation.json` 同一形状）。"""
        return {
            "schema": REPORT_SCHEMA,
            "engine": self.engine,
            "version": self.version,
            "created_at": self.created_at,
            "modules": list(self.modules),
            "score": self.score,
            "killed": self.killed,
            "survived": self.survived,
            "tests": {
                t: {"kills": list(v.kills), "unique": list(v.unique)}
                for t, v in sorted(self.tests.items())
            },
            "zero_kill_tests": list(self.zero_kill_tests),
        }


# ------------------------------------------------------------------ 引擎
def engine_versions() -> dict[str, str]:
    """装了的引擎与版本（没装的不出现）。"""
    found: dict[str, str] = {}
    for dist, label in (("cosmic-ray", "cosmic-ray"), ("mutmut", "mutmut")):
        try:
            found[label] = md.version(dist)
        except md.PackageNotFoundError:
            continue
    return found


def require_engine(versions: dict[str, str] | None = None) -> tuple[str, str]:
    """返回 `(引擎名, 版本)`；一个都没有 ⇒ `EngineMissingError`（明确报「引擎不在」）。"""
    found = engine_versions() if versions is None else dict(versions)
    if not found:
        raise EngineMissingError(
            "引擎不在：`mutmut` / `cosmic-ray` 都没装 —— 读不出变异报告，"
            "本次**不产出** zero_kill_tests（fail closed，不许把没跑成说成 0 个零独有击杀）"
        )
    # mutmut 3.x 在原生 Windows 上直接拒绝运行（只支持 WSL）；优先用能跑的那个。
    if "cosmic-ray" in found:
        return "cosmic-ray", found["cosmic-ray"]
    return "mutmut", found["mutmut"]


# ------------------------------------------------------------------ 计算
def score_of(killed: int, survived: int) -> float:
    """变异分 = 杀人 / 总数 × 100；总数 0 ⇒ 0（不给"满分"假象）。"""
    total = int(killed) + int(survived)
    if total <= 0:
        return 0.0
    return round(100.0 * int(killed) / total, 4)


def unique_kills(kills: dict[str, set[str]]) -> dict[str, set[str]]:
    """每个用例**独占**击杀的变异体（同一变异体被多份用例杀掉 ⇒ 谁都不独占）。"""
    counts: dict[str, int] = {}
    for ids in kills.values():
        for mid in ids:
            counts[mid] = counts.get(mid, 0) + 1
    return {t: {m for m in ids if counts.get(m) == 1} for t, ids in kills.items()}


def build_report(
    engine: str,
    version: str,
    modules: list[str] | tuple[str, ...],
    mutants: list[dict[str, Any]],
    *,
    all_tests: list[str] | tuple[str, ...] = (),
    created_at: str | None = None,
) -> Report:
    """由「变异体 → 杀它的用例」矩阵建报告（`killer` 为空 = 存活）。"""
    kills: dict[str, set[str]] = {}
    # ★ 同一变异体 id 出现多次只算**一条变异体**；同一 (变异体, 用例) 重复也只算一次。
    #   一个变异体被多份用例杀掉时，杀它的用例要全记下来（否则"独占"会判错）。
    counted: dict[str, set[str]] = {}
    for row in mutants:
        mid = str(row.get("id") or "")
        if not mid:
            raise ValueError("变异体缺 id")
        killers = counted.setdefault(mid, set())
        killer = row.get("killer")
        if killer:
            killers.add(str(killer))
    killed = sum(1 for killers in counted.values() if killers)
    for mid, killers in counted.items():
        for killer in killers:
            kills.setdefault(killer, set()).add(mid)
    total = len(counted)
    survived = total - killed
    unique = unique_kills(kills)
    tests: dict[str, TestScore] = {}
    for name in sorted(set(kills) | {str(t) for t in all_tests}):
        tests[name] = TestScore(
            test=name,
            kills=tuple(sorted(kills.get(name, ()))),
            unique=tuple(sorted(unique.get(name, ()))),
        )
    zero = tuple(sorted(t for t, s in tests.items() if not s.unique))
    at = created_at or dt.datetime.now().isoformat(timespec="seconds")
    return Report(
        engine=engine,
        version=version,
        created_at=at,
        modules=tuple(modules),
        score=score_of(killed, survived),
        killed=killed,
        survived=survived,
        tests=tests,
        zero_kill_tests=zero,
    )


def report_from_json(raw: dict[str, Any]) -> Report:
    """读回一份 `mutation.json`；形状不对 ⇒ `ValueError`（不猜）。"""
    if not isinstance(raw, dict):
        raise ValueError("报告顶层不是 object")
    missing = REPORT_KEYS - set(raw)
    extra = set(raw) - REPORT_KEYS
    if missing or extra:
        raise ValueError(f"报告键不对：缺 {sorted(missing)}，多 {sorted(extra)}")
    if raw["schema"] != REPORT_SCHEMA:
        raise ValueError(f"schema 不是 {REPORT_SCHEMA}：{raw['schema']!r}")
    tests: dict[str, TestScore] = {}
    body = raw["tests"]
    if not isinstance(body, dict):
        raise ValueError("tests 不是 object")
    for name, one in body.items():
        if not isinstance(one, dict) or set(one) != {"kills", "unique"}:
            raise ValueError(f"{name}: tests 条目形状不对")
        tests[str(name)] = TestScore(
            test=str(name),
            kills=tuple(str(x) for x in one["kills"]),
            unique=tuple(str(x) for x in one["unique"]),
        )
    killed = int(raw["killed"])
    survived = int(raw["survived"])
    score = float(raw["score"])
    if abs(score - score_of(killed, survived)) > 1e-6:
        raise ValueError(f"score {score} 与 killed/survived 算出来的不一致")
    zero = tuple(sorted(str(x) for x in raw["zero_kill_tests"]))
    expect_zero = tuple(sorted(t for t, s in tests.items() if not s.unique))
    if zero != expect_zero:
        raise ValueError("zero_kill_tests 与 tests 里算出来的不一致（报告自相矛盾）")
    return Report(
        engine=str(raw["engine"]),
        version=str(raw["version"]),
        created_at=str(raw["created_at"]),
        modules=tuple(str(x) for x in raw["modules"]),
        score=score,
        killed=killed,
        survived=survived,
        tests=tests,
        zero_kill_tests=zero,
    )


def load_report(path: Path) -> Report:
    return report_from_json(json.loads(Path(path).read_text(encoding="utf-8")))


def score_after_deleting(report: Report, removed: str) -> float:
    """删掉一条用例后的变异分：**它独占击杀的变异体现在变成存活**（其余不动）。"""
    target = report.tests.get(removed)
    if target is None:
        raise KeyError(f"报告里没有这条用例：{removed}")
    killed = report.killed - len(target.unique)
    return score_of(killed, report.survived + len(target.unique))


def deletion_problems(
    total_cases: int,
    deleted: int,
    score_before: float,
    score_after: float,
    protected_hit: tuple[str, ...] = (),
) -> list[str]:
    """删除批的硬约束（卡 §段 2 判据 4）：≤3% 且变异分下降 ≤0.5，保护清单一条不许碰。"""
    problems: list[str] = []
    if total_cases <= 0:
        problems.append("用例总数为 0 —— 没有分母就不许判删除上限")
    elif deleted > total_cases * MAX_DELETE_RATIO:
        problems.append(
            f"删除 {deleted} 条 > 上限 {total_cases * MAX_DELETE_RATIO:.2f}"
            f"（总数的 {MAX_DELETE_RATIO:.0%}）"
        )
    drop = score_before - score_after
    if drop > MAX_SCORE_DROP:
        problems.append(f"变异分下降 {drop:.2f} > 上限 {MAX_SCORE_DROP}")
    if protected_hit:
        problems.append(f"碰了保护清单：{sorted(protected_hit)}（一条都不许删）")
    return problems


def delete_candidates(report: Report, protected: tuple[str, ...] = PROTECTED_TESTS) -> list[str]:
    """零独有击杀里**不在保护清单**的那些（清册的候选面，不是自动删除名单）。"""
    keep = set(protected)
    return [t for t in report.zero_kill_tests if t not in keep]


# ------------------------------------------------------------------ 参数化合并清册
def _normalized_body(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """函数体的归一化指纹：**常量抹成占位符**、去掉 docstring（只比"结构一样"）。"""
    clone = copy.deepcopy(node)
    clone.body = [ln for ln in clone.body if not (
        isinstance(ln, ast.Expr) and isinstance(ln.value, ast.Constant)
        and isinstance(ln.value.value, str)
    )] or [ast.Pass()]
    for sub in ast.walk(clone):
        if isinstance(sub, ast.Constant):
            sub.value = "<literal>"
    return ast.unparse(clone.body)


def merge_families(tests_dir: Path) -> dict[str, object]:
    """扫 `tests/*.py`，按「同一文件 + 归一化函数体」分组；只产出清册，不写测试文件。"""
    families: list[dict[str, object]] = []
    functions = 0
    for path in sorted(Path(tests_dir).glob("test_*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        groups: dict[str, list[str]] = {}
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            functions += 1
            groups.setdefault(_normalized_body(node), []).append(node.name)
        for ids in groups.values():
            if len(ids) < 2:
                continue
            families.append({"file": path.name, "ids": sorted(ids), "count": len(ids)})
    families.sort(key=lambda f: (-int(f["count"]), str(f["file"]), list(f["ids"])[0]))
    return {
        "schema": "merge-families/1",
        "functions": functions,
        "families": families,
        "family_count": len(families),
        "mergible_functions": sum(int(f["count"]) for f in families),
    }


# ------------------------------------------------------------------ CLI
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="变异驱动的用例汰换（卡 E51 / E37）")
    ap.add_argument("--report", default=None, help="mutation.json 路径")
    ap.add_argument("--families", default=None, metavar="测试目录", help="生成参数化合并清册")
    ap.add_argument("--require-engine", action="store_true", help="只查引擎在不在（0/2）")
    ap.add_argument("--json", action="store_true", help="JSON 输出（键名固定）")
    a = ap.parse_args(argv)

    if a.families:
        inventory = merge_families(Path(a.families))
        print(json.dumps(inventory, ensure_ascii=False, indent=2))
        return 0

    if a.require_engine:
        try:
            name, version = require_engine()
        except EngineMissingError as exc:
            print(f"[FAIL] {exc}", file=sys.stderr)
            return 2
        print(f"[OK] 引擎 {name} {version}")
        return 0

    if not a.report:
        print("[FAIL] 给 --report（读变异报告）或 --families（生成合并清册）", file=sys.stderr)
        return 2
    path = Path(a.report)
    if not path.is_file():
        print(f"[FAIL] 报告不存在：{path}", file=sys.stderr)
        return 2
    try:
        report = load_report(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[FAIL] 报告读不懂（fail closed）：{exc}", file=sys.stderr)
        return 2
    payload = {
        "engine": report.engine,
        "version": report.version,
        "modules": list(report.modules),
        "score": report.score,
        "killed": report.killed,
        "survived": report.survived,
        "zero_kill_tests": list(report.zero_kill_tests),
        "delete_candidates": delete_candidates(report),
        "protected": list(PROTECTED_TESTS),
    }
    if a.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"引擎 {report.engine} {report.version}：{report.score:.2f} 分"
              f"（{report.killed} 杀 / {report.survived} 存活）")
        print(f"零独有击杀 {len(report.zero_kill_tests)} 条：")
        for t in report.zero_kill_tests:
            print(f"  {t}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
