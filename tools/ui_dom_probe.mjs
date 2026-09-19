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

globalThis.document = {
  getElementById: (id) => byId.get(id) || null,
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

const DB = {
  '/api/config': { accent_color: '#3b82f6', theme: 'light', gpa_scale: '4.0' },
  '/api/mydays': [], '/api/overdue': [], '/api/tasks': [], '/api/tasks/deleted': [],
  '/api/review/due': [], '/api/review/items': [], '/api/groups': [],
  // 任务详情（右栏 #detailRail）：T-B1 起详情面板带「备注」，编辑态渲染必须也跑一遍
  '/api/tasks/t1': {
    id: 't1', title: '探针任务', due_date: '2030-01-01', group_name: null, repeat_days: null,
    parent_id: null, is_myday: true, status: '未开始', created_at: '2026-09-18T10:00:00',
    updated_at: '2026-09-18T10:00:00', version: 1, groups: [], assignments: [],
    subtask_done: 0, subtask_total: 0, note: '备注也要渲染一遍', priority: '高', flagged: true,
    attach: [{ target: 'https://x.example/要求', title: '要求页' },
      { target: 'D:\\课件\\第3章.pdf', title: null }],
  },
  '/api/tasks/t1/facts': [],
  '/api/tasks/t1/subtasks': [],
  '/api/summary': { debt_count: 0, invest_hours: 0, manual_hours: 0, review_count: 0, output_count: 0 },
  '/api/summary/weekly': { start: '2026-09-14', end: '2026-09-20', days: [], focus_hours: 0, steady_note: '—' },
  '/api/focus/today': { focus_minutes: 0 }, '/api/focus/active': null,
  '/api/habits': [], '/api/selfcheck': { week_focus_minutes: 0, week_habit_done: 0, debt_count: 0 },
  '/api/feedback': null, '/api/courses': [], '/api/grades': [], '/api/assessments/upcoming': [],
  // 全部考核项（T-B4 起学业页用它列表 + 挂要求链接）与附件打开方式设置
  '/api/assessments': [],
  '/api/settings/attach': {
    mode: 'folder', whitelist: [],
    modes: [{ value: 'folder', label: '打开所在文件夹' },
      { value: 'direct', label: '直接用默认程序打开' }, { value: 'auto', label: '按格式自动' }],
    default_mode: 'folder', doc_extensions: ['.pdf'], blocked_extensions: ['.exe'],
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
    + 'globalThis.__render=render;globalThis.__setEdit=v=>{detailEditing=v};')();
} catch (e) {
  console.log(`❌ 脚本求值就抛错：${e.message}`);
  process.exit(1);
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const views = ['today', 'tasks', 'important', 'planned', 'flagged', 'focus', 'stats', 'habit',
  'academic', 'review', 'memo', 'setting'];
let bad = 0;
let detailBad = 0;
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

try {
  const body = code.split('const ACTIONS')[1];
  const registered = new Set([...body.matchAll(/'([a-z-]+)':\s*(?:el\s*=>|\()/g)].map((x) => x[1]));
  for (const a of new Set(CLICK_ACTIONS)) if (!registered.has(a)) unused.push(a);
} catch { /* 模板里没有 data-action 也不该失败 */ }

console.warn = realWarn;
if (process.argv.includes('--json')) {
  console.log(JSON.stringify(
    { views: results, detail: detailChecks, problems, unregistered: unused }, null, 2));
}
if (unused.length) {
  console.log(`  ❌ 模板里用到但未注册的动作：${unused.join(', ')}`);
}
if (problems.length) {
  console.log(`  ⚠️  运行时告警/异常：${problems.slice(0, 5).join(' | ')}`);
}
const failed = bad > 0 || detailBad > 0 || unused.length > 0 || problems.length > 0;
console.log(`\n${failed ? '❌' : '✅'} 假 DOM 渲染探针：${views.length - bad}/${views.length} 个视图正常渲染`
  + `，详情面板 ${detailChecks.length - detailBad}/${detailChecks.length} 正常`
  + `，未注册动作 ${unused.length} 个，运行时告警 ${problems.length} 条`);
process.exit(failed ? 1 : 0);
