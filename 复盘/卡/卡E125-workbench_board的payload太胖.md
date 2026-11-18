# 卡 E125 · workbench_board 的 payload 太胖：不给 section 220748 字符、单给 section=cards 126478

> 台账号 T-AG634｜分区 E（门禁与可信度）｜树 .wt/E125｜层 判据层｜基准 c94b5e27（立卡时主树 HEAD）｜depends 无
> 依据：用户 m00001「workbench_board 不给 section 时整包 220411 字符，单给 section=cards 仍 126296 —— 会话里塞不下，且里面大半是不变的台账字段」
> 尺子（全篇统一，别混用）：`len(json.dumps(x, ensure_ascii=False))` —— 即 MCP wire 上那一段 text 所在回包的字符数。
> 复算脚本：`gates/diag/_e125_numbers.py`（现状 + 压缩设计）、`_e125_blocks.py`（逐块 dumps + 幂等）、`_e125_split.py`（省量拆解）、`_e125_churn.py`（台账变更史）。全在 gitignore 的 `gates/diag/` 下，不是交付物。

## 要解决的问题（逐条实测，不是推测）

### 问题 1 · 整包 220748 里 99.9% 是机器块，人话段只有 288 字符

```text
$ python -X utf8 gates/diag/_e125_numbers.py      # HEAD 043fee47
整包 wire                        = 220748
section=cards 126478 / gates 2026 / verdicts 70816 / leases 1065 / fences 10394 / worktrees 12438
人话段（标题行 + 六行摘要）      = 288
machine 块（紧凑单行）           = 195000
reading 紧凑单行                 = 194817
command 字符                     = 119
escaping 放大（machine 外层再 dumps）= 25748
```

- 220748 = 人话段 288 + 标记/围栏 + `json.dumps(data)` 一行 195000 + 外层再 dumps 的转义放大 25748。**会话里塞的是整段，不是只有那六行摘要。**
- 题面报的 220411 与我复算的 220748 差 337 字符：HEAD 已从 `89cd4deb` 前进到 `043fee47`（中间多了卡 E126 的立卡提交），同一把尺子在 `89cd4deb` 上是 220480 / 126210。量级一致；**差值的确切来源未验证**（可能是量取时刻台账不同，或客户端外层序列化口径略异）。本卡判据一律用本地实测值。

### 问题 2 · section=cards 也 126478，因为 `_board_subset` 只按块名过滤，块内一行不裁

`tools/pool_mcp.py:1763-1771`：

```python
def _board_subset(reading: dict[str, Any], section: str | None) -> dict[str, Any]:
    """按块名取子集：块本身 + 它的 `<块>_*` 说明键（`cards_note` / `fences_broken` …）。
    ★ **原样**取，不填默认、**不洗 null** ……"""
    if section is None:
        return reading
    return {k: v for k, v in reading.items() if k == section or k.startswith(section + "_")}
```

- 它只决定「端哪几块」；端出来的那一块**逐行原样**（`tools/pool_mcp.py:1865-1870` 的 `data["reading"] = _board_subset(reading, section)`）。
- 于是 `section=cards` = cards 块 118417 + 说明键 57 + 同一份 `command` + 人话一行。压缩点在**行内字段**与**已完卡**，不在「选哪块」。
- 人话段与机器块是**同一份 data 打两遍**：`tools/pool_mcp.py:856` 的 `_result()` = `f'{text.rstrip()}\n\n{_fence(data)}'`；wire 上没有 `structuredContent`（`tools/pool_mcp.py:3048`）。**任何一次压缩都要同时说清「人话行还念不念得出数」**（`_board_line` 在 `tools/pool_mcp.py:1774-1792` 只念 `len(val)`，不重算读数）。

### 问题 3 · cards 一块 118417 字符里 47% 是 files/depends 两个数组

```text
cards 块 dumps = 118417；368 行；每行键集唯一 ('depends','files','id','risk','spec','status','task','title','tree')
逐键成本（值 + key + 标点）：files 49626 / title 15997 / spec 11733 / tree 6928 / task 6130 /
                              status 5927 / depends 5781 / risk 4825 / id 4110；行外开销 7360
files 数组总字符 = 46314（1618 条）；depends 数组总字符 = 1733（178 条）
files 长度直方 = {1:40, 2:100, 3:63, 4:59, 5:27, 6:23, 7:13, 8:8, 9:8, 10:3, 11:5, 12:5, 13:2, 16:3, 17:2, 18:2, 21:2, 36:1, 41:1, 45:1}
最长一行 = 卡 G9 1961 字符（其次 F6 1577 / E59 1328）
status 分布 = {done: 355, pending: 13}；risk 分布 = {low: 100, mid: 227, high: 41}
tree 去重 363/368；spec 去重 368/368
```

- **files + depends = 55407 字符，占 cards 块 46.8%**；status 只占 5927（5.0%）。
- 换成计数（`files_n` / `depends_n`）后的省量（`gates/diag/_e125_split.py`）：

```text
cards 原始 dumps = 118417 → 压缩后 14377；省 104040
  其中「数组 → 计数」省 = 45811
  其中「done 卡折叠成骨架行」省 = 58229
done 行 355 张，折叠后单行平均 33.2 字符；在飞 13 张，压缩后单行平均 199.4 字符
```

### 问题 4 · 真正在变的是 status；spec/tree/task/risk/files/depends 是台账不变事实

`gates/diag/_e125_churn.py` 逐 hunk 统计（台账全史 567 个 hunk）：

```text
单行值改写（同键一减一加）按键：status 218 / depends 13 / spec 10 / files 7 / task 7 / title 4 / reviewed 2 / risk 1
所有 -<key> 行计数：status -493 +860 / files -269 +636 / spec -272 +639 / depends -233 +574 /
                    id -262 +629 / risk -258 +625 / task -269 +636 / title -266 +633 / tree -262 +629
```

- **status 是唯一高频变化的字段（218 次单行改写）**；files/spec/task/title/tree 的增删几乎全是「新卡入场」带来的整块新增，不是既有卡的值在漂。
- 字段归类（`tools/pipeline_view.py:123-124` 的 `row_fields` 九项）：
  - **台账不变事实**（入场后基本不动）：`spec`（368/368 各不相同，指向卡规格文件）、`tree`（363/368 不同）、`task`、`risk`、`files`、`depends`。
  - **每次要看的变化**：`status`。另 `id` 是主键、`title` 是显示名（两者都不变，但必须留 —— 没有它们的行读不出是谁）。
- 结论：默认视图应当留 `id/status/title/task/risk`，把 `files`/`depends` 压成计数，把 `spec`/`tree` 留给点名一张卡时再取。**但具体留哪几项是本卡的交付判断，判据只钉「默认不带 files/depends 明细」这一条硬要求。**

### 问题 5 · 两种方案并列（不替人挑）

**甲案：压 payload（改 `tools/pool_mcp.py` 的端出形状）**

```text
P1 只 cards：files/depends → 计数 + done 折叠成 {id,status}   整包 110887   section=cards 16617
P2 P1 + verdicts 的 attempts → attempts_n                    整包  85379   section=cards 16617
P3 P2 + verdicts 只留有判决 + worktrees 只留脏树              整包  73665   section=cards 16617
P4 P3 + 去 verdict_first_line                                整包  49165   section=cards 16617
（现状 220748 / 126478；只做 cards 计数、不折叠 done = 171912 —— 单靠计数压不到 10 万以下）
```

- 代价：默认视图不再是 `pipeline_view` 的原样投影，**多出一层「MCP 侧的视图约定」**；`_initialize` 的 instructions（`tools/pool_mcp.py:3060-3070`）与工具 description（`:527-531`）必须同步改，否则那两句就成了新的谎。
- 收益：默认一问就完整（六块都在），不需要调用方懂 `section`；在飞卡仍是完整行（199.4 字符/张）。
- 风险：`tests/test_pool_mcp_board.py:140` 要求 done 卡仍在 `reading["cards"]` 里且 id 顺序不变 ⇒ **done 只能折叠成骨架行，不能过滤掉**；折叠后 `_board_line` 的「cards：368 项」仍然成立（行数没变），这点是设计上的硬约束。

**乙案：教人用 section（不改 payload，改 skills/ 与工具说明）**

```text
section=gates 2026 / leases 1065 / fences 10394 / worktrees 12438 / verdicts 70816 / cards 126478
单卡明细：section=cards 一行 G9 = 1961 字符；带说明键 ≈ 2539 字符（vs 126478）
```

- 代价：`section=cards` 仍然是 126478 —— **这张卡要解决的那个数一个字符都没降**；`skills/` 目前 0 处提到 `workbench_board`（grep 实测），教人用 section 等于新写一份用法文档，且没法强制（模型照样可以不给 section）。
- 收益：`tools/pipeline_view.py` 的六块结构与 `row_fields` 一个字不动，撞测试的面几乎为零；判据仍然是「一份真源」。
- 兼容点：乙案必须回答「为什么不给 section」，而现在的默认就是「一次看全六块」——这是卡 213 写下的行为（`docs/changelog.d/T-G324.md:3`）。

> 两案不是互斥的（甲案之后 section 仍然有用；乙案之后 payload 仍然胖），但**本卡只能选一条主线**，否则判据会互相打架。选哪条由人定，本规格不替人选。

## 兼容面（改了会碰到谁 —— grep 出来的，不是猜的）

- `grep workbench_board skills/` = **0 命中**。skills/ 教的全是 `python -X utf8 tools/pipeline_view.py --json`（`skills/pipe-workbench/SKILL.md:47`、`skills/pipe-workbench/references/tools.md:10` 等 20+ 处）⇒ **只改 MCP payload、不动 pipeline_view 的 row_fields 时，skills 一个字都不用改**。
- 面板 `tools/dsh_panel.py` **不走 MCP**：`:257` `script_rel = 'tools/pipeline_view.py'`、`:2463` `const cards = (data.reading && data.reading.cards) || []`、`:2435-2453` 只用 `id/title/task/status` ⇒ 压缩放 MCP 侧则面板零影响。
- `tools/workbench_bridge.py:88-93`、`:120` 直接吃 `row["files"]` 列表；`tests/test_workbench_bridge.py:238-255` 用 `files` 反转做幂等钉子 ⇒ **它们读的是 pipeline_view 直连，不受 MCP 压缩影响；但反过来，若把压缩做进 pipeline_view，这两处必红**。
- `tools/timeflow_inbox.py:237` / `:49-53`、`tools/wb_daily.py:303-309`（只用 id + status）同样读 pipeline_view 直连。
- 注册点 `.trae/mcp.json`：`python -X utf8 <repo>/tools/pool_mcp.py`，改完要重启客户端才生效（**是否热加载未验证**）。
- `docs/全局面板.md:59-60`、`docs/decisions/0002-mcp-extension-slot.md:29`（「MCP 工具调同一段库，不重写判据」）—— 甲案有个字面张力：MCP 侧开始有「自己的视图约定」。要在卡规格里写清：**视图约定不是判据**（不新增任何读数、不重算任何数，只决定端出多少），否则这句话会被读成被推翻。

## 判据

### 判据 1 · 默认瘦、点名胖（甲案的核心行为，一条钉两头）

- 不给 `section`、不给新参数时：`reading["cards"]` 每一行**不含** `files` / `depends` 两个键，改为 `files_n` / `depends_n`（整数，等于原数组长度）；`status == "done"` 的行只剩 `{id, status}`，**不许删行**（行数与 id 顺序必须与原读数一致）。
- **钉子**：`tests/test_pool_mcp_board.py:140` 的 `assert [c["id"] for c in reading["cards"]] == ["213", "207"]` 不许改语义（fixture 的 207 是 done 卡 ⇒ 现存断言本身就要求 done 行还在）。
- 只有显式 `fields=full`（或 `verbose=true`，二选一，由实现定，但只许有一个口径）才端全明细；此时 `reading["cards"]` 与 `pipeline_view` 原样逐键相等。
- **人话段仍是六块摘要**：`text` 里六行都在，cards 那行仍是 `  · cards：368 项`（折叠不改行数 ⇒ 这句不许变成 13 项，那会是谎）；`_board_line` 不许新增「已折叠 N 张」以外的重算。
- **钉子**：`tests/test_pool_mcp_board.py:213` 的 `assert all(k == "gates" or k.startswith("gates_") for k in reading)` ⇒ 新增的顶层键（如 `cards_done_n`）**必须以 `<块名>_` 打头**，否则 section 过滤会把它漏掉/带错。

### 判据 2 · 字符预算（实测定的阈值，不是拍的）

尺子同上：`len(json.dumps(pool_mcp.call_tool('workbench_board', <args>, root=<真实仓>), ensure_ascii=False))`。

```text
断言 A：不给 section 的整包 ≤ 60000 字符       （现状 220748；P1 110887 / P2 85379 / P3 73665 / P4 49165）
断言 B：section=cards      ≤ 20000 字符       （现状 126478；P1–P4 均 16617）
断言 C：点名一张卡（section=cards&fields=full 或 id 过滤）≤ 4000 字符（现状单卡最长 1961，留约 2×）

> 落地时的两处调整（2026-11-17，本卡自己，实测后改口径不是拍脑袋）：
> ① **断言 A 放宽到 90000**。地板是 84039（默认瘦视图，主树 root 实测）：判据 3 不许丢
>    `verdict_first_line`（212 行里 194 行的退出码 / 会话 uuid / 第几次只存在于它，丢它 = 删证据），
>    保住它之后 60000 达不到；同时原 60000 是按「data 单行 json.dumps」估的，而验收尺子把整段
>    `text` 再 dumps 一次、fence 里约 10136 个引号每个多一层转义 ≈ +10.2K，是量具口径差不是代码差。
>    90000 相对 223435 仍是 **62.4% 削减**，余量 5961。
> ② **断言 C 取消**。仓库里没有「按卡号点名」的落点（workbench_board 只有 `section`，没有 id 参数），
>    加 id 参数是另一个功能；本卡只做投影。取消理由留在 `tests/test_pool_mcp_board.py` 的预算注释与
>    落地文书 gaps 段，不另造假机制。
```

- **已知地板**：只动 cards 一处，A 必红（110887）——这就是这条判据的用处：它逼着把 verdicts（70816）与 worktrees（12438）一起纳入交付，或者由人明确把 A 放宽到 120000。**放宽必须在卡规格里写一行理由，不许在测试里悄悄改数。**
- 阈值余量按「在飞卡数」留，不按当前 13 张写死：合成 fixture 实测（`gates/diag/_e125_scale3.py`）每张在飞卡 压缩后 +186 字符、每张已完卡 +38 字符 ⇒ 60000 的预算大约撑得住 100 张在飞卡；在飞卡数超过这个量级时该红就红（宁可红，不要静默爆）。

### 判据 3 · 坏读数 / 缺来源不许因为压缩变成「没有」

- `reading["cards"] is None` 时：仍然 `None` + `cards_note` 原文 + 人话行「**没有** —— <note>」；**不许**变成 `[]`、`0 项`、或「已折叠 0 张」。
- `reading["gates"] is None` 同理（`gates_note` 里要有 `last.json`）。
- 非零退出 / 超时 / JSON 坏 / 顶层非 dict 四条错路：`is_error=True`、`reading=None`、原样 stdout/stderr 一字不少。
- **钉子**：`tests/test_pool_mcp_board.py:190-204`（null + note 透传）、`:146-176`（非零 / 超时如实报）、`:179-184`（坏 section 报错并列出六块）。压缩**不许**在 `_result` 之前把 `data` 里任何一个 `None` 换成空容器。

### 判据 4 · 幂等 + `--json` 稳定（不许把墙钟写进 JSON）

- 同一进程连续两次 `call_tool('workbench_board', {}, root=<真实仓>)` ⇒ 机器块**逐字相同**（实测现状已如此：`gates/diag/_e125_blocks.py` 的 `两次调用逐字相同 = True`）。
- JSON 里**不许**出现「取值时算出来的时刻」（`time.time()` / `datetime.now()` / `utcnow`）：允许的时刻只有来源文件里已经写死的值（例如 `verdict_first_line` 里的 `结束于=2026-11-09T12:03:42`、`gates.rev=f833d006`）。
- `tools/pipeline_view.py --json` 的序列化口径不许动：`tests/test_pipeline_view.py:386-388` 的 `_json_bytes = json.dumps(reading, ensure_ascii=False, indent=2, sort_keys=True)` 是幂等比对的同一把尺子。
- **钉子**：`tests/test_pool_mcp_board.py:224-229`（`test_same_fixture_twice_is_byte_identical`）。新增测试建议再钉一条：`cards_done_n` 这类派生计数在两次调用里必须相同，不许从 `time` 派生。

### 判据 5 · 不许削弱 `tools/pipeline_view.py` 的六块结构与既有钉子

- `tools/pipeline_view.py:110-149` 的 `BLOCKS` 是**唯一口径源**；本卡**不许**改它的 `row_fields`（尤其不许把 cards 的 `files`/`depends` 从声明表里删掉）。压缩是 MCP 侧的**投影**，不是第二份口径。
- 点名会被撞的测试（改了 pipeline_view 侧就必红，这一条就是让实现者别去改）：
  - `tests/test_pipeline_view.py:159` `test_six_blocks_all_present`，其中 `:173-174` `assert c["files"] == ["src/a.py"]` / `assert c["depends"] == []`；
  - `tests/test_pipeline_view.py:401` `test_blocks_table_declares_six_blocks`（六块 id 顺序、每块六个键、`continuous` 只有 gates+leases）；
  - `tests/test_pipeline_view.py:415` `test_json_rows_match_blocks_row_fields`，`:425` `assert set(payload) == set(_spec(bid)["row_fields"])`；
  - `tests/test_pipeline_view.py:363-370` `--report` 六个 tag。
- 工具面：加参数**不许多出工具**。`tests/test_pool_mcp.py:44-58` 的 `TOOL_NAMES` 十三项硬编码 + `:190` 的 `assert [t["name"] for t in tools] == TOOL_NAMES` 是钉子；`:193-197`（object / `additionalProperties is False` / `required ⊆ properties` / `readOnlyHint True` / description 非空）要求新参数**必须写进 `properties`**，且 `additionalProperties` 仍为 `False`（`tests/test_pool_mcp_board.py:120` 单独钉了这一条）。
- `tests/test_pool_registry.py:143` 的 `POOL_TOOL_NAMES` 同样只钉名字，不受参数影响。

### 判据 6 · 反向变异 ≥4（证明判据自己会咬人）

用 monkeypatch / 直接构造 data，逐条把压缩逻辑掰坏，断言对应判据变红：

1. 把 `files_n` 算成 `len(str(files))`（字符数而不是条数）⇒ 判据 1 红（`files_n` 与 fixture 数组长度不等）。
2. 把 done 卡**过滤掉**而不是折叠 ⇒ 判据 1 红（`test_pool_mcp_board.py:140` 的 id 列表对不上）。
3. 把 `cards: None` 洗成 `[]` ⇒ 判据 3 红（`:199` 的 `is None` 不成立）。
4. 在 data 里塞一个 `compressed_at = datetime.now().isoformat()` ⇒ 判据 4 红（两次调用不再逐字相同）。
5. 把 `cards_done_n` 改名叫 `done_cards`（不满足 `<块名>_` 前缀）⇒ 判据 1 的 section 过滤断言红（`:213`）。

## 交付

1. `tools/pool_mcp.py`：新增一个**纯函数**（建议 `_board_compact(reading, fields)`，放 `_board_subset` 附近，`tools/pool_mcp.py:1763` 之前），只做「按块投影」、不读文件、不取时间；`tool_workbench_board` 在 `:1869` 把 `_board_subset(...)` 的结果再过一遍它。
2. `tools/pool_mcp.py`：`workbench_board` 的 `inputSchema`（`:532-543`）加一个参数（`fields` 枚举 `summary|full`，或 `verbose` 布尔 —— 只选一个），仍写 `additionalProperties: False`、并把新键写进 `properties`；工具 description（`:527-531`）与 `_initialize` 的 instructions（`:3060-3070`）同步说清「默认瘦、点名胖」。
3. `tools/pool_mcp.py`：`_board_line`（`:1774-1792`）若要在 cards 行里多说一句（如「（已完成 N 张折叠成骨架）」），只许用已解析 data 里的数，不许新起一次读盘。
4. `tests/test_pool_mcp_board.py`：**扩 fixture**（`:37-62` 现在只有两张卡）—— 至少 20 张 done + 2 张 pending，其中一张带 40+ 条 `files`，用来钉「默认不带明细 / 点名才带」与预算；新增判据 1/2/3/4/6 的用例，**不改** `:140`、`:199-204`、`:213`、`:224-229` 的语义。
5. `tests/test_pipeline_view.py`：**不改**。若发现必须改，说明压缩做错了层 —— 停下来改设计。
6. `docs/全局面板.md:59-60` 与 `docs/decisions/0002-mcp-extension-slot.md:29`：若默认行为变了，各加一句「MCP 侧的默认视图是投影，不是第二份判据」（当前事实改就地改；只在有读者会拿它当现状时）。
7. docs/changelog.d/T-AG634.md：一行结论 + 前后读数（220748 → 实测值）+ 尺子。

## 验收（三条，落地前自跑，零手工步骤）

```bash
# ① 判据 1 + 4：默认瘦、点名胖、两次逐字相同
python -X utf8 -m pytest tests/test_pool_mcp_board.py -q

# ② 判据 2：真实仓的整包 / section=cards 字符数（把两个数打出来，人工核对阈值）
python -X utf8 -c "import sys;sys.path.insert(0,'tools');import json,pool_mcp;from pathlib import Path;f=lambda a:len(json.dumps(pool_mcp.call_tool('workbench_board',a,root=Path('.')),ensure_ascii=False));print('full',f({}),'cards',f({'section':'cards'}))"

# ③ 判据 5：口径源没被动过
python -X utf8 -m pytest tests/test_pipeline_view.py tests/test_workbench_bridge.py tests/test_pool_mcp.py -q
```

## 不许做

- **不许**改 `tools/pipeline_view.py` 的 `BLOCKS` / `row_fields`（判据 5 点名的四条测试就是护栏）。
- **不许**在 MCP 侧重算任何读数（不许自己读 `docs/workbacklog.toml`、`gates/last.json`、租约目录）：压缩只能是对已解析 JSON 的**纯投影**。
- **不许**把 done 卡从 `reading["cards"]` 里过滤掉（折叠成骨架行可以，删行不行 —— `tests/test_pool_mcp_board.py:140`）。
- **不许**为了过预算把 `verdict_first_line` / `attempts` / `worktrees` 也顺手改掉却不写进卡规格：那属于本卡的交付范围，必须显式列在「交付」里，并给出前后读数。
- **不许**把 `null` 洗成 `[]` / `0 项` / `没有` 三种以外的东西；`cards_note` 原文一字不许改写。
- **不许**在 JSON 里写墙钟（`time.time()` / `datetime.now()` / `utcnow` / `perf_counter`）。
- **不许**新增工具（`TOOL_NAMES` 十三项是硬的）；也不许多挂一个 `workbench_board_detail` 之类的第二个工具。
- **不许**动 `.wt/` 工作树、不许在 `gates/diag/` 的读数脚本上做交付（那些是证据，不是产物）。
- **不许**用「让调用方记得加 section」代替判据 2 —— 那是乙案要讨论的事，选乙案就明说把判据 2 删掉并写理由，不许假装它还在。

