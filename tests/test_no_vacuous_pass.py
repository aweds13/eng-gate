r"""钉「一道门都没跑也算通过」（卡 E63 · T-AG521）：五条判据各一颗钉子。

## 病

本仓的门禁有三把尺子（本地 `scripts/run_gates.py`、云机 `tools/gate_pool.py`、
落地链 `tools/pool/landing.py`），对「通过」的定义各写各的。最严重的一条：

    gates_ok([]) is True        # `all()` 在空表上的数学性质

⇒ **一道门都没跑，整趟退 0、`ok=True`**，而同一份 payload 的 `not_run` 还写着「未验证」
—— 产物自己打自己（卡 E62 那趟 `gates/diag/cloud-gate-E62b.log` 就是活标本：
`ok=True`、`not_run=['render']`、`render exit=3 status=NOT RUN`）。

## 判据（卡规格 `复盘/卡/卡E63-一道门都没跑也算通过.md` §判据）

1. **零门必须红**：`gates_ok([])` 为 False；有门但全是不阻断的 `exit=3` ⇒ 判「未验证」；
   绿对照必须仍然绿；真红仍要红。
2. **`not_run` 非空 ⇒ 整趟不许 `ok=True`**（健康 payload 的键集合不许被顺手改掉）。
3. **三把尺子说同一句话**：同一份 payload 交给三处判据，结论必须一致。
4. **跨机复用不许冒充本机真跑**：`reused` 条目必须能追到 `host`；判不出来源就红。
5. 反向证据（「把产品改回老写法 ⇒ 对应钉子必红」）记在卡规格的「反向验证」节。

## 怎么跑（不跑真门禁、不写真 `gates/last.json`、不碰 git）

    python -X utf8 -m pytest tests/test_no_vacuous_pass.py -q --no-cov -p no:cacheprovider

## 边界（如实写）

- 这里只判**纯函数**（`gates_ok` / `gate_verdict.judge` / `validate_cloud_return` /
  `recent_full_ok` / `reuse_host_problem`）。整趟 `main()` 的退出码由
  `tests/test_gate_docs.py`（`--only` ⇒ 3）与 `gates/last.json` 的实跑读数覆盖。
- 真云机没在这颗钉子里跑（主控统一跑）；这里钉的是「判据怎么读产物」，不是「云机通不通」。
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import gate_pool as gp  # noqa: E402
import gate_verdict as gv  # noqa: E402

HERE = socket.gethostname().strip().lower()
OTHER_HOST = "cloud-elsewhere"


def _load(name: str, relpath: str):
    target = ROOT / relpath
    spec = importlib.util.spec_from_file_location(name, target)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


rg = _load("run_gates_under_test", "scripts/run_gates.py")


def _nightly():
    return _load("wb_nightly_under_test", "tools/wb_nightly.py")


# ---------------------------------------------------------------- 夹具
def _payload(
    gates: list[dict[str, Any]],
    *,
    not_run: list[str] | None = None,
    host: str = "thisbox",
    ok: bool = True,
    reused: dict[str, str] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {"rev": "abc1234", "ok": ok, "host": host, "gates": gates}
    if not_run is not None:
        out["not_run"] = not_run
    if reused is not None:
        out["reused"] = reused
    return out


def _e62_shape() -> dict[str, Any]:
    """卡 E62 那趟的活标本（等价重造，不写死 worktree 路径）：`ok=True` 且 `not_run` 非空。"""
    return {
        "rev": "e62beef",
        "host": "thisbox",
        "ok": True,
        "gates": [
            {"name": "ruff", "exit_code": 0, "blocking": True},
            {
                "name": "render",
                "exit_code": 3,
                "blocking": False,
                "status": "NOT RUN",
                "summary": "环境里没有 node：未验证，不算通过",
            },
        ],
        "not_run": ["render"],
    }


def _local_ok(payload: dict[str, Any]) -> bool:
    """本地尺子的成品结论 —— `main()` 就是这么算的：`gates_ok(门)` 且复核后的 `ok`。"""
    return bool(rg.gates_ok(payload.get("gates") or [])) and rg._apply_vacuous_verdict(
        dict(payload), True
    ).get("ok") is True


def _cloud_problems(payload: dict[str, Any], doors: list[str]) -> list[str]:
    return gp.validate_cloud_return(
        payload,
        expected_rev=str(payload.get("rev") or ""),
        expected_doors=doors,
        pytest_passed=100,
        pytest_total=100,
        workspace_clean=True,
        expect_host=str(payload.get("host") or ""),
    )


# ---------------------------------------------------------------- ① 零门必须红
def test_zero_doors_is_not_a_pass() -> None:
    """★ `gates_ok([])` 必须是 False —— `all()` 对空列表返 True 是数学性质，不是判据。"""
    assert rg.gates_ok([]) is False, "零门被判成通过：`all()` 的空表真值又回来了（卡 E63 判据 1）"


def test_all_non_blocking_doors_is_unverified() -> None:
    """有门但全是不阻断的 `exit=3`（NOT RUN）⇒ 什么都没证明，不许算通过。"""
    only_not_run = [{"name": "render", "exit_code": 3, "blocking": False, "status": "NOT RUN"}]
    assert rg.gates_ok(only_not_run) is False, "全是 NOT RUN 也被判通过了（卡 E63 判据 1）"
    verdict = gv.judge(_payload(only_not_run, not_run=["render"]))
    assert verdict.ok is False
    assert verdict.state == gv.UNVERIFIED, verdict.state


def test_green_control_is_still_green() -> None:
    """绿对照：一道真跑过并退 0 的阻断门 ⇒ 仍然绿（判据不许把绿灯也咬掉）。"""
    assert rg.gates_ok([{"name": "ruff", "exit_code": 0}]) is True
    payload = _payload([{"name": "ruff", "exit_code": 0}], not_run=[])
    assert gv.judge(payload).ok is True
    assert _local_ok(payload) is True


def test_a_real_red_is_still_red() -> None:
    """真红仍要红（且不是被「未验证」洗成别的状态）。"""
    assert rg.gates_ok([{"name": "ruff", "exit_code": 1}]) is False
    verdict = gv.judge(_payload([{"name": "ruff", "exit_code": 1}], not_run=[]))
    assert verdict.ok is False
    assert verdict.state == gv.RED, verdict.state


# ---------------------------------------------------------------- ② not_run ≠ 通过
def test_ok_true_with_not_run_is_rewritten_to_false() -> None:
    """★ 产物不许自相矛盾：`ok=True` 与 `not_run=['render']` 并存 ⇒ `ok` 必须被改成 False。"""
    fixed = rg._apply_vacuous_verdict(_e62_shape(), True)
    assert fixed["ok"] is False, "`ok=True` 和 `not_run` 并存还落了盘（卡 E63 判据 2）"
    assert not (fixed["ok"] and fixed["not_run"])
    block = fixed["verdict"]
    assert block["state"] == gv.UNVERIFIED, block
    assert any("render" in one for one in block["problems"]), block["problems"]


def test_healthy_payload_shape_is_untouched() -> None:
    """健康的一趟**不加键**：`last.json` 的形状不许被这张卡顺手改掉。"""
    healthy = _payload([{"name": "ruff", "exit_code": 0}], not_run=[])
    out = rg._apply_vacuous_verdict(dict(healthy), True)
    assert out["ok"] is True
    assert "verdict" not in out, "绿的一趟也被塞了 verdict 块（形状变了）"


def test_red_run_is_not_rewritten_into_unverified() -> None:
    """已经是红的（门真红）就不该被写成「未验证」—— 别把红洗成中性。"""
    red = _payload([{"name": "ruff", "exit_code": 1}], not_run=[], ok=False)
    out = rg._apply_vacuous_verdict(dict(red), False)
    assert out["ok"] is False
    assert "verdict" not in out


def test_a_not_run_row_inside_gates_is_unverified() -> None:
    """★ 判据 4 前半（现网真数据的形状）：`not_run` 是**空的**，但**门行自己**写着 NOT RUN。

    `gates/last.json` 里 `web_live` 就是 `exit_code=3 / blocking=False /
    status='NOT RUN'`、自己的 note 写着「这一层没有验证，不算通过」
    —— 「有没有验证」被 `not_run` 与 `gates[].status` 各记一半，只看一边就漏。
    """
    payload = _payload(
        [
            {"name": "ruff", "exit_code": 0},
            {"name": "web_live", "exit_code": 3, "blocking": False, "status": "NOT RUN"},
        ],
        not_run=[],
    )
    verdict = gv.judge(payload)
    assert verdict.ok is False, "门行写着 NOT RUN 还被判通过（判据 4 前半）"
    assert verdict.state == gv.UNVERIFIED, verdict
    assert any("web_live" in one for one in verdict.problems), verdict.problems
    # 反向：同一形状里那道门真绿时，不许被这条判据误伤
    green = _payload([{"name": "ruff", "exit_code": 0}], not_run=[])
    assert gv.judge(green).ok is True


# ---------------------------------------------------------------- ③ 三把尺子
_AGREE_CASES: list[tuple[str, dict[str, Any], list[str], bool]] = [
    (
        "绿：一道真跑过并退 0 的门",
        _payload([{"name": "ruff", "exit_code": 0}], not_run=[]),
        ["ruff"],
        True,
    ),
    ("零门：payload 里一条 gate 记录都没有", _payload([], not_run=[]), ["ruff"], False),
    (
        "半趟：跑了 ruff，render 没跑（not_run）",
        _payload(
            [
                {"name": "ruff", "exit_code": 0},
                {"name": "render", "exit_code": 3, "blocking": False},
            ],
            not_run=["render"],
        ),
        ["ruff", "render"],
        False,
    ),
    (
        "全是 NOT RUN：一条阻断门都没有",
        _payload([{"name": "render", "exit_code": 3, "blocking": False}], not_run=["render"]),
        ["render"],
        False,
    ),
    (
        "真红：阻断门 exit=1",
        _payload([{"name": "ruff", "exit_code": 1}], not_run=[]),
        ["ruff"],
        False,
    ),
]


@pytest.mark.parametrize(
    "label,payload,doors,green", _AGREE_CASES, ids=[c[0] for c in _AGREE_CASES]
)
def test_three_rulers_agree(
    label: str, payload: dict[str, Any], doors: list[str], green: bool
) -> None:
    """★ 同一份 payload：本地 / 云机 / 落地链三处必须说同一句话（不一致就是病）。"""
    local = _local_ok(payload)
    cloud = _cloud_problems(payload, doors)
    landing = gv.judge(payload, check_host=False).ok
    assert local is green, f"[{label}] 本地尺子说 {local}（应为 {green}）"
    assert (not cloud) is green, f"[{label}] 云机尺子说 {cloud}"
    assert landing is green, f"[{label}] 落地链尺子说 {landing}（应为 {green}）"


def test_three_rulers_all_call_the_shared_judge() -> None:
    """防漂移：三处都必须调**同一份**判据（谁又自己写一份，这条就红）。"""
    for rel in ("scripts/run_gates.py", "tools/gate_pool.py", "tools/pool/landing.py"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "gate_verdict" in text, f"{rel} 没接共用判据（卡 E63 判据 3）"
    assert "gate_verdict.judge(" in (ROOT / "tools/gate_pool.py").read_text(encoding="utf-8")
    assert "gate_verdict.judge(" in (ROOT / "tools/pool/landing.py").read_text(encoding="utf-8")


def test_landing_rejudges_the_payload_after_rc_zero() -> None:
    """落地链不许只看 `rc`：`rc == 0` 之后必须再读产物判一遍（卡 E63 判据 3/4）。"""
    text = (ROOT / "tools/pool/landing.py").read_text(encoding="utf-8")
    at = text.find("if rc != 0:")
    assert at != -1, "落地链的门禁段变了形状，这条钉子要跟着改"
    after = text[at:]
    assert "gate_verdict.judge(" in after, "rc == 0 之后没有重判 payload（只看退出码）"
    assert 'wt / "gates" / "last.json"' in after, "没读 gates/last.json"


# ---------------------------------------------------------------- ④ 复用来源
def test_reused_row_without_host_is_red() -> None:
    """`reused: true` 但没写来源宿主 ⇒ 判不出来源 ⇒ 红（fail closed）。"""
    payload = _payload(
        [{"name": "render", "exit_code": 0, "reused": True, "inputs_hash": "aaa"}],
        not_run=[],
        reused={"render": "aaa"},
    )
    verdict = gv.judge(payload, check_host=False)
    assert verdict.ok is False, "复用条目没有 host 也被当成通过（卡 E63 判据 4）"
    assert any("render" in one for one in verdict.problems), verdict.problems


def test_reused_row_from_another_host_is_red() -> None:
    """复用的判定来自别的宿主 ⇒ 不许算本机通过。"""
    payload = _payload(
        [{"name": "render", "exit_code": 0, "reused": True, "host": OTHER_HOST}],
        not_run=[],
        host="thisbox",
        reused={"render": "aaa"},
    )
    verdict = gv.judge(payload, check_host=False)
    assert verdict.ok is False, "跨机复用冒充本机真跑（卡 E63 判据 4）"
    assert any(OTHER_HOST in one for one in verdict.problems), verdict.problems


def test_reused_row_from_this_host_is_ok() -> None:
    """本机自己的复用照旧放行（判据不许把复用一棍子打死）。"""
    payload = _payload(
        [{"name": "render", "exit_code": 0, "reused": True, "host": "thisbox"}],
        not_run=[],
        host="thisbox",
        reused={"render": "aaa"},
    )
    assert gv.judge(payload, check_host=False).ok is True


def test_run_gates_refuses_a_reuse_record_without_a_host() -> None:
    """老 `gates/reuse.json`（没有 `host`）不许复用 —— 升级后第一趟宁可真跑。"""
    here = rg.socket.gethostname()
    assert rg.reuse_host_problem({"hash": "x", "verdict": "pass"}, here) is not None
    assert rg.reuse_host_problem({"hash": "x", "host": OTHER_HOST}, here) is not None
    assert rg.reuse_host_problem({"hash": "x", "host": here}, here) is None


def test_payload_host_must_match_when_it_is_known() -> None:
    """产物自称是哪台机器跑的：本机路径下对不上号 ⇒ 红。"""
    payload = _payload([{"name": "ruff", "exit_code": 0}], not_run=[], host=OTHER_HOST)
    assert gv.judge(payload, expect_host=socket.gethostname()).ok is False
    ok_payload = _payload([{"name": "ruff", "exit_code": 0}], not_run=[], host=socket.gethostname())
    assert gv.judge(ok_payload, expect_host=socket.gethostname()).ok is True


# ---------------------------------------------------------------- ⑤ 闸二：夜间记录要交代来源
def _git(root: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def _repo(root: Path) -> tuple[str, str]:
    """造一棵真 git 树（闸二现在要核 rev 与 tree，合成目录不够用了）。"""
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "-c", "user.email=t@e63", "-c", "user.name=E63", "commit", "-q", "--allow-empty",
         "-m", "e63 fixture")
    return _git(root, "rev-parse", "--short", "HEAD"), _git(root, "rev-parse", "--show-toplevel")


def _nightly_record(
    root: Path, *, at: dt.datetime, ok: bool, rev: str, tree: str
) -> None:
    nightly = _nightly()
    record: dict[str, Any] = {
        "at": at.isoformat(timespec="seconds"),
        "record": f"nightly-{at.strftime('%Y%m%d-%H%M%S')}.json",
        "rev": rev,
        "ok": ok,
        "exit_code": 0 if ok else 1,
        "seconds": 1.0,
        "worktree": "",
        "log": "",
        "note": "测试合成",
    }
    if tree:
        record["tree"] = tree
    nightly.write_record(record, root)


def test_nightly_fresh_same_rev_same_tree_passes(tmp_path: Path) -> None:
    """绿对照：rev 等于当前 HEAD + 本树 + 刚跑的 `at` ⇒ 放行。"""
    nightly = _nightly()
    rev, tree = _repo(tmp_path)
    now = dt.datetime(2026, 10, 25, 12, 0, 0)
    _nightly_record(tmp_path, at=now - dt.timedelta(hours=1), ok=True, rev=rev, tree=tree)
    ok, why = nightly.recent_full_ok(root=tmp_path, now=now)
    assert ok is True, why


def test_nightly_rejects_an_old_rev(tmp_path: Path) -> None:
    """★ 旧提交上跑绿的记录不许给今天这棵新树开绿灯。"""
    nightly = _nightly()
    rev, tree = _repo(tmp_path)
    now = dt.datetime(2026, 10, 25, 12, 0, 0)
    old = rev[::-1]  # 同一棵树上另一个 rev
    _nightly_record(tmp_path, at=now - dt.timedelta(hours=1), ok=True, rev=old, tree=tree)
    ok, why = nightly.recent_full_ok(root=tmp_path, now=now)
    assert ok is False, "跨 rev 的绿记录被当成今天的全量（卡 E63 判据 4）"
    assert "rev 对不上" in why, why


def test_nightly_rejects_a_record_without_rev(tmp_path: Path) -> None:
    """记录里没有 rev ⇒ 判不出来源 ⇒ 当没有记录（fail closed，不许猜）。"""
    nightly = _nightly()
    _rev, tree = _repo(tmp_path)
    now = dt.datetime(2026, 10, 25, 12, 0, 0)
    _nightly_record(tmp_path, at=now - dt.timedelta(hours=1), ok=True, rev="", tree=tree)
    ok, why = nightly.recent_full_ok(root=tmp_path, now=now)
    assert ok is False, "没有 rev 的记录被当成绿（卡 E63 判据 4：fail closed）"
    assert "rev" in why, why


def test_nightly_rejects_another_tree(tmp_path: Path) -> None:
    """别的树跑出来的全量记录不算本树全量（跨树/跨机冒充）。"""
    nightly = _nightly()
    rev, _tree = _repo(tmp_path / "this")
    other = tmp_path / "other"
    other.mkdir()
    now = dt.datetime(2026, 10, 25, 12, 0, 0)
    _nightly_record(tmp_path / "this", at=now - dt.timedelta(hours=1), ok=True, rev=rev,
                    tree=str(other))
    ok, why = nightly.recent_full_ok(root=tmp_path / "this", now=now)
    assert ok is False, "别的树的全量记录放行了本树（卡 E63 判据 4）"
    assert "树" in why, why


def test_nightly_rejects_a_record_without_tree(tmp_path: Path) -> None:
    """记录里没有 tree ⇒ 判不出是哪棵树跑的 ⇒ 当没有记录。"""
    nightly = _nightly()
    rev, _tree = _repo(tmp_path)
    now = dt.datetime(2026, 10, 25, 12, 0, 0)
    _nightly_record(tmp_path, at=now - dt.timedelta(hours=1), ok=True, rev=rev, tree="")
    ok, why = nightly.recent_full_ok(root=tmp_path, now=now)
    assert ok is False, "没有 tree 的记录被当成绿（卡 E63 判据 4）"
    assert "tree" in why, why


def test_nightly_still_reports_the_old_reasons(tmp_path: Path) -> None:
    """老的四条原因（没有记录 / 时间戳读不懂 / 红的 / 超过 24h）不许被这张卡改味。

    三个场景各用**各自的一棵树**：`latest_record()` 按 `at` 取最大，同一棵树里叠三份记录
    只会读到最新的那份（第一版就踩了这个坑，读到的是红的而不是 30 小时前那份）。
    """
    nightly = _nightly()
    now = dt.datetime(2026, 10, 25, 12, 0, 0)

    empty = tmp_path / "empty"
    _repo(empty)
    ok, why = nightly.recent_full_ok(root=empty, now=now)
    assert ok is False and "夜间" in why, why

    red_root = tmp_path / "red"
    rev, tree = _repo(red_root)
    _nightly_record(red_root, at=now - dt.timedelta(hours=1), ok=False, rev=rev, tree=tree)
    ok, why = nightly.recent_full_ok(root=red_root, now=now)
    assert ok is False and "红的" in why, why

    stale = tmp_path / "stale"
    rev2, tree2 = _repo(stale)
    _nightly_record(stale, at=now - dt.timedelta(hours=30), ok=True, rev=rev2, tree=tree2)
    ok, why = nightly.recent_full_ok(root=stale, now=now)
    assert ok is False and "30" in why, why
