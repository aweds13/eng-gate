/* timeflow · 手机离线记（SR-NF17 / G 批 · T-G10 = 跨端场景 ①）
 *
 * **这是什么**：手机（或任何浏览器）在**没有网络**时也能记下几件事，攒进本机队列；
 * 回到电脑前**导出一份同步包**（`timeflow-sync` v1，与 T-G8 电脑↔电脑用的是**同一个格式**），
 * 在电脑的设置页「跨端同步」里导入 —— 合并规则、冲突留痕、幂等都由电脑那边一套代码负责。
 *
 * **为什么不在这里合并**：浏览器里没有 SQLite，也没有领域层（债务/账本/状态机）。
 * 手机上做一套"半套合并"必然与电脑那套口径分叉 —— 所以手机只做**采集 + 打包**，
 * 判断留给电脑（一处口径）。
 *
 * **能离线记什么（v1 范围）**：
 *   ① 新建任务（标题 / 截止日 / 是否加入今天 / 优先级 / 备注）
 *   ② 勾完成、撤销完成（对**缓存里已有的**任务）
 *   ③ 习惯打卡
 *   ④ 备忘录一条
 *   ⑤ 每日反馈（今天打算 / 卡在哪）
 *
 * **这一版明确不做**（写在这里，免得以后以为漏了）：
 *   - 离线**专注计时**：`focus.finished` 会牵动电脑那边的派生缓存（当日反馈里的专注分钟），
 *     而"导入"是直接写行、**不过订阅器**，那条派生链需要在电脑侧重算 —— 单独一张卡，不混进来；
 *   - 离线**删除**：硬删要动墓碑，手机上判不准"这条是不是电脑那边也改过"；
 *   - 手机上**改字段**（改截止日/优先级等）：LWW 会拿手机的快照覆盖电脑的新改动，风险不对等；
 *   - 从电脑**回到**手机（手机没有库，不做反向合并）。
 *
 * **两条诚实边界**：
 *   1. 手机要**打开这个应用**，得先让服务对局域网可见（那是场景 ②，默认关，还没做）。
 *      在此之前：可以在电脑浏览器的"离线模式"（DevTools → Network → Offline）里验这条链。
 *   2. 队列**导出后不清空** —— 文件丢了不至于丢数据；重复导入是安全的（合并幂等）。
 *      要清空得自己点「清空（我已导入电脑）」+ 二次确认。
 *
 * **可测性**：本文件把"造行 / 打包"写成**纯函数**（不碰 DOM、不碰 IndexedDB、不发请求），
 * 于是 `tools/phone_check.mjs` 能在 Node 里用**同一份代码**造出真包，再交给电脑侧真导入一次
 * （见 `tests/test_offline_phone_line.py`）—— 这比"看字符串在不在"强：它验的是包**真的能被吃下去**。
 */
(function (global) {
  'use strict';

  // 包的身份：与电脑侧 `core/syncpack.py` 同一套（改一处必须改两处 —— 有护栏测试对账）
  var FORMAT = 'timeflow-sync';
  var FORMAT_VERSION = 1;

  var DB_NAME = 'timeflow-offline';
  var DB_VERSION = 1;
  var STORE_QUEUE = 'queue';
  var STORE_CACHE = 'cache';
  var DEVICE_KEY = 'tf_device';
  var EXPORT_KEY = 'tf_offline_export';

  // ---------------------------------------------------------------- 纯函数
  /* 表字段白名单：**界面拿到的对象不是数据库里的行**（`TaskOut` 多出 groups/overdue_days 等
     十八般派生字段），直接塞进包里就是给电脑塞了它没有的列。所以按白名单挑字段 ——
     这份名单与 `PRAGMA table_info` 对账由 `tests/test_offline_phone_line.py` 钉住。 */
  var FIELDS = {
    tasks: ['id', 'title', 'due_date', 'group_name', 'repeat_days', 'parent_id', 'is_myday',
      'status', 'created_at', 'updated_at', 'version', 'note', 'priority', 'flagged', 'attach',
      'remind_at', 'task_type', 'course_id', 'doing_rank', 'created_by'],
    facts: ['id', 'kind', 'subject_type', 'subject_id', 'value_num', 'value_text', 'extra',
      'occurred_at', 'recorded_at', 'source', 'device_id', 'revision', 'supersedes'],
    habit_logs: ['habit_id', 'date', 'done'],
    memos: ['id', 'text', 'ref_handle', 'task_id', 'created_at'],
    feedback_logs: ['date', 'plan_note', 'executed', 'gap_note', 'focus_minutes', 'created_at',
      'updated_at'],
  };
  // 各表的主键（与电脑侧 `syncpack.PRIMARY_KEYS` 同口径）：队列按它去重，一条只留最新
  var PRIMARY_KEYS = {
    task_groups: ['task_id', 'group_id'],
    habit_logs: ['habit_id', 'date'],
    feedback_logs: ['date'],
  };
  var DEFAULT_PK = ['id'];

  var PRIORITIES = ['高', '中', '低'];
  var STATUS_TODO = '未开始';
  var STATUS_DONE = '完成';
  var STATUS_OVERDUE = '逾期';
  var TASK_TYPE_PLAIN = '普通';
  // 手机写的事实来源（电脑那边是 desktop / ai）—— 只作记录与追溯，不参与任何计算
  var SOURCE = 'phone';

  function pick(row, cols) {
    var out = {};
    for (var i = 0; i < cols.length; i++) {
      if (Object.prototype.hasOwnProperty.call(row, cols[i])) out[cols[i]] = row[cols[i]];
    }
    return out;
  }

  function pad(n) { return String(n).padStart(2, '0'); }

  /** 本机时间 `YYYY-MM-DDTHH:MM:SS`（电脑侧 `datetime.now().isoformat(timespec="seconds")` 同形）。 */
  function localNow(d) {
    var x = d || new Date();
    return x.getFullYear() + '-' + pad(x.getMonth() + 1) + '-' + pad(x.getDate()) + 'T'
      + pad(x.getHours()) + ':' + pad(x.getMinutes()) + ':' + pad(x.getSeconds());
  }

  /** 本机日期 `YYYY-MM-DD`（**本地时区**，不用 toISOString —— 那会被时区推成昨天/明天）。 */
  function localDay(d) {
    var x = d || new Date();
    return x.getFullYear() + '-' + pad(x.getMonth() + 1) + '-' + pad(x.getDate());
  }

  /** 12 位十六进制 id —— 与电脑侧 `uuid.uuid4().hex[:12]` 同形同长（界面/接口不用改）。 */
  function newId() {
    var c = (typeof crypto !== 'undefined' && crypto && crypto.getRandomValues) ? crypto : null;
    if (c) {
      var b = new Uint8Array(6);
      c.getRandomValues(b);
      var s = '';
      for (var i = 0; i < b.length; i++) s += pad(b[i].toString(16));
      return s;
    }
    // 老环境兜底：这里只为"别撞 id"，不做密码学用途
    var out = '';
    for (var j = 0; j < 12; j++) out += Math.floor(Math.random() * 16).toString(16);
    return out;
  }

  /** 附件列表 → 电脑库存的 JSON 文本（电脑侧 `attach.dump_attach`）。 */
  function attachText(list) {
    var items = [];
    if (Array.isArray(list)) {
      for (var i = 0; i < list.length; i++) {
        var it = list[i];
        if (!it || !it.target || !String(it.target).trim()) continue;
        var t = it.title;
        items.push({
          target: String(it.target).trim(),
          title: (t && String(t).trim()) ? String(t).trim() : null,
        });
      }
    }
    return JSON.stringify(items);
  }

  /** 新建任务的行（字段与电脑侧 `create_task` 的 INSERT 对齐）。 */
  function taskRow(input) {
    var at = input.at || localNow();
    var due = input.due_date || null;
    return {
      id: input.id || newId(),
      title: String(input.title || '').trim(),
      due_date: due,
      group_name: null,
      repeat_days: null,
      parent_id: null,
      is_myday: input.is_myday ? 1 : 0,
      // 与电脑侧一致：建的时候就过期 → 初始状态「逾期」（之后的逾期是派生显示）
      status: (due && due < localDay()) ? STATUS_OVERDUE : STATUS_TODO,
      created_at: at,
      updated_at: at,
      version: 1,
      note: input.note || null,
      priority: PRIORITIES.indexOf(input.priority) >= 0 ? input.priority : '中',
      flagged: 0,
      attach: '[]',
      remind_at: null,
      task_type: TASK_TYPE_PLAIN,
      course_id: null,
      doing_rank: null,
      created_by: 'me',
    };
  }

  /** 状态跃迁事实（与电脑侧 `_publish_status_facts` 同形）。`extra` 在库里是 **JSON 文本**。 */
  function statusFact(kind, task, fromStatus, at) {
    var extra = (kind === 'task.completed')
      ? { title: task.title, due_date: task.due_date, from_status: fromStatus,
          completed_on: String(at).slice(0, 10) }
      : { title: task.title, to_status: task.status, reverted_on: String(at).slice(0, 10) };
    return {
      id: newId(),
      kind: kind,
      subject_type: 'task',
      subject_id: task.id,
      value_num: null,
      value_text: task.title,
      extra: JSON.stringify(extra),
      occurred_at: at,
      recorded_at: at,
      source: SOURCE,
      device_id: null,
      revision: 1,
      supersedes: null,
    };
  }

  /** 界面上的任务（`TaskOut`）→ 数据库里的行：按白名单削字段 + 补齐库里的存法。 */
  function cachedTaskRow(task) {
    var t = pick(task, FIELDS.tasks);
    // 库里存的是 JSON **文本**（`attach.dump_attach`），接口给的是**列表** —— 这一处不换就会
    // 往库里写一个列表，电脑那边 `load_attach` 读到的虽仍是同一批附件（它容错），但字段类型就散了。
    t.attach = typeof t.attach === 'string' ? t.attach : attachText(t.attach);
    t.is_myday = t.is_myday ? 1 : 0;      // 布尔 → 0/1（库里就是这么存的）
    t.flagged = t.flagged ? 1 : 0;
    t.version = Number(task.version || 1);
    return t;
  }

  /** 从界面拿到的任务（`TaskOut`）削成数据库里的行 —— 完成态。 */
  function completeTask(task, at) {
    var t = cachedTaskRow(task);
    var from = t.status;
    t.status = STATUS_DONE;
    t.updated_at = at;
    // version 必须比电脑那边**更大**才会赢（LWW 优先比 version）——
    // 缓存里存过电脑给的 version，就在它上面 +1；没存过（老缓存）当 1 再 +1。
    t.version = Number(task.version || 1) + 1;
    return { row: t, fact: statusFact('task.completed', t, from, at) };
  }

  /** 撤销完成：行回到「未开始」+ 一条 `task.uncompleted`（账本撤销照扣靠的就是它）。 */
  function uncompleteTask(task, at) {
    var t = cachedTaskRow(task);
    var from = t.status;
    t.status = STATUS_TODO;
    t.updated_at = at;
    t.version = Number(task.version || 1) + 1;
    return { row: t, fact: statusFact('task.uncompleted', t, from, at) };
  }

  /** 习惯打卡行。`done=false` 就是电脑上「取消打卡」（电脑那边也是把 done 改 0，不是删行）。 */
  function habitRow(habitId, date, done) {
    return { habit_id: String(habitId), date: date || localDay(), done: done === false ? 0 : 1 };
  }

  function memoRow(input) {
    return {
      id: input.id || newId(),
      text: String(input.text || '').trim(),
      ref_handle: null,
      task_id: null,
      created_at: input.at || localNow(),
    };
  }

  /** 每日反馈整行（日期是主键；带上电脑给的其余字段，避免"只改一句"把别的抹掉）。 */
  function feedbackRow(input) {
    var at = input.at || localNow();
    var prev = input.prev || {};
    return {
      date: input.date || localDay(),
      plan_note: input.plan_note !== undefined ? input.plan_note : (prev.plan_note || null),
      executed: prev.executed || null,
      gap_note: input.gap_note !== undefined ? input.gap_note : (prev.gap_note || null),
      focus_minutes: Number(prev.focus_minutes || 0),
      created_at: prev.created_at || at,
      updated_at: at,
    };
  }

  function pkColumns(table) { return PRIMARY_KEYS[table] || DEFAULT_PK; }

  /** 一行在包/队列里的统一标识（复合主键用 `|` 拼，与电脑侧墓碑同口径）。 */
  function rowKey(table, row) {
    var cols = pkColumns(table);
    if (cols.length === 1) return String(row[cols[0]]);
    var parts = [];
    for (var i = 0; i < cols.length; i++) parts.push(String(row[cols[i]]));
    return parts.join('|');
  }

  /** 队列条目的存储键：表 + 标识。同一行反复改 → **只留最新那条**（队列自己去重）。 */
  function queueKey(table, row) { return table + '|' + rowKey(table, row); }

  /** 把队列条目装成同步包（与电脑侧 `syncpack.build_pack` 同格式）。 */
  function buildPack(device, entries, at) {
    var tables = {};
    var counts = {};
    for (var i = 0; i < entries.length; i++) {
      var e = entries[i];
      if (!tables[e.table]) { tables[e.table] = []; counts[e.table] = 0; }
      tables[e.table].push(e.row);
      counts[e.table] += 1;
    }
    return {
      format: FORMAT,
      format_version: FORMAT_VERSION,
      // 手机没有库、没有结构 —— 如实写 0（电脑侧只把它写进报告，不据此做任何判断）
      schema_version: 0,
      device_id: device,
      created_at: at,
      tables: tables,
      tombstones: [],
      counts: counts,
      note: '手机离线记导出的同步包（场景 ①）：只装手机上记下的东西，**不含**手机的任何设置。'
        + '导入电脑后合并按 version → updated_at 判新旧，覆盖与保留都记进冲突日志；'
        + '**导入不会删电脑上的任何东西**。',
    };
  }

  function packText(pack) { return JSON.stringify(pack, null, 2); }

  /** 文件名与电脑侧 `syncpack.default_filename` 同规矩：`sync-<设备>-<时间戳>.json`。 */
  function packFilename(device, at) {
    var stamp = String(at).replace(/-/g, '').replace(/:/g, '').replace('T', '-');
    return 'sync-' + device + '-' + stamp + '.json';
  }

  /** 队列条目 → 一行人话（队列列表用；不含用户正文以外的任何推断）。 */
  function describe(entry) {
    var row = entry.row || {};
    if (entry.table === 'tasks') {
      // 队列里同一条只留最新，所以"这一条是什么"只能从行的长相看：完成态=完成，
      // version 还是 1 = 新建（完成/撤销都会把 version +1），否则就是撤销完成。
      var what = row.status === STATUS_DONE ? '完成'
        : (Number(row.version || 1) <= 1 ? '新建' : '改回未完成');
      return '任务「' + (row.title || row.id) + '」· ' + what;
    }
    if (entry.table === 'facts') {
      return row.kind === 'task.completed' ? '完成记录' : '撤销记录';
    }
    if (entry.table === 'habit_logs') return '习惯打卡 · ' + row.date;
    if (entry.table === 'memos') return '备忘 · ' + String(row.text || '').slice(0, 18);
    if (entry.table === 'feedback_logs') return '每日反馈 · ' + row.date;
    return entry.table;
  }

  /** 纯函数出口（Node 侧单测只认这一块：不碰 DOM / IndexedDB / 网络）。 */
  var PURE = {
    FIELDS: FIELDS, PRIMARY_KEYS: PRIMARY_KEYS, DEFAULT_PK: DEFAULT_PK, FORMAT: FORMAT,
    FORMAT_VERSION: FORMAT_VERSION, SOURCE: SOURCE,
    newId: newId, localNow: localNow, localDay: localDay, attachText: attachText,
    pick: pick, taskRow: taskRow, cachedTaskRow: cachedTaskRow,
    completeTask: completeTask, uncompleteTask: uncompleteTask,
    habitRow: habitRow, memoRow: memoRow, feedbackRow: feedbackRow,
    pkColumns: pkColumns, rowKey: rowKey, queueKey: queueKey, buildPack: buildPack,
    packText: packText, packFilename: packFilename, describe: describe, statusFact: statusFact,
  };

  // ---------------------------------------------------------------- 本机存储（设备号 / 队列 / 缓存）
  var memDevice = null;

  function lsGet(key) {
    try { return global.localStorage ? global.localStorage.getItem(key) : null; } catch (e) { return null; }
  }
  function lsSet(key, value) {
    try { if (global.localStorage) global.localStorage.setItem(key, value); } catch (e) { /* 隐私模式：只留在内存 */ }
  }

  /** 本机（这台手机）的设备号：包里带着它，电脑据此认"这份包从哪来"、也据此**拒绝自己导给自己**。 */
  function deviceId() {
    var existing = lsGet(DEVICE_KEY);
    if (existing) return existing;
    if (memDevice) return memDevice;
    memDevice = newDeviceId();
    lsSet(DEVICE_KEY, memDevice);
    return memDevice;
  }

  function newDeviceId() {
    // 手机的设备号前缀 `ph-`：与电脑的 12 位十六进制一眼分得开（排障时省事），
    // 且**不会**与电脑设备号相同 —— 否则电脑那边会把手机包当成"自己导给自己"拒掉。
    return 'ph-' + newId();
  }

  function idbAvailable() {
    try { return typeof indexedDB !== 'undefined' && indexedDB !== null; } catch (e) { return false; }
  }

  function openDb() {
    if (!idbAvailable()) {
      return Promise.reject(new Error('这个浏览器不支持离线存储（IndexedDB）—— 离线记用不了'));
    }
    return new Promise(function (resolve, reject) {
      var req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = function () {
        var db = req.result;
        if (!db.objectStoreNames.contains(STORE_QUEUE)) db.createObjectStore(STORE_QUEUE, { keyPath: 'k' });
        if (!db.objectStoreNames.contains(STORE_CACHE)) db.createObjectStore(STORE_CACHE, { keyPath: 'k' });
      };
      req.onsuccess = function () { resolve(req.result); };
      req.onerror = function () { reject(new Error('打不开本机离线存储：' + (req.error && req.error.message))); };
    });
  }

  function tx(store, mode, fn) {
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        var t = db.transaction(store, mode);
        var req = fn(t.objectStore(store));
        t.oncomplete = function () { resolve(req ? req.result : null); };
        t.onerror = function () { reject(new Error('离线存储写入失败：' + (t.error && t.error.message))); };
        t.onabort = function () { reject(new Error('离线存储操作被中断')); };
      });
    });
  }

  function enqueue(table, row, label) {
    var entry = {
      k: queueKey(table, row), table: table, row: row,
      at: localNow(), label: label || describe({ table: table, row: row }),
    };
    return tx(STORE_QUEUE, 'readwrite', function (s) { return s.put(entry); }).then(function () {
      return entry;
    });
  }

  function pending() {
    return tx(STORE_QUEUE, 'readonly', function (s) { return s.getAll(); }).then(function (rows) {
      var list = rows || [];
      list.sort(function (a, b) { return String(a.at) < String(b.at) ? -1 : 1; });
      return list;
    });
  }

  function pendingCount() {
    return tx(STORE_QUEUE, 'readonly', function (s) { return s.count(); }).then(function (n) {
      return Number(n || 0);
    });
  }

  function clearQueue() {
    return tx(STORE_QUEUE, 'readwrite', function (s) { return s.clear(); });
  }

  function putCache(kind, rows) {
    return tx(STORE_CACHE, 'readwrite', function (s) {
      return s.put({ k: kind, rows: rows, at: localNow() });
    });
  }

  function getCache(kind) {
    return tx(STORE_CACHE, 'readonly', function (s) { return s.get(kind); }).then(function (got) {
      return got || null;
    });
  }

  // ---------------------------------------------------------------- 导出（下载 / 复制）
  function lastExport() {
    var raw = lsGet(EXPORT_KEY);
    if (!raw) return null;
    try { return JSON.parse(raw); } catch (e) { return null; }
  }

  function rememberExport(info) { lsSet(EXPORT_KEY, JSON.stringify(info)); }

  function download(filename, text) {
    try {
      if (typeof document === 'undefined' || typeof URL === 'undefined'
        || typeof URL.createObjectURL !== 'function') return false;
      var blob = new Blob([text], { type: 'application/json' });
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url; a.download = filename;
      document.body.appendChild(a); a.click();
      document.body.removeChild(a);
      setTimeout(function () { URL.revokeObjectURL(url); }, 4000);
      return true;
    } catch (e) {
      return false;   // 下载不了不是错误：界面会给「复制包文本」兜底
    }
  }

  /** 导出：把队列里的一切装成一个包。**导出不清空队列**（文件丢了不至于丢数据）。 */
  function exportPack() {
    var device = deviceId();
    var at = localNow();
    return pending().then(function (entries) {
      var pack = buildPack(device, entries, at);
      var text = packText(pack);
      var name = packFilename(device, at);
      var saved = download(name, text);
      var info = { at: at, filename: name, rows: entries.length, downloaded: saved,
        device_id: device };
      rememberExport(info);
      return { pack: pack, text: text, filename: name, rows: entries.length, downloaded: saved,
        info: info };
    });
  }

  /** 打包成文本但不下载（复制兜底 / 自检用）。 */
  function packOnce() {
    var device = deviceId();
    var at = localNow();
    return pending().then(function (entries) {
      return { text: packText(buildPack(device, entries, at)), rows: entries.length,
        device_id: device, at: at };
    });
  }

  global.TFOffline = {
    // 纯函数（Node 自检直接调这一块）
    PURE: PURE,
    // 常量（界面/文档引用）
    FORMAT: FORMAT, FORMAT_VERSION: FORMAT_VERSION, SOURCE: SOURCE,
    FIELDS: FIELDS,
    // 设备与时间
    deviceId: deviceId, newId: newId, localNow: localNow, localDay: localDay,
    // 存储
    available: idbAvailable, enqueue: enqueue, pending: pending, pendingCount: pendingCount,
    clearQueue: clearQueue, putCache: putCache, getCache: getCache,
    // 导出
    exportPack: exportPack, packOnce: packOnce, lastExport: lastExport, describe: describe,
    // 给界面用的：把界面上的一份数据变成"要入队的行"
    taskRow: taskRow, completeTask: completeTask, uncompleteTask: uncompleteTask,
    habitRow: habitRow, memoRow: memoRow, feedbackRow: feedbackRow,
  };
})(typeof window !== 'undefined' ? window : globalThis);
