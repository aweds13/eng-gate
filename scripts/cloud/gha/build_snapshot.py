"""把当前 engineering 树打成快照、推上 GitHub，让冻结的 workflow 在 windows-latest 上跑门禁。

这是 `scripts/cloud/run_gate.sh` 那条「云门禁」路线的 GitHub Actions 等价物：run_gate.sh 租一台
云机、ssh 过去跑；这里不租机器，改成把树打成快照推到远端仓，由它继承来的
`.github/workflows/ci.yml` 里那个 `windows-autostart-e2e` 作业跑（最后一步写死
`python -m pytest -q tests/test_windows_autostart_e2e.py` ⇒ 适配器必须叫这个名字）。

三个阶段（`--stage`）：
  build  打 bundle → 建快照 → 装适配器与垫片 → 补仓外号池桩 → 重算派生文档
  smoke  在快照上复刻 runner 要做的事：定向 pytest + ruff + check_docs
  push   提交 + 判两条「只有提交之后才能判」的判据 + 推送（红了就**不推**，免得白跑一趟）

为什么参数都从外面给：本脚本不许出现本机盘符、用户目录、硬编码 IP
（`tests/test_ci_portability.py` 会逐行扫 `scripts/cloud/**`）。仓根由
`git rev-parse --show-toplevel` 现算；远端 URL 走 `--remote` / `GHA_REMOTE`，SSH 私钥走
`GIT_SSH_COMMAND`。

退出码（`tests/test_gha_cloud_gate.py` 逐条钉住，五个值互不相同）：
  0  成功
  2  缺配置：远端没给 / GIT_SSH_COMMAND 没给 / 适配器或垫片文件不存在
  3  取不回历史或 workflow（bundle / fetch / checkout .github 失败）
  4  提交失败
  5  快照前置不成立（conftest 已有 pytest_addoption / 台账已豁免 / 缺证据文件）
  6  号池桩不成立，或提交后的判据红 ⇒ 拒绝推送
"""
import argparse
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import time

EXIT_OK = 0
EXIT_CONFIG = 2
EXIT_HISTORY = 3
EXIT_COMMIT = 4
EXIT_SNAPSHOT = 5
EXIT_POOL = 6

#: 快照提交的 trailer 里那个台账编号。gate 的 audit 门与 tools/pytest_select.py 的
#: log_batch() 都读它；T-AG526 是台账里唯一贴云门禁的那条（evidence 含
#: scripts/cloud/run_gate.sh）。没有它 ⇒ audit 报「没有 Task: trailer」。
DEFAULT_TASK = "T-AG526"

#: 只在这一组目录里跑 ruff（与 scripts/run_gates.py 的 ruff 门同口径）。
RUFF_PATHS = ["src", "tests", "scripts", "tools", "examples", "harness"]

#: 推送前必须绿的定向 pytest（每一条都是历史上真红过的那一种）。
SMOKE_TARGETS = [
    "tests/test_audit_tightening.py::test_real_repo_history_files_are_all_claimed",
    "tests/test_pool_sink_wiring.py::test_sink_module_eight_functions_untouched",
    "tests/test_two_rulers.py::test_old_rev_still_has_gates_stripped",
    "tests/test_card_doc_budget.py::test_numeric_short_sha_is_still_a_pointer",
    "tests/test_doc_debt_ratchet.py::test_real_repo_debt_does_not_exceed_baseline",
    "tests/test_gate_selfproof.py::test_real_ledger_passes_all_criteria",
    "tests/test_pool_jobs.py::test_real_diag_census_buckets",
    "tests/test_pool_accounts.py::test_ledger_lives_outside_tool_root",
    "tests/test_pool_projects.py",
    "tests/test_check_docs.py::test_every_own_ext_is_justified",
    "tests/test_gate_env_parity.py::test_workspace_crlf_vs_head_blob_lf_is_not_a_defect",
    "tests/test_web_live_json_retry.py",
    "tests/test_pool_readme_counts.py::test_real_readme_matches_recount",
    "tests/test_pool_landing.py::test_real_tree_derived_docs_are_consistent",
    "tests/test_pool_landing.py::test_every_leg_checks_the_index",
    "tests/test_pool_jobs.py::test_gen_pool_readme_check_is_green",
    "tests/test_wb_land.py::test_card_and_batch_is_exactly_one",
    "tests/test_gate_selfproof_product.py::test_web_live_bites_when_the_event_delegation_is_gone",
]

#: 提交之后才能判的两条（都读「最近一笔提交」）。
SMOKE4_TARGETS = [
    "tests/test_pytest_select.py::test_log_batch_agrees_with_the_per_commit_reads",
    "tests/test_docs_fragments.py::test_audit_verdict_unchanged_by_sync",
]

#: 号池桩必须齐的四件（第五件 projects.toml 现写）。
POOL_NEED = ["pool_models.py", "models.whitelist.toml", "models.live.json", "accounts.toml"]


def log(*a):
    print(" ".join(str(x) for x in a))
    sys.stdout.flush()


def sh(args, cwd=None, tries=1, quiet=False, env=None):
    """跑一条命令，失败重试（每次间隔 6s），返回最后一次的 CompletedProcess。"""
    last = None
    for i in range(1, tries + 1):
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=env,
                           # ★ 卡 148 的不弹窗钉子：本机跑构建器时别闪黑窗。
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if p.returncode == 0:
            if not quiet:
                log("$", " ".join(args), "-> rc=0")
                if p.stdout.strip():
                    log("  out:", p.stdout.strip()[:800])
            return p
        last = p
        tag = " (try " + str(i) + "/" + str(tries) + ")"
        log("$", " ".join(args), "-> rc=" + str(p.returncode) + tag)
        if p.stderr.strip():
            log("  err:", p.stderr.strip()[-600:])
        if i < tries:
            time.sleep(6)
    return last


def git_toplevel(start):
    """仓根由 git 现算 —— 脚本被拷到哪儿都成立，不写死任何盘符。"""
    p = sh(["git", "-C", start, "rev-parse", "--show-toplevel"], quiet=True)
    if p is not None and p.returncode == 0 and p.stdout.strip():
        return os.path.abspath(p.stdout.strip())
    # 兜底：<仓根>/scripts/cloud/gha/build_snapshot.py
    here = os.path.abspath(__file__)
    for _ in range(4):
        here = os.path.dirname(here)
    return here


def load_module(path, name):
    """把适配器当模块载进来 —— 冒烟必须复刻 runner 做的事，唯一真源是适配器本身。"""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def gen_env():
    """跑派生文档生成器用的环境。"""
    e = dict(os.environ)
    e["PYTHONIOENCODING"] = "utf-8"
    e.pop("TF_PROJECTS_TOML", None)
    # 必须钉 UTC。runner（windows-latest）是 UTC、开发机是 +08，而生成器只认
    # datetime.date.today()（scripts/gen_pool_readme.py 的 resolve_date）⇒ 不钉就会让
    # 快照里的 README 日期与 runner 现算差一天，一路连带 7 条 pytest 红。
    e["TZ"] = "UTC"
    return e


def smoke_env(dst):
    """冒烟与提交后判据共用的环境。"""
    e = dict(os.environ)
    e["PYTHONIOENCODING"] = "utf-8"
    e["TF_PROJECTS_TOML"] = os.path.join(os.path.dirname(dst), "infra", "pool", "projects.toml")
    # 与适配器的 setdefault 同值：冒烟这里若比 runner 宽或严，冒烟绿了真跑还会红。
    e["TF_WEB_LIVE_TIMEOUT"] = "60"
    return e


def ssh_env():
    """git 走 SSH 时用的环境（HTTPS:443 在这台机器上不可达，见 run_gate.sh 的注释）。"""
    cmd = os.environ.get("GIT_SSH_COMMAND", "").strip()
    if not cmd:
        log("MISSING_GIT_SSH_COMMAND")
        sys.exit(EXIT_CONFIG)
    e = dict(os.environ)
    e["GIT_SSH_COMMAND"] = cmd
    return e


def do_build(a):
    root, dst, stub = a.root, a.dest, a.stub
    if os.path.exists(a.bundle):
        os.remove(a.bundle)
    p = sh(["git", "bundle", "create", a.bundle, "HEAD"], cwd=root)
    if p is None or p.returncode != 0:
        log("BUNDLE_FAILED")
        sys.exit(EXIT_HISTORY)
    log("bundle bytes:", os.path.getsize(a.bundle))
    p = sh(["git", "rev-parse", "HEAD"], cwd=root, quiet=True)
    log("ROOT HEAD:", (p.stdout or "").strip())

    if os.path.isdir(dst):
        shutil.rmtree(dst, ignore_errors=True)
    os.makedirs(dst, exist_ok=True)
    sh(["git", "init", "-q", "-b", "main"], cwd=dst)
    sh(["git", "config", "core.autocrlf", "true"], cwd=dst)
    sh(["git", "config", "core.longpaths", "true"], cwd=dst)
    sh(["git", "remote", "add", "origin", a.remote], cwd=dst)

    # bundle 由 git bundle create <f> HEAD 生成 ⇒ 里面那根 ref 叫 HEAD（不是 refs/heads/…）
    p = sh(["git", "fetch", "-q", a.bundle, "HEAD"], cwd=dst)
    if p is None or p.returncode != 0:
        log("BUNDLE_FETCH_FAILED")
        sys.exit(EXIT_HISTORY)
    sh(["git", "checkout", "-q", "-f", "-B", "main", "FETCH_HEAD"], cwd=dst)
    p = sh(["git", "rev-list", "--count", "HEAD"], cwd=dst, quiet=True)
    log("history commits:", (p.stdout or "").strip())
    p = sh(["git", "log", "--oneline", "-1"], cwd=dst, quiet=True)
    log("base:", (p.stdout or "").strip())

    # 浅 fetch 只用来拿**冻结的** .github（workflow 正文在远端那一份里，本 token 改不了它）
    p = sh(["git", "fetch", "--no-tags", "--depth", "1", "origin", "main"],
           cwd=dst, tries=4, quiet=True, env=ssh_env())
    if p is None or p.returncode != 0:
        log("FETCH_FAILED")
        sys.exit(EXIT_HISTORY)
    p = sh(["git", "checkout", "FETCH_HEAD", "--", ".github"], cwd=dst)
    if p is None or p.returncode != 0:
        log("WORKFLOW_CHECKOUT_FAILED")
        sys.exit(EXIT_HISTORY)
    log("workflows:", sorted(os.listdir(os.path.join(dst, ".github", "workflows"))))

    if not os.path.isdir(stub):
        log("MISSING_POOL_STUB", stub)
        sys.exit(EXIT_POOL)
    names = sorted(os.listdir(stub))
    miss = [n for n in POOL_NEED if n not in names]
    if miss:
        log("POOL_STUB_INCOMPLETE", miss)
        sys.exit(EXIT_POOL)
    projects_path = os.path.join(stub, "projects.toml")
    with open(projects_path, encoding="utf-8") as fh:
        proj = fh.read()
    dst_posix = dst.replace(os.sep, "/")
    proj2 = re.sub(r'(?m)^root = "[^"]*"', 'root = "' + dst_posix + '"', proj)
    # 桩是共享的：上一趟可能已经把 root 改成本趟的同一路径 ⇒ 判「改后是否等于 DST」
    mroot = re.search(r'(?m)^root = "([^"]*)"', proj2)
    if not mroot or mroot.group(1) != dst_posix:
        log("PROJECT_ROOT_NOT_REWRITTEN", mroot.group(1) if mroot else None)
        sys.exit(EXIT_POOL)
    with open(projects_path, "w", encoding="utf-8", newline=chr(10)) as fh:
        fh.write(proj2)
    if os.path.isdir(os.path.join(dst, "infra")):
        log("INFRA_INSIDE_SNAPSHOT")
        sys.exit(EXIT_POOL)
    log("pool stub (outside repo):", names)
    log("projects.toml root ->", dst_posix)

    adapter_dst = os.path.join(dst, "tests", "test_windows_autostart_e2e.py")
    os.makedirs(os.path.dirname(adapter_dst), exist_ok=True)
    shutil.copyfile(a.adapter, adapter_dst)
    with open(adapter_dst, "rb") as fh:
        data = fh.read()
    if not data.endswith(b"\n"):
        with open(adapter_dst, "ab") as fh:
            fh.write(b"\n")
        log("adapter trailing newline appended")
    log("adapter installed:", os.path.getsize(adapter_dst), "B")

    cf = os.path.join(dst, "tests", "conftest.py")
    with open(cf, "rb") as fh:
        body = fh.read()
    with open(a.conftest_shim, "rb") as fh:
        shimtxt = fh.read()
    if b"pytest_addoption" in body:
        log("CONFTEST_ALREADY_HAS_ADDOPTION")
        sys.exit(EXIT_SNAPSHOT)
    if not body.endswith(b"\n"):
        body += b"\n"
    with open(cf, "wb") as fh:
        fh.write(body + shimtxt)
    log("conftest shim appended:", len(shimtxt), "B")

    # 三件 diag fixture **不进提交面**（2026-11-18 反向实测）：gates/diag/ 被 .gitignore
    # 忽略，硬塞进提交会让 test_own_exts_covers… 报「本仓真跟踪、却不在 OWN_EXTS 里：
    # [.jsonl]」，还会把 README 的「派活日志 N 份」从 242 压成 3 ⇒ 四条红。
    # 改为**适配器运行时现写**。

    tr = os.path.join(dst, "docs", "traceability.toml")
    with open(tr, encoding="utf-8") as fh:
        txt = fh.read()
    # 幂等：只认【顶层】那个键（文档正文里出现过这个说法是正常的）
    if re.search(r"(?m)^claimed_files_exempt\s*=", txt):
        log("LEDGER_ALREADY_EXEMPT")
        sys.exit(EXIT_SNAPSHOT)
    nl = chr(10)
    block = "# GHA cloud gate snapshot: files this build commit touches" + nl
    block += "claimed_files_exempt = [" + nl
    block += '  "tests/test_windows_autostart_e2e.py",' + nl
    block += '  "tests/conftest.py",' + nl
    block += '  ".github/**",' + nl
    block += "]" + nl + nl
    idx = txt.index("[meta]")
    with open(tr, "w", encoding="utf-8", newline=nl) as fh:
        fh.write(txt[:idx] + block + txt[idx:])
    log("ledger exempt block written")

    for keep in ("gates/last.json", "gates/reuse.json"):
        f = os.path.join(dst, keep.replace("/", os.sep))
        if not os.path.exists(f):
            log("MISSING_EVIDENCE_FILE", keep)
            sys.exit(EXIT_SNAPSHOT)
        bak = os.path.join(a.tmp, "before-" + keep.replace("/", "_"))
        shutil.copyfile(f, bak)
        log("kept evidence", keep, os.path.getsize(f), "B")

    # 生成器之前必须**先造出适配器运行时才会造的那些 fixture**，否则快照里的 README 与
    # runner 上的现算对不上：适配器现写 3 份 wb-*.jsonl ⇒ gen_pool_readme 的
    # unreadable_diag_rows() 读到 3（不是 0）⇒ 不 hold「派活日志」那行 ⇒ 拿 3 去比文件里的
    # 242 ⇒ 5 条 pytest 红。修法：build 期就调适配器自己的 helper 造同一批 fixture。
    shim = load_module(a.adapter, "gha_adapter_build")
    shim.ROOT = dst
    shim._ensure_diag_fixtures()

    # 派生文档与现算对齐（README 的「派活日志 / 批预声明」两行、docs/INDEX.md）：
    # 必须在**产物树里**跑生成器，而不是把开发机的数字搬过去。
    for gen_args, tag in (
        (["scripts/gen_pool_readme.py"], "GEN_README"),
        (["scripts/gen_doc_index.py", "--target", "docs"], "GEN_INDEX"),
    ):
        g = sh([sys.executable, "-X", "utf8"] + gen_args, cwd=dst, quiet=True, env=gen_env())
        log(tag + "_RC", None if g is None else g.returncode)
        log(tag + "_OUT", ((g.stdout or "") + (g.stderr or ""))[-1200:])

    log("BUILD_OK", dst)


def do_smoke(a):
    dst = a.dest
    # 冒烟必须**复刻适配器在 runner 上做的事**，否则冒烟绿了、真跑还红。
    shim = load_module(a.adapter, "gha_adapter_smoke")
    shim.ROOT = dst
    shim._ensure_pool_stub()
    shim._ensure_diag_fixtures()
    env = smoke_env(dst)

    log("=== SMOKE 1: targeted pytest ===")
    p = sh([sys.executable, "-X", "utf8", "-m", "pytest", "-q", "-o", "addopts=",
            "-p", "no:cacheprovider"] + SMOKE_TARGETS, cwd=dst, quiet=True, env=env)
    log("SMOKE1_RC", None if p is None else p.returncode)
    log("SMOKE1_OUT", ((p.stdout or "") + (p.stderr or ""))[-6000:])

    log("=== SMOKE 2: ruff ===")
    p = sh([sys.executable, "-X", "utf8", "-m", "ruff", "check"] + RUFF_PATHS,
           cwd=dst, quiet=True, env=env)
    log("SMOKE2_RC", None if p is None else p.returncode)
    log("SMOKE2_OUT", ((p.stdout or "") + (p.stderr or ""))[-2000:])

    log("=== SMOKE 3: check_docs ===")
    p = sh([sys.executable, "-X", "utf8", "scripts/check_docs.py", "--mode", "report"],
           cwd=dst, quiet=True, env=env)
    log("SMOKE3_RC", None if p is None else p.returncode)
    log("SMOKE3_OUT", ((p.stdout or "") + (p.stderr or ""))[-1500:])


def do_push(a):
    dst = a.dest
    sh(["git", "config", "user.name", a.git_user], cwd=dst)
    sh(["git", "config", "user.email", a.git_email], cwd=dst)
    sh(["git", "add", "-A"], cwd=dst)
    # 不再 git add -f 三件 diag fixture：它们在 .gitignore 里，本来就该留在家外
    p = sh(["git", "status", "--porcelain"], cwd=dst, quiet=True)
    lines = [ln for ln in (p.stdout or "").splitlines() if ln.strip()]
    log("changed entries:", len(lines))
    for ln in lines[:15]:
        log("  ", ln)
    # 必须带合规的 Task: trailer（gate 的 audit 门与 pytest_select 的 log_batch()
    # 都读它）。无 trailer ⇒ audit 报「没有 Task: trailer」、pytest_select 报 task 是
    # 空字节而不是空串（空 trailer 时 %x1f 后直接跟记录分隔符）。
    msg = a.message + "\n\nTask: " + a.task
    r = sh(["git", "commit", "-q", "-m", msg], cwd=dst)
    if r is None or r.returncode != 0:
        log("COMMIT_FAILED")
        sys.exit(EXIT_COMMIT)
    p = sh(["git", "rev-parse", "HEAD"], cwd=dst, quiet=True)
    log("HEAD:", (p.stdout or "").strip())

    # 提交之后才能判的两条（都读「最近一笔提交」）：Task trailer 是否合规、以及依赖
    # audit 判决的 docs 片段判据。红了就**不推**（否则又是一趟白跑的 GHA）。
    env4 = smoke_env(dst)
    env4["GHA_GATE_ADAPTER"] = "1"
    shim = load_module(a.adapter, "gha_adapter_push")
    shim.ROOT = dst
    shim._ensure_diag_fixtures()  # 幂等：--stage push 单跑时也要有那 3 份
    log("=== SMOKE 4: post-commit trailer checks ===")
    p = sh([sys.executable, "-X", "utf8", "-m", "pytest", "-q", "-o", "addopts=",
            "-p", "no:cacheprovider"] + SMOKE4_TARGETS, cwd=dst, quiet=True, env=env4)
    log("SMOKE4_RC", None if p is None else p.returncode)
    log("SMOKE4_OUT", ((p.stdout or "") + (p.stderr or ""))[-3000:])
    if p is None or p.returncode != 0:
        log("SMOKE4_FAILED -> refuse to push")
        sys.exit(EXIT_POOL)

    p = sh(["git", "push", "--progress", "--force", "origin", "HEAD:refs/heads/main"],
           cwd=dst, tries=4, quiet=True, env=ssh_env())
    ok = p is not None and p.returncode == 0
    if ok:
        log("PUSH_OK via ssh")
    else:
        log("PUSH_FAILED")
    log("PUSH_RC:", 0 if ok else 1)
    log("BUILD_DONE")


def build_parser():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(
        prog="build_snapshot.py",
        description="把当前树打成快照推到 GHA 仓，让冻结的 windows workflow 跑门禁。",
    )
    ap.add_argument("--stage", default=os.environ.get("STAGE", "all"),
                    choices=["all", "build", "smoke", "push"])
    ap.add_argument("--root", default=None, help="源树根（默认 git rev-parse --show-toplevel）")
    ap.add_argument("--dest", default=None, help="快照目录（默认 <root>/gates/diag/_tmp/enggate）")
    ap.add_argument("--tmp", default=None, help="临时目录（默认 <root>/gates/diag/_tmp）")
    ap.add_argument("--bundle", default=None,
                    help="历史 bundle 落点（默认 <tmp>/eng-history.bundle）")
    ap.add_argument("--remote", default=os.environ.get("GHA_REMOTE", ""),
                    help="快照要推到的远端（也可用 GHA_REMOTE）")
    ap.add_argument("--stub", default=None, help="仓外号池桩目录（默认 <tmp>/infra/pool）")
    ap.add_argument("--adapter", default=os.path.join(here, "adapter.py"), help="适配器路径")
    ap.add_argument("--conftest-shim", default=os.path.join(here, "conftest_shim.txt"),
                    help="覆盖率选项垫片")
    ap.add_argument("--task", default=DEFAULT_TASK, help="快照提交的 Task trailer")
    ap.add_argument("--message",
                    default="gate: engineering 23 gates on windows-latest (adapter v18)",
                    help="快照提交的标题行")
    ap.add_argument("--git-user", default=os.environ.get("GHA_GIT_USER", "gate-bot"))
    ap.add_argument("--git-email", default=os.environ.get("GHA_GIT_EMAIL", "gate-bot@example.com"))
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    a.root = os.path.abspath(a.root or git_toplevel(os.path.dirname(os.path.abspath(__file__))))
    a.tmp = os.path.abspath(a.tmp or os.path.join(a.root, "gates", "diag", "_tmp"))
    a.dest = os.path.abspath(a.dest or os.path.join(a.tmp, "enggate"))
    a.bundle = os.path.abspath(a.bundle or os.path.join(a.tmp, "eng-history.bundle"))
    a.stub = os.path.abspath(a.stub or os.path.join(a.tmp, "infra", "pool"))
    a.adapter = os.path.abspath(a.adapter)
    a.conftest_shim = os.path.abspath(a.conftest_shim)
    if not a.remote:
        log("MISSING_REMOTE")
        return EXIT_CONFIG
    for label, path in (("adapter", a.adapter), ("conftest_shim", a.conftest_shim)):
        if not os.path.exists(path):
            log("MISSING_" + label.upper(), path)
            return EXIT_CONFIG
    os.makedirs(a.tmp, exist_ok=True)
    log("root:", a.root)
    log("dest:", a.dest)
    log("remote:", a.remote)
    log("stage:", a.stage)
    if a.stage in ("all", "build"):
        do_build(a)
    if a.stage in ("all", "smoke"):
        do_smoke(a)
    if a.stage in ("all", "push"):
        do_push(a)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
