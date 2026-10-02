r"""项目索引的钉子（`tools/pool/projects.py` + `tools/wb_project.py`，卡 120 · T-G232）。

为什么值当测：号池 / 派活 / MCP 是**通用层**，记忆与规矩是**项目层**。把"哪个项目、根在哪、
允许派到哪些树"机器化，才能让"同一个窗口跑不同项目"从**自觉**变成**可查**。索引自己也会漂，
所以三条硬判据（根存在 / 两根不同 / 前缀非空）要**先红后绿**地钉住。

| 判据 | 钉什么 |
|---|---|
| ① 索引自检 | 缺根 / 根不存在 / 两根同 / 前缀空 ⇒ 报错**并点名**；`TF_PROJECTS_TOML` 覆盖 |
| ② 反查 | `find_by_tree`：前缀命中 / 主树归属 / 反查不到 = `None`（不猜） |
| ③ 记忆入口 | `memory` 照索引**逐字**打印；`use/show/memory` 的三条退码 |

★ `project_guard` 的三种咬法（别的项目的树 / 未登记项目 / 反查不到 / 「码道」反例）钉在
  `tests/test_pool_guards.py`（守卫就该跟它同住）。
★ 一律用 `TF_PROJECTS_TOML` / `TF_CURRENT_PROJECT` 指临时文件 —— 不碰 `infra/` 与真 `gates/diag/`。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import wb_project  # noqa: E402 —— tools/ 已在 sys.path 上
from pool import projects, registry  # noqa: E402

#: 真索引里 engineering 的那三份记忆入口（与 `infra/pool/projects.toml` 逐字一致）。
ENGINEERING_MEMORY = ("复盘/新窗口交接卡.md", "复盘/交接-重构进度.md", "复盘/口径坑.md")


def _write_index(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "projects.toml"
    path.write_text(body, encoding="utf-8")
    return path


@pytest.fixture()
def two_projects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """两个**根不同**的项目：engineering（`.wt/`）与 other（`cards/`）—— 供"别的项目的树"测试。"""
    eng = tmp_path / "eng"
    other = tmp_path / "other"
    eng.mkdir()
    other.mkdir()
    path = _write_index(tmp_path, (
        "[project.engineering]\n"
        f'root = "{eng.as_posix()}"\n'
        'memory = ["a.md", "b.md"]\n'
        'tree_prefixes = [".wt/"]\n'
        "\n[project.other]\n"
        f'root = "{other.as_posix()}"\n'
        'memory = ["o.md"]\n'
        'tree_prefixes = ["cards/"]\n'))
    monkeypatch.setenv("TF_PROJECTS_TOML", str(path))
    return path


# ================================================================ ① 索引自检


def test_index_path_honors_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "x.toml"
    monkeypatch.setenv("TF_PROJECTS_TOML", str(path))
    assert projects.index_path() == path


def test_default_index_is_found_by_walking_up(monkeypatch: pytest.MonkeyPatch) -> None:
    """★ 号池不在本仓 ⇒ 从本树逐级向上找 `infra/pool/projects.toml`（真索引在）。"""
    monkeypatch.delenv("TF_PROJECTS_TOML", raising=False)
    got = projects.index_path()
    assert got.name == "projects.toml" and got.is_file()
    assert "infra/pool/projects.toml" in got.as_posix()


def test_missing_index_is_an_error_not_a_guess(tmp_path: Path,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TF_PROJECTS_TOML", str(tmp_path / "没有这份.toml"))
    with pytest.raises(projects.ProjectsError):
        projects.load()


def test_missing_root_is_refused_and_named(tmp_path: Path,
                                           monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TF_PROJECTS_TOML", str(_write_index(tmp_path, (
        "[project.broken]\nmemory = []\ntree_prefixes = [\".wt/\"]\n"))))
    with pytest.raises(projects.ProjectsError) as exc:
        projects.load()
    assert "broken" in str(exc.value) and "root" in str(exc.value)


def test_nonexistent_root_is_refused_and_named(tmp_path: Path,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TF_PROJECTS_TOML", str(_write_index(tmp_path, (
        "[project.ghost]\n"
        f'root = "{(tmp_path / "没有这个目录").as_posix()}"\n'
        'tree_prefixes = [".wt/"]\n'))))
    with pytest.raises(projects.ProjectsError) as exc:
        projects.load()
    assert "ghost" in str(exc.value) and "不存在" in str(exc.value)


def test_two_projects_sharing_a_root_is_refused_names_both(tmp_path: Path,
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    same = tmp_path / "same"
    same.mkdir()
    monkeypatch.setenv("TF_PROJECTS_TOML", str(_write_index(tmp_path, (
        "[project.aaa]\n"
        f'root = "{same.as_posix()}"\n'
        'tree_prefixes = [".wt/"]\n'
        "\n[project.bbb]\n"
        f'root = "{same.as_posix()}"\n'
        'tree_prefixes = [".wt/"]\n'))))
    with pytest.raises(projects.ProjectsError) as exc:
        projects.load()
    assert "aaa" in str(exc.value) and "bbb" in str(exc.value) and "同一个 root" in str(exc.value)


def test_empty_tree_prefixes_is_refused_and_named(tmp_path: Path,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "p"
    root.mkdir()
    monkeypatch.setenv("TF_PROJECTS_TOML", str(_write_index(tmp_path, (
        "[project.noprefix]\n"
        f'root = "{root.as_posix()}"\n'
        'tree_prefixes = []\n'))))
    with pytest.raises(projects.ProjectsError) as exc:
        projects.load()
    assert "noprefix" in str(exc.value) and "tree_prefixes" in str(exc.value)


# ================================================================ ② 反查 / 前缀


def test_under_prefix_respects_the_slash_boundary() -> None:
    assert projects.under_prefix(".wt/x", [".wt/"]) is True
    assert projects.under_prefix(".wt", [".wt/"]) is True
    assert projects.under_prefix(".wtother/x", [".wt/"]) is False    # 不误吞同名前缀
    assert projects.under_prefix("docs/x", [".wt/"]) is False
    assert projects.under_prefix("anything", []) is False            # 空前缀 = 不命中


def test_find_by_tree_by_prefix(two_projects: Path) -> None:
    assert projects.find_by_tree(".wt/card") == "engineering"
    assert projects.find_by_tree("cards/x") == "other"
    assert projects.find_by_tree("somewhere/else") is None           # 反查不到 = None（不猜）


def test_get_and_find_do_not_invent(two_projects: Path) -> None:
    assert projects.get("engineering")["memory"] == ["a.md", "b.md"]
    assert projects.get("没有这个") is None


# ================================================================ ⑤ 记忆入口 / wb_project


def test_memory_entries_of_engineering_matches_the_index_verbatim(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """★ `memory_entries('engineering')` 与索引**逐字一致**（照抄，不发现 / 不推断）。"""
    monkeypatch.delenv("TF_PROJECTS_TOML", raising=False)
    assert tuple(projects.memory_entries("engineering")) == ENGINEERING_MEMORY


def test_memory_entries_unknown_project_raises(two_projects: Path) -> None:
    with pytest.raises(projects.ProjectsError):
        projects.memory_entries("没有这个")


def test_wb_project_use_show_memory_round_trip(two_projects: Path, tmp_path: Path,
                                               monkeypatch: pytest.MonkeyPatch,
                                               capsys: pytest.CaptureFixture) -> None:
    current = tmp_path / "current-project.json"
    monkeypatch.setenv("TF_CURRENT_PROJECT", str(current))
    monkeypatch.setenv("TF_WINDOW_ID", "win-120")

    assert wb_project.main(["use", "engineering"]) == 0
    data = json.loads(current.read_text(encoding="utf-8"))
    assert data["project"] == "engineering" and data["window"] == "win-120"

    capsys.readouterr()
    assert wb_project.main(["show"]) == 0
    assert "engineering" in capsys.readouterr().out

    capsys.readouterr()
    assert wb_project.main(["memory"]) == 0
    out = capsys.readouterr().out
    assert "a.md" in out and "b.md" in out and "o.md" not in out    # 只读当前项目


def test_wb_project_memory_explicit_project_is_verbatim(two_projects: Path,
                                                        tmp_path: Path,
                                                        monkeypatch: pytest.MonkeyPatch,
                                                        capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setenv("TF_CURRENT_PROJECT", str(tmp_path / "none.json"))
    assert wb_project.main(["memory", "other"]) == 0
    assert "o.md" in capsys.readouterr().out


def test_wb_project_show_without_selection_is_nonzero(tmp_path: Path,
                                                      monkeypatch: pytest.MonkeyPatch,
                                                      capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setenv("TF_CURRENT_PROJECT", str(tmp_path / "none.json"))
    assert wb_project.main(["show"]) != 0
    assert "还没选当前项目" in capsys.readouterr().err


def test_wb_project_use_unregistered_is_refused(two_projects: Path, tmp_path: Path,
                                                monkeypatch: pytest.MonkeyPatch,
                                                capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setenv("TF_CURRENT_PROJECT", str(tmp_path / "current.json"))
    assert wb_project.main(["use", "码道"]) != 0
    assert "没登记过的项目" in capsys.readouterr().err


def test_wb_project_memory_without_current_is_nonzero(tmp_path: Path,
                                                      monkeypatch: pytest.MonkeyPatch,
                                                      capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setenv("TF_CURRENT_PROJECT", str(tmp_path / "none.json"))
    assert wb_project.main(["memory"]) != 0


def test_registry_error_still_maps_to_exit_2(two_projects: Path, tmp_path: Path,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    """兜底：算不出主树（且没给 TF_CURRENT_PROJECT）时 `use` 干净退 2，不崩。"""
    monkeypatch.delenv("TF_CURRENT_PROJECT", raising=False)
    monkeypatch.setattr(registry, "main_tree_root",
                        lambda: (_ for _ in ()).throw(registry.RegistryError("算不出主树")))
    assert wb_project.main(["use", "engineering"]) == 2
