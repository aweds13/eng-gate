"""`tools/tf_group.py` 的三态与「只读」不变量（卡 096 / 台账号 `T-G191`）。

钉的是**会咬人的那几条**：

1. `report` 现算分布正确、并列出与现有 group 的**不一致清单**；
2. `propose --only PROCESS` 逐条给出「建议 group + 命中规则 + 理由」，判不了的标「判不了」；
3. ★ `check`：**不一致退 1** / **一致退 0**；`PROCESS` 且判不了不算冲突；非五桶（规格号）跳过；
4. ★ **只读**：三个子命令跑完前后，**假台账字节一个都不变**（防「只读」变「会写」）。

全程在 `tmp_path` 的假台账上做，绝不动真仓库的 `docs/traceability.toml`。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "tf_group.py"

# 假台账：四条各命中一条规则 + 一条判不了（PROCESS）+ 一条已一致 + 一条规格号（应跳过）
FAKE_LEDGER = """\
[entries."T-FAKE-A"]
id = "T-FAKE-A"
title = "派活器与号池：工人并发调度"
group = "PROCESS"

[entries."T-FAKE-B"]
id = "T-FAKE-B"
title = "门禁复用与封存指纹"
group = "PROCESS"

[entries."T-FAKE-C"]
id = "T-FAKE-C"
title = "端口锁清理与磁盘日志"
group = "PROCESS"

[entries."T-FAKE-D"]
id = "T-FAKE-D"
title = "铁律与口径模板"
group = "PROCESS"

[entries."T-FAKE-E"]
id = "T-FAKE-E"
title = "My Day 拖拽排序"
group = "PROCESS"

[entries."T-FAKE-F"]
id = "T-FAKE-F"
title = "门禁门与回归断言"
group = "ENGINEERING"

[entries."T-FAKE-G"]
id = "T-FAKE-G"
title = "规格条目：My Day 视图"
group = "F1"
"""

# 已一致：每条现在 group 就等于建议（或判不了留 PROCESS）；不含任何冲突。
CONSISTENT_LEDGER = """\
[entries."T-OK-A"]
id = "T-OK-A"
title = "派活器与号池"
group = "OUTSOURCE"

[entries."T-OK-B"]
id = "T-OK-B"
title = "门禁复用"
group = "ENGINEERING"

[entries."T-OK-C"]
id = "T-OK-C"
title = "My Day 视图"
group = "PROCESS"
"""


def write_ledger(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "fake_traceability.toml"
    p.write_text(text, encoding="utf-8")
    return p


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(TOOL), *args],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def test_report_distribution_and_conflict_list(tmp_path: Path) -> None:
    ledger = write_ledger(tmp_path, FAKE_LEDGER)
    done = run("report", "--ledger", str(ledger))
    assert done.returncode == 0, done.stderr
    out = done.stdout
    # 现算分布：OUTSOURCE 1 / ENGINEERING 2 / OPS 1 / RULES 1 / PROCESS 2（E 判不了 + G 规格号）
    assert "OUTSOURCE    1" in out
    assert "ENGINEERING  2" in out
    assert "OPS          1" in out
    assert "RULES        1" in out
    assert "PROCESS      2" in out
    # 不一致 4 条（A/B/C/D；E 判不了不算、F 一致不算、G 非五桶跳过）
    assert "不一致清单（4 条）" in out
    for eid in ("T-FAKE-A", "T-FAKE-B", "T-FAKE-C", "T-FAKE-D"):
        assert eid in out
    assert "T-FAKE-E" not in out  # 判不了，不报
    assert "T-FAKE-F" not in out  # 已一致，不报
    assert "T-FAKE-G" not in out  # 非五桶，跳过
    # 逐条能对：点名「现在 / 建议 / 命中规则」
    assert 'T-FAKE-B · 现在=PROCESS · 建议=ENGINEERING · 命中规则="门禁/测试/构建/复用"' in out


def test_propose_only_process_gives_rule_and_reason(tmp_path: Path) -> None:
    ledger = write_ledger(tmp_path, FAKE_LEDGER)
    done = run("propose", "--only", "PROCESS", "--ledger", str(ledger))
    assert done.returncode == 0, done.stderr
    lines = [ln for ln in done.stdout.splitlines() if ln.startswith("T-FAKE-")]
    # 只列现在=PROCESS 的五条（A-E），不含 F（ENGINEERING）/ G（F1）
    assert {ln.split(" · ")[0] for ln in lines} == {
        "T-FAKE-A", "T-FAKE-B", "T-FAKE-C", "T-FAKE-D", "T-FAKE-E",
    }
    # ★ 每条都带「命中规则」与「理由」（判不了的那条规则写 (无)、理由写 判不了）
    for ln in lines:
        assert "命中规则=" in ln and "理由=" in ln
    assert 'T-FAKE-A · 现在=PROCESS · 建议=OUTSOURCE · 命中规则="外包/派活/号池"' in done.stdout
    assert 'T-FAKE-E · 现在=PROCESS · 建议=PROCESS · 命中规则=(无) · 理由=判不了' in done.stdout
    assert "共 5 条" in done.stdout


def test_check_returns_1_when_inconsistent(tmp_path: Path) -> None:
    ledger = write_ledger(tmp_path, FAKE_LEDGER)
    done = run("check", "--ledger", str(ledger))
    assert done.returncode == 1
    assert "FAIL" in done.stdout and "4 条" in done.stdout


def test_check_returns_0_when_consistent(tmp_path: Path) -> None:
    ledger = write_ledger(tmp_path, CONSISTENT_LEDGER)
    done = run("check", "--ledger", str(ledger))
    assert done.returncode == 0, done.stdout
    assert done.stdout.startswith("OK")


def test_ledger_bytes_unchanged_by_all_readonly_commands(tmp_path: Path) -> None:
    """★ 跑完三个子命令，假台账**字节一个都不变**（防「只读」变「会写」）。"""
    ledger = write_ledger(tmp_path, FAKE_LEDGER)
    before = ledger.read_bytes()
    for argv in (("report",), ("propose", "--only", "PROCESS"), ("check",)):
        done = run(*argv, "--ledger", str(ledger))
        assert done.returncode in (0, 1), done.stderr
    assert ledger.read_bytes() == before
    # 目录里也没多出别的文件（工具没顺手落盘任何东西）
    assert [p.name for p in tmp_path.iterdir()] == ["fake_traceability.toml"]


def test_missing_ledger_is_clear_error(tmp_path: Path) -> None:
    done = run("report", "--ledger", str(tmp_path / "nope.toml"))
    assert done.returncode == 2
    assert "台账不存在" in done.stderr


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
