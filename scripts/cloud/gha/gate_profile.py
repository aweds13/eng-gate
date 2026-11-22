"""GHA 云门禁的「每仓一份适配层」—— 与 ECS 那条路的 scripts/cloud/profiles/<仓>.toml 同一个意思。

为什么要有它：scripts/cloud/gha/build_snapshot.py 里原来写死的全是 engineering 的形状
（快照装成 tests/test_windows_autostart_e2e.py、跑 python 门禁、仓外号池桩、台账豁免块、
保留 gates/last.json 当证据、提交带 Task: trailer）。第二仓（OpenMAIC）是 node 腿：
不装 python 适配器、没有号池桩、没有台账、提交也不带 trailer。这些差异只该写在 profile 里，
骨架只认键、不认仓。

规则：
  * 文件必须叫 profiles/<仓>.toml；--repo <仓> 只认这个目录里真有的那几份。
  * **未知的段 / 未知的键一律拒**（调用方退 2 + 打 PROFILE_INVALID）—— 拼错的键静默生效
    就等于「profile 写了但没人读」，这类洞在 ECS 那条路上踩过一次。
  * 缺省的键一律取 SCHEMA 里的默认值，所以同一份骨架能服务「配全」和「只配一半」的仓。
  * 这里不碰盘（除了读这份 toml）、不联网、不看环境变量：只做「文件 → 结构」。
"""
from __future__ import annotations

import os
import shlex
from pathlib import Path

import tomllib

#: profile 目录（与 ECS 那条路的 scripts/cloud/profiles/ 分开放：两套骨架认的键不是一套，
#: 混在一起会让「这份 profile 喂给哪个骨架」靠猜）。
PROFILES = Path(__file__).resolve().parent / "profiles"

#: 每仓一份适配层能说的**全部**键。四种类型：
#:   str / bool / strlist（字符串列表）/ cmdlist（[{tag, cmd}] 的命令表）/
#:   srcdst（[{src, dst}] 的文件搬运表）。
SCHEMA = {
    "name": ("str", ""),
    "message": ("str", ""),
    "task": ("str", ""),
    "remote": {
        # 远端 URL 从哪个环境变量取（--remote 仍然优先）。
        "env": ("str", "GHA_REMOTE"),
        # 推仓走哪条传输：ssh 需要 GIT_SSH_COMMAND；https 交给 credential helper。
        "transport": ("str", "ssh"),
        # 快照推到远端的哪条分支（镜像仓都只有一条 main）。
        "branch": ("str", "main"),
    },
    "sync": {
        # bundle = 本机 git bundle 打到快照目录再 fetch（不依赖远端历史）；
        # remote = 直接从远端取（远端已有同一段历史时更省）；
        # tree   = 只要工作树的**当前内容**（源仓是浅克隆时用：浅仓打出来的 bundle 是断链，
        #          fetch 会报 did not send all necessary objects —— 不是网络问题）。
        "mode": ("str", "bundle"),
        "bundle_name": ("str", ""),
    },
    "snapshot": {
        "dir_name": ("str", ""),
        # true = 从远端取 .github（workflow 在远端冻结、本 token 改不了）；
        # false = 用源树自带的 .github（该仓的 workflow 归它自己）。
        "from_remote_workflows": ("bool", True),
        # 快照里必须存在的路径（缺一个就退 5：说明这一趟装错树了）。
        "require_files": ("strlist", []),
        # 快照里必须**含有的字样**：[{path="", needle=""}]。查的是「这棵树是不是我以为的那棵」，
        # （这条也用来证明「装进去的 workflow 真的提到了要跑的那个命令」）
        # 不联网、不装依赖 —— 装依赖要十几分钟，那不属于推之前该做的事。
        "require_text": ("pairlist", []),
        # 必须保留的「上一趟读数」（缺了就退 5：它们是审计证据，不是生成物）。
        "evidence_files": ("strlist", []),
        # 提交面里这次构建会碰到的文件（写进台账豁免块；空 = 不写豁免块）。
        "ledger_exempt": ("strlist", []),
        # 派生文档生成器：[{tag="GEN_XXX", cmd="scripts/gen_x.py --flag"}]。
        "generators": ("cmdlist", []),
        # 往快照里补的引导件：[{src="", dst=""}]，src 相对本目录、dst 相对快照根。
        # 用在「源仓不是 Python 项目，但远端冻结的 workflow 硬要 pip install -e .」这种错配上
        # （卡 E156 实测：dsh 是 Node 仓，没有 pyproject.toml ⇒ 那一步 exit 1，连适配器都没跑到）。
        "extra_files": ("srcdst", []),
    },
    "workflow": {
        # 装进快照的件：[{src="", dst=""}]，src 相对本目录、dst 相对快照根。
        # 有的仓 workflow 在远端冻结、改不了（engineering：本 token 没有 workflow scope）；
        # 有的仓归它自己（OpenMAIC：推上去就按树里那几份跑）—— 后者要给这道门单独装一份，
        # 因为它自己的 ci.yml 是给它自己用的，不认我们那套 BEGIN/END 读数。
        "install": ("srcdst", []),
    },
    "adapter": {
        "enabled": ("bool", False),
        "src": ("str", "adapter.py"),
        "snapshot_name": ("str", ""),
        # 垫片文件（相对 scripts/cloud/gha/）；追加到快照里的哪份 conftest 由 conftest_path 决定。
        "conftest_shim": ("str", ""),
        # 垫片挂在哪份 conftest 上（相对快照根）。默认 tests/conftest.py = engineering 的老形状；
        # 树根就有 conftest.py 的仓（framework）或根本没有 conftest 的仓（dsh / UltraRAG）
        # 必须把它指到 "conftest.py" —— 写死 tests/ 的话那两类仓连垫片都装不进去（卡 E156）。
        "conftest_path": ("str", "tests/conftest.py"),
        # 幂等判据：这份 conftest 里已经有这个字样 ⇒ 说明垫片装过了，退 5 而不是装第二份。
        "conftest_marker": ("str", "pytest_addoption"),
        "diag_fixtures": ("bool", False),
    },
    "pool": {
        "stub": ("bool", False),
        "need": ("strlist", []),
        "rewrite_root": ("bool", False),
    },
    "smoke": {
        "python_targets": ("strlist", []),
        # ruff 只在给了目录的仓跑（它属于冒烟，不属于快照形状）。
        "ruff_paths": ("strlist", []),
        "commands": ("cmdlist", []),
        "docs_check": ("str", ""),
        "post_commit_targets": ("strlist", []),
        # 冒烟期注入的环境变量（"K=V"；空 = 不注入）。
        "env": ("strlist", []),
    },
}

#: 顶层那三个字符串键（其余都是段）。
_SCALARS = ("name", "message", "task")


class ProfileError(Exception):
    """profile 不成立（缺文件 / 未知键 / 类型不对 / 名字对不上）。调用方转成退出码 2。"""


def list_repos():
    """profiles/ 里真有的仓名（排序，给 --repo 的 choices 用）。

    刻意**不读测试里那张白名单**：判据要能独立于实现说出「这个仓有适配层」，
    从被测代码反查白名单会让判据跟着实现一起漂。
    """
    if not PROFILES.is_dir():
        return []
    return sorted(p.stem for p in PROFILES.glob("*.toml"))


def resolve(repo_or_path):
    """--repo openmaic 与一份 .toml 的路径都收。"""
    p = Path(repo_or_path)
    if p.suffix == ".toml" or p.is_file():
        return p
    return PROFILES / (repo_or_path + ".toml")


def _check(where, value, kind):
    if kind == "str":
        if not isinstance(value, str):
            raise ProfileError(where + " 必须是字符串，现在是 " + type(value).__name__)
        return
    if kind == "bool":
        if not isinstance(value, bool):
            raise ProfileError(where + " 必须是 true/false，现在是 " + repr(value))
        return
    if kind == "strlist":
        if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
            raise ProfileError(where + " 必须是字符串列表，现在是 " + repr(value))
        return
    if kind == "pairlist":
        if not isinstance(value, list):
            raise ProfileError(where + " 必须是表数组，现在是 " + repr(value))
        for i, item in enumerate(value):
            if not isinstance(item, dict) or set(item) != {"path", "needle"}:
                raise ProfileError(
                    where + "[" + str(i) + "] 必须是 {path=..., needle=...} 两项都有的表，现在是 "
                    + repr(item))
            for k in ("path", "needle"):
                if not isinstance(item[k], str) or not item[k].strip():
                    raise ProfileError(where + "[" + str(i) + "]." + k + " 必须是非空字符串")
        return
    if kind == "srcdst":
        if not isinstance(value, list):
            raise ProfileError(where + " 必须是表数组，现在是 " + repr(value))
        for i, item in enumerate(value):
            if not isinstance(item, dict) or set(item) != {"src", "dst"}:
                raise ProfileError(
                    where + "[" + str(i) + "] 必须是 {src=..., dst=...} 两项都有的表，现在是 "
                    + repr(item))
            for k in ("src", "dst"):
                if not isinstance(item[k], str) or not item[k].strip():
                    raise ProfileError(where + "[" + str(i) + "]." + k + " 必须是非空字符串")
        return
    if kind == "cmdlist":
        if not isinstance(value, list):
            raise ProfileError(where + " 必须是命令表（数组），现在是 " + repr(value))
        for i, item in enumerate(value):
            if not isinstance(item, dict) or set(item) != {"tag", "cmd"}:
                raise ProfileError(
                    where + "[" + str(i) + "] 必须是 {tag=..., cmd=...} 两项都有的表，现在是 "
                    + repr(item))
            for k in ("tag", "cmd"):
                if not isinstance(item[k], str) or not item[k].strip():
                    raise ProfileError(where + "[" + str(i) + "]." + k + " 必须是非空字符串")
        return
    raise AssertionError("未知的键类型 " + repr(kind))


def load(repo_or_path):
    """读一份 profile，补全缺省值，逐键校验。返回「段 → 键」两层 dict（顶层键在自身）。"""
    path = resolve(repo_or_path)
    if not path.is_file():
        raise ProfileError("找不到 profile：" + str(path))
    try:
        with open(path, encoding="utf-8") as fh:
            raw = tomllib.loads(fh.read())
    except tomllib.TOMLDecodeError as exc:
        raise ProfileError(str(path) + " 不是合法 TOML：" + str(exc)) from exc

    out = {}
    for key in _SCALARS:
        kind, default = SCHEMA[key]
        value = raw.pop(key, default)
        _check(path.name + ":" + key, value, kind)
        out[key] = value

    sections = [k for k in SCHEMA if k not in _SCALARS]
    unknown = sorted(set(raw) - set(sections))
    if unknown:
        raise ProfileError(
            path.name + ": 未知的段 " + str(unknown) + "（只认 " + str(sorted(sections)) + "）"
            " —— 拼错一个段名就等于这段配置没人读")

    for section in sections:
        table = raw.get(section, {})
        if not isinstance(table, dict):
            raise ProfileError(path.name + ": [" + section + "] 必须是一张表")
        spec = SCHEMA[section]
        bad = sorted(set(table) - set(spec))
        if bad:
            raise ProfileError(
                path.name + ": [" + section + "] 里有未知的键 " + str(bad)
                + "（只认 " + str(sorted(spec)) + "）")
        merged = {}
        for key, (kind, default) in spec.items():
            value = table.get(key, default)
            _check(path.name + ":[" + section + "]." + key, value, kind)
            merged[key] = value
        out[section] = merged

    _cross_check(path, out)
    return out


def _cross_check(path, out):
    """跨键的约束：单看一个键都对、合起来自相矛盾的那几种。"""
    if out["name"] and out["name"] != path.stem:
        raise ProfileError(
            path.name + ": name = " + repr(out["name"]) + " 与文件名 " + repr(path.stem)
            + " 对不上 —— --repo 认的是文件名，两处不一致会让「哪份 profile 在跑」只能靠猜")
    if out["remote"]["transport"] not in ("ssh", "https"):
        raise ProfileError(
            path.name + ": [remote].transport = " + repr(out["remote"]["transport"])
            + "（只认 ssh / https）")
    if out["sync"]["mode"] not in ("bundle", "remote", "tree"):
        raise ProfileError(
            path.name + ": [sync].mode = " + repr(out["sync"]["mode"])
            + "（只认 bundle / remote / tree）")
    if out["sync"]["bundle_name"] and out["sync"]["mode"] != "bundle":
        raise ProfileError(path.name + ": [sync].bundle_name 只在 mode = bundle 时有意义")
    if out["adapter"]["enabled"] and not out["adapter"]["snapshot_name"]:
        raise ProfileError(
            path.name + ": [adapter].enabled = true 时必须给 snapshot_name"
            "（装到快照里叫什么，是 workflow 能收集到它的唯一依据）")
    if out["adapter"]["conftest_shim"] and not out["adapter"]["enabled"]:
        raise ProfileError(
            path.name + ": [adapter].conftest_shim 给了路径但没有适配器 —— 垫片是给"
            "适配器在 runner 上收集用例用的，没适配器就没有人要它")
    if out["adapter"]["diag_fixtures"] and not out["adapter"]["enabled"]:
        raise ProfileError(
            path.name + ": [adapter].diag_fixtures = true 但没有适配器 —— 那些 fixture 是"
            "适配器运行时现写的，没适配器就没有人写它们")
    cp = out["adapter"]["conftest_path"]
    if cp.startswith("/") or "\\" in cp or ".." in cp.split("/"):
        raise ProfileError(
            path.name + ": [adapter].conftest_path = " + repr(cp)
            + " 必须是快照内的相对路径（POSIX 分隔符）—— 垫片只往快照里写，不许写到外面")
    if not out["adapter"]["conftest_marker"].strip():
        raise ProfileError(
            path.name + ": [adapter].conftest_marker 不能为空 —— 它是「垫片装过没有」的唯一依据，"
            "空串会让每一趟都判定成没装过")
    tuned = (cp != "tests/conftest.py"
             or out["adapter"]["conftest_marker"] != "pytest_addoption")
    if tuned and not out["adapter"]["conftest_shim"]:
        raise ProfileError(
            path.name + ": 调了 conftest_path / conftest_marker 却没有 conftest_shim"
            " —— 没有垫片文件，这两个键没人读")
    for item in out["snapshot"]["extra_files"]:
        dst = item["dst"]
        if dst.startswith("/") or ".." in dst.split("/"):
            raise ProfileError(
                path.name + ": [snapshot].extra_files 里 " + repr(dst)
                + " 必须是快照内的相对路径（这些是往快照里补的引导件，不许写到外面）")
        if dst.replace(os.sep, "/").startswith(".github/"):
            raise ProfileError(
                path.name + ": [snapshot].extra_files 里 " + repr(dst)
                + " 落在 .github/ 下 —— workflow 归 [workflow].install 管，"
                "这里写会被 from_remote_workflows 的远端那份盖掉")
    for item in out["workflow"]["install"]:
        if item["dst"].startswith("/") or ".." in item["dst"].split("/"):
            raise ProfileError(
                path.name + ": [workflow].install 里 " + repr(item["dst"])
                + " 必须是快照内的相对路径（这些都是往快照里写，不许写到外面）")
    if out["workflow"]["install"] and out["snapshot"]["from_remote_workflows"]:
        raise ProfileError(
            path.name + ": [workflow].install 与 [snapshot].from_remote_workflows = true 相冲"
            " —— 后者会用远端那份 .github 覆盖掉刚装进去的 workflow")
    if out["pool"]["stub"] and not out["pool"]["need"]:
        raise ProfileError(
            path.name + ": [pool].stub = true 时必须给 need（桩里必须有哪几件）"
            " —— 空清单等于「桩里什么都没有」却照样判合格")
    if out["pool"]["need"] and not out["pool"]["stub"]:
        raise ProfileError(path.name + ": [pool].need 给了清单但 stub = false，没人会去造它")
    if out["pool"]["rewrite_root"] and not out["pool"]["stub"]:
        raise ProfileError(path.name + ": [pool].rewrite_root 只在 stub = true 时有意义")
    if out["pool"]["rewrite_root"] and "projects.toml" not in out["pool"]["need"]:
        # 卡 E151：rewrite_root 要读 projects.toml 改 root，而 need 只校验列在里面的件。
        # 少列它的时候，缺件不是「桩不完整」（退 6）而是裸 FileNotFoundError（退 1）。
        raise ProfileError(
            path.name + ": [pool].rewrite_root = true 时 need 里必须有 projects.toml"
            " —— 那是被改写 root 的那一件；不列进 need 就没人开跑前查它在不在，"
            "缺件会变成裸 FileNotFoundError 而不是可读的 POOL_STUB_INCOMPLETE")
    if out["snapshot"]["ledger_exempt"] and not out["message"]:
        raise ProfileError(path.name + ": 要写台账豁免块就必须有 message")
    for item in out["smoke"]["env"]:
        if "=" not in item:
            raise ProfileError(
                path.name + ": [smoke].env 里 " + repr(item) + " 不是 KEY=VALUE")


def shell_split(cmd):
    """把 profile 里写成一行的命令拆成 argv。

    用 shlex（posix=True）：**认引号**。理由是一条实测出来的需求 —— node 腿要跑
    形如 node -e "<一段带分号/括号的 JS>"，按空白硬拆会把那段 JS 拆成好几截。
    仍然不认管道 / 重定向 / 变量展开：这里只拆参数，**不起 shell**。
    """
    return shlex.split(cmd, posix=True)
