r"""六种「看起来接上了其实没接上」各一条钉子（卡 A301 · `T-AG415`）。

口径来源：`复盘/接手能力-方案.md` §6（六条失败模式）。每条钉子的形状固定：
**① 本仓当前状态不误咬**（判据对真数据是绿的）+ **② 人为注入坏数据 ⇒ 咬**（同一把尺子翻红）。
判据尽量复用**生产函数**（`scripts/audit_progress.py` / `tools/wb_verify.py` /
`tools/pool/guards.py` / `tools/pool/landing.py` / `tools/wb_takeover.py`），
不在测试里另写一套"看着像"的判据 —— 第二套判据就是假绿的温床（卡 080 的病根）。

另带三针在**落地前置快检**（`tools/wb_land.py --precheck`，卡 A301 第一件事）上：
快检自己也可能假绿（永远不红 = 没装），所以它也要有对偶用例。

| # | 失败模式 | 判据（真源） | 注入的坏数据 |
|---|---|---|---|
| 1 | 门永远绿因为没真跑 | `wb_verify.check_gates` | 结论 `ok=True` 但某门 `exit_code=1` |
| 2 | 卡登记了但没人派 | `pool.guards.tree_guard` / `_is_live` | 一条 2 小时前的死租约 |
| 3 | 证据指向不存在的路径 | `audit_progress.eval_assertion` | `file:` 指向没落地的路径 |
| 4 | 台账 done 但证据不可求值 | `audit_progress.check_shape` | `status=done` + `evidence=[]` |
| 5 | 骨架铺进了对方主干 | `landing.main_tree_offenders` | 主树里改白名单外的跟踪文件 |
| 6 | 把本仓特有当通用 | `wb_takeover.probe` 的 A 类判据 | 把本仓面板塞进 A 类判据 |
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

import pytest
import tomllib

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "scripts"))

import audit_progress as ap  # noqa: E402
import check_layers as cl  # noqa: E402
import wb_land as wl  # noqa: E402
import wb_takeover as wt  # noqa: E402
import wb_verify as wv  # noqa: E402
from pool import guards, landing  # noqa: E402
from pool.no_window import NO_WINDOW  # noqa: E402


def _git(cwd: Path, *args: str) -> str:
    """跑一条只读 git 命令（★ 子进程一律不弹窗）。"""
    done = subprocess.run(
        ["git", "-c", "core.quotepath=false", "-c", "user.email=t@t", "-c", "user.name=t",
         *args],
        cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
        errors="replace", **NO_WINDOW,
    )
    return (done.stdout or "").strip()


def _iso(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts).isoformat(timespec="seconds")


# ================================================================ ① 门假绿
def _normalize_newer_gates(payload: dict) -> list[str]:
    """把「门表比 `gates/last.json` 新一代」这件事归一化掉（卡 F6）。

    **为什么必须归一化**：`scripts/run_gates.py` 只在**整趟跑完之后**才写 `last.json`
    （`:2500`）。所以「往门表里加一道门」的那一趟，手上那份产物必然是上一代的 ——
    ①半拿上一代产物去对下一代门表 ⇒ 判「少一道门」⇒ 这道钉子红 ⇒ `pytest` 红 ⇒
    写出来的产物是红的 ⇒ 下一趟①半读到红产物，还是红。**加门这个动作本身把钉子锁死。**

    归一化只补「门表新增、产物还没有」的那几道（记 `exit_code=0` 并打 `[INFO]` 点名）；
    反向缺口（产物里有、门表没有 / 产物里有一道真红）**一律不补**，照咬 ——
    所以伪造 `ok`、逐门 `exit_code=1`、门数回退这三条判据一条都没放松。
    """
    expected, _source = wv.expected_gate_names(ROOT, payload.get("profiles_run") or [])
    got = {str(g.get("name")) for g in payload.get("gates", []) if isinstance(g, dict)}
    added = [n for n in expected if n not in got]
    if added:
        payload.setdefault("gates", []).extend(
            {"name": n, "exit_code": 0, "seconds": 0,
             "summary": "[INFO] 归一化：门表新增，产物是上一代的（不是复用、不是通过）"}
            for n in added
        )
        print(f"[INFO] 门表比 gates/last.json 新一代，归一化补上：{added}")
    return added


def test_pin_gate_green_is_exit_codes_not_the_ok_field(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`gates/last.json` 的 `ok` 字段可以是真的 —— 但**判据必须读每道门的 exit_code**。

    ① 真读数（本仓 `gates/last.json` 的门）：`check_gates` 不咬。
       ★ 只把 `rev` 对齐到父提交：卡树 HEAD 不一定就是"被封的那一笔"，那是环境差异，
         不是判据要考的东西（不归一化就会变成一条看树的状态而红的假钉子）。
       ★ 同理把**门表比产物新一代**也归一化（卡 F6，见下面 `_normalize_newer_gates`）：
         加一道门的那一趟，产物必然是上一代的 —— 不归一化就是**加门这件事本身**让这道钉子
         永远红（`run_gates.py` 只在整趟跑完才写 `last.json`，红产物又喂给下一趟）。
    ② 注入：`ok` 照写 True、把第一道门的 `exit_code` 改成 1 ⇒ 必须咬「有门没过」。
    """
    parent = _git(ROOT, "rev-parse", "--short", "HEAD^")
    assert parent, "拿不到父提交（测试要在真仓里跑）"

    payload = json.loads((ROOT / "gates" / "last.json").read_text(encoding="utf-8"))
    payload["rev"] = parent
    _normalize_newer_gates(payload)
    _rows = payload.get("gates", [])
    if any(int(r.get("exit_code", 0)) != 0 for r in _rows) or payload.get("not_run"):
        # ★ 卡 E63（T-AG521）：这条钉子读的是**树上当前那份** gates/last.json。
        #   它自己红着的时候（上一次跑红、或是从云机 scp 回来的读数）这条钉子没有判别力 ——
        #   拿一份红产物去证明「判据不算红」是空转。显式跳过并写清原因，下面注入那半照跑。
        pytest.skip(
            "树上当前 gates/last.json 不是绿的（上一次跑红 / 别处回传）"
            "⇒「真读数不误红」这半没有判别力；注入那半仍然执行"
        )

    def fake_git(real: str):
        def _fake(tree: Path, *args: str) -> str:
            return real if args[:1] == ("show",) else parent
        return _fake

    monkeypatch.setattr(wv, "_git", fake_git(json.dumps(payload, ensure_ascii=False)))
    good = wv.Screen()
    wv.check_gates(good, ROOT, parent)
    assert good.fails == 0, f"真 last.json 被判红 —— 判据先自己坏了\n{capsys.readouterr().out}"
    capsys.readouterr()

    payload["ok"] = True
    payload["gates"][0]["exit_code"] = 1
    tampered = json.dumps(payload, ensure_ascii=False)
    monkeypatch.setattr(wv, "_git", fake_git(tampered))
    bad = wv.Screen()
    wv.check_gates(bad, ROOT, parent)
    out = capsys.readouterr().out
    assert bad.fails == 1, f"结论说绿、读数里有红门 ⇒ 必须咬（实际 {bad.fails}）\n{out}"
    assert "有门没过" in out, out


# ================================================================ ② 卡没人派
def test_pin_card_without_a_live_lease_is_a_dead_card() -> None:
    """「在飞」只认**活租约**：队列里有卡、面板有读数都不算。

    对偶两半（同一条判据）：
    - 活租约（刚登记、TTL 内）⇒ 树被占（咬）；
    - 同一条租约放到 2 小时前（超 TTL）⇒ 不咬 —— **死租约不许冒充有人在跑**（死卡）。
    """
    now = 1_800_000_000.0
    fresh = {"card": "A301", "tree": ".wt/A301", "at": _iso(now - 60),
             "ttl_seconds": 600, "owner": "w1"}
    stale = {**fresh, "at": _iso(now - 7200)}

    assert guards.tree_guard(".wt/A301", [fresh], now), "活租约必须占住树（否则并发会撞）"
    assert guards.tree_guard(".wt/A301", [stale], now) == [], (
        "死租约被当成活租约 ⇒ 「卡没人派」这种假成功就抓不出来")
    assert guards.tree_guard(".wt/A301", [], now) == [], "空登记 = 没人占树（切片那句话的判据）"


# ================================================================ ③ 证据路径不存在
def test_pin_evidence_path_must_really_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`file:` 证据的判据是**路径打不开就红**，不是「写了 file: 就算有证据」。"""
    assert ap.eval_assertion("file:tools/wb_land.py")[0] is True, "真仓里这条必须是绿的"

    monkeypatch.setattr(ap, "ROOT", tmp_path)
    (tmp_path / "demo").mkdir()
    (tmp_path / "demo" / "real.py").write_text("X = 1\n", encoding="utf-8")
    assert ap.eval_assertion("file:demo/real.py")[0] is True
    ok, desc = ap.eval_assertion("file:demo/ghost.py")
    assert ok is False, "注入：路径不存在却判成立 ⇒ 假证据"
    assert "demo/ghost.py" in desc, desc


# ================================================================ ④ done 无证据
def test_pin_done_without_evidence_is_caught() -> None:
    """台账 `status=done` 必须带**机器可求值**的证据 —— 空列表要当场点名。"""
    data = tomllib.loads((ROOT / "docs" / "traceability.toml").read_text(encoding="utf-8"))
    errs = ap.check_shape(data)
    assert not [e for e in errs if "没有任何证据" in e], errs

    bad = copy.deepcopy(data)
    bad["entries"]["T-G999"] = {
        "title": "假的 done", "group": "ENGINEERING", "status": "done",
        "evidence": [], "gaps": "",
    }
    errs2 = ap.check_shape(bad)
    assert any("T-G999" in e and "没有任何证据" in e for e in errs2), errs2


# ================================================================ ⑤ 骨架污染主干
def test_pin_skeleton_must_not_land_in_the_main_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """骨架只许落在隔离树里：主树**白名单外**的跟踪文件被改 ⇒ `main_tree_offenders` 咬。"""
    repo = tmp_path / "main"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "a.py").write_text("A = 1\n", encoding="utf-8")
    (repo / "b.py").write_text("B = 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    monkeypatch.setattr(landing, "_main_tree_root", lambda: repo)

    assert landing.main_tree_offenders([]) == [], "干净主干不许咬"
    (repo / "b.py").write_text("B = 2\n", encoding="utf-8")
    offenders = landing.main_tree_offenders(["a.py"])
    assert offenders and "b.py" in offenders[0], f"主干被改却没咬：{offenders}"
    assert landing.main_tree_offenders(["b.py"]) == [], "在白名单里的改动要放行"


# ================================================================ ⑥ 本仓特例当通用
def _looks_like_us_only(tmp_path: Path) -> Path:
    """只有本仓**特例**（面板 / 工作台拼法）的目录 —— 没有任何通用管线信号。"""
    d = tmp_path / "looks-like-us"
    (d / "tools").mkdir(parents=True)
    (d / "gates").mkdir()
    (d / "tools" / "dsh_panel.py").write_text("# 本仓特例：DSH 面板\n", encoding="utf-8")
    (d / "tools" / "pipeline_view.py").write_text("# 本仓特例：工作台拼法\n", encoding="utf-8")
    (d / "gates" / "last.json").write_text("{}", encoding="utf-8")
    return d


def test_pin_repo_specific_markers_are_not_generic_criteria(tmp_path: Path) -> None:
    """本仓的面板/工作台**不许**被当成「这项目已有管线」（换个项目就判错类）。"""
    assert wt.probe(_looks_like_us_only(tmp_path))["kind"] != "A"


def test_pin_repo_specific_marker_mutation_makes_it_bite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """把本仓特例塞进 A 类判据 ⇒ 上一条钉子**当场红**（证明它真的会翻，不是空话）。"""
    d = _looks_like_us_only(tmp_path)
    monkeypatch.setattr(
        wt, "OWN_PIPELINE_FILES", (*wt.OWN_PIPELINE_FILES, "tools/dsh_panel.py"))
    with pytest.raises(AssertionError):
        assert wt.probe(d)["kind"] != "A", "本仓特例被当成通用判据了"


# ================================================================ 附：前置快检自己也要会咬
def test_precheck_flags_bare_names_but_allows_root_files(tmp_path: Path) -> None:
    """裸文件名判据：无目录分隔 + `.md`/`.toml`/`.py` 结尾；**仓根真有**的同名文件放行。"""
    (tmp_path / "pipeline.toml").write_text("x = 1\n", encoding="utf-8")
    text = ("见 `limits.md` / `NOTES.md` / `scripts/run_gates.py` / `pipeline.toml`\n"
            "还有一条 `docs/changelog.md`\n")
    hits = [word for _, word in wl.bare_names(text, tmp_path)]
    assert hits == ["limits.md", "NOTES.md"], hits


def test_precheck_red_stops_before_the_two_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """文书里有裸文件名 ⇒ 退 1，且**两道子检查一次都不跑**（省的就是这几秒）。"""
    doc = tmp_path / "_text_TAG999.md"
    doc.write_text("=== gaps ===\n- 见 `NOTES.md`\n", encoding="utf-8")
    called: list[tuple[str, ...]] = []

    def never_runs(cmd: tuple[str, ...], root: Path) -> tuple[int, str]:
        called.append(cmd)
        return 0, ""

    monkeypatch.setattr(wl, "_run_step", never_runs)
    rc = wl.run_precheck([doc], tmp_path, out=lambda _s: None)
    assert rc == 1 and called == [], f"rc={rc} called={called}"


def test_precheck_green_runs_both_and_can_still_go_red(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """文书干净 ⇒ 两道都跑；其中任一道红 ⇒ 退 2（快检不是「扫完文书就算过」）。"""
    doc = tmp_path / "clean.md"
    doc.write_text("=== gaps ===\n- 见 `docs/changelog.md`\n", encoding="utf-8")
    seen: list[str] = []

    def both_green(cmd: tuple[str, ...], root: Path) -> tuple[int, str]:
        seen.append(cmd[0])
        return 0, ""

    def first_red(cmd: tuple[str, ...], root: Path) -> tuple[int, str]:
        return 1, "boom"

    monkeypatch.setattr(wl, "_run_step", both_green)
    assert wl.run_precheck([doc], tmp_path, out=lambda _s: None) == 0
    assert seen == ["scripts/check_layers.py", "-m"], seen

    monkeypatch.setattr(wl, "_run_step", first_red)
    assert wl.run_precheck([doc], tmp_path, out=lambda _s: None) == 2


def test_precheck_agrees_with_the_real_gate(tmp_path: Path) -> None:
    """快检与真门**同向**：同一个裸文件名，`check_layers` 的引用完整性也判断链。

    ★ 这是本卡最关键的一条对偶：早失败工具若比门**严**，就是假红；若比门**松**，就白费。
    """
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "x.md").write_text("见 `limits.md`\n", encoding="utf-8")
    problems, _notes, checked = cl.check_link_integrity(tmp_path)
    assert checked == 1, checked
    assert problems and "limits.md" in problems[0], problems

    doc = tmp_path / "_text_TAG999.md"
    doc.write_text("见 `limits.md`\n", encoding="utf-8")
    hits = wl.precheck_docs([doc], tmp_path)
    assert hits and "limits.md" in hits[0], hits
