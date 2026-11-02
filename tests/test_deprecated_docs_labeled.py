"""「自己说已废弃」的文档必须挂上牌子（卡 F13 / T-AG585）的钉子。

判据全在 `scripts/check_docs.py` 的 `check_superseded()`：正文自声明已过时
（`本文件已废弃` / `本文档不再适用。` / `本文档被 docs/x.md 取代` / `# 已废弃：x`）
却没有 frontmatter `status: superseded` + 非空 `supersedes:` ⇒ 欠账一条。
补了 frontmatter 就跳过（`if labeled: continue`）。

这四条钉的是**这份 dsh-web 对照文档真的挂上了牌子**，不许靠「删掉那句声明」蒙混：

1. 真仓库那篇文档：首行就是 frontmatter，且 `split_frontmatter()` 读得出
   `status == "superseded"` 与**非空** `supersedes`，且 supersedes 点名了取代它的真身；
2. 反向（证据的一半）：把正文那句自声明摘掉 frontmatter 后丢进合成仓 ⇒
   `check_superseded()` 必须正好报 1 条 —— 它不红，这条判据就是死的；
3. 全仓不变式：真仓库里被判「自声明已过时却没挂 frontmatter」的，只有那 1 篇已知欠账，
   本篇**不在**里面；
4. 原文没被删：四条「没有远程访问面」的原句仍在文件里（作废 ≠ 抹掉历史）。

**不许把行号写死进本文件** —— 文档会长，行号会漂（这正是本卡在治的病）。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import check_docs as cd  # noqa: E402 —— 先把 scripts/ 挂上 sys.path

REL = "复盘/DSH插件-dsh-web逐包对照.md"
# 已知欠账：没挂 frontmatter 的自声明废弃篇（基线 superseded = 1 就是它）
KNOWN_UNLABELED = "复盘/已废弃-学校通知聚合.md"
# 当年那四条「没有远程面」的原句（作废是加牌子，不是删历史）
ORIGINAL_CLAIMS = (
    "远程/移动面：**没有**",
    "我们没有远程访问面",
    "服务的是一个我们没有的远程通道",
    "无远程面；",
)


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _labeled(text: str) -> bool:
    """与 `check_docs.check_superseded()` 同一条口径：status + 非空 supersedes。"""
    meta, _, _ = cd.split_frontmatter(text)
    return (
        meta.get("status", "").strip().lower() == "superseded"
        and bool(meta.get("supersedes", "").strip())
    )


def test_the_doc_is_labeled_superseded() -> None:
    text = _read(REL)
    first = text.lstrip("\ufeff").split("\n", 1)[0].rstrip("\r").strip()
    assert first == "---", f"首行必须逐字是 ---（不然 frontmatter 根本不被认）：{first!r}"

    meta, body, offset = cd.split_frontmatter(text)
    assert offset > 0, "split_frontmatter 没认出 frontmatter（它要求首行就是 ---）"
    assert meta.get("status", "").strip().lower() == "superseded", meta
    supersedes = meta.get("supersedes", "").strip()
    assert supersedes, "supersedes 不许空 —— 空着等于没说是谁取代了它"
    assert (
        "src/timeflow/core/lan.py" in supersedes
        or "docs/subsystems/pool/README.md" in supersedes
    ), f"supersedes 必须点名真身（代码或现算说明书），不许写「同上」：{supersedes!r}"
    assert body.strip(), "frontmatter 之后正文不许是空的"


def test_removing_the_label_makes_the_checker_report_it(tmp_path: Path) -> None:
    """反向：摘掉 frontmatter 丢进合成仓 ⇒ 必须正好报 1 条。"""
    text = _read(REL)
    meta, body, _ = cd.split_frontmatter(text)
    assert meta, "前提不成立：这篇现在没有 frontmatter，反向钉子无从谈起"

    stripped = body.lstrip("\n")
    doc = tmp_path / "复盘" / Path(REL).name
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(stripped, encoding="utf-8")

    assert not _labeled(stripped), "摘掉 frontmatter 之后不该还被当成已标注"
    decls = cd.superseded_declarations(stripped)
    assert decls, (
        "摘掉 frontmatter 后一句自声明都认不出来 —— 说明牌子只挂在 frontmatter 上，"
        "正文里那句「本文件已废弃」写坏了（`check_docs` 的自声明句式认不出它）"
    )

    findings = cd.check_superseded(tmp_path, [doc])
    assert len(findings) == 1, [(f.where, f.detail) for f in findings]
    assert "status: superseded" in findings[0].detail


def test_no_new_unlabeled_declared_deprecation_in_the_repo() -> None:
    """全仓不变式：被判「自声明已过时却没挂 frontmatter」的只许是那一篇已知欠账。"""
    report = cd.scan(ROOT)
    tokens = sorted(f.where for f in report.superseded)
    assert tokens == [KNOWN_UNLABELED], (
        "自声明已过时却没挂 frontmatter 的篇目变了。多出来的是谁就补谁的牌子："
        f"{tokens}"
    )
    assert REL not in tokens


def test_the_original_four_claims_are_still_there() -> None:
    """作废 = 加牌子，不是删历史。原句必须还在，否则这张卡变成「悄悄改结论」。"""
    text = _read(REL)
    missing = [s for s in ORIGINAL_CLAIMS if s not in text]
    assert not missing, f"这些原句被删掉了（不许删，只许在上面挂作废横幅）：{missing}"
    assert "本文件已废弃" in text
    assert "现在以什么为准" in text
