# 门禁自证（product 档 11 道）—— 哪些门真的会咬，哪些只能人工

> 立项：2026-10-27（父任务：证明 22 道门「每一道都真的会咬」，不只是「会跑」）。
> 本文书是 **product 档 11 道**那一半；全 22 门的主台账在姊妹件
> `gates/gate-selfproof.toml`（四列 `name` / `reverse_case` / `why_no_case` / `since`）。
> 一句话：**「会跑」是退出码存在；「会咬」是造对错时它退非零、并且点名你造的那个错。**

## 0. 口径：什么叫「会咬」

两条判据，缺一不算：

| # | 判据 | 只有这条说明什么 |
|---|---|---|
| ① | 造错时必须**退非零** | 只有 ① ="会跑" —— 它确实在跑，但抓没抓到不知道 |
| ② | 必须**点名**造的那个错（报出具体是哪条、哪个值） | 只有 ② ="会说话但不拦" —— 它把问题说得很清楚，然后照样退 0 |

所以每条自证都记三样东西：`probe`（可复现的造错命令）、`expect`（期望它红/退非零）、
`evidence`（一条**真实读数**：退出码或失败断言原文）。三样缺一，那一行就不算自证过。

## 1. 三件交付物

| 件 | 位置 | 作用 |
|---|---|---|
| 自证表 | `gates/gate-selfproof-product.toml` | 11 行 × 7 列（`door` / `kind` / `probe` / `expect` / `verified_at` / `evidence` / `residue`） |
| 钉子 | `tests/test_gate_selfproof_product.py` | 15 条：4 条钉表的形状（覆盖/读数/汇总），11 条**真的造错**跑一遍 |
| 本文书 | `docs/subsystems/ci/门禁自证-product.md` | 哪些能自证、哪些只能人工、为什么 |

跑钉子（必须 `--no-cov`，`pyproject.toml` 的 addopts 带 `--cov-fail-under=70`）：

```bash
python -X utf8 -m pytest tests/test_gate_selfproof_product.py -q --no-cov
```

★ **不带 `--no-cov` 会红，但红在覆盖率闸，不在这 15 条用例上。** 实测两次（2026-10-28）：

| 命令 | 结果 |
|---|---|
| `pytest tests/test_gate_selfproof_product.py --no-cov` | **`15 passed in 16.13s`**，退出码 0 |
| `pytest tests/test_gate_selfproof_product.py -q`（父任务原话） | `FAIL Required test coverage of 70% not reached. Total coverage: 37.04%`，退出码 1 |
| **对照**：`pytest tests/test_style_audit.py -q`（与本卡无关的既有文件，同样不带 `--no-cov`） | `FAIL Required test coverage of 70% not reached. Total coverage: 0.00%`，退出码 1 |

对照组证明：这条闸是 `pyproject.toml` 的 `addopts = "-q -m \"not acceptance and not chain\" --cov=timeflow --cov-fail-under=70"`
对**任何**单文件跑法都生效的全仓口径（覆盖率靠整趟 pytest 积累，单跑一个文件必然不达标），
与本文书这 15 条用例无关。仓内惯例也是带 `--no-cov` 单跑（`docs/changelog.md` 里多处同写法）。

## 2. 结论表（11 道，逐门）

| 门 | 档 | 怎么造反向 | 反向进了 pytest？ | 剩余盲区（`residue`） |
|---|---|---|---|---|
| `check_layers` | A | `--root` 换到合成小树，删一个域规格 | ✅ | none —— `--root` 是完整注入口 |
| `contrast` | A | `--css` 换一份把墨色调浅的副本 | ✅ | none —— `--css` 是完整注入口 |
| `style` | A | 纯函数 `collect()` 喂追加了孤儿字面量的 CSS | ✅ | none —— 判据与打印分离 |
| `ui_text` | A | 纯函数 `verdicts()` 喂一条 35 字长句 | ✅ | none —— `verdicts()` 是纯函数 |
| `commands` | A | 换模块常量 `cc.COMMANDS`，改一条路由 | ✅ | none —— 无 CLI 入参，换常量即可 |
| `ui_dom_probe` | A | 换根 + 改坏一个视图 | ✅ | DOM 桩不是真浏览器（不验布局、不验真实点击） |
| `proxy` | A | `--map` 换一份把 `last_verified` 推到 2020 的表 | ✅ | none —— `--map` 是完整注入面 |
| `lf1_live` | B | 真起 uvicorn + ASGI 中间件改写 complete 响应体 | ✅（0.7s） | 端口用 `free_port()` 现取，理论上仍可能抢占 |
| `web_live` | B | 换根 + 拆掉事件委托监听 | ❌（要 ~6s + 真起服务） | 13 组 `live_*` 真服务检查没进 pytest |
| `render` | C | 换根 + 改一个字的文案，真浏览器采到不同清单 | ⚠️ 只进了一半 | 采集层本身不在 pytest；别的机器没 Edge 时退 3 = NOT RUN |
| `ui_flow` | C | 换根 + 改掉原句中间的字，`t.has` 变 false | ⚠️ 只进了一半 | 真浏览器跑流不在 pytest；其余 25 条流没逐条造反例 |

合计：**11 道全部造出反向案例并实测退非零**（`can_self_prove = 11`），
其中 **8 道整条进了 pytest**；`render` / `ui_flow` 进的是「不依赖浏览器」的那几段判据，
采集层只在探针里留痕；`web_live` 整条没进 pytest。

## 3. 能自证 vs 只能人工

### 3.1 能自证（9 道，含 8 道全进 pytest）

**A 档 7 道**（不需要网络、不需要端口、不需要浏览器）：它们的判据都能被「换一份输入」喂到 ——
`--root` / `--css` / `--map` 是现成的参数，`style` / `ui_text` 的判据是**判据与打印分离的纯函数**
（`collect()`+`evaluate()`、`verdicts()`），`commands` 没有 CLI 入参但模块常量 `COMMANDS` 可换。
这一档的反向全在临时目录里造，**真实仓库一个字节都不写**（照 `scripts/test_check_layers.py` 的老规矩：
它当年改写真仓被 `tests/test_dark_teeth.py::test_5_self_proof_never_touches_the_repo` 抓到过）。

**B 档 `lf1_live`**：输入是「跑起来的服务」，没有文件可换 —— 但**产品行为**可以被 ASGI 中间件改写。
自证的做法是让产品返回错的东西（`{"status": "PROBE-未开始"}` 而不是 `完成`），
这正是这道门要抓的东西（行为退化）。实测 **0.66s 绿 / 0.45s 红**，走 `free_port()`、用临时库、不写项目库，
所以它**进了 pytest**。

> ★ 这条推翻了两个先前的判断，都记在这里免得再犯：
> ① 姊妹件 `tests/test_gate_selfproof.py::test_lf1_check_helper_bites` 的 docstring 写「真起 uvicorn
> 那一段在这里跑不了（要在真机起服务），仍是盲区」—— 实测跑得了，0.7s；
> ② 本自证表早先写「要 ~30s 且占端口 —— 不进 pytest」—— 那也是没实测过的猜测，已改。

### 3.2 只进了一半（2 道：`render` / `ui_flow`）

这两道门的**主体**是真浏览器（`tools/tf_browser.mjs` 起本机 Edge + CDP 采集），
但它们的判据里都还有**不依赖浏览器**的硬段，那几段进了 pytest：

| 门 | 进了 pytest 的部分 | 没进的部分 |
|---|---|---|
| `render` | `--update` 不写 `--reason` ⇒ 退 1；未知参数 ⇒ 退 1 | 真浏览器采集 3 档宽度 × 14 视图 + 逐字节比黄金 |
| `ui_flow` | 未知参数 ⇒ 退 1；`--only` 过滤后零条流 ⇒ 退 1；`--coverage --doc` 人工清单里没人认账的项 ⇒ 退 1（写明理由 ⇒ 退 0） | 真浏览器跑 26 条行为流 |

**采集层的反向是用探针手工实测的**（`gates/diag/_probe_product_heavy.py`，不入库）：

- `render`：换根 + 把侧栏标题 `timeflow ·` 改成 `timeflow PROBE ·` ⇒ 真浏览器采到的清单与黄金不一致
  ⇒ 退 1，原文 `❌ 渲染与黄金不一致：3 份不同、0 份多余`（11.9s）。
- `ui_flow`：换根 + 把「在下面的输入框写下一件要做的事」改成「在下面写一件要做的事」⇒ `t.has` 的
  `includes()` 变 false ⇒ 退 1，原文 `[FAIL] ⑦ 新手引导…` + `❌ 行为流有失败：1/1 条`（11.5s）。

为什么不进 pytest：真 Edge + 各 ~12s + 抢固定端口段（`tools/pool/lease.py` 管着端口段），
放在 pytest 里会让每一趟 pytest 多 25s 且可能和正在跑的门禁撞端口。

### 3.3 只能人工（0 道 `manual_only`，但**有 3 处盲区**）

product 档 11 道**没有一道是「只能人工」** —— 每一道都造出了反向案例并实测退非零。
但「能自证」不等于「没有盲区」，下面三处必须写清楚，否则就是假装 100%：

1. **`ui_dom_probe` 的 DOM 桩不是真浏览器**。它验的是「渲染函数会不会抛、画布空不空」，
   不验 CSS 布局、不验真实点击。真浏览器那一层由 `render` / `ui_flow` 盖。
   这道门自己的头注释写着「本环境**跑不了浏览器**（沙箱禁止命名管道，无头 Edge 直接挂死）」——
   **这句已被本次实测推翻**：`tools/tf_browser.mjs` 走 CDP 不走 playwright，本机
   `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe` 实存，真跑真咬。
2. **`render` / `ui_flow` 在别的机器上会退 3 = NOT RUN**。没有 Edge 时它们不咬 ——
   但**NOT RUN 不是 PASS**（门表注释原话：「起不了服务就记 `not_run`，NOT RUN 不是 PASS」）。
   本机有 Edge，所以这次是真跑的。
3. **`render` 的 `--only` 匹配不到任何视图时退 0**（实测：`--only 自证-不存在的视图` ⇒ exit 0，
   打 `[OK ] 0 份清单与黄金逐字节一致`）。这是「空真」—— 0 份清单当然全都一致。
   它不是这次能修的东西（改 `.mjs` 要另开卡），但**必须记在这里**：
   拿 `--only` 缩小范围时，先确认它真的匹配上了东西（`ui_flow` 的 `--only` 会退 1 并发流名清单，
   `render` 不会 —— 两道门在这一点上不对称）。

## 4. 逐门证据（真实读数摘要）

完整读数与 `probe` 命令在 `gates/gate-selfproof-product.toml` 的 `evidence` / `probe` 两列，这里只摘要点。

| 门 | 正向（exit 0） | 反向（exit 非零 + 点名） |
|---|---|---|
| `check_layers` | `LAYER CHECKS: PASS ✅` | `[FAIL] 缺详细规格: docs/specification/domains/F5-*.md` + `LAYER CHECKS: FAIL ❌`；另一条 `[FAIL] 约定层有 1 条规则未标注来源 N：` |
| `contrast` | `对比度审美门 PASS（文字达标 38 / 已登记欠账 0 / 新欠账或变差 0 …` | `light:--toast-ink on --toast-bg  1.05 < 4.5  新欠账 ｜ .toast：toast 底上的字`；`light:图形 --ink on --panel  1.05 < 3.0  新欠账` |
| `style` | `green_new = []` | `('literal:gap:2px', 'NEW', …全表只出现 1 次（.probe-orphan）—— 只出现一次的值就是没进体系')` |
| `ui_text` | `(0, 4, 0)`（fails 0 / ≥20 字 4 条 / ≥30 字 0 条） | `(['L7  35 字：…', '≥20 字的片段 5 条 > 基线 4 条（这一档只许减）'], 5, 1)` |
| `commands` | `命令表与四个真源一致 ✅（没有硬冲突）` | `[FAIL] OP-1：路由 'POST /api/tasksPROBE' 在 app.py 里不存在（手抄或过期）` + `[FAIL] CLI timeflow add-task：路由 'POST /api/tasks' 不是 OP-1 的路由` |
| `proxy` | `[OK  ] 5 条全新鲜（阈值 30 天）` | `[FAIL] 5 条过期（阈值 30 天）：` + `· done-count 过期 2462 天（上次验证 2020-01-01，距今 2492 天）` |
| `ui_dom_probe` | `✅ 假 DOM 渲染探针：14/14 个视图正常渲染…` | `⚠️  tasks     main      0B  rail   76B` + `ReferenceError: renderTasksPROBE is not defined` |
| `lf1_live` | `LF-1 真实运行验证：PASS（主链全通过，含第 4 步前端界面）` | `[FAIL] ⑦ 任务状态: got='PROBE-未开始' want='完成'` + `FAIL（1 项：⑦ 任务状态）`；同轮 `服务已启动：http://127.0.0.1:57303` |
| `web_live` | `[OK ] 手机侧造包自检通过` / `[OK ] 局域网：对码配对成功` | `[FAIL] 有事件委托监听`（**仅此一条**，其余仍绿 ⇒ 精确定位而不是整页崩） |
| `render` | `[OK ] 3 份清单与黄金逐字节一致（3 档宽度 × 14 个视图 + 1 个浮层）` | `❌ 渲染与黄金不一致：3 份不同、0 份多余` |
| `ui_flow` | `[OK ] ⑦ 新手引导：首次出现、关掉不再来、设置里能再看  7 项断言` | `[FAIL] ⑦ 新手引导…` + `❌ 行为流有失败：1/1 条` + `· 卡片上说清了第一步做什么 —— 在这段里没找到「在下面的输入框写下一件要做的事」` |

## 5. 教训（都是这次踩出来的，写下来免得再踩）

1. **变异必须真的生效，否则红是假的**。每条反向用例都断言了「变异后文本 ≠ 变异前」；
   `ui_flow` 那条更狠：`t.has` 的真身是 `hay.includes(needle)`（`tools/ui_flow_check.mjs:153`），
   **只往后追加字，原句仍是子串，照样通过** —— 头两次探针就是这么假绿的，必须改掉原句中间的字。
2. **每条红都要配一条绿**。`ui_dom_probe` / `web_live` 的反向靠换根，所以绿基线**也**在换根的副本上跑：
   同一棵副本、只把页面换回真的那一份。否则「红了」可能只是树搭错了。
3. **换根要连真源一起搬**。`web_live` 的判据 spawn `tools/phone_check.mjs`，它从 `HERE/../src/web/offline.js`
   取料 —— 漏搬会让**绿基线**因「造包脚本不存在」而假红（踩过一次）。
   另外仓是 editable 安装（`.pth` 指向真仓 `src`），副本必须把 `PYTHONPATH` 顶到 `<副本>/src` 最前，
   否则 `import timeflow` 会解析回真仓、页面还是真仓的。
4. **`--check` 不是装饰**。`style_audit` / `ui_text_audit` 不传 `--check` 时**恒退 0**（只报告）。
   门表里它们都带了 `--check` —— 自证时也必须带，否则造错也绿。
5. **纯函数门省一半事**。`style` / `ui_text` 的判据与打印是分开的（`collect()`+`evaluate()`、
   `verdicts()`），pytest 直接喂合成数据，0.0s，连子进程都不用起。这是判据该长成的样子。
6. **`gates/last.json` 是封存读数，别乱动**。这次的探针全部直调工具函数 / 跑 `--only`，
   不走 `run_gates.py` 的封存路径，所以封存没被污染。

## 6. 怎么复现（全部命令）

```bash
# 表 + 钉子（15 条，约 30s；必须 --no-cov）
python -X utf8 -m pytest tests/test_gate_selfproof_product.py -q --no-cov

# 逐门探针（不入库，gates/diag/ 被 .gitignore 掉）
python -X utf8 gates/diag/_probe_product_a.py          # check_layers / contrast / style / ui_text / proxy
python -X utf8 gates/diag/_probe_product_b.py          # commands / web_live / lf1_live（真起服务）
python -X utf8 gates/diag/_probe_product_heavy.py      # ui_dom_probe / render / ui_flow（真浏览器）
python -X utf8 gates/diag/_probe_pytest_cases.py       # 用例级的「先证明它会红」
python -X utf8 gates/diag/_probe_pytest_cases2.py
python -X utf8 gates/diag/_probe_pytest_cases3.py      # 绿基线
python -X utf8 gates/diag/_probe_pytest_cases4.py      # lf1 真起服务
```

★ `gates/diag/**` 被 `.gitignore` 掉、**不入库** —— 探针只在本机留痕，pytest **不依赖**它们
（`tests/test_subprocess_encoding.py` 的头注释也是这个理由）。所以三件入库的交付物里，
`gates/gate-selfproof-product.toml` 的 `probe` 列既能指向探针，也写了**等价的手工命令**，
换台机器照着敲也能复现。
