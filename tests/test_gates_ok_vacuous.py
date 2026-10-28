"""卡 E63（T-AG521）：判不出来的时候不许说没事 —— 六条判据的钉子。

判据 1：`gates_ok([])` 必须 False（配绿对照，否则写成 `return False` 也能过）。
判据 2：**真路径**上「一道门都没跑」必须退非零（本卡主判据 —— 只钉单元函数不够）。
判据 3：三把尺子（`run_gates` / `gate_pool` / `wb_verify`）对同一份产物必须说同一句话，
        而且**判据本体只许一份**（`tools/gate_verdict.judge`）。
判据 4：`exit_code == 3` / `status == "NOT RUN"` 不算通过。
判据 5：金样本绑机器 —— 别的机器记 `EXCLUDED`：不跑、不说通过、理由进产物。
判据 6：排除是豁免，只有 `GOLDEN_PINNED` 里声明过的门才许，且理由不许空。

历史（这张卡为什么要存在）：
  · `gates_ok([])` 曾返回 `True`（`all()` 对空集为真）⇒ 一道门都没跑也算通过；
  · `run_gates.py --fast` 零门时退 0；`render_check.mjs --only <零匹配>` 退 0（卡 E62 修）；
  · `web_live` 缺 node 时记 `not_run`（`exit_code=3`、`blocking=False`），整趟却 `ok=True`。
  · `gates/render/*.txt` 是**某台机器显示栈**渲出来的：云机装了 node 之后 45 份里 39 份
    不一致，差异全是字形度量 —— 这道门跨机跑本身没有意义，以前它要么静默不算、要么红。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _d in ("tools", "scripts"):
    if str(ROOT / _d) not in sys.path:
        sys.path.insert(0, str(ROOT / _d))

import gate_verdict as gv  # noqa: E402 —— 判据本体（三把尺子共用）
import run_gates as rg  # noqa: E402

CAPTURE_REL = "gates/render/CAPTURED_ON.json"


# ---------------------------------------------------------------- 工具


def _payload(gates: list[dict[str, object]], **extra: object) -> dict[str, object]:
    """一份最小可判的 `last.json`。默认「本机跑的、真跑了且通过」，各用例按需破坏。

    ★ `host` 必须给：`judge()` 的来源判据（红）是「没有 host 就证明不了是哪台机器跑的」。
    """
    base: dict[str, object] = {
        "ok": True,
        "rev": "0" * 40,
        "host": rg.platform.node(),
        "gates": gates,
        "not_run": [],
        "reused": {},
    }
    base.update(extra)
    return base


def _door(name: str, code: int = 0, *, blocking: bool = True,
          status: str | None = None, **extra: object) -> dict[str, object]:
    row: dict[str, object] = {"name": name, "exit_code": code, "seconds": 1,
                              "blocking": blocking, "summary": "…"}
    if status is not None:
        row["status"] = status
    row.update(extra)
    return row


def _reasons(payload: dict[str, object]) -> tuple[bool, tuple[str, ...]]:
    v = gv.judge(payload)
    return v.ok, v.problems


# ---------------------------------------------------------------- 判据 1：空集不是「全过」


def test_gates_ok_of_an_empty_list_is_false() -> None:
    """判据 1：`all()` 对空集为真 —— 这正是「一道门都没跑也算通过」的病根。"""
    assert rg.gates_ok([]) is False


def test_gates_ok_lets_a_passing_blocking_door_through() -> None:
    """绿对照：改成 `return False` 也能让上一条过，所以必须有这条。"""
    assert rg.gates_ok([_door("ruff", 0)]) is True


def test_gates_ok_ignores_a_non_blocking_nonzero_door() -> None:
    """非阻断门的非零退出不阻断整趟（T-AG518 的口径），但「一道阻断门都没有」仍然红。"""
    assert rg.gates_ok([_door("ruff", 0), _door("web_live", 3, blocking=False)]) is True
    assert rg.gates_ok([_door("web_live", 3, blocking=False)]) is False


# ---------------------------------------------------------------- 判据 2：真路径上零门必须退非零


def _path_without_node() -> str:
    """PATH 里所有「目录下真有 node」的段都摘掉。"""
    keep: list[str] = []
    for part in os.environ.get("PATH", "").split(os.pathsep):
        if not part:
            continue
        if (Path(part) / ("node.exe" if os.name == "nt" else "node")).exists():
            continue
        if "nodejs" in part.lower() or Path(part).name.lower() == "node":
            continue
        keep.append(part)
    return os.pathsep.join(keep)


def test_zero_jobs_is_never_green_through_main(monkeypatch: pytest.MonkeyPatch) -> None:
    """真·零门：`build_jobs()` 返回空 ⇒ `main()` 必须退 3（未验证），不许退 0。

    ★ 2026-10-28 对抗复核：`--only` 会把没跑的门塞进 `not_run`，于是它**无论零门逻辑
      坏没坏都退 3** —— 挡它的是另一条判据。这里把「一道门都没选出来」直接喂进
      `main()`，钉的才是零门本身。
    """
    import run_gates as rg

    monkeypatch.setattr(rg, "build_jobs", lambda *a, **kw: [])
    monkeypatch.setattr(rg.sys, "argv", ["run_gates.py", "--no-write"])
    rc = rg.main()
    assert rc == 3, f"零门必须退 3（未验证），实际 {rc}"

def test_only_a_node_door_without_node_exits_nonzero() -> None:
    """判据 2（主判据）：`--only render` + 环境没 node ⇒ **一道门都没跑** ⇒ 必须退非零。

    ★ 为什么用 `--no-write`：`--only` 会**覆盖真的 `gates/last.json`**，测试拿它钉退出码
      就会顺手把提交闸的产物改成「1 门真跑 + 其余 not_run」。
    ★ 这条路会随机器给出两种形状，两种都必须是红：
      采集机上 → `render` 记 `NOT RUN`（没有 node）；别的机器上 → `render` 记 `EXCLUDED`。
    """
    env = dict(os.environ)
    env["PATH"] = _path_without_node()
    env["TF_GATE_PORT_BASE"] = "9790"  # 换段：`--only render` 会先清本树端口段里的遗留
    probe = subprocess.run(["where", "node"] if os.name == "nt"
                           else ["sh", "-c", "command -v node"],
                           env=env, capture_output=True)
    if probe.returncode == 0:
        pytest.skip("裁不掉 node —— 这条钉子钉不了")

    proc = subprocess.run(
        [sys.executable, "-X", "utf8", str(ROOT / "scripts" / "run_gates.py"),
         "--only", "render", "--no-write",
         # ★ 不许走复用缓存：复用会把「上一次真跑过」的绿判定端上来，
         #   这条钉子就量不到「没有 node 时这道门怎么记账」。
         "--no-reuse"],
        cwd=ROOT, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=900, check=False,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    assert proc.returncode != 0, f"零门却退 0（这正是本卡的病）：\n{out[-3000:]}"
    # 产物必须**自己说出**「这道门没验证」，而不是只在别处红一下就算数。
    assert "render" in out, f"产物没提 render：\n{out[-3000:]}"
    assert any(w in out for w in ("NOT RUN", "EXCLUDED", "跳过", "not_run", "未验证")), (
        f"产物没说清 render 没跑成：\n{out[-3000:]}"
    )
    assert "通过 ✅" not in out, f"零门却打印了「通过」：\n{out[-3000:]}"


def test_no_write_does_not_touch_the_gate_product() -> None:
    """`--no-write` 必须真的不写盘 —— 否则上一条钉子会把提交闸的产物踩掉。"""
    last = ROOT / "gates" / "last.json"
    before = last.read_bytes() if last.exists() else b""
    env = dict(os.environ)
    env["TF_GATE_PORT_BASE"] = "9791"
    subprocess.run(
        [sys.executable, "-X", "utf8", str(ROOT / "scripts" / "run_gates.py"),
         "--only", "acceptance", "--no-write"],
        cwd=ROOT, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=900, check=False,
    )
    after = last.read_bytes() if last.exists() else b""
    assert after == before, "`--no-write` 还是把 gates/last.json 改了"


# ---------------------------------------------------------------- 判据 3：判据只许一份


def test_the_judgment_lives_in_exactly_one_place() -> None:
    """判据 3：`run_gates` 不许再自带一份 `payload_verdict`（那份曾判出另一个结论）。"""
    assert not hasattr(rg, "payload_verdict"), (
        "`run_gates.payload_verdict` 又长回来了 —— 判据只许在 tools/gate_verdict.judge 一份"
    )
    assert callable(gv.judge)


# ---------------------------------------------------------------- 判据 4：NOT RUN 不是 PASS


def test_a_payload_with_no_doors_is_red() -> None:
    ok, reasons = _reasons(_payload([]))
    assert ok is False
    assert any("零门" in r for r in reasons), reasons


def test_a_payload_whose_doors_are_all_not_run_is_red() -> None:
    ok, reasons = _reasons(
        _payload([_door("web_live", 3, blocking=False, status="NOT RUN")])
    )
    assert ok is False
    assert any("零阻断门" in r or "未验证" in r for r in reasons), reasons


def test_a_single_not_run_door_is_not_a_pass() -> None:
    """判据 4：`exit_code == 3` / `status == "NOT RUN"` —— 跑了但没验证。"""
    ok, reasons = _reasons(
        _payload([_door("ruff", 0), _door("web_live", 3, blocking=False, status="NOT RUN")])
    )
    assert ok is False
    assert any("未验证" in r for r in reasons), reasons


def test_doors_that_all_started_and_passed_are_green() -> None:
    """绿对照：真的都跑了且都过 ⇒ 通过。"""
    assert _reasons(_payload([_door("ruff", 0), _door("mypy", 0)])) == (True, ())


def test_a_door_that_never_started_is_red() -> None:
    ok, reasons = _reasons(_payload([_door("ruff", 0)], not_run=["render"]))
    assert ok is False
    assert any("render" in r for r in reasons), reasons


# ---------------------------------------------------------------- 判据 5：来源要说得出是哪台机器


def test_a_product_without_a_host_is_red() -> None:
    """判据 5：产物说得出是哪台机器跑的吗？说不出来 ⇒ **不许算通过**（fail closed）。

    ★ 这条是反向验证撕出来的洞（`gates/diag/_rev_E63.py` 的 M3）：把
      `gate_verdict.host_problems()` 改成恒不报，**原来一条钉子都不红** —— 因为夹具都
      老老实实写了 `host`，没人钉「没写会怎样」。判据没有反向钉子，就等于没判据。
    """
    payload = _payload([_door("ruff", 0), _door("mypy", 0)])
    payload.pop("host")
    ok, reasons = _reasons(payload)
    assert ok is False, "没有 host 的产物居然算通过了"
    assert any("host" in r for r in reasons), reasons


def test_a_product_from_another_host_is_red() -> None:
    """判据 5 的另一半：`expect_host` / `not_host` 给了就必须对得上。"""
    me = rg.platform.node()
    payload = _payload([_door("ruff", 0)], host="some-other-box")
    assert gv.judge(payload, expect_host=me).ok is False
    assert gv.judge(payload, not_host=me).ok is True, "not_host 只该拦「就是这台」"
    # ★ 2026-10-28 对抗复核：上面这条恒真 —— payload 的 host 本来就不是 me，
    #   `not_host` 分支根本没被触发。补一条真正该红的：host 就是本机 + not_host 本机。
    mine = _payload([_door("ruff", 0)], host=me)
    assert gv.judge(mine, not_host=me).ok is False, "not_host 命中却没红"


# ---------------------------------------------------------------- 判据 6：排除不伪装成红


def test_excluded_rows_shape() -> None:
    """判据 5：`EXCLUDED` 行**不伪装成红**（exit 0 / 非阻断），理由必须写进产物。"""
    rows = rg.excluded_rows({"render": "金样本采集自别的机器"})
    assert len(rows) == 1
    row = rows[0]
    assert row["name"] == "render"
    assert row["status"] == "EXCLUDED"
    assert row["exit_code"] == 0
    assert row["blocking"] is False
    assert row["excluded_reason"] == "金样本采集自别的机器"
    assert "金样本采集自别的机器" in str(row["summary"])


def test_a_declared_gate_excluded_with_a_reason_is_not_red() -> None:
    """判据 5 的绿侧：声明过的门 + 有理由 ⇒ 整趟照样能过（排除不是红）。"""
    rows = [*rg.excluded_rows({"render": "金样本采集自别的机器"}), _door("ruff", 0)]
    assert _reasons(_payload(rows, excluded={"render": "金样本采集自别的机器"})) == (True, ())


def test_golden_host_reason_is_none_on_the_capture_host() -> None:
    """判据 5 的绿对照：**采集机本机**必须真跑（返回 None），否则这机制等于把所有机器都关掉。"""
    rec = json.loads((ROOT / CAPTURE_REL).read_text(encoding="utf-8"))
    if str(rec.get("host") or "") != rg.platform.node():
        pytest.skip("本机不是金样本采集机 —— 这条绿对照只能在采集机上跑")
    assert rg.golden_host_reason("render") is None


def test_golden_host_reason_names_the_other_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """判据 5：不是采集机 ⇒ 返回**人话理由**，且理由里要点名两台机器。"""
    monkeypatch.setattr(rg.platform, "node", lambda: "NOT-THE-CAPTURE-HOST")
    why = rg.golden_host_reason("render")
    assert why, "在非采集机上必须给出理由（返回 None 就等于静默跳过）"
    assert "NOT-THE-CAPTURE-HOST" in why, why


def test_golden_host_reason_when_the_record_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """判据 5：读不到采集记录 ⇒ **按未验证处理**（返回理由），不许因为读不出来就跳过。"""
    monkeypatch.setattr(rg, "ROOT", tmp_path)
    why = rg.golden_host_reason("render")
    assert why and "读不到" in why, why


def test_golden_host_reason_ignores_gates_that_are_not_pinned() -> None:
    """判据 5 的边界：没绑金样本的门（`pytest` / `ui_flow`）永远返回 None。"""
    for name in ("pytest", "ui_flow", "web_live"):
        assert rg.golden_host_reason(name) is None


def test_the_pin_table_is_shared_by_all_rulers() -> None:
    """判据 3 的补丁：豁免表只有一张 —— `run_gates` 用的是 `gate_verdict` 里那张。"""
    assert rg.GOLDEN_PINNED is gv.GOLDEN_PINNED
    assert gv.GOLDEN_PINNED == {"render": CAPTURE_REL}


# ---------------------------------------------------------------- 判据 6：排除必须念给人听


def test_an_undeclared_gate_may_not_be_excluded() -> None:
    """判据 6：不在 `GOLDEN_PINNED` 里的门自报排除 ⇒ 红（否则什么红都能洗成绿）。"""
    rows = [
        _door("ui_flow", 0, blocking=False, status="EXCLUDED", excluded_reason="我跑不动"),
        _door("ruff", 0),
    ]
    ok, reasons = _reasons(_payload(rows))
    assert ok is False
    assert any("不许自报豁免" in r for r in reasons), reasons


def test_excluded_without_a_reason_is_red() -> None:
    """判据 6：排除必须能念给人听 —— 理由空 ⇒ 红。"""
    rows = [_door("render", 0, blocking=False, status="EXCLUDED"), _door("ruff", 0)]
    ok, reasons = _reasons(_payload(rows))
    assert ok is False
    assert any("没写理由" in r for r in reasons), reasons


def test_excluded_cannot_be_both_exempt_and_blocking() -> None:
    """判据 6：一条行不许两副面孔（既豁免又阻断）。"""
    rows = [
        _door("render", 0, blocking=True, status="EXCLUDED", excluded_reason="别的机器"),
        _door("ruff", 0),
    ]
    ok, reasons = _reasons(_payload(rows))
    assert ok is False
    assert any("两副面孔" in r for r in reasons), reasons


def test_excluded_with_a_nonzero_exit_code_is_red() -> None:
    """判据 6：豁免行不许带非零退出码（那是「既没跑又红了」的自相矛盾）。"""
    rows = [
        _door("render", 1, blocking=False, status="EXCLUDED", excluded_reason="别的机器"),
        _door("ruff", 0),
    ]
    ok, reasons = _reasons(_payload(rows))
    assert ok is False
    assert any("非零退出码" in r for r in reasons), reasons
