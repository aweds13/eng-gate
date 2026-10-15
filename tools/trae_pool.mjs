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
 *
 * ★★ 卡 227（T-G343，2026-10-14）—— **多开窗口时选面板**（本卡只动本文件）：
 *   病：原来只会拿**第一个** `solo-lite` 页面（`findWorkbench` 里的 `list.find`）⇒ 用户多开 Trae 时，
 *   活可能被派进**不是他想要的那个窗口**；也看不见"现在到底有几个面板"。
 *   ★ 卡 218 里我试补过一次 `--target`，**补丁打在陈旧文本上、静默没生效** —— `--target` 报
 *     "连不上 CDP"，其实是参数根本没接上（`parseArgs` 收下了却没人用）。本卡把它**接对**：
 *     ① `--target "#N"`（**1 基**，第 N 个面板）或 `--target <子串>`（按 URL/标题子串匹配）；
 *     ② 匹配**不唯一**或**匹配不到** ⇒ **在连面板之前就停手并列出所有候选**（不许"随便挑一个"）；
 *     ③ 不给 `--target` ⇒ 走老路（第一个面板），**行为逐字不变**；
 *     ④ 只读子命令 `list`（也认 `--list`）列出所有可驱动面板（序号 / 标题 / URL / 是否已有会话），
 *        给 `--target` 当索引；
 *     ⑤ 判据 `selftest`（纯函数，不需要 Trae）钉住上面三条 + 越界 —— ★ 为什么判据在本文件里、
 *        不另开 `tests/`：本卡栅栏 `gates/diag/batch/B-20261017.toml` 的成员 227
 *        `paths = ["tools/trae_pool.mjs"]` —— 另开测试文件就是**域外改动**（`wb_review` ⑥ 拒）。
 *   ★ 边界（诚实写）：`--target "#N"` 的 N 是**这次 `/json/list` 里的出现序号**，面板增减会漂；
 *     断了线重连时优先按 **target id / 标题**锁回原面板（同代面板的 URL 一模一样，不能靠 URL 认）。
 *
 * ★★ 卡 245（T-G366，2026-10-15）—— 两处硬伤：**模型切换点不到** + **残留 1 字就静默不发**（本卡只动本文件）：
 *   ① `send` 支持 `--model <名字>`：开下拉 → 逐项扫描（目标项 `scrollIntoView` 滚进**可点区域**再点，
 *      下拉不会自动滚 ⇒ 坐标点击会落空）→ 点选后**回读当前模型名并比对**：不一致 / 核不到 ⇒
 *      **非零退出并打原话**（★ 不许"点了就当成功"）。名字**大小写/前后缀宽松匹配但必须唯一**，
 *      0 个 / 多个候选 ⇒ **停手并列出候选**（照 `--target` 已有口径）。
 *   ② 发送前先读输入框：非空**且**不是本次要发的内容 ⇒ 先清空（选区全选 + Delete，**只圈输入框自己**，
 *      不用全局 Ctrl+A —— 免得焦点不在输入框时把会话选进去）再重新输入；清不干净 ⇒ **停手退 3**；
 *      发送后**核验真的发出去了**（输入框变空，或会话里出现本次内容）—— 核不到 ⇒ **退 3 并说明**，
 *      不再"只打一行警告就退 0"。
 *   ③ 判据：`selftest` 扩充（`--model` 唯一性 / 回读比对短路 ⇒ 必须失败 / 清空短路 ⇒ 必须失败），
 *      卡 227 既有用例（面板选择那段）一条没删。
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

/* ------------------------------------------------- 卡 227：面板枚举 + --target 选择 */

/** 什么算「可驱动的面板」：`type=page` 且有 ws 调试口，URL 含 `workbench`（老）或 `solo-lite`（新）。
 *  与卡 218 的 `findWorkbench` 同一口径，抽成常量避免两份判据各自演化。 */
const PANEL_HINT = /workbench|solo-lite/

/**
 * ★ 纯函数（可单测、不碰 CDP）：从 `/json/list` 的**原始 target 数组**里挑出所有可驱动面板，
 * **保持原顺序**，加上 1 基序号。`--target "#N"` / `--list` 都以它为准。
 *
 * 返回 [{ index, id, title, url, webSocketDebuggerUrl }]（index 从 1 起 —— **本工具用 1 基**）。
 */
export function panelsOf(targets) {
  const out = []
  for (const t of targets || []) {
    if (!t || t.type !== 'page' || !t.webSocketDebuggerUrl) continue
    const url = String(t.url || '')
    if (!PANEL_HINT.test(url)) continue
    out.push({
      index: out.length + 1,
      id: String(t.id || ''),
      title: String(t.title || ''),
      url,
      webSocketDebuggerUrl: String(t.webSocketDebuggerUrl),
    })
  }
  return out
}

/**
 * ★ 纯函数（可单测、不碰 CDP）：按 `--target` 选面板。**不许"随便挑一个"**。
 *
 *  · `target` 不给（null/''）⇒ 返回第一个 —— ★ 与老行为**逐字一致**（老代码就是 `list.find` 取首个）。
 *  · `target === "#N"` ⇒ 第 N 个（**1 基**：`#1` 是第一个）；越界 ⇒ 停手。
 *  · 其它 ⇒ 在 **URL 或标题**里找**子串**；命中 1 个才回；0 个 / ≥2 个 ⇒ 停手（由调用方列候选）。
 *
 * 返回 `{ ok, panel?, code?, reason? }`；`code` ∈ {first,index,nomatch,ambiguous,none,range}。
 */
export function pickPanel(panels, target) {
  const list = panels || []
  if (list.length === 0) return { ok: false, code: 'none', reason: '一个可驱动面板都没有' }
  if (target == null || target === '') return { ok: true, code: 'first', panel: list[0] }
  const s = String(target)
  const m = /^#(\d+)$/.exec(s)
  if (m) {
    const n = Number(m[1])
    if (n < 1 || n > list.length) {
      return { ok: false, code: 'range',
               reason: `--target ${s} 越界：只有 ${list.length} 个面板（1..${list.length}，**1 基**）` }
    }
    return { ok: true, code: 'index', panel: list[n - 1] }
  }
  const hits = list.filter((p) => String(p.url).includes(s) || String(p.title).includes(s))
  if (hits.length === 0) {
    return { ok: false, code: 'nomatch', reason: `--target ${JSON.stringify(s)} 谁都匹配不上` }
  }
  if (hits.length > 1) {
    return { ok: false, code: 'ambiguous',
             reason: `--target ${JSON.stringify(s)} 匹配到 ${hits.length} 个 —— 不唯一，不许随便挑` }
  }
  return { ok: true, code: 'substr', panel: hits[0] }
}

/** 把面板列成**候选清单**（`--list` 与「停手列候选」共用一份格式）：序号 / 标题 / URL / 会话。 */
export function formatPanels(panels) {
  if (!panels || panels.length === 0) return '  （一个可驱动面板都没有）\n'
  return panels
    .map((p) => `  #${p.index}\t${p.title || '(无标题)'}\t${p.url}\t${p.session || '会话：未探'}`)
    .join('\n') + '\n'
}

/* ------------------------------------- 卡 245：模型匹配与发送核验（纯函数，可单测、不碰 CDP） */

/** 归一化：压空白 + 转小写（大小写/空白宽松匹配的底座）。 */
function normText(s) {
  return String(s == null ? '' : s).replace(/\s+/g, ' ').trim().toLowerCase()
}

/**
 * ★ 卡 245 纯函数：在候选模型名里找 `wanted`。**宽松匹配但必须唯一，不许"随便挑一个"**。
 *
 *  · 归一化后**相等** ⇒ exact；否则**前缀/后缀**（双向）⇒ loose；
 *  · 命中 0 个 / ≥2 个 ⇒ 停手（由调用方列候选，同 `--target` 口径）。
 *
 * 返回 `{ ok, code, model? }`；`code` ∈ {exact,loose,nomatch,ambiguous,empty}。
 */
export function matchModel(candidates, wanted) {
  const list = (candidates || []).map((c) => String(c))
  const nw = normText(wanted)
  if (!nw) return { ok: false, code: 'empty', reason: '--model 不能为空' }
  const exact = list.filter((t) => normText(t) === nw)
  let hits = exact
  let code = 'exact'
  if (hits.length === 0) {
    hits = list.filter((t) => {
      const nt = normText(t)
      return nt.startsWith(nw) || nw.startsWith(nt) || nt.endsWith(nw) || nw.endsWith(nt)
    })
    code = 'loose'
  }
  if (hits.length === 0) {
    return { ok: false, code: 'nomatch',
             reason: `--model ${JSON.stringify(String(wanted))} 没有候选匹配得上`,
             candidates: list }
  }
  if (hits.length > 1) {
    return { ok: false, code: 'ambiguous',
             reason: `--model ${JSON.stringify(String(wanted))} 宽松匹配到 ${hits.length} 个 —— 不唯一，不许随便挑`,
             candidates: list }
  }
  return { ok: true, code, model: hits[0] }
}

/**
 * ★ 卡 245 纯函数：**切换后回读比对** —— "点了"不算成功，回读一致才算。
 *
 *  · 回读不到（空/没读到）⇒ `unreadable`（核验被短路就栽在这里 —— **不核验不算成功**）；
 *  · 回读与 wanted 对不上 ⇒ `mismatch`；
 *  · 一致（宽松口径，复用 matchModel）⇒ ok。
 */
export function judgeModelSwitch(wanted, readBack) {
  const rb = String(readBack == null ? '' : readBack).replace(/\s+/g, ' ').trim()
  if (!rb) {
    return { ok: false, code: 'unreadable',
             reason: '回读不到当前模型名 —— 核不到不算切换成功' }
  }
  const m = matchModel([rb], wanted)
  if (!m.ok) {
    return { ok: false, code: 'mismatch',
             reason: `回读到的模型名是 ${JSON.stringify(rb)}，与 --model ${JSON.stringify(String(wanted))} 对不上` }
  }
  return { ok: true, code: m.code, model: rb }
}

/**
 * ★ 卡 245 纯函数：**发送核验** —— 判"真的发出去了"。
 *
 *  · 输入框变空 ⇒ ok `input-empty`（最强信号）；
 *  · 会话里出现本次内容 ⇒ ok `chat-match`；
 *  · 输入框仍残留内容 ⇒ **失败** `residual`（残留不许静默）；
 *  · 输入框读不到、会话里也没有 ⇒ **失败** `unverifiable`（核不到不许当成功）。
 *  `prompt` 自己为空 ⇒ 无从核起，一律失败。
 */
export function judgeSend(prompt, { inputAfter, chatHasPrompt } = {}) {
  const p = normText(prompt)
  if (!p) return { ok: false, code: 'empty', reason: '要发的内容是空的，无从核验' }
  const inp = inputAfter == null ? null : normText(inputAfter)
  if (inp === '') return { ok: true, code: 'input-empty' }
  if (chatHasPrompt === true) return { ok: true, code: 'chat-match' }
  if (inp == null) {
    return { ok: false, code: 'unverifiable',
             reason: '发送后核不到：输入框读不到，会话里也没找到本次内容' }
  }
  return { ok: false, code: 'residual',
           reason: `发送后输入框仍残留 ${inp.length} 字 —— 没发出去（残留不许静默）` }
}

/**
 * ★ 卡 245 纯函数：发送前读到的输入框内容 ⇒ 要不要清。
 *
 *  · 空 ⇒ 不清（`clean`）；
 *  · 恰是本次要发的内容（如上一轮打完没发）⇒ 不清也**不重输**（防重复），只补发送（`already-typed`）；
 *  · 别的残留 ⇒ 必须先清（`residual`）。
 */
export function decideClear(before, prompt) {
  const b = normText(before)
  if (!b) return { clear: false, code: 'clean' }
  if (b === normText(prompt)) return { clear: false, code: 'already-typed' }
  return { clear: true, code: 'residual' }
}

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
  while (Date.now() - t0 < timeoutMs) {
    try {
      const r = await fetch(`http://127.0.0.1:${port}/json/list`)
      if (r.ok) {
        const panels = panelsOf(await r.json())
        if (panels.length) return panels[0]   // ★ 卡 227：仍取**第一个**（不给 --target 时的老行为）
      }
    } catch { /* 还没起来 */ }
    await sleep(1000)
  }
  return null
}

/** ★ 卡 227：一次拉全**可驱动面板**（不是只找第一个）。返回 null = **连不上 CDP**（与
 *  「连上了但 0 个面板」的 `[]` 区分开 —— 前者是"CDP 没开"，后者是"开着但没有面板"）。 */
async function fetchPanels(port, timeoutMs = 3000) {
  const t0 = Date.now()
  while (Date.now() - t0 < timeoutMs) {
    try {
      const r = await fetch(`http://127.0.0.1:${port}/json/list`)
      if (r.ok) return panelsOf(await r.json())
    } catch { /* 还没起来 */ }
    await sleep(300)
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

/** 连上**指定**面板（卡 227 抽出，供"选好的那个面板"复用）。连不上抛错（调用方决定怎么收）。 */
async function connectPage(page) {
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

/** ★ 卡 227：只读探一个面板**是否已有会话**（逐个面板接一下、数 agent 轮次）。**绝不动它**。
 *  best-effort：接不上 / 读不到 ⇒ 回 `会话：未知`（不猜、不当失败）。 */
async function probeSession(panel) {
  let cdp = null
  try {
    cdp = await connectPage(panel)
    const n = await cdp.eval(`document.querySelectorAll(${JSON.stringify(SEL_AGENT)}).length`)
    if (typeof n === 'number') return n > 0 ? `有会话(${n})` : '空(0)'
    return '会话：未知'
  } catch {
    return '会话：未知'
  } finally {
    if (cdp) cdp.close()
  }
}

/** 连上 CDP：先找现成的口；找不到且允许拉起就拉 IDE 再轮询最多 60 秒。连不上返回 null。
 *
 *  ★ 卡 218：`findMs` 可调 —— **重连**时面板刚重载，目标可能还没出现在 `/json/list`，
 *    给 2 秒太短（第一次派卡就是这么"看着像连不上"）；重连走 15 秒。
 *  ★ 卡 227：**不给 --target 时**这条老路逐字未改（取第一个面板）。
 */
async function attach(port, { launch, workspace, findMs = 2000 }) {
  let page = await findWorkbench(port, findMs)
  if (!page && launch) {
    if (!existsSync(IDE_PATH)) throw new Error(`找不到 IDE：${IDE_PATH}（可用 TF_TRAE_EXE 覆盖）`)
    launchIde(port, workspace)
    page = await findWorkbench(port, 60000)
  }
  if (!page) return null
  return await connectPage(page)
}

/** ★ 卡 227：按 `--target` 选面板**并**连上去。返回 `{ code, cdp?, panel? }`（code===0 才是连上了）。
 *
 *  顺序**刻意**是"先选、后连"：匹配不唯一 / 匹配不到 / 越界 ⇒ **一个面板都不连**，停手 + 列候选。
 *  ★ 这正是卡 218 那个坑的反面 —— 那次 `--target` 没接上，于是**盲连第一个**、报一句
 *    "连不上 CDP"，把"参数没生效"伪装成"网络问题"。这里让"没选成"变成一条**说谎不出口**的失败。
 */
async function connectTarget(port, target, { launch, workspace, log = null }) {
  let panels = await fetchPanels(port, 2000)
  if ((panels == null || panels.length === 0) && launch) {
    if (!existsSync(IDE_PATH)) {
      process.stderr.write(`[trae] 找不到 IDE：${IDE_PATH}（可用 TF_TRAE_EXE 覆盖）\n`)
      return { code: 2 }
    }
    launchIde(port, workspace)
    panels = await fetchPanels(port, 60000)
  }
  if (panels == null) {
    process.stderr.write(`[trae] 连不上 CDP（127.0.0.1:${port}）\n`)
    return { code: 2 }
  }
  const pick = pickPanel(panels, target)
  if (!pick.ok) {
    // ★ 必须：**停手** + **列出所有候选**（不许"随便挑一个"）。
    process.stderr.write(`[trae] 选面板停手：${pick.reason}\n`)
    process.stderr.write(`[trae] 候选（本机 ${panels.length} 个可驱动面板；--target 可用 "#N" 或子串）：\n`)
    process.stderr.write(formatPanels(panels))
    if (pick.code === 'ambiguous') {
      process.stderr.write(`[trae] 提示：改 --target "#1".."#${panels.length}" 指到想用的那一个（1 基）\n`)
    } else if (pick.code === 'nomatch') {
      process.stderr.write('[trae] 提示：子串要能在某个面板的 URL 或标题里找得到\n')
    } else if (pick.code === 'range') {
      process.stderr.write('[trae] 提示：--target "#N" 是 **1 基**（第 1 个就是 "#1"）\n')
    }
    if (log) {
      log({ ev: 'target', ok: false, code: pick.code, reason: pick.reason,
            panels: panels.map((p) => p.url) })
    }
    return { code: 2 }
  }
  if (log) log({ ev: 'target', ok: true, how: pick.code, index: pick.panel.index, url: pick.panel.url })
  const cdp = await connectPage(pick.panel)   // 连不上会抛，由调用方 catch 收
  return { code: 0, cdp, panel: pick.panel }
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

/* ------------------------------------------------- 卡 245：模型下拉驱动 + 发送核验（DOM） */

/** 模型名字样（`gates/diag/_cdp_models.mjs` 实测正则，照抄 —— 只用来"找出像模型名的叶子"，
 *  唯一性由 matchModel 把关，这里宁滥勿缺）。 */
const MODEL_HINT = /GLM|DeepSeek|Kimi|Claude|GPT|Qwen|Doubao|Hunyuan|MiniMax|Flash|Pro|Max/i

/** 扫页面上所有"像模型名的可见叶子"。返回 [{text,x,y,inInput}]（不去重，调用方去重）。
 *  ★ 实测（卡 245 真机第一跑）：输入区里还有「Max」这种**模式开关**叶子也命中家族词 ——
 *    再要求**含数字**（模型名都带版本号：GLM-5.3-FlashX / Kimi-K3 / MiMo-V2.6-Pro…；"Max"/"Pro" 裸词不算）。 */
async function scanModelLeafs(cdp) {
  return await cdp.eval(`(() => {
    const RE = ${MODEL_HINT.toString()};
    const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
    const out = [];
    for (const el of document.querySelectorAll('div,span,li,button,p')) {
      if (el.children.length) continue;
      const t = norm(el.innerText);
      if (!t || t.length > 44 || !RE.test(t) || !/\\d/.test(t)) continue;
      const r = el.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0) continue;
      const st = getComputedStyle(el);
      if (st.display === 'none' || st.visibility === 'hidden' || Number(st.opacity) === 0) continue;
      out.push({ text: t, x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2),
                 inInput: !!el.closest('[class*="chat-input"]') });
    }
    return out;
  })()`)
}

/** 按文本去重（保持原序，同文取第一个）。 */
function dedupLeafs(leafs) {
  const seen = new Set()
  const out = []
  for (const l of leafs || []) {
    if (!l || seen.has(l.text)) continue
    seen.add(l.text); out.push(l)
  }
  return out
}

/** 读"当前模型名"：优先取**输入区里**的模型叶子；恰好一种字样才算读到了（多种 ⇒ 如实说不唯一）。 */
async function readCurrentModel(cdp) {
  const leafs = dedupLeafs(await scanModelLeafs(cdp))
  const inInput = leafs.filter((l) => l.inInput)
  const pool = inInput.length ? inInput : leafs
  const texts = [...new Set(pool.map((l) => l.text))]
  if (texts.length !== 1) return { ok: false, texts }
  return { ok: true, model: texts[0], texts }
}

/** 鼠标三连（探测结论：下拉/模型项要真坐标点击，`el.click()` 不一定走 UI 事件链）。 */
async function clickAt(cdp, x, y) {
  const mv = { type: 'mouseMoved', x, y }
  await cdp.send('Input.dispatchMouseEvent', mv)
  await cdp.send('Input.dispatchMouseEvent', { ...mv, type: 'mousePressed', button: 'left', clickCount: 1 })
  await cdp.send('Input.dispatchMouseEvent', { ...mv, type: 'mouseReleased', button: 'left', clickCount: 1 })
}

/** Esc 关下拉（开着才有关的效果；已关则无害）。 */
async function pressEscape(cdp) {
  const esc = { key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27, nativeVirtualKeyCode: 27 }
  await cdp.send('Input.dispatchKeyEvent', { type: 'keyDown', ...esc })
  await cdp.send('Input.dispatchKeyEvent', { type: 'keyUp', ...esc })
}

/** 读输入框内容（contenteditable 用 innerText；读不到元素返回 null）。 */
async function readInput(cdp) {
  return await cdp.eval(`(() => {
    const el = document.querySelector(${JSON.stringify(SEL_INPUT)});
    if (!el) return null;
    return (el.innerText || el.value || '');
  })()`)
}

/** 清空输入框：**只圈输入框自己**的选区全选 + Delete（不用全局 Ctrl+A —— 焦点不在输入框时
 *  会把整个会话选进去，Delete 就成删消息了）。返回全选是否成了。 */
async function clearInput(cdp) {
  const focused = await cdp.eval(`(() => {
    const el = document.querySelector(${JSON.stringify(SEL_INPUT)});
    if (!el) return false;
    el.focus();
    if (document.activeElement !== el) return false;
    const sel = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(el);
    sel.removeAllRanges();
    sel.addRange(range);
    return true;
  })()`)
  if (!focused) return false
  const del = { key: 'Delete', code: 'Delete', windowsVirtualKeyCode: 46, nativeVirtualKeyCode: 46 }
  await cdp.send('Input.dispatchKeyEvent', { type: 'keyDown', ...del })
  await cdp.send('Input.dispatchKeyEvent', { type: 'keyUp', ...del })
  return true
}

/** 会话里（**刨掉输入框自己**，防"残留还在输入框里"被当成本次内容）有没有出现本次内容头。 */
async function chatHasPrompt(cdp, head) {
  if (!head) return false
  return await cdp.eval(`(() => {
    const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
    const el = document.querySelector(${JSON.stringify(SEL_INPUT)});
    let txt = norm(document.body ? document.body.innerText : '');
    if (el) {
      const t = norm(el.innerText || '');
      if (t) { const i = txt.indexOf(t); if (i >= 0) txt = txt.slice(0, i) + ' ' + txt.slice(i + t.length) }
    }
    return txt.includes(${JSON.stringify(head)});
  })()`)
}

/**
 * ★ 卡 245：把模型切到 `wanted`。返回 `{ code, model? }`。
 *
 *  code 0=切好且回读一致；2=没选成就停手（触发器/候选不唯一或没有候选 —— 已列候选）；
 *  3=点了但核不到 / 回读不一致（★ 不许"点了就当成功"）。
 *
 *  下拉定位：点触发器开下拉 → 扫全部"像模型名的叶子"当候选 → 目标项 `scrollIntoView` 滚进
 *  **可点区域**（实测下拉不会自动滚，坐标点击会落空）→ 真坐标点击 → Esc 收尾 → 回读比对。
 */
async function switchModel(cdp, wanted, { log = null } = {}) {
  // ① 快路径：当前模型已经是它 ⇒ 不动下拉（回读一致是平凡的）。
  let cur = null
  try { cur = await readCurrentModel(cdp) } catch { cur = null }
  if (cur && cur.ok) {
    const fast = matchModel([cur.model], wanted)
    if (fast.ok) {
      if (log) log({ ev: 'model', ok: true, code: 'already', model: cur.model })
      process.stderr.write(`[trae] 当前模型已是 ${cur.model}，无需切换\n`)
      return { code: 0, model: cur.model }
    }
  }
  // ② 找触发器（当前模型名那枚叶子，优先输入区里的）。
  if (!cur || !cur.ok) {
    const why = cur == null
      ? '读页面失败，找不到当前模型名'
      : (cur.texts.length === 0
          ? '页面上找不到模型名的叶子（面板没渲染？）'
          : `模型名叶子不唯一（${cur.texts.length} 种字样），不敢乱点：${cur.texts.join(' | ')}`)
    if (log) log({ ev: 'model', ok: false, code: 'trigger', why })
    process.stderr.write(`[trae] 切模型停手：${why}\n`)
    return { code: 2 }
  }
  const leafs = await scanModelLeafs(cdp)
  const trig = leafs.find((l) => l.text === cur.model && l.inInput)
    || leafs.find((l) => l.text === cur.model)
  if (!trig) {
    if (log) log({ ev: 'model', ok: false, code: 'trigger', why: '读到了模型名但没有可点的叶子' })
    process.stderr.write('[trae] 切模型停手：读到了模型名但没有可点的叶子\n')
    return { code: 2 }
  }
  // ③ 开下拉。
  await clickAt(cdp, trig.x, trig.y)
  await sleep(1500)
  // ④ 扫候选（下拉里的项）并匹配 —— 0/多 ⇒ 关下拉、停手、列候选。
  const items = dedupLeafs(await scanModelLeafs(cdp))
  const texts = items.map((l) => l.text)
  const m = matchModel(texts, wanted)
  if (!m.ok) {
    await pressEscape(cdp)
    if (log) log({ ev: 'model', ok: false, code: m.code, wanted: String(wanted), candidates: texts })
    process.stderr.write(`[trae] 切模型停手：${m.reason}\n`)
    process.stderr.write(`[trae] 下拉里的候选（${texts.length} 个）：\n`)
    for (const t of texts) process.stderr.write(`  ▶ ${t}\n`)
    return { code: 2 }
  }
  // ⑤ 目标项滚进**可点区域**再点（★ 下拉不滚 ⇒ 点击落空，主控实测的硬伤就是这条）。
  const where = await cdp.eval(`(() => {
    const RE = ${MODEL_HINT.toString()};
    const want = ${JSON.stringify(m.model)};
    const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
    const vw = window.innerWidth, vh = window.innerHeight;
    for (const el of document.querySelectorAll('div,span,li,button,p')) {
      if (el.children.length) continue;
      if (norm(el.innerText) !== want) continue;
      if (!/\\d/.test(want)) continue;   // 与扫描口径一致：模型名带版本数字
      const r0 = el.getBoundingClientRect();
      if (r0.width <= 0 || r0.height <= 0) continue;
      el.scrollIntoView({ block: 'center' });
      const r = el.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0) continue;
      if (r.y < 0 || r.y > vh || r.x < 0 || r.x > vw) continue;
      const st = getComputedStyle(el);
      if (st.display === 'none' || st.visibility === 'hidden' || Number(st.opacity) === 0) continue;
      return JSON.stringify({ x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) });
    }
    return null;
  })()`)
  if (!where) {
    await pressEscape(cdp)
    if (log) log({ ev: 'model', ok: false, code: 'unreachable', wanted: m.model })
    process.stderr.write(`[trae] 切模型失败：候选 ${JSON.stringify(m.model)} 滚不进可点区域 —— 核不到不算成功\n`)
    return { code: 3 }
  }
  const pt = JSON.parse(where)
  await clickAt(cdp, pt.x, pt.y)
  await sleep(1200)
  await pressEscape(cdp)
  await sleep(600)
  // ⑥ 回读比对 —— ★ 不许"点了就当成功"。
  let rb = null
  try { rb = await readCurrentModel(cdp) } catch { rb = null }
  const j = judgeModelSwitch(wanted, rb && rb.ok ? rb.model : null)
  if (!j.ok) {
    const extra = rb && !rb.ok && rb.texts.length
      ? `（页面上读到 ${rb.texts.length} 种模型字样：${rb.texts.join(' | ')}）` : ''
    if (log) log({ ev: 'model', ok: false, code: j.code, wanted: String(wanted), reason: j.reason })
    process.stderr.write(`[trae] 切模型失败：${j.reason}${extra} —— 退 3\n`)
    return { code: 3 }
  }
  if (log) log({ ev: 'model', ok: true, code: 'switched', wanted: String(wanted), model: j.model })
  process.stderr.write(`[trae] 模型已切到 ${j.model}（回读一致）\n`)
  return { code: 0, model: j.model }
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
  const target = args.target == null ? null : String(args.target)   // ★ 卡 227：不给 ⇒ 老路
  const modelWanted = args.model == null ? null : String(args.model).trim()   // ★ 卡 245
  if (!promptFile || !logPath || !outPath) {
    process.stderr.write('用法：node tools/trae_pool.mjs send --workspace <目录> --prompt-file <文件> --log <jsonl> --out <md> [--port 9333] [--timeout-sec 3600] [--no-launch] [--target "#N"|<子串>] [--model <名字>]\n')
    return 2
  }
  const log = makeLogger(logPath)
  const prompt = readFileSync(promptFile, 'utf8')

  // ★★ 卡 227：`--target` 给就**先选面板再连**（选不成直接停手，见 connectTarget）；
  //   不给 `--target` ⇒ `attach`（取第一个面板）—— 老行为**逐字不变**。
  let chosen = null
  let cdp
  try {
    if (target != null) {
      const r = await connectTarget(port, target, { launch: !noLaunch, workspace, log })
      if (r.code !== 0) return r.code
      cdp = r.cdp
      chosen = r.panel
    } else {
      cdp = await attach(port, { launch: !noLaunch, workspace })
    }
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
      if (chosen) {
        // ★ 卡 227：重连**要锁回选中的那个面板**，别悄悄换成别的（否则又"派进别的窗口"）。
        //   同代面板的 URL 一模一样 ⇒ 不能靠 URL 认：优先 **target id → 标题 → 重跑 pickPanel**。
        const panels = await fetchPanels(port, 15000)
        const same = panels && (
          panels.find((p) => p.id && p.id === chosen.id)
          || panels.find((p) => p.title && p.title === chosen.title)
          || (() => { const r = pickPanel(panels, target); return r.ok ? r.panel : null })())
        if (same) {
          fresh = await connectPage(same)
          log({ ev: 'reconnect-target', index: same.index, url: same.url })
        }
      } else {
        fresh = await attach(port, { launch: false, findMs: 15000 })
      }
    } catch (e) {
      log({ ev: 'reconnect', ok: false, msg: e.message })
      return false
    }
    if (!fresh) {
      log({ ev: 'reconnect', ok: false,
            msg: chosen ? '重解析 /json/list 没锁回原面板' : '重解析 /json/list 没找到 solo-lite 目标' })
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

    // ★★ 卡 245①：切模型（在发指令**前**）。没选成 / 核不到 / 不一致 ⇒ 非零退出（switchModel 里已打原话）。
    if (modelWanted != null && modelWanted !== '') {
      let sw = null
      try { sw = await switchModel(cdp, modelWanted, { log }) } catch (e) {
        log({ ev: 'error', msg: 'model switch failed: ' + e.message })
        process.stderr.write(`[trae] 切模型失败：${e.message}\n`)
        return 3
      }
      if (sw.code !== 0) return sw.code
    }

    // ★★ 卡 245②：发送前先确认输入框是干净的 —— 残留别人的字就先清空（清不干净 ⇒ 停手，不静默）。
    let preInput = null
    try { preInput = await readInput(cdp) } catch { preInput = null }
    const clear = decideClear(preInput, prompt)
    log({ ev: 'input-before', len: preInput == null ? -1 : preInput.length, action: clear.code })
    if (clear.clear) {
      let cleaned = false
      try { cleaned = await clearInput(cdp) } catch { cleaned = false }
      let afterClear = null
      try { afterClear = await readInput(cdp) } catch { afterClear = null }
      const still = afterClear == null ? null : afterClear.replace(/\s+/g, '')
      if (!cleaned || (still != null && still.length > 0)) {
        log({ ev: 'error', msg: `清空输入框失败（cleaned=${cleaned}, still=${still == null ? '读不到' : still.length + '字'}）` })
        process.stderr.write('[trae] 输入框清空失败，残留还在 —— 停手不发（残留不许静默），退 3\n')
        return 3
      }
    }

    // ★ 记发送前的 agent 轮次数：完成判据要求"出现了**新的** agent 轮次"，防被上一轮的「完成。」骗。
    const baseline = (await readAgents(cdp)).count

    // 发送：insertText 打字 → Enter。★ 发指令这一刻断了**不重发**（会重复提问）—— 如实报错退 3。
    //  ★ 卡 245②：残留恰是本次内容（already-typed）⇒ 不重复输入，只补发送。
    try {
      if (clear.code !== 'already-typed') {
        await cdp.send('Input.insertText', { text: prompt })
      }
      const enter = { key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13, text: '\r' }
      await cdp.send('Input.dispatchKeyEvent', { type: 'keyDown', ...enter })
      await cdp.send('Input.dispatchKeyEvent', { type: 'keyUp', ...enter })
    } catch (e) {
      cdp.markDead('发指令时读页面失败：' + e.message)
      log({ ev: 'error', msg: 'send failed（不重发，避免重复提问）: ' + e.message })
      process.stderr.write(`[trae] 发指令失败（不重发）：${e.message}\n`)
      return 3
    }
    log({ ev: 'send', promptLen: prompt.length, action: clear.code })

    // ★★ 卡 245②：发送后**核验真的发出去了**（输入框变空，或会话里出现本次内容）——
    //   核不到 ⇒ 退 3 并说明，**不许只打一行警告就退 0**。最多核 12 秒（Enter 生效有延迟）。
    const head = prompt.replace(/\s+/g, ' ').trim().slice(0, 30)
    let verdict = null
    {
      const deadline = Date.now() + 12000
      while (Date.now() < deadline) {
        if (!(await ensureCdp())) { await sleep(1000); continue }
        let inp = null
        let chat = false
        try {
          inp = await readInput(cdp)
          chat = await chatHasPrompt(cdp, head)
        } catch (e) {
          cdp.markDead('发送核验读页面失败：' + e.message)
          await sleep(1000)
          continue
        }
        verdict = judgeSend(prompt, { inputAfter: inp, chatHasPrompt: chat })
        if (verdict.ok) break
        await sleep(1000)
      }
    }
    if (!verdict || !verdict.ok) {
      const why = verdict ? verdict.reason : '发送核验 12 秒内没有得出结论（输入框没空、会话里也没找到本次内容）'
      log({ ev: 'error', msg: 'send verify failed: ' + why })
      process.stderr.write(`[trae] 发送核验不过：${why} —— 按"没发出去"处理，退 3\n`)
      return 3
    }
    log({ ev: 'send-verified', code: verdict.code })

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

/* ---------------------------------------------------------------- 卡 227：list / selftest */

/** 只读子命令：列出**所有可驱动面板**（序号 / 标题 / URL / 是否已有会话），给 `--target` 当索引。
 *  ★ 一个字节都不写（只读 CDP）；连不上 CDP ⇒ 退 2 并说清。`list` 与 `--list` 两种写法都认。 */
async function cmdList(argv) {
  const args = parseArgs(argv)
  const port = Number(args.port || DEFAULT_PORT)
  const panels = await fetchPanels(port, 2000)
  if (panels == null) {
    process.stderr.write(`[trae] 连不上 CDP（127.0.0.1:${port}）`
      + ` —— IDE 没开着，或没带 --remote-debugging-port=${port}？\n`)
    return 2
  }
  // 逐个面板探"是否已有会话"（只读、best-effort；探不到就写"未知"，不猜）。
  for (const p of panels) p.session = await probeSession(p)
  process.stdout.write(`[trae] 可驱动面板 ${panels.length} 个`
    + `（--target 用 "#N"（1 基）或 URL/标题子串）：\n`)
  process.stdout.write(formatPanels(panels))
  return 0
}

/** ★ 卡 227 判据：纯函数，**不碰 Trae / CDP** —— 钉住「老行为 / 1 基序号 / 两条反例 / 越界 / 唯一命中」。
 *
 *  为什么判据在本文件里、不另开 `tests/`：本卡栅栏域只有 `tools/trae_pool.mjs`
 *  （`gates/diag/batch/B-20261017.toml` 成员 227 的 `paths`）—— 另开测试文件就是**域外改动**。
 *  跑法：`node tools/trae_pool.mjs selftest` —— 全绿退 0，任一条红退 1。
 */
async function cmdSelftest() {
  const mk = (n, title, url) => ({
    index: n, id: `P${n}`, title,
    url: url || `solo-lite.html?win=${n}`,
    webSocketDebuggerUrl: `ws://127.0.0.1:1/x${n}`,
  })
  const two = [mk(1, 'Agent'), mk(2, 'Agent')]   // 反例素材：两个面板标题一模一样
  const one = [mk(1, 'Agent')]
  const checks = [
    ['老行为：不给 --target ⇒ 第一个面板（逐字不变）',
      pickPanel(two, null), (r) => r.ok && r.code === 'first' && r.panel.index === 1],
    ['--target "#1"（**1 基**）⇒ 第 1 个', pickPanel(two, '#1'),
      (r) => r.ok && r.code === 'index' && r.panel.index === 1],
    ['--target "#2" ⇒ 第 2 个', pickPanel(two, '#2'),
      (r) => r.ok && r.code === 'index' && r.panel.index === 2],
    ['反例①：两个面板标题都含同一子串 ⇒ 停手且不唯一（不许择一）',
      pickPanel(two, 'Agent'), (r) => !r.ok && r.code === 'ambiguous'],
    ['反例②：子串谁都不匹配 ⇒ 停手（nomatch）',
      pickPanel(two, 'zzz-no-such'), (r) => !r.ok && r.code === 'nomatch'],
    ['越界：--target "#9" ⇒ 停手（range）', pickPanel(two, '#9'), (r) => !r.ok && r.code === 'range'],
    ['子串唯一命中 ⇒ 选中它', pickPanel(one, 'Agent'),
      (r) => r.ok && r.code === 'substr' && r.panel.index === 1],
    ['一个可驱动面板都没有 ⇒ 停手（none）', pickPanel([], '#1'),
      (r) => !r.ok && r.code === 'none'],
  ]
  let bad = 0
  for (const [name, got, ok] of checks) {
    const pass = ok(got)
    if (!pass) bad += 1
    process.stdout.write(`[${pass ? '绿' : '红'}] ${name}  → code=${got.code}`
      + `${got.panel ? ' #' + got.panel.index : ''}\n`)
  }
  // "停手要列出候选" 也顺带验：反例的候选清单里两个面板都得在。
  const listed = formatPanels(two)
  const both = listed.includes('win=1') && listed.includes('win=2')
  if (!both) bad += 1
  process.stdout.write(`[${both ? '绿' : '红'}] 停手时列的候选清单把两个面板都列了出来\n`)

  // ★★ 卡 245 判据：--model 唯一性 / 回读比对不许短路 / 残留不许静默（纯函数，不碰 Trae）。
  //   卡 227 的 checks（面板选择那段）一条没删 —— 上面照原样跑过。
  const MODELS = ['GLM-5.3-FlashX', 'DeepSeek-V4', 'Kimi-K3', 'MiMo-V2.6-Pro', 'Kimi-K2.8-Preview']
  const checks245 = [
    ['--model 唯一命中（大小写宽松）⇒ 选中原名', matchModel(MODELS, 'kimi-k3'),
      (r) => r.ok && r.code === 'exact' && r.model === 'Kimi-K3'],
    ['--model 前后缀宽松唯一命中 ⇒ 选中', matchModel(MODELS, 'K3'),
      (r) => r.ok && r.code === 'loose' && r.model === 'Kimi-K3'],
    ['反例①：--model 不存在的名字 ⇒ 停手（nomatch）且列出候选',
      matchModel(MODELS, 'GPT-99'),
      (r) => !r.ok && r.code === 'nomatch' && Array.isArray(r.candidates) && r.candidates.length === MODELS.length],
    ['反例②：--model 前缀匹配多项（"Kimi" 命中两个）⇒ 停手（ambiguous，不许择一）',
      matchModel(MODELS, 'Kimi'), (r) => !r.ok && r.code === 'ambiguous'],
    ['--model 空串 ⇒ 停手（empty）', matchModel(MODELS, ''), (r) => !r.ok && r.code === 'empty'],
    // "不核验不算成功"：回读被短路（读不到）⇒ 必须失败，不许 0。
    ['回读被短路（读不到模型名）⇒ 必须失败（unreadable）',
      judgeModelSwitch('Kimi-K3', null), (r) => !r.ok && r.code === 'unreadable'],
    ['回读与目标不一致（还是 GLM）⇒ 必须失败（mismatch）',
      judgeModelSwitch('Kimi-K3', 'GLM-5.3-FlashX'), (r) => !r.ok && r.code === 'mismatch'],
    ['回读一致 ⇒ 通过', judgeModelSwitch('Kimi-K3', 'Kimi-K3'), (r) => r.ok],
    // "残留不许静默"：清空被短路（输入框仍有别人的字、会话里也没有本次内容）⇒ 必须失败。
    ['发送核验：输入框空 ⇒ 判已发出（input-empty）',
      judgeSend('帮我复核', { inputAfter: '', chatHasPrompt: false }),
      (r) => r.ok && r.code === 'input-empty'],
    ['发送核验：会话里出现本次内容 ⇒ 判已发出（chat-match）',
      judgeSend('帮我复核', { inputAfter: null, chatHasPrompt: true }),
      (r) => r.ok && r.code === 'chat-match'],
    ['发送核验：残留 1 字且会话里没有 ⇒ 必须失败（residual，不许静默）',
      judgeSend('帮我复核', { inputAfter: '好', chatHasPrompt: false }),
      (r) => !r.ok && r.code === 'residual'],
    ['发送核验：输入框读不到且会话里也没有 ⇒ 核不到必须失败（unverifiable）',
      judgeSend('帮我复核', { inputAfter: null, chatHasPrompt: false }),
      (r) => !r.ok && r.code === 'unverifiable'],
    ['发送前：输入框干净 ⇒ 不清', decideClear('', '随便什么'), (r) => !r.clear && r.code === 'clean'],
    ['发送前：残留别人的字 ⇒ 必须先清（residual）',
      decideClear('上一单的残留', '本次内容'), (r) => r.clear && r.code === 'residual'],
    ['发送前：残留恰是本次内容 ⇒ 不清也不重输（already-typed，防重复）',
      decideClear('本次内容', '本次内容'), (r) => !r.clear && r.code === 'already-typed'],
  ]
  for (const [name, got, ok] of checks245) {
    const pass = ok(got)
    if (!pass) bad += 1
    process.stdout.write(`[${pass ? '绿' : '红'}] ${name}  → code=${got.code}\n`)
  }
  process.stdout.write(bad === 0
    ? `[OK] selftest 全绿（${checks.length + 1 + checks245.length} 条）\n`
    : `[FAIL] selftest 有 ${bad} 条红\n`)
  return bad === 0 ? 0 : 1
}

/* ---------------------------------------------------------------- 入口 */

async function main() {
  const argv = process.argv.slice(2)
  const cmd = argv[0]
  let code
  if (cmd === 'balance') code = await cmdBalance(argv.slice(1))
  else if (cmd === 'send') code = await cmdSend(argv.slice(1))
  else if (cmd === 'list' || cmd === '--list') code = await cmdList(argv.slice(1))
  else if (cmd === 'selftest' || cmd === '--selftest') code = await cmdSelftest()
  else {
    process.stderr.write('用法：node tools/trae_pool.mjs balance [--port 9333]\n')
    process.stderr.write('      node tools/trae_pool.mjs list [--port 9333]     # 只读：列可驱动面板（= --list）\n')
    process.stderr.write('      node tools/trae_pool.mjs selftest                # 判据：面板选择 + 模型匹配/发送核验（不需要 Trae）\n')
    process.stderr.write('      node tools/trae_pool.mjs send --workspace <目录> --prompt-file <文件> --log <jsonl> --out <md> [--port 9333] [--timeout-sec 3600] [--no-launch] [--target "#N"|<子串>] [--model <名字>]\n')
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
