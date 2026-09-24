/* 真浏览器 + 真后端的**共用底座**（T-G34 抽出来的）。
 *
 * 为什么抽出来：`render_check.mjs`（黄金几何层，T-G32）与 `ui_flow_check.mjs`（行为流层，T-G34）
 * 需要的是同一样东西 —— 起一个**干净的库**、起**真浏览器**、把渲染环境**钉成确定的**。
 * 这些细节每一条都是踩出来的（滚动条吃掉 15px、随机设备号、mkdtemp 随机目录名…），
 * 抄一遍就是等着两份慢慢长歪。所以：**一处实现，两个工具都用它**。
 *
 * 这里只放"怎么把环境和浏览器弄起来"，**不放判据**：
 *  · 黄金层判「变了没有」→ 清单与黄金比，归 `render_check.mjs`；
 *  · 流层判「能不能用」→ 真点击/真按键后的行为，归 `ui_flow_check.mjs`。
 * 判据留在各自工具里，这一层保持沉默（不打印、不返回结论，只返回事实）。
 */
import { spawn } from 'node:child_process'
import { existsSync, rmSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as sleep } from 'node:timers/promises'

export const HERE = dirname(fileURLToPath(import.meta.url))
export const ROOT = join(HERE, '..')

/* ------------------------------------------------- 视口 / 视图（与 CSS 断点对齐） */

// app.css 的三条断点：≥980 有左栏（桌面三栏）、641–979 单列+宽底栏、≤640 手机。
// 所以取三档：只要覆盖到"左栏在不在"和"手机那条断点"，就不会有断点带没人看过。
export const VIEWPORTS = [
  { name: 'desktop', width: 1280, height: 900 },
  { name: 'narrow', width: 820, height: 900 },
  { name: 'phone', width: 390, height: 844 },
]
export const VIEWS = ['today', 'tasks', 'important', 'planned', 'flagged', 'focus', 'stats',
  'habit', 'academic', 'review', 'memo', 'team', 'setting', 'offline']
// 采集时钉住的"这台设备是谁"（`offline.js` 的 `tf_device`，正常是随机生成的）
export const FIXED_DEVICE = 'ph-000000000000'
// 采集时钉住的导出目录（`serve.py --fresh` 默认用 mkdtemp 的随机名，见 `startServer`）
export const EXPORT_DIR = join(process.env.TEMP ?? process.env.TMP ?? '/tmp', 'tf-render-export')
// 清单里要把这些**字面前缀**换成 `<path>`：本机临时目录（导出目录、临时库都在它下面）。
// 机器路径不是设计，写进黄金只会泄露用户名、还会让黄金换机器就红。
export const MASK_PATHS = [process.env.TEMP ?? process.env.TMP ?? '/tmp', EXPORT_DIR]

/* ---------------------------------------------------------------- 工具 */

export function iso(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
/** 相对某个基准日偏移 n 天（不传基准 = 真今天，或采集层钉住的那一天）。
 *
 *  T-G62：验证层把「今天」钉在某一天（`CAPTURE_DAY`），fixture 必须**按那一天**算相对日期 ——
 *  否则"服务器以为是 6-15、数据是按 9-25 造的"，两边对不上，采出来的就是自相矛盾的界面。
 *  基准日由采集工具通过 `setFixtureDay()` 设；不设时行为与以前完全一样（真今天）。
 */
let FIXTURE_DAY = null
export function setFixtureDay(day) { FIXTURE_DAY = day || null }
export function dayOffset(n, base = FIXTURE_DAY) {
  const d = base ? new Date(`${base}T12:00:00`) : new Date()
  d.setDate(d.getDate() + n)
  return iso(d)
}

/* ---------------------------------------------------------------- 假时钟（T-G62） */

/** 采集时钉住的那一天：**必须是一个固定的日期常量**，不能算成"真今天"。
 *
 * 为什么（真实事故）：渲染黄金里有两个视图锚在「今天」上（`habit` / `stats` 的热力图窗口
 * 是「53 周、到今天为止」且未来几天不渲染）→ 同一个星期内每过一天就多一个格子，
 * 2026-09-25 00:0x 跨过午夜重跑，红 **6 份**。钉住它之后：黄金跨天、跨几点都不再变。
 * 选 2026-06-15 只是"一个普通的日子"（周一，离任何边界都远）。
 */
export const CAPTURE_DAY = '2026-06-15'

/** 钉住浏览器时钟的垫片（在页面脚本**之前**执行）。
 *
 * 为什么两边都要钉：`clock.py` 钉的是**服务器**的「今天」，而习惯热力图/统计页的网格
 * 是**前端**用 `new Date()` 算的 —— 只钉一边，"服务器以为 6-15、浏览器以为今天"，
 * 界面里的对账会自相矛盾（那不是验证，是伪造一个界面）。
 * 只覆盖 `Date`（`Date.now()` 与无参构造）；`setTimeout` 之类与它无关，
 * 而本层只做**静态采集**，不需要时间真的走。
 */
export function clockShimSource(day) {
  return `(() => {
    const FIXED = new Date(${JSON.stringify(`${day}T12:00:00`)}).getTime();
    const Real = Date;
    class FakeDate extends Real {
      constructor(...args) { if (args.length === 0) super(FIXED); else super(...args); }
      static now() { return FIXED; }
    }
    FakeDate.parse = Real.parse;
    FakeDate.UTC = Real.UTC;
    window.Date = FakeDate;
  })()`
}
export { sleep }

/* ---------------------------------------------------------------- 起服务 */

/** 起一个**干净的**后端（`serve.py --fresh`：临时库 + 自动备份，只绑回环）。
 *  `extraEnv.TIMEFLOW_FAKE_TODAY` 就是 T-G62 的假时钟（采集层传 `CAPTURE_DAY`）。 */
export function startServer(port, extraEnv = {}) {
  const python = process.env.PYTHON ?? (process.platform === 'win32' ? 'python' : 'python3')
  const env = { ...process.env, ...extraEnv }
  const shim = join(ROOT, 'tools', 'sandbox_shim')
  env.PYTHONPATH = existsSync(shim) ? shim + (env.PYTHONPATH ? ';' + env.PYTHONPATH : '') : env.PYTHONPATH
  // 导出目录**钉成固定路径**（`serve.py --fresh` 默认用 mkdtemp 的随机名，
  // 于是设置页那句「默认 <路径> · 文件名就是日期：…」在不同轮次换长度，
  // 在 820px 这个换行临界宽度上会把折行位置也换掉 —— 实测只有 narrow/setting 会红）。
  // `serve.py` 用的是 `os.environ.setdefault`，所以我们先设就能盖住它。
  env.TIMEFLOW_EXPORT__DIR = EXPORT_DIR
  const child = spawn(python, ['-X', 'utf8', 'tools/serve.py', '--fresh', '--port', String(port)], {
    cwd: ROOT, env, stdio: ['ignore', 'pipe', 'pipe'],
  })
  let out = ''
  child.stdout.on('data', (b) => { out += b.toString() })
  child.stderr.on('data', (b) => { out += b.toString() })
  return { child, dump: () => out }
}

export async function waitHealth(port, timeoutMs = 30000) {
  const t0 = Date.now()
  while (Date.now() - t0 < timeoutMs) {
    try {
      const r = await fetch(`http://127.0.0.1:${port}/api/health`)
      if (r.ok) return true
    } catch { /* 还没起来 */ }
    await sleep(300)
  }
  return false
}

/* ---------------------------------------------------------------- 种子数据 */

/** 用**真 HTTP 接口**造一份确定性的 fixture（不直接写库：走界面一样的路）。
 *
 * 日期一律**相对今天**算：这样「今天 / 明天 / 已逾期 N 天」这类相对标签永远稳定，
 * 黄金不会因为"明天再跑一次"就整片变红。绝对时间戳由采集端归一化。
 * 不用/不碰的东西：正在跑的专注计时（每秒都在变）、软删除的回收站（带删除时刻）、
 * 「刚刚/N 分钟前」这类会自己走的文本。
 *
 * 两个工具共用同一份 fixture —— 这样"黄金里的那个界面"和"流里点的那个界面"是**同一份数据**。
 */
export async function seedFixture(port) {
  const base = `http://127.0.0.1:${port}`
  const problems = []
  async function call(method, path, body) {
    const r = await fetch(base + path, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
    const text = await r.text()
    if (!r.ok) { problems.push(`${method} ${path} → ${r.status} ${text.slice(0, 120)}`); return null }
    try { return JSON.parse(text) } catch { return null }
  }

  // 分组（两级：路径显示用）。注意 `set_task_groups` 收的是**分组 id** 不是路径 ——
  // 这正是建这一层时撞出 T-G33 的地方（当时传了一个不存在的分组，接口直接 500；
  // 现在不存在的分组会干净地 404 并说清是哪个 id，见 `复盘/接口500-分组不存在-T-G33.md`）。
  const g1 = await call('POST', '/api/groups', { name: '高数' })
  const g2 = g1 ? await call('POST', '/api/groups', { name: '作业', parent_id: g1.id }) : null
  const groupIds = g2 ? [g2.id] : []

  // 课程 → 作业/考试要挂在课程上
  const course = await call('POST', '/api/courses', { name: '高等数学', credits: 5, teacher: '王老师' })
  const courseId = course?.id ?? null

  // 任务：覆盖 逾期 / 今天 / 有计划 / 重要 / 已标记 / 完成 / 子步骤 / 尝试失败
  // 优先级只有 高/中/低 三档（中文，领域层定的），任务类型只有 普通/作业/考试/论文/小测。
  //
  // ★ 日期偏移有**硬约束**（T-G40 实测抓到的第二个坑）：周结算的债务取的是**周日快照**
  //   （`weekly_summary` 的 `end` = 本周日），而"周日离今天几天"随**星期几**变（周一 6 天、周日 0 天）。
  //   于是**未完成**任务的偏移只有两类是稳的：**≤ -1**（哪一天看都已经逾期，恒计债）
  //   与 **≥ +7**（永远落在周日之后，恒不计债）；偏移 0…+6 会让债务读数随星期几变 ——
  //   黄金就"没有任何代码改动、第二天自己变红"（那正是用户最恨的漂移）。
  //   下面一律照这条摆：逾期那条 -2，其余**未完成**的全部 ≥ +7（已完成的不影响债务：按状态排除）。
  const overdue = await call('POST', '/api/tasks', { title: '补交上周的实验报告', due_date: dayOffset(-2), priority: '高', groups: groupIds })
  const todayTask = await call('POST', '/api/tasks', { title: '把第三章习题做完', due_date: dayOffset(7), is_myday: true, priority: '高', flagged: true, note: '重点是 3.4 的证明题' })
  const planned = await call('POST', '/api/tasks', { title: '预习下周的线性代数', due_date: dayOffset(9), priority: '中' })
  const parent = await call('POST', '/api/tasks', { title: '写课程设计报告', due_date: dayOffset(14), priority: '低' })
  if (parent) {
    const s1 = await call('POST', `/api/tasks/${parent.id}/subtasks`, { title: '列提纲', due_date: dayOffset(11) })
    await call('POST', `/api/tasks/${parent.id}/subtasks`, { title: '写正文', due_date: dayOffset(12) })
    if (s1) await call('POST', `/api/tasks/${s1.id}/complete`)
  }
  const tried = await call('POST', '/api/tasks', { title: '重装打印机驱动', due_date: dayOffset(10), priority: '中' })
  if (tried) {
    await call('POST', `/api/tasks/${tried.id}/attempt-failed`, { note: '换了 USB 口也不行' })
    await call('POST', `/api/tasks/${tried.id}/attempt-failed`, { note: '官网驱动装到一半报错' })
  }
  // 已完成的那条**可以**用 0：债务按状态排除，它的日期不参与任何读数（"今天"这个日期本身照旧被渲染出来）
  const done = await call('POST', '/api/tasks', { title: '交英语作业', due_date: dayOffset(0), is_myday: true })
  if (done) await call('POST', `/api/tasks/${done.id}/complete`)
  const assignment = await call('POST', '/api/tasks', { title: '把数据整理成表', due_date: dayOffset(13), priority: '中' })

  void overdue; void todayTask; void planned

  // 学业：课程 + 考核 + 成绩
  if (courseId) {
    await call('POST', '/api/assessments', { course_id: courseId, name: '期中考试', due_date: dayOffset(9), weight: 0.4 })
    await call('POST', '/api/grades', { course_id: courseId, term: '2026 秋', score: 86, credits: 5 })
    const hw = await call('POST', '/api/tasks', { title: '第三章习题', due_date: dayOffset(8), task_type: '作业', course_id: courseId })
    void hw
  }

  // 习惯：一个做过、一个没做（两种状态都要进黄金）
  const h1 = await call('POST', '/api/habits', { name: '早睡' })
  const h2 = await call('POST', '/api/habits', { name: '跑步' })
  if (h1) await call('POST', `/api/habits/${h1.id}/toggle`)
  void h2

  // 复习卡（due 与否都行，页面本身要能渲染）
  await call('POST', '/api/review/items', { title: '拉格朗日中值定理', ref_handle: '高数 · 第三章' })

  // 备忘录（注意：`--fresh` 已把 markdown 落盘目录指到临时目录，不会写进仓库 export/ 或 Vault）
  await call('POST', '/api/memos', { text: '问老师期中考试的题型分布' })

  // 团队分配（谁负责 / 进展到哪）
  if (assignment) await call('POST', '/api/team/assign', { task_id: assignment.id, assignee: '小李', assigner: '我' })

  // 账本一条手动投入（**单位：秒**）：让统计页有非零内容
  await call('POST', '/api/ledger/invest', { value: 2700, kind: 'focus', note: '专注写报告' })

  return problems
}

/* ---------------------------------------------------------------- 浏览器 */

const EDGE_CANDIDATES = [
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
  '/usr/bin/microsoft-edge',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium',
]

export function findBrowser() {
  if (process.env.TF_CHROME && existsSync(process.env.TF_CHROME)) return process.env.TF_CHROME
  for (const p of EDGE_CANDIDATES) if (existsSync(p)) return p
  return null
}

export class Cdp {
  constructor(ws) { this.ws = ws; this.id = 0; this.pending = new Map() }

  static async attach(browserPath, port, profileDir) {
    rmSync(profileDir, { recursive: true, force: true })
    const child = spawn(browserPath, [
      '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
      '--disable-crash-reporter', '--disable-extensions', '--hide-scrollbars',
      `--remote-debugging-port=${port}`, `--user-data-dir=${profileDir}`, 'about:blank',
    ], { stdio: 'ignore' })
    let page = null
    for (let i = 0; i < 60 && !page; i++) {
      try {
        const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()
        page = list.find((t) => t.type === 'page' && t.webSocketDebuggerUrl)
      } catch { /* 还没起来 */ }
      if (!page) await sleep(400)
    }
    if (!page) { child.kill(); return null }
    const ws = new WebSocket(page.webSocketDebuggerUrl)
    await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej })
    const cdp = new Cdp(ws)
    cdp.child = child
    ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data)
      if (m.id && cdp.pending.has(m.id)) { cdp.pending.get(m.id)(m); cdp.pending.delete(m.id) }
    }
    await cdp.send('Page.enable')
    await cdp.send('Runtime.enable')
    // 把滚动条**显式**藏掉：设置页有 6000px 高，一条竖滚动条会吃掉 15px 内容宽，
    // 于是"同一份清单"在不同轮次里宽度差 13px（实测踩到）。`--hide-scrollbars` 那个启动参数
    // 不够硬 —— 这里用 CDP 再钉一次。**这不是"把差异涂掉"，是把渲染环境钉成确定的。**
    await cdp.send('Emulation.setScrollbarsHidden', { hidden: true })
    return cdp
  }

  send(method, params = {}) {
    return new Promise((res) => {
      const id = ++this.id
      this.pending.set(id, res)
      this.ws.send(JSON.stringify({ id, method, params }))
    })
  }

  async eval(expression) {
    const out = await this.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })
    if (out.result?.exceptionDetails) {
      throw new Error('页面里抛错：' + JSON.stringify(out.result.exceptionDetails).slice(0, 400))
    }
    return out.result?.result?.value
  }

  /** 钉住**浏览器**的「今天」（T-G62）—— 在页面脚本之前注入 `Date` 垫片。
   *
   *  为什么必须和服务器一起钉：热力图/统计页的网格是**前端**用 `new Date()` 算的，
   *  只钉服务器会得到"服务器以为 6-15、浏览器以为今天"的自相矛盾界面。
   *  用 `addScriptToEvaluateOnNewDocument`：每次导航都会先跑它（比"导航完再 eval"可靠 ——
   *  后者跑在应用脚本之后，页面里第一次 `new Date()` 已经用了真时间）。
   */
  async installClock(day) {
    await this.send('Page.addScriptToEvaluateOnNewDocument', { source: clockShimSource(day) })
  }

  async navigate(url) {
    const done = new Promise((res) => {
      const prev = this.ws.onmessage
      this.ws.onmessage = (ev) => {
        const m = JSON.parse(ev.data)
        if (m.method === 'Page.loadEventFired') res()
        prev(ev)
      }
    })
    await this.send('Page.navigate', { url })
    await Promise.race([done, sleep(20000)])
  }

  async shot(path) {
    const r = await this.send('Page.captureScreenshot', { format: 'png' })
    const data = r.result?.data
    if (data) writeFileSync(path, Buffer.from(data, 'base64'))
    return Boolean(data)
  }

  /* ---- 下面几个是 T-G34 为"行为流层"加的：**真的按下去**，不是 `el.click()` ----
   * 为什么要真鼠标事件：`el.click()` 会绕过命中测试 —— 一个被浮层盖住、被挤出视口、
   * 或者 `pointer-events:none` 的按钮，`.click()` 照样"成功"。而用户点不到就是点不到。
   * 所以：先滚进视口 → 算中心点 → `elementFromPoint` 做**命中测试** → 再真按。 */

  /** 元素**视口坐标**（先滚到视口中间；滚不动就按当前位置算）。 */
  async rectOf(selector) {
    return this.eval(`(() => {
      const el = document.querySelector(${JSON.stringify(selector)});
      if (!el) return null;
      el.scrollIntoView({ block: 'center', inline: 'center' });
      const r = el.getBoundingClientRect();
      return { x: r.x, y: r.y, w: r.width, h: r.height, cx: r.x + r.width / 2, cy: r.y + r.height / 2,
               text: (el.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 60) };
    })()`)
  }

  /** 命中测试：这个坐标上**真正会被点到**的是谁？返回 true = 就是它（或它的子元素）。 */
  async hitTest(selector, x, y) {
    return this.eval(`(() => {
      const el = document.querySelector(${JSON.stringify(selector)});
      if (!el) return { ok: false, why: '找不到元素' };
      const hit = document.elementFromPoint(${x}, ${y});
      if (!hit) return { ok: false, why: '那个坐标上没有元素（可能被滚出去了）' };
      const ok = hit === el || el.contains(hit) || hit.contains(el);
      const d = (n) => n ? n.tagName.toLowerCase() + (n.id ? '#' + n.id : '') +
        (n.className && typeof n.className === 'string' && n.className ? '.' + n.className.split(/\\s+/).join('.') : '') : '无';
      return { ok, why: ok ? '' : '那个点上其实是 ' + d(hit), hit: d(hit) };
    })()`)
  }

  async clickAt(x, y) {
    const p = { x: Math.round(x), y: Math.round(y), button: 'left', clickCount: 1 }
    await this.send('Input.dispatchMouseEvent', { type: 'mouseMoved', ...p, buttons: 0 })
    await this.send('Input.dispatchMouseEvent', { type: 'mousePressed', ...p, buttons: 1 })
    await sleep(30)
    await this.send('Input.dispatchMouseEvent', { type: 'mouseReleased', ...p, buttons: 0 })
  }

  /** 真按键（`Input.dispatchKeyEvent`）—— 走的是浏览器真正的事件管线，会触发 keydown/keyup。
   *  ★ 单字母也认（T-G61）：键盘层的快捷键就是字母（`t`/`f`/`r`/`n`…），
   *  一个个登记进表里只会让"加个键位"变成改工具 —— 字母的 VK 码与 ASCII 大写一致，可以直接算。 */
  async key(name) {
    const table = {
      Enter: { key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 },
      Tab: { key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9, nativeVirtualKeyCode: 9 },
      Escape: { key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27, nativeVirtualKeyCode: 27 },
      Backspace: { key: 'Backspace', code: 'Backspace', windowsVirtualKeyCode: 8, nativeVirtualKeyCode: 8 },
      // 方向键（T-G61：命令面板用 ↑↓ 换选中）
      ArrowDown: { key: 'ArrowDown', code: 'ArrowDown', windowsVirtualKeyCode: 40, nativeVirtualKeyCode: 40 },
      ArrowUp: { key: 'ArrowUp', code: 'ArrowUp', windowsVirtualKeyCode: 38, nativeVirtualKeyCode: 38 },
    }
    const k = table[name] || (/^[a-zA-Z]$/.test(name)
      ? { key: name.toLowerCase(), code: 'Key' + name.toUpperCase(),
          windowsVirtualKeyCode: name.toUpperCase().charCodeAt(0),
          nativeVirtualKeyCode: name.toUpperCase().charCodeAt(0) }
      : null)
    if (!k) throw new Error(`没有登记这个键：${name}（要用就往 Cdp.key 的表里加一条）`)
    await this.send('Input.dispatchKeyEvent', { type: 'rawKeyDown', ...k })
    await this.send('Input.dispatchKeyEvent', { type: 'keyUp', ...k })
  }

  /** 全选（Ctrl+A）—— 重填一个已经有内容的输入框时必须先清干净：
   *  光标落在中间时直接打字会**接在原文后面**（实测踩到：25:00-07:00 后面又接了 22:00-07:00，
   *  于是"合法时段加不上"伪装成了界面缺陷）。 */
  async selectAll() {
    const base = { key: 'a', code: 'KeyA', windowsVirtualKeyCode: 65, nativeVirtualKeyCode: 65, modifiers: 2 }
    await this.send('Input.dispatchKeyEvent', { type: 'rawKeyDown', ...base })
    await this.send('Input.dispatchKeyEvent', { type: 'keyUp', ...base })
  }

  /** 组合键（`Ctrl/⌘ + 字母`）—— 键盘层要用（T-G61：⌘K 命令面板）。
   *  CDP 的 `modifiers` 是位掩码：Alt=1 / Ctrl=2 / Meta=4 / Shift=8。
   *  界面认的是 `ev.ctrlKey || ev.metaKey`（两个平台各一套），默认发 **Ctrl**（这台机器是 Windows）；
   *  要验另一半就传 `{meta:true, ctrl:false}`。 */
  async chord(letter, { ctrl = true, meta = false, shift = false } = {}) {
    const up = String(letter).toUpperCase()
    const vk = up.charCodeAt(0)
    const modifiers = (ctrl ? 2 : 0) | (meta ? 4 : 0) | (shift ? 8 : 0)
    const base = { key: letter, code: 'Key' + up, windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk, modifiers }
    await this.send('Input.dispatchKeyEvent', { type: 'rawKeyDown', ...base })
    await this.send('Input.dispatchKeyEvent', { type: 'keyUp', ...base })
  }

  /** 逐字符**真打字**（keydown + char + keyup），不是 `value = '…'`。
   *  为什么要这样：`data-enter` / 输入校验 / 大小写与标点都只有真打字才经过；
   *  直接改 value 会绕过事件，测出来的"能用"是假的。
   *
   *  ★ 标点**只发 `char` 事件**（不发明文键码）。踩过的坑（T-G35）：第一版给每个字符都填
   *  `windowsVirtualKeyCode = charCode`，而 `.` 的 charCode 是 **46 = VK_DELETE** ——
   *  Chromium 照虚拟键码当"删除"处理，于是路径里的点**被静默吃掉**
   *  （`…205321.json` 变成 `…205321json`，后端回"找不到这个文件"）。
   *  字母数字的 VK 码与 ASCII 一致，照旧走按下/抬起；其余标点一律只发 `char`。 */
  async typeText(text) {
    for (const ch of text) {
      const base = { key: ch, text: ch, unmodifiedText: ch }
      if (/[0-9A-Za-z]/.test(ch)) {
        const vk = ch.toUpperCase().charCodeAt(0)
        await this.send('Input.dispatchKeyEvent', { type: 'rawKeyDown', ...base, windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk })
        await this.send('Input.dispatchKeyEvent', { type: 'char', ...base })
        await this.send('Input.dispatchKeyEvent', { type: 'keyUp', ...base, windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk })
      } else {
        await this.send('Input.dispatchKeyEvent', { type: 'char', ...base })
      }
    }
  }

  /** 焦点在谁身上（用来证明"键盘能走到这儿"）。 */
  async activeElement() {
    return this.eval(`(() => { const a = document.activeElement;
      return a ? a.tagName.toLowerCase() + (a.id ? '#' + a.id : '') + (a.dataset && a.dataset.action ? '[data-action=' + a.dataset.action + ']' : '') : '' })()`)
  }

  /** 断网模拟（DevTools 的那个 Offline 开关就是这条 CDP）：`navigator.onLine` 与 online/offline 事件都会跟着变。 */
  async setOffline(offline) {
    await this.send('Network.enable')
    await this.send('Network.emulateNetworkConditions', {
      offline, latency: 0, downloadThroughput: offline ? 0 : -1, uploadThroughput: offline ? 0 : -1,
    })
  }

  close() { try { this.ws.close() } catch { /* ignore */ } try { this.child?.kill() } catch { /* ignore */ } }
}

/* ---------------------------------------------------------------- 等页面安静 */

// 装一个"页面还在动吗"的计数器：**用 DOM 变动计数**，不用 innerHTML 长度。
// 为什么（第一版踩到）：设置页的强调色色板是等 `/api/config` 回来之后才补上 `on` 类的 ——
// 那一刻 innerHTML 只长了 3 个字符、且发生在"连续三次长度不变"之后，于是被当成"渲染完了"，
// 两遍采集结果不一致。**这个自检救了这条线**：黄金要是建在这种状态上，以后每次都会随机变红。
// 空转（transitions/动画）不改 DOM，不用管；`#clock` 每秒改一次文本，**必须排除**，否则永远不安静。
export const MUTATION_WATCH = `
(() => {
  if (window.__tfobs) return true;
  window.__tfmut = 0;
  window.__tfobs = new MutationObserver((recs) => {
    for (const r of recs) {
      const t = r.target.nodeType === 1 ? r.target : r.target.parentElement;
      if (t && t.closest && t.closest('#clock')) continue;
      window.__tfmut++;
    }
  });
  window.__tfobs.observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true });
  return true;
})()`

export async function waitQuiet(cdp, { quiet = 6, step = 120, max = 80 } = {}) {
  let last = -1
  let q = 0
  for (let i = 0; i < max && q < quiet; i++) {
    await sleep(step)
    const n = await cdp.eval('window.__tfmut')
    if (n === last) q++
    else { q = 0; last = n }
  }
}

/* 装一个"手上还有没有请求"的计数器（钩在 `fetch` 上）。
   为什么**必须**有它（T-G40，实测抓到的真缺陷）：`waitQuiet` 只看 DOM 变动，而"点一个视图"
   到"数据回来、`innerHTML` 被换掉"之间**一段 DOM 都不动** —— 于是它会在半路上宣布"安静了"。
   ★ 统计页就栽在这里（7 个接口串起来，含 371 天热力图）：**`stats` 的黄金一直是上一个视图
   （`focus`）的内容**（`desktop__stats.txt` 与 `desktop__focus.txt` 逐字节同大小、同 rows），
   两遍采集一遍冷一遍热才会红。装了它之后：**请求没落地就不算安静**。 */
export const FETCH_WATCH = `
(() => {
  if (window.__tffetch) return true;
  const st = { pending: 0, done: 0 };
  window.__tffetch = st;
  const orig = window.fetch;
  window.fetch = function (...args) {
    st.pending++;
    let p;
    try { p = orig.apply(this, args) } catch (e) { st.pending--; throw e }
    return p.finally(() => { st.pending--; st.done++; });
  };
  return true;
})()`

/** 等**真的闲下来**：DOM 连续 `quiet` 拍不变，**并且手上没有在飞的请求**。
 *
 *  两件事必须一起判 —— 只看 DOM 会撞上"请求在路上、页面一动不动"那个空档（T-G40 的缺陷）；
 *  只看请求也不行（`MUTATION_WATCH` 那条注释里的色板/`#clock` 都靠 DOM 计数才判得对）。
 *  没装 `FETCH_WATCH` 时按"没有请求"算（退化成 `waitQuiet`，不会假装更严）。 */
export async function waitIdle(cdp, { quiet = 6, step = 120, max = 120 } = {}) {
  let lastMut = -1
  let q = 0
  for (let i = 0; i < max && q < quiet; i++) {
    await sleep(step)
    const s = await cdp.eval(
      '({mut: window.__tfmut || 0, pending: window.__tffetch ? window.__tffetch.pending : 0})'
    )
    if (s.pending === 0 && s.mut === lastMut) q++
    else { q = 0; lastMut = s.mut }
  }
}

/** 等**应用启动完成**再动手：铺完配置、左栏渲染出来才算这一页真的起来了。 */
export async function waitApp(cdp, { tries = 60, step = 120 } = {}) {
  for (let i = 0; i < tries; i++) {
    await sleep(step)
    const booted = await cdp.eval(`document.querySelectorAll('.rail nav button').length > 0 && !!document.querySelector('#main').innerHTML.length`)
    if (booted) return true
  }
  return false
}

/** 把本机存储**钉成已知状态**并加载页面（两个工具都从这里起步，比的才是界面而不是"这台设备的历史"）。
 *
 * 为什么不能只清不写（实测踩到两次）：
 *   · 强调色的"当前选择"是**页面加载那一刻**从 localStorage 读进内存的（`initTheme`），
 *     以后再写 localStorage 也不会改它 —— 只清不写就会采到「色板一个都没选中」的中间态，
 *     而且它跟首屏时序有关、会来回翻；
 *   · 手机设备号 `ph-xxxxxxxxxxxx` 是 `offline.js` 首次运行时**随机生成**再存下的（`tf_device`），
 *     清掉之后每次加载都换一个。
 * 所以：清空 + 把这两个值**钉成常量**。钉住比"从清单里涂掉"更好 —— 值本身照比。
 */
export async function bootApp(cdp, url, { device = FIXED_DEVICE, accent = null, keep = [] } = {}) {
  await cdp.navigate(url)
  await cdp.eval(`(() => { try {
    localStorage.clear(); sessionStorage.clear();
    localStorage.setItem('tf_device', ${JSON.stringify(device)});
    ${accent ? `localStorage.setItem('tf_accent', ${JSON.stringify(accent)});` : ''}
    ${keep.map(([k, v]) => `localStorage.setItem(${JSON.stringify(k)}, ${JSON.stringify(v)});`).join('\n    ')}
  } catch (e) {} return true })()`)
  await cdp.navigate(url)
  const ok = await waitApp(cdp)
  await sleep(300)
  await cdp.eval('document.readyState') // 触一次，确保上下文活着
  // 装上"请求计数器"：**必须在第一次点视图之前**（T-G40）—— 之后每次渲染都能等到请求落地。
  await cdp.eval(FETCH_WATCH)
  return ok
}

/** 换一档宽度。**每次都要重钉滚动条可见性** —— `setDeviceMetricsOverride` 会把它一起重置。 */
export async function setViewport(cdp, vp) {
  await cdp.send('Emulation.setDeviceMetricsOverride', {
    width: vp.width, height: vp.height, deviceScaleFactor: 1, mobile: false,
  })
  await cdp.send('Emulation.setScrollbarsHidden', { hidden: true })
}
