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
 *   ③ **不做"全覆盖"**：够用的条数就停（现在 17 条）。要加一条，得先说明它替掉哪条人工项。
 *
 * 已知边界（**不谎报**）：
 *   · 起不了浏览器 → 退出码 3（NOT RUN），**NOT RUN 不是 PASS**（`run_gates.py` 单列一栏）。
 *   · 它只验"行为对不对"，**不验好看**，也**不验口味**（文案好不好、版式美不美）。
 *   · 要人工准备的物理场景（两台设备 / 手机连热点 / 校园网隔离 / 计划任务）它做不了，仍在人工那一栏。
 *   · ★ "等闲下来" = **DOM 不动 + 手上没有在飞的请求**（`waitIdle`，T-G40）：只等 DOM 会在
 *     "请求还在路上、页面一动不动"那一段提前收工，然后拿**上一个画面**去断言（黄金层就被这么坑过）。
 *
 * 用法
 *     node tools/ui_flow_check.mjs                 # 跑全部（**默认一遍**；见下面"最小验证法则"）
 *     node tools/ui_flow_check.mjs --twice         # 跑两遍并比断言指纹（**按需**：改这套流本身时用）
 *     node tools/ui_flow_check.mjs --only 新手引导  # 只跑名字/编号里含这几个字的那条
 *     node tools/ui_flow_check.mjs --list          # 列出所有流与它们替掉的人工项
 *     node tools/ui_flow_check.mjs --json          # 机器可读结果
 *     node tools/ui_flow_check.mjs --port 8541 --keep   # 换端口 / 跑完不杀服务
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
import { existsSync, mkdirSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { setTimeout as sleep } from 'node:timers/promises'

import {
  Cdp, EXPORT_DIR, FETCH_WATCH, MUTATION_WATCH, ROOT, VIEWPORTS, VIEWS,
  bootApp, findBrowser, iso, seedFixture, setViewport, startServer, waitApp, waitHealth, waitIdle,
} from './tf_browser.mjs'

const SHOTS_DIR = join(ROOT, 'gates', 'render', 'shots')  // 证据与黄金层放一起（同样不进仓库）
const TEMP_DIR = process.env.TEMP ?? process.env.TMP ?? '/tmp'

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
  const a = { json: false, keep: false, twice: false, quiet: false, list: false, port: 8541, only: '' }
  for (let i = 0; i < argv.length; i++) {
    const k = argv[i]
    if (k === '--json') a.json = true
    else if (k === '--keep') a.keep = true
    else if (k === '--twice') a.twice = true
    else if (k === '--quiet') a.quiet = true
    else if (k === '--list') a.list = true
    else if (k === '--shots') a.shots = true
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

  /** 装两个计数器：**页面还在动吗**（`MUTATION_WATCH`）与**还有没有请求在飞**（`FETCH_WATCH`）。
   *  每次导航之后都要重装（页面上下文是新的）；`bootApp` 里也会装一遍（那条路不经过这里）。 */
  async arm() {
    await this.cdp.eval(MUTATION_WATCH)
    await this.cdp.eval(FETCH_WATCH)
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
    const m = await this.mark(`[data-view="${name}"]`)
    if (!m.ok) throw new Error(`界面上找不到视图 ${name} 的入口`)
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
  async press(selector, label = selector, { quiet = true } = {}) {
    const r = await this.cdp.rectOf(selector)
    if (!r) { this.ok(`点得到：${label}`, false, '找不到元素（可能没渲染出来）'); return false }
    if (r.w < 1 || r.h < 1) { this.ok(`点得到：${label}`, false, `元素是 ${r.w}×${r.h}，点不到`); return false }
    const hit = await this.cdp.hitTest(selector, r.cx, r.cy)
    if (!hit.ok) { this.ok(`点得到：${label}（没被别的东西挡住）`, false, hit.why); return false }
    await this.cdp.clickAt(r.cx, r.cy)
    if (quiet) await waitIdle(this.cdp)
    return true
  }

  /** 按 `data-action` 点（界面里所有交互都挂在这张表上，见 T-G31 的命令表）。 */
  async pressAction(name, opts = {}) {
    const m = await this.mark(`[data-action="${name}"]`, opts)
    if (!m.ok) { this.ok(`界面上有这个动作：${name}`, false, `匹配到 ${m.all} 个，可见 ${m.pool} 个`); return false }
    return this.press(HIT, `${name}${opts.text ? `（${opts.text}）` : ''}`)
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

  async key(name) { await this.cdp.key(name); await waitIdle(this.cdp) }

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

  /** 等提示条里出现某句话（操作是异步的：点了之后要等后端回话）。
   *  ★ 失败时回的是**最后一句非空的**提示条，不是"最后一次采样" ——
   *  第一版回最后一次采样，而提示条 2.2 秒后就自己消失了，于是失败信息永远是『（空）』，
   *  看着像"点了没反应"，其实它明明说过一句别的（T-G35 就这么被误导过一次）。 */
  async waitToast(needle, ms = 5000) {
    const t0 = Date.now()
    let last = ''
    while (Date.now() - t0 < ms) {
      const now = await this.toast()
      if (now) last = now
      if (now.includes(needle)) return { ok: true, text: now }
      await sleep(100)
    }
    return { ok: false, text: last }
  }

  /** 等某个条件成立（自带轮询；用在"列表里应当多出一行"这类异步结果上）。 */
  async waitFor(fn, ms = 5000, step = 120) {
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
   *  注意：**能走界面的一律走界面**（那才是这一层要验的东西），这里只补界面做不到的部分。 */
  async api(method, path, body) {
    const res = await fetch(this.url.replace(/\/$/, '') + path, {
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
  id: '⑨', name: '专注白名单/勿扰：能加能删，非法时段被后端拦下并原话透传',
  item: '前端批次③ ⑨ 设置页「专注（白名单/勿扰）」增删条',
  vp: 'desktop',
  async run(t) {
    await t.start('setting')
    t.has('设置页有这一节', await t.bodyText(), '专注（白名单 / 勿扰）')
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
    t.has('并且说清了到期时间排好了', created.text, '到期时间由 FSRS 排好')
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
    t.has('没有把已录成绩的算进来（说明里写着未录成绩）', body, '未录成绩')
  },
})

flow({
  id: '⑬', name: '导出 Markdown：目录能改，导出今天真的写出文件',
  item: 'G 批 ⑬ 设置页「导出（Markdown）」',
  vp: 'desktop',
  async run(t) {
    await t.start('setting')
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
      await t.view(v, { quiet: false })
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

/* ---------------------------------------------------------------- 跑 */

function fingerprint(results) {
  return JSON.stringify(results.map((r) => [r.id, r.error ?? '', r.checks.map((c) => [c.label, c.ok])]))
}

async function runPass(pass, browserPath, resultsOut) {
  const serverPort = ARGS.port + 2 * (pass - 1)
  const cdpPort = serverPort + 1
  const url = `http://127.0.0.1:${serverPort}/`
  const profileDir = join(process.env.TEMP ?? '/tmp', `tf-flow-profile-${serverPort}`)
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
        console.log(`   · ${rec.id} 两遍结果不同：第一遍 ${JSON.stringify(other[2].filter((x) => !x[1]))} / ` +
          `第二遍 ${JSON.stringify(mine.filter((x) => !x[1]))}`)
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
