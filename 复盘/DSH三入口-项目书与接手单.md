# DSH 三入口（工具箱 / 禅道 / timeflow）：当一个大项目接手

> 结论先说：这三样**不是三个小功能**，是一个「能用但不成器」的项目。
> 本页是接手单：现状 → 缺口 → 验收数字 → 拆卡 → 谁来做。

## 1. 症状：为什么「别人的插件直接打开，我们的要等」

实测读数（2026-10，DSH 桌面 59137 / 面板插件工作区版）：

| 观测 | 读数 | 位置 |
|---|---|---|
| 左栏点「工具箱」到出内容 | 6 处「读数中…」占位挡在首帧 | 客户端 `SourceShell` |
| 客户端缓存 | **0 命中**（无 `localStorage` / 无 `cache` / 无 stale 复用） | 装好的 `lib/client.js` |
| 最慢读数 | `stack-status` **2.15 s**（spawn `stack.py status` 探 5 个端口） | 宿主 `/dsh-panel/stack-status` |
| 其余读数 | 0.15–0.55 s（`/workbench-board` 0.44，`/zentao-gantt` 0.18，`/timeflow-inbox` 0.15） | 同上 |
| 别人的插件 | 首帧即本地渲染，不阻塞于 HTTP | DSH 内置页 |

→ 差异不在网络，在**渲染策略**：我们是「等数据 → 才画」，内置页是「先画壳 → 数据到了再填」。

## 2. 缺口清单（四项，按用户体感排序）

1. **首屏阻塞**：任何一次读数慢，整页就是「读数中…」；断网/服务停则永远停在那。
2. **内嵌页白屏**：禅道/时间流 iframe 直连，服务停或首答慢 ⇒ 白框，且没有「一键启动」入口（工具箱里才有）。
3. **层级重复**：工作台状态（8787）与工具箱总览是两份状态，A286 已把前者收进后者，但入口文案/回退路径还没统一。
4. **右栏不可用时不降级**：宿主无 session surface 时报 `sidebarRight: no session surface is mounted`，应自动退回「内嵌/新窗」。

## 3. 验收数字（不达标就不算完）

- 首屏有内容 **< 150 ms**（用上次读数或骨架，**不得**出现「读数中…」独占首帧）。
- 冷启动首次读数 **< 1.2 s**；`stack-status` 加**宿主内存缓存 TTL 5 s**，二次 < 50 ms。
- 服务全停时：三个入口都能画出壳 + 「一键启动」，**不白屏、不空白**。
- 任一读数失败：状态点变红 + 原话（HTTP 码/异常），**不留空白**。
- `python -X utf8 tools/dsh_panel.py --check` 绿；`pytest tests/test_dsh_panel.py` 全绿；零颜色字面量。

## 4. 拆卡（走 infra 记法：卡 → 工人 → 门禁 → 落地）

| 卡 | 工作包 | 内容 | 判据 |
|---|---|---|---|
| A289 | WP1 首屏秒开 | 客户端 stale-while-revalidate + localStorage 上次读数；宿主 `stack-status` 内存缓存 TTL；`useSource` 改「先给上次值，再后台刷新」 | 验收 1、2 |
| A290 | WP2 内嵌页壳 | iframe 先画工具条；服务 down ⇒ 壳 + 一键启动；加载超时 8 s 给提示；右栏不可用自动降级 | 验收 3、4 |
| A291 | WP3 项目书 | 本页（已写）落进 git，巡检能引用 | 本文件在库里 |
| A292 | WP4 skills 注册 | 仓库 `skills/` 挂进 DSH `customSkillDirs`（已改 profile，待重启验证） | 重启后目录里出现 pipe-* |

## 5. 接手方式（照 infra 与 skills 的流程）

- 判据在库/门：`tools/dsh_panel.py --check`、`tests/`、`scripts/audit_progress.py`、`tools/wb_land.py`。
- 操作知识在 `skills/`：`pipe-card`（建卡/申报）→ 工人 → `pipe-gate`（三值判决）→ `pipe-land`（集成）。
- 面板本身**只读**：除 `tools/settings.toml` 参数写口子外不写仓库、不起工人。
- 外包：一块工作包一张卡，一张卡一个工人；落地由我串链，工人不直接合主树。

## 6. 待用户拍板

1. 首屏数字（150 ms / 1.2 s）是否按此验收？
2. 禅道内嵌是保留 iframe（走反代）还是改成「只读看板 + 打开真页」两段式？
