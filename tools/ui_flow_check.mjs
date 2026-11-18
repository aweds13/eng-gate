/* 行为流层（T-G34）：**真浏览器 + 真点击 + 真按键**，把「待人工确认」里功能性的那部分搬给机器。
 *
 * 为什么还要一层（T-G32 的黄金层不够吗）：
 *   · 黄金层判的是「**看起来**变了没有」（几何清单逐字节比）——它不点任何东西；
 *     界面里"按钮点了没反应""点了报错""取消之后数据被改了"这类事，它一个字都不会说。
 *   · `web_live_check.py` 判的是**接口**，`ui_dom_probe.mjs` 判的是**假 DOM 里的渲染**。
 *     夹在中间那层一直空着：**真界面上真按下去，会怎样**。
 *   这一层就是那层。它搬的是 `复盘/交接-重构进度.md` §二「待人工确认 28 项」里**功能性**的那些：
 *   「能点开吗 / 关掉之后还来吗 / 填个非法值会不会被拦 / 二次确认是不是站内弹窗」。
 *   **搬不动的（喜欢不喜欢、这句话说得对不对）照旧留给人** —— 那不叫验证，叫决策。
 *
 * 三条纪律（最小验证法则下保留的那三条 —— 其余"为了更全"的想法一律不进这张卡）：
 *   ① 每条流都**声明它替掉哪一条人工项**（打印出来 + 测试钉住），"搬走了哪几条"有据可查；
 *   ② 真点击做**命中测试**（`elementFromPoint`）：被浮层盖住、被挤出视口的按钮，
 *      `el.click()` 会"成功"，而用户点不到 —— 所以这里一律真按坐标，且先验"那个点上是不是它"；
 *   ③ **不做"全覆盖"**：够用的条数就停（现在 **26** 条）。要加一条，得先说明它替掉哪条人工项。
 *
 * 已知边界（**不谎报**）：
 *   · 起不了浏览器 → 退出码 3（NOT RUN），**NOT RUN 不是 PASS**（`run_gates.py` 单列一栏）。
 *   · 它只验"行为对不对"，**不验好看**，也**不验口味**（文案好不好、版式美不美）。
 *   · 要人工准备的物理场景（两台设备 / 手机连热点 / 校园网隔离 / 计划任务）它做不了，仍在人工那一栏。
 *   · 第五批（T-G73）里"第二个库 / 第二个客户端"是**同一台机器上的**两个真进程/真浏览器 ——
 *     真手机、真校园网、两个物理窗口仍然是人工项（`docs/人工验收-照着点.md` 里如实标着）。
 *   · ★ "等闲下来" = **DOM 不动 + 手上没有在飞的请求**（`waitIdle`，T-G40）：只等 DOM 会在
 *     "请求还在路上、页面一动不动"那一段提前收工，然后拿**上一个画面**去断言（黄金层就被这么坑过）。
 *
 * 用法
 *     node tools/ui_flow_check.mjs                 # 跑全部（**默认一遍**；见下面"最小验证法则"）
 *     node tools/ui_flow_check.mjs --twice         # 跑两遍并比断言指纹（**按需**：改这套流本身时用）
 *     node tools/ui_flow_check.mjs --only 新手引导  # 只跑名字/编号里含这几个字的那条
 *     node tools/ui_flow_check.mjs --list          # 列出所有流与它们替掉的人工项
 *     node tools/ui_flow_check.mjs --coverage      # ★ 正向对账（卡 159）：清单里每个功能项
 *                                                  #   要么被某条流的 item 指到、要么写明
 *                                                  #   机器判不了的理由；不起浏览器
 *     node tools/ui_flow_check.mjs --json          # 机器可读结果
 *     node tools/ui_flow_check.mjs --port <端口> --keep   # 换端口 / 跑完不杀服务
 *
 * ★ 最小验证法则（T-G38，用户交代"别在验证上花那么多时间"之后定的）：
 *   ① **默认只跑一遍**。确定性自检（`--twice`）是"改这套流本身"时才需要的工具 ——
 *      流失败只是红一下、**不会污染任何持久数据**（黄金层不一样：那里的两遍自检是常开的，
 *      因为一份抖出来的清单会被写进黄金，那是真的污染）。两处的取舍不同，就按不同对待。
 *   ② 这条线**不再扩**：够用的条数就停，不为"把 225 个动作都盖住"再加流。
 *   ③ 时间预算：这条流的目标是**一遍 ≲3 分钟**；超了就砍条数，不许悄悄变慢。
 *
 * 退出码：0 全通过 / 1 有流失败 / 2 fixture（种子数据）坏了 / 3 起不了真浏览器（NOT RUN）/
 *         4 两遍断言指纹不一致（只在 `--twice` 时可能出现）。
 */
import { copyFileSync, existsSync, mkdirSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { setTimeout as sleep } from 'node:timers/promises'

import {
  Cdp, EXPORT_DIR, FETCH_WATCH, MUTATION_WATCH, ROOT, TOAST_WATCH, VIEWPORTS, VIEWS,
  bootApp, findBrowser, iso, portBase, portBusyReason, seedFixture, setViewport, startServer,
  waitApp, waitHealth, waitIdle,
} from './tf_browser.mjs'
// 卡 E135（T-AG644）：等待预算的旋钮。**只乘预算、不改判据** —— 三个原语的默认值、
// 轮询粒度、「等到就绪就返回」的循环结构全部照旧（不设 env 时行为与加它之前逐字一致）。
import { scaleMs, waitScale } from './tf_wait_budget.mjs'

const SHOTS_DIR = join(ROOT, 'gates', 'render', 'shots')  // 证据与黄金层放一起（同样不进仓库）
const TEMP_DIR = process.env.TEMP ?? process.env.TMP ?? '/tmp'

/** 备份名里的时间戳 / 界面上那个时间标签（⑪ 用）。
 *
 * 产品格式是 `<库名>.bak-YYYYmmdd-HHMMSS`（`storage/backup.py`，**本地时间**），
 * 界面按钮上的字是 `YYYY-MM-DD HH:MM:SS · 大小`。两个都从同一个 Date 算，
 * 免得"我算的时间戳"和"界面显示的时间"差一秒就点不中那个按钮。
 */
function stampOf(d) {
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}`
    + `-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`
}
function labelOf(d) {
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} `
    + `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

/** 最新那个同步包在哪（⑰ 用）。
 *
 * 为什么要从**磁盘**上找：界面只说"完整路径已复制到剪贴板"，路径本身不在 DOM 里；
 * 而这一条流要证明的第一件事正是"**包真的写出来了**" —— 那就直接去看磁盘。
 * `serve.py --fresh` 把库放在 `TEMP/timeflow_fresh_*` 下，包写在库旁边（同目录）。
 */
function newestSyncPack() {
  let best = null
  let dirs = []
  try { dirs = readdirSync(TEMP_DIR) } catch { return null }
  for (const d of dirs) {
    if (!d.startsWith('timeflow_fresh_')) continue
    const dir = join(TEMP_DIR, d)
    let files = []
    try { files = readdirSync(dir) } catch { continue }
    for (const f of files) {
      if (!/^sync-.*\.json$/.test(f)) continue
      const p = join(dir, f)
      let mtime = 0
      try { mtime = statSync(p).mtimeMs } catch { continue }
      if (!best || mtime > best.mtime) best = { path: p, mtime }
    }
  }
  return best
}

/* ---------------------------------------------------------------- 参数 */

function parseArgs(argv) {
  const a = { json: false, keep: false, twice: false, quiet: false, list: false, port: portBase() + 10, only: '', coverage: false, doc: '' }
  for (let i = 0; i < argv.length; i++) {
    const k = argv[i]
    if (k === '--json') a.json = true
    else if (k === '--keep') a.keep = true
    else if (k === '--twice') a.twice = true
    else if (k === '--quiet') a.quiet = true
    else if (k === '--list') a.list = true
    else if (k === '--shots') a.shots = true
    else if (k === '--coverage') a.coverage = true
    else if (k === '--doc') a.doc = argv[++i] ?? ''
    else if (k === '--port') a.port = Number(argv[++i])
    else if (k === '--only') a.only = argv[++i] ?? ''
    else { console.error(`未知参数：${k}`); process.exit(1) }
  }
  return a
}

const ARGS = parseArgs(process.argv.slice(2))
const log = (...m) => { if (!ARGS.quiet) console.log(...m) }
let CFG_ACCENT = null

/* ---------------------------------------------------------------- 引擎 */

const HIT = '[data-tfprobe="hit"]'

/** 一条流手上的工具。**断言不抛异常**：一条流里的每一项都跑完，失败项一起报（修起来才知道全貌）。 */
class T {
  constructor(cdp, url, vpName) {
    this.cdp = cdp
    this.url = url
    this.vpName = vpName
    this.checks = []
    // 卡 E140：提示条窗口的起点。还没点过任何东西时，窗口从这条流开始算。
    this.toastMark = Date.now()
  }

  /* ---- 断言 ---- */
  ok(label, cond, detail = '') {
    this.checks.push({ label, ok: Boolean(cond), detail: cond ? '' : String(detail) })
    return Boolean(cond)
  }

  eq(label, actual, expected) {
    return this.ok(label, actual === expected, `实际 ${JSON.stringify(actual)}，期望 ${JSON.stringify(expected)}`)
  }

  has(label, haystack, needle) {
    const hay = String(haystack ?? '')
    return this.ok(label, hay.includes(needle), `在这段里没找到「${needle}」：${hay.slice(0, 140)}`)
  }

  lacks(label, haystack, needle) {
    const hay = String(haystack ?? '')
    return this.ok(label, !hay.includes(needle), `不该出现「${needle}」，但它出现了：${hay.slice(0, 140)}`)
  }

  /* ---- 起步 ---- */

  /** 每一条流都从这里开始：换宽度 → **清本机状态并钉住** → 加载 → 进视图 → 等安静。 */
  async start(view = null) {
    await setViewport(this.cdp, VIEWPORTS.find((v) => v.name === this.vpName))
    const booted = await bootApp(this.cdp, this.url, { accent: CFG_ACCENT })
    if (!booted) throw new Error('应用没启动起来（左栏没渲染）—— 界面可能根本没起来')
    await this.arm()
    if (view) await this.view(view)
    await waitIdle(this.cdp)
  }

  /** 装三个计数器：**页面还在动吗**（`MUTATION_WATCH`）、**还有没有请求在飞**（`FETCH_WATCH`）、
   *  **提示条说过什么**（`TOAST_WATCH`，卡 E140）。
   *  每次导航之后都要重装（页面上下文是新的）；`bootApp` 里也会装一遍（那条路不经过这里）。 */
  async arm() {
    await this.cdp.eval(MUTATION_WATCH)
    await this.cdp.eval(FETCH_WATCH)
    await this.cdp.eval(TOAST_WATCH)
  }

  /** 只看不点地重新加载（保留本机状态 —— 验"刷新后还保持着吗"要用它）。 */
  async reload() {
    await this.cdp.navigate(this.url)
    const booted = await waitApp(this.cdp)
    if (!booted) throw new Error('刷新之后应用没起来')
    await this.arm()
    await waitIdle(this.cdp)
  }

  async view(name, { quiet = true } = {}) {
    const readyMs = 8000
    let m = null
    const got = await this.waitFor(async () => {
      m = await this.mark(`[data-view="${name}"]`)
      return m.ok
    }, readyMs)
    if (!got) throw new Error(`界面上找不到视图 ${name} 的入口（等了约${readyMs}ms，匹配到 ${m.all} 个）`)
    await this.press(HIT, `视图 ${name}`, { quiet })
    if (quiet) await waitIdle(this.cdp)
    else await this.settle()
  }

  /** 只等**这一屏画出来**（`#main` 连续 3 拍不变，≈0.6s），不等整页安静（那要 ~0.7s+）。
   *  给"扫文本"这类用途：它不需要"整页不再变"的强保证，代价是**更晚才到的东西会漏** ——
   *  所以取 3 拍而不是 1 拍。真正验行为的那几条流一律用默认的 `waitIdle`。 */
  async settle(taps = 3, step = 200, max = 40) {
    let last = ''
    let same = 0
    for (let i = 0; i < max && same < taps; i++) {
      await sleep(step)
      const n = await this.cdp.eval('document.getElementById("main").innerHTML.length')
      if (n === last) same++
      else { same = 0; last = n }
    }
  }

  /* ---- 找元素 / 点 / 打字 ---- */

  /** 按选择器（可再加"文字里含…"/"它所在的那张卡里含…"）挑一个**可见**的元素，打个临时标记，
   *  返回标记选择器。为什么用标记：路标是数据 id 拼的（`asTarget-<uuid>`）没法写死，
   *  而"第几个"会随排序变。标记只活在这一次页面里，页面一刷新就没了 —— 所以每条流都是现找现点。
   *  `inCard` 是给"卡片上的按钮"用的：详情按钮自己的字是「详情」，只能靠**它在哪张卡里**认。 */
  async mark(selector, { text = null, inCard = null, nth = 0 } = {}) {
    const cond = (e) => {
      const own = `(e.textContent || '').includes(${JSON.stringify(text)})`
      const card = `((e.closest('.card') || {}).textContent || '').includes(${JSON.stringify(inCard)})`
      if (text && inCard) return `${own} && ${card}`
      if (text) return own
      if (inCard) return card
      return 'true'
    }
    return this.cdp.eval(`(() => {
      document.querySelectorAll('[data-tfprobe]').forEach((e) => e.removeAttribute('data-tfprobe'));
      const all = [...document.querySelectorAll(${JSON.stringify(selector)})];
      const vis = all.filter((e) => e.getClientRects().length);
      const pool = (vis.length ? vis : all).filter((e) => ${cond('e')});
      const el = pool[${nth}];
      if (!el) return { ok: false, pool: pool.length, all: all.length };
      el.setAttribute('data-tfprobe', 'hit');
      return { ok: true, pool: pool.length, all: all.length,
               text: (el.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 80) };
    })()`)
  }

  /** 真按下去：滚进视口 → **命中测试** → 真鼠标事件（`Input.dispatchMouseEvent`）。 */
  async press(selector, label = selector, { quiet = true, readyMs = 8000 } = {}) {
    let r = null
    const got = await this.waitFor(async () => {
      r = await this.cdp.rectOf(selector)
      return r && r.w > 0 && r.h > 0
    }, readyMs)
    if (!r) { this.ok(`点得到：${label}`, false, `等了约${readyMs}ms 仍找不到元素（可能没渲染出来）`); return false }
    if (!got) { this.ok(`点得到：${label}`, false, `等了约${readyMs}ms，元素仍是 ${r.w}×${r.h}，点不到`); return false }
    const hit = await this.cdp.hitTest(selector, r.cx, r.cy)
    if (!hit.ok) { this.ok(`点得到：${label}（没被别的东西挡住）`, false, hit.why); return false }
    this.toastMark = Date.now()  // 卡 E140：提示条的窗口从**点击那一刻**算，不从等待结束那一刻算
    await this.cdp.clickAt(r.cx, r.cy)
    if (quiet) await waitIdle(this.cdp)
    return true
  }

  /** 按 `data-action` 点（界面里所有交互都挂在这张表上，见 T-G31 的命令表）。 */
  async pressAction(name, opts = {}) {
    const readyMs = opts.readyMs ?? 8000
    let m = null
    const got = await this.waitFor(async () => {
      m = await this.mark(`[data-action="${name}"]`, opts)
      return m.ok
    }, readyMs)
    if (!got) { this.ok(`界面上有这个动作：${name}`, false, `等了约${readyMs}ms，匹配到 ${m.all} 个，可见 ${m.pool} 个`); return false }
    return this.press(HIT, `${name}${opts.text ? `（${opts.text}）` : ''}`, { readyMs })
  }

  /** 真拖（T-G79）：按住 `from` 拖到 `to`（`frac` 决定落在目标卡的哪个高度上）。
   *
   * ★ 三条都是被实测坑出来的（`gates/diag/probes/drag_probe.mjs`）：
   *   ① **两个 rect 必须在同一次求值里读**：`rectOf()` 自己会 `scrollIntoView` —— 先读起点、
   *      再读落点，第二次滚动会让第一组坐标失效。当时的症状特别像"拖了没反应"：按下的那个点
   *      其实是**另一张卡的抓手**（坐标已经飘到它头上了），于是"拖丙"变成了"拖甲"。
   *   ② **按之前先做命中测试**：坐标飘了就当场报"那个点上其实是 …"，而不是拖完发现顺序没变。
   *   ③ `frac` 不是装饰：落点算的是"鼠标在目标卡中线的上面还是下面"，要验"插到这条前面"
   *      就得落在它**上半部分**（默认 0.3）—— 落正中间会算成"插到它的下一条前面"。
   */
  async drag(fromSel, toSel, { frac = 0.3, steps = 10, readyMs = 8000 } = {}) {
    let both = null
    await this.waitFor(async () => {
      // 只借 `rectOf` 的 scrollIntoView（把起点那一列滚进视口），返回值不用
      await this.cdp.rectOf(fromSel)
      both = await this.cdp.eval(`(() => {
      const a = document.querySelector(${JSON.stringify(fromSel)});
      const b = document.querySelector(${JSON.stringify(toSel)});
      if (!a || !b) return null;
      const box = (e) => { const r = e.getBoundingClientRect();
        return { x: r.x, y: r.y, w: r.width, h: r.height, cx: r.x + r.width / 2,
                 cy: r.y + r.height / 2 } };
      const out = { a: box(a), b: box(b), vh: window.innerHeight };
      out.offscreen = [out.a, out.b].some((r) => r.y < 0 || r.y + r.h > out.vh);
      return out; })()`)
      return both && both.a.w >= 1 && both.a.h >= 1 && both.b.w >= 1 && both.b.h >= 1 && !both.offscreen
    }, readyMs)
    if (!both) { this.ok(`拖得动：${fromSel} → ${toSel}`, false, `等了约${readyMs}ms，起点或落点没找到`); return false }
    if (both.a.w < 1 || both.a.h < 1 || both.b.w < 1 || both.b.h < 1) {
      this.ok(`拖得动：${fromSel} → ${toSel}`, false,
        `等了约${readyMs}ms，起点 ${both.a.w}×${both.a.h} / 落点 ${both.b.w}×${both.b.h}`)
      return false
    }
    if (both.offscreen) {
      this.ok(`拖得动：${fromSel} → ${toSel}`, false,
        `等了约${readyMs}ms，起点或落点在视口外（视口高 ${both.vh}）—— 先把这一列滚进来再拖`)
      return false
    }
    const hit = await this.cdp.hitTest(fromSel, both.a.cx, both.a.cy)
    if (!hit.ok) {
      this.ok(`按得住起点：${fromSel}`, false, `${hit.why}（${hit.hit || '空'}）`)
      return false
    }
    this.toastMark = Date.now()  // 卡 E140：拖也可能弹提示条，窗口同样从动作那一刻算
    await this.cdp.dragPath({ x: both.a.cx, y: both.a.cy },
      { x: both.b.cx, y: both.b.y + both.b.h * frac }, { steps })
    await waitIdle(this.cdp)
    return true
  }

  /** 真打字（逐字符 keydown/char/keyup）——不是 `value = '…'`：输入事件、`data-enter` 都要真经过。
   *  打之前先 Ctrl+A **全选**：输入框里可能还留着上一次的内容（不清干净会变成"接在后面"）。 */
  async type(selector, text) {
    const focused = await this.press(selector, `输入框 ${selector}`)
    if (!focused) return false
    await this.cdp.selectAll()
    await this.cdp.typeText(text)
    await waitIdle(this.cdp)
    return true
  }

  async key(name) {
    this.toastMark = Date.now()  // 卡 E140：回车/快捷键也会弹提示条（⑬ 就是按 Enter 提交的）
    await this.cdp.key(name)
    await waitIdle(this.cdp)
  }

  /** 组合键（`Ctrl/⌘ + 字母`）—— T-G61 的键盘层要用它打 ⌘K。 */
  async chord(letter, opts) {
    this.toastMark = Date.now()  // 卡 E140：同上
    await this.cdp.chord(letter, opts)
    await waitIdle(this.cdp)
  }

  /** 设置页分层（T-G63）：那一节默认是**折着**的 —— 先把 `set-xxx` 展开再操作。
   *  幂等（已经开着就什么都不做），所以每条流在动那一节之前调一次就行。
   *  ★ 这一条本身也是验证：如果哪天"折叠"被做成"删掉"，这里会**找不到那个展开按钮**而报错。 */
  async openSetting(sec) {
    const state = await this.cdp.eval(`(() => { const b = document.getElementById('body-${sec}');
      return b ? (b.hidden ? 'closed' : 'open') : 'missing' })()`)
    if (state === 'open') return true
    const readyMs = 8000
    let m = null
    const got = await this.waitFor(async () => {
      m = await this.mark(`[data-action="set-fold"][data-sec="${sec}"]`)
      return m.ok
    }, readyMs)
    if (!got) { this.ok(`设置页有「${sec}」这一节（可展开）`, false, `等了约${readyMs}ms，匹配到 ${m.all} 个`); return false }
    return this.press(HIT, `展开设置里的「${sec}」`)
  }

  /** 清空一个输入框（真点 → Ctrl+A → 真按退格）。
   *  ★ 别拿 `type(sel, '')` 当清空：那是"一个字符都不打"，原来的内容**原样留着**（T-G37 踩到）。 */
  async clear(selector) {
    const focused = await this.press(selector, `输入框 ${selector}`)
    if (!focused) return false
    await this.cdp.selectAll()
    await this.cdp.key('Backspace')
    await waitIdle(this.cdp)
    return true
  }

  /* ---- 读 ---- */

  text(selector) {
    return this.cdp.eval(`(() => { const e = document.querySelector(${JSON.stringify(selector)});
      return e ? (e.innerText || e.textContent || '').replace(/\\s+/g, ' ').trim() : null })()`)
  }

  bodyText() {
    return this.cdp.eval(`document.body.innerText.replace(/\\s+/g, ' ').trim()`)
  }

  count(selector) { return this.cdp.eval(`document.querySelectorAll(${JSON.stringify(selector)}).length`) }

  geom(selector, prop = null) {
    return this.cdp.eval(`(() => { const e = document.querySelector(${JSON.stringify(selector)});
      if (!e) return null; const r = e.getBoundingClientRect(); const cs = getComputedStyle(e);
      return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height),
               display: cs.display, style: ${prop ? `cs[${JSON.stringify(prop)}]` : 'null'} } })()`)
  }

  attr(selector, name) {
    return this.cdp.eval(`(() => { const e = document.querySelector(${JSON.stringify(selector)});
      return e ? e.getAttribute(${JSON.stringify(name)}) : null })()`)
  }

  /** 输入框**当前的值**（property，不是 attribute —— 打字改的是 property，不是 attribute；
   *  第一版拿 `attr(sel,'value')` 验"粘进去了没有"，永远拿到 null）。 */
  value(selector) {
    return this.cdp.eval(`(() => { const e = document.querySelector(${JSON.stringify(selector)});
      return e ? e.value : null })()`)
  }

  ls(key) { return this.cdp.eval(`(() => { try { return localStorage.getItem(${JSON.stringify(key)}) } catch (e) { return null } })()`) }

  /** 右下角提示条的**当前**文字（没显示时返回空串 —— 过场提示本来就会自己消失）。 */
  toast() {
    return this.cdp.eval(`(() => { const t = document.getElementById('toast');
      return t && t.classList.contains('show') ? (t.innerText || '').replace(/\\s+/g, ' ').trim() : '' })()`)
  }

  /** 卡 E140：窗口内**已经说过**的提示条（按时间正序）。
   *  起点是**动作那一刻**（`this.toastMark`），不是「现在」—— 提示条只活 2.2 秒，
   *  而点完之后那句 `waitIdle` 可能已经花掉 6 秒；等回来再采样，读到的永远是空。 */
  toastSince(at) {
    const since = Number(at || 0) - 50  // 容许 50ms 的时钟颗粒差（页面与 Node 各有自己的 Date.now）
    return this.cdp.eval(`(() => ((window.__tftoast || []).filter((r) => r.at >= ${Number(since)})))()`)
  }

  /** 等提示条里出现某句话（操作是异步的：点了之后要等后端回话）。
   *  ★ 失败时回的是**最后一句非空的**提示条，不是"最后一次采样" ——
   *  第一版回最后一次采样，而提示条 2.2 秒后就自己消失了，于是失败信息永远是『（空）』，
   *  看着像"点了没反应"，其实它明明说过一句别的（T-G35 就这么被误导过一次）。 */
  // ★ 卡 092：默认预算 5s → 12s。满载下提示条要十几秒才出来（实测 ㉕ 就是 5s 没等到而假红）——
  // 这仍是**等到就绪就返回**的轮询，不是固定 sleep。
  async waitToast(needle, ms = 12000) {
    ms = scaleMs(ms, waitScale())  // 卡 E135：只乘预算（×1 时等于原值）；轮询粒度与循环结构不动
    const t0 = Date.now()
    let last = ''
    // 卡 E140：先查**点击以来**的历史（提示条 2.2 秒就消失，而 press 的 waitIdle 可能更久）
    for (const h of (await this.toastSince(this.toastMark)) || []) {
      if (h.text) last = h.text
      if (h.text.includes(needle)) return { ok: true, text: h.text }
    }
    while (Date.now() - t0 < ms) {
      const now = await this.toast()
      if (now) last = now
      if (now.includes(needle)) return { ok: true, text: now }
      await sleep(100)
    }
    return { ok: false, text: last }
  }

  /** ★ 卡 092：等**提示条满足整条判据**（不是一个前缀）。
   *
   *  为什么不能"先 `waitToast('已导入：')`、再拿眼前文本断言 `删除 1`"：提示条是**分步渲染**的，
   *  满载下先出现的是前半句，那一瞬间去断言后半句**必然落空**（实测 ㉒「导入报告里写了删了几行」
   *  就是这么挂的）。判据必须**一次说完整**：等到它整条成立，或者超时后说实话。 */
  async waitToastWhere(pred, ms = 12000, step = 150) {
    ms = scaleMs(ms, waitScale())  // 卡 E135：预算变、step（轮询粒度）不变
    const t0 = Date.now()
    let last = ''
    // 卡 E140：先查**点击以来**的历史（理由同 waitToast）
    for (const h of (await this.toastSince(this.toastMark)) || []) {
      if (h.text) last = h.text
      if (h.text && pred(h.text)) return { ok: true, text: h.text }
    }
    while (Date.now() - t0 < ms) {
      const now = await this.toast()
      if (now) last = now
      if (now && pred(now)) return { ok: true, text: now }
      await sleep(step)
    }
    return { ok: false, text: last }
  }

  /** 等某个条件成立（自带轮询；用在"列表里应当多出一行"这类异步结果上）。 */
  async waitFor(fn, ms = 5000, step = 120) {
    ms = scaleMs(ms, waitScale())  // 卡 E135：预算变、step（轮询粒度）不变
    const t0 = Date.now()
    while (Date.now() - t0 < ms) {
      if (await fn()) return true
      await sleep(step)
    }
    return false
  }

  /** 装一个"浏览器原生弹窗有没有被调过"的探针（证明危险动作走的是**站内**模态）。 */
  async spyNativeDialogs() {
    await this.cdp.eval(`(() => { window.__tfNative = [];
      for (const k of ['confirm', 'alert', 'prompt']) { const old = window[k];
        window[k] = (msg) => { window.__tfNative.push(k + ':' + String(msg).slice(0, 40)); return old === window.prompt ? null : false } }
      return true })()`)
  }

  nativeDialogs() { return this.cdp.eval('window.__tfNative || []') }

  /** 从 **Node 侧**直接打接口（不带 Origin）—— 两条用途：
   *  ① 验"界面上看不见的那一半"（AI 合作接口的边界、403 原话）；
   *  ② 给界面准备一点它自己要用的数据（如"我自己建的那个任务"的 id）。
   *  注意：**能走界面的一律走界面**（那才是这一层要验的东西），这里只补界面做不到的部分。
   *
   *  `base`（第 4 个参数，T-G73）：指向**另一个 base URL** —— ㉒ 要拿"一份别的设备的包"，
   *  所以流里会**再起一个真服务**当那台设备；对它的那几个调用走这个参数，不改 `this.url`。 */
  async api(method, path, body, base = this.url) {
    const res = await fetch(base.replace(/\/$/, '') + path, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
    let json = null
    try { json = await res.json() } catch { /* 可能没有 body */ }
    return { status: res.status, json }
  }

  async shot(name) {
    mkdirSync(SHOTS_DIR, { recursive: true })
    await this.cdp.shot(join(SHOTS_DIR, `flow-${name}.png`))
  }
}

/* ---------------------------------------------------------------- 流 */

const FLOWS = []
/** 登记一条流。`item` = 它替掉 `复盘/交接-重构进度.md` §二「待人工确认」里的哪一条（有据可查）。 */
function flow(spec) { FLOWS.push(spec) }
/** 这一轮要跑哪些流（`--only` 按编号或名字里含的那几个字挑）。**只有这一处判定**，
 *  免得"跑哪些"和"有没有挑到"两处各写一遍、慢慢长歪。 */
function selectedFlows() {
  if (!ARGS.only) return FLOWS
  return FLOWS.filter((f) => f.id.includes(ARGS.only) || f.name.includes(ARGS.only))
}

flow({
  id: '⑦', name: '新手引导：首次出现、关掉不再来、设置里能再看',
  item: '前端批次③ ⑦ 今日页新手引导卡片',
  vp: 'desktop',
  async run(t) {
    await t.start('today')
    t.eq('新设备打开就有引导卡', await t.count('#guideCard'), 1)
    t.has('卡片上说清了第一步做什么', await t.text('#guideCard'), '在下面的输入框写下一件要做的事')
    await t.pressAction('guide-done')
    t.eq('点「知道了」之后卡片消失', await t.count('#guideCard'), 0)
    t.eq('状态记在本机（tf_guide=done）', await t.ls('tf_guide'), 'done')
    await t.reload()
    t.eq('刷新之后不再出现（不是每次打开都弹）', await t.count('#guideCard'), 0)
    await t.view('setting')
    await t.openSetting('set-appearance')      // T-G63：这一节现在是折着的
    await t.pressAction('guide-replay')
    t.eq('设置页「再看一遍新手引导」能把它叫回来', await t.count('#guideCard'), 1)
    t.ok('叫回来之后站的是今日页（不是停在设置里）', (await t.count('[data-view="today"].active')) >= 1)
  },
})

flow({
  id: '⑧', name: '收起右栏：中列变宽、刷新后保持、能再展开',
  item: '前端批次③ ⑧ 左栏与设置页的「收起右栏」',
  vp: 'desktop',
  async run(t) {
    await t.start('today')
    const rail0 = await t.geom('.sidebar')
    const main0 = await t.geom('#main')
    t.ok('桌面宽度下右栏本来是显示的', rail0 && rail0.display !== 'none', JSON.stringify(rail0))
    await t.pressAction('rail-toggle')
    t.eq('右栏收起了', (await t.geom('.sidebar')).display, 'none')
    const main1 = await t.geom('#main')
    t.ok('中列变宽了', main1.w > main0.w, `收起前 ${main0.w}px → 收起后 ${main1.w}px`)
    t.eq('按钮字变成「展开右栏」', await t.text('#railToggle'), '展开右栏')
    t.eq('选择记在本机（tf_rail=off）', await t.ls('tf_rail'), 'off')
    await t.reload()
    t.eq('刷新之后仍然是收起的', (await t.geom('.sidebar')).display, 'none')
    t.eq('刷新之后按钮字也对', await t.text('#railToggle'), '展开右栏')
    await t.pressAction('rail-toggle')
    t.ok('再点一次能展开回来', (await t.geom('.sidebar')).display !== 'none')
    t.eq('状态也回到 on', await t.ls('tf_rail'), 'on')
  },
})

flow({
  id: '㉙', name: '左栏智能视图：三个开关各管各的，默认全关，老偏好迁移（T-G162）',
  item: '用户 2026-09-27 更正：不是并成一组固定在左栏，是能自由选择（T-G162）',
  vp: 'desktop',
  async run(t) {
    await t.start('today')
    // 默认全关（没存过偏好）：三项一个都不在左栏，主视图还在（沿用 T-G154 的默认）
    t.eq('默认左栏看不到「重要」', (await t.geom('.rail nav button[data-view="important"]')).display, 'none')
    t.eq('默认左栏这三项一个都没露（hidden）',
      await t.count('.rail nav button[data-view="important"]:not([hidden]), .rail nav button[data-view="planned"]:not([hidden]), .rail nav button[data-view="flagged"]:not([hidden])'), 0)
    t.eq('主视图还在（左栏不是空的）', await t.count('.rail nav button[data-view="today"]:not([hidden])'), 1)

    // 设置→外观：三个名字显式写出、各一个开关
    await t.view('setting')
    await t.openSetting('set-appearance')
    t.eq('设置里是三个独立开关（名字显式）', await t.count('[data-action="left-rail-view"]'), 3)

    // 只开「有计划」：左栏只出它，另两项仍然收着
    await t.press('[data-action="left-rail-view"][data-view="planned"]', '「有计划」开关')
    t.eq('只开 planned 后左栏只有一项露出来',
      await t.count('.rail nav button[data-view="important"]:not([hidden]), .rail nav button[data-view="planned"]:not([hidden]), .rail nav button[data-view="flagged"]:not([hidden])'), 1)
    t.eq('露出来的正是「有计划」', await t.count('.rail nav button[data-view="planned"]:not([hidden])'), 1)
    t.eq('逐项记在本机（tf_rail_views）', await t.ls('tf_rail_views'), '["planned"]')

    // 刷新后保持
    await t.reload()
    t.eq('刷新后「有计划」仍在左栏', await t.count('.rail nav button[data-view="planned"]:not([hidden])'), 1)
    t.eq('刷新后另两项仍收着', await t.count('.rail nav button[data-view="important"]:not([hidden])'), 0)

    // 老偏好迁移：删掉新键、预置旧布尔 on → 三项全开，并落进新键
    await t.cdp.eval(`(() => { localStorage.removeItem('tf_rail_views'); localStorage.setItem('tf_rail_direct', 'on'); return true })()`)
    await t.reload()
    t.eq('老偏好 on → 三项全回到左栏',
      await t.count('.rail nav button[data-view="important"]:not([hidden]), .rail nav button[data-view="planned"]:not([hidden]), .rail nav button[data-view="flagged"]:not([hidden])'), 3)
    t.eq('迁移结果写进新键', await t.ls('tf_rail_views'), '["important","planned","flagged"]')

    // 逐项收起：只动「重要」自己
    await t.view('setting')
    await t.openSetting('set-appearance')
    await t.press('[data-action="left-rail-view"][data-view="important"]', '「重要」开关')
    t.eq('收起「重要」后左栏剩两项',
      await t.count('.rail nav button[data-view="important"]:not([hidden]), .rail nav button[data-view="planned"]:not([hidden]), .rail nav button[data-view="flagged"]:not([hidden])'), 2)
    t.eq('收起后本机数组也对了', await t.ls('tf_rail_views'), '["planned","flagged"]')
  },
})

/** 暗色读数（T-G163）：一屏的关键元素计算色 + 全页「文字色 == 背景色」扫描，一次求值拿回来。
 *  为什么用探针元素比对令牌：令牌是 `#0b1220` 这种字面，计算值是 `rgb(11, 18, 32)` ——
 *  字符串比不了。造一个 `background: var(--bg)` 的临时元素读它的计算值，两边同一格式。
 *  `bad` 只扫**有自有文字**的元素：文字色等于它最近的不透明祖先背景 = 字看不见。 */
const DARK_SNAPSHOT = `(() => {
  const alpha = (s) => { const m = s.match(/rgba?\\\\(([^)]+)\\\\)/); if (!m) return 1;
    const p = m[1].split(',').map(parseFloat); return p.length >= 4 ? p[3] : 1 };
  const resolved = (name) => { const i = document.createElement('i');
    i.style.background = 'var(' + name + ')'; i.style.display = 'none';
    document.body.appendChild(i); const v = getComputedStyle(i).backgroundColor; i.remove(); return v };
  const bg = resolved('--bg'); const panel = resolved('--panel'); const accent = resolved('--accent');
  const bad = [];
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1 || !el.getClientRects().length) continue;
    if (![...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())) continue;
    let eb = null;
    for (let e = el; e; e = e.parentElement) {
      const b = getComputedStyle(e).backgroundColor;
      if (alpha(b) > 0) { eb = b; break }
    }
    if (eb && getComputedStyle(el).color === eb) {
      bad.push(el.tagName.toLowerCase() + (el.id ? '#' + el.id : '')
        + (el.classList.length ? '.' + [...el.classList].slice(0, 2).join('.') : ''));
      if (bad.length >= 5) break;
    }
  }
  const card = document.querySelector('#main .card, #main .panel');
  const fb = document.querySelector('#fbPlan');
  const active = document.querySelector('nav button.active');
  return {
    theme: document.documentElement.dataset.theme,
    bodyBg: getComputedStyle(document.body).backgroundColor,
    bg, panel, accent,
    cardBg: card ? getComputedStyle(card).backgroundColor : null,
    fbBg: fb ? getComputedStyle(fb).backgroundColor : null,
    activeBg: active ? getComputedStyle(active).backgroundColor : null,
    bad,
  };
})()`

flow({
  id: '㉚', name: '暗色模式：切到暗色后关键元素落在暗色集、没有「文字与背景同色」的元素',
  item: '新增（不是搬移项）：用户 2026-09-27 反馈暗色没适配（T-G163）',
  vp: 'desktop',
  async run(t) {
    // 默认路径（用户没选过强调色）才是暗色令牌真正生效的路径 —— 这套工具每条流都会把
    // 配置默认的强调色钉进本机存储（`bootApp({accent})`），先清掉再重载，走的就是
    // 「令牌区说了算」的那条路（内联强调色只该在用户真选过时出现，同卡修的那条 JS）。
    await t.start('today')
    await t.cdp.eval(`(() => { try { localStorage.removeItem('tf_accent') } catch (e) {} return true })()`)
    await t.reload()
    // 记下亮色基线：后面的「落在暗色集」必须**同时**证明「跟亮色不一样」——
    // 否则「body 背景 == --bg 的计算值」这条断言在亮色下也成立，是个恒真断言。
    const light = await t.cdp.eval(DARK_SNAPSHOT)
    t.eq('动手前确实是亮色', light.theme, 'light')

    // 走真 UI 切暗色：设置页「外观」里的「暗色」按钮（不是直接改 data-theme —— 那是探针干的事）
    await t.view('setting')
    await t.openSetting('set-appearance')
    await t.press('[data-action="set-theme"][data-theme-choice="dark"]', '主题「暗色」')
    t.eq('主题切到暗色（html data-theme）', await t.attr('html', 'data-theme'), 'dark')
    t.eq('html 上没有内联 --accent（默认强调色交给令牌区，暗色令牌才生效）',
      await t.cdp.eval(`document.documentElement.style.getPropertyValue('--accent') || ''`), '')

    // planned 的左栏按钮默认收着（T-G162 改后：三个独立开关、默认全关，旧总开关 left-rail-smart 已拆）
    // —— 走真 UI 把「有计划」那个开关打开再进，与 ㉙ 同一条路径；本机存储每条流都会被
    // bootApp 清掉重钉，不污染后面的流。（I-10 集成：此处原按 T-G163 树上的旧总开关写，并树后换向）
    await t.press('[data-action="left-rail-view"][data-view="planned"]', '「有计划」开关')
    t.eq('「有计划」回到左栏（点得到它）',
      await t.count('.rail nav button[data-view="planned"]:not([hidden])'), 1)

    for (const view of ['habit', 'planned', 'review']) {
      await t.view(view)
      const d = await t.cdp.eval(DARK_SNAPSHOT)
      t.eq(`${view}：还在暗色`, d.theme, 'dark')
      t.ok(`${view}：body 底跟亮色不一样`, d.bodyBg !== light.bodyBg,
        `亮 ${light.bodyBg} / 暗 ${d.bodyBg}`)
      t.eq(`${view}：body 底 = --bg 的暗色值`, d.bodyBg, d.bg)
      t.eq(`${view}：卡片底 = --panel 的暗色值`, d.cardBg, d.panel)
      t.ok(`${view}：没有「文字色 == 背景色」的元素`, d.bad.length === 0,
        `文字与背景同色的有：${d.bad.join(' / ') || '（无）'}`)
      if (view === 'habit') {
        // 每日反馈的两块 textarea（#fbPlan / #fbGap）就是用户点名的那处：
        // 修复前暗色下是 UA 白底，与 --panel 对不上。
        t.eq('habit：每日反馈 textarea 底 = --panel 的暗色值（不再吃 UA 白底）', d.fbBg, d.panel)
      }
      if (view === 'habit') {
        // 强调色：默认路径下必须落在 --accent 的**暗色**那一档 —— 修复前它被内联写死的
        // 亮色默认值盖住（探针 60 处「没跟着主题变」的主因）。只断「亮暗不同」：
        // 「选中项底 == accent」会撞上悬停态的 color-mix（点完左栏鼠标还停在那颗按钮上）。
        t.ok('habit：强调色确实换成了暗色那一档', d.accent !== light.accent,
          `亮 ${light.accent} / 暗 ${d.accent}`)
      }
    }
  },
})

flow({
  id: '⑨', name: '专注白名单/勿扰：能加能删，非法时段被后端拦下并原话透传',
  item: '前端批次③ ⑨ 设置页「专注（白名单/勿扰）」增删条',
  vp: 'desktop',
  async run(t) {
    await t.start('setting')
    t.has('设置页有这一节', await t.bodyText(), '专注（白名单 / 勿扰）')
    // T-G63（设置页分层）：折叠**不是藏起来** —— 折着的时候标题下就有"现状"，展开才出控件
    t.eq('这一节默认是折着的', (await t.geom('#body-set-focus-guard')).display, 'none')
    t.has('折着也看得见现状（不用点开就知道现在的口径）',
      await t.text('#sum-set-focus-guard'), '现状：')
    await t.openSetting('set-focus-guard')
    t.ok('点「展开」之后控件才出来', (await t.geom('#body-set-focus-guard')).display !== 'none')
    t.eq('一开始没有勿扰时段', await t.count('[data-action="guard-dnd-del"]'), 0)

    // ① 非法时段：`25:00-07:00`。前端只判"非空/重复"，所以**必须由后端拦下**，
    //    界面把后端那句原话透出来（不是自己编一句"格式错误"）。
    await t.type('#guardDnd', '25:00-07:00')
    t.eq('真点过之后焦点确实在输入框里（不是"看起来聚焦"）',
      await t.cdp.activeElement(), 'input#guardDnd')
    await t.key('Enter')
    const bad = await t.waitToast('操作未完成')
    t.ok('非法时段被拦下了', bad.ok, `提示条里是：${bad.text || '（空）'}`)
    t.has('透出来的是后端原话（哪一条、错在哪）', bad.text,
      '勿扰时段要写成 HH:MM-HH:MM（24 小时制）：25:00-07:00')
    // 后端原话是**直接显示在提示条上**的，所以它也得过"界面上不许有字面星号"这一关。
    // （这是**抽样**不是保证：只有走过提示条的那些原话会被这一条看见，见复盘 §6 边界。）
    t.lacks('后端原话进了提示条也不许画星号', bad.text, '**')
    t.eq('非法时段没有被记进列表', await t.count('[data-action="guard-dnd-del"]'), 0)

    // ② 合法时段：真打字 + 真回车（走的是 `data-enter` 那条键盘通路，不是点按钮）
    // ★ 判据用**持久信号**（列表里真多出一行），不拿提示条当唯一证据：
    //   提示条 2.2 秒就自己消失，而满负载的一轮里一次 CDP 采样可能要几百毫秒 ——
    //   于是"操作其实成功了"会被记成失败（T-G60 那轮撞到过一次假红，单跑两次都过）。
    //   提示条本身仍在①那条路上验（那里验的是"后端原话透传"，是它存在的理由）。
    await t.type('#guardDnd', '22:00-07:00')
    await t.key('Enter')
    t.ok('合法时段加上了（列表里真出现）',
      await t.waitFor(async () => (await t.count('[data-action="guard-dnd-del"]')) === 1, 8000))
    t.has('列表里写的就是它', await t.text('[data-action="guard-dnd-del"]'), '22:00-07:00')

    // ③ 能删掉（自己收拾干净，不给后面的流留状态）—— 同样以列表为准
    await t.pressAction('guard-dnd-del')
    t.ok('能删掉（列表里真没了）',
      await t.waitFor(async () => (await t.count('[data-action="guard-dnd-del"]')) === 0, 8000))
  },
})

flow({
  id: '⑩', name: '危险动作走站内二次确认：写清动作名、能取消、取消不动数据',
  item: '前端批次③ ⑩ 危险动作的二次确认是站内弹窗',
  vp: 'desktop',
  async run(t) {
    await t.start('setting')
    await t.spyNativeDialogs()
    const groupsBefore = await t.count('[data-action="group-delete"]')
    t.ok('设置页里有分组（有东西可删）', groupsBefore > 0, `找到 ${groupsBefore} 个删除按钮`)

    const m = await t.mark('[data-action="group-delete"]')
    if (!t.ok('找得到某个分组的删除按钮', m.ok)) return
    const name = await t.attr(HIT, 'data-name')
    await t.press(HIT, `删除分组「${name}」`)

    t.eq('弹出的是站内模态', await t.attr('#modal', 'hidden'), null)
    t.has('标题写清了删的是哪个分组', await t.text('#modalTitle'), `删除分组「${name}」`)
    t.has('标题里也说了后果（任务会保留）', await t.text('#modalTitle'), '任务会保留')
    t.eq('确定按钮上写的是动作名（不是笼统的"确定"）', await t.text('#modalOk'), '删除分组')
    t.eq('confirm 态不给打字框（只让人选）', await t.attr('#modalInput', 'hidden'), '')
    await sleep(200)
    t.eq('没有偷偷弹浏览器原生 confirm', JSON.stringify(await t.nativeDialogs()), '[]')

    await t.pressAction('modal-cancel')
    t.eq('取消之后模态关掉了', await t.attr('#modal', 'hidden'), '')
    t.eq('取消之后分组一个没少（没动手）', await t.count('[data-action="group-delete"]'), groupsBefore)

    // ★ T-G60 补的一半（不在 ⑩ 原来替掉的那条人工项里，但同一页同一批控件，顺手钉住）：
    //   **点开一个分组看它的任务**（只读列表，走那条以前没有入口的路由），再点一次收起。
    const gt = await t.mark('[data-action="group-tasks"]')
    if (t.ok('分组行上有「看任务」', gt.ok)) {
      const gid = await t.attr(HIT, 'data-id')
      await t.press(HIT, '点「看任务」')
      const box = `#groupTasks-${gid}`
      const opened = await t.waitFor(async () => (await t.count(`${box} > *`)) > 0, 6000)
      t.ok('展开了那个分组的任务（或如实说它还没有任务）', opened)
      const close = await t.mark(`${box} [data-action="group-tasks"]`)
      if (close.ok) {
        await t.press(HIT, '点「收起」')
        await sleep(200)
        t.eq('再点一次收起（挂载点空了）', await t.count(`${box} > *`), 0)
      }
    }
  },
})

flow({
  id: '①', name: '升级为复习卡：建得成，第二次不会重复建',
  item: '前端批次① ① 任务详情 →「升级为复习卡」',
  vp: 'desktop',
  async run(t) {
    await t.start('tasks')
    const card = await t.mark('[data-action="task-detail"]', { inCard: '把第三章习题做完' })
    if (!t.ok('找得到那张任务卡', card.ok, `匹配 ${card.all} 个详情按钮，没有一张卡里含这个标题`)) return
    await t.press(HIT, '打开任务详情')
    t.has('详情里写着「升级为复习卡」', await t.text('#detailRail'), '升级为复习卡')

    await t.pressAction('task-to-review')
    const created = await t.waitToast('已升级为复习卡')
    t.ok('点一下就建好了', created.ok, `提示条里是：${created.text || '（空）'}`)
    t.has('回话钉住最小语义（T-G142）', created.text, '已升级为复习卡')
    t.lacks('解释句不许回来（T-G142）', created.text, 'FSRS')
    t.ok('建完自动去了复习页（看得到结果）', (await t.count('[data-view="review"].active')) >= 1)

    await t.view('tasks')
    const again = await t.mark('[data-action="task-detail"]', { inCard: '把第三章习题做完' })
    if (!t.ok('回到任务列表还能找到它', again.ok)) return
    await t.press(HIT, '再打开一次任务详情')
    t.has('这次按钮变成「再看复习卡」', await t.text('#detailRail'), '再看复习卡')
    await t.pressAction('task-to-review')
    const dup = await t.waitToast('已经有复习卡')
    t.ok('再点一次不会重复建，而且明说了', dup.ok, `提示条里是：${dup.text || '（空）'}`)
    t.has('原话是「不会重复建」', dup.text, '不会重复建')
  },
})

flow({
  id: '③', name: '专注页「波动/空档」那行只描述事实（不出现目标/达标）',
  item: '前端批次① ③ 专注页「本周投入」最下面那行波动/空档',
  vp: 'desktop',
  async run(t) {
    await t.start('focus')
    const m = await t.mark('.sub', { text: '波动' })
    if (!t.ok('本周投入那张卡下面有「波动」那一行', m.ok)) return
    const line = await t.text(HIT)
    t.has('它同时报了「空档」', line, '本周最长空档')
    t.has('空档报的是天数（原始单位，不折算）', line, '天')
    t.lacks('不出现「目标」', line, '目标')
    t.lacks('不出现「达标」', line, '达标')
    t.lacks('不出现「应该」', line, '应该')
  },
})

flow({
  id: '⑥', name: '统计页「学业投入 vs 自学投入」有对照图、无判断',
  item: '前端批次② ⑥ 统计页「学业投入 vs 自学投入」',
  vp: 'desktop',
  async run(t) {
    await t.start('stats')
    const body = await t.bodyText()
    t.has('有这张图', body, '学业投入 vs 自学投入')
    // ★ 这条流被改过两次，别改回去：它原来认的是图下那段**口径解释句**。
    //   用户 2026-09-24 先选「≤8 字」（于是改短过一版），2026-09-25 又改成**全删** ——
    //   所以界面上现在**一个字都没有**：口径由后端契约（`tests/test_insights.py` 的
    //   `academic_vs_self` 那一组）与 `docs/user-guide.md` 承担，界面只留**两条数据标签**
    //   （它们自己就说清了归因）。这条流钉的是：图还在、标签还在、且**不替人下判断**。
    const a = await t.mark('.sub.split', { text: '学业：挂了课程的任务' })
    if (!t.ok('对照图的两条数据标签还在（口径句已按用户决定全删）', a.ok)) return
    const b = await t.mark('.sub.split', { text: '自学：没挂课程的任务' })
    t.ok('自学的归因也写在标签上（没挂课程的任务）', b.ok)
    const pageText = await t.bodyText()
    t.lacks('不替人下判断（不再出现「该占多少」这类建议）', pageText, '该占多少')
    t.lacks('界面上不再写那句口径（手动投入不计入 / 不参与）', pageText, '手动投入不')
  },
})

flow({
  id: '④', name: '学业页硬考核区：角标 + 粗左边条 + 「逾期不候」说明',
  item: '前端批次② ④ 学业页顶部「硬考核：临期与逾期」区',
  vp: 'desktop',
  async run(t) {
    await t.start('academic')
    const n = await t.count('.card.hard')
    if (!t.ok('有硬考核卡（种子数据里有一项 14 天内的考核）', n > 0, `只找到 ${n} 张`)) return
    const card = await t.geom('.card.hard', 'borderLeftWidth')
    t.eq('粗左边条是 5px（比普通卡的 1px 明显）', card.style, '5px')
    t.has('卡上有「硬考核」角标', await t.text('.badge.hard'), '硬考核')
    const body = await t.bodyText()
    t.has('单独放在前面并说明了', body, '硬考核：临期与逾期')
    t.has('写明了这类是「逾期不候」', body, '逾期不候')
    t.lacks('解释句不许回来（T-G142）', body, '交了就计成绩')
    t.has('没有把已录成绩的算进来（说明里写着未录成绩）', body, '未录成绩')
  },
})

flow({
  id: '⑬', name: '导出 Markdown：目录能改，导出今天真的写出文件',
  item: 'G 批 ⑬ 设置页「导出（Markdown）」',
  vp: 'desktop',
  async run(t) {
    await t.start('setting')
    await t.openSetting('set-export')          // T-G63：这一节现在是折着的
    const shown = await t.attr('#exportDir', 'value')
    t.has('设置页显示的是这台机器上的导出目录', shown, 'tf-render-export')

    // ① 目录能改（改成临时目录下的一个子目录 —— 这根线**真写盘**，所以必须钉在一个确定的地方）
    const sub = join(EXPORT_DIR, 'flow-export')
    await t.type('#exportDir', sub)
    await t.key('Enter')
    const set = await t.waitToast('导出目录已设为')
    t.ok('目录能改', set.ok, `提示条里是：${set.text || '（空）'}`)
    t.has('改完回话里说的是新目录', set.text, 'flow-export')

    // ② 导出今天 → 文件**真的**落在磁盘上（这一条不看界面看文件系统）
    await t.pressAction('export-day')
    const wrote = await t.waitToast('已写出')
    t.ok('点「导出今天」有回话', wrote.ok, `提示条里是：${wrote.text || '（空）'}`)
    const day = iso(new Date())
    const file = join(sub, `${day}.md`)
    if (t.ok(`文件真的写出来了：${day}.md`, existsSync(file), `磁盘上没有 ${file}`)) {
      const md = readFileSync(file, 'utf8')
      t.has('标题就是那一天（一天一个文件）', md, `# ${day}`)
      t.has('有「完成」那一段', md, '## 完成')
      t.has('有「投入」那一段', md, '## 投入')
      t.has('有「备忘」那一段', md, '## 备忘')
      // **注意**：md 是给 Obsidian 看的 **markdown 产物**，里面的 `**加粗**` 是**对的** ——
      // 这正是 §㉑ 那条流要区分开的：**界面文字**不许画星号，**markdown 产物**本来就该有。
    }

    // ③ 收拾干净：把目录改回去（不给后面的流留状态）
    await t.type('#exportDir', EXPORT_DIR)
    await t.key('Enter')
    t.eq('目录改回原样', (await t.waitToast('导出目录已设为')).ok, true)
    t.has('「打开目录」那个按钮在（会真的弹出资源管理器窗口 —— **故意不点**）',
      await t.bodyText(), '打开目录')
  },
})

flow({
  id: '⑯', name: 'AI 接口边界：默认关 → 打开能加步骤 → 你建的它碰不了',
  item: 'G 批 ⑯ 设置页「AI 接口（只读 + 新增）」',
  vp: 'desktop',
  async run(t) {
    await t.start('setting')
    await t.openSetting('set-ai')              // T-G63：这一节现在是折着的
    t.has('界面明说默认是关的', await t.bodyText(), '现在：关着（默认 —— 这一组接口一律 403）')

    // ① 关着的时候：**整组一律 403**，而且原话告诉你先去哪打开
    const off = await t.api('POST', '/api/ai/tasks', { title: 'AI 建的任务' })
    t.eq('关着时 AI 接口一律 403（读也拦）', off.status, 403)
    t.has('403 的原话指向设置页那个开关', String(off.json && off.json.detail), 'AI 接口默认是')

    // ② 打开（真点界面上的按钮）
    await t.pressAction('set-ai', { text: '打开' })
    const opened = await t.waitToast('AI 接口已打开')
    t.ok('开关能打开', opened.ok, `提示条里是：${opened.text || '（空）'}`)
    const ping = await t.api('GET', '/api/ai/ping')
    t.eq('打开后 ping 能自证', ping.status, 200)
    t.has('自述里写着这一版是只读 + 新增', JSON.stringify(ping.json), '只读')

    // ③ AI 给一个**我建的**任务加步骤 = 「回报进展」的正规形式 → 那张卡要带「AI 建的」徽标
    const list = await t.api('GET', '/api/tasks')
    const mine = (Array.isArray(list.json) ? list.json : []).find((x) => x.title === '把第三章习题做完')
    if (!t.ok('拿得到我自己建的那个任务', Boolean(mine))) return
    const added = await t.api('POST', '/api/ai/tasks', { title: 'AI 加的步骤', parent_id: mine.id })
    t.eq('AI 能加步骤（这就是"回报进展"）', added.status, 200)
    await t.view('tasks')
    const body = await t.bodyText()
    t.has('任务列表里出现了它', body, 'AI 加的步骤')
    t.has('★ 那张卡上带「AI 建的」徽标（可回溯）', body, 'AI 建的')

    // ④ 边界：拿**我自己建的**任务去勾完成 → 400 带原话，而且**状态一个字节不动**
    const before = await t.api('GET', `/api/tasks/${mine.id}`)
    const bad = await t.api('POST', `/api/ai/tasks/${mine.id}/complete`, {})
    t.eq('勾你建的 → 400（这就是那道边界）', bad.status, 400)
    t.has('原话点明「是你亲手建的」', String(bad.json && bad.json.detail), '你亲手建的')
    // 别写死状态值（那是领域层的中文口径，会变）：**比"拒前拒后一不一样"**才是不变式
    const after = await t.api('GET', `/api/tasks/${mine.id}`)
    t.eq('被拒之后状态没被动过', after.json && after.json.status, before.json && before.json.status)
    t.eq('也没被写上完成时间', after.json && after.json.completed_at, before.json && before.json.completed_at)

    // ⑤ 收拾干净：关回去
    await t.view('setting')
    await t.openSetting('set-ai')              // 中间去过别的视图 → 折叠状态被重置了（T-G63）
    await t.pressAction('set-ai', { text: '关闭' })
    t.eq('能关回去', (await t.waitToast('AI 接口已关闭')).ok, true)
  },
})

flow({
  id: '㉔', name: '复习改判：记得 → 改判为忘了，进度不重复计（顺带 ⑤ toast 上那个「记一笔产出」）',
  item: 'T-G13 ㉔ 复习改判（同一趟顺带覆盖前端批次② ⑤）',
  vp: 'desktop',
  async run(t) {
    await t.start('review')
    /** 进度条上那个 **done 数**（`今日复习进度 0/2`）。**不写死总数** ——
     *  总数取决于"这一趟之前有没有别的流又建了一张复习卡"（① 就会），
     *  而这一条流真正要证明的是**改判不会重复计**：done 从 0 → 1，改判后**仍是 1**。
     *  （第一版写死了 `0/1`，单独跑绿、跟着整套跑红 —— **"两遍一致"抓不到这种错**，
     *    因为两遍都是按同一个顺序跑的。见复盘 §5-⑤。） */
    const doneCount = async () => {
      const row = await t.cdp.eval(`(() => {
        const e = [...document.querySelectorAll('.sub')].find((x) => x.textContent.includes('今日复习进度'));
        return e ? e.textContent.replace(/\\s+/g, '') : null })()`)
      const hit = /今日复习进度(\d+)\//.exec(String(row))
      return hit ? Number(hit[1]) : null
    }
    const TITLE = '拉格朗日中值定理'
    t.eq('一开始还没复习过（done=0）', await doneCount(), 0)
    t.has('到期那一节列着它', await t.bodyText(), `到期复习（`)

    // ① 点「记得」（**钉在那张卡里**点：这一页可能不止一张到期卡）
    const rate = await t.mark('[data-action="review-do"]', { inCard: TITLE, text: '记得' })
    if (!t.ok('到期卡上有「记得」', rate.ok)) return
    await t.press(HIT, '点「记得」')
    const rec = await t.waitToast('复习已记录')
    t.ok('记下来了', rec.ok, `提示条里是：${rec.text || '（空）'}`)
    t.has('★ 提示条上出现「记一笔产出」（前端批次② ⑤）', rec.text, '记一笔产出')
    t.eq('这一次计入进度（done=1）', await doneCount(), 1)
    t.has('「今天复习过的」里出现它、并写着今天记的是哪一档', await t.bodyText(), '今天记的是 记得')
    // ⑤ 的另一半：**不点会自己消失**（赖着不走就不叫"过场提示"了）
    t.ok('不去点它的话，提示条会自己消失', await t.waitFor(async () => (await t.toast()) === '', 9000))

    // ② 改判：同一档不给（改了没意义），只给另外两档
    const same = await t.mark('[data-action="review-regrade"]', { inCard: TITLE, text: '记得' })
    t.ok('不会给「改判为 记得」自己那一档（那是无效动作）', !same.ok)
    const amend = await t.mark('[data-action="review-regrade"]', { inCard: TITLE, text: '忘了' })
    if (!t.ok('已经复习过的卡上给了「改判为 忘了」', amend.ok)) return
    await t.press(HIT, '点「改判为 忘了」')
    t.has('二次确认说清了排期怎么重算', await t.text('#modalTitle'), '按新的一档重算')
    t.has('也说清了「投入不会重复计」', await t.text('#modalTitle'), '投入不会重复计')
    t.eq('确认按钮上写的是动作名', await t.text('#modalOk'), '改判')

    await t.pressAction('modal-ok')
    const done = await t.waitToast('已改判为「忘了」')
    t.ok('改判成功', done.ok, `提示条里是：${done.text || '（空）'}`)
    t.has('那行变成「忘了」', await t.bodyText(), '今天记的是 忘了')
    t.eq('★ 进度仍是 1（改判不重复计）', await doneCount(), 1)
  },
})

flow({
  id: '⑰', name: '跨端同步：导出的包真写出来了，自己导给自己被明说没有意义',
  item: 'G 批 ⑰ 跨端同步（没有第二台也能验一半）',
  vp: 'desktop',
  async run(t) {
    await t.start('setting')
    await t.openSetting('set-syncpack')        // T-G63：这一节现在是折着的
    t.has('这一节写着怎么用（导到另一台、先预览再导入）', await t.bodyText(), '先预览再导入')
    t.eq('「同时应用对方的删除」默认是不勾的（㉒ 的第一半）',
      await t.attr('#syncDel', 'checked'), null)
    t.has('旁边写着默认不删的理由', await t.text('#syncDelHint'), '默认不删')

    // ① 导出：真点界面上的按钮 → 提示条说"已写出 + 完整路径已复制" → ★ 文件**真的在磁盘上**
    await t.pressAction('sync-export')
    const wrote = await t.waitToast('同步包已写出')
    t.ok('点「导出同步包」有回话', wrote.ok, `提示条里是：${wrote.text || '（空）'}`)
    t.has('回话里说了包名与行数', wrote.text, 'sync-')
    t.has('也说了行数', wrote.text, '行')
    const pack = newestSyncPack()
    t.ok('★ 磁盘上真的多了一个同步包（不是嘴上说说）', Boolean(pack), `在 ${TEMP_DIR} 下没找到 sync-*.json`)

    // ② 把它粘回去预览 —— **这台机器导出的包**，所以后端应当拒绝并说清为什么
    if (pack) {
      // 先问后端一次（Node 侧）：它认这个包、但拒绝"自己导给自己" —— 这样界面那一步若没反应，
      // 是界面的事，而不是"包本身有问题"（不然两种失败分不开）。
      const apiRes = await t.api('POST', '/api/sync/import', { path: pack.path, dry_run: true })
      t.eq('后端认得这个包（只是拒绝自己导给自己）', apiRes.status, 400)
      t.has('后端原话就是「自己导给自己没有意义」', JSON.stringify(apiRes.json), '自己导给自己没有意义')

      await t.type('#syncPath', pack.path)
      t.eq('路径粘进去了（读的是 property，不是 attribute）', await t.value('#syncPath'), pack.path)
      await t.pressAction('sync-preview')
      const self = await t.waitToast('自己导给自己没有意义')
      t.ok('★ 界面上也明说了（把后端原话透出来）', self.ok, `提示条里说的是：${self.text || '（空）'}`)
      t.has('还告诉你该怎么做（在另一台导出、在这台导入）', self.text, '另一台机器')
      t.lacks('提示条里不画星号', self.text, '**')
    }

    // ③ 预览是**纯读**：一个字节都不该写（比对"上次导入"那行还在不在"还没导入过"）
    t.has('预览之后仍然写着「还没导入过」', await t.bodyText(), '上次导入：还没导入过')
  },
})

flow({
  id: '㉓', name: '团队视角：管理者/执行者两种看法，不填名字就不猜你是谁',
  item: 'T-G12 ㉓ 团队视角页',
  vp: 'desktop',
  async run(t) {
    await t.start('team')
    const body = () => t.bodyText()
    // ① 默认是管理者视角：按执行者分组（种子里"把数据整理成表"分配给了小李）
    t.has('默认是管理者视角（按执行者分组）', await body(), '小李 · 1 件')
    t.ok('管理者视角**不要**你填名字（分配记录本来就是你建的）', await t.count('#teamMe') === 0)
    t.has('页面上写着这是两种看法、不是两套数据', await body(), '不是两套数据')

    // ② 切到执行者视角：先要一个名字 —— 没填就**什么都看不到**（工具不猜你是谁）
    await t.pressAction('team-view', { text: '执行者' })
    t.ok('执行者视角要一个名字', await t.count('#teamMe') === 1)
    t.has('没填名字时明说"先填我是谁"', await body(), '先在上面填「我是谁」')

    // ③ 填分配记录里写过的那个名字 → 只看到分给这个人的
    await t.type('#teamMe', '小李')
    await t.pressAction('team-me')
    const named = await t.waitToast('执行者视角：你是「小李」')
    t.ok('名字记在这台设备上', named.ok, `提示条里是：${named.text || '（空）'}`)
    t.has('看到的就是分给小李的那件', await body(), '把数据整理成表')
    t.eq('本机记下了这个名字', await t.ls('tf_team_me'), '小李')

    // ④ 换一个名字 → 分给别人的一件都没有（**不制造假归因**）
    await t.type('#teamMe', '王五')
    await t.pressAction('team-me')
    await t.waitToast('执行者视角：你是「王五」')
    t.has('换一个名字就什么都看不到（不猜、也不硬塞）', await body(), '这个视角下没有任务')

    // ⑤ 视角与名字都活过刷新
    await t.reload()
    await t.view('team')
    t.eq('刷新之后还是执行者视角', await t.ls('tf_team_view'), 'executor')
    t.eq('刷新之后名字还在（本机记着）', await t.attr('#teamMe', 'value'), '王五')
  },
})

flow({
  id: '㉕', name: '学校通知合作接口：默认关 → 投递去重 → 转成任务 → 关掉后 403',
  item: 'G 批 ㉕ 学校通知合作接口',
  vp: 'desktop',
  async run(t) {
    await t.start('setting')
    await t.openSetting('set-notify')          // T-G63：这一节现在是折着的
    t.has('默认是关的（并说清这叫「未接入」）', await t.bodyText(), '这叫"未接入"')

    // ① 关着的时候：投递一律 403（这是"未接入"，不是坏掉）
    const note = { source: '教务处', external_id: 'N-2026-001', title: '期中考试安排已发布',
      url: 'https://example.edu/x', summary: '高数期中在第十周周三' }
    const off = await t.api('POST', '/api/notify/school', note)
    t.eq('关着时投递被 403 拒绝', off.status, 403)
    t.has('原话说明这是「没接入」不是故障', JSON.stringify(off.json), '没接入')
    t.has('也点明了默认收严这条口径', JSON.stringify(off.json), '默认收严')

    // ② 打开（真点按钮），投递一条 → 收件箱里出现
    await t.pressAction('set-notify', { text: '打开' })
    const opened = await t.waitToast('合作接口已打开')
    t.ok('开关能打开', opened.ok, `提示条里是：${opened.text || '（空）'}`)
    const first = await t.api('POST', '/api/notify/school', note)
    t.eq('打开后投递成功', first.status, 200)
    t.eq('这是新收下的一条', first.json && first.json.created, true)

    // ③ 同一条**再投一次** → 去重：不新增行、返回 duplicate
    const again = await t.api('POST', '/api/notify/school', note)
    t.eq('重复投递不算错', again.status, 200)
    t.eq('★ 去重：同一来源同一条只留一行', again.json && again.json.duplicate, true)
    const inbox = await t.api('GET', '/api/notify/school')
    t.eq('收件箱里仍然只有一条', inbox.json && inbox.json.count, 1)

    // ④ 回设置页刷新 → 收件箱看得见，点「转成任务」
    await t.view('setting')
    t.has('设置页收件箱里出现了这条通知', await t.bodyText(), '期中考试安排已发布')
    await t.pressAction('notice-to-task', { text: '转成任务' })
    const made = await t.waitToast('已转成任务')
    t.ok('点一下才转成任务（人始终在环里）', made.ok, `提示条里是：${made.text || '（空）'}`)

    // ⑤ 转出来的任务**看得出从哪来**（来源 + 链接 + 摘要都写进备注）
    await t.view('tasks')
    const card = await t.mark('[data-action="task-detail"]', { inCard: '期中考试安排已发布' })
    if (t.ok('任务列表里出现了这条任务', card.ok)) {
      await t.press(HIT, '打开它看备注')
      const detail = await t.text('#detailRail')
      t.has('★ 备注里写着「来自学校通知」（可回溯）', detail, '来自学校通知：教务处')
      t.has('链接也在备注里', detail, 'https://example.edu/x')
    }

    // ⑥ 关回去：新投递又被 403，但**已有的那条照样能处理**（收件箱是你的数据）
    await t.view('setting')
    await t.openSetting('set-notify')          // 中间去过别的视图 → 折叠状态被重置了（T-G63）
    await t.pressAction('set-notify', { text: '关闭' })
    t.eq('能关回去', (await t.waitToast('合作接口已关闭')).ok, true)
    const closed = await t.api('POST', '/api/notify/school', { source: '教务处', external_id: 'N-2026-002', title: '又一条' })
    t.eq('关掉之后投递又被 403', closed.status, 403)
    const still = await t.api('GET', '/api/notify/school')
    t.eq('收件箱里那条还在（读不要求接口开着）', still.json && still.json.count, 1)
  },
})

flow({
  id: '㉗', name: '离线只读区：联网逛过之后断网，那一区看得见、且一个按钮都没有',
  item: 'T-G16 ㉗ 手机上看得更全（离线只读区）',
  vp: 'phone',
  async run(t) {
    // ① 联网时先逛一遍（手机档宽度 —— 这正是"手机上看得更全"那条人工项的场景）
    //    注意手机上没有左栏：底栏只有 7 个入口，复习/学业/备忘录那些**从设置页那一节进**
    //    （左栏 nav 在 ≤640px 是 `display:none`，所以"点得到"这件事在手机档是真的要挑入口的）。
    await t.start('today')
    await t.view('tasks')
    await t.view('setting')
    await t.view('review')

    // ② 断网前先确认**壳已经被 Service Worker 接管** —— 不然"断网还能打开"根本无从谈起
    //    （这一步是把前提说出来，不是把失败藏起来：壳没接管，下面那条断言会直接红）
    const swReady = await t.waitFor(async () => Boolean(await t.cdp.eval(
      '!!(navigator.serviceWorker && navigator.serviceWorker.controller)')), 10000)
    t.ok('壳已经装进 Service Worker（断网才可能打开这一页）', swReady)

    // ③ 断网（DevTools 那个 Offline 开关就是这条 CDP：`navigator.onLine` 与 online/offline 事件都会跟着变）
    await t.cdp.setOffline(true)
    t.eq('断网之后浏览器自己知道', await t.cdp.eval('navigator.onLine'), false)

    // ④ ★ 断网**刷新** —— 应自动落到「离线记」（壳从缓存里拿出来，见 `offlineNow()?'offline':'today'`）
    await t.reload()
    t.ok('★ 断网刷新之后自动落在「离线记」这一页', await t.count('#offlineSeen') > 0,
      `页面上看到的是：${(await t.bodyText()).slice(0, 120)}`)

    // ⑤ ★ 只读区四段都要在（数据是**上次联网时**那几份接口的响应，原样缓存、不在这里重算）
    const seen = await t.text('#offlineSeen')
    if (t.ok('★ 断网后看得到「上次看到的（只读）」那一区', Boolean(seen))) {
      t.has('有「该提醒了」那一段', seen, '该提醒了（')
      t.has('有「今天该复习」那一段', seen, '今天该复习（')
      t.has('有「逾期」那一段', seen, '逾期（')
      t.has('有今日摘要那一行', seen, '今日摘要（上次联网时）')
      t.has('★ 如实写着"不是实时的"', seen, '上次联网时看到的样子')
      t.has('★ 也写着提醒只标不通知', seen, '只标出来、不发系统通知')
      // ★ 反证：这一区**一个能改数据的动作都没有**（提醒是"标出来"，不是"点掉"）
      t.eq('★ 只读区里一个按钮/动作都没有', await t.count('#offlineSeen [data-action]'), 0)
    }

    // ⑥ 页面上还写着"怎么回电脑"（离线包只有一个格式，见结构约定）
    t.has('页面上写着回电脑的路', await t.bodyText(), '同步包')

    // ⑦ 收拾干净：把网接回来（下一条流不该继承"断网"这个状态）
    await t.cdp.setOffline(false)
    t.eq('网接回来了', await t.cdp.eval('navigator.onLine'), true)
  },
})

flow({
  id: '⑮', name: 'Obsidian 只读跳转：红线真的拦得住（导出目录不许放进 Vault）',
  item: 'G 批 ⑮ Obsidian（只读跳转）+ 红线 400',
  vp: 'desktop',
  async run(t) {
    await t.start('setting')
    await t.openSetting('set-export')           // T-G63：Vault 那一节住在「导出」这一节里
    const vault = join(EXPORT_DIR, 'flow-vault')
    mkdirSync(vault, { recursive: true })
    t.has('界面写着这是只读跳转（不往 Vault 里写东西）', await t.bodyText(), '只读')

    // ① 存 Vault（名字 + 根目录）——根目录**必须真的存在**（软件不会替你在 Vault 里建目录）
    await t.type('#vaultName', '我的笔记库')
    await t.type('#vaultDir', vault)
    await t.pressAction('set-vault')
    const saved = await t.waitToast('已保存：Vault')
    t.ok('Vault 设置能存下', saved.ok, `提示条里是：${saved.text || '（空）'}`)

    // ② ★ 红线：把导出目录填成 Vault 里的子目录 → 后端 400 带原话
    await t.openSetting('set-export')          // T-G63：导出那一节也是折着的
    await t.type('#exportDir', join(vault, 'timeflow-export'))
    await t.key('Enter')
    const red = await t.waitToast('操作未完成')
    t.ok('★ 把导出目录放进 Vault 被拦下了', red.ok, `提示条里说的是：${red.text || '（空）'}`)
    t.has('原话点明了红线（导出目录不能放在 Vault 里）', red.text, '导出目录不能放在 Obsidian 的 Vault 里')
    t.lacks('原话进了提示条也不画星号', red.text, '**')

    // ③ 拦下之后**后端那边的设置没有被偷偷改掉**（不然就是"报错了但已经写进去"）
    const after = await t.api('GET', '/api/settings/export')
    t.has('导出目录在后端还是原来那个', JSON.stringify(after.json), 'tf-render-export')

    // ④ 只有"真的跳过去"这件事**故意不验** —— 那一下会真的把 Obsidian 拉起来
    //    （人要看见的是"点一下能跳过去"，机器没法在不启动外部程序的前提下证明它）。
    t.has('设置页写着这是只读跳转（不往笔记库里写东西）', await t.bodyText(), '只读跳转')

    // ⑤ 收拾干净：清空 Vault 设置（跳转关着）
    await t.clear('#vaultName')
    await t.clear('#vaultDir')
    t.eq('名字真被清空了', await t.value('#vaultName'), '')
    await t.pressAction('set-vault')
    t.eq('能关掉跳转', (await t.waitToast('已清空 Vault 设置')).ok, true)
  },
})

flow({
  id: '㉑', name: '14 个视图里都没有字面的星号（**）',
  item: 'T-G11 ㉑ 扫一眼还有没有字面的星号',
  vp: 'desktop',
  async run(t) {
    await t.start('today')
    const bad = []
    let total = 0
    for (const v of VIEWS) {
      // 只扫文本：用轻量的"这一屏画出来了"就够（14 个视图 × 整页安静 = 光是等就 30s）
      if (v === 'offline') {
        // T-G162：「离线记」不在 PC 左栏了 —— 从它现在的真入口进（设置→数据「手机离线记」小节）
        await t.view('setting', { quiet: false })
        await t.openSetting('set-offline')
        await t.press('[data-action="view"][data-view="offline"]', '设置→数据的「离线记」入口', { quiet: false })
      } else {
        await t.view(v, { quiet: false })
      }
      // **一处都不放过**：这句话本来是"人扫一眼"，人扫一眼最容易只看见第一处 ——
      // 所以这里把每一处都抠出来（含上下文），而不是碰见第一个就收工。
      const hits = await t.cdp.eval(`(() => {
        const text = document.body.innerText.replace(/\\s+/g, ' ');
        const out = [];
        let i = text.indexOf('**');
        while (i >= 0 && out.length < 20) {
          out.push(text.slice(Math.max(0, i - 30), i + 30));
          i = text.indexOf('**', i + 2);
        }
        return out;
      })()`)
      for (const h of hits) bad.push(`${v}: …${h}…`)
      total += hits.length
    }
    t.ok(`14 个视图逐页扫过，一处字面的 ** 都没有（共扫出 ${total} 处）`, bad.length === 0, bad.join('\n       · '))
  },
})

flow({
  id: 'K', name: '命令面板（键盘附加层）：真按键打开、真打字过滤、↑↓ 换选中、Enter 跑、Esc 关',
  item: '新增（不是搬移项）：T-G61 键盘附加层 ②③④ —— 它本来就还没有人工项可搬',
  vp: 'desktop',
  async run(t) {
    await t.start('today')
    // ① 默认不在；入口上写着键位（键盘那半的"可学习性"—— 借的是 Raycast 的"快捷键可学习"，
    //    不是"一切都靠键盘"）
    t.eq('一开始没有面板', await t.attr('#palette', 'hidden'), '')
    t.has('左栏那个入口把键位写在自己身上', await t.text('#cmdBtn'), 'Ctrl K')

    // ② 真按 Ctrl+K（走浏览器真正的事件管线，不是调函数）
    await t.chord('k')
    t.eq('Ctrl+K 打开了面板', await t.attr('#palette', 'hidden'), null)
    t.eq('焦点落在过滤框里（不是别处）', await t.cdp.activeElement(), 'input#paletteInput')
    const box = await t.geom('.palette-box')
    t.ok('面板在视口里（没被推到屏幕外）', box && box.x >= 0 && box.y >= 0 && box.w > 0, JSON.stringify(box))
    t.ok('它是个小浮层、没盖满宽度', box && box.w <= 640, JSON.stringify(box))
    const backdrop = await t.geom('.palette-backdrop')
    t.ok('遮罩铺满视口（点空白处能关）', backdrop && backdrop.w > 600 && backdrop.h > 400, JSON.stringify(backdrop))
    const rows0 = await t.count('.palette-row')
    t.ok('列出的命令够多（动作 + 视图）', rows0 >= 15, `只有 ${rows0} 条`)
    t.has('列表按组分节', await t.text('#paletteList'), '视图')
    t.eq('开局选中的正好一条', await t.count('.palette-row.on'), 1)
    t.eq('选中的是第一条', await t.attr('.palette-row.on', 'data-index'), '0')

    // ③ ↑↓ 换选中（真方向键；此时还是全表）
    await t.key('ArrowDown')
    t.eq('↓ 之后选中的是第二条', await t.attr('.palette-row.on', 'data-index'), '1')
    await t.key('ArrowUp')
    t.eq('↑ 回到第一条', await t.attr('.palette-row.on', 'data-index'), '0')

    // ④ 真打字过滤（界面走的是 `input` 事件 —— 中文输入法选字时不发 keydown，只有这条路抓得到），
    //    然后 Enter 跑筛出来的那一条：**面板不是摆设**，它真的切了视图
    await t.type('#paletteInput', '复习')
    const rows1 = await t.count('.palette-row')
    t.ok('打字就筛（剩下的比全表少）', rows1 >= 1 && rows1 < rows0, `${rows0} → ${rows1}`)
    t.has('筛出来的就是「复习」', await t.text('#paletteList'), '复习')
    t.lacks('没关的视图被筛掉了', await t.text('#paletteList'), '备忘录')
    await t.key('Enter')
    t.eq('Enter 之后面板自己关掉', await t.attr('#palette', 'hidden'), '')
    t.ok('真的到了复习页', (await t.count('[data-view="review"].active')) >= 1)

    // ⑤ 单字母快捷键：**没在打字**时生效
    await t.key('t')
    t.ok('单字母 t 回今日页', (await t.count('[data-view="today"].active')) >= 1)
    await t.key('h')
    t.ok('单字母 h 去习惯页', (await t.count('[data-view="habit"].active')) >= 1)
    //    而**在打字**时一个字都不抢（这是"附加层"不惹麻烦的关键）
    await t.key('t')
    await t.press('#newTitle', '今日页的新建输入框')
    await t.cdp.typeText('h')
    t.has('输入框里的 h 就是 h（没被当成快捷键）', await t.value('#newTitle'), 'h')
    t.ok('还站在今日页（没被 h 切去习惯页）', (await t.count('[data-view="today"].active')) >= 1)

    // ⑥ 再开一次：面板里那条「设置」Enter 过去（顺带证明每次打开都是**全表、选第一条**）
    await t.chord('k')
    await t.eq('再按 Ctrl+K 又开', await t.attr('#palette', 'hidden'), null)
    t.eq('重新打开是全表（不是上次筛剩的）', await t.count('.palette-row'), rows0)
    await t.type('#paletteInput', '设置')
    await t.key('Enter')
    t.ok('从面板回车能到设置页', (await t.count('[data-view="setting"].active')) >= 1)

    // ⑦ 那条「新建任务」把光标送进输入框（不造第二个创建路径）
    await t.chord('k')
    await t.key('Enter')                       // 选中态是全表第一条 = 新建任务
    t.eq('跑完自己关掉', await t.attr('#palette', 'hidden'), '')
    t.eq('光标落进了今日页那个输入框', await t.cdp.activeElement(), 'input#newTitle')

    // ⑧ Esc：关掉最上面那一层。两条都验 —— 面板，以及**一直关不掉的模态**
    //    （模态的注释里写着"可键盘"，但从 R2 建起来到这次之前，Esc 对它没有任何作用）
    await t.chord('k')
    await t.key('Escape')
    t.eq('Esc 关掉面板', await t.attr('#palette', 'hidden'), '')
    const made = await t.api('POST', '/api/tasks', { title: 'ESC 取消删除用', is_myday: true })
    const tid = made.json && made.json.id
    t.ok('（准备）建了一张待删的任务', Boolean(tid), JSON.stringify(made).slice(0, 120))
    await t.view('today')
    // ★ T-G63（按钮瘦身）：卡上不再是一排 8–10 个同级按钮 —— 先量一张卡，再走"删除在「…」里"这条路。
    const rowBtns = await t.cdp.eval(`(() => { const c = document.querySelector('.card');
      if (!c) return -1;
      return [...c.querySelectorAll(':scope > .row > button')].filter((b) => b.getClientRects().length).length })()`)
    t.ok('一张卡上常显的动作 ≤3 个（勾选圈在卡外，不计）', rowBtns >= 1 && rowBtns <= 3, `实测 ${rowBtns} 个`)
    t.eq('删除不在卡上直接摆着（它在「…」里）', await t.count('[data-action="task-delete"]'), 0)
    await t.pressAction('task-more', { inCard: 'ESC 取消删除用' })
    t.eq('点「…」才展开菜单，删除在里面', await t.count('[data-action="task-delete"]'), 1)
    await t.pressAction('task-delete', { inCard: 'ESC 取消删除用' })
    t.eq('删除弹出了站内确认框', await t.attr('#modal', 'hidden'), null)
    await t.key('Escape')
    t.eq('Esc 关得掉确认框', await t.attr('#modal', 'hidden'), '')
    t.has('任务还在（Esc 是取消，不是确认）', await t.bodyText(), 'ESC 取消删除用')
    // 菜单也能收起来（同一张卡再点一次）—— 不然展开一次就永远是展开的
    await t.pressAction('task-more', { inCard: 'ESC 取消删除用' })
    t.eq('再点一次「…」收起菜单', await t.count('[data-action="task-delete"]'), 0)
    if (tid) await t.api('DELETE', `/api/tasks/${tid}`)

    // ⑨ 鼠标那半：点「命令」开、点空白关（附加层也要能用鼠标发现它）
    await t.pressAction('palette-open')
    t.eq('点左栏「命令」也能开', await t.attr('#palette', 'hidden'), null)
    await t.pressAction('palette-close')
    t.eq('点空白处关掉', await t.attr('#palette', 'hidden'), '')
  },
})

/* ------------------------------------------- 人工验收搬家 · 第五批（T-G73）-----------
 *
 * 搬的是 §二 清单里标着「下一批可搬的（工具已就位）」那四条：⑭ 词表 / ㉒ 删除可选 /
 * ㉖ 手机上传 / ㉘ 跨端镜像（双窗口版）。
 *
 * 这一批和前三批（T-G34/35/36/37）的不同：那三批搬的是"一屏之内点几下"的项，
 * 这四条**都要第二样东西**才验得了 —— 第二个库（㉒）、第二个客户端（㉘）、
 * 断网那一半（㉖）、以及"加的一项在另一处真的生效"（⑭）。所以它们比前面的流慢，
 * 这笔账照旧明码标价（每条的秒数由跑的时候打出来）。
 *
 * 仍然搬不动的（照旧留在人工那一栏，别假装搬了）：
 *   · 真手机 / 真校园网 / 两个**物理**窗口 —— 这里是"同一台机器上的两个真浏览器"；
 *   · 真把 Obsidian 拉起来（⑮ 那半）、桌面窗口长什么样（⑫）、备份恢复动真数据（⑪）。
 */

flow({
  id: '⑭', name: '可配置词表：界面上加一项，复习卡的形式下拉里立刻选得到',
  item: 'C 批 ⑭ 可配置词表（加一项 → 复习卡里选得到）',
  vp: 'desktop',
  async run(t) {
    // 词表 key 是**后端**的（`vocab.REVIEW_FORMS.key`），界面按它拼元素 id：`vb_<key>_id/_label`
    const KEY = 'review_forms'
    const del = `[data-action="vocab-del"][data-key="${KEY}"]`
    const add = `[data-action="vocab-add"][data-key="${KEY}"]`
    const reset = `[data-action="vocab-reset"][data-key="${KEY}"]`
    // 这张页上有好几张词表、每张一个「加一项」——`pressAction` 只按 data-action 挑会挑错，
    // 所以这里按**带 data-key 的选择器**挑，再走同一条"真按 + 命中测试"的路。
    const press = async (sel, label) => {
      // ★ 卡 092 补齐：与 t.press / t.pressAction 同一判据 —— 先轮询等它出现，别一次性断言
      let m = null
      const readyMs = 8000
      const got = await t.waitFor(async () => { m = await t.mark(sel); return m.ok }, readyMs)
      if (!got) { t.ok(`点得到：${label}`, false, `等了约${readyMs}ms，匹配到 ${m.all} 个`); return false }
      return t.press(HIT, label, { readyMs })
    }

    // ① 先记下**没加之前**卡上那个下拉长什么样（下面要比"只多了这一项、别的没动"）
    await t.start('review')
    t.ok('界面上有可编辑的复习卡', await t.count('[data-action="review-edit"]') >= 1)
    const cardId = await t.attr('[data-action="review-edit"]', 'data-id')
    await t.pressAction('review-edit')
    const opts0 = await t.count('#rvForm option')
    const form0 = await t.value('#rvForm')
    t.ok('（准备）卡上原来选的就是词表里的某一项', Boolean(form0), `实测 ${form0}`)
    await t.pressAction('review-edit-cancel')

    // ② 设置页：这一节折着（折着也写着现状），展开才出控件
    await t.view('setting')
    t.eq('「可配置词表」这一节默认折着', (await t.geom('#body-set-vocab')).display, 'none')
    await t.openSetting('set-vocab')
    t.has('折着也看得见现状', await t.text('#sum-set-vocab'), '现状：')
    const before = await t.count(del)
    t.ok('「复习形式」那张表本来就有几项', before >= 3, `实测 ${before} 项`)

    // ③ 反证：两个框都空 → 界面自己拦（不拿空 id 去撞后端）
    await press(add, '「复习形式」的加一项（空框）')
    t.ok('空框时说清了要填什么', (await t.waitToastWhere((x) => x.includes('id 和显示名都要填'))).ok,
      '等了约 12s 也没等到「id 和显示名都要填」那句话')

    // ④ 反证：非法 id → **后端原话**透出来，且那张表一个字节没变
    await t.type(`#vb_${KEY}_id`, 'My Form')
    await t.type(`#vb_${KEY}_label`, '口述复述')
    await press(add, '「复习形式」的加一项（非法 id）')
    const bad = await t.waitToast('id 只能')
    t.has('非法 id 被拦下，且用的是后端自己的原话', bad.text, 'id 只能用小写英文')
    t.eq('拦下之后那张表没多出东西', await t.count(del), before)

    // ⑤ 真加一项（真打字；`type` 先 Ctrl+A，等于覆盖上次填的）
    await t.type(`#vb_${KEY}_id`, 'my_form')
    await t.type(`#vb_${KEY}_label`, '口述复述')
    await press(add, '「复习形式」的加一项')
    const okAdd = await t.waitToast('已加进')
    t.has('加成功的回话里带那张表的名字与这一项', okAdd.text, '已加进「复习形式」：口述复述')
    t.eq('表里只多了一项', await t.count(del), before + 1)

    // ⑥ ★ 人工项的本体：复习卡的「形式」下拉里选得到刚加的那项
    await t.view('review')
    await t.pressAction('review-edit')
    t.eq('★ 下拉里多了一项', await t.count('#rvForm option'), opts0 + 1)
    t.has('★ 多的那一项就是刚加的', await t.text('#rvForm'), '口述复述')
    t.eq('★ 已有卡片原来选的那一项没被顶掉', await t.value('#rvForm'), form0)
    // 选它 → 保存：整条链走通（界面 → 词表生效 → 后端按**现在的**词表校验 → 落库）。
    // 这里直接改 `value`：`review-save` 读的就是它，而这个 select 上没有任何 change 监听
    //（`data-change` 没挂它）—— 用户选一下和这一句在浏览器里是同一件事。
    await t.cdp.eval(`(() => { document.getElementById('rvForm').value = 'my_form'; return true })()`)
    await t.pressAction('review-save')
    t.ok('保存有回话', (await t.waitToast('已保存')).ok)
    const back = cardId ? await t.api('GET', `/api/review/items/${cardId}`) : null
    t.eq('★ 卡上那个新形式真的落库了', back && back.json && back.json.form, 'my_form')

    // ⑦ 收尾：把卡改回原来的形式，再把词表回到默认 —— 别给后面的流留一个"词表里没有的形式"
    if (cardId && form0) await t.api('PATCH', `/api/review/items/${cardId}`, { form: form0 })
    await t.view('setting')
    await t.openSetting('set-vocab')
    await press(reset, '「复习形式」的回到默认')
    t.ok('回默认有回话', (await t.waitToast('已回到默认')).ok)
    t.eq('表回到原来的条数', await t.count(del), before)
  },
})

flow({
  id: '㉒', name: '删除可选：拿一份"别的设备的包"真导一次 —— 默认不删，勾了才删，取消不动库',
  item: 'B 批 ㉒ 删除可选（剩下的那半：别的设备的包真导一次）',
  vp: 'desktop',
  async run(t) {
    // 人工项的本体是"**拿一份别的设备的包**"——所以这一条里**真的**再起一个服务当那台设备：
    // 它有自己的库、自己的 device_id、自己的包（不是自己导给自己，那种会被后端拒）。
    const peerPort = Number(new URL(t.url).port) + 6
    const peerUrl = `http://127.0.0.1:${peerPort}/`
    const peer = startServer(peerPort)
    try {
      t.ok('（准备）另起一份真库当"另一台设备"', await waitHealth(peerPort))
      const made = await t.api('POST', '/api/tasks', { title: '别的设备上彻底删掉的那条', is_myday: true }, peerUrl)
      const yid = made.json && made.json.id
      t.ok('（准备）那台上建了一条任务', Boolean(yid), JSON.stringify(made).slice(0, 120))
      if (!yid) return
      const p1 = await t.api('POST', '/api/sync/export', {}, peerUrl)
      const path1 = p1.json && p1.json.path
      t.ok('（准备）导出第一份包（那条行还在里面）', Boolean(path1), JSON.stringify(p1).slice(0, 140))
      if (!path1) return

      // ① 界面上把那份包导进来 —— 于是本机与"另一台"有了同一行（连 id 都一样）
      await t.start('setting')
      await t.openSetting('set-syncpack')
      await t.type('#syncPath', path1)
      await t.pressAction('sync-preview')
      t.ok('先预览有回话', (await t.waitToast('预览：')).ok)
      await t.pressAction('sync-import')
      t.eq('导入前有站内二次确认', await t.attr('#modal', 'hidden'), null)
      t.lacks('默认那一档的确认按钮上不写"删除"', await t.text('#modalOk'), '删除')
      await t.pressAction('modal-ok')
      t.ok('导入完成', (await t.waitToast('已导入：')).ok)
      const listA = await t.api('GET', '/api/tasks')
      t.ok('★ 那台设备上的行真的进来了（同一行 id 也带过来了）', (listA.json || []).some((x) => x.id === yid))
      const stillThere = async () => (await t.api('GET', '/api/tasks')).json.some((x) => x.id === yid)

      // ② 那台上**彻底删掉**它（软删进回收站 → 清空回收站 = 真删；墓碑是 DELETE 触发器写的）
      await t.api('DELETE', `/api/tasks/${yid}`, undefined, peerUrl)
      const purged = await t.api('DELETE', `/api/tasks/${yid}/purge`, undefined, peerUrl)
      t.eq('（准备）那台上彻底删掉了它', purged.status, 200)
      const p2 = await t.api('POST', '/api/sync/export', {}, peerUrl)
      const path2 = p2.json && p2.json.path
      t.ok('（准备）第二份包：只剩它的墓碑', Boolean(path2))
      if (!path2) return

      // ③ 默认那一档（不勾）：预览里不许出现"删除"，导完那一行**还在**
      await t.type('#syncPath', path2)
      await t.pressAction('sync-preview')
      const prev = await t.waitToast('预览：')
      t.has('预览里如实说明按墓碑跳过/记下墓碑', prev.text, '墓碑')
      t.lacks('★ 默认那一档的预览里没有"删除"', prev.text, '删除')
      await t.pressAction('sync-import')
      t.lacks('默认那一档的确认按钮上也没写"删除"', await t.text('#modalOk'), '删除')
      await t.pressAction('modal-ok')
      t.ok('★ 反证：默认那一档导完，本地那一行还在', await stillThere())

      // ④ 勾上「同时应用对方的删除」→ 提示改成人话（含不可撤销），预览说要删 1 行
      //    注意：上一步导入成功后会 `view(current)` 重渲染 —— 输入框被**重建**（里面是空的），
      //    那颗勾选框也回到默认。所以每碰一次"导入成功"，路径与勾选都要重新来一遍。
      await t.type('#syncPath', path2)
      await t.press('#syncDel', '「同时应用对方的删除」勾选框')
      t.eq('勾上了', await t.cdp.eval('document.getElementById("syncDel").checked'), true)
      const hint = await t.text('#syncDelHint')
      t.has('★ 勾上之后把"这会删东西"说清楚', hint, '不可撤销')
      t.has('也说了本地改过的那种仍然不删', hint, '本地改过的那种仍然不删')
      await t.pressAction('sync-preview')
      t.ok('★ 预览明说会删 1 行',
        (await t.waitToastWhere((x) => x.includes('预览：') && x.includes('删除 1 行'))).ok,
        '等了约 12s 也没等到同时含「预览：」与「删除 1 行」的提示条')

      // ⑤ 取消 = 什么都不动（★ 反证：确认框不是"点了就干"）
      await t.pressAction('sync-import')
      t.eq('确认按钮写的是「导入并删除」', await t.text('#modalOk'), '导入并删除')
      t.has('确认框里带 ⚠️ 那半句（不可撤销）', await t.text('#modalTitle'), '不可撤销')
      await t.key('Escape')
      t.eq('Esc 关掉了确认框', await t.attr('#modal', 'hidden'), '')
      t.ok('★ 反证：取消之后那一行还在', await stillThere())

      // ⑥ 真删（同一个包、同一个勾选，这次点确认）
      await t.pressAction('sync-import')
      await t.pressAction('modal-ok')
      t.ok('导入报告里写了删了几行',
        (await t.waitToastWhere((x) => x.includes('已导入：') && x.includes('删除 1'))).ok,
        '等了约 12s 也没等到同时含「已导入：」与「删除 1」的提示条')
      t.ok('★ 勾了才真删：那一行不在了', !(await stillThere()))
    } finally {
      try { peer.child.kill() } catch { /* ignore */ }
    }
  },
})

flow({
  id: '㉖', name: '手机直接上传：断网先记、离线点它给原话、连上才传、重复传不重复计数',
  item: 'A 批 ㉖ 手机直接上传同步包',
  vp: 'phone',
  async run(t) {
    const TITLE = '手机上断网记的一条'
    // ① 联网时先逛一下（离线页那半"上次看到的"要有东西可看）
    await t.start('today')
    await t.view('tasks')

    // ② ★ 断网**刷新** —— 壳从 Service Worker 里拿出来，自动落回「离线记」（同 ㉗ 那条流）
    const swReady = await t.waitFor(async () => Boolean(await t.cdp.eval(
      '!!(navigator.serviceWorker && navigator.serviceWorker.controller)')), 10000)
    t.ok('壳已经装进 Service Worker（断网还能回到这一页）', swReady)
    await t.cdp.setOffline(true)
    t.eq('断网之后浏览器自己知道', await t.cdp.eval('navigator.onLine'), false)
    await t.reload()
    t.ok('★ 断网刷新落在「离线记」', await t.count('#offlineStatus') > 0)

    // ③ 断网记一条 → **存进手机队列**，并且如实说"先存在手机上"
    await t.type('#offTitle', TITLE)
    await t.pressAction('offline-task-add')
    t.ok('★ 断网时如实说"先存在手机上"',
      (await t.waitToastWhere((x) => x.includes('连不上电脑') && x.includes('先存在手机上'))).ok,
      '等了约 12s 也没等到同时含「连不上电脑」与「先存在手机上」的提示条')
    t.has('队列里看得见这一条', await t.bodyText(), TITLE)
    t.has('待同步计数是 1', await t.text('#offlineStatus'), '待同步 1 条')

    // ④ ★ 反证：**离线时**点「直接传到电脑」→ 直说"等连上再点"，不许转圈再失败
    await t.pressAction('offline-upload')
    const off = await t.waitToast('现在连不上电脑')
    t.has('★ 离线时点它就是这句话', off.text, '先「导出同步包」')
    t.eq('也没有弹确认框（它一步都没走）', await t.attr('#modal', 'hidden'), '')
    const notYet = await t.api('GET', '/api/tasks')
    t.ok('★ 反证：这时候电脑库里没有那条（没有偷偷传）',
      !(notYet.json || []).some((x) => x.title === TITLE))
    t.has('队列还在（1 条）', await t.text('#offlineStatus'), '待同步 1 条')

    // ⑤ 连上 → 真传（先问一句，再走电脑上那条**已有的合并路径**）
    await t.cdp.setOffline(false)
    t.eq('网接回来了', await t.cdp.eval('navigator.onLine'), true)
    // ★ T-G76 之一：**界面自己会走回在线**（不靠用户点、不靠刷新）—— 这是修好的那半。
    //   T-G73 记的病症：断网期间"在飞"的请求失败得晚，网回来了它才回来、把标记又打回离线。
    //   现在「出发早于最近一次成功」的失败不许再改标记（`markDown(startedAt)`），所以它会自己收敛。
    const stateOf = () => t.cdp.eval('({off: offlineNow(), down: netDown, net: navigator.onLine})')
    const online = await t.waitFor(async () => (await stateOf()).off === false, 12000, 250)
    t.ok('★ 界面自己走回在线（不靠用户点、不靠刷新）', online, JSON.stringify(await stateOf()))
    // ★ T-G76 之二（**确定性的那一半**）：把"它以为是断的"和"点下去"放进**同一次求值**里 ——
    //   JS 不会在中间插进别的任务，所以这一下必然走"提示说连不上"的那条分支
    //   （T-G73 那两秒窗口里就是它）。旧写法在这里**直接拒绝**：一个明明能成的操作连试都不试。
    //   为什么这一步允许合成 click：要验的是**决定**（拒绝之前探不探），不是"点得到" ——
    //   后者 ④ 已经用真鼠标证过（真点击 → 真原话），往下的确认与上传也仍然走真鼠标。
    const forced = await t.cdp.eval(`(() => {
      netDown = true;
      const b = document.querySelector('[data-action="offline-upload"]');
      if (!b) return null;
      const hint = offlineNow();          // 点下去那一刻，界面以为自己是离线的
      b.click();
      return { hint };
    })()`)
    t.ok('（准备）按回"以为是断的"，且那一刻确实是那个状态', Boolean(forced) && forced.hint === true,
      JSON.stringify(forced))
    const asked = await t.waitFor(
      async () => String(await t.text('#modalTitle') || '').includes('传到电脑'), 8000)
    t.ok('★ 提示过期也照样试：确认框出来了', asked, await t.text('#modalTitle'))
    t.eq('★ 一探就自己更正了（标记回到假）', await t.cdp.eval('netDown'), false)
    await t.pressAction('modal-ok')
    const sent = await t.waitToast('已传到电脑')
    t.ok('★ 回话里带合并报告', sent.ok && sent.text.includes('新增'),
      `提示条里是：${sent.text || '（空）'}`)
    const inPc = async () => (await t.api('GET', '/api/tasks')).json.filter((x) => x.title === TITLE).length
    t.eq('★ 电脑库里真的多了一条（就叫这个名字）', await inPc(), 1)

    // ⑥ ★ 传完**再问一次**要不要清空手机队列；这次先不清（下面还要验重复传）
    t.has('★ 传完又问了一次要不要清空队列', await t.text('#modalTitle'), '清空手机上的队列')
    await t.pressAction('modal-cancel')
    t.has('没清：队列还在（1 条）', await t.text('#offlineStatus'), '待同步 1 条')

    // ⑦ ★ 反证：同一条**再传一次** —— 电脑那边不许多出一条（合并幂等）
    await t.pressAction('offline-upload')
    await t.pressAction('modal-ok')
    const again = await t.waitToast('已传到电脑')
    t.has('第二次的合并报告里没有"新增"', again.text, '新增 0')
    t.eq('★ 反证：电脑库里还是只有一条（重复点不重复计数）', await inPc(), 1)
    await t.pressAction('modal-cancel')        // 第二次那个"要不要清空"先留着不清

    // ⑧ 收尾：走「清空（我已导入电脑）」那条路（清之前把后果说清楚）
    await t.pressAction('offline-clear')
    t.has('清空前把后果说清楚', await t.text('#modalTitle'), '清空手机上这')
    await t.pressAction('modal-ok')
    t.ok('清空有回话', (await t.waitToast('队列已清空')).ok)
    t.has('待同步回到 0 条', await t.text('#offlineStatus'), '待同步 0 条')
    t.eq('★ 反证：清队列不会把电脑上那条也清掉', await inPc(), 1)
  },
})

flow({
  id: '㉘', name: '跨端专注镜像：两个真客户端同开 —— 对面开始/结束都看得到，这面一个按钮都没有',
  item: 'A 批 ㉘ 跨端专注镜像（双窗口版）',
  vp: 'desktop',
  async run(t) {
    const serverPort = Number(new URL(t.url).port)
    let peer = null
    try {
      await t.start('focus')
      const m0 = (await t.api('GET', '/api/focus/today')).json.focus_minutes

      // ① 第二个**真客户端**：独立浏览器 + 独立 profile（所以它有自己的 `tf_client`）
      peer = await Cdp.attach(findBrowser(), serverPort + 4, join(TEMP_DIR, `tf-flow-peer-${serverPort}`))
      t.ok('（准备）第二个真客户端起来了（独立浏览器 / 独立 profile）', Boolean(peer))
      if (!peer) return
      const t2 = new T(peer, t.url, 'desktop')
      await t2.start('focus')
      t2.has('第二台上：现在什么都没在跑', await t2.bodyText(), '不绑定任务')
      // 镜像的判据就是"这台的 device_id 不是我" —— 两台要是同一个号，这条流什么都验不到
      const meA = await t.cdp.eval('clientId()')
      const meB = await t2.cdp.eval('clientId()')
      t.ok('（准备）两台是两个**不同的**客户端', Boolean(meA) && Boolean(meB) && meA !== meB, `${meA} vs ${meB}`)

      // ② 这一台开始专注 → 另一台**不用点任何东西**、在 10 秒那一档轮询里自己看到镜像
      const t0 = Date.now()
      await t.pressAction('focus-start', { text: '普通计时' })
      t.has('本机开始计时（右栏是真计时器，带结束按钮）', await t.text('#focusRail'), '结束（计入投入）')
      const seen = await t2.waitFor(async () => ((await t2.text('#focusRail')) || '').includes('别处正在专注'), 14000, 200)
      const waitMs = Date.now() - t0
      t.ok('★ 另一台不用点任何东西就看到「别处正在专注」', seen, `等了 ${waitMs}ms`)
      t.ok('★ 而且是 10 秒那一档轮询该有的时间（≤12.5s）', waitMs <= 12500, `实测 ${waitMs}ms`)
      const mirror = await t2.text('#focusRail')
      t.has('镜像里写了这是哪来的', mirror, '来自另一台设备')
      t.has('★ 也写了"只看不动"', mirror, '只看不动')
      t.eq('镜像走的是**另一个**钟（#clockPeer），不是本机那支计时器', await t2.count('#clockPeer'), 1)
      t.eq('★ 反证：镜像上一个按钮都没有', await t2.count('#focusRail button'), 0)
      t.eq('★ 反证：也一个 data-action 都没有（不能停对面的、也没有"我也开始"）',
        await t2.count('#focusRail [data-action]'), 0)

      // ③ 这一台结束 → 另一台 10 秒内变回"没有进行中的专注"
      const t1 = Date.now()
      await t.pressAction('focus-finish', { text: '结束（计入投入）' })
      const gone = await t2.waitFor(async () => !(((await t2.text('#focusRail')) || '').includes('别处正在专注')), 14000, 200)
      const waitMs2 = Date.now() - t1
      t.ok('★ 这一台结束后，另一台 10 秒内不再显示镜像', gone, `等了 ${waitMs2}ms`)
      t.ok('★ 也是 10 秒那一档该有的时间（≤12.5s）', waitMs2 <= 12500, `实测 ${waitMs2}ms`)
      t.has('另一台回到"当前没有进行中的专注"那一屏', await t2.text('#focusRail'), '当前没有进行中的专注')

      // ④ ★ 反证：这段时间**只记了一笔**投入（镜像那台不会自己也记一笔）
      const secs = Math.round((t1 - t0) / 1000)
      const m1 = (await t.api('GET', '/api/focus/today')).json.focus_minutes
      const grew = Math.round((m1 - m0) * 60)
      // ★ 标签里**不许写测量值**（T-G76）：指纹比的就是"每条流 × 每条断言的标签 + 通过与否"，
      //   秒数写进标签 → 两遍差一点就报"工具不可靠"（T-G73 那次没红纯属凑巧两遍一样）。
      //   数字搬进 detail —— 它给人看，但不进指纹。
      t.ok('★ 今日专注分钟只涨了一次的量', grew >= secs - 4 && grew <= secs + 4,
        `涨了 ${grew}s，会话 ${secs}s —— 翻倍会明显超出去`)
    } finally {
      peer?.close()
    }
  },
})

/* ⑪ 备份与恢复（B 批里最后一条"要动真数据"的人工项）：**在临时库上**把恢复这条路真走一遍。
 *
 * 为什么这一条必须设计走法（T-G73 当时就是卡在这儿没搬）：恢复是**不可逆**动作，而备份就落在
 * **库文件旁边**（`<库名>.bak-<时间戳>`，见 `storage/backup.py`）。这一层起服务用的是
 * `serve.py --fresh` —— 库在 `%TEMP%/timeflow_fresh_*` 里，**它的备份也在那儿**：真实库与
 * 真实备份目录一个字节都不会被碰（这一条本身也有断言，不是口头保证）。
 *
 * 一条流里没法重启服务去触发"启动前自动备份"，所以这份备份由流自己按**产品的命名规则**放一个
 * —— 于是这一条验的是**恢复那条不可逆的路**：列表认不认得它、确认框有没有写清哪个时间点、
 * 取消会不会动库、恢复有没有真把数据带回那一刻、恢复前的现库有没有留退路、**再点回去能不能回来**。
 * `make_backup` 本身由 `tests/test_backup_restore_line.py`（14 条）盯着，这里不重复。
 */
flow({
  id: '⑪', name: '备份与恢复：数据真回到那一刻、恢复前的现库也留一份、再点回去能回来、取消不动库',
  item: 'B 批 ⑪ 备份与恢复',
  vp: 'desktop',
  async run(t) {
    const TITLE = '恢复之后不该还在的任务'
    // ① 设置页 →「备份与恢复」：先看清这一轮跑在哪儿（临时库）
    await t.start('setting')
    await t.openSetting('set-backup')
    const info = (await t.api('GET', '/api/settings/backups')).json || {}
    const dir = String(info.dir || ''), dbName = String(info.db || '')
    t.ok('（准备）这一轮跑在**临时库**上（真实备份目录不会被碰）',
      dir.includes('timeflow_fresh_') && !dir.startsWith(ROOT), `dir=${dir}`)
    const dbPath = join(dir, dbName)
    t.ok('（准备）库文件真在磁盘上', dbName.endsWith('.db') && existsSync(dbPath), dbPath)

    // ② 按产品的命名规则放一份"旧备份"（时间戳取 1 分钟前 → 它排在最新那份之后）
    const d0 = new Date(Date.now() - 60000)
    const stamp = stampOf(d0)
    const bakName = `${dbName}.bak-${stamp}`
    copyFileSync(dbPath, join(dir, bakName))
    await t.view('setting'); await t.openSetting('set-backup')
    const bakSel = `[data-action="restore-backup"][data-name="${bakName}"]`
    t.eq('★ 这份备份出现在列表里', await t.count(bakSel), 1)
    const bakLabel = String((await t.text(bakSel)) || '')
    t.ok('★ 界面把它当**正常备份**（时间戳解析得出来，没被标"名字被改过"）',
      bakLabel.length > 0 && !bakLabel.includes('名字被改过'), bakLabel)

    // ③ 改点东西 —— 恢复之后它必须不见
    await t.view('tasks')
    await t.type('#allTitle', TITLE)
    await t.pressAction('task-add-here')
    t.has('（准备）新加的任务在列表里', await t.bodyText(), TITLE)
    const nBefore = (((await t.api('GET', '/api/settings/backups')).json || {}).items || []).length

    // ④ 点它 → 二次确认（写清恢复到哪个时间点）→ **先按 Esc 取消**
    await t.view('setting'); await t.openSetting('set-backup')
    await t.pressAction('restore-backup', { text: labelOf(d0) })
    const title = String((await t.text('#modalTitle')) || '')
    t.has('★ 确认框写清恢复到**哪个时间点**', title, stamp)
    t.has('★ 写清恢复范围（连设置一起）（T-G142）', title, '连设置一起')
    t.lacks('解释句不许回来（T-G142）', title, '选错了还能回去')
    await t.key('Escape')
    t.eq('★ 反证：取消之后没有多出备份（它一步都没走）',
      (((await t.api('GET', '/api/settings/backups')).json || {}).items || []).length, nBefore)
    await t.view('tasks')
    t.has('★ 反证：取消之后那条任务还在', await t.bodyText(), TITLE)

    // ⑤ 再来一次，这次确认 → 数据真的回到那一刻
    await t.view('setting'); await t.openSetting('set-backup')
    await t.pressAction('restore-backup', { text: labelOf(d0) })
    await t.pressAction('modal-ok')
    const done = await t.waitToast('已恢复')
    t.has('★ 回话里说清恢复了哪一份', done.text, bakName)
    t.has('★ 也说清"恢复前的现库也留了一份"', done.text, '留了一份')
    await t.view('tasks')
    t.ok('★ 数据真的回到那一刻（那条后来才加的任务不在了）',
      !(await t.bodyText()).includes(TITLE), '库应回到备份那一刻的样子')
    const items = ((await t.api('GET', '/api/settings/backups')).json || {}).items || []
    t.eq('★ 恢复前自动又备份了一份现库（多出一条）', items.length, nBefore + 1)
    const safety = items.filter((x) => x.name !== bakName)[0]
    t.ok('（准备）认出那份"恢复前的现库"', Boolean(safety), JSON.stringify(items.map((x) => x.name)))

    // ⑥ ★ 可逆：点那份 safety → 数据回来（"选错了还能回去"不是一句空话）
    await t.view('setting'); await t.openSetting('set-backup')
    await t.pressAction('restore-backup', { text: String(safety.at).replace('T', ' ') })
    await t.pressAction('modal-ok')
    t.ok('回话里有恢复成功那几个字', (await t.waitToast('已恢复')).ok)
    await t.view('tasks')
    t.has('★ 点回去 → 那条任务又回来了（可逆）', await t.bodyText(), TITLE)

    // ⑦ 收尾：再恢复那份旧备份一次 —— 世界回到这一遍开始时的样子（这条路也可以重复走）
    await t.view('setting'); await t.openSetting('set-backup')
    await t.pressAction('restore-backup', { text: labelOf(d0) })
    await t.pressAction('modal-ok')
    t.ok('同一条路可以再走一次', (await t.waitToast('已恢复')).ok)
    await t.view('tasks')
    t.ok('★ 收尾：库里没有留下这条任务（不污染后面那些流）',
      !(await t.bodyText()).includes(TITLE), '这条流自己造的数据要自己收干净')
  },
})

/* M 今天清单的拖拽排序（T-G79）—— 用户 2026-09-25 在两张预演图上选了 **B（真拖拽）**。
 *
 * 这一条与别条不同的地方：它按下去的是**鼠标**，中间**分十步移动**，再松开 —— 走的就是
 * Chromium 把鼠标合成成 pointer 事件那条真路（`pointerdown/move/up`）。
 * 三条判据：
 *   ① **顺序真的变了**（界面上那三张卡的先后按 DOM 读出来）；
 *   ② ★ **落库了**（刷新一次还是那个顺序 —— 这是"真拖拽"与"前端自己排一排"的分界线）；
 *   ③ ↑↓ 是**等价入口**（键盘/读屏那条路），落到同一份序号上。
 */
flow({
  id: 'M', name: '今天清单拖拽排序：真按住拖 → 顺序变了、刷新还在、↑↓ 也能调',
  item: '新增（不是搬移项）：T-G79 今天清单的拖拽排序（用户 2026-09-25 在预演图上选的 B 真拖拽）',
  vp: 'desktop',
  async run(t) {
    const A = '拖拽甲', B = '拖拽乙', C = '拖拽丙'
    const mine = [A, B, C]
    // ① 三张我有把握的卡（判据要能一眼看出"谁在前"）。
    //    为什么中间 sleep 一秒多：`created_at` 只到**秒**，同一秒建的三条谁在前是不确定的 ——
    //    那会让"拖之前是这个顺序"这条断言变成看运气（判据不许建在"同秒的任意顺序"上）。
    const ids = {}
    for (const title of mine) {
      const made = await t.api('POST', '/api/tasks', { title, is_myday: true })
      t.ok(`（准备）建了「${title}」并放进今天`, made.status === 200, JSON.stringify(made).slice(0, 120))
      ids[title] = made.json && made.json.id
      await sleep(1100)
    }
    await t.start('today')
    await t.view('today')
    const orderOf = () => t.cdp.eval(`(() => {
      const want = ${JSON.stringify(mine)};
      return [...document.querySelectorAll('#mydayList .card')]
        .map((c) => ((c.querySelector('.title') || {}).textContent || '').trim())
        .filter((x) => want.some((w) => x.includes(w))); })()`)
    t.eq('（准备）三张卡按创建顺序排在今天清单里', JSON.stringify(await orderOf()),
      JSON.stringify([A, B, C]))

    // ② 只读的几件：抓手是"按住拖"的手势区（不是按钮、也不占 Tab），↑↓ 在卡片正文里
    t.ok('★ 今天清单的卡都带拖拽抓手', await t.count('#mydayList [data-drag="myday"]') >= 3,
      `实测 ${await t.count('#mydayList [data-drag="myday"]')} 个`)
    t.eq('★ 抓手不是按钮（不混进"卡上动作"那笔账、也不占 Tab）',
      await t.count('#mydayList button[data-drag]'), 0)
    t.eq('★ 卡片本身不能拖（只能按住抓手拖 —— 不然点标题也会被当成拖）',
      await t.count('#mydayList .card[data-drag]'), 0)
    const rowBtns = await t.cdp.eval(`(() => { const c = document.querySelector('#mydayList .card');
      return c ? [...c.querySelectorAll(':scope > .row > button')].length : -1 })()`)
    t.ok('★ 卡片外层动作行没被撑大（↑↓ 在正文里，不在动作行）', rowBtns >= 1 && rowBtns <= 3,
      `实测 ${rowBtns} 个`)
    t.has('★ 卡上写着它在第几位（顺序是数据，界面得说清）', await t.text('#mydayList'), '第 ')

    // ③ ★ 真拖：按住「丙」的抓手（按**任务 id** 找，不靠"第几张"），拖到「甲」的上半边 → 松手。
    //    先把整列滚到视口顶：拖拽要求起点与落点**同时在视口里**（工具会当场判，不然报"在视口外"）。
    await t.cdp.eval("(() => { const el = document.getElementById('mydayList');" +
      " if (el) el.scrollIntoView({ block: 'start' }); return true })()")
    const dragged = await t.drag(`#mydayList [data-drag="myday"][data-id="${ids[C]}"]`,
      `#mydayList .card[data-myday-id="${ids[A]}"]`, { frac: 0.3 })
    if (!dragged) return
    t.eq('★ 拖完顺序变了（丙跑到最前）', JSON.stringify(await orderOf()), JSON.stringify([C, A, B]))

    // ④ ★ 顺序是**数据**：刷新一次还在（前端自己排的那种会在这里打回原样）
    await t.reload()
    await t.view('today')
    t.eq('★ 刷新之后还是那个顺序（落库了）', JSON.stringify(await orderOf()), JSON.stringify([C, A, B]))
    const served = (await t.api('GET', '/api/tasks')).json.filter((x) => mine.includes(x.title))
    t.ok('★ 库里也带着序号（不是只有界面记得）',
      served.length === 3 && served.every((x) => typeof x.myday_rank === 'number'),
      JSON.stringify(served.map((x) => [x.title, x.myday_rank])))

    // ⑤ 键盘那条路：最后一张按 ↑ 往上挪一位（与拖拽落到同一份序号上）
    await t.pressAction('myday-move', { inCard: B })
    t.eq('★ ↑↓ 与拖拽落在同一份序号上', JSON.stringify(await orderOf()), JSON.stringify([C, B, A]))
  },
})

/* ------------------------------------------------ 正向对账（卡 159 · T-G259 · INV-76）
 * 人工验收清单里每个**非物理 / 非口味**项，要么被某条流的 `item` 指到（机器搬走了），
 * 要么写明「机器判不了 / 机器已验到哪」的理由 —— 两样都没有 = 一条没人认账的验收项，
 * 它会无限期停在「人看一眼」或被悄悄丢掉。判据只吃清单本身 + FLOWS 的 item 列，
 * `--doc <路径>` 可换清单（自检喂合成坏样例用），**不起浏览器**。 */

const REASON_MARKERS = [
  // 「机器判不了 / 剩哪眼给人」的理由
  '机器判不了', '机器验不了', '机器不许碰', '机器碰不了', '机器动不了',
  '人的观感', '是人读', '是人看', '要人读', '要人看', '人读出来', '人的判断',
  '留给人工', '没搬给机器', '只有人能', '需人点', '没验过', '没人点过', '没人看过',
  '无门禁', '无判据', '环境差异',
  // 「机器已验到哪」的记账（有机器判据的行也算对过账，不是黑洞）
  '机器已经', '机器搬走', '机器只能', '机器判据', '你不用点', '渲染黄金', '对比度门',
  '每轮门禁', '每轮比对', '零命中',
]

function classifySection(name) {
  if (name.includes('物理') || name.includes('机器动不了')) return 'physical'
  if (name.includes('口味')) return 'taste'
  return 'functional'
}

/** 解析人工验收清单：回 `{ physical, taste, items }`；
 *  `items` 是功能项（非物理 / 非口味）的表格行 `{ id, row, flowCovered, reasoned }`。 */
function parseManualDoc(text, flowItems) {
  const stat = { physical: 0, taste: 0, items: [] }
  let kind = 'functional'
  for (const line of text.split(/\r?\n/)) {
    const h = line.match(/^##\s+(.*)$/)
    if (h) { kind = classifySection(h[1]); continue }
    if (kind === 'physical') { if (/^\|\s*\*\*/.test(line)) stat.physical += 1; continue }
    if (kind === 'taste') { if (/^\|\s*\*\*/.test(line)) stat.taste += 1; continue }
    if (!line.startsWith('|')) continue
    const m = line.match(/^\|\s*\*\*(.+?)\*\*/)
    if (!m) continue
    const id = m[1].replace(/<br>.*$/, '').trim()
    if (!id || id === '#') continue
    stat.items.push({
      id,
      row: line.trim().slice(0, 160),
      flowCovered: flowItems.some((it) => it.includes(id)),
      reasoned: REASON_MARKERS.some((k) => line.includes(k)),
    })
  }
  return stat
}

function coverageReport(docPath) {
  const path = docPath || MANUAL_DOC
  if (!existsSync(path)) {
    console.log(`❌ 找不到人工验收清单：${path}`)
    return 2
  }
  const text = readFileSync(path, 'utf8')
  const flowItems = FLOWS.map((f) => f.item)
  const stat = parseManualDoc(text, flowItems)
  const unclaimed = stat.items.filter((x) => !x.flowCovered && !x.reasoned)
  console.log('=== 正向对账：人工验收清单 ↔ 行为流（卡 159 / T-G259）===')
  console.log(`  清单：${path}`)
  console.log(`  物理场景 ${stat.physical} 条 · 口味判断 ${stat.taste} 条（机器不动，豁免）`)
  console.log(`  功能项 ${stat.items.length} 条：流覆盖 ${stat.items.filter((x) => x.flowCovered).length}`
    + ` · 写明机器判不了/已验到哪 ${stat.items.filter((x) => x.reasoned).length}`
    + ` · 未对账 ${unclaimed.length}`)
  if (unclaimed.length) {
    console.log('\n❌ 未对账的功能项（既没有被某条流的 item 指到、也没写明机器判不了的理由）：')
    for (const x of unclaimed) console.log(`  · ${x.id} —— ${x.row}`)
    console.log('  补法：给这条流加 `item` 指到它，或在清单该行末列写明机器判不了的理由。')
    return 1
  }
  console.log('\n正向对账通过 ✅ 每个功能项都有去处（流覆盖或写明理由）')
  return 0
}

const MANUAL_DOC = join(ROOT, 'docs', '人工验收-照着点.md')

/* ---------------------------------------------------------------- 跑 */

function fingerprint(results) {

  return JSON.stringify(results.map((r) => [r.id, r.error ?? '', r.checks.map((c) => [c.label, c.ok])]))
}

async function runPass(pass, browserPath, resultsOut) {
  const serverPort = ARGS.port + 2 * (pass - 1)
  const cdpPort = serverPort + 1
  const url = `http://127.0.0.1:${serverPort}/`
  const profileDir = join(process.env.TEMP ?? '/tmp', `tf-flow-profile-${serverPort}`)
  // ★ 判据 3（卡 E73）：同 `render_check.mjs` —— 起服务前先探端口，占着就点名退出，不 seed 别人的库。
  const busy = await portBusyReason(serverPort)
  if (busy) return { code: 2, note: `端口 ${serverPort} 已被占用（可能是并行的另一条门）：${busy}` }
  const server = startServer(serverPort)
  let cdp = null
  try {
    if (!(await waitHealth(serverPort))) {
      return { code: 2, note: '起不了后端服务：' + server.dump().slice(-400) }
    }
    const problems = await seedFixture(serverPort)
    if (problems.length) return { code: 2, note: 'fixture 没造全：' + problems.join(' / ') }
    try {
      const cfg = await (await fetch(`http://127.0.0.1:${serverPort}/api/config`)).json()
      CFG_ACCENT = cfg && typeof cfg.accent_color === 'string' && cfg.accent_color ? cfg.accent_color : null
    } catch { CFG_ACCENT = null }
    cdp = await Cdp.attach(browserPath, cdpPort, profileDir)
    if (!cdp) return { code: 3, note: '浏览器起来了但 CDP 端点连不上' }

    const todo = selectedFlows()
    for (const f of todo) {
      const t = new T(cdp, url, f.vp)
      let error = null
      const t0 = Date.now()
      try {
        await f.run(t)
      } catch (e) {
        error = String(e && e.message ? e.message : e)
      }
      const failed = t.checks.filter((c) => !c.ok)
      const rec = {
        id: f.id, name: f.name, item: f.item, checks: t.checks, error,
        seconds: Number(((Date.now() - t0) / 1000).toFixed(1)),
      }
      resultsOut.push(rec)
      if (error || failed.length) {
        console.log(`[FAIL] ${f.id} ${f.name}  （替 ${f.item}）`)
        if (error) console.log(`       · 跑不下去：${error}`)
        for (const c of failed) console.log(`       · ${c.label}${c.detail ? ' —— ' + c.detail : ''}`)
        if (ARGS.shots) await t.shot(`${pass}-${f.id}`)
      } else {
        console.log(`[OK ] ${f.id} ${f.name}  ${t.checks.length} 项断言  ${rec.seconds}s`)
      }
    }
    return { code: 0 }
  } finally {
    cdp?.close()
    if (!ARGS.keep) { try { server.child.kill() } catch { /* ignore */ } }
  }
}

async function main() {
  const t0 = Date.now()
  const result = { ok: false, code: 1, flows: 0, failed: [], notRun: false, notes: [], fuzzy: false }

  if (ARGS.list) {
    for (const f of FLOWS) console.log(`${f.id}\t${f.name}\t← ${f.item}`)
    return { ...result, code: 0, ok: true }
  }

  // ★ 正向对账（卡 159 / T-G259）：不起浏览器，只对清单与流的 item 列
  if (ARGS.coverage) {
    const code = coverageReport(ARGS.doc || null)
    return { ...result, code, ok: code === 0 }
  }

  const browserPath = findBrowser()
  if (!browserPath) {
    log('[NOT RUN] 找不到真浏览器（Edge/Chrome/Chromium）。这一层**没有验证**，不算通过。')
    log('          可用 TF_CHROME=<路径> 指定。')
    return { ...result, notRun: true, code: 3 }
  }

  // `--only` 写错一个字就一条都不跑 —— 那时**必须报错**，不能报"0 条流通过"：
  // 空集永远满足"所有流都通过"，这种绿灯是假的（比红更坏）。
  if (ARGS.only && selectedFlows().length === 0) {
    console.log(`❌ --only「${ARGS.only}」一条流都没匹配上。现有这些：`)
    for (const f of FLOWS) console.log(`   · ${f.id} ${f.name}`)
    return { ...result, code: 1, notes: ['--only 没匹配到任何流'] }
  }

  // ★ 最小验证法则（T-G38）：**默认一遍**。`--twice` 是"改这套流本身"时的按需工具 ——
  //   流失败只是红一下，不会污染任何持久数据；而黄金层的两遍自检是常开的（那里抖一次就会被写进黄金）。
  const passes = ARGS.twice && !ARGS.only ? 2 : 1
  // 卡 E135 判据 4：生效的预算必须**自报**，不许悄悄变宽。不设 env（倍数 = 1）时一个字都不打 ——
  // 默认输出零变化，否则黄金层 / 指纹类判据会被这行噪声碰。
  const budgetScale = waitScale()
  if (budgetScale !== 1) {
    log(`[note] 等待预算 ×${budgetScale}（TF_UI_FLOW_WAIT_SCALE）—— 判据强度不变，只是等得更久`)
  }
  log(`=== 行为流层：真浏览器 ${browserPath.split(/[\\/]/).pop()}，${FLOWS.length} 条流，跑 ${passes} 遍 ===`)
  if (passes === 1) {
    log('[note] 只跑了一遍（最小验证法则）—— 这一轮**没有**做"两遍指纹"自检；')
    log('       改这套流本身时用 `--twice` 开一次。黄金层那边的两遍自检是常开的（那里抖一次会写进黄金）。')
  }
  const prints = []
  let last = []
  for (let pass = 1; pass <= passes; pass++) {
    if (passes > 1) log(`\n--- 第 ${pass} 遍（新库 + 新浏览器）---`)
    const out = []
    const r = await runPass(pass, browserPath, out)
    if (r.code !== 0) {
      console.log(`❌ ${r.note}`)
      result.notes.push(r.note)
      return { ...result, code: r.code, notRun: r.code === 3 }
    }
    prints.push(fingerprint(out))
    last = out
    result.flows = out.length
  }

  const failed = last.filter((r) => r.error || r.checks.some((c) => !c.ok))
  result.failed = failed.map((f) => f.id)

  if (passes > 1 && prints[0] !== prints[1]) {
    console.log('\n❌ 两遍的断言指纹不一致 —— 这是**工具的**问题（时序/状态没钉住），不是"界面变了"。')
    console.log('   先修工具（把会自己变的东西钉住），别改界面。')
    const a = last
    for (const rec of a) {
      const other = JSON.parse(prints[0]).find((x) => x[0] === rec.id)
      const mine = rec.checks.map((c) => [c.label, c.ok])
      if (other && JSON.stringify(other[2]) !== JSON.stringify(mine)) {
        const badA = other[2].filter((x) => !x[1])
        const badB = mine.filter((x) => !x[1])
        if (badA.length || badB.length) {
          console.log(`   · ${rec.id} 两遍结果不同：第一遍 ${JSON.stringify(badA)} / ` +
            `第二遍 ${JSON.stringify(badB)}`)
        } else {
          // ★ 两遍都全绿却指纹不同 → 差在**断言清单本身**（条数/顺序/标签），不在通过与否。
          //   旧写法这时只会印「第一遍 [] / 第二遍 []」，等于什么都不说（T-G76 撞到）。
          const la = other[2].map((x) => x[0])
          const lb = mine.map((x) => x[0])
          console.log(`   · ${rec.id} 两遍**断言清单**不同（两边都全绿）：` +
            `第一遍 ${la.length} 条 / 第二遍 ${lb.length} 条；` +
            `只在第一遍：${JSON.stringify(la.filter((x) => !lb.includes(x)))}；` +
            `只在第二遍：${JSON.stringify(lb.filter((x) => !la.includes(x)))}`)
        }
      }
    }
    result.fuzzy = true
    return { ...result, code: 4 }
  }
  if (passes > 1) log(`\n[OK ] 确定性自检：两遍断言指纹一致（${result.flows} 条流）`)

  if (failed.length) {
    console.log(`\n❌ 行为流有失败：${failed.length}/${result.flows} 条`)
    console.log('   （失败项在上面每一条的 · 后面；`--only <名字>` 可以单独重跑一条）')
    result.code = 1
    return result
  }

  const total = last.reduce((s, r) => s + r.checks.length, 0)
  log(`\n行为流层通过 ✅ ${result.flows} 条流 / ${total} 项断言（替掉了 ${last.length} 条人工确认项）`)
  log(`[耗时] ${((Date.now() - t0) / 1000).toFixed(1)}s`)
  return { ...result, ok: true, code: 0 }
}

const res = await main()
if (ARGS.json) {
  console.log(JSON.stringify({
    ok: res.ok, code: res.code, flows: res.flows, failed: res.failed,
    not_run: res.notRun, fuzzy: res.fuzzy, notes: res.notes,
  }, null, 2))
}
process.exit(res.code)
