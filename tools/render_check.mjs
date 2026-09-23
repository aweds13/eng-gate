/* 渲染验证层：用**真浏览器**把每个视图 × 每档宽度渲染一遍，采成"几何清单"当黄金，逐行比对。
 *
 * 为什么需要（T-G32）：在此之前，全项目**没有任何一样东西**能证明"界面看起来是对的"。
 * 14 道门能证明结构、能证明令牌的对比度、能证明"体系里没有新的破例"，
 * 但**没有任何一道门看过渲染结果** —— 于是 `.new input` 把复选框也当文本框画
 * （复选框被拉成 76×13 的白方块、把「也放进今天」这行标签挤成竖排三行）
 * 这种"打开首页第一眼就能看见"的缺陷，能一路穿过 14 道门。这个工具就是补这一层。
 *
 * 它采什么：每个可见元素一行，7 个字段（选择器路径 / 文本 / 盒子 / 字号·行高·字重 / 前景·背景 / 圆角·内边距）。
 * 为什么是文本清单而不是图片：**文本能逐行 diff**。图片 diff 有抗锯齿噪声，判不了"变了没有"，
 * 只能给人看。所以：几何清单当**判据**（机器逐行比），PNG 当**证据**（`--shots` 时另存，给人看）。
 *
 * 为什么它不会漂（这是这套东西的全部意义）：
 *   ① 黄金文件**进仓库**，跟代码一起版本化；
 *   ② 门禁**每次都重跑**（人写的检查会烂 —— 本仓库自己已经烂过两次：空的动线自查表、过期的 gaps）；
 *   ③ 采集**每轮跑两遍**做确定性自检：两遍不一致 = 这个工具自己不可信 → 直接 FAIL（不当成"界面变了"）；
 *   ④ 改黄金必须 `--update --reason "<为什么>"`，理由落进 `LAST_UPDATE.md` 一起提交。
 *
 * 已知的边界（**不谎报**）：
 *   · 起不了浏览器 → 退出码 3（NOT RUN），**NOT RUN 不是 PASS**；`run_gates.py` 会把它单独记一栏。
 *   · 它判"变了没有"，**判不了"好不好看"** —— 好看是人的事，而人只该在有意的视觉改动时看一眼 diff 图。
 *   · 绝对时间戳（「完成于 2026年09月23日 12:31」）按固定形状归一化（`YYYY年MM月DD日 HH:MM`）：
 *     黄金证明的是版式与状态，不是"当时几点"。归一化了几处会打印出来，**不静默**。
 *
 * 用法
 *     node tools/render_check.mjs                     # 比对黄金（默认）
 *     node tools/render_check.mjs --update --reason "…"   # 用当前渲染重写黄金（必须写理由）
 *     node tools/render_check.mjs --shots             # 另存 PNG 到 gates/render/shots/（不进仓库）
 *     node tools/render_check.mjs --json              # 机器可读结果
 *     node tools/render_check.mjs --port 8531 --keep   # 调试：换端口 / 跑完不杀服务
 *
 * 退出码：0 通过 / 1 与黄金不一致或其它失败 / 2 fixture（种子数据）坏了 /
 *         3 起不了真浏览器（NOT RUN）/ 4 采集本身不确定（自检失败）。
 */
import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { setTimeout as sleep } from 'node:timers/promises'

// 起服务 / 起真浏览器 / 把渲染环境钉成确定的 —— 这些**两个工具都要**的事在
// `tools/tf_browser.mjs`（T-G34 抽出来的共用底座）。行为流层（`ui_flow_check.mjs`）
// 用的是同一套：一处实现、两处使用，免得两份慢慢长歪。
import {
  Cdp, FIXED_DEVICE, MASK_PATHS, MUTATION_WATCH, ROOT, VIEWPORTS, VIEWS,
  bootApp, findBrowser, seedFixture, setViewport, startServer, waitHealth, waitQuiet,
} from './tf_browser.mjs'

const GOLDEN_DIR = join(ROOT, 'gates', 'render')
const SHOTS_DIR = join(GOLDEN_DIR, 'shots')
const UPDATE_LOG = join(GOLDEN_DIR, 'LAST_UPDATE.md')
const SCHEMA = 'v1'

/* ---------------------------------------------------------------- 参数 */

function parseArgs(argv) {
  const a = { update: false, shots: false, json: false, keep: false, port: 8531, reason: '', quiet: false }
  for (let i = 0; i < argv.length; i++) {
    const k = argv[i]
    if (k === '--update') a.update = true
    else if (k === '--shots') a.shots = true
    else if (k === '--json') a.json = true
    else if (k === '--keep') a.keep = true
    else if (k === '--quiet') a.quiet = true
    else if (k === '--port') a.port = Number(argv[++i])
    else if (k === '--reason') a.reason = argv[++i] ?? ''
    else if (k === '--only') a.only = argv[++i]
    else if (k === '--seed-only') a.seedOnly = true
    else { console.error(`未知参数：${k}`); process.exit(1) }
  }
  if (a.update && !a.reason.trim()) {
    console.error('❌ --update 必须带 --reason "<一句话说明为什么这次改动是对的>"')
    console.error('   （黄金是判据，改判据必须留下理由 —— 跟台账登记、棘轮销账一个道理）')
    process.exit(1)
  }
  return a
}

const ARGS = parseArgs(process.argv.slice(2))

/* ------------------------------------------------- 视口 / 视图 */

// 三档宽度（desktop / narrow / phone，与 app.css 三条断点对齐）、14 个视图名，
// 以及采集时要钉住的常量（设备号 / 导出目录 / 要归一化的本机路径）都住在 `tf_browser.mjs`。

/* ---------------------------------------------------------------- 工具 */

const log = (...m) => { if (!ARGS.quiet) console.log(...m) }
const nowISO = () => new Date().toISOString().replace('T', ' ').slice(0, 19)
// 采集时钉住的强调色（默认取 `/api/config` 里的那个；见 `bootApp` 的注释）
let CFG_ACCENT = '#3b82f6'

/* ---------------------------------------------------------------- 采集 */

// 这一大段是**在页面里跑**的采集器。注意几条纪律：
//   · 不采任何 data-* 的值（里面有 uuid，每次都不一样）；
//   · `#clock` 与 `#toast` 不采（一个每秒在走，一个是过场提示）；
//   · 绝对时间戳统一成固定形状（「2026年09月23日 12:31」→「YYYY年MM月DD日 HH:MM」）。
const COLLECT = /* js */ `
(() => {
  const VP = window.__tfvp;
  const norm = (s) => String(s == null ? '' : s).replace(/\\s+/g, ' ').trim().slice(0, 90);
  const hex = (c) => {
    if (!c) return '';
    const m = String(c).match(/^rgba?\\(([^)]+)\\)$/);
    if (!m) return String(c);
    const p = m[1].split(',').map((x) => x.trim());
    const [r, g, b] = p.slice(0, 3).map(Number);
    const a = p.length > 3 ? Number(p[3]) : 1;
    const h = '#' + [r, g, b].map((v) => Number(v).toString(16).padStart(2, '0')).join('');
    return a >= 1 ? h : h + '@' + a.toFixed(2);
  };
  const sel = (el) => {
    // 元素 id **不总是**能当路标：有些是拿数据 id 拼出来的（「asTarget-a5289330e5c2」），
    // 每次种子数据都是新的 uuid —— 那种 id 一律不写进路标，退回"标签 + nth-child"。
    const idUsable = (e) => Boolean(e.id) && !/[-_][0-9a-f]{6,}$/.test(e.id);
    const sig = (x) => x.tagName.toLowerCase() +
      (idUsable(x) ? '#' + x.id : (x.classList && x.classList.length ? '.' + [...x.classList].join('.') : ''));
    const part = (e) => {
      let s = e.tagName.toLowerCase();
      if (idUsable(e)) s += '#' + e.id;
      else if (e.classList && e.classList.length) s += '.' + [...e.classList].join('.');
      const p = e.parentElement;
      if (p) {
        const same = [...p.children].filter((x) => sig(x) === sig(e));
        if (same.length > 1) s += ':nth-child(' + ([...p.children].indexOf(e) + 1) + ')';
      }
      return s;
    };
    const chain = [];
    let e = el;
    while (e && e.tagName && chain.length < 4) { chain.unshift(part(e)); e = e.parentElement }
    return chain.join('>');
  };

  let masked = 0;
  const bump = (v) => () => { masked++; return v };
  // **归一化的是"环境/身份/时刻"，不是"版式/状态"**（这一条决定了黄金能不能活过明天）：
  //  · 绝对日期与时刻：种子用的是**相对今天**的日期，所以「今天/还有 3 天/已逾期 2 天」这类
  //    相对标签天生稳定，而「2026-09-21」这种字面日期**明天就变了** —— 归成固定形状。
  //    日期算得对不对是 pytest 的事（那里才有断言）；这一层只管"画出来的样子"。
  //  · 临时目录名 / 长十六进制串（同步设备号、配对码）：每次起服务、每个库都不一样。
  const mask = (t) => {
    // 先换掉**已知的字面前缀**（本机临时目录）：这一类不是"模式"而是"这台机器的路径"，
    // 由 Node 侧把要换的前缀传进来（页面里不用猜）。
    for (const p of (VP.paths || [])) { if (p && t.indexOf(p) >= 0) { t = t.split(p).join('<path>'); masked++ } }
    return t
      .replace(/\\d{4}年\\d{2}月\\d{2}日 \\d{2}:\\d{2}/g, bump('YYYY年MM月DD日 HH:MM'))
      .replace(/\\d{4}-\\d{2}-\\d{2}[T ]\\d{2}:\\d{2}(:\\d{2})?/g, bump('YYYY-MM-DD HH:MM'))
      .replace(/\\d{4}-\\d{2}-\\d{2}/g, bump('YYYY-MM-DD'))
      .replace(/timeflow_fresh_[0-9a-z_]+/g, bump('timeflow_fresh_<tmp>'))
      .replace(/\\b(?=[0-9a-f]*[a-f])[0-9a-f]{10,}\\b/g, bump('<id>'));
  };
  // 「code」标签里放的就是机器标识（设备号 / 配对码 / 落盘文件名）：整段按"机器标识"归一，
  // 但**长度照比**（长度是版式的一部分）。
  const isCodeToken = (s) => /^[0-9A-Za-z\\-_.:\\\\/]{6,}$/.test(s);

  const SKIP_ID = new Set(['clock', 'toast']);
  const rows = [];
  for (const el of document.body.querySelectorAll('*')) {
    const tag = el.tagName.toLowerCase();
    if (tag === 'script' || tag === 'style' || tag === 'link' || tag === 'meta') continue;
    if (el.id && SKIP_ID.has(el.id)) continue;
    if (el.closest && el.closest('#clock')) continue;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    if (Number(cs.opacity) === 0) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    const hasElKids = el.children.length > 0;
    const hasName = Boolean(el.id) || (el.classList && el.classList.length > 0);
    // 采两类：叶子（文本/控件在哪、多大、什么颜色）+ 有名字的容器（版式骨架）。
    // 匿名容器不单独采 —— 它的几何变化一定会反映到叶子的位置/尺寸上。
    if (hasElKids && !hasName) continue;
    let text = '';
    if (tag === 'input') text = '(' + (el.type || 'text') + ')' + norm(el.placeholder || el.value || '');
    else if (tag === 'select') text = norm(el.selectedOptions && el.selectedOptions[0] ? el.selectedOptions[0].textContent : '');
    else if (!hasElKids) text = norm(el.textContent);
    else if (el.getAttribute('aria-label')) text = norm(el.getAttribute('aria-label'));
    if (tag === 'code' && isCodeToken(text)) { text = '‹code:' + text.length + '›'; masked++ }
    const px = (v) => { const n = parseFloat(v); return Number.isFinite(n) ? Math.round(n * 10) / 10 : (v || '') };
    rows.push([
      sel(el),
      mask(text),
      [r.x, r.y, r.width, r.height].map((v) => Math.round(v)).join(','),
      [px(cs.fontSize), px(cs.lineHeight), cs.fontWeight].join('/'),
      hex(cs.color) + '/' + hex(cs.backgroundColor),
      [px(cs.borderTopLeftRadius), norm(cs.padding)].join(';'),
    ].join('\\t'));
  }
  return { view: VP.view, vp: VP.name, w: innerWidth, h: innerHeight, rows, masked,
    header: document.querySelector('.rail button.active') ? document.querySelector('.rail button.active').textContent.trim() : '' };
})()
`

// "页面还在动吗"的计数器（`MUTATION_WATCH`）与"等它安静下来"（`waitQuiet`）都在 `tf_browser.mjs`：
// 行为流层点完一个按钮之后要等的东西**跟这里一模一样**，所以那一份实现是共用的。

async function collectView(cdp, vp, view) {
  await cdp.eval(MUTATION_WATCH)
  const clicked = await cdp.eval(`(() => {
    const btns = [...document.querySelectorAll('[data-view="${view}"]')];
    const vis = btns.find((b) => b.offsetParent !== null) || btns[0];
    if (!vis) return false;
    vis.click();
    return true;
  })()`)
  if (!clicked) throw new Error(`界面上找不到视图 ${view} 的入口`)
  // 等"页面安静下来"：DOM 变动计数连续 6 拍（≈0.7s）不再增长，且至少等够一拍渲染
  await waitQuiet(cdp)
  return cdp.eval(`window.__tfvp = {name:${JSON.stringify(vp.name)}, view:${JSON.stringify(view)}, paths:${JSON.stringify(MASK_PATHS)}}; ${COLLECT}`)
}

function manifestText(res) {
  const lines = [`# render-manifest ${SCHEMA} viewport=${res.vp} ${res.w}x${res.h} view=${res.view} rows=${res.rows.length} accent=${CFG_ACCENT} device=${FIXED_DEVICE}`]
  for (const row of res.rows) lines.push(row)
  return lines.join('\n') + '\n'
}

async function collectAll(cdp, url, port) {
  const out = new Map()
  for (const vp of VIEWPORTS) {
    // 换宽度（每次都重钉滚动条）+ 从**同一个已知的本机存储**起步 —— 这两件事在 `tf_browser.mjs` 里。
    await setViewport(cdp, vp)
    const booted = await bootApp(cdp, url, { accent: CFG_ACCENT })
    if (!booted) throw new Error('应用没有启动完成（左栏没渲染出来）—— 界面可能根本没起来')
    for (const view of VIEWS) {
      if (ARGS.only && ARGS.only !== view) continue
      const res = await collectView(cdp, vp, view)
      out.set(`${vp.name}/${view}`, { header: res, text: manifestText(res) })
      if (ARGS.shots) {
        mkdirSync(SHOTS_DIR, { recursive: true })
        await cdp.shot(join(SHOTS_DIR, `${vp.name}-${view}.png`))
      }
    }
    void port
  }
  return out
}

/* ---------------------------------------------------------------- 比对 */

function diffLines(a, b) {
  const A = a.split('\n')
  const B = b.split('\n')
  const n = A.length
  const m = B.length
  // 经典 LCS 表（清单只有几千行，够用；只为了把 diff 对齐得好看一点）
  const dp = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1))
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1])
    }
  }
  const out = []
  let i = 0
  let j = 0
  while (i < n && j < m) {
    if (A[i] === B[j]) { i++; j++ }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { out.push(['-', A[i]]); i++ }
    else { out.push(['+', B[j]]); j++ }
  }
  while (i < n) { out.push(['-', A[i]]); i++ }
  while (j < m) { out.push(['+', B[j]]); j++ }
  return out
}

/* ---------------------------------------------------------------- 主流程 */

async function main() {
  const t0 = Date.now()
  const url = `http://127.0.0.1:${ARGS.port}/`
  const result = { ok: false, code: 1, views: 0, changed: [], notRun: false, notes: [] }

  const browserPath = findBrowser()
  if (!browserPath) {
    log('[NOT RUN] 找不到真浏览器（Edge/Chrome/Chromium）。这一层**没有验证**，不算通过。')
    log('          可用 TF_CHROME=<路径> 指定。')
    result.notRun = true
    result.code = 3
    return result
  }

  log(`=== 渲染验证层：真浏览器 ${browserPath.split(/[\\/]/).pop()} ===`)
  const server = startServer(ARGS.port)
  const cdpPort = ARGS.port + 1
  const profileDir = join(process.env.TEMP ?? '/tmp', `tf-render-profile-${ARGS.port}`)
  let cdp = null
  try {
    if (!(await waitHealth(ARGS.port))) {
      console.log('❌ 起不了后端服务：' + server.dump().slice(-600))
      result.notes.push('serve.py 没起来')
      result.code = 2
      return result
    }
    const problems = await seedFixture(ARGS.port)
    if (problems.length) {
      console.log('❌ fixture（种子数据）没造全 —— 半份数据生成的黄金不可信，先修 seed：')
      for (const p of problems) console.log('   · ' + p)
      result.notes.push(...problems)
      result.code = 2
      return result
    }
    // 强调色钉成**配置里的那个**（不是写死一个值）：黄金上就写着"这份清单是按哪个强调色采的"，
    // 以后改默认色，diff 会明明白白地显示"是色换了"而不是一屏莫名其妙的位移。
    try {
      const cfg = await (await fetch(`http://127.0.0.1:${ARGS.port}/api/config`)).json()
      if (cfg && typeof cfg.accent_color === 'string' && cfg.accent_color) CFG_ACCENT = cfg.accent_color
    } catch { /* 拿不到就用兜底值，header 里会写明 */ }

    // `--seed-only`：起服务 + 造数据，然后**停在那儿**（给"在真数据上试 CSS"用）。
    // 为什么要有：黄金每轮 95 秒，拿它试三个候选样式太慢；先起一个有数据的服务，
    // 再用浏览器注入候选 CSS 量一遍，选定之后才动 app.css —— 改动是量出来的，不是猜出来的。
    if (ARGS.seedOnly) {
      console.log(`[seed-only] ${url}（数据已就绪；Ctrl+C 或 job_kill 停）`)
      await new Promise(() => { /* 一直挂着，等服务被外部停掉 */ })
    }

    cdp = await Cdp.attach(browserPath, cdpPort, profileDir)
    if (!cdp) {
      log('[NOT RUN] 浏览器起来了但 CDP 端点连不上（沙箱常拦这条：命名管道/IPC）。**没有验证**，不算通过。')
      result.notRun = true
      result.code = 3
      return result
    }

    const pass1 = await collectAll(cdp, url, ARGS.port)
    const pass2 = await collectAll(cdp, url, ARGS.port)
    result.views = pass1.size

    // ③ 确定性自检：同一个界面采两遍必须**一模一样**，否则是这个工具自己不可信
    const unstable = []
    for (const [k, v1] of pass1) {
      const v2 = pass2.get(k)
      if (!v2 || v1.text !== v2.text) unstable.push(k)
    }
    if (unstable.length) {
      console.log(`❌ 采集本身不确定（两遍不一致）：${unstable.length} 份 —— ${unstable.slice(0, 8).join(' / ')}`)
      console.log('   → 这是**工具的**问题（页面里有会自己变的东西），不是"界面变了"。先修工具，别更新黄金。')
      for (const k of unstable.slice(0, 3)) {
        const d = diffLines(pass1.get(k).text, pass2.get(k).text)
        console.log(`   · ${k}  第一遍 vs 第二遍：`)
        for (const [sign, line] of d.slice(0, 4)) console.log(`     ${sign} ${line.slice(0, 150)}`)
      }
      result.notes.push('确定性自检失败：' + unstable.join(','))
      result.code = 4
      return result
    }
    log(`[OK ] 确定性自检：${pass1.size} 份清单各采两遍，逐字节一致`)

    const maskedTotal = [...pass1.values()].reduce((s, v) => s + v.header.masked, 0)
    if (maskedTotal) log(`[note] 归一化了 ${maskedTotal} 处绝对时间戳（版式照判，钟点不判；不静默）`)

    // ④ 比对 / 更新
    mkdirSync(GOLDEN_DIR, { recursive: true })
    const changed = []
    for (const [key, cur] of [...pass1.entries()].sort()) {
      const file = join(GOLDEN_DIR, key.replace('/', '__') + '.txt')
      // 读黄金时把 CRLF 归成 LF：`.gitattributes` 已经给黄金钉了 `eol=lf`，这里是**第二道保险** ——
      // 这台机器的全局配置是 `core.autocrlf=true`，谁要是换了台机器/改了配置，
      // 逐字节比会因为"行尾被 git 改写"而满地红，而那种红看不出到底哪里变了。
      const prev = existsSync(file) ? readFileSync(file, 'utf8').replace(/\r\n/g, '\n') : null
      if (prev === cur.text) continue
      changed.push({ key, file, prev })
    }
    const gone = []
    // `--only` 是调试用的：只采一个视图时，**不能**把其余黄金当成"多余"删掉
    // （第一版就这么干过：`--only today --update` 一口气删了 39 份黄金，日志还写着
    // "界面里已经没有这个视图" —— 一句假话。现在 `--only` 一律不动别人的黄金。）
    if (!ARGS.only && existsSync(GOLDEN_DIR)) {
      for (const f of readdirTxt(GOLDEN_DIR)) {
        if (!pass1.has(f.replace('.txt', '').replace('__', '/'))) gone.push(f)
      }
    }

    if (ARGS.update) {
      for (const c of changed) writeFileSync(c.file, pass1.get(c.key).text, { encoding: 'utf8' })
      for (const g of gone) rmSync(join(GOLDEN_DIR, g), { force: true })
      const stamp = nowISO()
      const entry = `\n## ${stamp} · ${changed.length} 份改动${gone.length ? ` / 删 ${gone.length} 份` : ''}\n\n> 理由：${ARGS.reason}\n\n` +
        changed.map((c) => `- \`${c.key}\`${c.prev === null ? '（新增）' : ''}`).join('\n') + '\n' +
        gone.map((g) => `- \`${g}\`（删：界面里已经没有这个视图/视口了）`).join('\n') + '\n'
      if (!existsSync(UPDATE_LOG)) {
        writeFileSync(UPDATE_LOG, '# 渲染黄金的更新记录\n\n每次改黄金都要写清理由（`--update --reason`），跟代码一起提交。\n', 'utf8')
      }
      writeFileSync(UPDATE_LOG, readFileSync(UPDATE_LOG, 'utf8') + entry, { encoding: 'utf8' })
      log(`[更新] 黄金：改 ${changed.length} 份、删 ${gone.length} 份 → 理由已记进 ${UPDATE_LOG.replace(ROOT + '\\', '')}`)
      result.changed = changed.map((c) => c.key)
      result.ok = true
      result.code = 0
      return result
    }

    if (changed.length || gone.length) {
      console.log(`\n❌ 渲染与黄金不一致：${changed.length} 份不同、${gone.length} 份多余`)
      for (const c of changed.slice(0, 6)) {
        const d = diffLines(c.prev ?? '', pass1.get(c.key).text)
        const minus = d.filter((x) => x[0] === '-').length
        const plus = d.filter((x) => x[0] === '+').length
        console.log(`\n  · ${c.key}  -${minus} +${plus}${c.prev === null ? '（新增黄金）' : ''}`)
        for (const [sign, line] of d.slice(0, 8)) console.log(`      ${sign} ${line.slice(0, 150)}`)
      }
      if (changed.length > 6) console.log(`  …另有 ${changed.length - 6} 份不同`)
      console.log('\n  若这次改动**是有意的**：node tools/render_check.mjs --update --reason "一句话为什么"')
      console.log('  若是无意的：这就是它抓到的回归。')
      result.changed = changed.map((c) => c.key)
      result.code = 1
      return result
    }

    log(`[OK ] ${pass1.size} 份清单与黄金逐字节一致（${VIEWPORTS.length} 档宽度 × ${VIEWS.length} 个视图）`)
    result.ok = true
    result.code = 0
    return result
  } finally {
    cdp?.close()
    if (!ARGS.keep && !ARGS.seedOnly) { try { server.child.kill() } catch { /* ignore */ } }
    // 浏览器进程退出是异步的：profile 目录常被它多占几百毫秒。清不掉不算错误（临时目录本来就会被系统回收），
    // 但**必须吞掉** —— 采集都成功了却因为"扫尾扫不掉"报失败，是假失败（第一版就踩了）。
    await sleep(400)
    try { rmSync(profileDir, { recursive: true, force: true }) } catch { /* 留给系统回收 */ }
    log(`[耗时] ${((Date.now() - t0) / 1000).toFixed(1)}s`)
  }
}

function readdirTxt(dir) {
  try {
    return readdirSync(dir).filter((f) => f.endsWith('.txt'))
  } catch { return [] }
}

const res = await main()
if (ARGS.json) {
  console.log(JSON.stringify({ ok: res.ok, code: res.code, views: res.views, changed: res.changed, not_run: res.notRun, notes: res.notes }, null, 2))
} else if (res.code === 0) {
  console.log(res.changed.length ? '\n渲染黄金已更新 ✅（记得和代码一起提交，`--reason` 已落档）' : '\n渲染验证层通过 ✅')
}
process.exit(res.code)
