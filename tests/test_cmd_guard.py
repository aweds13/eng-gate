"""命令行写法检查器的钉子：管道截断与 sleep 硬等必须被拦下。"""

from __future__ import annotations

from tools.cmd_guard import check, main


def test_pipe_tail_is_blocked():
    hits = check("python -X utf8 tools/wb_land.py --card A302 2>&1 | tail -3")
    assert hits, "管道截断必须被拦下"


def test_pipe_head_and_cut_are_blocked():
    assert check("cat gates/diag/long.log | head -5")
    assert check("git log --oneline | cut -d' ' -f1")


def test_sleep_polling_is_blocked():
    assert check("sleep 120 && git log --oneline -1")


def test_logged_landing_is_allowed():
    cmd = (
        "python -X utf8 tools/run_logged.py --log gates/diag/land-A302.log -- "
        "python -X utf8 tools/wb_land.py --card A302"
    )
    assert check(cmd) == []


def test_main_returns_one_on_violation(capsys):
    code = main(["--cmd", "python tools/wb_land.py --card A9 | tail -2"])
    out = capsys.readouterr().out
    assert code == 1
    assert "被禁止" in out
    assert "run_logged" in out


def test_main_returns_zero_on_clean_command(capsys):
    code = main(["--cmd", "python -X utf8 -m pytest tests/test_cmd_guard.py -q"])
    assert code == 0
    assert "写法可以" in capsys.readouterr().out
