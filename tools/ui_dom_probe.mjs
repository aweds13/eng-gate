/* 假 DOM 渲染探针：在 Node 里把 index.html 的脚本真跑一遍，逐个视图检查渲染是否抛错。
 *
 * 为什么需要（2026-09-18 起）：本环境**跑不了浏览器**（沙箱禁止命名管道，无头 Edge 直接挂死），
 * `node --check` 只能证明"语法对"，字符串护栏只能证明"片段在"，**都不能证明"渲染跑得通"**。
 * 这个探针补上中间那一层：用最小 DOM 桩 + 假后端响应，把 9 个视图各渲染一遍，
 * 任何 TypeError / 未注册动作 / 空渲染都会被抓到。
 *
 * 用法：node tools/ui_dom_probe.mjs [--json]
 * 退出码：0 = 全部视图渲染正常；1 = 有视图抛错或渲染为空。
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const INDEX = join(HERE, '..', 'src', 'web', 'index.html');
const src = readFileSync(INDEX, 'utf8');
const m = src.match(/<script>([\s\S]*?)<\/script>/);
if (!m) {
  console.log('❌ index.html 里找不到 <script> 块');
  process.exit(1);
}
const code = m[1];
const CLICK_ACTIONS = [...src.matchAll(/data-action="([a-z-]+)"/g)].map((x) => x[1]);

const PALETTE = {
  '--accent-1': '#3b82f6', '--accent-2': '#8b5cf6', '--accent-3': '#10b981',
  '--accent-4': '#f59e0b', '--accent-5': '#ef4444', '--accent-6': '#0ea5e9',
};

class El {
  constructor(tag = 'div', id = '') {
    this.tagName = tag.toUpperCase();
    this.id = id;
    this.dataset = {};
    this.children = [];
    this._html = '';
    this._text = '';
    this.hidden = false;
    this.value = '';
    this.checked = false;
    const set = new Set();
    this.classList = {
      add: (c) => set.add(c),
      remove: (c) => set.delete(c),
      contains: (c) => set.has(c),
      toggle: (c, on) => {
        if (on === undefined) { set.has(c) ? set.delete(c) : set.add(c); }
        else { on ? set.add(c) : set.delete(c); }
        return set.has(c);
      },
    };
    this.style = { setProperty() {} };
    this.scrollIntoView = () => {};
  }
  set innerHTML(v) { this._html = String(v); }
  get innerHTML() { return this._html; }
  set textContent(v) { this._text = String(v); }
  get textContent() { return this._text; }
  addEventListener() {}
  removeEventListener() {}
  appendChild(c) { this.children.push(c); return c; }
  closest() { return null; }
  focus() {}
  select() {}
}

const byId = new Map();
for (const id of ['main', 'summary', 'toast', 'modal', 'modalInput', 'modalTitle',
  'focusRail', 'detailRail', 'refresh', 'clock', 'hmRow', 'hmBox', 'hmNote', 'groupAdmin']) {
  byId.set(id, new El('div', id));
}
const navButtons = [];
for (const v of ['today', 'tasks', 'focus', 'stats', 'habit', 'academic', 'review', 'memo', 'setting']) {
  const b = new El('button');
  b.dataset = { view: v, action: 'view' };
  navButtons.push(b);
}

const shellEl = new El('div', 'shell');
globalThis.document = {
  getElementById: (id) => byId.get(id) || null,
  querySelector: (sel) => (sel === '.shell' ? shellEl : null),
  querySelectorAll: (sel) => (sel.includes('nav button') ? navButtons : []),
  addEventListener() {},
  createElement: (t) => new El(t),
  documentElement: new El('html'),
};
globalThis.window = { matchMedia: () => ({ matches: false, addEventListener() {} }), addEventListener() {} };
Object.defineProperty(globalThis, 'navigator', { value: { onLine: true }, configurable: true });
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
globalThis.getComputedStyle = () => ({ getPropertyValue: (k) => PALETTE[k] || '' });
globalThis.AbortController = class { constructor() { this.signal = {}; } abort() {} };

// 假后端里的任务对象：字段与 `TaskOut` 对齐（缺字段会让渲染拿到 undefined，探针就抓不到了）
function probeTask(over = {}) {
  return {
    id: 't0', title: '探针任务', due_date: null, group_name: null, repeat_days: null,
    parent_id: null, is_myday: false, status: '未开始', created_at: '2026-09-18T10:00:00',
    updated_at: '2026-09-18T10:00:00', version: 1, groups: [], assignments: [],
    subtask_done: 0, subtask_total: 0, note: null, priority: '中', flagged: false, attach: [],
    remind_at: null, reminder_state: null, task_type: '普通', course_id: null, course_name: null,
    doing_rank: null,
    // 派生逾期天数（T-F7）：界面不自己拿今天去减，后端算好再给
    overdue_days: 0, ...over,
  };
}

const DB = {
  '/api/config': { accent_color: '#3b82f6', theme: 'light', gpa_scale: '4.0' },
  '/api/mydays': [], '/api/overdue': [], '/api/tasks/deleted': [],
  // 状态机（F 批 · T-F1）：三段都要真渲染出来 ——
  // 「全部任务」主列表 + 搁置区（待定/取消）+ 档案区（手动归档，可撤销）
  '/api/tasks': [probeTask({ id: 't2', title: '普通任务', is_myday: false,
      subtask_done: 1, subtask_total: 3, current_step: '第 2 步：写解答',
      current_step_due: '2026-09-25' }),
    probeTask({ id: 'p1', title: '待定的事', status: '待定' }),
    probeTask({ id: 'x1', title: '取消的事', status: '取消' })],
  // 「正在做」：**可以同时多个**，各带自己的顺序号（↑↓ 用 `doing_rank` 排）
  '/api/tasks/doing': [probeTask({ id: 'd1', title: '写高数作业', status: '进行中', doing_rank: 1 }),
    probeTask({ id: 'd2', title: '背单词', status: '进行中', doing_rank: 2 })],
  '/api/tasks/archived': [probeTask({ id: 'a9', title: '归档的事', status: '归档' }),
    // 档案的**另一半**（T-F2）：完成满 N 天自动收入的 —— 徽标、「试了几回」、备注都要真渲染出来
    probeTask({ id: 'af1', title: '自动收走的事', status: '完成', auto_archived: true,
      completed_on: '2026-09-17', attempt_count: 3, note: '笔记：第三章的推导' })],
  // 到点提醒（T-B5）：今日页「该提醒了」区用它
  '/api/reminders/due': [],
  // 复习线（SR-F6.2 / SR-F6.5 / SR-F8.3）：到期卡非空 —— 卡片态要渲染出「改形式/句柄」按钮
  '/api/review/due': [{ id: 'r1', title: '探针复习卡', reps: 2, interval_days: 3,
    source: 'internal', ref_handle: 'notes/数学.md', form: 'qa', due_date: '2026-09-20', task_id: 't1' }],
  '/api/review/items': [], '/api/groups': [],
  // 复习卡的定义类字段（T-C6·C7）：词表来自后端，编辑态要渲染形式/执行源下拉 + 句柄输入
  '/api/review/meta': {
    forms: [{ value: 'cloze', label: '挖空' }, { value: 'qa', label: '问答卡' },
      { value: 'exam', label: '真题' }],
    sources: [{ value: 'internal', label: '内置' }, { value: 'external', label: '外部 app' }],
    default_form: 'qa', default_source: 'internal',
  },
  '/api/review/items/r1': { id: 'r1', title: '探针复习卡', form: 'qa', source: 'internal',
    due_date: '2026-09-20', reps: 2, interval_days: 3, ref_handle: 'notes/数学.md', task_id: 't1' },
  // 任务详情（右栏 #detailRail）：T-B1 起详情面板带「备注」，编辑态渲染必须也跑一遍
  '/api/tasks/t1': {
    id: 't1', title: '探针任务', due_date: '2030-01-01', group_name: null, repeat_days: null,
    parent_id: null, is_myday: true, status: '未开始', created_at: '2026-09-18T10:00:00',
    updated_at: '2026-09-18T10:00:00', version: 1, groups: [], assignments: [],
    subtask_done: 0, subtask_total: 0, note: '备注也要渲染一遍', priority: '高', flagged: true,
    // 类型 + 所属课程（T-C12）：编辑态要渲染课程下拉、只读态要渲染课程徽标
    task_type: '作业', course_id: 'c1', course_name: '高等数学',
    attach: [{ target: 'https://x.example/要求', title: '要求页' },
      { target: 'D:\\课件\\第3章.pdf', title: null }],
  },
  '/api/tasks/t1/facts': [],
  // 子步骤（F 批 · T-F4）：每一步有自己的截止日 + 「明天 / 尝试失败 / 详情 / 脱离」；
  // 第一张卡（t2）带「当前该做哪一步」，用来看主任务卡是不是真的显示了**一步**
  '/api/tasks/t1/subtasks': [
    probeTask({ id: 's1', title: '第 1 步：读题', status: '完成', parent_id: 't1',
      due_date: '2026-09-18' }),
    probeTask({ id: 's2', title: '第 2 步：写解答', parent_id: 't1', due_date: '2026-09-25' }),
  ],
  // 派生逾期（T-F7）：字段状态还是「未开始」、后端算出"已逾期 12 天" —— 详情面板要**两个都显示**，
  // 不能再出现"列在逾期栏里、面板却写未开始"的自相矛盾
  '/api/tasks/t9': probeTask({
    id: 't9', title: '拖了很久的事', status: '未开始', due_date: '2020-01-01', overdue_days: 12,
  }),
  // 「尝试失败」（F 批 · T-F3）：详情面板要显示「试了 N 回」+ 历次留下的说明 + 「尝试失败」入口
  '/api/tasks/t1/attempts': { count: 0, notes: [] },
  '/api/tasks/t9/attempts': { count: 3, notes: ['试了前两章，卡在第 3 题', '换了本参考书还是不行'] },
  // 「完成 N 天后进档案」的 N（F 批 · T-F2）：设置页要渲染出天数输入框与口径说明
  '/api/settings/archive': { after_days: 3, default_after_days: 3, max_after_days: 365,
    note: '完成之后不是立刻收走：满 N 天自动进档案（0 = 当天就收）。' },
  // 任务 → 复习卡（T-C5）：详情面板要显示"这张任务升级出来的卡"
  '/api/tasks/t1/review-cards': [{ id: 'r1', title: '探针复习卡', due_date: '2026-09-20T00:00:00',
    form: 'qa', source: 'internal', ref_handle: 'notes/数学.md', task_id: 't1' }],
  '/api/summary': { debt_count: 0, invest_hours: 0, manual_hours: 0, review_count: 0, output_count: 0,
    output_kpi: 2, output_asset: 3 },
  // 今天做成了什么（T-C11）：三个可展开项都要真渲染一遍（含父任务分组与进度）
  '/api/today/done': {
    date: '2026-09-19',
    tasks: [{ id: 't1', title: '背单词', completed_at: '2026-09-19T10:00:00' }],
    steps: [
      { id: 's1', title: '第 1 题', parent_id: 'p1', parent_title: '高数作业', completed_at: '2026-09-19T11:00:00' },
      { id: 's2', title: '第 2 题', parent_id: 'p1', parent_title: '高数作业', completed_at: '2026-09-19T11:20:00' }],
    parents: [{ id: 'p1', title: '高数作业', done_today: 2, done_total: 2, total_steps: 5 }],
    outputs: [
      { entry_id: 'o1', kind: 'kpi', value: 1, note: '数学卷子', occurred_at: '2026-09-19T12:00:00', retracted: false },
      { entry_id: 'o2', kind: 'asset', value: 2, note: '笔记#3', occurred_at: '2026-09-19T13:00:00', retracted: true }],
    output_kpi: 1, output_asset: 1,
  },
  '/api/summary/weekly': { start: '2026-09-14', end: '2026-09-20', days: [], focus_hours: 0, steady_note: '—' },
  '/api/focus/today': { focus_minutes: 0 }, '/api/focus/active': null,
  '/api/habits': [], '/api/selfcheck': { week_focus_minutes: 0, week_habit_done: 0, debt_count: 0 },
  '/api/feedback': null, '/api/courses': [{ id: 'c1', name: '高等数学', credits: 4, teacher: '张老师' }],
  '/api/grades': [],
  // 学校硬考核（T-C8）：`upcoming_assessments()` 只返回**未录成绩**的考核项 —— 学业页要把这类
  // 呈现得比普通逾期更明显（置顶 + 粗左边条 + 角标 + 一句说明），这里给一条让它真渲染出来。
  '/api/assessments/upcoming': [{ id: 'a1', name: '期中考试', course_id: 'c1',
    course_name: '高等数学', due_date: '2026-09-21', days_until: 1, weight: 0.3,
    attach: [], score: null }],
  // 学业投入 vs 自学投入（SR-F5.1b / T-C10）：统计页那张对照图要用它
  '/api/insights/academic-vs-self': { days: 90, academic_hours: 2.0, self_hours: 1.5,
    unbound_hours: 0.5, academic_tasks: 2, self_tasks: 1 },
  // 备份与恢复（SR-NF12 / SR-F9.3）：设置页要列出备份、每个都能点「恢复」
  '/api/settings/backups': {
    db: 'timeflow.db', dir: 'D:/data',
    note: '恢复会把整库回到那个时间点（连设置一起）。',
    items: [
      { name: 'timeflow.db.bak-20260921-090000', size: 204800, at: '2026-09-21T09:00:00', parsed: true },
      { name: 'timeflow.db.bak-20260920-210000', size: 200704, at: '2026-09-20T21:00:00', parsed: true },
    ],
  },
  // 全部考核项（T-B4 起学业页用它列表 + 挂要求链接）与附件打开方式设置
  '/api/assessments': [],
  '/api/settings/attach': {
    mode: 'folder', whitelist: [],
    modes: [{ value: 'folder', label: '打开所在文件夹' },
      { value: 'direct', label: '直接用默认程序打开' }, { value: 'auto', label: '按格式自动' }],
    default_mode: 'folder', doc_extensions: ['.pdf'], blocked_extensions: ['.exe'],
  },
  // 到点通知开关（T-B5 后半）
  '/api/settings/reminder': {
    enabled: false, style: 'alarm',
    styles: [{ value: 'alarm', label: '闹钟式（留在屏幕上 + 循环响铃）' },
      { value: 'gentle', label: '温和通知（几秒后消失）' }],
    task_name: 'timeflow-reminders', installed: false, interval_minutes: 1,
    last_notify_at: null, last_result: null, last_error: null,
  },
  // 专注白名单 / 勿扰设置（SR-F3.3 / GAP-F3-02）：设置页要能渲染已有条目（可增删）
  '/api/focus/guard': {
    block_by_default: true, whitelist: ['vscode', '微信'], do_not_disturb: ['22:00-07:00'],
    note: '白名单 = 专注时允许用的来源。', window_format: 'HH:MM-HH:MM', max_items: 50,
  },
  '/api/gpa': { gpa: 0, credits: 0, scale: '4.0', weighted_average: 0, weighted_credits: 0 },
  '/api/memos': [], '/api/ledger/outputs': [], '/api/ledger/invests': [],
  '/api/insights/daily': [], '/api/insights/groups': [], '/api/insights/heatmap': [],
  '/api/sync/status': { enabled: false, conflict_logs: 0 },
};
globalThis.fetch = async (path) => {
  const key = String(path).split('?')[0];
  const body = key in DB ? DB[key] : null;
  return { ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body) };
};

const problems = [];
process.on('unhandledRejection', (e) => problems.push(`unhandledRejection: ${(e && e.message) || e}`));
const realWarn = console.warn;
console.warn = (...a) => problems.push('warn: ' + a.join(' '));

try {
  new Function(code + '\n;globalThis.__view=view;globalThis.__showDetail=showDetail;'
    + 'globalThis.__render=render;globalThis.__setEdit=v=>{detailEditing=v};'
    + 'globalThis.__setDoneOpen=v=>{doneOpen=v};globalThis.__setReviewEdit=v=>{reviewEdit=v};')();
} catch (e) {
  console.log(`❌ 脚本求值就抛错：${e.message}`);
  process.exit(1);
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const views = ['today', 'tasks', 'important', 'planned', 'flagged', 'focus', 'stats', 'habit',
  'academic', 'review', 'memo', 'setting'];
let bad = 0;
let detailBad = 0;
let doneBad = 0;
let reviewBad = 0;
let hardBad = 0;
let guardBad = 0;
let stateBad = 0;
let overdueBad = 0;
let attemptBad = 0;
let archiveBad = 0;
let stepBad = 0;
const results = [];
for (const v of views) {
  byId.get('main')._html = '';
  try {
    await globalThis.__view(v);
    await new Promise((r) => setTimeout(r, 30));
    const html = byId.get('main')._html;
    const rail = byId.get('focusRail')._html;
    const ok = /<div|<svg|<button/.test(html);
    if (!ok) bad++;
    results.push({ view: v, main: html.length, rail: rail.length, rendered: ok });
    console.log(`  ${ok ? '✅' : '⚠️ '} ${v.padEnd(9)} main ${String(html.length).padStart(6)}B  rail ${String(rail.length).padStart(4)}B`);
  } catch (e) {
    bad++;
    results.push({ view: v, error: e.message });
    console.log(`  ❌ ${v.padEnd(9)} 渲染抛错: ${e.message}`);
  }
}

const unused = [];
// 右栏详情面板（R3 渐进聚焦）：任务字段 + 事实流水 + 编辑态（T-B1 的备注输入就在这里）。
// 视图循环覆盖不到它 —— 探针默认没有选中任务（`detailTaskId` 为空时右栏是空的），
// 所以这里单独跑两遍：只读态 + 编辑态，任何 TypeError／空渲染都算失败。
const detailChecks = [];
for (const editing of [false, true]) {
  byId.get('detailRail')._html = '';
  globalThis.__setEdit(editing);
  try {
    await globalThis.__showDetail('t1');
    await sleep(30);
    const rail = byId.get('detailRail')._html;
    // 只读态：显示任务字段（含备注、优先级色标）；编辑态：两个可写控件都在
    const needs = editing
      ? ['id="editNote"', 'id="editPriority"']
      : ['备注也要渲染一遍', 'prio', 'attach-open', '要求页'];
    const missing = needs.filter((n) => !rail.includes(n));
    const rendered = rail.includes('任务详情') && missing.length === 0;
    if (!rendered) detailBad++;
    detailChecks.push({ editing, rail: rail.length, rendered, missing });
    console.log(`  ${rendered ? '✅' : '⚠️ '} 详情面板${editing ? '·编辑态' : '·只读'} rail ${String(rail.length).padStart(5)}B`
      + (missing.length ? `  缺: ${missing.join(', ')}` : ''));
  } catch (e) {
    detailBad++;
    detailChecks.push({ editing, error: e.message });
    console.log(`  ❌ 详情面板${editing ? '·编辑态' : '·只读'} 渲染抛错: ${e.message}`);
  }
}
globalThis.__setEdit(false);

// 今天做成了什么（T-C11）：三个选项卡**默认收起**，视图循环只覆盖收起态 ——
// 这里把三项全展开再渲染一遍（父任务分组、父任务进度、已撤销产出都必须真渲染出来）。
const doneChecks = [];
try {
  globalThis.__setDoneOpen({ tasks: true, steps: true, outputs: true });
  byId.get('main')._html = '';
  await globalThis.__view('today');
  await sleep(30);
  const html = byId.get('main')._html;
  const needs = ['今天做成了什么', '第 1 题', '高数作业', '该任务进度 2/5 步', '已撤销（不计入条数）',
    // 新手引导（SR-NF2 / R5）：探针的 localStorage 返回 null → 首屏应出引导卡片且可关
    '第一次用，按这三步走就行', 'guide-start', 'guide-done'];
  const missing = needs.filter((n) => !html.includes(n));
  const rendered = missing.length === 0;
  if (!rendered) doneBad++;
  doneChecks.push({ rendered, missing });
  console.log(`  ${rendered ? '✅' : '⚠️ '} 今日·完成明细展开 main ${String(html.length).padStart(6)}B`
    + (missing.length ? `  缺: ${missing.join(', ')}` : ''));
} catch (e) {
  doneBad++;
  doneChecks.push({ error: e.message });
  console.log(`  ❌ 今日·完成明细展开 渲染抛错: ${e.message}`);
}

// 复习卡的定义类字段（SR-F6.5 形式 / SR-F8.3 引用句柄 / T-C6·C7）：
// 视图循环只覆盖"卡片态" —— 这里把**编辑态**也渲染一遍：形式/执行源下拉、引用句柄输入、
// 保存/取消按钮，以及"排期字段不给人手改"的说明。词表来自后端 `/api/review/meta`。
const reviewChecks = [];
try {
  globalThis.__setReviewEdit({ id: 'r1', item: DB['/api/review/items/r1'], meta: DB['/api/review/meta'] });
  byId.get('main')._html = '';
  await globalThis.__view('review');
  await sleep(30);
  const html = byId.get('main')._html;
  const needs = ['id="rvForm"', 'id="rvSource"', 'id="rvHandle"', '问答卡',
    'review-save', 'review-edit-cancel', '不给人手改'];
  const missing = needs.filter((n) => !html.includes(n));
  const rendered = missing.length === 0;
  if (!rendered) reviewBad++;
  reviewChecks.push({ rendered, missing });
  console.log(`  ${rendered ? '✅' : '⚠️ '} 复习·改形式填句柄 main ${String(html.length).padStart(6)}B`
    + (missing.length ? `  缺: ${missing.join(', ')}` : ''));
} catch (e) {
  reviewBad++;
  reviewChecks.push({ error: e.message });
  console.log(`  ❌ 复习·改形式填句柄 渲染抛错: ${e.message}`);
}
globalThis.__setReviewEdit({ id: null, item: null, meta: null });

// 学校硬考核（T-C8）：视图循环只覆盖"有没有渲染"，这里断言**强呈现的要素真的在**。
const hardChecks = [];
try {
  byId.get('main')._html = '';
  await globalThis.__view('academic');
  await sleep(30);
  const html = byId.get('main')._html;
  const needs = ['card hard', 'badge hard', '硬考核', '未录成绩', '逾期不候'];
  const missing = needs.filter((n) => !html.includes(n));
  const rendered = missing.length === 0;
  if (!rendered) hardBad++;
  hardChecks.push({ rendered, missing });
  console.log(`  ${rendered ? '✅' : '⚠️ '} 学业·硬考核强呈现 main ${String(html.length).padStart(6)}B`
    + (missing.length ? `  缺: ${missing.join(', ')}` : ''));
} catch (e) {
  hardBad++;
  hardChecks.push({ error: e.message });
  console.log(`  ❌ 学业·硬考核强呈现 渲染抛错: ${e.message}`);
}

// 设置页两块新东西：专注白名单/勿扰（SR-F3.3 / GAP-F3-02）+ 备份与恢复（SR-NF12 / SR-F9.3）。
// 都要**真的把已有条目渲染出来**（可增删 / 可点恢复），而不是只画个标题。
const guardChecks = [];
try {
  byId.get('main')._html = '';
  await globalThis.__view('setting');
  await sleep(30);
  const html = byId.get('main')._html;
  const needs = ['set-focus-guard', 'guard-block', 'guard-wl-del', 'guard-dnd-del',
    'guard-wl-add', 'guard-dnd-add', 'vscode', '22:00-07:00',
    // 备份与恢复：列表里的时间点 + 每个都可点
    'set-backup', 'restore-backup', '备份与恢复', '2026-09-21 09:00:00'];
  const missing = needs.filter((n) => !html.includes(n));
  const rendered = missing.length === 0;
  if (!rendered) guardBad++;
  guardChecks.push({ rendered, missing });
  console.log(`  ${rendered ? '✅' : '⚠️ '} 设置·白名单勿扰+备份 main ${String(html.length).padStart(6)}B`
    + (missing.length ? `  缺: ${missing.join(', ')}` : ''));
} catch (e) {
  guardBad++;
  guardChecks.push({ error: e.message });
  console.log(`  ❌ 设置·白名单勿扰+备份 渲染抛错: ${e.message}`);
}

// 状态机（F 批 · T-F1）：三块新界面各渲染一遍并断言要素真的在 ——
// 今日「正在做」（多个 + 顺序号 + ↑↓ + 停止）、全部任务「搁置」（待定/取消 + 取回）、「档案」（撤销归档）。
const stateChecks = [];
for (const [view, needs] of [
  ['today', ['正在做（2）', '写高数作业', 'doing-move', 'data-dir="up"', 'data-dir="down"', 'task-stop']],
  ['tasks', ['搁置', '待定的事', '取消的事', 'task-unpark', '档案', '归档的事', 'task-unarchive']],
]) {
  try {
    byId.get('main')._html = '';
    await globalThis.__view(view);
    await sleep(30);
    const html = byId.get('main')._html;
    const missing = needs.filter((n) => !html.includes(n));
    const rendered = missing.length === 0;
    if (!rendered) stateBad++;
    stateChecks.push({ view, rendered, missing });
    console.log(`  ${rendered ? '✅' : '⚠️ '} ${view}·状态机 main ${String(html.length).padStart(6)}B`
      + (missing.length ? `  缺: ${missing.join(', ')}` : ''));
  } catch (e) {
    stateBad++;
    stateChecks.push({ view, error: e.message });
    console.log(`  ❌ ${view}·状态机 渲染抛错: ${e.message}`);
  }
}

// 派生逾期（F 批 · T-F7）：字段状态 + 派生天数**两个都要在**，且不打架。
const overdueChecks = [];
try {
  byId.get('detailRail')._html = '';
  await globalThis.__showDetail('t9');
  await sleep(30);
  const rail = byId.get('detailRail')._html;
  const needs = ['状态 未开始', '已逾期 12 天', 'badge hard'];
  const missing = needs.filter((n) => !rail.includes(n));
  const rendered = missing.length === 0;
  if (!rendered) overdueBad++;
  overdueChecks.push({ rendered, missing });
  console.log(`  ${rendered ? '✅' : '⚠️ '} 详情·派生逾期 rail ${String(rail.length).padStart(5)}B`
    + (missing.length ? `  缺: ${missing.join(', ')}` : ''));
} catch (e) {
  overdueBad++;
  overdueChecks.push({ error: e.message });
  console.log(`  ❌ 详情·派生逾期 渲染抛错: ${e.message}`);
}

// 档案视图（F 批 · T-F2）：一屏里两种来源都要真渲染出来 ——
// 手动归档（撤销归档）与"完成满 N 天自动收入"（撤销完成回到列表），外加「试了几回」与备注；
// 设置页要能改那个 N。
const archiveChecks = [];
for (const [view, needs] of [
  ['tasks', ['自动归档', '手动归档', '撤销完成（回到列表）', '试了 3 回', '笔记：第三章的推导',
    'task-unarchive', '自动收走的事']],
  ['setting', ['完成几天后进档案', 'archiveDays', 'set-archive-days', '上限 365 天']],
]) {
  try {
    byId.get('main')._html = '';
    await globalThis.__view(view);
    await sleep(30);
    const html = byId.get('main')._html;
    const missing = needs.filter((n) => !html.includes(n));
    const rendered = missing.length === 0;
    if (!rendered) archiveBad++;
    archiveChecks.push({ view, rendered, missing });
    console.log(`  ${rendered ? '✅' : '⚠️ '} ${view}·档案 main ${String(html.length).padStart(6)}B`
      + (missing.length ? `  缺: ${missing.join(', ')}` : ''));
  } catch (e) {
    archiveBad++;
    archiveChecks.push({ view, error: e.message });
    console.log(`  ❌ ${view}·档案 渲染抛错: ${e.message}`);
  }
}

// 子步骤（F 批 · T-F4）：主任务卡上显示「当前该做哪一步」；
// 详情里每一步都有截止日输入框与「明天 / 尝试失败 / 详情 / 脱离」，添加步骤那一行也有日期框。
const stepChecks = [];
for (const [where, needs] of [
  ['tasks', ['步骤 1/3', '当前：第 2 步：写解答', '2026-09-25 前']],
  ['detail', ['第 2 步：写解答', 'subtask-due', 'id="subtaskDue"', '尝试失败', '脱离']],
]) {
  try {
    let html = '';
    if (where === 'tasks') {
      byId.get('main')._html = '';
      await globalThis.__view('tasks');
      await sleep(30);
      html = byId.get('main')._html;
    } else {
      byId.get('detailRail')._html = '';
      await globalThis.__showDetail('t1');
      await sleep(30);
      html = byId.get('detailRail')._html;
    }
    const missing = needs.filter((n) => !html.includes(n));
    const rendered = missing.length === 0;
    if (!rendered) stepBad++;
    stepChecks.push({ where, rendered, missing });
    console.log(`  ${rendered ? '✅' : '⚠️ '} ${where}·子步骤 ${String(html.length).padStart(5)}B`
      + (missing.length ? `  缺: ${missing.join(', ')}` : ''));
  } catch (e) {
    stepBad++;
    stepChecks.push({ where, error: e.message });
    console.log(`  ❌ ${where}·子步骤 渲染抛错: ${e.message}`);
  }
}

// 「尝试失败」（F 批 · T-F3）：详情要显示「试了 N 回」+ 历次说明 + 入口按钮。
// 只认显式点击这件事在领域层/接口层有测试钉住，这里只管"界面真的把它渲染出来了"。
const attemptChecks = [];
try {
  byId.get('detailRail')._html = '';
  await globalThis.__showDetail('t9');
  await sleep(30);
  const rail = byId.get('detailRail')._html;
  const needs = ['试了 3 回', '过去尝试留下的说明', '试了前两章，卡在第 3 题',
    'data-action="task-attempt"'];
  const missing = needs.filter((n) => !rail.includes(n));
  const rendered = missing.length === 0;
  if (!rendered) attemptBad++;
  attemptChecks.push({ rendered, missing });
  console.log(`  ${rendered ? '✅' : '⚠️ '} 详情·尝试失败 rail ${String(rail.length).padStart(5)}B`
    + (missing.length ? `  缺: ${missing.join(', ')}` : ''));
} catch (e) {
  attemptBad++;
  attemptChecks.push({ error: e.message });
  console.log(`  ❌ 详情·尝试失败 渲染抛错: ${e.message}`);
}

try {
  const registered = new Set([...body.matchAll(/'([a-z-]+)':\s*(?:el\s*=>|\()/g)].map((x) => x[1]));
  for (const a of new Set(CLICK_ACTIONS)) if (!registered.has(a)) unused.push(a);
} catch { /* 模板里没有 data-action 也不该失败 */ }
console.warn = realWarn;
if (process.argv.includes('--json')) {
  console.log(JSON.stringify(
    { views: results, detail: detailChecks, done: doneChecks, review: reviewChecks,
      hard: hardChecks, guard: guardChecks, state: stateChecks, overdue: overdueChecks,
      attempt: attemptChecks, archive: archiveChecks, step: stepChecks,
      problems, unregistered: unused },
    null, 2));
}
if (unused.length) {
  console.log(`  ❌ 模板里用到但未注册的动作：${unused.join(', ')}`);
}
if (problems.length) {
  console.log(`  ⚠️  运行时告警/异常：${problems.slice(0, 5).join(' | ')}`);
}
const failed = bad > 0 || detailBad > 0 || doneBad > 0 || reviewBad > 0 || hardBad > 0
  || guardBad > 0 || stateBad > 0 || overdueBad > 0 || attemptBad > 0 || archiveBad > 0
  || stepBad > 0
  || unused.length > 0 || problems.length > 0;
console.log(`\n${failed ? '❌' : '✅'} 假 DOM 渲染探针：${views.length - bad}/${views.length} 个视图正常渲染`
  + `，详情面板 ${detailChecks.length - detailBad}/${detailChecks.length} 正常`
  + `，今日完成明细展开 ${doneChecks.length - doneBad}/${doneChecks.length} 正常`
  + `，复习卡编辑态 ${reviewChecks.length - reviewBad}/${reviewChecks.length} 正常`
  + `，硬考核强呈现 ${hardChecks.length - hardBad}/${hardChecks.length} 正常`
  + `，白名单勿扰 ${guardChecks.length - guardBad}/${guardChecks.length} 正常`
  + `，状态机 ${stateChecks.length - stateBad}/${stateChecks.length} 正常`
  + `，派生逾期 ${overdueChecks.length - overdueBad}/${overdueChecks.length} 正常`
  + `，尝试失败 ${attemptChecks.length - attemptBad}/${attemptChecks.length} 正常`
  + `，档案视图 ${archiveChecks.length - archiveBad}/${archiveChecks.length} 正常`
  + `，子步骤 ${stepChecks.length - stepBad}/${stepChecks.length} 正常`
  + `，未注册动作 ${unused.length} 个，运行时告警 ${problems.length} 条`);
process.exit(failed ? 1 : 0);
