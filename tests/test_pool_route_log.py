r"""路由回放（`tools/pool/route_log.py`，卡 A363 · T-F39）的测试。

## 为什么值当测

「谁被试过、谁真答了」在 pool 从前**只落在人话里**（`trae_dispatch._verdict_text` 的七段
判决正文 + `jobs.scan_jobs` 的 `why`）。想回答「这一轮按什么顺序试过哪几个模型、最后是谁
答的」，只能人肉翻 `gates/diag/wb-usage.jsonl` 的「模型 / 轮次」两列再脑补顺序 ——
而 `wb_dispatch` 的 429 三拍**真的会换模型**，真实尝试顺序是一条只有它自己知道的信息。

magpie 的解法（`internal/gateway/trace.go` 包注释）不是事后读日志重算，而是**在做决定的
地方、用做决定时的那几个值**记一条，事后不重算。这十条钉子钉的就是「不许退回到重算」。

最后一条（`test_row_shape_is_exactly_eight_keys`）是**卡 A382 / F48** 追加的：行形状是**闭集**，
会话维度不在里面 —— 那是**决定**（没有一个可信的会话来源之前加这个键，就是逼下游拿空串当真值），
不是欠账。

| 钉子 | 钉哪一位 |
|---|---|
| `test_one_line_per_round` | 一次派活**恰好一条**（不是零、不是两条） |
| `test_no_prompt_no_secret` | 正文里的哨兵串**进不去**记录 |
| `test_tries_follow_real_order` | `tried` 是真实顺序，不是白名单顺序 |
| `test_served_is_the_winner` | 全挂 ⇒ `served` 空 且 `status` 是终态 |
| `test_recorded_where_decided` | ★ 喂一个与 usage 账**矛盾**的 `tried`，记录跟着传进来的走 |
| `test_read_is_idempotent` | 读两次结构相等，且一个字节都不写（`mtime` 不变） |
| `test_missing_file_is_empty_not_error` | 文件不在 ⇒ `([], 0)`，不是错误 |
| `test_broken_line_is_reported` | 坏行跳过但**如实计数**，不许静默当空 |
| `test_status_vocabulary_closed` | `status` 四个值的闭集，第五个必须抛 |
| `test_row_shape_is_exactly_eight_keys` | 行形状恰好八键，且**没有**会话维度（F48 / 卡 A382） |

★ 一律用 `--root` / `root=` 指临时目录 —— **不往真的 `gates/diag/` 里写**。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from pool import jobs, registry, route_log, trae_dispatch  # noqa: E402 —— tools/ 已在 sys.path 上

CARD = "A363"
M1, M2, M3 = "model-one", "model-two", "model-three"
#: 判据 2 的哨兵串：把它写进 spec / 回答正文，然后断言它**没进**路由账。
SECRET = "<SECRET-2f9a>"


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """登记文件指到临时目录；门禁锁一律当"空着"；根 = 临时根。返回那个根。"""
    monkeypatch.setenv("TF_POOL_REGISTRY", str(tmp_path / "reg.json"))
    monkeypatch.setattr(registry, "read_lock_body", lambda *a, **k: "")
    monkeypatch.setenv("TF_WINDOW_ID", "test-window")
    return tmp_path / "root"


def _log(root: Path) -> Path:
    return route_log.route_path(root)


def _raw_lines(root: Path) -> list[str]:
    return [ln for ln in _log(root).read_text(encoding="utf-8").splitlines() if ln.strip()]


def _dispatch(env: Path, *, tried: list[dict], served: str, asked: str = M1,
              exit_code: int = 0, answer: str = "PORT") -> Path:
    """走一遍真实的 Trae 道：start 占树 → 正文里带哨兵的回答 → finish 收工。"""
    trae_dispatch.start(card=CARD, tree=".wt/A363", files=["tools/pool/route_log.py"],
                        task="T-F39", pool="trae", model=asked, root=env)
    out = env / "answer.md"
    out.write_text(answer, encoding="utf-8")
    code, text = trae_dispatch.finish(card=CARD, log=None, exit_code=exit_code, root=env,
                                      answer_file=out, asked=asked, tried=tried,
                                      served=served, release=True)
    assert code == 0, text
    return _log(env)


# ================================================================ ① 一行一轮


def test_one_line_per_round(env: Path) -> None:
    """一次派活**恰好一条**结构化记录（不是零、不是两条）。

    ★ 这里必须让 `tried` **非空**：`trae_dispatch.finish` 的口径是「`tried` 空 ⇒ 不落
      记录」（空意思是"没有可记的尝试顺序"，见 `route_log` 的 docstring）。拿空 `tried`
      跑这条，断言 `len(...) == 1` 永远失败、断言 `== 0` 则是**假牙**（`[] == []` 恒真）。
    """
    path = _dispatch(env, tried=[{"model": M1, "fail": ""}], served=M1)

    rows, bad = route_log.read_routes(CARD, root=env)

    assert bad == 0, "好记录不该被算坏行"
    assert len(rows) == 1, f"一次派活该恰好一条，实际 {len(rows)} 条：{rows}"
    assert len(_raw_lines(env)) == 1, "落盘的文件本身也只有一行（不许一次写两行）"
    assert path == _log(env)
    assert rows[0]["card"] == CARD and rows[0]["attempt"] == 1
    assert rows[0]["tried"] == [{"model": M1, "fail": ""}]


# ================================================================ ② 不含正文与凭据


def test_no_prompt_no_secret(env: Path) -> None:
    """记录里**没有** prompt / 回答正文 / 凭据：正文里有的哨兵串，落盘的 JSON 里没有。

    ★ 断言的是**落盘的字节**（`_raw_lines` 的原文），不是内存里那个 dict ——
      只有这样才抓得住"写的时候顺手把 spec 也带上"。
    """
    spec = env / "spec.md"
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text(f"# 卡规格\n\n口令是 {SECRET}，别外传。\n", encoding="utf-8")
    path = _dispatch(env, tried=[{"model": M1, "fail": "超时"}], served=M1,
                     answer=f"答完了。{SECRET} 也在这份回答里。")

    raw = "\n".join(_raw_lines(env))
    assert SECRET not in raw, f"哨兵串漏进了账：{raw}"
    assert SECRET not in path.read_text(encoding="utf-8")
    # 反向自证：哨兵串真的到过这场派活（否则上面两句是空的）
    assert SECRET in (env / "answer.md").read_text(encoding="utf-8")
    assert SECRET in spec.read_text(encoding="utf-8")


# ================================================================ ③ 真实顺序


def test_tries_follow_real_order(env: Path) -> None:
    """`tried` 是**真实尝试顺序**：第 2 个失败、第 3 个成功 ⇒ 三条按那个次序，第 2 条带原因。

    ★ 传进来的次序是 `m3, m1, m2`（**故意不是白名单顺序**）—— 若实现按白名单重排，
      这条会红。真实顺序是「做决定的人」知道的，本模块不许替它排序。
    """
    tried = [{"model": M3, "fail": ""},
             {"model": M1, "fail": "429 限流（第 1 拍）"},
             {"model": M2, "fail": "面板超时"}]
    _dispatch(env, tried=tried, served=M3)

    rows, bad = route_log.read_routes(CARD, root=env)

    assert bad == 0
    assert [row["model"] for row in rows[0]["tried"]] == [M3, M1, M2], "次序被动了"
    assert rows[0]["tried"][1]["fail"] == "429 限流（第 1 拍）"
    assert rows[0]["served"] == M3
    assert rows[0]["status"] == route_log.STATUS_SERVED


# ================================================================ ④ served 说的是真答的


def test_served_is_the_winner(env: Path) -> None:
    """全挂 ⇒ `served` 是空串，且 `status` 是终态 `all_failed`（不是"成功"、不是空）。"""
    _dispatch(env, tried=[{"model": M1, "fail": "429"},
                          {"model": M2, "fail": "429（第 2 拍）"}],
              served="", exit_code=1)

    rows, _bad = route_log.read_routes(CARD, root=env)

    assert rows[0]["served"] == "", "全挂却报了赢家 —— 那是编数"
    assert rows[0]["status"] == route_log.STATUS_ALL_FAILED
    assert rows[0]["status"] in route_log.STATUSES


# ================================================================ ⑤ ★ 记录发生在做决定的地方


def test_recorded_where_decided(env: Path) -> None:
    """★ 本卡唯一需要「构造出重算必然算不出」的钉子。

    场景：`gates/diag/wb-usage.jsonl` 里这一轮**只记了 `m1`**（它是每轮一行 —— 同一轮里
    `m1` 挂了换 `m2` 这件事，它记不出来），而做决定的那个人**试过 `m1` 和 `m2`**。
    ⇒ 记录里的 `tried` 必须是 `[m1, m2]`。若实现是「事后读 usage 重算」，它只会得到
      `[m1]`，这条就红。

    ★ 光断言「值变了」不够：必须让**重算的结果与传进来的不同**，并且断言的是那个
      **只有传进来的值才对**的形状。
    """
    diag = jobs.diag_dir(env)
    diag.mkdir(parents=True, exist_ok=True)
    # 这一份账说"只试了 m1" —— 与下面传进来的 tried 互相矛盾（这是构造，不是 bug）
    (diag / "wb-usage.jsonl").write_text(
        json.dumps({"卡": CARD, "模型": M1, "轮次": 1, "退出码": 1, "判决": "限流"},
                   ensure_ascii=False) + "\n",
        encoding="utf-8")

    tried = [{"model": M1, "fail": "429 限流（第 1 拍）"},
             {"model": M2, "fail": ""}]
    _dispatch(env, tried=tried, served=M2)

    rows, _bad = route_log.read_routes(CARD, root=env)
    recorded = [row["model"] for row in rows[0]["tried"]]
    recomputed = [json.loads(ln)["模型"] for ln in
                  (diag / "wb-usage.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]

    assert recomputed == [M1], "构造失败：usage 账得只记 m1（否则重算也能对上，这条就没有咬合面）"
    assert recorded == [M1, M2], f"记录跟着 usage 重算了（得到 {recorded}）—— 那是事后重算"
    assert recorded != recomputed, "重算得出的值与记录相同 ⇒ 这条钉子没有咬合面"
    assert rows[0]["served"] == M2


# ================================================================ ⑥ 只读且幂等


def test_read_is_idempotent(env: Path) -> None:
    """同一份文件读两次，结构完全相等；且**读不写盘**（`mtime` 与字节数都不许变）。"""
    _dispatch(env, tried=[{"model": M1, "fail": ""}], served=M1)
    path = _log(env)
    before_mtime = path.stat().st_mtime_ns
    before_bytes = path.read_bytes()

    first, bad_first = route_log.read_routes(card=None, root=env)
    second, bad_second = route_log.read_routes(card=CARD, root=env)

    assert first == second and bad_first == bad_second == 0
    assert path.stat().st_mtime_ns == before_mtime, "读的时候写了盘"
    assert path.read_bytes() == before_bytes


# ================================================================ ⑦ 空表是合法读数


def test_missing_file_is_empty_not_error(env: Path) -> None:
    """文件不在 ⇒ `([], 0)`，**不是错误**（体例照 `pipeline_view._read_leases`）。"""
    assert not _log(env).exists()

    rows, bad = route_log.read_routes(CARD, root=env)

    assert rows == [] and bad == 0, "空表是合法读数：不许抛，也不许把「没有」算成「坏了」"
    assert not _log(env).exists(), "只读的调用不许顺手建出文件来"


# ================================================================ ⑧ 坏行如实报坏


def test_broken_line_is_reported(env: Path) -> None:
    """坏 JSON 行跳过但**计数**（第二返回值），好行照常读出来 —— 不许静默当空。"""
    _dispatch(env, tried=[{"model": M1, "fail": ""}], served=M1)
    path = _log(env)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write("{这不是 JSON\n")
        handle.write("[1, 2, 3]\n")          # 合法 JSON，但不是对象
        handle.write("\n")                   # 空行：不算坏行

    rows, bad = route_log.read_routes(CARD, root=env)

    assert bad == 2, f"坏行该数出 2 条（坏 JSON + 非对象），实际 {bad}"
    assert len(rows) == 1, "坏行不许把好行也带下去"
    assert rows[0]["served"] == M1


# ================================================================ ⑨ status 闭集


def test_status_vocabulary_closed(env: Path) -> None:
    """`status` 只允许四个值；第五个必须抛 —— 闭集断言，不靠人记。"""
    assert route_log.STATUSES == ("served", "all_failed", "stopped", "quota_blocked")

    for status in route_log.STATUSES:
        route_log.append_route(card=CARD, attempt=1, asked=M1, tried=[{"model": M1, "fail": ""}],
                               served=M1 if status == "served" else "", status=status,
                               started_at=None, root=env)

    with pytest.raises(route_log.RouteError):
        route_log.append_route(card=CARD, attempt=2, asked=M1, tried=[{"model": M1, "fail": ""}],
                               served=M1, status="succeeded", started_at=None, root=env)
    with pytest.raises(route_log.RouteError):
        route_log.append_route(card=CARD, attempt=3, asked=M1, tried=[{"model": M1, "fail": ""}],
                               served=M1, status="", started_at=None, root=env)

    rows, bad = route_log.read_routes(CARD, root=env)
    assert bad == 0
    assert [row["status"] for row in rows] == list(route_log.STATUSES), "四次合法的各落一条"
    assert "succeeded" not in {row["status"] for row in rows}, "第五个值居然落盘了"


# ================================================================ ⑩ 行形状闭集（卡 A382 / F48）


def test_row_shape_is_exactly_eight_keys(env: Path) -> None:
    """行的形状**恰好八键**，且**没有**会话维度 —— 这是闭集钉，不是欠账单。

    ★ 为什么不是 `xfail(strict=True)` 闹钟：闭集是**阳性**断言 —— 哪天有人加 `"session"`
      键，它当场红，含义明确（「改了形状就回来改这份规格」）。写成 xfail 会把一条**决定**
      读成一条**欠账**，而且 strict 的 XPASS 只有跑全量时才看得见。

    ★ 为什么今天**不该**有会话键：`tools/pool/route_log.py` 的 docstring 写死了本模块的边界 ——
      「每个参数都是**调用方传进来的事实**，本模块不读别的账、不重算、不排序」。会话维度若进来
      只能由调用方传；而网关今天不认任何会话头（F48 判据 1）。**在没有一个可信来源之前加这个键，
      就是逼下游拿空串当真值** —— 正是 F48 要禁的那件事。
    """
    keys = ["asked", "at", "attempt", "card", "served", "started_at", "status", "tried"]
    forbidden = {"session", "caller", "conversation", "session_id", "conversation_id"}

    _dispatch(env, tried=[{"model": M1, "fail": ""}], served=M1)
    rows, bad = route_log.read_routes(CARD, root=env)

    assert bad == 0, "好记录不该被算坏行"
    assert len(rows) == 1, f"该恰好一条，实际 {len(rows)} 条"
    assert sorted(rows[0]) == keys, (
        f"行形状变了：{sorted(rows[0])}；规格写死的八键是 {keys} —— "
        f"要加键先改这份钉子和 docs/subsystems/pool/事后判据清单.md，三处一起改"
    )
    assert forbidden & set(rows[0]) == set(), (
        f"行里出现了会话维度的键：{sorted(forbidden & set(rows[0]))} —— "
        f"没有一个可信的会话来源之前不许加"
    )
