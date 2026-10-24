"""pytest 红单归并 —— 同因只打一次（卡 E4 / T-AG446）。

**它解决的是哪一次真事故**：一次全量门禁红了 **34 条**，屏幕上是 788 KB 日志 + 34 条并列的
`FAILED …`；人要自己把 34 条读成「其实是 3 个原因」。这张卡把那一层读数变成
**≤3 行：同因归并 + 计数 + 一条示例**。

★ **归并的键是「异常类型 + 首句 + 首个仓内文件」**，**不是**测试文件名
（卡 §不许做 明写：按文件名归并会让「同一个根因、分布在两个测试文件」拆成两类，正好反了）。

★ **只读、只算，不丢原始输出**：本模块只接收 pytest 的完整 stdout 文本，返回结构；
屏幕打几行由调用方决定，`gates/logs/pytest.log` 仍由 `run_gates.finish_gate` 全量落盘。

用法（主要给 `scripts/run_gates.py` 用，也可单独跑）：
    python -X utf8 tools/failure_group.py gates/logs/pytest.log
"""

from __future__ import annotations

import dataclasses
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------- 行级正则

# short test summary 里的一行：`FAILED tests/x.py::test - AssertionError: ...`
# ★ `-q` 档不带冒号后的原因，所以整段 reason 是可选的。
_FAILED_RE = re.compile(r"^FAILED\s+(\S+?)(?:\s+-\s+(.*))?$")
# FAILURES 段里每个用例的块头：`__________ test_foo __________`
_BLOCK_RE = re.compile(r"^_{3,}\s+(.+?)\s+_{3,}$")
# 段分隔：`======== short test summary info ========`
_SECTION_RE = re.compile(r"^=+\s.*\s=+$")
# traceback 里的异常行：`E   AssertionError: assert 0 == 1`
_E_LINE_RE = re.compile(r"^E\s{2,}(\S.*)$")
# traceback 里的文件位置：`tests\test_x.py:123: AssertionError` / `src/x.py:45: in foo`
_LOC_RE = re.compile(r"([^\s:()<>\"']+\.py):(\d+)")
# 从「异常行」里拆出异常类型（`ModuleNotFoundError: …` / `Failed: …`）
_EXC_RE = re.compile(
    r"^((?:[A-Z][A-Za-z0-9_.]*)?(?:Error|Exception|Warning|Failed|Failure))\s*:?\s*(.*)$"
)

# 这些路径不是「仓内文件」：解释器 / 第三方 / 临时目录
_NOT_REPO = ("site-packages", "AppData", "Temp", "pytest-of-", "Lib/", "<")

# 展示用的截断宽度（防止一条超长 assertion 把一行撑爆；nodeid 不截，它是定位用的）
MAX_MESSAGE = 80


@dataclasses.dataclass(frozen=True)
class Failure:
    """一条红：哪条用例、什么异常、首句是什么、落在哪个仓内文件。"""

    nodeid: str
    exception: str
    message: str
    file: str


@dataclasses.dataclass
class FailureGroup:
    """同一因的一组红（`nodeids` 保持首次出现的顺序）。"""

    exception: str
    message: str
    file: str
    nodeids: list[str] = dataclasses.field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.nodeids)

    @property
    def representative(self) -> str:
        """代表用例：这一组里**第一次**出现的那条（稳定、可复现）。"""
        return self.nodeids[0] if self.nodeids else ""

    def as_dict(self) -> dict[str, object]:
        """落 `last.json` 的形状（列表明细，供 `wb_review` 与面板读）。"""
        return {
            "exception": self.exception,
            "message": self.message,
            "file": self.file,
            "count": self.count,
            "representative": self.representative,
            "nodeids": list(self.nodeids),
        }


def _repo_path(raw: str) -> str | None:
    """把 traceback 里的路径归成「仓内相对路径」；不是仓内的返回 None。"""
    p = raw.replace("\\", "/").strip()
    if not p or any(bad in p for bad in _NOT_REPO):
        return None
    for marker in ("tests/", "tools/", "scripts/", "src/", "harness/", "examples/"):
        i = p.find(marker)
        if i >= 0:
            return p[i:]
    return p.lstrip("./") or None


def _first_sentence(raw: str) -> str:
    """取「首句」：第一行，句号处截断（中文句号也算）。

    ★ 分组键用**完整首句**（不截断）—— 截断会让两句不同的红撞成一类；
    截断只发生在展示时（见 `report_lines`）。
    """
    s = raw.strip().splitlines()[0] if raw.strip() else ""
    for cut in ("。", ". "):
        if cut in s:
            s = s.split(cut, 1)[0]
    return s.strip()


def _split_exception(raw: str) -> tuple[str, str]:
    """`AssertionError: assert 0 == 1` → (`AssertionError`, `assert 0 == 1`)。"""
    s = raw.strip()
    if s.startswith("assert") and (s == "assert" or s[6:7].isspace()):
        return "AssertionError", s
    m = _EXC_RE.match(s)
    if m:
        return m.group(1), m.group(2).strip()
    return "Error", s


def _blocks(lines: list[str]) -> list[tuple[str, list[str]]]:
    """切出 FAILURES 段里的每个块：`(用例名, 块内行)`。"""
    out: list[tuple[str, list[str]]] = []
    name: str | None = None
    body: list[str] = []
    for ln in lines:
        m = _BLOCK_RE.match(ln)
        if m:
            if name is not None:
                out.append((name, body))
            name, body = m.group(1).strip(), []
            continue
        if name is None:
            continue
        if _SECTION_RE.match(ln):  # 进了别的段：本块收尾
            out.append((name, body))
            name, body = None, []
            continue
        body.append(ln)
    if name is not None:
        out.append((name, body))
    return out


def _block_annotation(body: list[str]) -> tuple[str, str, str]:
    """一个块 → `(异常类型, 首句, 仓内文件)`。"""
    raw = ""
    for ln in body:
        m = _E_LINE_RE.match(ln)
        if not m:
            continue
        content = m.group(1).strip()
        # `E    +  where …` / `E    +    where …` 是断言展开，不是异常行
        if content.startswith("+") or content.startswith("where "):
            continue
        raw = content
        break
    exception, message = _split_exception(raw) if raw else ("Error", "")
    if not message and raw:
        message = raw

    file = ""
    for ln in body:
        m = _LOC_RE.search(ln)
        if not m:
            continue
        got = _repo_path(m.group(1))
        if got:
            file = got
            break
    return exception, _first_sentence(message), file


def parse_pytest_output(text: str) -> list[Failure]:
    """pytest 完整 stdout → 每条红一条 `Failure`（顺序 = short summary 的顺序）。

    ★ 认不出块的（例如 `-q` 只给了 summary、没有 FAILURES 段）**不伪造**：
    用 summary 那行 `- 原因` 当首句，异常类型兜底 `Error`，文件取 nodeid 的路径部分。
    """
    lines = text.splitlines()
    # 同名用例可能出现在两个文件里（同名不同文件）→ 按名字收一列，取文件对得上的那个。
    by_name: dict[str, list[tuple[str, str, str]]] = {}
    for name, body in _blocks(lines):
        by_name.setdefault(name, []).append(_block_annotation(body))

    out: list[Failure] = []
    for ln in lines:
        m = _FAILED_RE.match(ln)
        if not m:
            continue
        nodeid = m.group(1)
        reason = (m.group(2) or "").strip()
        func = nodeid.split("::")[-1]
        node_file = _repo_path(nodeid.split("::")[0]) or ""
        cands = by_name.get(func, [])
        hit = next((c for c in cands if c[2] == node_file), None) or (cands[0] if cands else None)
        exc, msg, file = hit if hit else ("", "", "")
        if not exc:
            exc, msg = (_split_exception(reason) if reason else ("Error", nodeid))
            file = node_file
        out.append(Failure(nodeid=nodeid, exception=exc, message=msg, file=file))
    return out


def group_failures(failures: list[Failure]) -> list[FailureGroup]:
    """按「异常类型 + 首句 + 首个仓内文件」归并；多的一类在前（同类按首次出现）。"""
    groups: dict[tuple[str, str, str], FailureGroup] = {}
    order: dict[tuple[str, str, str], int] = {}
    for i, f in enumerate(failures):
        key = (f.exception, f.message, f.file)
        g = groups.get(key)
        if g is None:
            g = groups[key] = FailureGroup(f.exception, f.message, f.file)
            order[key] = i
        g.nodeids.append(f.nodeid)
    return sorted(
        groups.values(),
        key=lambda g: (-g.count, order[(g.exception, g.message, g.file)]),
    )


def _clip(s: str, width: int) -> str:
    return s if len(s) <= width else s[: width - 1] + "…"


def report_lines(groups: list[FailureGroup], limit: int = 3) -> list[str]:
    """屏幕报告：每类一行；超过 `limit` 类才追加「…另有 K 类见日志」。

    ★ 只截**首句**，`← 代表用例 nodeid` **整条保留** —— 那一行就是给人去定位的。
    """
    lines = [
        f"× {g.count}  [{g.exception}] {_clip(g.message, MAX_MESSAGE)}  ← {g.representative}"
        for g in groups[:limit]
    ]
    if len(groups) > limit:
        lines.append(f"…另有 {len(groups) - limit} 类见日志")
    return lines


def summarize(text: str, limit: int = 3) -> list[str]:
    """一步到位：pytest 文本 → 屏幕那几行（空列表 = 没认出红）。"""
    return report_lines(group_failures(parse_pytest_output(text)), limit=limit)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    path = Path(args[0])
    if not path.is_file():
        print(f"没有这个文件：{path}", file=sys.stderr)
        return 2
    text = path.read_text(encoding="utf-8", errors="replace")
    failures = parse_pytest_output(text)
    groups = group_failures(failures)
    for ln in report_lines(groups):
        print(ln)
    if not groups:
        print("（没认出 FAILED 行）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
