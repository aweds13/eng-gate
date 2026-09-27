/* 暗色探针（T-G163 · **只读**）：对指定视图，分别在亮色 / 暗色下渲染一遍，逐元素读
 * `background-color` / `color` / `border-*-color` 的计算值，输出两张判据表：
 *
 *   A「没跟着主题变」：暗色下的值**逐字节等于**亮色下的值，且该值不在白名单里
 *     （白名单：transparent / rgba(0,0,0,0) / inherit / --accent-1..6 六个强调色预设 ——
 *     它们本来就两主题同值）。
 *   B「对比度不足」：文字色 vs 它最近的不透明祖先背景的对比度 < 4.5（正文）/
 *     < 3.0（≥18px 或次要语义 = 文字色即当前主题 `--muted` 值的那一类）。
 *
 * 它**不改**任何产品代码、**不写**任何文件 —— 只打印。它也不是门禁：
 * 门禁判据在 `ui_flow_check.mjs` 的暗色流（同卡 §2.3-A），这里只负责把问题照出来。
 *
 * 为什么不猜「哪几屏不适配」：亮色黄金 45 份里没有 dark 变体、ui_flow 也不切主题，
 * 暗色此前**零机器判据** —— 先造这个探针拿到现场证据，再动手修（先量再改）。
 *
 * 视图名（与 `tools/tf_browser.mjs` 的 `VIEWS` 对齐，别猜）：
 *   habit   = 习惯页（用户说的「每日反馈（计划 vs 执行）」区块就在这一页里，index.html:2744）
 *   planned = 「有计划」（用户口语里的「计划」）
 *   review  = 复习（用户口语里的「复盘」）
 *
 * 用法
 *     node tools/dark_probe.mjs                            # 默认 habit,planned,review
 *     node tools/dark_probe.mjs --view habit,planned,review
 *     node tools/dark_probe.mjs --view today --port 8961   # 调试：换视图 / 端口
 *
 * 退出码：0 打印完成（有没有命中都算探针正常收工——它是诊断工具，不是门）/
 *         1 起不来（服务 / fixture / 浏览器）/
 *         2 探针自检失败（切暗色后 `--bg` 的解析值毫无变化 —— 探针自己不可信，读数作废）。
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { setTimeout as sleep } from 'node:timers/promises'

import {
  CAPTURE_DAY, Cdp, ROOT, bootApp, findBrowser, seedFixture, setFixtureDay, setViewport,
  startServer, waitHealth, waitIdle,
} from './tf_browser.mjs'

/* ---------------------------------------------------------------- 参数 */

function parseArgs(argv) {
  const a = { view: 'habit,planned,review', port: 8961, keep: false, json: false }
  for (let i = 0; i < argv.length; i++) {
    const k = argv[i]
    if (k === '--view') a.view = argv[++i] ?? a.view
    else if (k === '--port') a.port = Number(argv[++i])
    else if (k === '--keep') a.keep = true
    else if (k === '--json') a.json = true
    else { console.error(`未知参数：${k}`); process.exit(1) }
  }
  a.views = a.view.split(',').map((s) => s.trim()).filter(Boolean)
  if (!a.views.length) { console.error('--view 是空的'); process.exit(1) }
  return a
}

const ARGS = parseArgs(process.argv.slice(2))
const VIEWS = ARGS.views

/* ---------------------------------------------------------------- 页内采集 */

/** 采一屏所有**可见**元素的样式读数。只读，不改页面。
 *  每行：选择器路径 / 自有文字 / 各颜色属性 / 字号 / 最近的不透明祖先背景。 */
const COLLECT = `(() => {
  const pathOf = (el) => {
    const parts = [];
    for (let e = el; e && e !== document.body; e = e.parentElement) {
      let s = e.tagName.toLowerCase();
      if (e.id) s += '#' + e.id;
      else if (e.classList.length) s += '.' + [...e.classList].slice(0, 2).join('.');
      parts.unshift(s);
      if (e.id) break;
    }
    return parts.join(' > ') || 'body';
  };
  const ownText = (el) => [...el.childNodes]
    .filter((n) => n.nodeType === 3).map((n) => n.textContent.trim()).join(' ')
    .replace(/\\s+/g, ' ').slice(0, 40);
  const alphaOf = (s) => { const m = s.match(/rgba?\\(([^)]+)\\)/); if (!m) return 1;
    const p = m[1].split(',').map((x) => parseFloat(x)); return p.length >= 4 ? p[3] : 1; };
  const effBg = (el) => {
    for (let e = el; e; e = e.parentElement) {
      const bg = getComputedStyle(e).backgroundColor;
      if (alphaOf(bg) > 0) return bg;
    }
    return 'rgb(0,0,0)';
  };
  const out = [];
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1 || !el.getClientRects().length) continue;
    const cs = getComputedStyle(el);
    out.push({
      p: pathOf(el), t: ownText(el),
      bg: cs.backgroundColor, fg: cs.color,
      bt: cs.borderTopColor, br: cs.borderRightColor, bb: cs.borderBottomColor, bl: cs.borderLeftColor,
      fs: cs.fontSize, ebg: effBg(el),
    });
  }
  const root = getComputedStyle(document.documentElement);
  const tokens = {};
  for (const name of ['--bg', '--panel', '--panel-2', '--ink', '--muted', '--border', '--border-strong',
    '--border-control', '--accent', '--accent-1', '--accent-2', '--accent-3', '--accent-4',
    '--accent-5', '--accent-6', '--danger', '--ok', '--toast-bg', '--toast-ink', '--danger-weak']) {
    tokens[name] = root.getPropertyValue(name).trim();
  }
  return { rows: out, tokens, bodyBg: getComputedStyle(document.body).backgroundColor };
})()`

/* ---------------------------------------------------------------- 判据（Node 侧） */

const norm = (s) => String(s ?? '').replace(/\s+/g, '').toLowerCase()

function parseRgb(s) {
  const m = String(s ?? '').match(/rgba?\(([^)]+)\)/)
  if (!m) return null
  const p = m[1].split(',').map((x) => parseFloat(x))
  if (p.length >= 4 && p[3] === 0) return null
  return p.slice(0, 3)
}
function lum([r, g, b]) {
  const f = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4 }
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
}
function contrast(a, b) {
  const x = parseRgb(a); const y = parseRgb(b)
  if (!x || !y) return null
  const [l1, l2] = [lum(x), lum(y)].sort((m, n) => n - m)
  return (l1 + 0.05) / (l2 + 0.05)
}

/** 白名单：字面透明 + 六个强调色预设（它们本来就该两主题同值）。 */
function buildWhitelist(tokensLight, tokensDark) {
  const set = new Set(['transparent', 'rgba(0,0,0,0)', 'inherit'].map(norm))
  for (const t of tokensLight) set.add(norm(t))
  for (const t of tokensDark) set.add(norm(t))
  return set
}

/** 逐元素过 A / B 两条判据。`rows` = [{view, theme, row}]。 */
function judge(rows, tokens) {
  const accents = ['--accent-1', '--accent-2', '--accent-3', '--accent-4', '--accent-5', '--accent-6']
  const wl = buildWhitelist(accents.map((k) => tokens.light[k]), accents.map((k) => tokens.dark[k]))
  const byEl = new Map()
  for (const { view, theme, row } of rows) {
    const key = view + '\u0000' + row.p
    if (!byEl.has(key)) byEl.set(key, { view, p: row.p, t: row.t, fs: row.fs })
    byEl.get(key)[theme] = row
  }
  const hitsA = []
  const hitsB = []
  for (const el of byEl.values()) {
    const L = el.light; const D = el.dark
    if (!L || !D) continue
    // 判据 A：暗值 === 亮值（逐字节）且不在白名单 → 没跟着主题变
    for (const [prop, lv, dv] of [
      ['background-color', L.bg, D.bg], ['color', L.fg, D.fg],
      ['border-top-color', L.bt, D.bt], ['border-right-color', L.br, D.br],
      ['border-bottom-color', L.bb, D.bb], ['border-left-color', L.bl, D.bl],
    ]) {
      if (norm(lv) === norm(dv) && !wl.has(norm(lv))) {
        hitsA.push({ view: el.view, p: el.p, prop, val: lv })
      }
    }
    // 判据 B：文字对比度（只看有自有文字的元素；背景取「最近的不透明祖先」）
    if (el.t && !hitsA.some((h) => h.p === el.p && h.prop === 'color')) {
      const themeRows = [[L, 'light'], [D, 'dark']]
      for (const [row, theme] of themeRows) {
        const ratio = contrast(row.fg, row.ebg)
        if (ratio == null) continue
        const fs = parseFloat(row.fs) || 0
        const isMuted = norm(row.fg) === norm(tokens[theme]['--muted'])
        const threshold = fs >= 18 || isMuted ? 3.0 : 4.5
        if (ratio < threshold) {
          hitsB.push({ view: el.view, p: el.p, theme, fg: row.fg, bg: row.ebg,
            ratio: Math.round(ratio * 100) / 100, threshold,
            role: fs >= 18 ? '≥18px' : isMuted ? '次要(--muted)' : '正文' })
        }
      }
    }
  }
  // 同一元素亮暗两边都低 → 只留更差的那条 + 标明两边；简单起见全保留（诊断工具，宁可多报）
  return { hitsA, hitsB }
}

/* ---------------------------------------------------------------- 主题等待 */

/** 切完主题要等**渲染稳定**：`--dur-*` 过渡那一下会让 getComputedStyle 读到中间值。
 *  等「body 背景 + 变异计数」连续 4 拍不变（拍 150ms），再多睡一拍。 */
async function waitThemeStable(cdp) {
  let last = ''
  let same = 0
  for (let i = 0; i < 40 && same < 4; i++) {
    await sleep(150)
    const s = await cdp.eval(
      `getComputedStyle(document.body).backgroundColor + '|' + (window.__tfmut || 0)`
    )
    if (s === last) same++
    else { same = 0; last = s }
  }
  await sleep(150)
}

/* ---------------------------------------------------------------- 令牌自检 */

/** 数 app.css 令牌区：亮色区几个颜色令牌 / 暗色区几个 / 只在亮色区（暗色没覆盖）几个。
 *  只按「:root {}」与「[data-theme="dark"] {}」两个块数 `--xxx:` 定义（文本层，不做求值）。 */
function tokenAudit() {
  const css = readFileSync(join(ROOT, 'src', 'web', 'app.css'), 'utf8')
  const block = (re) => { const m = css.match(re); return m ? m[1] : '' }
  const light = block(/:root\s*\{([\s\S]*?)\n\}/)
  const dark = block(/\[data-theme="dark"\]\s*\{([\s\S]*?)\n\}/)
  const names = (s) => [...s.matchAll(/^\s*(--[\w-]+)\s*:/gm)].map((m) => m[1])
    .filter((n) => !/^(--sp|--r-|--fs|--lh|--fw|--dur|--nav|--page|--shadow$)/.test(n)
      && n !== '--shadow-rgb')
  const ln = names(light); const dn = names(dark)
  const onlyLight = ln.filter((n) => !dn.includes(n))
  return { light: ln.length, dark: dn.length, onlyLight }
}

/* ---------------------------------------------------------------- 主流程 */

async function main() {
  const result = { ok: false, code: 1, views: VIEWS, hitsA: [], hitsB: [], notes: [] }
  const browserPath = findBrowser()
  if (!browserPath) {
    console.log('[NOT RUN] 找不到真浏览器（Edge/Chrome/Chromium）。可用 TF_CHROME=<路径> 指定。')
    return { ...result, code: 1 }
  }
  setFixtureDay(CAPTURE_DAY)
  const server = startServer(ARGS.port, { TIMEFLOW_FAKE_TODAY: CAPTURE_DAY })
  const cdpPort = ARGS.port + 1
  const profileDir = join(process.env.TEMP ?? '/tmp', `tf-dark-probe-${ARGS.port}`)
  let cdp = null
  try {
    if (!(await waitHealth(ARGS.port))) {
      console.log('❌ 起不了后端服务：' + server.dump().slice(-600))
      return result
    }
    const problems = await seedFixture(ARGS.port)
    if (problems.length) {
      console.log('❌ fixture（种子数据）没造全 —— 半份数据照不出真实界面：')
      for (const p of problems) console.log('   · ' + p)
      return result
    }
    cdp = await Cdp.attach(browserPath, cdpPort, profileDir)
    if (!cdp) {
      console.log('[NOT RUN] 浏览器起来了但 CDP 端点连不上。**没有验证**，不算通过。')
      return result
    }
    await cdp.installClock(CAPTURE_DAY)
    await setViewport(cdp, { name: 'desktop', width: 1280, height: 900 })
    const url = `http://127.0.0.1:${ARGS.port}/`
    const booted = await bootApp(cdp, url)
    if (!booted) throw new Error('应用没有启动完成（左栏没渲染出来）')

    // ★ 探针自检：dataset 直接切暗色，`--bg` 的解析值必须真的变 —— 不然下面的读数全是废的。
    const bgLight = await cdp.eval(
      `getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()`
    )
    await cdp.eval(`document.documentElement.dataset.theme = 'dark'`)
    await waitThemeStable(cdp)
    const bgDark = await cdp.eval(
      `getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()`
    )
    await cdp.eval(`document.documentElement.dataset.theme = 'light'`)
    await waitThemeStable(cdp)
    if (norm(bgLight) === norm(bgDark)) {
      console.log(`❌ 探针自检失败：切暗色后 --bg 没变（亮 ${bgLight} / 暗 ${bgDark}）—— 读数作废。`)
      return { ...result, code: 2 }
    }

    // 逐屏 × 亮/暗 采集
    const rows = []
    for (const view of VIEWS) {
      const clicked = await cdp.eval(`(() => {
        const btns = [...document.querySelectorAll('[data-view="${view}"]')];
        const vis = btns.find((b) => b.offsetParent !== null) || btns[0];
        if (!vis) return false; vis.click(); return true; })()`)
      if (!clicked) throw new Error(`界面上找不到视图 ${view} 的入口`)
      await waitIdle(cdp)
      for (const theme of ['light', 'dark']) {
        await cdp.eval(`document.documentElement.dataset.theme = ${JSON.stringify(theme)}`)
        await waitThemeStable(cdp)
        const res = await cdp.eval(`${COLLECT}`)
        for (const row of res.rows) rows.push({ view, theme, row })
        if (theme === 'dark') darkTokens[view] = res.tokens
        else lightTokens[view] = res.tokens
        await sleep(0)
      }
    }
    const tokens = { light: lightTokens[VIEWS[0]], dark: darkTokens[VIEWS[0]] }
    const { hitsA, hitsB } = judge(rows, tokens)
    const audit = tokenAudit()

    if (ARGS.json) {
      console.log(JSON.stringify({ ok: true, views: VIEWS, audit, hitsA, hitsB, tokens }, null, 2))
    } else {
      console.log(`\n=== 暗色探针（只读）· 视图 ${VIEWS.join(', ')} · 1280×900 · 今天=${CAPTURE_DAY} ===`)
      console.log(`[令牌自检] 亮色区 ${audit.light} 个颜色令牌 / 暗色区 ${audit.dark} 个 / 只在亮色区（暗色没覆盖）${audit.onlyLight.length} 个${audit.onlyLight.length ? '：' + audit.onlyLight.join(' ') : ''}`)
      console.log(`\n--- 判据 A「没跟着主题变」：${hitsA.length} 处 ---`)
      if (!hitsA.length) console.log('（无）')
      for (const h of hitsA) {
        console.log(`  ${h.view} | ${h.p} | ${h.prop} | ${h.val}`)
      }
      console.log(`\n--- 判据 B「对比度不足」：${hitsB.length} 处 ---`)
      if (!hitsB.length) console.log('（无）')
      for (const h of hitsB) {
        console.log(`  ${h.view} | ${h.p} | [${h.theme}] ${h.fg} on ${h.bg} = ${h.ratio}（要 ≥ ${h.threshold}，${h.role}）`)
      }
      console.log(`\n合计：A ${hitsA.length} 处 / B ${hitsB.length} 处`)
    }
    result.hitsA = hitsA
    result.hitsB = hitsB
    result.ok = true
    result.code = 0
    return result
  } catch (exc) {
    console.log('❌ ' + (exc instanceof Error ? exc.message : String(exc)))
    return result
  } finally {
    cdp?.close()
    if (!ARGS.keep) { try { server.child.kill() } catch { /* ignore */ } }
  }
}

const lightTokens = {}
const darkTokens = {}
const res = await main()
process.exit(res.code)
