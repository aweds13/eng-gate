# 卡 E120 · tools/gate_pool.py 把「读不到」洗成「读到空」：队列 / 日志 / 播种源 / 槽位 / 锁 六类静默

> 台账号 T-AG629｜分区 E｜树 .wt/E120｜层 判据层｜基准 89cd4deb（立卡时主树 HEAD）｜depends 无
> 依据：用户 m00001「tools/gate_pool.py 的四处 PermissionError 静默……你要自己重新取证，不许照抄我的转述」
> 行号已按 2026-11-16/17 现场（主树 89cd4deb，分支 line/impl-v1，Python 3.14.6）逐条复核；tools/gate_pool.py 共 999 行。
> 全部实验在 tempfile.mkdtemp() 里做，脚本 gates/diag/_e120_*.py（未跟踪；gates/diag/* 被 .gitignore:76 忽略），未碰主树任何受保护文件。

## 要解决的问题

上一轮体检说「gate_pool.py:200-207 等四处 PermissionError 被吞掉」，没点名是哪四处、也没说后果。现场复核后实际是**六类、八处**，最重的一处不在 grep 的五种模式里（:176-180 接的是 `(OSError, json.JSONDecodeError)`）。判据只有一条：**读不到被当成读到空 ⇒ 撒谎；打印了警告且让调用方知道判不了 ⇒ 合法**。逐处下结论，合法的另列在问题 9。

### 问题 1（最重）：PoolQueue.load() 把「读不到 / 坏了 / 路径是目录」全洗成空状态，随即被 submit 写回盘覆盖历史

`tools/gate_pool.py:176-180` 的 try 读 `queue.read_text()` + `json.loads`，except 接 `(OSError, json.JSONDecodeError)` 后 `return _empty_state()`；`:137-138` 的 `_empty_state()` 就是 `{"head": None, "waiting": [], "done": [], "slots": {}}` —— 与「队列真的是空的」**逐字相同**，调用方无从分辨。

四种形态（gates/diag/_e120_probe.py 的 P1）返回**同一个**空状态：

```text
  a) 文件不存在 -> {'head': None, 'waiting': [], 'done': [], 'slots': {}}
  b) 文件在但 JSON 断了 -> {'head': None, 'waiting': [], 'done': [], 'slots': {}}
  c) 文件在但被独占打开（真 PermissionError） -> {'head': None, 'waiting': [], 'done': [], 'slots': {}}
  c') 同文件 read_text 原始异常 -> RAISED PermissionError: [Errno 13] Permission denied: '...\\q3.json'
  d) 路径是个目录 -> {'head': None, 'waiting': [], 'done': [], 'slots': {}}
  d') 目录 read_text 原始异常 -> RAISED PermissionError: [Errno 13] Permission denied
```

后果不是「少印一行」，是**覆盖**（P2）：

```text
  第一次 submit commit=aaa -> slot=0 queued=False
  此刻 free_slots(1) = []
  截断后 load() = {'head': None, 'waiting': [], 'done': [], 'slots': {}}
  截断后 free_slots(1) = [0]  ← 槽 0 其实还在跑
  第二次 submit commit=bbb -> slot=0 queued=False  port_base=9200
  覆盖后文件只剩 bbb（'head': {'commit': 'bbb', 'slot': 0, 'port_base': 9200, ...}）
  commit=aaa 还在吗 -> find('aaa') = None
```

⇒ 两趟门禁同时占槽 0、同一端口段 9200。A330 定的 `.bak` 纪律只做了写那一半：submit 两次后 `.bak` 确实在（top keys `['done','head','slots','waiting']`），`lastgood.read_with_fallback(p, validate=gp._validate_queue_text)` 能从坏文件里读回 198 B、`restored=True`（P11），**退路现成却没人调**。

CLI 面同样撒谎（P18，真子进程 `python tools/gate_pool.py status --root <临时树>`）：

```text
P18 正常队列: rc=0
  {"path": "...\\gate-pool-queue.json", "head": {"state": "running", "slot": 0, "commit": "aaa", "port_base": 9200}, "waiting": [], "done": []}
P18 坏文件: rc=0
  {"path": "...", "head": null, "waiting": [], "done": []}
P18 文件被独占（真 PermissionError）: rc=0
  {"path": "...", "head": null, "waiting": [], "done": []}
P18 路径是个目录: rc=0
  {"path": "...", "head": null, "waiting": [], "done": []}
```

四形 rc 全 0、stderr 全空、没有一句警告 ⇒ 运维看得出「队列空」，看不出「队列读不到」。

### 问题 2：_read_back 的 logs 循环 `continue` ⇒ 读不到的日志不写，上一趟的旧日志留在卡树里冒充这一趟

`tools/gate_pool.py:657-664` 逐份读 `<树>/gates/logs/*.log`，`:663-664` 是 `except OSError: continue` —— 不打印、不记、不告诉调用方少了几份。

```text
  P4 pytest.log 被目录冒充 -> _read_back 返回 payload={'at': ...} logs={}（pytest.log 静默消失）
  P4 parse_pytest_passed('') = 0
  P4 validate_cloud_return 问题清单 = ["②′ 阻断门没写 exit_code（未声明 ≠ 跑过）：['pytest(没写 exit_code)']",
                                     "④ pytest 用例数不够：0 passed < 全量 3303 的 95%（至少要 3137）—— 像「跑了个子集当全量」"]
```

判据④仍会判红，**这一层是合法兜底**；撒谎在下一层：`:848-861` 的 `_write_back` 只在 `if logs:`（:855）时才建目录写日志，所以读不到的那份**不会被写、也不会被删**（P16）：

```text
  P16/P17 logs={} 时 gates/logs/pytest.log 还在吗 = True 内容 = 3000 passed（上一趟的）
```

⇒ 写进卡树的 `gates/logs` 里躺着一份**上一趟**的 pytest.log，而下游 `tools/pool/landing.py:2705`、`tools/failure_group.py:11/14` 正是拿 `gates/logs/pytest.log` 当入口，会把别人的读数当这一趟的。全程无打印。（`:642-646` 的 docstring 已经写明「读不到就抛，绝不拿上一趟的残留冒充这一趟」—— 那条纪律只落到了 last.json 上，没落到 logs 上。）

### 问题 3：check-product-fresh 的 --seed 读不到 ⇒ 空串 ⇒ 最硬的证据（③）整条失效 ⇒ 退 0 判 fresh

`tools/gate_pool.py:981-986`：`--seed` 给的路径读不出来时 `except OSError: seed_text = ""`；`:557-558` 的 `product_is_from_this_run` 第③条正是「产物与播种源**逐字相同** ⇒ 云机没写新读数」。seed 变空串后 `if seed_text and ...` 整条短路 ⇒ ③ 静默通过。

同一份数据、只把播种源换成「读不到」（走真 CLI 子进程，gates/diag/_e120_p3.py）：

```text
  A 播种源可读、与产物逐字相同 -> rc=3  err='[stale] ③ 产物与播种源逐字相同 ⇒ 云机没写新读数（这趟没跑出来）'
  B 播种源读不到（目录冒充，PermissionError 被 :985-986 吞成空串） -> rc=0  out='[fresh] at=2026-11-16T23:00:00 ≥ 2026-11-16T22:00:00'
```

⇒ 同一趟活，**证据越不可得，结论越绿**。`scripts/cloud/run_gate.sh:533-543` 用 `--seed "$seed_dir/last.json"` 调它，非 0 才 `rm -f .wt/$card/gates/last.json` 并 exit 9 —— 现在这条失败永远等不到。

### 问题 4：main('slots') 把「读不到可用内存」印成 avail_gb=0.0 —— 编出来的数

`tools/gate_pool.py:955-963`：`avail = available_memory_gb() or 0.0`（:959）+ `except Exception: avail = 0.0`（:960-961）。而上游 `scripts/run_gates.py:178-179` 的签名与 docstring 明确是 `available_memory_gb() -> float | None`，「读不到 → None（调用方跳过这道闸，不静默当通过、也不拒跑）」。

```text
  P7  available_memory_gb 打炸弹 -> 'cpu=32 avail_gb=0.0 ⇒ 1 槽；端口段 [(9200, 9239)]'  rc=0
  P7b 对照（能读 -> 15.5）       -> 'cpu=32 avail_gb=15.5 ⇒ 3 槽；端口段 [(9200,9239),(9240,9279),(9280,9319)]'  rc=0
```

0.0 是一个**看起来正常的读数**（真·内存耗尽时也是这个数），人和机器都分不出「只剩 0 块」与「量不出来」；下游照它算槽数 ⇒ 整池退化成 1 槽。另：`slot_count(32, None)` 直接 `RAISED TypeError: float() argument must be a string or a real number, not 'NoneType'`（P20），所以「把 None 原样传下去」也不能算修法，得显式拒绝。

### 问题 5：锁四处失手，最重的一条是 acquire_slot_lock 的 timeout 对「删不掉的陈旧锁」完全不生效

`tools/gate_pool.py:368-393` 的 `acquire_slot_lock(timeout)`：`:381` 只接 `FileExistsError`，`:382` 判陈旧（`_lock_age`），`:383-385` 用 `contextlib.suppress(OSError)` 包 `path.unlink()` 后 `continue`。锁文件陈旧但删不掉时，suppress 吞掉 WinError 32，`continue` 回到 while 顶再撞 FileExistsError ⇒ **无出口死循环，timeout 参数形同不存在**。

```text
  P15 父体：子体 8 s 没退出 ⇒ timeout=0.5 不生效，已强杀（总耗时 8.04s）
  P15 子体输出原文：
    P15 锁路径 ...\\gate-pool-slot2.lock age = 99999.0 >= DEFAULT_STALE_AFTER 10800.0
    P15 独占句柄 ok = 0x148
```

生产调用点 `:905` 用的正是 `acquire_slot_lock(..., timeout=0.0)` —— 一旦撞上这种锁，`run_cloud_gate` 直接卡死而不是报错。

同组其余三处：

```text
  P6 _lock_age（:360-365）: a) 不存在 -> 0.0；b) 路径超长 stat 抛 OSError -> 0.0（被 :363-364 吞）；
                            c) 目录冒充 -> 0.0006（目录 stat 有真 mtime）；e) 锁被独占 -> False（判成「被人占着」）
  P5 release_slot_lock（:396-403）: a) 锁本来不在 -> False；b) 在且可删 -> True；c) 锁在但删不掉（WinError 5）-> False
     ⇒ a) 与 c) 同一返回值，二义，且不打印
  P10c locked() 的 finally（:208-215）: 临界区内 os.chmod(lock, stat.S_IREAD) 后「无异常；锁文件还在 = True」，
     原始异常 PermissionError: [WinError 5] 拒绝访问 被 :212-215 两处 suppress(OSError) 吞掉 ⇒ 之后 submit 等满 LOCK_WAIT_S=30 s 再无锁写
```

### 问题 6：busy_slots 读不懂槽号就整条跳过 ⇒ 那个槽被当空闲

`tools/gate_pool.py:218-229`：`:227-228` 用 `contextlib.suppress(TypeError, ValueError)` 包 `used.add(int(row.get('slot')))`，转不动就跳过这一行。

```text
  P9 busy_slots: slot=0 -> {0}；'0' -> {0}；1.0 -> {1}；True -> {1}；
                'abc' / 'None' / '' -> set() ⇒ free_slots(2) = [0, 1]，那个槽被当成空闲
```

队列行是被别的进程写进来的，槽号写坏完全可能；这一处与问题 1 同族 —— 读不懂被当成「没有」。

### 问题 7：异常态下 PermissionError 直接漏出去（与问题 1/5 同源，但漏的是异常而非空值）

```text
  P12 队列锁路径是目录: q.locked() -> RAISED PermissionError: [Errno 13] Permission denied: '...\\gate-pool-queue.json.lock'
      （异常出在 :202 os.open，不在 :200-207 只接的那个 FileExistsError 支）
  P13 release_slot_lock(目录, 0) -> False；acquire_slot_lock(目录, timeout=0.3) -> RAISED PermissionError [Errno 13]，耗时 0.00s
      （:381 只接 FileExistsError ⇒ 立刻漏，timeout 也没兜）
```

调用方 `tools/pool/landing.py:1525` 直接 `PoolQueue(wt/'gates'/'diag'/'gate-pool-queue.json')`，没有异常兜。

### 问题 8（顺带，不属本题）：main(argv) 的形参被丢掉，库内调用只能打帮助

`tools/gate_pool.py:940-941`：

```text
def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is not None else argv)
```

三元两支写反：形参**给了**反而取 `sys.argv[1:]`（丢掉调用方那一份），形参**没给**则 `list(None)` 直接炸。

```text
  P19 进程 sys.argv = ['gates/diag/_e120_p19.py']
  P19 gp.main() -> RAISED TypeError: 'NoneType' object is not iterable
  P19 gp.main(['slots'])  -> rc=0；首行 = 用法：python -X utf8 tools/gate_pool.py status [--root <树>]
  P19 gp.main(['status']) -> rc=0；首行 = 用法：python -X utf8 tools/gate_pool.py status [--root <树>]
```

⇒ 任何想在进程内调 `main([...])` 的钉子/工具都会静默拿到帮助文本 + rc=0（看起来像成功）。本卡的实验因此全部走真 CLI 子进程。

### 问题 9（合法，不改）：这几处「判不了 ⇒ 抛 / 判红」是对的

```text
  :780-786 SshTransport.reachable 的 TCP 探  except OSError: return False —— 探不通本身就是结论
  :782     run_gate 起进程失败 -> raise CloudUnreachable —— fail closed
  :890     reachable 抛 -> raise CloudUnreachable —— fail closed
  :648-653 last.json 读不到 -> RAISED CloudUnreachable: 云门禁退 0 但卡树里没有可读的 gates/last.json（FileNotFoundError: ...）
  :600-606 read_pytest_baseline 读不到 -> 0，调用方 tools/pool/landing.py:1479-1491 判红并说清怎么补
```

本卡**不动**这五处；改法照它们的样子（读不到 ⇒ 抛 / 退非 0 ⇒ 调用方必须处理），不要反过来把它们也改成返回空。

## 先例（本仓现成的「读不到要说读不到」写法，改法照抄这四条）

1. `tools/dsh_skills_guard.py:117-120` —— 三态退出码里**判不了单列一码**：

```text
    try:
        text = profile.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:  # 判不了要明说，不许当成绿
        return 2, [f"[FAIL] 判不了：profile 读不出来（{exc}）→ {profile}"]
```

2. `scripts/run_gates.py:232-251` + `tests/test_mem_guard.py:104-123` —— **同一个函数**（`available_memory_gb`）在本仓已经有一份合法用法：读不到（None 或抛）就 `print(f"=== 内存闸：读不到可用内存（阈值 {threshold:.1f} GB）→ 跳过这道闸（读不到不当通过、也不拒跑）===")` 并「跳过」，钉子 `test_unreadable_memory_skips_without_refusing` 断言打印里含「读不到」。`main('slots')` 的 `or 0.0` 是**唯一**把 None 编成数字的地方 —— 同一份数据两种口径，本卡只收拾后者。

3. `tools/pipeline_view.py:235-238`（`_fingerprint`）与 `:365-367`（`_lease_dead -> bool | None`）—— 判不了就返回 `None`/`None` 这一**第三种值**，绝不与 `False`/空串混用；docstring 逐字：「任何一个文件读不到 ⇒ None（不查缓存，仍走『缺什么说什么』/ last-good）」「判不了就说 None」。

4. `tools/pool/lastgood.py:321-347`（`read_with_fallback`）+ 真实使用者 `tools/pool/registry.py:164`、`tools/pool/quota_history.py:220` —— 两边都坏就抛，**不吞、不返回空串**；恢复成功**必须**调 `log=`。这是问题 1 若走 `.bak` 路线的现成件。

另有 `tools/contract_audit.py:602-609` 同一形状：「表读不出来 ⇒ return 2 并点名」，与「漂了 ⇒ 退 1」分开（`:53` 的三态 docstring）。

## 兼容面（grep 出来的，改签名会碰到谁）

- `PoolQueue.load()` 的调用点：`tools/gate_pool.py:248-250 submit`（`with self.locked(): state = self.load()`）、`:275-... promote`、`:331-... find`、`:948-954 main('status')`；外部 `tools/pool/landing.py:1525`。
- `_read_back` / `_write_back`：`tools/gate_pool.py:935`（run_cloud_gate 收尾）；下游读者 `tools/pool/landing.py:2705`、`tools/failure_group.py:11/14`。
- `check-product-fresh` 的退码被 `scripts/cloud/run_gate.sh:533-543` 吃（非 0 ⇒ `rm -f .wt/$card/gates/last.json` + exit 9）。
- `available_memory_gb()` 的 None 语义在 `scripts/run_gates.py:178-179`；`main('slots')`（:955-963）是唯一把 None 变成数字的地方。
- 锁三件套 `acquire_slot_lock` / `release_slot_lock` / `PoolQueue.locked` 的调用点只在 `tools/gate_pool.py:896/905/910-913`（`release_slot_lock` 在 finally）与钉子 `tests/test_gate_pool.py:222/:232`。
- `lastgood.write_atomic`（:186 `save()`）也要看一眼：写侧的 `.bak` 已经在跑，读侧没接上。

## 判据（6 条）

### 判据 1（判不了要单列一码）
`PoolQueue.load()` 必须把「文件不存在」与「读不到 / 坏 JSON」分成两种结果：前者返回空状态，后者**抛**（`GatePoolUnreadable`，或返回带 `unevaluable` 标记的状态），消息里带原始异常与路径。
**钉子**：`tests/test_gate_pool.py::test_queue_load_distinguishes_missing_from_unreadable` —— 三形（不存在 / 独占 / 目录）分别断言「空状态」与「抛 + 消息含 errno 13」。
★不许用 `lastgood.read_with_fallback` 静默恢复来「修」这一条；要用它就必须带 `log=`，且恢复失败照抛（先例 4）。

### 判据 2（读不到不许写）
队列读不到时 `submit()` 必须**拒写**并把异常/状态交给调用方，不许先 `_empty_state()` 再写回盘。
**钉子**：`tests/test_gate_pool.py::test_submit_refuses_when_queue_unreadable` —— 先真 submit 一次（占槽 0），把文件弄成读不到，第二次 submit 必须抛，且盘上原文件**字节不变**（用 `read_bytes()` 前后比对）。

### 判据 3（证据不可得不许判绿）
`check-product-fresh --seed` 读不到时不许把 seed 当空串：退码必须 ≠ 0（取 3，与「没跑出来」同码），stderr 点名路径与异常；`product_is_from_this_run` 的③不得在 seed 缺失时通过。
**钉子**：`tests/test_cloud_product_freshness.py::test_cli_seed_unreadable_is_not_fresh` —— 复用该文件现成的三态 CLI 形状（:117-146），播种源用目录冒充，断言 rc==3 且 stdout 不含 `[fresh]`。

### 判据 4（量不出来不许印成数字）
`main('slots')` 在 `available_memory_gb()` 返回 None 或抛时必须打印「判不了」（如 `avail_gb=unknown`）并退 2，不许印 `0.0`；`slot_count(cpu, None)` 必须是显式拒绝（现在 `RAISED TypeError: float() argument must be ...`）而不是落到 1 槽。
**钉子**：`tests/test_gate_pool.py::test_slots_unreadable_memory_is_not_zero` —— monkeypatch `available_memory_gb` 抛异常，断言 rc==2 且 stdout 不含 `avail_gb=0.0`；另加 `test_slot_count_none_memory_rejected`。

### 判据 5（锁：timeout 必须真的到期，还锁失败必须响）
`acquire_slot_lock(timeout=T)` 对「陈旧但删不掉的锁」必须在 T 秒量级内返回失败（抛或 False + 消息），不许死循环；`release_slot_lock` 必须三态（`'no-lock'` / `True` / 失败抛或 `False` + 打印）；`PoolQueue.locked()` 的 finally 还锁失败必须打印，不许 suppress 掉就跑。
**钉子**：`test_acquire_slot_lock_times_out_on_undeletable_stale_lock`（用 `ctypes` `CreateFileW(path, 0xC0000000, 0, None, 3, 0x80, None)` 独占句柄造 WinError 32，断言 `timeout=0.5` 在 1.5 s 内返回）、`test_release_slot_lock_distinguishes_no_lock_from_failure`、`test_locked_reports_unlock_failure`。
★不许把 `acquire_slot_lock(..., timeout=0.0)` 的调用点改成无限等来绕过这条。

### 判据 6（日志读不到不许留下上一趟的）
`_read_back` 读不到某份 log 时必须（a）打印点名，且（b）`_write_back` 不得让卡树里那份旧日志冒充这一趟 —— 要么删掉并在产物里记一笔，要么写一份带「本趟未取到」标记的占位。
**钉子**：`tests/test_gate_pool.py::test_write_back_does_not_leave_stale_log` —— 先放一份旧 `gates/logs/pytest.log`，再 `_write_back(wt, payload, {})`，断言要么文件不在、要么内容含本趟标记且不含旧内容。

## 交付

1. `tools/gate_pool.py`：新增 `GatePoolUnreadable`（或等价），改 :176-180 / :218-229 / :360-403 / :657-664 / :848-861 / :955-963 / :981-986；:941 的三元一并修（形参优先）。
2. `tests/test_gate_pool.py` 新增判据 1/2/4/5/6 六条钉子；`tests/test_cloud_product_freshness.py` 新增判据 3 一条钉子。
3. `scripts/cloud/run_gate.sh` 只在需要时改（若 `--seed` 读不到改退 3，确认 :533-543 的 exit 9 分支仍成立），改则在卡片 evidence 里贴一次脚本级读法。
4. `docs/changelog.d/T-AG629.md` 与 `docs/traceability.d/T-AG629.toml` 片段（由落地链生成，本卡不手写）。
5. 一张「读不到 ≠ 读到空」的对照表进卡规格 evidence：八处逐条给改前 / 改后的返回值与打印原文。
6. 若判据 1 选择 `lastgood` 路线，`tools/pool/lastgood.py:321-347` 的 `log=` 必须被真的传进去（先例使用者：`tools/pool/registry.py:164`、`tools/pool/quota_history.py:220`）。

## 验收（跑完逐条报末行原文）

```bash
python -X utf8 -m pytest tests/test_gate_pool.py tests/test_cloud_product_freshness.py -o addopts= -q --no-cov
```

```bash
python -X utf8 -m ruff check tools/gate_pool.py tests/test_gate_pool.py tests/test_cloud_product_freshness.py
```

```bash
python -X utf8 scripts/check_derived_docs.py --check
```

## 不许做

1. 不许把「读不到」统一改成「返回空」的另一种写法（返回 `{}` / `''` / `0` / `False` 都算没改）。
2. 不许删掉问题 9 里的五处合法 fail-closed（它们正是改法的样板）。
3. 不许用 `contextlib.suppress(Exception)` 换掉原来的 `suppress(OSError)` 来「消除漏异常」。
4. 不许改 `available_memory_gb()` 的 None 语义（`scripts/run_gates.py:178-179`）—— 该改的是 `main('slots')` 那一侧。
5. 不许为了让钉子过而放宽 `validate_cloud_return` 的 95% 阈值（`tools/gate_pool.py:80 PASSED_MIN_RATIO = 0.95`）或 `total<=0` 判红（:492-493）。
6. 不许动 `.wt/` 下任何工作树；不许把这些灰区产物之外的实验脚本入库（`gates/diag/*` 已忽略，:76）。
7. 不许把 `acquire_slot_lock` 的 timeout 改成 0 或无限等来「避免死循环」。

