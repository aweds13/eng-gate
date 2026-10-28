"""钉子：`subprocess.*(text=True)` 必须同时给 `encoding=` —— 归属 `pytest` 门。

★ 这道钉子红了 = 有人写了**在云门禁机上会炸**的调用，不是格式洁癖：
云门禁机（Windows Server 2022 / `administrator`）的区域编码是 **cp936**，开发机是
utf-8 —— 所以 `text=True` 不给 `encoding=` 时本机怎么跑都对，云机上只要子进程
（尤其 `git`）吐中文路径或中文提交信息就 `UnicodeDecodeError`；`capture_output=True`
下 `r.stdout` 还会变成 `None`，下游 `r.stdout.strip()` 接着抛
`AttributeError: 'NoneType' object has no attribute 'strip'`。
云机实测：`scripts/run_gates.py` 的 `git()` 就是这么崩掉 `pytest_chain` 的，全仓同型
共 23 处，已逐处补 `encoding="utf-8", errors="replace"`。
`errors="replace"` 的理由：宁可拿到带替换符的中文，也不要在云机上整条炸掉。

判据只用 **AST**，不用 grep：grep 按行看，`encoding=` 写在**下一行**的调用会被误判成
「有」（假绿），而本仓大量调用是跨行写的。判据与 `gates/diag/_scan_encoding.py`
同一份，但**照抄不 import** —— `gates/diag/` 被 `.gitignore` 掉、不入库，测试不能
依赖一个仓库里不存在的东西。

★ 第二段（本卡补）：光扫「`text=True` 有没有 `encoding=`」漏掉两类**云机真崩过**的形态：
1. `encoding=` 给了但**不是** utf-8（或 `errors` 不是 `replace`）—— 扫 encoding 存在性会放过它；
2. `r.stdout.strip()` 裸着写 —— 解码失败时 `stdout` 是 `None`，`.strip()` 抛
   `AttributeError: 'NoneType' object has no attribute 'strip'`（本机 utf-8 永远看不见）；
3. `gates/last.json` 的 payload 不记 `"host"` —— 落地链的「必须是云机跑的」永远判不过。

用例清单：
- `test_repo_calls_all_carry_encoding` —— 真仓扫描，任一违规即红，打印 `路径:行:函数名`，
  并顺带断言「真扫到了东西」（文件数 / 候选调用数有下限），防扫描器退化成恒真空转；
- `test_scanner_bites_on_a_planted_violation` —— **反向用例**：往 `tmp_path` 造一个
  违规调用，断言扫描器抓得到；同文件再造一个 `encoding=` 写在**下一行**的合规调用
  （正是 grep 会假绿的那种），断言不被误报。没有这条，整道钉子可能永远空转。
- `test_landing_lock_calls_carry_encoding` —— `tools/pool/landing.py` 的 `release_lock` /
  `_renewer_loop`（锁续租）必须 utf-8 + replace：这两处被 `contextlib.suppress(Exception)`
  包着，云机解码一崩就被吞掉 ⇒ 锁续不上、没人知道；
- `test_landing_has_no_bare_stdout_strip` —— `landing.py` 不许有裸 `.stdout.strip()`；
- `test_run_gates_payload_records_host` —— `scripts/run_gates.py` 的 payload 必记
  `"host": socket.gethostname()`（★ 只认 `main()` 的 payload；`seal()` 不写 host，
  `--seal` 之后没有 host 是正常的，别把判据写成那边）；
- `test_text_mode_without_encoding_loses_output_on_undecodable_bytes` —— **真跑一条**：
  子进程真吐 `0xff 0xfe 0x41`，断言不带 `encoding=` 时 `stdout is None`
  （或老版本主线程抛 `UnicodeDecodeError`），带 `errors="replace"` 时拿到替换符。
  没有这条，前三道源码判据仍然只是「读起来对」；
- `test_landing_and_payload_detectors_bite_on_planted_violations` —— **反向用例**：
  上面三道源码判据各造一份违规，断言全咬得住、合规不误报。
★ 第三段（本卡补）：`encoding=` 给了也要 `errors=`。
- `test_repo_calls_with_encoding_also_carry_errors` —— 真仓扫描，判据是
  「有 `encoding=` 但缺 `errors=`」（与第一段**镜像**，不是重复），同样带
  防空转护栏（扫到的文件数 / 带 `encoding=` 的调用数各有下限）；
- `test_missing_errors_scanner_bites_on_a_planted_violation` —— **反向用例**：
  往 `tmp_path` 植一处只写 `encoding=` 的调用，断言咬得住；带 `errors=` 的、
  压根不解码的都不误报。
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# ★ 卡 E59（T-AG517）：`Path.read_text/write_text(newline=)` 是 **Python 3.13 才加**的参数，
#   云门禁机是 3.12.8 ⇒ 直接用会在云机 `TypeError`（本机 3.14 永远看不见）。走 tools/read_write.py。
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))
from read_write import read_text as _read_text_bw  # noqa: E402

SCAN_DIRS = ("scripts", "tools", "tests")
SKIP_PARTS = {".wt", "gates", "__pycache__", ".git"}

# 判据要盯的子进程入口（少一个 = 那道门漏一个洞）。
SUBPROCESS_ENTRIES = {
    "run",
    "Popen",
    "check_output",
    "check_call",
    "call",
    "getoutput",
    "getstatusoutput",
}


def _is_subprocess_call(node: ast.Call) -> bool:
    """是不是 `subprocess.run/Popen/check_output/check_call/call/getoutput/...`。"""
    func = node.func
    if isinstance(func, ast.Attribute):
        base = func.value
        if isinstance(base, ast.Name) and base.id == "subprocess":
            return func.attr in SUBPROCESS_ENTRIES
    return False


def _kw(node: ast.Call, name: str) -> ast.keyword | None:
    for kw in node.keywords:
        if kw.arg == name:
            return kw
    return None


def _enclosing(tree: ast.AST, lineno: int) -> str:
    """最内层把这一行包住的 def/class 名（报告里好定位）。"""
    best: tuple[int, str] = (0, "<module>")
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            start = getattr(node, "lineno", 0)
            end = getattr(node, "end_lineno", 0) or 0
            if start <= lineno <= end and start >= best[0]:
                best = (start, node.name)
    return best[1]


def _text_on(node: ast.Call) -> bool:
    """`text=` 是不是真开着（`text=True` 或任何真值常量）。"""
    text_kw = _kw(node, "text")
    if text_kw is None:
        return False
    if getattr(text_kw.value, "value", False) is True:
        return True
    return isinstance(text_kw.value, ast.Constant) and bool(text_kw.value.value)


def scan_source(src: str, label: str = "<src>") -> list[str]:
    """扫一段源码，返回 `标签:行: 函数名: 缺 encoding` 形式的违规清单。"""
    tree = ast.parse(src)
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_subprocess_call(node):
            continue
        if not _text_on(node):
            continue
        if _kw(node, "encoding") is not None:
            continue
        note = "缺 encoding"
        if _kw(node, "errors") is None:
            note += "，也缺 errors"
        hits.append(f"{label}:{node.lineno}: {_enclosing(tree, node.lineno)}: {note}")
    return hits


def scan_file(path: Path) -> list[str]:
    """扫一个文件；读不动/解析不了就跳过（不因一个坏文件把整道门判红）。"""
    try:
        src = _read_text_bw(path, encoding="utf-8", newline="")
    except (UnicodeDecodeError, OSError):
        return []
    try:
        return scan_source(src, path.as_posix())
    except SyntaxError:
        return []


def _candidate_calls(src: str) -> int:
    """带 `text=True` 的子进程调用数（正反两用：证明扫描器真在看）。"""
    tree = ast.parse(src)
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _is_subprocess_call(node) and _text_on(node)
    )


def test_repo_calls_all_carry_encoding() -> None:
    """★ 真仓扫描：`scripts/` `tools/` `tests/` 里不许有 `text=True` 缺 `encoding=` 的调用。"""
    hits: list[str] = []
    scanned = 0
    candidates = 0
    for d in SCAN_DIRS:
        base = ROOT / d
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            # ★ 卡 E59：判据必须比**相对仓根**的分量 —— 卡树住在 `.wt/<卡号>` 里，
            #   拿绝对路径的 parts 去比 `.wt` 会把整棵树一起跳掉（scanned=0 假红）。
            if SKIP_PARTS & set(path.relative_to(ROOT).parts):
                continue
            scanned += 1
            hits.extend(scan_file(path))
            try:
                candidates += _candidate_calls(_read_text_bw(path, encoding="utf-8", newline=""))
            except (UnicodeDecodeError, OSError, SyntaxError):
                continue

    # 防空转：扫描器「什么都没扫到」也会返回零命中，那种绿是假的。
    assert scanned >= 200, f"只扫到 {scanned} 个 .py，扫描范围坏了"
    assert candidates >= 150, f"只看到 {candidates} 个 text=True 调用，判据没在看"

    assert not hits, (
        "以下调用在云门禁机（cp936）遇到中文输出会 UnicodeDecodeError、"
        "r.stdout 变 None 再炸下游：\n  " + "\n  ".join(hits)
    )


def test_scanner_bites_on_a_planted_violation(tmp_path: Path) -> None:
    """★ 反向用例：钉子必须咬得住 —— 造违规能抓到，跨行合规不误报。"""
    planted = tmp_path / "planted.py"
    planted.write_text(
        "import subprocess\n"
        "\n"
        "\n"
        "def release_lock(wt):\n"
        "    subprocess.run(\n"
        '        ["git", "status", "--porcelain"],\n'
        "        cwd=str(wt),\n"
        "        capture_output=True,\n"
        "        text=True,\n"
        "        check=False,\n"
        "    )\n"
        "\n"
        "\n"
        "def compliant(wt):\n"
        "    # encoding= 故意写在**下一行**：grep 会在这里假绿，AST 不会。\n"
        "    return subprocess.run(\n"
        '        ["git", "log", "-1"],\n'
        "        cwd=str(wt),\n"
        "        capture_output=True,\n"
        "        text=True,\n"
        '        encoding="utf-8",\n'
        '        errors="replace",\n'
        "        check=False,\n"
        "    )\n",
        encoding="utf-8",
        newline="",
    )

    hits = scan_file(planted)

    assert len(hits) == 1, f"应该只抓到违规那一处，实际：{hits}"
    assert "planted.py:5:" in hits[0], hits[0]
    assert "release_lock" in hits[0], hits[0]
    assert "缺 encoding" in hits[0], hits[0]
    assert "也缺 errors" in hits[0], hits[0]
    assert "compliant" not in hits[0], f"跨行写了 encoding= 的调用被误报：{hits[0]}"


# ---------------------------------------------- 8. `encoding=` 必须配 `errors=`
#: 这一段是「缺 encoding」的**镜像**：`scan_source` 只问 `encoding=` 在不在，给了
#: `encoding=` 却不给 `errors=` 的调用它照样放行 —— 而云机（cp936）上那条
#: `UnicodeDecodeError` 恰恰是从「只有 encoding」这条路进来的：编码选对了，
#: 字节不合法一样炸。给 `encoding=` 的所有子进程调用一律要 `errors="replace"`。
MIN_SCANNED_FILES = 200
MIN_CALLS_WITH_ENCODING = 200


def scan_missing_errors(src: str, label: str = "<src>") -> list[str]:
    """扫一段源码，返回「有 `encoding=` 但缺 `errors=`」的违规清单（`标签:行: 函数名`）。"""
    tree = ast.parse(src)
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_subprocess_call(node):
            continue
        if _kw(node, "encoding") is None or _kw(node, "errors") is not None:
            continue
        func = _enclosing(tree, node.lineno)
        hits.append(f"{label}:{node.lineno}: {func}: 有 encoding 缺 errors")
    return hits


def scan_file_missing_errors(path: Path) -> list[str]:
    """扫一个文件；读不动/解析不了就跳过（同 `scan_file` 的口径，不因坏文件误红）。"""
    try:
        src = _read(path)
    except (UnicodeDecodeError, OSError):
        return []
    try:
        return scan_missing_errors(src, path.as_posix())
    except SyntaxError:
        return []


def _encoding_calls(src: str) -> int:
    """带 `encoding=` 的子进程调用数（防空转用：证明判据真在看）。"""
    tree = ast.parse(src)
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _is_subprocess_call(node) and _kw(node, "encoding")
    )


def test_repo_calls_with_encoding_also_carry_errors() -> None:
    """★ 真仓扫描：给了 `encoding=` 就必须同时给 `errors="replace"`。

    判据是**镜像**而不是重复：`test_repo_calls_all_carry_encoding` 管「有没有
    encoding」；这条管「有了 encoding 之后，非法字节会不会把整条调用炸掉」。
    """
    hits: list[str] = []
    scanned = 0
    with_encoding = 0
    for d in SCAN_DIRS:
        base = ROOT / d
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            # ★ 卡 E59：判据必须比**相对仓根**的分量 —— 卡树住在 `.wt/<卡号>` 里，
            #   拿绝对路径的 parts 去比 `.wt` 会把整棵树一起跳掉（scanned=0 假红）。
            if SKIP_PARTS & set(path.relative_to(ROOT).parts):
                continue
            scanned += 1
            hits.extend(scan_file_missing_errors(path))
            try:
                with_encoding += _encoding_calls(_read(path))
            except (UnicodeDecodeError, OSError, SyntaxError):
                continue

    # 防空转：扫描器「什么都没扫到」也返回零命中，那种绿是假的。
    # 补 errors 改完那一刻实测：361 个 .py / 245 处带 encoding=。
    assert scanned >= MIN_SCANNED_FILES, f"只扫到 {scanned} 个 .py，扫描范围坏了"
    assert with_encoding >= MIN_CALLS_WITH_ENCODING, (
        f"只看到 {with_encoding} 个带 encoding= 的调用，判据没在看"
    )

    assert not hits, (
        '以下调用给了 encoding= 却没给 errors="replace"：编码选对不代表字节合法，'
        "云机（cp936）上子进程吐一个 0xff 就 UnicodeDecodeError：\n  " + "\n  ".join(hits)
    )


def test_missing_errors_scanner_bites_on_a_planted_violation(tmp_path: Path) -> None:
    """★ 反向用例：造一处「有 encoding 缺 errors」，钉子必须咬住；合规/不解码都不误报。"""
    planted = tmp_path / "planted_no_errors.py"
    planted.write_text(
        "import subprocess\n"
        "\n"
        "\n"
        "def legacy(wt):\n"
        "    # 只有 encoding、没有 errors：云机上遇到非法字节就 UnicodeDecodeError。\n"
        "    return subprocess.run(\n"
        "        ['git', 'log'],\n"
        "        cwd=str(wt),\n"
        "        capture_output=True,\n"
        "        text=True,\n"
        '        encoding="utf-8",\n'
        "    )\n"
        "\n"
        "\n"
        "def compliant(wt):\n"
        "    return subprocess.run(\n"
        "        ['git', 'diff'],\n"
        "        cwd=str(wt),\n"
        "        capture_output=True,\n"
        "        text=True,\n"
        '        encoding="utf-8",\n'
        '        errors="replace",\n'
        "    )\n"
        "\n"
        "\n"
        "def undecoded(wt):\n"
        "    # 压根不解码的调用不归这条判据管。\n"
        "    return subprocess.run(\n"
        "        ['git', 'cat-file', '-p', 'HEAD'],\n"
        "        cwd=str(wt),\n"
        "        capture_output=True,\n"
        "    )\n",
        encoding="utf-8",
        newline="",
    )

    hits = scan_file_missing_errors(planted)

    assert len(hits) == 1, f"应该只抓到 legacy 那一处，实际：{hits}"
    assert "planted_no_errors.py:6:" in hits[0], hits[0]
    assert "legacy" in hits[0], hits[0]
    assert "有 encoding 缺 errors" in hits[0], hits[0]
    assert "compliant" not in hits[0], f"带 errors= 的调用被误报：{hits[0]}"
    assert "undecoded" not in hits[0], f"压根不解码的调用被误报：{hits[0]}"

# ---------------------------------------------------------------- 落地点逐处钉

LANDING = ROOT / "tools" / "pool" / "landing.py"
RUN_GATES = ROOT / "scripts" / "run_gates.py"

#: 裸 `.stdout.strip()`：`capture_output=True` + 解码失败时 `stdout` 是 `None` ⇒ AttributeError。
BARE_STDOUT_STRIP = re.compile(r"\.stdout\.strip\(\)")
FALLBACK_STDOUT = 'stdout or ""'

#: `landing.py` 里必须逐个给 `encoding="utf-8", errors="replace"` 的两处锁调用。
LANDING_LOCK_FUNCS: tuple[str, ...] = ("release_lock", "_renewer_loop")

_MISSING = object()


def _read(path: Path) -> str:
    """按字节读、不做换行翻译（`scripts/run_gates.py` 里有历史遗留的多重 CR）。"""
    return _read_text_bw(path, encoding="utf-8", newline="")


def _func_node(tree: ast.Module, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    """取指定名字的函数节点；找不到直接失败（改名了就得改判据，不许静默空转）。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(f"找不到函数 {name}（改名了就把判据一起改，别让它静默空转）")


def _subprocess_calls_in(node: ast.AST) -> list[ast.Call]:
    return [n for n in ast.walk(node) if isinstance(n, ast.Call) and _is_subprocess_call(n)]


def _kw_literal(call: ast.Call, name: str) -> object:
    """关键字的**字面量**值；没给返回 `_MISSING`，给了非字面量返回 `"<非字面量>"`。"""
    kw = _kw(call, name)
    if kw is None:
        return _MISSING
    return getattr(kw.value, "value", "<非字面量>")


def scan_text_mode_encoding(
    src: str, func_names: tuple[str, ...], label: str = "<src>"
) -> list[str]:
    """在指定函数里找 `text=True` 但 `encoding`/`errors` 不是 utf-8/replace 的调用。

    ★ 这是对 `scan_source` 的**加强**：`scan_source` 只问「有没有 encoding=」，
    给个 `encoding="gbk"` 它照样放过 —— 而云机要的是 utf-8 + replace。
    """
    tree = ast.parse(src)
    hits: list[str] = []
    for name in func_names:
        for call in _subprocess_calls_in(_func_node(tree, name)):
            if not _text_on(call):
                continue
            enc = _kw_literal(call, "encoding")
            err = _kw_literal(call, "errors")
            bad: list[str] = []
            if enc is _MISSING:
                bad.append("缺 encoding")
            elif enc != "utf-8":
                bad.append(f"encoding={enc!r}（应 utf-8）")
            if err is _MISSING:
                bad.append("缺 errors")
            elif err != "replace":
                bad.append(f"errors={err!r}（应 replace）")
            if bad:
                hits.append(f"{label}:{call.lineno}: {name}: {'，'.join(bad)}")
    return hits


def scan_bare_stdout_strip(src: str, label: str = "<src>") -> list[str]:
    """找裸 `.stdout.strip()`（`stdout` 可能是 `None` ⇒ 云机上 AttributeError）。"""
    return [
        f"{label}:{lineno}: {line.strip()}"
        for lineno, line in enumerate(src.splitlines(), start=1)
        if BARE_STDOUT_STRIP.search(line)
    ]


def scan_host_payload(src: str, label: str = "<src>") -> list[str]:
    """`gates/last.json` 的 payload 必须记 `"host": socket.gethostname()`。

    只认 `import socket` + **payload 字典字面量**里的 `host` 键：
    云机回传没有 host ⇒ 落地链的「必须是云机跑的」永远判不过。
    ★ 边界：`seal()` 不写 payload，只有 `main()` 写 —— 所以 `--seal` 之后
    `gates/last.json` 里没有 host 是正常的，判据不碰那一条路径。
    """
    tree = ast.parse(src)
    problems: list[str] = []
    has_socket = any(
        isinstance(n, ast.Import) and any(a.name == "socket" for a in n.names)
        for n in ast.walk(tree)
    )
    if not has_socket:
        problems.append(f"{label}: 没有 import socket")
    payload: ast.Dict | None = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Dict):
            continue
        if any(isinstance(t, ast.Name) and t.id == "payload" for t in node.targets):
            payload = node.value
            break
    if payload is None:
        problems.append(f'{label}: 找不到 payload 字典字面量（"host" 键没处可挂）')
        return problems
    value: ast.expr | None = None
    for key, val in zip(payload.keys, payload.values, strict=True):
        if isinstance(key, ast.Constant) and key.value == "host":
            value = val
            break
    if value is None:
        problems.append(f'{label}: payload 没有 "host" 键')
        return problems
    ok = (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Attribute)
        and value.func.attr == "gethostname"
        and isinstance(value.func.value, ast.Name)
        and value.func.value.id == "socket"
    )
    if not ok:
        problems.append(f'{label}: payload["host"] 不是 socket.gethostname()')
    return problems


def test_landing_lock_calls_carry_encoding() -> None:
    """★ `landing.py` 的两处锁调用（`release_lock` / `_renewer_loop`）必带 utf-8 + replace。

    这两处原本是 `capture_output=True, text=True` 裸的：云机 cp936 下 `gate_lock.py`
    吐中文就崩；`contextlib.suppress(Exception)` 又会把异常**吞掉** ⇒ 锁续不上、没人知道。
    """
    hits = scan_text_mode_encoding(_read(LANDING), LANDING_LOCK_FUNCS, "tools/pool/landing.py")
    assert not hits, "锁调用在云机（cp936）会 UnicodeDecodeError：\n  " + "\n  ".join(hits)

    # 防空转：这两个函数里真得有 `text=True` 的调用，否则判据什么都没看。
    tree = ast.parse(_read(LANDING))
    checked = sum(
        1
        for name in LANDING_LOCK_FUNCS
        for call in _subprocess_calls_in(_func_node(tree, name))
        if _text_on(call)
    )
    assert checked >= 2, f"只看到 {checked} 处 text=True 的锁调用，判据没在看"


def test_landing_has_no_bare_stdout_strip() -> None:
    """★ `landing.py` 不许有裸 `.stdout.strip()`（③ sync_counts / ⑤ seal / ⑦ audit 三处）。

    解码失败时 `r.stdout` 是 `None`，`.strip()` 直接 AttributeError —— 本机 utf-8
    永远看不到，云机一跑就炸。正解是 `(r.stdout or "").strip()`。
    """
    src = _read(LANDING)
    hits = scan_bare_stdout_strip(src, "tools/pool/landing.py")
    assert not hits, "以下位置在 stdout 为 None 时会 AttributeError：\n  " + "\n  ".join(hits)
    # 防空转：文件里确实有大量 .stdout 用法，且已有 `或空串` 的兜底写法。
    n_dot_stdout = src.count(".stdout")
    n_fallback = src.count(FALLBACK_STDOUT)
    assert n_dot_stdout >= 20, f"只看到 {n_dot_stdout} 处 .stdout，判据没在看"
    assert n_fallback >= 10, f"只看到 {n_fallback} 处 `… stdout or 空串` 兜底写法，判据可能换了形状"


def test_run_gates_payload_records_host() -> None:
    """★ `scripts/run_gates.py` 的 payload 必须记 `"host": socket.gethostname()`。

    ★ 边界（如实写）：`seal()` **不写** payload —— `--seal` 之后 `gates/last.json`
    里没有 host 是正常的；只有 `main()` 那一趟全量跑才写。
    """
    problems = scan_host_payload(_read(RUN_GATES), "scripts/run_gates.py")
    assert not problems, (
        "云机回传没有 host ⇒ 落地链的「必须是云机跑的」永远判不过：\n  " + "\n  ".join(problems)
    )


# ★ 这条用例**故意**跑一个不带 encoding= 的调用，3.14 会把 UnicodeDecodeError 抛在
#   `_readerthread` 里 ⇒ pytest 记成 PytestUnhandledThreadExceptionWarning。
#   那是本用例要证明的现象，不是噪音；限定到这一条，别放宽到整个会话。
@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_text_mode_without_encoding_loses_output_on_undecodable_bytes() -> None:
    """★ 真跑一条：`text=True` 不给 `encoding=` ⇒ 不可解码的字节**把 stdout 变成 None**。

    这不是只读源码：子进程真吐 `0xff 0xfe 0x41`，本机 utf-8 / 云机 cp936 都解不了。
    - 3.14：解码在 `_readerthread` 里做，`UnicodeDecodeError` 只打到 stderr、**被线程吞掉**，
      `r.stdout` 变成 `None` ⇒ 下游 `r.stdout.strip()` 抛 AttributeError（云机事故原样）；
    - 更老的版本会在主线程直接抛 `UnicodeDecodeError`。
    两种情况都是「本机 utf-8 看不见的雷」，而 `encoding="utf-8", errors="replace"`
    一条都不犯：既不抛、也不返回 None。
    """
    code = (
        "import sys\n"
        "sys.stdout.buffer.write(bytes([0xFF, 0xFE, 0x41]))\n"
        "sys.stdout.buffer.flush()\n"
    )
    # ★ 故意不带 encoding= —— 为的是把违规配置真跑一遍。
    #   用字典展开构造，调用点上没有 `text=True` 字面量，
    #   `test_repo_calls_all_carry_encoding` 不会把这条反向用例自己判成违规。
    bad_kwargs: dict[str, object] = {"capture_output": True, "check": False, "text": True}
    try:
        broken = subprocess.run([sys.executable, "-c", code], **bad_kwargs)  # type: ignore[arg-type]
    except UnicodeDecodeError:
        pass  # 老版本：主线程直接抛，同样证明「不带 encoding= 会炸」
    else:
        assert broken.stdout is None, f"没带 encoding= 却解出了文本：{broken.stdout!r}"
        with pytest.raises(AttributeError):
            broken.stdout.strip()  # type: ignore[union-attr]

    fixed = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert fixed.stdout is not None, "带了 encoding= 却仍是 None"
    assert "\ufffd" in fixed.stdout, f"没拿到替换符，实际：{fixed.stdout!r}"


def test_landing_and_payload_detectors_bite_on_planted_violations(tmp_path: Path) -> None:
    """★ 反向用例：上面三道源码判据都必须咬得住（造违规 ⇒ 抓到；合规 ⇒ 不误报）。"""
    planted = tmp_path / "planted_landing.py"
    planted.write_text(
        "import subprocess\n"
        "\n"
        "\n"
        "def release_lock(wt):\n"
        "    subprocess.run(['git', 'status'], cwd=str(wt),\n"
        "                   capture_output=True, text=True)\n"
        "\n"
        "\n"
        "def _renewer_loop(wt):\n"
        "    subprocess.run(['git', 'log'], cwd=str(wt), capture_output=True,\n"
        "                   text=True, encoding='gbk', errors='ignore')\n"
        "\n"
        "\n"
        "def compliant(wt):\n"
        "    return subprocess.run(['git', 'diff'], cwd=str(wt), capture_output=True,\n"
        "                          text=True, encoding='utf-8', errors='replace')\n"
        "\n"
        "\n"
        "def noisy(wt):\n"
        "    return subprocess.run(['git', 'diff'], cwd=str(wt), capture_output=True,\n"
        "                          text=True, encoding='utf-8', errors='replace').stdout.strip()\n",
        encoding="utf-8",
        newline="\n",
    )
    src = planted.read_text(encoding="utf-8")

    enc_hits = scan_text_mode_encoding(src, LANDING_LOCK_FUNCS, "planted")
    assert len(enc_hits) == 2, f"两处锁调用都该被抓到，实际：{enc_hits}"
    assert "缺 encoding" in enc_hits[0] and "缺 errors" in enc_hits[0], enc_hits[0]
    assert "encoding='gbk'" in enc_hits[1], enc_hits[1]
    assert "errors='ignore'" in enc_hits[1], enc_hits[1]
    assert all("compliant" not in h for h in enc_hits), f"合规调用被误报：{enc_hits}"

    strip_hits = scan_bare_stdout_strip(src, "planted")
    assert len(strip_hits) == 1, f"应只抓到 noisy 那一处，实际：{strip_hits}"
    # 行号由源码现算，不写死：写死会在补一行注释后就假红。
    noisy_line = next(
        i for i, line in enumerate(src.splitlines(), start=1) if ".stdout.strip()" in line
    )
    assert strip_hits[0].startswith(f"planted:{noisy_line}:"), strip_hits[0]
    assert "compliant" not in strip_hits[0], f"带兜底的调用被误报：{strip_hits[0]}"

    planted_gate = tmp_path / "planted_gates.py"
    planted_gate.write_text(
        "import os\n"
        "\n"
        "payload = {'rev': os.getcwd(), 'ok': True}\n",
        encoding="utf-8",
        newline="\n",
    )
    problems = scan_host_payload(planted_gate.read_text(encoding="utf-8"), "planted_gates")
    assert any("没有 import socket" in p for p in problems), problems
    assert any('没有 "host" 键' in p for p in problems), problems


# 正则/子进程/临时目录都是新用例要的，统一放在这份补丁里加进导入区。
