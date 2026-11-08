r"""CI 可复现性判据（卡 E55 · 云门禁加固）。

为什么有它：云门禁的红历史上**反复**来自「本机绿 / 云机红」，而且每次都不是代码坏，
是**环境差**（`docs/subsystems/ci/云门禁-可复现性清单.md` 是这张清单的正文）。判据不
写下来，下一次变配 / 换机 / 换人还会重演同一批假红。

本文件钉两条：

**判据 A —— 云机回传的 `gates/last.json` 必须能证明是云机跑的。**
  判据器 `tools/gate_pool.py::validate_cloud_return` 的 ③ 早就 fail closed，但**生产者
  缺失**：`scripts/run_gates.py` 从来就不写 `host` 字段（全文件 `grep host` 零命中），
  于是 `tools/pool/landing.py` 的落地链读到的 `host` 恒为空 ⇒ 永远「证明不了是云机跑的」
  ⇒ 落地只能 `--commit-only`。这里钉住两半：**写得进去** 与 **没有就必拒**。

**判据 B —— CI 脚本不许依赖本机私有状态。**
  AST 扫 `scripts/cloud/**`（含 `profiles/*.toml`）+ `scripts/run_gates.py`，
  禁硬编码本机盘符路径与 IP。
  白名单每条都写理由（见 `WHITELIST`），并且**白名单本身也被钉住**：多一条、少一条、
  理由空着，都会红 —— 否则白名单会悄悄烂成「什么都放行」。

钉的是**口径**，不是「看起来对了」：

| # | 钉子 | 坏掉会红在哪 |
|---|---|---|
| A1 | `payload` 字典里有 `host` 且值是 `socket.gethostname()` | 删掉那行 ⇒ 落地链永远拒 |
| A2 | `host` 不许塞进 `payload_env_fields()` | 塞进去 ⇒ reuse-line 的键集钉子红 |
| A3 | `seal()` 不重赋值 `host` | seal 抹掉 ⇒ 回传的 last.json 又没 host |
| A4 | 伪造「无 host」的 last.json ⇒ 判据必拒 | 去掉 ③ ⇒ A4 红 |
| A5 | 伪造「host 是别的机器」⇒ 判据必拒 | 去掉 expect_host 分支 ⇒ A5 红 |
| B1 | 扫描范围内无本机私有盘符路径 | 写死 `D:/…` ⇒ B1 红 |
| B2 | 扫描范围内无硬编码 IP（`127.0.0.1` 除外） | 写死云机 IP ⇒ B2 红 |
| B3 | 白名单每条有理由、且无过期条目 | 白名单悄悄膨胀 / 腐烂 ⇒ B3 红 |
| B4 | 反向用例：临时塞进一行 `D:/` ⇒ 扫描器必须报 | 扫描器失灵 ⇒ B4 红 |

★ 全部离线：**不连云机、不跑门禁**（云机实测由主控做；任务书也禁止在云机上跑全量）。
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "tools", Path(__file__).resolve().parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import _cloud_profile as prof  # noqa: E402 —— 测试侧读法（渲染 / 骨架 / profile）
import gate_pool as gp  # noqa: E402

RUN_GATES = ROOT / "scripts" / "run_gates.py"
CLOUD_DIR = ROOT / "scripts" / "cloud"
RUN_GATE_SH = CLOUD_DIR / "run_gate.sh"
PROFILES_DIR = CLOUD_DIR / "profiles"


# ====================================================================== 判据 A
# ---------------------------------------------------------------- A1 生产者：写
def _payload_dict_node(tree: ast.Module) -> ast.Dict:
    """`payload = {…}` 在 run_gates.py 里只出现一处；只认 Assign + Dict。"""
    found: list[ast.Dict] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "payload" for t in node.targets):
            continue
        if isinstance(node.value, ast.Dict):
            found.append(node.value)
    assert len(found) == 1, f"`payload = {{…}}` 应恰好一处，实际 {len(found)} 处"
    return found[0]


def _payload_keys(node: ast.Dict) -> dict[str, ast.expr | None]:
    out: dict[str, ast.expr | None] = {}
    for k, v in zip(node.keys, node.values, strict=False):
        if isinstance(k, ast.Constant) and isinstance(k.value, str):
            out[k.value] = v
    return out


def _run_gates_tree() -> ast.Module:
    # 该文件 2538 处 `\r\r\r\n` + 32 处 lone CR，但 ast.parse 能正常吃下
    return ast.parse(RUN_GATES.read_bytes().decode("utf-8"))


def test_a1_payload_writes_host_from_gethostname() -> None:
    """A1：`payload` 里有 `host`，值是 `socket.gethostname()`。

    去掉这一行 ⇒ 云机回传的 last.json 又没有 host ⇒ 落地链永远判「证明不了是云机跑的」。
    """
    keys = _payload_keys(_payload_dict_node(_run_gates_tree()))
    assert "host" in keys, (
        "payload 没有 host 字段 ⇒ 云机回传的 gates/last.json 证明不了是云机跑的 "
        "（落地链 tools/pool/landing.py 会拒提交）。判据 A 的生产端在这里。"
    )
    assert ast.unparse(keys["host"]) == "socket.gethostname()", (  # type: ignore[arg-type]
        f"payload['host'] 应取机器名（socket.gethostname()），实际 {ast.unparse(keys['host'])!r}"
    )


def test_a1b_socket_is_imported() -> None:
    """A1b：`socket` 已 import —— 那一行是 lone-CR 分隔的，`^import socket$` 匹配不到。"""
    src = RUN_GATES.read_bytes().decode("utf-8")
    assert re.search(r"(?:^|[\r\n])import socket(?:[\r\n]|$)", src), "socket 未 import"


# ------------------------------------------------------------ A2 不许进 env 字段
def test_a2_host_must_not_go_into_payload_env_fields() -> None:
    """A2：`payload_env_fields()` 的键集被 `tests/test_gates_reuse_line.py` **精确**钉成
    `{"python": platform.python_version()}` ⇒ `host` 只能另起一处写，不能塞进去。
    """
    tree = _run_gates_tree()
    fn = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "payload_env_fields":
            fn = node
            break
    assert fn is not None, "找不到 payload_env_fields()"
    ret = next(n for n in ast.walk(fn) if isinstance(n, ast.Return))
    assert isinstance(ret.value, ast.Dict)
    keys = {k.value for k in ret.value.keys if isinstance(k, ast.Constant)}
    assert keys == {"python"}, (
        f"payload_env_fields() 的键集必须恰好 {{'python'}}（tests/test_gates_reuse_line.py "
        f"精锁它），实际 {sorted(keys)} —— host 要另起一处写"
    )


# ------------------------------------------------------------- A3 seal 不许抹掉
def test_a3_seal_does_not_reassign_host() -> None:
    """A3：`seal()` 只重算 `tree/tree_scope/untracked/sealed_at`，**不重建** payload。

    若 seal 重建 payload 或重赋值 host ⇒ 云机跑完 `--seal` 后回传的 last.json 又没 host。
    """
    tree = _run_gates_tree()
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "seal"), None)
    assert fn is not None, "找不到 seal()"

    rebuilt = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "payload" for t in n.targets)
        and isinstance(n.value, ast.Dict)
    ]
    assert not rebuilt, "seal() 重建了整个 payload ⇒ 会丢 host"

    reassigned = {
        n.targets[0].slice.value  # type: ignore[attr-defined]
        for n in ast.walk(fn)
        if isinstance(n, ast.Assign)
        and isinstance(n.targets[0], ast.Subscript)
        and isinstance(n.targets[0].value, ast.Name)
        and n.targets[0].value.id == "payload"
    }
    assert "host" not in reassigned, f"seal() 重赋值了 host：{sorted(reassigned)}"
    assert reassigned, "seal() 一个键都没重赋值 —— 结构变了，重看这条钉子"


# ------------------------------------------------------ A4/A5 消费者：没有就必拒
def _cloud_payload(**over: object) -> dict:
    """一份「五条都过」的云机回传；逐条测试只改动它关心的那一项。"""
    base = {
        "rev": "1ea4be7a",
        "ok": True,
        "host": "gates-runner-host",
        "gates": [{"name": "pytest", "exit_code": 0}, {"name": "ruff", "exit_code": 0}],
        "not_run": [],
    }
    base.update(over)
    return base


def _validate(payload: dict, **over: object) -> list[str]:
    kwargs: dict = dict(
        expected_rev="1ea4be7a",
        expected_doors=["pytest", "ruff"],
        pytest_passed=3303,
        pytest_total=3303,
        workspace_clean=True,
    )
    kwargs.update(over)
    return gp.validate_cloud_return(payload, **kwargs)


def test_a4_forged_last_json_without_host_is_rejected() -> None:
    """A4：**伪造一个没有 host 的 last.json** ⇒ 判据必须拒。

    这就是修复前的云机现场（21 个键里没有 host）。去掉 ③ ⇒ 本钉子红。
    """
    forged = _cloud_payload()
    forged.pop("host")
    problems = _validate(forged)
    assert problems, "没有 host 却没有一个问题 —— 判据失灵，假绿会一路走到落地"
    assert any(p.startswith("③ host") for p in problems), problems
    assert "证明不了是云机跑的" in problems[0] + "".join(problems)

    # 空串 / 纯空白 同样算「没有」—— 悄悄写个 "" 也不能过
    for junk in ("", "   ", None):
        problems = _validate(_cloud_payload(host=junk))
        assert any(p.startswith("③ host") for p in problems), (junk, problems)


def test_a5_forged_last_json_from_other_host_is_rejected() -> None:
    """A5：host 非空但**不是这台云机** ⇒ 给了 `expect_host` 就必须拒（本机冒名）。"""
    problems = _validate(_cloud_payload(host="DEV-HOST"),
                         expect_host="gates-runner-host")
    assert any(p.startswith("③ host") for p in problems), problems
    assert "不是这台云机" in "".join(problems)

    # 对得上就不许乱红（否则云绿也不算数）
    assert _validate(_cloud_payload(), expect_host="gates-runner-host") == []


def test_a6_landing_reads_host_field_name() -> None:
    """A6：落地链读的就是 `payload.get("host")` —— 键名改了 A1 会绿而落地链永远空。

    只读 `tools/pool/landing.py`（该文件在禁改清单里，这里只断言不许我们写错键名）。
    """
    src = (ROOT / "tools" / "pool" / "landing.py").read_bytes().decode("utf-8")
    assert 'payload.get("host")' in src or "payload.get('host')" in src, (
        "落地链不再读 payload['host'] —— A1 写的键名与消费者脱节了"
    )


# ====================================================================== 判据 B
# 扫描范围：CI 会真的在**两台机器**上执行的东西
SCAN_SUFFIXES = {".sh", ".ps1", ".py", ".bash"}
# ★ profiles/*.toml 必须单独加：profile 化之后，仓相关的默认值（R2 那条本机 D 盘路径）
#   从骨架搬进了 profile。只按上面四个后缀扫 ⇒ 它正好落在扫描面之外，R2 会**假绿**。
SCAN_EXTRA = [
    ROOT / "scripts" / "run_gates.py",
    CLOUD_DIR / "pool-config" / "projects.toml.tmpl",
]

# 本机私有盘符路径：`D:\`/`D:/`、`C:/Users/`、`C:/infra/`、`~/.ssh`
_PRIVATE_PATH_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("本机 D 盘", re.compile(r"(?<![A-Za-z])D:[\\/]")),
    ("用户目录", re.compile(r"(?<![A-Za-z])C:[\\/]Users[\\/]", re.I)),
    ("裸 ~/.ssh", re.compile(r"(?<![A-Za-z0-9_])~[\\/]\.ssh[\\/]")),
)

_IP_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
_LOOPBACK = {"127.0.0.1"}

# 白名单：`(相对路径, 规则标签, 子串, 理由)` —— 几条**全部**命中才豁免（逐行判）。
# 门槛：这一行必须在**云机上照样成立**，而不是「在本机上方便」。
# 已尽力把能改的都改成不写死（见 gates/diag/_fix_run_gate_paths.py）：7 → 4 条。
# ★ profile 化之后从骨架搬进 `profiles/*.toml` 的三条也在这里登记（不是整文件豁免：
#   每条只钉一个子串、一行）。
WHITELIST: tuple[tuple[str, str, str, str], ...] = (
    (
        "scripts/cloud/run_gate.sh",
        "裸 ~/.ssh",
        'KEY="$HOME/.ssh/id_ed25519_cloud"',
        "本机 ssh 私钥：这段跑在**本机** bash 里（它去连云机），不是云机侧脚本。"
        "判据 B 要禁的是「云机侧依赖本机状态」，这条方向相反、本来就该在本机。",
    ),
    (
        "scripts/cloud/run_gate.sh",
        "裸 ~/.ssh",
        "云机 SSH 可用（~/.ssh/id_ed25519_cloud）",
        "文件头「前提」注释里的同一条私钥路径（给人读的运行前提），同上，跑在本机侧。",
    ),
    (
        "scripts/cloud/profiles/engineering.toml",
        "本机 D 盘",
        'source_default = "D:/repo/infra/pool"',
        "⚠ **现存债，不是合理**：默认值绑死本机祖父目录（只读它、scp 它）。profile 化之后它"
        "从骨架搬进了这份 profile —— 债没消失、只是换了位置，所以这里也必须登记：不登记它正好"
        "落在扫描面之外（只扫 .sh/.ps1/.py/.bash），B1 会假绿。留着的理由：改成「从脚本位置推」"
        "会改变 Git Bash 下 /d/… vs D:/… 的取值，而本卡不许真跑云门禁 ⇒ 无法端到端验证，"
        "不为好看冒断掉云门禁的险。运维一律显式给 TF_POOL_CFG_SOURCE_DIR。"
        "见 docs/subsystems/ci/云门禁-可复现性清单.md §2 的 R2。",
    ),
    (
        "scripts/cloud/profiles/engineering.toml",
        "本机 D 盘",
        'repo_root = "D:/repo/engineering"',
        "**按设计如此**：profile 就是「每仓一份、描述这台机器上的这个仓」的那层配置"
        "（profile.py 的 cmd_check 把 repo_root 列为必填键），值天然是本机绝对路径。"
        "它**不会流向云机**：骨架 run_gate.sh 对 P_REPO_ROOT 零引用（grep P_REPO_ROOT 零命中）。"
        "哪天骨架开始引用它，这条豁免必须改成「从脚本位置推」。",
    ),
    (
        "scripts/cloud/profiles/openmaic.toml",
        "本机 D 盘",
        'repo_root = "D:/repo/program/OpenMAIC"',
        "同上（第二仓的 profile）：只描述「openmaic 这个仓在这台机器上的位置」，"
        "骨架不消费 P_REPO_ROOT ⇒ 不进云机脚本。它是 profile 的必填键，删不掉。",
    ),
    (
        "scripts/run_gates.py",
        "IP",
        "127.0.0.1",
        "回环：`_is_listening()` 探端口用（与 gates/diag/gate_lock.py 同一套探法）。"
        "回环在两台机器上语义相同，换机器不会变，不构成环境分歧。",
    ),
)


def _scan_targets() -> list[Path]:
    out: list[Path] = []
    if CLOUD_DIR.is_dir():
        for p in sorted(CLOUD_DIR.rglob("*")):
            if p.is_file() and p.suffix in SCAN_SUFFIXES:
                out.append(p)
    # ★ profile 也是「CI 会真的执行的东西」：profile 的值由它填进骨架，等价于脚本的一部分。
    #   只扫四个后缀会让仓相关的私有默认值从扫描面溜走（R2 就是这么藏进去的）。
    if PROFILES_DIR.is_dir():
        profiles = sorted(PROFILES_DIR.glob("*.toml"))
        # ★ 自证：扫不到 .toml 就等于扫描面自己缩水 —— 上面那条 glob 会静默扫空，
        #   R2 又躲回扫描面之外假装不存在。宁可在这里红，也不要 B1 假绿。
        assert profiles, f"{_rel(PROFILES_DIR)} 下一份 profile 都没扫到 —— 扫描面缩水了"
        out.extend(profiles)
    out.extend(p for p in SCAN_EXTRA if p.is_file())
    return [p for p in out if p.exists()]


def _rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


def _find_violations(text: str, rel: str) -> list[tuple[str, int, str]]:
    """返回 `(规则标签, 行号, 行内容)`。白名单命中的跳过。"""
    allowed = [
        (wl_rel, wl_label, wl_sub)
        for wl_rel, wl_label, wl_sub, _ in WHITELIST
        if wl_rel == rel
    ]
    out: list[tuple[str, int, str]] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for label, rx in _PRIVATE_PATH_RULES:
            if not rx.search(line):
                continue
            if any(lab == label and sub in line for _, lab, sub in allowed):
                continue
            out.append((label, lineno, line.strip()))
        for m in _IP_RE.finditer(line):
            if m.group(0) in _LOOPBACK:
                continue
            if any(lab == "IP" and sub in line for _, lab, sub in allowed):
                continue
            out.append(("硬编码 IP", lineno, line.strip()))
    return out


def test_b1_b2_ci_scripts_have_no_private_paths_or_hardcoded_ips() -> None:
    """B1 + B2：扫描范围内不许有本机私有盘符路径、不许有硬编码 IP。

    两件事一起断言是故意的：它们都是「换台机器就变」的字面量，红的时候要一次看全。
    """
    targets = _scan_targets()
    assert targets, "扫描范围是空的 —— 判据 B 形同虚设"

    bad: list[str] = []
    for path in targets:
        rel = _rel(path)
        for label, lineno, line in _find_violations(
                path.read_bytes().decode("utf-8", "replace"), rel):
            bad.append(f"{rel}:{lineno}  [{label}]  {line[:120]}")

    assert not bad, (
        "CI 脚本里出现了本机私有状态（换台机器就变）：\n  "
        + "\n  ".join(bad)
        + "\n\n处置：要么改成环境变量注入，要么在 tests/test_ci_portability.py 的 "
          "WHITELIST 里登记并**写清理由**（理由空着 B3 会红）。"
    )


def test_b2b_no_hardcoded_cloud_ip_anywhere_in_ci() -> None:
    """B2b：不给 `CLOUD_HOST` 时**不许**回落到写死的云机地址。

    历史现场：`run_gate.sh:59` 的默认值是变配前的 `administrator@203.0.113.12`（早已失效）
    —— 「没配就默默去连死机器」，失败现场看起来像网络问题。
    """
    text = RUN_GATE_SH.read_bytes().decode("utf-8")
    m = re.search(r'^HOST="\$\{CLOUD_HOST:-([^}]*)\}"', text, re.M)
    if m is not None:
        pytest.fail(
            f"CLOUD_HOST 仍有默认值 {m.group(1)!r}：云机地址变了它就连死机器。"
            "应该 fail fast（缺配置就退 9），不做默认。"
        )
    assert re.search(r'^HOST="\$CLOUD_HOST"', text, re.M), (
        "找不到 `HOST=\"$CLOUD_HOST\"` —— 约定是显式注入，缺了就 fail fast"
    )
    assert "exit 9" in text, "缺 CLOUD_HOST 必须 fail fast（exit 9）"


def test_b3_whitelist_entries_are_justified_and_live() -> None:
    """B3：白名单**自己**也被钉住 —— 每条有理由、都是四元组、且仍然命中真实文本。

    不做这条，白名单会悄悄烂成「什么都放行」：条目留着、代码早改了，于是下一条真实
    违规也顺带被豁免。
    """
    assert WHITELIST, "白名单空了 —— 若真已清干净，请把这条钉子的断言一起改"
    stale: list[str] = []
    for entry in WHITELIST:
        assert len(entry) == 4, f"白名单条目必须是 (路径, 标签, 子串, 理由)：{entry!r}"
        rel, label, sub, why = entry
        assert why.strip(), f"白名单条目没有理由：{entry!r}"
        assert len(why.strip()) >= 20, f"理由太短（写清为什么它能进白名单）：{entry!r}"
        assert label in {r[0] for r in _PRIVATE_PATH_RULES} | {"IP"}, (
            f"白名单标签 {label!r} 不是已知规则名"
        )
        path = ROOT / rel
        assert path.is_file(), f"白名单指向的文件不存在：{rel}"
        if sub not in path.read_bytes().decode("utf-8", "replace"):
            stale.append(f"{rel} [{label}] {sub!r}")

    assert not stale, (
        "白名单里有**过期**条目（子串已不在文件里）—— 删掉它，否则它会继续豁免别的违规：\n  "
        + "\n  ".join(stale)
    )


def test_b4_reverse_case_scanner_actually_bites() -> None:
    """B4 反向用例：往一份**看起来合法**的脚本里塞违规 ⇒ 扫描器必须报出来。

    没有这条，B1/B2 可能只是「什么都没扫到」而恒绿。
    """
    cases = {
        "D 盘": 'cp -r "D:/repo/engineering" ./\n',
        "用户目录": 'KEY="C:/Users/example/.ssh/id_ed25519_cloud"\n',
        "裸 ~/.ssh": 'scp -i ~/.ssh/id_ed25519_cloud a b\n',
        "硬编码 IP": 'HOST="administrator@203.0.113.10"\n',
    }
    for expect, line in cases.items():
        hits = _find_violations(f"#!/usr/bin/env bash\n{line}", "scripts/cloud/__probe__.sh")
        assert hits, f"反向用例没咬住：{expect} —— 扫描器对这行放行了：{line!r}"
        assert any(h[1] == 2 for h in hits), f"{expect} 命中的行号不对：{hits}"

    # 干净脚本必须**不**报（否则这钉子只会一直红，没人看）
    assert _find_violations('cd C:/eng && python -X utf8 scripts/run_gates.py\n',
                            "scripts/cloud/__probe__.sh") == []


def test_b4b_reverse_case_whitelist_still_observed() -> None:
    """B4b 反向用例：白名单**只豁免登记过的那一行**，不许整文件豁免。

    这是白名单最容易退化的形式：一条命中 ⇒ 整个文件都不查了。
    """
    rel = "scripts/cloud/run_gate.sh"
    text = RUN_GATE_SH.read_bytes().decode("utf-8")
    assert not _find_violations(text, rel), "白名单没生效（现有文件不该有违规）"

    # 同一份文件里**新加**一行本机私有路径 ⇒ 必须被咬（不能被白名单顺带放过）
    tampered = text + 'cp -r "D:/secret/thing" ./\n'
    hits = _find_violations(tampered, rel)
    assert hits, "白名单把整份文件都豁免了 —— 新加的违规也放过了"


# ------------------------------------------------- 判据 B 的「CI 真会跑」自证
def test_b5_run_gate_sh_is_still_syntax_valid() -> None:
    """B5：`run_gate.sh` 改完仍是合法 bash（`bash -n`）。

    它没有 `-e`，语法错不会早退，而是跑到一半炸 —— 所以必须静态验。
    """
    import shutil
    import subprocess

    bash = shutil.which("bash")
    if not bash:
        pytest.skip("本机没有 bash（CI 在 Windows 上跑，靠 git-bash）")
    proc = subprocess.run([bash, "-n", str(RUN_GATE_SH)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert proc.returncode == 0, f"run_gate.sh 语法错：\n{proc.stderr}"
# ============================== 主表（R1–R16）逐行判据：清单里每一行都得有钉子
# 这几条是 `docs/subsystems/ci/云门禁-可复现性清单.md` §2 主表的「判据」列所指的节点。
# 加它们的目的不是「再多几条测试」，而是让那张表**不可能写成纯文字**：
#   test_doc_rows_are_all_machine_checkable 会解析 §2，任何一行引用不存在的节点就红。
AUDIT_PROGRESS = ROOT / "scripts" / "audit_progress.py"
BOOTSTRAP_PS1 = CLOUD_DIR / "bootstrap.ps1"
CHECKLIST_DOC = ROOT / "docs" / "subsystems" / "ci" / "云门禁-可复现性清单.md"


def _src(p: Path) -> str:
    return p.read_bytes().decode("utf-8", "replace")


def _rendered() -> str:
    """engineering profile 渲染后的**平铺脚本** —— R9/R14 这类断言的 haystack。

    ★ 为什么不能读 `run_gate.sh` 原件：profile 化之后，仓相关的值（解释器路径、
      `-m pip install`、两趟 `run_gates.py` 调用）住在 `profiles/engineering.toml`，
      骨架里只剩 `${P_…}` 槽位。对着空槽位断言，锚点必然丢 —— 断言会变成「看不到就说
      不存在」，比红更糟。渲染产物才是 CI 真正执行的那份。
    """
    return prof.render("engineering")


def _bash_step(text: str, tag: str) -> str:
    """取 `=== <tag> …` 到下一个 `=== ` 之间的片段（tag 例如 `3.5/5`）。"""
    start = text.index(f"=== {tag} ")
    nxt = text.find("=== ", start + 4)
    return text[start:] if nxt < 0 else text[start:nxt]


def test_r1_python_version_is_pinned_and_recorded() -> None:
    """R1：Python 版本「钉在云机 3.12.8 / 只记不比对」这件事本身被钉住。

    三件事：① 云机装的是 3.12.8（`bootstrap.ps1`）；② `run_gates.py` 的门槛是**地板** 3.11，
    不是「应为 3.12」；③ `last.json.python` 记了实际版本。

    ★ 第 ④ 条是**债的钉子**：判据器里**没有**拿 `python` 跟某个期望版本比 ——
    这正是 R1 只算「⚠️ 半条」的原因。哪天有人把比对加上了，这条会红，
    那时请把清单 R1 的「修没修」改成 ✅ 并删掉这条断言。
    """
    boot = _src(BOOTSTRAP_PS1)
    assert "3.12.8" in boot, "bootstrap.ps1 不再钉 3.12.8 —— 云机解释器版本漂了"
    assert r"C:\Program Files\Python312" in boot, "bootstrap.ps1 的安装目录不再是 Python312"

    rg = _src(RUN_GATES)
    m = re.search(r"^MIN_PYTHON\s*=\s*\(([^)]*)\)", rg, re.M)
    assert m is not None, "run_gates.py 里找不到 MIN_PYTHON —— 解释器地板没了"
    assert m.group(1).replace(" ", "") == "3,11", (
        f"MIN_PYTHON 变成 ({m.group(1)}) 了：它是**地板**不是目标版本，改它要同步改 bootstrap.ps1"
    )

    tree = _run_gates_tree()
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "payload_env_fields"), None)
    assert fn is not None, "payload_env_fields() 没了 —— last.json 不再记解释器版本"
    body = ast.unparse(fn)
    assert "platform.python_version()" in body, f"payload_env_fields() 没记解释器版本：{body}"

    # ④ 债：判据器里没有「应为 3.12」的比对
    gp_src = _src(ROOT / "tools" / "gate_pool.py")
    assert not re.search(r'"3\.12(\.\d+)?"', gp_src), (
        "gate_pool.py 里出现了期望版本字面量 —— R1 的「只记不比对」已经被修好了？"
        " 请把清单 R1 的「修没修」改成 ✅ 并删掉这条断言。"
    )


def test_r2_local_drive_default_stays_registered_debt() -> None:
    """R2：本机 D 盘默认值是**登记过的债**，不许悄悄消失、也不许悄悄扩散。

    ★ profile 化之后债搬了家：`run_gate.sh` 里只剩 `${P_CFG_SOURCE_DEFAULT:-}` 这个槽位，
      带盘符的字面住在 `scripts/cloud/profiles/engineering.toml` 的 `source_default`。
      本用例对**新位置**钉三头：
      · 值还在 toml 里 ⇒ 清单 R2 的「现状」没写错；
      · 渲染之后仍落到 `cfg_local=` ⇒ 「搬进 profile」没有顺手把取值链改断；
      · 还在 `WHITELIST` 里、且理由 ≥20 字符并点名 R2 ⇒ 它没有被顺手删掉白名单
        （删了 B1/B2 会红），也没有被扩成「整文件放行」（B4b 另有反向用例）。
    """
    # ★ profile 化之后这条债**搬了家**：骨架里只剩一个 cfg_local= 的展开，
    #   带盘符的字面在 profiles/engineering.toml。
    #   所以两头都钉：值还在 toml 里、渲染后仍落到 cfg_local。
    toml_text = _src(PROFILES_DIR / "engineering.toml")
    debt = 'source_default = "D:/repo/infra/pool"'
    assert debt in toml_text, (
        "R2 那行本机 D 盘默认值不见了 —— 若已真改成「从脚本位置推」，"
        "请同步删掉白名单条目并更新清单 R2"
    )
    assert 'cfg_local="${TF_POOL_CFG_SOURCE_DIR:-D:/repo/infra/pool}"' in _rendered(), (
        "profile 里的 source_default 没有渲染进 cfg_local —— 债的位置对了，但取值链断了"
    )
    hits = [e for e in WHITELIST
            if e[0] == "scripts/cloud/profiles/engineering.toml" and e[2] == debt]
    assert len(hits) == 1, f"R2 这条债必须在 WHITELIST 里恰好登记一次，实际 {len(hits)} 次"
    why = hits[0][3]
    assert len(why.strip()) >= 20, "R2 的白名单理由太短"
    assert "R2" in why, "R2 的白名单理由必须点名清单里的 R2（否则读者不知道它为什么还在）"


def test_r9_gate_invocation_carries_utf8_mode() -> None:
    """R9：跑门禁的每一次 python 调用都带 `-X utf8`（本仓铁律）。

    为什么钉：云机 stdout 是 gbk，本机靠私有 `PYTHONIOENCODING=utf-8` 掩盖 ⇒
    少一个 `-X utf8` 就是「本机绿 / 云机红」，而且现场看起来像代码坏。
    """
    rg = _src(RUN_GATES)
    n = rg.count('"-X", "utf8"')
    assert n >= 3, (
        f"run_gates.py 里只有 {n} 处 `-X utf8` —— 至少 pytest / 工具脚本 / 子进程三条链要带"
    )

    # ★ haystack 是**渲染产物**：4/5 的两趟 python 由 profile 的 gate.cmd 填进骨架，
    #   骨架里只剩 ${P_GATE_CMD} ⇒ 对原件断言等于「槽位里没有就说不存在」。
    step4 = _bash_step(_rendered(), "4/5")
    assert step4.count("-X utf8") >= 2, (
        "4/5 没给两趟 python 都带 `-X utf8`（门禁 + seal）—— 看的是渲染后的脚本"
    )


def test_r12_freshness_window_is_naive_local_on_both_sides() -> None:
    """R12：120 秒新鲜度判据是**裸本地钟**比对 —— 时区/钟偏会改判定。

    这是**债的钉子**：不是「证明它安全」，而是「证明它长什么样、别被悄悄改口径」。
    真正的修法（带时区）要动 `last.json` 时间戳格式，本轮不做。
    """
    ap = _src(AUDIT_PROGRESS)
    m = re.search(r"if\s+parent_at\s*-\s*at\s*>\s*timedelta\(seconds=(\d+)\)", ap)
    assert m is not None, "audit_progress.py 的 120 秒新鲜度判据找不到或被改写"
    assert m.group(1) == "120", f"新鲜度窗口变成 {m.group(1)} 秒了（清单 R12 写的是 120）"

    assert re.search(r"at\s*=\s*datetime\.fromisoformat\(at_raw\)\.replace\(tzinfo=None\)", ap), (
        "产物侧时间戳不再按「裸本地钟」解析 —— 口径变了，请同步清单 R12"
    )
    assert re.search(
        r"parent_at\s*=\s*datetime\.fromisoformat\(parent_ts\)\.replace\(tzinfo=None\)", ap
    ), "父提交侧时间戳不再按「裸本地钟」解析 —— 两侧口径必须一致，否则差 8 小时"

    # 生产侧同样不带时区（否则两侧一边带一边不带，判据必然错）
    rg = _src(RUN_GATES)
    assert rg.count('datetime.now().isoformat(timespec="seconds")') >= 2, (
        "run_gates.py 不再用裸 `datetime.now()` 写时间戳 —— 若改成带时区，"
        "请同步 audit_progress.py 的解析并更新清单 R12"
    )
    assert not re.search(r"from datetime import [^\n]*\btimezone\b", rg), (
        "run_gates.py 开始 import timezone 了 —— 时间戳口径在变，请同步清单 R12"
    )


def test_r13_gate_port_falls_inside_a_pool_segment() -> None:
    """R13：云跑法传的端口段必须落在号池的某个 slot 段里，且与门禁默认段不重叠。

    撞段 = 端口占用假红；而门禁锁是**本地文件** ⇒ 两台机器不共享锁，
    「谁在跑这一段」只能靠这个算术 + 人。
    """
    m = re.search(r'^port="\$\{2:-(\d+)\}"', _src(RUN_GATE_SH), re.M)
    assert m is not None, "run_gate.sh 里找不到端口段默认值 `port=\"${2:-<数字>}\"`"
    default_port = int(m.group(1))

    slot4 = gp.port_segment(4)
    assert slot4 == (gp.POOL_PORT_BASE + 4 * gp.SLOT_PORT_STRIDE,
                     gp.POOL_PORT_BASE + 5 * gp.SLOT_PORT_STRIDE - 1), slot4
    assert slot4[0] <= default_port <= slot4[1], (
        f"云跑法默认端口 {default_port} 不在号池 slot 4 的段 {slot4} 里 —— 撞段就会端口占用假红"
    )

    # 门禁自己的默认段（8531）必须落在号池段之外，否则本机跑门禁会撞上号池工人
    rg = _src(RUN_GATES)
    d = re.search(
        r"def port_base\(\)[^\n]*\n(?:.*\n){0,6}?\s*raw\s*=\s*os\.environ\.get\("
        r"\"TF_GATE_PORT_BASE\"",
        rg,
    )
    assert d is not None, "run_gates.py 的 port_base() 结构变了 —— 它的默认端口段没人钉了"
    assert gp.POOL_PORT_BASE > 8531, (
        f"门禁默认段 8531 撞进号池段（起点 {gp.POOL_PORT_BASE}）—— 本机跑门禁会踩工人端口"
    )


def test_r14_gate_runs_on_the_interpreter_that_got_the_deps() -> None:
    """R14：**装依赖的解释器 == 跑门禁的解释器**（本轮修的云门禁真缺陷）。

    历史现场：`3.5/5` 把 `.[dev]` 装进 `"C:/Program Files/Python312/python.exe"`，
    `4/5` 却用裸 `python`（走 PATH）⇒ 门禁可能跑在没装依赖的解释器上，一片假红，
    而 `3.5/5` 看起来还是绿的。

    ★ profile 化之后这两步的**整条命令**都从 profile 渲染出来（`prepare.cmd` / `gate.cmd`），
      骨架里只剩 `${P_PREPARE_CMD}` / `${P_GATE_CMD}` 槽位。⇒ haystack 必须是渲染产物。
      且渲染后是**普通双引号**（TOML 值直接展开，不再套一层 shell 转义），原先把引号写成
      转义形态的正则在这里零命中 —— 那不是「锚点丢了」，是正则盯着旧的那一层。
    """
    text = _rendered()

    step35 = _bash_step(text, "3.5/5")
    mm = re.search(r'"([A-Za-z]:/[^"]*python\.exe)"\s+-m\s+pip\s+install', step35)
    assert mm is not None, "3.5/5 不再是「固定解释器 + -m pip install」，R14 的锚点丢了"
    installs_into = mm.group(1)

    step4 = _bash_step(text, "4/5")
    runners = re.findall(
        r'"([A-Za-z]:/[^"]*python\.exe)"\s+-X\s+utf8\s+scripts/run_gates\.py',
        step4,
    )
    assert len(runners) == 2, (
        f"4/5 应该有**两处**固定解释器调用（门禁 + --seal），实际 {len(runners)} 处"
    )
    assert set(runners) == {installs_into}, (
        f"装依赖的解释器 {installs_into!r} 与跑门禁的 {set(runners)!r} 不是同一个 —— "
        "门禁会跑在没装依赖的解释器上"
    )
    assert " python -X utf8 scripts/run_gates.py" not in text, (
        "渲染后出现了裸 `python -X utf8 scripts/run_gates.py`（走 PATH）—— R14 的修复被回退了"
    )


# --------------------------------------------------- 清单自身：每一行都得能被机器检查
_DOC_REQUIRED_ITEMS = (
    "Python 版本", "种子机制", "补丁排除项", "pip 依赖钉版本", "locale", "行尾",
    "ignore", "时区", "端口段冲突", "host",
)


def _doc_main_table(text: str) -> list[list[str]]:
    """取 §2 主表的行（每行按 `|` 切好、去掉首尾空串与空白）。"""
    start = text.index("## 2.")
    end = text.index("## 3.")
    rows: list[list[str]] = []
    for line in text[start:end].splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if not cells or not re.match(r"^R\d+$", cells[0]):
            continue
        rows.append(cells)
    return rows


def _node_exists(ref: str) -> tuple[bool, str]:
    """`<相对路径>::<用例名>` 是否真的存在（本模块用 import 后取属性，别的文件找 `def`）。"""
    if "::" not in ref:
        return False, "判据单元格里没有 `::`（判据必须是 pytest 节点 id）"
    rel, name = ref.split("::", 1)
    path = ROOT / rel
    if not path.is_file():
        return False, f"文件不存在：{rel}"
    if path.resolve() == Path(__file__).resolve():
        return (hasattr(sys.modules[__name__], name), "" if hasattr(sys.modules[__name__], name)
                else f"本模块没有用例 {name}")
    src = _src(path)
    ok = re.search(rf"^def {re.escape(name)}\b", src, re.M) is not None
    return ok, "" if ok else f"{rel} 里没有 `def {name}`"


def test_doc_rows_are_all_machine_checkable() -> None:
    """清单 §2 主表**自己**被钉住 —— 任何一行不能机器检查，这条就红。

    钉四件事：
      ① 表在、行数够（R1–R16）；
      ② 每行 6 列，`风险等级` 与 `修没修` 非空（不许「待定」式糊弄）；
      ③ 每行的「判据」列里**每一个** `<文件>::<用例>` 都能解析到真节点；
      ④ 任务书要求的项一个都不许漏（Python/种子/补丁/pins/locale/行尾/ignore/时区/端口/host）。

    ★ 这条是本清单「不是纯文字」的唯一保证：删掉某个节点却忘了改表，这里会红。
    """
    assert CHECKLIST_DOC.is_file(), f"清单不存在：{CHECKLIST_DOC}"
    text = _src(CHECKLIST_DOC)
    rows = _doc_main_table(text)
    assert len(rows) >= 16, f"§2 主表只剩 {len(rows)} 行（清单约定 R1–R16 至少 16 行）"

    bad: list[str] = []
    seen_ids: list[str] = []
    for cells in rows:
        rid = cells[0]
        if len(cells) != 6:
            bad.append(f"{rid}: 列数 {len(cells)} ≠ 6（项 / 现状 / 判据 / 风险等级 / 修没修）")
            continue
        seen_ids.append(rid)
        # cells = [#, 项, 现状, 判据, 风险等级, 修没修]
        _, _, _, evidence, risk, fixed = cells
        if not risk:
            bad.append(f"{rid}: 风险等级空着")
        if not fixed:
            bad.append(f"{rid}: 修没修空着")
        refs = re.findall(r"tests/[\w/]+\.py::[A-Za-z0-9_]+", evidence)
        if not refs:
            bad.append(f"{rid}: 判据列里没有任何 pytest 节点 id（判据成了纯文字）")
            continue
        for ref in dict.fromkeys(refs):
            ok, why = _node_exists(ref)
            if not ok:
                bad.append(f"{rid}: 引用的判据解析不到 —— {why}")

    assert seen_ids == [f"R{i}" for i in range(1, len(seen_ids) + 1)], (
        f"§2 主表编号不连续：{seen_ids}"
    )

    items = " ".join(cells[1] for cells in rows if len(cells) == 6)
    missing = [k for k in _DOC_REQUIRED_ITEMS if k not in items]
    assert not missing, f"§2 主表漏了任务书要求的项：{missing}"

    assert not bad, (
        "清单 §2 主表有不能机器检查的行（判据不是钉子，或者行本身没写全）：\n  "
        + "\n  ".join(bad)
        + "\n\n处置：每个「判据」单元格至少写一个能跑的 pytest 节点 id；"
          "新增节点写进本文件或已有的钉子文件，别写进注释。"
    )
