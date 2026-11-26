"""GitHub Actions（Windows）上的门禁适配器 —— 库里的一份源码，由构建脚本装成快照里的一个测试文件。

## 它是什么

`scripts/cloud/run_gate.sh` 那条路是「租一台云机、ssh 过去跑门禁」；这一条不租机器：
`scripts/cloud/gha/build_snapshot.py` 把树打成快照推给 GitHub，由那边继承来的
`.github/workflows/ci.yml` 里那个 `windows-autostart-e2e` 作业跑门禁。

## 为什么钉这个文件名

那个作业的最后一步写死是

    python -m pytest -q tests/test_windows_autostart_e2e.py

而本 token 没有 workflow scope（写不了 workflow 文件）。⇒ workflow 是**冻结的骨架**，
「跑什么」只能靠这个文件名钉住的适配器承载：它替云机把 23 道门跑一遍，
再把真读数（gates/last.json）原样打到作业日志里 —— 日志就是回传通道。
**这个文件名不许改**，改了作业就收集不到任何东西、整趟绿得毫无意义。

## 两条防呆（缺一条就会自己咬自己）

1. 只在 `GITHUB_ACTIONS == "true"` 时干活（本机 collect 到直接放过、不写任何文件）。
2. 门禁自己的 pytest 也会收集到这个文件 ⇒ 用 `GHA_GATE_ADAPTER` 拦住递归。
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BEGIN = "=== GHA-GATE-READING-BEGIN ==="
END = "=== GHA-GATE-READING-END ==="
MISSING = "=== GHA-GATE-READING-MISSING ==="
GUARD = "GHA_GATE_ADAPTER"

# workflow 只装了运行期依赖 + pytest；门禁要的 dev 工具与三件隐式依赖在这里补。
# 版本钉法抄 scripts/cloud/bootstrap.ps1:50-62（卡 E49 的教训：ruff 版本差会判出不同结果）。
EXTRA = [
    "pytest-cov==7.1.0",
    "pytest-xdist==3.8.0",
    "mypy==2.3.1",
    "ruff==0.16.6",
    "hypothesis",
    "httpx==0.28.1",
    "fsrs==6.3.2",
    "psutil==7.2.2",
]


#: 仓外号池桩（四件；第五件 projects.toml 由 PROJECTS_TMPL 现写）。
#: 真号池 infra/pool/ 不在本仓（跨项目复用）：tools/pool/models.py 的 POOL_ANCHOR
#: 只沿祖先链找 infra/pool/pool_models.py，runner 上找不到 ⇒ 20 条 pytest 报「找不到项目索引」。
#: ★ 这里**没有任何凭据**：accounts.toml 只写 credential 的**位点**（file + 路径），不写内容。
STUB = {
    "pool_models.py": '"""CI stub: 只作锚点用（判据只看这个文件在不在）。"""\n',
    "models.whitelist.toml": (
        "[[approved]]\n"
        'pool = "codearts"\n'
        'model = "huaweicloud-maas/GLM-5.2"\n'
        "\n"
        "[[approved]]\n"
        'pool = "codearts"\n'
        'model = "huaweicloud-maas/deepseek-v4.1-flash"\n'
    ),
    "models.live.json": json.dumps({
        "approved": ["huaweicloud-maas/GLM-5.2", "huaweicloud-maas/deepseek-v4.1-flash"],
        "live": ["huaweicloud-maas/deepseek-v4.1-flash", "huaweicloud-maas/GLM-5.2"],
        "in_both": ["huaweicloud-maas/GLM-5.2", "huaweicloud-maas/deepseek-v4.1-flash"],
        "approved_but_missing": [],
        "live_but_unapproved": [],
        "live_names": {
            "huaweicloud-maas/deepseek-v4.1-flash": "deepseek-v4.1-flash",
            "huaweicloud-maas/GLM-5.2": "GLM-5.2",
        },
        "at": "2026-11-17 06:12:12",
        "raw_len": 100,
    }, ensure_ascii=False, indent=1) + "\n",
    "accounts.toml": (
        "[[account]]\n"
        'id = "codearts-1"\n'
        'label = "CI stub seat"\n'
        'platform = "codearts"\n'
        'state = "active"\n'
        'added_at = "2026-11-17"\n'
        'approved_models = ["huaweicloud-maas/GLM-5.2", "huaweicloud-maas/deepseek-v4.1-flash"]\n'
        "\n"
        "[account.credential]\n"
        'kind = "file"\n'
        'locator = "~/.codeartsdoer/pool.env"\n'
        "\n"
        "[account.quota]\n"
        'unit = "credits"\n'
        'source = "unknown"\n'
        'observed_at = "2026-11-17T00:00:00+08:00"\n'
        "samples = []\n"
        "\n"
        "[account.health]\n"
        'state = "unknown"\n'
        "consecutive_failures = 0\n"
        'last_probe = "2026-11-17T00:00:00+08:00"\n'
        'last_checkin = "unknown"\n'
    ),
}

#: 项目索引桩。root 必须**真存在**（tools/pool/projects.py 的硬判据），
#: memory 必须与 tests/test_pool_projects.py:33 的 ENGINEERING_MEMORY **逐字一致**。
PROJECTS_TMPL = '''# GHA 云门禁：仓外项目索引（适配器现写，不进提交面）
[project.engineering]
name = "timeflow（engineering）"
root = "{root}"
memory = [
  "复盘/新窗口交接卡.md",
  "复盘/交接-重构进度.md",
  "复盘/口径坑.md",
]
layers = ["审美层", "后端", "前端", "文档层", "门禁层", "运维层"]
tree_prefixes = [".wt/"]
queue = "docs/workbacklog.toml"
ledger = "docs/traceability.toml"
cards = "复盘/卡"
'''

#: 三份派活日志 fixture（**变体名**，不是 canonical wb-<卡>.jsonl）：
#: tests/test_pool_jobs.py:392 VARIANT_LOGS 点名的三条。
#: ★ gates/diag/* 被 .gitignore 忽略 ⇒ 它们不进提交面，只在运行时现写。
FIXTURES = ("wb-E14.trae.jsonl", "wb-141.attempt1.old.jsonl", "wb-148.old.jsonl")
FIXTURE_LINE = json.dumps(
    {"ev": "verdict", "ok": False, "why": "ci fixture", "card": "E14"}, ensure_ascii=False
) + "\n"


def _show(run, tail=20000):
    print("$", " ".join(run.args), "-> rc=" + str(run.returncode), flush=True)
    out = (run.stdout or "")[-tail:]
    err = (run.stderr or "")[-6000:]
    if out:
        print(out, flush=True)
    if err:
        print(err, flush=True)


def _run(argv, env=None, timeout=None):
    return subprocess.run(
        argv,
        cwd=ROOT,
        env=env,
        timeout=timeout,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        # ★ 卡 148 的不弹窗钉子：脚本进了 scripts/ 就在判据扫描面里。
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _reading():
    path = os.path.join(ROOT, "gates", "last.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    rows = [
        {
            "name": g.get("name"),
            "exit_code": g.get("exit_code"),
            "seconds": g.get("seconds"),
            "blocking": g.get("blocking", True),
            "status": g.get("status"),
            "reused": g.get("reused"),
            "summary": (g.get("summary") or "")[:400],
        }
        for g in data.get("gates", [])
    ]
    return {
        "ok": data.get("ok"),
        "host": data.get("host"),
        "rev": data.get("rev"),
        "branch": data.get("branch"),
        "at": data.get("at"),
        "sealed_at": data.get("sealed_at"),
        "not_run": data.get("not_run"),
        "python": data.get("python"),
        "workers": data.get("workers"),
        "n_gates": len(rows),
        "gates": rows,
    }


LOGS = os.path.join(ROOT, "gates", "logs")


def _fail_lines(name, limit=120):
    """把红门的红单从 gates/logs/<门>.log 里抠出来 —— 门面只印前三类，其余全在这里。

    作业日志是唯一回传通道（workflow 冻结、没有 artifact 上传），所以红单必须自己打。
    """
    path = os.path.join(LOGS, name + ".log")
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            # ★ 必须 strip：行为流层的子断言行是「       · 标签 —— 详情」（行首 7 个空格），
            #   不 strip 就一条都收不到 —— v6/v7 两轮 ui_flow 只剩标题行、无从定性，就是这么丢的。
            s = line.strip()
            if (
                s.startswith("FAILED ")
                or s.startswith("ERROR ")
                or s.startswith("❌")
                or s.startswith("·")
                or "[FAIL]" in s
            ):
                out.append(s)
    return out[-limit:]


def _pytest_captured(limit=200):
    """pytest FAILURES 段里抄着用例的 **stdout 原文** —— 用例自己只留 `[-1500:]`（还多是 stderr
    的 `api_write` JSON），定位不了是哪条子检查红。这里把 `[OK ]`/`[FAIL]`/`[SKIP]` 行挖出来。

    ★ 只读 `gates/logs/pytest.log`，不重跑、不改判据 —— 纯取证。
    """
    path = os.path.join(LOGS, "pytest.log")
    if not os.path.exists(path):
        return []
    out = []
    inside = False
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            s = line.rstrip()
            if not inside:
                if s.startswith("====") and "FAILURES" in s:
                    inside = True
                continue
            if s.startswith("====") and (
                "warnings summary" in s or "short test summary" in s or " slowest" in s
            ):
                break
            t = s.strip()
            if t.startswith("[OK ]") or t.startswith("[FAIL]") or t.startswith("[SKIP]"):
                out.append(t)
    return out[-limit:]


def _door_log_tail(name, limit=9000):
    """红门的 `gates/logs/<门>.log` **原文尾部**（先丢掉开头的 JSONL 行）。

    为什么门级红也需要这个：v12 唯一红是 `web_live`（不是 pytest），而门面只印 FAIL 行；
    真正的现场（前 21 条 `[OK ]`、`[提示]`、`[重试]`、`[SKIP]` 各出现没出现）全在门的
    日志里。没有这一段，「没读到响应」到底是第一次就崩、还是重试过仍不成，判不出来。
    ★ 纯取证：只读盘上已有的产物，不重跑、不改判定。
    """
    path = os.path.join(LOGS, name + ".log")
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    keep = [ln for ln in text.splitlines() if not ln.startswith("{")]
    return "\n".join(keep)[-limit:]


def _web_live_repro(env, tail=4000, budget=900):
    """把 `tools/web_live_check.py` 用**同一套 env** 再跑一遍 —— 分「稳定红」与「抖动」。

    `web_live` 是门级红，不经过 pytest ⇒ v12 那三条取证钩子（都挂在 pytest 红上）一条
    都没触发。门面只印 FAIL 行，看不出前 21 条子检查是否已算出来、重试有没有发生。
    这里重跑一次（判据仍是原来的判据，只是让它在日志里把话说完），打 rc + 尾部原文。
    """
    script = os.path.join(ROOT, "tools", "web_live_check.py")
    if not os.path.exists(script):
        return
    print("=== GHA-GATE-WEBLIVE-REPRO ===", flush=True)
    argv = [sys.executable, "-X", "utf8", script]
    try:
        run = _run(argv, env=env, timeout=budget)
    except subprocess.TimeoutExpired:
        print("[web-live-repro] 超时 " + str(budget) + "s，放弃取证（不判死）", flush=True)
        return
    print("$ web-live-repro -> rc=" + str(run.returncode), flush=True)
    out = (run.stdout or "") + (run.stderr or "")
    print(out[-tail:], flush=True)


def _pytest_failures_section(limit=9000):
    """把 `gates/logs/pytest.log` 的 FAILURES 段**原文尾部**打出来。

    v11 回传的那份日志里，两条红只剩断言消息的 `[-1500:]`（尾巴全是 stderr 的 api_write
    JSON），`_pytest_captured()` 又只收 `[OK ]/[FAIL]/[SKIP]` 行 —— 这两条一条都没有，
    于是回传 0 行。原文尾部至少带着 traceback，能看出错在哪个文件哪一行、差多少。
    """
    path = os.path.join(LOGS, "pytest.log")
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    at = text.find("FAILURES")
    if at < 0:
        return text[-limit:]
    head = text.rfind("====", 0, at)
    return text[max(head, 0) :][-limit:]


def _failed_node_ids(limit=6):
    """从 pytest 的 short test summary 里取 `FAILED <nodeid>` 的 nodeid（去重、限量）。"""
    path = os.path.join(LOGS, "pytest.log")
    if not os.path.exists(path):
        return []
    ids = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            s = line.strip()
            if not (s.startswith("FAILED ") or s.startswith("ERROR ")):
                continue
            node = s.split(" ", 1)[1].split(" - ")[0].strip()
            if node and node not in ids:
                ids.append(node)
    return ids[:limit]


def _rerun_isolated(env, limit=6, tail=16000, budget=900):
    """把红掉的 nodeid **单独**重跑一遍，带 `--tb=long` 打全 traceback。

    为什么非重跑不可：全量那一趟里 pytest 的 FAILURES 段只有断言消息，而 `-n 4` 下
    究竟是不是「并发/顺序」造成的，只能靠「同样这两条单独跑会不会红」来分。
    ★ 纯取证：不影响 `gates/last.json` 的判定（那是上一趟跑完就落盘的）。
    """
    ids = _failed_node_ids(limit)
    if not ids:
        return
    print("=== GHA-GATE-ISOLATED " + str(len(ids)) + " ===", flush=True)
    for node in ids:
        print("· " + node, flush=True)
    argv = [
        sys.executable,
        "-X",
        "utf8",
        "-m",
        "pytest",
        "-q",
        "-o",
        "addopts=",
        "-p",
        "no:cacheprovider",
        "--tb=long",
        *ids,
    ]
    try:
        run = _run(argv, env=env, timeout=budget)
    except subprocess.TimeoutExpired:
        print("[isolated] 超时 " + str(budget) + "s，放弃取证（不判死）", flush=True)
        return
    print("$ isolated -> rc=" + str(run.returncode), flush=True)
    out = (run.stdout or "") + (run.stderr or "")
    print(out[-tail:], flush=True)


#: 自证用例的取证驱动：`test_web_live_bites_when_the_event_delegation_is_gone` 把副本的
#: stdout 只留 `[-1500:]`（尾巴全是 api_write JSON）⇒ runner 上哪条子检查红，回传看不到。
#: 这里把用例**原样再跑一遍**，只劫它的 `_out()` 把副本 stdout 的 `[OK ]/[FAIL]/[SKIP]` 行抄出来。
#: 不改判据、不改被跟踪源码 —— 判据还是那个判据，只是让它把话说完。
WEBLIVE_DRIVER = r"""
import importlib.util
import pathlib
import sys


class Loose(str):
    def __getitem__(self, key):
        return str(self)


root = pathlib.Path(sys.argv[1])
tmp = pathlib.Path(sys.argv[2])
tmp.mkdir(parents=True, exist_ok=True)
spec = importlib.util.spec_from_file_location(
    "sp", root / "tests" / "test_gate_selfproof_product.py"
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
texts = []


def _out(proc):
    text = (proc.stdout or "") + (proc.stderr or "")
    texts.append(text)
    return Loose(text)


mod._out = _out
failed = None
try:
    mod.test_web_live_bites_when_the_event_delegation_is_gone(tmp)
except BaseException as exc:
    failed = type(exc).__name__ + ": " + str(exc)[:600]
for idx, text in enumerate(texts):
    keep = [
        x.strip()
        for x in text.splitlines()
        if x.strip().startswith(("[OK ]", "[FAIL]", "[SKIP]"))
    ]
    print("=== WEBLIVE-OUT %d len=%d lines=%d ===" % (idx, len(text), len(keep)))
    for line in keep:
        print(line)
    if keep:
        continue
    print(text[-2500:])
print("=== WEBLIVE-EXC " + ("none" if failed is None else failed) + " ===")
"""


def _web_live_probe(env, tail=14000, budget=900):
    """把自证用例再跑一遍，把副本 web_live 的子检查行抄回来（只在 pytest 红时调）。"""
    import tempfile

    case = os.path.join(ROOT, "tests", "test_gate_selfproof_product.py")
    if not os.path.exists(case):
        return
    tmp = tempfile.mkdtemp(prefix="weblive_probe_")
    driver = os.path.join(tmp, "driver.py")
    with open(driver, "w", encoding="utf-8") as fh:
        fh.write(WEBLIVE_DRIVER)
    print("=== GHA-GATE-WEBLIVE-PROBE ===", flush=True)
    argv = [sys.executable, "-X", "utf8", driver, ROOT, os.path.join(tmp, "case")]
    try:
        run = _run(argv, env=env, timeout=budget)
    except subprocess.TimeoutExpired:
        print("[weblive-probe] 超时 " + str(budget) + "s，放弃取证（不判死）", flush=True)
        return
    print("$ weblive-probe -> rc=" + str(run.returncode), flush=True)
    out = (run.stdout or "") + (run.stderr or "")
    print(out[-tail:], flush=True)


def _ensure_history():
    """actions/checkout 默认 depth=1 ⇒ 父提交 / 历史区间一律解不开，11 条判据假红。

    实测：浅仓 `git rev-list --count HEAD` = 1，`git fetch --unshallow origin` rc=0 之后
    变成 892，`git rev-parse --short HEAD^` 也能取到 ⇒ 不必改被冻结的 workflow
    （它没有 fetch-depth 参数，改它要走 workflow scope，本 token 没有）。
    失败只记日志、**不退出**：历史类判据自己会红，别把整趟门禁按死在这里。
    """
    run = _run(["git", "fetch", "--unshallow", "origin"])
    print("[unshallow] rc=" + str(run.returncode), flush=True)
    if run.stderr.strip():
        print(run.stderr[-2000:], flush=True)


def _ensure_pool_stub():
    """现写仓外号池桩（五件）→ 返回 TF_PROJECTS_TOML 该指的那份。

    位置必须是 `<ROOT>/../infra/pool`：`tools/pool/projects.py::index_path()` 从本树逐级
    向上找 `infra/pool/projects.toml`；桩**只许在仓外** —— `DST/infra` 一旦存在，
    快照里就多出被跟踪的 infra/（那是另一个仓的东西）。
    """
    pool = os.path.join(os.path.dirname(ROOT), "infra", "pool")
    os.makedirs(pool, exist_ok=True)
    for name, text in STUB.items():
        with open(os.path.join(pool, name), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    projects = os.path.join(pool, "projects.toml")
    with open(projects, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(PROJECTS_TMPL.format(root=ROOT.replace(os.sep, "/")))
    print("[pool-stub]", pool, sorted(os.listdir(pool)), flush=True)
    return projects


def _ensure_diag_fixtures():
    """现写三份派活日志 fixture（`gates/diag/*` 被 .gitignore 忽略 ⇒ 不进提交面）。

    `tests/test_pool_jobs.py::test_real_diag_census_buckets` 三条断言：盘上非空、
    变体名归到第一段、variant 集合与测试内独立重算相等。一行合成 JSON 就满足
    （实测 `jobs.scan_jobs()` 读出 3 行、三条全 card_kind=variant）。
    """
    diag = os.path.join(ROOT, "gates", "diag")
    os.makedirs(diag, exist_ok=True)
    for name in FIXTURES:
        with open(os.path.join(diag, name), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(FIXTURE_LINE)
    print("[diag-fixtures]", list(FIXTURES), flush=True)


def test_windows_runner_runs_the_gates():
    # 门禁自己的 pytest 会收集到这个文件 —— 拦住递归（第一道防呆）。
    if os.environ.get(GUARD):
        return
    # 这个文件只存在于 GHA 快照里；主树没有它。本机 collect 到就当没跑。
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return

    print("python:", sys.version, flush=True)
    print("cwd:", ROOT, flush=True)

    run = _run([sys.executable, "-m", "pip", "install", "-q", *EXTRA])
    print("[pip-extra] rc=" + str(run.returncode), flush=True)
    if run.stderr:
        print(run.stderr[-3000:], flush=True)

    _ensure_history()
    projects = _ensure_pool_stub()
    _ensure_diag_fixtures()

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env[GUARD] = "1"
    env.setdefault("TF_PYTEST_WORKERS", "4")
    # 卡 E67 / E134：runner 上机器比开发机慢，连接层偶发抖动 —— 调等待窗与重放次数，
    # **不放宽判据**（判据仍是「全部子检查通过」）。v7 起抬到 60s：v5/v6 两轮
    # PUT /api/settings/ai 都在 30s 上超时（服务端已复核无长阻塞：set_enabled 只有一次
    # _put_raw + commit），runner 上这条连接层偶发卡顿比开发机长。
    env.setdefault("TF_WEB_LIVE_TIMEOUT", "60")
    # ★ 不设 TF_WEB_LIVE_JSON_RETRY：它是「默认值」判据的一部分
    #   （tests/test_web_live_json_retry.py:204 硬断言默认重放 1 次 ⇒ 共 2 次）。
    #   实测只留 TIMEOUT=30 就够 web_live 转绿。
    # 卡 E135（T-AG644，2026-11-19 落在 ee8e4819）：浏览器门的等待预算乘数 ——
    # 只乘时长、不动判据（上界 WAIT_SCALE_MAX=10，坏值退回 1）。在此之前这里设的值是空转：
    # v6/v7 两轮 ui_flow 各 5/26 条流红，而同一批流在本机快照逐条单跑全绿
    # ⇒ 红的是 runner 单核慢约 2×、等待窗不够，不是界面坏。同一旋钮在本机 1.8 GB 可用内存
    # 那趟门禁（TF_UI_FLOW_WAIT_SCALE=3）把 ui_flow 从 3/26 红拉回 26 条流 / 362 项断言全绿。
    env.setdefault("TF_UI_FLOW_WAIT_SCALE", "6")
    # 卡 E120：项目索引必须在**仓外**（这里现写的桩），指针指过去而不是摘掉它
    # —— 摘掉会让 20 条判据退成「找不到项目索引（不许猜路径）」
    env["TF_PROJECTS_TOML"] = projects

    run = _run([sys.executable, "-X", "utf8", "scripts/run_gates.py", "--no-reuse"], env=env)
    _show(run)
    print("[run_gates] rc=" + str(run.returncode), flush=True)

    brief = _reading()
    if brief is None:
        print(MISSING, flush=True)
        raise AssertionError("云机跑完但没有 gates/last.json —— 证明不了跑过哪几道门")
    # ★ v14：同一份读数**也落一份到盘上**（gates/diag/_gha_reading.json），
    #   由 tests/conftest.py 尾部的 pytest_terminal_summary 钩子在收尾阶段再打一遍。
    #   为什么需要：pytest 只在**失败**时打 Captured stdout ⇒ v13 那趟 23 门全绿、
    #   作业日志里一条 GHA-GATE 都没有，绿灯反而拿不到读数。钩子在 capture 之外，
    #   绿红都打。文件被 .gitignore 的 gates/diag/* 忽略，不进提交面。
    blob = json.dumps(brief, ensure_ascii=False, indent=1)
    try:
        hook_path = os.path.join(ROOT, "gates", "diag", "_gha_reading.json")
        os.makedirs(os.path.dirname(hook_path), exist_ok=True)
        with open(hook_path, "w", encoding="utf-8", newline=chr(10)) as fh:
            fh.write(blob + chr(10))
        print("[reading-hook] wrote " + hook_path, flush=True)
    except Exception as exc:  # 取证通道坏了不许改判定
        print("[reading-hook] write failed: " + repr(exc), flush=True)
    print(BEGIN, flush=True)
    print(blob, flush=True)
    print(END, flush=True)
    # 红单：门面只印前三类（"另有 29 类见日志"），逐条定性要的就是那 29 类。
    # ★ 必须打在 END 之后：BEGIN/END 之间只放那一段 JSON，别让红单里的花括号混进解析。
    bad = [g for g in brief["gates"] if g["blocking"] and g["exit_code"] != 0]
    for name in [g["name"] for g in bad]:
        lines = _fail_lines(name)
        print("=== GHA-GATE-FAILS " + name + " " + str(len(lines)) + " ===", flush=True)
        for s in lines:
            print(s, flush=True)
    # ★ v13：门级红（v12 实测是 web_live 这一道）也要有现场 —— 上面那三条只挂在
    #   pytest 红上，v12 一整轮一条都没触发。这里把**每道红门的日志尾部**打出来，再对
    #   web_live 用同一套 env 重跑一次（分「稳定红」还是「抖动」）。都不改判定。
    for name in [g["name"] for g in bad]:
        body = _door_log_tail(name)
        print("=== GHA-GATE-DOORLOG " + name + " " + str(len(body)) + " ===", flush=True)
        if body:
            print(body, flush=True)
    if "web_live" in [g["name"] for g in bad]:
        _web_live_repro(env)
    # pytest 的 FAILURES 段里抄着用例 stdout 原文（`[FAIL] …` 子检查）——
    # 用例自己的断言消息只留 `[-1500:]`，而尾巴几乎全是 stderr 的 api_write JSON。
    if "pytest" in [g["name"] for g in bad]:
        captured = _pytest_captured()
        print("=== GHA-GATE-PYTEST-CAPTURED " + str(len(captured)) + " ===", flush=True)
        for s in captured:
            print(s, flush=True)
        # v12：上面那条钩子对「用例自己不打 [OK ]/[FAIL]」的红是 0 行（v11 实测）。
        # 三条兜底全是**纯取证**，都不改 gates/last.json 的判定：
        #   ① FAILURES 段原文尾部 —— 全量那趟的 traceback；
        #   ② 把红掉的 nodeid 单独重跑（--tb=long）—— 分「并发/顺序」还是「稳红」；
        #   ③ 只对自证用例再跑一遍，把副本 web_live 的子检查行抄回来。
        section = _pytest_failures_section()
        print("=== GHA-GATE-PYTEST-FAILURES " + str(len(section)) + " ===", flush=True)
        if section:
            print(section, flush=True)
        _rerun_isolated(env)
        _web_live_probe(env)

    red = [g["name"] for g in bad]
    assert brief["ok"] is True, "门禁没绿：ok=" + repr(brief["ok"]) + "，红门=" + repr(red)
    assert not brief["not_run"], "有门未验证（NOT RUN 不是 PASS）：" + repr(brief["not_run"])
    assert brief["host"], "last.json 没有 host —— 证明不了是云机跑的"
