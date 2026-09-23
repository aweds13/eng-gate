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
 * 三条纪律（跟黄金层同一套道理，一条都不能少）：
 *   ① 每条流都**声明它替掉哪一条人工项**（打印出来 + 测试钉住），"搬走了哪几条"有据可查；
 *   ② 每轮默认**跑两遍**（各自新库 + 新浏览器），两遍的断言指纹必须一致 ——
 *      不一致 = **这个工具自己不可信**（退出码 4），不当成"界面坏了"；
 *   ③ 真点击做**命中测试**（`elementFromPoint`）：被浮层盖住、被挤出视口的按钮，
 *      `el.click()` 会"成功"，而用户点不到 —— 所以这里一律真按坐标，且先验"那个点上是不是它"。
 *
 * 已知边界（**不谎报**）：
 *   · 起不了浏览器 → 退出码 3（NOT RUN），**NOT RUN 不是 PASS**（`run_gates.py` 单列一栏）。
 *   · 它只验"行为对不对"，**不验好看**，也**不验口味**（文案好不好、版式美不美）。
 *   · 要人工准备的物理场景（两台设备 / 手机连热点 / 校园网隔离 / 计划任务）它做不了，仍在人工那一栏。
 *
 * 用法
 *     node tools/ui_flow_check.mjs                 # 跑全部（两遍，含确定性自检）
 *     node tools/ui_flow_check.mjs --once          # 只跑一遍（调试用；**没有**确定性自检）
 *     node tools/ui_flow_check.mjs --only 新手引导  # 只跑名字/编号里含这几个字的那条
 *     node tools/ui_flow_check.mjs --list          # 列出所有流与它们替掉的人工项
 *     node tools/ui_flow_check.mjs --json          # 机器可读结果
 *     node tools/ui_flow_check.mjs --port 8541 --keep   # 换端口 / 跑完不杀服务
 *
 * 退出码：0 全通过 / 1 有流失败 / 2 fixture（种子数据）坏了 / 3 起不了真浏览器（NOT RUN）/
 *         4 两遍断言指纹不一致（工具自己不可信）。
 */
import { existsSync, mkdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { setTimeout as sleep } from 'node:timers/promises'

import {
  Cdp, EXPORT_DIR, MUTATION_WATCH, ROOT, VIEWPORTS, VIEWS,
  bootApp, findBrowser, iso, seedFixture, setViewport, startServer, waitApp, waitHealth, waitQuiet,
} from './tf_browser.mjs'

const SHOTS_DIR = join(ROOT, 'gates', 'render', 'shots')  // 证据与黄金层放一起（同样不进仓库）

/* ---------------------------------------------------------------- 参数 */

function parseArgs(argv) {
  const a = { json: false, keep: false, once: false, quiet: false, list: false, port: 8541, only: '' }
  for (let i = 0; i < argv.length; i++) {
    const k = argv[i]
    if (k === '--json') a.json = true
    else if (k === '--keep') a.keep = true
    else if (k === '--once') a.once = true
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
    await waitQuiet(this.cdp)
  }

  /** 装"页面还在动吗"的计数器。**每次导航之后都要重装**（页面上下文是新的）。 */
  async arm() { await this.cdp.eval(MUTATION_WATCH) }

  /** 只看不点地重新加载（保留本机状态 —— 验"刷新后还保持着吗"要用它）。 */
  async reload() {
    await this.cdp.navigate(this.url)
    const booted = await waitApp(this.cdp)
    if (!booted) throw new Error('刷新之后应用没起来')
    await this.arm()
    await waitQuiet(this.cdp)
  }

  async view(name, { quiet = true } = {}) {
    const m = await this.mark(`[data-view="${name}"]`)
    if (!m.ok) throw new Error(`界面上找不到视图 ${name} 的入口`)
    await this.press(HIT, `视图 ${name}`, { quiet })
    if (quiet) await waitQuiet(this.cdp)
    else await this.settle()
  }

  /** 只等**这一屏画出来**（`#main` 连续 3 拍不变，≈0.6s），不等整页安静（那要 ~0.7s+）。
   *  给"扫文本"这类用途：它不需要"整页不再变"的强保证，代价是**更晚才到的东西会漏** ——
   *  所以取 3 拍而不是 1 拍。真正验行为的那几条流一律用默认的 `waitQuiet`。 */
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
    if (quiet) await waitQuiet(this.cdp)
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
    await waitQuiet(this.cdp)
    return true
  }

  async key(name) { await this.cdp.key(name); await waitQuiet(this.cdp) }

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

  ls(key) { return this.cdp.eval(`(() => { try { return localStorage.getItem(${JSON.stringify(key)}) } catch (e) { return null } })()`) }

  /** 右下角提示条的**当前**文字（没显示时返回空串 —— 过场提示本来就会自己消失）。 */
  toast() {
    return this.cdp.eval(`(() => { const t = document.getElementById('toast');
      return t && t.classList.contains('show') ? (t.innerText || '').replace(/\\s+/g, ' ').trim() : '' })()`)
  }

  /** 等提示条里出现某句话（操作是异步的：点了之后要等后端回话）。 */
  async waitToast(needle, ms = 5000) {
    const t0 = Date.now()
    let last = ''
    while (Date.now() - t0 < ms) {
      last = await this.toast()
      if (last.includes(needle)) return { ok: true, text: last }
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
    await t.type('#guardDnd', '22:00-07:00')
    await t.key('Enter')
    const good = await t.waitToast('已加上勿扰时段：22:00-07:00')
    t.ok('合法时段加上了', good.ok, `提示条里是：${good.text || '（空）'}`)
    t.ok('列表里出现了它', await t.waitFor(async () => (await t.count('[data-action="guard-dnd-del"]')) === 1))
    t.has('列表里写的就是它', await t.text('[data-action="guard-dnd-del"]'), '22:00-07:00')

    // ③ 能删掉（自己收拾干净，不给后面的流留状态）
    await t.pressAction('guard-dnd-del')
    const gone = await t.waitToast('已移除勿扰时段：22:00-07:00')
    t.ok('能删掉', gone.ok, `提示条里是：${gone.text || '（空）'}`)
    t.eq('删完列表空了', await t.count('[data-action="guard-dnd-del"]'), 0)
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
  id: '⑥', name: '统计页「学业投入 vs 自学投入」写明了口径',
  item: '前端批次② ⑥ 统计页「学业投入 vs 自学投入」',
  vp: 'desktop',
  async run(t) {
    await t.start('stats')
    const body = await t.bodyText()
    t.has('有这张图', body, '学业投入 vs 自学投入')
    // 认**唯一属于这张图**的那句话（`未绑定任务的专注另有…`）：另一张卡里也出现"未绑定任务的专注"，
    // 拿它当路标会挑错元素（第一版就挑错了，断言全落在隔壁那张卡上）。
    const m = await t.mark('.sub', { text: '手动投入不参与这张图' })
    if (!t.ok('下面写着这张图的口径', m.ok)) return
    const line = await t.text(HIT)
    t.has('未绑定的「单列」', line, '单列')
    t.has('写明了「手动投入不参与这张图」', line, '手动投入不参与这张图')
    t.has('也说明了不替人下判断', line, '不做「学业该占多少」的建议')
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

  const passes = ARGS.once || ARGS.only ? 1 : 2
  log(`=== 行为流层：真浏览器 ${browserPath.split(/[\\/]/).pop()}，${FLOWS.length} 条流，跑 ${passes} 遍 ===`)
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
