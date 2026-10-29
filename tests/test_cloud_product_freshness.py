"""卡 E66（T-AG526）：没跑完也把上一趟的绿搬回来了 —— 五条判据的钉子。

病灶（2026-10-29 03:00 云机被定时关机时实测）：
  `scripts/cloud/run_gate.sh` 的 2/5 把**上一趟的绿**播种到云机 `gates/last.json`，
  4/5 中途断线 ⇒ 5/5 **无条件**把那个路径 scp 回卡树。于是卡树里出现一份
  「绿的、`host` 是云机的、`rev` 也对得上」的产物 —— 它不是这一趟跑出来的，
  而落地链的 `ok` / `host` / `tree` 三道自检**全都过得去**。

判据 1：`at` 早于本趟起跑 ⇒ 不新鲜（①）。
判据 2：`at` 缺失或解不出 ⇒ 不新鲜（fail closed，判不出来的时候不许说没事）（②）。
判据 3：与播种源**逐字相同** ⇒ 不新鲜 —— 这条不依赖任何时钟（③，最硬的一条）。
判据 4：CLI 退码三态：新鲜 0 / 不新鲜 3 / 读不出 3（bash 侧只认非零）。
判据 5：`run_gate.sh` 的 5/5 真的会核验；不新鲜时**删掉产物并退 9**（脚本级，
        防「把这段删了而测试不知道」）。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _d in ("tools", "scripts"):
    if str(ROOT / _d) not in sys.path:
        sys.path.insert(0, str(ROOT / _d))

import gate_pool  # noqa: E402  —— 被测对象（sys.path 先插好了）

CLI = [sys.executable, "-X", "utf8", str(ROOT / "tools" / "gate_pool.py"), "check-product-fresh"]


def _product(at: str | None = None) -> dict:
    data: dict = {"ok": True, "rev": "abc1234", "host": "cloud-x"}
    if at is not None:
        data["at"] = at
    return data


# ---------------------------------------------------------------- 判据 1 / 2 / 3


def test_product_older_than_start_is_stale() -> None:
    """① `at` 早于起跑时刻 ⇒ 上一趟的读数。"""
    fresh, why = gate_pool.product_is_from_this_run(
        _product("2026-10-29T00:31:14"), started_at="2026-10-29T02:00:00"
    )
    assert fresh is False
    assert "早于本趟起跑" in why


def test_product_without_at_is_stale() -> None:
    """② 没有 `at` ⇒ 判不了 ⇒ 不许当新鲜。"""
    fresh, why = gate_pool.product_is_from_this_run(
        _product(None), started_at="2026-10-29T02:00:00"
    )
    assert fresh is False
    assert "at" in why


def test_product_with_unparseable_at_is_stale() -> None:
    """② `at` 写了但不是时间 ⇒ 同样判不了。"""
    fresh, why = gate_pool.product_is_from_this_run(
        _product("昨天下午"), started_at="2026-10-29T02:00:00"
    )
    assert fresh is False
    assert "at" in why


def test_product_identical_to_seed_is_stale_even_if_at_looks_new() -> None:
    """③ 逐字等于播种源 ⇒ 云机没写新读数，`at` 再新也不认（不依赖时钟）。"""
    text = json.dumps(_product("2026-10-29T03:10:00"), indent=2)
    fresh, why = gate_pool.product_is_from_this_run(
        json.loads(text),
        started_at="2026-10-29T02:00:00",
        shipped_text=text,
        seed_text=text,
    )
    assert fresh is False
    assert "播种源" in why


def test_boundary_at_equal_to_start_is_fresh() -> None:
    """边界：`at` 恰等于起跑时刻 ⇒ 算新鲜（否则秒级抖动会误杀真产物）。"""
    fresh, why = gate_pool.product_is_from_this_run(
        _product("2026-10-29T02:00:00"), started_at="2026-10-29T02:00:00"
    )
    assert fresh is True, why


def test_aware_and_naive_timestamps_compare_as_same_wall_clock() -> None:
    """`at` 是朴素串、起跑带偏移（`date -Iseconds` 就是这样）⇒ 按同一墙上时钟比。"""
    fresh, why = gate_pool.product_is_from_this_run(
        _product("2026-10-29T03:00:00"), started_at="2026-10-29T02:00:00+08:00"
    )
    assert fresh is True, why


# ---------------------------------------------------------------- 判据 4（CLI 三态）


def _run_cli(*args: str) -> tuple[int, str]:
    done = subprocess.run(CLI + list(args), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def test_cli_exit_code_is_three_for_stale(tmp_path: Path) -> None:
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps(_product("2026-10-29T00:31:14"), indent=2), encoding="utf-8")
    shipped = tmp_path / "last.json"
    shipped.write_text(seed.read_text(encoding="utf-8"), encoding="utf-8")
    rc, out = _run_cli(str(shipped), "--started-at", "2026-10-29T02:00:00", "--seed", str(seed))
    assert rc == 3, out
    assert "[stale]" in out


def test_cli_exit_code_is_zero_for_fresh(tmp_path: Path) -> None:
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps(_product("2026-10-29T00:31:14"), indent=2), encoding="utf-8")
    shipped = tmp_path / "last.json"
    shipped.write_text(json.dumps(_product("2026-10-29T03:05:00"), indent=2), encoding="utf-8")
    rc, out = _run_cli(str(shipped), "--started-at", "2026-10-29T02:00:00", "--seed", str(seed))
    assert rc == 0, out
    assert "[fresh]" in out


def test_cli_missing_product_is_not_fresh(tmp_path: Path) -> None:
    """文件根本不在（云机没回传 / 已被删）⇒ 非零，不许静默当通过。"""
    rc, out = _run_cli(str(tmp_path / "nope.json"), "--started-at", "2026-10-29T02:00:00")
    assert rc == 3, out


# ---------------------------------------------------------------- 判据 5（脚本级）


def test_run_gate_verifies_and_deletes_stale_product() -> None:
    """5/5 必须调核验、失败必须 `rm` 掉产物并 `exit 9` —— 删掉这段而不改测试是不行的。"""
    script = (ROOT / "scripts" / "cloud" / "run_gate.sh").read_text(encoding="utf-8")
    assert "check-product-fresh" in script
    assert "--started-at \"$started_at\"" in script
    assert "--seed \"$seed_dir/last.json\"" in script
    # 顺序：先核验，失败才删 —— 反过来就永远删不到东西
    idx_check = script.index("check-product-fresh")
    idx_rm = script.index('rm -f ".wt/$card/gates/last.json"')
    idx_exit = script.index("exit 9", idx_rm)
    assert idx_check < idx_rm < idx_exit
    # 起跑时刻必须记在**真正跑门禁之前**（记晚了就永远「at 早于起跑」⇒ 每趟都误杀）
    assert script.index("started_at=$(date -Iseconds)") < script.index("scripts/run_gates.py &&")


@pytest.mark.parametrize("marker", ["check-product-fresh", "--seed \"$seed_dir/last.json\""])
def test_script_keeps_seed_flag(marker: str) -> None:
    """播种源必须一直传进去 —— 只靠 `at` 比较挡不住「时钟回拨 / 同秒重写」。"""
    script = (ROOT / "scripts" / "cloud" / "run_gate.sh").read_text(encoding="utf-8")
    assert marker in script
