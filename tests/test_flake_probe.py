"""卡 E72 · T-AG561 —— 隔离复核探针的钉子。

这一层的判据只有一句话：**红门红了之后，「隔离跑绿」这个读数必须能取到，并且绝不会
被当成绿。** 钉子按三条线摆：

* 命令形状（判据 1 + 判据 6）：单 nodeid、串行、单进程、**不带** xdist 参数；模块里
  不许出现门名判断、不许读 `gates/last.json`、不许写任何文件。
* 三态判定（判据 1 + 判据 3）：真红 ⇒ `reproduced`；单跑绿 ⇒ `isolated_green`；
  超时 / 起不来 / 空清单 ⇒ `error`，**error 不许退化成绿**。
* 计数口径（§不许做）：`repeat > 1` 只数「几次里有几次红」，不是跑到绿为止。

`-k reverse` 选中的那几条是真起 pytest 子进程的（合成用例：一条必红、一条必绿），
因为只有真子进程才能证明「退出码 → 判定」这条链没被写反。
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
#: `scripts/` 没有 `__init__.py`，也不是包；这里**不**用「先插 sys.path 再 import」那种
#: 需要压制 E402 的写法（本卡 §不许做 明令不许用压制注释），改成按路径加载 ——
#: 与 `scripts/run_gates.py` 自己加载 `tools/pytest_select.py` 是同一体例。
_SPEC = importlib.util.spec_from_file_location(
    "flake_probe_for_tests", ROOT / "scripts" / "flake_probe.py"
)
assert _SPEC is not None and _SPEC.loader is not None, "找不到 scripts/flake_probe.py"
fp = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = fp
_SPEC.loader.exec_module(fp)

SYNTH = """\
import time


def test_green():
    assert True


def test_red():
    assert 0, "这条必定红 —— 反向验证的锚"


def test_sleep():
    time.sleep(30)
    assert True
"""

#: 门名清单：flake_probe.py **不认识**任何门（判据 6）。`pytest` 本身不在此列 —— 它是
#: 被调用的框架，不是「按门名分叉」。
DOOR_NAMES = (
    "acceptance",
    "pytest_chain",
    "web_live",
    "ruff",
    "mypy",
    "audit_titles",
    "skills_claims",
    "invariants",
    "contrast",
    "ui_text",
    "ui_dom_probe",
    "check_layers",
)


def _synth(tmp_path: Path) -> Path:
    """落一份合成用例文件（在 tmp_path 里，`root` 就是它）。"""
    path = tmp_path / "test_synth_flake.py"
    path.write_text(SYNTH, encoding="utf-8")
    return path


def _src() -> str:
    return (ROOT / "scripts" / "flake_probe.py").read_text(encoding="utf-8")


def _load_run_gates():
    """按路径加载 `scripts/run_gates.py`（同样为了不写那条压制 E402 的注释）。"""
    name = "run_gates_for_flake_tests"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "run_gates.py")
    assert spec is not None and spec.loader is not None, "找不到 scripts/run_gates.py"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- 命令形状


def test_probe_cmd_is_one_serial_single_nodeid_pytest_run() -> None:
    """判据 1：命令逐字固定 —— 单 nodeid、串行、单进程。"""
    nodeid = "tests/test_x.py::test_y"
    got = fp.probe_cmd(nodeid)
    assert got == [
        sys.executable,
        "-X",
        "utf8",
        "-m",
        "pytest",
        nodeid,
        "-q",
        "-o",
        "addopts=",
        "--no-cov",
    ]
    assert got.count(nodeid) == 1


def test_probe_cmd_carries_no_xdist_switch_at_all() -> None:
    """判据 1：不许挂 xdist —— 任何并行开关都会把「隔离」变成「换一种并发跑法」。"""
    got = fp.probe_cmd("tests/test_x.py::test_y")
    joined = " ".join(got)
    for banned in ("-n", "--numprocesses", "--dist", "-d", "xdist", "--tx"):
        assert banned not in got, f"probe 命令行里出现了并行开关 {banned!r}：{joined}"
    assert "-p" not in got  # -p pluggy 通道同样能把 xdist 塞回来


def test_probe_cmd_clears_configured_addopts_and_coverage() -> None:
    """清掉配置里的 addopts（含 --cov-fail-under）—— 隔离跑的判定不许被覆盖率门槛污染。"""
    got = fp.probe_cmd("tests/test_x.py::test_y")
    assert "-o" in got and "addopts=" in got
    assert "--no-cov" in got


# ---------------------------------------------------------------- 三态判定（真跑）


def test_reverse_real_red_case_is_judged_reproduced(tmp_path: Path) -> None:
    """反向验证锚：必定失败的合成用例 ⇒ `reproduced`（真红不许被当成绿）。"""
    _synth(tmp_path)
    got = fp.probe(["test_synth_flake.py::test_red"], root=tmp_path, timeout_s=300)
    assert got["verdict"] == fp.REPRODUCED, got
    assert got["nodeid"] == "test_synth_flake.py::test_red"
    assert isinstance(got["seconds"], float) and got["seconds"] >= 0
    assert "test_red" in str(got["tail"])


def test_reverse_real_green_case_is_judged_isolated_green(tmp_path: Path) -> None:
    """反向验证锚：单跑绿的用例 ⇒ `isolated_green`（这才是「假红」的那个读数）。"""
    _synth(tmp_path)
    got = fp.probe(["test_synth_flake.py::test_green"], root=tmp_path, timeout_s=300)
    assert got["verdict"] == fp.ISOLATED_GREEN, got
    assert "1 passed" in str(got["tail"])


def test_reverse_missing_root_is_error_never_green(tmp_path: Path) -> None:
    """起不来（cwd 不存在）⇒ `error`。半个字都不许说成绿。"""
    gone = tmp_path / "not-here"
    got = fp.probe(["test_synth_flake.py::test_green"], root=gone, timeout_s=30)
    assert got["verdict"] == fp.ERROR, got
    assert "起不来" in str(got["tail"])


def test_reverse_timeout_is_error_never_green(tmp_path: Path) -> None:
    """超时 ⇒ `error`（不许当绿；也不许当红 —— 判不出就是判不出）。"""
    _synth(tmp_path)
    got = fp.probe(["test_synth_flake.py::test_sleep"], root=tmp_path, timeout_s=1.5)
    assert got["verdict"] == fp.ERROR, got
    assert "超时" in str(got["tail"])


def test_empty_nodeid_list_is_a_loud_error() -> None:
    """空清单不许静默返回绿 —— 那正好是「没看就说过」的形状。"""
    with pytest.raises(ValueError):
        fp.probe([], root=ROOT)
    with pytest.raises(ValueError):
        fp.probe(["  ", ""], root=ROOT)


# ---------------------------------------------------------------- 计数口径


def test_repeat_counts_reds_instead_of_looping_until_green(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`repeat` 只是「数几次红」，不是「跑到绿为止」。"""
    script = [fp.REPRODUCED, fp.ISOLATED_GREEN, fp.REPRODUCED]
    seen: list[float] = []

    def fake_run_once(nodeid: str, root: Path, timeout_s: float) -> dict[str, object]:
        seen.append(timeout_s)
        verdict = script[len(seen) - 1]
        return {"verdict": verdict, "seconds": 0.0, "tail": f"第{len(seen)}次：{verdict}"}

    monkeypatch.setattr(fp, "_run_once", fake_run_once)
    got = fp.probe(["t.py::a"], root=tmp_path, repeat=3, timeout_s=7)
    assert len(seen) == 3, "repeat=3 就必须真跑 3 次，不许提前收工"
    assert seen == [7, 7, 7], "timeout_s 要逐次透传"
    assert got["verdict"] == fp.REPRODUCED
    assert got["tail"].startswith("[2/3 次红]")


def test_repeat_all_green_reports_zero_reds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """3 次全绿 ⇒ 前缀写明 0/3，判定仍是 `isolated_green`。"""

    def fake_run_once(nodeid: str, root: Path, timeout_s: float) -> dict[str, object]:
        return {"verdict": fp.ISOLATED_GREEN, "seconds": 0.0, "tail": "1 passed"}

    monkeypatch.setattr(fp, "_run_once", fake_run_once)
    got = fp.probe(["t.py::a"], root=tmp_path, repeat=3)
    assert got["verdict"] == fp.ISOLATED_GREEN
    assert got["tail"].startswith("[0/3 次红]")


def test_repeat_one_run_carries_no_counter_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """默认 repeat=1 时尾部就是原始输出，不许加计数前缀。"""

    def fake_run_once(nodeid: str, root: Path, timeout_s: float) -> dict[str, object]:
        return {"verdict": fp.REPRODUCED, "seconds": 0.0, "tail": "1 failed"}

    monkeypatch.setattr(fp, "_run_once", fake_run_once)
    got = fp.probe(["t.py::a"], root=tmp_path)
    assert got["tail"] == "1 failed"


def test_tail_respects_the_size_budget() -> None:
    """尾部口径与 `gate_detail()` 同量级：≤20 行、≤2000 字。"""
    blob = "\n".join(f"line {i} " + "x" * 200 for i in range(400))
    got = fp._tail(blob)
    assert len(got.splitlines()) <= fp.TAIL_LINES
    assert len(got) <= fp.TAIL_MAX_CHARS
    assert got.rstrip().endswith("x" * 10)


# ---------------------------------------------------------------- 判据 6：只读、不识门


def test_probe_source_never_branches_on_a_door_name() -> None:
    """判据 6：flake_probe.py 里不许出现门名判断。"""
    src = _src()
    for door in DOOR_NAMES:
        assert door not in src, f"flake_probe.py 里出现了门名 {door!r} —— 判据 6 不许"
    assert not re.search(r"""name\s*==\s*["'][a-z_]+["']""", src)


def test_probe_source_never_reads_the_gate_ledger() -> None:
    """判据 6：不许读门禁台账（判定只来自退出码）。"""
    src = _src()
    assert "last.json" not in src
    assert "gates/" not in src
    assert not re.search(r"^\s*(?:from|import)\s+gates\b", src, re.M)


def test_probe_source_writes_no_file_at_all() -> None:
    """§不许做：flake_probe 唯一输出是返回值 —— 源码里不许有落盘动作。"""
    src = _src()
    for verb in ("write_text", "write_bytes", ".mkdir(", "open(", "shutil.copy"):
        assert verb not in src, f"flake_probe.py 里出现了落盘动作 {verb!r}"


def test_probe_leaves_the_tree_untouched(tmp_path: Path) -> None:
    """真跑一趟，跑完之后目录里只多出 pytest 自己的缓存，没有探针产物。"""
    _synth(tmp_path)
    before = sorted(p.name for p in tmp_path.iterdir())
    fp.probe(["test_synth_flake.py::test_green"], root=tmp_path, timeout_s=300)
    after = sorted(p.name for p in tmp_path.iterdir())
    assert set(after) - set(before) <= {".pytest_cache", "__pycache__"}, after


def test_child_env_drops_pytest_addopts_and_puts_the_tree_src_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`PYTEST_ADDOPTS` 是外部塞并行参数的唯一通道 —— 必须摘掉；本树 `src/` 必须首位。"""
    monkeypatch.setenv("PYTEST_ADDOPTS", "-n 2 --maxfail=1")
    monkeypatch.setenv("PYTHONPATH", "somewhere-else")
    got = fp.child_env(tmp_path)
    assert "PYTEST_ADDOPTS" not in got
    assert got["PYTHONUTF8"] == "1"
    assert got["PYTHONIOENCODING"] == "utf-8"
    first = got["PYTHONPATH"].split(";")[0]
    assert Path(first) == (tmp_path / "src").resolve()


def test_caller_pytest_addopts_cannot_make_the_probe_parallel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """带着 `-n 2` 的环境变量进来，隔离跑仍然给出正常判定（参数没被偷渡进去）。"""
    _synth(tmp_path)
    monkeypatch.setenv("PYTEST_ADDOPTS", "-n 2")
    got = fp.probe(["test_synth_flake.py::test_green"], root=tmp_path, timeout_s=300)
    assert got["verdict"] == fp.ISOLATED_GREEN, got

# ---------------------------------------------------------------- run_gates 接线（判据 2/3/4）

FAKE_RED = "import sys\nprint('FAILED tests/test_fake.py::test_boom')\nsys.exit(1)\n"
FAKE_GREEN = "import sys\nprint('all good')\nsys.exit(0)\n"

#: 判据 4 要求关着时 detail 里必须出现的半句（不许静默省略）。
OFF_NOTE = "本次未做隔离复核"


class _StubProbe:
    """替身探针：只回一个判定，不起子进程（真子进程那条链由 `-k reverse` 那四条守）。"""

    def __init__(self, verdict: str, tail: str = "stub") -> None:
        self.verdict = verdict
        self.tail = tail

    def probe(self, nodeids, *, root, repeat=1, timeout_s=600.0):
        assert repeat == 1 and nodeids, (repeat, nodeids)
        return {"nodeid": nodeids[0], "verdict": self.verdict, "seconds": 0.0, "tail": self.tail}


@pytest.fixture()
def rg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """拿 run_gates，并把它的日志目录挪进 tmp（不往 gates/logs 里写东西）。"""
    run_gates = _load_run_gates()

    monkeypatch.setattr(run_gates, "LOG_DIR", tmp_path / "logs")
    monkeypatch.delenv(run_gates.FLAKE_PROBE_ENV, raising=False)
    return run_gates


def _run_fake_gate(rg, name: str, code: str) -> dict:
    """起一道假门并收结果（与 tests/test_gate_summary_truthful.py 同一体例）。"""
    proc, t0, why = rg.start_gate(name, [sys.executable, "-c", code])
    assert proc is not None, why
    return rg.finish_gate(name, proc, t0, 120)


def test_wiring_isolated_green_still_keeps_the_gate_red(rg, monkeypatch) -> None:
    """判据 3：`[隔离跑绿]` 只加信息 —— exit_code 不许因此变 0。"""
    monkeypatch.setenv(rg.FLAKE_PROBE_ENV, "1")
    monkeypatch.setattr(rg, "_FLAKE_MODULE", _StubProbe(fp.ISOLATED_GREEN))
    row = _run_fake_gate(rg, "pytest", FAKE_RED)
    assert row["exit_code"] == 1, row
    head = str(row["detail"]).splitlines()[0]
    assert head.startswith(rg.FLAKE_LABELS[fp.ISOLATED_GREEN]), head
    assert "tests/test_fake.py::test_boom" in head


def test_wiring_undecidable_error_still_keeps_the_gate_red(rg, monkeypatch) -> None:
    """判据 1：判不出（超时/起不来）不许当绿，也不许当红 —— 门仍是原来那个红。"""
    monkeypatch.setenv(rg.FLAKE_PROBE_ENV, "1")
    monkeypatch.setattr(rg, "_FLAKE_MODULE", _StubProbe(fp.ERROR, "超时 600 秒没跑完：x"))
    row = _run_fake_gate(rg, "pytest", FAKE_RED)
    assert row["exit_code"] == 1, row
    head = str(row["detail"]).splitlines()[0]
    assert head.startswith(rg.FLAKE_LABELS[fp.ERROR]), head


def test_wiring_green_gate_row_still_carries_no_detail(rg, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 2：绿门 detail 逐字不变（仍是空）—— 探针开关开着也一样。"""
    monkeypatch.setenv(rg.FLAKE_PROBE_ENV, "1")
    monkeypatch.setattr(rg, "_FLAKE_MODULE", _StubProbe(fp.ISOLATED_GREEN))
    row = _run_fake_gate(rg, "pytest", FAKE_GREEN)
    assert row["exit_code"] == 0, row
    assert not row.get("detail"), row


def test_wiring_off_switch_says_so_instead_of_staying_silent(rg) -> None:
    """判据 4：关着时 detail 第一段明写「本次未做隔离复核」，不许静默省略。"""
    assert rg.flake_probe_on() is False
    row = _run_fake_gate(rg, "pytest", FAKE_RED)
    assert row["exit_code"] == 1, row
    first = str(row["detail"]).splitlines()[0]
    assert first == rg.FLAKE_PROBE_OFF_NOTE, first
    assert OFF_NOTE in rg.FLAKE_PROBE_OFF_NOTE


def test_wiring_switch_reads_only_a_literal_one(rg, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 4：`1` 才开；`0` / `yes` / 空串 / 没设 都算关。"""
    monkeypatch.setenv(rg.FLAKE_PROBE_ENV, "1")
    assert rg.flake_probe_on() is True
    for other in ("0", "yes", "true", "  ", ""):
        monkeypatch.setenv(rg.FLAKE_PROBE_ENV, other)
        assert rg.flake_probe_on() is False, other
    monkeypatch.delenv(rg.FLAKE_PROBE_ENV, raising=False)
    assert rg.flake_probe_on() is False
