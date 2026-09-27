# 渲染黄金的更新记录

**这是什么**：`gates/render/*.txt` 是**渲染黄金** —— 3 档宽度（desktop 1280 / narrow 820 / phone 390）
× 14 个视图，每个视图一份"几何清单"（每个可见元素的 选择器 / 文本 / 盒子 / 字号·行高·字重 / 前景·背景 / 圆角·内边距）。
门禁每次重跑 `node tools/render_check.mjs`，与它**逐字节比**；任何差异都算 FAIL。

**为什么要有理由**：黄金就是判据本身。改判据必须留下理由，跟台账登记、棘轮销账一个道理 ——
所以 `--update` 必须带 `--reason "…"`，下面每一条都是它。

**怎么重新生成**

```
node tools/render_check.mjs                    # 比对（门禁里跑的就是这条）
node tools/render_check.mjs --update --reason "一句话为什么"
node tools/render_check.mjs --shots            # 另存 PNG 到 gates/render/shots/（给人看，不入库）
node tools/render_check.mjs --only today       # 只看/只重出一个视图（**不会动别人的黄金**）
node tools/render_check.mjs --seed-only        # 起一个有种子数据的服务，停在那儿（用来在真数据上试样式）
```

**两条阅读须知**

1. 清单是**归一化过**的：绝对日期与时刻（`YYYY-MM-DD HH:MM`）、本机临时目录（`<path>`）、
   机器标识（`<id>`、`‹code:N›`）都换成固定形状 —— 判的是**版式与状态**，不是"当时几点"。归一化了几处会打印出来。
2. 黄金与**这台机器**绑定（字体、渲染引擎、临时目录路径）。换机器跑第一次大概是红的：
   先看 diff 是不是只有字体度量差异，是的话 `--update` 并写清理由。

> 这一层在建成期间反复重出过黄金 —— 它的**确定性自检**（每轮把同一份清单采两遍）一条条抓出了
> 页面里"会自己变的东西"（随时间翻的选中态、随机设备号、滚动条吃掉 15px、mkdtemp 的随机目录名…）。
> 那场来回不写在这里，记在 `复盘/渲染验证层-T-G32.md`；下面只留**定型之后**的改动记录。

## 2026-09-23 · 首次定型（修复后的基线）

> 理由：修掉渲染层抓到的三类真缺陷后，把它自己的黄金定下来 ——
> ① 卡片正文被一排按钮挤成竖排（19 处内联 `flex:1` → `.card-body`，给正文真实基宽 240px + 下限 8em）；
> ② 复选框被当文本框画（`.new` / `.field` 的 `input` 规则不再命中 checkbox/radio）；
> ③ 离线页那张「这台设备用不了离线存储」**永远挂着**（`ready ? '' : …`）。
> 期间为让黄金活过"明天再跑一次"与"换个机器起服务"，补齐了归一化规则（日期/时刻/机器路径/机器标识 id）
> 并钉住了本机状态（强调色、设备号、导出目录）。

- 全部 42 份（3 档宽度 × 14 个视图）

## 2026-09-23 11:58:37 · 3 份改动

> 理由：T-G34：把后端 describe() 那些「口径说明」文字统一走 noteHTML()。它们在界面里是用 esc() 画的，于是源码里的 **重点** 就原样画出星号（T-G11 修的是 index.html 里的静态文案，这是同一族的另一半：说明文字在后端）。改动只落在设置页那 3 档宽度：**x** 变成 <b>x</b>（字重 700），其它 41 份清单逐字节不变。

- `desktop/setting`
- `narrow/setting`
- `phone/setting`


## 2026-09-23 13:53:58 · 12 份改动

> 理由：T-G38 两处：① 离线页「放进今天」的勾选框被 .field 的 flex 列默认为 stretch 横向拉满（123x13），加一条 align-self:flex-start → 13x13；② 采集器原来只认 rgb()，color-mix() 算出来的底色（#22c55e/#ef4444@0.18 那 15 行）被原样存成 color(srgb ...) —— 归一成 hex，人读得懂、也不怕浏览器版本换字符串。

- `desktop/academic`
- `desktop/offline`
- `desktop/planned`
- `desktop/tasks`
- `narrow/academic`
- `narrow/offline`
- `narrow/planned`
- `narrow/tasks`
- `phone/academic`
- `phone/offline`
- `phone/planned`
- `phone/tasks`


## 2026-09-23 14:30:35 · 42 份改动

> 理由：T-G39：默认强调色按用户决定换成 workbench 包的 #2f6feb（白字 4.57 过 AA，原来 #3b82f6 只有 3.68）。42 份清单里只有'底色/字色带强调色的那些行'变了（按钮/选中导航/大写数字/色板头部 accent=），几何一个像素没动 —— 这是纯换色。另：本次采集遇到过**一次** stats 视图两遍不一致（自检当场拦下、重跑即稳定），成因未定，已记进 T-G39 的 gaps。

- `desktop/academic`
- `desktop/flagged`
- `desktop/focus`
- `desktop/habit`
- `desktop/important`
- `desktop/memo`
- `desktop/offline`
- `desktop/planned`
- `desktop/review`
- `desktop/setting`
- `desktop/stats`
- `desktop/tasks`
- `desktop/team`
- `desktop/today`
- `narrow/academic`
- `narrow/flagged`
- `narrow/focus`
- `narrow/habit`
- `narrow/important`
- `narrow/memo`
- `narrow/offline`
- `narrow/planned`
- `narrow/review`
- `narrow/setting`
- `narrow/stats`
- `narrow/tasks`
- `narrow/team`
- `narrow/today`
- `phone/academic`
- `phone/flagged`
- `phone/focus`
- `phone/habit`
- `phone/important`
- `phone/memo`
- `phone/offline`
- `phone/planned`
- `phone/review`
- `phone/setting`
- `phone/stats`
- `phone/tasks`
- `phone/team`
- `phone/today`


## 2026-09-23 17:08:05 · 21 份改动

> 理由：四个原因（都在 T-G40 / T-G41 两张卡里）：① 采集竞态 —— 装上请求计数器后等请求落地（以前 stats 采到的是上一个视图 focus 的残留内容）；② fixture 日期改成星期无关（未完成任务的偏移只留 <=-1 与 >=+7，周结算的债务读数不再随星期几变）；③ 习惯页的今天改成按本地时区（原 toISOString 会拿 UTC 日期：凌晨会显示成没打卡、点一下反而取消掉）+ 热力图格子差一天一并修；④ 采集器不再把嵌了 title 的 SVG 图元当匿名容器跳过（热力图/节奏图的点亮状态以前根本没进黄金）。另：设置页多一行 AI 路由（T-G21）。

- `desktop/focus`
- `desktop/habit`
- `desktop/offline`
- `desktop/planned`
- `desktop/setting`
- `desktop/stats`
- `desktop/tasks`
- `narrow/focus`
- `narrow/habit`
- `narrow/offline`
- `narrow/planned`
- `narrow/setting`
- `narrow/stats`
- `narrow/tasks`
- `phone/focus`
- `phone/habit`
- `phone/offline`
- `phone/planned`
- `phone/setting`
- `phone/stats`
- `phone/tasks`


## 2026-09-24 03:14:55 · 42 份改动

> 理由：T-G42 徽标原语换成 chip + 8px 状态点（对比度 10 条清零）：徽标几何（pill / 11px / 1px 边）与状态点都进了清单，所以 42 份黄金整体重采；除徽标外无改动

- `desktop/academic`
- `desktop/flagged`
- `desktop/focus`
- `desktop/habit`
- `desktop/important`
- `desktop/memo`
- `desktop/offline`
- `desktop/planned`
- `desktop/review`
- `desktop/setting`
- `desktop/stats`
- `desktop/tasks`
- `desktop/team`
- `desktop/today`
- `narrow/academic`
- `narrow/flagged`
- `narrow/focus`
- `narrow/habit`
- `narrow/important`
- `narrow/memo`
- `narrow/offline`
- `narrow/planned`
- `narrow/review`
- `narrow/setting`
- `narrow/stats`
- `narrow/tasks`
- `narrow/team`
- `narrow/today`
- `phone/academic`
- `phone/flagged`
- `phone/focus`
- `phone/habit`
- `phone/important`
- `phone/memo`
- `phone/offline`
- `phone/planned`
- `phone/review`
- `phone/setting`
- `phone/stats`
- `phone/tasks`
- `phone/team`
- `phone/today`


## 2026-09-24 03:18:06 · 9 份改动

> 理由：T-G42 徽标原语（chip + 8px 状态点）：点改成真元素 <i class=dot> 所以进了清单；状态徽标不再用合成底 + 同色字。其余视图无改动

- `desktop/academic`
- `desktop/planned`
- `desktop/tasks`
- `narrow/academic`
- `narrow/planned`
- `narrow/tasks`
- `phone/academic`
- `phone/planned`
- `phone/tasks`


## 2026-09-24 03:30:14 · 15 份改动

> 理由：T-G42 采集器补回一处覆盖：徽标加了 8px 状态点之后它从叶子变成容器，徽标上的字就从清单里静默消失了 —— 改成「孩子全是空壳时仍采自己的字」

- `desktop/academic`
- `desktop/planned`
- `desktop/setting`
- `desktop/tasks`
- `desktop/today`
- `narrow/academic`
- `narrow/planned`
- `narrow/setting`
- `narrow/tasks`
- `narrow/today`
- `phone/academic`
- `phone/planned`
- `phone/setting`
- `phone/tasks`
- `phone/today`


## 2026-09-24 04:08:48 · 36 份改动

> 理由：T-G43 视觉线步 0：99 处内联 style 收进 app.css（只改选择器列；原匿名容器有名字后进了清单，覆盖面变大）。已用「旧行是新行子集」的脚本逐视图证明视觉零变化

- `desktop/academic`
- `desktop/flagged`
- `desktop/focus`
- `desktop/habit`
- `desktop/important`
- `desktop/planned`
- `desktop/review`
- `desktop/setting`
- `desktop/stats`
- `desktop/tasks`
- `desktop/team`
- `desktop/today`
- `narrow/academic`
- `narrow/flagged`
- `narrow/focus`
- `narrow/habit`
- `narrow/important`
- `narrow/planned`
- `narrow/review`
- `narrow/setting`
- `narrow/stats`
- `narrow/tasks`
- `narrow/team`
- `narrow/today`
- `phone/academic`
- `phone/flagged`
- `phone/focus`
- `phone/habit`
- `phone/important`
- `phone/planned`
- `phone/review`
- `phone/setting`
- `phone/stats`
- `phone/tasks`
- `phone/team`
- `phone/today`


## 2026-09-24 04:11:31 · 3 份改动

> 理由：T-G43 步 0 复采：雷达图改回行内（先前误加 display:block 会让整页下移）；柱子顶角 4px 并进 --r-xs（T-G24 记的裸像素，唯一一处有意收敛）

- `desktop/academic`
- `narrow/academic`
- `phone/academic`


## 2026-09-24 04:26:30 · 9 份改动

> 理由：T-G44 步 1：颜色令牌改名对齐 workbench（值不变）；唯一有意变化 = --accent-soft 并进 --panel-2，进度条槽 #f1f5f9→#eef2f7

- `desktop/academic`
- `desktop/review`
- `desktop/stats`
- `narrow/academic`
- `narrow/review`
- `narrow/stats`
- `phone/academic`
- `phone/review`
- `phone/stats`


## 2026-09-24 09:51:44 · 31 份改动

> 理由：T-G45：4 处一次性裸值收敛到最近的档（.rail nav gap 2→4、.fact padding 3→4、panel-card .title 下边距 2→4、.swatch 圆角 50%→--r-pill）；互动态（hover/focus）本身零像素变化

- `desktop/academic`
- `desktop/flagged`
- `desktop/focus`
- `desktop/habit`
- `desktop/important`
- `desktop/memo`
- `desktop/offline`
- `desktop/planned`
- `desktop/review`
- `desktop/setting`
- `desktop/stats`
- `desktop/tasks`
- `desktop/team`
- `desktop/today`
- `narrow/academic`
- `narrow/flagged`
- `narrow/focus`
- `narrow/habit`
- `narrow/important`
- `narrow/memo`
- `narrow/offline`
- `narrow/planned`
- `narrow/review`
- `narrow/setting`
- `narrow/stats`
- `narrow/tasks`
- `narrow/team`
- `narrow/today`
- `phone/academic`
- `phone/offline`
- `phone/setting`


## 2026-09-24 10:10:50 · 6 份改动

> 理由：T-G45：修「中文被压碎」三处（.habit-head 允许换行 / 习惯页摘要卡改块内容卡 / 分组名给宽度下限 minw-160）—— 只影响原本被挤的那几个视图

- `desktop/habit`
- `desktop/setting`
- `narrow/habit`
- `narrow/setting`
- `phone/habit`
- `phone/setting`


## 2026-09-24 11:16:35 · 18 份改动

> 理由：T-G49 界面不解释（第一轮）：空态不再解释怎么用，口径压到 8 字以内

- `desktop/academic`
- `desktop/offline`
- `desktop/review`
- `desktop/setting`
- `desktop/stats`
- `desktop/today`
- `narrow/academic`
- `narrow/offline`
- `narrow/review`
- `narrow/setting`
- `narrow/stats`
- `narrow/today`
- `phone/academic`
- `phone/offline`
- `phone/review`
- `phone/setting`
- `phone/stats`
- `phone/today`


## 2026-09-24 11:20:43 · 6 份改动

> 理由：T-G49 界面不解释（收尾）：智能视图那三行 note 也按新口径改（重要型去掉解释、已标记只留「只提醒自己」）

- `desktop/flagged`
- `desktop/important`
- `narrow/flagged`
- `narrow/important`
- `phone/flagged`
- `phone/important`


## 2026-09-24 13:19:05 · 42 份改动

> 理由：T-G51 视觉线步2静音层落地：1px 边框做层次 + 阴影归位浮层 + 尺度收敛到包的 6 档间距/3 档圆角 + 读数卡退 --panel-2；同一轮带 T-G53 行高令牌与 T-G46 输入框元素级规则。42 份全动，属有意改版

- `desktop/academic`
- `desktop/flagged`
- `desktop/focus`
- `desktop/habit`
- `desktop/important`
- `desktop/memo`
- `desktop/offline`
- `desktop/planned`
- `desktop/review`
- `desktop/setting`
- `desktop/stats`
- `desktop/tasks`
- `desktop/team`
- `desktop/today`
- `narrow/academic`
- `narrow/flagged`
- `narrow/focus`
- `narrow/habit`
- `narrow/important`
- `narrow/memo`
- `narrow/offline`
- `narrow/planned`
- `narrow/review`
- `narrow/setting`
- `narrow/stats`
- `narrow/tasks`
- `narrow/team`
- `narrow/today`
- `phone/academic`
- `phone/flagged`
- `phone/focus`
- `phone/habit`
- `phone/important`
- `phone/memo`
- `phone/offline`
- `phone/planned`
- `phone/review`
- `phone/setting`
- `phone/stats`
- `phone/tasks`
- `phone/team`
- `phone/today`


## 2026-09-24 13:21:34 · 3 份改动

> 理由：T-G51 补一条 .card > button 标签不断行：1px 边框吃掉 2px 内容宽，把 phone/offline 的「完成」顶成两行（squeeze 0->8）；只影响这一份黄金

- `desktop/offline`
- `narrow/offline`
- `phone/offline`


## 2026-09-24 13:36:05 · 0 份改动

> 理由：诊断用（并行条件下取数，稍后按结论回滚或重采）




## 2026-09-24 13:43:05 · 3 份改动

> 理由：T-G51 收口：offline 的 3 份黄金改用**全量跑**采（此前那 3 份是 --only 采的，而 --only 不访问在线页面 → 离线缓存为空 → 采到的是退化版式；视图之间不是独立的）

- `desktop/offline`
- `narrow/offline`
- `phone/offline`


## 2026-09-24 14:00:26 · 26 份改动

> 理由：T-G54 图标系统：底栏 7 个 emoji + 标记/删除/折叠/上下移/勾选共 15 处字形换成内联 SVG（24 网格、只描边、currentColor，颜色随状态走）；底栏行盒 24→21px（图标不再撑高行盒）

- `desktop/flagged`
- `desktop/important`
- `desktop/planned`
- `desktop/setting`
- `desktop/tasks`
- `desktop/today`
- `narrow/flagged`
- `narrow/important`
- `narrow/planned`
- `narrow/setting`
- `narrow/tasks`
- `narrow/today`
- `phone/academic`
- `phone/flagged`
- `phone/focus`
- `phone/habit`
- `phone/important`
- `phone/memo`
- `phone/offline`
- `phone/planned`
- `phone/review`
- `phone/setting`
- `phone/stats`
- `phone/tasks`
- `phone/team`
- `phone/today`


## 2026-09-24 14:18:41 · 12 份改动

> 理由：T-G55 图表规范：6 个手写 SVG 的静态尺寸/颜色下沉成 app.css 的 .chart-* 类（一致性门从此看得见图表）+ 习惯热力图窗口 90→371 天（左 3/4 恒空的真缺口）+ 空态/数字口径按约定改短；同轮含 T-G54 图标系统（15 处字形→内联 SVG，底栏行盒 24→21px）

- `desktop/academic`
- `desktop/habit`
- `desktop/stats`
- `desktop/today`
- `narrow/academic`
- `narrow/habit`
- `narrow/stats`
- `narrow/today`
- `phone/academic`
- `phone/habit`
- `phone/stats`
- `phone/today`


## 2026-09-24 14:30:28 · 3 份改动

> 理由：T-G56：设置页接进两条无界面路由（全量提醒列表 OP-47 / 冲突日志 OP-40·OP-41）—— 只读展示 + 各一个「读一次」按钮，不开新视图；setting 3 档宽度因此变化

- `desktop/setting`
- `narrow/setting`
- `phone/setting`


## 2026-09-24 14:42:38 · 12 份改动

> 理由：T-G57 界面文案清理：T-G49 第一轮剩下的 18 条 ≥30 字句子逐条清完（数字口径改到 ≤8 字、解释与教学句删掉、清单搬进 docs/user-guide.md），离线页保留能力边界与两条实话；团队页口径也改短（后端 core/team/team.py）

- `desktop/habit`
- `desktop/offline`
- `desktop/setting`
- `desktop/team`
- `narrow/habit`
- `narrow/offline`
- `narrow/setting`
- `narrow/team`
- `phone/habit`
- `phone/offline`
- `phone/setting`
- `phone/team`


## 2026-09-24 14:50:08 · 0 份改动

> 理由：T-G57 收尾：把被测试/探针/流钉着的边界事实补回精简版（离线能力边界 + 同一 WiFi + 设备号会写进包里、习惯页指路手动投入、改判确认拆两行保住「按新的一档重算 / 投入不会重复计」）




## 2026-09-24 15:03:04 · 6 份改动

> 理由：用户 2026-09-25 决定：三句数字口径**全删**（环下、学业vs自学、分组分布各删一个 .sub），事实搬进 docs/user-guide.md；today ×3 与 stats ×3 六份黄金因此变化

- `desktop/stats`
- `desktop/today`
- `narrow/stats`
- `narrow/today`
- `phone/stats`
- `phone/today`


## 2026-09-24 15:22:22 · 3 份改动

> 理由：T-G60：分组管理里每个分组加「看任务」按钮（点开在该分组下面行内展开它的任务，只读；再点收起）—— 分组行外层多了一层包裹容器，setting 3 档宽度因此变化

- `desktop/setting`
- `narrow/setting`
- `phone/setting`


## 2026-09-24 15:53:15 · 31 份改动

> 理由：T-G61 键盘附加层：左栏多一个带键位徽标的「命令」入口（14 个视图的清单都会动一行）+ 新增浮层伪视图 palette 的 3 份黄金（⌘K 面板：--panel 底 / --r-md / --shadow 只给浮层 / 行是 div 不抢 Tab）；同一提交还改了 --fast 新增命令面板对账那一节

- `desktop/academic`
- `desktop/flagged`
- `desktop/focus`
- `desktop/habit`
- `desktop/important`
- `desktop/memo`
- `desktop/offline`
- `desktop/palette`（新增）
- `desktop/planned`
- `desktop/review`
- `desktop/setting`
- `desktop/stats`
- `desktop/tasks`
- `desktop/team`
- `desktop/today`
- `narrow/academic`
- `narrow/flagged`
- `narrow/focus`
- `narrow/habit`
- `narrow/important`
- `narrow/memo`
- `narrow/offline`
- `narrow/palette`（新增）
- `narrow/planned`
- `narrow/review`
- `narrow/setting`
- `narrow/stats`
- `narrow/tasks`
- `narrow/team`
- `narrow/today`
- `phone/palette`（新增）


## 2026-09-24 16:09:44 · 6 份改动

> 理由：T-G61 键盘附加层（第二次重采，同一张卡）：上一轮采于 2026-09-24 23:5x，跨过午夜后 habit/stats 两个视图按'今天'锚定，格子数与窗口首日标签各差一天 —— 本轮在 2026-09-25 重采，把它们对齐到新的一天（这恰好证明黄金层还有一处跨天漂移，已立卡 T-G62）

- `desktop/habit`
- `desktop/stats`
- `narrow/habit`
- `narrow/stats`
- `phone/habit`
- `phone/stats`


## 2026-09-24 16:34:19 · 45 份改动

> 理由：T-G62 假时钟落地：黄金的「今天」钉在 CAPTURE_DAY=2026-06-15（serve --today + fixture 基准日 + 浏览器 Date 垫片三处一致），清单头一行新增 day= …；热力图/统计页的格子数与首日标签从此是固定值（以前随真今天/几点跑）。同勾：27 处 date.today()/datetime.now() 收敛到 timeflow.clock

- `desktop/academic`
- `desktop/flagged`
- `desktop/focus`
- `desktop/habit`
- `desktop/important`
- `desktop/memo`
- `desktop/offline`
- `desktop/palette`
- `desktop/planned`
- `desktop/review`
- `desktop/setting`
- `desktop/stats`
- `desktop/tasks`
- `desktop/team`
- `desktop/today`
- `narrow/academic`
- `narrow/flagged`
- `narrow/focus`
- `narrow/habit`
- `narrow/important`
- `narrow/memo`
- `narrow/offline`
- `narrow/palette`
- `narrow/planned`
- `narrow/review`
- `narrow/setting`
- `narrow/stats`
- `narrow/tasks`
- `narrow/team`
- `narrow/today`
- `phone/academic`
- `phone/flagged`
- `phone/focus`
- `phone/habit`
- `phone/important`
- `phone/memo`
- `phone/offline`
- `phone/palette`
- `phone/planned`
- `phone/review`
- `phone/setting`
- `phone/stats`
- `phone/tasks`
- `phone/team`
- `phone/today`


## 2026-09-25 00:22:26 · 21 份改动

> 理由：T-G63 按钮瘦身（用户 2026-09-25：「不要那么多按钮」，选 A′）：① 任务卡动作行从「每卡 8-10 个同级按钮」收成「在做/开始 + 专注 + 「…」」（点开行内展开其余；删除在菜单里且是红边 ghost）；详情按钮换成点标题；② 设置页每节折成「标题 + 现状 + 展开」（91 个可见按钮 / 7099px → 4 个 / 1164px）。两个视图的全部黄金因此重采（卡上多了「…」、设置页只剩目录行）

- `desktop/flagged`
- `desktop/important`
- `desktop/palette`
- `desktop/planned`
- `desktop/setting`
- `desktop/tasks`
- `desktop/today`
- `narrow/flagged`
- `narrow/important`
- `narrow/palette`
- `narrow/planned`
- `narrow/setting`
- `narrow/tasks`
- `narrow/today`
- `phone/flagged`
- `phone/important`
- `phone/palette`
- `phone/planned`
- `phone/setting`
- `phone/tasks`
- `phone/today`


## 2026-09-25 15:51:49 · 6 份改动

> 理由：My Day 卡片加拖拽抓手（span.grab）与顺序行、列表加 #mydayList 包裹（T-G79 真拖拽）

- `desktop/palette`
- `desktop/today`
- `narrow/palette`
- `narrow/today`
- `phone/palette`
- `phone/today`


## 2026-09-26 06:10:13 · 45 份改动

> 理由：T-G104 字号档位对齐设计包：删 --fs-base:14（5 个消费者改指 --fs-md:13）+ --fs-xl 18→20（对齐 --t-section）；T-G101 删拖拽恒假早退

- `desktop/academic`
- `desktop/flagged`
- `desktop/focus`
- `desktop/habit`
- `desktop/important`
- `desktop/memo`
- `desktop/offline`
- `desktop/palette`
- `desktop/planned`
- `desktop/review`
- `desktop/setting`
- `desktop/stats`
- `desktop/tasks`
- `desktop/team`
- `desktop/today`
- `narrow/academic`
- `narrow/flagged`
- `narrow/focus`
- `narrow/habit`
- `narrow/important`
- `narrow/memo`
- `narrow/offline`
- `narrow/palette`
- `narrow/planned`
- `narrow/review`
- `narrow/setting`
- `narrow/stats`
- `narrow/tasks`
- `narrow/team`
- `narrow/today`
- `phone/academic`
- `phone/flagged`
- `phone/focus`
- `phone/habit`
- `phone/important`
- `phone/memo`
- `phone/offline`
- `phone/palette`
- `phone/planned`
- `phone/review`
- `phone/setting`
- `phone/stats`
- `phone/tasks`
- `phone/team`
- `phone/today`


## 2026-09-26 17:19:23 · 45 份改动

> 理由：T-G142 界面解释文案第二批（卡 I8 集成）：按「界面不解释」口径删/压 ≥20 字文案，渲染清单随之重采

- `desktop/academic`
- `desktop/flagged`
- `desktop/focus`
- `desktop/habit`
- `desktop/important`
- `desktop/memo`
- `desktop/offline`
- `desktop/palette`
- `desktop/planned`
- `desktop/review`
- `desktop/setting`
- `desktop/stats`
- `desktop/tasks`
- `desktop/team`
- `desktop/today`
- `narrow/academic`
- `narrow/flagged`
- `narrow/focus`
- `narrow/habit`
- `narrow/important`
- `narrow/memo`
- `narrow/offline`
- `narrow/palette`
- `narrow/planned`
- `narrow/review`
- `narrow/setting`
- `narrow/stats`
- `narrow/tasks`
- `narrow/team`
- `narrow/today`
- `phone/academic`
- `phone/flagged`
- `phone/focus`
- `phone/habit`
- `phone/important`
- `phone/memo`
- `phone/offline`
- `phone/palette`
- `phone/planned`
- `phone/review`
- `phone/setting`
- `phone/stats`
- `phone/tasks`
- `phone/team`
- `phone/today`


## 2026-09-27 08:01:19 · 36 份改动

> 理由：集成十一张并行卡：060 左栏三项收进设置(桌面15+窄屏15左栏各少三行) + 057/058/059 各改本视图，按合并后源码全量重采(T-G153)

- `desktop/academic`
- `desktop/flagged`
- `desktop/focus`
- `desktop/habit`
- `desktop/important`
- `desktop/memo`
- `desktop/offline`
- `desktop/palette`
- `desktop/planned`
- `desktop/review`
- `desktop/setting`
- `desktop/stats`
- `desktop/tasks`
- `desktop/team`
- `desktop/today`
- `narrow/academic`
- `narrow/flagged`
- `narrow/focus`
- `narrow/habit`
- `narrow/important`
- `narrow/memo`
- `narrow/offline`
- `narrow/palette`
- `narrow/planned`
- `narrow/review`
- `narrow/setting`
- `narrow/stats`
- `narrow/tasks`
- `narrow/team`
- `narrow/today`
- `phone/academic`
- `phone/memo`
- `phone/palette`
- `phone/review`
- `phone/team`
- `phone/today`

