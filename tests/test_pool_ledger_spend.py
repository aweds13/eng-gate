"""卡 E95 · 判据 3：写侧记「无价」（`tools/pool/ledger_spend.py::append(priced=...)`）。

三态，逐条钉住：

- `priced=None`（缺省）⇒ **不写这个键**：老行形状逐字节不变（9 键，键序/序列化都不动）；
- `priced=False` ⇒ 写字面 `false`，`unpriced()` 数得到（判据的钉子：`== 1`）；
- `priced=True` ⇒ 写字面 `true`，`unpriced()` **不**数它；
- 读侧：缺席键仍按 `Entry.priced = True`（老行照样算有价）。

账一律写在 `tmp_path` 里（`root=`），**不碰仓库真 `gates/diag/pool-spend.jsonl`**。
"""

from __future__ import annotations

import importlib
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

ledger_spend = importlib.import_module("pool.ledger_spend")
pool_accounts = importlib.import_module("pool_accounts")

TZ = pool_accounts.TZ
#: 钉死的「现在」—— 与 `tests/test_pool_cleared.py` 同一个时刻，方便对着读。
NOW = datetime(2026, 10, 12, 23, 28, tzinfo=TZ)
#: 计数的窗口：左闭右开 `[START, END)`。
START = NOW - timedelta(hours=1)
END = NOW + timedelta(hours=1)
ACCOUNT = "acct-e95"

#: 老行的 9 个键（`append()` 从未写 `priced` 时的形状）。判据 3 说的「老行形状不变」就是这 9 个。
LEGACY_KEYS = (
    "account",
    "at",
    "cache_read",
    "cache_write",
    "card",
    "cost",
    "input_tokens",
    "model",
    "output_tokens",
)


def rows(root: Path) -> list[dict[str, object]]:
    """把账文件逐行读回 dict（`spend_path(root)` 是唯一口径）。"""
    path = ledger_spend.spend_path(root)
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def add(root: Path, **extra: object) -> Path:
    """往 `root` 的账里追加一行；`extra` 透传给 `append()`（用 `priced=`）。"""
    return ledger_spend.append(
        ACCOUNT,
        "E95",
        "m95",
        input_tokens=10,
        output_tokens=2,
        cache_read=3,
        cost=0.5,
        at=NOW,
        root=root,
        **extra,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------- 判据 3：缺省不写键

def test_append_without_priced_keeps_the_legacy_shape(tmp_path: Path) -> None:
    """判据 3 前半：`None` ⇒ 不写这个键（老行形状逐字节不变）。"""
    add(tmp_path)
    (row,) = rows(tmp_path)
    assert "priced" not in row
    assert tuple(sorted(row)) == LEGACY_KEYS
    # 逐字节：整行就是这 9 键按 `sort_keys` 序列化出来的那一串。
    path = ledger_spend.spend_path(tmp_path)
    assert path.read_text(encoding="utf-8") == json.dumps(
        row, ensure_ascii=False, sort_keys=True
    ) + "\n"


def test_append_without_priced_does_not_get_counted_as_unpriced(tmp_path: Path) -> None:
    """判据 3 的钉子后半：默认 `append()` 后 `unpriced(...)` 仍是 0。"""
    add(tmp_path)
    assert ledger_spend.unpriced(ACCOUNT, START, END, root=tmp_path) == 0


def test_entry_defaults_missing_priced_to_true(tmp_path: Path) -> None:
    """读侧：缺席键按 `True`（老行照样算有价）—— 这一条不许被写侧的改动带坏。"""
    add(tmp_path)
    (line,) = [
        text
        for text in ledger_spend.spend_path(tmp_path).read_text(encoding="utf-8").splitlines()
        if text
    ]
    entry = ledger_spend._entry(line)  # noqa: SLF001 —— 判据要打在真解析上
    assert entry is not None
    assert entry.priced is True


# ---------------------------------------------------------------- 判据 3：显式给值

def test_append_priced_false_is_counted_by_unpriced(tmp_path: Path) -> None:
    """判据 3 的钉子前半：`append(priced=False)` 后 `unpriced(...) == 1`。"""
    add(tmp_path, priced=False)
    assert ledger_spend.unpriced(ACCOUNT, START, END, root=tmp_path) == 1
    (row,) = rows(tmp_path)
    assert row["priced"] is False  # 字面 `false`，不是字符串、不是 0


def test_append_priced_true_is_not_counted_and_is_written_literally(tmp_path: Path) -> None:
    add(tmp_path, priced=True)
    assert ledger_spend.unpriced(ACCOUNT, START, END, root=tmp_path) == 0
    (row,) = rows(tmp_path)
    assert row["priced"] is True


def test_three_states_land_in_one_file_and_are_counted_separately(tmp_path: Path) -> None:
    """三种形态共存：只有 `False` 那一行被数到；另外两行（缺席 / `True`）都算有价。"""
    add(tmp_path)
    add(tmp_path, priced=True)
    add(tmp_path, priced=False)
    add(tmp_path, priced=False)
    got = rows(tmp_path)
    assert [row.get("priced", "缺省") for row in got] == ["缺省", True, False, False]
    assert ledger_spend.unpriced(ACCOUNT, START, END, root=tmp_path) == 2
    # 无价的行仍然有 tokens / cost（`unpriced()` 是提问，不是估算：不改别的数）。
    # tokens = input + output + cache_write = 12/行 × 4 行；cost 5 毛 × 4；calls 4。
    assert ledger_spend.sums(ACCOUNT, START, END, root=tmp_path) == (48, 2.0, 4)


# ---------------------------------------------------------------- 口径：仍按 `sums()` 那套

def test_unpriced_respects_the_window_and_the_account(tmp_path: Path) -> None:
    """左闭右开、只数本账号 —— 与 `sums()` 同口径（窗口外 / 别的账号都不算）。"""
    add(tmp_path, priced=False)
    ledger_spend.append(
        "other",
        "E95",
        "m95",
        input_tokens=1,
        output_tokens=0,
        cache_read=0,
        cost=0.0,
        at=NOW,
        priced=False,
        root=tmp_path,
    )
    ledger_spend.append(
        ACCOUNT,
        "E95",
        "m95",
        input_tokens=1,
        output_tokens=0,
        cache_read=0,
        cost=0.0,
        at=END + timedelta(seconds=1),
        priced=False,
        root=tmp_path,
    )
    assert ledger_spend.unpriced(ACCOUNT, START, END, root=tmp_path) == 1


def test_unpriced_is_zero_when_the_file_is_missing(tmp_path: Path) -> None:
    """文件不存在 ⇒ `0`（不是「判不出来」的异常）—— 与 `sums()` 同一口径。"""
    assert not ledger_spend.spend_path(tmp_path).exists()
    assert ledger_spend.unpriced(ACCOUNT, START, END, root=tmp_path) == 0
