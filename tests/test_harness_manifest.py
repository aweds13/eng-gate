"""harness/manifest.py 的硬口径测试（卡 088 · T-G183）。

判据就是卡 §1.2 那句：项目专有值只进仓根 harness.toml；写错（缺文件/坏 TOML/缺段/缺键/
未知键/未知段/空值/非字符串/路径不存在）必须**指名道姓报错**，不许静默默认值。
"""

from __future__ import annotations

import ast
import importlib.util
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

