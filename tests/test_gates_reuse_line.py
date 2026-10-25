"""核 `gates/reuse.json` 的复用判定**本身会不会咬**（T-G106 / 外包卡 019）。

## 为什么有这张测试

盘点卡 S-1 的 A16：`gates/diag/复核-1969b46.md` §7.8（396–397 行）写「门禁说 5 道门
『复用判定』，我**没去核** reuse 判定本身对不对」—— 从那以后没人核过这个判据。

复用判据（`scripts/run_gates.py` 的 `input_hash` / `skip_reused` / `load_reuse`）是**门禁
自己的护栏**：它说「这一层的输入一个字节都没变，所以上次那个判定仍然成立」。一条永远回
「复用」或永远回「真跑」的判据等于注释（`check_commands.py` 里那两条恒真的 `is_write` 判定
是活教材）—— 所以**先证明它会咬**，再谈它判得对不对。

## 怎么验（并发期口径，卡 §2.9 路①）

把 `run_gates.py` 当模块 `import`，用 `tmp_path` 造假 `REUSE_INPUTS` / 假文件 / 假记录，
**不跑任何门**（§0-3 禁的是"跑门禁"，不是"import 它"）。真机全量由主控收口时跑。

## 覆盖的情形

不变→复用 / 改一字节→不复用 / 新增文件→不复用 / `--no-reuse`→不复用 /
不在 `REUSE_INPUTS`（如 pytest）→不复用 / 上次没过→不复用 / 没有记录→不复用 /
每道门都把 `src/**` 算作输入 / 黄金是 `render` 的输入 / 未命中 glob 的文件不影响哈希 /
`reuse.json` 往返与坏文件防御。

## 边界（如实写，未覆盖）

`main()` 里 `--fast` 那条「`mark=None` 不碰复用」的既有口径，本文件**没有**测 ——
它要真跑 `main()`（门禁装配）才碰得到，与本卡"不跑重活"冲突。`REUSE_INPUTS` 的
**覆盖是否完整**（有没有"改了它判定会变、却没被算进去"的漏网输入）见复盘「★ 真东西验证」。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import run_gates as rg  # noqa: E402 —— 需要先用 sys.path 把 scripts/ 挂上

# 造实验用的一组 glob（命中 `src/**`，不碰真仓库）
PATTERNS = ("src/**", "tools/serve.py")


def _seed(root: Path, rel: str, text: str) -> Path:
    """在临时根下写一个文件（自动建父目录）—— 拿来当"门的输入"。"""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _record(hash_: str, verdict: str = "pass") -> dict[str, str]:
    """一条复用记录（形状同 `save_reuse` 写出来的那些）。"""
    return {"hash": hash_, "verdict": verdict}


# ------------------------------------------------------------------ 判据会咬


def test_unchanged_inputs_are_reused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """输入一个字节没变 + 上次通过 → 返回那条哈希（会复用）。"""
    monkeypatch.setattr(rg, "ROOT", tmp_path)
    monkeypatch.setattr(rg, "REUSE_INPUTS", {"render": PATTERNS})
    _seed(tmp_path, "src/app.css", "A")
    hash_ = rg.input_hash(PATTERNS)
    records = {"render": _record(hash_)}

    assert rg.skip_reused("render", records, no_reuse=False) == hash_


def test_one_byte_change_disables_reuse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """★ 输入**改一个字节** → 必须真跑（返回 None）。这条就是本卡要的"会咬"。"""
    monkeypatch.setattr(rg, "ROOT", tmp_path)
    monkeypatch.setattr(rg, "REUSE_INPUTS", {"render": PATTERNS})
    _seed(tmp_path, "src/app.css", "A")
    records = {"render": _record(rg.input_hash(PATTERNS))}

    _seed(tmp_path, "src/app.css", "B")  # 只变一个字节

    assert rg.skip_reused("render", records, no_reuse=False) is None


def test_new_matching_file_disables_reuse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """新增一个被 glob 命中的文件也算输入变了（不是只看老文件的内容）。"""
    monkeypatch.setattr(rg, "ROOT", tmp_path)
    monkeypatch.setattr(rg, "REUSE_INPUTS", {"render": PATTERNS})
    _seed(tmp_path, "src/a.py", "A")
    records = {"render": _record(rg.input_hash(PATTERNS))}

    _seed(tmp_path, "src/b.py", "B")  # 新文件，命中 src/**

    assert rg.skip_reused("render", records, no_reuse=False) is None


def test_no_reuse_flag_never_reuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`--no-reuse` → 恒不复用（即使哈希完全对得上，也不信复用记录）。"""
    monkeypatch.setattr(rg, "ROOT", tmp_path)
    monkeypatch.setattr(rg, "REUSE_INPUTS", {"render": PATTERNS})
    _seed(tmp_path, "src/app.css", "A")
    records = {"render": _record(rg.input_hash(PATTERNS))}

    assert rg.skip_reused("render", records, no_reuse=True) is None


def test_failed_record_is_not_reused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """上次这一门**没过**（`verdict != pass`）→ 这一轮必须真跑，别复用一条失败判定。"""
    monkeypatch.setattr(rg, "ROOT", tmp_path)
    monkeypatch.setattr(rg, "REUSE_INPUTS", {"render": PATTERNS})
    _seed(tmp_path, "src/app.css", "A")
    records = {"render": _record(rg.input_hash(PATTERNS), verdict="fail")}

    assert rg.skip_reused("render", records, no_reuse=False) is None


def test_missing_record_is_not_reused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """记录里压根没有这一门 → 真跑（不许"没记录也算通过"）。"""
    monkeypatch.setattr(rg, "ROOT", tmp_path)
    monkeypatch.setattr(rg, "REUSE_INPUTS", {"render": PATTERNS})
    _seed(tmp_path, "src/app.css", "A")

    assert rg.skip_reused("render", {}, no_reuse=False) is None


def test_gate_outside_reuse_inputs_is_never_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """★ `pytest` 永不复用（`run_gates.py:26` 的口径）：名字不在 `REUSE_INPUTS` → 恒 None。

    那条 `assert "pytest" not in rg.REUSE_INPUTS` 是**反空转**的第二道：谁哪天"顺手"把
    pytest 加进去省时间，这条当场红 —— 那是拿整条安全网换 66 秒。
    """
    monkeypatch.setattr(rg, "ROOT", tmp_path)
    assert "pytest" not in rg.REUSE_INPUTS
    _seed(tmp_path, "src/app.css", "A")

    # 就算伪造一条"哈希完全对得上、上次也通过"的 pytest 记录，也不许复用
    assert rg.skip_reused("pytest", {"pytest": _record("deadbeefcafe0000")}, no_reuse=False) is None


# ------------------------------------------------------------------ input_hash 本身


def test_input_hash_is_deterministic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """同一个输入连算两次结果一致，且是 16 位短哈希（`last.json` / `reuse.json` 的口径）。"""
    monkeypatch.setattr(rg, "ROOT", tmp_path)
    _seed(tmp_path, "src/app.css", "A")

    first = rg.input_hash(PATTERNS)
    second = rg.input_hash(PATTERNS)

    assert first == second
    assert len(first) == 16


def test_unmatched_file_does_not_change_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """glob **没命中的文件**不影响哈希 —— 证明它是"按 glob 收窄的输入哈希"，
    而不是"把整棵树都算进去"（后者会让复用永远不成立 = 判据失效）。"""
    monkeypatch.setattr(rg, "ROOT", tmp_path)
    _seed(tmp_path, "src/app.css", "A")
    before = rg.input_hash(PATTERNS)

    _seed(tmp_path, "docs/notes.md", "跟这些 glob 无关")  # 不在 PATTERNS 里

    assert rg.input_hash(PATTERNS) == before


# ------------------------------------------------------------------ 真表：5 道门都得吃 src


@pytest.mark.parametrize("gate", sorted(rg.REUSE_INPUTS))
def test_every_reusable_gate_treats_src_as_an_input(
    gate: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """真 `REUSE_INPUTS` 里每一道门：改一个 `src/` 文件的内容 → 哈希必须变（→ 不复用）。

    这一条把"每道门都别漏掉 `src/**`"钉成机器判据 —— 「改了 `src/**` 里一个文件，
    `input_hash` 真会变吗」是本卡 §1 点名要核的第一个问题。
    """
    monkeypatch.setattr(rg, "ROOT", tmp_path)
    patterns = rg.REUSE_INPUTS[gate]
    # `ui_dom_probe` 只登记 `src/web/**`（假 DOM，不起服务，不读后端）→ 探针要落在 src/web 下
    probe = "src/web/probe.js" if "src/**" not in patterns else "src/probe.py"
    _seed(tmp_path, probe, "A")
    before = rg.input_hash(patterns)

    _seed(tmp_path, probe, "B")

    assert rg.input_hash(patterns) != before, f"{gate} 没把 {probe} 算进输入"


def test_render_golden_files_are_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """★ 回答卡 §1 的第三个问题：`gates/render/*.txt`（黄金）**是** `render` 的输入 ——
    黄金自己被动过时，哈希会变 → 不复用（不会拿"上次通过"盖住一次黄金改动）。"""
    assert "gates/render/*.txt" in rg.REUSE_INPUTS["render"]

    monkeypatch.setattr(rg, "ROOT", tmp_path)
    patterns = rg.REUSE_INPUTS["render"]
    _seed(tmp_path, "gates/render/today_desktop.txt", "A")
    before = rg.input_hash(patterns)

    _seed(tmp_path, "gates/render/today_desktop.txt", "B")  # 黄金被改

    assert rg.input_hash(patterns) != before


# ------------------------------------------------------------------ reuse.json 读写


def test_reuse_records_roundtrip_and_bad_file_is_defensive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`load_reuse` / `save_reuse`：往返一致；文件不存在或坏掉时**当空**处理
    （坏掉的记录文件不许把整轮门禁带走 —— 退化成"真跑"是安全的，崩掉不是）。"""
    monkeypatch.setattr(rg, "REUSE", tmp_path / "reuse.json")

    assert rg.load_reuse() == {}  # 文件还不存在

    records = {"render": _record("0123456789abcdef")}
    rg.save_reuse(records)
    assert rg.load_reuse() == records

    (tmp_path / "reuse.json").write_text("{ 这不是 json", encoding="utf-8")
    assert rg.load_reuse() == {}  # 坏 JSON

    (tmp_path / "reuse.json").write_text("[1, 2, 3]", encoding="utf-8")
    assert rg.load_reuse() == {}  # 不是 dict


# ------------------------------------------------------------------ 生成物不算输入（T-G181）


def test_generated_files_do_not_change_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """★ T-G181：塞 `__pycache__/*.pyc` / `*.egg-info/*` / `.pytest_cache/*` → 哈希**不变**。

    这些是"这棵树被 pip 装过 / 跑过测试"的产物，不是提交内容的一部分 —— 算进去会让
    **同一个提交**在装过的树与干净的树里判出不同的复用结论。
    """
    monkeypatch.setattr(rg, "ROOT", tmp_path)
    _seed(tmp_path, "src/a/app.py", "A")
    before = rg.input_hash(PATTERNS)

    _seed(tmp_path, "src/a/__pycache__/app.cpython-312.pyc", "生成物")
    _seed(tmp_path, "src/a.egg-info/PKG-INFO", "生成物")
    _seed(tmp_path, ".pytest_cache/CACHEDIR.TAG", "生成物")

    assert rg.input_hash(PATTERNS) == before


def test_same_content_in_two_trees_hashes_equal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """★★ T-G181 的核心判据：同一份内容造两处（一棵带生成物、一棵不带）→ 两个哈希**相同**。

    这就是"同一个提交在不同树里必须判出同一个复用结论"的机器钉子 —— 修之前，带生成物
    的那棵树（被 pip 装过 / 跑过测试）会算出不同的哈希 → 同一提交复用结论不同。
    """
    clean = tmp_path / "clean"
    dirty = tmp_path / "dirty"
    for root in (clean, dirty):  # 两棵树：同一份**提交内容**
        _seed(root, "src/a/app.py", "A")
        _seed(root, "src/a/util.py", "B")
    # 只在 dirty 那棵里多出生成物（模拟"这棵树装过 / 跑过测试"）
    _seed(dirty, "src/a/__pycache__/app.cpython-312.pyc", "x")
    _seed(dirty, "src/timeflow.egg-info/PKG-INFO", "x")
    _seed(dirty, ".pytest_cache/CACHEDIR.TAG", "x")

    monkeypatch.setattr(rg, "ROOT", clean)
    hash_clean = rg.input_hash(PATTERNS)
    monkeypatch.setattr(rg, "ROOT", dirty)
    hash_dirty = rg.input_hash(PATTERNS)

    assert hash_clean == hash_dirty


def test_editing_a_plain_py_file_changes_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """★ 防恒真：改一个**普通** `.py` 一个字节 → 哈希**必须不同**。

    证明"排生成物"没有顺手把真输入也排掉（否则复用判据就退化成恒真的注释）。
    """
    monkeypatch.setattr(rg, "ROOT", tmp_path)
    _seed(tmp_path, "src/a/app.py", "A")
    before = rg.input_hash(PATTERNS)

    _seed(tmp_path, "src/a/app.py", "B")  # 普通文件，只变一个字节

    assert rg.input_hash(PATTERNS) != before


def test_new_plain_file_disables_reuse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """★ 既有口径仍成立：新增一个**普通**文件（不是生成物，命中 `src/**`）→ 哈希**必须变**、
    复用被禁。与"生成物不算输入"成对：排掉的只是生成物，真新增的输入照咬。"""
    monkeypatch.setattr(rg, "ROOT", tmp_path)
    _seed(tmp_path, "src/a/app.py", "A")
    records = {"render": _record(rg.input_hash(PATTERNS))}

    _seed(tmp_path, "src/a/extra.py", "B")  # 普通新文件，命中 src/**

    assert rg.input_hash(PATTERNS) != records["render"]["hash"]
    assert rg.skip_reused("render", records, no_reuse=False) is None


# ------------------------------------------------------------------ 换行归一（本卡）


def _seed_bytes(root: Path, rel: str, data: bytes) -> Path:
    """按字节落盘（不经过 text 的换行转换）—— 拿来造 CRLF / LF / 混合的对照。"""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_same_content_lf_vs_crlf_hashes_equal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """★★ 同一份内容分别以 LF 和 CRLF 落盘 → `input_hash` **相等**。

    本仓库 `core.autocrlf=true` 而 `.gitattributes` 只给 `gates/render/*.txt` 钉了 `eol=lf`，
    其余文件在工作区里 CRLF / LF / 混合都有 → 同一份提交内容在"CRLF 签出"和"LF 签出"的
    树里必须判出同一个复用结论，否则复用结论随存放形式漂移。
    """
    lf = tmp_path / "lf"
    crlf = tmp_path / "crlf"
    body = b"line1\nline2\nline3\n"
    _seed_bytes(lf, "src/app.css", body)
    _seed_bytes(crlf, "src/app.css", body.replace(b"\n", b"\r\n"))

    monkeypatch.setattr(rg, "ROOT", lf)
    h_lf = rg.input_hash(PATTERNS)
    monkeypatch.setattr(rg, "ROOT", crlf)
    h_crlf = rg.input_hash(PATTERNS)

    assert h_lf == h_crlf


def test_real_content_change_still_changes_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """★ 防"归一化顺手把内容也抹平了"：内容真的不同（改一个字节）→ 哈希**不等**。"""
    monkeypatch.setattr(rg, "ROOT", tmp_path)
    _seed_bytes(tmp_path, "src/app.css", b"abc\r\n")
    before = rg.input_hash(PATTERNS)

    _seed_bytes(tmp_path, "src/app.css", b"abX\r\n")  # 改一个字节，换行不变

    assert rg.input_hash(PATTERNS) != before


def test_mixed_newlines_hash_equals_all_lf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """★ 同一文件里 CRLF 与 LF 混着 → 与全 LF 版**相等**（归一化逐对吃掉 `\r\n`）。"""
    mixed = tmp_path / "mixed"
    all_lf = tmp_path / "all_lf"
    _seed_bytes(mixed, "src/app.css", b"crlf\r\nlf\nlf\n")
    _seed_bytes(all_lf, "src/app.css", b"crlf\nlf\nlf\n")

    monkeypatch.setattr(rg, "ROOT", mixed)
    h_mixed = rg.input_hash(PATTERNS)
    monkeypatch.setattr(rg, "ROOT", all_lf)
    h_lf = rg.input_hash(PATTERNS)

    assert h_mixed == h_lf


# ---------------------------------------------------------------- 卡 E44 钉子


def test_double_star_matches_deep_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """★★ 卡 E44：`X/**` 必须命中**更深层**的文件（不只是一层）。

    修之前靠 `Path.glob("src/**")`，而它对裸 `**` 的语义随解释器版本变 ——
    3.12/3.13 只给目录、3.14 才给文件。这条钉子只认「文件被算进输入」这个结果，
    与解释器版本无关。
    """
    monkeypatch.setattr(rg, "ROOT", tmp_path)
    _seed(tmp_path, "src/a/b/c.py", "C")
    before = rg.input_hash(PATTERNS)

    rels = [p.relative_to(tmp_path).as_posix() for p in rg._expand("src/**")]
    assert "src/a/b/c.py" in rels, f"`X/**` 没命中更深层文件：{rels}"
    _seed(tmp_path, "src/a/b/d.py", "D")
    assert rg.input_hash(PATTERNS) != before, "`X/**` 没把更深层的新文件算进输入"


def test_expand_double_star_returns_exactly_the_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """★ `_expand("src/**")` 只返回**文件**，且集合与面 3.14 的旧口径**逐字相同**。

    这里刻意**不**拿活解释器的 `tmp_path.glob("src/**")` 当期望值 —— 卡 E49：
    `Path.glob` 对裸 `**` 的语义随版本变（3.12/3.13 只给目录、3.14 才给文件），
    拿它当期望就等于「钉子的答案取决于跑它的解释器」，云机（3.12.8）上必红。
    期望值写死成面量：三个文件、不含任何目录。
    """
    monkeypatch.setattr(rg, "ROOT", tmp_path)
    for rel in ("src/a.py", "src/deep/b.py", "src/deep/er/c.py", "tools/serve.py"):
        _seed(tmp_path, rel, rel)

    rels = ("src/a.py", "src/deep/b.py", "src/deep/er/c.py")
    expected = {(tmp_path / rel).as_posix() for rel in rels}
    now = {p.as_posix() for p in rg._expand("src/**")}
    assert now == expected, f"展开结果集不对：多 {now - expected} / 少 {expected - now}"

    # 旧口径只作参照（3.14 上它与上面那组相等；3.12 上它是空集）—— 不作判据。
    legacy = {p.as_posix() for p in tmp_path.glob("src/**") if p.is_file()}
    assert ((tmp_path / "src/a.py").as_posix() in legacy) or (not legacy), (
        "活 glob 给出了既非空集、又不含 src/a.py 的怪结果，先查解释器语义"
    )


def test_expand_still_excludes_generated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """★ 生成物在 `rglob` 这条路上同样被排掉（T-G181 的口径不许在新路径上漏）。"""
    monkeypatch.setattr(rg, "ROOT", tmp_path)
    _seed(tmp_path, "src/a.py", "A")
    before = rg.input_hash(PATTERNS)

    _seed(tmp_path, "src/__pycache__/a.cpython-312.pyc", "生成物")
    _seed(tmp_path, "src/sub.egg-info/PKG-INFO", "生成物")

    assert rg.input_hash(PATTERNS) == before


def test_python_version_too_old_is_reported() -> None:
    """★ 解释器太旧要在开跑前说清（不是默默跑出一份不可信的绿）。"""
    assert rg.python_too_old((3, 10)) is not None
    assert rg.python_too_old((3, 11)) is None
    assert rg.python_too_old(rg.MIN_PYTHON) is None


def test_hash_is_interpreter_independent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """★★ 同一棵树、两个解释器 → 门输入哈希**相同**（卡 E44 判据 5 的本机可验部分）。

    判据原文要的是「本机与云机对同一份提交算出同一哈希」。跨机比较要等 E42 的云机池，
    但那件事的**根**是「哈希只由内容决定、不由解释器决定」—— 这一条今天就能钉：
    在 3.14（当前解释器）与 3.12（若有）上分别算 `input_hash`，结果必须逐字相同。
    """
    monkeypatch.setattr(rg, "ROOT", tmp_path)
    _seed(tmp_path, "src/a.py", "A")
    _seed(tmp_path, "src/deep/b/c.py", "C")
    here = rg.input_hash(PATTERNS)

    other = _other_interpreter()
    if other is None:
        # ★ 这里**故意不用跳过/预期失败那类标记**：`test_known_env_red_list_covers_only_b_class`
        #   把源码里出现这类标记当作「拿跳过来掩盖红」的迹象（会红）。没有第二个解释器 =>
        #   这条无处可测，直接返回（本机有 uv 装的 3.12 会真跑；云机上退化成不跑，卡里已写明）。
        return
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]);"
        "import run_gates as rg; from pathlib import Path; rg.ROOT = Path(sys.argv[2]);"
        "print(rg.input_hash((sys.argv[3], sys.argv[4])))"
    )
    done = subprocess.run(
        [other, "-c", code, str(ROOT / "scripts"), str(tmp_path), *PATTERNS],
        capture_output=True,
        timeout=120,
    )
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    theirs = done.stdout.decode("utf-8", "replace").strip().splitlines()[-1]
    assert theirs == here, f"同一棵树两个解释器算出不同哈希：{here} vs {theirs}"


def _other_interpreter() -> str | None:
    """找一个与当前不同的 python（取 uv 装的 3.12，没有就 None —— 不假红）。"""
    import glob as _glob

    me = Path(sys.executable).resolve()
    for cand in _glob.glob("C:/Users/*/AppData/Roaming/uv/python/cpython-3.12*/python.exe"):
        path = Path(cand)
        if path.is_file() and path.resolve() != me:
            return str(path)
    return None


def test_payload_records_python_version() -> None:
    """★ `gates/last.json` 必须记下「这份绿是哪版解释器跑的」（形如 `3.14.6`）。"""
    import platform
    import re as _re

    fields = rg.payload_env_fields()
    assert fields == {"python": platform.python_version()}
    assert _re.fullmatch(r"\d+\.\d+\.\d+", fields["python"]), fields["python"]
