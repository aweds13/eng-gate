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

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
ANCHOR = "> **给新对话窗口用的交接文档。** 读完本文 + §五 的必读清单，即可无缝接手。"


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


def _selfcheck(wt: pathlib.Path) -> list[str]:
    r"""写完**立刻**验一遍机器可读文件（2026-10-01 一天里我自己的工具弄坏过 4 次机器可读文件）。

    判据只有四条，都是**真踩过**的：
      ① 台账能 `tomllib` 解析 —— 病：`\U` 被当 unicode 转义（坑 22）
      ② changelog 首行是 `## ` 标题 —— 病：bullet 插到标题之上（坑 23）
      ③ 三个共享文档是纯 CRLF —— 病：汇总器写死 `\n` 整份变 LF
      ④ 片段 ↔ 汇总一致 —— 病：手改了汇总却没改片段（或反之）
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

    # ★ 卡 107（B 方案）：只要 `docs/changelog.d/` 在，就走**片段模式** ——
    #   写三个片段文件、再调汇总器把共享文档拼出来；旧的"直接往共享文档里插"整段跳过。
    #   为什么：共享文档是**每笔都在同一锚点改**的那三个文件 ⇒ 并发提交必冲突（B 就是为它做的）。
    frag_dir = wt / "docs" / "changelog.d"
    if frag_dir.is_dir():
        return _fragments_mode(wt, a, gaps, cl, cp)

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
        lines += [f"  {_toml_str('file:' + _unescape_git_quoted(e))}," for e in a.evidence]
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
    bad = _selfcheck(wt)
    if bad:
        print("★ 写后自检没过 ⇒ 停手（别拿去提交）：")
        for item in bad:
            print(f"   - {item}")
        return 3
    print("OK（写后自检 4 条全过：台账可解析 / changelog 首行是标题 / 纯 CRLF / 片段↔汇总一致）")
    return 0




def _fragments_mode(wt: pathlib.Path, a, gaps: str, cl: str, cp: str) -> int:
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
    lines = [f'[entries."{a.id}"]', f'id = "{a.id}"', f'title = "{a.title}"',
             f'group = "{a.group}"', 'status = "done"', "evidence = ["]
    lines += [f"  {_toml_str('file:' + _unescape_git_quoted(e))}," for e in a.evidence]
    lines += ["]", 'gaps = "' + quote_safe(gaps) + '"', ""]
    frag2 = trc_d / f"{a.id}.toml"
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
    bad = _selfcheck(wt)
    if bad:
        print("★ 写后自检没过 ⇒ 停手（别拿去提交）：")
        for item in bad:
            print(f"   - {item}")
        return 3
    print("OK（写后自检 4 条全过：台账可解析 / changelog 首行是标题 / 纯 CRLF / 片段↔汇总一致）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
