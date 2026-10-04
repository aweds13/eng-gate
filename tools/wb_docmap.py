r"""文档地图生成器（卡 183 · T-G283）—— 自举第一步：把「我们已用过的那些文档」盘成机器可读索引。

为什么有它（用户 2026-10-03 原话）：框架做出来后**第 1 步就是把已用文档全部整理一遍**。
`复盘/` 有 377 份、`docs/` 99 份 `.md`，靠人读读不完 —— 本工具把人读变成**机器读数**：
每份文档一条记录，含路径 / 字节数 / 顶层归属 / 被引用次数 / 引用它的位置 /
**是否被台账按路径钉住**。

★ 「被台账钉住」与「只被人读过」在字段上**分开** —— 前者动了会碎台账（`docs/traceability.toml`
里有 `file:`/`text:` 断言指到它），后者只是文档间互引。这条区分是本卡最值钱的读数：
它就是「框架要能整文档，先得把台账与实现解绑」的实测证据（卡 178 要的解耦路径）。

引用面不许凭印象，用**现成的尺子**：
  ① 文档间引用 —— 复用 `scripts/check_layers.py` 的反引号 `.md` 正则（`` `…\.md` ``），
     多基准解析（相对当前文档 / docs 根 / 仓库根 / 裸文件名递归找）；
  ② 非文档引用 —— 在台账 toml / 队列 / 门禁脚本 / 工具里 grep 文档路径（含卡规格）；
  ③ 被台账钉住 —— 解析 `docs/traceability.toml` 的 `entries.*.evidence`，
     取 `file:`/`text:` 指向的 `.md`。

★ 只读：不写任何被扫的文档；只写 `--out` 指定的索引文件（默认 `复盘/文档索引.toml`）。
★ 不 import timeflow 业务代码（这是工具，不是产品的一部分）；只用标准库。
★ 幂等：不写时间戳，按 path 排序 —— 连生成两次逐字节相同。

用法：
    python -X utf8 tools/wb_docmap.py                 # 生成 复盘/文档索引.toml
    python -X utf8 tools/wb_docmap.py --json          # 输出 JSON 到 stdout
    python -X utf8 tools/wb_docmap.py --check         # 只报差异、不写文件
    python -X utf8 tools/wb_docmap.py --root <路径>   # 换一棵树（自检喂临时夹具）
    python -X utf8 tools/wb_docmap.py --exclude 复盘/文档重整方案.md
        # 排除本卡产物（免得方案文档自引用搅乱读数）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import tomllib

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "复盘" / "文档索引.toml"
DEFAULT_LEDGER = ROOT / "docs" / "traceability.toml"

#: 扫描域：这两个目录下的 `.md` 才进索引。
SCAN_DIRS = ("复盘", "docs")
#: 反引号 `.md` 路径正则 —— 复用 scripts/check_layers.py 的尺子（支持中文文件名）。
MD_LINK_RE = re.compile(r"`([^\s`]*?\.md)`")
#: 非文档引用面：在这些文件里 grep 文档路径。
NON_DOC_GREF_DIRS = ("scripts", "tools", "gates", "harness")
NON_DOC_GREF_FILES = (
    "docs/traceability.toml",
    "docs/workbacklog.toml",
    "复盘/不变量台账.toml",
    "复盘/优化候选.toml",
)
#: 引用位置最多列几条（人看，不刷屏）。
MAX_REFS = 6


class DocMapError(Exception):
    """坏输入（目录不存在 / 读不了）—— 不许静默出空表。"""


def to_posix(path: Path, root: Path) -> str:
    """仓库内 posix 相对路径（比对才稳，Windows 反斜杠抹平）。不在 root 下就回 str(path)。"""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def top_level(rel: str) -> str:
    """顶层归属：`复盘/卡/...` → `复盘.卡`；
    `docs/specification/domains/...` → `docs.specification`；
    `docs/README.md` → `docs`（顶层文件归到第一段）。
    """
    parts = rel.split("/")
    if len(parts) <= 2:
        return parts[0]
    return ".".join(parts[:2])


def collect_docs(root: Path, exclude: set[str] | None = None) -> list[Path]:
    """扫 `复盘/**` 与 `docs/**` 的 `.md`，回排序后的绝对路径列表。

    `exclude` 是一组 posix 相对路径，命中的不扫（生成本卡索引时排除本卡产物，
    免得方案文档自引用搅乱读数）。
    """
    if not root.exists():
        raise DocMapError(f"根目录不存在：{root}")
    excl = exclude or set()
    out: list[Path] = []
    for name in SCAN_DIRS:
        base = root / name
        if not base.exists():
            continue
        for p in base.rglob("*.md"):
            if p.is_file() and to_posix(p, root) not in excl:
                out.append(p)
    return sorted(out)


def resolve_md_target(rel: str, src: Path, root: Path, docs_root: Path,
                      by_name: dict[str, list[Path]]) -> Path | None:
    """把一个反引号 `.md` 路径解析到具体文档 —— 多基准尝试（复用 check_layers 的口径）。

    候选：相对当前文档 / 相对 docs 根 / 相对仓库根；裸文件名时按同名递归找。
    命中其一即回（与 check_layers 同语义，但回路径而非 bool）。
    """
    if rel.startswith(("http", "/")) or re.match(r"^[A-Za-z]:[\\/]", rel):
        return None
    candidates = [
        (src.parent / rel).resolve(),
        (docs_root / rel).resolve(),
        (root / rel).resolve(),
    ]
    if "/" not in rel and "\\" not in rel:
        candidates.extend(by_name.get(rel, []))
    for c in candidates:
        if c.exists() and c.is_file():
            return c
    return None


def find_doc_refs(docs: list[Path], root: Path, docs_root: Path
                  ) -> dict[Path, list[tuple[str, int]]]:
    """文档间引用：扫每份 `.md` 里反引号包的 `.md` 路径。

    回「被引用文档 → [(引用者posix, 行号)]」。
    """
    by_name: dict[str, list[Path]] = {}
    for d in docs:
        by_name.setdefault(d.name, []).append(d)
    out: dict[Path, list[tuple[str, int]]] = {}
    for src in docs:
        try:
            text = src.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for m in MD_LINK_RE.finditer(line):
                target = resolve_md_target(m.group(1), src, root, docs_root, by_name)
                if target is not None and target != src:
                    out.setdefault(target, []).append((to_posix(src, root), i))
    return out


def find_non_doc_refs(docs: list[Path], root: Path
                      ) -> dict[Path, list[tuple[str, int]]]:
    """非文档引用：在台账 / 队列 / 门禁脚本 / 工具里 grep 文档路径。

    对每个非文档文件逐行扫：若某行含某已扫文档的 posix 相对路径，记一条引用。
    """
    posix_set = {to_posix(d, root): d for d in docs}
    out: dict[Path, list[tuple[str, int]]] = {}
    files: list[Path] = []
    for rel in NON_DOC_GREF_FILES:
        p = root / rel
        if p.exists() and p.is_file():
            files.append(p)
    for dname in NON_DOC_GREF_DIRS:
        base = root / dname
        if base.exists():
            files.extend(p for p in base.rglob("*.py") if p.is_file())
    for src in files:
        try:
            text = src.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        src_posix = to_posix(src, root)
        for i, line in enumerate(text.splitlines(), 1):
            for rel, target in posix_set.items():
                if rel in line:
                    out.setdefault(target, []).append((src_posix, i))
    return out


def find_pinned(docs: list[Path], root: Path, ledger: Path
                ) -> dict[Path, list[str]]:
    """被台账按路径钉住：解析 `docs/traceability.toml` 的 `entries.*.evidence`。

    取 `file:`/`text:` 指向的 `.md`，回「文档 → [台账号]」。
    ★ 这是「动了一定碎台账」的那批 —— 与「只被人读过」严格分开。
    """
    if not ledger.exists():
        return {}
    posix_set = {to_posix(d, root): d for d in docs}
    out: dict[Path, list[str]] = {}
    try:
        with ledger.open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise DocMapError(f"台账读不了：{ledger}（{exc}）") from exc
    for eid, entry in data.get("entries", {}).items():
        for ev in entry.get("evidence", []):
            s = str(ev)
            kind, _, rest = s.partition(":")
            path: str | None = None
            if kind == "file":
                path = rest.strip()
            elif kind == "text":
                path = rest.partition("::")[0].strip()
            if path and path in posix_set:
                out.setdefault(posix_set[path], []).append(str(eid))
    return out


def build_index(root: Path, ledger: Path | None = None,
                exclude: set[str] | None = None) -> list[dict[str, Any]]:
    """组合一份索引：每份文档一条记录，字段稳定、按 path 排序（幂等）。

    `exclude`：一组 posix 相对路径，既不扫作文档、也不作引用源（本卡产物用）。
    """
    root = root.resolve()
    docs_root = root / "docs"
    docs = collect_docs(root, exclude)
    if not docs:
        raise DocMapError(f"在 {root} 下没扫到任何 .md（复盘/ 与 docs/ 都空？）")
    doc_refs = find_doc_refs(docs, root, docs_root)
    non_doc_refs = find_non_doc_refs(docs, root)
    pinned = find_pinned(docs, root, ledger or (root / "docs" / "traceability.toml"))
    entries: list[dict[str, Any]] = []
    for d in docs:
        rel = to_posix(d, root)
        refs = sorted(set(doc_refs.get(d, []) + non_doc_refs.get(d, [])))
        ref_strs = [f"{src}:{ln}" for src, ln in refs[:MAX_REFS]]
        pin = sorted(set(pinned.get(d, [])))
        entries.append({
            "path": rel,
            "bytes": d.stat().st_size,
            "top": top_level(rel),
            "ref_count": len(refs),
            "pinned": bool(pin),
            "pinned_by": pin,
            "referenced_by": ref_strs,
        })
    entries.sort(key=lambda e: str(e["path"]))
    return entries


def _toml_str(s: str) -> str:
    """TOML 基本串：用双引号，转义反斜杠与双引号（中文不转义）。"""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_toml(entries: list[dict[str, Any]]) -> str:
    """手写 TOML（标准库没有 tomli_w；字段简单，自己写最稳）。"""
    lines: list[str] = [
        "# 文档索引（卡 183 · T-G283）—— 由 tools/wb_docmap.py 生成，不要手改。",
        "# 字段：path/bytes/top/ref_count/pinned/pinned_by/referenced_by",
        "# pinned=true ⇒ docs/traceability.toml 有 file:/text: 断言指到它（动了会碎台账）。",
        "# referenced_by 最多列 6 条（文件:行）；ref_count 是全部引用数。",
        f"# 共 {len(entries)} 条。",
        "",
    ]
    for e in entries:
        lines.append("[[doc]]")
        lines.append(f"path = {_toml_str(str(e['path']))}")
        lines.append(f"bytes = {int(e['bytes'])}")
        lines.append(f"top = {_toml_str(str(e['top']))}")
        lines.append(f"ref_count = {int(e['ref_count'])}")
        lines.append(f"pinned = {'true' if e['pinned'] else 'false'}")
        pin = list(e["pinned_by"])
        if pin:
            inner = ", ".join(_toml_str(str(x)) for x in pin)
            lines.append(f"pinned_by = [{inner}]")
        else:
            lines.append("pinned_by = []")
        refs = list(e["referenced_by"])
        if refs:
            lines.append("referenced_by = [")
            for r in refs:
                lines.append(f"  {_toml_str(str(r))},")
            lines.append("]")
        else:
            lines.append("referenced_by = []")
        lines.append("")
    return "\n".join(lines)


def render_json(entries: list[dict[str, Any]]) -> str:
    """JSON 输出（ensure_ascii=False 保中文，sort_keys=False 按 path 序）。"""
    return json.dumps(entries, ensure_ascii=False, indent=2)


def diff_entries(old: list[dict[str, Any]], new: list[dict[str, Any]]
                 ) -> list[str]:
    """`--check` 用：对比两份索引，回人话差异（空 = 无差异）。"""
    old_by = {str(e["path"]): e for e in old}
    new_by = {str(e["path"]): e for e in new}
    msgs: list[str] = []
    for p in sorted(set(old_by) | set(new_by)):
        if p not in new_by:
            msgs.append(f"- 消失：{p}")
        elif p not in old_by:
            msgs.append(f"+ 新增：{p}")
        else:
            for k in ("bytes", "top", "ref_count", "pinned", "pinned_by", "referenced_by"):
                if old_by[p].get(k) != new_by[p].get(k):
                    msgs.append(
                        f"~ 变更：{p} 的 {k}：{old_by[p].get(k)!r} → {new_by[p].get(k)!r}")
    return msgs


def load_index_toml(path: Path) -> list[dict[str, Any]]:
    """读回自己生成的索引 toml（用 tomllib，字段稳定）。"""
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    return list(data.get("doc", []))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="文档地图生成器：把 复盘/ 与 docs/ 的 .md 盘成机器可读索引")
    parser.add_argument("--root", default=str(ROOT),
                        help="查哪棵树（默认本仓根；自检喂临时夹具）")
    parser.add_argument("--out", default=str(DEFAULT_OUT),
                        help="索引写出位置（默认 复盘/文档索引.toml）")
    parser.add_argument("--ledger", default=None,
                        help="台账路径（默认 <root>/docs/traceability.toml）")
    parser.add_argument("--exclude", action="append", default=[],
                        help="排除某文档（posix 相对路径，可重复）；"
                             "生成本卡索引时排除方案文档，免自引用搅乱读数")
    parser.add_argument("--json", action="store_true",
                        help="输出 JSON 到 stdout（不写文件）")
    parser.add_argument("--check", action="store_true",
                        help="只报差异、不写文件（对比 --out 处的旧索引）")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    ledger = Path(args.ledger).resolve() if args.ledger else None
    excl = set(args.exclude) if args.exclude else None
    try:
        entries = build_index(root, ledger, excl)
    except DocMapError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(render_json(entries))
        return 0

    if args.check:
        out = Path(args.out)
        if not out.exists():
            print(f"[FAIL] 旧索引不存在，无法 --check：{out}", file=sys.stderr)
            return 2
        try:
            old = load_index_toml(out)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            print(f"[FAIL] 旧索引读不了：{exc}", file=sys.stderr)
            return 2
        msgs = diff_entries(old, entries)
        if msgs:
            print(f"[FAIL] 索引有 {len(msgs)} 处差异：")
            for m in msgs[:30]:
                print(f"  {m}")
            if len(msgs) > 30:
                print(f"  …等共 {len(msgs)} 处")
            return 1
        print(f"[OK ] 索引无差异：{len(entries)} 条与 {out.name} 一致")
        return 0

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_toml(entries), encoding="utf-8", newline="\n")
    pinned_n = sum(1 for e in entries if e["pinned"])
    print(f"[OK ] 写出 {len(entries)} 条到 {out}（被台账钉住 {pinned_n} 份）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
