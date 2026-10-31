r"""写盘纪律（卡 A356 · `T-AG569`）：坏文件旁存、BOM / 权限位 / 换行原样保留、注释不许被抹掉。

为什么值当测：`tools/pool/lastgood.py` 的 `write_atomic` 是**八处写盘**的唯一落点，而它原先
只做「旧的好就顶成 `.bak`」+「tmp + `os.replace`」——三条实测缺陷都在「字节之外」：

- 坏文件**既不进 `.bak` 也不旁存**，写一次就**悄悄没了**（场景 A：没有证据，事后没人查得出）；
- 原文件 `0o600`（凭据类）写完变 `0o666`（场景 D：谁都能改凭据账本）；
- 原文件 CRLF、写完变 LF（场景 C：整仓文本是 CRLF，写完就多一行 diff）；
- 原文件带 UTF-8 BOM，写完 BOM 消失（场景 E：下游把它当另一个文件）。

外加一条**数据不可逆**的：`pool_accounts._dump_toml` 是**整份重生成**，账本里若有行首注释，
`save_ledger` 一写就抹掉 —— 账本在**仓外**，没有 git 能把它 checkout 回来。

| 钉子 | 判什么 | 会红在哪 |
|---|---|---|
| ① 全零字节有名有姓 | 消息带字节数且含 `every one zero` | 若三支合并成「it doesn't parse」 |
| ② 空白是「空」不是「坏」 | 只有空白 ⇒ `it is empty` | 若把「空」也报成「不解析」 |
| ③ 坏文件先旁存 | 写完目录里多一个 `.bad-*`，字节逐字相同 | 若回到「坏的就跳过」 |
| ④ `.bak` 原样不动 | 旁存坏文件时 `.bak` 的字节与 mtime 都不变 | 若顺手把坏的顶成 `.bak` |
| ⑤ 同样的坏字节只存一份 | 连写两次 ⇒ 只有一个 `.bad-*` | 若每次都新存一份 |
| ⑥ 同秒撞名往后编号 | 注入固定 `now`，两个不同坏字节 ⇒ `-2` | 若用 `write_bytes`（会覆盖） |
| ⑦ BOM 原样保留 | 原 BOM ⇒ 新也 BOM；原无 ⇒ 新也无（两支） | 若只钉一支 / 从没补回 |
| ⑧ 权限位原样保留 | `0o600` 与 `0o640` 两组各自回原值 | 若漏 `tmp.Chmod(mode)`（见下 ★） |
| ⑨ 新文件拿默认权限位 | 目标不存在 ⇒ `DEFAULT_PERM` | 若沿用「上一个文件的」 |
| ⑩ 跟着 CRLF（要了才跟） | `follow_ending=True` ⇒ CRLF；`False` ⇒ LF（两支） | 若偷偷改了默认 |
| ⑪ 混合换行不许当成纯 CRLF | 1 CRLF + 1 LF ⇒ 仍按调用方给的来 | 若把判据写成 `crlf > 0` |
| ⑫ 有注释就拒绝写 | 抛 `LedgerError` 且文件字节**一字未变** | 若改成「先备份再写」 |
| ⑬ 无注释照常写 | 今天真实账本形状（无行首 `#`）⇒ 正常落盘 | 若把检查做成一律拒绝 |
| ⑭ 行尾注释不算 | 只有行尾 `# …` ⇒ 返回空列表 | 若匹配「`#` 出现在行内任意位置」 |
| ⑮ 老调用点字节不变 | `registry.save` / `queue._save` 各跑一次比字节 | 若新参数改了默认字节 |

★ 钉子 ⑧ 的**如实交代**：这条钉子的红只证明「权限位没被显式设」，**不证明**「保留的是原来
那个」—— 要区分这两件事得再加一条「原文件 `0o640` ⇒ 出来 `0o640`」。所以钉子 ⑧ 写成
**两组权限位**（`0o600` 与 `0o640`），否则它就是半根牙。而 Windows 的 `os.chmod` 只认只读位
（实测 `0o600` / `0o640` 都读回 `0o666`）⇒ win32 上这一支钉的是「确实拿**原**权限位调了
`chmod`」（spy），真值只在 POSIX 上钉。这不是放宽，是把「平台给不了的真值」换成「平台给得了
的等价证据」，并在回执里明说。

★ 导入口径照既有测试（`tests/test_pool_lastgood.py`）：把 `tools/` 挂上 `sys.path` 再 `import`；
全程 `tmp_path`，不碰真仓，也不碰仓外真账本。
"""

from __future__ import annotations

import json
import os
import stat
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import pool_accounts as pa  # noqa: E402 —— tools/ 已在 sys.path 上
from pool import lastgood, queue, registry  # noqa: E402

#: 坏得「不是空、也不是全零」的字节：`describe_bad` 的第三支（it doesn't parse）。
CORRUPT = "{坏掉的 JSON"

#: 最小账本（无行首注释 —— 今天的真账本形状，实测 91 行 0 条 `^#`）。
LEDGER_HEAD = """
[[account]]
id = "codearts-1"
label = "备用号 codearts"
platform = "codearts"
state = "active"
added_at = "2026-09-30"
approved_models = []

[account.credential]
kind = "none"
"""

#: 注入给 `keep_bad` 的固定时刻（同秒冲突只能靠注入，等真钟表一秒是不允许的写法）。
FIXED_NOW = datetime(2026, 1, 2, 3, 4, 5)
FIXED_STAMP = "20260102-030405"


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _bad_files(target: Path) -> list[Path]:
    return sorted(p for p in target.parent.iterdir() if lastgood.BAD_SUFFIX in p.name)


# ---------------------------------------------------------------- ① ~ ② describe_bad


def test_describe_bad_names_the_zero_filled_case():
    """断电留下的全零文件（magpie #1505）必须一眼看得出来，不许混成「不解析」。"""
    raw = b"\x00" * 4096
    said = lastgood.describe_bad(raw)
    assert "4096" in said  # ★ 字节数要带
    assert "every one zero" in said
    assert said != lastgood.describe_bad(None)  # 与 `None` 那一支必须可区分


def test_describe_bad_names_the_empty_case():
    """只有空白 ⇒ `it is empty`（不是 `it doesn't parse`，也不是全零）。"""
    assert lastgood.describe_bad(b"  \r\n\t\n ") == "it is empty"
    assert lastgood.describe_bad(None) == "it doesn't parse"  # 三支不许合并
    assert lastgood.describe_bad(CORRUPT.encode("utf-8")) == "it doesn't parse"


# ---------------------------------------------------------------- ③ ~ ⑥ keep_bad


def test_keep_bad_copies_a_corrupt_file_aside(tmp_path):
    """场景 A：旧文件坏了，写新值之前**先把坏字节旁存**（从前它就这么没了）。"""
    target = _write(tmp_path / "reg.json", CORRUPT)
    lastgood.write_atomic(target, "[]\n", validate=json.loads)

    kept = _bad_files(target)
    assert len(kept) == 1  # ★ 必须**多出**一个 `.bad-*`，不是「没崩就行」
    assert kept[0].read_bytes() == CORRUPT.encode("utf-8")  # 逐字节相同
    assert kept[0].name.startswith("reg.json.bad-")
    assert target.read_text(encoding="utf-8") == "[]\n"  # 写盘照常进行
    assert not lastgood.backup_path(target).exists()  # 坏的仍不进 `.bak`


def test_keep_bad_leaves_the_bak_alone(tmp_path):
    """已有好 `.bak` 时旁存坏文件：`.bak` 的字节与 mtime **都不许动**。"""
    target = _write(tmp_path / "reg.json", "[]\n")
    bak = lastgood.backup_path(target)
    _write(bak, "[]\n")
    os.utime(bak, (1_600_000_000, 1_600_000_000))
    before_bytes = bak.read_bytes()
    before_mtime = bak.stat().st_mtime

    target.write_text(CORRUPT, encoding="utf-8")  # 正式文件被人手改坏
    lastgood.write_atomic(target, '[{"a": 1}]\n', validate=json.loads)

    assert bak.read_bytes() == before_bytes
    assert bak.stat().st_mtime == before_mtime  # ★ mtime 也要钉：重写同样字节也算动了
    assert len(_bad_files(target)) == 1


def test_keep_bad_does_not_keep_the_same_bytes_twice(tmp_path):
    """同样坏字节已经存过 ⇒ 返回已有路径，不再存第二份（照 `keptAlready`）。"""
    target = _write(tmp_path / "reg.json", CORRUPT)
    lastgood.write_atomic(target, "[]\n", validate=json.loads)
    first = _bad_files(target)
    assert len(first) == 1

    # 同一份坏字节又被写坏一次（内容一字不差）
    target.write_text(CORRUPT, encoding="utf-8")
    again = lastgood.keep_bad(target, CORRUPT.encode("utf-8"))
    assert again == first[0]  # ★ 返回的是**已有的**那个
    assert len(_bad_files(target)) == 1  # 目录里没有第二份


def test_keep_bad_numbers_collisions_within_one_second(tmp_path):
    """注入固定 `now`：同秒两个**不同**坏字节 ⇒ `.bad-<stamp>` 与 `.bad-<stamp>-2`。"""
    target = _write(tmp_path / "reg.json", CORRUPT)  # 目录与文件名先就位

    one = lastgood.keep_bad(target, b"bad-one", now=FIXED_NOW)
    two = lastgood.keep_bad(target, b"bad-two", now=FIXED_NOW)

    assert one is not None
    assert two is not None
    assert one.name == f"reg.json{lastgood.BAD_SUFFIX}{FIXED_STAMP}"
    assert two.name == f"reg.json{lastgood.BAD_SUFFIX}{FIXED_STAMP}-2"  # ★ 同秒不许互相覆盖
    assert one.read_bytes() == b"bad-one"
    assert two.read_bytes() == b"bad-two"



# ------------------------------------------------------- ⑦ ~ ⑪ BOM / 权限位 / 换行


def test_write_atomic_keeps_the_byte_order_mark(tmp_path):
    """场景 E：原 BOM ⇒ 新也 BOM；原无 BOM ⇒ 新也无 BOM（**两支都要**）。"""
    with_bom = tmp_path / "bom.toml"
    with_bom.write_bytes(lastgood.BOM + b"a = 1\n")
    lastgood.write_atomic(with_bom, "a = 2\n")
    assert with_bom.read_bytes() == lastgood.BOM + b"a = 2\n"  # ★ BOM 只补一次，不叠两个

    plain = tmp_path / "plain.toml"
    plain.write_bytes(b"a = 1\n")
    lastgood.write_atomic(plain, "a = 2\n")
    assert plain.read_bytes() == b"a = 2\n"  # ★ 不许给本来没有 BOM 的文件加一个


def test_write_atomic_keeps_the_file_mode(tmp_path, monkeypatch):
    """场景 D：`0o600` 与 `0o640` 各自回原值（★ 见文件头：一组权限位是半根牙）。

    POSIX 钉**真值**；Windows 上 `os.chmod` 只认只读位（实测 `0o600`/`0o640` 都读回 `0o666`），
    真值不可得 ⇒ 改钉**「用的是原文件此刻的权限位、不是常量」**这一件事：Windows 上新建文件
    默认是 `0o666`，与 `DEFAULT_PERM = 0o644` **不同**，所以「传了 `0o666`」本身就证明它读了原
    文件；若有人把 `tmp.Chmod(mode)` 删掉、或把 `mode` 写死成 `DEFAULT_PERM`，这一支都会红。
    """
    calls: list[tuple[str, int]] = []
    real_chmod = os.chmod

    def spy(path, mode, *args, **kwargs):
        calls.append((str(path), mode))
        return real_chmod(path, mode, *args, **kwargs)

    monkeypatch.setattr(lastgood.os, "chmod", spy)

    wanted = (0o600, 0o640) if sys.platform != "win32" else (0o600,)
    for old_mode in wanted:
        p = tmp_path / f"reg-{old_mode:o}.json"
        p.write_text("[]\n", encoding="utf-8")
        os.chmod(p, old_mode)
        observed = stat.S_IMODE(p.stat().st_mode)  # 平台实际记住的（POSIX 上是 old_mode 本身）

        calls.clear()
        lastgood.write_atomic(p, '[{"a": 1}]\n', validate=json.loads)

        assert any(mode == observed and path != str(p) for path, mode in calls), (
            f"没有拿原权限位 {oct(observed)} 去 chmod 临时文件（漏了 tmp.Chmod(mode)？）"
        )
        if sys.platform != "win32":
            assert observed == old_mode
            assert stat.S_IMODE(p.stat().st_mode) == old_mode  # POSIX 上钉**真值**（两组各自原值）
        else:
            assert observed != lastgood.DEFAULT_PERM  # ⇒ 传 `observed` 就不是「写死的默认值」
            assert p.read_text(encoding="utf-8") == '[{"a": 1}]\n'


def test_write_atomic_new_file_gets_the_default_mode(tmp_path, monkeypatch):
    """目标**不存在** ⇒ `DEFAULT_PERM`（不沿用「上一个文件的」权限位）。"""
    calls: list[tuple[str, int]] = []
    real_chmod = os.chmod

    def spy(path, mode, *args, **kwargs):
        calls.append((str(path), mode))
        return real_chmod(path, mode, *args, **kwargs)

    monkeypatch.setattr(lastgood.os, "chmod", spy)
    target = tmp_path / "fresh.json"  # 从不存在
    lastgood.write_atomic(target, "[]\n", validate=json.loads)

    assert lastgood.DEFAULT_PERM == 0o644  # 逐字照 `file.go:151`
    assert any(mode == lastgood.DEFAULT_PERM for _path, mode in calls)
    if sys.platform != "win32":
        assert stat.S_IMODE(target.stat().st_mode) == 0o644


def test_write_atomic_follows_a_crlf_file_when_asked(tmp_path):
    """场景 C：**要了才跟**（`follow_ending=True` ⇒ CRLF；`False` ⇒ 仍是 LF）。"""
    followed = tmp_path / "crlf-follow.toml"
    followed.write_bytes(b"a = 1\r\nb = 2\r\n")
    lastgood.write_atomic(followed, "a = 1\nb = 3\n", follow_ending=True)
    assert followed.read_bytes() == b"a = 1\r\nb = 3\r\n"  # ★ 跟着原文件

    ignored = tmp_path / "crlf-ignore.toml"
    ignored.write_bytes(b"a = 1\r\nb = 2\r\n")
    lastgood.write_atomic(ignored, "a = 1\nb = 3\n")  # 默认 False
    assert ignored.read_bytes() == b"a = 1\nb = 3\n"  # ★ 默认值不许偷偷改


def test_write_atomic_does_not_follow_a_mixed_ending_file(tmp_path):
    """混合换行（1 个 CRLF + 1 个 LF）**不算**纯 CRLF ⇒ 按调用方给的来。"""
    target = tmp_path / "mixed.toml"
    target.write_bytes(b"a = 1\r\nb = 2\n")  # 夹具必须真的是混合：改判据不改它就绿
    raw = target.read_bytes()
    assert raw.count(b"\r\n") == 1 and raw.count(b"\n") == 2  # 自证夹具是混合的

    lastgood.write_atomic(target, "a = 1\nb = 3\n", follow_ending=True)
    assert target.read_bytes() == b"a = 1\nb = 3\n"  # ★ 不许整份改成 CRLF


# ------------------------------------------------------------ ⑫ ~ ⑭ save_ledger


def _data_with_one_account() -> dict:
    return {
        "account": [
            {
                "id": "codearts-1",
                "label": "备用号 codearts",
                "platform": "codearts",
                "state": "active",
                "added_at": "2026-09-30",
                "approved_models": [],
                "credential": {"kind": "none"},
            }
        ]
    }


def test_save_ledger_refuses_a_ledger_with_comments(tmp_path):
    """有行首注释 ⇒ 抛 `LedgerError`，且**文件字节一字未变**（先存快照再比）。"""
    target = _write(tmp_path / "accounts.toml", "# 这是人写的注释\n" + LEDGER_HEAD)
    before = target.read_bytes()

    with pytest.raises(pa.LedgerError) as excinfo:
        pa.save_ledger(target, _data_with_one_account())

    message = str(excinfo.value)
    assert "账本里有注释" in message
    assert "_dump_toml" in message  # 必须点名「谁」会抹掉它
    assert "1" in message  # 前 3 个行号里要有第 1 行
    assert target.read_bytes() == before  # ★ 一个字节都不许写
    assert not lastgood.backup_path(target).exists()  # 也不许「先备份再写」


def test_save_ledger_writes_a_comment_free_ledger_unchanged(tmp_path):
    """今天真实账本的形状（无行首 `#`）⇒ 照常写（拒绝不许变成一律拒绝）。"""
    target = _write(tmp_path / "accounts.toml", LEDGER_HEAD)
    pa.save_ledger(target, _data_with_one_account())

    written = target.read_text(encoding="utf-8")
    pa._validate_ledger_toml(written)  # 判据 10：仍能过 TOML 校验
    assert written.startswith("[[account]]")
    assert 'id = "codearts-1"' in written
    assert list(tmp_path.glob("*.tmp")) == []  # 原子写没留渣


def test_ledger_would_lose_comments_ignores_trailing_comments(tmp_path):
    """只有**行尾** `# …` ⇒ 返回空列表（管不了就明说管不了，不许误报）。"""
    target = _write(
        tmp_path / "accounts.toml",
        'id = "codearts-1"  # 行尾注释，_dump_toml 也会丢，但这条不算「整份重生成」的锅\n'
        'label = "备用号"  # 也是行尾\n',
    )
    assert pa.ledger_would_lose_comments(target) == []

    # 而行首（允许前置空白）的 `#` 必须被抓出来，且行号是 1 起的
    target2 = _write(
        tmp_path / "two.toml",
        'a = 1\n  # 缩进过的行首注释\nb = 2  # 行尾不算\n',
    )
    assert pa.ledger_would_lose_comments(target2) == [2]


# ---------------------------------------------------------- ⑮ 老调用点字节不变


def test_write_atomic_old_callers_are_byte_identical(tmp_path, monkeypatch):
    """不传新参数时，`registry.save` 与 `queue._save` 的落盘字节与从前一致。"""
    reg = tmp_path / "pool-registry.json"
    rows = [{"task": "T-A", "tree": ".wt/a"}]
    registry.save(rows, reg)
    assert reg.read_bytes() == (json.dumps(rows, ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8"
    )

    q = tmp_path / "merge-queue.json"
    monkeypatch.setenv("TF_MERGE_QUEUE", str(q))
    state = {"head": None, "waiting": [{"task": "T-B", "tree": ".wt/b"}]}
    queue._save(state)
    assert q.read_bytes() == (
        json.dumps(state, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    # ★ 两支都不许带 BOM、不许把 `\n` 换成 `\r\n`（新参数的默认值不改字节）
    assert not q.read_bytes().startswith(lastgood.BOM)
    assert q.read_bytes().count(b"\r\n") == 0
