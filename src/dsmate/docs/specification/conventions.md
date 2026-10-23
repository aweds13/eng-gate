# conventions.md — 横切基线（不能违反什么）

> 规格层里写「做什么」，这份文件写「**无论做什么都不许碰**」。
> 改这份文件要给理由，且要改 `decisions.md` 对应条目。

## C1 不碰风控与鉴权
**不实现 PoW（工作量证明）求解、不伪造设备指纹、不复刻登录流程、不绕过任何限流或风控。**
理由：REA 项目自己的 `DISCLAIMER.md` 就把 bypassing bot protection 排除在外；而且用户已改走官方 API（D4）。
边界：本项目只做一件事——**拿用户自己的 API key，调用户有权调的公开 API**。

## C2 不抓网页端
不做 DOM 抓取、不做 Playwright 驱动、不注入浏览器扩展。
理由：用户原话撤回（T1）。抓来的内容永远是二手且易碎。

## C3 不存账号密码
只存 API key（及可选的 baseURL / 模型名）。**绝不**存 DeepSeek 账号、密码、cookie、session token。

## C4 模型名不许写死
型号名的唯一真源是 `GET /api/list-models`。代码里出现硬编码模型 id 的地方，只能出现在
「默认值」「探测用例」两种位置，且必须能被清单覆盖。
理由：用户明确担心「模型会更新，不同的前缀名字会有不同」（D9）。

## C5 图片只能出现在 user 消息
API 硬约束：图片放 system / assistant 消息会返回 400。
边界：教材页的「上下文说明」（书名、页码）只能是文本，不能带图。

## C6 公式原文取 LaTeX 源
渲染与复制都读 LaTeX 源串，**不许**从渲染后的可见文字反推公式。
理由：从 `x²` 反推出的是 `x^2` 的猜测，映射回去必错（下标、分式、矩阵都会走样）。

## C7 教材图不长期托管
教材页只在本机存；随请求送出时用 base64 或临时上传，用完即弃。
理由：官方 App 自己都会提示 `The file has expired. Please re-upload.`（`evidence.md` §4）。

## C8 SymPy 的结论不得被表述为「正确」
它是**第二意见**，不是判决书。UI 文案禁止出现「已验证正确」「答案无误」，只能说
「SymPy 得到同样的结果」/「两边不一致」。三方都不一致时**必须**展示不一致，不许折叠掉。
理由：`simplify` 自己会慢、会化简不到位（`evidence.md` §2）。

## C9 许可证红线
发布物里**不得打包 AGPL-3.0 / GPL-3.0 的代码**。
已核实：`cherry-studio` 是 AGPL-3.0、`chatbox` 是 GPL-3.0、`lobehub` 是 NOASSERTION ⇒ 一律不引入。
可引入：MIT（big-AGI、KaTeX、markdown-it）、BSD（SymPy）、Apache-2.0（mathjs、Shiki）。

## C10 密钥不落地明文
key 存 Android Keystore 保护的加密区；导出备份时**默认不导出密钥**（要用户显式勾选，且导出物加密）。

## C11 花钱的地方要如实显示
搜索按次计费（$0.75/1000 次）、token 按量计费。界面上显示的调用次数与花费**不许四舍五入成 0**，
少于 1 分钱就显示「< $0.01」。理由：这是用户的钱。

## C12 不许静默失败
任何一次 API 调用失败，必须有一个可见的面（行内错误条 / 顶部提示），且**不得丢消息**。
失败的消息留在原处可重试，不许悄悄吞掉。

## C13 单一真源
- 模型清单 → `list-models`
- 教材页码 → 用户编号（不是文件名、不是 OCR 猜的序号）
- 分支关系 → `parentId` + 分支点消息 id（不是靠消息内容猜）

## C14 本项目只碰两个前缀
- **能写**：`src/dsmate/**`、`复盘/卡/卡D*.md`。
- **只读**：其余全部，含 `docs/workbacklog.toml`、`docs/partitions.toml`、`docs/traceability.toml`、
  `gates/`、`tools/`、`skills/`。唯一例外是登记与落地时由 `tools/wb_plan.py` / `tools/wb_land.py`
  自己写账务文件——那是工具写的，不是我手改的。
- **提交一律 path 限定**：`git commit -m … -- <paths>`。**禁止 `git add -A` / `git commit -a`**。
  这个仓同时有别的窗口在干活，`-A` 会把别人的暂存吞进我的提交（2026-10-23 `38e5b1cc`
  真实发生过：我的 D 分区被扫进另一个窗口的落地）。
