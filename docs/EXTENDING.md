# 如何加一个功能（模板）

> 依据：`SR-NF7`（可扩展：预留扩展点 +「如何加一个功能」模板）、`SR-NF10`（零基础定制友好）。
> 能跑的示例在 **`../examples/`**（三个，由浅入深）；本文是**照着填的模板**。
> 一句话：这个项目的每个功能都要**同时**在五层留下痕迹，少一层就会被 `scripts/check_layers.py`
> 或 `scripts/audit_progress.py` 拦下来 —— 这不是形式主义，是让"下一个人能接着改"。

---

## 0. 先判层：这件事属于哪一层？（**别跳这一步**）

判断错了，后面全歪。问自己一句：**这是"发生了什么"，还是"怎么理解它"？**

| 层 | 什么时候来这里 | 落点 | **不要**做什么 |
|---|---|---|---|
| **事实层** `core/facts/` | 系统里**新发生了一件事**（读了书、结束了专注、撤销了一笔产出） | `facts.record(conn, kind="域.动作", ...)` + `facts.publish(...)` | 不要把"算成多少小时/打了多少分"塞进事实（那是解读） |
| **解读层** `core/ledger/`、`core/insights.py` | 要**给用户看一个数字/图表**（本周投入、债务程度、均衡度） | 只读事实层算账；口径写成**一个函数**（如 `weekly_summary()`），别散在路由里 | 不要新增"事实"来存算好的结果；不要折算时间；不要设目标/告警 |
| **操作层** `docs/contracts/` + `core/*/` | 用户要点一个**动作**（建/改/删/升级/打开附件） | 契约补一节 `OP-nn`（六要素）→ 领域函数 → API 路由 | 不要让不可逆动作没有二次确认；不要让失败静默 |
| **配置层** `config.py` + `config.example.toml` | 要让**用户自己调**（时长、阈值、制式、开关） | 见 `../examples/02_add_a_config_option.py` 的四处落点 | 不要把敏感信息写进 example；不要写死在代码里 |
| **界面层** `src/web/index.html` + `app.css` | 要**看得见 / 点得到** | `data-action` 声明 + `ACTIONS` 注册（事件委托）；颜色只写 `app.css` 令牌区 | 不要引入构建步骤或前端依赖；不要在 JS 里写颜色字面量 |

> 一件事常常跨多层 —— 那就**每层都留下痕迹**，这正是五层文档存在的原因。

---

## 1. 五步模板（照着填）

### ① 意图（intention）—— 为什么要做
- 产出：一句话写清**用户的痛点**与**成功的样子**；若是新需求，先问"这属于哪条已有意图（N 编号）"。
- 落点：`docs/intention/needs.md`（新需求才加）；`复盘/` 里的决策记录（口径变化）。
- 硬要求：**口径变化必须留决策记录**（谁定的、为什么、代价是什么）。

### ② 规格（specification）—— 必须做到什么
- 产出：一条 `SR-Fx.y` 或 `SR-NFnn`（**可验证的事实句**），必要时加 `conventions.md` 的横切约定。
- 落点：`docs/specification/functional.md` / `nonfunctional.md` / `conventions.md`。
- 硬要求：写清**边界**（不做什么）与**验证方式**；改口径要在原条目下写"口径调整"并注明日期与依据。

### ③ 契约（contracts）—— 用户怎么走完这件事
- 产出：一个 `OP-nn`（**六要素**：入口 / 前置 / 输入 / 后续 / 可逆 / 反馈 + 边界）。
- 落点：`docs/contracts/domains/`（每域一份契约，如 F1 是 `docs/contracts/domains/F1-tasks.md`）；
  跨域动线写 `docs/contracts/interactions.md`。
- 硬要求：**可逆性**必须回答（能撤销吗？撤销做什么？）；错误路径必须回答（失败了用户看到什么）。

### ④ 实现（implementation）—— 代码 + 测试
- 落点：`src/timeflow/core/<域>/`（领域逻辑，不碰存储细节）→ `src/timeflow/api/app.py`（路由）
  → `src/web/index.html`（界面）；**测试与功能同一次提交**：`tests/test_<线>_line.py`。
- 硬要求：
  - 领域函数**不依赖 FastAPI**，用连接对象执行 SQL（业务与存储分离）；
  - 新增/改字段 → `storage/db.py` **加一版迁移**（`_migrate_vNN` + 幂等 `_add_column_if_missing`）；
  - 前端加动作 → **同时**改 `data-action` 声明与 `ACTIONS` 注册（`audit_progress` 会两边都查）；
  - 改完接口 → 同步 `docs/implementation/modules.md`（模块职责 + 事实 kind 总表）。

### ⑤ 台账（traceability）—— 声称 = 证据（**最容易漏的一步**）
- 落点：`docs/traceability.toml` 加/改条目；编号规则见 `CODING_GUIDELINES.md` §9.1。
- 写法：
  ```toml
  [entries."SR-Fx.y"]          # 或 SR-Fx.ya（拆卡）；自造卡用 T-*/OP-*/STEP-*
  id = "SR-Fx.y"
  title = "<以规格原词开头>：<这张卡具体落地了什么>"
  group = "Fx"
  status = "done"              # done 必须给证据；partial/todo 必须写 gaps
  evidence = ["text:src/...::def 函数名", "route:GET /api/xxx", "test:test_xxx_line.py"]
  gaps = ""
  ```
- 硬要求：`status = "done"` 的**每条断言都会被审计真跑一遍**（文件/文字/路由/表/列/界面动作/测试文件）。
  写了就必须成立；做不到就 `partial` + 老实写 `gaps`（**不许把半成品写成 done**）。

---

## 2. 三条红线（每个功能都要过一遍）

1. **不做时间折算** —— 分钟/小时/天数照报原值。`scripts/check_layers.py` 会扫禁用词（如"时间折算"）。
2. **数据不出本地** —— 不上云、不新增对用户数据的外部依赖；外部监测走独立脚本 + 接口。
3. **温和不施压** —— 只描述事实：不设"目标"实体、不做目标对标、不告警（措辞测试里钉死了禁用词）。

---

## 3. 三种最常见的改动 → 抄哪份

| 我想… | 抄这个 | 关键点 |
|---|---|---|
| 记一件新发生的事 | `../examples/01_add_a_fact_kind.py` | `kind` 自由字符串、`record` + `publish` 分开、订阅者拿 `payload["conn"]` |
| 让用户能调一个值 | `../examples/02_add_a_config_option.py` | 四处落点（config.py / example.toml / 读它的模块 / 文档） |
| **让用户自己加"选项"（不改核心）** | `src/timeflow/vocab.py` 的 `REVIEW_FORMS` | 加一条 `Vocabulary` 声明即可：配置校验、默认值、API、设置页界面全都自动跟着走（见 §3.1） |
| 加一个数字或图表 | `../examples/03_add_a_ledger_view.py` + 本文 §四 | 只读事实层、按 `subject_id` 去重、**撤销照扣** |
| 加一个用户动作 | `docs/contracts/domains/F1-tasks.md` 的 `OP-9` | 六要素齐 + 路由 + `data-action` 两处 + 测试 |
| 加一个字段 | `storage/db.py` 的 `_migrate_v12` | 新版本号 + 幂等 `_add_column_if_missing` + 同步 `TaskOut`/`sync.merge_task` |

### 3.1 可配置词表：**用户自己就能加**的那一类（SR-NF7 / T-G1）

先把话说清楚 —— `N36` 要的是"用户能加**功能/字段/复习形式/可视化/集成**，不改核心"。逐项看下来：

| N36 说的 | 不改核心能做到吗 | 怎么做 |
|---|---|---|
| 复习形式 | ✅ | 词表：`vocab.REVIEW_FORMS`（用户可以自己加"菜谱卡"这种形式） |
| 可视化维度 | ✅ **换一个维度看已有的数** | 词表：`vocab.HEATMAP_DIMENSIONS`（**算一个全新的维度仍要改核心**） |
| 集成 | ✅ | 外部脚本直接调 REST（**怎么写见本文最后一节**） |
| **字段** | ❌ | 加字段必须走 **schema 迁移**（`storage/db.py` + 版本号 + 同步读出口） |
| **功能** | ❌ | 新功能 = **领域函数 + 路由 + 界面**（本文 §一~§五 那五步） |

**加一张新词表 = 三步，不用碰路由和界面**：

1. 在 `src/timeflow/vocab.py` 里加一条声明：
   ```python
   MY_TABLE = Vocabulary(
       key="my_table", title="界面上叫什么", question="这张表管什么？",
       builtin=(("first", "第一项"),),      # 没配置时的兜底
       allowed=None,                        # None = id 用户随便起；给了名单就只能从名单里选
   )
   ```
   然后把它加进文件末尾的 `ALL` 元组。
2. 如果它需要"配置文件里的默认值"：在 `src/timeflow/config.py` 加一个 pydantic 字段 +
   `field_validator` 调 `vocab.parse(...)`（**写错当场报错**，不静默回落），并在
   `config.example.toml` 写上示例。
3. 想读到它就 `vocab.get(conn, MY_TABLE, defaults)`；从界面改由 `GET/PUT /api/settings/vocab`
   与 `POST /api/settings/vocab/reset` 通用路由负责，设置页那一节是**通用渲染**的。

`allowed` 的用法举例：热力图维度必须对应**真的算得出来的数据字段**（`insights.HEATMAP_FIELDS`），
所以它的 `allowed` 就是那五个字段名 —— 用户能改"用哪些、叫什么、排第几"，但**配不出算不出来的东西**。
`tests/test_vocab_line.py` 里有一条断言把 `allowed` 与 `HEATMAP_FIELDS` 钉在一起（多一个少一个都会红）。

---

## 四、照例 3 走一遍：把一条解读层口径接进产品（4 处改动）

假设你要加「本周产出条数（按类分开）」：

1. **解读层** —— `src/timeflow/core/ledger/ledger.py` 加一个**只读**函数
   （形状抄 `../examples/03_add_a_ledger_view.py` 的 `outputs_since`；口径与 `summary()` 同源）；
2. **API** —— `src/timeflow/api/app.py` 加只读路由 `@app.get("/api/...")`（只读就别写 PATCH/DELETE）；
3. **界面** —— `src/web/index.html` 渲染它（如顶部摘要行）；**颜色只写 `app.css` 令牌区**；
4. **台账** —— `docs/traceability.toml` 那条卡加证据：`text:` 指向函数 + `route:` + `test:`。

> 只做 1、2 不做 3、4 —— 那就是**后端就绪、界面未做**的半成品。
> 这种如实状态写 `status = "partial"` + `gaps` 说清缺什么，并且**进 `[exceptions]` 留痕**
> （`[exceptions]` 是"已知欠账"清单，**修一条删一条**，不许静默豁免）。

---

## 五、提交前必跑（照协议，不许跳）

```powershell
cd "D:/repo/engineering"   # 换成你的真实路径
$env:PYTHONPATH="$PWD\tools\sandbox_shim"     # 本仓沙箱需要这个垫片（run_gates 已内置）
python -X utf8 scripts/run_gates.py           # 十一项阻断门：测试/验收/lint/类型/分层/护栏审计/真机自检
python -X utf8 examples/01_add_a_fact_kind.py # 改过示例就跑一遍（tests/test_examples.py 也会跑）
```

门禁全绿之后提交，提交信息带四段 trailer（写法见 `../.github/pull_request_template.md`）：

```
Task: T-xN          # 必填：任务卡编号（台账里必须有这一条）—— **只写一个卡号**
Refs: SR-Fx.y, OP-nn
Ledger: <台账状态怎么变的>
Gates: <run_gates 的结论行>
```

> ⚠️ **`Task:` 只写一个卡号**：审计把这一行当成**恰好一个台账编号**（既用它做严格校验，
> 也用它做"台账 ↔ git"对账）。写成 `T-G13 / F6 OP-27 延伸` 这种，两处都认不出来 ——
> 严格模式会 FAIL，对账则**误报**"台账 done 但 git 里没有挂 Task:T-G13 的提交"。
> 牵扯到的 SR/OP 编号请写进 `Refs:`（血泪教训见 `../复盘/提交标签写错-T-G17.md`）。

**审计不通过就别提交** —— 这道闸门是 `scripts/audit_progress.py`（六项检查），
它挡的正是"改了代码忘了改文档 / 声称做了但证据不成立"这两件事。

---

## 六、怎么写外部脚本（集成）—— 不改 timeflow 一行代码

> SR-NF7 里"集成"那一项（G 批 · T-G2）。可跑示例：`../examples/04_external_script.py`。

**核心一句话**：timeflow 跑起来就是一个**本机 HTTP 服务**，`/api/...` 就是它的全部能力 ——
你的脚本、手机快捷指令、Obsidian 按钮、定时任务都能直接调，**不用改它的代码**。

```powershell
# ① 起服务（桌面窗口同理；这一步是你的程序与 timeflow 的唯一接口）
python -X utf8 tools/serve.py            # → http://127.0.0.1:8000

# ② 读：健康检查给出"能自证的事实"（schema 版本 / 表条数），不报"一切正常"这种空话
Invoke-RestMethod http://127.0.0.1:8000/api/health

# ③ 写：建一个任务 → 完成它（成对动作，随时可撤）
$t = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/tasks `
      -ContentType 'application/json; charset=utf-8' `
      -Body (@{ title = '外部脚本建的任务'; is_myday = $true } | ConvertTo-Json)
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/tasks/$($t.id)/complete"

# ④ 读账本：数字来自事实层（完成收益 +1）
(Invoke-RestMethod http://127.0.0.1:8000/api/summary).gain_count

# ⑤ 撤销也走接口：账本自己回退（别自己去改数字）
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/tasks/$($t.id)/uncomplete"
```

Python 版（与示例同构；示例用 `TestClient` 只是为了**不占端口、不依赖先起服务**，
请求与响应的形状和真机完全一致）：

```python
import json, urllib.request

BASE = "http://127.0.0.1:8000"

def call(method: str, path: str, body: dict | None = None) -> object:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310 —— 只连本机
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req) as resp:   # noqa: S310
        return json.loads(resp.read().decode("utf-8"))

print(call("GET", "/api/health"))
print(call("POST", "/api/tasks", {"title": "外部脚本建的任务", "is_myday": True}))
```

### 五条规矩（外部脚本也守）

1. **别直接改 SQLite 库**。账本/债务/洞察这些数字都由**事实层**算出来；绕过接口直接 `UPDATE`
   会让"事实"和"状态"对不上（下次迁移或回填时打架）。要写就走 `/api/...`。
2. **动作是成对的**：`complete`/`uncomplete`、`POST /api/ledger/invest` 与
   `DELETE /api/ledger/invest/{id}`、`POST /api/ledger/output` 与对应 `DELETE` ——
   别自己造一套"删除"，否则撤销口径就分叉了。
3. **日期一律本地日历、日界 00:00**（`specification/behaviors.md`）：传 `YYYY-MM-DD`，
   别传 UTC 时间戳（否则东八区凌晨会差一天 —— 这个坑真踩过，见 `../复盘/门禁跨午夜暴露的时区口径缺陷-T-D12.md`）。
4. **只监听本机**：服务默认绑 `127.0.0.1`；写类接口还额外要求"本机页面来源"（`require_local_origin`）。
   要让别的机器访问，请自己想清楚暴露面 —— 这不是本项目的默认姿势。
5. **出错会说话**：非法值给 4xx + 中文原话（不静默回落、不写脏数据）。照原话改，别猜。

### 边界（用户 2026-09-21 定，如实标注）

| 你想加什么 | 不改核心能做到吗 | 怎么做 |
|---|---|---|
| 集成（外部程序跟它打交道） | ✅ | 就是本文这一节 |
| 复习形式 / 可视化维度这类**选项** | ✅ | 可配置词表（§3.1），界面上自己加 |
| 记一件新发生的事 | ✅ | 新事实 `kind`（§3 表第 1 行） |
| **加字段** | ❌ | 必须走 **schema 迁移**（`storage/db.py` + 版本号 + 同步读出口） |
| **加功能** | ❌ | 必须写**领域函数 + 路由 + 界面**（§一~§五 那五步） |

"插件化"到"能加功能/字段而不改核心"这一层**本项目没做到**，也不假装能做到 ——
`SR-NF7` 的口径是：**能加的（词表 / 集成 / 事实 kind）都让它能加，加不了的（字段 / 功能）如实写明** ——
不假装插件化。

---

## 七、反模式（这几件都踩过，别再来一次）

| 反模式 | 为什么坏 | 正确的做法 |
|---|---|---|
| 把"算好的结果"当事实存起来 | 换口径时历史全是错的（事实与解读混了） | 只存原始事实，读数时算 |
| 半成品写 `done` | 审计断言实跑会 FAIL；就算躲过，后来的人也信了假话 | `partial` + `gaps` 写清缺什么 |
| 前端加动作只改一半 | `audit_progress` 查 `data-action` 声明 **和** `ACTIONS` 注册两处 | 两处一起改 |
| 编号自己顺手编 | 2026-09-20 就因此出现"`SR-F1.3` 在规格与台账里指两件事" | 照 `CODING_GUIDELINES.md` §9.1 的三种合法形态 |
| 文档里贴代码片段当示例 | 接口一改，片段就腐烂且没人发现 | 示例写成**能跑的脚本**，用测试兜住（`tests/test_examples.py`） |
