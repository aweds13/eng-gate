# 写法参考 · feat/ui-refactor 分支（仅作参考，以当前工作为准）

> **定位**：本文件是**写法参考**，不是当前主线的规格。
> - 主线 = `audit-snapshot` 分支（约定层 + 契约层 + 本次复盘）。
> - 本文件只记录：**另一条分支 `feat/ui-refactor` 当初是怎么写那些缺口的**，供以后写具体实现时借鉴。
> - ⚠️ **它没有被合并，也不并入**。只取"写法"，不取"结论"。
> - 分支信息：`feat/ui-refactor`，基点 `96ba466`，3 个提交（重构 UI + changelog + 修 5 缺口）。

---

## 一、这条分支做了什么

```
2db71c7  feat(ui): 重构为极简瑞士风+柔和UI——三栏聚焦布局、N32可视化(曲线/热力图/进度环)、
                  N30双主题/调色盘、SVG图标、toast/二次确认、数据洞察接口
556220e  docs: changelog 补 0.2.0 UI重构
01ab7f5  fix: 修复5个前端交互缺口（专注结束计时/恢复移出按钮/删除撤销/详情编辑/调色盘同步）
              + sqlite并发500（每请求独立连接）+ B008按文件忽略
```

**结构变化**：前端从「单文件 `index.html`（195 行）」→ 拆成 `index.html`(42) + `app.css`(147) + `app.js`(333)；
后端新增 `core/insights.py`(51 行) + `tests/test_insights.py`(44 行)。

---

## 二、可直接借鉴的写法（4 个）

### 写法 1：专注计时器（前端）—— `startClock()`

**问题**：MVP 缺口 OP-3/OP-4（无计时 UI、无法结束）。
**它的写法**：三个模块级变量 + `setInterval` 每 500ms 刷新 + 番茄到点自动结束。

```js
let focusTimer = null, focusSessionId = null, focusStartTs = 0;
const POMODORO_MS = 25*60*1000;

function startClock(){
  const el = document.getElementById("focusClock");
  if (!el) return;
  const tick = ()=> {
    const remain = Math.max(0, POMODORO_MS - (Date.now()-focusStartTs));
    el.textContent = new Date(remain).toISOString().slice(14,19);   // HH:MM:SS
  };
  tick();
  if (focusTimer) clearInterval(focusTimer);
  focusTimer = setInterval(tick, 500);
}

async function startFocus(kind){
  const s = await api("/api/focus/start",{method:"POST",body:JSON.stringify({kind})});
  focusSessionId = s.id; focusStartTs = Date.now();
  const dur = kind==='tomato'?POMODORO_MS:30*60*1000;
  toast("专注已开始");
  if (kind==='tomato') setTimeout(()=>stopFocus('finished'), dur);  // 番茄到点自动结束
  view(current);
}

async function stopFocus(status){
  if (!focusSessionId) return;
  const duration = Math.round((Date.now()-focusStartTs)/1000);
  await api(`/api/focus/${focusSessionId}/finish`,{method:"POST",
    body:JSON.stringify({duration_sec:duration,status})});
  toast(status==='finished'?"专注完成，已计入投入":"已记中断");
  clearInterval(focusTimer); focusSessionId=null; focusTimer=null;
  view(current);
}
```

**UI 侧**：计时中用条件渲染显示时钟 + 两个按钮（`记中断(interrupted)` / `结束(finished)`）：
```js
${focusSessionId?`<div class="card"><div class="title">专注进行中…</div>
  <span id="focusClock" style="font-size:28px;font-weight:800;color:var(--accent)"></span>
  <button class="btn danger sm" onclick="stopFocus('interrupted')">记中断</button>
  <button class="btn sm" onclick="stopFocus('finished')">结束</button></div>`:""}
```

**✅ 值得借鉴**：计时实现、状态用模块变量而非框架、条件渲染。
**⚠️ 它的不足（我们契约要求而它没做）**：
- **时长只写进 `focus_sessions`，没有触发记账/反馈累加**（OP-4 后续四步仍缺）。
- **无法绑定任务**（`startFocus` 不传 `task_id`）。
- toast 说"已计入投入"，**实际没计入** —— 属"虚假反馈"。

---

### 写法 2：数据洞察接口（后端）—— `core/insights.py`

**问题**：MVP 缺口 OP-7（摘要口径）与 SR-NF3（可视化无数据支撑）。
**它的写法**：一个纯数据聚合函数，按天返回三元组，前端负责可视化。

```python
def daily_insights(conn, days: int = 14) -> list[dict[str, object]]:
    """返回近 days 天（含今天）每天：投入分钟 / 债务数 / 习惯打卡数。"""
    today = date.today()
    start = today - timedelta(days=days - 1)
    result = []
    for i in range(days):
        d = (start + timedelta(days=i)).isoformat()
        focus = conn.execute(
            "SELECT COALESCE(SUM(duration_sec),0) FROM focus_sessions "
            "WHERE status = 'finished' AND substr(started_at,1,10) = ?", (d,)).fetchone()
        debt = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE due_date IS NOT NULL AND due_date < ? "
            "AND status NOT IN ('完成','取消','归档')", (d,)).fetchone()
        habit = conn.execute(
            "SELECT COUNT(*) FROM habit_logs WHERE date = ? AND done = 1", (d,)).fetchone()
        result.append({"date": d,
                       "focus_minutes": round((focus[0] or 0)/60.0, 1),
                       "debt_count": int(debt[0] or 0),
                       "habit_done": int(habit[0] or 0)})
    return result
```

**✅ 值得借鉴**：
- **"后端出数据、前端出图表"的分工** —— 正好落在 SR-NF3（不同数据用最合适呈现）与约定层（计算型走结构化）。
- 一次调用返回多域时序，前端一张图复用。
- 有 `days` 边界校验（路由层限 1–90）。

**⚠️ 注意**：它的投入口径仍用 `status='finished'`，**和"开始即 finished"的老状态机耦合**——若沿用，须先修状态机（见写法 3 的缺口）。

---

### 写法 3：二次确认 + 删除（前端）—— `delTask()` + `confirmBox()`

**问题**：MVP 缺口 OP-6（无删除入口、不可逆操作要确认）。
**它的写法**：把"确认"抽成一个通用函数，删除走确认回调。

```js
async function delTask(id){ confirmBox("确定删除这个任务？", async ()=>{
   await api(`/api/tasks/${id}`,{method:"DELETE"}); toast("已删除"); view(current);
});}
```

**✅ 值得借鉴**：
- **`confirmBox` 抽通用** —— 约定层红线「不可逆操作须二次确认」可复用（删除/删分组/债务重组都要）。
- 与 `toast()` 配套，形成"操作 → 确认 → 反馈"三件套。

---

### 写法 4：任务详情编辑（前端）—— `showDetail()` + `saveDetail()`

**问题**：MVP 缺口 OP-1/OP-5（无法查看/编辑字段）。
**它的写法**：详情弹层 + 保存函数。

```js
async function saveDetail(id){ /* 收集表单字段 → PATCH /api/tasks/{id} → 刷新 */ }
```

**✅ 值得借鉴**：以弹层承载"编辑"，避免列表膨胀（对应 SR-NF4「重信息点进去才有」）。

---

### 写法 5（基础设施）：每请求独立连接 —— 修 sqlite 并发 500

**问题**：`create_app` 里全局一个 `conn`，并发请求即 500。
**它的写法**：路由用依赖注入拿连接 —— `def groups(conn: sqlite3.Connection = Depends(get_conn))`。

```python
@app.get("/api/tasks")
def list_tasks(conn: sqlite3.Connection = Depends(get_conn)) -> list[TaskOut]:
    ...
```

**✅ 值得借鉴**：**这是纯收益的工程修复**，与业务无关，可直接采纳到主线。

---

## 三、它**没有**解决的（重要：别误以为它修好了）

| 我们契约要求 | feat 分支状态 |
|---|---|
| OP-4 结束专注 → **记投入账** | ❌ **没做**（只落 `focus_sessions`；toast 却宣称"已计入投入"） |
| OP-4 结束专注 → **累加当日反馈** | ❌ 没做 |
| OP-4 结束专注 → **累加绑定任务** | ❌ 没做（且无法绑定任务） |
| OP-3 专注**可绑定任务** | ❌ 没做（`startFocus` 不传 `task_id`） |
| 专注**状态机**（开始应为"进行中"） | ❌ **后端仍返回 `STATUS_FINISHED`**（开始即完成的老问题没修） |
| OP-1 新建任务**可设截止日** | ❌ 没做（仍是 `{title,is_myday:true}` 风格） |
| OP-2 **挑已有任务进 My Day** | ⚠️ 只"恢复了移出按钮"，未见"加入"入口 |
| OP-5 完成**记投入账** | ❌ 没做 |
| OP-8 Repeat **触发点** | ❌ 没做 |

**一句话：feat 分支修的是"第①层操作闭环"的一半（前端能点、能动），完全没碰"第②层模块联动"。**

---

## 四、结论：怎么用这条分支

| 用途 | 可取 | 不可取 |
|---|---|---|
| 专注计时器写法 | ✅ 取 `startClock/stopFocus` 骨架 | ❌ 别照抄"宣称计入投入"的假反馈 |
| 可视化数据层 | ✅ 取 `insights.py` 分工 | ❌ 别沿用耦合旧状态机的口径 |
| 确认/toast 基建 | ✅ 全取 | — |
| 每请求独立连接 | ✅ 全取（纯收益） | — |
| 前端三文件拆分 | ✅ 可参考结构 | ❌ 别整体替换（与契约未对齐） |
| 作为"已完成"依据 | ❌ **不可** —— 联动全缺 | |

> **正确姿势**：按 `contracts/interactions.md` + `flows.md` 写实现，**遇到"计时器/确认框/洞察聚合"这类局部难题时，翻本文件抄写法**；其余一切以主线契约为准。
