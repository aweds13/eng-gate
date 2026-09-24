"""跑质量门并**落盘结果**（`gates/last.json`），供 `scripts/audit_progress.py` 核对。

为什么要落盘：以前"pytest 284 passed"只是我在报告里打的一行字，**没人能验证**。
现在门禁由脚本执行、结果结构化写到 `gates/last.json` 并随代码提交 ——
提交里的 `Gates:` trailer 就有产物支撑，换个人/换个窗口复跑也能得到同样判断。

用法（**三层速度，按需要挑**）
    python -X utf8 scripts/run_gates.py --fast   # ① 十几秒：ruff/护栏/审计（内循环，不落盘）
    python -X utf8 scripts/run_gates.py --quick  # ② ~90 秒：跳过真机层（提交前够用）
    python -X utf8 scripts/run_gates.py          # ③ 全量（三层一起，~3 分钟；验收/封版前用它）
    python -X utf8 scripts/run_gates.py --no-reuse   # 不信复用记录，全部真跑一遍
    python -X utf8 scripts/run_gates.py --serial     # 全串行（对照"并行下偶发失败"用）

★ T-G47 提速（判定不变，只是不再"一个速度用到底"）
  1. **三层**：`--fast`（十几秒）→ `--quick`（~90 秒）→ 全量（~3 分钟）。
     `--fast` **不写 `gates/last.json`** —— 它不是提交闸，写了就会让"门禁产物与提交一致"
     这条审计失效（那才是最坏的：用半轮结果冒充一轮）。
  2. **两条泳道并行**：轻门（pytest / ruff / mypy / 三道护栏 / 两道审计 / 两个真机 HTTP 检查）
     与浏览器层（render / ui_flow）**同时跑**。这两层互不依赖：
     各自 `serve.py --fresh`（临时库）、各自浏览器 profile（按端口分目录）、端口互不相同
     （render 8531/8532、ui_flow 8541~8544，`web_live` 的局域网自检改成自动挑空闲端口）。
     实测 412s → **~185s**（受最长的那条 ui_flow 决定，32 核机器上不构成 CPU 争用）。
  3. **输入没变就复用上次判定**（`gates/reuse.json`，**带输入哈希留痕**）：
     render / ui_flow 这类真机层的**输入是"网页资源 + 服务端 + 门上自己的脚本 + 黄金"** ——
     这些都没动时，判定**不可能**变（不是"懒得跑"，是"跑的是同一件事"）。
     ★ **pytest 永不复用**：它是唯一"从行为上证明功能还在"的那层，也是唯一能发现
       "谁动了 `src/` 却以为无关"的那层。跳过它省 66 秒，代价是把整条安全网摘掉。

pytest 会**并行**跑（装了 `pytest-xdist` 时 `-n auto`）：用例之间没有共享状态（各自 tmp 库 +
各自进程内的事实总线），而每个用例都要起真 app + 真库 —— 串行是这里唯一的瓶颈。
覆盖率照旧判 70% 那道门（pytest-cov 会合并各 worker 的数据）。

约定（与用户确认）：**门禁或审计任一不通过 → 退出码非零 → 不许提交**。
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GATES = ROOT / "gates" / "last.json"
REUSE = ROOT / "gates" / "reuse.json"
PY = sys.executable

COMMON = [
    ("pytest", []),                # 占位：按有没有 pytest-xdist 决定并行/串行（见 pytest_cmd）
    # 验收层只跑 2 个用例，必须关掉全局 addopts 里的覆盖率门，否则"覆盖率不达标"会误判验收失败
    ("acceptance", [PY, "-m", "pytest", "-m", "acceptance", "--no-cov"]),
    ("ruff", [PY, "-m", "ruff", "check", "src/", "tests/", "scripts/", "tools/", "examples/"]),
    ("mypy", [PY, "-m", "mypy", "src/"]),
    ("check_layers", [PY, "-X", "utf8", "scripts/check_layers.py"]),
    ("check_layers_selftest", [PY, "-X", "utf8", "scripts/test_check_layers.py"]),
    # 对比度审美门（T-G27 建 → T-G42 收紧）：令牌层的 WCAG 对比度。
    # T-G42 把登记表清空了，所以这里换成 **--strict** —— 它从"棘轮"变成**硬门**：
    # 任何一条不达 AA 都当场红（连"登记一下先欠着"这条退路也一并关掉）。
    # 来由见 `复盘/视觉线第0.5步-对比度与状态色-T-G42.md`，边界见该工具的 docstring。
    ("contrast", [PY, "-X", "utf8", "tools/contrast_audit.py", "--strict"]),
    # 风格一致性体检（T-G29）：「融洽」里**能机器判**的那一半 —— 同形状重复 / 一次性裸值 /
    # 缺 :hover·:focus-visible / 动效越界。它只证明「体系里没有新的破例」，**不证明好看**。
    ("style", [PY, "-X", "utf8", "tools/style_audit.py", "--check"]),
    # 命令表检查（T-G31）：四个面（界面/⌘K/CLI/AI·MCP）共用的那一个源，必须与三个真源对得上 ——
    # 契约层的 OP、app.py 的路由、界面 ACTIONS/VIEWS。"洞"（没填出路由/入口的行）是进度不是错误。
    ("commands", [PY, "-X", "utf8", "scripts/check_commands.py", "--check"]),
    ("ui_dom_probe", []),          # 占位：下面按 node 是否可用来填
    ("audit", [PY, "-X", "utf8", "scripts/audit_progress.py", "--all"]),
    # 台账↔规格 标题对账（T-D2）：`--check` 一发现「确定错位」或「无规格对应的 SR 卡」就退 1。
    # 2026-09-20 校正前它挂的是"信息性"（blocking=false）—— 因为台账里 F/NF 两层编号错位还没修，
    # 一接进来就会 FAIL。T-D1 校正完（见 `复盘/台账编号校正-方案A落地.md`）后转正为阻断项。
    ("audit_titles", [PY, "-X", "utf8", "scripts/audit_titles.py", "--check"]),
]
# 真机层：起真服务 / 真浏览器。轻的那两个（HTTP 层）跟轻门同一泳道，重的两个自己一条泳道。
REAL_PY = [
    ("lf1_live", [PY, "-X", "utf8", "tools/lf1_live_check.py"]),
    ("web_live", [PY, "-X", "utf8", "tools/web_live_check.py"]),
]
# 渲染验证层（T-G32）：真浏览器把 3 档宽度 × 14 个视图各渲染一遍，采成"几何清单"与黄金逐字节比。
# 那一层里**每次采两遍**做确定性自检：不一致 = 工具自己不可信（退出码 4），不当成"界面变了"。
# 退出码 3 = 起不了真浏览器 → 记 `not_run`：**NOT RUN 不是 PASS**（last.json 单列一栏 +
# trailer 里写 NOT RUN）。
# 行为流层（T-G34）：真浏览器 + 真点击 + 真按键，把「待人工确认」里功能性的那些搬给机器。
# 每轮默认**跑两遍**（各自新库 + 新浏览器）比对断言指纹，不一致同样退 4。
BROWSER = ("render", "ui_flow")
# ① --fast：开发内循环用。挑的是"**改一行就能犯、且十几秒内查得出来**"的那几道 ——
# 尤其 audit（TOML/台账语法，实测犯过 5 次）与 contrast/style（照抄包时最容易抄错的令牌层）。
FAST = ("ruff", "contrast", "style", "commands", "audit", "audit_titles")
# 这些门是 **node 脚本**：环境里没有 node 时就跑不了 —— 统一记 `not_run`（不许静默跳过当通过）。
NODE_TOOLS = ("ui_dom_probe", "render", "ui_flow")
# 信息性检查（只报告、不阻断）—— 当前为空：`audit_titles` 已转正为阻断项（T-D2 收口）。
INFO_GATES: list[tuple[str, list[str]]] = []
SUCCESS_HINTS = ("passed", "failed", "error", "PASS", "Success", "checks passed", "OK")

# ---------------------------------------------------------------- 复用（T-G47）
# 每道真机门的**输入**：这些文件一动，判定就可能变 → 必须真跑。
# 刻意写宽一点（宁可多跑一次，也不要"以为无关"）：`src/**` 一律算输入。
REUSE_INPUTS: dict[str, tuple[str, ...]] = {
    "render": ("src/**", "tools/render_check.mjs", "tools/tf_browser.mjs", "tools/serve.py",
               "gates/render/*.txt"),
    "ui_flow": ("src/**", "tools/ui_flow_check.mjs", "tools/tf_browser.mjs", "tools/serve.py"),
    "lf1_live": ("src/**", "tools/lf1_live_check.py", "tools/serve.py"),
    "web_live": ("src/**", "tools/web_live_check.py", "tools/serve.py"),
    "ui_dom_probe": ("src/web/**", "tools/ui_dom_probe.mjs"),
}
REUSABLE = tuple(REUSE_INPUTS)


def input_hash(patterns: tuple[str, ...]) -> str:
    """把一组 glob 命中的**文件内容**哈希起来（路径 + 内容，稳定排序）。"""
    digest = hashlib.sha256()
    files: list[Path] = []
    for pattern in patterns:
        files.extend(p for p in ROOT.glob(pattern) if p.is_file())
    for path in sorted(set(files), key=lambda p: p.as_posix()):
        digest.update(path.relative_to(ROOT).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()[:16]


def load_reuse() -> dict[str, dict[str, str]]:
    if not REUSE.exists():
        return {}
    try:
        data = json.loads(REUSE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def save_reuse(records: dict[str, dict[str, str]]) -> None:
    REUSE.parent.mkdir(parents=True, exist_ok=True)
    REUSE.write_text(
        json.dumps(records, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )


def dom_probe_cmd() -> list[str] | None:
    """假 DOM 渲染探针：真跑 9 个视图。node 不在就跳过（不谎报通过）。"""
    node = shutil.which("node")
    return [node, str(ROOT / "tools" / "ui_dom_probe.mjs")] if node else None


def render_cmd() -> list[str] | None:
    """渲染验证层：真浏览器采几何清单与黄金比。node 不在就跳过（不谎报通过）。"""
    node = shutil.which("node")
    return [node, str(ROOT / "tools" / "render_check.mjs")] if node else None


def ui_flow_cmd() -> list[str] | None:
    """行为流层（T-G34）：真浏览器真点真按，验功能性的验收项。node 不在就跳过。"""
    node = shutil.which("node")
    return [node, str(ROOT / "tools" / "ui_flow_check.mjs")] if node else None


# 这三门都是 **node 脚本**：环境里没有 node 就跑不了 —— 统一记 `not_run`（不许静默跳过当通过）。
NODE_CMD = {
    "ui_dom_probe": dom_probe_cmd,
    "render": render_cmd,
    "ui_flow": ui_flow_cmd,
}


def xdist_available() -> bool:
    """装了 `pytest-xdist` 吗？没装就串行跑 —— **不谎报**，也不因为缺插件把门禁弄红。"""
    probe = subprocess.run(
        [PY, "-c", "import xdist"], capture_output=True, text=True, check=False
    )
    return probe.returncode == 0


def pytest_cmd(serial: bool = False) -> list[str]:
    """pytest 那条命令：装了 xdist 就 `-n auto` 并行，否则串行。

    为什么可以并行（T-G7 实测的结论）：每个用例都起**真 app + 真库**（单次 `create_app()` ≈ 190ms、
    `connect + 迁移` ≈ 26ms），757 个用例串行要 3~4 分钟，而**用例之间没有共享状态** ——
    各自 `tmp_path` 一个库、各自进程内的 facts 总线，所以这是"安全的那一类提速"。
    覆盖率不受影响：pytest-cov 会把各 worker 的数据合并后，再判 `--cov-fail-under=70`。
    `--serial` 是给"并行下偶发失败"用的对照跑法（同一条命令、单进程）。
    """
    cmd = [PY, "-m", "pytest"]
    if not serial and xdist_available():
        cmd += ["-n", "auto"]
    return cmd


def env() -> dict[str, str]:
    e = dict(os.environ)
    shim = str(ROOT / "tools" / "sandbox_shim")
    e["PYTHONPATH"] = shim + (os.pathsep + e["PYTHONPATH"] if e.get("PYTHONPATH") else "")
    return e


def summarize(out: str) -> str:
    """抓一行结论（供 trailer 用）。

    注意：Windows 命令输出里常有中文警告，直接取"最后一行含关键词"会抓到 ResourceWarning
    （第一版就抓错了）。所以优先匹配测试框架的**汇总行**，并跳过各类 warning。
    """
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    summary_re = re.compile(r"\d+\s+(passed|failed|error|deselected)|no issues found|checks passed|"
                            r"LAYER CHECKS|SELF-TEST|PASS（|审计通过|OK \]")
    for line in reversed(lines):
        if "Warning" in line or line.startswith("ResourceWarning"):
            continue
        if summary_re.search(line):
            return line[:160]
    for line in reversed(lines):
        if "Warning" in line:
            continue
        if any(k in line for k in SUCCESS_HINTS):
            return line[:160]
    return lines[-1][:160] if lines else ""


def staged_tree() -> str:
    """把"即将提交的内容"（索引 + 工作区）写成一个临时 tree，返回它的哈希。

    为什么不能用 HEAD 的 tree：门禁在**提交前**跑，那时 HEAD 还是上一次提交。
    工作树在提交前后一致，但工作区可能还有未 add 的改动，所以用 `git add -A` 到临时索引后
    `git write-tree` 得到"这次要提交的那棵树"——它与最终提交的 tree 必然相同。
    临时索引放在 `.git/` 下的独立文件里，不动用户真正的索引。
    """
    tmp_index = ROOT / ".git" / "dsh_gates_index"
    if tmp_index.exists():
        tmp_index.unlink()
    env_with_index = dict(os.environ)
    env_with_index["GIT_INDEX_FILE"] = str(tmp_index)
    read = subprocess.run(
        ["git", "read-tree", "HEAD"], cwd=ROOT, env=env_with_index,
        capture_output=True, text=True, check=False,
    )
    if read.returncode != 0:
        return git("rev-parse", "HEAD^{tree}")
    subprocess.run(
        ["git", "add", "-A"], cwd=ROOT, env=env_with_index,
        capture_output=True, text=True, check=False,
    )
    written = subprocess.run(
        ["git", "write-tree"], cwd=ROOT, env=env_with_index,
        capture_output=True, text=True, check=False,
    )
    if tmp_index.exists():
        tmp_index.unlink()
    tree = written.stdout.strip()
    return tree or git("rev-parse", "HEAD^{tree}")


def git(*args: str) -> str:
    # core.quotepath=false：否则 git 把中文路径输出成八进制转义（\345\244\215 这种），
    # 于是"复盘/xxx.md 有没有一起改"这类判断会永远为假（实测踩到，等于中文文档的同步检查失效）。
    r = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    return r.stdout.strip()


def docs_sync_precheck() -> tuple[bool, list[str]]:
    """④ 的前置检查：改了源码就必须同时改台账/changelog/CHECKPOINT（**提交前**就发现）。"""
    changed = set(git("status", "--porcelain").split())
    changed |= set(git("diff", "--cached", "--name-only").split())
    if not any(p.startswith(("src/timeflow/", "src/web/")) for p in changed):
        return True, []
    missing = [n for n in ("docs/traceability.toml", "docs/changelog.md") if n not in changed]
    if not any(p in changed for p in ("复盘/长任务执行协议.md", "复盘/交接-重构进度.md")):
        missing.append("复盘/长任务执行协议.md（或 交接-重构进度.md）")
    return not missing, missing


def seal() -> int:
    """封存：只把 `gates/last.json` 里的 tree 更新为"含本文件自身的最新工作树"。

    为什么需要（自指问题，实测踩到）：`gates/last.json` **本身也是被提交的文件**。
    第一次跑门禁时它被写进工作区，工作树随之改变 → 与刚算出的 tree 不再相等 →
    提交后审计发现"门禁产物与提交不一致"。本步骤在正式提交前把 tree 重算一次即可收敛
    （只改一个字段，不重跑测试）。
    """
    if not GATES.exists():
        print("[FAIL] 还没有 gates/last.json，先跑一次门禁")
        return 1
    payload = json.loads(GATES.read_text(encoding="utf-8"))
    if not payload.get("ok"):
        print("[FAIL] gates/last.json 里 ok=false，封存没有意义（先让门禁通过）")
        return 1
    old = payload.get("tree", "")
    payload["tree"] = staged_tree()
    payload["sealed_at"] = datetime.now().isoformat(timespec="seconds")
    GATES.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"[封存] gates/last.json tree: {old[:12]} → {payload['tree'][:12]}")
    print("[提示] 现在 `git add gates/last.json && git commit` 后，产物与提交的树会一致")
    return 0


# ---------------------------------------------------------------- 跑一道门
PRINT_LOCK = threading.Lock()


def resolve_cmd(name: str, cmds: dict[str, list[str]], serial: bool) -> list[str] | None:
    """把占位命令填实（node 不在 → None = 这一门没跑，记 `not_run`，不算通过）。

    ★ 顺序有讲究（T-G47 实测踩到）：**先**看"是不是占位门"，**再**从 `cmds` 取字面命令。
    反过来写的话（第一版就是），`jobs` 里 `("pytest", [])` / `("render", [])` 这些**空占位**
    会先被 `name in cmds` 命中 → 返回 `[]` → `Popen([])` 在 Windows 上抛
    `OSError: [WinError 87]`（"参数错误"，看不出跟命令有关）→ 那 4 道门全记成"起不来"。
    """
    if name in NODE_CMD:
        return NODE_CMD[name]()
    if name == "pytest":
        return pytest_cmd(serial=serial)
    loaded = cmds.get(name)
    return loaded if loaded else None


def start_gate(name: str, cmd: list[str]) -> tuple[subprocess.Popen[str] | None, float, str]:
    """**在主线程里**把门起起来（返回进程 + 起始时刻 + 错误文本）。

    ★ 为什么"起进程"必须串行、不能放在线程池里（T-G47 实测踩到）：
    多个线程**同时** `subprocess.Popen` 在 Windows 上会随机抛
    `OSError: [WinError 87] 参数错误`（CPython 在 Windows 上创建子进程不是线程安全的：
    句柄继承与 startupinfo 会互相踩）。而"并行"真正需要的是**等输出**那一段 ——
    进程起完就各自在跑了，等待完全可以在线程里做。于是拆成 start / finish 两步。

    一道门**起不来**（解释器不在、命令写错）也如实记成一条 FAIL，而不是让整个门禁脚本崩掉
    —— 崩掉会丢掉其余门的结论，"失败要留下证据"这条先于"这次跑得顺"。
    """
    t0 = time.time()
    try:
        proc = subprocess.Popen(  # noqa: S603
            cmd, cwd=ROOT, env=env(),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
    except OSError as exc:  # 起不来：记 FAIL，别把整轮门禁带走
        return None, t0, f"{type(exc).__name__}: {exc}"
    return proc, t0, ""


def finish_gate(name: str, proc: subprocess.Popen[str], t0: float) -> dict[str, object]:
    """等一道门跑完，汇成它的结果条目（这一半可以放心并行）。"""
    out, _ = proc.communicate()
    item: dict[str, object] = {
        "name": name,
        "exit_code": proc.returncode,
        "seconds": round(time.time() - t0, 2),
        "summary": summarize(out or ""),
    }
    if name in NODE_CMD and proc.returncode == 3:
        item["blocking"] = False
        item["status"] = "NOT RUN"
        item["note"] = "起不了真浏览器：这一层**没有验证**，不算通过"
    with PRINT_LOCK:
        tag = f"{name:<22} exit={proc.returncode}  {item['seconds']}s"
        if item.get("status") == "NOT RUN":
            print(f"[SKIP] {tag}  （起不了真浏览器）")
        else:
            mark = "[OK ]" if proc.returncode == 0 else "[FAIL]"
            print(f"{mark} {tag}  {item['summary']}")
    return item


def dead_gate(name: str, t0: float, why: str) -> dict[str, object]:
    """起不来的门：记一条 FAIL（宁可红，也不要"看起来没这回事"）。"""
    with PRINT_LOCK:
        print(f"[FAIL] {name:<22} 起不来：{why}")
    return {
        "name": name,
        "exit_code": -1,
        "seconds": round(time.time() - t0, 2),
        "summary": f"起不来：{why}",
    }


def skip_reused(name: str, records: dict[str, dict[str, str]], no_reuse: bool) -> str | None:
    """输入没变且上次是通过 → 返回那条记录里的哈希（调用方据此记 `reused`）；否则 None。"""
    if no_reuse or name not in REUSE_INPUTS:
        return None
    record = records.get(name)
    if not record or record.get("verdict") != "pass":
        return None
    current = input_hash(REUSE_INPUTS[name])
    return current if record.get("hash") == current else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="跳过真机层（提交前够用）")
    ap.add_argument("--fast", action="store_true", help="只跑十几秒那几道（内循环；不落盘）")
    ap.add_argument("--serial", action="store_true", help="全串行（对照并行下的偶发失败）")
    ap.add_argument("--no-reuse", action="store_true", help="不信复用记录，真机层全部重跑")
    ap.add_argument("--seal", action="store_true", help="提交前封存：只更新 tree 字段")
    args = ap.parse_args()
    if args.seal:
        return seal()

    jobs: list[tuple[str, list[str]]] = [*COMMON, *REAL_PY]
    if args.fast:
        jobs = [j for j in jobs if j[0] in FAST]
    elif not args.quick:
        jobs += [(n, []) for n in BROWSER]
    cmds = dict(jobs)

    ok_docs: bool = True                     # --fast 不判"文档同提交"（那是提交闸的事）
    missing: list[str] = []
    if args.fast:
        # ★ 这一档**不写 gates/last.json**：它不是提交闸。写了就会让
        # "门禁产物与提交一致"（审计第 ⑤ 条）失效 —— 那是拿半轮结果冒充一轮。
        print("=== --fast：开发内循环（ruff / 护栏 / 审计；**不是提交闸，不落盘**）===")
    else:
        ok_docs, missing = docs_sync_precheck()
        print("=== ④ 文档与代码同提交（提交前检查）===")
        if ok_docs:
            print("  [OK ] 源码有改动时，台账/changelog/CHECKPOINT 都在改动清单里"
                  "（或本轮没改源码）")
        else:
            print(f"  [FAIL] 改了源码但还没同步：{missing}")

    if args.serial:
        mode = "串行（--serial）"
    elif xdist_available():
        mode = "并行（pytest-xdist，-n auto）"
    else:
        mode = "串行（环境里没装 pytest-xdist）"
    if not args.fast:
        print(f"=== pytest 跑法：{mode} ===")

    # 复用判定：只对"输入确实是那几样"的真机门做（--quick 里本来就没有真机层，--fast 更不碰）。
    records = load_reuse()
    reused: dict[str, str] = {}
    todo: list[tuple[str, list[str]]] = []
    not_run: list[str] = []
    for name, _ in jobs:
        mark = None if args.fast else skip_reused(name, records, args.no_reuse)
        if mark is not None:
            reused[name] = mark
            print(f"[REUSE] {name:<22} 输入未变（{mark}）→ 复用上次通过判定")
            continue
        cmd = resolve_cmd(name, cmds, args.serial)
        if cmd is None:
            print(f"[WARN] {name:<22} 跳过：环境里没有 node（未验证，不算通过）")
            not_run.append(name)
            continue
        todo.append((name, cmd))

    order = {name: i for i, (name, _) in enumerate(jobs)}
    results: list[dict[str, object]] = []

    if args.serial:
        # 全串行：给"并行下的偶发失败"当对照跑法（本文件自己的老路径）
        for name, cmd in todo:
            proc, t0, why = start_gate(name, cmd)
            results.append(dead_gate(name, t0, why) if proc is None
                           else finish_gate(name, proc, t0))
    else:
        # **两条泳道并行**：轻门一路、真机浏览器一路（浏览器层 2 条互不依赖：端口 / 临时库 /
        # profile 目录都分开）。
        # ★ 起进程一律在**主线程依次**做（见 start_gate 的注释：多线程同时 Popen 在 Windows 上
        # 会 WinError 87）；并行只发生在"等输出"这一半 —— 而墙钟时间恰恰由等待决定。
        light = [(n, c) for n, c in todo if n not in BROWSER]
        heavy = [(n, c) for n, c in todo if n in BROWSER]
        print(f"=== 泳道：轻门 {len(light)} 道 ∥ 真机浏览器 {len(heavy)} 道（各自内部并行）===")
        started: list[tuple[str, subprocess.Popen[str] | None, float, str]] = []
        for name, cmd in [*heavy, *light]:        # 长的那两条先起，让它俩先跑起来
            proc, t0, why = start_gate(name, cmd)
            started.append((name, proc, t0, why))
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures = [
                pool.submit(dead_gate, n, t0, why) if proc is None
                else pool.submit(finish_gate, n, proc, t0)
                for n, proc, t0, why in started
            ]
            results = [f.result() for f in futures]

    for name, mark in reused.items():
        results.append({
            "name": name,
            "exit_code": 0,
            "seconds": 0,
            "summary": f"复用上次通过判定（输入未变 {mark}）",
            "reused": True,
            "inputs_hash": mark,
        })
    for name in not_run:
        results.append({
            "name": name, "exit_code": 3, "seconds": 0,
            "summary": "环境里没有 node：未验证，不算通过",
            "blocking": False, "status": "NOT RUN",
        })
    # 结果按**固定顺序**排（而不是完成顺序）：last.json 要能逐字节比较，trailer 也要稳定
    results.sort(key=lambda r: order.get(str(r["name"]), 99))

    # 信息性检查：只报告、不阻断（blocking=False，不计进 ok）
    for name, cmd in ([] if (args.quick or args.fast) else INFO_GATES):
        t0 = time.time()
        info_proc = subprocess.run(
            cmd, cwd=ROOT, env=env(), capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=False,
        )
        out = (info_proc.stdout or "") + (info_proc.stderr or "")
        tail = [ln.strip() for ln in out.splitlines() if ln.strip()]
        summary = next(
            (ln[:160] for ln in reversed(tail) if ln.startswith("共 ") or "全部对得上" in ln), ""
        )
        summary = summary or (tail[-1][:160] if tail else "")
        item = {
            "name": name,
            "exit_code": info_proc.returncode,
            "seconds": round(time.time() - t0, 2),
            "summary": summary,
            "blocking": False,
            "note": "信息性：台账↔规格 标题对账；T-D1 完成后改成阻断项（audit_titles.py --check）",
        }
        results.append(item)
        mark = "[OK ]" if info_proc.returncode == 0 else "[WARN]"
        print(f"{mark} {name:<22} exit={info_proc.returncode}  {item['seconds']}s  "
              f"{summary}（不阻断）")

    blocking = [r for r in results if r.get("blocking", True)]
    ok = all(int(str(r["exit_code"])) == 0 for r in blocking)
    if not args.fast:
        ok = ok and ok_docs
    passed = [r for r in blocking if int(str(r["exit_code"])) == 0]

    if args.fast:
        bad = [r for r in blocking if int(str(r["exit_code"])) != 0]
        if bad:
            print(f"\n[FAIL] --fast 里 {len(bad)} 道不通过：{[r['name'] for r in bad]}")
            return 1
        print("\n--fast 全过 ✅（只覆盖「改一行就能犯」那几类；提交前仍要 --quick 或全量）")
        return 0

    payload = {
        "rev": git("rev-parse", "--short", "HEAD"),
        # 注意：**不要**把 tree 当"这一版代码"的凭据 —— gates/last.json 自己也在那棵树里，
        # 写入哈希会让树变化（自指悖论，实测踩到）。这里留着 tree 只作参考，审计不看它。
        "tree": staged_tree(),
        "parent": git("rev-parse", "--short", "HEAD"),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(git("status", "--porcelain")),
        "at": datetime.now().isoformat(timespec="seconds"),
        "quick": args.quick,
        "docs_sync_ok": ok_docs,
        "docs_sync_missing": missing,
        "ok": ok,
        "gates": results,
        # 没验证成的门（当前只有渲染层会遇到：起不了真浏览器）。**不是"通过"**，
        # 单列一栏 + 写进 trailer，让"这次提交哪些东西没被验证过"有据可查。
        "not_run": not_run,
        # 复用了上次判定的门（T-G47）：单列一栏 + 带上输入哈希。**不是"通过"的同义词** ——
        # 它是"这一层的输入一个字节都没变，所以上次那个判定仍然成立"，写出来才禁得住问。
        "reused": {k: v for k, v in reused.items()},
        "trailer": "; ".join(
            [f"{r['name']} {r['summary']}" for r in passed]
            + [f"{n} NOT RUN" for n in not_run]
        ) or "（无通过项）",
    }
    GATES.parent.mkdir(parents=True, exist_ok=True)
    GATES.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    # 复用记录只在**这一轮真跑且通过**时更新（复用过的门保持原记录：哈希本来就一样）
    for name in REUSABLE:
        if name in reused:
            continue
        entry = next((r for r in results if r["name"] == name), None)
        if entry is None or int(str(entry["exit_code"])) != 0:
            continue
        if name in REUSE_INPUTS:
            records[name] = {
                "hash": input_hash(REUSE_INPUTS[name]),
                "verdict": "pass",
                "at": datetime.now().isoformat(timespec="seconds"),
                "what": "输入哈希一致时可复用这条判定（T-G47）",
            }
    save_reuse(records)
    print(f"\n[落盘] gates/last.json  ok={ok}  rev={payload['rev']}")
    used = ", ".join(f"{k}({v})" for k, v in reused.items()) or "无"
    print(f"[复用] {used}")
    print(f"[建议 trailer] Gates: {str(payload['trailer'])[:200]}")
    if not ok:
        print("\n质量门或文档同步未通过 —— **不许提交**（用户约定）。")
        return 1
    print("\n质量门 + 文档同步通过 ✅（下一步：commit 并带上 Task:/Refs:/Gates: trailer）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
