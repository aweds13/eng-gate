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
const SEL_AGENT = '.turn__agent-message' // agent 回复轮次

// 授权框文案**并集**（探测结论 §9.2：路径授权 与 「高风险命令 git commit」是**两套**文案，只认一套会漏）。
// 命中即"是授权类按钮"；优先级见 pickApproval。
const APPROVE_RE = /仅本次运行|本次会话允许|始终允许|拒绝执行|允许运行|允许一次|允许本次|继续执行|继续|确认|批准|同意|允许|Allow|Approve|Accept|Continue|Run/i

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
  constructor(ws) { this.ws = ws; this.id = 0; this.pending = new Map() }

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
      throw new Error('页面里抛错：' + JSON.stringify(out.result.exceptionDetails).slice(0, 300))
    }
    return out.result?.result?.value
  }

  close() { try { this.ws.close() } catch { /* ignore */ } }
}

/** 轮询 `/json/list`，找当前 Trae 面板那条 `type=page` 且 url 含 `workbench` 的目标。 */
async function findWorkbench(port, timeoutMs) {
  const t0 = Date.now()
  while (Date.now() - t0 < timeoutMs) {
    try {
      const r = await fetch(`http://127.0.0.1:${port}/json/list`)
      if (r.ok) {
        const list = await r.json()
        const page = list.find((t) => t.type === 'page' && t.webSocketDebuggerUrl && String(t.url).includes('workbench'))
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

/** 连上 CDP：先找现成的口；找不到且允许拉起就拉 IDE 再轮询最多 60 秒。连不上返回 null。 */
async function attach(port, { launch, workspace }) {
  let page = await findWorkbench(port, 2000)
  if (!page && launch) {
    if (!existsSync(IDE_PATH)) throw new Error(`找不到 IDE：${IDE_PATH}（可用 TF_TRAE_EXE 覆盖）`)
    launchIde(port, workspace)
    page = await findWorkbench(port, 60000)
  }
  if (!page) return null
  const ws = new WebSocket(page.webSocketDebuggerUrl)
  await new Promise((res, rej) => {
    ws.onopen = res
    ws.onerror = () => rej(new Error('WebSocket 连不上 ' + page.webSocketDebuggerUrl))
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
    for (const el of document.querySelectorAll('button, [role="button"], a, div, span')) {
      const t = (el.innerText || '').replace(/\\s+/g, '');
      if (!t || t.length >= 16) continue;
      if (el.children.length) continue;
      if (!RE.test(t) || DENY.test(t)) continue;
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
  try {
    log({ ev: 'connect', port })

    // 记账：发指令**前**读一次。
    const before = await readBalance(cdp)
    log({ ev: 'balance', value: before })

    // 等输入框出现（面板可能还在渲染）。
    let ready = false
    while (Date.now() - startedAt < 30000) {
      if (await focusInput(cdp)) { ready = true; break }
      await sleep(1000)
    }
    if (!ready) {
      log({ ev: 'error', msg: 'input box not found' })
      process.stderr.write('[trae] 找不到输入框（面板没渲染出来？）\n')
      return 3
    }

    // ★ 记发送前的 agent 轮次数：完成判据要求"出现了**新的** agent 轮次"，防被上一轮的「完成。」骗。
    const baseline = (await readAgents(cdp)).count

    // 发送：insertText 打字 → Enter。
    await cdp.send('Input.insertText', { text: prompt })
    const enter = { key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13, text: '\r' }
    await cdp.send('Input.dispatchKeyEvent', { type: 'keyDown', ...enter })
    await cdp.send('Input.dispatchKeyEvent', { type: 'keyUp', ...enter })
    log({ ev: 'send', promptLen: prompt.length })

    // 盯梢：每 3 秒自动点授权 + 判完成。
    //  完成判据（★ 只看最后一条 agent 轮次 + 必须出现了**新**轮次）：
    //   · 快路径：卡规格原文 `/任务耗时/`（本机实测不出现，保留以防别的版本有）；
    //   · 实测定稿：新轮次 且 连续 2 拍 `!busy && sendDisabled===true`（生成中 send 键不带 disabled）。
    let turns = 0
    let lastText = ''
    let done = false
    let idleStreak = 0
    while (true) {
      await sleep(3000)
      const sec = Math.round((Date.now() - startedAt) / 1000)
      const label = await clickApproval(cdp)
      if (label) log({ ev: 'approve', label })
      const st = await readAgents(cdp)
      turns = st.count
      lastText = st.last || ''
      const isNew = st.count > baseline
      const idle = st.sendDisabled === true && !st.busy
      idleStreak = (isNew && idle) ? idleStreak + 1 : 0
      const isDone = isNew && (st.specDone || idleStreak >= 2)
      log({ ev: 'poll', sec, turns: st.count, lastLen: lastText.length, busy: st.busy, done: isDone })
      if (isDone) { done = true; break }
      if (Date.now() - startedAt > timeoutSec * 1000) break
    }

    // 记账：收工读**后**一次；两次都落 log。
    const after = await readBalance(cdp)
    log({ ev: 'balance', before, after })

    writeFileSync(outPath, lastText, 'utf8')
    const sec = Math.round((Date.now() - startedAt) / 1000)
    const reason = done ? 'done' : 'timeout'
    log({ ev: 'done', sec, reason })
    process.stdout.write(`[trae] ${done ? 'DONE' : 'TIMEOUT'} sec=${sec} turns=${turns} balance ${before}->${after} out=${outPath}\n`)
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

await main()
