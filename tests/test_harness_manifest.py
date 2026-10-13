"""harness/manifest.py 的硬口径测试（卡 088 · T-G183）。

判据就是卡 §1.2 那句：项目专有值只进仓根 harness.toml；写错（缺文件/坏 TOML/缺段/缺键/
未知键/未知段/空值/非字符串/路径不存在）必须**指名道姓报错**，不许静默默认值。
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import manifest  # noqa: E402

ALL_KEYS = {
    "backlog": "docs/workbacklog.toml",
    "workbench": "tools",
    "gate_lock": "gates/diag/gate_lock.py",
    "gates_runner": "scripts/run_gates.py",
    "ledger": "docs/traceability.toml",
    "changelog": "docs/changelog.md",
    "handoff": "复盘/交接-重构进度.md",
    "handoff_card": "复盘/新窗口交接卡.md",
    "gates_state": "gates/last.json",
    "gates_reuse": "gates/reuse.json",
}


def write_cfg(tmp: Path, **overrides: str) -> Path:
    """在 tmp 写一份最小合法 harness.toml；overrides 可覆盖/删除（值给 None=删掉该键）。"""
    values = dict(ALL_KEYS)
    values.update(overrides)
    lines = ["[paths]"]
    for key, value in values.items():
        if value is not None:
            lines.append(f'{key} = "{value}"')
    cfg = tmp / "harness.toml"
    cfg.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return cfg


@pytest.fixture(autouse=True)
def _reset_cache_and_env(monkeypatch: pytest.MonkeyPatch):
    manifest._CACHE = None
    monkeypatch.delenv(manifest.ENV_OVERRIDE, raising=False)
    yield
    manifest._CACHE = None


def test_real_repo_config_loads_and_paths_resolve():
    """仓根真配置 10 键齐全，must_exist 的 backlog 在盘上。"""
    cfg = manifest.load()
    assert set(cfg) == {"paths"}
    assert set(cfg["paths"]) == set(ALL_KEYS)
    assert manifest.path("paths.backlog", must_exist=True).is_file()
    assert Path(__file__).resolve().parents[1] == manifest.ROOT


def test_load_strips_surrounding_whitespace(tmp_path: Path):
    # 值首尾空白剥掉（路径里带空格是笔误，不该静默保留）
    cfg = tmp_path / "harness.toml"
    body = '[paths]\nworkbench = " wb "\n' + "\n".join(
        f'{k} = "{v}"' for k, v in ALL_KEYS.items() if k != "workbench"
    )
    cfg.write_text(body + "\n", encoding="utf-8")
    assert manifest.load(cfg)["paths"]["workbench"] == "wb"


def test_missing_file_named_in_error(tmp_path: Path):
    with pytest.raises(manifest.ManifestError, match="配置文件不存在") as exc:
        manifest.load(tmp_path / "nope.toml")
    assert "nope.toml" in str(exc.value)
    assert "合法键" in str(exc.value)


def test_bad_toml_named_in_error(tmp_path: Path):
    cfg = tmp_path / "harness.toml"
    cfg.write_text("[paths\nworkbench = 1\n", encoding="utf-8")
    with pytest.raises(manifest.ManifestError, match="不是合法 TOML"):
        manifest.load(cfg)


def test_missing_section(tmp_path: Path):
    cfg = tmp_path / "harness.toml"
    cfg.write_text('[other]\nx = "y"\n', encoding="utf-8")
    with pytest.raises(manifest.ManifestError, match=r"未知段 \['other'\]"):
        manifest.load(cfg)


def test_no_paths_section_at_all(tmp_path: Path):
    cfg = tmp_path / "harness.toml"
    cfg.write_text("# 只有注释\n", encoding="utf-8")
    with pytest.raises(manifest.ManifestError, match="缺段 \\[paths\\]"):
        manifest.load(cfg)


def test_unknown_key_is_a_typo_not_silent(tmp_path: Path):
    cfg = write_cfg(tmp_path, ledger=None)
    cfg.write_text(cfg.read_text(encoding="utf-8") + 'ledgre = "docs/x.toml"\n',
                   encoding="utf-8")
    with pytest.raises(manifest.ManifestError, match=r"未知键 \['ledgre'\]") as exc:
        manifest.load(cfg)
    assert "合法键" in str(exc.value)
    assert "ledger" in str(exc.value)


def test_missing_key_named(tmp_path: Path):
    cfg = write_cfg(tmp_path, gate_lock=None)
    with pytest.raises(manifest.ManifestError, match="缺键 paths.gate_lock"):
        manifest.load(cfg)


@pytest.mark.parametrize("bad", ['workbench = ""', "workbench = 3", "workbench = ['x']"])
def test_value_must_be_nonempty_string(tmp_path: Path, bad: str):
    lines = ["[paths]", bad]
    lines += [f'{k} = "{v}"' for k, v in ALL_KEYS.items() if k != "workbench"]
    cfg = tmp_path / "harness.toml"
    cfg.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(manifest.ManifestError, match="paths.workbench 必须是非空字符串"):
        manifest.load(cfg)


def test_path_relativity_and_must_exist(tmp_path: Path):
    cfg = write_cfg(tmp_path, backlog="no/such.toml")
    # path() 经 get() 读环境旁路指到的临时配置；must_exist=False 只解析不查盘
    old = os.environ.get(manifest.ENV_OVERRIDE)
    os.environ[manifest.ENV_OVERRIDE] = str(cfg)
    manifest._CACHE = None
    try:
        assert manifest.path("paths.backlog") == manifest.ROOT / "no/such.toml"
        with pytest.raises(manifest.ManifestError, match="paths.backlog 指向的路径不存在"):
            manifest.path("paths.backlog", must_exist=True)
    finally:
        if old is None:
            os.environ.pop(manifest.ENV_OVERRIDE, None)
        else:
            os.environ[manifest.ENV_OVERRIDE] = old
        manifest._CACHE = None


def test_absolute_value_passes_through(tmp_path: Path):
    target = tmp_path / "elsewhere.toml"
    target.write_text("x", encoding="utf-8")
    cfg = write_cfg(tmp_path, backlog=target.resolve().as_posix())
    os.environ[manifest.ENV_OVERRIDE] = str(cfg)
    manifest._CACHE = None
    try:
        assert manifest.path("paths.backlog", must_exist=True) == target
    finally:
        os.environ.pop(manifest.ENV_OVERRIDE, None)
        manifest._CACHE = None


def test_get_key_shape_and_unknown_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(manifest.ENV_OVERRIDE, str(write_cfg(tmp_path)))
    manifest._CACHE = None
    assert manifest.get("paths.workbench") == "tools"
    with pytest.raises(manifest.ManifestError, match="段.键"):
        manifest.get("paths")
    with pytest.raises(manifest.ManifestError, match="缺键 paths.nope"):
        manifest.get("paths.nope")
    with pytest.raises(manifest.ManifestError, match=r"段 \[zzz\] 的合法键：\[\]"):
        manifest.get("zzz.nope")


def test_env_override_is_the_only_bypass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    assert manifest.config_path() == manifest.CONFIG_PATH
    alt = write_cfg(tmp_path, workbench="wb-alt")
    monkeypatch.setenv(manifest.ENV_OVERRIDE, str(alt))
    assert manifest.config_path() == alt
    manifest._CACHE = None
    assert manifest.get("paths.workbench") == "wb-alt"


# ================================================================ 复制体 vs 原件（卡 205 · T-G313）
#
# 为什么有这一段：`harness/` 是 `tools/` 的**复制体**，它的不变量是「冻结输入下原件/复制体
# 输出逐字节相同」—— 可卡 203 把原件 `tools/wb_plan.py` 的派活命令改成对的形态（加 `--cwd`、
# 不再 `pushd`）之后，复制体 `harness/wb_plan.py` **悄悄漂了**，而本文件从前**只测
# `harness.toml` 的加载**、从不比较两者 ⇒ 那条不变量破了一路绿灯。下面三条给这条不变量装牙。

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL_WB_PLAN = ROOT / "tools" / "wb_plan.py"
REPLICA_WB_PLAN = ROOT / "harness" / "wb_plan.py"
#: 原件把派活器脚本**写死**在 `tools/wb_dispatch.py`；复制体从 `harness.toml`
#: `paths.workbench` 取目录（本仓 = `tools`）。这是两者之间**唯一**允许的差异（路径前缀）。
ORIGINAL_DISPATCHER = "tools/wb_dispatch.py"
DISPATCHER_PLACEHOLDER = "<工作台>/wb_dispatch.py"


def _import_as(name: str, path: Path, dep_dir: Path):
    """把 `path` 当**独立模块**加载（不占 `wb_plan` 这个常见名），加载期间把 `dep_dir` 挂上
    `sys.path`，完了摘掉。

    两个 `wb_plan` 依赖不同目录：原件 `from pool import …`（要 `tools/` 在 `sys.path`），
    复制体 `import manifest`（要 `harness/`）—— 只有按文件路径加载 + 临时改 `sys.path`
    才能在同一进程里**同时**拿到两个。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(dep_dir))
    # ★ 必须先登记进 sys.modules 再 exec：复制体里有 `@dataclass`，dataclass 的注解解析会
    #   回头查 `sys.modules[cls.__module__]` —— 不登记就 `AttributeError`。
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
        sys.path.remove(str(dep_dir))
    return module


@pytest.fixture(scope="module")
def two_wb_plans():
    """（原件, 复制体）—— 各自独立加载，供下面三条判据逐字比较。"""
    return (
        _import_as("card205_original_wb_plan", ORIGINAL_WB_PLAN, ROOT / "tools"),
        _import_as("card205_replica_wb_plan", REPLICA_WB_PLAN, ROOT / "harness"),
    )


def _frozen_card(tree: str) -> SimpleNamespace:
    """冻结输入的「鸭子卡」—— `render_dispatch`/`dispatch_argv` 只读 `.id/.spec/.tree`。
    用 `SimpleNamespace` 免得在两个模块各自的 `Card` 类之间来回换算。"""
    return SimpleNamespace(id="205", spec="复盘/卡/卡205-harness复制体不许漂.md", tree=tree)


def _dispatcher_token(rendered: str) -> str:
    """渲染行里的**派活器脚本路径**那一段（`python -X utf8 <工作台>/wb_dispatch.py …`）。

    按「以 `wb_dispatch.py` 结尾」认，不按位置认 —— 老 `pushd <树>; …` 形态里它的位置不同。
    """
    tokens = [tok for tok in rendered.split() if tok.endswith("wb_dispatch.py")]
    assert len(tokens) == 1, rendered
    return tokens[0]


def test_card205_replica_renders_the_same_dispatch_as_original(two_wb_plans):
    """★ 卡 205 命门：冻结输入下，复制体与原件对同一张卡渲染出的派活命令**一致**。

    允许的差异**只有一处**：派活器脚本路径的前缀（复制体从 `harness.toml`
    `paths.workbench` 取目录，原件把 `tools/wb_dispatch.py` 写死）。把这一处各自换成
    占位符之后，两边必须**逐字节相同** —— 不许「大致相等」。
    """
    origin, replica = two_wb_plans
    for tree in ("", ".wt/harnesssy"):
        card = _frozen_card(tree)
        from_origin = origin.render_dispatch(card)
        from_replica = replica.render_dispatch(card)
        assert _dispatcher_token(from_origin) == ORIGINAL_DISPATCHER, from_origin
        assert _dispatcher_token(from_replica).endswith("/wb_dispatch.py"), from_replica
        assert (from_origin.replace(ORIGINAL_DISPATCHER, DISPATCHER_PLACEHOLDER)
                == from_replica.replace(_dispatcher_token(from_replica),
                                        DISPATCHER_PLACEHOLDER)), (
            f"tree={tree!r}（工作台路径前缀换成占位符后仍该逐字节相同）\n"
            f"  原件：{from_origin}\n  复制体：{from_replica}")


def test_card205_replica_never_pushes_and_carries_cwd(two_wb_plans):
    """★ 卡 205 反例：复制体输出**不许出现 `pushd`**；卡树带 `--cwd`、主树不带（与原件同一条）。"""
    origin, replica = two_wb_plans
    for module in (origin, replica):
        main_tree = module.render_dispatch(_frozen_card(""))
        card_tree = module.render_dispatch(_frozen_card(".wt/harnesssy"))
        assert "pushd" not in main_tree, main_tree
        assert "pushd" not in card_tree, card_tree
        assert "--cwd" not in main_tree, main_tree
        assert "--cwd" in card_tree, card_tree


def test_card205_replica_cwd_is_the_card_tree_absolute_path(two_wb_plans):
    """★ 卡 205：`--cwd` 是**该卡树的绝对路径**，且两个模块锚在同一处主树根（卡树里也回主树）。"""
    origin, replica = two_wb_plans
    card = _frozen_card(".wt/harnesssy")
    cwds = []
    for module in (origin, replica):
        argv = module.render_dispatch(card).split()
        cwd = argv[argv.index("--cwd") + 1]
        assert Path(cwd).is_absolute(), cwd
        assert cwd.endswith("/.wt/harnesssy"), cwd
        cwds.append(cwd)
    assert cwds[0] == cwds[1], cwds


def test_card205_harness_copies_do_not_import_tools():
    """★ 卡 205 / README 那句：`harness/` 复制体**不依赖 `tools/`** —— 不许 `import tools`
    或 `from pool import …`（`pool` 是 `tools/pool/` 的包名）。AST 扫，docstring 里的引用不算。

    这一条正是把 README 那句断言**变成机器判据**（否则以后谁给复制体顺手补一句 import，
    只有人读 README 才发现 —— 见 `复盘/问题清单-组2.md` Q-L10-06）。
    """
    files = sorted((ROOT / "harness").glob("*.py"))
    assert files, "没扫到 harness/*.py —— 判据空了"
    offenders: list[str] = []
    for path in files:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(n == "tools" or n.startswith("tools.")
                   or n == "pool" or n.startswith("pool.") for n in names):
                offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, f"复制体不许 import 原件（`tools/` / `pool`）：{offenders}"


# ================================================================ 复制体 vs 原件（卡 214 · T-G326）
#
# 卡 205 只给 `wb_plan.py` 装了牙；另外三份复制体（`wb_state` / `wb_diag` / `wb_status`）
# 与原件的等价仍然没有判据。下面三条把 README 那句「冻结输入下原件/复制体输出逐字节相同」
# 对这三份也变成机器判据。
#
# 冻结输入的定义（三份各自写进对应判据的 docstring）：
#   · wb_status：一段合成的 stream-json `lines`（覆盖 system/assistant/text/tool_use/
#     user/tool_result/result/坏行），喂给两边的 `parse_events`，比 `(timeline, summary)`。
#     不允许任何差异。
#   · wb_diag：一段合成的 stream-json `lines`（含 FAILED/ERROR/三类断言/项目内+外部栈帧/
#     工具调用/result），喂给两边的 `diagnose(lines, root=ROOT)`（传 root 避免 `repo_root()`
#     跑 git），比返回 dict。不允许任何差异。
#   · wb_state：mock `subprocess.run` 返回冻结的 git/锁/进程输出 + `LOCALAPPDATA=""`，
#     喂给两边的 `main()`，比 stdout。允许的差异只有一处：原件有「白名单对账」行
#     （`line_roster`，依赖 `tools/wb_dispatch`+`tools/pool.models`，复制体按 README 约束
#     不 import `tools/` 故不复制），剥掉后逐字相同。

ORIGINAL_WB_STATUS = ROOT / "tools" / "wb_status.py"
REPLICA_WB_STATUS = ROOT / "harness" / "wb_status.py"
ORIGINAL_WB_DIAG = ROOT / "tools" / "wb_diag.py"
REPLICA_WB_DIAG = ROOT / "harness" / "wb_diag.py"
ORIGINAL_WB_STATE = ROOT / "tools" / "wb_state.py"
REPLICA_WB_STATE = ROOT / "harness" / "wb_state.py"


def _import_wb_diag_with_status(name: str, path: Path, dep_dir: Path, wb_status_module):
    """加载 `wb_diag`，把指定的 `wb_status` 注入 `sys.modules` —— 两个 `wb_diag` 各自
    `import wb_status` 要拿到**对应版本**（原件拿原件的，复制体拿复制体的），不能串。

    加载完恢复 `sys.modules["wb_status"]`、摘掉 `dep_dir`、移除 `name`（与卡 205 的
    `_import_as` 同一套清理规矩）。
    """
    saved = sys.modules.get("wb_status")
    sys.modules["wb_status"] = wb_status_module
    sys.path.insert(0, str(dep_dir))
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        if saved is not None:
            sys.modules["wb_status"] = saved
        else:
            sys.modules.pop("wb_status", None)
        sys.modules.pop(name, None)
        sys.path.remove(str(dep_dir))
    return module


@pytest.fixture(scope="module")
def card214_six_modules():
    """（原件/复制体 × status/diag/state）六个模块各自独立加载，供下面三条判据逐字比较。"""
    o_status = _import_as("card214_o_wb_status", ORIGINAL_WB_STATUS, ROOT / "tools")
    r_status = _import_as("card214_r_wb_status", REPLICA_WB_STATUS, ROOT / "harness")
    o_diag = _import_wb_diag_with_status(
        "card214_o_wb_diag", ORIGINAL_WB_DIAG, ROOT / "tools", o_status)
    r_diag = _import_wb_diag_with_status(
        "card214_r_wb_diag", REPLICA_WB_DIAG, ROOT / "harness", r_status)
    o_state = _import_as("card214_o_wb_state", ORIGINAL_WB_STATE, ROOT / "tools")
    r_state = _import_as("card214_r_wb_state", REPLICA_WB_STATE, ROOT / "harness")
    return SimpleNamespace(
        o_status=o_status, r_status=r_status,
        o_diag=o_diag, r_diag=r_diag,
        o_state=o_state, r_state=r_state,
    )


def _frozen_status_lines() -> list[str]:
    """wb_status.parse_events 的冻结输入：覆盖 system init / assistant text / tool_use /
    user tool_result（成功+失败）/ result / 非 JSON 行 / 非对象事件 七种情况。"""
    return [
        json.dumps({"type": "system", "subtype": "init", "model": "claude-x", "tools": ["a", "b"]}),
        json.dumps({"type": "assistant", "message": {"content": "hello"}}),
        json.dumps({"type": "assistant", "message": {"content": [
            {"type": "text", "text": "say"},
            {"type": "tool_use", "name": "Edit", "input": {"file_path": "src/x.py"}},
        ]}}),
        json.dumps({"type": "user", "message": {"content": [
            {"type": "tool_result", "content": "ok"},
            {"type": "tool_result", "is_error": True, "content": "boom"},
        ]}}),
        json.dumps({"type": "result", "subtype": "done", "result": "all good"}),
        "not json",
        json.dumps([1, 2]),
    ]


def _frozen_diag_lines() -> list[str]:
    """wb_diag.diagnose 的冻结输入：覆盖 FAILED/ERROR 行、assert/AssertionError/Error: 三类
    断言、项目内栈帧、外部库栈帧、工具调用、result 事件。"""
    failed_text = "FAILED tests/test_x.py::test_a\nERROR tests/test_y.py::test_b"
    assert_text = "  assert x == 1\n  AssertionError: boom\n  ValueError: bad"
    frame_text = '  File "src/x.py", line 42\n  File "/usr/lib/python3/y.py", line 1'
    return [
        json.dumps({"type": "system", "subtype": "init", "model": "m"}),
        json.dumps({"type": "user", "message": {"content": [
            {"type": "tool_result", "content": failed_text},
        ]}}),
        json.dumps({"type": "user", "message": {"content": [
            {"type": "tool_result", "content": assert_text},
        ]}}),
        json.dumps({"type": "user", "message": {"content": [
            {"type": "tool_result", "content": frame_text},
        ]}}),
        json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
        ]}}),
        json.dumps({"type": "result", "subtype": "done", "result": "ok"}),
    ]


def test_card214_wb_status_replica_parse_events_matches_original(card214_six_modules):
    """★ 卡 214 命门：冻结输入下，`wb_status.parse_events` 两边逐字相同。

    冻结输入 = `_frozen_status_lines()`（合成 stream-json，覆盖七种事件分支）。
    比 `(timeline, summary)` 逐字相等。**不允许任何差异**：`wb_status` 是纯函数，
    复制体内联 `parse_events`，原件委托 `pool.jobs.parse_events`，逻辑该等价。
    装之前它是绿的（量测：两边输出逐字相同）。
    """
    m = card214_six_modules
    lines = _frozen_status_lines()
    o_tl, o_sum = m.o_status.parse_events(lines)
    r_tl, r_sum = m.r_status.parse_events(lines)
    assert o_tl == r_tl, f"timeline 漂:\n  原={o_tl}\n  复={r_tl}"
    assert o_sum == r_sum, f"summary 漂:\n  原={o_sum}\n  复={r_sum}"


def test_card214_wb_diag_replica_diagnose_matches_original(card214_six_modules):
    """★ 卡 214 命门：冻结输入下，`wb_diag.diagnose` 两边逐字相同。

    冻结输入 = `_frozen_diag_lines()`（合成 stream-json，含 FAILED/ERROR/断言/栈帧/工具调用）
    + `root=ROOT`（传 root 避免 `repo_root()` 跑 git，让 diagnose 成纯函数）。
    比返回 dict 逐字相等。**不允许任何差异**：`wb_diag` 的核心是 `wb_status.parse_events`
    + 一组纯函数，前者已由上一条钉住，后者两边逐字同源。
    装之前它是绿的（量测：两边输出逐字相同）。
    """
    m = card214_six_modules
    lines = _frozen_diag_lines()
    o_d = m.o_diag.diagnose(lines, root=ROOT)
    r_d = m.r_diag.diagnose(lines, root=ROOT)
    assert o_d == r_d, f"diagnose 漂:\n  原={o_d}\n  复={r_d}"


def _fake_subprocess_run_214(cmd, *a, **kw):
    """冻结的 subprocess.run：给 wb_state.main() 喂固定的 git/锁/进程输出，让现场板成纯函数。"""
    import subprocess as sp
    cmdstr = " ".join(str(c) for c in cmd)
    if "rev-parse" in cmdstr and "--short" in cmdstr:
        return sp.CompletedProcess(cmd, 0, stdout="abc1234\n", stderr="")
    if "rev-parse" in cmdstr and "--abbrev-ref" in cmdstr:
        return sp.CompletedProcess(cmd, 0, stdout="main\n", stderr="")
    if "status" in cmdstr and "--porcelain" in cmdstr:
        return sp.CompletedProcess(cmd, 0, stdout=" M src/x.py\n?? tmp\n", stderr="")
    if "log" in cmdstr and "--format" in cmdstr:
        return sp.CompletedProcess(cmd, 0, stdout="abc1234 init\n", stderr="")
    if "gate_lock" in cmdstr:
        return sp.CompletedProcess(cmd, 0, stdout="未上锁\n", stderr="")
    if "Win32_Process" in cmdstr or "ps" in cmdstr:
        return sp.CompletedProcess(cmd, 0, stdout="[]", stderr="")
    return sp.CompletedProcess(cmd, 0, stdout="", stderr="")


def _grab_wb_state_main_214(mod, monkeypatch: pytest.MonkeyPatch):
    """跑 `wb_state.main()` 抓 stdout（mock subprocess.run + LOCALAPPDATA）。"""
    import contextlib
    import io
    monkeypatch.setattr("subprocess.run", _fake_subprocess_run_214)
    monkeypatch.setenv("LOCALAPPDATA", "")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        mod.main()
    return buf.getvalue()


def test_card214_wb_state_replica_main_matches_original_modulo_roster(
        card214_six_modules, monkeypatch: pytest.MonkeyPatch):
    """★ 卡 214 命门：冻结输入下，`wb_state.main()` 两边**剥掉白名单对账行后**逐字相同。

    冻结输入 = mock `subprocess.run` 返回固定的 git/锁/进程输出 + `LOCALAPPDATA=""`
    （让 `line_head`/`line_lock`/`lines_procs`/`lines_commits`/`line_trae` 成纯函数）。

    允许的差异**只有一处**：原件输出含一行「白名单对账」（`line_roster`，它惰性 import
    `tools/wb_dispatch` + `tools/pool.models` 算两份名单的并排对账）；复制体按 README
    「不依赖 `tools/`」的约束**不复制这一行**。把含「白名单对账」的那一行从原件输出里
    剥掉后，两边必须**逐字节相同** —— 不许「大致相等」。

    ★ 这条判据防的是**以后**漂：现在复制体与原件在这条允许差异内一致（装之前它是绿的）；
    谁要是把 `line_head`/`line_lock` 等共享行的格式改得两边不一样，这条会红。
    """
    m = card214_six_modules
    o_out = _grab_wb_state_main_214(m.o_state, monkeypatch)
    r_out = _grab_wb_state_main_214(m.r_state, monkeypatch)
    o_stripped = [ln for ln in o_out.splitlines() if "白名单对账" not in ln]
    r_lines = r_out.splitlines()
    assert "白名单对账" not in r_out, f"复制体不该有白名单对账行（不 import tools/）：\n{r_out}"
    assert o_stripped == r_lines, (
        f"剥掉白名单对账行后仍该逐字相同\n"
        f"  原件（剥后）：{o_stripped}\n  复制体：{r_lines}")

