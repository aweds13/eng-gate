r"""禁用表的钉子（卡 A353 · T-AG566 · F84「禁用的模型」）—— 18 条，名字逐字照设计原件。

## 钉什么（一层意思）

「禁用的模型」不是「批准集」的另一半，而是**另一个维度的拒绝**：

- **三种名字**：一个模型可以按 ``model`` / ``provider/model`` / ``尾段`` 三种写法被禁
  （`names_of`）；一个**裸 id** 又是另外三档（`id_names`）—— 两个函数**不是**同一个。
- **单星号 glob**：通配只有 ``*`` 与 ``?`` 两个；``*`` **跨斜杠**，``[`` 是**字面**。
  ⇒ **不许用 `fnmatch`**（它的 ``[`` 是字符类、``*`` 语义也不同），本卡自写回溯。
- **读不到 = 全禁**：禁用表**不存在** ⇒ 没禁用；**存在但坏了** ⇒ **不知道 ⇒ 一个都不放行**。
  钉 12 与钉 13 是**成对**的：只钉「坏了 ⇒ unknown」的话，一个「永远返回 unknown」的懒实现
  也能过；钉 12 把它堵死。同理钉 13 的夹具**必须先 ``assert path.exists()``** —— 夹具写错了，
  这一条与钉 14、钉 16 会**全绿地空转**（设计原件 §F84 变异 6 如实交代的陷阱）。

## 边界（如实写）

- 卡 A353 当时**只提供判据、不接线**；接线由卡 E105（T-AG614）补上：`assert_not_disabled`
  今天被三处生产入口调用（派活主闸 / 网关 `_model_block` / MCP 干跑面），判据仍只有这一份。
- 「整组都被禁」那条文案**搬不过来**：pool 没有「路由组」概念（缺口如实记在卡规格里）。
- 所有 glob 钉子都用**手写字符串**，没有一份来自真 `settings.json` 的 `DisabledModels` 样本。

★ 本文件**不动** ``tests/test_model_registry.py`` 的既有钉子（那 23 条必须照旧全绿）。
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

# ★ 导入用 `importlib`：本仓禁 noqa 注释，而 `sys.path.insert` 之后直接写 import 语句会踩 E402。
#   口径同 `tests/test_pool_callers.py:44-56`（那里是同一套理由）。
mr = importlib.import_module("pool.model_registry")

MAX_DISABLED_CHARS = mr.MAX_DISABLED_CHARS
MAX_DISABLED_PATTERNS = mr.MAX_DISABLED_PATTERNS
UNKNOWN = mr.UNKNOWN
DisabledUnknownError = mr.DisabledUnknownError
ModelRegistryError = mr.ModelRegistryError
assert_not_disabled = mr.assert_not_disabled
glob_match = mr.glob_match
id_disabled = mr.id_disabled
id_names = mr.id_names
load_disabled = mr.load_disabled
load_registry = mr.load_registry
match_disabled = mr.match_disabled
model_disabled = mr.model_disabled
names_of = mr.names_of
normalize_disabled = mr.normalize_disabled
rotation_chain_for = mr.rotation_chain_for


# ---------------------------------------------------------------- 辅助（夹具）
def _point_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str | None,
) -> Path:
    """把 ``TF_POOL_DISABLED`` 指到临时禁用表；``content is None`` ⇒ **不写文件**（造"不存在"）。"""
    path = tmp_path / "model-disabled.toml"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    monkeypatch.setenv("TF_POOL_DISABLED", str(path))
    return path


def _write_table(tmp_path: Path, patterns: tuple[str, ...]) -> Path:
    """写一份**合法**的临时禁用表（``disabled = [...]``）。"""
    rows = "".join(f'  "{p}",\n' for p in patterns)
    path = tmp_path / "model-disabled.toml"
    path.write_text("disabled = [\n" + rows + "]\n", encoding="utf-8")
    return path


BROKEN_TOML = 'disabled = ["glm-5*",\n'  # 括号没闭合 ⇒ TOMLDecodeError


# ---------------------------------------------------------------- 钉 1–5：glob
def test_glob_matches_star_across_slashes() -> None:
    """钉 1（判据 2）：``*`` **跨斜杠** —— ``"/" among them``（原件注释 `disabled.go:101-104`）。

    ★ 这是「禁用表 glob ≠ 文件路径 glob」的第一个证据：``*fable*`` 必须穿过
      ``anthropic/claude-fable-5`` 里那个 ``/``。
    """
    assert glob_match("*fable*", "anthropic/claude-fable-5") is True
    assert glob_match("*", "a/b/c") is True
    assert glob_match("a/*/c", "a/b/c") is True
    assert glob_match("*fable*", "anthropic/claude-glm-5") is False


def test_glob_question_mark_is_any_one_character() -> None:
    """钉 2（判据 3）：``?`` = **恰好一个**字符 —— 匹配单字符、不匹配空串、不匹配两个字符。

    ★ 这是与 `_glob_re` 的**分界钉**：那边 ``re.escape`` 把 ``?`` 当字面问号（有意更严），
      本函数照 magpie ``globMatch`` 把它当「任意一个字符」。两条语义**不可互换**。
      ⇒ 变异 2（把 ``?`` 的处理删掉、只支持 ``*``）必让本条红。
    """
    assert glob_match("?", "x") is True
    assert glob_match("?", "") is False
    assert glob_match("?", "xy") is False
    assert glob_match("a?c", "abc") is True
    assert glob_match("a?c", "ac") is False
    assert glob_match("a?c", "abbc") is False


def test_glob_bracket_is_literal_not_a_character_class() -> None:
    """钉 3（判据 4）：``[`` 是**字面**，不是字符类 —— ★ 这一条是「不照搬 `fnmatch`」的钉子。

    ★ 断言是**正反两向**的：``[abc]`` 匹配字面 ``[abc]`` **且** 不匹配 ``a``。
      `fnmatch` 在**前一个**方向就假（它把 ``[abc]`` 当字符类，匹配不了带方括号的字面串），
      所以这不是同义反复。⇒ 变异 1（换 `fnmatch.fnmatch`）必让本条红。
    """
    assert glob_match("[abc]", "[abc]") is True
    assert glob_match("[abc]", "a") is False
    assert glob_match("[abc]", "b") is False
    assert glob_match("x[0-9]y", "x5y") is False
    assert glob_match("x[0-9]y", "x[0-9]y") is True


def test_glob_double_star_backtracks() -> None:
    """钉 4（判据 5）：多星号要**回溯** —— ``a*b*c`` 对 ``aXbYc`` 真、对 ``aXbY`` 假。

    ★ 贪婪一支走不通时必须退回来重试（原件 ``star`` / ``mark`` 两个游标就是干这个的）：
      只会「每段找第一次出现」的贪心实现，在 ``a*b*c`` 对 ``aXbXcYc`` 这类输入上会假阴。
    """
    assert glob_match("a*b*c", "aXbYc") is True
    assert glob_match("a*b*c", "aXbY") is False
    assert glob_match("a*b*c", "abc") is True
    # ★ 贪婪退回：第一个 * 先吃掉 "Xb"，发现后面接不上再吐回来
    assert glob_match("a*b*c", "aXbXcYc") is True
    assert glob_match("*a*a*", "aa") is True


def test_glob_without_wildcards_is_exact_equality() -> None:
    """钉 5（判据 1）：没有通配符时**退化成 `pat == s`**，且 `glob_match` **不转大小写**。

    ★ 短路那一支（原件 ``if !strings.ContainsAny(pat, "*?") { return pat == s }``）与
      回溯一支在**行为上不可区分** —— 所以本条钉的是它的**可观察后果**：
      没有通配符的 pattern 只认逐字相等（``.`` / ``[`` / ``?`` 之外的一切都不是元字符）。
    ★ **大小写**（判据 1 后半）：转换发生在 `match_disabled` 里，`glob_match` 自己**不转** ——
      所以 ``glob_match("GLM-5.3", "glm-5.3")`` 是 **False**。这一条把「顺手在
      `glob_match` 里 lower 一下」那种实现钉死（那样 `match_disabled` 就会转两次）。
    """
    assert glob_match("glm-5.3-flash", "glm-5.3-flash") is True
    assert glob_match("glm-5.3-flash", "glm-5.3") is False
    assert glob_match("glm-5.3-flash", "GLM-5.3-flash") is False  # 不转大小写
    assert glob_match("a.b", "axb") is False  # '.' 不是正则元字符
    assert glob_match("a.b", "a.b") is True


# ---------------------------------------------------------------- 钉 6–8：三种名字
def test_names_of_gives_two_names_for_a_bare_id() -> None:
    """钉 6（判据 6）：裸 model **只有两档** —— ``model`` 与 ``provider/model``（没有第三档）。

    ★ 与钉 7 是**同一个函数、不同的输入形状**（裸名 vs 带斜杠名），所以两条合起来才能定位
      「哪一档名字没了」：变异 5（删掉 `LastIndex` 那一段）会让钉 7 红、钉 6 **仍绿** ——
      单看钉 7 就不知道是不是把函数整个改坏了。
    """
    assert names_of("anthropic", "claude-fable-5") == (
        "claude-fable-5", "anthropic/claude-fable-5")
    assert names_of("", "claude-fable-5") == ("claude-fable-5",)
    # 首尾空白照原件 TrimSpace 掉
    assert names_of("anthropic", "  claude-fable-5  ")[0] == "claude-fable-5"


def test_names_of_gives_three_names_for_a_slashed_id() -> None:
    """钉 7（判据 7）：带斜杠的 model **三档** —— 第三档是 `LastIndex("/")` **之后**那段。

    ⇒ 变异 5（删掉 ``LastIndex`` 那一段）必让本条红（钉 6 仍绿）。
    """
    assert names_of("openrouter", "anthropic/claude-fable-5") == (
        "anthropic/claude-fable-5",
        "openrouter/anthropic/claude-fable-5",
        "claude-fable-5",
    )
    # 尾段在匹配侧真的生效
    assert match_disabled(["claude-fable-5"], names_of(
        "openrouter", "anthropic/claude-fable-5")) == "claude-fable-5"


def test_id_names_gives_three_different_names() -> None:
    """钉 8（判据 8）：**裸 id** 的第三档是 ``Cut("/")`` **第一刀之后** —— 与 `names_of` 不同。

    ★ 与钉 7 的差别必须**可断言**（设计原件原话）：
      · `names_of` 的 ``provider`` 是**入参**，第 2 档 = ``provider + "/" + model``（**加**）；
      · `id_names` 的 provider 是**切出来的**，第 3 档 = ``Cut`` 后那段（**切**）。
      拿错一个，本条立刻红。
    ★ 顺带钉判据 18 的 docstring 义务：`id_disabled` 必须**写明** `idOff` 十步里缺哪四步
      （pool 没有「组」⇒ 第 5/6/7 步无落点；没有 resolver ⇒ 第 9 步无落点）。
    """
    assert id_names("openrouter/anthropic/claude-fable-5") == (
        "openrouter/anthropic/claude-fable-5",   # id 本身
        "claude-fable-5",                        # LastIndex 之后
        "anthropic/claude-fable-5",              # Cut 第一刀之后
    )
    assert id_names("glm-5.3-flash") == ("glm-5.3-flash",)  # 没斜杠 ⇒ 只有一档
    # ★ 与 names_of **不是同一个函数**：同一个字符串，两边的第 2/3 档形状不同
    assert names_of("openrouter", "anthropic/claude-fable-5") != id_names(
        "openrouter/anthropic/claude-fable-5")
    # ★ 判据 18：docstring 必须点清缺的步
    doc = id_disabled.__doc__ or ""
    for missing in ("第 5 步", "第 6 步", "第 7 步", "第 9 步"):
        assert missing in doc, f"id_disabled 的 docstring 必须写明缺「{missing}」"


# ---------------------------------------------------------------- 钉 9–11：匹配与清洗
def test_match_disabled_returns_the_pattern_as_written() -> None:
    """钉 9（判据 9）：返回的是**原样的 pattern**，不是小写版 —— 让人拿原文去配置里改。

    ★★ **输入必须混大小写**（``"Claude-Fable*"``）：全小写的输入下，「返回原样」与「返回
      小写版」看不出差别 —— 那条钉子就是**假牙**。⇒ 变异 4（返回 ``lp``）必让本条红。
    ★ 顺带钉判据 10：空 pattern（trim 后为空）与空名字都**跳过** —— 没有这一支，
      ``""`` 会命中"空前缀"的每一条。
    """
    assert match_disabled(["Claude-Fable*"], ["claude-fable-5"]) == "Claude-Fable*"
    assert match_disabled(["  GLM-5.3  "], ["glm-5.3"]) == "  GLM-5.3  "
    # 判据 10：空 pattern / 空名字都跳过
    assert match_disabled(["", "  "], ["x"]) is None
    assert match_disabled(["*"], ["", "x"]) == "*"
    assert match_disabled([], ["x"]) is None


def test_normalize_disabled_dedupes_ignoring_case_and_keeps_order() -> None:
    """钉 10（判据 11）：trim、丢空、**忽略大小写**去重、**保序**、保留首次出现的大小写。

    ★ 逐字照 magpie ``normalDisabled``（`disabled.go:191-202`）：去重是 ``EqualFold``，
      **不做** ``ToLower`` —— 所以 ``"A"`` 被丢掉（与 ``"a"`` 同一条），但留下来的还是 ``"a"``。
    """
    assert normalize_disabled([" a ", "A", "", "b"]) == ("a", "b")
    assert normalize_disabled(["B", "a", "b", "A"]) == ("B", "a")  # 保序 + 忽略大小写
    assert normalize_disabled([]) == ()
    assert normalize_disabled(["  ", "\t"]) == ()


def test_normalize_disabled_enforces_the_two_limits_separately() -> None:
    """钉 11（判据 12）：**两条上限分开** —— 501 条抛一次、一条 301 字符抛一次。

    ★ 不许合并成一条判据（否则「501 条都很短」与「1 条超长」这两种错会给出同一句话，
      人拿着话去查时不知道该删条数还是删字符）。
    ★ 两个数都是**借来的**（`access/models.go:31` / `:26`），不是禁用表原件的事实 ——
      但既然定了就得是硬的：越界**响亮抛**，绝不静默丢（丢一条 = 悄悄少禁一条）。
    """
    too_many = tuple(f"m{i}" for i in range(MAX_DISABLED_PATTERNS + 1))
    with pytest.raises(ModelRegistryError) as excinfo:
        normalize_disabled(too_many)
    assert str(MAX_DISABLED_PATTERNS) in str(excinfo.value)
    assert "条" in str(excinfo.value)

    too_long = ("a" * (MAX_DISABLED_CHARS + 1),)
    with pytest.raises(ModelRegistryError) as excinfo:
        normalize_disabled(too_long)
    assert str(MAX_DISABLED_CHARS) in str(excinfo.value)
    assert "字符" in str(excinfo.value)

    # 恰好在界内：都不抛
    assert len(normalize_disabled(tuple(f"m{i}" for i in range(MAX_DISABLED_PATTERNS)))) == 500
    assert normalize_disabled(("a" * MAX_DISABLED_CHARS,)) == ("a" * MAX_DISABLED_CHARS,)


# ---------------------------------------------------------------- 钉 12–14：读不到 = 全禁
def test_load_disabled_absent_file_is_empty_not_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """钉 12（判据 13）：文件**不存在** ⇒ ``Disabled(patterns=(), unknown=False)``。

    ★ 与钉 13 是**成对**的（设计原件 §F84 变异 3 的理由）：只钉「坏了 ⇒ unknown」的话，
      一个**永远返回 unknown** 的懒实现也能过 —— 本条把它堵死。
    ★ 语义来源：原件「没配过 ``DisabledModels`` = 没禁用」。
    """
    path = _point_disabled(tmp_path, monkeypatch, None)
    assert not path.exists(), "前置：这份禁用表确实不存在（否则本条测的是别的东西）"
    table = load_disabled()
    assert table.patterns == ()
    assert table.unknown is False, "文件不存在 = 没禁用，**不是**不知道"
    # 没禁用 ⇒ 谁都不拒
    assert model_disabled("codebuddy", "glm-5.3-flash") is None
    assert_not_disabled("codebuddy", "glm-5.3-flash")  # 不抛


def test_load_disabled_broken_file_is_unknown_not_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """钉 13（判据 14）：文件**存在但解析失败** ⇒ ``unknown=True`` —— ★ **不是空表**。

    ★★ 这是本卡的核心判据，也是全篇最容易写成假牙的一条：
      **夹具必须先 `assert path.exists()`**，再断言 ``unknown is True``。
      夹具写错（比如 `tmp_path` 里其实没写文件）时，``load_disabled`` 会走"不存在"那一支
      ⇒ 本条、钉 14、钉 16 会**全绿地空转**（设计原件 §F84 变异 6 如实交代的陷阱）。
    """
    path = _point_disabled(tmp_path, monkeypatch, BROKEN_TOML)
    assert path.exists(), "★ 夹具前置：坏文件必须真的存在，否则本条空转"
    assert path.read_text(encoding="utf-8") == BROKEN_TOML, "★ 夹具前置：写进去的就是坏内容"
    table = load_disabled()
    assert table.unknown is True, "读到了却读不懂 = 不知道，**绝不当成没禁用**"
    assert table.patterns == ()
    # 形状不认识同样算「不知道」（fail closed），不是「空表」
    _point_disabled(tmp_path, monkeypatch, 'something_else = 1\n')
    assert load_disabled().unknown is True
    _point_disabled(tmp_path, monkeypatch, 'disabled = "glm*"\n')
    assert load_disabled().unknown is True
    _point_disabled(tmp_path, monkeypatch, 'disabled = ["ok", 1]\n')
    assert load_disabled().unknown is True


def test_unknown_table_refuses_every_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """钉 14（判据 15/16）：``unknown`` ⇒ 哨兵 `UNKNOWN`（非 None）**或**抛 —— **绝不放行**。

    ★ 三件事一起钉：
      ① `model_disabled` 返回**非 None** 的哨兵（调用方没法把"不知道"读成"没禁用"）；
      ② `id_disabled` 同样；
      ③ `assert_not_disabled` 抛 `DisabledUnknownError`，消息里必须有「不知道」与
         「不许当成没禁用」两句（fail-closed 的可读性判据）。
    ★ 「**every** model」是逐个数着过的：不是只试一个名字就算数。
    """
    path = _point_disabled(tmp_path, monkeypatch, BROKEN_TOML)
    assert path.exists(), "★ 夹具前置：坏文件必须真的存在，否则本条空转"
    assert load_disabled().unknown is True, "★ 夹具前置：这份表确实是 unknown"
    for model in ("glm-5.3-flash", "deepseek-v4.1-flash", "anything/at/all", "?", ""):
        assert model_disabled("codebuddy", model) == UNKNOWN, model
        assert model_disabled("codearts", model) == UNKNOWN, model
        with pytest.raises(DisabledUnknownError) as excinfo:
            assert_not_disabled("codebuddy", model)
        msg = str(excinfo.value)
        assert "不知道" in msg, msg
        assert "不许当成没禁用" in msg, msg
    for model_id in ("glm-5.3-flash", "deepseek-v4.1-flash", "anything/at/all", "?"):
        assert id_disabled(model_id) == UNKNOWN, model_id
    # ★ 判据 18 的**顺序**钉：`gateway/disabled.go:50-88` 的 ``idOff`` 第 2 步（空串）
    #   排在**第 3 步（不知道）之前** —— 所以一条**空 id** 在 unknown 表下仍回 None。
    #   这不是放行：空 id 根本不是一个模型名，而且这个顺序是照原件抄的。
    assert id_disabled("") is None, "第 2 步（空串）先于第 3 步（unknown）—— 照原件顺序"
    assert id_disabled("   ") is None, "TrimSpace 之后为空，同样走第 2 步"
    assert UNKNOWN is not None


# ---------------------------------------------------------------- 钉 15–17：拒绝的理由
def test_hit_error_names_the_pattern_and_the_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """钉 15（判据 17）：命中时抛的异常里必须有**原样的 pattern** 与被打的 id。

    ★ 对照原件三条文案里都有 ``%q`` 的 ``pat``：人拿着这句话就能直接去配置里搜那一条。
      只给一句「被禁了」等于让人翻整份表。
    """
    _point_disabled(tmp_path, monkeypatch, 'disabled = ["GLM-5*"]\n')
    with pytest.raises(ModelRegistryError) as excinfo:
        assert_not_disabled("codebuddy", "glm-5.3-flash")
    msg = str(excinfo.value)
    assert "GLM-5*" in msg, f"消息里要有原样的 pattern；实际={msg!r}"
    assert "glm-5.3-flash" in msg, f"消息里要有被打的 id；实际={msg!r}"
    assert "codebuddy/glm-5.3-flash" in msg, "provider 给了就写全"
    assert str(mr.disabled_path()) in msg, "还要说清去哪个文件改"

    # 没命中 ⇒ 安静返回（不抛）
    assert_not_disabled("codebuddy", "deepseek-v4.1-flash")


def test_disabled_wins_over_whitelist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """钉 16：**既在批准集里又被禁用** ⇒ `assert_not_disabled` 必须抛（禁用赢）。

    ★ 这是本卡最要紧的一条语义：禁用**不是**批准集的另一半，而是**另一个维度的拒绝**。
      「在注册表里」永远不等于"能用"——把禁用表塞进 ``[[model]]`` 会让"批准但禁用"
      **不可表达**（禁令 2）。
    ★ 两半都要钉：
      ① 命中一条 pattern ⇒ 抛 `ModelRegistryError`（此处变异 4 会顺带改它的文案）；
      ② 表是 **unknown** ⇒ 同样抛（此处变异 6「unknown 时放行」必红）——
         批准集再干净也压不住「不知道」。
    """
    registry = (
        '[[model]]\n'
        'alias   = "deepseek-v4.1-flash"\n'
        'pool    = "codebuddy"\n'
        'id      = "deepseek-v4.1-flash"\n'
        'default = true\n'
    )
    (tmp_path / "model-registry.toml").write_text(registry, encoding="utf-8")
    monkeypatch.setenv("TF_MODEL_REGISTRY", str(tmp_path / "model-registry.toml"))
    monkeypatch.delenv("TF_POOL_DISABLED", raising=False)
    # 禁用表落在**注册表旁边**（默认位置，不设 DISABLED_ENV）
    table_path = tmp_path / "model-disabled.toml"
    table_path.write_text('disabled = ["deepseek*"]\n', encoding="utf-8")
    assert table_path.exists(), "★ 夹具前置：禁用表与注册表同目录"

    # 前置：这个模型确实在**批准集**里
    assert "deepseek-v4.1-flash" in rotation_chain_for("codebuddy")
    # ① 批准但禁用 ⇒ 拒
    with pytest.raises(ModelRegistryError) as excinfo:
        assert_not_disabled("codebuddy", "deepseek-v4.1-flash")
    assert "deepseek*" in str(excinfo.value)

    # ② 批准但**不知道** ⇒ 同样拒（禁用赢，unknown 也赢）
    table_path.write_text(BROKEN_TOML, encoding="utf-8")
    assert table_path.exists(), "★ 夹具前置：坏文件必须真的存在"
    assert load_disabled().unknown is True, "★ 夹具前置：这份表确实是 unknown"
    assert "deepseek-v4.1-flash" in rotation_chain_for("codebuddy"), "前置：它仍在批准集里"
    with pytest.raises(DisabledUnknownError):
        assert_not_disabled("codebuddy", "deepseek-v4.1-flash")


def test_registry_and_disabled_are_read_from_separate_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """钉 17：两张表、两个文件、**不互相污染**（改禁用表不动 `load_registry()`）。

    ★ 咬的是「禁用表若另存一份就是第二真源」的反面：它们**必须**是两个文件
      （批准 / 拒绝两个维度），但**不许**互相影响读数。
    ★ 顺带钉 TOML 第 4 条纪律的一半：禁用表**默认就落在注册表旁边**
      （``disabled_path()`` 跟着 ``registry_path()`` 的目录走）。
    """
    registry = (
        '[[model]]\n'
        'alias   = "deepseek-v4.1-flash"\n'
        'pool    = "codebuddy"\n'
        'id      = "deepseek-v4.1-flash"\n'
        'default = true\n'
    )
    (tmp_path / "model-registry.toml").write_text(registry, encoding="utf-8")
    monkeypatch.setenv("TF_MODEL_REGISTRY", str(tmp_path / "model-registry.toml"))
    monkeypatch.delenv("TF_POOL_DISABLED", raising=False)

    before = load_registry()
    # ★ 默认位置 = 注册表同目录（不是 gates/diag/）
    assert mr.disabled_path() == tmp_path / "model-disabled.toml"
    assert "gates" not in str(mr.disabled_path()).replace("\\", "/").split("model-disabled")[0]
    # 禁用表：不存在 ⇒ 没禁用
    assert load_disabled().unknown is False

    # 加一份禁用表 ⇒ 注册表读数**一个字不变**
    (tmp_path / "model-disabled.toml").write_text('disabled = ["glm*"]\n', encoding="utf-8")
    assert load_disabled().patterns == ("glm*",)
    assert load_registry() == before, "改禁用表不许影响注册表读数"
    assert [e.alias for e in load_registry()] == ["deepseek-v4.1-flash"]

    # 反向：禁用表不动，改注册表 ⇒ 禁用表读数不变
    (tmp_path / "model-registry.toml").write_text(
        registry + (
            '[[model]]\n'
            'alias   = "glm-5.3-flash"\n'
            'pool    = "codebuddy"\n'
            'id      = "glm-5.3-flash"\n'
            'default = false\n'
        ), encoding="utf-8")
    assert load_disabled().patterns == ("glm*",), "改注册表不许影响禁用表读数"
    assert len(load_registry()) == 2


# ---------------------------------------------------------------- 钉 18：注释与源码对上
def test_glob_re_docstring_no_longer_claims_a_difference_that_does_not_exist() -> None:
    """钉 18：`_glob_re` 的 docstring **不再**声称一条不存在的差别（本卡唯一的文档钉）。

    ★ 为什么值得钉文档：原注释说「本实现把字面片段 `re.escape()` 掉，magpie 那边 `(` / `.`
      是正则元字符、编不过就 panic」—— 而 magpie `compileGlob`
      （`internal/access/models.go:99-105`）**同样** `regexp.QuoteMeta` 转义。
      错的不是实现（实现是对的），是这条来处；留着它，后面每一波都会有人照它推理。
    ★ 两件事一起钉：
      ① 旧的那句（含「唯一差别」四字）**没了**，新的来处（「QuoteMeta」与「?」）**在**；
      ② 同文件的 `glob_match()` **存在** —— 改注释不能顺手删掉实现（判据 1 全部挂在它身上）。
    """
    doc = mr._glob_re.__doc__ or ""
    assert "唯一差别" not in doc, f"旧注释那句必须删掉；实际={doc!r}"
    assert "QuoteMeta" in doc, "必须点明 magpie 同样 QuoteMeta 转义"
    assert "?" in doc, "必须点明两边的差别**只在 `?`**"
    assert "有意为之" in doc, "必须写明「`?` 更严是本模块有意为之、不许改回去」"
    # 新函数必须在（注释改了、实现没加 = 半张卡）
    assert hasattr(mr, "glob_match")
    assert mr.glob_match("?", "x") is True  # 与 `_glob_re` 的 `?` 口径**不同**
    assert mr._glob_re("?x").match("x") is None, "`_glob_re` 把 `?` 当字面（有意更严）"
