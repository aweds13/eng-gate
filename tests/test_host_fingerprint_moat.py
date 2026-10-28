"""宿主窗口指纹不许渗进子进程（卡 E58 · T-AG509 漏掉的第二条路）。

## 疼在哪（2026-10-28 实测）

卡 E57 加了 `tests/conftest.py` 的 `_no_host_session_id` 夹具，把 `DSH_SESSION_ID`
从测试进程里摘掉。它对「测试进程自己」是对的，但**拦不住环境快照**：

    _ENV = {k: v for k, v in os.environ.items() if k not in (...)}

这种写法在**模块导入时**就把 `os.environ` 拍成快照。conftest 先导入、测试模块后导入
—— 所以夹具在用例执行时删得再干净，快照里**照样带着指纹**，指纹跟着 `env=_ENV`
进了每个子进程。

实际后果（不是理论）：壳里带着 `session-c5ee5ccd-…` 时

    tests/test_wb_land.py::test_card_and_batch_is_exactly_one

拿到的不是「恰好给一个」，而是

    ★ 卡 T-G999 归另一个对话窗口（session-…）；换手要显式加 --take-over

因为 `gates/diag/session-leases.json`（gitignored 的**本机状态**）里恰好挂着 `T-G999`。
与 E57 那次假红 9 条完全同型：判据吃进了「这台机器上谁持有哪张卡」。

## 修法（一处，不是八处）

`tests/conftest.py` **在模块级**就 `os.environ.pop("DSH_SESSION_ID", None)`。
conftest 必定先于所有测试模块被导入 ⇒ 8 处快照与夹具**两条路一起干净**，
不用去八个文件里各加一个过滤条件（那种改法下一份新快照又会漏）。

## 判据（本文件钉住的四件事）

1. `tests/conftest.py` 在**模块级**（0 缩进、且早于夹具定义）摘指纹。
2. **功能验证**：真设一个哨兵指纹，在子进程里导入带快照的测试模块，
   断言快照里**没有**那个哨兵 —— 这是唯一能证明「导入时摘掉了」的方式。
3. 反向验证：如果 conftest 没摘，快照里就该有 —— 证明第 2 条不是空转。
4. `wb_session` 的口径不变：指纹缺失 ⇒ 一律放行（不是报错、不是不确定）。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFTEST = ROOT / "tests" / "conftest.py"

#: 哨兵指纹 —— 一个现实中不可能撞上的值。
SENTINEL = "session-0000deadbeef-E58-sentinel"

#: 带环境快照、且会被本钉子功能验证的两个测试模块。
#: 选这两个是因为它们的快照直接喂给 `wb_session` 判定会话归属。
PROBE_MODULES = ("tests/test_wb_land.py", "tests/test_landing_stamp.py")

#: 子进程里跑的一段探针：导入 conftest 与目标模块，报告快照里有没有哨兵。
_PROBE = r"""
import json, os, sys
from pathlib import Path

root = Path(sys.argv[1])
target = sys.argv[2]
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "tests"))

sentinel = os.environ.get("DSH_SESSION_ID")

# 1) 先导入 conftest（pytest 在真跑时就是先导入它）
import conftest  # noqa: F401

after_conftest = os.environ.get("DSH_SESSION_ID")

# 2) 再导入被测模块 —— 此刻它会在模块级拍快照
import importlib.util
spec = importlib.util.spec_from_file_location("_probe_mod", root / target)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

env = getattr(mod, "_ENV", None)
leaked = None if env is None else env.get("DSH_SESSION_ID")

print(json.dumps({
    "target": target,
    "sentinel_in_shell": sentinel,
    "after_conftest": after_conftest,
    "snapshot_has_sentinel": leaked,
    "has_snapshot": env is not None,
}))
"""


def _run_probe(target: str, *, with_sentinel: bool) -> dict:
    """在子进程里导入 conftest + 目标模块，回报快照里有没有指纹。"""
    env = {k: v for k, v in os.environ.items()}
    env.pop("DSH_SESSION_ID", None)
    if with_sentinel:
        env["DSH_SESSION_ID"] = SENTINEL
    r = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", _PROBE, str(ROOT), target],
        cwd=str(ROOT), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    out = (r.stdout or "").strip()
    assert r.returncode == 0 and out, (
        f"探针没跑起来（exit={r.returncode}）\nstdout={r.stdout}\nstderr={r.stderr}"
    )
    import json
    return json.loads(out.splitlines()[-1])


def test_conftest_pops_the_fingerprint_at_import_time() -> None:
    """`tests/conftest.py` 必须在**模块级**摘指纹（不是只在夹具里）。"""
    lines = CONFTEST.read_text(encoding="utf-8").splitlines()

    pop_lines = [
        i for i, line in enumerate(lines, start=1)
        if "os.environ.pop" in line and "DSH_SESSION_ID" in line
    ]
    assert pop_lines, (
        'tests/conftest.py 没有在导入时 `os.environ.pop("DSH_SESSION_ID", None)` —— '
        "只靠 `_no_host_session_id` 夹具拦不住「模块导入时快照环境」的那些 `_ENV`"
    )

    for lineno in pop_lines:
        text = lines[lineno - 1]
        assert text == text.lstrip(), (
            f"tests/conftest.py:{lineno} 的 `os.environ.pop` 有缩进 ⇒ 不在模块级，导入时不执行"
        )

    fixture_line = next(
        (i for i, line in enumerate(lines, start=1) if "def _no_host_session_id" in line),
        None,
    )
    if fixture_line is not None:
        assert min(pop_lines) < fixture_line, (
            f"`os.environ.pop` 在第 {min(pop_lines)} 行，晚于夹具定义（第 {fixture_line} 行）"
            " —— 位置本身不致命，但它该待在模块顶部，和别的「进程级口径」放一起"
        )


def test_sentinel_does_not_reach_any_snapshot() -> None:
    """★ 功能判据：壳里带哨兵指纹时，导入后的环境快照里**不许**有它。"""
    for target in PROBE_MODULES:
        info = _run_probe(target, with_sentinel=True)
        assert info["sentinel_in_shell"] == SENTINEL, (
            f"{target}：哨兵没被传进子进程，判据不成立\n{info}"
        )
        assert info["after_conftest"] is None, (
            f"{target}：导入 conftest 之后 `DSH_SESSION_ID` 还在（={info['after_conftest']!r}）"
            " ⇒ 模块级 pop 没生效"
        )
        assert info["has_snapshot"], (
            f"{target}：模块里已经没有 `_ENV` 快照 —— 本钉子探测的目标变了，请更新 PROBE_MODULES"
        )
        assert info["snapshot_has_sentinel"] is None, (
            f"{target}：`_ENV` 快照里带着宿主指纹 {info['snapshot_has_sentinel']!r}"
            " ⇒ 它会跟着 `env=_ENV` 进子进程，`wb_session` 于是判「另一个对话窗口」"
        )


def test_reverse_the_snapshot_would_carry_it_without_the_pop() -> None:
    """反向验证：不导入 conftest 时，同一份快照**会**带上哨兵 —— 证明上一条不是空转。"""
    env = {k: v for k, v in os.environ.items()}
    env["DSH_SESSION_ID"] = SENTINEL
    code = (
        "import json, os\n"
        "_ENV = {k: v for k, v in os.environ.items() if k != 'PYTHONPATH'}\n"
        "print(json.dumps({'leaked': _ENV.get('DSH_SESSION_ID')}))\n"
    )
    r = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", code],
        cwd=str(ROOT), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert r.returncode == 0, r.stderr
    import json
    assert json.loads(r.stdout.strip())["leaked"] == SENTINEL, (
        "不摘指纹时快照居然没带上它 —— 那上一条判据就是空转，得换探测方式"
    )


def test_wb_session_allows_when_fingerprint_is_absent() -> None:
    """口径钉子：指纹缺失 ⇒ `wb_session` 一律放行（不是报错、不是不确定）。"""
    env = {k: v for k, v in os.environ.items() if k != "DSH_SESSION_ID"}
    r = subprocess.run(
        [sys.executable, "-X", "utf8", str(ROOT / "tools" / "wb_session.py"),
         "--status", "T-G999"],
        cwd=str(ROOT), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    out = (r.stdout or "") + (r.stderr or "")
    assert "另一个对话窗口" not in out, (
        "指纹缺失时 wb_session 仍判「另一个窗口」—— 口径反了。输出：\n" + out
    )
