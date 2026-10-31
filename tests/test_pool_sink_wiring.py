"""卡 A351（`T-AG563`）：sink 沉底接进派活器 —— 429 换模型那一段的钉子。

判据 7 条全在这里钉住（每条都钉**行为**或**源码事实**，不钉「写得像不像」）：
  ① 沉不沉只问 `sink.should_sink()`，调用侧不许自带 `kind == "限流"` 私有判据；
  ② `routing` 是本仓没有的配置 ⇒ 具名模块级常量 `SINK_ROUTING = "order"`；
  ③ 只沉在「探针仍挂」那一支（探针通了说明已经好了，不该沉）；
  ④ key 是 `sink.sunk_at()` 认的两段式 `<account>/<model>`，账号段用**稳定 id**；
  ⑤ 没给 `--account` 时**仍然沉**（`/<model>`），且读得回来 —— 不许静默跳过；
  ⑥ 换模型前扫**整条尾巴**（含 `nxt` 自己）：全沉 ⇒ 落进既有停路（退出码 7）；
  ⑦ `tools/pool/sink.py` 八个公开函数的签名与行为一字不动。

★ 一律用 `TF_POOL_SINK` 把状态指到 `tmp_path` —— `pool_sink.sink_path()` 不认 `wd.ROOT`，
  不隔离就会往真仓 `gates/diag/pool-sink.json` 里写（那是本机状态，但测试不该碰它）。
"""

from __future__ import annotations

import ast
import inspect
import json
import sys
from pathlib import Path

import pytest
import test_wb_dispatch as twd

from tools import wb_session as wb_session

ROOT = Path(__file__).resolve().parent.parent
# ★ 必须复用隔壁模块那个 `wd` **对象**（`import wb_dispatch` 拿到的是同一份，
#   `from tools import wb_dispatch` 会执行出第二个模块 —— 夹具 patch 的 ROOT 就落不到它身上）。
wd = twd.wd
#: 调用侧真正在用的那个 sink 模块对象（`wd` 里 `from pool import sink as pool_sink`）。
pool_sink = wd.pool_sink

#: 沙箱夹具与三份 helper 都在隔壁模块里（同一套「像仓库的临时根」，别再造一份）。
sandbox = twd.sandbox

_QUOTA_LINE = twd._quota_result_event(with_reset=True)
#: 「余额耗尽」形状：没有「将在 … 重置」⇒ `quota_error()` 判成余额耗尽（不是限流）。
_BROKE_LINE = json.dumps({"type": "result", "subtype": "error_during_execution",
                          "result": "额度已用尽", "errors": None}, ensure_ascii=False)

_EIGHT = ("sink", "sunk_at", "unsink", "unsink_all", "sink_order", "sink_last",
          "sinks", "should_sink")


@pytest.fixture(autouse=True)
def isolated_session_ledger(tmp_path: Path, monkeypatch) -> Path:
    """照隔壁模块同款隔离：`wd.main()` 的 `wb_session.claim()` 不许写**真**账本。"""
    ledger = tmp_path / "gates" / "diag" / "session-leases.json"
    monkeypatch.setattr(wb_session, "LEDGER", ledger)
    return ledger


@pytest.fixture()
def sink_state(tmp_path: Path, monkeypatch) -> Path:
    """把 sink 状态文件隔离到临时目录（判据 7 的「不在真仓留状态」由它兜住）。"""
    state = tmp_path / "pool-sink.json"
    monkeypatch.setenv("TF_POOL_SINK", str(state))
    return state


def _rounds(calls: list[list[str]], first: str = _QUOTA_LINE,
            rest: list[str] | None = None):
    """假 runner：第 1 轮写 `first`（默认限流 429），之后写 `rest`（默认一组成功事件）。"""
    def run(cmd, log, errlog, **kwargs):          # noqa: ANN001, ANN202
        calls.append(list(cmd))
        log.parent.mkdir(parents=True, exist_ok=True)
        body = first if len(calls) == 1 else "\n".join(rest or twd.EVENTS)
        log.write_text(body + "\n", encoding="utf-8")
        errlog.write_text("", encoding="utf-8")
        return 0, "", "", f"sid-{len(calls)}"
    return run


def _sunk_keys(state: Path) -> dict[str, dict]:
    if not state.exists():
        return {}
    return json.loads(state.read_text(encoding="utf-8"))["m"]


def _models(calls: list[list[str]]) -> list[str]:
    return [c[c.index("--model") + 1] for c in calls]


def _three_model_registry(tmp_path: Path) -> Path:
    """三模型链（真仓只有两个）：判据 6 要「尾巴里还有第三个没沉」，两个模型分不出来。"""
    path = tmp_path / "model-registry.toml"
    rows: list[str] = []
    for alias, default in (("alpha", True), ("beta", False), ("gamma", False)):
        rows += ["[[model]]", f'alias = "{alias}"', 'pool = "codebuddy"',
                 f'id = "{alias}"', f"default = {str(default).lower()}", ""]
    path.write_text("\n".join(rows), encoding="utf-8")
    return path


# ---------------------------------------------------------------- 判据 1 / 2


def test_callsite_uses_should_sink_not_a_private_predicate(
        sandbox: Path, sink_state: Path, monkeypatch) -> None:
    """判据 1 / 2：沉不沉**只问** `pool_sink.should_sink()`；routing 是具名常量 `"order"`。

    两半都钉：① 源码事实（那一段里不许有 `== "限流"` 私有判据、`SINK_ROUTING` 必须是模块级
    常量且值为 `"order"`）；② 运行时事实（spy 收到的实参就是 `("限流", "order")`）。
    """
    src = (ROOT / "tools" / "wb_dispatch.py").read_text(encoding="utf-8")
    assert "pool_sink.should_sink(" in src, "调用侧必须调 sink.should_sink()，不许自己判"
    assert wd.SINK_ROUTING == "order", "routing 的取值是本仓唯一的真源：模块级常量"

    head = "# ★ 卡 A351（T-AG563）：探针仍挂"
    body = src[src.index(head):src.index("if nxt is None:", src.index(head))]
    assert "== \"限流\"" not in body and "'限流'" not in body, (
        "这一段里不许再写一遍 `kind == \"限流\"` —— 判据只有 sink.should_sink() 一份")
    assert "should_sink(quota.get(\"kind\"), SINK_ROUTING)" in body, (
        "must_sink 的两个实参：quota 的 kind + 具名常量 SINK_ROUTING")

    seen: list[tuple[str, str]] = []
    real = pool_sink.should_sink

    def spy(kind, routing, *, on=True):           # noqa: ANN001, ANN202
        seen.append((kind, routing))
        return real(kind, routing, on=on)

    monkeypatch.setattr(pool_sink, "should_sink", spy)
    monkeypatch.setattr(wd, "run_worker", _rounds([]))
    monkeypatch.setattr(wd, "quota_probe_ok", lambda *a, **k: (False, "额度仍挂"))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--execute", "--quota-wait", "0"])
    assert wd.main() == 0
    assert seen == [("限流", "order")], f"沉之前只问了 should_sink 一次，实参要原样：{seen}"


# ---------------------------------------------------------------- 判据 3


def test_sink_happens_only_when_probe_still_fails(
        sandbox: Path, sink_state: Path, monkeypatch) -> None:
    """判据 3：探针**仍挂** ⇒ 沉；探针通过 ⇒ 一个 key 都不许沉（已经好了，不该沉）。"""
    monkeypatch.setattr(wd, "run_worker", _rounds([]))
    monkeypatch.setattr(wd, "quota_probe_ok", lambda *a, **k: (True, "探测通过"))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--execute", "--quota-wait", "0"])
    assert wd.main() == 0
    assert _sunk_keys(sink_state) == {}, "探针通了说明这个 key 现在能用 —— 沉它就是把人烧掉"

    calls: list[list[str]] = []
    monkeypatch.setattr(wd, "run_worker", _rounds(calls))
    monkeypatch.setattr(wd, "quota_probe_ok", lambda *a, **k: (False, "额度仍挂"))
    # ★ 第二轮要重跑同一张卡 ⇒ 清掉上一轮落下的 log（真流程里第二轮写的是 `.r2.jsonl`，
    #   这里是**新的**一次 `main()`，它从第 1 轮数起 —— 不清就被「log 已存在」拦住）。
    for stale in (sandbox / "gates" / "diag").glob("wb-001*"):
        stale.unlink()
    assert wd.main() == 0
    assert "/deepseek-v4.1-flash" in _sunk_keys(sink_state), "探针仍挂 ⇒ 这个 key 要沉下去"


# ---------------------------------------------------------------- 判据 4


def test_sink_key_is_account_slash_model(sandbox: Path, sink_state: Path, monkeypatch) -> None:
    """判据 4：key 是 `<稳定 id>/<model>`（账号段用账本的稳定 id，不是 profile 名）。"""
    ledger = twd._ledger_with_profiles(
        sandbox, ("codebuddy-demo", "demo", "~/codebuddy-accounts/demo"))
    twd._use_ledger(monkeypatch, ledger)
    stub = twd._account_stub(sandbox, {"demo": twd._demo_vars()})
    monkeypatch.setenv("TF_ACCOUNT_SCRIPT", str(stub))
    monkeypatch.setattr(wd, "run_worker", _rounds([]))
    monkeypatch.setattr(wd, "quota_probe_ok", lambda *a, **k: (False, "额度仍挂"))
    twd._account_argv(monkeypatch, "--account", "demo", "--execute", "--quota-wait", "0")
    assert wd.main() == 0

    keys = set(_sunk_keys(sink_state))
    assert "codebuddy-demo/deepseek-v4.1-flash" in keys, (
        f"key 要用稳定 id + 斜杠 + 模型名（sunk_at 认的两段式），实际 {keys}")
    assert "demo/deepseek-v4.1-flash" not in keys, "profile 名不许进 key（闸查表用的是 id）"
    assert pool_sink.sunk_at("codebuddy-demo/deepseek-v4.1-flash") is not None


# ---------------------------------------------------------------- 判据 5


def test_empty_account_still_sinks_and_reads_back(
        sandbox: Path, sink_state: Path, monkeypatch) -> None:
    """判据 5：没给 `--account` **照样沉**，key = `/<model>`，且 `sunk_at()` 读得回来。

    不许因为账号为空就整段静默跳过 —— 那只是把「不接线」换个形状继续存在。
    """
    monkeypatch.setattr(wd, "run_worker", _rounds([]))
    monkeypatch.setattr(wd, "quota_probe_ok", lambda *a, **k: (False, "额度仍挂"))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--execute", "--quota-wait", "0"])
    assert wd.main() == 0
    keys = set(_sunk_keys(sink_state))
    assert keys == {"/deepseek-v4.1-flash"}, f"空账号那一档的 key 就是 `/<model>`：{keys}"
    assert pool_sink.sunk_at("/deepseek-v4.1-flash") is not None, "沉了就必须读得回来"


# ---------------------------------------------------------------- 判据 6


def test_rotation_chain_tail_scan_not_just_next(
        sandbox: Path, sink_state: Path, tmp_path: Path, monkeypatch) -> None:
    """判据 6 前半：尾巴里**还有一个没沉** ⇒ 照旧换过去（不许只看 `nxt` 一个）。

    三模型链 `alpha → beta → gamma`；`alpha` 撞限流被沉、`beta` **预先**沉过、`gamma` 没沉。
    只看 `nxt`（beta）的实现会误判「全沉了」→ 停（退出码 7）；真判据看得见 gamma ⇒ 换 beta。
    """
    monkeypatch.setenv("TF_MODEL_REGISTRY", str(_three_model_registry(tmp_path)))
    pool_sink.sink("/beta")
    calls: list[list[str]] = []
    monkeypatch.setattr(wd, "run_worker", _rounds(calls))
    monkeypatch.setattr(wd, "quota_probe_ok", lambda *a, **k: (False, "额度仍挂"))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--execute", "--quota-wait", "0", "--model", "alpha"])
    assert wd.main() == 0, "gamma 没沉过 ⇒ 这只是「换个模型」，不是「全挂」"
    assert len(calls) == 2, f"要换到 beta 再派一轮，实际 {len(calls)} 轮"
    assert _models(calls) == ["alpha", "beta"], f"按序换，不许跳：{_models(calls)}"


def test_all_tail_sunk_lands_on_exit_7(
        sandbox: Path, sink_state: Path, tmp_path: Path, monkeypatch, capsys) -> None:
    """判据 6 后半：尾巴**全沉** ⇒ 走既有停路（退出码 7、同一句 release_tree），不新开码。"""
    monkeypatch.setenv("TF_MODEL_REGISTRY", str(_three_model_registry(tmp_path)))
    pool_sink.sink("/beta")
    pool_sink.sink("/gamma")
    calls: list[list[str]] = []
    monkeypatch.setattr(wd, "run_worker", _rounds(calls))
    monkeypatch.setattr(wd, "quota_probe_ok", lambda *a, **k: (False, "额度仍挂"))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--execute", "--quota-wait", "0", "--model", "alpha"])
    assert wd.main() == 7, "全沉了就停，退出码沿用既有的 7"
    assert len(calls) == 1, "一个没沉过的模型都不剩 ⇒ 不许再派第二轮空撞"
    said = capsys.readouterr()
    both = said.out + said.err
    assert "额度全挂 → 任务停下" in both, (
        f"要落进既有的那条停路（release_tree 的原因原样带出来）：{both}")
    verdict = (sandbox / "gates" / "diag" / "wb-001.verdict.txt").read_text(encoding="utf-8")
    assert "额度判决" in verdict and "任务停下" in verdict


# ---------------------------------------------------------------- 判据 1（余额耗尽）


def test_balance_exhausted_is_never_sunk(
        sandbox: Path, sink_state: Path, monkeypatch) -> None:
    """判据 1 的另一半：`余额耗尽` **绝不沉**（由 `should_sink()` 内部硬拦，不加旁路）。"""
    monkeypatch.setattr(wd, "run_worker", _rounds([], first=_BROKE_LINE, rest=[_BROKE_LINE]))
    monkeypatch.setattr(wd, "quota_probe_ok", lambda *a, **k: (False, "额度仍挂"))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "001", "--spec", "spec.md",
                                      "--execute", "--quota-wait", "0"])
    assert wd.main() == 7, "余额耗尽那条路照旧：链尾就停（不许因本卡改变）"
    assert _sunk_keys(sink_state) == {}, "余额耗尽是硬挡，沉下去这个号就永远回不来了"


# ---------------------------------------------------------------- 判据 7


def _baseline_source() -> str:
    import subprocess

    done = subprocess.run(["git", "show", "eaeb3923:tools/pool/sink.py"], cwd=str(ROOT),
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert done.returncode == 0, f"读不到基准版本的 sink.py：{done.stderr}"
    return done.stdout


def _signatures(source: str) -> dict[str, tuple[str, tuple[str, ...]]]:
    """`名字 → (签名原文, 形参名元组)`；只认模块级 def，八个之外的一律不管。"""
    out: dict[str, tuple[str, tuple[str, ...]]] = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name in _EIGHT:
            ret = ast.unparse(node.returns) if node.returns else ""
            names = tuple(a.arg for a in (*node.args.posonlyargs, *node.args.args))
            names += (node.args.vararg.arg,) if node.args.vararg else ()
            names += tuple(a.arg for a in node.args.kwonlyargs)
            names += (node.args.kwarg.arg,) if node.args.kwarg else ()
            out[node.name] = (f"({ast.unparse(node.args)}) -> {ret}", names)
    return out


def test_sink_module_eight_functions_untouched() -> None:
    """判据 7：八个公开函数的签名与基准 `eaeb3923` **逐字一致**（行为不许改，签名也不许改）。"""
    base = _signatures(_baseline_source())
    now = _signatures((ROOT / "tools" / "pool" / "sink.py").read_text(encoding="utf-8"))
    assert set(base) == set(_EIGHT), f"基准里没找齐八个函数：{sorted(base)}"
    for name in _EIGHT:
        assert now.get(name) == base[name], (
            f"{name} 的签名被改了：基准 {base[name]!r} → 现在 {now.get(name)!r}")
        # 运行时那一份也要对得上（源码里写对了但没接上导出 / 被同名遮蔽，这里必红）。
        live = tuple(inspect.signature(getattr(pool_sink, name)).parameters)
        assert live == base[name][1], (
            f"{name} 运行时形参表与基准不一致：{live} vs {base[name][1]}")
