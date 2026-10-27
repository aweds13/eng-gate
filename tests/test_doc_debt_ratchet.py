"""文档欠账基线**不许静默回涨**、也**不许为了变绿往上抬**（卡 F6）。

## 为什么单开这个文件

`tests/test_check_docs.py` 有意**只钉"看得见 + 基线可读"，不钉欠账条数**（那个文件里
写明了理由：写进钉子会让还债的人莫名撞红）。于是"欠账悄悄涨回 343"这件事**没人守**：
`check_docs.py` 自己的 ratchet 只在**跑那道门时**才咬，而门可以很久不跑。

这个文件补的正是那一格。

## ★ 关键事实：`ratchet()` 咬不住「往上调基线」

`scripts/check_docs.py` 的 `ratchet()` 比的是「**当前读数 vs 当前基线**」。所以有人把
`docs/doc-debt-baseline.toml` 里的 `dead_refs` 从 152 改成 199 时，读数 152 < 199 ⇒
门打的是 `死指针 152（基线 199，-47）`、**exit=0**，一片绿。这不是断言写松了，是结构：
基线自己当参照物，抬高它必然绿。**实测过**：

    $ sed -i 's/^dead_refs = 152$/dead_refs = 199/' docs/doc-debt-baseline.toml
    $ python -X utf8 scripts/check_docs.py --mode report   # EXIT=0，全绿

⇒ 所以这里需要**第二个参照物**：`PINNED_FLOOR`（这棵树**曾经到过的地板**）。它与基线
互相钳制：基线 ≤ 地板（本文件的钉子），读数 ≤ 基线（`check_docs` 的 ratchet）。
地板**只许跟着真还债往下改**（改它等于承认"这棵树到过更低"，是一句可核对的事实，
不是"我想让门绿"），**永不上调**。

## 只比 dead_refs / superseded，不比 drift

与 `scripts/check_docs.py` 的 `ratchet()` 同一口径：`drift` 是**可漂移量**（每一笔代码
提交都会动它，拿它做阈值必然假红），它只做对照、不参与 ratchet。要漂移的读数见
`docs/doc-debt-baseline.toml` 里 `drift` 那一段注释（基线 379 / 实测 432，差额待查）。

## 四条用例分工

1. `test_guard_bites_on_any_rise`（合成读数）—— 证明判据本体真的会咬，先红后绿，
   不做这条的话下面几条可能是"永远绿的空转"。
2. `test_pinned_floor_never_rises`（真文件）—— ★ 咬「往上调基线」那一手。
3. `test_real_repo_debt_does_not_exceed_baseline`（真文件）—— 咬「欠账回涨」。
4. `test_cli_bites_on_real_regression`（`tmp_path` 真 git 小树 + **真子进程**）——
   证明不是只有我这个模块在自说自话：`scripts/check_docs.py` 在命令行上遇到
   「读数 > 基线」确实退 1 并打出「涨到」。

## 红了怎么办（顺序写死，别跳步）

1. **先查是不是回涨**：读失败信息里的差额，再到 `check_docs.py --json` 看是哪几条。
2. 确认是**判据被改宽**（不是欠账变多）⇒ 那是判据的事，先改判据、别动这里。
3. 确认是**真回涨**（新写坏的引用 / 新欠账）⇒ 修文档，把读数压回去。
4. **绝不**为了让这条绿而往上调基线或地板 —— 那等于把判据改软（基线文件头第 ④ 条）。
   真还债之后该做的是**同时**把基线与地板的数字往下压（两格都改，不是只改一个）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import check_docs as cd  # noqa: E402 —— 需要先把 scripts/ 挂上 sys.path

BASELINE_REL = "docs/doc-debt-baseline.toml"

#: 参与 ratchet 的两项（`drift` 不在此列：它每笔提交都动，见文件头）。
RATCHETED = ("dead_refs", "superseded")

#: ★ 这棵树**曾经到过的地板**（2026-10-27 实测：判据收窄 + 修掉 103 条 `../` 层级错）。
#:
#: 只许**跟着真还债往下改**（改小 = 「我确认真降到这么低了」，可核对）；
#: **永不上调** —— 上调就是替"把基线抬上去让门变绿"背书，而那正是本文件要拦的手。
#: 基线文件与它交叉钳制：`ratchet()` 保证读数 ≤ 基线，这里保证基线 ≤ 地板。
PINNED_FLOOR = {"dead_refs": 152, "superseded": 1}


def _over(counts: dict[str, int], baseline: dict[str, int]) -> list[str]:
    """逐项比「现在 vs 基线」；**只报涨的**（降了是好事，不是这里的判据）。"""
    problems: list[str] = []
    for key in RATCHETED:
        now, was = counts.get(key, 0), baseline.get(key, 0)
        if now > was:
            problems.append(f"{key}：基线 {was} → 现在 {now}（+{now - was}）")
    return problems


def _above_floor(baseline: dict[str, int], floor: dict[str, int]) -> list[str]:
    """逐项比「基线 vs 地板」；基线**高过地板**就点名（调高基线 = 把门改软）。"""
    problems: list[str] = []
    for key in RATCHETED:
        now, floor_at = baseline.get(key, 0), floor.get(key, 0)
        if now > floor_at:
            problems.append(
                f"{key}：地板 {floor_at} → 基线被抬到 {now}（+{now - floor_at}）"
            )
    return problems


# ------------------------------------------------- ① 判据真的会咬（合成读数）
@pytest.mark.parametrize(
    ("counts", "baseline", "expected"),
    [
        # 涨一条就红（这就是"静默回涨"）
        ({"dead_refs": 5, "superseded": 0}, {"dead_refs": 4, "superseded": 0},
         ["dead_refs：基线 4 → 现在 5（+1）"]),
        # 两项同时涨 ⇒ 两条都点名
        ({"dead_refs": 9, "superseded": 3}, {"dead_refs": 8, "superseded": 1},
         ["dead_refs：基线 8 → 现在 9（+1）", "superseded：基线 1 → 现在 3（+2）"]),
        # 持平 ⇒ 不红（基线是地板，不是天花板）
        ({"dead_refs": 4, "superseded": 1}, {"dead_refs": 4, "superseded": 1}, []),
        # 降了 ⇒ 不红（降了之后该做的是把基线调低，不是把这里改红）
        ({"dead_refs": 2, "superseded": 0}, {"dead_refs": 4, "superseded": 5}, []),
        # drift 涨多少都不在这里红（可漂移量，不参与 ratchet）
        ({"dead_refs": 4, "superseded": 1, "drift": 999},
         {"dead_refs": 4, "superseded": 1, "drift": 379}, []),
    ],
)
def test_guard_bites_on_any_rise(
    counts: dict[str, int], baseline: dict[str, int], expected: list[str]
) -> None:
    """★ 判据本体：涨了必须点名到「哪一项、基线多少、现在多少、差额多少」。"""
    assert _over(counts, baseline) == expected, _over(counts, baseline)


# ------------------------------------------------- ② 基线不许被抬到地板之上
def test_pinned_floor_never_rises() -> None:
    """★ 咬「往上调基线让门变绿」：基线**不许高过地板**（`ratchet()` 结构上拦不住）。"""
    baseline, why = cd.load_baseline(ROOT / BASELINE_REL)
    assert why == "", f"基线读不了（{BASELINE_REL}）：{why}"

    problems = _above_floor(baseline, PINNED_FLOOR)
    assert not problems, (
        "基线被抬到地板之上了 —— 而 `ratchet()` 比的是「读数 vs 当前基线」，"
        "把基线抬高必然变绿（实测：改成 199 时门 exit=0 打「-47」）：\n  "
        + "\n  ".join(problems)
        + f"\n\n当前基线：{baseline}\n地板（PINNED_FLOOR）：{PINNED_FLOOR}"
        + "\n\n改法：把基线的数字**改回地板**（真还债了就把地板也一起往下压）；"
        "\n**不许**为了让门绿往上调基线（基线文件头第 ④ 条）。"
    )


# ------------------------------------------------- ③ 真仓库：读数不许超基线
def test_real_repo_debt_does_not_exceed_baseline() -> None:
    """★ 真仓库跑一遍：`check_docs.scan()` 的 dead_refs / superseded **不许超基线**。"""
    baseline, why = cd.load_baseline(ROOT / BASELINE_REL)
    assert why == "", f"基线读不了（{BASELINE_REL}）：{why}"

    report = cd.scan(ROOT)
    counts = report.counts()
    problems = _over(counts, baseline)

    assert not problems, (
        "文档欠账**回涨**了 —— 基线是地板，只能降不能升：\n  "
        + "\n  ".join(problems)
        + f"\n\n实测读数：{counts}\n基线读数：{baseline}"
        + f"\n（drift 差额 {counts.get('drift', 0) - baseline.get('drift', 0):+d}"
        "：可漂移量，不在这里判，见基线文件里 drift 那段注释）"
        + "\n\n改法：先查是哪几条（`python -X utf8 scripts/check_docs.py --json`），"
        "修回欠账；\n**不许**为了让这条绿而往上调基线（那是把判据改软）。"
    )

    # 反空转：这道门在真仓库上必须**看得见东西**，否则"没超基线"可能只是扫了个空。
    assert counts["dead_refs"] + counts["superseded"] > 0, (
        f"真仓库上一条欠账都没判出来（{counts}）⇒ 这条判据等于空转，不许算绿"
    )


# ------------------------------------------------- ④ 命令行上真的会红（真子进程）
def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """在合成树里跑一条 git（不弹窗；测试里只用来把文件"入库"）。"""
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=str(root), capture_output=True, text=True, encoding="utf-8",
        errors="replace",
    )


def _tiny_repo(tmp_path: Path, baseline: dict[str, int]) -> Path:
    """一棵真 git 小树：`docs/ok.md` 合法 + 基线由 `baseline` 指定（**全是已入库文件**）。"""
    root = tmp_path / "tree"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "ok.md").write_text("见 `docs/ok.md`\n", encoding="utf-8")
    rows = "\n".join(f"{key} = {value}" for key, value in baseline.items())
    (root / BASELINE_REL).write_text(
        "# 合成基线（本用例只在 tmp 树里用）\n"
        "#   python -X utf8 scripts/check_docs.py --write-baseline\n"
        f"[baseline]\nupdated = \"2026-10-27\"\ntask = \"T-TEST\"\n{rows}\n",
        encoding="utf-8",
    )
    assert _git(root, "init", "-q").returncode == 0
    assert _git(root, "add", "-A").returncode == 0
    commit = _git(
        root, "-c", "user.name=test", "-c", "user.email=test@example.invalid",
        "commit", "-q", "-m", "seed",
    )
    assert commit.returncode == 0, commit.stderr
    return root


def _run_cli(root: Path, mode: str = "report") -> tuple[int, str]:
    """**真跑子进程**：`python -X utf8 scripts/check_docs.py --root <树> --mode <档>`。"""
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", str(ROOT / "scripts" / "check_docs.py"),
         "--root", str(root), "--mode", mode],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, proc.stdout + proc.stderr


def test_cli_bites_on_real_regression(tmp_path: Path) -> None:
    """★ 真子进程：新写坏一条引用把读数顶过基线 ⇒ 命令行退 1 且出现「涨到」。"""
    root = _tiny_repo(tmp_path, {"dead_refs": 0, "superseded": 0})
    code, out = _run_cli(root)
    assert code == 0, f"基线内应当绿，实际退 {code}：\n{out}"

    # 真写坏一条：`docs/bad.md` 指着不存在的 `docs/missing.md`
    (root / "docs" / "bad.md").write_text("看 `docs/missing.md` 这一句\n", encoding="utf-8")
    assert _git(root, "add", "-A").returncode == 0

    code, out = _run_cli(root)
    assert code == 1, f"超基线应当退 1，实际退 {code}：\n{out}"
    assert "涨到" in out, f"超基线时输出里必须有「涨到」，实际：\n{out}"
    assert "dead_refs" in out, f"必须点名是哪一项，实际：\n{out}"
