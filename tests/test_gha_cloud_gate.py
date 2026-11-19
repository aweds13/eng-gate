"""GitHub Actions 云门禁（`scripts/cloud/gha/`）的钉子。

这几组判据守的是同一件事：那条把树推上 GitHub、让冻结 workflow 跑门禁的路线，
**今天在仓里、明天也还在仓里**，而且它失败时说的话（退出码）不会被下一个改它的人悄悄改掉。

这些脚本本身跑不动（要远端、要 SSH key、要 windows-latest），所以判据全落在
「可读的东西」上：文件在不在、有没有本机字面、退出码是不是那五个、
两个 helper 在临时目录上行不行。真读数由 GHA 那一趟自己回传。
"""
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GHA = ROOT / "scripts" / "cloud" / "gha"
BUILD = GHA / "build_snapshot.py"
ADAPTER = GHA / "adapter.py"
SHIM = GHA / "conftest_shim.txt"

#: 适配器在快照里必须叫这个名字 —— 冻结的 workflow 最后一步写死它。
ADAPTER_SNAPSHOT_NAME = "test_windows_autostart_e2e.py"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", **kw)


def test_three_files_are_in_git():
    """判据 1：三件进库，且 `git ls-files` 认它们（不是只躺在盘上）。"""
    out = _run(["git", "ls-files", "--", "scripts/cloud/gha"]).stdout
    tracked = {ln.strip() for ln in out.splitlines() if ln.strip()}
    for p in (BUILD, ADAPTER, SHIM):
        rel = p.relative_to(ROOT).as_posix()
        assert rel in tracked, f"{rel} 没进 git —— 只在盘上的脚本换个机器就没了"


def test_build_snapshot_help_has_the_three_switches():
    """判据 1：`--help` 能跑，且三个关键开关都在（它们是「换仓不改代码」的入口）。"""
    p = _run([sys.executable, "-X", "utf8", str(BUILD), "--help"])
    assert p.returncode == 0, p.stderr[-1200:]
    for flag in ("--stage", "--dest", "--remote"):
        assert flag in p.stdout, f"--help 里没有 {flag}"


def test_adapter_snapshot_name_is_pinned():
    """判据 1：适配器装成哪个名字是**判据**，不是实现细节。"""
    src = BUILD.read_text(encoding="utf-8")
    assert ADAPTER_SNAPSHOT_NAME in src, (
        f"构建脚本里没有把适配器装成 {ADAPTER_SNAPSHOT_NAME} —— 冻结的 workflow "
        "最后一步写死这个名字，改了它作业就一条用例都收集不到"
    )


def test_no_private_paths_or_ips_under_gha():
    """判据 2：`scripts/cloud/gha/**.py` 零本机字面、零硬编码 IP。"""
    rules = (
        ("本机 D 盘", re.compile(r"^[^#]*?(?<![A-Za-z])D:[\\/]")),
        ("用户目录", re.compile(r"^[^#]*?(?<![A-Za-z])C:[\\/]Users[\\/]", re.I)),
        ("裸 ~/.ssh", re.compile(r"^[^#]*?(?<![A-Za-z0-9_])~[\\/]\\.ssh[\\/]")),
    )
    ip_rx = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
    bad = []
    for path in sorted(GHA.glob("*.py")):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for label, rx in rules:
                if rx.search(line):
                    bad.append(f"{path.name}:{i} [{label}] {line.strip()[:80]}")
            for m in ip_rx.finditer(line):
                if m.group(0) != "127.0.0.1":
                    bad.append(f"{path.name}:{i} [硬编码 IP] {line.strip()[:80]}")
    assert not bad, "这些行带着本机字面（换台机器就跑不动）：\n" + "\n".join(bad)


def test_portability_whitelist_was_not_extended_for_gha():
    """判据 2 的反面：**不许**用白名单条目把上面那条绕过去。"""
    src = (ROOT / "tests" / "test_ci_portability.py").read_text(encoding="utf-8")
    assert "scripts/cloud/gha" not in src, (
        "可移植性判据的白名单里出现了 scripts/cloud/gha —— 那是把判据改成"
        "「这件事我不管」，不是把脚本改干净"
    )


def test_exit_codes_are_five_distinct_values():
    """判据 3：五个失败码互不相同，且每个都在源码里真实被用过。"""
    mod = _load(BUILD, "gha_build_snapshot_for_exit_codes")
    codes = {
        "EXIT_CONFIG": mod.EXIT_CONFIG,
        "EXIT_HISTORY": mod.EXIT_HISTORY,
        "EXIT_COMMIT": mod.EXIT_COMMIT,
        "EXIT_SNAPSHOT": mod.EXIT_SNAPSHOT,
        "EXIT_POOL": mod.EXIT_POOL,
    }
    assert mod.EXIT_OK == 0
    assert len(set(codes.values())) == 5, f"五个失败码有重复：{codes}"
    src = BUILD.read_text(encoding="utf-8")
    for name, value in codes.items():
        assert value != 0, f"{name} 不能是 0（0 是成功）"
        assert re.search(r"\b" + name + r"\b", src), f"源码里没有用 {name}"
        assert re.search(r"(sys\.exit|return)\s*\(?\s*" + name + r"\b", src), (
            f"{name} 定义了却没有任何 sys.exit/return 用它 —— 那就是个装饰"
        )


def test_each_failure_has_a_readable_tag():
    """判据 3：失败时都打一句人话（读日志的人靠它判断是哪一段坏）。"""
    src = BUILD.read_text(encoding="utf-8")
    for tag in (
        "MISSING_REMOTE",
        "MISSING_GIT_SSH_COMMAND",
        "BUNDLE_FAILED",
        "FETCH_FAILED",
        "COMMIT_FAILED",
        "MISSING_EVIDENCE_FILE",
        "MISSING_POOL_STUB",
        "POOL_STUB_INCOMPLETE",
        # 卡 E145：两个缺口收口后新出现的两句 —— 缺快照目录、冒烟红了。
        "MISSING_DEST",
        "SMOKE_FAILED",
    ):
        assert tag in src, f"源码里没有失败标签 {tag} —— 换了码却没人看得懂"


def test_missing_dest_fails_fast_with_config_code(tmp_path):
    """判据 1：快照目录不存在 ⇒ 退 2 + MISSING_DEST，**不是** traceback（卡 E145 问题 1）。"""
    dest = tmp_path / "no-such-snapshot"
    env = dict(os.environ)
    env["GHA_REMOTE"] = "git@example.invalid:someone/repo.git"
    env["GIT_SSH_COMMAND"] = "ssh -i /dev/null"
    p = _run([sys.executable, "-X", "utf8", str(BUILD), "--stage", "smoke",
              "--dest", str(dest), "--tmp", str(tmp_path / "tmp")], env=env)
    assert p.returncode == 2, (
        f"缺快照目录却退了 {p.returncode}（2 才是「环境没准备好」）：\n"
        + (p.stdout + p.stderr)[-2000:]
    )
    assert "MISSING_DEST" in p.stdout, "退 2 了但没说缺的是哪一样：" + p.stdout[-800:]
    assert "Traceback" not in p.stderr, "还是抛了栈 —— 调用方分不清是环境问题还是脚本坏了"
    assert not dest.exists(), "判完还顺手造了目录"


def test_smoke_red_is_not_green(tmp_path, capsys):
    """判据 2：冒烟任一段红 ⇒ 退 5（EXIT_SNAPSHOT），不许退 0（卡 E145 问题 2）。"""
    import types

    mod = _load(BUILD, "gha_build_snapshot_for_smoke_red")
    dest = tmp_path / "snapshot"
    dest.mkdir()
    args = types.SimpleNamespace(dest=str(dest), adapter=str(ADAPTER))

    class _Red:
        returncode = 1
        stdout = ""
        stderr = ""

    real_sh = mod.sh
    mod.sh = lambda *a, **kw: _Red()
    try:
        with pytest.raises(SystemExit) as ei:
            mod.do_smoke(args)
        assert ei.value.code == mod.EXIT_SNAPSHOT, (
            f"冒烟红了却退 {ei.value.code}（该退 {mod.EXIT_SNAPSHOT}）"
        )
        out = capsys.readouterr().out
        assert "SMOKE_FAILED" in out, "退 5 了但日志里没有 SMOKE_FAILED：" + out[-800:]

        # 正面控制：三段全绿时**不许**退（否则这条判据会退化成「永远退 5」）
        class _Green:
            returncode = 0
            stdout = ""
            stderr = ""

        mod.sh = lambda *a, **kw: _Green()
        mod.do_smoke(args)   # 没有 SystemExit 就是通过
    finally:
        mod.sh = real_sh


def test_adapter_is_inert_on_a_local_machine(tmp_path):
    """判据 4：本机 collect 到直接绿、且不写任何文件。"""
    tests = tmp_path / "tests"
    tests.mkdir()
    dst = tests / ADAPTER_SNAPSHOT_NAME
    dst.write_bytes(ADAPTER.read_bytes())
    env = {k: v for k, v in os.environ.items()
           if k not in ("GITHUB_ACTIONS", "GHA_GATE_ADAPTER")}
    p = _run([sys.executable, "-X", "utf8", "-m", "pytest", "-q", "-o", "addopts=",
              "-p", "no:cacheprovider", str(dst)], cwd=str(tmp_path), env=env)
    assert p.returncode == 0, (p.stdout + p.stderr)[-2500:]
    written = [x.relative_to(tmp_path).as_posix() for x in tmp_path.rglob("*")
               if ".pytest_cache" not in x.as_posix() and "__pycache__" not in x.as_posix()]
    new = [x for x in written if x.startswith(("gates/", "infra/"))]
    assert not new, f"本机跑一遍就写出了这些文件：{new}"


def test_adapter_guards_against_recursion(tmp_path):
    """判据 4 的反面：`GHA_GATE_ADAPTER=1` 时不干活（门禁自己的 pytest 会收集到它）。"""
    tests = tmp_path / "tests"
    tests.mkdir()
    dst = tests / ADAPTER_SNAPSHOT_NAME
    dst.write_bytes(ADAPTER.read_bytes())
    env = dict(os.environ)
    env["GHA_GATE_ADAPTER"] = "1"
    env["GITHUB_ACTIONS"] = "true"   # 故意让「在云上」成立，看门那一条咬不咬
    p = _run([sys.executable, "-X", "utf8", "-m", "pytest", "-q", "-o", "addopts=",
              "-p", "no:cacheprovider", str(dst)], cwd=str(tmp_path), env=env)
    assert p.returncode == 0, (p.stdout + p.stderr)[-2500:]
    assert not (tmp_path / "gates").exists(), "被拦住了却还是写了 gates/"


def test_pool_stub_is_written_outside_the_repo(tmp_path):
    """判据 5：号池桩落在 `ROOT/../infra/pool`，返回 projects.toml，仓内不出现 infra/。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    mod = _load(ADAPTER, "gha_adapter_stub")
    mod.ROOT = str(repo)
    projects = Path(mod._ensure_pool_stub())
    pool = tmp_path / "infra" / "pool"
    assert projects == pool / "projects.toml"
    for name in ("pool_models.py", "models.whitelist.toml", "models.live.json",
                 "accounts.toml", "projects.toml"):
        assert (pool / name).exists(), f"桩缺 {name}"
    assert not (repo / "infra").exists(), "桩写进仓里了 —— 那是另一个仓的东西"
    assert repo.as_posix() in projects.read_text(encoding="utf-8"), (
        "projects.toml 的 root 没指向这棵树"
    )
    acc = (pool / "accounts.toml").read_text(encoding="utf-8")
    assert "kind" in acc and "locator" in acc, "桩里的凭据要写成「位点」而不是内容"
    low = acc.lower()
    assert "password" not in low and "secret" not in low and "token" not in low, (
        "桩里出现了凭据内容 —— 它会随快照推到远端仓"
    )


def test_diag_fixtures_are_three_files_under_gates(tmp_path):
    """判据 5：三份派活日志 fixture 写进 `ROOT/gates/diag/`（进不了提交面）。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    mod = _load(ADAPTER, "gha_adapter_fixtures")
    mod.ROOT = str(repo)
    mod._ensure_diag_fixtures()
    names = sorted(p.name for p in (repo / "gates" / "diag").glob("wb-*.jsonl"))
    assert len(names) == len(mod.FIXTURES) == 3, names
    assert names == sorted(mod.FIXTURES)


def test_conftest_shim_only_registers_cov_options():
    """垫片只补 `--cov*` 六个占位，**不许**顺手改判据。"""
    text = SHIM.read_text(encoding="utf-8")
    assert "pytest_addoption" in text
    for opt in ("--cov", "--cov-report", "--cov-fail-under", "--cov-config",
                "--no-cov", "--cov-branch"):
        assert opt in text, f"垫片没注册 {opt} —— runner 上 pytest 会在收集前就退出"
    assert "import pytest_cov" in text, "垫片要先探测真插件在不在，装了就不能抢它的参数"
