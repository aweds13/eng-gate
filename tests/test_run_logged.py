"""长命令跑法的钉子（卡 E102 · T-AG611）—— 「起不来」不许是一条静默的空日志。

## 为什么有它（用户现场）

带日志跑法是本仓的硬规矩（`AGENTS.md`「长命令怎么跑」）。可这条规矩在 Windows 上
有个洞：`Popen(["npm", "--version"])` 抛 `FileNotFoundError: [WinError 2] 系统找不到
指定的文件。` —— 因为 PATH 里只有 `npm.CMD`，而 CreateProcess 不做 PATHEXT 解析。
后果是日志里只剩一行「起跑」，看上去跟「跑得很慢」一模一样。

## 钉子判什么

1. 裸名必须解析到 PATHEXT 命中的那个文件（不是猜一个 `.exe`）。
2. 批处理（`.cmd` / `.bat`）必须过 cmd，**参数原样**（`a&b`、`a^b`、带空格的一段）。
3. 普通程序走 argv 列表，参数**逐字节**原样（不经 shell ⇒ `%VAR%` 不被展开）。
4. 解析不到 ⇒ `main()` 回 `127`、stdout 点名、**不打印 traceback**，日志里有「找不到的是」。
5. 子进程退出码原样透传。
6. 心跳会打、收尾会回放最后几行、命令自己的 `--` 不被吞。

★ 所有子进程调用都带 `errors="replace"`：Windows 上 `.cmd` 的输出是 GBK，
按 utf-8 硬解会抛 `UnicodeDecodeError`（探针踩过）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from tools import run_logged as rl

WINDOWS_ONLY = pytest.mark.skipif(os.name != "nt", reason="批处理 / PATHEXT 只在 Windows 上有")


def _write_batch(dirpath: Path, name: str) -> Path:
    """造一个把 `%*` 原样回显、并以 3 退出的批处理。"""
    path = dirpath / f"{name}.cmd"
    path.write_bytes(b"@echo off\r\necho GOT:%*\r\nexit /b 3\r\n")
    return path


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def test_quote_for_cmd_only_quotes_what_needs_it() -> None:
    assert rl.quote_for_cmd("plain") == "plain"
    assert rl.quote_for_cmd("a b") == '"a b"'
    assert rl.quote_for_cmd('q"uote') == '"q""uote"'
    assert rl.quote_for_cmd("") == '""'


def test_cmd_line_wraps_the_whole_line_once() -> None:
    line = rl.cmd_line([r"C:\Program Files\x\y.cmd", "a b"])
    assert " /d /s /c " in line, "批处理必须走 cmd 的 /d /s /c"
    assert line.count('"') == 6, f"外层一对 + 两个参数各一对：{line}"
    assert r'"C:\Program Files\x\y.cmd"' in line


def test_unresolvable_name_is_none_not_a_guess() -> None:
    assert rl.resolve_program("definitely-not-installed-xyz") is None
    assert rl.resolve_program("") is None
    with pytest.raises(rl.ProgramNotFoundError):
        rl.prepare_command(["definitely-not-installed-xyz"])


@WINDOWS_ONLY
def test_bare_name_resolves_through_pathext(tmp_path: Path, monkeypatch) -> None:
    """裸名在 PATH 里只以 `.CMD` 存在时也要解析得到（这就是 WinError 2 的洞）。"""
    made = _write_batch(tmp_path, "nailcmd")
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ.get("PATH", ""))
    got = rl.resolve_program("nailcmd")
    assert got is not None, "裸名必须按 PATHEXT 解析到 .cmd"
    assert Path(got).resolve() == made.resolve()
    assert rl.needs_cmd_shell(got)


@WINDOWS_ONLY
def test_batch_gets_a_cmd_line_and_keeps_its_arguments(tmp_path: Path, monkeypatch, capsys) -> None:
    """批处理必须过 cmd；`a&b` 不许被拆成两条命令（拆了就会多一行 GOT 或报错）。"""
    _write_batch(tmp_path, "nailcmd")
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ.get("PATH", ""))
    log = tmp_path / "run.log"
    code = rl.main(["--log", str(log), "--every", "0.05", "--", "nailcmd", "a&b", "a^b", "x y"])
    out = capsys.readouterr().out
    body = _read(log)
    assert code == 3, out + body
    assert "过 cmd（批处理）" in out
    assert body.count("GOT:") == 1, body
    assert "a&b" in body and "a^b" in body and "x y" in body, body


def test_normal_program_passes_argv_verbatim(tmp_path: Path, capsys) -> None:
    """普通程序走 argv 列表：`%VAR%` 不被展开，引号与 `&` 不被解释。"""
    log = tmp_path / "run.log"
    probe = "import sys;[print(repr(a)) for a in sys.argv[1:]]"
    args = ["%PATH%", "a&b", "a^b", 'q"uote', "x y"]
    code = rl.main(["--log", str(log), "--", sys.executable, "-c", probe, *args])
    body = _read(log)
    assert code == 0, body
    assert "直接 exec" in capsys.readouterr().out
    for arg in args:
        assert repr(arg) in body, f"{arg!r} 没有原样到达：{body}"


def test_missing_program_is_loud_and_returns_127(tmp_path: Path, capsys) -> None:
    log = tmp_path / "run.log"
    code = rl.main(["--log", str(log), "--", "definitely-not-installed-xyz", "--flag"])
    out = capsys.readouterr().out
    body = _read(log)
    assert code == rl.EXIT_NOT_FOUND == 127
    assert "definitely-not-installed-xyz" in out
    assert "找不到的是：definitely-not-installed-xyz" in body
    assert "Traceback" not in out, "起不来不是崩溃：不许拿 traceback 糊人"


def test_exit_code_passes_through(tmp_path: Path, capsys) -> None:
    log = tmp_path / "run.log"
    code = rl.main(["--log", str(log), "--", sys.executable, "-c", "raise SystemExit(7)"])
    assert code == 7
    assert "退出码=7" in capsys.readouterr().out


def test_command_keeps_its_own_double_dash(tmp_path: Path) -> None:
    """只剥**开头**那个分隔符：命令自己的 `--` 要留给它。"""
    log = tmp_path / "run.log"
    probe = "import sys;print(repr(sys.argv[1:]))"
    code = rl.main(["--log", str(log), "--", sys.executable, "-c", probe, "--", "x"])
    assert code == 0
    assert "['--', 'x']" in _read(log)


def test_command_works_without_the_separator(tmp_path: Path) -> None:
    """没写 `--` 也不许把命令名当分隔符吃掉（旧实现 `args.cmd[1:]` 就是这么坏的）。"""
    log = tmp_path / "run.log"
    probe = "print('ran')"
    code = rl.main(["--log", str(log), sys.executable, "-c", probe])
    body = _read(log)
    assert code == 0, body
    assert "ran" in body


def test_heartbeat_and_tail_replay(tmp_path: Path, capsys) -> None:
    log = tmp_path / "run.log"
    probe = ("import time\n"
             "for i in range(8):\n"
             "    print(f'line-{i}')\n"
             "    time.sleep(0.1)\n")
    code = rl.main(["--log", str(log), "--every", "0.05", "--tail", "2",
                    "--", sys.executable, "-c", probe])
    out = capsys.readouterr().out
    assert code == 0
    assert "[心跳]" in out, "长命令必须留下心跳，否则作业看起来像卡死"
    assert "[完] 退出码=0" in out
    tail = out.split("[完]")[1]
    assert "line-7" in tail, tail
    assert "line-0" not in tail, "--tail 只回放末尾几行"


def test_no_command_is_a_usage_error(tmp_path: Path, capsys) -> None:
    code = rl.main(["--log", str(tmp_path / "run.log")])
    assert code == 2
    assert "缺命令" in capsys.readouterr().out
