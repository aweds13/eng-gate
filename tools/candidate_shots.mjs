/* 候选预演（视觉线步 2 起）—— 把**候选 CSS**注入真界面，截图 + 量数，选定之后才动 `app.css`。
 *
 * 为什么要有这一步（T-G30 §5 定的口径）：从步 2 起改动**看得见**了 —— "层次语言 / 排版节奏"
 * 这类改动，判据不再是"超没超过某个数"，而是"你要哪一种"。而**人只该在有意的视觉改动时看一眼**，
 * 所以流程是：**先给能看的（候选 + 截图），选定，再改进代码**。
 *
 * 为什么不是"改三遍 app.css 再看"：那样每次都得改真文件、跑门、再回退，回退漏一处就是脏树；
 * 而且候选之间只能一次看一个。注入 `<style>` 的方式：**同一份 app.css**（一个后端、一份种子数据、
 * 一个浏览器），候选只差一个覆盖层 —— 比较的变量只有一个。
 *
 * 它与门禁的关系：**它不是门禁，也不写任何黄金**。它只产两样东西：
 *   · `gates/render/candidates/<候选>/*.png`（人看的证据，别入库 —— 同 `--shots`）；
 *   · 一张数字表（每个视图的页高 / 卡片数 / 有边框的卡片数 / 非白底卡片数）。
 * 判"变了没有"仍然是渲染黄金层的事（`render_check.mjs`），选定之后由它重采黄金并留理由。
 *
 * 用法
 *     node tools/candidate_shots.mjs                          # 跑 gates/candidates/*.css + 一组"今天"基线
 *     node tools/candidate_shots.mjs --dir gates/candidates/step2
 *     node tools/candidate_shots.mjs --views today,focus,stats,habit
 *     node tools/candidate_shots.mjs --vp desktop,phone --json
 *
 * 退出码：0 正常 / 2 起不了服务或种子数据不全 / 3 起不了真浏览器（NOT RUN）。
 */
import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import { basename, join } from 'node:path'
import { setTimeout as sleep } from 'node:timers/promises'

import {
  Cdp, ROOT, VIEWPORTS, VIEWS, bootApp, findBrowser, seedFixture,
  setViewport, startServer, waitHealth, waitIdle,
} from './tf_browser.mjs'

const OUT_ROOT = join(ROOT, 'gates', 'render', 'candidates')
const DEFAULT_DIR = join(ROOT, 'gates', 'candidates')

function parseArgs(argv) {
  const a = { dir: DEFAULT_DIR, port: 8541, keep: false, json: false, views: null, vps: null, only: null }
  for (let i = 0; i < argv.length; i++) {
    const k = argv[i]
    if (k === '--dir') a.dir = argv[++i]
    else if (k === '--only') a.only = argv[++i]
    else if (k === '--port') a.port = Number(argv[++i])
    else if (k === '--views') a.views = argv[++i].split(',').map((s) => s.trim()).filter(Boolean)
    else if (k === '--vp') a.vps = argv[++i].split(',').map((s) => s.trim()).filter(Boolean)
    else if (k === '--keep') a.keep = true
    else if (k === '--json') a.json = true
    else { console.error(`未知参数：${k}`); process.exit(1) }
  }
  return a
}

const ARGS = parseArgs(process.argv.slice(2))
const VIEWS_RUN = ARGS.views ? VIEWS.filter((v) => ARGS.views.includes(v)) : VIEWS
const VPS_RUN = ARGS.vps ? VIEWPORTS.filter((v) => ARGS.vps.includes(v.name)) : VIEWPORTS
for (const want of ARGS.views ?? []) {
  if (!VIEWS.includes(want)) { console.error(`没有这个视图：${want}`); process.exit(1) }
}
for (const want of ARGS.vps ?? []) {
  if (!VIEWPORTS.some((v) => v.name === want)) { console.error(`没有这档宽度：${want}`); process.exit(1) }
}

/* 量什么：都是**从计算样式现读**的事实，不是我写在纸上的期望值。
 * `docH` 是密度（间距收紧会变矮）、卡片那几个计数是"层次"（有边框的卡 / 有阴影的卡 / 非白底的卡）。
 * 注意这里**不判"好不好看"** —— 那一步只能人看 PNG。 */
const MEASURE = /* js */ `
(() => {
  const cards = [...document.querySelectorAll('.card')];
  const st = cards.map((c) => getComputedStyle(c));
  const panels = [...document.querySelectorAll('.panel')].map((p) => getComputedStyle(p));
  const bg = new Set(st.map((s) => s.backgroundColor));
  const radius = new Set(cards.map((c) => getComputedStyle(c).borderTopLeftRadius));
  return {
    docH: Math.round(document.documentElement.scrollHeight),
    scrollW: document.documentElement.scrollWidth,
    nodes: document.body.querySelectorAll('*').length,
    cards: cards.length,
    cardBorder: st.filter((s) => parseFloat(s.borderTopWidth) > 0).length,
    cardShadow: st.filter((s) => s.boxShadow !== 'none').length,
    cardTint: st.filter((s) => s.backgroundColor !== 'rgb(255, 255, 255)').length,
    cardBgKinds: bg.size,
    cardRadius: [...radius].join('|'),
    panels: panels.length,
    panelBorder: panels.filter((s) => parseFloat(s.borderTopWidth) > 0).length,
  };
})()`

async function measureView(cdp, vp, view) {
  await cdp.eval(`(() => {
    const btns = [...document.querySelectorAll('[data-view="${view}"]')];
    const vis = btns.find((b) => b.offsetParent !== null) || btns[0];
    if (!vis) return false; vis.click(); return true;
  })()`)
  await waitIdle(cdp)
  return cdp.eval(MEASURE)
}

async function runCandidate(cdp, url, accent, name, css) {
  const outDir = join(OUT_ROOT, name)
  rmSync(outDir, { recursive: true, force: true })   // 上一轮的残留不能跟这一轮混在一起
  mkdirSync(outDir, { recursive: true })
  const rows = []
  for (const vp of VPS_RUN) {
    await setViewport(cdp, vp)
    const booted = await bootApp(cdp, url, { accent })
    if (!booted) throw new Error('应用没启动完成（左栏没渲染出来）')
    if (css) {
      // 注入**在 bootApp 之后**：每次导航都会把注入的 <style> 冲掉，所以按"每档宽度一次"重注。
      // 放在 `<head>` 末尾 = 与 app.css 同权重选择器时它赢（这正是"覆盖层"要的语义）。
      const ok = await cdp.eval(`(() => {
        const s = document.createElement('style');
        s.id = 'candidate-css';
        s.textContent = ${JSON.stringify(css)};
        document.head.appendChild(s);
        return document.getElementById('candidate-css').sheet.cssRules.length;
      })()`)
      if (!ok) throw new Error(`候选 ${name} 的 CSS 没生效（规则数 0）`)
    }
    for (const view of VIEWS_RUN) {
      const m = await measureView(cdp, vp, view)
      rows.push({ vp: vp.name, view, ...m })
      await cdp.shot(join(outDir, `${vp.name}-${view}.png`))
    }
  }
  const lines = ['# candidate ' + name + ' views=' + VIEWS_RUN.length + ' viewports=' + VPS_RUN.map((v) => v.name).join(',')]
  for (const r of rows) lines.push(JSON.stringify(r))
  writeFileSync(join(outDir, 'summary.txt'), lines.join('\n') + '\n', 'utf8')
  return rows
}

async function main() {
  const t0 = Date.now()
  const url = `http://127.0.0.1:${ARGS.port}/`
  const result = { ok: false, code: 1, candidates: [] }

  const files = existsSync(ARGS.dir)
    ? readdirSync(ARGS.dir).filter((f) => f.endsWith('.css'))
      .filter((f) => !ARGS.only || f.includes(ARGS.only)).sort()
    : []
  if (!files.length) {
    console.error(`❌ ${ARGS.dir} 里没有 .css 候选文件`)
    return { ...result, code: 2 }
  }

  const browserPath = findBrowser()
  if (!browserPath) {
    console.log('[NOT RUN] 找不到真浏览器（Edge/Chrome/Chromium）。这次预演**没有发生**。')
    return { ...result, code: 3, notRun: true }
  }

  console.log(`=== 候选预演：${files.length} 个候选 × ${VPS_RUN.length} 档宽度 × ${VIEWS_RUN.length} 个视图 ===`)
  const server = startServer(ARGS.port)
  const cdpPort = ARGS.port + 2
  const profileDir = join(process.env.TEMP ?? '/tmp', `tf-cand-profile-${ARGS.port}`)
  let cdp = null
  try {
    if (!(await waitHealth(ARGS.port))) {
      console.error('❌ 起不了后端服务：' + server.dump().slice(-600))
      return { ...result, code: 2 }
    }
    const problems = await seedFixture(ARGS.port)
    if (problems.length) {
      console.error('❌ 种子数据没造全，先修 seed：')
      for (const p of problems) console.error('   · ' + p)
      return { ...result, code: 2 }
    }
    let accent = '#3b82f6'
    try {
      const cfg = await (await fetch(`http://127.0.0.1:${ARGS.port}/api/config`)).json()
      if (cfg?.accent_color) accent = cfg.accent_color
    } catch { /* 兜底值，header 里会写明 */ }

    cdp = await Cdp.attach(browserPath, cdpPort, profileDir)
    if (!cdp) {
      console.log('[NOT RUN] 浏览器起来了但 CDP 连不上。这次预演**没有发生**。')
      return { ...result, code: 3, notRun: true }
    }

    // 第一组永远是"今天"（不注入任何东西）：没有它，候选之间的数字无从比较。
    const table = []
    table.push({ name: '今天', rows: await runCandidate(cdp, url, accent, '0-今天', null) })
    for (const f of files) {
      const name = basename(f, '.css')
      const css = readFileSync(join(ARGS.dir, f), 'utf8')
      console.log(`[候选] ${name}（${css.split('\n').length} 行）`)
      table.push({ name, rows: await runCandidate(cdp, url, accent, name, css) })
    }

    // 数字表：以"今天"为基准，逐视图给页高差与卡片层次计数
    const base = new Map(table[0].rows.map((r) => [`${r.vp}/${r.view}`, r]))
    const out = ['# 候选数字表（页高差 = 候选 − 今天，负数=更紧凑）']
    for (const t of table) {
      out.push(`\n## ${t.name}`)
      out.push('  视口/视图            页高    Δ页高  节点  卡  有边框  有阴影  非白底  卡底种类  卡圆角')
      for (const r of t.rows) {
        const b = base.get(`${r.vp}/${r.view}`)
        const d = b ? r.docH - b.docH : 0
        out.push(`  ${(r.vp + '/' + r.view).padEnd(20)} ${String(r.docH).padStart(5)}  ${String(d).padStart(6)}` +
          `  ${String(r.nodes).padStart(4)}  ${String(r.cards).padStart(3)}  ${String(r.cardBorder).padStart(5)}` +
          `  ${String(r.cardShadow).padStart(5)}  ${String(r.cardTint).padStart(5)}  ${String(r.cardBgKinds).padStart(7)}` +
          `  ${r.cardRadius}`)
      }
    }
    console.log('\n' + out.join('\n'))
    writeFileSync(join(OUT_ROOT, 'NUMBERS.md'), out.join('\n') + '\n', 'utf8')
    result.ok = true
    result.code = 0
    result.candidates = table.map((t) => t.name)
    console.log(`\n[产物] ${OUT_ROOT.replace(ROOT + '\\', '')}\\<候选>\\*.png + summary.txt；数字表 NUMBERS.md`)
    return result
  } finally {
    cdp?.close()
    if (!ARGS.keep) { try { server.child.kill() } catch { /* ignore */ } }
    await sleep(400)
    try { rmSync(profileDir, { recursive: true, force: true }) } catch { /* 留给系统回收 */ }
    console.log(`[耗时] ${((Date.now() - t0) / 1000).toFixed(1)}s`)
  }
}

const res = await main()
if (ARGS.json) console.log(JSON.stringify(res, null, 2))
process.exit(res.code)
