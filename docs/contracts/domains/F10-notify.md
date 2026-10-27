# SR-F10 学校通知接口 · 操作与动线契约

> 六要素见 `../interactions.md`；横切行为见 `../../specification/behaviors.md`。
> 规格定位见 `../../specification/domains/F10-notify.md`：**监测由独立脚本做，主工具只提供合作接口**。
> 复盘（口径取舍 / 三个坑 / 遗留）见 `../../../复盘/学校通知合作接口-T-G14.md`。

## OP-44 外部通知导入（合作接口）

- 入口：外部脚本 → `POST /api/notify/school`；设置页「学校通知（合作接口）」一节看开关、字段表与示例。
- 前置：① 本机来源（跨站来源一律 403）② 设置页把开关打开（**默认关**，关着时投递 **403 带原话**）。
- 输入：`source`（必填）、`title`（必填）、`external_id`、`url`（http/https）、`summary`、`at`、
  `due_date`；**其余字段原样存进 `extra`**（扩展位，不写死）。
- 后续：落进收件箱（`school_notices`）→ 标来源 → 你看一眼 → 点「转成任务」才建任务。
- 可逆：忽略可改回待看（**不删行**：删了下次投递又回来，反而像"没收到过"）；
  转出来的任务按任务自己的规矩删/取消。
- 反馈：投递返回 `{id, created, duplicate, updated, notice}`（新收下 / 重复 / 重复且内容变了）。
- 边界：主工具**不抓取**；重复投递**去重靠数据库唯一索引**（`fingerprint`）；
  参数错 **400**、"未接入" **403**（两种状态码刻意分开：一个要用户去点开关，一个要脚本改代码）；
  外部脚本没跑时主工具什么都不做。

- **实现（T-G14，2026-09-23）**：schema **v18** `school_notices`（`fingerprint` 唯一 +
  `extra` 扩展位 + `status`/`task_id`），规则与措辞**一处**写在 `src/timeflow/core/notify.py`
  （`api/app.py` 只做 HTTP 落地与来源校验；放在 core 而不是 `getaways/`：`getaways/` 是给出站
  适配器留的位，这一版是"本机合作用的 HTTP 接口 + 领域逻辑"，与 `core/ai.py` 同类）：
  - `GET·PUT /api/settings/notify`（现状 + 字段表 + 自述 / 开关，**默认关**）；
  - `GET /api/notify/school?status=&limit=`（收件箱，新的在前）、`POST /api/notify/school`（投递）；
  - `POST /api/notify/school/{id}/to-task`（**你点一下才发生**；走 `tasks.create_task` 同一条路，
    备注记着"来自学校通知：来源 · 时间 · 链接 · 摘要"；**幂等**，已转过再点返回同一个任务，
    且不再看这次传的参数）；
  - `POST /api/notify/school/{id}/ignore`（`{ignored:false}` 改回待看；已转任务的不许忽略）；
  - 三件**不要求开关开着**：转任务 / 忽略 / 看收件箱 —— 开关管的是"脚本能不能投递"，
    收件箱里已经是你的数据；
  - **不进同步包**（`syncpack.EXCLUDED_TABLES` 显式记着："是收件箱，不是你自己写的东西"）；
  - 验证：`../../../tests/test_school_notify_line.py`（18 条）+ 真机自检 9 条
    + DOM 探针「设置·学校通知」1 档（三种状态三种按钮 + 两种空态分得开）。

## 验收

- **不纳入第一版 AC**（F10 不是第一版验收项，它是"给外部脚本留的口子"）；
  行为由上面的测试映射与真机自检钉住。
