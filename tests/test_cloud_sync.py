r"""云机确定性钉子（卡 E35 · T-AG489）—— 「换一台机器跑门禁」的装配/同步脚本必须可复核。

## 为什么有这张测试

卡 E35 的病灶是「同 commit、同 worker 数，两个环境给两套读数」：云机 37 条红里，
一大半不是代码坏，而是**装配与同步没进版本库**（`gates/diag/` 被 gitignore）、
**依赖没钉版本**（云机 ruff 0.17.2 vs 本机 0.16.6 ⇒ `I001` 判不同）、
**上一趟的 `gates/last.json` 被下一趟读到**（`git clean -fdq` 不删被忽略文件）。

所以这里钉的不是"云机跑得通"，而是**脚本的口径**（脚本本身在库里、可 review）：

- `test_run_gate_cleans_ignored_files` —— 清树必须 `git clean -xfdq`（改回 `-fdq` ⇒ 红）
- `test_run_gate_refuses_residual_last_json` —— 跑前断言 `gates/last.json` 不存在（真跑一针）
- `test_bootstrap_pins_every_cloud_dependency` —— httpx/fsrs/psutil 都在且带版本
- `test_bootstrap_ruff_pin_matches_canonical` —— ruff 钉到与本机同一版本（去掉 ⇒ 红）
- `test_run_gate_fails_fast_without_projects_toml` —— 缺 `TF_PROJECTS_TOML` ⇒ 报错、一步不跑
- `test_cloud_scripts_are_repo_files` —— 两个脚本进得了库（不是被 gitignore 吞掉的）
- `test_known_env_red_list_covers_only_b_class` —— 名单 = B 类 15 条，且没被 skip 掩盖

## 边界（如实写）

- 本文件**不连云机**（没有 SSH 凭据，也不该让单测产生网络副作用）⇒ 它钉的是「脚本口径」，
  不是「云机读数」。真正的两趟读数与 A 类子集输出见卡 E35 的申报。
- `known-env-red` 名单住在 `docs/subsystems/ci/云门禁机.md`（**不是** pytest marker）：
  本卡白名单不许改那三个测试文件，所以名单只能落在文档侧；钉子的作用是
  **不许它悄悄扩大、也不许把名单里的用例改成 skip 蒙混**。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from pool.no_window import NO_WINDOW  # noqa: E402 —— 先用 sys.path 把 tools/ 挂上

SCRIPT_DIR = ROOT / "scripts" / "cloud"
BOOTSTRAP = SCRIPT_DIR / "bootstrap.ps1"
RUN_GATE = SCRIPT_DIR / "run_gate.sh"
DOC = ROOT / "docs" / "subsystems" / "ci" / "云门禁机.md"

#: 2026-10-25 本机 `pip freeze` 原样 pin（卡 E35 §1「钉版本」）。
#: ★ 改这里 = 改判据口径：要么本机真升了，要么云机会和本机给出两套答案。
EXPECTED_PINS: dict[str, str] = {
    "fastapi": "0.141.1",
    "uvicorn": "0.52.4",
    "pydantic": "2.13.4",
    "httpx": "0.28.1",
    "fsrs": "6.3.2",
    "psutil": "7.2.2",
    "pytest": "9.1.1",
    "pytest-cov": "7.1.0",
    "pytest-xdist": "3.8.0",
    "mypy": "2.3.1",
    "ruff": "0.16.6",
}

#: 云机缺了必红的三条（卡 E35 §1 实测）：装配清单一字不许少。
REQUIRED_PACKAGES = ("httpx", "fsrs", "psutil")

#: 卡 E35 §6 的反向验证点名要的那一条：ruff 与本机同版本，否则 `I001` 两套答案。
RUFF_CANONICAL = "0.16.6"

#: B 类 15 条的分布（卡 §「现在疼在哪」第 1 条）。名单只许收缩不许扩大。
B_CLASS_COUNTS = {
    "test_gates_reuse_line.py": 10,
    "test_run_gates_timeout.py": 4,
    "test_concurrency.py": 1,
}

_PIN_RE = re.compile(r"^\s*'([a-z0-9][a-z0-9\-]*)(?:\[[^\]]+\])?==([0-9][^'\s]*)'", re.MULTILINE)
_KNOWN_ROW_RE = re.compile(r"^\|\s*`tests/([^`]+)`\s*\|\s*(\d+)\s*\|", re.MULTILINE)


# ------------------------------------------------------------------ 小工具
def _run(cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None):
    """起子进程（★ 一律带 NO_WINDOW：测试里也不许给用户闪窗）。"""
    return subprocess.run(
        cmd,
        cwd=str(cwd or ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        **NO_WINDOW,
    )


def _git(*args: str):
    return _run(["git", *args])


def _find_bash() -> str:
    """找 bash：PATH 上优先，其次 Git for Windows 的默认安装位置 —— 卡 E49。

    云门禁机（裸 Windows）装完 Git 2.47.1 后 `bash.exe` 不在 PATH 上（装配脚本从不改 PATH）
    ⇒ 原来 `["bash", ...]` 直接 `FileNotFoundError`，把「脚本口径没钉住」和「这台机器 PATH
    干净」混成了同一条红。找法就是**人找它的同一套办法**；真找不到才如实失败（不 skip 掩盖）。
    """
    found = shutil.which("bash")
    if found:
        return found
    for cand in (
        Path("C:/Program Files/Git/bin/bash.exe"),
        Path("C:/Program Files/Git/usr/bin/bash.exe"),
        Path("C:/Program Files (x86)/Git/bin/bash.exe"),
    ):
        if cand.is_file():
            return str(cand)
    pytest.fail(
        "找不到 bash：本仓的门禁与云脚本都靠 Git Bash 跑。云机装配里 Git for Windows 是必装项"
        "（scripts/cloud/bootstrap.ps1），装了就在 C:/Program Files/Git/bin/bash.exe；本机同理。"
        "这条失败是「这台机器缺前置」，不是脚本坏 —— 装完重跑。"
    )


def _bash(*args: str, env: dict[str, str] | None = None):
    return _run([_find_bash(), *args], env=env)


def _bootstrap_text() -> str:
    """读装配脚本（带 BOM 也不带进去 —— `utf-8-sig` 吃掉它）。"""
    return BOOTSTRAP.read_text(encoding="utf-8-sig")


def _doc_text() -> str:
    return DOC.read_text(encoding="utf-8")


# ------------------------------------------------------------------ 装配清单
def test_bootstrap_is_utf8_with_bom() -> None:
    """PowerShell 5.1 读无 BOM 的中文 `.ps1` 会按 ANSI 解 ⇒ 报「字符串缺少终止符」。"""
    head = BOOTSTRAP.read_bytes()[:3]
    assert head == b"\xef\xbb\xbf", f"bootstrap.ps1 缺 UTF-8 BOM（首 3 字节 {head!r}）"


def test_bootstrap_pins_every_cloud_dependency() -> None:
    """依赖清单：三个缺了必红的包 + 其余门禁依赖，**每一条都带版本**。"""
    pins = dict(_PIN_RE.findall(_bootstrap_text()))

    missing = [name for name in REQUIRED_PACKAGES if name not in pins]
    assert not missing, f"装配清单缺这三个包（云机必红）：{missing}"
    for name in REQUIRED_PACKAGES:
        assert pins[name], f"{name} 没有钉版本（钉成 {name}==<版本>）"

    # 清单里出现的每个包都要能对上本机 freeze（多装可以，少装/漂版本不行）
    drift = {k: (pins[k], EXPECTED_PINS[k]) for k in EXPECTED_PINS if k in pins}
    bad = {k: v for k, v in drift.items() if v[0] != v[1]}
    assert not bad, f"装配清单版本与本机不一致（云机会给第二套答案）：{bad}"
    assert set(EXPECTED_PINS) <= set(pins), f"清单少了：{sorted(set(EXPECTED_PINS) - set(pins))}"


def test_bootstrap_ruff_pin_matches_canonical() -> None:
    """★ 卡 §6 的反向验证点：ruff 版本钉去掉（或钉成别的版本）⇒ 本条必须红。

    为什么单列一条：云机 ruff 0.17.2 vs 本机 0.16.6 时 `I001` 判出不同结果，
    `tests/test_wb_land.py` 的 4 条 `test_preflight_*` 在云机红 —— 版本就是判据的一部分。
    """
    pins = dict(_PIN_RE.findall(_bootstrap_text()))
    assert pins.get("ruff") == RUFF_CANONICAL, (
        f"ruff 必须钉成 =={RUFF_CANONICAL}（现为 {pins.get('ruff')!r}）；"
        "不钉版本 ⇒ 云机与本机的 I001 结论会分叉"
    )


# ------------------------------------------------------------------ 清残留
def test_run_gate_cleans_ignored_files() -> None:
    """★ 卡 §6 的反向验证点：`-xfdq` 改回 `-fdq` ⇒ 本条必须红。

    不带 `-x` 时上一趟的 `gates/last.json` / `gates/logs/`（都是被忽略文件）留在盘上，
    下一趟的自指钉子必红 —— 2026-10-25 实测踩过，手工换成 `-xfdq` 才干净。
    """
    text = RUN_GATE.read_text(encoding="utf-8")
    assert "git clean -xfdq" in text, "清树必须带 -x（`git clean -xfdq`）"
    # 反向：不许别处还留一条不带 -x 的清树
    offenders = [
        line.strip() for line in text.splitlines() if "clean -fdq" in line and "-xfdq" not in line
    ]
    assert not offenders, f"还有不带 -x 的清树：{offenders}"


def test_run_gate_refuses_residual_last_json(tmp_path: Path) -> None:
    """跑前断言 `gates/last.json` 不存在 —— 存在就报错退出（不静默沿用上一趟）。"""
    clean = tmp_path / "clean"
    clean.mkdir()
    ok = _bash(str(RUN_GATE), "--check-residue", str(clean))
    assert ok.returncode == 0, f"干净目录不该被拒：{ok.stdout}{ok.stderr}"

    dirty = tmp_path / "dirty"
    (dirty / "gates").mkdir(parents=True)
    (dirty / "gates" / "last.json").write_text("{}", encoding="utf-8")
    bad = _bash(str(RUN_GATE), "--check-residue", str(dirty))
    assert bad.returncode == 2, f"有残留必须退 2，实际 {bad.returncode}：{bad.stdout}{bad.stderr}"
    assert "残留" in bad.stderr, f"报错要指名残留：{bad.stderr!r}"
    assert "last.json" in bad.stderr


# ------------------------------------------------------------------ 仓外配置（fail fast）
def test_run_gate_fails_fast_without_projects_toml() -> None:
    """缺 `TF_PROJECTS_TOML` ⇒ 当场报错、**一步都不跑**（不许跑一半才发现没配）。"""
    env = dict(os.environ)
    env.pop("TF_PROJECTS_TOML", None)
    proc = _bash(str(RUN_GATE), "E35", env=env)

    assert proc.returncode == 2, f"缺配置必须退 2，实际 {proc.returncode}：{proc.stderr}"
    assert "TF_PROJECTS_TOML" in proc.stderr
    # 一步都没跑：同步/补丁/门禁的步骤横幅一个都不许出现
    for banner in ("0/5", "1/5", "4/5"):
        assert banner not in proc.stdout, f"缺配置却已经开始跑了（出现 {banner}）：{proc.stdout}"


def test_run_gate_injects_config_into_cloud_command() -> None:
    """配置是**显式注入**到云机那条命令里的（不是靠云机的环境碰巧有）。"""
    text = RUN_GATE.read_text(encoding="utf-8")
    assert 'set \\"TF_PROJECTS_TOML=$projects_toml\\"' in text
    assert "TF_MODEL_REGISTRY" in text, "模型注册表的真名是 TF_MODEL_REGISTRY（非 TF_MODELS_TOML）"


# ------------------------------------------------------------------ 在库里
def test_cloud_scripts_are_repo_files() -> None:
    """★ 卡判据 4：两个脚本要进得了库（`gates/diag/` 那边不再有它们）。

    未提交时 `git ls-files --cached` 还没有它们，所以口径取
    `--cached --others --exclude-standard`：**在索引里 或 能被 `git add` 收进去**（即没被 ignore）。
    主控提交之后，同一条查询里 `--cached` 就命中了。
    """
    for path in ("scripts/cloud/bootstrap.ps1", "scripts/cloud/run_gate.sh"):
        listed = _git("ls-files", "--cached", "--others", "--exclude-standard", "--", path)
        assert listed.returncode == 0, listed.stderr
        assert path in listed.stdout.splitlines(), f"{path} 不在库里，也进不了库"

        ignored = _git("check-ignore", "-q", path)
        assert ignored.returncode != 0, f"{path} 被 .gitignore 吞掉了（等于云机拿不到）"

    diag = _git("ls-files", "--", "gates/diag")
    offenders = [line for line in diag.stdout.splitlines() if "cloud_" in line]
    assert not offenders, f"gates/diag/ 下仍有云机脚本入库：{offenders}"


# ------------------------------------------------------------------ known-env-red 名单
def _known_env_red_rows() -> dict[str, int]:
    text = _doc_text()
    block = re.search(r"<!-- known-env-red:begin(.*?)<!-- known-env-red:end", text, re.S)
    assert block, "文档里没有 `known-env-red:begin/end` 名单块"
    return {path: int(count) for path, count in _KNOWN_ROW_RE.findall(block.group(1))}


def test_known_env_red_list_covers_only_b_class() -> None:
    """★ 名单 = B 类 15 条（10 + 4 + 1），**只许收缩不许扩大**。

    防两件事：① 悄悄把新红的用例塞进名单当"已知"；② 把名单里的用例改成 `skip` 变绿
    （卡 §不许做：不许用 skip 掩盖 —— A266/T-G157 前科）。
    """
    rows = _known_env_red_rows()
    assert rows == B_CLASS_COUNTS, f"known-env-red 分布不对：{rows}"
    assert sum(rows.values()) == 15

    for module, count in rows.items():
        path = ROOT / "tests" / module
        assert path.is_file(), f"名单里的模块不存在：{module}"
        src = path.read_text(encoding="utf-8")
        markers = ("pytest.mark.skip", "pytest.mark.skipif", "pytest.mark.xfail", "pytest.skip(")
        for marker in markers:
            assert marker not in src, f"{module} 里出现 {marker} ⇒ 拿 skip 掩盖红，不许"
        assert count > 0


def test_known_env_red_is_declared_in_repo() -> None:
    """卡判据 3：`git grep known-env-red` 能查到声明处。"""
    hit = _git("-c", "core.quotePath=false", "grep", "-l", "known-env-red", "--", "docs")
    assert hit.returncode == 0 and "云门禁机.md" in hit.stdout, hit.stdout + hit.stderr


# ------------------------------------------------------------------ 文档不许再写假话
def test_doc_no_longer_claims_diag_scripts_are_in_git() -> None:
    """★ 卡判据增补：`grep -n "已入库" docs/...` 无输出；脚本路径指到仓内。"""
    text = _doc_text()
    assert "已入库" not in text, "§2 曾把 gitignore 里的脚本说成在库 —— 不许回潮"
    assert "scripts/cloud/bootstrap.ps1" in text
    assert "scripts/cloud/run_gate.sh" in text
    assert "gates/diag/cloud_bootstrap.ps1" not in text
    assert "gates/diag/cloud_run_gate.sh" not in text


def test_doc_keeps_controlled_ab_numbers() -> None:
    """卡判据增补：§7.1 的四个数逐字一致（403.46 / 417 / 684.27 / 37）；§7.2 有分类表。"""
    text = _doc_text()
    assert "### 7.1" in text and "### 7.2" in text
    for number in ("403.46", "417", "684.27"):
        assert number in text, f"§7.1 少了实测数 {number}"
    assert re.search(r"37\s*failed", text), "§7.1 少了云机 37 failed 那个读数"


# ------------------------------------------------------------------ 卡 E54：给定面收紧
def test_bootstrap_installs_dev_extras_as_the_single_source() -> None:
    """★ 卡 E54：依赖**集合**只能来自仓里 `pyproject.toml` 的 `[dev]`，bootstrap 自己不许再当家。

    云机 pass12 的 `tests/test_properties.py` 收集期 `ModuleNotFoundError: No module named
    'hypothesis'` —— 因为 E51 把 hypothesis 加进了 dev extras，而 bootstrap 按手抄清单装包。
    """
    text = _bootstrap_text()
    assert '-e "$Repo[dev]"' in text, "bootstrap 必须按仓里 pyproject 的 [dev] 装依赖"
    assert "$pinsFile" in text, "版本钉要单独落成 constraints 文件（-c），不能再当包清单"
    # 反向：任何把 pytest/ruff/mypy 直接当包名装的写法都不许回来
    forbidden_forms = (
        "pip install --quiet @Packages",
        "pip install --quiet pytest",
        "pip install pytest",
    )
    for forbidden in forbidden_forms:
        assert forbidden not in text, f"又回到手抄清单装包了：{forbidden!r}"


def test_run_gate_pushes_only_the_whitelisted_config() -> None:
    """★ 卡 E54：供给面只许白名单，不许 `scp *.toml *.json` 把本机私账与私有开关推上云机。

    实测污染：`test_pool_accounts.py` 两条「账本缺失要报错」在云机判不出来，
    `test_wb_dispatch.py::test_account_auth_uses_the_profile_env_and_model` 被判「未授权模型」。
    """
    text = RUN_GATE.read_text(encoding="utf-8")
    assert 'cfg_allow=(models.whitelist.toml)' in text, "白名单要写死成数组（可读、可核）"
    assert '"$cfg_local"/*.toml' not in text, "不许再通配推 *.toml（会把 accounts.toml 推上去）"
    assert '"$cfg_local"/*.json' not in text, "不许再通配推 *.json"
    # 只看**可执行行**：注释里点名是解释来龙去脉（E54 就写在注释里），不算供给面。
    code_lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
    code = chr(10).join(code_lines)
    for forbidden in ("accounts.toml", "model-switches.toml"):
        assert forbidden not in code, f"私账/私有开关不许出现在供给面（可执行行）：{forbidden}"
    assert "fail fast" in text and "exit 5" in text, "白名单缺件必须 fail fast"


def test_run_gate_cleans_stale_config_before_provisioning() -> None:
    """铺配置前要先清掉上一次的旧账（否则上一趟推上去的 accounts.toml 继续污染）。"""
    text = RUN_GATE.read_text(encoding="utf-8")
    idx = text.index("0.4/5")
    tail = text[idx : idx + 1200]
    assert "Get-ChildItem" in tail and "Remove-Item" in tail, "铺之前必须先删白名单之外的文件"
    for keep in ("projects.toml", "models.whitelist.toml"):
        assert keep in tail, f"白名单里的 {keep} 必须保留"


def test_run_gate_asserts_the_remote_tree_matches_the_target_commit() -> None:
    """★ 卡 E54：远端 HEAD 必须等于本次目标提交，不等就 fail closed（退 7）。

    实测：云机停在旧提交 `050fa3d`（trailer 还是 T-AG503）时，`test_wb_plan.py` 报
    「卡 E53：已落却仍 pending」—— 拿陈旧树判新队列，结论写进 last.json 的 rev。
    """
    text = RUN_GATE.read_text(encoding="utf-8")
    assert "2.5/5" in text, "树一致性断言要是独立一步（可见的进度条）"
    idx = text.index("2.5/5")
    tail = text[idx : idx + 900]
    assert 'git rev-parse HEAD' in tail, "要读远端 HEAD"
    assert "exit 7" in tail, "不一致必须 fail closed（退 7），不许警告继续"
    assert text.index("2.5/5") < text.index("=== 4/5"), "断言必须在跑门禁之前"


def test_run_gate_syncs_dev_extras_before_running_gates() -> None:
    """每趟开跑前按 extras 同步一次依赖（已满足时只花几秒；缺件会退 8 而不是给假红）。"""
    text = RUN_GATE.read_text(encoding="utf-8")
    assert "3.5/5" in text, "依赖同步要是独立一步"
    idx = text.index("3.5/5")
    tail = text[idx : idx + 900]
    assert ".[dev]" in tail, "同步要按 pyproject 的 [dev]"
    assert "C:/pins.txt" in tail, "版本钉来自 bootstrap 落的 C:/pins.txt"
    assert "exit 8" in tail, "同步失败必须 fail closed（退 8）"
    assert text.index("3.5/5") < text.index("=== 4/5"), "同步必须早于跑门禁"


def test_run_gate_provisions_pool_config_for_walk_up() -> None:
    """仓外配置必须铺到「向上找」认得的位置（C:/infra/pool），不是只放 C:/poolcfg。

    ★ 卡 E49：云机 22 红里 12 条是池索引/账本类，真因是 **配置没按约定落位** ——
    `tools/pool/*.py` 从 cwd 逐级向上找 `infra/pool/<文件>`：开发机上是
    `D:/repo/infra/pool/`（仓的祖父目录），云机上仓库在 `C:/eng` ⇒ 对应
    `C:/infra/pool/`。只把文件 scp 到 `C:/poolcfg/` 再靠 `TF_PROJECTS_TOML` 注入，
    救不了那些**自己 `delenv` 去测"向上找"**的用例。
    """
    text = RUN_GATE.read_text(encoding="utf-8")
    assert "C:/infra/pool" in text, "配置要铺到向上找认得的位置（C:/infra/pool）"
    assert "TF_POOL_CFG_DIR" in text, "配置源要可换（TF_POOL_CFG_DIR）"
    assert "0.4/5" in text, "铺配置必须是门禁之前的独立一步（可见的进度条）"
    # 铺配置那一步失败不许静默继续
    idx = text.index("0.4/5")
    tail = text[idx : idx + 1600]
    assert "exit 5" in tail, "配置铺不动必须 fail fast（退非零），不许继续跑门禁"
    # 反向：铺配置要在跑门禁（4/5）之前
    assert text.index("0.4/5") < text.index("=== 4/5"), "铺配置必须早于跑门禁"


def test_project_index_template_replaces_the_dev_root() -> None:
    """项目索引不能原样搬上云：模板里的 `root` 必须是占位符，由同步步渲染成云机路径。

    ★ 卡 E49：`infra/pool/projects.toml` 的 `[project.engineering].root` 是开发机绝对路径。
    原样 scp ⇒ 云机上那个目录不存在 ⇒ 项目守卫「宁拒不许猜」拒掉 ⇒
    `test_mem_guard` / `test_pool_*` / `test_wb_plan` 一片红（实测 `assert 1 == 0`、
    `problems == ['项目索引读不了…D:/repo/engineering…']`）。
    """
    tmpl = SCRIPT_DIR / "pool-config" / "projects.toml.tmpl"
    assert tmpl.is_file(), f"没有云机项目索引模板：{tmpl}"
    text = tmpl.read_text(encoding="utf-8")
    assert "__REPO_ROOT__" in text, "模板必须留 `__REPO_ROOT__` 占位（不许写死某台机器的路径）"
    assert 'root = "__REPO_ROOT__"' in text
    # 注释里可以讲「开发机那份指着哪」（那是给人读的），**有效配置行**里不许出现开发机路径。
    effective = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    offenders = [ln for ln in effective if "文档/jelly_ware" in ln]
    assert not offenders, f"模板的有效配置行里还留着开发机路径：{offenders}"
    # 渲染步要真去替换它，且失败要 fail fast
    run_gate = RUN_GATE.read_text(encoding="utf-8")
    assert "0.45/5" in run_gate, "渲染项目索引必须是独立一步（可见的进度条）"
    idx = run_gate.index("0.45/5")
    tail = run_gate[idx : idx + 1600]
    assert "__REPO_ROOT__" in tail, "渲染步要提到占位符"
    assert "exit 6" in tail, "渲染不了必须 fail fast"


def test_step2_seeds_previous_reading_instead_of_trusting_the_commit() -> None:
    """★ 卡 E49：`gates/last.json` / `gates/reuse.json` 是**入库文件**，

    `git clean -xfdq` 只清未跟踪/被忽略文件 ⇒ 清不掉它们；`git checkout -f` 还会把它们
    恢复成提交里那份陈旧读数，被自指钉子当成「上一轮」。
    所以第二步必须**显式删**再断言不在 —— 这条钉子钉住「别退回只靠 clean」。
    """
    script = RUN_GATE.read_text(encoding="utf-8")
    step2_start = script.index("=== 2/5")
    step3_start = script.index("=== 3/5")
    step2 = script[step2_start:step3_start]
    assert "TF_LAST_SEED" in step2, "第二步要支持用本机那份「绿的上一趟」播种"
    assert "last.json" in step2 and "reuse.json" in step2
    assert "scp" in step2, "播种必须是把本机那份传上去（不许沿用提交里的基线）"
    # 播种要发生在断言之前（先放再说「有」）
    assert step2.index("scp") < step2.index("if exist gates")


def test_run_gate_kills_leftover_remote_processes_before_patching() -> None:
    """跑门禁前必须清掉云机上的残留 python（否则补丁在被占的文件上失败）。

    ★ 卡 E49 实测：`ssh` 中途 `Connection reset` 断掉后，云机上的 xdist worker 还活着，
    下一次 `git apply` 报 `unable to unlink 'docs/traceability.toml': Invalid argument` +
    `unable to write file ... Permission denied` —— 补丁半途而废，门禁在**坏树**上跑完，
    读数还"看起来正常"。这是把"跑了一趟"误当成"验了一趟"的典型场面。
    """
    text = RUN_GATE.read_text(encoding="utf-8")
    assert "1.5/5" in text, "清残留必须是补丁/对齐之前的独立一步（可见的进度条）"
    idx = text.index("1.5/5")
    tail = text[idx : idx + 1200]
    assert "Stop-Process" in tail, "要真停掉残留 python 进程（Stop-Process）"
    assert "exit 4" in tail, "清不掉必须 fail fast，不许带着残留继续 apply 补丁"
    assert text.index("1.5/5") < text.index("=== 2/5"), "清残留必须早于对齐/打补丁"


def test_run_gate_checks_out_the_card_tree_commit_not_the_caller_commit() -> None:
    """云机 checkout 的必须是**卡树**的 HEAD，不是调用者（主仓）的 HEAD。

    ★ 卡 E49 pass7 实测：`head="$(git rev-parse HEAD)"` 在调用者 cwd 求值 ⇒ 主仓一往前走，
    云机就 checkout 到主仓 HEAD，而补丁是按卡树 HEAD 做的 diff ⇒
    `git apply` 报 `patch failed: 复盘/交接-重构进度.md:3871`，门禁跑在**错的树**上，
    读数还写得挺像回事。判据：这两行必须带 `git -C`。
    """
    text = RUN_GATE.read_text(encoding="utf-8")
    head_lines = [
        ln.strip() for ln in text.splitlines() if ln.strip().startswith(("head=", "short="))
    ]
    assert head_lines, "找不到 head/short 的赋值行"
    for ln in head_lines:
        assert "git -C" in ln, f"提交号必须从卡树取（当前：{ln}）"
    assert ".wt/$card" in " ".join(head_lines), "取提交号的树必须是 .wt/$card"


def test_run_gate_patch_excludes_the_seeded_baseline_files() -> None:
    """补丁不许带 `gates/last.json` / `gates/reuse.json`（它们由 2/5 步播种）。

    ★ 卡 E49 pass6 实测：这两件是**入库文件**，2/5 步先从本机拷到云机，
    3/5 步再 `git apply` 一份**含它们**的补丁 ⇒
    `error: patch failed: gates/last.json:1 / patch does not apply`，
    整份补丁不生效，门禁跑在裸提交上 —— 出来 14 条红全是假红。
    """
    text = RUN_GATE.read_text(encoding="utf-8")
    assert "diff HEAD --binary" in text, "找不到导出补丁的那一行"
    assert ":(exclude)gates/last.json" in text, "补丁必须排除 gates/last.json（否则与播种冲突）"
    assert ":(exclude)gates/reuse.json" in text, "补丁必须排除 gates/reuse.json（同上）"
    export_at = text.index("diff HEAD --binary")
    assert export_at < text.index(":(exclude)gates/last.json"), "排除要挂在导出补丁这条命令上"
    assert export_at < text.index("=== 3/5"), "排除要在 3/5 传补丁之前生效"


def test_run_gate_seeds_from_a_read_only_dir_and_never_from_the_return_dir() -> None:
    """播种目录 ≠ 回传目录（卡 E49 pass8 实测的第四个坑）。

    原来 `seed_dir` 默认 `.wt/<卡>/gates`，而 `5/5` 又把云机那份读数 scp 回同一个目录
    ⇒ 第二趟播的是**上一趟的红读数**，自指钉子（真 last.json 必须绿）当场判红自己。
    """
    text = RUN_GATE.read_text(encoding="utf-8")
    assert 'seed_dir="${TF_LAST_SEED:-gates/diag/seed-$card}"', (
        "播种源要落在 gates/diag/seed-<卡>（gitignored、只读），不许再用回传目录"
    )
    # 回传仍然落在 .wt/<卡>/gates（那是产物目录，可以被覆盖）
    assert '".wt/$card/gates/last.json"' in text


def test_run_gate_refuses_a_red_seed_snapshot() -> None:
    """播种前必须验「这份读数是不是绿的」—— 拿红读数当上一趟，红的是判据自己。"""
    text = RUN_GATE.read_text(encoding="utf-8")
    assert "exit_code" in text and "sys.exit(4)" in text, (
        "要有绿读数校验（按 exit_code 判，不看 ok 字段的脸色）"
    )
    assert "不许拿红读数当「上一趟」" in text, "拒绝时要讲清为什么、以及怎么补一份绿的"


# ------------------------------------------------- 卡 E54（第二笔）：两个「云机才撞到」的坑
def test_bootstrap_constraints_have_no_extras() -> None:
    """`-c` 是 **constraints** 文件：pip 先驳 extras（`ERROR: Constraints cannot have extras`）。

    ★ 卡 E54 实测：装配清单里写着 `uvicorn[standard]==0.52.4`，`Set-Content $pinsFile` 原样落盘，
    于是 **extras 那份清单被当成约束**喂给 `pip install -e "$Repo[dev]" -c $pinsFile`
    ⇒ 整步退非零、云机一个门禁都不跑。判据：落 constraints 之前必须剥掉 `[...]`，
    而「要装什么」另存一份 requirements（那份**保留** extras）。
    """
    text = _bootstrap_text()
    assert "$pinsOnly" in text, "constraints 必须由剥掉 extras 的那份清单生成"
    assert "-replace '" in text and "[^" in text, "剥法必须是真的正则（不是手抄一份）"
    assert "$reqFile" in text, ("回退用的 requirements 要单独一份"
                               "（extras 是「要装的东西」，不是约束）")
    # 反向：回退分支不许再拿 constraints 当 requirements 装
    assert "-r $pinsFile" not in text, "回退分支拿 -r 去装 constraints ⇒ extras 全丢"


def test_run_gate_escapes_powershell_current_item_variable() -> None:
    """`$_` 在 bash 双引号里会**先在本地展开**，远端收到的是被啃坏的命令。

    ★ 卡 E54 实测：`ssh ... "powershell -Command \"... -notcontains $_.Name ...\""`
    本地把 `$_` 换成上一条命令的最后一个参数 ⇒ 远端 PowerShell 语法错 ⇒ `0.4/5` 退 5，
    而错误信息读起来像「云机上没有配置源」（误导性极强）。判据：必须写成 `\\$_`。
    """
    text = RUN_GATE.read_text(encoding="utf-8")
    assert "$_.Name" in text, "这条钉子得有一行真的用到 PowerShell 的 $_（否则空转）"
    bare = [
        line for line in text.splitlines()
        if "$_.Name" in line and r"\$_.Name" not in line
    ]
    assert not bare, f"这些行里的 $_ 会被本地 bash 先展开：{bare[:1]}"
# ------------------------------------------------- 卡 E84（T-AG591）：断线不许把现场一起弄丢
def _gate_code_lines() -> list[str]:
    """只看 `run_gate.sh` 的**可执行行**：注释里点名解释来龙去脉，不算判据本体。"""
    return [
        ln for ln in RUN_GATE.read_text(encoding="utf-8").splitlines()
        if not ln.lstrip().startswith("#")
    ]


def _region(text: str, start: str, end: str) -> str:
    """切出 `=== <start>` 到 `=== <end>` 之间那一段（两端横幅都算在内）。"""
    i = text.index(start)
    return text[i : text.index(end, i)]


def test_run_gate_keeps_the_ssh_session_alive() -> None:
    """判据 1：一趟门禁约 15 分钟，长连接空闲会被中间设备剪断（卡 A366 那趟本机收到 rc=255）。

    ★ 实测：`SSHOPTS` 原来只有 StrictHostKeyChecking / UserKnownHostsFile / BatchMode，
    **没有 ServerAliveInterval** ⇒ 连接被掐掉时云机上的门禁照跑，本机只看到 rc=255，
    那 15 分钟的 stdout 谁也没去取。保活三项必须挂在**共用的 SSHOPTS** 上。
    """
    code = chr(10).join(_gate_code_lines())
    assert "SSHOPTS=" in code, "要有一份共用的 SSHOPTS（不要每条命令自己拼）"
    seg = code[code.index("SSHOPTS=") : code.index("TMP=")]
    assert "ServerAliveInterval=30" in seg, "SSHOPTS 要每 30 s 探一次（可执行行，不是注释里写写）"
    ve = re.search(r"ServerAliveCountMax=(\d+)", seg)
    assert ve is not None, "要有 ServerAliveCountMax（否则一次探测丢包就判定断线）"
    assert int(ve.group(1)) >= 6, f"容忍次数 {ve.group(1)} 太小：一趟门禁不能一丢包就断线"
    assert "TCPKeepAlive=yes" in seg, "TCP 层也要保活"


def test_run_gate_bounds_the_remote_gate_with_a_timeout() -> None:
    """判据 2：4/5 必须有硬超时；秒数可由 `TF_CLOUD_GATE_TIMEOUT` 覆盖、缺省 3600；124 单独可辨。

    ★ 原来那条 ssh 是裸的：云机挂死时本机就无限等（只有上层 gate_pool 的 3600 s 兜底，
    而那层看不到 4/5 之前任何一步的现场）。
    """
    text = RUN_GATE.read_text(encoding="utf-8")
    step4 = _region(text, "=== 4/5", "=== 5/5")
    assert "TF_CLOUD_GATE_TIMEOUT:-3600" in step4, "超时秒数要可由 env 覆盖、缺省 3600"
    assert 'timeout "$gate_timeout" ssh' in step4, "那条 ssh 必须被 timeout 包住"
    assert '"$rc" = "124"' in step4, "124 是 timeout 的退出码，要单独判（别混进门禁红里）"
    assert "超时" in step4, "超时要给一句人话，不许只报退码"


def test_the_gate_output_is_written_on_the_cloud_side_too() -> None:
    """判据 3：4/5 的 stdout 在云机上也要落一份 —— 断线后这份还在盘上，能补取。

    ★ 卡 A366 实测：4/5 只写本机 `$TMP/gate.out`，传输一断连它一起没了；
    云机那边 22 门其实已经跑完（`C:/eng/gates/last.json` 完整）。
    """
    text = RUN_GATE.read_text(encoding="utf-8")
    step4 = _region(text, "=== 4/5", "=== 5/5")
    assert 'remote_out="C:/eng/gates/diag/cloud-4of5-$card.log"' in step4, (
        "云侧要有一份固定路径的输出（5/5 才知道去哪儿补取）"
    )
    assert "> $remote_out 2>&1" in step4, "重定向要真的挂在远端那条命令上"
    assert step4.index("> $remote_out") > step4.index("ssh $SSHOPTS"), "重定向写在 ssh 之后"
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "gates/diag/" in ignored, "云侧日志只许落在 gitignored 的 gates/diag/（不许入库）"


def test_local_capture_is_written_before_any_scp() -> None:
    """判据 4：ssh 一返回就把本机这一侧落盘，**早于** 5/5 的任何 scp。

    ★ 卡 A366 实测：原来 `cp "$TMP/gate.out" gates/diag/cloud-gate-<卡>.log` 在 5/5 末尾，
    传输断在 4/5 之前 ⇒ 本机只剩 1026 字节，连「这趟是断是超时」都没记下来。
    """
    text = RUN_GATE.read_text(encoding="utf-8")
    step4 = _region(text, "=== 4/5", "=== 5/5")
    assert "gates/diag/cloud-gate-$card.log" in step4, "本机现场必须落在 4/5 段里（不是 5/5）"
    assert "# rc=$rc" in step4, "头部要记 rc 与用时（回来看才知道这趟是断线还是超时）"
    assert 'cat "$TMP/gate.out"' in step4, "要把 ssh 抓到的输出并进那份文件"
    step5 = text[text.index("=== 5/5") :]
    assert 'cp "$TMP/gate.out"' not in step5, "现场的 cp 不许再留在 5/5（那会晚于 scp）"
    assert step4.index("gates/diag/cloud-gate-$card.log") < text.index("=== 5/5"), (
        "落盘必须早于 5/5 横幅"
    )


def test_step5_fetches_everything_best_effort() -> None:
    """判据 5：三项各自 best effort，任何一项取不回都不许中断后面两项、更不许 exit。"""
    text = RUN_GATE.read_text(encoding="utf-8")
    step5 = text[text.index("=== 5/5") :]
    assert "fetch()" in step5, "取回要收成一个函数（三项共用一套重试与话术）"
    assert 'while [ "$try" -le 3 ]' in step5, "要重试（单次丢包就放弃等于没做）"
    for what in ('"$remote_out"', '"$cloud_dir/gates/last.json"', '"$cloud_dir/gates/logs/*.log"'):
        assert what in step5, f"5/5 必须取回 {what}"
    assert step5.count('fetch "') >= 3, "三项都要走 fetch"
    assert "return 0" in step5, "取不回也要正常返回（后面还有两项）"
    head = step5.split("if ! python -X utf8 tools/gate_pool.py", 1)[0]
    assert "exit" not in head, "取回这一段不许 exit —— 一项失败就退，等于把另外两项一起丢"
    assert 'scp $SSHOPTS -i "$KEY" "$HOST:$cloud_dir/gates/last.json"' not in text, (
        "原来那种直连 scp（失败即中断）已换成 fetch"
    )


def test_run_gate_explains_broken_connection_and_timeout() -> None:
    """判据 6：rc=255（传输断）与 rc=124（超时）各给诊断 + 现场路径 + 怎么取回。"""
    text = RUN_GATE.read_text(encoding="utf-8")
    step4 = _region(text, "=== 4/5", "=== 5/5")
    assert '"$rc" = "255"' in step4, "rc=255 要单独判（那是断线，不是门禁红）"
    assert '"$rc" = "124"' in step4, "rc=124 要单独判（超时）"
    blob = chr(10).join(ln for ln in step4.splitlines() if ">&2" in ln)
    for word in ("云机", "现场", "scp"):
        assert word in blob, f"断线/超时的提示里要有「{word}」—— 只报退码等于让人去猜"
    assert "TF_CLOUD_GATE_TIMEOUT" in blob, "超时时要说放宽哪个变量"
