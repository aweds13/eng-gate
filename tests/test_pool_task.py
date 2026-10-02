r"""任务栅栏搬进 git（卡 119 · T-G217）的钉子。

为什么有它：任务栅栏（注册任务 → 每张卡交成送申请 → 集齐才收口）原来住在 `gates/diag/tf_batch.py`
—— gitignore 的 scratch。卡 119 把它搬进 git（权威副本 `tools/pool/task.py`，命令行壳
`tools/wb_task.py`）。搬运的判据是「**行为一个字都不许变**」，所以：

| 判据 | 钉什么 |
|---|---|
| ① 原 33 条反例钉子 | `task.selftest()` 的每条守卫**逐条搬成 pytest**（一条不许少）——搬完还能咬人 |
| ② 壳与本体一致 | 同一任务，`tools/wb_task.py status` 与 `pool.task` 的输出**逐字一致** |
| ③ TOML 文本安全 | `_toml_str()` 对含 `"` 与反斜杠的文本产出的仍是**合法 TOML** |

★ 导入口径照既有测试：把 `tools/` 挂上 `sys.path` 再 `import`（`tests/test_pool_lib.py` 同款）。
★ 33 条钉子共用**一套顺序场景**（状态机是接力的），所以用一个 module 级 fixture 重放一遍、
  逐条记录读数，再按名字参数化成 33 个用例 —— 谁红了看得见是哪条。
"""

from __future__ import annotations

import contextlib
import datetime
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import tomllib

if TYPE_CHECKING:
    from collections.abc import Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from pool import task  # noqa: E402 —— tools/ 已在 sys.path 上

#: 33 条钉子的名字 —— 与 `task.selftest()` 里 `nail(...)` 的**逐字一致、顺序一致**（一条不许少）。
NAIL_NAMES = (
    "register 注册任务成功",
    "★ 放行判据记成『全部成送申请』而不是数量",
    "层从成员里推出来",
    "第 1 张卡交申请 ⇒ 仍是 collecting（不提前放行）",
    "还缺 B、C",
    "重复交申请幂等（计数不涨）",
    "★ 逐卡域越界必须拒收（rc=2 + 点名到文件 + 指出这张卡的域）",
    "★ 越界那次**没覆盖**已收到的申请",
    "★ 名单外的申请不算数",
    "★ 成功申请**必须带证据**（没证据 rc=2）",
    "投『不通过』不进成功数",
    "★ 名单都投过了、但有一张『不通过』⇒ **仍然不放行**",
    "不通过挡住的理由写进 history",
    "★ 重投成功申请 ⇒ 集齐当场放行（awaiting-commit）",
    "门禁读数进状态（green）",
    "文书骨架自动生成且**按层分组**",
    "骨架里带上乙的证据",
    "状态变化全进 history",
    "人手补的『为什么』文件被建出来（单独一份）",
    "★ 申请更新后 advance 能重算骨架",
    "★ 重算**不冲掉**人写的 why 文件",
    "重算记进 history（写日志）",
    "★ 豁免后不齐也能放行（留痕）",
    "豁免在骨架里写明",
    "★ 门禁红 ⇒ 停在 ready 不提交且非零退出",
    "★ 过期只判死不放行",
    "缺 layer 必须报错（rc=2）",
    "★ 预声明没验过就**不落盘**（不留下半截任务）",
    "缺 paths（这张卡的域）必须报错",
    "★ 按层把待办登记收成成员",
    "★ 成任务后从待办表划掉（不重复收）",
    "空层成任务必须报错（rc=2）",
    "★ 目录**不存在**时也能登记（自己把目录建出来）",
)


def _replay(root: Path, record: Callable[[str, bool, str], None]) -> None:
    """把 `task.selftest()` 的整套场景**原样重放**一遍，逐条把读数交给 `record`。

    `record(名字, 是否通过, 细节)` —— ★ 只搬**场景步骤**（调 `task.main` 这些公开函数），
    不重写任何判据 —— 判据仍在 `pool.task` 里。
    """

    def run_cap(*argv: str) -> tuple[int, str]:
        """跑一条命令并**连人看到的报错一起收**（守卫咬人时 `main` 兜底成 rc=2 + stderr）。"""
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = task.main([*argv])
        return rc, err.getvalue()

    # ★ 源预声明放 `src/` 子目录，**不要**直接放批目录 —— 否则"有没有落半截任务"这条自证
    #   会被源文件自己撞成假阳性（自证时咬过一次）。
    (root / "src").mkdir(parents=True, exist_ok=True)

    def write_man(name: str, body: str) -> Path:
        path = root / "src" / name
        path.write_text(body, encoding="utf-8", newline="\n")
        return path

    # ★ 门禁桩（卡 128）：`gate_cmd` 现在过**白名单**（只认 `python -X utf8 scripts/…|tools/…`），
    #   所以桩不能再写 `exit 0` / `exit 1` —— 用仓库内脚本：green=rc0、red=rc2。
    gate_green = "python -X utf8 tools/wb_task.py list"
    gate_red = "python -X utf8 tools/wb_task.py status __no_such_task__"

    man = write_man("T-1.toml", (
        'id = "T-1"\n'
        'why = "自证用：审美层 + 后端一次收口"\n'
        f'gate_cmd = {json.dumps(gate_green)}\non_complete = ["gate", "draft"]\n'
        '\n[[member]]\nid = "卡A"\nlayer = "后端"\nwhat = "甲"\npaths = ["tools/a/*"]\n'
        '\n[[member]]\nid = "卡B"\nlayer = "后端"\nwhat = "乙"\npaths = ["tools/b/*"]\n'
        '\n[[member]]\nid = "卡C"\nlayer = "审美层"\nwhat = "丙"\npaths = ["ui/*"]\n'))

    rc = run_cap("register", str(man))[0]
    record("register 注册任务成功", rc == 0, f"rc={rc}")
    st = task.read_json(root / "T-1.json")
    record("★ 放行判据记成『全部成送申请』而不是数量", st["need"] == 3 and "claims" in st,
           f"need={st['need']}")
    record("层从成员里推出来", st["layers"] == ["后端", "审美层"], str(st["layers"]))

    rc, err = run_cap("claim", "T-1", "卡A", "--evidence", "pytest 3 passed", "--files",
                      "tools/a/x.py", "--why", "甲好了")
    st = task.read_json(root / "T-1.json")
    record("第 1 张卡交申请 ⇒ 仍是 collecting（不提前放行）",
           rc == 0 and st["state"] == "collecting", f"state={st['state']}")
    record("还缺 B、C", task._missing(st) == "卡B、卡C", task._missing(st))

    rc, err = run_cap("claim", "T-1", "卡A", "--evidence", "pytest 3 passed",
                      "--files", "tools/a/x.py", "--why", "甲又更新了")
    st = task.read_json(root / "T-1.json")
    record("重复交申请幂等（计数不涨）", len(task._ok(st)) == 1, str(task._ok(st)))

    rc, err = run_cap("claim", "T-1", "卡A", "--evidence", "x", "--files", "docs/别的.md")
    record("★ 逐卡域越界必须拒收（rc=2 + 点名到文件 + 指出这张卡的域）",
           rc == 2 and "自己域外" in err and "docs/别的.md" in err, f"rc={rc} err={err.strip()}")
    record("★ 越界那次**没覆盖**已收到的申请",
           task.read_json(root / "T-1.d" / "卡A.json")["why"] == "甲又更新了")

    rc, err = run_cap("claim", "T-1", "卡Z", "--evidence", "夹带", "--files", "tools/a/x.py")
    record("★ 名单外的申请不算数", rc == 2 and "不在这个任务的名单里" in err,
           f"rc={rc} err={err.strip()}")

    rc, err = run_cap("claim", "T-1", "卡B", "--files", "tools/b/x.py", "--why", "乙好了")
    record("★ 成功申请**必须带证据**（没证据 rc=2）",
           rc == 2 and "必须带证据" in err, f"rc={rc} err={err.strip()}")

    # ---- "不通过"必须挡住收口 ----
    rc, err = run_cap("claim", "T-1", "卡B", "--claim", "failed", "--why", "乙那件事黄了")
    st = task.read_json(root / "T-1.json")
    record("投『不通过』不进成功数", task._ok(st) == {"卡A"}, str(task._ok(st)))
    rc, err = run_cap("claim", "T-1", "卡C", "--evidence", "ui 三张图都过", "--files", "ui/c.png")
    st = task.read_json(root / "T-1.json")
    record("★ 名单都投过了、但有一张『不通过』⇒ **仍然不放行**",
           rc == 3 and st["state"] == "collecting", f"rc={rc} state={st['state']}")
    record("不通过挡住的理由写进 history",
           any("不通过" in row["note"] for row in st["history"]))

    rc, err = run_cap("claim", "T-1", "卡B", "--evidence", "重做后 pytest 5 passed",
                      "--files", "tools/b/x.py", "--why", "乙重做完了")
    st = task.read_json(root / "T-1.json")
    record("★ 重投成功申请 ⇒ 集齐当场放行（awaiting-commit）",
           rc == 0 and st["state"] == "awaiting-commit", f"rc={rc} state={st['state']}")
    record("门禁读数进状态（green）", (st.get("gate") or {}).get("verdict") == "green",
           str(st.get("gate")))
    draft = root / "T-1.draft.md"
    text = draft.read_text(encoding="utf-8") if draft.exists() else ""
    record("文书骨架自动生成且**按层分组**", "### 层：后端" in text and "### 层：审美层" in text)
    record("骨架里带上乙的证据", "乙重做完了" in text)
    record("状态变化全进 history",
           any("集齐全部成送申请" in row["note"] for row in st["history"]))

    # ---- 骨架可重算 + 人写的东西不被冲掉 ----
    why = root / "T-1.why.md"
    record("人手补的『为什么』文件被建出来（单独一份）", why.exists())
    why.write_text("我人写的：为什么这三张卡一起收", encoding="utf-8", newline="\n")
    rc = run_cap("claim", "T-1", "卡A", "--evidence", "pytest 4 passed", "--files",
                 "tools/a/x.py", "--why", "甲再改一句")[0]
    rc = run_cap("advance", "T-1")[0]
    text = draft.read_text(encoding="utf-8")
    record("★ 申请更新后 advance 能重算骨架", rc == 0 and "甲再改一句" in text, f"rc={rc}")
    record("★ 重算**不冲掉**人写的 why 文件",
           why.read_text(encoding="utf-8") == "我人写的：为什么这三张卡一起收")
    record("重算记进 history（写日志）",
           any("重算骨架" in row["note"] for row in task.read_json(root / "T-1.json")["history"]))

    # ---- 豁免是"不齐也能放行"的唯一合法路径 ----
    man2 = write_man("T-2.toml", (
        'id = "T-2"\nwhy = "豁免自证"\n'
        f'gate_cmd = {json.dumps(gate_green)}\non_complete = ["gate", "draft"]\n'
        '\n[[member]]\nid = "卡A"\nlayer = "后端"\nwhat = "甲"\npaths = ["a/*"]\n'
        '\n[[member]]\nid = "卡B"\nlayer = "后端"\nwhat = "乙"\npaths = ["b/*"]\n'))
    run_cap("register", str(man2))
    run_cap("claim", "T-2", "卡A", "--evidence", "ok", "--files", "a/x.py")
    rc, err = run_cap("waive", "T-2", "卡B", "--reason", "乙那件事用户撤了")
    st2 = task.read_json(root / "T-2.json")
    record("★ 豁免后不齐也能放行（留痕）", rc == 0 and st2["state"] == "awaiting-commit",
           f"rc={rc} state={st2['state']}")
    record("豁免在骨架里写明", "豁免" in (root / "T-2.draft.md").read_text(encoding="utf-8"))

    # ---- 门禁红了 ⇒ 不许提交 ----
    man3 = write_man("T-3.toml", (
        'id = "T-3"\nwhy = "红门禁自证"\n'
        f'gate_cmd = {json.dumps(gate_red)}\non_complete = ["gate", "draft"]\n'
        '\n[[member]]\nid = "卡A"\nlayer = "后端"\nwhat = "甲"\npaths = ["a/*"]\n'))
    run_cap("register", str(man3))
    rc, err = run_cap("claim", "T-3", "卡A", "--evidence", "ok", "--files", "a/x.py")
    st3 = task.read_json(root / "T-3.json")
    record("★ 门禁红 ⇒ 停在 ready 不提交且非零退出", rc == 3 and st3["state"] == "ready",
           f"rc={rc} state={st3['state']}")

    # ---- 过期判死绝不放行 ----
    man4 = write_man("T-4.toml", (
        'id = "T-4"\nwhy = "过期自证"\n'
        '\n[[member]]\nid = "卡A"\nlayer = "后端"\nwhat = "甲"\npaths = ["a/*"]\n'
        '\n[[member]]\nid = "卡B"\nlayer = "后端"\nwhat = "乙"\npaths = ["b/*"]\n'))
    run_cap("register", str(man4))
    run_cap("claim", "T-4", "卡A", "--evidence", "ok", "--files", "a/x.py")
    run_cap("expire", "T-4")
    st4 = task.read_json(root / "T-4.json")
    record("★ 过期只判死不放行", st4["state"] == "timeout", st4["state"])

    # ---- 预声明不合法 ⇒ 不落盘 ----
    man5 = write_man("T-5.toml", 'id = "T-5"\nwhy = "缺 layer"\n'
                                 '\n[[member]]\nid = "卡A"\nwhat = "甲"\npaths = ["a/*"]\n')
    rc, err = run_cap("register", str(man5))
    record("缺 layer 必须报错（rc=2）", rc == 2 and "layer" in err, f"rc={rc} err={err.strip()}")
    record("★ 预声明没验过就**不落盘**（不留下半截任务）",
           not (root / "T-5.toml").exists() and not (root / "T-5.json").exists())
    man6 = write_man("T-6.toml", 'id = "T-6"\nwhy = "缺 paths"\n'
                                 '\n[[member]]\nid = "卡A"\nlayer = "后端"\nwhat = "甲"\n')
    rc, err = run_cap("register", str(man6))
    record("缺 paths（这张卡的域）必须报错", rc == 2 and "paths" in err,
           f"rc={rc} err={err.strip()}")

    # ---- 待办登记 → 成任务 ----
    run_cap("pool", "add", "--layer", "前端", "--what", "甲", "--files", "web/a.ts")
    run_cap("pool", "add", "--layer", "前端", "--what", "乙", "--files", "web/b.ts")
    run_cap("pool", "add", "--layer", "后端", "--what", "丙", "--files", "srv/c.py")
    rc, err = run_cap("register", "--from-pool", "前端", "--id", "T-P1")
    stp = task.read_json(root / "T-P1.json")
    record("★ 按层把待办登记收成成员", rc == 0 and stp["declared"] == ["P-1", "P-2"],
           f"rc={rc} declared={stp['declared']}")
    record("★ 成任务后从待办表划掉（不重复收）",
           [r["id"] for r in task._load_pool()] == ["P-3"],
           str([r["id"] for r in task._load_pool()]))
    rc, err = run_cap("register", "--from-pool", "空层", "--id", "T-P9")
    record("空层成任务必须报错（rc=2）", rc == 2 and "一条登记都没有" in err,
           f"rc={rc} err={err.strip()}")

    # ---- 新机器第一次用：目录还不存在 ----
    fresh = root / "fresh" / "batch"
    old = os.environ["TF_BATCH_DIR"]
    os.environ["TF_BATCH_DIR"] = str(fresh)
    try:
        rc, err = run_cap("pool", "add", "--layer", "后端", "--what", "w", "--files", "x.py")
        record("★ 目录**不存在**时也能登记（自己把目录建出来）",
               rc == 0 and (fresh / "pool.json").exists(), f"rc={rc} err={err.strip()}")
    finally:
        os.environ["TF_BATCH_DIR"] = old


@pytest.fixture(scope="module")
def nailed(tmp_path_factory):
    """重放一遍 33 条钉子的场景，返回 `{名字: (是否通过, 细节)}`（重放一次给 33 个用例共用）。"""
    root = tmp_path_factory.mktemp("task-119")
    saved = os.environ.get("TF_BATCH_DIR")
    os.environ["TF_BATCH_DIR"] = str(root)
    results: dict[str, tuple[bool, str]] = {}
    try:
        _replay(root, lambda name, ok, detail="": results.__setitem__(name, (ok, detail)))
    finally:
        if saved is None:
            os.environ.pop("TF_BATCH_DIR", None)
        else:
            os.environ["TF_BATCH_DIR"] = saved
    missing = [name for name in NAIL_NAMES if name not in results]
    assert not missing, f"重放没记到这 {len(missing)} 条钉子：{missing}"
    assert len(results) == len(NAIL_NAMES), f"记到 {len(results)} 条，应 {len(NAIL_NAMES)} 条"
    return results


@pytest.mark.parametrize("name", NAIL_NAMES)
def test_nail(nailed, name):
    """原 `task.selftest()` 的一条反例钉子（搬成 pytest，判据一字未改）。"""
    ok, detail = nailed[name]
    assert ok, f"{name}   [{detail}]"


# ================================================================ 两条新钉子


def test_shell_status_matches_body(tmp_path, monkeypatch):
    """★ 壳与本体行为一致：同一任务，`tools/wb_task.py status` 与 `pool.task` 的输出逐字一致。"""
    batch = tmp_path / "batch"
    src = tmp_path / "src"
    src.mkdir()
    man = src / "T-1.toml"
    man.write_text(
        'id = "T-1"\nwhy = "壳/本体一致自证"\n'
        '\n[[member]]\nid = "卡A"\nlayer = "后端"\nwhat = "甲"\npaths = ["a/*"]\n',
        encoding="utf-8", newline="\n")

    monkeypatch.setenv("TF_BATCH_DIR", str(batch))
    assert task.main(["register", str(man)]) == 0

    # 本体（进程内）
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc_body = task.main(["status", "T-1"])
    body = buf.getvalue()

    # 壳（真起一个子进程跑 `tools/wb_task.py`）
    env = dict(os.environ)
    env["TF_BATCH_DIR"] = str(batch)
    done = subprocess.run(
        [sys.executable, "-X", "utf8", str(ROOT / "tools" / "wb_task.py"), "status", "T-1"],
        cwd=str(ROOT), env=env, capture_output=True, text=True, encoding="utf-8",
        errors="replace")

    assert done.returncode == rc_body, (
        f"壳 exit={done.returncode} 本体 exit={rc_body}：{done.stderr}")
    assert done.stdout == body, f"壳与本体输出不一致：\n--壳--\n{done.stdout}\n--本体--\n{body}"


def test_toml_str_survives_quotes_and_backslashes():
    """★ 写进 TOML 的文本不怕引号：`_toml_str()` 对含 `"` 与反斜杠的文本产出的仍是合法 TOML。"""
    raw = 'he said "你好" \\ and C:\\x\\y and a "" pair'
    encoded = task._toml_str(raw)
    assert tomllib.loads("v = " + encoded)["v"] == raw
    # 反证：原样（不转义）塞进 TOML 就不是合法语法 —— 说明这条钉子确有其事
    with pytest.raises(tomllib.TOMLDecodeError):
        tomllib.loads("v = " + raw)


# ================================================================ 卡 128 的六处判据（九条新钉子）

GATE_GREEN = "python -X utf8 tools/wb_task.py list"
GATE_RED = "python -X utf8 tools/wb_task.py status __no_such_task__"


def _manifest(task_id, paths_by_member, *, gate_cmd=None, on_complete=("draft",), deadline=None):
    """拼一份预声明 TOML。`paths_by_member` = [(成员号, [域…]), …]。"""
    lines = [f'id = "{task_id}"', f'why = "{task_id} 用"']
    if gate_cmd:
        lines.append(f"gate_cmd = {json.dumps(gate_cmd)}")
    if deadline:
        lines.append(f"deadline = {json.dumps(deadline)}")
    lines.append(f"on_complete = {json.dumps(list(on_complete))}")
    for mid, paths in paths_by_member:
        lines += ["", "[[member]]", f'id = "{mid}"', 'layer = "后端"', f'what = "{mid}"',
                  f"paths = {json.dumps(paths, ensure_ascii=False)}"]
    return "\n".join(lines) + "\n"


def _register(tmp_path, task_id, body, *, expect_ok=True):
    """写预声明 → `register`；返回 (rc, stderr 文本)。"""
    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)
    man = src / f"{task_id}.toml"
    man.write_text(body, encoding="utf-8", newline="\n")
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        rc = task.main(["register", str(man)])
    if expect_ok:
        assert rc == 0, err.getvalue()
    return rc, err.getvalue()


def _iso(offset_seconds: float) -> str:
    return (datetime.datetime.now().astimezone()
            + datetime.timedelta(seconds=offset_seconds)).isoformat(timespec="seconds")


def _green(cmd: str) -> dict:
    return {"cmd": cmd, "exit_code": 0, "verdict": "green", "at": task.now_iso(), "tail": ""}


def test_nail128_01_stale_lock_taken_over(tmp_path, monkeypatch):
    """① 陈旧锁能接管：伪造 `at = now - TTL - 60` ⇒ claim 成功，history 有接管那一行。"""
    monkeypatch.setenv("TF_BATCH_DIR", str(tmp_path / "batch"))
    _register(tmp_path, "T-X", _manifest("T-X", [("卡A", ["tools/a/*"]), ("卡B", ["tools/b/*"])]))
    lock = task.state_path("T-X").with_suffix(".json.lock")
    lock.write_text(json.dumps({"owner": "ghost", "pid": 999, "task": "T-X",
                                "at": _iso(-(task.DEFAULT_LOCK_TTL + 60))}), encoding="utf-8")

    rc = task.main(["claim", "T-X", "卡A", "--evidence", "ok", "--files", "tools/a/x.py"])
    state = task.read_json(task.state_path("T-X"))
    takeover = [row["note"] for row in state["history"] if "接管" in row["note"]]
    assert rc == 0, f"rc={rc}"
    assert takeover, f"history 里没有接管行：{state['history']}"
    assert "ghost" in takeover[0], takeover[0]
    assert not lock.exists(), "跑完该把锁放掉"


def test_nail128_02_live_lock_refused(tmp_path, monkeypatch):
    """② 活锁照样拒：刚写的锁 ⇒ rc=2，不许接管。"""
    monkeypatch.setenv("TF_BATCH_DIR", str(tmp_path / "batch"))
    monkeypatch.setenv("TF_BATCH_LOCK_WAIT", "0.3")   # 别真等 10 秒
    _register(tmp_path, "T-X", _manifest("T-X", [("卡A", ["tools/a/*"])]))
    lock = task.state_path("T-X").with_suffix(".json.lock")
    lock.write_text(json.dumps({"owner": "someone", "pid": 1, "task": "T-X",
                                "at": task.now_iso()}), encoding="utf-8")

    rc = task.main(["claim", "T-X", "卡A", "--evidence", "ok", "--files", "tools/a/x.py"])
    assert rc == 2, f"rc={rc}"
    assert json.loads(lock.read_text(encoding="utf-8"))["owner"] == "someone", "活锁不许被接管"


def test_nail128_03_gate_runs_without_lock(tmp_path, monkeypatch):
    """③ 门禁在无锁状态跑：桩检查锁文件**不存在**并写标记 ⇒ 标记在。"""
    monkeypatch.setenv("TF_BATCH_DIR", str(tmp_path / "batch"))
    _register(tmp_path, "T-X", _manifest("T-X", [("卡A", ["tools/a/*"])],
                                         gate_cmd=GATE_GREEN, on_complete=("gate", "draft")))
    lock = task.state_path("T-X").with_suffix(".json.lock")
    marker = tmp_path / "gate_ran.txt"
    seen: dict[str, object] = {}

    def stub(cmd: str) -> dict:
        seen["lock_exists_when_gating"] = lock.exists()
        marker.write_text("ran", encoding="utf-8")
        return _green(cmd)

    monkeypatch.setattr(task, "_run_gate_cmd", stub)
    rc = task.main(["claim", "T-X", "卡A", "--evidence", "ok", "--files", "tools/a/x.py"])
    assert rc == 0, f"rc={rc}"
    assert marker.exists(), "桩门禁没被跑到"
    assert seen["lock_exists_when_gating"] is False, "门禁跑的时候还持着锁"


def test_nail128_04_gate_runs_only_once(tmp_path, monkeypatch):
    """④ 门禁只跑一次：桩计数 + 重复投递 ⇒ `_run_gate_cmd` 执行次数 = 1。"""
    monkeypatch.setenv("TF_BATCH_DIR", str(tmp_path / "batch"))
    _register(tmp_path, "T-X", _manifest("T-X", [("卡A", ["tools/a/*"]), ("卡B", ["tools/b/*"])],
                                         gate_cmd=GATE_GREEN, on_complete=("gate", "draft")))
    calls: list[str] = []
    monkeypatch.setattr(task, "_run_gate_cmd", lambda cmd: (calls.append(cmd), _green(cmd))[1])

    assert task.main(["claim", "T-X", "卡A", "--evidence", "ok", "--files", "tools/a/x.py"]) == 0
    assert task.main(["claim", "T-X", "卡B", "--evidence", "ok", "--files", "tools/b/x.py"]) == 0
    # 再投一次（此时已是 awaiting-commit）—— 不许重跑
    assert task.main(["claim", "T-X", "卡A", "--evidence", "ok2", "--files", "tools/a/x.py"]) == 0
    assert len(calls) == 1, f"门禁跑了 {len(calls)} 次"

    # 第二个投递者看到 `gating`（门禁还没记账）⇒ 不重复跑
    state = task.read_json(task.state_path("T-X"))
    state["state"] = "gating"
    task.write_json_atomic(task.state_path("T-X"), state)
    task.main(["claim", "T-X", "卡A", "--evidence", "ok3", "--files", "tools/a/x.py"])
    assert len(calls) == 1, "看到 gating 还重复跑了门禁"


def test_nail128_05_selftest_restores_batch_dir(tmp_path, monkeypatch):
    """⑤ `selftest()` 之后 `batch_dir()` 复原（不指向已删的临时目录）。"""
    keep = tmp_path / "keep"
    monkeypatch.setenv("TF_BATCH_DIR", str(keep))
    before = task.batch_dir()
    assert task.selftest() == 0
    assert task.batch_dir() == before, f"batch_dir() 漂了：{task.batch_dir()}"


def test_nail128_06_advance_refuses_terminal(tmp_path, monkeypatch):
    """⑥ `advance` 对 `landed` / `timeout` 都拒（rc≠0 且状态**一字不变**）。"""
    monkeypatch.setenv("TF_BATCH_DIR", str(tmp_path / "batch"))
    _register(tmp_path, "T-X", _manifest("T-X", [("卡A", ["tools/a/*"])]))
    assert task.main(["claim", "T-X", "卡A", "--evidence", "ok", "--files", "tools/a/x.py"]) == 0
    assert task.main(["landed", "T-X", "--commit", "deadbeef"]) == 0

    before = task.read_json(task.state_path("T-X"))
    rc = task.main(["advance", "T-X"])
    assert rc == 2, f"advance-on-landed rc={rc}"
    assert task.read_json(task.state_path("T-X")) == before, "advance 动了 landed 的状态"

    st = task.read_json(task.state_path("T-X"))
    st["state"], st["landed"] = "timeout", None
    task.write_json_atomic(task.state_path("T-X"), st)
    before = task.read_json(task.state_path("T-X"))
    rc = task.main(["advance", "T-X"])
    assert rc == 2, f"advance-on-timeout rc={rc}"
    assert task.read_json(task.state_path("T-X")) == before, "advance 抹了 timeout"


def test_nail128_07_expire_and_deadline(tmp_path, monkeypatch):
    """⑦ `expire` 没到期 ⇒ 拒；到期 ⇒ 判死；过期的任务再 claim ⇒ 自动判死且不放行。"""
    monkeypatch.setenv("TF_BATCH_DIR", str(tmp_path / "batch"))
    future, past = _iso(86400), _iso(-86400)

    # 没到期 ⇒ 拒（状态不变）
    _register(tmp_path, "T-A", _manifest("T-A", [("卡A", ["tools/a/*"])], deadline=future))
    assert task.main(["expire", "T-A"]) == 2
    assert task.read_json(task.state_path("T-A"))["state"] == "collecting"

    # 到期 ⇒ 判死
    _register(tmp_path, "T-B", _manifest("T-B", [("卡A", ["tools/a/*"])], deadline=past))
    assert task.main(["expire", "T-B"]) == 0
    assert task.read_json(task.state_path("T-B"))["state"] == "timeout"

    # 过期的任务再 claim ⇒ 自动判死且不放行（成功申请数 = 0）
    _register(tmp_path, "T-C", _manifest("T-C", [("卡A", ["tools/a/*"])], deadline=past))
    rc = task.main(["claim", "T-C", "卡A", "--evidence", "ok", "--files", "tools/a/x.py"])
    st = task.read_json(task.state_path("T-C"))
    assert rc == 2, f"过期 claim rc={rc}"
    assert st["state"] == "timeout", st["state"]
    assert task._ok(st) == set(), "过期还放进了成功申请"


def test_nail128_08_gate_cmd_whitelist(tmp_path, monkeypatch):
    """⑧ `gate_cmd` 校验：shell 元字符 / `bash -c` / 仓外脚本 ⇒ register 拒并点名；正常 ⇒ 通过。"""
    monkeypatch.setenv("TF_BATCH_DIR", str(tmp_path / "batch"))
    one = [("卡A", ["tools/a/*"])]
    bad_cmds = [
        "bash -c 'echo hi'",
        "rm -rf /",
        "python -X utf8 scripts/run_gates.py; rm -rf x",
        "python -X utf8 scripts/run_gates.py | tee log",
        "python -X utf8 scripts/run_gates.py > log",
        "python -X utf8 scripts/`x`.py",
        "python -X utf8 /etc/passwd",
    ]
    for i, bad in enumerate(bad_cmds):
        tid = f"T-BAD{i}"
        rc, err = _register(tmp_path, tid, _manifest(tid, one, gate_cmd=bad), expect_ok=False)
        assert rc == 2, f"{bad!r} ⇒ rc={rc}"
        assert bad in err, f"报错没点名那条命令：{err!r}"

    # 正常的仓库内脚本 ⇒ 通过（两次：scripts/ 与 tools/）
    for i, ok in enumerate(["python -X utf8 scripts/run_gates.py", GATE_GREEN]):
        tid = f"T-OK{i}"
        _register(tmp_path, tid, _manifest(tid, one, gate_cmd=ok))

    # claim 时**再校验一次**（防手改 manifest）
    _register(tmp_path, "T-OKX", _manifest("T-OKX", one, gate_cmd=GATE_GREEN))
    task.manifest_path("T-OKX").write_text(
        _manifest("T-OKX", one, gate_cmd="bash -c 'evil'"), encoding="utf-8", newline="\n")
    rc = task.main(["claim", "T-OKX", "卡A", "--evidence", "ok", "--files", "tools/a/x.py"])
    assert rc == 2, f"手改 manifest 后 claim 没拒：rc={rc}"


def test_nail128_09_protected_files_rejected(tmp_path, monkeypatch):
    """⑨ 受保护文件不许进域：写进 `paths` ⇒ register 拒；写进 `--files` ⇒ claim 拒。"""
    monkeypatch.setenv("TF_BATCH_DIR", str(tmp_path / "batch"))

    # register：精确路径与通配都拒
    for i, paths in enumerate([["docs/traceability.toml"], ["docs/**"], ["gates/*.json"]]):
        tid = f"T-P{i}"
        rc, err = _register(tmp_path, tid, _manifest(tid, [("卡A", paths)]), expect_ok=False)
        assert rc == 2, f"paths={paths} ⇒ rc={rc}"
        assert "受保护" in err, f"没点名受保护文件：{err!r}"

    # claim：域合法，但 `--files` 自报了一个受保护文件 ⇒ 拒
    _register(tmp_path, "T-Q", _manifest("T-Q", [("卡A", ["tools/a/*"])]))
    rc = task.main(["claim", "T-Q", "卡A", "--evidence", "ok", "--files", "docs/traceability.toml"])
    assert rc == 2, f"claim 把受保护文件写进 --files 没拒：rc={rc}"
