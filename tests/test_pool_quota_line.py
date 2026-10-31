r"""卡 A358（T-AG571）：一行说完「现在能不能派」—— magpie `statusline` 的 16 条钉子 + 2 条护栏。

为什么值当测：这条线的全部价值在三个**反直觉**的选择上，每一个写错都不会报错，只会「悄悄多说
一个字」或「悄悄少一行」：

* **问不到就打空行**（`statusline_cli.go:67` `return ""`）。写成 `"?"` 会多说了「有一个不知道的
  额度」，写成 `"（无）"` 更糟 —— 那是把「没料」当成一个读数报出去。
* **星号只给最新那条、紧贴名字**（`:149` `name += "*"`）。
* **`>= 1 小时` 不带秒**（`:151` 五对替换）—— 一行里 `1h40m24s` 的 `24s` 是纯噪音。

★ 与本卡判据的对应（15 条判据 → 钉子，见 `复盘/卡/卡A358-一行说完能不能派.md`）：
  ①判据 1 ②判据 2 ③判据 3 ④判据 4 ⑤判据 5 ⑥判据 6 ⑦判据 7 ⑧判据 8 ⑨判据 9
  ⑩⑪判据 10/11 ⑫判据 12 ⑬判据 13 ⑭判据 14 ⑮判据 15 ⑯接入点 2
  另加两条（卡规格「至少 18 条」）：`MAX_ONLY` 护栏与四态短标记逐字。

★ 导入口径：一律走包路径（`from tools.pool import quota_line`），不往 `sys.path` 里塞东
西、不写「闭嘴」类注释（本仓规矩）。
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from tools import pool_quota
from tools.pool import quota_line as ql

#: 固定「现在」—— 一行版不读钟，这个值只是为证明它**不被读**（判据 15）。
NOW = "2026-10-31T12:00:00+08:00"

#: 一天之内 / 跨两天，用来咬「只留最晚那一天」。
DAY_OLD = "2026-10-30T09:00:00+08:00"
DAY_NEW = "2026-10-31T09:00:00+08:00"


def _st(card: str, model: str, state: str, *,
        recorded_at: str | None = DAY_NEW, remaining: int | None = None) -> dict[str, Any]:
    """造一条「`status()` 产出形状」的读数（真的走 `status()` 也能得，但这三条钉子只要形状）。"""
    return {
        "card": card, "model": model, "state": state,
        "recorded_at": recorded_at,
        "reset_at": None, "now": NOW,
        "remaining_seconds": remaining, "expired_seconds": None,
        "can_dispatch": False, "need_probe": True,
        "rest_until": None, "rest_by": None, "why": "夹具",
    }


# ================================================================ ① 问不到就打空行


def test_one_line_of_nothing_is_the_empty_string() -> None:
    """判据 1：`one_line([])` 是 `""` —— **不是** `"?"`、**不是** `"（无）"`。

    `""` = 这行不说话；`"?"` = 多说了「有一个不知道的额度」（照 `statusline_cli.go:67`）。
    """
    assert ql.one_line([]) == ""
    assert ql.one_line([], now=NOW) == ""
    assert ql.one_line([], only=("A318",)) == "", "点名要看的也没有 ⇒ 一样不说话"
    assert ql.NO_DATA == ""


def test_all_unrecorded_states_print_nothing() -> None:
    """判据 2：全是 `未记录`、`only` 为空 ⇒ 空串（`未记录` 在 `pick()` 里就被丢掉）。

    ★ 与判据 1 咬的是同一个 `if not picked: return ""`，但**不是**同义反复：只要 `pick()` 忘了
    过滤 `未记录`，这一条会红、判据 1 那条仍绿 —— 缺这一条就测不出「过滤」这层。
    """
    states = [_st("A318", f"m{i}", "未记录") for i in range(3)]
    assert ql.one_line(states, now=NOW) == ""
    assert ql.one_line(states, only=("A318",), now=NOW) == ""


# ================================================================ ② 谁能占一格


def test_pick_drops_unrecorded_and_undated_rows() -> None:
    """判据 3：四态各一条，掉两条（`未记录` 一条 + 无 `recorded_at` 一条），其余全留。"""
    states = [
        _st("A318", "m1", "限流中", remaining=600),
        _st("A318", "m2", "已过期，需重新探测", recorded_at=None),
        _st("A319", "m3", "余额耗尽"),
        _st("A320", "m4", "未记录"),
    ]
    kept = ql.pick(states)
    assert [(s["card"], s["model"]) for s in kept] == [("A318", "m1"), ("A319", "m3")]


def test_pick_with_only_keeps_every_match() -> None:
    """判据 4：`only` 非空 ⇒ 只按 `matches()` 过滤，**「最近那批优先」不生效**。

    ★ 夹具里必须有「同一天里有一条更晚」——否则与判据 5 的结果一样，这条钉子就是瞎的。
    """
    states = [
        _st("A318", "m1", "限流中", recorded_at=DAY_OLD, remaining=60),
        _st("A318", "m2", "余额耗尽", recorded_at=DAY_NEW),
        _st("A319", "m3", "余额耗尽", recorded_at=DAY_OLD),
    ]
    kept = ql.pick(states, only=("A318",))
    assert [(s["card"], s["model"]) for s in kept] == [("A318", "m1"), ("A318", "m2")], \
        "点名要看的，不许被「只留最晚那天」裁掉"


def test_pick_prefers_the_freshest_day() -> None:
    """判据 5：`only` 为空且跨了两天 ⇒ 只留 `recorded_at` 最晚那一天的那批。"""
    states = [
        _st("A318", "m1", "余额耗尽", recorded_at=DAY_OLD),
        _st("A319", "m2", "余额耗尽", recorded_at=DAY_NEW),
        _st("A320", "m3", "限流中", recorded_at=DAY_NEW, remaining=30),
        _st("A321", "m4", "余额耗尽", recorded_at="2026-10-29T23:59:59+08:00"),
    ]
    kept = ql.pick(states)
    assert [(s["card"], s["model"]) for s in kept] == [("A319", "m2"), ("A320", "m3")]


def test_matches_three_strings_case_insensitively() -> None:
    """判据 6：比且只比 `card` / `model` / `card/model` 三串；空串不参与；大小写不敏感。"""
    st = _st("A318", "kimi-k3-1", "余额耗尽")
    assert ql.matches(st, ["A318"]) is True
    assert ql.matches(st, ["a318"]) is True, "大小写不敏感"
    assert ql.matches(st, ["KIMI-K3-1"]) is True
    assert ql.matches(st, ["A318/KIMI-K3-1"]) is True, "整串命中"
    assert ql.matches(st, ["", "A318"]) is True, "空串不参与，但不许把别的命中一起吞掉"
    assert ql.matches(st, [""]) is False, "空串不参与 ⇒ 不命中"
    assert ql.matches(st, ["kimi"]) is False, "只比三个整串，不做子串匹配"
    assert ql.matches(st, []) is False


def test_freshest_is_the_latest_recorded_and_empty_when_undated() -> None:
    """判据 7：`recorded_at` 字典序最大那条的 `card/model`；全 `None` ⇒ `""`；并列取第一条。"""
    assert ql.freshest([
        _st("A318", "m1", "余额耗尽", recorded_at=DAY_OLD),
        _st("A319", "m2", "余额耗尽", recorded_at=DAY_NEW),
    ]) == "A319/m2"
    assert ql.freshest([]) == ""
    assert ql.freshest([_st("A318", "m1", "余额耗尽", recorded_at=None)]) == ""
    assert ql.freshest([
        _st("A318", "m1", "余额耗尽", recorded_at=DAY_NEW),
        _st("A319", "m2", "余额耗尽", recorded_at=DAY_NEW),
    ]) == "A318/m1", "并列取第一条（max 的稳定性）"


# ================================================================ ③ 星号 / 一格 / 短码


def test_star_sits_on_the_freshest_without_a_space() -> None:
    """判据 8：`*` 只在 freshest 那条上，位置是**名字末尾、前面不加空格**。

    ★ 两颗断言成对才是一颗真牙：只断言 `"A318*" in line` 是瞎的（星号前多一个空格时它也绿，
    因为那一串仍在），必须同时断言带空格的那种**不在**。
    """
    line = ql.one_line([
        _st("A318", "kimi-k3-1", "余额耗尽", recorded_at=DAY_OLD),
        _st("A319", "glm-5.3", "余额耗尽", recorded_at=DAY_NEW),
    ], now=NOW)
    assert "A319/glm-5.3*" in line
    assert "A319/glm-5.3 *" not in line
    assert "A318/kimi-k3-1*" not in line, "星号只给最新那条"


def test_cell_is_card_slash_model_then_the_short_state() -> None:
    """判据 9：一格 = `card/model` +（`*`）+ `CELL_SEP` + `short_state`。

    `限流中` 的短码是 `short_hms(remaining_seconds)` = `1h40m` —— **不是** `_hms` 的 `01:40:24`
    （那两套格式各有各的家：`_hms` 给多行 `render()`，`short_hms` 给这一行）。
    """
    line = ql.one_line([_st("A318", "kimi-k3-1", "限流中", remaining=6024)], now=NOW)
    assert line == "A318/kimi-k3-1* 1h40m"
    assert "01:40:24" not in line, "`_hms` 的格式不许漏进这一行"
    assert ql.one_line([_st("A318", "m1", "已过期，需重新探测")], now=NOW) == "A318/m1* 过期"
    assert ql.one_line([_st("A318", "m1", "余额耗尽")], now=NOW) == "A318/m1* 耗尽"


def test_short_hms_takes_seconds_off_above_an_hour() -> None:
    """判据 10 + 11：`>= 3600` 不带秒，且**边界 3600 也算**（`6024 → "1h40m"`）。

    ★ 只测 `6024` 与 `59` 抓不到「`>=` 写成 `>`」—— 夹具里必须有 `3600` 这个边界值。
    """
    assert ql.short_hms(6024) == "1h40m"
    assert "24s" not in ql.short_hms(6024), "一小时以上不许带秒（这是「一行」的硬约束）"
    assert ql.short_hms(3600) == "1h0m", "边界上也要走「小时」那条分支"
    assert ql.short_hms(3599) == "59m59s", "差一秒就还是分钟档"
    assert ql.short_hms(59) == "0m59s"
    assert ql.short_hms(0) == "0m0s"
    assert ql.HOUR_MIN == 3600
    assert ql.MINUTE_S == 60


def test_short_hms_treats_none_and_negative_alike() -> None:
    """判据 10 后半：`None` 与负数都是 `"?"`（负数当没有，不许算成 `-1m-1s`）。"""
    assert ql.short_hms(None) == "?"
    assert ql.short_hms(-1) == "?"
    assert ql.short_hms(-3600) == "?"
    assert ql.UNKNOWN_HMS == "?"


# ================================================================ ④ 一行只有两种分隔符


def test_one_line_uses_only_the_two_separators() -> None:
    """判据 12：段间只用 `SEP`、格间只用 `CELL_SEP`；返回串里没有换行、没有两个连续空格。

    ★ 夹具必须**至少两段、每段两格**，否则「段与格混成一种分隔」这个错看不出来。
    """
    states = [
        _st("A318", "m1", "限流中", remaining=600),
        _st("A318", "m2", "余额耗尽"),
        _st("A319", "m3", "已过期，需重新探测"),
        _st("A320", "m4", "余额耗尽"),
    ]
    line = ql.one_line(states, now=NOW)
    assert line.count(ql.SEP) == 3, "四段 ⇒ 三个段分隔符，一个不多一个不少"
    assert "\n" not in line
    assert "  " not in line, "两个连续空格 = 段与格混了"
    assert ql.SEP == " | "
    assert ql.CELL_SEP == " "
    assert line == "A318/m1* 10m0s | A318/m2 耗尽 | A319/m3 过期 | A320/m4 耗尽", \
        "四段同一天 ⇒ 四段都在；星号在第一条（并列取第一条）"


def test_one_line_keeps_the_input_order() -> None:
    """判据 13：输入顺序即输出顺序 —— 故意**倒序**传入，断言输出同序（不排序、不聚合）。"""
    states = [
        _st("A320", "m4", "余额耗尽", recorded_at=DAY_NEW),
        _st("A319", "m3", "余额耗尽", recorded_at=DAY_NEW),
        _st("A318", "m1", "余额耗尽", recorded_at=DAY_NEW),
    ]
    line = ql.one_line(states, now=NOW)
    assert line.index("A320/") < line.index("A319/") < line.index("A318/")
    assert line == "A320/m4* 耗尽 | A319/m3 耗尽 | A318/m1 耗尽"


def test_unknown_state_raises_instead_of_inventing_words() -> None:
    """判据 14：不认识的 `state` 抛 `KeyError` —— 不编话兜底。

    照 `tools/pool/holds.py:142-144` `why_text` 的口径：「只认那一小撮原串，别的直接 KeyError」。
    """
    with pytest.raises(KeyError):
        ql.one_line([_st("A318", "m1", "限流")], now=NOW)  # 账本的 `kind`，不是 `status()` 的态
    with pytest.raises(KeyError):
        ql.short_state(_st("A318", "m1", "其他"))


# ================================================================ ⑤ 零 IO + 接入点


def test_quota_line_imports_no_io_and_no_network() -> None:
    """判据 15：模块源码里没有任何 IO / 网络 import（`ast` 扫 import，**不扫注释**）。

    ★ 扫 AST 而不是扫字符串：docstring 里写着「零网络」不会误红，而真 import 一句一定红。
    """
    source = Path(ql.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    banned = {
        "socket", "urllib", "http", "http.client", "urllib.request",
        "pool_accounts", "tools.pool_accounts",
        "lastgood", "tools.pool.lastgood",
        "subprocess", "pathlib", "os", "shutil", "io",
    }
    seen: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            seen.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            seen.append(node.module)
    hit = sorted(name for name in seen if name in banned)
    assert hit == [], f"本模块必须零 IO / 零网络，扫到：{hit}"


def test_line_cli_prints_an_empty_line_when_there_is_nothing(capsys: pytest.CaptureFixture[str],
                                                             tmp_path: Path) -> None:
    """接入点 2：`print(...)` 打的是**一个换行**（`print("")`），不是什么都不打。

    照 `statusline_cli.go:38` 的用法串末句：`prints nothing when the gateway isn't running` ——
    而 `fmt.Println("")` 确实是**打一个空行**。
    """
    rc = pool_quota.main(["line", "--now", NOW, "--root", str(tmp_path)])
    assert rc == pool_quota.EXIT_OK
    assert capsys.readouterr().out == "\n"


# ================================================================ ⑥ 两条护栏


def test_short_state_maps_the_four_states_verbatim() -> None:
    """`SHORT` 四个字面量与 `status()` 的四态**逐字**对上（`"限流中"` 不是 `"限流"`）。"""
    assert set(ql.SHORT) == {"限流中", "已过期，需重新探测", "余额耗尽", "未记录"}
    assert ql.SHORT["已过期，需重新探测"] == "过期"
    assert ql.SHORT["余额耗尽"] == "耗尽"
    assert ql.SHORT["未记录"] == "未记录"
    assert ql.SHORT["限流中"] == "", "限流中的短码是算出来的倒计时，不是字面量"


def test_only_above_max_is_refused() -> None:
    """`MAX_ONLY = 32` 是 pool **新加**的护栏（★ **没有 magpie 出处**）：超了直接 `ValueError`。

    理由：magpie 的 `only` 由人打在命令行上、无上限；将来若被脚本调用，无上限的 `only` 会变成
    一次 O(n·m) 扫描。护栏失效不会报错，只会悄悄变慢 ⇒ 必须有一颗钉子。
    """
    assert ql.MAX_ONLY == 32
    states = [_st("A318", f"m{i}", "余额耗尽") for i in range(3)]
    assert ql.pick(states, only=[f"A318/m{i}" for i in range(ql.MAX_ONLY)]) != []
    with pytest.raises(ValueError):
        ql.pick(states, only=[f"x{i}" for i in range(ql.MAX_ONLY + 1)])
