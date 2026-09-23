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
const OFFLINE = join(HERE, '..', 'src', 'web', 'offline.js');
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
for (const id of ['main', 'summary', 'toast', 'modal', 'modalInput', 'modalTitle', 'offlineBar',
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

/* 内存版 IndexedDB（只实现 offline.js 用到的那几个方法：open / transaction / put / get /
   getAll / count / clear）。**为什么值得写这个桩**：手机离线记的真身就在 IndexedDB 里，
   没有浏览器就只剩"字符串在不在"可查；有了它，探针能真的入队、真的渲染、真的打包一份包出来。 */
function makeIndexedDbStub() {
  const dbs = new Map();   // name → Map(store → Map(k → v))
  const req = (result) => {
    const r = { result, error: null, onsuccess: null, onerror: null, onupgradeneeded: null };
    queueMicrotask(() => { if (r.onsuccess) r.onsuccess(); });
    return r;
  };
  return {
    open(name) {
      const fresh = !dbs.has(name);
      if (fresh) dbs.set(name, new Map());
      const stores = dbs.get(name);
      const r = { result: null, error: null, onsuccess: null, onerror: null, onupgradeneeded: null };
      r.result = {
        objectStoreNames: { contains: (s) => stores.has(s) },
        createObjectStore: (s) => { stores.set(s, new Map()); return {}; },
        transaction(store) {
          if (!stores.has(store)) stores.set(store, new Map());
          const data = stores.get(store);
          const t = { error: null, oncomplete: null, onerror: null, onabort: null,
            objectStore: () => ({
              put: (v) => { data.set(v.k, v); return req(v.k); },
              get: (k) => req(data.get(k)),
              getAll: () => req([...data.values()]),
              count: () => req(data.size),
              clear: () => { data.clear(); return req(undefined); },
            }) };
          queueMicrotask(() => { if (t.oncomplete) t.oncomplete(); });
          return t;
        },
      };
      queueMicrotask(() => {
        if (fresh && r.onupgradeneeded) r.onupgradeneeded();
        if (r.onsuccess) r.onsuccess();
      });
      return r;
    },
  };
}
globalThis.indexedDB = makeIndexedDbStub();

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
    probeTask({ id: 'p1', title: '待定的事', status: '待定', depth: 2,
      groups: ['高数 / 第三章'], group_ids: ['g2'] }),
    probeTask({ id: 'x1', title: '取消的事', status: '取消' }),
    // 谁建的（T-G6）：AI 建的卡要带「AI 建的」徽标 —— 这是"可回溯"在界面上的那一半
    probeTask({ id: 'a1', title: 'AI 加的步骤', created_by: 'ai', status: '未开始' })],
  // 「正在做」：**可以同时多个**，各带自己的顺序号（↑↓ 用 `doing_rank` 排）
  '/api/tasks/doing': [probeTask({ id: 'd1', title: '写高数作业', status: '进行中', doing_rank: 1 }),
    probeTask({ id: 'd2', title: '背单词', status: '进行中', doing_rank: 2 })],
  '/api/tasks/archived': [probeTask({ id: 'a9', title: '归档的事', status: '归档' }),
    // 档案的**另一半**（T-F2）：完成满 N 天自动收入的 —— 徽标、「试了几回」、备注都要真渲染出来
    probeTask({ id: 'af1', title: '自动收走的事', status: '完成', auto_archived: true,
      completed_on: '2026-09-17', attempt_count: 3, note: '笔记：第三章的推导' })],
  // 到点提醒（T-B5）：今日页「该提醒了」区用它
  '/api/reminders/due': [],
  // 复习线（SR-F6.2 / SR-F6.5 / SR-F8.3）：到期卡非空 —— 卡片态要渲染出「改形式/句柄」按钮，
  // 外加 T-G5 的「在 Obsidian 打开」（后端拼好的 `obsidian://` 链接 —— 界面不自己拼 URL）
  '/api/review/due': [{ id: 'r1', title: '探针复习卡', reps: 2, interval_days: 3,
    source: 'internal', ref_handle: 'notes/数学.md', form: 'qa', due_date: '2026-09-20', task_id: 't1',
    ref_url: 'obsidian://open?vault=MyVault&file=notes/%E6%95%B0%E5%AD%A6.md', ref_reason: '' }],
  '/api/review/items': [],
  // 复习卡的定义类字段（T-C6·C7）：词表来自后端，编辑态要渲染形式/执行源下拉 + 句柄输入
  '/api/review/meta': {
    forms: [{ value: 'cloze', label: '挖空' }, { value: 'qa', label: '问答卡' },
      { value: 'exam', label: '真题' }],
    sources: [{ value: 'internal', label: '内置' }, { value: 'external', label: '外部 app' }],
    // 三档反馈的中文（T-G13）：界面用它渲染三态按钮与「改判」按钮 —— 探针里也得给，
    // 否则渲染出来的是一排没有字的按钮（"没有字"在断言里很难看出来，所以要真给）。
    ratings: [{ value: 'remember', label: '记得' }, { value: 'fuzzy', label: '模糊' },
      { value: 'forgot', label: '忘了' }],
    default_form: 'qa', default_source: 'internal',
  },
  // 今天复习过的卡（T-G13）：复习页下半段 + 「改判」入口（只给另外两档）
  '/api/review/today': [{ id: 'r2', title: '今天复习过的卡', form: 'qa', source: 'internal',
    due_date: '2026-10-01', reps: 3, lapses: 0, interval_days: 9, state: 'done', task_id: null,
    feedback: 'remember', feedback_label: '记得', reviewed_at: '2026-09-23T09:10:00',
    fact_id: 'fact-r2' }],
  '/api/review/items/r1': { id: 'r1', title: '探针复习卡', form: 'qa', source: 'internal',
    due_date: '2026-09-20', reps: 2, interval_days: 3, ref_handle: 'notes/数学.md', task_id: 't1' },
  // 任务详情（右栏 #detailRail）：T-B1 起详情面板带「备注」，编辑态渲染必须也跑一遍
  '/api/tasks/t1': {
    id: 't1', title: '探针任务', due_date: '2030-01-01', group_name: null, repeat_days: null,
    parent_id: null, is_myday: true, status: '未开始', created_at: '2026-09-18T10:00:00',
    updated_at: '2026-09-18T10:00:00', version: 1, assignments: [],
    subtask_done: 0, subtask_total: 0, note: '备注也要渲染一遍', priority: '高', flagged: true,
    // 分组（T-F10）：`groups` 是**路径**、`group_ids` 是勾选状态用的 id
    groups: ['高数 / 第三章'], group_ids: ['g2'],
    // 类型 + 所属课程（T-C12）：编辑态要渲染课程下拉、只读态要渲染课程徽标
    task_type: '作业', course_id: 'c1', course_name: '高等数学',
    attach: [{ target: 'https://x.example/要求', title: '要求页' },
      { target: 'D:\\课件\\第3章.pdf', title: null }],
  },
  '/api/tasks/t1/facts': [],
  // 子步骤（F 批 · T-F4 + T-F5）：整棵子树一次给出（前序 + 绝对层数），
  // 每一步有自己的截止日 + 「明天 / 尝试失败 / 详情 / 脱离」；第 2 层那步自己还有一层（看折叠按钮）。
  '/api/tasks/t1/subtasks': [
    probeTask({ id: 's1', title: '第 1 步：读题', status: '完成', parent_id: 't1',
      due_date: '2026-09-18' }),
    probeTask({ id: 's2', title: '第 2 步：写解答', parent_id: 't1', due_date: '2026-09-25' }),
  ],
  '/api/tasks/t1/tree': [
    { task: probeTask({ id: 's1', title: '第 1 步：读题', status: '完成', parent_id: 't1',
      due_date: '2026-09-18', depth: 2 }), depth: 2 },
    { task: probeTask({ id: 's2', title: '第 2 步：写解答', parent_id: 't1',
      due_date: '2026-09-25', depth: 2 }), depth: 2 },
    { task: probeTask({ id: 's3', title: '第 2 步的第 1 小问', parent_id: 's2', depth: 3 }),
      depth: 3 },
  ],
  // 派生逾期（T-F7）：字段状态还是「未开始」、后端算出"已逾期 12 天" —— 详情面板要**两个都显示**，
  // 不能再出现"列在逾期栏里、面板却写未开始"的自相矛盾
  '/api/tasks/t9': probeTask({
    id: 't9', title: '拖了很久的事', status: '未开始', due_date: '2020-01-01', overdue_days: 12,
  }),
  // 「尝试失败」（F 批 · T-F3）：详情面板要显示「试了 N 回」+ 历次留下的说明 + 「尝试失败」入口
  '/api/tasks/t1/attempts': { count: 0, notes: [] },
  '/api/tasks/t9/attempts': { count: 3, notes: ['试了前两章，卡在第 3 题', '换了本参考书还是不行'] },
  // 分组可嵌套（F 批 · T-F5）：树序（父在子前）+ 路径 + 层数，设置页按它缩进渲染
  '/api/groups': [
    { id: 'g1', name: '高数', parent_id: null, depth: 1, path: '高数', task_count: 2 },
    { id: 'g2', name: '第三章', parent_id: 'g1', depth: 2, path: '高数 / 第三章', task_count: 1 },
  ],
  // 「完成 N 天后进档案」的 N（F 批 · T-F2）：设置页要渲染出天数输入框与口径说明
  '/api/settings/archive': { after_days: 3, default_after_days: 3, max_after_days: 365,
    note: '完成之后不是立刻收走：满 N 天自动进档案（0 = 当天就收）。' },
  // 口径与一键回退（SR-NF8 / D 批 · T-D11）：设置页要渲染出"当前做法 / 另一种做法 /
  // 影子差异（含样例）/ 回到默认位"。这里给一条真口径 + 1 处影子差异，看它是不是真按
  // "当前 → 影子"渲染，而不是只把说明文字抄一遍。
  '/api/settings/behavior': {
    max_samples: 3,
    note: '这里只有可重算的派生口径；改数据的事走上面的「备份与恢复」。',
    switch_note: '开关默认停在现状位（没动过 = 什么都没变）；影子只是拿另一套口径试算。',
    items: [{
      key: 'tasks.debt_undated_myday',
      title: '债务：无截止日的 My Day 老账',
      question: '「昨天没做完、又没有截止日」的 My Day 任务，算不算一笔债？',
      kind: 'derived',
      current: 'from_created', current_label: '算：天数从创建日算起',
      current_note: '现在的做法（F 批 · T-F8 定案 A）',
      default: 'from_created', is_default: true,
      variants: [
        { id: 'from_created', label: '算：天数从创建日算起', note: '现在的做法', is_default: true },
        { id: 'uncounted', label: '不算：不进债务卡', note: 'T-F8 之前的表现', is_default: false },
      ],
      shadow: { available: true, variant: 'uncounted', label: '不算：不进债务卡', diff_count: 1,
        samples: [{ label: '债务卡「高数作业」', current: '9 天', shadow: '不在债务里' }],
        summary: '影子跑「不算：不进债务卡」：1 处不同，下面列前 1 条。' },
    }],
  },
  // 任务 → 复习卡（T-C5）：详情面板要显示"这张任务升级出来的卡"
  '/api/tasks/t1/review-cards': [{ id: 'r1', title: '探针复习卡', due_date: '2026-09-20T00:00:00',
    form: 'qa', source: 'internal', ref_handle: 'notes/数学.md', task_id: 't1' }],
  // 债务卡（F 批 · T-F9）：数字 = 卡的张数；每张卡是**还活着的父任务**，逾期的子孙挂在它后面。
  // 这里造一张"父任务 9 天 + 挂着的第 2 题 4 天"的卡，看界面是不是真按"卡 + 挂"渲染。
  '/api/summary': { debt_count: 1, invest_hours: 0, manual_hours: 0, review_count: 0, output_count: 0,
    output_kpi: 2, output_asset: 3,
    debt_items: [{ title: '高数作业', due_date: '2026-09-10', overdue_days: 9, degree: '重',
      steps: [{ title: '第 2 题', overdue_days: 4, degree: '中' }] }] },
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
  '/api/memos': [{ id: 'm1', text: '记一条带引用的备忘', ref_handle: 'notes/数学.md', task_id: null,
    created_at: '2026-09-21T20:00:00', ref_reason: '',
    ref_url: 'obsidian://open?vault=MyVault&file=notes/%E6%95%B0%E5%AD%A6.md' }],
  '/api/ledger/outputs': [], '/api/ledger/invests': [],
  '/api/insights/daily': [], '/api/insights/groups': [],
  // 年历热力图（SR-NF7 / G 批 · T-G1 顺手修掉的缺陷）：**必须给非零值**。
  // 老代码拿短 id（'focus'）去取字段，而真字段叫 `focus_minutes` → 取不到 → 每个格子都是 0 →
  // 整张图永远灰。这里放一天有数的日子，就能靠"颜色到底出没出现过"把这条钉住。
  '/api/insights/heatmap': [
    { date: '2026-09-19', focus_minutes: 0, manual_minutes: 0, review_count: 0,
      output_count: 0, debt_count: 0 },
    { date: '2026-09-20', focus_minutes: 90, manual_minutes: 20, review_count: 3,
      output_count: 1, debt_count: 1 },
  ],
  // 热力图维度（G 批 · T-G1）：按钮由**后端词表**渲染 —— 注意 id 就是数据字段名
  '/api/insights/heatmap-dimensions': {
    note: '要算一个全新的维度仍需改核心代码。',
    items: [
      { id: 'focus_minutes', label: '专注', unit: '分钟', kind: 'minutes' },
      { id: 'review_count', label: '复习', unit: '张', kind: 'count' },
    ],
  },
  // 导出 markdown（SR-F8 / G 批 · T-G4）：设置页要显示目录、今天那份的状态、错误与口径说明。
  // 夹具里**同时**给"已写出"和"上次失败"—— 两条都该渲染出来（错误不许静默消失）。
  '/api/settings/export': {
    dir: 'D:/timeflow-export', default_dir: 'export', configured: true, exists: true,
    today: '2026-09-21', note_path: 'D:/timeflow-export/2026-09-21.md', note_exists: true,
    note_bytes: 512, last_written_at: '2026-09-21T21:10:00',
    last_error: '建不了导出目录：D:/nope（拒绝访问）',
    // Obsidian 跳转（SR-F8.2 / G 批 · T-G5）：名字 + 根目录都填了 —— 设置页要渲染出这两栏，
    // 以及"只读跳转、不往 Vault 里写"这句口径（红线写在界面上才算数）。
    vault: 'MyVault', vault_dir: 'D:/Notes/MyVault', default_vault: '', default_vault_dir: '',
    vault_configured: true, vault_overlap: '',
    vault_note: '填上 Vault 名字，引用句柄就能一键跳进 Obsidian（只读跳转）；软件不往 Vault 里写任何东西。',
    note: '数据库是权威，md 是产物：手改不会被读回，下次导出会覆盖。',
    where: '写在你自己指定的独立目录里（默认项目下 export/）—— 不写进 Obsidian 的笔记目录。',
  },
  // 可配置词表（SR-NF7 / G 批 · T-G1）：设置页要渲染出两张表（可加 / 可删 / 可回默认）
  '/api/settings/vocab': {
    note: '词表只决定「能选什么 / 叫什么」，不改计算。',
    items: [
      { key: 'review_forms', title: '复习形式',
        question: '建复习卡时「形式」这一栏有哪几种？',
        items: [{ id: 'cloze', label: '挖空' }, { id: 'qa', label: '问答卡' }],
        defaults: [{ id: 'cloze', label: '挖空' }], is_default: true, allowed: [],
        free_id: true, max_items: 20, note: '形式只是标签，所以你想起什么名字都行。' },
      { key: 'heatmap_dimensions', title: '时间热力图的维度',
        question: '统计页那张年历热力图，可以按哪些维度看、分别叫什么？',
        items: [{ id: 'focus_minutes', label: '专注' }, { id: 'review_count', label: '复习' }],
        defaults: [], is_default: false, allowed: ['focus_minutes', 'review_count'],
        free_id: false, max_items: 8, note: '要算一个全新的维度仍需改核心代码。' },
    ],
  },
  // AI 接口（SR-F7.3 / G 批 · T-G6）：设置页要渲染出开关、边界、动作表与示例命令（可复制）；
  // 夹具给"开着"这一态（关着那一态只差一个 bool，断言值不落在这里）。
  '/api/settings/ai': {
    enabled: true, default_enabled: false, configured: true,
    boundary: '只读 + 新增 + 勾自己建的：AI 能读任务、能建任务与步骤，只能勾它自己建的。',
    why: '为什么这么收：判据从改不改换成动的是不是你亲手写的东西。',
    note: 'AI 的每一次状态变化都发事实（source=ai）；默认关。',
    surface: [
      { method: 'GET', path: '/api/ai/ping', what: '自证：接口开着吗、边界是什么' },
      { method: 'POST', path: '/api/ai/tasks', what: '新增：建任务；给 parent_id 就是加一个步骤' },
    ],
    example: 'curl http://127.0.0.1:8000/api/ai/ping',
  },
  // 局域网访问 + 配对码（SR-NF17 / G 批 · T-G10b / 场景 ②）
  '/api/settings/lan': {
    lan_open: true, config_allow_lan: true, pairing_required: true,
    addresses: ['http://192.168.1.23:8520'], code: '246810', code_visible: true,
    header: 'X-Timeflow-Pair',
    note: '局域网访问只在**同一个 WiFi 里**管用，不涉及公网；配对码是那道门。',
  },
  // 学校通知的合作接口（SR-F10.1 / G 批 · T-G14）：开关 + 字段表 + 收件箱
  '/api/settings/notify': {
    enabled: true, default_enabled: false, configured: true, total: 3,
    surface: [{ method: 'POST', path: '/api/notify/school', what: '投递一条通知（脚本用）' }],
    fields: [{ name: 'source', required: true, what: '来源标记（哪个网站/群）' },
      { name: 'title', required: true, what: '标题（任务就用它当标题）' }],
    statuses: [{ value: 'new', label: '待看', count: 1 },
      { value: 'converted', label: '已转任务', count: 1 },
      { value: 'ignored', label: '已忽略', count: 1 }],
    boundary: '主工具**不去网上抓**：监测由你自己的独立脚本做，这里只是收件箱。',
    why: '为什么不抓：规格把抓取划给独立脚本。',
    note: '转任务要你点一下。',
    example: 'curl -X POST http://127.0.0.1:8000/api/notify/school \\\n  -d \'{"source":"教务处","title":"期中安排"}\'',
  },
  '/api/notify/school': { count: 3, items: [
    { id: 'n1', source: '教务处网站', external_id: 'A-1', title: '期中考试安排已发布',
      url: 'https://example.edu/x', summary: '考场在第 3 教学楼', at: '2026-09-17T09:30:00',
      due_date: '2026-10-08', received_at: '2026-09-17T10:00:00', status: 'new',
      status_label: '待看', task_id: null, extra: { 批次: '第 1 批' } },
    { id: 'n2', source: '班级群', title: '实验报告提交时间改了', url: null, summary: null,
      at: null, due_date: null, received_at: '2026-09-17T09:00:00', status: 'converted',
      status_label: '已转任务', task_id: 't1', extra: {} },
    { id: 'n3', source: '公众号', title: '某个不相关的讲座', url: null, summary: null,
      at: null, due_date: null, received_at: '2026-09-16T09:00:00', status: 'ignored',
      status_label: '已忽略', task_id: null, extra: {} },
  ] },
  '/api/sync/status': {
    file_sync: true, network_sync: false, device_id: 'probe-device-1', tombstones: 2,
    conflict_logs: 3,
    last_export: { at: '2026-09-22T21:00:00', path: 'D:/data/sync-x-1.json', rows: 12 },
    last_import: { at: '2026-09-22T21:05:00', from_device: 'other',
      totals: { inserted: 4, updated: 1, kept: 2, tombstoned: 0, tombstone_added: 1 },
      conflict_count: 1 },
    note: '走文件的跨端同步：在一台机器导出同步包，拷到另一台导入。导入不会删你本地的任何东西。',
  },
};
// 团队视角页（SR-F7.1 / OP-33 / T-G12）：**同一份记录两种看法**，所以要按 query 回不同形状 ——
// 探针这里只演"界面拿到这两种数据会渲染成什么"，真正的归组/过滤规则由后端负责，
// 后端那一侧由 `tests/test_team_view_line.py` + `tools/web_live_check.py` 真跑兜着。
const TEAM_ITEM_ASSIGNED = { id: 'as1', task_id: 't1', assignee: '小王', assigner: 'me',
  note: '周五前给初稿', status: 'assigned', task_title: '探针任务', task_due: '2030-01-01',
  task_status: '未开始', task_missing: false, task_deleted: false, created_at: '2026-09-22' };
const TEAM_ITEM_BLOCKED = { id: 'as2', task_id: 'gone-task', assignee: '小王', assigner: 'me',
  note: null, status: 'blocked', task_title: null, task_due: null, task_status: null,
  task_missing: true, task_deleted: false, created_at: '2026-09-22' };
// 软删（进回收站）与彻底删除**不是一回事**：软删的任务还在，标题照显示、后面注明"在回收站"
const TEAM_ITEM_RECYCLED = { id: 'as3', task_id: 'trash-task', assignee: '小王', assigner: 'me',
  note: null, status: 'done', task_title: '扔进回收站的事', task_due: null, task_status: '已删',
  task_missing: false, task_deleted: true, created_at: '2026-09-22' };
const TEAM_VIEWS = [{ value: 'manager', label: '管理者（我分配的）' },
  { value: 'executor', label: '执行者（分配给我的）' }];
const TEAM_STATUSES = [{ value: 'assigned', label: '已分配', count: 1 },
  { value: 'in_progress', label: '进行中', count: 0 }, { value: 'done', label: '已完成', count: 1 },
  { value: 'blocked', label: '受阻', count: 1 }];
const TEAM_BOARD = {
  manager: {
    view: 'manager', me: '', status_filter: '', views: TEAM_VIEWS, statuses: TEAM_STATUSES,
    groups: [{ assignee: '小王', count: 3,
      items: [TEAM_ITEM_ASSIGNED, TEAM_ITEM_BLOCKED, TEAM_ITEM_RECYCLED] }],
    total: 3, shown: 3,
    note: '你分配出去的任务都在这里：谁手上有什么、进展到哪。分配出去的任务不计个人投入（只记协调这件事本身）。',
  },
  executor: {
    view: 'executor', me: '小王', status_filter: '', views: TEAM_VIEWS, statuses: TEAM_STATUSES,
    groups: [{ assignee: '小王', count: 1, items: [TEAM_ITEM_ASSIGNED] }],
    total: 1, shown: 1,
    note: '分给「小王」的任务：进展由你自己回报（点下一步动作）。不强制对方装这个软件。',
  },
  executor_no_me: {
    view: 'executor', me: '', status_filter: '', views: TEAM_VIEWS, statuses: TEAM_STATUSES,
    groups: [], total: 0, shown: 0,
    note: '执行者视角要先说「我是谁」—— 分配记录里的名字是你自己填的自由文本，工具没有账号体系，不猜你是谁。填一个名字，就能看分给你的那几件。',
  },
};
globalThis.fetch = async (path) => {
  const key = String(path).split('?')[0];
  if (key === '/api/team/board') {
    const q = new URL(String(path), 'http://probe').searchParams;
    const view = q.get('view') === 'executor' ? 'executor' : 'manager';
    const me = q.get('me') || '';
    const body = view === 'executor' && !me ? TEAM_BOARD.executor_no_me : TEAM_BOARD[view];
    return { ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body) };
  }
  const body = key in DB ? DB[key] : null;
  return { ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body) };
};

const problems = [];
process.on('unhandledRejection', (e) => problems.push(`unhandledRejection: ${(e && e.message) || e}`));
const realWarn = console.warn;
console.warn = (...a) => problems.push('warn: ' + a.join(' '));

try {
  // 手机离线记的引擎（页面里是 `<script src="/offline.js">`）：先求值，再把它挂成全局 ——
  // 页面脚本里是**裸 `TFOffline`**（真浏览器里它就是全局），这里的假 window 只是普通对象。
  new Function('window', readFileSync(OFFLINE, 'utf8')
    + '\n;globalThis.TFOffline=window.TFOffline;')(globalThis.window);
} catch (e) {
  console.log(`❌ offline.js 求值就抛错：${e.message}`);
  process.exit(1);
}
try {
  new Function(code + '\n;globalThis.__view=view;globalThis.__showDetail=showDetail;'
    + 'globalThis.__render=render;globalThis.__setEdit=v=>{detailEditing=v};'
    + 'globalThis.__setDoneOpen=v=>{doneOpen=v};globalThis.__setReviewEdit=v=>{reviewEdit=v};'
    + 'globalThis.__pairWall=pairWallHTML;')();
} catch (e) {
  console.log(`❌ 脚本求值就抛错：${e.message}`);
  process.exit(1);
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const views = ['today', 'tasks', 'important', 'planned', 'flagged', 'focus', 'stats', 'habit',
  'academic', 'review', 'memo', 'team', 'setting', 'offline'];
let bad = 0;
let detailBad = 0;
let doneBad = 0;
let reviewBad = 0;
let regradeBad = 0;
let hardBad = 0;
let guardBad = 0;
let stateBad = 0;
let overdueBad = 0;
let attemptBad = 0;
let archiveBad = 0;
let stepBad = 0;
let debtBad = 0;
let behaviorBad = 0;
let obsidianBad = 0;
let aiBad = 0;
let syncBad = 0;
let vocabBad = 0;
let heatmapBad = 0;
let exportBad = 0;
let offlineBad = 0;
let lanBad = 0;
let teamBad = 0;
let noticeBad = 0;
let boldBad = 0;
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

/* 复习·改判（T-G13）：复习页下半段「今天复习过的」——
   ① 卡片上要写明**今天记的是哪一档**（否则改判时不知道从哪改到哪）；
   ② 「改判为」只给**另外两档**（同一个档不给按钮）；
   ③ 反证：那一段里不许出现"和现在一样"的那一档按钮（否则用户点了会吃 400）；
   ④ 空态：今天还没复习过时给一句带路的说明（不是干巴巴「暂无数据」）。 */
const regradeChecks = [];
try {
  globalThis.__setReviewEdit({ id: null, item: null, meta: null });
  byId.get('main')._html = '';
  await globalThis.__view('review');
  await sleep(30);
  const html = byId.get('main')._html;
  // 切两段：`[0]` = 标题之前，`[1]` = 「今天复习过的」之后的那一段（要查的内容都在里面）。
  const done = html.split('今天复习过的（1）')[1] || '';
  const needs = ['今天记的是', '记得', '改判为',
    'data-action="review-regrade"', 'data-feedback="fuzzy"', 'data-feedback="forgot"',
    '撤销这次'];
  const missing = needs.filter((n) => !done.includes(n));
  const pure = !done.includes('data-feedback="remember"');   // 当前那一档不该给按钮

  const saved = DB['/api/review/today'];
  DB['/api/review/today'] = [];
  byId.get('main')._html = '';
  await globalThis.__view('review');
  await sleep(30);
  const emptyHtml = byId.get('main')._html;
  DB['/api/review/today'] = saved;
  const emptyOk = emptyHtml.includes('今天还没复习过卡') && emptyHtml.includes('还能改判');

  const rendered = missing.length === 0 && pure && emptyOk;
  if (!rendered) regradeBad++;
  regradeChecks.push({ rendered, missing, pure, emptyOk });
  console.log(`  ${rendered ? '✅' : '⚠️ '} 复习·改判 main ${String(html.length).padStart(6)}B`
    + `（只给另外两档 ${pure ? '对' : '不对'}·空态 ${emptyOk ? '带路' : '没带路'}）`
    + (missing.length ? `  缺: ${missing.join(', ')}` : ''));
} catch (e) {
  regradeBad++;
  regradeChecks.push({ error: e.message });
  console.log(`  ❌ 复习·改判 渲染抛错: ${e.message}`);
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

// 口径与一键回退（D 批 · T-D11）：设置页那一节要真渲染出"当前做法 / 另一种做法 /
// 影子差异（连样例的『当前 → 影子』都要有）/ 一键回到默认位"。
const behaviorChecks = [];
for (const [view, needs] of [
  ['setting', ['口径与回退', '债务：无截止日的 My Day 老账', '算：天数从创建日算起',
    '不算：不进债务卡', 'set-behavior', 'behavior-reset', '回到默认位', '默认位',
    '影子跑「不算：不进债务卡」：1 处不同', '债务卡「高数作业」：9 天 → 不在债务里']],
]) {
  try {
    byId.get('main')._html = '';
    await globalThis.__view(view);
    await sleep(30);
    const html = byId.get('main')._html;
    const missing = needs.filter((n) => !html.includes(n));
    const rendered = missing.length === 0;
    if (!rendered) behaviorBad++;
    behaviorChecks.push({ view, rendered, missing });
    console.log(`  ${rendered ? '✅' : '⚠️ '} ${view}·口径回退 main ${String(html.length).padStart(6)}B`
      + (missing.length ? `  缺: ${missing.join(', ')}` : ''));
  } catch (e) {
    behaviorBad++;
    behaviorChecks.push({ view, error: e.message });
    console.log(`  ❌ ${view}·口径回退 渲染抛错: ${e.message}`);
  }
}

// 可配置词表（SR-NF7 / G 批 · T-G1）：设置页那一节是**通用渲染** —— 后端给几张表就画几张，
// 每张表都能加一项、删一项、回默认，且"只能从这些 id 里选"的表要把可选 id 写出来。
const vocabChecks = [];
for (const [view, needs] of [
  ['setting', ['可配置词表', '复习形式', '时间热力图的维度', '建复习卡时「形式」这一栏有哪几种？',
    '挖空', '问答卡', 'vocab-add', 'vocab-del', 'vocab-reset', '回到默认',
    '只能从这些 id 里选：focus_minutes · review_count']],
]) {
  try {
    byId.get('main')._html = '';
    await globalThis.__view(view);
    await sleep(30);
    const html = byId.get('main')._html;
    const missing = needs.filter((n) => !html.includes(n));
    const rendered = missing.length === 0;
    if (!rendered) vocabBad++;
    vocabChecks.push({ view, rendered, missing });
    console.log(`  ${rendered ? '✅' : '⚠️ '} ${view}·可配置词表 main ${String(html.length).padStart(6)}B`
      + (missing.length ? `  缺: ${missing.join(', ')}` : ''));
  } catch (e) {
    vocabBad++;
    vocabChecks.push({ view, error: e.message });
    console.log(`  ❌ ${view}·可配置词表 渲染抛错: ${e.message}`);
  }
}

// 年历热力图（G 批 · T-G1 顺手修的缺陷）：维度按钮来自后端词表；**关键断言是"颜色真的出现过"** ——
// 老代码按短 id（'focus'）取字段（真字段叫 focus_minutes）→ 取不到 → 全是 0 → 整张图永远灰，
// 而"能渲染出按钮/说明"这种断言照样会绿。所以这里必须断言 SVG 里出现过 `var(--accent)`。
const heatmapChecks = [];
try {
  byId.get('main')._html = '';
  await globalThis.__view('stats');
  await sleep(30);
  const html = byId.get('main')._html;
  const needs = ['时间热力图（近一年）', 'data-action="set-heatmap" data-metric="focus_minutes"',
    'data-action="set-heatmap" data-metric="review_count"', '专注 · 颜色越深=当天投入越多',
    'var(--accent)'];
  const missing = needs.filter((n) => !html.includes(n));
  // 反证：老代码那种"取不到值"的图里，所有格子都是 `--surface-2`，不会出现 accent
  const hasAccent = html.includes('var(--accent)');
  const rendered = missing.length === 0 && hasAccent;
  if (!rendered) heatmapBad++;
  heatmapChecks.push({ rendered, missing, hasAccent });
  console.log(`  ${rendered ? '✅' : '⚠️ '} stats·热力图有值渲染 main ${String(html.length).padStart(6)}B`
    + (missing.length ? `  缺: ${missing.join(', ')}` : ''));
} catch (e) {
  heatmapBad++;
  heatmapChecks.push({ error: e.message });
  console.log(`  ❌ stats·热力图 渲染抛错: ${e.message}`);
}

// 导出 markdown（SR-F8 / G 批 · T-G4）：设置页要显示目录输入框、今天那份的状态、**上次的错误**，
// 以及两条口径说明（数据库权威 / 不写进 Obsidian 笔记目录）—— 后者是红线，写在界面上才算数。
const exportChecks = [];
for (const [view, needs] of [
  ['setting', ['导出（Markdown）', 'id="exportDir"', 'set-export-dir', 'export-day', '打开目录',
    '2026-09-21.md', '已写出', 'D:/timeflow-export',
    '上次导出失败：建不了导出目录：D:/nope（拒绝访问）',
    '数据库是权威，md 是产物', '不写进 Obsidian 的笔记目录']],
]) {
  try {
    byId.get('main')._html = '';
    await globalThis.__view(view);
    await sleep(30);
    const html = byId.get('main')._html;
    const missing = needs.filter((n) => !html.includes(n));
    const rendered = missing.length === 0;
    if (!rendered) exportBad++;
    exportChecks.push({ view, rendered, missing });
    console.log(`  ${rendered ? '✅' : '⚠️ '} ${view}·导出 markdown main ${String(html.length).padStart(6)}B`
      + (missing.length ? `  缺: ${missing.join(', ')}` : ''));
  } catch (e) {
    exportBad++;
    exportChecks.push({ view, error: e.message });
    console.log(`  ❌ ${view}·导出 markdown 渲染抛错: ${e.message}`);
  }
}

// 子步骤（F 批 · T-F4）：主任务卡上显示「当前该做哪一步」；
// 详情里每一步都有截止日输入框与「明天 / 尝试失败 / 详情 / 脱离」，添加步骤那一行也有日期框。
const stepChecks = [];
for (const [where, needs] of [
  ['tasks', ['步骤 1/3', '当前：第 2 步：写解答', '2026-09-25 前', '子任务', '高数 / 第三章']],
  ['detail', ['第 2 步：写解答', 'subtask-due', 'id="subtaskDue"', '尝试失败', '脱离',
    '第 2 步的第 1 小问', '子步骤', 'step-toggle', 'data-group="g2"']],
  ['group', ['高数 / 第三章', 'group-sub', 'group-parent', 'id="groupParent"']],
]) {
  try {
    let html = '';
    if (where === 'tasks') {
      byId.get('main')._html = '';
      await globalThis.__view('tasks');
      await sleep(30);
      html = byId.get('main')._html;
    } else if (where === 'group') {
      // 分组管理是设置页里**异步渲染进 #groupAdmin 那一块**的（不在 main 的 HTML 里），
      // 所以要读它自己的节点 —— 这也是这段检查存在的意义：那条异步路径以前没人测。
      byId.get('main')._html = '';
      byId.get('groupAdmin')._html = '';
      await globalThis.__view('setting');
      await sleep(60);
      html = byId.get('groupAdmin')._html;
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

// 债务卡（F 批 · T-F9）：日常视图里 "逾期共 N 项" 后面要是**父任务卡 + 挂在它下面的步**，
// 而不是把每一步都当成一条独立债务（那是用户明确不要的）。
const debtChecks = [];
try {
  byId.get('main')._html = '';
  await globalThis.__view('today');
  await sleep(30);
  const html = byId.get('main')._html;
  const needs = ['逾期共 1 项', '高数作业(重·9天)', '第 2 题(中·4天)'];
  const missing = needs.filter((n) => !html.includes(n));
  const rendered = missing.length === 0;
  if (!rendered) debtBad++;
  debtChecks.push({ rendered, missing });
  console.log(`  ${rendered ? '✅' : '⚠️ '} 今日·债务卡 main ${String(html.length).padStart(6)}B`
    + (missing.length ? `  缺: ${missing.join(', ')}` : ''));
} catch (e) {
  debtBad++;
  debtChecks.push({ error: e.message });
  console.log(`  ❌ 今日·债务卡 渲染抛错: ${e.message}`);
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

// Obsidian 跳转（SR-F8.2 / G 批 · T-G5）：三处都要真渲染出来 ——
// 设置页的 Vault 两栏（名字/根目录）+「只读跳转」口径；复习卡与备忘录上的「在 Obsidian 打开」
// （**按钮只在后端给了链接时才出现** —— 没配 Vault 时不该摆个点了没用的按钮）。
const obsidianChecks = [];
for (const [where, needs] of [
  ['setting', ['id="vaultName"', 'id="vaultDir"', 'set-vault', 'Obsidian（只读跳转）',
    'value="MyVault"', 'value="D:/Notes/MyVault"', '已填：', '不往 Vault 里写任何东西']],
  ['review', ['data-action="vault-open"', 'data-handle="notes/数学.md"', '在 Obsidian 打开']],
  ['memo', ['data-action="vault-open"', 'data-handle="notes/数学.md"', '在 Obsidian 打开']],
]) {
  try {
    byId.get('main')._html = '';
    await globalThis.__view(where);
    await sleep(30);
    const html = byId.get('main')._html;
    const missing = needs.filter((n) => !html.includes(n));
    const rendered = missing.length === 0;
    if (!rendered) obsidianBad++;
    obsidianChecks.push({ where, rendered, missing });
    console.log(`  ${rendered ? '✅' : '⚠️ '} ${where}·Obsidian 跳转 main ${String(html.length).padStart(6)}B`
      + (missing.length ? `  缺: ${missing.join(', ')}` : ''));
  } catch (e) {
    obsidianBad++;
    obsidianChecks.push({ where, error: e.message });
    console.log(`  ❌ ${where}·Obsidian 跳转 渲染抛错: ${e.message}`);
  }
}

// 没配 Vault 时**不许**出现那个按钮（否则用户点了只会得到一句"还没填 Vault 名字"）：
// 把夹具换成一个没有 ref_url 的卡，同一个视图再渲染一遍，按钮必须消失。
try {
  DB['/api/review/due'][0] = { ...DB['/api/review/due'][0], ref_url: '' };
  byId.get('main')._html = '';
  await globalThis.__view('review');
  await sleep(30);
  const html = byId.get('main')._html;
  const ok = !html.includes('data-action="vault-open"') && html.includes('引用 notes/数学.md');
  if (!ok) obsidianBad++;
  obsidianChecks.push({ where: 'no-vault', rendered: ok });
  console.log(`  ${ok ? '✅' : '⚠️ '} review·没配 Vault 时不摆按钮`);
  DB['/api/review/due'][0] = { ...DB['/api/review/due'][0],
    ref_url: 'obsidian://open?vault=MyVault&file=notes/%E6%95%B0%E5%AD%A6.md' };
} catch (e) {
  obsidianBad++;
  obsidianChecks.push({ where: 'no-vault', error: e.message });
  console.log(`  ❌ review·没配 Vault 时不摆按钮 渲染抛错: ${e.message}`);
}

// AI 接口（SR-F7.3 / G 批 · T-G6）：设置页那一节要真渲染出 **开关（现在开着）+ 边界 + 动作表 +
// 示例命令（可复制）**；任务卡上要出现「AI 建的」徽标（你建的**不**标 —— 反证在下面）。
const aiChecks = [];
for (const [where, needs] of [
  ['setting', ['set-ai', 'data-on="true"', 'data-on="false"', 'AI 接口（只读 + 新增）',
    '只读 + 新增 + 勾自己建的', 'GET /api/ai/ping', 'POST /api/ai/tasks',
    'curl http://127.0.0.1:8000/api/ai/ping', 'ai-copy', '复制示例命令',
    '动的是不是你亲手写的东西']],
  ['tasks', ['AI 建的', 'AI 加的步骤']],
]) {
  try {
    byId.get('main')._html = '';
    await globalThis.__view(where);
    await sleep(30);
    const html = byId.get('main')._html;
    const missing = needs.filter((n) => !html.includes(n));
    const rendered = missing.length === 0;
    if (!rendered) aiBad++;
    aiChecks.push({ where, rendered, missing });
    console.log(`  ${rendered ? '✅' : '⚠️ '} ${where}·AI 接口 main ${String(html.length).padStart(6)}B`
      + (missing.length ? `  缺: ${missing.join(', ')}` : ''));
  } catch (e) {
    aiBad++;
    aiChecks.push({ where, error: e.message });
    console.log(`  ❌ ${where}·AI 接口 渲染抛错: ${e.message}`);
  }
}
// 反证：**你建的**任务不许带那枚徽标（否则"AI 建的"这个标记就没意义了）
try {
  byId.get('main')._html = '';
  await globalThis.__view('tasks');
  await sleep(30);
  const html = byId.get('main')._html;
  const badgeCount = (html.match(/AI 建的/g) || []).length;
  const titles = (html.match(/普通任务/g) || []).length;
  const ok = badgeCount === 1 && titles >= 1;
  if (!ok) aiBad++;
  aiChecks.push({ where: 'badge-count', rendered: ok });
  console.log(`  ${ok ? '✅' : '⚠️ '} tasks·只有 AI 建的那张带徽标（徽标 ${badgeCount} 个 / 普通任务 ${titles} 张）`);
} catch (e) {
  aiBad++;
  aiChecks.push({ where: 'badge-count', error: e.message });
  console.log(`  ❌ tasks·徽标反证 渲染抛错: ${e.message}`);
}

// 跨端同步（SR-F9.2 / G 批 · T-G8，场景 ③）：设置页要真渲染出 **导出/预览/导入三个入口 +
// 设备号 + 上次导出/导入的读数 + 边界说明**（"导入不会删你本地的任何东西"这句必须在界面上）。
const syncChecks = [];
for (const [where, needs] of [
  ['setting', ['set-syncpack', '跨端同步（走文件）', 'sync-export', 'sync-preview', 'sync-import',
    'id="syncPath"', 'probe-device-1', '上次导出：2026-09-22 21:00:00 · 12 行',
    '上次导入：2026-09-22 21:05:00 · 新增 4 / 覆盖 1',
    '不含', 'schema 版本',
    // T-G8b：删除是**可选项**（默认不删 + 勾选框 + 代价写在界面上）
    'id="syncDel"', 'data-change="sync-del-toggle"', '同时应用对方的删除', '默认不删', '不可撤销']],
]) {
  try {
    byId.get('main')._html = '';
    await globalThis.__view(where);
    await sleep(30);
    const html = byId.get('main')._html;
    const missing = needs.filter((n) => !html.includes(n));
    const rendered = missing.length === 0;
    if (!rendered) syncBad++;
    syncChecks.push({ where, rendered, missing });
    console.log(`  ${rendered ? '✅' : '⚠️ '} ${where}·跨端同步 main ${String(html.length).padStart(6)}B`
      + (missing.length ? `  缺: ${missing.join(', ')}` : ''));
  } catch (e) {
    syncBad++;
    syncChecks.push({ where, error: e.message });
    console.log(`  ❌ ${where}·跨端同步 渲染抛错: ${e.message}`);
  }
}

/* 手机离线记（SR-NF17 / G 批 · T-G10，场景 ①）：这一档不只查"渲染出来了"，而是
   **真的往（内存版）IndexedDB 里入队 → 页面真渲染 → 真的打出一份包**。
   为什么必须真跑：手机侧的错（入队键错、包结构错）在字符串层面完全看不出来，
   真要等拷到手机才发现。打出来的包结构与"能被电脑吃下去"由
   `tests/test_offline_phone_line.py` 接着验（那边把它真导进一个真库）。 */
const offlineChecks = [];
try {
  const OFF = globalThis.TFOffline;
  if (!OFF) throw new Error('页面里没有 TFOffline（offline.js 没被加载？）');
  await OFF.enqueue('memos', OFF.PURE.memoRow({ text: '探针离线记一条', at: '2026-09-23T20:15:00' }));
  await OFF.enqueue('habit_logs', OFF.PURE.habitRow('h1', '2026-09-23', true));
  const pending = await OFF.pendingCount();
  // 「上次看到的」（T-G16）：先把**联网时看一遍**这件事真的做出来 —— 临时换上有内容的桩，
  // 渲染今日页（它会拉 mydays/overdue/reminders/summary），那几份响应会被 rememberForOffline 缓存；
  // 再渲染离线页，那几段就该有东西。跑完把桩还原（别的档还要用空列表）。
  const saved = {
    mydays: DB['/api/mydays'], overdue: DB['/api/overdue'],
    reminders: DB['/api/reminders/due'], summary: DB['/api/summary'],
  };
  DB['/api/mydays'] = [probeTask({ id: 't1', title: '今天要做的', is_myday: true,
    remind_at: '2026-09-23T21:00', reminder_state: 'today' })];
  DB['/api/overdue'] = [probeTask({ id: 't2', title: '欠着的事', due_date: '2026-09-20',
    overdue_days: 3, status: '逾期' })];
  DB['/api/reminders/due'] = [probeTask({ id: 't3', title: '该提醒的事',
    remind_at: '2026-09-23T08:30', reminder_state: 'over' })];
  DB['/api/summary'] = { ...saved.summary, debt_count: 2, invest_hours: 1.5, review_count: 3 };
  byId.get('main')._html = '';
  await globalThis.__view('today');
  await sleep(40);
  byId.get('main')._html = '';
  await globalThis.__view('offline');
  await sleep(40);
  const html = byId.get('main')._html;
  Object.assign(DB, { '/api/mydays': saved.mydays, '/api/overdue': saved.overdue,
    '/api/reminders/due': saved.reminders, '/api/summary': saved.summary });
  const needs = ['手机离线记', 'id="offlineStatus"', 'id="offlineQueue"', '离线记一笔',
    'offline-task-add', 'offline-memo-add', 'offline-feedback-save', 'offline-export',
    'offline-copy', 'offline-clear', '待同步（2）', '备忘 · 探针离线记一条',
    '习惯打卡 · 2026-09-23', '<b>不会清空</b>队列', '<b>重复导入是安全的</b>', '同一个 WiFi',
    '会写进包里',
    // T-G15（直接传到电脑）：按钮 + 那段实话（合并规则在电脑那边、失败绝不清空）
    'offline-upload', '直接传到电脑', '合并规则仍然只在电脑那边', '<b>失败绝不清空</b>',
    // T-G16（更完整的"看"）：四段只读清单 + 今日摘要 + 提醒时间的口径
    'id="offlineSeen"', '上次看到的（只读）', '今日摘要（上次联网时）',
    '该提醒了（1）', '该提醒的事', '提醒时间 2026-09-23 08:30',
    '今天该复习（', '逾期（1）', '欠着的事', '逾期 3 天',
    '<b>只标出来、不发系统通知</b>', '<b>上次联网时看到的样子</b>'];
  const missing = needs.filter((n) => !html.includes(n));
  // 反证：只读区里**不许**出现"只看不改"以外能改数据的东西（提醒是"标出来"，不是"点掉"）
  const seenBlock = html.split('id="offlineSeen"', 2)[1] || '';
  const seenPure = !seenBlock.includes('offline-done') && !seenBlock.includes('offline-habit');
  const packed = await OFF.packOnce();
  const parsed = JSON.parse(packed.text);
  const packOk = parsed.format === 'timeflow-sync' && parsed.format_version === 1
    && parsed.device_id.startsWith('ph-')
    && parsed.tables.memos.length === 1 && parsed.tables.habit_logs.length === 1
    && (parsed.tables.habit_logs[0] || {}).done === 1
    && packed.rows === 2 && Array.isArray(parsed.tombstones) && parsed.tombstones.length === 0
    // 上传走的就是这个 `pack` 对象（不再从文本里反解一遍）—— 它必须跟 text 是同一份
    && JSON.stringify(packed.pack) === JSON.stringify(parsed);
  // 反证：包文本里**不许**出现这台设备的设置（那是"这台机器的事"，不跟着包走）
  const noSettings = !packed.text.includes('app_settings');
  const rendered = missing.length === 0 && packOk && noSettings && pending === 2 && seenPure;
  if (!rendered) offlineBad++;
  offlineChecks.push({ rendered, missing, packOk, noSettings, pending, seenPure });
  console.log(`  ${rendered ? '✅' : '⚠️ '} offline·手机离线记 main ${String(html.length).padStart(6)}B`
    + `（队列 ${pending} 条 · 包 ${packed.rows} 行 · ${packOk ? '结构对' : '结构不对'}`
    + `${noSettings ? '' : ' · 混进了设置表'}`
    + ` · 只读区${seenPure ? '干净' : '混进了能改数据的东西'}）`
    + (missing.length ? `  缺: ${missing.join(', ')}` : ''));
} catch (e) {
  offlineBad++;
  offlineChecks.push({ error: e.message });
  console.log(`  ❌ offline·手机离线记 渲染抛错: ${e.message}`);
}

/* 设置·学校通知（SR-F10.1 / G 批 · T-G14）：合作接口那一节 + 收件箱 ——
   ① 开关、边界实话、字段表、示例命令、（其它字段不丢）都要真渲染出来；
   ② 收件箱三种状态各一条，**按钮要跟着状态变**：
      待看 → 「转成任务」(×2) + 「忽略」；已转任务 → 只有「打开原文」（不许再给"转成任务"）；
      已忽略 → 「改回待看」；
   ③ 反证：接口关着 + 空收件箱时，那句话是"接口关着…"而不是"接口开着…"（两种空态分得开）。 */
const noticeChecks = [];
try {
  byId.get('main')._html = '';
  await globalThis.__view('setting');
  await sleep(40);
  const html = byId.get('main')._html;
  const inbox = html.split('收件箱（', 2)[1] || '';
  const needs = ['id="set-notify"', 'data-action="set-notify"', 'data-action="notify-copy"',
    '不去网上抓', 'source', 'title', 'data-action="notice-to-task"', '转成任务（加入今天）',
    'data-action="notice-ignore"', 'data-action="attach-open"',
    '期中考试安排已发布', '另有 1 个额外字段', '待看 1', '已转任务 1', '已忽略 1'];
  const missing = needs.filter((n) => !html.includes(n));
  // 三种状态的按钮各不相同：已转任务那条不许再出现「转成任务」
  const converted = inbox.split('实验报告提交时间改了')[1] || '';
  const convertedCard = converted.split('</div></div>')[0];
  const convertedOk = !convertedCard.includes('notice-to-task');
  const ignored = inbox.split('某个不相关的讲座')[1] || '';
  const ignoredCard = ignored.split('</div></div>')[0];
  const ignoredOk = ignoredCard.includes('改回待看') && ignoredCard.includes('data-ignored="0"');

  // 空态：关着 + 空收件箱 → 说的是"接口关着"，不是"接口开着"
  const savedCfg = DB['/api/settings/notify'];
  const savedList = DB['/api/notify/school'];
  DB['/api/settings/notify'] = { ...savedCfg, enabled: false, total: 0,
    statuses: savedCfg.statuses.map((s) => ({ ...s, count: 0 })) };
  DB['/api/notify/school'] = { count: 0, items: [] };
  byId.get('main')._html = '';
  await globalThis.__view('setting');
  await sleep(40);
  const emptyHtml = byId.get('main')._html;
  DB['/api/settings/notify'] = savedCfg;
  DB['/api/notify/school'] = savedList;
  const emptyOk = emptyHtml.includes('接口关着，收件箱是空的')
    && !emptyHtml.includes('接口开着，但还没有通知投递进来');

  const rendered = missing.length === 0 && convertedOk && ignoredOk && emptyOk;
  if (!rendered) noticeBad++;
  noticeChecks.push({ rendered, missing, convertedOk, ignoredOk, emptyOk });
  console.log(`  ${rendered ? '✅' : '⚠️ '} 设置·学校通知 main ${String(html.length).padStart(6)}B`
    + `（按钮随状态变 ${convertedOk && ignoredOk ? '对' : '不对'}·空态 ${emptyOk ? '分得开' : '混了'}）`
    + (missing.length ? `  缺: ${missing.join(', ')}` : ''));
} catch (e) {
  noticeBad++;
  noticeChecks.push({ error: e.message });
  console.log(`  ❌ 设置·学校通知 渲染抛错: ${e.message}`);
}

/* 团队视角页（SR-F7.1 / OP-33 / T-G12）：两个视角都要真渲染 + 三处反证 ——
   ① 管理者视角：按执行者分组、标「我分配」、能点"下一步"、任务被删的那条如实标"保留审计"；
   ② 执行者视角（说了名字）：标「分配给我」、只留这个人的；
   ③ 执行者视角（**没说名字**）：不猜 —— 出输入框 + 空态说明，且不许冒出"分配给我"的条目；
   ④ 反证：管理者视角里不许出现「分配给我」（两个视角是**两种看法**，不是同一坨文字）。
   视角与名字存在本机 localStorage 里，所以这一段临时换成能真存的内存实现，跑完还原。 */
const teamChecks = [];
try {
  const realLocalStorage = globalThis.localStorage;
  const mem = {};
  const useStore = (init) => {
    for (const k of Object.keys(mem)) delete mem[k];
    Object.assign(mem, init || {});
    globalThis.localStorage = {
      getItem: (k) => (k in mem ? mem[k] : null),
      setItem: (k, v) => { mem[k] = String(v); },
      removeItem: (k) => { delete mem[k]; },
    };
  };
  const renderTeam = async () => { byId.get('main')._html = ''; await globalThis.__view('team'); await sleep(40); return byId.get('main')._html; };

  useStore({});
  const mgr = await renderTeam();
  const mgrMissing = ['data-action="team-view"', '管理者（我分配的）', '执行者（分配给我的）',
    '小王 · 3 件', '我分配 · ', 'data-action="team-status"', 'data-status="in_progress"',
    '任务已删除（分配记录保留下来做审计）', '（已删除 · 在回收站）', '全部 3', '受阻 1',
    '已完成 1'].filter((n) => !mgr.includes(n));  // 「两种看法」的判据不看那两个字（切视角的按钮标签里本来就有"分配给我"），
  // 而是看**这一页的内容**：管理者页里有"你分配出去的…"这句、且没有执行者那份条目。
  const mgrPure = mgr.includes('你分配出去的任务都在这里') && !mgr.includes('分给「小王」的任务');

  useStore({ tf_team_view: 'executor', tf_team_me: '小王' });
  const exe = await renderTeam();
  const exeMissing = ['分配给我', '小王 · 1 件', '分给「小王」的任务'].filter((n) => !exe.includes(n));
  const exePure = exe.includes('分给「小王」的任务') && !exe.includes('你分配出去的任务都在这里')
    && !exe.includes('任务已删除');

  useStore({ tf_team_view: 'executor' });
  const noMe = await renderTeam();
  // 没填名字 = 一行都不给看（不是"猜一个人"）：只有输入框与说明，没有任何"下一步"按钮
  const noMeOk = noMe.includes('id="teamMe"') && noMe.includes('data-action="team-me"')
    && noMe.includes('先在上面填「我是谁」') && !noMe.includes('data-action="team-status"');
  globalThis.localStorage = realLocalStorage;

  const rendered = mgrMissing.length === 0 && exeMissing.length === 0 && mgrPure && exePure && noMeOk;
  if (!rendered) teamBad++;
  teamChecks.push({ rendered, mgrMissing, exeMissing, mgrPure, exePure, noMeOk });
  console.log(`  ${rendered ? '✅' : '⚠️ '} 团队·视角切换 管理者 ${String(mgr.length).padStart(6)}B`
    + `（两个视角 ${mgrPure && exePure ? '分得开' : '混了'}·没填名字 ${noMeOk ? '不猜' : '猜了'}）`
    + (mgrMissing.length ? `  管理者缺: ${mgrMissing.join(', ')}` : '')
    + (exeMissing.length ? `  执行者缺: ${exeMissing.join(', ')}` : ''));
} catch (e) {
  teamBad++;
  teamChecks.push({ error: e.message });
  console.log(`  ❌ 团队·视角切换 渲染抛错: ${e.message}`);
}

/* 局域网访问 + 配对码（SR-NF17 / G 批 · T-G10b / 场景 ②）：两块都要真渲染 ——
   ① 设置页那一节（开着时给地址 + 本机可见的配对码 + 两个按钮）；
   ② **配对墙**：把 fetch 换成"回 401 说没配对"，看整页是不是真变成那面墙，
      再把 fetch 换回来，看墙是不是自己撤了（这一串就是手机上第一次连电脑的走法）。
   ③ 反证：非本机请求拿不到配对码时，那一节**不许**显示码、也不许摆"换一个"（那是本机才有的动作）。 */
const lanChecks = [];
try {
  byId.get('main')._html = '';
  await globalThis.__view('setting');
  await sleep(40);
  const setting = byId.get('main')._html;
  const needs = ['局域网访问（手机连电脑）', 'id="set-lan"', '对局域网开着',
    'http://192.168.1.23:8520', '246810', 'data-action="copy-lan"', 'data-action="lan-rotate"',
    '只在这台电脑上显示', '同一个 WiFi',
    // T-G10c（校园网/热点场景）：排查顺序与自检按钮都要真的渲染出来
    '怎么让手机连上（按顺序试）', '移动热点', '192.168.137.1', '客户端隔离',
    'data-action="lan-selfcheck"', 'id="lanSelfCheck"'];
  const missing = needs.filter((n) => !setting.includes(n));

  const wall = globalThis.__pairWall();
  const wallNeeds = ['id="pairWall"', '这台设备还没和电脑配对', '输入配对码', 'pair-ask',
    'pair-clear', '只在那台电脑上显示'];
  const wallMissing = wallNeeds.filter((n) => !wall.includes(n));

  // 真走一次：所有请求都回 401（没配对）→ 整页应当是那面墙；换回正常 fetch → 应当恢复
  const realFetch = globalThis.fetch;
  globalThis.fetch = async () => ({
    ok: false, status: 401,
    json: async () => ({ detail: '这台设备还没和电脑配对：请在那台电脑的「设置 → 局域网访问」里看配对码' }),
    text: async () => '',
  });
  byId.get('main')._html = '';
  await globalThis.__view('today');
  await sleep(40);
  const blocked = byId.get('main')._html;
  const wallShown = blocked.includes('id="pairWall"');
  globalThis.fetch = realFetch;
  byId.get('main')._html = '';
  await globalThis.__view('today');
  await sleep(40);
  const recoveredHtml = byId.get('main')._html;
  const recovered = !recoveredHtml.includes('id="pairWall"') && recoveredHtml.length > 300;

  // 反证：非本机请求（code 为空 / code_visible=false）→ 不显示码、不摆「换一个」
  const saved = DB['/api/settings/lan'];
  DB['/api/settings/lan'] = { ...saved, code: '', code_visible: false };
  byId.get('main')._html = '';
  await globalThis.__view('setting');
  await sleep(40);
  const phoneSide = byId.get('main')._html;
  DB['/api/settings/lan'] = saved;
  const hiddenOk = phoneSide.includes('这是故意的') && !phoneSide.includes('lan-rotate');

  const rendered = missing.length === 0 && wallMissing.length === 0 && wallShown && recovered
    && hiddenOk;
  if (!rendered) lanBad++;
  lanChecks.push({ rendered, missing, wallMissing, wallShown, recovered, hiddenOk });
  console.log(`  ${rendered ? '✅' : '⚠️ '} setting·局域网配对 main ${String(setting.length).padStart(6)}B`
    + `（墙 ${wallShown ? '出现' : '没出现'}·${recovered ? '已撤' : '没撤'}`
    + `·非本机看不到码 ${hiddenOk ? '对' : '不对'}）`
    + (missing.length ? `  缺: ${missing.join(', ')}` : '')
    + (wallMissing.length ? `  墙缺: ${wallMissing.join(', ')}` : ''));
} catch (e) {
  lanBad++;
  lanChecks.push({ error: e.message });
  console.log(`  ❌ setting·局域网配对 渲染抛错: ${e.message}`);
}

/* 字面星号（T-G11 缺陷）：**渲染结果里不许出现 `**重点**`**。
   背景：`noteHTML()` 只把**后端给来的**文字里的 `**x**` 转成 `<b>`；而静态模板里若直接写 `**x**`，
   浏览器就把星号原样显示出来（用户看到的是一堆 `**`）。实测 today/tasks/planned/habit/setting 都有。
   两层查：
   ① **按输出查**（下面这段）：把 13 个视图 + 详情/展开态都渲染一遍，扫渲染结果 —— 有就 FAIL；
   ② **按源码查**（`scanBoldInSource`）：把脚本里的**字符串字面量**（含模板串）扫一遍 ——
      静态文案只要写了 `**` 就报，**不依赖探针的桩数据**（① 会漏掉"桩里没有数据所以没渲染"的分支）。
   为什么不用"grep 整个文件"：`**` 大量出现在 JS/HTML 注释里（那些不影响界面），
   而且我第一次写的行级分类器把块注释判错了 —— 所以这里用**状态机**过一遍真正的字符串。 */
function scanBoldInSource(code) {
  const hits = [];
  let i = 0;
  let line = 1;
  let mode = 'code';           // code | line | block | single | double | template | regex
  const stack = [];            // 模板串嵌套（` 里出现 ${ 时要回到 code，遇 } 再回来）
  const literal = [];          // 当前字符串/模板里已扫到的内容
  const lineOf = [];
  const prev = [];             // 最近的非空字符（判断 `/` 是除法还是正则字面量）
  let inClass = false;         // 正则里的 [...] 字符组（其中的 / 不结束正则）
  let brace = 0;               // ${ ... } 里的花括号深度（里面有对象字面量，不能见 } 就回模板）
  const bump = (ch) => { if (ch === '\n') line += 1; };
  const push = (ch) => { literal.push(ch); lineOf.push(line); };
  const flush = (kind) => {
    const text = literal.join('');
    const re = /\*\*[^*\n]{1,60}\*\*/g;
    let m;
    while ((m = re.exec(text)) !== null) {
      hits.push({ line: lineOf[m.index] || 0, kind, text: m[0] });
    }
    literal.length = 0;
    lineOf.length = 0;
  };
  // `/` 前面是这些字符/位置时，它是**正则字面量**而不是除号（否则 `/[&<>"']/g` 里那些引号会把扫描带偏）
  const REGEX_OK = new Set(['(', ',', '=', ':', '[', '!', '&', '|', '?', '{', '}', ';', '+',
    '-', '*', '%', '~', '^', '<', '>', '\n']);
  while (i < code.length) {
    const ch = code[i];
    const two = code.slice(i, i + 2);
    if (mode === 'code') {
      if (two === '//') { mode = 'line'; i += 2; continue; }
      if (two === '/*') { mode = 'block'; i += 2; continue; }
      if (ch === "'") { mode = 'single'; i += 1; continue; }
      if (ch === '"') { mode = 'double'; i += 1; continue; }
      if (ch === '`') { mode = 'template'; i += 1; continue; }
      if (ch === '{') { stack.push('brace'); bump(ch); i += 1; continue; }
      if (ch === '}') {
        if (stack[stack.length - 1] === 'brace') { stack.pop(); bump(ch); i += 1; continue; }
        if (stack[stack.length - 1] === 'tpl') { stack.pop(); mode = 'template'; i += 1; continue; }
        bump(ch); i += 1; continue;
      }
      if (ch === '/' && (!prev.length || REGEX_OK.has(prev[prev.length - 1]))) {
        mode = 'regex'; inClass = false; i += 1; continue;
      }
      if (!/\s/.test(ch)) { prev.push(ch); if (prev.length > 8) prev.shift(); }
      bump(ch); i += 1; continue;
    }
    if (mode === 'line') { if (ch === '\n') { mode = 'code'; } bump(ch); i += 1; continue; }
    if (mode === 'block') {
      if (two === '*/') { mode = 'code'; i += 2; continue; }
      bump(ch); i += 1; continue;
    }
    if (mode === 'regex') {
      if (ch === '\\') { i += 2; continue; }
      if (ch === '[') inClass = true;
      else if (ch === ']') inClass = false;
      else if (ch === '/' && !inClass) {
        mode = 'code';
        prev.length = 0;            // 正则后面是标识符（flags）→ 下一个 / 一定不是正则
        i += 1; continue;
      }
      bump(ch); i += 1; continue;
    }
    // 字符串/模板内部
    if (ch === '\\') { push(ch); push(code[i + 1] || ''); i += 2; continue; }
    if ((mode === 'single' && ch === "'") || (mode === 'double' && ch === '"')) {
      flush(mode); mode = 'code'; i += 1; continue;
    }
    if (mode === 'template') {
      if (ch === '`') { flush(mode); mode = 'code'; i += 1; continue; }
      if (two === '${') { flush('template+expr'); stack.push('tpl'); mode = 'code'; i += 2; continue; }
    }
    push(ch); bump(ch); i += 1;
  }
  return hits;
}
const boldChecks = [];
let boldSource = [];
try {
  boldSource = scanBoldInSource(code);
} catch (e) {
  boldChecks.push({ where: 'source', error: e.message });
}
if (boldSource.length) {
  boldBad++;
  boldChecks.push({ where: 'source', frags: boldSource.map((h) => `${h.line}:${h.text}`) });
  console.log(`  ❌ 源码里的字符串字面量含字面星号 ${boldSource.length} 处：`);
  for (const h of boldSource.slice(0, 40)) console.log(`       ${h.line}: ${h.text}`);
}
try {
  const cases = [];
  for (const v of views) cases.push([v, async () => { await globalThis.__view(v); }]);
  cases.push(['detail·只读', async () => { await globalThis.__showDetail('t1'); }]);
  cases.push(['detail·编辑态', async () => {
    await globalThis.__showDetail('t1'); globalThis.__setEdit(true); await globalThis.__render('today');
  }]);
  cases.push(['today·明细展开', async () => {
    globalThis.__setDoneOpen(true); await globalThis.__view('today');
  }]);
  const dirty = [];
  for (const [label, run] of cases) {
    byId.get('main')._html = '';
    byId.get('detailRail')._html = '';
    byId.get('groupAdmin')._html = '';
    try {
      await run();
      await sleep(30);
      const html = (byId.get('main')._html || '') + (byId.get('detailRail')._html || '')
        + (byId.get('groupAdmin')._html || '');
      const frags = [...new Set(html.match(/\*\*[^*\n]{1,40}\*\*/g) || [])];
      if (frags.length) dirty.push([label, frags]);
    } catch (e) {
      dirty.push([label, [`渲染抛错: ${e.message}`]]);
    }
  }
  if (dirty.length) boldBad++;
  for (const [label, frags] of dirty) {
    boldChecks.push({ label, frags });
    console.log(`  ❌ ${label} 渲染结果里有字面星号：${frags.join(' , ')}`);
  }
  if (!dirty.length) console.log('  ✅ 13 个视图 + 详情/展开态：渲染结果里没有字面 `**`');
} catch (e) {
  boldBad++;
  console.log(`  ❌ 字面星号检查本身抛错: ${e.message}`);
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
      regrade: regradeChecks,
      attempt: attemptChecks, archive: archiveChecks, step: stepChecks, debt: debtChecks,
      behavior: behaviorChecks, vocab: vocabChecks, heatmap: heatmapChecks,
      export: exportChecks, obsidian: obsidianChecks, ai: aiChecks, sync: syncChecks,
      offline: offlineChecks, lan: lanChecks, team: teamChecks, notice: noticeChecks,
      bold: boldChecks,
      problems, unregistered: unused },
    null, 2));
}
if (unused.length) {
  console.log(`  ❌ 模板里用到但未注册的动作：${unused.join(', ')}`);
}
if (problems.length) {
  console.log(`  ⚠️  运行时告警/异常：${problems.slice(0, 5).join(' | ')}`);
}
const failed = bad > 0 || detailBad > 0 || doneBad > 0 || reviewBad > 0 || regradeBad > 0 || hardBad > 0  || guardBad > 0 || stateBad > 0 || overdueBad > 0 || attemptBad > 0 || archiveBad > 0
  || stepBad > 0 || debtBad > 0 || behaviorBad > 0 || vocabBad > 0 || heatmapBad > 0 || exportBad > 0
  || obsidianBad > 0
  || aiBad > 0
  || syncBad > 0
  || offlineBad > 0
  || lanBad > 0
  || teamBad > 0
  || noticeBad > 0
  || boldBad > 0
  || unused.length > 0 || problems.length > 0;
console.log(`\n${failed ? '❌' : '✅'} 假 DOM 渲染探针：${views.length - bad}/${views.length} 个视图正常渲染`
  + `，详情面板 ${detailChecks.length - detailBad}/${detailChecks.length} 正常`
  + `，今日完成明细展开 ${doneChecks.length - doneBad}/${doneChecks.length} 正常`
  + `，复习卡编辑态 ${reviewChecks.length - reviewBad}/${reviewChecks.length} 正常`
  + `，复习改判 ${regradeChecks.filter((c) => c.rendered).length}/${regradeChecks.length} 正常`
  + `，硬考核强呈现 ${hardChecks.length - hardBad}/${hardChecks.length} 正常`
  + `，白名单勿扰 ${guardChecks.length - guardBad}/${guardChecks.length} 正常`
  + `，状态机 ${stateChecks.length - stateBad}/${stateChecks.length} 正常`
  + `，派生逾期 ${overdueChecks.length - overdueBad}/${overdueChecks.length} 正常`
  + `，尝试失败 ${attemptChecks.length - attemptBad}/${attemptChecks.length} 正常`
  + `，档案视图 ${archiveChecks.length - archiveBad}/${archiveChecks.length} 正常`
  + `，子步骤 ${stepChecks.length - stepBad}/${stepChecks.length} 正常`
  + `，债务卡 ${debtChecks.length - debtBad}/${debtChecks.length} 正常`
  + `，口径回退 ${behaviorChecks.length - behaviorBad}/${behaviorChecks.length} 正常`
  + `，可配置词表 ${vocabChecks.length - vocabBad}/${vocabChecks.length} 正常`
  + `，热力图有值 ${heatmapChecks.length - heatmapBad}/${heatmapChecks.length} 正常`
  + `，导出 markdown ${exportChecks.length - exportBad}/${exportChecks.length} 正常`
  + `，Obsidian 跳转 ${obsidianChecks.filter((c) => c.rendered).length}/${obsidianChecks.length} 正常`
  + `，AI 接口 ${aiChecks.filter((c) => c.rendered).length}/${aiChecks.length} 正常`
  + `，跨端同步 ${syncChecks.filter((c) => c.rendered).length}/${syncChecks.length} 正常`
  + `，手机离线记 ${offlineChecks.filter((c) => c.rendered).length}/${offlineChecks.length} 正常`
  + `，局域网配对 ${lanChecks.filter((c) => c.rendered).length}/${lanChecks.length} 正常`
  + `，团队视角 ${teamChecks.filter((c) => c.rendered).length}/${teamChecks.length} 正常`
  + `，学校通知 ${noticeChecks.filter((c) => c.rendered).length}/${noticeChecks.length} 正常`
  + `，字面星号 ${boldBad === 0 ? '0' : '有'}（源码 + 渲染两遍查）`
  + `，未注册动作 ${unused.length} 个，运行时告警 ${problems.length} 条`);
process.exit(failed ? 1 : 0);
