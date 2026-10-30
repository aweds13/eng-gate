"""卡 A343 / T-AG545：中午之前的「已经签过了」不算数（magpie F29 复查窗口移植进 pool）。

钉子表（照卡规格 §钉子表；★ 是反向验证专钉）：

  ① ``test_provisional_before_noon_counts_nothing``
     上午那句「已签过」不算数 ⇒ ``provisional() is True``。
  ② ``test_provisional_after_noon_is_trusted``
     同一条，过了中午就当真 ⇒ ``False``。
  ③ ``test_provisional_cross_day_is_not_today``
     「昨天 22:00 说的」不是今天 ⇒ ``False``（跨天归 ``due_for_recheck`` 的「跨天了」管）。
  ④ ``test_claimed_is_never_provisional``
     ``CLAIMED`` 是真签到，任何时候都不是 provisional；``INACTIVE`` 同样是「说签过了」。
  ⑤ ``test_due_recheck_never_asked``
     从没问过 ⇒ ``(True, "从没问过")``。
  ⑥ ``test_due_recheck_same_day_settled``
     当天已定案（``CLAIMED``）⇒ ``(False, "当日已定案")``。
  ⑦ ``test_retry_after_backs_off_offline``
     离线按次数退避 60/120/240/480/960/1800；在线恒 1800。
  ⑧ ★ ``test_reverse_provisional_without_the_noon_line``
     ``CHECKIN_SURE_HOUR`` 12→0 时，零点那半分钟的重签必须从 True 翻成 False ——
     这条钉是「中午那条线不是摆设」的反证；开头 ``monkeypatch.delenv`` 自清，
     证明没有任何环境变量能把它调走（判据不许配置）。

另加两条（卡规格 8 条之外，本卡自己补的，只加不减）：
  ⑨ ``test_recheck_rows_tolerates_ledger_shapes`` —— 账本的历史形状读得懂，
     认不出时**朝复查的方向** fail-open（本卡唯一允许的 fail-open）。
  ⑩ ``test_due_cli_never_writes`` —— ``due`` 是只读子命令：不签到、不改账本、不写留档。

★ 导入口径：一律走包路径（``from tools import pool_accounts`` / ``from tools.pool import
  checkin``），不往 ``sys.path`` 里塞 ``tools/`` —— 塞了就得给 ``noqa: E402``，本仓不许 ``noqa``。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from tools import pool_accounts as pa
from tools.pool import checkin as ck

ROOT = Path(__file__).resolve().parent.parent

TZ = pa.TZ

#: 固定「今天」。测试不许靠真实钟表（照 `tests/test_quota_clock.py` 的口径）。
TODAY = datetime(2026, 10, 26, tzinfo=TZ)


def at(hour: int, minute: int = 0, *, day_offset: int = 0) -> datetime:
    """今天的某个时刻（可跨天）。"""
    return (TODAY + timedelta(days=day_offset)).replace(hour=hour, minute=minute)


LEDGER = """
[[account]]
id = "qoder-1"
label = "Qoder 活动号"
platform = "qoder"
state = "active"
added_at = "2026-10-01"
approved_models = []

[account.credential]
kind = "file"
locator = "~/.qoder/token"

[account.health]
state = "ok"
last_checkin = "already-claimed"
last_probe = "2026-10-26T10:00:00+08:00"

[[account]]
id = "codearts-1"
label = "备用号 codearts"
platform = "codearts"
state = "active"
added_at = "2026-09-30"
approved_models = []

[account.credential]
kind = "file"
locator = "~/.codeartsdoer/pool.env"

[account.health]
state = "ok"
last_checkin = "claimed"
last_probe = "2026-10-26T10:00:00+08:00"

[[account]]
id = "shop-1"
label = "商城里领过一次的老号"
platform = "opencode"
state = "active"
added_at = "2026-09-01"
approved_models = []

[account.credential]
kind = "file"
locator = "~/opencode/token"

[account.health]
state = "unknown"
last_checkin = "2026-10-25T18:30:00+08:00"

[[account]]
id = "fresh-1"
label = "从没问过的号"
platform = "trae"
state = "active"
added_at = "2026-10-25"
approved_models = []

[account.credential]
kind = "file"
locator = "~/.trae/token"

[account.health]
state = "unknown"

[[account]]
id = "broken-1"
label = "时间戳坏了的老号"
platform = "minimax"
state = "active"
added_at = "2026-08-01"
approved_models = []

[account.credential]
kind = "file"
locator = "~/minimax/token"

[account.health]
state = "unknown"
last_checkin = "半截-时间戳"
"""


@pytest.fixture()
def ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把账本钉到 tmp：`find_ledger()` 从**仓库根**向上找锚点（卡 E49），所以两处都钉。

    开头 `delenv` 自清：本机若继承了 `TF_ACCOUNTS_TOML` 之类的值，会把夹具指到别处
    ⇒ 钉子变成假钉子。
    """
    monkeypatch.delenv("TF_ACCOUNTS_TOML", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(pa, "TOOL_ROOT", tmp_path)
    monkeypatch.setattr(pa, "DATA_ROOT", tmp_path)
    # 能力表用仓里那份真表（判据要按真 `claim_flow` 判「平台不支持签到」）。
    monkeypatch.setattr(pa, "_platforms_path", lambda: ROOT / "tools" / "pool" / "platforms.toml")
    path = tmp_path / "infra" / "pool" / "accounts.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(LEDGER, encoding="utf-8", newline="\n")
    return path


def platforms_table() -> dict:
    return pa.load_platforms()


# ---------------------------------------------------------------- ① ~ ④ provisional


def test_provisional_before_noon_counts_nothing() -> None:
    """① 上午 10:00 那句「已签过」，11:00 看仍不算数（现在还没到中午）。"""
    outcome = ck.Outcome(ck.ALREADY_CLAIMED)
    assert ck.provisional(outcome, at=at(10), now=at(11), timezone=TZ) is True


def test_provisional_after_noon_is_trusted() -> None:
    """② 同一条，13:00 再看就当真了：中午之后它说的就是今天。"""
    outcome = ck.Outcome(ck.ALREADY_CLAIMED)
    assert ck.provisional(outcome, at=at(10), now=at(13), timezone=TZ) is False


def test_provisional_cross_day_is_not_today() -> None:
    """③ 昨天 22:00 说的「已签过」，今天 09:00 看：不是今天的事，不归 provisional 判。"""
    outcome = ck.Outcome(ck.ALREADY_CLAIMED)
    assert ck.provisional(outcome, at=at(22, day_offset=-1), now=at(9), timezone=TZ) is False


def test_claimed_is_never_provisional() -> None:
    """④ `CLAIMED` 是真签到 ⇒ 任何时候都不算 provisional；`INACTIVE` 也在「说已签过」那一类。"""
    assert ck.provisional(ck.Outcome(ck.CLAIMED), at=at(10), now=at(11), timezone=TZ) is False
    assert ck.provisional(ck.Outcome(ck.INACTIVE), at=at(10), now=at(11), timezone=TZ) is True


# ---------------------------------------------------------------- ⑤ ~ ⑦ due_for_recheck


def test_due_recheck_never_asked() -> None:
    """⑤ 从没问过 ⇒ 该问，理由就是「从没问过」。"""
    got = ck.due_for_recheck(None, at=None, now=at(11), timezone=TZ, platform="codearts")
    assert got == (True, "从没问过")


def test_due_recheck_same_day_settled() -> None:
    """⑥ 当天真签过（`CLAIMED`，10:00），11:00 看 ⇒ 已定案，不再问。"""
    got = ck.due_for_recheck(
        ck.Outcome(ck.CLAIMED), at=at(10), now=at(11), timezone=TZ, platform="codearts"
    )
    assert got == (False, "当日已定案")


def test_retry_after_backs_off_offline() -> None:
    """⑦ 离线按次数退避（1/2/4/8/16 分钟，第 5 次起封顶 30 分钟）；在线恒 30 分钟。"""
    assert [ck.retry_after_s(offline=True, tries=n) for n in range(6)] == [
        60,
        120,
        240,
        480,
        960,
        1800,
    ]
    assert [ck.retry_after_s(offline=False, tries=n) for n in (0, 1, 5, 99)] == [1800] * 4


# ---------------------------------------------------------------- ⑧ 反向钉子


def test_reverse_provisional_without_the_noon_line(monkeypatch: pytest.MonkeyPatch) -> None:
    """⑧ ★ 把中午那条线拿掉，零点那半分钟的重签必须当场失效。

    场景取事故读数最狠的那半分钟：`ALREADY_CLAIMED @ 今天 00:30`、`now = 今天 00:31`。
    12 点时它是 True（今天还没签、天也没跨）；`CHECKIN_SURE_HOUR` 改成 0 之后，
    `now.hour < 0` 永不成立 ⇒ 必须翻成 False。翻不动 ⇒ 这条判据没有牙。

    开头 `delenv` 自清并顺手反证：`CHECKIN_SURE_HOUR` 不许可配置 —— 环境里那几个名字
    全删掉，判据一个字节都不该变。
    """
    for name in ("CHECKIN_SURE_HOUR", "POOL_CHECKIN_SURE_HOUR", "TF_CHECKIN_SURE_HOUR"):
        monkeypatch.delenv(name, raising=False)
    assert ck.CHECKIN_SURE_HOUR == 12

    outcome = ck.Outcome(ck.ALREADY_CLAIMED)
    scene = {"at": at(0, 30), "now": at(0, 31), "timezone": TZ}
    assert ck.provisional(outcome, **scene) is True

    monkeypatch.setattr(ck, "CHECKIN_SURE_HOUR", 0)
    assert ck.provisional(outcome, **scene) is False


# ---------------------------------------------------------------- ⑨ ~ ⑩ 本卡自补


def test_recheck_rows_tolerates_ledger_shapes(ledger: Path) -> None:
    """⑨ 账本的历史形状都要读得懂，且认不出时朝「去复查」的方向 fail-open。"""
    platforms = platforms_table()
    data = pa.load_ledger(ledger, platforms)
    rows = pa.recheck_rows(data, platforms, now=at(11, 30))

    # 稳定排序 (platform, id)；结果集就是该复查的那几条，理由逐条原样。
    assert [(row["platform"], row["id"]) for row in rows] == [
        ("minimax", "broken-1"),
        ("opencode", "shop-1"),
        ("qoder", "qoder-1"),
        ("trae", "fresh-1"),
    ]
    assert [(row["id"], row["why"], row["provisional"]) for row in rows] == [
        # 时间戳认不出 ⇒ 当「从没问过」（唯一 fail-open，方向是去复查）
        ("broken-1", "从没问过", False),
        # 老账本里的 ISO 时刻 ⇒ 跨天了
        ("shop-1", "跨天了", False),
        # 上午的「已签过」⇒ 本卡的主角
        ("qoder-1", "上午的「已签过」不可信，复查窗口到了", True),
        # 压根没问过
        ("fresh-1", "从没问过", False),
    ]
    # 当天真签过的（codearts-1）不在里面。
    assert "codearts-1" not in [row["id"] for row in rows]

    # `--platform` 过滤只留那一个平台。
    only = pa.recheck_rows(data, platforms, now=at(11, 30), platform="qoder")
    assert [row["id"] for row in only] == ["qoder-1"]


def test_due_cli_never_writes(
    ledger: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """⑩ `due` 只读：跑完账本一个字节不变、不留签到留档，退出码 0。"""
    before = ledger.read_bytes()
    code = pa.main(["--ledger", str(ledger), "due", "--json", "--now", "2026-10-26T11:30:00+08:00"])
    payload = json.loads(capsys.readouterr().out)

    assert code == pa.EXIT_OK
    assert [row["id"] for row in payload["results"]] == [
        "broken-1",
        "shop-1",
        "qoder-1",
        "fresh-1",
    ]
    assert payload["results"][2]["provisional"] is True
    assert ledger.read_bytes() == before
    # 签到留档一份都不许落地（`DATA_ROOT` 在夹具里钉到 tmp）。
    assert not (pa.DATA_ROOT / "gates" / "diag").exists()

    # 认不出 --now ⇒ 用法错（2），绝不用 EXIT_NEEDS_HUMAN。
    assert pa.main(["--ledger", str(ledger), "due", "--now", "明天"]) == pa.EXIT_USAGE
