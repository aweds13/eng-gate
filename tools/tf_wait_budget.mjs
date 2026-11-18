/* 等待预算的旋钮（卡 E135 / T-AG644）：**只乘预算，不改判据**。
 *
 * 为什么单独一个文件，而不是在 `ui_flow_check.mjs` 里就地读 env：
 *   · 判据要能被**不起浏览器**地钉住 —— `node --input-type=module -e` 直接 import 这个文件就能测，
 *     不用为了「读一个数字」去起服务、起浏览器（那条路一遍两三分钟，钉不住任何东西）；
 *   · 三个等待原语的预算必须**一处**变；散着读 env 迟早漏一个（漏的那个就是下次假红的地方）。
 *
 * 口径三条（都是卡 E135 明令，反向变异钉着）：
 *   ① 默认 **1** ⇒ 行为与加这个文件之前逐字一致（三个原语的默认预算仍是 12000 / 12000 / 5000）；
 *   ② 上界 **10** —— 不许「等于永不超时」（那等于把判据换成运气，红与绿都不再有意义）；
 *   ③ 只乘在**等待时长**上：轮询粒度（`sleep(100)` / `step`）与「等到就绪就返回」的循环结构不动。
 *
 * 为什么不给「绝对毫秒」的旋钮（`TF_UI_FLOW_TIMEOUT_MS` 那种）：26 条流各自给 6000–14000，
 * 绝对值要改 26 处调用点；**只乘不改**调用点才是这张卡要的形状。
 */

export const WAIT_SCALE_ENV = 'TF_UI_FLOW_WAIT_SCALE'

/** 上界：再慢的机器也只等 10 倍。**不许**无边 —— 无边等于「永不超时」。 */
export const WAIT_SCALE_MAX = 10

/** 一句话：把 env 的原文折成预算倍数。空 / 坏值 / NaN / 负数 / 0 ⇒ 1；合法区间 [1, 10]。
 *
 *  为什么坏值回 1 而不是报错：这是**抬预算**的旋钮，读错时退回现状（本机行为）比让整道门起不来安全；
 *  真要 auditable 的读数，`main()` 在倍数 ≠ 1 时会自报一行（判据 4）。
 */
export function parseWaitScale(raw) {
  if (raw === undefined || raw === null) return 1
  const text = String(raw).trim()
  if (!text) return 1
  const n = Number(text)
  if (!Number.isFinite(n) || n <= 0) return 1
  // 下界 1（0.5 这种「把预算调小」的读法不认：那是改判据强度，不是抬预算），上界 WAIT_SCALE_MAX
  return Math.min(Math.max(n, 1), WAIT_SCALE_MAX)
}

export function waitScale() {
  return parseWaitScale(process.env[WAIT_SCALE_ENV])
}

/** 把某个等待原语的预算乘一次（**只动时长**，不动轮询粒度）。 */
export function scaleMs(ms, scale) {
  return Math.round(ms * scale)
}
