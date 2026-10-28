"""钉子：本机私有状态 vs 仓库分发 —— 归属 `pytest` 门。

## 为什么有这张测试（两起已在云门禁上真实导致假红的事故）

① **`.wt/` 只写在 `.git/info/exclude` 里。** 那份文件是本机私有、不随仓库分发。
   本机 `git check-ignore .wt/F6` 命中 ⇒ `scripts/check_docs.py` 把 `.wt/...` 引用当
   「gitignored ⇒ skip」；云机（克隆出来的仓，没有那份 info/exclude）**不忽略** ⇒
   20 条 `.wt/...` 引用被判成死指针，`docs` 门 dead_refs 152 → 172，门红。
   修法：`.gitignore` 尾部加 `# worktrees` + `.wt/`（现命中 `.gitignore:120`）。

② **`gates/review/` 从来没有被 ignore。** `tools/pool/landing.py` 的 `REVIEW_DIR` 与
   旁边注释一直宣称「gitignored，运行时产物」，但 `.gitignore` 里没有这条规则 ⇒
   93 个 `wb_review.py` 产出的 JSON 成了永久未跟踪，文档里引用
   `gates/review/<任务>.json` 被 `check_docs` 判死指针。修法：`.gitignore:117`。

共同形状：**凡是「云机需要、但只存在于本机私有状态」的东西，都会造成本机绿 / 云机红，
而这类差异没有任何判据能看见。** 这张测试就是把它们变成判据。

## 判据（每条都有反向用例，证明钉子真的会咬）

1. `test_info_exclude_rules_are_mirrored_in_gitignore` —— `.git/info/exclude` 的每一条
   都必须在 `.gitignore` 里有等价规则（或在 `EXCLUDE_WHITELIST` 里，每条写理由）。
2. `test_declared_runtime_artifacts_are_really_ignored` —— `.gitignore` 里那些「运行时
   产物」必须真的被忽略，**而且是在只有 `.gitignore` 的 scratch 仓里**被忽略
   （= 云机视角；在本仓里问会被 `.git/info/exclude` 掩盖）。
3. `test_workspace_crlf_vs_head_blob_lf_is_not_a_defect` /
   `test_known_multi_cr_files_still_carry_double_cr` —— 本机 `core.autocrlf=true`
   ⇒ 工作区整树 CRLF、HEAD blob 是 LF，**这不是缺陷**；要钉的是「多重 CR」（`\\r\\r`）。
4. `test_subprocess_encoding_is_pinned_elsewhere` —— 占位 skip，见用例 docstring。
5. `test_gate_code_reads_no_local_private_paths` —— `scripts/run_gates.py` /
   `gates/defs/*.py` / `scripts/check_*.py` 都不许读 `.git/info/exclude` / `~/.ssh` /
   `C:/infra` 之类的本机私有路径（AST 扫常量与 `Path.home()` / `expanduser()`）。

## 边界（如实写）

- 判据 1 在云机上是**平凡通过**的：克隆出来的仓 `.git/info/exclude` 只有注释。它不是
  空转 —— 反向用例 `test_exclude_mirror_detector_bites_on_an_unmirrored_rule` 证明
  检测器会咬；而本机每次往 info/exclude 加东西都会被这条立刻问出「`.gitignore` 里有吗」。
- 判据 2 用 scratch 仓而不是本仓 `git check-ignore`：本仓的 `check-ignore -v` 在两条
  规则都命中时只报 `.git/info/exclude`（实测），会把事故一那种状态判成「已忽略」。
- 判据 3 只钉「多重 CR 文件还在」+「集合没变」，**不**钉具体条数：正常编辑会让
  `\\r\\r` 计数增长（`scripts/run_gates.py` 正在被人改），钉条数就是假红。
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# ★ 卡 E59（T-AG517）：`Path.read_text/write_text(newline=)` 是 **Python 3.13 才加**的参数，
#   云门禁机是 3.12.8 ⇒ 直接用会在云机 `TypeError`（本机 3.14 永远看不见）。走 tools/read_write.py。
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))
from read_write import read_text as _read_text_bw  # noqa: E402
from read_write import write_text as _write_text_bw  # noqa: E402


def _git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """跑 git，输出一律按 utf-8 解码（云机区域编码是 cp936，不给 encoding 会崩）。"""
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd or ROOT),
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


# ---------------------------------------------------------------- 判据 1：info/exclude

#: `.git/info/exclude` 里允许**不**镜像进 `.gitignore` 的规则 —— 每条必须写理由。
#: 口径：只收「本机产生、云机永远不会产生、且写进共享 `.gitignore` 反而有害」的条目。
EXCLUDE_WHITELIST: dict[str, str] = {
    "/pytest-of-example/": (
        "本机受限沙箱的 pytest basetemp 残留（0 文件空目录，本沙箱 ACL 删不掉）；"
        "云机不会产生它，而把这种无名临时目录永久写进共享 .gitignore 等于把事故固化成规则。"
        "证据：复盘/交接后审计-不一致与风险修复.md:31"
    ),
    "/zz_mkdtemp_blgiom22/": (
        "同上：本机受限沙箱一次 mkdtemp 的残留（0 文件空目录），云机不会产生。"
        "证据：复盘/交接后审计-不一致与风险修复.md:31"
    ),
}

_CLASS = re.compile(r"\[([^\]]+)\]")


def _exclude_rules(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]


def _probe_path(rule: str) -> str:
    """把一条 ignore 规则合成一个「它一定能匹配」的路径（用于 `check-ignore --no-index`）。"""
    body = rule[1:] if rule.startswith("!") else rule
    body = _CLASS.sub(lambda m: m.group(1)[0], body)
    body = body.lstrip("/")
    if body.endswith("/"):
        body += "probe"
    return body.replace("**", "probe").replace("*", "probe").replace("?", "probe")


def _scratch_hits(
    gitignore_text: str, probes: list[str], workdir: Path
) -> dict[str, tuple[str, str]]:
    """在**只有 `.gitignore`** 的空 scratch 仓里问「这些路径被忽略吗」（= 云机视角）。

    为什么不在本仓问：`.git/info/exclude` 与 `.gitignore` 同时命中时，`check-ignore -v`
    只报 info/exclude（实测）—— 那样本机永远绿，事故一正是这样躲过所有判据的。

    返回 `{探针路径: (命中行号, 规则文本)}`。★ 规则文本必须一起回：删掉一行后行号会整体
    前移，只比行号会把「换了一条规则在兜底」误判成「同一行还在命中」。
    """
    if not probes:
        return {}
    repo = workdir / "scratch"
    # parents=True：反向用例里的 workdir 是不存在的子目录（tmp_path / "b"）。
    repo.mkdir(parents=True)
    _git("init", "-q", str(repo))
    # 归一成 LF 再写进 scratch 仓：`.gitignore` 本身是 CRLF/LF 混合，
    # 不归一会让 git 把行尾的 CR 当成规则的一部分。
    flat = gitignore_text.replace("\r\n", "\n")
    _write_text_bw(repo / ".gitignore", flat, encoding="utf-8", newline="")
    proc = subprocess.run(
        [
            "git",
            "-c",
            f"core.excludesFile={repo / 'no-such-excludes'}",
            "-C",
            str(repo),
            "check-ignore",
            "--no-index",
            "-v",
            "-z",
            "--stdin",
        ],
        capture_output=True,
        # ★ 字节 stdin + `-z`（NUL 分隔），不用文本 + 制表符分行：
        #   文本模式回显的路径会被行尾的 CR 污染（实测 gates/review/x.json 后面多一个 CR），
        #   探针永远比对不上 —— 判据会退化成恒红。
        input=b"".join(p.encode("utf-8") + b"\x00" for p in probes),
        check=False,
    )
    fields = proc.stdout.split(b"\x00")
    out: dict[str, tuple[str, str]] = {}
    # 每组 4 段：源文件 / 行号 / 规则 / 路径
    for i in range(0, len(fields) - 3, 4):
        rel = fields[i + 3].decode("utf-8", errors="replace")
        lineno = fields[i + 1].decode("utf-8", errors="replace")
        rule = fields[i + 2].decode("utf-8", errors="replace")
        out[rel] = (lineno, rule)
    return out

def unmirrored_exclude_rules(
    exclude_text: str,
    gitignore_text: str,
    workdir: Path,
    whitelist: dict[str, str],
) -> list[str]:
    """返回「只活在本机 info/exclude、`.gitignore` 里没有等价规则」的那些规则。"""
    rules = _exclude_rules(exclude_text)
    if not rules:
        return []
    probes = [_probe_path(r) for r in rules]
    hits = _scratch_hits(gitignore_text, probes, workdir)
    return [
        rule
        for rule, probe in zip(rules, probes, strict=True)
        if probe not in hits and rule not in whitelist
    ]


def _read(rel: str) -> str:
    """按字节读、不做换行翻译（`.gitignore` 是 CRLF/LF 混合，翻译了就分不清行）。"""
    return _read_text_bw(ROOT / rel, encoding="utf-8", newline="")


#: 行尾字节对（判据 3 全部按字节算，不经文本模式）。
CRLF = b"\r\n"
LF = b"\n"


def test_info_exclude_rules_are_mirrored_in_gitignore(tmp_path: Path) -> None:
    """判据 1：本机 info/exclude 的每一条，`.gitignore` 里都要有等价规则（或白名单带理由）。

    ★ 这条直接钉住事故一：`.wt/` 当初只在 info/exclude 里 ⇒ 云机不忽略 ⇒ dead_refs +20。
    """
    exclude_rel = ".git/info/exclude"
    exclude_path = ROOT / exclude_rel
    exclude_text = (
        _read_text_bw(exclude_path, encoding="utf-8", newline="") if exclude_path.exists() else ""
    )
    gitignore_text = _read(".gitignore")

    bad = unmirrored_exclude_rules(exclude_text, gitignore_text, tmp_path, EXCLUDE_WHITELIST)
    assert not bad, (
        f"{exclude_rel} 里这些规则没有镜像进 .gitignore，云机不会忽略它们（事故一同型）：\n  "
        + "\n  ".join(bad)
        + "\n修法：把等价规则加进 .gitignore；确实是本机私有且云机不需要的，"
        "加进本文件的 EXCLUDE_WHITELIST 并写清理由。"
    )
    # 白名单本身不许退化成「空理由」或「随手放行」。
    for rule, reason in EXCLUDE_WHITELIST.items():
        assert reason.strip(), f"白名单 {rule} 没写理由"
        assert len(reason) >= 20, f"白名单 {rule} 的理由太短，等于没写：{reason!r}"
    assert _exclude_rules(gitignore_text), ".gitignore 读出来是空的 —— 路径或编码错了，判据在空转"


def test_exclude_mirror_detector_bites_on_an_unmirrored_rule(tmp_path: Path) -> None:
    """**反向用例**：造一条只在 info/exclude、`.gitignore` 里没有的规则，检测器必须咬。"""
    exclude_text = "/.wt/\n/only-local-dir/\n# 注释不算规则\n\n"
    gitignore_text = ".wt/\n"
    bad = unmirrored_exclude_rules(exclude_text, gitignore_text, tmp_path, EXCLUDE_WHITELIST)
    assert bad == ["/only-local-dir/"], f"检测器没咬住（或咬了不该咬的）：{bad}"

    # 白名单要真的放行——否则白名单等于没接上。
    ok = unmirrored_exclude_rules(
        exclude_text,
        gitignore_text,
        tmp_path / "b",
        {"/only-local-dir/": "本机沙箱残留，云机不产生"},

    )
    assert ok == [], f"白名单没生效：{ok}"

    # 镜像好了就必须一条不剩（否则钉子会对正常状态误报）。
    mirrored = unmirrored_exclude_rules(exclude_text, ".wt/\nonly-local-dir/\n", tmp_path / "c", {})
    assert mirrored == [], f"规则已镜像却仍报缺陷：{mirrored}"


# ------------------------------------------------- 判据 2：声明的运行时产物真的被 ignore

#: `.gitignore` 里自称「运行时产物」的路径 —— 每条都要在**只有 .gitignore 的仓**里被忽略。
#: 加新条目时请带上「谁在写它」，否则下一个人不知道为什么不能删。
RUNTIME_ARTIFACT_PATHS: tuple[tuple[str, str], ...] = (
    (
        "gates/review/x.json",
        "事故二：tools/pool/landing.py 的 REVIEW_DIR，wb_review.py 每落一次地写一个",
    ),
    ("gates/logs/x.log", "scripts/run_gates.py 的门禁日志"),
    ("gates/diag/x.log", "AGENTS.md 指定的长跑日志（tools/run_logged.py --log）"),
    ("gates/render/shots/x.png", "渲染截图"),
    ("gates/candidates/x.json", "候选产物"),
    ("gates/render/candidates/x.txt", "渲染候选"),
    ("gates/tia.json", "scripts/tia_map.py 的产物"),
    (".wt/F6", "事故一：工作树根"),
    (".pytest_tmp/x", "pytest basetemp"),
    ("logs/x.log", "运行日志"),
    ("dist/x.js", "构建产物"),
    ("snapshots/x.json", "快照"),
    ("export/x.json", "导出"),
    ("blobs/x.bin", "二进制缓存"),
    ("__pycache__/x.pyc", "字节码"),
    (".ruff_cache/x", "ruff 缓存"),
    (".mypy_cache/x", "mypy 缓存"),
    (
        "tools/settings.toml",
        "事故二同型：tools/dsh_panel.py:1010 的 SETTINGS_REL 原子写出本机参数",
    ),
    (
        "tools/settings.toml.tmp",
        "tools/dsh_panel.py:1078 先写 .tmp 再 rename 的中间文件",
    ),
)


def test_declared_runtime_artifacts_are_really_ignored(tmp_path: Path) -> None:
    """判据 2：`.gitignore` 声明的运行时产物，在**云机的视角**（只有 `.gitignore`）真被忽略。

    ★ 这条直接钉住事故二：`gates/review/` 当年一条规则都没有，93 个 JSON 永久未跟踪。
    """
    gitignore_text = _read(".gitignore")
    probes = [_probe_path(p) for p, _ in RUNTIME_ARTIFACT_PATHS]
    hits = _scratch_hits(gitignore_text, probes, tmp_path)
    missing = [
        f"{path}（{why}）"
        for (path, why), probe in zip(RUNTIME_ARTIFACT_PATHS, probes, strict=True)
        if probe not in hits
    ]
    assert not missing, (
        "这些「运行时产物」在只有 .gitignore 的仓里**不**被忽略 —— 云机上就是永久未跟踪，"
        "文档里引用它们会被 check_docs 判死指针（事故二同型）：\n  " + "\n  ".join(missing)
    )


def test_runtime_artifact_rule_is_load_bearing(tmp_path: Path) -> None:
    """**反向用例**：逐条把「判决它的那一行」从 `.gitignore` 里删掉，钉子必须立刻咬。"""
    gitignore_text = _read(".gitignore")
    lines = gitignore_text.splitlines(keepends=True)
    probes = [_probe_path(p) for p, _ in RUNTIME_ARTIFACT_PATHS]
    hits = _scratch_hits(gitignore_text, probes, tmp_path)
    assert len(hits) == len(set(probes)), f"基线就没建起来，读数：{hits}"

    for path, probe in zip([p for p, _ in RUNTIME_ARTIFACT_PATHS], probes, strict=True):
        lineno, rule = hits[probe]
        stripped = "".join(line for i, line in enumerate(lines, start=1) if i != int(lineno))
        after = _scratch_hits(stripped, [probe], tmp_path / f"rm{lineno}_{len(probe)}")
        remaining = after.get(probe)
        assert remaining is None or remaining[1] != rule, (
            f"{path} 由第 {lineno} 行的规则 {rule!r} 判决，但那行删掉后仍由同一条规则命中 —— "
            "反向用例没真的删到判决行"
        )
        if remaining is None:
            continue  # 删掉即不再忽略：这条规则是唯一支撑，事故二的形状
        # 还有别的规则兜着也算「这行不是唯一支撑」，但必须换了一条规则（说明删对了行）。
    # 显式覆盖事故二那一行：gates/review/ 删掉后必须**完全**不再忽略。
    review_line = hits[_probe_path("gates/review/x.json")][0]
    stripped = "".join(line for i, line in enumerate(lines, start=1) if i != int(review_line))
    after = _scratch_hits(stripped, [_probe_path("gates/review/x.json")], tmp_path / "review")
    assert not after, (
        f"把 .gitignore:{review_line}（gates/review/）删掉之后仍被忽略：{after} —— "
        "说明这条反向用例没真的删到判决行"
    )


# ------------------------------------------------------------ 判据 3：行尾策略

#: 全仓仅有的 3 个「多重 CR」文件（`\\r\\r`），是**已提交进库**的内容。
#: 钉住它们是为了防止有人用编辑器「归一化」后无声无息地改掉整个文件（diff 会变成全文）。
MULTI_CR_FILES: tuple[str, ...] = (
    "scripts/run_gates.py",
    "tests/test_model_registry.py",
    "tools/wb_land.py",
)

#: 行尾读数用的样本：blob 里是纯 LF、工作区在 autocrlf=true 下是 CRLF。
CRLF_SAMPLES: tuple[str, ...] = (
    "tests/conftest.py",
    "gates/defs/domains.py",
    ".gitignore",
    ".gitattributes",
)


def multi_cr_defect(raw: bytes) -> bool:
    """`\\r\\r` 才是缺陷；`\\r\\n` 是 `core.autocrlf=true` 的正常签出结果。

    ★ 判据只能咬多重 CR：整树 CRLF 是本机常态（blob 全是 LF），拿「工作区与 blob 不同」
    当缺陷会天天假红；拿「有 CRLF」当缺陷同样假红。真正在库里的是那 3 个 `\\r\\r` 文件。
    """
    return b"\r\r" in raw


def _blob(rel: str) -> bytes:
    proc = subprocess.run(
        ["git", "cat-file", "blob", f"HEAD:{rel}"],
        cwd=str(ROOT),
        capture_output=True,
        check=False,
    )
    return proc.stdout if proc.returncode == 0 else b""


def _tracked_files() -> list[str]:
    out = _git("ls-files", "-z").stdout
    return [p for p in out.split("\0") if p]


def test_workspace_crlf_vs_head_blob_lf_is_not_a_defect() -> None:
    """判据 3a：工作区行尾与 HEAD blob 不同**不许**红 —— 只打印读数。

    `core.autocrlf=true`（system gitconfig）⇒ 签出时整树 CRLF、入库时归一成 LF，于是
    「工作区 == blob」在这台机器上恒为 False。任何拿它当健康判据的钉子都会天天假红。
    """
    autocrlf = _git("config", "--get", "core.autocrlf").stdout.strip() or "(unset)"
    readings: list[str] = []
    for rel in CRLF_SAMPLES:
        wt = (ROOT / rel).read_bytes()
        blob = _blob(rel)
        wt_crlf, wt_lf = wt.count(CRLF), wt.count(LF)
        bl_crlf, bl_lf = blob.count(CRLF), blob.count(LF)
        readings.append(
            f"  {rel}: 工作区 CRLF={wt_crlf}/LF={wt_lf}"
            f"  blob CRLF={bl_crlf}/LF={bl_lf}"
            f"  same={wt == blob}"
        )
        # 无论行尾怎样，这些样本都不该有多重 CR（多重 CR 由下面那条钉）。
        assert not multi_cr_defect(wt), f"{rel} 出现了多重 CR，不在 MULTI_CR_FILES 里：{readings}"
    print(f"\n[行尾读数] core.autocrlf={autocrlf}\n" + "\n".join(readings))

    if autocrlf == "true":
        # autocrlf=true 下工作区必然是 CRLF、blob 是 LF —— 这正是「不许当缺陷」的证据。
        wt = (ROOT / "tests/conftest.py").read_bytes()
        blob = _blob("tests/conftest.py")
        assert blob.count(b"\r\n") == 0, "blob 里出现 CRLF：autocrlf 没生效或这个文件被强制钉了行尾"
        assert wt.count(b"\r\n") > 0, "autocrlf=true 但工作区不是 CRLF：读数与配置矛盾"
        assert wt != blob, "工作区与 blob 逐字节相同：autocrlf 没在起作用（判据的前提变了）"

    # 谓词本身的两个方向（防止 multi_cr_defect 退化成恒 False/恒 True）。
    assert multi_cr_defect(b"a\r\nb\r\n") is False
    assert multi_cr_defect(b"a\r\r\nb") is True


def test_known_multi_cr_files_still_carry_double_cr() -> None:
    """判据 3b：全仓「多重 CR」文件集合恰好是这 3 个 —— 少一个 = 被人无声归一了。

    ★ 运行时读字节，不写死行号、不写死条数：正常编辑会让 `\\r\\r` 计数增长。
    """
    files = _tracked_files()
    assert len(files) > 1000, f"tracked 文件只有 {len(files)} 个，判据可能在空转"

    found: dict[str, int] = {}
    for rel in files:
        try:
            raw = (ROOT / rel).read_bytes()
        except OSError:
            continue
        if multi_cr_defect(raw):
            found[rel] = raw.count(b"\r\r")

    missing = [rel for rel in MULTI_CR_FILES if rel not in found]
    assert not missing, (
        "这些文件里的多重 CR（`\\r\\r`）消失了 —— 有人把它们归一了。"
        "那等于无声无息改掉整个文件（已提交内容变了，diff 会变成全文）：\n  " + "\n  ".join(missing)
    )
    extra = sorted(set(found) - set(MULTI_CR_FILES))
    assert not extra, (
        "出现了新的多重 CR 文件（不在 MULTI_CR_FILES 里）：\n  "
        + "\n  ".join(f"{rel}（\\r\\r={found[rel]}）" for rel in extra)
        + "\n如果它是真的（不是编辑器事故），把路径加进本文件的 MULTI_CR_FILES 并在注释里写明来历。"
    )
    print("\n[多重 CR 读数] " + ", ".join(f"{rel}={found[rel]}" for rel in sorted(found)))


# ------------------------------------------------------------ 判据 4：编码（占位）

@pytest.mark.skip(
    reason="由 tests/test_subprocess_encoding.py 负责，本文件不重复实现"
)
def test_subprocess_encoding_is_pinned_elsewhere() -> None:
    """判据 4 的占位：`subprocess` 的 `encoding=` 由 `tests/test_subprocess_encoding.py` 负责。

    ★ 本文件**不重复实现**——同一件事写两份判据，改一处忘另一处就会两份互相打架
    （本仓已有先例：`gates/diag/_scan_encoding.py` 与测试照抄不 import，因为 diag 不入库）。

    为什么本文件仍要留这一条：本文件讲的是「本机 vs 云机的差异」，编码差异是其中一类
    （本机 `PYTHONIOENCODING=utf-8` 是注册表里的私有设置，云机没有；云机区域编码 cp936）。
    留个占位是为了让读这张测试的人知道它被谁接走了，而不是以为这里漏了一条。
    """
    raise AssertionError("占位用例不该被执行 —— 它上面有 skip")


# ------------------------------------------- 判据 5：门禁不依赖本机私有文件

#: 门禁链里真正跑在云机上的那些文件（加新门时记得把新文件加进来）。
GATE_FILES: tuple[str, ...] = (
    "scripts/run_gates.py",
    "gates/defs/domains.py",
    "gates/defs/lang_python.py",
    "gates/defs/product_timeflow.py",
    "gates/defs/contract.py",
    "scripts/check_commands.py",
    "scripts/check_docs.py",
    "scripts/check_layers.py",
    "scripts/check_toml.py",
    "tools/gate_pool.py",
)

#: 「本机私有路径」的标记：出现在门禁代码的字符串常量里就红。
PRIVATE_MARKERS: tuple[str, ...] = (
    ".git/info/exclude",
    "info/exclude",
    ".ssh",
    "C:/infra",
    "C:\\infra",
    "AppData",
    "safe.directory",
    "C:/Users/",
    "/home/",
)

#: 本机私有主目录的调用。
PRIVATE_CALLS: tuple[str, ...] = ("home", "expanduser")

#: 显式白名单 —— 键是 (文件, 标记)，每条写理由。口径：只在**真云机传输**路径上用，
#: 且该路径不在任何钉子/门禁判定路径上。
PRIVATE_PATH_WHITELIST: dict[tuple[str, str], str] = {
    ("tools/gate_pool.py", ".ssh"): (
        "SshTransport.key 的默认值指向 ~/.ssh/id_ed25519_cloud —— 这是**真云机传输**用的，"
        "单测一律注入假 transport（该类 docstring 自述），不在任何门禁判定路径上。"
        "scripts/cloud/run_gate.sh 才是在云机上跑门禁的那条链。"
    ),
    ("tools/gate_pool.py", ".home()"): (
        "同一处的 `pathlib.Path.home()`（SshTransport.key 的默认值）—— 理由同上："
        "只在真云机传输路径上用，门禁判定不读它。"
    ),
}


def scan_private_paths(src: str, rel: str) -> list[tuple[str, int, str, str]]:
    """AST 扫「读本机私有路径」：`Path.home()` / `expanduser()` / 命中标记的字符串常量。

    返回 `(文件, 行号, 标记, 片段)`。用 AST 而不是 grep：grep 会被注释里的示例骗到
    （本文件自己就满篇 `.ssh`），也会漏掉跨行拼接的常量。
    """
    tree = ast.parse(src)
    hits: list[tuple[str, int, str, str]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in PRIVATE_CALLS
        ):
            hits.append((rel, node.lineno, f".{node.func.attr}()", ast.unparse(node)))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            for marker in PRIVATE_MARKERS:
                if marker in node.value:
                    hits.append((rel, node.lineno, marker, node.value))
                    break
    return hits


def unwhitelisted_private_paths(
    src: str, rel: str, whitelist: dict[tuple[str, str], str]
) -> list[tuple[str, int, str, str]]:
    return [hit for hit in scan_private_paths(src, rel) if (hit[0], hit[2]) not in whitelist]


def test_gate_code_reads_no_local_private_paths() -> None:
    """判据 5：门禁代码不许依赖「只在本机存在」的文件。

    ★ 这正是整张卡的根：云机缺一份本机私有状态，门禁就换了行为，而且没有任何判据能看见。
    """
    missing = [rel for rel in GATE_FILES if not (ROOT / rel).exists()]
    assert not missing, f"扫描面里的文件不见了（改名就改 GATE_FILES）：{missing}"

    problems: list[str] = []
    scanned = 0
    for rel in GATE_FILES:
        src = _read_text_bw(ROOT / rel, encoding="utf-8", newline="")
        scanned += len(src)
        hits = unwhitelisted_private_paths(src, rel, PRIVATE_PATH_WHITELIST)
        for file, lineno, marker, snippet in hits:
            problems.append(f"{file}:{lineno}: 命中 {marker!r} —— {snippet}")

    assert scanned > 50_000, f"只扫到 {scanned} 字符，扫描面可能在空转"
    assert not problems, (
        "门禁代码在读本机私有路径 —— 云机上这些文件不存在，门禁行为会**静默**改变：\n  "
        + "\n  ".join(problems)
        + "\n修法：改成仓库内的相对路径（如 `ROOT / '.gitignore'`），或加进 "
        "PRIVATE_PATH_WHITELIST 并写清「为什么云机上不会因此变行为」。"
    )


def test_private_path_detector_bites_on_a_planted_violation(tmp_path: Path) -> None:
    """**反向用例**：造三份违规源码，扫描器必须都咬住；合规的（注释里提 `.ssh`）不许误报。"""
    planted = (
        "from pathlib import Path\n"
        "key = Path.home() / '.ssh' / 'id_ed25519_cloud'\n"
        "exclude = Path('.git/info/exclude').read_text(encoding='utf-8')\n"
        "infra = Path('C:/infra/pool.json')\n"
    )
    hits = scan_private_paths(planted, "planted.py")
    markers = {marker for _, _, marker, _ in hits}
    assert ".git/info/exclude" in markers, hits
    assert ".ssh" in markers, hits
    assert "C:/infra" in markers, hits
    assert any(marker == ".home()" for _, _, marker, _ in hits), f"没抓到 Path.home()：{hits}"

    ok_src = (
        "from pathlib import Path\n"
        "# 注释里提 .ssh 不算：判据只看常量与调用\n"
        "doc = 'this is fine'\n"
    )
    assert scan_private_paths(ok_src, "ok.py") == [], "合规源码被误报"

    # 白名单要按 (文件, 标记) 生效，不能整文件放行、也不能整标记放行。
    wl = {("planted.py", ".ssh"): "测试用理由足够长足够长足够长"}
    left = unwhitelisted_private_paths(planted, "planted.py", wl)
    assert all(marker != ".ssh" for _, _, marker, _ in left), f"白名单没生效：{left}"
    assert any(marker == ".git/info/exclude" for _, _, marker, _ in left), (
        f"白名单放行过头：{left}"
    )
    assert unwhitelisted_private_paths(planted, "other.py", wl), "白名单跨文件生效了"
