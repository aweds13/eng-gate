"""把当前树打成快照、推上 GitHub，让 Actions 上的门禁作业跑起来 —— **骨架，不认仓**。

这是 `scripts/cloud/run_gate.sh` 那条「云门禁」路线的 GitHub Actions 等价物：run_gate.sh 租一台
云机、ssh 过去跑；这里不租机器，改成把树打成快照推到远端仓，由那边的 workflow 跑门禁。

★ 仓与仓的差别**全在 profile 里**（`scripts/cloud/gha/profiles/<仓>.toml`，由 `--repo` 选，
   键的语义见 `gate_profile.py`）。这个文件里只有「顺序」：
     build  打历史 → 建快照 → 按 profile 装适配器/垫片/号池桩/台账豁免/证据文件 → 重算派生文档
     smoke  在快照上复刻 runner 要做的事（profile 说跑什么就跑什么，红一段就不许当绿）
     push   提交 + 判「只有提交之后才能判」的判据 + 推送（红了就**不推**，免得白跑一趟）

为什么还留着 CLI 开关：profile 是「这个仓是什么形状」，CLI 是「这一趟怎么跑」（换目录、换远端、
单跑某一段）。两者都能改的东西 —— CLI 优先。

为什么脚本里不许出现本机盘符 / 用户目录 / 硬编码 IP：`tests/test_ci_portability.py` 会逐行扫
`scripts/cloud/**`。仓根由 `git rev-parse --show-toplevel` 现算；远端 URL 走 `--remote` 或
profile 指定的环境变量；SSH 私钥走 `GIT_SSH_COMMAND`。

退出码（`tests/test_gha_cloud_gate.py` 逐条钉住，五个值互不相同）：
  0  成功
  2  缺配置：profile 不成立 / 远端没给 / ssh 没给 GIT_SSH_COMMAND / 适配器或垫片文件不存在 /
     快照目录不存在（非 build 段）
  3  取不回历史或 workflow（bundle / fetch / checkout .github 失败）
  4  提交失败
  5  快照前置不成立（conftest 已有 pytest_addoption / 台账已豁免 / 缺证据文件 / 缺 require_files），
     或冒烟有任一段红（冒烟红了就不许当绿）
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

#: 同目录的 gate_profile.py（不放 site-packages 里：它是这个骨架的一部分）。
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import gate_profile  # noqa: E402


def log(*a):
    print(" ".join(str(x) for x in a))
    sys.stdout.flush()


def _resolve_argv0(args):
    """argv[0] 走 PATHEXT 解析一次。

    为什么需要它：Windows 上 `corepack` 真实文件是 `corepack.CMD`，而 CreateProcess 只按
    `.exe` 找 —— 直接传 `corepack` 会 FileNotFoundError[WinError 2]，看着像「命令不存在」，
    其实是「少了扩展名」。node 腿的 `corepack pnpm install` 就是被这个咬的。
    骨架不写死任何可执行文件的绝对路径：解析交给 PATH + PATHEXT。
    """
    if not args or os.path.isabs(args[0]) or os.sep in args[0]:
        return list(args)
    found = shutil.which(args[0])
    return list(args) if not found else [found] + list(args[1:])


def sh(args, cwd=None, tries=1, quiet=False, env=None):
    """跑一条命令，失败重试（每次间隔 6s），返回最后一次的 CompletedProcess。"""
    args = _resolve_argv0(args)
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
    # 必须钉 UTC。runner 是 UTC、开发机是 +08，而生成器只认
    # datetime.date.today()（scripts/gen_pool_readme.py 的 resolve_date）⇒ 不钉就会让
    # 快照里的 README 日期与 runner 现算差一天，一路连带 7 条 pytest 红。
    e["TZ"] = "UTC"
    return e


def smoke_env(dst, profile):
    """冒烟与提交后判据共用的环境：骨架给通用两件，其余由 profile 的 [smoke].env 给。"""
    e = dict(os.environ)
    e["PYTHONIOENCODING"] = "utf-8"
    if profile["pool"]["stub"]:
        e["TF_PROJECTS_TOML"] = os.path.join(os.path.dirname(dst), "infra", "pool", "projects.toml")
    for item in profile["smoke"]["env"]:
        k, _, v = item.partition("=")
        e[k.strip()] = v
    return e


def remote_env(profile):
    """推/拉远端时用的环境。「缺私钥就退 2」是 ssh 那条路的事，https 不该被它连坐。"""
    if profile["remote"]["transport"] == "ssh":
        cmd = os.environ.get("GIT_SSH_COMMAND", "").strip()
        if not cmd:
            log("MISSING_GIT_SSH_COMMAND")
            sys.exit(EXIT_CONFIG)
        e = dict(os.environ)
        e["GIT_SSH_COMMAND"] = cmd
        return e
    e = dict(os.environ)
    # 凭据由 credential helper 给；没凭据时**立刻失败**，不要卡在交互式提示上。
    e["GIT_TERMINAL_PROMPT"] = "0"
    return e


def _require_files(dst, paths):
    """profile 说「快照里必须真有这些」—— 缺一件就说明这一趟装错树了。"""
    miss = [p for p in paths if not os.path.exists(os.path.join(dst, p.replace("/", os.sep)))]
    if miss:
        log("MISSING_REQUIRED_FILE", miss)
        sys.exit(EXIT_SNAPSHOT)
    log("required files ok:", len(paths))


def _install_extra_files(dst, items):
    """profile 说「往快照里补这几件引导件」—— src 相对本目录，dst 相对快照根。

    为什么需要它：镜像仓借的是**冻结的** windows workflow，那四步写死成
    「actions/setup-python → pip install -e . "pytest>=8" → python -m pytest -q <适配器>」。
    这对 Python 仓刚好，对 Node 仓（dsh-superagent-prototype）就是错配：没有 pyproject.toml，
    第一步 pip install 就 exit 1，作业连适配器都没跑到（卡 E156 实测，日志原文
    「does not appear to be a Python project」）。
    补一份空的 pyproject.toml 只为了让那一步能过，跑什么仍由适配器说。
    """
    for item in items:
        src = os.path.join(HERE, item["src"].replace("/", os.sep))
        if not os.path.isfile(src):
            log("MISSING_EXTRA_SRC", item["src"])
            sys.exit(EXIT_CONFIG)
        out = os.path.join(dst, item["dst"].replace("/", os.sep))
        parent = os.path.dirname(out)
        if parent:
            os.makedirs(parent, exist_ok=True)
        shutil.copyfile(src, out)
        log("extra file installed:", item["dst"], "<-", item["src"], os.path.getsize(out), "B")
    if items:
        log("extra files installed:", len(items))


def _install_workflows(dst, items):
    """profile 说「给这个仓装一份自己的 workflow」—— src 相对本目录，dst 相对快照根。

    为什么需要它：有的仓 workflow 在远端**冻结**（engineering：本 token 没有 workflow scope，
    只能把远端那份 checkout 回来），有的仓 workflow **归它自己**（OpenMAIC：推上去就按树里
    那几份跑）。后者若要用我们这套 BEGIN/END 读数，就得单独装一份 —— 它自己那份 ci.yml
    不认我们的读数格式。装什么由 profile 的 [workflow].install 说，骨架不认仓。
    """
    for item in items:
        src = os.path.join(HERE, item["src"].replace("/", os.sep))
        if not os.path.isfile(src):
            log("MISSING_WORKFLOW_SRC", item["src"])
            sys.exit(EXIT_CONFIG)
        out = os.path.join(dst, item["dst"].replace("/", os.sep))
        os.makedirs(os.path.dirname(out), exist_ok=True)
        shutil.copyfile(src, out)
        log("workflow installed:", item["dst"], "<-", item["src"])
    if items:
        log("workflows installed:", len(items))


def _require_text(dst, items):
    """profile 说「这些文件里必须含这些字样」—— 查的是「这棵树是不是我以为的那棵」。

    不联网、不装依赖：装依赖要十几分钟，那不属于推之前该做的事。所以它只做静态读盘，
    红了就是装错树（或上游把关键一行删了），不许悄悄放过。
    """
    bad = []
    for item in items:
        rel = item["path"]
        full = os.path.join(dst, rel.replace("/", os.sep))
        try:
            with open(full, encoding="utf-8", errors="replace") as f:
                body = f.read()
        except OSError:
            bad.append(rel + " (读不到)")
            continue
        if item["needle"] not in body:
            bad.append(rel + " (缺 " + item["needle"] + ")")
    if bad:
        log("MISSING_REQUIRED_TEXT", bad)
        sys.exit(EXIT_SNAPSHOT)
    log("required text ok:", len(items))


def _rewrite_projects_root(stub, dst):
    """把仓外号池桩里 projects.toml 的 root 改写成这一趟的快照路径。

    卡 E151：这一件是被改写 root 的那一份，读之前先判在不在 —— 否则缺件走的是裸
    FileNotFoundError（退 1），而不是可读的 POOL_STUB_INCOMPLETE（退 6），
    与 0/2/3/4/5/6 这张退出码表对不上（2026-11-21 真踩：删掉临时目录后重推，两趟都撞）。
    """
    projects_path = os.path.join(stub, "projects.toml")
    if not os.path.isfile(projects_path):
        log("POOL_STUB_INCOMPLETE", ["projects.toml"])
        sys.exit(EXIT_POOL)
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
    log("projects.toml root ->", dst_posix)


def _exec_bits(root):
    """源仓里哪些文件是可执行的（tree 模式要把这几个位带回快照）。

    为什么要单独搬：Windows 的文件系统没有可执行位，tar 解出来一律 100644，
    `git add` 就把它记成 100644 推到远端 —— 到了 Linux runner 上
    `scripts/ci-run-parallel.sh` 直接 Permission denied（exit 126）。这不是源仓的错，
    是「在 Windows 上造 Linux 快照」这个动作本身会丢信息，所以按源仓的记录补回去。
    """
    p = sh(["git", "ls-tree", "-r", "-z", "HEAD"], cwd=root, quiet=True)
    out = []
    for rec in (p.stdout or "").split("\0"):
        if not rec or "\t" not in rec:
            continue
        meta, path = rec.split("\t", 1)
        if meta.split(" ")[0] == "100755":
            out.append(path)
    return out


def _restore_exec_bits(dst, paths):
    if not paths:
        return
    keep = [p for p in paths if os.path.exists(os.path.join(dst, p.replace("/", os.sep)))]
    if not keep:
        return
    # 分批：Windows 的命令行长上限约 32K，几百个路径一次传会顶破。
    for i in range(0, len(keep), 200):
        chunk = keep[i:i + 200]
        sh(["git", "update-index", "--chmod=+x", "--"] + chunk, cwd=dst, quiet=True)
    log("exec bits restored:", len(keep), "of", len(paths))


def _install_adapter(dst, ad, adapter_src):
    """把适配器装进快照，装到 workflow 会去跑的那个文件名上。"""
    adapter_dst = os.path.join(dst, ad["snapshot_name"].replace("/", os.sep))
    os.makedirs(os.path.dirname(adapter_dst), exist_ok=True)
    shutil.copyfile(adapter_src, adapter_dst)
    with open(adapter_dst, "rb") as fh:
        data = fh.read()
    if not data.endswith(b"\n"):
        with open(adapter_dst, "ab") as fh:
            fh.write(b"\n")
        log("adapter trailing newline appended")
    log("adapter installed:", ad["snapshot_name"], os.path.getsize(adapter_dst), "B")


def _append_conftest_shim(dst, ad, shim_src):
    """把垫片挂到 profile 指定的那份 conftest 上。

    两条都是实测出来的：
      * 落点写过 tests/conftest.py（engineering 的形状），但 framework 的 conftest 在树根、
        dsh 与 UltraRAG 根本没有 conftest —— 写死 tests/ 的那三类仓一个都装不进去（卡 E156）。
      * 目标文件不存在时**新建**：pytest 只要树根有 conftest.py 就会加载它，
        「没有这个文件」不是「不该有垫片」。
    """
    rel = ad["conftest_path"]
    cf = os.path.join(dst, rel.replace("/", os.sep))
    with open(shim_src, "rb") as fh:
        shimtxt = fh.read()
    if os.path.exists(cf):
        with open(cf, "rb") as fh:
            body = fh.read()
        if ad["conftest_marker"].encode("utf-8") in body:
            log("CONFTEST_ALREADY_HAS_ADDOPTION")
            sys.exit(EXIT_SNAPSHOT)
        if not body.endswith(b"\n"):
            body += b"\n"
    else:
        os.makedirs(os.path.dirname(cf) or dst, exist_ok=True)
        body = b""
    with open(cf, "wb") as fh:
        fh.write(body + shimtxt)
    if not body:
        log("conftest created:", rel, len(shimtxt), "B")
    else:
        log("conftest shim appended:", len(shimtxt), "B")


def do_build(a):
    root, dst = a.root, a.dest
    prof = a.profile
    snap, sync = prof["snapshot"], prof["sync"]
    branch = prof["remote"]["branch"]

    if os.path.isdir(dst):
        shutil.rmtree(dst, ignore_errors=True)
    os.makedirs(dst, exist_ok=True)
    sh(["git", "init", "-q", "-b", branch], cwd=dst)
    sh(["git", "config", "core.autocrlf", "true"], cwd=dst)
    sh(["git", "config", "core.longpaths", "true"], cwd=dst)
    sh(["git", "remote", "add", "origin", a.remote], cwd=dst)

    if sync["mode"] == "bundle":
        # bundle 由 git bundle create <f> HEAD 生成 ⇒ 里面那根 ref 叫 HEAD（不是 refs/heads/…）
        if os.path.exists(a.bundle):
            os.remove(a.bundle)
        p = sh(["git", "bundle", "create", a.bundle, "HEAD"], cwd=root)
        if p is None or p.returncode != 0:
            log("BUNDLE_FAILED")
            sys.exit(EXIT_HISTORY)
        log("bundle bytes:", os.path.getsize(a.bundle))
        p = sh(["git", "fetch", "-q", a.bundle, "HEAD"], cwd=dst)
        if p is None or p.returncode != 0:
            log("BUNDLE_FETCH_FAILED")
            sys.exit(EXIT_HISTORY)
    elif sync["mode"] == "remote":
        # remote：远端已有同一段历史时更省 —— 但快照里只有远端那些提交，没有本机未推的。
        p = sh(["git", "fetch", "-q", "--no-tags", "origin", branch],
               cwd=dst, tries=4, env=remote_env(prof))
        if p is None or p.returncode != 0:
            log("FETCH_FAILED")
            sys.exit(EXIT_HISTORY)
    else:
        # tree：只要工作树的当前内容。源仓是浅克隆时（两个值：git rev-parse）打出来的 bundle
        # 是**断链**，fetch 会报 did not send all necessary objects —— 那不是网络坏，
        # 是历史本身不完整。这条路不要源仓的历史，只要它此刻树长什么样。
        pass
    p = sh(["git", "rev-parse", "HEAD"], cwd=root, quiet=True)
    log("ROOT HEAD:", (p.stdout or "").strip())
    if sync["mode"] == "tree":
        # tar 先落盘再解：sh() 抓的是文本 stdout，二进制直接过管道会被按 utf-8 拆坏。
        tar = os.path.join(a.tmp, a.repo_name + "-tree.tar")
        if os.path.exists(tar):
            os.remove(tar)
        p = sh(["git", "archive", "--format=tar", "-o", tar, "HEAD"], cwd=root, quiet=True)
        if p is None or p.returncode != 0:
            log("ARCHIVE_FAILED")
            sys.exit(EXIT_HISTORY)
        import tarfile
        with tarfile.open(tar) as tf:
            tf.extractall(dst)
        os.remove(tar)
        log("tree extracted:", len(os.listdir(dst)), "entries at top level")
        # 快照的**起点**自己造：这条路不搬源仓历史，所以它只有「base + 构建提交」两笔。
        sh(["git", "add", "-A", "."], cwd=dst)
        p = sh(["git", "commit", "-q", "-m", "base: working tree snapshot"], cwd=dst)
        if p is None or p.returncode != 0:
            log("BASE_COMMIT_FAILED")
            sys.exit(EXIT_HISTORY)
        p = sh(["git", "rev-parse", "HEAD"], cwd=dst, quiet=True)
        log("base commit:", (p.stdout or "").strip())
        # 可执行位在 Windows 上会被 tar 解包 + git add 抹平：按源仓的记录补回去，
        # 否则 Linux runner 上 `scripts/ci-run-parallel.sh` 是 Permission denied（exit 126）。
        _restore_exec_bits(dst, _exec_bits(root))
        # 不再 `git add`：那会按工作树重新判位（Windows 上没有可执行位），刚补的又会被抹掉。
        p = sh(["git", "commit", "-q", "--amend", "--no-edit"], cwd=dst)
        if p is None or p.returncode != 0:
            log("EXEC_BIT_COMMIT_FAILED")
            sys.exit(EXIT_HISTORY)
    else:
        sh(["git", "checkout", "-q", "-f", "-B", branch, "FETCH_HEAD"], cwd=dst)
    p = sh(["git", "rev-list", "--count", "HEAD"], cwd=dst, quiet=True)
    log("history commits:", (p.stdout or "").strip())
    p = sh(["git", "log", "--oneline", "-1"], cwd=dst, quiet=True)
    log("base:", (p.stdout or "").strip())
    _require_files(dst, snap["require_files"])
    _install_extra_files(dst, snap["extra_files"])

    if snap["from_remote_workflows"]:
        # 浅 fetch 只用来拿**冻结的** .github（workflow 正文在远端那一份里，本 token 改不了它）
        p = sh(["git", "fetch", "--no-tags", "--depth", "1", "origin", branch],
               cwd=dst, tries=4, quiet=True, env=remote_env(prof))
        if p is None or p.returncode != 0:
            log("FETCH_FAILED")
            sys.exit(EXIT_HISTORY)
        p = sh(["git", "checkout", "FETCH_HEAD", "--", ".github"], cwd=dst)
        if p is None or p.returncode != 0:
            log("WORKFLOW_CHECKOUT_FAILED")
            sys.exit(EXIT_HISTORY)
        # checkout <rev> -- <path> 只覆盖同名文件，不删「源树有、远端没有」的那些残留。
        # 残留的 workflow 会被 push 当成「新增 workflow」，而本 token 没有 workflow scope，
        # 于是整趟推不上去（卡 E156 实测：ura-gate 的 ci-smoke.yml / dockerhub-nightly.yml
        # 是上游自带的，镜像仓上从来没有过）。语义上也更对：from_remote_workflows = true
        # 的意思就是「.github 逐字等于远端那份」。只删远端没有的，别整棵删 ——
        # 那会把源树自己有、远端也有的东西一起抹掉。
        p = sh(["git", "ls-tree", "-r", "--name-only", "FETCH_HEAD", "--", ".github"],
               cwd=dst, quiet=True)
        keep = set((p.stdout or "").split())
        for dirpath, _dirnames, filenames in os.walk(os.path.join(dst, ".github")):
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, dst).replace(os.sep, "/")
                if rel not in keep:
                    os.remove(full)
                    log("stale file under .github removed:", rel)
    elif not os.path.isdir(os.path.join(dst, ".github", "workflows")):
        # profile 说「workflow 归本仓自己」⇒ 树里就必须真有它，否则推上去一条作业都不会起。
        log("MISSING_WORKFLOWS_IN_TREE")
        sys.exit(EXIT_HISTORY)
    _install_workflows(dst, prof["workflow"]["install"])
    if os.path.isdir(os.path.join(dst, ".github", "workflows")):
        log("workflows:", sorted(os.listdir(os.path.join(dst, ".github", "workflows"))))

    # 「这棵树是不是我以为的那棵」要在装依赖之前就判掉：装依赖十几分钟，装完才发现
    # 装错树是最贵的失败方式。键的语义见 gate_profile.SCHEMA 的 [snapshot].require_text。
    _require_text(dst, snap["require_text"])

    if prof["pool"]["stub"]:
        stub = a.stub
        if not os.path.isdir(stub):
            log("MISSING_POOL_STUB", stub)
            sys.exit(EXIT_POOL)
        names = sorted(os.listdir(stub))
        miss = [n for n in prof["pool"]["need"] if n not in names]
        if miss:
            log("POOL_STUB_INCOMPLETE", miss)
            sys.exit(EXIT_POOL)
        if prof["pool"]["rewrite_root"]:
            _rewrite_projects_root(stub, dst)
        if os.path.isdir(os.path.join(dst, "infra")):
            log("INFRA_INSIDE_SNAPSHOT")
            sys.exit(EXIT_POOL)
        log("pool stub (outside repo):", names)

    ad = prof["adapter"]
    if ad["enabled"]:
        _install_adapter(dst, ad, a.adapter)
        if ad["conftest_shim"]:
            _append_conftest_shim(dst, ad, a.conftest_shim)

    if snap["ledger_exempt"]:
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
        for rel in snap["ledger_exempt"]:
            block += '  "' + rel + '",' + nl
        block += "]" + nl + nl
        idx = txt.index("[meta]")
        with open(tr, "w", encoding="utf-8", newline=nl) as fh:
            fh.write(txt[:idx] + block + txt[idx:])
        log("ledger exempt block written:", len(snap["ledger_exempt"]), "entries")

    for keep in snap["evidence_files"]:
        f = os.path.join(dst, keep.replace("/", os.sep))
        if not os.path.exists(f):
            log("MISSING_EVIDENCE_FILE", keep)
            sys.exit(EXIT_SNAPSHOT)
        bak = os.path.join(a.tmp, "before-" + keep.replace("/", "_"))
        shutil.copyfile(f, bak)
        log("kept evidence", keep, os.path.getsize(f), "B")

    if ad["enabled"] and ad["diag_fixtures"]:
        # 生成器之前必须**先造出适配器运行时才会造的那些 fixture**，否则快照里的读数与
        # runner 上的现算对不上：适配器现写 3 份 wb-*.jsonl ⇒ gen_pool_readme 的
        # unreadable_diag_rows() 读到 3（不是 0）⇒ 拿 3 去比文件里那个数 ⇒ 5 条 pytest 红。
        shim = load_module(a.adapter, "gha_adapter_build")
        shim.ROOT = dst
        shim._ensure_diag_fixtures()

    # 派生文档与现算对齐：必须在**产物树里**跑生成器，而不是把开发机的数字搬过去。
    for item in snap["generators"]:
        g = sh([sys.executable, "-X", "utf8"] + gate_profile.shell_split(item["cmd"]),
               cwd=dst, quiet=True, env=gen_env())
        log(item["tag"] + "_RC", None if g is None else g.returncode)
        log(item["tag"] + "_OUT", ((g.stdout or "") + (g.stderr or ""))[-1200:])

    log("BUILD_OK", dst)


def do_smoke(a):
    dst = a.dest
    prof = a.profile
    ad, sm = prof["adapter"], prof["smoke"]
    # 冒烟必须**复刻适配器在 runner 上做的事**，否则冒烟绿了、真跑还红。
    if ad["enabled"]:
        shim = load_module(a.adapter, "gha_adapter_smoke")
        shim.ROOT = dst
        if prof["pool"]["stub"]:
            shim._ensure_pool_stub()
        if ad["diag_fixtures"]:
            shim._ensure_diag_fixtures()
    env = smoke_env(dst, prof)

    # 每段都先打完自己的读数再判：日志要留得住哪一段红、红在哪几行，
    # 但**判据是退出码**——一段红就不许把这一趟当绿（卡 E145 问题 2：这里以前
    # 只 log 不 exit，dest 指错地方时三段全红、脚本还退 0）。
    red = []

    def _step(tag, argv, tail):
        log("=== " + tag + " ===")
        p = sh(argv, cwd=dst, quiet=True, env=env)
        log(tag + "_RC", None if p is None else p.returncode)
        log(tag + "_OUT", ((p.stdout or "") + (p.stderr or ""))[-tail:])
        if p is None or p.returncode != 0:
            red.append(tag)

    if sm["python_targets"]:
        _step("SMOKE1", [sys.executable, "-X", "utf8", "-m", "pytest", "-q", "-o", "addopts=",
                         "-p", "no:cacheprovider"] + sm["python_targets"], 6000)
    if sm["ruff_paths"]:
        _step("SMOKE2",
              [sys.executable, "-X", "utf8", "-m", "ruff", "check"] + sm["ruff_paths"], 2000)
    if sm["docs_check"]:
        _step("SMOKE3",
              [sys.executable, "-X", "utf8"] + gate_profile.shell_split(sm["docs_check"]), 1500)
    # profile 自带的命令（node 腿用它跑 node 版本契约之类几秒的真判据）
    for item in sm["commands"]:
        _step(item["tag"], gate_profile.shell_split(item["cmd"]), 4000)

    if red:
        log("SMOKE_FAILED", ",".join(red), "-> refuse to report green")
        sys.exit(EXIT_SNAPSHOT)


def do_push(a):
    dst = a.dest
    prof = a.profile
    ad, sm = prof["adapter"], prof["smoke"]
    branch = prof["remote"]["branch"]
    sh(["git", "config", "user.name", a.git_user], cwd=dst)
    sh(["git", "config", "user.email", a.git_email], cwd=dst)
    sh(["git", "add", "-A"], cwd=dst)
    p = sh(["git", "status", "--porcelain"], cwd=dst, quiet=True)
    lines = [ln for ln in (p.stdout or "").splitlines() if ln.strip()]
    log("changed entries:", len(lines))
    for ln in lines[:15]:
        log("  ", ln)
    if not lines and prof["sync"]["mode"] == "tree":
        # tree 模式的整个树在 build 段就已经落成一笔提交（not 一个 base + 一个构建提交：
        # 这条路不搬源仓历史，第一笔就是全部内容）。冒烟段若没改动任何文件，这里就
        # 没有第二笔可写 —— 那不是失败，**不许**退 4（实测 2026-11-20：openmaic 的
        # 冒烟只跑 node 版本契约与 lockfile-only，二者都不改盘 ⇒ changed entries: 0）。
        # 照原样推 HEAD：远端的树确实会变（行尾 / 模式位），GHA 照样会被触发。
        log("NOTHING_TO_COMMIT", "(tree 模式的整棵树已在 build 段提交，冒烟无改动) -> push HEAD")
    else:
        # Task: trailer 是台账仓的判据（audit 门与 pytest_select 的 log_batch() 都读它）。
        # 没有台账的仓由 profile 给空 task ⇒ 不写 —— 硬塞一个编号等于伪造出处。
        msg = a.message
        if a.task:
            msg = msg + "\n\nTask: " + a.task
        r = sh(["git", "commit", "-q", "-m", msg], cwd=dst)
        if r is None or r.returncode != 0:
            log("COMMIT_FAILED")
            sys.exit(EXIT_COMMIT)
    p = sh(["git", "rev-parse", "HEAD"], cwd=dst, quiet=True)
    log("HEAD:", (p.stdout or "").strip())

    if sm["post_commit_targets"]:
        # 提交之后才能判的判据（都读「最近一笔提交」）：trailer 是否合规、以及依赖
        # audit 判决的 docs 片段判据。红了就**不推**（否则又是一趟白跑的 GHA）。
        env4 = smoke_env(dst, prof)
        env4["GHA_GATE_ADAPTER"] = "1"
        if ad["enabled"] and ad["diag_fixtures"]:
            shim = load_module(a.adapter, "gha_adapter_push")
            shim.ROOT = dst
            shim._ensure_diag_fixtures()  # 幂等：--stage push 单跑时也要有那几份
        log("=== SMOKE 4: post-commit trailer checks ===")
        p = sh([sys.executable, "-X", "utf8", "-m", "pytest", "-q", "-o", "addopts=",
                "-p", "no:cacheprovider"] + sm["post_commit_targets"],
               cwd=dst, quiet=True, env=env4)
        log("SMOKE4_RC", None if p is None else p.returncode)
        log("SMOKE4_OUT", ((p.stdout or "") + (p.stderr or ""))[-3000:])
        if p is None or p.returncode != 0:
            log("SMOKE4_FAILED -> refuse to push")
            sys.exit(EXIT_POOL)

    p = sh(["git", "push", "--progress", "--force", "origin",
            "HEAD:refs/heads/" + branch], cwd=dst, tries=4, quiet=True, env=remote_env(prof))
    ok = p is not None and p.returncode == 0
    if ok:
        log("PUSH_OK via " + prof["remote"]["transport"])
    else:
        log("PUSH_FAILED")
    log("PUSH_RC:", 0 if ok else 1)
    log("BUILD_DONE")


def build_parser():
    ap = argparse.ArgumentParser(
        prog="build_snapshot.py",
        description="按 profile 把当前树打成快照推到 GHA 仓，让那边的 workflow 跑门禁。",
    )
    ap.add_argument("--repo", default=os.environ.get("GHA_REPO", "engineering"),
                    help="哪一份 profile（gha/profiles/<仓>.toml；也可给 .toml 路径）")
    ap.add_argument("--stage", default=os.environ.get("STAGE", "all"),
                    choices=["all", "build", "smoke", "push"])
    ap.add_argument("--root", default=None, help="源树根（默认 git rev-parse --show-toplevel）")
    ap.add_argument("--dest", default=None,
                    help="快照目录（默认 <tmp>/<profile.snapshot.dir_name>）")
    ap.add_argument("--tmp", default=None, help="临时目录（默认 <root>/gates/diag/_tmp）")
    ap.add_argument("--bundle", default=None,
                    help="历史 bundle 落点（默认 <tmp>/<profile.sync.bundle_name>）")
    ap.add_argument("--remote", default=None,
                    help="快照要推到的远端（默认取 profile 指定的环境变量）")
    ap.add_argument("--stub", default=None, help="仓外号池桩目录（默认 <tmp>/infra/pool）")
    ap.add_argument("--adapter", default=None,
                    help="适配器路径（默认 <本目录>/<profile.adapter.src>）")
    ap.add_argument("--conftest-shim", default=None,
                    help="覆盖率选项垫片（默认 <本目录>/<profile 给的名字>）")
    ap.add_argument("--task", default=None, help="快照提交的 Task trailer（默认取 profile）")
    ap.add_argument("--message", default=None, help="快照提交的标题行（默认取 profile）")
    ap.add_argument("--git-user", default=os.environ.get("GHA_GIT_USER", "gate-bot"))
    ap.add_argument("--git-email", default=os.environ.get("GHA_GIT_EMAIL", "gate-bot@example.com"))
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    # ★ profile 先读：它决定后面每一条默认值；不成立时退 2 比后面 traceback 好读。
    try:
        a.profile = gate_profile.load(a.repo)
    except gate_profile.ProfileError as exc:
        log("PROFILE_INVALID", str(exc))
        return EXIT_CONFIG
    prof = a.profile
    a.repo_name = prof["name"] or os.path.basename(str(a.repo))
    a.root = os.path.abspath(a.root or git_toplevel(HERE))
    a.tmp = os.path.abspath(a.tmp or os.path.join(a.root, "gates", "diag", "_tmp"))
    snap_dir = prof["snapshot"]["dir_name"] or a.repo_name
    a.dest = os.path.abspath(a.dest or os.path.join(a.tmp, snap_dir))
    a.bundle = os.path.abspath(a.bundle or os.path.join(
        a.tmp, prof["sync"]["bundle_name"] or (a.repo_name + "-history.bundle")))
    a.stub = os.path.abspath(a.stub or os.path.join(a.tmp, "infra", "pool"))
    a.message = a.message if a.message is not None else prof["message"]
    a.task = a.task if a.task is not None else prof["task"]
    ad = prof["adapter"]
    a.adapter = os.path.abspath(a.adapter or os.path.join(HERE, ad["src"])) if ad["enabled"] else ""
    a.conftest_shim = (os.path.abspath(a.conftest_shim or os.path.join(HERE, ad["conftest_shim"]))
                       if ad["enabled"] and ad["conftest_shim"] else "")
    a.remote = (a.remote or "").strip() if a.remote is not None else ""
    if not a.remote:
        a.remote = os.environ.get(prof["remote"]["env"], "").strip()
    if not a.remote:
        log("MISSING_REMOTE", "( --remote 或 " + prof["remote"]["env"] + " )")
        return EXIT_CONFIG
    if ad["enabled"]:
        for label, path in (("adapter", a.adapter), ("conftest_shim", a.conftest_shim)):
            if path and not os.path.exists(path):
                log("MISSING_" + label.upper(), path)
                return EXIT_CONFIG
    os.makedirs(a.tmp, exist_ok=True)
    # 除 build 之外的每个 stage 都**在已有的快照目录上干活**（smoke 还会往
    # <dest>/../infra/pool 造桩、往 <dest>/gates/diag 写 fixture）。目录不在还往下走，
    # 只会得到 traceback（push）或全红的假绿（smoke）——卡 E145 问题 1/2 实测。
    # ★ 只有 smoke / push 需要目录**已经**在；build 与 all 都是「从头造」，造完就有了。
    #   （--stage all 在全新 dest 上曾被这条挡成退 2 —— 2026-11-21 实测。）
    if a.stage in ("smoke", "push") and not os.path.isdir(a.dest):
        log("MISSING_DEST", a.dest)
        return EXIT_CONFIG
    log("profile:", a.repo_name, "(" + a.repo_name + ".toml)")
    log("root:", a.root)
    log("dest:", a.dest)
    log("remote:", a.remote)
    log("transport:", prof["remote"]["transport"], "branch:", prof["remote"]["branch"])
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
