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

#: 每仓一份适配层（键的语义见 gate_profile.py 的 SCHEMA）。
PROFILE_LOADER = GHA / "gate_profile.py"
PROFILES = GHA / "profiles"


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
    for p in (BUILD, ADAPTER, SHIM, PROFILE_LOADER, PROFILES / "engineering.toml",
              PROFILES / "openmaic.toml"):
        rel = p.relative_to(ROOT).as_posix()
        assert rel in tracked, f"{rel} 没进 git —— 只在盘上的脚本换个机器就没了"


def test_build_snapshot_help_has_the_three_switches():
    """判据 1：`--help` 能跑，且三个关键开关都在（它们是「换仓不改代码」的入口）。"""
    p = _run([sys.executable, "-X", "utf8", str(BUILD), "--help"])
    assert p.returncode == 0, p.stderr[-1200:]
    for flag in ("--stage", "--dest", "--remote"):
        assert flag in p.stdout, f"--help 里没有 {flag}"


def test_adapter_snapshot_name_is_pinned():
    """判据 1：适配器装成哪个名字是**判据**，不是实现细节（现在钉在 profile 里）。"""
    src = (PROFILES / "engineering.toml").read_text(encoding="utf-8")
    assert ADAPTER_SNAPSHOT_NAME in src, (
        f"engineering profile 里没有把适配器装成 {ADAPTER_SNAPSHOT_NAME} —— 冻结的 workflow "
        "最后一步写死这个名字，改了它作业就一条用例都收集不到"
    )
    # 反面：名字不许再回到骨架里 —— 那是「每仓一份」退化成 engineering 专用脚本的征兆。
    build = BUILD.read_text(encoding="utf-8")
    assert ADAPTER_SNAPSHOT_NAME not in build, (
        "适配器文件名又写回 build_snapshot.py 了 —— 骨架只该问 profile「装到哪」")


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


def test_stage_all_on_a_fresh_dest_is_not_blocked_by_missing_dest(tmp_path, capsys):
    """`--stage all` 是「从头造」：全新 dest 不许被 MISSING_DEST 挡成退 2（2026-11-21 实测）。

    这条钉子来自一次真事故：`--stage all` 在全新目录上直接退 2，日志只有一行
    `MISSING_DEST …` —— 而 dest 正是**这一趟要造**的东西。判据只该管 smoke / push
    （它们必须在已有的快照上干活）。
    """
    mod = _load(BUILD, "gha_build_snapshot_for_stage_all")
    calls = []
    mod.do_build = lambda a: calls.append("build")
    mod.do_smoke = lambda a: calls.append("smoke")
    mod.do_push = lambda a: calls.append("push")
    dest = tmp_path / "brand-new-snapshot"
    env = {"GHA_REMOTE": "git@example.invalid:someone/repo.git",
           "GIT_SSH_COMMAND": "ssh -i /dev/null"}
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        rc = mod.main(["--stage", "all", "--dest", str(dest), "--tmp", str(tmp_path / "tmp")])
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    out = capsys.readouterr().out
    assert "MISSING_DEST" not in out, "全新 dest 上 --stage all 又被挡了：" + out[-600:]
    assert rc == 0, f"--stage all 没走完（rc={rc}）：" + out[-600:]
    assert calls == ["build", "smoke", "push"], calls

def test_smoke_red_is_not_green(tmp_path, capsys):
    """判据 2：冒烟任一段红 ⇒ 退 5（EXIT_SNAPSHOT），不许退 0（卡 E145 问题 2）。"""
    import types

    mod = _load(BUILD, "gha_build_snapshot_for_smoke_red")
    dest = tmp_path / "snapshot"
    dest.mkdir()
    # 冒烟跑什么由 profile 说（engineering 那份 = 定向 pytest + ruff + check_docs）
    prof = mod.gate_profile.load("engineering")
    args = types.SimpleNamespace(dest=str(dest), adapter=str(ADAPTER), profile=prof)

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

# ---------------------------------------------------------------------------
# 第二仓：骨架真的不认仓，靠的是 profiles/<仓>.toml 这一层。
# ---------------------------------------------------------------------------

#: 这些字面只要还在骨架里，就说明「每仓一份」退化成了一份 engineering 专用脚本。
ENGINEERING_ONLY_LITERALS = (
    ADAPTER_SNAPSHOT_NAME,
    "T-AG526",
    "gate: engineering",
    "models.whitelist.toml",
)


def test_skeleton_has_no_repo_specific_literals():
    """判据 1 的反面：骨架（build_snapshot.py）里不许再有 engineering 的形状。"""
    src = BUILD.read_text(encoding="utf-8")
    bad = [lit for lit in ENGINEERING_ONLY_LITERALS if lit in src]
    assert not bad, (
        f"骨架里还写死着 {bad} —— 那是「每仓一份适配层」还没抽干净；"
        "第二仓只能靠复制脚本才用得上，两份必然各自漂移"
    )


def test_every_profile_in_the_directory_loads():
    """判据 1：profiles/ 里每一份都得读得动（拼错的键静默生效 = 配置没人读）。"""
    mod = _load(PROFILE_LOADER, "gha_gate_profile_for_profiles")
    names = mod.list_repos()
    assert "engineering" in names and "openmaic" in names, (
        f"profiles/ 里没有这两份：{names} —— 第二仓的适配层必须在仓里，不能只在本机"
    )
    for name in names:
        prof = mod.load(name)   # 不抛 = 通过
        assert prof["name"] == name
        assert prof["message"], f"{name}.toml 没给提交标题行"


def test_second_repo_profile_has_no_engineering_keys():
    """验收③：第二仓那份 profile 里，engineering 专属键一个都不许出现。"""
    text = (PROFILES / "openmaic.toml").read_text(encoding="utf-8")
    for key in ("TF_PROJECTS_TOML", "models.whitelist.toml", "line/impl-v1"):
        assert key not in text, (
            f"openmaic profile 里出现了 engineering 专属的 {key} —— "
            "那说明适配层还是照着 engineering 抄的，换个仓就再抄一份"
        )


def test_second_repo_profile_turns_the_engineering_machinery_off():
    """判据 2：node 腿不该被 python 那套机械连坐（适配器/号池桩/台账 trailer 全关）。"""
    mod = _load(PROFILE_LOADER, "gha_gate_profile_for_second_repo")
    prof = mod.load("openmaic")
    assert prof["adapter"]["enabled"] is False, "node 腿不需要 python 适配器"
    assert prof["pool"]["stub"] is False, "这个仓没有号池"
    assert prof["snapshot"]["ledger_exempt"] == [], "这个仓没有台账，不该写豁免块"
    assert prof["task"] == "", "没有台账却写 Task trailer = 伪造出处"
    assert prof["snapshot"]["from_remote_workflows"] is False, (
        "这个仓的 workflow 归它自己；去远端取会把它自己那份换掉"
    )
    assert prof["smoke"]["commands"], "至少得跑一条真的判据，不能「配不上就跳过」"


def test_unknown_repo_fails_fast_with_config_code(tmp_path):
    """判据 3：`--repo` 指到不存在的 profile ⇒ 退 2 + PROFILE_INVALID（不是 traceback）。"""
    env = dict(os.environ)
    env["GHA_REMOTE"] = "https://example.invalid/someone/repo.git"
    p = _run([sys.executable, "-X", "utf8", str(BUILD), "--repo", "no-such-repo",
              "--stage", "smoke", "--dest", str(tmp_path / "snap"),
              "--tmp", str(tmp_path / "tmp")], env=env)
    assert p.returncode == 2, (
        f"profile 不存在却退了 {p.returncode}（2 才是「配置没准备好」）：\n"
        + (p.stdout + p.stderr)[-1500:]
    )
    assert "PROFILE_INVALID" in p.stdout, "退 2 了但没说坏在哪：" + p.stdout[-800:]
    assert "Traceback" not in p.stderr, "还是抛了栈 —— 调用方分不清是配置还是脚本坏了"


def test_second_repo_missing_dest_does_not_ask_for_python_pieces(tmp_path):
    """判据 3：node 腿缺快照目录时，**不许**先抱怨 python 适配器/垫片/私钥。"""
    env = dict(os.environ)
    env["GHA_REMOTE"] = "https://example.invalid/someone/repo.git"
    env.pop("GIT_SSH_COMMAND", None)
    env.pop("GITHUB_ACTIONS", None)
    p = _run([sys.executable, "-X", "utf8", str(BUILD), "--repo", "openmaic",
              "--stage", "smoke", "--dest", str(tmp_path / "no-such"),
              "--tmp", str(tmp_path / "tmp")], env=env)
    out = p.stdout + p.stderr
    assert p.returncode == 2, out[-1500:]
    assert "MISSING_DEST" in p.stdout, "没说是快照目录不在：" + out[-800:]
    for tag in ("MISSING_ADAPTER", "MISSING_CONFTEST_SHIM", "MISSING_GIT_SSH_COMMAND"):
        assert tag not in p.stdout, (
            f"node 腿去要了 {tag} —— 那是 engineering 那条 ssh + python 的机械，"
            "第二仓不该被它连坐"
        )


# ---------------------------------------------------------------------------
# 两根新骨头：装 workflow、静态判「这棵树是不是我以为的那棵」。
# ---------------------------------------------------------------------------


def test_require_text_bites_when_the_tree_is_wrong(tmp_path, capsys):
    """`[snapshot].require_text` 必须真的咬人：缺字样 ⇒ 退 5，不是打一行日志继续。

    它挡的是「装错树」这类最贵的失败 —— 装依赖十几分钟，装完才发现跑的不是那个仓。
    """
    mod = _load(BUILD, "gha_build_snapshot_for_require_text")
    (tmp_path / "package.json").write_text('{"engines": {"node": ">=20.0.0"}}', encoding="utf-8")
    item = [{"path": "package.json", "needle": '"node": ">=22.19.0"'}]
    with pytest.raises(SystemExit) as exc:
        mod._require_text(str(tmp_path), item)
    assert exc.value.code == mod.EXIT_SNAPSHOT, (
        f"装错树却退了 {exc.value.code}（5 才是「快照形状不对」）"
    )
    out = capsys.readouterr().out
    assert "MISSING_REQUIRED_TEXT" in out, "退 5 了但没说是哪一件缺字样：" + out[-600:]
    assert "package.json" in out, "没点名是哪份文件：" + out[-600:]

    # 反面：字样在 ⇒ 不抛（否则这条判据就是「永远红」）
    (tmp_path / "package.json").write_text('"node": ">=22.19.0"', encoding="utf-8")
    mod._require_text(str(tmp_path), item)


def test_require_text_reports_unreadable_file_not_a_traceback(tmp_path, capsys):
    """文件根本不在 ⇒ 也要算「不一致」退 5，**不是** OSError 的栈。"""
    mod = _load(BUILD, "gha_build_snapshot_for_require_text_missing")
    item = [{"path": "nope.json", "needle": "x"}]
    with pytest.raises(SystemExit) as exc:
        mod._require_text(str(tmp_path), item)
    assert exc.value.code == mod.EXIT_SNAPSHOT
    out = capsys.readouterr().out
    assert "nope.json" in out and "读不到" in out, out[-600:]


def test_workflow_install_missing_src_fails_fast_with_config_code(tmp_path, capsys):
    """`[workflow].install` 指的源文件不在 ⇒ 退 2 + MISSING_WORKFLOW_SRC（不是 traceback）。"""
    mod = _load(BUILD, "gha_build_snapshot_for_workflow_install")
    with pytest.raises(SystemExit) as exc:
        mod._install_workflows(str(tmp_path), [{"src": "no-such-workflow.yml",
                                              "dst": ".github/workflows/x.yml"}])
    assert exc.value.code == mod.EXIT_CONFIG, "缺源文件是配置问题（2），不是快照形状（5）"
    assert "MISSING_WORKFLOW_SRC" in capsys.readouterr().out


def test_workflow_install_writes_into_the_snapshot(tmp_path):
    """正面：一个真源文件确实被拷进快照的 `<dst>`（骨架不写死装哪一份）。"""
    mod = _load(BUILD, "gha_build_snapshot_for_workflow_copy")
    mod._install_workflows(str(tmp_path), [{"src": "conftest_shim.txt",
                                           "dst": ".github/workflows/probe.yml"}])
    out = tmp_path / ".github" / "workflows" / "probe.yml"
    assert out.is_file(), "workflow 没落进快照 —— 推上去一条作业都不会起"
    assert out.read_bytes() == (GHA / "conftest_shim.txt").read_bytes(), "内容没原样搬"


def test_profile_rejects_workflow_dst_escaping_the_snapshot(tmp_path):
    """跨键约束：`[workflow].install` 的 dst 不许带 `..` / 绝对路径（那是往快照外写）。"""
    mod = _load(PROFILE_LOADER, "gha_gate_profile_for_workflow_dst")
    bad = tmp_path / "probe.toml"
    bad.write_text(
        'name = "probe"\n'
        '[snapshot]\nfrom_remote_workflows = false\n'
        '[[workflow.install]]\nsrc = "x.yml"\ndst = "../escape.yml"\n',
        encoding="utf-8",
    )
    with pytest.raises(mod.ProfileError) as exc:
        mod.load(str(bad))
    assert "escape.yml" in str(exc.value), str(exc.value)




# ---------------------------------------------------------------------------
# 卡 E151：号池桩里被改写 root 的那一件，必须也在 need 里（否则缺件是裸栈）。
# ---------------------------------------------------------------------------


def _write_profile(tmp_path, name, pool_body):
    prof = tmp_path / (name + ".toml")
    prof.write_text(
        'name = "' + name + '"\n'
        'message = "gate: someone 1 gate"\n'
        "[remote]\n"
        'transport = "https"\n'
        "[pool]\n" + pool_body,
        encoding="utf-8",
    )
    return prof


def test_rewrite_root_without_projects_in_need_is_rejected_at_load(tmp_path):
    """判据 4：rewrite_root = true 却把 projects.toml 漏在 need 外 ⇒ 加载即拒（不是裸栈）。

    这条挡的是「桩缺件时报的是 FileNotFoundError」—— 缺的那一件没人开跑前查，
    于是退出码落到 1，与 0/2/3/4/5/6 这张表对不上（卡 E151 实测踩过两趟）。
    """
    mod = _load(PROFILE_LOADER, "gha_gate_profile_for_rewrite_root")
    bad = _write_profile(tmp_path, "stubby", "stub = true\n"
                         'need = ["pool_models.py", "accounts.toml"]\n'
                         "rewrite_root = true\n")
    with pytest.raises(mod.ProfileError) as exc:
        mod.load(bad)
    msg = str(exc.value)
    assert "projects.toml" in msg, "拒了但没点名缺哪一件：" + msg
    assert "rewrite_root" in msg, "拒了但没说是哪个键招的：" + msg

    # 反面：need 里补上它 ⇒ 加载通过（否则这条判据就是「永远红」）
    good = _write_profile(tmp_path, "stubby", "stub = true\n"
                          'need = ["pool_models.py", "accounts.toml", "projects.toml"]\n'
                          "rewrite_root = true\n")
    assert mod.load(good)["pool"]["need"][-1] == "projects.toml"


def test_every_profile_that_rewrites_root_lists_projects_toml():
    """判据 5：目录里每一份要改写 root 的 profile 都把 projects.toml 列进 need。

    只修 engineering 那份的话，下一个加 profile 的人会照抄一个漏项 ——
    判据住在加载器里还不够，得有人真的把那句「所有 profile 都过」说出来。
    """
    mod = _load(PROFILE_LOADER, "gha_gate_profile_for_all_profiles")
    names = mod.list_repos()
    assert names, "profiles/ 里一份都没有"
    guilty = []
    for name in names:
        pool = mod.load(name)["pool"]
        if pool["rewrite_root"] and "projects.toml" not in pool["need"]:
            guilty.append(name)
    assert not guilty, (
        f"{guilty} 这些 profile 要改写 projects.toml 的 root，却没把它列进 [pool].need —— "
        "桩缺它时报的是 FileNotFoundError 而不是 POOL_STUB_INCOMPLETE"
    )


def test_rewrite_projects_root_missing_file_is_pool_code_not_traceback(tmp_path, capsys):
    """判据 4 第三处：rewrite 段自己判存在 —— 缺 projects.toml ⇒ 退 6 + POOL_STUB_INCOMPLETE。"""
    mod = _load(BUILD, "gha_build_snapshot_for_rewrite_root")
    stub = tmp_path / "stub"
    stub.mkdir()
    with pytest.raises(SystemExit) as exc:
        mod._rewrite_projects_root(str(stub), str(tmp_path / "snap"))
    assert exc.value.code == mod.EXIT_POOL, (
        f"缺 projects.toml 却退了 {exc.value.code}（6 才是「仓外号池桩不成立」）"
    )
    assert "POOL_STUB_INCOMPLETE" in capsys.readouterr().out

    # 正面：有它 ⇒ 改写成功，root 指向快照
    (stub / "projects.toml").write_text('root = "old"\n', encoding="utf-8")
    snap = tmp_path / "snap"
    mod._rewrite_projects_root(str(stub), str(snap))
    assert (stub / "projects.toml").read_text(encoding="utf-8").strip() == (
        'root = "' + snap.as_posix() + '"'
    )


# ---------------------------------------------------------------------------
# 卡 E156：三仓适配层收进仓 —— 适配器与 profile 在仓里，不是一次性脚本。
# ---------------------------------------------------------------------------

#: 第二波三仓：它们的适配器与 profile 一旦只在盘上，本机盘一没就再推不出来。
THREE_REPO_PROFILES = ("framework", "dsh", "ultrarag")


def test_three_repo_adapters_and_profiles_are_in_git():
    """判据 1：三份适配器 + 三份 profile + 读数垫片都在 git 里（不是只躺在盘上）。"""
    out = _run(["git", "ls-files", "--", "scripts/cloud/gha"]).stdout
    tracked = {ln.strip() for ln in out.splitlines() if ln.strip()}
    wanted = [GHA / "adapters" / (n + ".py") for n in THREE_REPO_PROFILES]
    wanted += [PROFILES / (n + ".toml") for n in THREE_REPO_PROFILES]
    wanted.append(GHA / "conftest_reading.txt")
    for p in wanted:
        rel = p.relative_to(ROOT).as_posix()
        assert rel in tracked, f"{rel} 没进 git —— 只在盘上的适配层换个机器就没了"


def test_three_repo_profiles_have_no_engineering_keys():
    """判据 3：三份新 profile 正文不含 engineering 的五个字面（换了仓就得换适配层）。"""
    literals = ("TF_PROJECTS_TOML", "models.whitelist.toml", "line/impl-v1",
                "T-AG526", "gate: engineering")
    guilty = []
    for name in THREE_REPO_PROFILES:
        text = (PROFILES / (name + ".toml")).read_text(encoding="utf-8")
        for lit in literals:
            if lit in text:
                guilty.append(f"{name}.toml <- {lit}")
    assert not guilty, (
        f"这三份 profile 里还有 engineering 专属的 {guilty} —— 照抄一份 engineering 的"
        "适配层，换个仓就再抄一份，两份必然各自漂移"
    )


def test_every_profile_adapter_src_exists_on_disk():
    """判据 5①：每份 profile 指的那份适配器都得真在盘上（拼错了就静默退化成配不上就跑）。"""
    mod = _load(PROFILE_LOADER, "gha_gate_profile_for_adapter_src")
    missing = []
    for name in mod.list_repos():
        prof = mod.load(name)
        ad = prof["adapter"]
        if not ad["enabled"]:
            continue
        if not (GHA / ad["src"]).is_file():
            missing.append(f"{name}.toml -> {ad['src']}")
        shim = ad["conftest_shim"]
        if shim and not (GHA / shim).is_file():
            missing.append(f"{name}.toml -> {shim}")
    assert not missing, f"profile 指的件不在盘上：{missing}"


def test_conftest_path_escaping_the_snapshot_is_rejected_at_load(tmp_path):
    """判据 5③：conftest_path 绝对路径或含两点相对 ⇒ 加载即拒（垫片只往快照里写）。"""
    mod = _load(PROFILE_LOADER, "gha_gate_profile_for_conftest_path")
    body = (
        'name = "probe"\n'
        'message = "gate: probe 1 gate"\n'
        "[remote]\n"
        'transport = "https"\n'
        "[adapter]\n"
        "enabled = true\n"
        'src = "adapters/dsh.py"\n'
        'snapshot_name = "tests/test_windows_autostart_e2e.py"\n'
        'conftest_shim = "conftest_reading.txt"\n'
        'conftest_path = "%s"\n'
        'conftest_marker = "GHA-READING-HOOK"\n'
    )
    for bad in ("/etc/conftest.py", "../outside/conftest.py", "tests\\conftest.py"):
        prof = tmp_path / "probe.toml"
        prof.write_text(body % bad, encoding="utf-8")
        with pytest.raises(mod.ProfileError) as exc:
            mod.load(str(prof))
        assert "conftest_path" in str(exc.value), str(exc.value)

    # 反面：快照内相对路径 ⇒ 通过（否则这条判据就是永远红）
    prof = tmp_path / "probe.toml"
    prof.write_text(body % "conftest.py", encoding="utf-8")
    assert mod.load(str(prof))["adapter"]["conftest_path"] == "conftest.py"


def test_conftest_shim_creates_the_file_when_the_repo_has_none(tmp_path, capsys):
    """判据 5④正面：目标 conftest 不存在 ⇒ 新建（UltraRAG / dsh 源仓都没有根 conftest.py）。"""
    mod = _load(BUILD, "gha_build_snapshot_for_shim_create")
    ad = {"conftest_path": "conftest.py", "conftest_marker": "GHA-READING-HOOK"}
    mod._append_conftest_shim(str(tmp_path), ad, str(GHA / "conftest_reading.txt"))
    out = tmp_path / "conftest.py"
    assert out.is_file(), "没有根 conftest.py 的仓必须能新建一份 —— 否则垫片永远装不上"
    body = out.read_text(encoding="utf-8")
    assert "GHA-READING-HOOK" in body, "新建出来的那份里没有 marker"
    assert "pytest_terminal_summary" in body, "新建出来的那份里没有钩子"
    printed = capsys.readouterr().out
    assert "conftest created" in printed, "新建了却没说 —— 事后查不出这份是谁造的"


def test_conftest_shim_is_idempotent_on_the_marker(tmp_path, capsys):
    """判据 5④反面：marker 已命中 ⇒ 退 5（不许把垫片追加第二遍）。"""
    mod = _load(BUILD, "gha_build_snapshot_for_shim_idem")
    (tmp_path / "tests").mkdir()
    existing = tmp_path / "tests" / "conftest.py"
    existing.write_text("# GHA-READING-HOOK\ndef pytest_terminal_summary(t, e, c):\n    pass\n",
                        encoding="utf-8")
    before = existing.read_bytes()
    ad = {"conftest_path": "tests/conftest.py", "conftest_marker": "GHA-READING-HOOK"}
    with pytest.raises(SystemExit) as exc:
        mod._append_conftest_shim(str(tmp_path), ad, str(GHA / "conftest_reading.txt"))
    assert exc.value.code == mod.EXIT_SNAPSHOT, (
        f"装第二遍却退了 {exc.value.code}（5 才是快照形状不对）"
    )
    assert "CONFTEST_ALREADY_HAS_ADDOPTION" in capsys.readouterr().out
    assert existing.read_bytes() == before, "拒了却已经把文件改了 —— 那不是幂等"


def test_extra_files_installer_feeds_the_frozen_workflow(tmp_path, capsys):
    """判据 1 补：extra_files 能把引导件搬进快照（Node 仓缺 pyproject.toml）。"""
    mod = _load(BUILD, "gha_build_snapshot_for_extra_files")
    mod._install_extra_files(str(tmp_path), [{"src": "extras/node-pyproject.toml",
                                             "dst": "pyproject.toml"}])
    out = tmp_path / "pyproject.toml"
    assert out.is_file(), "引导件没落进快照 —— 冻结的 workflow 那步 pip install 还会 exit 1"
    assert out.read_bytes() == (GHA / "extras" / "node-pyproject.toml").read_bytes()
    assert "extra file installed" in capsys.readouterr().out

    # 缺源 ⇒ 退 2（配置问题），不是 traceback
    with pytest.raises(SystemExit) as exc:
        mod._install_extra_files(str(tmp_path), [{"src": "extras/no-such.toml",
                                                 "dst": "pyproject.toml"}])
    assert exc.value.code == mod.EXIT_CONFIG
    assert "MISSING_EXTRA_SRC" in capsys.readouterr().out


def test_extra_files_under_dot_github_are_rejected_at_load(tmp_path):
    """跨键约束：extra_files 落在 .github 目录下 ⇒ 加载即拒（那里归 [workflow].install）。"""
    mod = _load(PROFILE_LOADER, "gha_gate_profile_for_extra_files")
    prof = tmp_path / "probe.toml"
    prof.write_text(
        'name = "probe"\n'
        'message = "gate: probe 1 gate"\n'
        "[remote]\n"
        'transport = "https"\n'
        "[snapshot]\n"
        "extra_files = [\n"
        '  { src = "extras/node-pyproject.toml", dst = ".github/workflows/x.yml" },\n'
        "]\n",
        encoding="utf-8",
    )
    with pytest.raises(mod.ProfileError) as exc:
        mod.load(str(prof))
    assert "extra_files" in str(exc.value) and ".github" in str(exc.value), str(exc.value)
