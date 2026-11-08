"""云门禁泛用化：**骨架不认识任何仓** + **每仓一份 profile** —— 这一层的钉子。

为什么需要这一层：
  卡 E35 那批钉子（tests/test_cloud_sync.py）问的是「**engineering 这趟端到端会怎么做**」，
  它们现在读渲染结果（骨架 + profiles/engineering.toml），所以它们挡住的是「engineering 行为变了」。
  但**没有一条**挡住反方向：「骨架里又偷偷写回一个 engineering 字面」——
  那种改动会让第二仓静默跑错树，而不是红。这个文件补这一针。

四条判据：
  ① 骨架的**可执行行**里没有 engineering 专属字面（注释里点历史可以，代码里不行）。
  ② profiles/openmaic.toml 全文（含注释）没有 engineering 专属键 —— 验收③。
  ③ 两份 profile 都能读（profile.py check rc=0），且**把这趟要用的键全给齐了**：
     渲染时不许出现「骨架引用了 profile 没给的键」——那种缺键会静默渲染成空串、
     让某一步空转（＝门禁少跑一段而没人知道），比红更危险。
  ④ engineering 的渲染结果必须逐字还原那几个历史字面（证明 profile 真的把行为搬回来了，
     而不是「测试读不到就放宽了」）。
"""

from __future__ import annotations

import subprocess
import sys

import _cloud_profile as prof
import pytest

ROOT = prof.ROOT

# 骨架里**不许**出现的 engineering 字面：仓名/目录、分支、池配置注入、模型白名单、
# 门禁入口、解释器与依赖钉版本、云机日志名。
ENGINEERING_ONLY = (
    "C:/eng",
    "line/impl-v1",
    "TF_PROJECTS_TOML",
    "models.whitelist",
    "C:/infra/pool",
    "run_gates.py",
    "C:/pins.txt",
    "Python312",
    "cloud-4of5",
)

# openmaic 那份 profile 里一条都不许有（验收③）：连注释也算。
NOT_IN_SECOND_PROFILE = (
    "TF_PROJECTS_TOML",
    "models.whitelist",
    "line/impl-v1",
    "C:/infra/pool",
    "run_gates.py",
)


def _code_lines(text: str) -> list[tuple[int, str]]:
    """只留**可执行行**：整行注释不算（注释里点名历史不等于代码依赖它）。"""
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        out.append((i, line))
    return out


def test_skeleton_does_not_know_any_repo() -> None:
    """① 骨架只认键：可执行行里出现 engineering 字面 ⇒ 第二仓会静默跑错树。"""
    hits = [
        (i, lit, line.strip())
        for i, line in _code_lines(prof.skeleton())
        for lit in ENGINEERING_ONLY
        if lit in line
    ]
    assert not hits, (
        "scripts/cloud/run_gate.sh 的可执行行里还有 engineering 专属字面"
        "（要挪进 scripts/cloud/profiles/engineering.toml，用 ${P_<键>} 引用）：\n"
        + "\n".join(f"  :{i} [{lit}] {s}" for i, lit, s in hits)
    )


def test_second_profile_has_no_first_repo_keys() -> None:
    """② 验收③：第二仓的 profile 里一条 engineering 专属键都不许出现（注释也算）。"""
    text = prof.profile_path("openmaic").read_text(encoding="utf-8")
    hits = [lit for lit in NOT_IN_SECOND_PROFILE if lit in text]
    assert not hits, f"profiles/openmaic.toml 混进了 engineering 专属键：{hits}"


@pytest.mark.parametrize("name", ["engineering", "openmaic"])
def test_profile_is_readable(name: str) -> None:
    """③a 两份 profile 都要能过 check（键名拼错/类型不对在这里就红，不必等云机）。"""
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", str(prof.CLOUD / "profile.py"), "check",
         "--profile", str(prof.profile_path(name)), "--card", "T1"],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert proc.returncode == 0, f"{name} 的 profile 读不出来：\n{proc.stdout}\n{proc.stderr}"


@pytest.mark.parametrize("name", ["engineering", "openmaic"])
def test_render_has_no_missing_key(name: str) -> None:
    """③b 骨架引用的每个 ${P_<键>} 都必须有 profile 给值。

    缺键的后果不是红，是**静默空转**：某一步整段不执行、门禁少跑一段而读数照样绿。
    profile.py render 会在 stderr 打「⚠ 骨架引用了 profile 没给的键」，这里把它变成红。
    """
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", str(prof.CLOUD / "profile.py"), "render",
         "--skeleton", str(prof.RUN_GATE), "--profile", str(prof.profile_path(name))],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert proc.returncode == 0, f"{name} 渲染失败：\n{proc.stderr}"
    assert "profile 没给的键" not in proc.stderr, (
        f"{name} 的 profile 缺键（这些步骤会静默空转）：\n{proc.stderr}"
    )


def test_engineering_render_restores_the_historical_literals() -> None:
    """④ engineering 的行为是**搬**过去的，不是放宽掉的：这几个历史字面必须还原。"""
    text = prof.render("engineering")
    expected = [
        # 4/5 的云机现场日志（唯一一处与 cloud_dir 自相矛盾的历史硬编码，卡 E84 的现场）
        'remote_out="C:/eng/gates/diag/cloud-4of5-$card.log"',
        # 2/5 的播种源：必须落在 gitignored 的 seed-<卡>，不许回传目录（卡 E49 pass8）
        'seed_dir="${TF_LAST_SEED:-gates/diag/seed-$card}"',
        # 3.5/5 装依赖的解释器与钉版本文件（R14：装依赖的 == 跑门禁的）
        '".[dev]"',
        "C:/pins.txt",
        # 0.4/5 的铺位（门禁工具从 cwd 逐级向上找 infra/pool）
        'pool_cfg_dst="${TF_POOL_CFG_DST:-C:/infra/pool}"',
        # 0.35/5 的白名单只推这几份（卡 E54：不许把私有账本推上云机）
        "models.whitelist.toml",
        # 0.45/5 的模板占位符（替换成云机仓库根）
        "__REPO_ROOT__",
        # 4/5 的超时口子（rc=124 单独报）
        'gate_timeout="${TF_CLOUD_GATE_TIMEOUT:-3600}"',
    ]
    missing = [e for e in expected if e not in text]
    assert not missing, (
        "engineering 的渲染结果里丢了这些历史字面（profile 没把行为搬全）：\n  "
        + "\n  ".join(missing)
    )
