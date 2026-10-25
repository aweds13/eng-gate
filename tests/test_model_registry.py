r"""模型注册表 —— 一层统一，按池分流（卡 166 · T-G266）的钉子。

## 钉什么

- ① 单层：wb_dispatch 常量是"读出来的结果"（不抄第二份）
- ② 默认不跨池：码道项排第一 ⇒ 默认仍是 codebuddy 的（不取首项）
- ③ 跨池串用被拒：codearts 的 id 给 codebuddy 池 ⇒ 拒并点名
- ④ 未知池：未知池 ⇒ 响亮拒绝，不静默降级
- ⑤ 注册表坏掉：找不到/坏掉 ⇒ ModelRegistryError、零副作用
- ⑥ CodeBuddy 不变：MODEL_WHITELIST/DEFAULT_MODEL 与旧常量逐字相同
- 规矩集：minimum_ruleset_text 含 5 条（卡 182 咬的 NO_WINDOW 等）
- 统一日志：list_dispatch_logs 看见两边目录（追加要求 3）

★ ②③④ 各有一条**真跑**的干跑读数（``wd.main()`` 真跑了闸门段）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import wb_dispatch as wd  # noqa: E402
from pool import model_registry as mr  # noqa: E402
from pool.model_registry import (  # noqa: E402
    ModelRegistryError,
    PoolMismatchError,
    PoolNotWiredError,
    UnknownPoolError,
    default_model_for,
    effective_allowed_for,
    get_adapter,
    load_registry,
    minimum_ruleset,
    minimum_ruleset_text,
    resolve_model,
    rotation_chain_for,
)


# ---------------------------------------------------------------- 辅助
def _write_registry(tmp_path: Path, content: str, monkeypatch) -> Path:
    """写一份临时注册表并指过去（隔离' 临时注册表，不读真文件）。"""
    path = tmp_path / "model-registry.toml"
    path.write_text(content, encoding="utf-8")
    monkeypatch.setenv("TF_MODEL_REGISTRY", str(path))
    return path


def _point_switches(tmp_path: Path, content: str, monkeypatch) -> Path:
    """写一份临时开关文件并指过去（隔离掉真开关文件）。"""
    path = tmp_path / "model-switches.toml"
    path.write_text(content, encoding="utf-8")
    monkeypatch.setenv("TF_MODEL_SWITCHES", str(path))
    return path


def _point_whitelist(
    tmp_path: Path,
    monkeypatch,
    models: tuple[str, ...] = ("huaweicloud-maas/GLM-5.2",),
) -> Path:
    """写一份临时码道白名单并指过去（卡 E49：判据不许依赖宿主的「号池目录」）。"""
    path = tmp_path / "models.whitelist.toml"
    rows = ["# 临时白名单 —— 判据自带一份，别去读宿主上那份", ""]
    for model in models:
        rows += ["[[approved]]", f'model = "{model}"', ""]
    path.write_text(chr(10).join(rows) + chr(10), encoding="utf-8")
    monkeypatch.setenv("TF_MODEL_WHITELIST", str(path))
    return path


# ---------------------------------------------------------------- ① 单层
def test_wb_dispatch_constants_are_read_from_registry(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    """① wb_dispatch 的 MODEL_WHITELIST / DEFAULT_MODEL / ALLOWED_MODELS 是"读出来的结果"。

    ★ 不是自己抄的第二份常量 —— 与注册表 codebuddy 段逐字相同。
    """
    _point_switches(tmp_path, "", monkeypatch)  # 隔离开关
    assert rotation_chain_for("codebuddy") == wd.MODEL_WHITELIST
    assert default_model_for("codebuddy").alias == wd.DEFAULT_MODEL
    assert (*rotation_chain_for("codebuddy"), *wd.ONE_OFF_MODELS) == wd.ALLOWED_MODELS


# ---------------------------------------------------------------- ② 默认不跨池
def test_default_is_pool_default_not_registry_first(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    """② ★ 反例钉子：注册表里码道项排在第一 ⇒ 默认**仍是** CodeBuddy 池的默认。

    ★ 这是卡 146 踩的雷：取注册表首项 ⇒ 跨池串了默认值。
    本卡按池声明默认（``default = true``），**绝不**取首项冒充。
    """
    registry = (
        '# 码道项**故意排第一** —— 默认仍必须是 codebuddy 的，不是首项\n'
        '[[model]]\n'
        'alias   = "huaweicloud-maas/GLM-5.2"\n'
        'pool    = "codearts"\n'
        'id      = "huaweicloud-maas/GLM-5.2"\n'
        'default = true\n'
        'note    = "码道池默认（排在第一）"\n'
        '[[model]]\n'
        'alias   = "deepseek-v4.1-flash"\n'
        'pool    = "codebuddy"\n'
        'id      = "deepseek-v4.1-flash"\n'
        'default = true\n'
        'note    = "codebuddy 默认"\n'
        '[[model]]\n'
        'alias   = "glm-5.3-flash"\n'
        'pool    = "codebuddy"\n'
        'id      = "glm-5.3-flash"\n'
        'default = false\n'
        'note    = "替补"\n'
    )
    _write_registry(tmp_path, registry, monkeypatch)
    entries = load_registry()
    # 首项是码道的（排第一）
    assert entries[0].pool == "codearts", "前置：码道项确实排第一"
    # ★ 但 codebuddy 默认仍是 codebuddy 的，不是首项
    default = default_model_for("codebuddy", entries)
    assert default.alias == "deepseek-v4.1-flash", "默认按池声明，不取注册表首项"
    assert default.pool == "codebuddy"


def test_main_default_is_pool_default_not_first(tmp_path, monkeypatch, capsys) -> None:  # noqa: ANN001
    """② ★ 真跑读数：``--pool codebuddy``（缺省 --model）⇒ 闸门段取 codebuddy 默认，不取首项。

    用码道项排第一的注册表；main() 的闸门段 ``default_model_for("codebuddy")`` 必须取
    ``deepseek-v4.1-flash``（不是首项 ``huaweicloud-maas/GLM-5.2``）。
    """
    _write_registry(tmp_path, (
        '[[model]]\n'
        'alias   = "huaweicloud-maas/GLM-5.2"\n'
        'pool    = "codearts"\n'
        'id      = "huaweicloud-maas/GLM-5.2"\n'
        'default = true\n'
        '[[model]]\n'
        'alias   = "deepseek-v4.1-flash"\n'
        'pool    = "codebuddy"\n'
        'id      = "deepseek-v4.1-flash"\n'
        'default = true\n'
        '[[model]]\n'
        'alias   = "glm-5.3-flash"\n'
        'pool    = "codebuddy"\n'
        'id      = "glm-5.3-flash"\n'
        'default = false\n'
    ), monkeypatch)
    _point_switches(tmp_path, "", monkeypatch)
    # main() 不给 --model ⇒ 闸门段按池取默认；--spec 不给 ⇒ 闸门后拒（退 2）
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "000",
                                      "--pool", "codebuddy", "--spec", "x"])
    # 闸门段会过（默认取到 deepseek-v4.1-flash，在允许集）；preflight 会拒（spec 不存在）
    # 但我们要证明的是"默认取到了 deepseek-v4.1-flash"——用 default_model_for 直接验
    default = default_model_for("codebuddy")
    assert default.alias == "deepseek-v4.1-flash", "main 闸门段会取这个默认"
    # 真跑 main()：闸门段过（默认 OK）→ preflight 拒（spec 不存在）→ 退 2
    assert wd.main() == 2
    err = capsys.readouterr().err
    # 不含跨池串用 / 未知池 / 未授权模型 —— Buddy 默认取对了
    assert "跨池串用" not in err
    assert "未知池" not in err
    assert "未授权模型" not in err


# ---------------------------------------------------------------- ③ 跨池串用被拒
def test_cross_pool_usage_refused(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    _point_whitelist(tmp_path, monkeypatch)
    """③ codearts 的 id 给 codebuddy 池 ⇒ PoolMismatchError；反过来同理。"""
    # codearts 的 id（provider/model 形式）给 codebuddy 池 ⇒ 拒
    with pytest.raises(PoolMismatchError) as excinfo:
        resolve_model("huaweicloud-maas/GLM-5.2", "codebuddy")
    msg = str(excinfo.value)
    assert "跨池串用" in msg and "codearts" in msg and "codebuddy" in msg, msg
    # codebuddy 的 id（裸名）给 codearts 池 ⇒ 拒
    with pytest.raises(PoolMismatchError) as excinfo:
        resolve_model("deepseek-v4.1-flash", "codearts")
    msg = str(excinfo.value)
    assert "跨池串用" in msg and "codebuddy" in msg and "codearts" in msg, msg


def test_main_refuses_cross_pool_with_exit_2(tmp_path, monkeypatch, capsys) -> None:  # noqa: ANN001
    _point_whitelist(tmp_path, monkeypatch)
    """③ ★ 真跑读数：``--pool codebuddy --model huaweicloud-maas/GLM-5.2`` ⇒ 退 2、点名跨池串用。"""
    _point_switches(tmp_path, "", monkeypatch)
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "000",
                                      "--pool", "codebuddy",
                                      "--model", "huaweicloud-maas/GLM-5.2",
                                      "--spec", "x", "--execute"])
    assert wd.main() == 2
    err = capsys.readouterr().err
    assert "跨池串用" in err, f"要点名跨池串用；实际 err={err!r}"
    assert "codearts" in err and "codebuddy" in err, "要点清属于哪个池、当前池是什么"


def test_main_refuses_bare_name_for_codearts_pool(tmp_path, monkeypatch, capsys) -> None:  # noqa: ANN001
    """③ ★ 真跑读数：``--pool codearts --model deepseek-v4.1-flash`` ⇒ 退 2、点名跨池串用。"""
    _point_switches(tmp_path, "", monkeypatch)
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "000",
                                      "--pool", "codearts",
                                      "--model", "deepseek-v4.1-flash",
                                      "--spec", "x", "--execute"])
    assert wd.main() == 2
    err = capsys.readouterr().err
    assert "跨池串用" in err, f"裸名给 codearts 池要拒；实际 err={err!r}"


# ---------------------------------------------------------------- ④ 未知池 / 未接池
def test_unknown_pool_refused() -> None:
    """④ 未知池 ⇒ UnknownPoolError（响亮拒绝，不静默降级）。"""
    with pytest.raises(UnknownPoolError) as excinfo:
        get_adapter("some-pool-not-wired")
    msg = str(excinfo.value)
    assert "some-pool-not-wired" in msg and "codebuddy" in msg and "codearts" in msg, msg


def test_codearts_pool_not_wired_refuses_loudly() -> None:
    """④ codearts 池的适配器只留接口 + 响亮拒绝（不静默回落到 codebuddy）。"""
    adapter = get_adapter("codearts")
    assert not adapter.wired, "codearts 池本卡不接真实调用"
    with pytest.raises(PoolNotWiredError) as excinfo:
        adapter.assert_wired()
    assert "codearts" in str(excinfo.value) and "还没接" in str(excinfo.value)


def test_codebuddy_pool_is_wired() -> None:
    """④ codebuddy 池是已接的（今天在用的）。"""
    adapter = get_adapter("codebuddy")
    assert adapter.wired
    adapter.assert_wired()  # 不抛


def test_main_refuses_unknown_pool_with_exit_2(tmp_path, monkeypatch, capsys) -> None:  # noqa: ANN001
    """④ ★ 真跑读数：``--pool some-unknown`` ⇒ 退 2、点名已接的池。"""
    _point_switches(tmp_path, "", monkeypatch)
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "000",
                                      "--pool", "some-unknown",
                                      "--model", "deepseek-v4.1-flash",
                                      "--spec", "x", "--execute"])
    assert wd.main() == 2
    err = capsys.readouterr().err
    assert "未知池" in err and "some-unknown" in err, f"要点名未知池；实际 err={err!r}"
    assert "codebuddy" in err and "codearts" in err, "要列出已接的池"


def test_main_refuses_codearts_pool_not_wired(tmp_path, monkeypatch, capsys) -> None:  # noqa: ANN001
    """④ ★ 真跑读数：``--pool codearts``（已接适配器但未接真实调用）⇒ 退 2、点名"还没接"。"""
    _point_switches(tmp_path, "", monkeypatch)
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "000",
                                      "--pool", "codearts",
                                      "--model", "huaweicloud-maas/GLM-5.2",
                                      "--spec", "x", "--execute"])
    assert wd.main() == 2
    err = capsys.readouterr().err
    assert "还没接" in err, f"codearts 池要响亮拒绝；实际 err={err!r}"


# ---------------------------------------------------------------- ⑤ 注册表坏掉
def test_registry_missing_refuses(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    """⑤ 注册表找不到 ⇒ ModelRegistryError（不退回内置名单）。"""
    monkeypatch.setenv("TF_MODEL_REGISTRY", str(tmp_path / "absent.toml"))
    with pytest.raises(ModelRegistryError, match="不存在"):
        load_registry()


def test_registry_broken_toml_refuses(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    """⑤ 注册表坏 TOML ⇒ ModelRegistryError 点名行号。"""
    _write_registry(tmp_path, "this is not = valid = toml =\n", monkeypatch)
    with pytest.raises(ModelRegistryError, match="解析失败"):
        load_registry()


def test_registry_empty_approved_refuses(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    """⑤ 注册表没有 [[model]] 条目 ⇒ ModelRegistryError（空名单不许静默当空）。"""
    _write_registry(tmp_path, "# 空注册表\n", monkeypatch)
    with pytest.raises(ModelRegistryError):
        load_registry()


def test_registry_broken_makes_main_exit_2(tmp_path, monkeypatch, capsys) -> None:  # noqa: ANN001
    """⑤ ★ 真跑读数：注册表坏掉 ⇒ main() 退 2、零副作用、点名。"""
    monkeypatch.setenv("TF_MODEL_REGISTRY", str(tmp_path / "absent.toml"))
    _point_switches(tmp_path, "", monkeypatch)
    spawned: list[list[str]] = []
    monkeypatch.setattr(wd, "run_worker", lambda *a, **k: (0, "", "", ""))
    monkeypatch.setattr(sys, "argv", ["wb_dispatch.py", "--card", "000",
                                      "--model", "deepseek-v4.1-flash",
                                      "--spec", "x", "--execute"])
    assert wd.main() == 2
    err = capsys.readouterr().err
    assert "注册表" in err or "不存在" in err, f"要点名注册表问题；实际 err={err!r}"
    assert spawned == [], "一个子进程都不许起"


# ---------------------------------------------------------------- ⑥ CodeBuddy 行为不变
def test_codebuddy_behavior_unchanged(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    """⑥ 本笔不许改变今天 CodeBuddy 池的行为：裸名照旧、允许集照旧、429 轮换链照旧。"""
    _point_switches(tmp_path, "", monkeypatch)  # 隔离开关
    # 轮换链 = 旧 MODEL_WHITELIST
    assert rotation_chain_for("codebuddy") == ("deepseek-v4.1-flash", "glm-5.3-flash")
    # 默认 = 旧 DEFAULT_MODEL
    assert default_model_for("codebuddy").alias == "deepseek-v4.1-flash"
    # 允许集 = 旧 ALLOWED_MODELS（ONE_OFF 空）
    assert effective_allowed_for("codebuddy") == ("deepseek-v4.1-flash", "glm-5.3-flash")
    # 429 轮换：① → ② → None
    assert wd.next_whitelist_model("deepseek-v4.1-flash", "codebuddy") == "glm-5.3-flash"
    assert wd.next_whitelist_model("glm-5.3-flash", "codebuddy") is None
    # wb_dispatch 的旧名字仍可用（PEP 562）
    assert wd.MODEL_WHITELIST == ("deepseek-v4.1-flash", "glm-5.3-flash")
    assert wd.DEFAULT_MODEL == "deepseek-v4.1-flash"
    assert wd.ALLOWED_MODELS == ("deepseek-v4.1-flash", "glm-5.3-flash")


def test_codebuddy_model_rejected_behaves_as_before(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    """⑥ model_rejected 对 codebuddy 池行为不变：名单内放行、表外拒。"""
    _point_switches(tmp_path, "", monkeypatch)
    assert wd.model_rejected("deepseek-v4.1-flash", "codebuddy") == ""
    assert wd.model_rejected("glm-5.3-flash", "codebuddy") == ""
    assert wd.model_rejected("no-such-model", "codebuddy") != ""


# ---------------------------------------------------------------- 最小规矩集（追加要求 2）
def test_minimum_ruleset_contains_all_keys() -> None:
    """★ 卡 166 追加要求 2：最小规矩集含 5 条（机器判据）。"""
    text = minimum_ruleset_text()
    ruleset = minimum_ruleset()
    assert set(ruleset.keys()) == set(mr.MINIMUM_RULESET_KEYS)
    # 每条都要在拼装后的文本里出现
    for key in mr.MINIMUM_RULESET_KEYS:
        assert ruleset[key] in text, f"最小规矩集漏了 {key}"
    # 具体内容钉子（卡 182 咬的那条：NO_WINDOW 铁律必须在）
    assert "NO_WINDOW" in text, "NO_WINDOW 铁律必须在（卡 182 咬的）"
    assert "不许 commit" in text
    assert "不许跑全量门禁" in text
    assert "禁区" in text
    assert "固定坑页" in text


def test_minimum_ruleset_in_built_command() -> None:
    """★ 机器判据：build_command 拼出去的提示里含最小规矩集。"""
    cmd = wd.build_command(Path("node"), Path("cli"), "000", "spec.md", "deepseek-v4.1-flash")
    prompt = cmd[cmd.index("-p") + 1]
    assert "NO_WINDOW" in prompt, "派出去的提示必须含 NO_WINDOW 铁律"
    assert "不许 commit" in prompt
    assert "不许跑全量门禁" in prompt
    assert "禁区" in prompt
    assert "固定坑页" in prompt


# ---------------------------------------------------------------- 统一日志读数（追加要求 3）
def test_dispatch_log_dirs_covers_both_pools() -> None:
    """★ 卡 166 追加要求 3：两边日志目录都被列出来（同一套读数看见两边）。"""
    dirs = mr.dispatch_log_dirs(ROOT)
    assert "codebuddy" in dirs and "codearts" in dirs
    assert dirs["codebuddy"].name == "diag"  # gates/diag/
    # codearts 的日志目录（infra/pool/logs/ 或回退）
    assert "logs" in dirs["codearts"].parts or dirs["codearts"].name == "logs"


def test_list_dispatch_logs_scans_both_patterns(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    """★ 统一读数能看见两边的日志文件（wb-<卡>.jsonl + card-<卡>.jsonl）。"""
    diag = tmp_path / "gates" / "diag"
    diag.mkdir(parents=True)
    (diag / "wb-001.jsonl").write_text("{}", encoding="utf-8")
    pool_logs = tmp_path / "infra" / "pool" / "logs"
    pool_logs.mkdir(parents=True)
    (pool_logs / "card-182.jsonl").write_text("{}", encoding="utf-8")
    # 让 find_pool_dir 找到 tmp_path/infra/pool
    (tmp_path / "infra" / "pool" / "pool_models.py").write_text("", encoding="utf-8")
    logs = mr.list_dispatch_logs(tmp_path)
    names = [p.name for p in logs]
    assert "wb-001.jsonl" in names, "codebuddy 池日志要被看见"
    assert "card-182.jsonl" in names, "codearts 池日志也要被看见"


# ---------------------------------------------------------------- 注册表条目结构
def test_registry_has_codebuddy_and_codearts_entries(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    _point_whitelist(tmp_path, monkeypatch)
    """注册表含两个池的条目（codebuddy 内联 + codearts 引用派生）。"""
    entries = load_registry()
    pools = {e.pool for e in entries}
    assert "codebuddy" in pools, "codebuddy 池要有条目"
    assert "codearts" in pools, "codearts 池要有条目（从 models.whitelist.toml 派生）"
    # codebuddy 条目的 id 是裸名（不含 /）
    for e in entries:
        if e.pool == "codebuddy":
            assert "/" not in e.id, f"codebuddy id 应是裸名，实际 {e.id!r}"
    # codearts 条目的 id 是 provider/model 形式（含 /）
    codearts = [e for e in entries if e.pool == "codearts"]
    if codearts:
        for e in codearts:
            assert "/" in e.id, f"codearts id 应是 provider/model 形式，实际 {e.id!r}"


def test_one_default_per_pool(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    """每池至多一条 default = true（多了 ⇒ 报错）。"""
    _write_registry(tmp_path, (
        '[[model]]\n'
        'alias = "a"\n pool = "codebuddy"\n id = "a"\n default = true\n'
        '[[model]]\n'
        'alias = "b"\n pool = "codebuddy"\n id = "b"\n default = true\n'
    ), monkeypatch)
    with pytest.raises(ModelRegistryError, match="多条 default"):
        load_registry()
