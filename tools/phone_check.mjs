/* 手机离线记的**真包自检**（G 批 · T-G10 / SR-NF17）。
 *
 * 为什么需要：手机侧的一切都在浏览器里，本环境**跑不了浏览器**。
 * 但"造包"这件事是纯函数（`src/web/offline.js` 的 `PURE`）——
 * 于是可以在这里用**同一份代码**造出一份真包，交给电脑侧**真导入**一次
 * （`tests/test_offline_phone_line.py`）：验的是"这包真的能被吃下去、账目真的对"，
 * 而不是"某个字符串在不在文件里"。
 *
 * 用法：node tools/phone_check.mjs <包输出路径> <清单输出路径>
 * 退出码：0 = 造出来的包符合电脑侧的全部格式要求；1 = 有不符合项。
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const OFFLINE = join(HERE, '..', 'src', 'web', 'offline.js');

const outPack = process.argv[2];
const outManifest = process.argv[3];
const MODE = process.argv.includes('--undo') ? 'undo' : 'done';
if (!outPack) {
  console.log('用法：node tools/phone_check.mjs <包输出路径> [清单输出路径] [--undo]');
  process.exit(2);
}

// 用**页面里同一个文件**求值：不在自检里抄一份实现（抄了就会腐烂）
const code = readFileSync(OFFLINE, 'utf8');
const fakeWindow = {
  localStorage: {
    _d: { tf_device: 'ph-selftest00001' },
    getItem(k) { return Object.prototype.hasOwnProperty.call(this._d, k) ? this._d[k] : null; },
    setItem(k, v) { this._d[k] = String(v); },
    removeItem(k) { delete this._d[k]; },
  },
};
let OFF;
try {
  new Function('window', code)(fakeWindow);
  OFF = fakeWindow.TFOffline;
} catch (e) {
  console.log(`❌ offline.js 求值就抛错：${e.message}`);
  process.exit(1);
}
if (!OFF || !OFF.PURE) {
  console.log('❌ offline.js 没有导出 TFOffline.PURE（Node 侧自检拿不到纯函数）');
  process.exit(1);
}
const P = OFF.PURE;

// ---------------------------------------------------------------- 造一份"手机上记下的东西"
const AT = '2026-09-23T20:15:00';          // 手机本地时间（固定，便于电脑侧断言）
const DAY = '2026-09-23';
const DEVICE = fakeWindow.localStorage.getItem('tf_device');

// 手机缓存里那条**电脑上已有的**任务 —— 故意把 `TaskOut` 的派生字段也塞进来，
// 检验白名单真的把它们削掉了（直接塞进去就是给电脑塞它没有的列）。
const cached = {
  id: 'phonecheck-cached', title: '缓存里的任务', due_date: null, group_name: null,
  repeat_days: null, parent_id: null, is_myday: true, status: '未开始',
  created_at: '2026-09-22T09:00:00', updated_at: '2026-09-22T09:00:00', version: 3,
  note: '电脑上写的备注', priority: '高', flagged: false,
  attach: [{ target: 'D:/课件/第3章.pdf', title: '课件' }], remind_at: null,
  task_type: '普通', course_id: null,
  // 以下是**只有接口才有**的派生字段：都不该进包
  groups: ['高数'], group_ids: ['g1'], assignments: [], subtask_done: 0, subtask_total: 0,
  current_step: null, current_step_due: null, reminder_state: null, overdue_days: 0,
  course_name: null, doing_rank: null, myday_rank: null, depth: 1, auto_archived: false,
  completed_on: null,
  attempt_count: 0, created_by: 'me',
};

const newTask = P.taskRow({
  title: '手机上记的', due_date: '2026-09-30', is_myday: true, priority: '高',
  note: '离线记的', at: AT,
});
// `--undo`：同一条缓存任务，手机上是**撤销完成**（电脑侧要能把它算回"没收益"）
const transition = MODE === 'undo' ? P.uncompleteTask(cached, AT) : P.completeTask(cached, AT);
const habit = P.habitRow('phonecheck-habit', DAY);
const memo = P.memoRow({ text: '路上想到的一件事', at: AT });
const feedback = P.feedbackRow({
  date: DAY, plan_note: '把第三章看完', gap_note: '卡在第 4 题',
  prev: { executed: '看完了第一节', focus_minutes: 25, created_at: '2026-09-23T08:00:00' },
  at: AT,
});

// 队列（与浏览器里 IndexedDB 存的东西同形）；同一条重复入队只留最新 —— 这里也验一下
const entries = [
  { k: P.queueKey('tasks', newTask), table: 'tasks', row: newTask, at: AT },
  { k: P.queueKey('tasks', transition.row), table: 'tasks', row: transition.row, at: AT },
  { k: P.queueKey('facts', transition.fact), table: 'facts', row: transition.fact, at: AT },
  { k: P.queueKey('habit_logs', habit), table: 'habit_logs', row: habit, at: AT },
  { k: P.queueKey('memos', memo), table: 'memos', row: memo, at: AT },
  { k: P.queueKey('feedback_logs', feedback), table: 'feedback_logs', row: feedback, at: AT },
];
const dup = P.queueKey('tasks', newTask) === P.queueKey('tasks', transition.row) ? 'SAME' : 'DIFF';

const pack = P.buildPack(DEVICE, entries, AT);
const text = P.packText(pack);

// ---------------------------------------------------------------- 自检（电脑侧吃包的前置条件）
const problems = [];
const ALLOWED_TABLES = ['tasks', 'facts', 'habit_logs', 'memos', 'feedback_logs'];
const check = (ok, what) => { if (!ok) problems.push(what); };

check(pack.format === 'timeflow-sync', 'format 不是 timeflow-sync');
check(pack.format_version === 1, 'format_version 不是 1');
check(pack.device_id === DEVICE && DEVICE.startsWith('ph-'), 'device_id 缺失或没有 ph- 前缀');
check(pack.created_at === AT, 'created_at 不对');
check(Array.isArray(pack.tombstones) && pack.tombstones.length === 0, 'tombstones 应该是空数组');
check(typeof pack.tables === 'object' && Object.keys(pack.tables).length === 5,
  `表数不对：${Object.keys(pack.tables).join(',')}`);
check(dup === 'DIFF', '队列去重没生效：缓存任务与手机新任务撞了 key');
for (const t of Object.keys(pack.tables)) {
  check(ALLOWED_TABLES.includes(t), `包里出现了不该有的表：${t}`);
  check(pack.counts[t] === pack.tables[t].length, `${t} 的 counts 与行数不一致`);
}
for (const t of Object.keys(pack.tables)) {
  for (const row of pack.tables[t]) {
    for (const k of Object.keys(row)) {
      check(P.FIELDS[t].includes(k), `${t} 的行里有电脑没有的列：${k}`);
    }
  }
}
// 白名单真的挡住了派生字段（这是"塞进去就出事"的那一处）
const WANT_STATUS = MODE === 'undo' ? '未开始' : '完成';
const WANT_KIND = MODE === 'undo' ? 'task.uncompleted' : 'task.completed';
const doneRow = pack.tables.tasks.find((r) => r.id === cached.id);
check(!!doneRow, '包里找不到那条缓存任务的行');
check(doneRow && doneRow.status === WANT_STATUS,
  `那条缓存任务的状态应该是「${WANT_STATUS}」，实际 ${doneRow && doneRow.status}`);
check(doneRow && doneRow.version === 4, `那条缓存任务的 version 应该是 4（3+1），实际 ${doneRow && doneRow.version}`);
check(doneRow && !('groups' in doneRow) && !('overdue_days' in doneRow) && !('course_name' in doneRow),
  '派生字段（groups/overdue_days/course_name）漏进包里了');
check(doneRow && typeof doneRow.attach === 'string', 'attach 应该是 JSON 文本（电脑库里存文本）');
const fact = (pack.tables.facts || [])[0];
check(!!fact && fact.kind === WANT_KIND, `facts 里没有 ${WANT_KIND}`);
check(!!fact && fact.source === 'phone', `事实 source 应该是 phone，实际 ${fact && fact.source}`);
check(!!fact && fact.subject_id === cached.id, '事实没指向那条任务');
check(!!fact && typeof fact.extra === 'string'
  && (MODE === 'undo' ? JSON.parse(fact.extra).reverted_on : JSON.parse(fact.extra).completed_on) === DAY,
  '事实的 extra 不是带日期字段的 JSON 文本');
check(!!fact && /^[0-9a-f]{12}$/.test(fact.id), `事实 id 形状不对：${fact && fact.id}`);
const newRow = pack.tables.tasks.find((r) => r.id === newTask.id);
check(!!newRow && newRow.status === '未开始' && newRow.is_myday === 1, '新任务的行不对');
check(!!newRow && newRow.created_by === 'me', '新任务的 created_by 应该是 me（你亲手写的）');
check(/^[0-9a-f]{12}$/.test(newTask.id), `新任务 id 形状不对：${newTask.id}`);
check(P.packFilename(DEVICE, AT) === `sync-${DEVICE}-20260923-201500.json`,
  `文件名不对：${P.packFilename(DEVICE, AT)}`);
check(!('app_settings' in pack.tables), '包里不该有 app_settings');
// 两个方向都要能造出来（--undo 用的是同一个函数，另一个方向在这里顺手再验一次形状）
const OTHER_KIND = MODE === 'undo' ? 'task.completed' : 'task.uncompleted';
const other = MODE === 'undo' ? P.completeTask(cached, AT) : P.uncompleteTask(cached, AT);
check(other.fact.kind === OTHER_KIND, '另一个方向的行/事实形状不对');

writeFileSync(outPack, text, 'utf8');
if (outManifest) {
  writeFileSync(outManifest, JSON.stringify({
    device_id: DEVICE, at: AT, day: DAY, mode: MODE,
    new_task_id: newTask.id, cached_task_id: cached.id, habit_id: 'phonecheck-habit',
    memo_id: memo.id, feedback_date: DAY,
    counts: pack.counts,
    // 字段白名单也交出去：Python 侧拿它跟**真库的 PRAGMA** 对账（这才是权威那份）
    fields: P.FIELDS, primary_keys: P.PRIMARY_KEYS,
  }, null, 2), 'utf8');
}

for (const p of problems) console.log(`❌ ${p}`);
console.log(problems.length === 0
  ? `✅ 手机包自检通过：${Object.entries(pack.counts).map(([k, v]) => `${k}=${v}`).join(' ')} → ${outPack}`
  : `❌ 手机包自检不通过（${problems.length} 项）`);
process.exit(problems.length === 0 ? 0 : 1);
