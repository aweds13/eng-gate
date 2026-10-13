/* TraeCode 池适配器（T-G172）—— 把主控 2026-09-27 实测跑通的 Trae IDE「CDP 驱动」正式化成工具。
 *
 * 它是什么：TraeCode 免费版 IDE 的 agent 面板是一条**能跑我们整条工具链**的免费池
 * （实测：worktree 内跑完 17 门全量门禁拿到 ok=True + rc=0，见 `gates/diag/Trae池-探测结论.md`）。
 * 本工具把那晚的临时脚本固化成**两条子命令**：`balance`（读免费积分）与 `send`（发指令 → 自动授权 → 判完成 → 记账）。
 *
 * 为什么是 Node 而不是 python：驱动靠 CDP，Node 22 **内建** `WebSocket` + `fetch` —— **零新依赖**，
 * 与本仓 `tools/tf_browser.mjs` 同一套做法（照它的风格：`node:` 前缀 import、纯函数 + `main()`）。
 *
 * 它不是什么（边界，诚实写）：
 *  · **不是派活器**：契约与 `tools/wb_dispatch.py` 不同（那边是 CodeBuddy CLI 的 JSONL/429/--resume 语义），
 *    这边是 DOM，**没有** token/回合/预算这类读数，唯一的用量读数是**整数积分**。
 *  · **脆**：全是 UI 自动化，面板改版/选择器改名就废；选择器里**不钉中文文案**（文案只用在授权框判据里）。
 *  · **串行**：一个面板一次一个任务。
 *
 * ★★ 卡 218（2026-10-13）当场裁决 —— **① 保留 + 就在这里写下结论**（不另开卡删它，不装作没这回事）：
 *   本机实测这条道**不可用于派活**：面板页会**重载 / 目标更替**（新版 TRAE 的 agent 界面是
 *   `workbench.desktop.main.solo-lite*`），而驱动原来对它**零韧性** ⇒ 第 1 次真派卡
 *   （`gates/diag/trae-218.jsonl`）就是这么死的 —— WS 一断，`poll` 里的 `await` 永远不 settle
 *   ⇒ 事件循环空掉 ⇒ Node 报 `Warning: Detected unsettled top-level await … await main()` 直接退出，
 *   而**任务在面板里还在跑**（"驱动死了、活没死"）。
 *   取证四条（同日，指向同一根因）：① CDP target 从 `title=Agent` 变成 `title=` 空、url 当标题
 *   （面板页重载/跳转）；② 端口 9333 的所有者 pid 从 5692 → 22340；③ 同一时刻
 *   `Page.captureScreenshot` 只 11 KB（正常 133 KB）；④ 树里零产出（只有主控种进来的两个文件）。
 *   ⇒ 卡 218 就地补了**断线重连**（`Cdp.markDead` + `cmdSend` 的 `ensureCdp`）：断线留痕、
 *   重解析 `/json/list` 找 `solo-lite`、重连、**接着判完成**；连不上 6 拍就明确报「已失联」退 3
 *   （不再是 Node 的内部警告）。
 *   ★ 但这条道**仍不接进派活**：首选是**反向**把我们的 `pool` MCP 挂进 Trae（`.trae/mcp.json`，
 *     不需要任何登录）—— 三条路的实测与证据见 `复盘/Trae-接入结论.md`。
 *     留着本文件只为「主控遥控 Trae 面板」这一用法有据可查，且改起来半天就能再战。
 */
import { spawn } from 'node:child_process'
import { appendFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as sleep } from 'node:timers/promises'

export const HERE = dirname(fileURLToPath(import.meta.url))
export const ROOT = join(HERE, '..')

// IDE 可执行文件（探测结论 §三 实测路径）。允许用环境变量覆盖，方便换机/换安装位置。
const IDE_PATH = process.env.TF_TRAE_EXE || 'D:\\Trae CN\\Trae CN.exe'
const DEFAULT_PORT = 9333

// 实测选择器（探测结论 §三 表；★ 别钉中文文案，文案会随语言/改版变）。
const SEL_BALANCE = '.icube-titlebar-cn-free-upgrade-button' // 免费积分按钮（文本如 4,650）
const SEL_INPUT = '.chat-input-v2-input-box-editable' // 输入框（role=textbox，需先 focus）
// ★★ 卡 218（2026-10-13 CDP 实测）：新版「Agent」界面（`solo-lite`）里，**agent 的最终回答**
//   落在 **`.core-finish-card`**（实测链路：`p.markdown-p` → `.markdown-renderer` →
//   `.core-finish-card__summary` → **`.core-finish-card`** → `.agent-plan-item`）；
//   老 UI 才是 `.turn__agent-message`。⇒ **两代都认**。
//   ★ 只认老的那个时 `--out` 抽到的是界面文字（当天真抽到过「TRAE / 思考过程 / 由 AI 生成」）。
const SEL_AGENT = '.turn__agent-message, .core-finish-card' // agent 回复轮次（老 UI + 新 UI）

// 授权框文案**并集**（探测结论 §9.2：路径授权 与 「高风险命令 git commit」是**两套**文案，只认一套会漏）。
// 命中即"是授权类按钮"；优先级见 pickApproval。
// ★★ 卡 218（2026-10-13 截图实证）：这一版**必须收紧成"授权框专有文案"**。
//   老写法把「继续 / 确认 / 允许 / Run」这类**通用词**也算授权 ⇒ 新版界面上一个
//   **快捷回复芯片**（"好的，执行吧"）被它当按钮点了，于是那句话被当成**用户消息发了出去**
//   （截图实证：那条出现在**用户侧**气泡，而 agent 回了一句
//   「目前没有待执行的任务——上一条我只按要求回复了 OK…」）。
//   ⇒ 只认授权框专有文案；通用词一律不算。
const APPROVE_RE = /仅本次运行|本次会话允许|始终允许|拒绝执行|允许运行|允许一次|允许本次|允许执行|批准并运行|同意并运行/

/* ---------------------------------------------------------------- 参数解析 */

function parseArgs(argv) {
  const out = { _: [] }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    if (a.startsWith('--')) {
      const key = a.slice(2)
      if (key === 'no-launch') { out.noLaunch = true; continue }
      out[key] = argv[++i]
    } else {
      out._.push(a)
    }
  }
  return out
}

/* ---------------------------------------------------------------- JSONL 记账 */

function makeLogger(path) {
  if (path) mkdirSync(dirname(path), { recursive: true })
  return (obj) => {
    if (path) appendFileSync(path, JSON.stringify(obj) + '\n', 'utf8')
  }
}

/* ---------------------------------------------------------------- CDP */

class Cdp {
  constructor(ws) {
    this.ws = ws; this.id = 0; this.pending = new Map(); this.closed = false; this.deathWhy = ''
    // ★★ 卡 218（2026-10-13 实测，第一次派真卡就是这么死的）：
    //   WS 一断，原来那些 pending 的 Promise **永远不 settle** ⇒ `await` 永久挂起 ⇒
    //   事件循环空掉 ⇒ Node 直接退出，原样报错：
    //     `Warning: Detected unsettled top-level await at …trae_pool.mjs:400 / await main()`
    //   而任务在面板里可能还在跑 ⇒ **看着像"驱动莫名其妙死了"**。
    //   ⇒ 断线时把 pending **全部拒绝**，让"断线"变成一条**可读的失败**；再配 `send` 的超时兜底。
    //   ★ 卡 218 再进一步：`cmdSend` 拿到这个"已死"标记后**重解析 /json/list 并重连**（见 ensureCdp）。
    ws.onclose = () => this.markDead('WS 关闭（面板可能重载了）')
    ws.onerror = () => this.markDead('WS 出错（面板可能重载了）')
  }

  /** 把这条连接判死：pending 全部拒绝（回 `{__closed}` 哨兵）—— 断线由此变成**可读的失败**。 */
  markDead(why) {
    if (this.closed) return
    this.closed = true; this.deathWhy = why
    for (const [, res] of this.pending) { try { res({ __closed: why }) } catch { /* ignore */ } }
    this.pending.clear()
  }

  send(method, params = {}, timeoutMs = 30000) {
    return new Promise((res, rej) => {
      if (this.closed) { rej(new Error('CDP 连接已关闭（面板重载？）')); return }
      const id = ++this.id
      const timer = setTimeout(() => {
        if (this.pending.delete(id)) rej(new Error(`${method} 超时 ${timeoutMs}ms —— 面板可能重载了`))
      }, timeoutMs)
      this.pending.set(id, (m) => { clearTimeout(timer); res(m) })
      try {
        this.ws.send(JSON.stringify({ id, method, params }))
      } catch (e) {
        this.pending.delete(id); clearTimeout(timer); rej(e)
      }
    })
  }

  async eval(expression) {
    const out = await this.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })
    // ★ 断线时 send 会回一个 `{__closed}` 哨兵（不是 CDP 的 reply）⇒ 这里如实翻成异常。
    if (out && out.__closed) throw new Error('CDP 断了：' + out.__closed)
    if (out.result?.exceptionDetails) {
      throw new Error('页面里抛错：' + JSON.stringify(out.result.exceptionDetails).slice(0, 300))
    }
    return out.result?.result?.value
  }

  close() { try { this.ws.close() } catch { /* ignore */ } }
}

/**
 * 轮询 `/json/list`，找当前 Trae 面板那条 `type=page` 的目标。
 *
 * ★★ 卡 218（2026-10-13 实测）：**新版 TRAE 的面板页不是 `workbench.html` 了**。
 *   合并 TraeWork/TraeCode 之后的「Agent」界面，URL 是
 *   `vscode-file://vscode-app/…/vs/code/electron-browser/**solo/solo-lite.html**` ——
 *   原来写死 `includes('workbench')` ⇒ **一个都匹配不上**，直接报「连不上 CDP」，
 *   而 `curl http://127.0.0.1:9333/json/version` **明明是通的**（主控当天实测）。
 *   ⇒ 两代都认：`workbench`（老）**或** `solo-lite`（新）。
 *   ★ 顺带实测：新界面里输入框类名 **`.chat-input-v2-input-box-editable` 一字没变**
 *     （`Runtime.evaluate` 现读），所以下游那些选择器**不用跟着改**。
 */
async function findWorkbench(port, timeoutMs) {
  const t0 = Date.now()
  const looksLikePanel = (t) =>
    t.type === 'page' && t.webSocketDebuggerUrl &&
    (String(t.url).includes('workbench') || String(t.url).includes('solo-lite'))
  while (Date.now() - t0 < timeoutMs) {
    try {
      const r = await fetch(`http://127.0.0.1:${port}/json/list`)
      if (r.ok) {
        const list = await r.json()
        const page = list.find(looksLikePanel)
        if (page) return page
      }
    } catch { /* 还没起来 */ }
    await sleep(1000)
  }
  return null
}

/** 拉起 IDE（探测结论 §三）。detached+unref：本进程正常结束它继续活；被 kill 会连坐（§9.1）。 */
function launchIde(port, workspace) {
  const args = [`--remote-debugging-port=${port}`]
  if (workspace) args.push(workspace)
  const child = spawn(IDE_PATH, args, { detached: true, stdio: 'ignore' })
  child.unref()
}

/** 连上 CDP：先找现成的口；找不到且允许拉起就拉 IDE 再轮询最多 60 秒。连不上返回 null。
 *
 *  ★ 卡 218：`findMs` 可调 —— **重连**时面板刚重载，目标可能还没出现在 `/json/list`，
 *    给 2 秒太短（第一次派卡就是这么"看着像连不上"）；重连走 15 秒。
 */
async function attach(port, { launch, workspace, findMs = 2000 }) {
  let page = await findWorkbench(port, findMs)
  if (!page && launch) {
    if (!existsSync(IDE_PATH)) throw new Error(`找不到 IDE：${IDE_PATH}（可用 TF_TRAE_EXE 覆盖）`)
    launchIde(port, workspace)
    page = await findWorkbench(port, 60000)
  }
  if (!page) return null
  const ws = new WebSocket(page.webSocketDebuggerUrl)
  // ★ 卡 218：这个 await 也必须**有条退路** —— 原来只挂 onopen/onerror，
  //   而"连上又立刻被关"（面板正在重载）会让 onerror 永远不来 ⇒ 又是挂死。
  //   ⇒ 加超时 + onclose 兜底，任何一条路都 settle。
  await new Promise((res, rej) => {
    const timer = setTimeout(
      () => rej(new Error('WebSocket 打开超时（面板在重载？） ' + page.webSocketDebuggerUrl)), 15000)
    ws.onopen = () => { clearTimeout(timer); res() }
    ws.onerror = () => { clearTimeout(timer); rej(new Error('WebSocket 连不上 ' + page.webSocketDebuggerUrl)) }
    ws.onclose = () => { clearTimeout(timer); rej(new Error('WebSocket 打开即关（面板在重载？）')) }
  })
  const cdp = new Cdp(ws)
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data)
    if (m.id && cdp.pending.has(m.id)) { cdp.pending.get(m.id)(m); cdp.pending.delete(m.id) }
  }
  await cdp.send('Runtime.enable')
  return cdp
}

/* ---------------------------------------------------------------- 页面动作 */

/** 读免费积分文本（如 `4,650`）；读不到返回 null。 */
async function readBalance(cdp) {
  return await cdp.eval(`(() => {
    const el = document.querySelector(${JSON.stringify(SEL_BALANCE)});
    if (!el) return null;
    const t = (el.innerText || '').replace(/\\s+/g, ' ').trim();
    const m = t.match(/[\\d][\\d,]*/);
    return m ? m[0] : (t || null);
  })()`)
}

/** focus 输入框并返回**焦点真的在它身上**（探测结论 §三 表要求先 focus）。 */
async function focusInput(cdp) {
  return await cdp.eval(`(() => {
    const el = document.querySelector(${JSON.stringify(SEL_INPUT)});
    if (!el) return false;
    el.focus();
    return document.activeElement === el;
  })()`)
}

/** 读**最后一条** agent 轮次（★ 完成判据只看它，别看整段尾部 —— 会被上一轮的「完成。」骗）。
 *
 *  ★ 2026-09-28 实测修正（本卡冒烟）：本机 TraeCode 3.3.104 的最后一条 agent 轮次里**没有**
 *    「任务耗时」字样（卡规格给的 `done = /任务耗时/` 在本机不成立，实测 300 秒白等到超时）。
 *    实测真正的工作态/完成态判据是**发送键的 disabled 状态**：
 *     · 生成中：`.chat-input-v2-send-button` **不带 disabled**（它此刻是"停止"键）、last 含 busy 关键词；
 *     · 完成：send 键**带 disabled**、last 不含 busy 关键词、任务列表出现「任务完成」。
 *    （探针读数：生成中 `busy:true, sendDisabled:false`；完成 `busy:false, sendDisabled:true`。）
 *    下面把 `specDone`（卡规格原判据，保留作快路径）与 `sendDisabled` 都返回，由调用方判完成。
 *
 *  ★ 另一处实测（同一冒烟）：最后一条 `.turn__agent-message` 的 innerText 里会**混进 chrome 小挂件**
 *    （实测两个：一个回显"之前某条用户话"，一个是"好的，执行吧"这类建议块）—— 直接当回复会脏。
 *    结构上：**正文与工具块都带 `data-item-type`**（`turn:assistant-avatar` / `task:explore-group` /
 *    `plan-item:toolcall` / `widget:action-bar`…），而那两个脏挂件是**没有 `data-item-type` 的 `container-*`**。
 *    所以取"有 `data-item-type` 或含 `.markdown-renderer`"的直接子块拼接（不钉任何 hash class，
 *    也不靠中文文案）。实测该法**保留工具输出**（`任务耗时` / `已执行 N 条命令`）且**丢掉脏挂件**。
 */
async function readAgents(cdp) {
  return await cdp.eval(`(() => {
    const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
    const agents = [...document.querySelectorAll(${JSON.stringify(SEL_AGENT)})];
    let last = '';
    if (agents.length) {
      const el = agents[agents.length - 1];
      last = [...el.children]
        .filter((c) => c.getAttribute('data-item-type') || c.querySelector('.markdown-renderer'))
        .map((c) => c.innerText)
        .filter((t) => norm(t))
        .join('\\n\\n');
    }
    const busy = /思考中|正在执行命令|正在规划下一步|执行中/.test(last);
    const specDone = /任务耗时/.test(last) && !busy;
    const sb = document.querySelector('.chat-input-v2-send-button');
    const sendDisabled = sb ? sb.hasAttribute('disabled') : false;
    return { count: agents.length, last, busy, specDone, sendDisabled };
  })()`)
}

/** 扫授权框并按**文案**点最合适的一个（不按 class）。返回点中的文案，没点到返回 null。
 *
 *  优先级：本次会话允许 → 始终允许 → 允许运行|允许一次|继续|确认 → 其余；
 *  ★ 命中「拒绝/取消/Deny/Reject/Cancel」的一律跳过；只认可见、无子元素、去空白后 < 16 字的。
 */
async function clickApproval(cdp) {
  return await cdp.eval(`(() => {
    const RE = ${APPROVE_RE.toString()};
    const DENY = /拒绝|取消|Deny|Reject|Cancel/i;
    const prio = (t) => {
      if (/本次会话允许/.test(t)) return 0;
      if (/始终允许/.test(t)) return 1;
      if (/允许运行|允许一次|继续|确认/.test(t)) return 2;
      return 3;
    };
    const cands = [];
    // ★★ 卡 218（2026-10-13 实测）：**只扫真按钮**，而且**排除**输入区 / 会话列表 / 侧栏。
    //   老写法扫 「button, [role=button], a, div, span」 且只要求"叶子 + 文案命中" ⇒
    //   新版界面上的**快捷回复芯片**（div/span）会被当成授权按钮点掉。
    for (const el of document.querySelectorAll('button, [role="button"], a')) {
      const t = (el.innerText || '').replace(/\\s+/g, '');
      if (!t || t.length >= 16) continue;
      if (el.children.length) continue;
      if (!RE.test(t) || DENY.test(t)) continue;
      if (el.closest('.chat-input-v2-input-box-editable, .task-list-group-sortable-wrapper, [class*="task-list"]')) continue;
      const r = el.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0) continue;
      const st = getComputedStyle(el);
      if (st.display === 'none' || st.visibility === 'hidden' || Number(st.opacity) === 0) continue;
      cands.push({ el, t, p: prio(t), area: r.width * r.height });
    }
    if (!cands.length) return null;
    cands.sort((a, b) => a.p - b.p || a.area - b.area);
    cands[0].el.click();
    return cands[0].t;
  })()`)
}

/* ---------------------------------------------------------------- 子命令 */

async function cmdBalance(argv) {
  const args = parseArgs(argv)
  const port = Number(args.port || DEFAULT_PORT)
  let cdp
  try {
    cdp = await attach(port, { launch: false })
  } catch (e) {
    process.stderr.write(`[trae] ${e.message}\n`)
    return 2
  }
  if (!cdp) {
    process.stderr.write(`[trae] 连不上 CDP（127.0.0.1:${port}）—— IDE 没开着？\n`)
    return 2
  }
  try {
    const v = await readBalance(cdp)
    if (v == null) { process.stderr.write('[trae] 页面上没读到余额元素\n'); return 2 }
    process.stdout.write(v + '\n')
    return 0
  } finally { cdp.close() }
}

async function cmdSend(argv) {
  const args = parseArgs(argv)
  const port = Number(args.port || DEFAULT_PORT)
  const workspace = args.workspace || null
  const promptFile = args['prompt-file']
  const logPath = args.log
  const outPath = args.out
  const timeoutSec = Number(args['timeout-sec'] || 3600)
  const noLaunch = Boolean(args.noLaunch)
  if (!promptFile || !logPath || !outPath) {
    process.stderr.write('用法：node tools/trae_pool.mjs send --workspace <目录> --prompt-file <文件> --log <jsonl> --out <md> [--port 9333] [--timeout-sec 3600] [--no-launch]\n')
    return 2
  }
  const log = makeLogger(logPath)
  const prompt = readFileSync(promptFile, 'utf8')

  let cdp
  try {
    cdp = await attach(port, { launch: !noLaunch, workspace })
  } catch (e) {
    log({ ev: 'error', msg: 'launch/connect failed: ' + e.message })
    process.stderr.write(`[trae] ${e.message}\n`)
    return 2
  }
  if (!cdp) {
    log({ ev: 'error', msg: `connect failed (port ${port})` })
    process.stderr.write(`[trae] 连不上 CDP（127.0.0.1:${port}）\n`)
    return 2
  }

  const startedAt = Date.now()
  // ★★ 卡 218：断线重连的读数 —— 都落进 JSONL（断线**留痕**），最后进 stdout 那行。
  let disconnects = 0
  let reconnects = 0
  let lost = false

  /** 连接是活的就放行；判死了就**重解析 `/json/list` 找 `solo-lite` 目标并重连**。
   *
   *  返回 false = 这一拍连不上（由调用方累计 `lostStreak`，够数就明说「已失联」退 3）。
   *  ★ 为什么不是"直接抛"：抛出去会带走 `main()`，回到"Node 内部警告"那条老路 ——
   *    卡 218 的死法正是**进程死了、活还在跑**；这里坚持"每一拍都有结论"。
   */
  async function ensureCdp() {
    if (!cdp.closed) return true
    disconnects += 1
    log({ ev: 'disconnect', why: cdp.deathWhy || '连接已关闭',
          sec: Math.round((Date.now() - startedAt) / 1000) })
    let fresh = null
    try {
      fresh = await attach(port, { launch: false, findMs: 15000 })
    } catch (e) {
      log({ ev: 'reconnect', ok: false, msg: e.message })
      return false
    }
    if (!fresh) {
      log({ ev: 'reconnect', ok: false, msg: '重解析 /json/list 没找到 solo-lite 目标' })
      return false
    }
    cdp = fresh
    reconnects += 1
    log({ ev: 'reconnect', ok: true, sec: Math.round((Date.now() - startedAt) / 1000) })
    return true
  }

  try {
    log({ ev: 'connect', port })

    // 记账：发指令**前**读一次。
    const before = await readBalance(cdp)
    log({ ev: 'balance', value: before })

    // 等输入框出现（面板可能还在渲染/重载 —— 期间断线照样重连）。
    let ready = false
    while (Date.now() - startedAt < 30000) {
      if (await ensureCdp() && await focusInput(cdp)) { ready = true; break }
      await sleep(1000)
    }
    if (!ready) {
      log({ ev: 'error', msg: 'input box not found' })
      process.stderr.write('[trae] 找不到输入框（面板没渲染出来？）\n')
      return 3
    }

    // ★ 记发送前的 agent 轮次数：完成判据要求"出现了**新的** agent 轮次"，防被上一轮的「完成。」骗。
    const baseline = (await readAgents(cdp)).count

    // 发送：insertText 打字 → Enter。★ 发指令这一刻断了**不重发**（会重复提问）—— 如实报错退 3。
    try {
      await cdp.send('Input.insertText', { text: prompt })
      const enter = { key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13, text: '\r' }
      await cdp.send('Input.dispatchKeyEvent', { type: 'keyDown', ...enter })
      await cdp.send('Input.dispatchKeyEvent', { type: 'keyUp', ...enter })
    } catch (e) {
      cdp.markDead('发指令时读页面失败：' + e.message)
      log({ ev: 'error', msg: 'send failed（不重发，避免重复提问）: ' + e.message })
      process.stderr.write(`[trae] 发指令失败（不重发）：${e.message}\n`)
      return 3
    }
    log({ ev: 'send', promptLen: prompt.length })

    // 盯梢：每 3 秒自动点授权 + 判完成。每一拍都先 ensureCdp（断线 ⇒ 重连 ⇒ 接着判）。
    //  完成判据（★ 只看最后一条 agent 轮次）：
    //   · 快路径：卡规格原文 `/任务耗时/`（本机实测不出现，保留以防别的版本有）；
    //   · 实测定稿：新轮次 且 连续 2 拍 `!busy && sendDisabled===true`（生成中 send 键不带 disabled）；
    //   · ★ 卡 218：**重连过之后**轮次数会被面板重载冲掉 ⇒ 不再要求"新轮次"，
    //     改成"**非空回答** 且 连续 2 拍 `!busy && sendDisabled===true`"。
    let turns = 0
    let lastText = ''
    let done = false
    let idleStreak = 0
    let lostStreak = 0
    while (true) {
      await sleep(3000)
      const sec = Math.round((Date.now() - startedAt) / 1000)
      if (!(await ensureCdp())) {
        lostStreak += 1
        if (lostStreak >= 6) {
          lost = true
          log({ ev: 'lost', sec, msg: '连不上面板（重解析 /json/list 也找不到 solo-lite 目标）' })
          break
        }
        continue
      }
      lostStreak = 0
      let label = null
      let st = null
      try {
        label = await clickApproval(cdp)
        st = await readAgents(cdp)
      } catch (e) {
        // 这一拍读挂了（超时 / 断线 / 页面抛错）—— 判死这条连接，下一拍走重连（**不当成功**）。
        cdp.markDead('这一拍读页面失败：' + e.message)
        log({ ev: 'poll-error', sec, msg: e.message })
        continue
      }
      if (label) log({ ev: 'approve', label })
      turns = st.count
      lastText = st.last || ''
      const isNew = reconnects > 0 ? lastText.length > 0 : st.count > baseline
      const idle = st.sendDisabled === true && !st.busy
      idleStreak = (isNew && idle) ? idleStreak + 1 : 0
      const isDone = isNew && (st.specDone || idleStreak >= 2)
      log({ ev: 'poll', sec, turns: st.count, lastLen: lastText.length, busy: st.busy, done: isDone })
      if (isDone) { done = true; break }
      if (Date.now() - startedAt > timeoutSec * 1000) break
    }

    // 记账：收工读**后**一次；两次都落 log。（读不到就如实记 null，不是失败。）
    let after = null
    try { after = await readBalance(cdp) } catch { after = null }
    log({ ev: 'balance', before, after })

    writeFileSync(outPath, lastText, 'utf8')
    const sec = Math.round((Date.now() - startedAt) / 1000)
    const reason = done ? 'done' : (lost ? 'lost' : 'timeout')
    log({ ev: 'done', sec, reason, disconnects, reconnects, lost })
    process.stdout.write(
      `[trae] ${done ? 'DONE' : (lost ? 'LOST' : 'TIMEOUT')} sec=${sec} turns=${turns}`
      + ` disconnect=${disconnects} reconnect=${reconnects} balance ${before}->${after} out=${outPath}\n`)
    return done ? 0 : 3
  } finally {
    cdp.close()
  }
}

/* ---------------------------------------------------------------- 入口 */

async function main() {
  const argv = process.argv.slice(2)
  const cmd = argv[0]
  let code
  if (cmd === 'balance') code = await cmdBalance(argv.slice(1))
  else if (cmd === 'send') code = await cmdSend(argv.slice(1))
  else {
    process.stderr.write('用法：node tools/trae_pool.mjs balance [--port 9333]\n')
    process.stderr.write('      node tools/trae_pool.mjs send --workspace <目录> --prompt-file <文件> --log <jsonl> --out <md> [--port 9333] [--timeout-sec 3600] [--no-launch]\n')
    code = 2
  }
  process.exitCode = code
}

// ★ 卡 218：顶层**显式兜底** —— 任何没接住的异常都变成一条**可读的失败** + 明确的退出码，
//   而不是 `Warning: Detected unsettled top-level await … await main()`（第一次派卡就是这么死的：
//   进程退出、面板里的活却还在跑）。`main()` 内部已把断线做成"每一拍都有结论"，
//   这里只兜最后一层。
await main().catch((e) => {
  process.stderr.write(`[trae] 没跑成：${e && e.message ? e.message : e}\n`)
  process.exitCode = 3
})
