r"""通用文档件生成器（主控用，实现层）：给一张卡的提交补 台账条目 + changelog + 交接 CHECKPOINT。

★ 已进 git（卡 139 · `T-G237`）—— **权威副本就是本文件**（`tools/pool/stage_card.py`，
  模块 `pool.stage_card`）。命令行壳是 `tools/wb_stage_card.py`；旧的 `gates/diag/_stage_card.py`
  保留成临时转发壳（免得旧调用点当夜断掉）。**本文件由原 `_integrate.py` 的同级脚本
  `gates/diag/_stage_card.py` 逐字搬来**（卡 139），除下面两处外**行为一字不变**：
  ① `ROOT` 由**硬编码绝对路径**（`pathlib.Path(r"D:/docs\…")`）改成**自推** ——
     `ROOT = pathlib.Path(__file__).resolve().parents[2]`（`tools/pool/` 上两级 = 仓库根）。
     这正是外部审查 §8 的 2.10「换机器即碎」那条；搬进 git 之前必须修掉，
     否则等于把 bug 一起搬进去。
  ② 只**按 ruff 的 line-length（100 列，CJK 算 2）折行** —— 折行只在**源码**层面，
     打印文本、退出码、判据一个字符都没动。

用法：
    python -X utf8 tools/wb_stage_card.py --tree .wt/mech2 --id T-G191 \
        --title "…" --group ENGINEERING \
        --evidence tools/tf_group.py tests/test_tf_group.py \
        --gaps-file gates/diag/_gaps_TG191.txt \
        --changelog-file gates/diag/_cl_TG191.txt \
        --checkpoint-file gates/diag/_cp_TG191.txt

三处都按**字节**改（这三个文件是纯 CRLF，写完要一个纯 LF 都不许有）：
  ① 台账：**末尾追加**条目（条目之间留一个空行）
  ② changelog：**插到最前**（新的在最上面）
  ③ 交接文档：新 CHECKPOINT 插在「> **给新对话窗口用的交接文档。** …」那一行之后

★ gaps 里的 ASCII 双引号会被自动换成「」（TOML 基本串不许裸引号 —— 这条坑踩过 8 次）。
★ 幂等：三处都已存在该 id 就跳过。
"""
from __future__ import annotations

try:
    import pipe_root
except ImportError:
    try:
        from tools import pipe_root
    except ImportError:  # pragma: no cover —— 落地桩/独立拷贝的树里没有 pipe_root
        pipe_root = None  # type: ignore[assignment]

import argparse
import pathlib
import sys

_FILE_ROOT = pathlib.Path(__file__).resolve().parents[2]
ROOT = pipe_root.data_root() if pipe_root is not None else _FILE_ROOT
ANCHOR = "> **给新对话窗口用的交接文档。** 读完本文 + §五 的必读清单，即可无缝接手。"

# ★ 卡 193（T-G293）：把 tools/ 挂上 path 以便 import 压缩文书判据
#   （判据唯一真源 = tools/card_doc_budget.py，不许在本文件重写一份）
_TOOLS_DIR = str(pathlib.Path(__file__).resolve().parent.parent)
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)
import card_doc_budget  # noqa: E402


def _unescape_git_quoted(value: str) -> str:
    """把 `git` 默认 `core.quotePath=true` 输出的**八进制转义路径**还原成人能用的路径。

    ★ 为什么要有这个：`git diff --name-only` / `git status` 对**非 ASCII** 路径会输出
      `"å¤..."`（带引号 + 八进制）。要是把它当路径传进来，写进台账就成了
      `"file:"å..."",` —— **TOML 直接非法**（`Unclosed array`）。卡 116 的片段就这么废了一趟。
    ★ 只在"整个值被一对引号包住"时才解码（Windows 合法文件名不含 `"` ⇒ 不会误伤普通路径）。
    """
    if len(value) < 2 or not (value.startswith('"') and value.endswith('"')):
        return value
    body = value[1:-1]
    out = bytearray()
    i = 0
    while i < len(body):
        if body[i] == "\\" and body[i + 1:i + 4].isdigit() and len(body[i + 1:i + 4]) == 3:
            out.append(int(body[i + 1:i + 4], 8))
            i += 4
        else:
            out.extend(body[i].encode("utf-8"))
            i += 1
    return out.decode("utf-8", errors="replace")


def _toml_str(value: str) -> str:
    """TOML 基本字符串（与 JSON 转义同规）—— 再野的字符也写不坏文件。"""
    import json as _json
    return _json.dumps(value, ensure_ascii=False)


#: 证据断言的种类前缀（与 `scripts/audit_progress.eval_assertion()` 认的种类**同源**）。
#: 调用方可以自带前缀（`test:…` / `text:…` / `file:…`）；没带才补 `file:`。
EVIDENCE_KINDS = ("file", "text", "test", "route", "table", "column", "ui")


def _as_assertion(raw: str) -> str:
    """把一条 `--evidence` 变成台账里的断言：**带种类前缀就原样保留**，否则补 `file:`。

    ★ 卡 E100（T-AG609）：`test:` 的**形态**要归一成裸文件名 —— 审计自己补 `tests/`
      （`scripts/audit_progress.py` 的 `p = ROOT / "tests" / fname`，`tools/evidence_map.py`
      的 `"tests/" + fname` 同口径）。带 `tests/` 前缀写进台账，求值就成了 `tests/tests/x.py`，
      **必红**，而且是到落地链 `③″` 才红（白烧一趟门禁）。实测：
      `test:tests/test_pool_limits.py::test_pin_24`
      ⇒ `(False, '测试文件 tests/test_pool_limits.py')`。
    ★ 只动 `test:` —— `text:` 的图案在 `::` 之后，含斜杠很正常，抹了就是改人话。
    """
    text = _unescape_git_quoted(raw)
    kind, sep, rest = text.partition(":")
    if not (sep and kind in EVIDENCE_KINDS):
        return "file:" + text
    if kind != "test":
        return text
    fname, sep2, case = rest.partition("::")
    return "test:" + _bare_test_file(fname) + (sep2 + case if sep2 else "")


def _bare_test_file(rest: str) -> str:
    """`tests/test_x.py` / `./tests/test_x.py` / `tests\\test_x.py` ⇒ `test_x.py`（幂等）。"""
    rel = rest.strip().replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]
    if rel.startswith("tests/"):
        rel = rel[len("tests/"):]
    return rel.lstrip("/")


def _judge_fresh_test_pointers(wt: pathlib.Path, raw: list[str]) -> list[str]:
    """★ 卡 E100：本次**新给**的 `test:` 指针，在写盘**之前**就按审计同一口径求值。

    为什么在写侧做：让落地链跑到 `③″` 才红，代价是 ~300 秒全量门禁（E99 首趟就是这么白跑的）。
    判据只有两件（与 `scripts/audit_progress.eval_assertion()` 的 `test:` 分支同口径）：
      ① 文件在不在 `{tree}/tests/<裸文件名>`；
      ② 用例名在不在那个文件里 —— 尺子复用 `tools/wb_invariants.py::defines_case`
         （唯一真源，不许写第二份）。
    `test:` 只写文件、没写 `::用例` 的形态**放行**（审计也放行：它只核文件在）。
    返回人话清单；空 = 全过。
    """
    bad: list[str] = []
    for raw_item in raw:
        item = _as_assertion(raw_item)
        kind, _sep, rest = item.partition(":")
        if kind != "test":
            continue
        fname, sep2, case = rest.partition("::")
        path = wt / "tests" / fname
        if not path.is_file():
            bad.append(f"test:{fname} ⇒ {path.relative_to(wt).as_posix()} 不存在"
                       f"（证据要指向这棵树里**真在**的测试文件）")
            continue
        if not sep2 or not case.strip():
            continue
        # ★ 尺子**惰性**导入：只有真走到「核用例名」这一步才需要它。
        #   提前 import 会让**一条 test: 都没有**的树也要求这个模块在
        #   （假仓实测：38 条落地钉子全炸）。
        #   判据真源 = tools/wb_invariants.py（用例存在性的唯一实现，不许在这里写第二份）。
        import wb_invariants as _inv
        bare = _inv.case_name(case)
        if not _inv.defines_case(path.read_text(encoding="utf-8", errors="replace"), bare):
            bad.append(f"test:{fname}::{case} ⇒ 用例 {bare} 不在 {path.name} 里"
                       f"（先把它写进测试文件，或改成真在的用例名）")
    return bad


def load(p: pathlib.Path) -> tuple[bytes, bytes]:
    raw = p.read_bytes()
    crlf = raw.count(b"\r\n")
    lf = raw.count(b"\n") - crlf
    assert lf == 0, f"{p} 有 {lf} 行纯 LF —— 停手（这些文件是纯 CRLF）"
    nl = b"\r\n" if crlf else b"\n"
    return raw, nl


def block(lines: list[str], nl: bytes) -> bytes:
    return nl.join(x.encode("utf-8") for x in lines)


def quote_safe(text: str) -> str:
    """把 ASCII 双引号成对换成「」（TOML 基本串里不许裸引号）**并把反斜杠转义**。

    ★ 2026-10-01 踩的（真断过链）：gaps 里写了 Windows 路径 `C:/Users/example\\...`，
      而 TOML **基本串**把 `\\U` 当成"8 位十六进制 unicode 转义"，`sers` 不是合法十六进制 ⇒
      `tomllib.TOMLDecodeError: Invalid hex value`，`sync_counts.py` 读台账当场炸
      （整条提交链第三步断）。
      ⇒ 反斜杠必须加倍；顺序是先换引号、最后加倍反斜杠。
    """
    parts = text.split('"')
    assert len(parts) % 2 == 1, f"ASCII 双引号不成对（{len(parts) - 1} 个）—— 停手"
    out = "".join(("「" + x + "」") if i % 2 else x for i, x in enumerate(parts))
    return out.replace("\\", "\\\\")


def _selfcheck(wt: pathlib.Path, *, cp_text: str = "", gaps_text: str = "",
               cl_text: str = "") -> list[str]:
    r"""写完**立刻**验一遍机器可读文件（2026-10-01 一天里我自己的工具弄坏过 4 次机器可读文件）。

    判据有五条，前四条**真踩过**、第五条卡 193 接线：
      ① 台账能 `tomllib` 解析 —— 病：`\U` 被当 unicode 转义（坑 22）
      ② changelog 首行是 `## ` 标题 —— 病：bullet 插到标题之上（坑 23）
      ③ 三个共享文档是纯 CRLF —— 病：汇总器写死 `\n` 整份变 LF
      ④ 片段 ↔ 汇总一致 —— 病：手改了汇总却没改片段（或反之）
      ⑤ 压缩文书结构预算 + 指针（卡 193 / T-G293）—— 判据真源 = tools/card_doc_budget.py
    """
    import subprocess
    import sys as _sys

    import tomllib

    bad: list[str] = []
    ledger = wt / "docs" / "traceability.toml"
    try:
        data = tomllib.loads(ledger.read_text(encoding="utf-8"))
        if "entries" not in data:
            bad.append(f"{ledger.name} 里没有 [entries] 表")
    except Exception as exc:  # noqa: BLE001 —— 自检就是要把任何异常变成一句人话
        bad.append(f"{ledger.name} 解析不了：{type(exc).__name__}: {exc}")

    changelog = wt / "docs" / "changelog.md"
    first = changelog.read_text(encoding="utf-8").splitlines()[:1]
    if not first or not first[0].startswith("## "):
        bad.append(f"{changelog.name} 首行不是 `## ` 标题，是 {first!r}")

    for rel in ("docs/traceability.toml", "docs/changelog.md", "复盘/交接-重构进度.md"):
        b = (wt / rel).read_bytes()
        lf = b.count(b"\n") - b.count(b"\r\n")
        if lf:
            bad.append(f"{rel} 有 {lf} 行纯 LF（这三个文件是纯 CRLF）")

    r = subprocess.run([_sys.executable, "-X", "utf8", "tools/sync_docs.py", "--check"],
                       cwd=str(wt), capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    if r.returncode != 0:
        detail = ((r.stdout or "") + (r.stderr or "")).strip()[:400]
        bad.append("sync_docs.py --check 不通过：" + detail)

    # ⑤ 卡 193（T-G293）：压缩文书结构预算 + 指针 —— 判据真源 = tools/card_doc_budget.py，
    #   文书正文从 main 透传（收口链的 _text_<台账号>.md 那条路），不在本文件重写判据。
    if cp_text or gaps_text or cl_text:
        bad += card_doc_budget.check_budget(checkpoint=cp_text, gaps=gaps_text, changelog=cl_text)
        if gaps_text.strip():
            bad += card_doc_budget.check_pointers(gaps_text, root=wt)
    return bad


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser()
    ap.add_argument("--tree", required=True)
    ap.add_argument("--id", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--group", default="ENGINEERING")
    ap.add_argument("--evidence", nargs="+", required=True)
    ap.add_argument("--gaps-file")
    ap.add_argument("--changelog-file")
    ap.add_argument("--checkpoint-file")
    ap.add_argument(
        "--text-file",
        help="一份文件里写三段（=== gaps === / === changelog === / === checkpoint ===）")
    a = ap.parse_args(argv)

    if a.text_file:
        raw = (ROOT / a.text_file).read_text(encoding="utf-8")
        parts: dict[str, str] = {}
        cur = None
        for line in raw.splitlines():
            s = line.strip()
            if s.startswith("=== ") and s.endswith(" ==="):
                cur = s.strip("= ").strip()
                parts[cur] = ""
                continue
            if cur:
                parts[cur] += line + "\n"
        for k in ("gaps", "changelog", "checkpoint"):
            assert parts.get(k, "").strip(), f"{a.text_file} 里缺 {k} 段"
        a.gaps_file, a.changelog_file, a.checkpoint_file = None, None, None
        tmp = ROOT / "gates" / "diag" / "_sect"
        tmp.mkdir(parents=True, exist_ok=True)
        for k in ("gaps", "changelog", "checkpoint"):
            (tmp / f"{k}.txt").write_text(parts[k].strip("\n") + "\n",
                                         encoding="utf-8", newline="\n")
        a.gaps_file = "gates/diag/_sect/gaps.txt"
        a.changelog_file = "gates/diag/_sect/changelog.txt"
        a.checkpoint_file = "gates/diag/_sect/checkpoint.txt"
    for req in ("gaps_file", "changelog_file", "checkpoint_file"):
        assert getattr(a, req), f"缺 --{req.replace('_', '-')}（或给 --text-file）"

    wt = ROOT / a.tree
    ledger = wt / "docs" / "traceability.toml"
    changelog = wt / "docs" / "changelog.md"
    handoff = wt / "复盘" / "交接-重构进度.md"
    raw_gaps = (ROOT / a.gaps_file).read_text(encoding="utf-8")
    # ★ 台账的 gaps 是**一行**超长 TOML 基本串 —— 段里若带了换行，写进 toml 会把那一行拆断
    #   （实测：纯 LF 冒出来、tomllib 直接解析失败）。所以这里把行拼起来。
    gaps = "".join(ln.strip() for ln in raw_gaps.splitlines())
    cl = (ROOT / a.changelog_file).read_text(encoding="utf-8").strip("\n")
    cp = (ROOT / a.checkpoint_file).read_text(encoding="utf-8").strip("\n")

    # ★ 卡 E100（T-AG609）：证据指针在**写盘之前**就按审计同一口径求值。
    #   病：`--evidence test:tests/x.py::case` 写进台账，审计自己补 `tests/` ⇒ 求值成
    #   `tests/tests/x.py` 必红，而红点落在落地链 ③″（E99 首趟白烧一趟全量门禁）。
    #   口径：**只核本次新给的**；片段里已有人写下的（carried）只归一、不判死 ——
    #   那是人手补的，判死会挡住别人正在收口的那一笔。
    bad_ptr = _judge_fresh_test_pointers(wt, a.evidence)
    if bad_ptr:
        print("★ 证据指针写盘前就核不过 ⇒ 停手（别等落地链 ③″ 才红）：")
        for item in bad_ptr:
            print(f"   - {item}")
        return 4

    # ★ 卡 107（B 方案）：只要 `docs/changelog.d/` 在，就走**片段模式** ——
    #   写三个片段文件、再调汇总器把共享文档拼出来；旧的"直接往共享文档里插"整段跳过。
    #   为什么：共享文档是**每笔都在同一锚点改**的那三个文件 ⇒ 并发提交必冲突（B 就是为它做的）。
    frag_dir = wt / "docs" / "changelog.d"
    if frag_dir.is_dir():
        return _fragments_mode(wt, a, gaps, cl, cp, raw_gaps=raw_gaps)

    # ① 台账
    raw, nl = load(ledger)
    marker = f'[entries."{a.id}"]'.encode()
    if marker in raw:
        print(f"台账里已有 {a.id}，跳过")
    else:
        assert raw.endswith(nl), "台账尾部没有换行，停手"
        pad = b"" if raw.endswith(nl + nl) else nl
        lines = [f'[entries."{a.id}"]', f'id = "{a.id}"', f'title = "{a.title}"',
                 f'group = "{a.group}"', 'status = "done"', "evidence = ["]
        lines += [f"  {_toml_str(_as_assertion(e))}," for e in a.evidence]
        lines += ["]", 'gaps = "' + quote_safe(gaps) + '"', ""]
        ledger.write_bytes(raw + pad + block(lines, nl))
        print(f"台账 {len(raw)} → {ledger.stat().st_size} 字节（{a.id}）")

    # ② changelog
    raw, nl = load(changelog)
    if a.id in raw.decode("utf-8"):
        print(f"changelog 里已有 {a.id}，跳过")
    else:
        assert raw.startswith(b"## 2026-"), "changelog 首行不是预期那一节，停手"
        changelog.write_bytes(block(cl.split("\n"), nl) + nl + raw)
        print(f"changelog {len(raw)} → {changelog.stat().st_size} 字节")

    # ③ 交接 CHECKPOINT
    raw, nl = load(handoff)
    if a.id in raw.decode("utf-8"):
        print(f"交接文档里已有 {a.id}，跳过")
    else:
        anchor = (ANCHOR + "\n\n").replace("\n", nl.decode()).encode("utf-8")
        assert raw.count(anchor) == 1, f"锚点命中 {raw.count(anchor)} 次，停手"
        handoff.write_bytes(raw.replace(anchor, anchor + block(cp.split("\n"), nl) + nl))
        print(f"交接文档 {len(raw)} → {handoff.stat().st_size} 字节")

    for p in (ledger, changelog, handoff):
        b = p.read_bytes()
        lf = b.count(b"\n") - b.count(b"\r\n")
        print(f"  {p.name}: {len(b)} 字节 纯LF={lf}")
        assert lf == 0
    bad = _selfcheck(wt, cp_text=cp, gaps_text=raw_gaps, cl_text=cl)
    if bad:
        print("★ 写后自检没过 ⇒ 停手（别拿去提交）：")
        for item in bad:
            print(f"   - {item}")
        return 3
    print("OK（写后自检 5 条全过：台账可解析 / changelog 首行是标题 / "
          "纯 CRLF / 片段↔汇总一致 / 文书预算+指针）")
    return 0




def _fragments_mode(wt: pathlib.Path, a, gaps: str, cl: str, cp: str,
                    raw_gaps: str = "") -> int:
    """写三个片段 → 调 `tools/sync_docs.py` 汇总（**幂等**）。返回 0。

    ★ 内容与旧写法**一字不差**：changelog 片段 = 原来要插到文件头的那一节；
      台账片段 = 原来要追加的那个 `[entries.<id>]` 表；交接片段 = 原来要插进锚点的那段 CHECKPOINT。
    """
    import subprocess
    import sys as _sys

    chg_d = wt / "docs" / "changelog.d"
    trc_d = wt / "docs" / "traceability.d"
    ho_d = wt / "复盘" / "交接.d"
    for d in (chg_d, trc_d, ho_d):
        d.mkdir(parents=True, exist_ok=True)

    # ① changelog 片段
    frag = chg_d / f"{a.id}.md"
    frag.write_text(cl + "\n", encoding="utf-8", newline="\n")
    print(f"  片段 {frag.relative_to(wt)}（{frag.stat().st_size} 字节）")

    # ② 台账片段（与旧写法同一个表）
    # ★ 卡 E25（T-AG479）：**合并**而不是覆盖 —— 这个片段可能就是人刚补过指针的那份。
    #   实测踩过两轮：台账里已有 6 条（含 `file:tests/xxx.py` / `test:xxx.py::用例`），
    #   落地链 ② 一走就把 evidence 换成本次 `--evidence` 的 N 条（N 常常是 2），
    #   随后审计 ⑫「这一笔改了 X 但台账没有指针」当场红（E24 落地两趟白跑 240 s/趟）。
    #   口径：**已有的条目原样在前，本次新增的追加在后，去重**；`gaps`/`title`/`status` 仍按本次写。
    frag2 = trc_d / f"{a.id}.toml"
    carried: list[str] = []
    import tomllib as _tomllib  # 局部导入：这个文件其余部分刻意不依赖 tomllib
    if frag2.is_file():
        try:
            old_data = _tomllib.loads(frag2.read_text(encoding="utf-8"))
            entry = old_data.get("entries", {}).get(a.id, {})
            # ★ 卡 E100：carried 也过一遍形态归一（`test:tests/x.py` ⇒ `test:x.py`），
            #   但**不判死** —— 见 main() 里那段理由。
            carried = [_as_assertion(str(x)) for x in entry.get("evidence", [])]
        except (OSError, _tomllib.TOMLDecodeError):
            carried = []
    fresh = [_as_assertion(e) for e in a.evidence]
    seen: set[str] = set()
    merged: list[str] = []
    for item in carried + fresh:
        if item and item not in seen:
            seen.add(item)
            merged.append(item)
    lines = [f'[entries."{a.id}"]', f'id = "{a.id}"', f'title = "{a.title}"',
             f'group = "{a.group}"', 'status = "done"', "evidence = ["]
    lines += [f"  {_toml_str(item)}," for item in merged]
    lines += ["]", 'gaps = "' + quote_safe(gaps) + '"', ""]
    dropped = [x for x in carried if x not in merged]
    if dropped:
        print(f"  ★ 台账片段里这些证据没进本次提交（域外文件？）：{dropped}")
    frag2.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"  片段 {frag2.relative_to(wt)}（{frag2.stat().st_size} 字节）")

    # ③ 交接片段（CHECKPOINT 引用块 + 末尾 `>` 分隔行）
    frag3 = ho_d / f"{a.id}.md"
    frag3.write_text(cp + "\n", encoding="utf-8", newline="\n")
    print(f"  片段 {frag3.relative_to(wt)}（{frag3.stat().st_size} 字节）")

    # ④ 汇总（幂等；汇总器只插入、绝不改写既有字节）
    r = subprocess.run([_sys.executable, "-X", "utf8", "tools/sync_docs.py"], cwd=str(wt),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    tail = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()[-3:]
    print("  sync_docs.py 退出码 =", r.returncode, "|", " / ".join(tail))
    if r.returncode != 0:
        print("  ★ 汇总失败 ⇒ 停手")
        return 2

    for rel in ("docs/traceability.toml", "docs/changelog.md", "复盘/交接-重构进度.md"):
        b = (wt / rel).read_bytes()
        lf = b.count(b"\n") - b.count(b"\r\n")
        print(f"  {rel}: {len(b)} 字节 纯LF={lf}")
        assert lf == 0, rel
    print("OK（片段模式）")
    bad = _selfcheck(wt, cp_text=cp, gaps_text=raw_gaps, cl_text=cl)
    if bad:
        print("★ 写后自检没过 ⇒ 停手（别拿去提交）：")
        for item in bad:
            print(f"   - {item}")
        return 3
    print("OK（写后自检 5 条全过：台账可解析 / changelog 首行是标题 / "
          "纯 CRLF / 片段↔汇总一致 / 文书预算+指针）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
