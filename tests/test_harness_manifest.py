"""harness/manifest.py 的硬口径测试（卡 088 · T-G183）。

判据就是卡 §1.2 那句：项目专有值只进仓根 harness.toml；写错（缺文件/坏 TOML/缺段/缺键/
未知键/未知段/空值/非字符串/路径不存在）必须**指名道姓报错**，不许静默默认值。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

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
