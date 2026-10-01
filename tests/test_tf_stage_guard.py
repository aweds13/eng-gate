"""白名单越界校验（`tools/tf_stage_guard.py`，卡 095 · 机器替代②）的测试。

判据：全在白名单 → 退 0；混进白名单外的 → 退 **2** 并点名；★ **空暂存区 → 退 3**
（空集永远满足「全在白名单」，那是假绿灯，不许当通过）。

这里用**假的暂存区**（monkeypatch `staged_paths`）—— 不需要真提交、也不碰真 git 索引。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import tf_stage_guard as tsg  # noqa: E402 —— 需要先挂 tools/


def _staged(*paths: str):
    """把 `staged_paths` 换成一份假输出（忽略 root 参数）。"""
    return lambda root=None: list(paths)


def test_all_in_allow_exits_0(monkeypatch, capsys) -> None:
    """全在白名单 → 退 0，并报出 staged 了几个文件。"""
    monkeypatch.setattr(tsg, "staged_paths", _staged("tools/a.py", "docs/b.md"))
    rc = tsg.main(["--allow", "tools/a.py", "docs/b.md"])
    assert rc == 0
    assert "staged 2 个文件全在白名单" in capsys.readouterr().out


def test_outside_exits_2_and_names(monkeypatch, capsys) -> None:
    """★ 反例：混进一个白名单外的路径 → 退 2，且**点名**到那个文件。"""
    monkeypatch.setattr(tsg, "staged_paths",
                        _staged("tools/a.py", "src/悄悄改的.py"))
    rc = tsg.main(["--allow", "tools/a.py"])
    assert rc == 2
    out = capsys.readouterr().out
    assert "1 个路径不在白名单" in out
    assert "src/悄悄改的.py" in out          # 点名到那个越界文件


def test_empty_stage_exits_3(monkeypatch, capsys) -> None:
    """★ 反例：暂存区为空 → 退 3（空集不算通过，那是假绿灯）。"""
    monkeypatch.setattr(tsg, "staged_paths", _staged())
    rc = tsg.main(["--allow", "tools/a.py"])
    assert rc == 3
    assert "暂存区为空" in capsys.readouterr().out


def test_allow_file_is_loaded(monkeypatch, tmp_path: Path, capsys) -> None:
    """`--allow-file`：每行一个路径的清单；`#` 注释与空行跳过。"""
    listing = tmp_path / "allow.txt"
    listing.write_text("# 本卡白名单\ntools/a.py\n\ndocs/b.md\n", encoding="utf-8")
    monkeypatch.setattr(tsg, "staged_paths", _staged("tools/a.py", "docs/b.md"))
    assert tsg.main(["--allow-file", str(listing)]) == 0


def test_allow_file_missing_exits_2(capsys) -> None:
    """清单文件不存在 → 退 2 并说清（不静默当通过）。"""
    assert tsg.main(["--allow-file", "没有这个清单.txt"]) == 2
    assert "不存在" in capsys.readouterr().err


def test_glob_allow(monkeypatch, capsys) -> None:
    """白名单支持 glob（fnmatch）：`tools/*.py` 放行 tools 下任意 py。"""
    monkeypatch.setattr(tsg, "staged_paths", _staged("tools/tf_portcheck.py"))
    assert tsg.main(["--allow", "tools/*.py"]) == 0
    monkeypatch.setattr(tsg, "staged_paths", _staged("tools/sub/x.py"))
    assert tsg.main(["--allow", "tools/*.py"]) == 0   # `*` 跨 `/`，与 fnmatch 口径一致


def test_non_ascii_path_matches_raw(monkeypatch, capsys) -> None:
    """★ 中文路径按**原样**比：白名单里的 `复盘/卡.md` 必须匹配得上。"""
    monkeypatch.setattr(tsg, "staged_paths", _staged("复盘/卡-095.md"))
    assert tsg.main(["--allow", "复盘/卡-095.md"]) == 0


def test_staged_paths_disables_quotepath(monkeypatch) -> None:
    """★ 钉住 `core.quotepath=false`：否则 git 会把中文路径八进制转义（跟白名单永远不匹配）。"""
    seen: dict = {}

    def fake_run(cmd, **kwargs):                       # noqa: ANN001, ANN202
        seen["cmd"] = list(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="复盘/卡.md\n", stderr="")

    monkeypatch.setattr(tsg.subprocess, "run", fake_run)
    paths = tsg.staged_paths(Path("."))
    assert "core.quotepath=false" in seen["cmd"]
    assert paths == ["复盘/卡.md"]                       # 原样，不是 `\345\244\215...`


def test_staged_paths_raises_on_git_failure(monkeypatch) -> None:
    """git 失败不静默吞掉 —— 抛错让调用方退非 0（宁可停，也不假装"全在白名单"）。"""
    def fake_run(cmd, **kwargs):                       # noqa: ANN001, ANN202
        return subprocess.CompletedProcess(cmd, 128, stdout="", stderr="fatal: bad")

    monkeypatch.setattr(tsg.subprocess, "run", fake_run)
    try:
        tsg.staged_paths(Path("."))
    except RuntimeError as exc:
        assert "fatal" in str(exc)
    else:                                              # pragma: no cover
        raise AssertionError("git 失败时应当抛 RuntimeError")
