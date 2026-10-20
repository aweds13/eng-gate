r"""墓碑表：被证伪的结论不许再当事实（卡 A307 · T-AG421）。

## 这张表治什么

`docs/tombstones.toml` 每一条记一句**曾经被当真、后来被实测推翻**的话 + 推翻它的证据。
文档只加不改（本仓「加注法」）⇒ 被推翻的结论天然会漂到新窗口的嘴里：上一轮的「边界」
被下一轮的实测打掉，可原文还在，新人照抄一眼看去就是事实。墓碑表就是那份**名单 + 门**。

## 三条判据（本文件就是门）

1. **表自洽**：字段齐 / id 唯一且成形 / `refuted_by` 与 `where` 都指向**真实存在且进 git**
   的文件 / `refuted_at` 是真日期。判错时点名哪条墓碑缺什么、指到哪个不存在的路径。
2. **判据会咬**：扫全仓**进 git** 的 markdown，某行含某条墓碑的 `needles`、且整行
   **没有任何推翻标记** ⇒ 红；点名 `文件:行` + 是哪条墓碑（不是笼统「有 3 处」）。
3. **`where` 不是摆设**：那几份文档必须**真的还提到它**，否则说这张表在撒谎。

②的取样是**临时目录里的合成样例**（造一份「原文照搬」⇒ 必须红；再给同一句加上
推翻标记 ⇒ 必须绿），不拿真仓库当小白鼠。真仓库那一遍（`test_repo_has_no_resurrection`）
是**顺带**的读数，脏了就是脏了，不许为它改判据。

## 扫描范围

`git ls-files -- '*.md'`：`docs/**` + `复盘/**` + `skills/**` + 根目录那几份。
不含 `.wt/<卡>` 旁支、不含 `gates/`（本机产物，不进 git）；没有 git 的临时目录退回 `rglob`。
"""

from __future__ import annotations

import re
import subprocess
from datetime import date
from pathlib import Path

import pytest
import tomllib

ROOT = Path(__file__).resolve().parent.parent
TABLE_REL = "docs/tombstones.toml"

# 一句「这已经被推翻了」的标记。整行命中任一 ⇒ 这一行不是「还在把它当事实讲」。
# 只收**明确的推翻词**：放宽到「注 / 存疑」就等于给判据开后门（原句还在，读者照样会照抄）。
RESURRECTION_MARKERS = (
    "推翻",
    "撤回",
    "证伪",
    "墓碑",
    "已废弃",
    "不再成立",
    "已被取代",
    "不可达",
    "更正",
    "refuted",
    "tombstone",
)

_ID_RE = re.compile(r"^T-AG421-\d{2}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_REQUIRED = ("id", "claim", "refuted_by", "refuted_at", "where", "needles")
_MIN_TABLE = 3


# ---------------------------------------------------------------- 纯函数（合成样例直接测它）


def marked(line: str) -> bool:
    """这一行有没有「已经被推翻」的标记。"""
    return any(m in line for m in RESURRECTION_MARKERS)


def resurrecting_lines(text: str, needles: list[str] | tuple[str, ...]) -> list[tuple[int, str]]:
    """把 `text` 逐行过一遍，返回还在把墓碑说法当事实的 (行号, 命中的 needle)。

    判据只有一句：**含 needle + 不含标记**。行号从 1 起，报给人看。
    """
    hits: list[tuple[int, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for needle in needles:
            if needle in line and not marked(line):
                hits.append((lineno, needle))
                break
    return hits


def markdown_texts(root: Path) -> dict[str, str]:
    """仓库里**进 git** 的 markdown：`{仓库相对路径: 全文}`。

    没有 `.git`（临时目录合成样例）⇒ 退回 `rglob("*.md")`，两种形态都能扫。
    """
    if (root / ".git").exists():
        raw = subprocess.run(
            ["git", "ls-files", "-z", "--", "*.md"],
            cwd=root,
            capture_output=True,
            check=True,
        ).stdout
        rels = [rel for rel in raw.decode("utf-8").split("\0") if rel]
    else:
        rels = [p.relative_to(root).as_posix() for p in sorted(root.rglob("*.md"))]
    return {rel: (root / rel).read_text(encoding="utf-8") for rel in rels}


def scan(root: Path, entries: list[dict]) -> list[str]:
    """跑一遍判据②，返回人话形式的违规（空 = 没有复活）。"""
    texts = markdown_texts(root)
    problems: list[str] = []
    for entry in entries:
        for rel, text in texts.items():
            for lineno, needle in resurrecting_lines(text, entry["needles"]):
                problems.append(
                    f"{rel}:{lineno} 还在把「{needle}」当事实讲（墓碑 {entry['id']}）"
                )
    return problems


def is_tracked(root: Path, rel: str) -> bool:
    """`git ls-files --error-unmatch <rel>` 认不认它（= 已进 git，不是本机残留）。"""
    if not (root / ".git").exists():
        return True
    done = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", rel], cwd=root, capture_output=True
    )
    return done.returncode == 0


# ---------------------------------------------------------------- 夹具


@pytest.fixture(scope="module")
def table() -> list[dict]:
    """把墓碑表读成 list[dict]（每条一条墓碑）。表坏了在这里就炸，不用等逐条断言。"""
    raw = (ROOT / TABLE_REL).read_text(encoding="utf-8")
    return tomllib.loads(raw)["tombstone"]


# ---------------------------------------------------------------- ① 表自洽


def test_table_has_enough_tombstones(table: list[dict]) -> None:
    """首批至少 3 条 —— 一条串不成「名单」，只是随笔。"""
    assert len(table) >= _MIN_TABLE, f"{TABLE_REL} 只有 {len(table)} 条墓碑"


def test_each_tombstone_has_required_fields(table: list[dict]) -> None:
    """字段齐 + 类型对（`where` / `needles` 是非空字符串列表）。"""
    for entry in table:
        missing = [key for key in _REQUIRED if key not in entry]
        assert not missing, f"墓碑 {entry.get('id', '<无 id>')} 缺字段 {missing}"
        for key in ("id", "claim", "refuted_by", "refuted_at"):
            assert isinstance(entry[key], str) and entry[key].strip(), (
                f"墓碑 {entry['id']} 的 {key} 必须是非空字符串"
            )
        for key in ("where", "needles"):
            value = entry[key]
            assert isinstance(value, list) and value, f"墓碑 {entry['id']} 的 {key} 必须是非空列表"
            bad = [item for item in value if not isinstance(item, str) or not item.strip()]
            assert not bad, f"墓碑 {entry['id']} 的 {key} 里有空项 / 非字符串：{bad}"


def test_ids_unique_and_shaped(table: list[dict]) -> None:
    """id 唯一，且长得像墓碑号（`T-AG421-NN`）—— 别拿句子当 id。"""
    ids = [entry["id"] for entry in table]
    assert len(ids) == len(set(ids)), f"墓碑 id 重复：{ids}"
    for tid in ids:
        assert _ID_RE.match(tid), f"墓碑 id 不合形（应 T-AG421-NN）：{tid}"


def test_refuted_at_is_a_real_date(table: list[dict]) -> None:
    """`refuted_at` 是 `YYYY-MM-DD` 且真是日历上的一天（2026-02-30 不算）。"""
    for entry in table:
        value = entry["refuted_at"]
        assert _DATE_RE.match(value), f"墓碑 {entry['id']} 的 refuted_at 不是 YYYY-MM-DD：{value}"
        try:
            date.fromisoformat(value)
        except ValueError as exc:  # pragma: no cover - 只有手滑才走到
            pytest.fail(f"墓碑 {entry['id']} 的 refuted_at 不是真日期：{value}（{exc}）")


def test_refuted_by_points_at_a_real_tracked_file(table: list[dict]) -> None:
    """`refuted_by` 必须是**仓内真实存在且进 git** 的文件 —— 证据不能是你脑子里的记忆。"""
    for entry in table:
        rel = entry["refuted_by"]
        path = ROOT / rel
        assert path.is_file(), f"墓碑 {entry['id']} 的证据不存在：{rel}"
        assert is_tracked(ROOT, rel), f"墓碑 {entry['id']} 的证据没进 git：{rel}"


def test_where_docs_exist(table: list[dict]) -> None:
    """`where` 列的每一份都得真实存在（写错路径 = 这份名单在骗人）。"""
    for entry in table:
        for rel in entry["where"]:
            assert (ROOT / rel).is_file(), f"墓碑 {entry['id']} 的 where 指向不存在的文件：{rel}"


def test_where_docs_still_mention_the_claim(table: list[dict]) -> None:
    """`where` 语义是「仍在引用它」⇒ 每份必须真的还含某个 needle，否则就是这张表在撒谎。"""
    for entry in table:
        for rel in entry["where"]:
            text = (ROOT / rel).read_text(encoding="utf-8")
            assert any(needle in text for needle in entry["needles"]), (
                f"墓碑 {entry['id']} 的 where 列了 {rel}，但那份文档根本不提这句话"
            )


def test_needles_are_specific(table: list[dict]) -> None:
    """needle 是「只属于这句话」的短语：太短会误伤全仓（`没跑过` 那种），跨墓碑重复也没意义。"""
    seen: dict[str, str] = {}
    for entry in table:
        for needle in entry["needles"]:
            assert len(needle) >= 4, f"墓碑 {entry['id']} 的 needle 太短，会误伤：{needle!r}"
            assert needle not in seen, (
                f"needle {needle!r} 同时挂在 {seen[needle]} 与 {entry['id']} 上"
            )
            seen[needle] = entry["id"]


# ---------------------------------------------------------------- ② 判据会咬（合成样例）


def _plant(root: Path, name: str, body: str) -> Path:
    """在临时目录里造一份 markdown（不写真仓库）。"""
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


SYNTHETIC_CLAIM = "开真实页面的正式口子是 openResource(url)，把 http 地址交给它就行"


def test_guard_bites_on_verbatim_copy(tmp_path: Path) -> None:
    """**原文照搬 ⇒ 必须红**，还点得出 文件:行（这条判据会咬的证明）。"""
    _plant(tmp_path, "docs/new.md", f"# 新文档\n\n结论：{SYNTHETIC_CLAIM}。\n")
    problems = scan(tmp_path, [{"id": "T-AG421-99", "needles": ["openResource(url)"]}])
    assert len(problems) == 1, problems
    assert "docs/new.md:3" in problems[0]
    assert "T-AG421-99" in problems[0]


def test_guard_tolerates_annotated_copy(tmp_path: Path) -> None:
    """同一句加一句推翻标记 ⇒ 必须绿（否则这判据只会逼人删原文）。"""
    body = f"# 新文档\n\n结论：{SYNTHETIC_CLAIM}（已被 `复盘/交接.d/T-G363.md` 推翻）。\n"
    _plant(tmp_path, "docs/annotated.md", body)
    assert scan(tmp_path, [{"id": "T-AG421-99", "needles": ["openResource(url)"]}]) == []


def test_guard_reports_every_offending_line(tmp_path: Path) -> None:
    """三行复活、两行加注 ⇒ 报 3 条，且逐行点名（不许只报一句「有问题」）。"""
    body = "\n".join(
        [
            SYNTHETIC_CLAIM,  # 1 红
            f"{SYNTHETIC_CLAIM}（已推翻）",  # 2 绿
            f"再次强调：{SYNTHETIC_CLAIM}",  # 3 红
            "",  # 4
            "与 openResource(url) 无关的另一句。",  # 5 红（含 needle、无标记）
        ]
    )
    _plant(tmp_path, "note.md", body + "\n")
    problems = scan(tmp_path, [{"id": "T-AG421-99", "needles": ["openResource(url)"]}])
    assert len(problems) == 3, problems
    assert [p.split()[0] for p in problems] == ["note.md:1", "note.md:3", "note.md:5"]


def test_real_needles_bite_on_a_synthetic_copy(tmp_path: Path, table: list[dict]) -> None:
    """拿**真表**的 needle 造一份「照搬」⇒ 每条都必须咬住（证明名单上的词真能拦住复述）。"""
    for entry in table:
        needle = entry["needles"][0]
        _plant(tmp_path, f"copy-{entry['id']}.md", f"这条道就是 {needle}，照它做。\n")
        problems = scan(tmp_path, [entry])
        assert problems, f"墓碑 {entry['id']} 的 needle {needle!r} 咬不住，这条墓碑是空的"


def test_scan_reads_files_at_all(tmp_path: Path) -> None:
    """反向：**没有** needle 的仓 ⇒ 绿；否则上面几条「红」可能来自 scan 本身乱报。"""
    _plant(tmp_path, "docs/clean.md", "# 干净文档\n\n这里什么墓碑说法都没有。\n")
    assert scan(tmp_path, [{"id": "T-AG421-98", "needles": ["openResource(url)"]}]) == []


# ---------------------------------------------------------------- ③ 真仓库读数


def test_scan_covers_the_repo(table: list[dict]) -> None:
    """先证明扫描面不是空的：几十份以上的 md，且 docs/ 与 复盘/ 都在里面。

    （一个什么都读不到的扫描会「全绿」—— 那是最坏的假绿。）
    """
    texts = markdown_texts(ROOT)
    assert len(texts) >= 50, f"只扫到 {len(texts)} 份 markdown，扫描面太小"
    assert any(rel.startswith("docs/") for rel in texts)
    assert any(rel.startswith("复盘/") for rel in texts)


def test_repo_has_no_resurrection(table: list[dict]) -> None:
    """真仓库跑一遍：**没有**任何一行还在把墓碑里的说法当事实讲。

    红了怎么办：给那一行补一句「（已被 <证据> 推翻）」再跑 —— 判据不改，原文不删。
    """
    problems = scan(ROOT, table)
    assert not problems, "以下行还在复述已被推翻的结论：\n" + "\n".join(problems)
