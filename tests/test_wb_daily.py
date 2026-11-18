r"""`tools/wb_daily.py`（卡 220 · T-G334）的测试 —— 「今天的一页」只读。

为什么值当测：这个工具是「每日一批自己跑，不靠人记」的那只**手** —— 判错的代价是
**该收的没收 / 该派的没派**（人就不看了）。所以「缺什么说什么」这条比读数本身更要钉：
读不到 backlog / 批状态坏了 / pipeline_view 挂了，都必须**如实点名**，不许空表冒充。

★ 只造**纯数据**（`tmp_path` 下的最小假仓），**不连网、不碰真仓**。
★ 六块读数一律调真 `tools/pipeline_view.py`（`--root` 指向假仓）—— 不假造读数。
"""

from __future__ import annotations

import datetime
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import wb_daily  # noqa: E402,I001 —— 需要先把 tools/ 挂上


# ------------------------------------------------------------------ 最小假仓


def _git(*a: str, cwd: Path) -> None:
    r = subprocess.run(
        ["git", *a],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert r.returncode == 0, r.stderr


def _make_repo(tmp_path: Path) -> Path:
    _git("init", "-q", cwd=tmp_path)
    _git("config", "user.email", "t@t", cwd=tmp_path)
    _git("config", "user.name", "t", cwd=tmp_path)
    (tmp_path / ".gitignore").write_text("*.tmp\n", encoding="utf-8")
    _git("add", ".gitignore", cwd=tmp_path)
    _git("commit", "-q", "-m", "init", cwd=tmp_path)
    return tmp_path


def _write_backlog(root: Path) -> None:
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "workbacklog.toml").write_text(
        '[base]\nreviewed = "abc1234"\n\n'
        '[[cards]]\nid = "001"\ntask = "T-G1"\ntitle = "样卡一"\n'
        'tree = ".wt/a"\nspec = "x.md"\nfiles = ["src/a.py"]\ndepends = []\n'
        'risk = "low"\nstatus = "pending"\n\n'
        '[[cards]]\nid = "002"\ntask = "T-G2"\ntitle = "样卡二"\n'
        'tree = ".wt/b"\nspec = "x.md"\nfiles = ["src/b.py"]\ndepends = []\n'
        'risk = "low"\nstatus = "pending"\n\n'
        '[[cards]]\nid = "003"\ntask = "T-G3"\ntitle = "样卡三"\n'
        'tree = ".wt/c"\nspec = "x.md"\nfiles = ["src/c.py"]\ndepends = []\n'
        'risk = "low"\nstatus = "done"\n',
        encoding="utf-8",
    )


def _write_gates_last(root: Path) -> None:
    (root / "gates").mkdir(parents=True, exist_ok=True)
    (root / "gates" / "last.json").write_text(
        json.dumps(
            {
                "ok": True,
                "rev": "deadbee",
                "gates": [{"name": "pytest", "exit_code": 0, "seconds": 1.5}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _write_registry(root: Path) -> None:
    diag = root / "gates" / "diag"
    diag.mkdir(parents=True, exist_ok=True)
    (diag / "pool-registry.json").write_text(
        json.dumps(
            [
                {
                    "card": "001",
                    "tree": ".wt/a",
                    "files": ["src/a.py"],
                    "owner": "host:1",
                    # ★ 卡 E128：写死的日期迟早过期，夹具就从「活租约」悄悄变成「死租约」。
                    #   这里用「一分钟前」，TTL 仍是 21600s。
                    "at": (
                        datetime.datetime.now() - datetime.timedelta(minutes=1)
                    ).isoformat(timespec="seconds"),
                    "ttl_seconds": 21600.0,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _write_batch(root: Path, tid: str, state: str, declared: list[str], ok: list[str]) -> None:
    """一个批的**两处**：`.toml`（`fences` 的清单）+ `.json`（`state`/`claims`）。"""
    batch = root / "gates" / "diag" / "batch"
    batch.mkdir(parents=True, exist_ok=True)
    members = "\n".join(
        f'[[member]]\nid = "{m}"\nlayer = "工具层"\npaths = ["tools/x.py"]\n' for m in declared
    )
    (batch / f"{tid}.toml").write_text(
        f'id = "{tid}"\nwhy = "测试"\non_complete = ["draft"]\n\n{members}', encoding="utf-8"
    )
    (batch / f"{tid}.json").write_text(
        json.dumps(
            {
                "id": tid,
                "state": state,
                "declared": declared,
                "claims": {m: "success" for m in ok},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _full_fake_repo(tmp_path: Path) -> Path:
    """队列 + last.json + 租约 + 四个批：等提交 / 已落 / 收集中 / 坏状态。"""
    root = tmp_path / "repo"
    root.mkdir()
    _make_repo(root)
    _write_backlog(root)
    _write_gates_last(root)
    _write_registry(root)
    _write_batch(root, "B-WAIT", "awaiting-commit", ["001"], ["001"])
    _write_batch(root, "B-DONE", "landed", ["002", "M-9"], ["002", "M-9"])
    _write_batch(root, "B-COLL", "collecting", ["003"], [])
    # 坏状态文件：清单（toml）在、状态（json）坏
    batch = root / "gates" / "diag" / "batch"
    (batch / "B-BROKEN.toml").write_text(
        'id = "B-BROKEN"\nwhy = "测试"\non_complete = ["draft"]\n\n'
        '[[member]]\nid = "M-1"\nlayer = "工具层"\npaths = ["tools/x.py"]\n',
        encoding="utf-8",
    )
    (batch / "B-BROKEN.json").write_text("{not json", encoding="utf-8")
    return root


def _run_cli(root: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            str(ROOT / "tools" / "wb_daily.py"),
            "--root",
            str(root),
            *extra,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8", errors="replace",
        **wb_daily.NO_WINDOW,
    )


# ------------------------------------------------------------------ 1. 五块读得出来


def test_page_reads_five_blocks(tmp_path: Path) -> None:
    """最小假仓 ⇒ 待派 / 在飞 / 等到提交 / 收集中 / 已落没翻 —— 五块都对。"""
    root = _full_fake_repo(tmp_path)
    page = wb_daily.build_page(root)

    # 待派 = status=pending 的两张（003 是 done，不算）
    assert page["to_dispatch"] == ["001", "002"]
    assert page["cards_reviewed"] == "abc1234"

    # 在飞 = 一条租约
    assert [lc["card"] for lc in page["leases"]] == ["001"]
    assert page["leases"][0]["tree"] == ".wt/a"
    assert page["leases"][0]["ttl_seconds"] == 21600.0

    # 等到提交 / 收集中
    assert [b["id"] for b in page["waiting"]] == ["B-WAIT"]
    assert page["waiting"][0]["ok"] == ["001"]
    assert [b["id"] for b in page["collecting"]] == ["B-COLL"]

    # 已落没翻：002 已落（B-DONE 成功申请）但仍 pending；M-9 不在队列
    assert page["stale"] == [{"card": "002", "status": "pending"}]
    assert page["stale_unknown"] == ["M-9"]

    # 门禁：最近一次读得出来
    assert page["gates"] == {"ok": True, "rev": "deadbee", "count": 1}


# ------------------------------------------------------------------ 2. 坏批状态被点名


def test_broken_batch_state_is_named(tmp_path: Path) -> None:
    """好的批照常读；坏的状态文件**点名**（不许静默跳过）。"""
    root = _full_fake_repo(tmp_path)
    page = wb_daily.build_page(root)
    assert any("B-BROKEN" in n for n in page["batch_notes"]), page["batch_notes"]
    # 其余批照常出
    assert [b["id"] for b in page["waiting"]] == ["B-WAIT"]


# ------------------------------------------------------------------ 3. 缺 backlog 如实说


def test_missing_backlog_says_so(tmp_path: Path) -> None:
    """没有 backlog ⇒ 待派读不到 + 带原话；**不**当成 0 张。"""
    root = tmp_path / "repo"
    root.mkdir()
    _make_repo(root)
    _write_gates_last(root)
    _write_registry(root)
    page = wb_daily.build_page(root)
    assert page["to_dispatch"] is None
    assert "workbacklog.toml" in page["to_dispatch_note"]
    out = wb_daily.render(page)
    assert "读不到" in out


# ------------------------------------------------------------------ 3b. 空仓：还没有卡池


def test_empty_repo_says_no_pool_yet(tmp_path: Path) -> None:
    """空目录 `git init`（**连 `docs/` 都没有**）⇒ 明说「还没有卡池」，且退 0。

    ★ 卡 A306（T-AG420）：新仓第一次跑「今日一页」时，一页空表若不说这句，人只会以为读数坏了。
      「没有卡」不是「出错」—— 所以：要说，但**不许**退非零。
    """
    root = tmp_path / "empty"
    root.mkdir()
    _make_repo(root)
    assert not (root / "docs").exists()

    page = wb_daily.build_page(root)
    assert page["has_pool"] is False
    assert "还没有卡池" in wb_daily.render(page)

    done = _run_cli(root)
    assert done.returncode == 0, done.stderr
    assert "还没有卡池" in done.stdout, done.stdout


def test_pool_present_does_not_cry_no_pool(tmp_path: Path) -> None:
    """有卡池 ⇒ **不**打那行（天天喊「还没有卡池」= 噪音，人就不看了）。"""
    root = tmp_path / "repo"
    root.mkdir()
    _make_repo(root)
    _write_backlog(root)

    page = wb_daily.build_page(root)
    assert page["has_pool"] is True
    assert page["pool_note"] == ""
    assert "还没有卡池" not in wb_daily.render(page)


# ------------------------------------------------------------------ 4. pipeline_view 挂了


def test_pipeline_view_failure_is_reported(tmp_path: Path, monkeypatch) -> None:
    """pipeline_view 起不来 / 退非 0 ⇒ 如实报（六块一起说「没有」，不编空表）。"""
    root = _full_fake_repo(tmp_path)
    monkeypatch.setattr(wb_daily, "PIPELINE_VIEW", tmp_path / "没有这个文件.py")
    page = wb_daily.build_page(root)
    assert page["pipeline"] is None
    assert "pipeline_view" in page["pipeline_note"]
    assert page["to_dispatch"] is None
    assert page["leases"] is None
    assert "pipeline_view" in page["batch_notes"][0]


# ------------------------------------------------------------------ 5. 租约空表 vs 文件不在


def test_empty_lease_file_absent_vs_empty(tmp_path: Path) -> None:
    """没有租约文件 ⇒ 说「文件不在（按 0 条算）」；文件在但空表 ⇒ 0 条不附注。"""
    root = tmp_path / "repo"
    root.mkdir()
    _make_repo(root)
    _write_backlog(root)
    _write_gates_last(root)
    page = wb_daily.build_page(root)  # ★ 没写 pool-registry.json
    assert page["leases"] == []
    assert "pool-registry.json" in page["leases_note"]

    _write_registry(root)
    (root / "gates" / "diag" / "pool-registry.json").write_text("[]", encoding="utf-8")
    page2 = wb_daily.build_page(root)
    assert page2["leases"] == []
    assert page2["leases_note"] == ""


# ------------------------------------------------------------------ 6. 内存读数（不猜值）


def test_memory_reading_shape() -> None:
    """内存读数：有 `gb` / `threshold` 两个键 —— 值读不到就是 None，不当「够」。"""
    mem = wb_daily.memory_reading()
    assert set(mem) == {"gb", "threshold", "note"}
    assert mem["gb"] is None or isinstance(mem["gb"], float)
    v = wb_daily._memory_verdict(mem)
    assert ("够" in v) or ("读不到" in v) or ("不够" in v) or ("闸已关" in v)


# ------------------------------------------------------------------ 7. render 有各块标签


def test_render_has_all_sections(tmp_path: Path) -> None:
    """人读的一页：五块 + 内存 + 门禁 + 「今天该做」都在。"""
    root = _full_fake_repo(tmp_path)
    out = wb_daily.render(wb_daily.build_page(root))
    for tag in (
        "[待派]",
        "[在飞]",
        "[批·等到提交]",
        "[已落没翻 status]",
        "[内存]",
        "[门禁]",
        "⇒ 今天该做：",
    ):
        assert tag in out, f"一页里缺 {tag}"
    assert "workbacklog.toml" in out  # 来源写清
    assert "1 张已落却没翻 status" in out  # 队列里的那张（002）
    assert "历史批成员 1 个（无卡号，不进队列）：M-9" in out  # 无卡号形态 ⇒ 不进队列，不报 ★
    assert "M-9" in out


# ------------------------------------------------------------------ 8. CLI（--json / 人读）


def test_cli_json_and_report(tmp_path: Path) -> None:
    """CLI 两条路都通：`--json` 可解析、默认人读含各块。"""
    root = _full_fake_repo(tmp_path)
    done = _run_cli(root, "--json")
    assert done.returncode == 0, done.stderr
    page = json.loads(done.stdout)
    assert page["to_dispatch"] == ["001", "002"]
    assert [b["id"] for b in page["waiting"]] == ["B-WAIT"]

    text = _run_cli(root)
    assert text.returncode == 0
    assert "[待派] 2 张" in text.stdout


# ------------------------------------------------------------------ 9. 「今天该做」据数说话


def test_todo_says_nothing_when_nothing(tmp_path: Path) -> None:
    """队列全 done 且没有批等着收口 ⇒ 不编出「该做」的话。"""
    root = tmp_path / "repo"
    root.mkdir()
    _make_repo(root)
    _write_gates_last(root)
    _write_registry(root)
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "workbacklog.toml").write_text(
        '[base]\nreviewed = "abc1234"\n\n'
        '[[cards]]\nid = "003"\ntask = "T-G3"\ntitle = "样卡三"\n'
        'tree = ".wt/c"\nspec = "x.md"\nfiles = ["src/c.py"]\ndepends = []\n'
        'risk = "low"\nstatus = "done"\n',
        encoding="utf-8",
    )
    page = wb_daily.build_page(root)
    assert page["todo"] == []
    assert "（读数里没读出要办的事）" in wb_daily.render(page)


# -------------------------------------------------- 10. 今日签到一行（卡 E48 聚合入口）


def test_checkin_line_says_not_run_when_no_archive(tmp_path: Path) -> None:
    """没有当天留档 ⇒ 说「今天没跑过签到」，绝不拿账本里的 last_checkin 冒充。"""
    root = tmp_path / "repo"
    root.mkdir()
    _make_repo(root)
    _write_gates_last(root)
    _write_registry(root)
    page = wb_daily.build_page(root)
    assert page["checkin"]["found"] is False
    assert "今天没跑过签到" in wb_daily.render(page)


def test_checkin_line_reads_archive_counts(tmp_path: Path) -> None:
    """留档在 ⇒ 一行报数（模式 + 总数 + 各结论码）。"""
    root = tmp_path / "repo"
    root.mkdir()
    _make_repo(root)
    _write_gates_last(root)
    _write_registry(root)
    diag = root / "gates" / "diag"
    diag.mkdir(parents=True, exist_ok=True)
    day = wb_daily.datetime.date.today().isoformat()
    (diag / f"checkin-{day}.json").write_text(
        json.dumps(
            {
                "date": day,
                "applied": True,
                "results": [
                    {"id": "a", "platform": "codearts", "kind": "claimed", "credit": 1000},
                    {"id": "b", "platform": "workbuddy", "kind": "already-claimed"},
                    {"id": "c", "platform": "trae", "kind": "uncertain"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    page = wb_daily.build_page(root)
    assert page["checkin"]["found"] is True
    assert page["checkin"]["counts"] == {"claimed": 1, "already-claimed": 1, "uncertain": 1}
    text = wb_daily.render(page)
    assert "[签到] 已真签 · 3 个号 · already-claimed=1 · claimed=1 · uncertain=1" in text


def test_checkin_line_is_honest_about_broken_archive(tmp_path: Path) -> None:
    """留档坏了 ⇒ 说读不了，不当成「没跑过」也不当成「签完了」。"""
    root = tmp_path / "repo"
    root.mkdir()
    _make_repo(root)
    _write_gates_last(root)
    _write_registry(root)
    diag = root / "gates" / "diag"
    diag.mkdir(parents=True, exist_ok=True)
    day = wb_daily.datetime.date.today().isoformat()
    (diag / f"checkin-{day}.json").write_text("{ 坏 json", encoding="utf-8")
    page = wb_daily.build_page(root)
    assert page["checkin"]["found"] is False
    assert "留档读不了" in wb_daily.render(page)


def _write_registry_at(root: Path, *, age_s: float) -> None:
    """一条租约，at 相对当前时间（age_s 大于 TTL ⇒ 死行）。"""
    diag = root / "gates" / "diag"
    diag.mkdir(parents=True, exist_ok=True)
    at = (datetime.datetime.now() - datetime.timedelta(seconds=age_s)).isoformat(timespec="seconds")
    (diag / "pool-registry.json").write_text(
        json.dumps([{"card": "001", "tree": ".wt/a", "files": ["src/a.py"],
                     "owner": "host:1", "at": at, "ttl_seconds": 21600.0}],
                   ensure_ascii=False),
        encoding="utf-8",
    )


def test_leases_line_counts_dead_rows(tmp_path: Path) -> None:
    """★ 判据 3：[在飞] 只数活的 + 念「其中 M 条已死」，死行行尾标「★ 已死」。"""
    root = tmp_path / "repo"
    root.mkdir()
    _make_repo(root)
    _write_gates_last(root)
    _write_registry_at(root, age_s=100000.0)
    page = wb_daily.build_page(root)
    assert page["leases"][0]["dead"] is True       # ★ dead 从读数搬过来，不是重算的
    text = wb_daily.render(page)
    assert "[在飞] 0 条活租约，其中 1 条已死" in text
    assert "★ 已死" in text


def test_todo_says_nobody_holds_the_tree_even_with_dead_rows(tmp_path: Path) -> None:
    """★ 判据 3 的另一半：盘上只剩死行时，「今天该做」必须敢说「无人占树」。"""
    root = tmp_path / "repo"
    root.mkdir()
    _make_repo(root)
    _write_gates_last(root)
    _write_registry_at(root, age_s=100000.0)
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "workbacklog.toml").write_text(
        '[base]\nreviewed = "abc1234"\n\n'
        '[[cards]]\nid = "001"\ntask = "T-G1"\ntitle = "样卡一"\n'
        'tree = ".wt/a"\nspec = "x.md"\nfiles = ["src/a.py"]\ndepends = []\n'
        'risk = "low"\nstatus = "pending"\n',
        encoding="utf-8",
    )
    page = wb_daily.build_page(root)
    assert "当前没有租约在飞 ⇒ 无人占树，可直接派活" in page["todo"]

    # 反过来：活的租约占着树 ⇒ 这句提示一个字都不许出（那是骗人「可以派活」）。
    _write_registry_at(root, age_s=60.0)
    again = wb_daily.build_page(root)
    assert "当前没有租约在飞 ⇒ 无人占树，可直接派活" not in again["todo"]
