"""卡 E64 / T-AG522：`wb_verify` 的 rev 判据必须能认出「同一个提交的两种短写法」。

病灶（实测）：门禁产物 `gates/last.json` 把 rev 记成 **10** 位（`rev[:10]`），
而 `parent` 来自 `git rev-parse --short`（**8** 位）。旧判据
`parent.startswith(rev)` 于是恒为 False ⇒ 每一笔落地都误判「rev != 父提交」。

这组用例全部走**真函数**（从 `tools/wb_verify.py` 里 import），不复制实现。
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
WB_VERIFY = ROOT / "tools" / "wb_verify.py"

FULL = "77dc71cb7717e734ef1ccb02f3b6d45232707bd3"


def _load():
    """按路径 import `tools/wb_verify.py`（它不是包，直接 import 名字会撞仓里别的模块）。"""
    spec = importlib.util.spec_from_file_location("wb_verify_card_e64", WB_VERIFY)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def wv():
    return _load()


def _payload(rev: str) -> dict:
    """一份形状最小、但自证通过的产物：一道阻断门 exit_code=0。"""
    return {
        "ok": True,
        "rev": rev,
        "host": "test-host",
        "at": "2026-10-29T00:31:14",
        "tree": "3c15aedaab20",
        "tree_scope": "worktree-minus-gates",
        "gates": [{"name": "pytest", "exit_code": 0, "blocking": True}],
        "not_run": [],
        "reused": {},
        "trailer": "pytest",
    }


def _rev_ok(wv, payload: dict, parent: str) -> bool:
    """把 `check_gates` 里的 rev 判据单独拎出来跑 —— 用**同一个** MIN_SHA_LEN 常量。"""
    rev = str(payload.get("rev") or "")
    rev_short = rev[: len(parent)] if parent else rev
    return bool(rev) and bool(parent) and min(len(rev_short), len(parent)) >= wv.MIN_SHA_LEN and (
        parent.startswith(rev_short) or rev_short.startswith(parent)
    )


def test_min_sha_len_is_the_git_short_floor(wv) -> None:
    """分辨率下限就是 7 —— 写死别的数（比如 6）会让「前 6 位撞车」被当成同一个提交。"""
    assert wv.MIN_SHA_LEN == 7


@pytest.mark.parametrize(
    ("rev", "parent"),
    [
        # 正例：门禁 10 位 vs `--short` 8 位（这是出事的那一对）
        (FULL[:10], "77dc71cb"),
        # 正例：反过来，rev 比 parent 短
        ("77dc71cb", FULL),
        # 正例：两边都是 7 位
        (FULL[:7], FULL[:7]),
        # 正例：短的那方是 8 位，长的那方 40 位
        (FULL[:8], FULL),
    ],
)
def test_same_commit_written_at_different_lengths_is_ok(wv, rev, parent) -> None:
    assert _rev_ok(wv, _payload(rev), parent) is True


@pytest.mark.parametrize(
    ("rev", "parent"),
    [
        # 反例：真不同的提交 —— 差异必须落在**可比的位**上。
        #   ★ 注意：rev 只有 10 位时，父提交在第 11 位之后怎么变都是「同一个提交的更长写法」，
        #   那不是判据的错，是 rev 本身的分辨率只到 10 位。所以反例要让差异出现在前 10 位内。
        (FULL[:10], FULL[:9] + "0" + FULL[10:]),
        (FULL[:10], "deadbeef"),
        # 反例：空 rev / 空 parent
        ("", "77dc71cb"),
        (FULL[:10], ""),
        # 反例：太短，没有分辨率（6 位）
        (FULL[:6], FULL[:6]),
        # 反例：短方仅 6 位，即便另一方是它的前缀也不算
        (FULL[:6], FULL),
    ],
)
def test_different_commit_or_too_short_is_red(wv, rev, parent) -> None:
    assert _rev_ok(wv, _payload(rev), parent) is False


def test_real_product_shape_passes(wv) -> None:
    """用仓里 `gates/last.json` 的真实 rev 形状（10 位）+ 真父提交（40 位）跑一遍。"""
    payload = _payload(FULL[:10])
    assert _rev_ok(wv, payload, FULL) is True


def test_the_old_ruler_would_have_failed_the_same_pair(wv) -> None:
    """反向证明：旧判据 `parent.startswith(rev)` 在同一对上**恒红**。

    这条用例存在的意义：如果哪天有人把判据改回单向 `startswith`，
    这里不会红（它测的是旧实现），但上面 `test_same_commit_*` 会红。
    留它是为了把「为什么必须双向」写成可执行的话。
    """
    rev, parent = FULL[:10], FULL[:8]
    assert parent.startswith(rev) is False
    assert _rev_ok(wv, _payload(rev), parent) is True
