# 审计 · GLM-5.3 对抗审核：整个外包系统（卡 153 · T-G252）

> **审核基线**：卡树 `.wt/audit53` @ `4b0ab34`；号池仓 `D:/repo\infra\pool\` 工作区现状。
> **已去重**：`复盘/坑总账.md`（344 条，主仓 @ `9ba2e02`）与 `复盘/不变量台账.toml`（77 条）全读；
> 已在其中的条目一律不重复，相邻条目在文中注明关系。
> **方法**：五路只读侦察（门禁跑器+锁 / 派活器+MCP / 收口+复核+栅栏 / 号池仓 / 审计脚本族）
> 出候选，**每条再由审核者亲自读码核到行号**；核不到的写明「查不出来」，不编。
> **严重度口径**：高 = 能造假绿 / 能越权 / 不可逆损失；中 = 判据漂移、假红、覆盖面缺口；
> 低 = 潜伏雷或边界没写破。每条标方向（① 单向判据 ② 只有人话 ③ 假绿/假红 ④ 覆盖面 ⑤ 多份真源 ⑥ 绕过路径）。

---

## 高（15 条）

### D-01 复核链的真源 `gates/last.json` 可徒手伪造，复核器没有任何他证（方向⑥）
- 出处：`tools/wb_review.py:131-151::check_gate_evidence` + `tools/wb_review.py:12`（取这一笔提交里的那一份）+ `scripts/run_gates.py:1658`
- 现象：③/③′/ⓖ 三档判据的全部输入（`ok`/`rev`/每门 `exit_code`/`docs_sync_ok`）都是纯 JSON 字段；`rev` 是短 SHA，工人一条 `git rev-parse --short HEAD^` 就拿到。手写一份全绿 last.json 提交，复核照过。
- 复现：读 `tools/wb_review.py:131-151`（全部判据只读 payload 字段、无完整性标记、不与 `gates/diag/` 原始读数交叉）；`scripts/run_gates.py:1658`（rev 就是短 SHA）。
- 真因：证据链自证其证 —— 产生证据的与提交证据的是同一个人；`--seal` 还会给伪造品重算合法指纹（`run_gates.py:770` 只要求 `ok=true`），连 `wb_verify.check_fingerprint` 都能过。
- 归位：`tools/wb_review.py::check_gate_evidence`（INV-01 note 只写了「绕过收口链是事后咬」，没写「last.json 本身可徒手造」）。
- 严重度：高 —— 整条复核链对「懒得跑 9 分钟门禁的工人」零防御，是全系统最值钱的假绿路径。
- 修法：last.json 落盘时附「当趟门禁全量输出（gates/logs/）的合并 sha256」一并入库，复核侧重算比对；或高危卡强制抽一道门真跑。

### D-02 ③′ 的 tree_scope 豁免是给伪造品留的后门：不写这个字段，门数判据整体失效（方向⑥③）
- 出处：`tools/wb_review.py:233-239::check_full_gate_run`
- 现象：判据自己写明「没有 tree_scope ⇒ 不是门禁跑出来的产物」，但处理是 `return [], note, reading` —— 零 problem。伪造者只要不写 tree_scope，全链最强的门数核对（现读 `build_jobs`）就只剩一行标注。
- 复现：读 `tools/wb_review.py:232-239`；推一份「无 tree_scope、门数不符」的 JSON 走一遍：两条路都返回空 problems。
- 真因：为护两个合成测试夹具开的豁免，用了「缺字段 ⇒ 放过」而不是「缺字段 ⇒ 拒」；新提交的笔不存在「旧笔」一说。
- 归位：`tools/wb_review.py::check_full_gate_run`（与 INV-14 同族不同条：INV-14 是不查门数，这条是查了但给伪造品留豁免口）。
- 严重度：高 —— 它把 D-01 里唯一像样的机器判据变成可选项。
- 修法：本笔提交里的 last.json 缺 tree_scope 一律判红；夹具豁免改为按测试环境变量或路径白名单识别，不按字段缺失识别。

### D-03 `gates/reuse.json` 手写一条 `verdict=pass` 即让真机门零跑过闸，痕迹可完全抹掉（方向⑥）
- 出处：`scripts/run_gates.py:1242-1255::skip_reused` + `:424-427::save_reuse` + `:757-764`（封存指纹排除 `gates/**`）
- 现象：复用判据只信「记录 verdict=pass + 输入哈希相等」，而哈希算法公开、输入全在仓内。工人算一次 `input_hash`，手写一条记录，render/ui_flow/lf1_live/web_live/ui_dom_probe 五道真机门全部「复用通过」—— 一次都没跑，last.json 却是全绿全门数。跑完 `git checkout -- gates/reuse.json`，提交里零痕迹。
- 复现：读 `scripts/run_gates.py:1242-1255`；`git ls-files gates/`（reuse.json 入库但指纹排除 gates/**）。
- 真因：复用判定把「仓内一份谁都能写的文件」当真源，没有完整性标记，也没绑到某次真实运行；wb_review 不查 `reused` 字典、不查复用记录真伪。
- 归位：`scripts/run_gates.py::skip_reused`（与坑总账「改门输入命中复用 · 没关」「复用在顶层 reused 字典」相邻：那两条是语义/覆盖面，这条是输入文件本身可伪造）。
- 严重度：高 —— 最慢最贵的 5 道真机门可被 20 字节 JSON 永久跳过，复核看不出。
- 修法：last.json 的 `reused` 非空时复核侧强制 `--no-reuse` 重跑或人工确认；复用记录与当趟 rev 绑定并由 wb_review 对账。

### D-04 `seal()` 把门禁时的指纹无条件覆盖成「现在的树」：门禁绿之后随便改，seal 给没验过的内容盖章（方向③）
- 出处：`scripts/run_gates.py:772-784::seal`
- 现象：门禁跑时 `staged_tree()` 把工作区指纹 T0 写进 last.json；`--seal` 重算成 T1 直接覆盖，old≠new 只打印一行就放行。而 staged_tree 是确定性固定点，old≠new ⟺ 门禁跑完后内容被改过 ⟺ 这部分从没被验过。流程：全量绿 → 徒手改 src → `--seal` → 提交，last.json 全部字段内部自洽。
- 复现：读 `scripts/run_gates.py:772-784`，确认没有 old 与 new 的相等性判据。
- 真因：seal 把「重算指纹」当目的，丢了「指纹必须仍指向门禁验过的那份内容」这个不变量。
- 归位：`scripts/run_gates.py::seal`（与坑总账「封存树≠提交树无对比 · 半关」「封存指纹没人查 · 未标」相邻但机制不同：那两条是消费端没人核，这条是生产端自我洗白 —— wb_review.py:67 目前故意不查 tree，可即使将来消费端开始查，seal 也保证它查不出）。
- 严重度：高 —— 封存指纹这条线从根上失去意义。
- 修法：seal 时 old≠new 直接拒（退出非零，提示重跑门禁），相等才重写。

### D-05 `DOOR_INPUTS['render']` 漏了 `tools/render_signatures.json`（render 门的真输入）——改语义签名命中复用假绿（方向④）
- 出处：`scripts/run_gates.py:325-326` + `tools/render_check.mjs:59`（启动即 `readFileSync` 该文件）
- 现象：render 门每屏的语义断言（must/forbid/min_count/min_rows）写在 `tools/render_signatures.json`，但它不在门输入表里。改签名文件 → 输入哈希不变 → 命中复用 → render 拿上次的 pass 冒充现在绿；`--affected` 用同一张表，同样漏裁。
- 复现：`grep render_signatures scripts/run_gates.py` → 0 命中；读 `tools/render_check.mjs:59`。
- 真因：门×输入表靠人登记，没有「门实际读了什么文件」的机器对账。
- 归位：`scripts/run_gates.py::DOOR_INPUTS`（坑总账「改门输入命中复用 · 没关」的具体活实例，且连着 `--affected` 一起漏）。
- 严重度：高 —— 把某屏断言改松/删掉，门禁照样绿，正是「判据改松了还留着」的假绿家族。
- 修法：输入表补 `tools/render_signatures.json`；长期立一条「输入表 vs 门脚本实际读文件」的机器对账。

### D-06 门禁锁纯自觉：`run_gates.py` 从头到尾不查锁，「拿到锁才跑」只是注释里的人话（方向⑥②）
- 出处：`scripts/run_gates.py::main`（全文无 gate_lock 调用）对照 `gates/diag/gate_lock.py:45-46`（用法注释）
- 现象：INV-02 标 covered，judge 钉的是锁工具本身；但跑器不验锁 —— 工人徒手 `python -X utf8 scripts/run_gates.py` 就整趟跑起来。pool 侧 `lock_guard` 只在派活那一刻查一次（跑门禁是几小时后的事，TOCTOU），徒手调用根本不过 pool。
- 复现：`grep gate_lock scripts/run_gates.py` → 仅 2 行注释命中，无调用。
- 真因：互斥机制是外挂自觉锁，判据钉在锁工具上，没钉「跑器必须持锁」这条链接。
- 归位：`scripts/run_gates.py::main`（坑总账「并发两趟门禁抢 CPU 端口 · 半关」记的是现象，这条是机制缺口：防并行唯一的机器闸是自愿的）。
- 严重度：高 —— 两趟同段门禁并行 ⇒ 撞端口假红，或同树双跑互掐。
- 修法：run_gates 开跑前读主仓锁文件，持有者 card/cwd 与本树不符就拒跑（或显式 `--no-lock` 并记进 last.json）。

### D-07 `gate_cmd` 白名单被 `..` 穿过：`startswith('tools/')` 不做路径规范化（方向⑥）
- 出处：`tools/pool/task.py:329-354::validate_gate_cmd` + `:779-796::_run_gate_cmd`
- 现象：判据是 `argv[3].replace('\\','/')` 后 `startswith(('scripts/','tools/'))`。`python -X utf8 tools/../../仓外任意.py` 照样以 `tools/` 开头 ⇒ 过白名单；执行时 `cwd=主树根` + `shell=False`，python 自己解析 `..` ⇒ 跑的是仓库外的脚本，而门禁读数照样「绿」。
- 复现：脑内过一遍 `validate_gate_cmd('python -X utf8 tools/../../x.py')`：无元字符、前缀齐、startswith 为真 ⇒ 不抛。
- 真因：白名单用字符串前缀当路径判据，没 normpath/resolve 后确认落在根内；`GATE_CMD_METACHARS` 不挡 `.` 和 `/`。
- 归位：`tools/pool/task.py::validate_gate_cmd`（坑总账「gate_cmd 任意 shell · 已关」关的是元字符那半，`..` 这半还开着；register 与 claim 共用这条判据，一洞两吃）。
- 严重度：高 —— 知道此洞的人注册一个任务就能把任务门禁换成仓外脚本。
- 修法：argv[3] 先 normpath，拒掉含 `..` 或 resolve 后不在 `<root>/scripts|tools` 下的，再谈前缀。

### D-08 栅栏的权威底账（manifest/state/inbox）全在 gitignored 目录，无版本无完整性 —— 复核器却拿它当权威域①（方向⑥⑤）
- 出处：`tools/pool/task.py:142-147::batch_dir` + `.gitignore:75-77` + `tools/wb_review.py:397-411::resolve_domain` + `tools/pool/task.py:456-457`（`register --force` 整锅重置）
- 现象：任务预声明（每卡域 paths）、状态（claims/waived/history）、收件箱全是主树里不进 git 的裸文件。① 徒手改宽 manifest 里自己的 paths ⇒ `check_domain` 与 `resolve_domain` 同时被喂假域；② 删掉别人投的 failed 申请或手改 claims ⇒ 「不通过挡收口」失效；③ `register --force` ⇒ 审计痕迹归零。全程无哈希、无签名、无 git 历史。
- 复现：读 `tools/wb_review.py:403-411`（域真源就是这份可改文件）与 `tools/pool/task.py:450-493`；`grep 'gates/diag' .gitignore`。
- 真因：栅栏状态层是 scratch 出身的活文档，从没上过完整性这一课；复核侧却把它升格成权威真源。
- 归位：`tools/pool/task.py`（状态层）+ `tools/wb_review.py::resolve_domain`（消费层）。
- 严重度：高 —— 「逐卡域检查」自称最重要的守卫，地基工人一只手就能换掉。
- 修法：manifest 落盘时算 sha256 写进 state，claim/复核时比对；或把 manifest 挪进 git（如 `复盘/任务/`），batch/ 只放运行态。

### D-09 权威域②吃卡树里的 `workbacklog.toml`：工人改宽自己的 files 后，域检查自证其域（方向⑥）
- 出处：`tools/wb_review.py:427-435::resolve_domain`（`ROOT/docs/workbacklog.toml`，ROOT=复核进程所在树=卡树）+ `tools/pool/plan.py:35-42::PROTECTED_FILES`（6 个文件，不含 backlog）
- 现象：非批任务时权威域退回卡树内 backlog。工人在卡树里把自己卡的 `files` 改宽（顺手把 `docs/workbacklog.toml` 本身也加进去），随后 `outside_domain(actual, widened)` 对「改了 backlog」这一行为本身也判在域内 —— 改动域定义的行为被改宽后的域合法化，循环自证。
- 复现：读 `tools/wb_review.py:427-466` 与 `tools/pool/plan.py:35-42`；推一遍「卡树改 backlog → 跑 wb_review --card」的数据流。
- 真因：域真源与被审对象同树同权限；review 只比「实际改动 vs 域」，不比「域 vs 域的上一版」。
- 归位：`tools/wb_review.py::resolve_domain`（与坑总账「域 4 份声明 · 没关」相邻但不同：那是多源不一致，这条是单源自证）。
- 严重度：高 —— 卡 131 专门补的第⑥档（实际改动 vs 权威域）对非批任务可被一步架空。
- 修法：backlog 一律取主树 `git show <主树HEAD>:docs/workbacklog.toml` 的版本；或把 workbacklog.toml 加进 PROTECTED_FILES。

### D-10 登记层 `reserve` 读-判-写无锁（TOCTOU），并发派活互相盖、租约丢失；`release` 不核 owner（方向③⑥）
- 出处：`tools/pool/registry.py:299-327::reserve` + `:330-338::release`
- 现象：reserve 是 `load → 滤死 → 过守卫 → save` 四步裸奔，中间没有任何锁（task.py 有现成 spin_lock，这里偏偏没有）。两个窗口同时 reserve：后写者整份覆盖，先登的租约从表里消失，它占的树/域此后对 tree_guard/domain_guard 不可见 ⇒ 一树两写者。release(card) 只按卡号删、不核 owner，任何窗口（含工人）可放掉别人树的租约。
- 复现：读 `registry.py:295-338`（无锁、无 owner 比对），对照 `task.py:242-291` 的 spin_lock。
- 真因：原子写（os.replace）只保证不读半截，不保证读-判-写互斥；设计者把两件事当成一件。
- 归位：`tools/pool/registry.py::reserve`（坑总账「登记与栅栏」22 条里没有 registry.py 的条目）。
- 严重度：高 —— 这个模块存在的唯一理由就是并发安全，而它在并发下静默丢登记。
- 修法：reserve/release 套 spin_lock（task.py 的实现直接搬）；release 加 owner 匹配才放。

### D-11 登录自检 `auth_ok` 三件套：超时不兜异常、探的是默认模型、fail-closed 分不清「没登录」与「探失败」（方向③）
- 出处：`tools/wb_dispatch.py:352-365::auth_ok` 对照 `:935-954::quota_probe_ok`
- 现象：① `subprocess.run(timeout=180)` 外面没有 try —— 超时抛 TimeoutExpired 炸穿 preflight，判决留痕路径走不到，「没跑」与「跑挂了」分不清；② 探针不带 `--model`，测的是 CLI 默认模型（hy4-preview）而不是被派模型 —— 默认模型限流/抖动就拒派；③ 唯一阳性信号是 `AUTH_NEEDLE` 子串 + `连接成功` 子串，其余一律 fail-closed，且不扫额度 needle（quota_probe_ok 三样都有：try/except、`--model`、QUOTA_TEXT_NEEDLES）。2026-10-02 夜里三次假红与此完全吻合。
- 复现：读 `tools/wb_dispatch.py:352-365`（无 try、无 --model、无 quota needle）对照 `:937-951`。
- 真因：auth_ok 是 T-G80 时期写的，quota_probe_ok 是后写的，后者补的三件从没回灌给前者。（§19.2.7 已把「用默认模型探测」记为已知口径并给 `--no-preflight` 人工逃生口；超时不兜与 fail-closed 混淆这两件没有任何地方登记。）
- 归位：`tools/wb_dispatch.py::auth_ok`。
- 严重度：高 —— 夜里网络一抖，派活器要么 traceback 崩掉且不留判决，要么把「探失败」当「不能派」，过夜批空转。
- 修法：照 quota_probe_ok 抄三件：except 归一为「探测跑不起来」、带上 `--model model`、扫额度 needle。

### D-12 `wt_prune --apply --min-size N` 会把「已跳过」的小树照样删掉（方向⑥）
- 出处：`tools/wt_prune.py:662-664::collect` + `:688-692::do_apply`
- 现象：collect 对小于 min-size 的树只打 `v.skipped=True` 并改写 reason，不清 `v.deletable`；do_apply 只判 `if not v.deletable: continue`，完全不看 skipped；第二拍 recheck_apply 也不知道 min_size。表格明说这些小树「跳过」，随后它们照样进删除循环。
- 复现：读 `tools/wt_prune.py:655-664` 与 `:688-699`。
- 真因：skipped 只是展示层标记，删除路径用的还是第一拍的 deletable；两拍之间过滤条件丢失。
- 归位：`tools/wt_prune.py::collect`（坑总账 wt_prune 的 4 条里没有这条）。
- 严重度：高 —— 用户按表格以为只删大树，实际符合七条的小树（可能正是他在意的）被一起删，删除不可逆。
- 修法：置 skipped 时同时 `v.deletable=False`，或 do_apply 开头 `if v.skipped: continue`。

### D-13 号池派活器 `infra/pool/dispatch.py` 没有任何项目/树/域/锁守卫 —— projects.toml 的三条硬判据在这条线上是零机器判据（方向④）
- 出处：`D:/repo\infra\pool\dispatch.py::preflight`（行 71-129）
- 现象：号池侧「五道前置」只有 凭证在/模型闸/卡规格在/树干净/日志不覆盖；全仓 grep `projects.toml|tree_guard|project_guard` 零命中。`--tree` 指到任何 git 仓（主仓根、别的项目）都放行，且 `CODEAGENT_PERMISSION_AUTO_ALLOW=true`（codearts.sh:23）是全自动批准写。
- 复现：`grep -n 'projects.toml|_guard' D:/repo\infra\pool\*.py` → 零命中；读 dispatch.py:99-117。
- 真因：INV-05/06 的守卫只接在主仓 wb_dispatch 那条线（坑总账已关的是那一侧）；号池 dispatch.py 是后写的第二套派活器，守卫没跟着移植；架构文档 §5-2「项目索引已写未接线」在这条线上仍然是事实。
- 归位：`infra/pool/dispatch.py::preflight`（应调主仓 `tools/pool/guards.py` 同一份纯函数）。
- 严重度：高 —— codearts 工人可以被派进主仓根或未登记项目，「一树一写者」「域守卫」在这条线上不存在，而台账里它们标 covered。
- 修法：preflight 加一道：解析 projects.toml → project_guard + tree_guard + lock_guard（复用纯函数，不写第二份）。

### D-14 `codearts.sh` 全局关闭 TLS 证书校验（`NODE_TLS_REJECT_UNAUTHORIZED=0`）（方向⑥）
- 出处：`D:/repo\infra\pool\codearts.sh:18`
- 现象：node 进程（codearts CLI）对所有 HTTPS 连接不再校验证书；周围 20 行注释很密，唯独这行裸着没有任何说明。pool.env 注入的 AK/SK（行 26-29）与全部提示词/代码流量在同一个进程里走不验证书的 TLS。
- 复现：读 `codearts.sh:15-25`。
- 真因：多半是接入初期绕某个证书问题顺手加的，之后没人再评审；它跟着 exec 进每一次派活。
- 归位：`infra/pool/codearts.sh:18`。
- 严重度：高 —— 中间人可窃可改凭据与代码流量，凭证明文级暴露面，无任何台账条目提过它。
- 修法：删掉这行；若确有证书问题，改用 `NODE_EXTRA_CA_CERTS` 钉具体 CA。

### D-15 `scripts/backup.py` 裸拷活 SQLite，无完整性自证，`copied=0` 也打印「备份完成」（方向③④）
- 出处：`scripts/backup.py:25-33::main`
- 现象：逐个 `copy2` 正在使用的 `*.db`/`*.db-wal`/`*.db-shm` —— 主库与 wal 不是同一时刻的快照，恢复出来可以是撕裂态；没有任何校验（不比哈希、不跑 integrity_check、不试恢复）；一个文件没拷到也打印「备份完成」。仓里另有 `src/timeflow/storage/backup.py::make_backup`（SQLite 在线备份 API，有钉子）——两套备份，脚本这套零测试零调用点。
- 复现：读 `scripts/backup.py:20-33`；对照 `src/timeflow/storage/backup.py` 与 `tests/test_backup_restore_line.py`。
- 真因：脚本写在产品备份 API 之外，没接到同一实现；「复制没抛异常」被当成「备份成功」。
- 归位：`scripts/backup.py::main`（方向 ③ 假绿 + ④ 它不在任何一道门里 + ⑤ 与产品备份两份真源）。
- 严重度：高 —— 真到恢复那天才发现备份是坏的，而打印的话术让人以为有底。
- 修法：删掉脚本或改成调 `timeflow.storage.backup.make_backup`，备份后做一次 integrity_check 自证。

---

## 中（25 条）

### D-16 「本段端口」两份真源且不一致：锁探 6 个口，跑器用 11 个口（8545–8549 是锁的盲区）（方向⑤④）
- 出处：`gates/diag/gate_lock.py:80`（`GATE_PORTS` 6 个）+ `:114-125`（非默认 BASE 也只返 6 个）对照 `scripts/run_gates.py:285-289::gate_port_set`（base, base+1, base+10..base+18 共 11 个）
- 现象：run_gates 实际用到 BASE+14..BASE+18（ui_flow 流内对端，铁律 37 要求查整段 BASE..BASE+16），gate_lock 的 `_ports_busy` 与 status 只探 6 个口 —— D-17 那条本就只是警告的端口检查，连警告都对 5 个真在用的端口失声。
- 复现：读上述行，两边逐个数。
- 真因：同一概念两份手写声明，T-G156 加端口时只改了跑器侧。
- 归位：`gates/diag/gate_lock.py::GATE_PORTS`。
- 严重度:中 —— 锁的状态报告系统性少报，8545–8549 上的冲突永远隐形。
- 修法：锁的端口表改为从 run_gates.gate_port_set 现读（或抽共享常量）。

### D-17 `gate_lock acquire` 明知本段端口被占仍发锁（退 0，只打一行警告）（方向②）
- 出处：`gates/diag/gate_lock.py:296-316`
- 现象：锁的语义是「拿到 = 这段端口归你用」，但 acquire 检测到端口已被占用时只印「★ 警告」就返回 0。拿着锁去跑门禁 → serve 绑不上 → 假红。
- 复现：读 `gate_lock.py:296-316`（busy 只进 print，不进返回值）。
- 真因：判据（端口忙）有了，动作（拒发锁/先清）没接 —— 只有人话没有机器判据。
- 归位：`gates/diag/gate_lock.py::main`（acquire 分支）。
- 严重度：中 —— 锁给了虚假安全感，端口冲突全部以门禁假红的形式事后爆发。
- 修法：busy 非空时 acquire 退非零（或转清遗留流程）。

### D-18 `docs_sync_precheck` 触发面只认 `src/timeflow/` + `src/web/`：只改 tools/scripts/tests 的提交，门④真空通过（方向④）
- 出处：`scripts/run_gates.py:744::docs_sync_precheck`
- 现象：门④名义判据是「改了源码就必须同时改台账/changelog/CHECKPOINT」，但「源码」的触发定义只有两棵子树。一笔只改 `tools/pool/landing.py` + `tests/` 的提交，④ 不查任何文档同步直接 OK —— 而本仓自己的惯例就是改 tools/ 也要落 changelog.d 片段。
- 复现：读 `scripts/run_gates.py:732-754`。
- 真因：触发条件按「产品代码」写死，与判据声称的范围不一致。
- 归位：`scripts/run_gates.py::docs_sync_precheck`（已 grep 坑总账两节核实未收录）。
- 严重度：中 —— 工具链/测试改动可以不带任何台账痕迹过闸，「改了什么必须留痕」失去机器背书。
- 修法：触发面扩到 `src/ tools/ scripts/ harness/`（或给出显式免同步白名单，其余全触发）。

### D-19 MCP 派活路径完全没有 `project_guard`（INV-06 在 MCP 写面失效）（方向④）
- 出处：`tools/pool_mcp.py:1063-1068::tool_pool_dispatch`（干跑只有树/域/锁/日志四条）+ `tools/pool/registry.py:303-307::reserve`（同样四条）+ `tools/wb_dispatch.py:2008-2016`（`--already-reserved` 跳过整个守卫段）
- 现象：CLI 派活有 project_guard（wb_dispatch.py:1827），MCP 这条路：pool_mcp 全文 grep 不到 project（零匹配）、registry 不接、wb_dispatch 又被 --already-reserved 跳过 ⇒ 三层都没有项目守卫。tree 可以指磁盘上任何 git 树，跨项目串树照过。
- 复现：`grep -n project tools/pool_mcp.py` → 无匹配；读 registry.py:303-307。
- 真因：卡 120 的 project_guard 只接进了 wb_dispatch 的 guard_problems；卡 125 给 MCP 面接守卫时接的是旧三条 + log_guard，此后没人对齐。
- 归位：`tools/pool_mcp.py::tool_pool_dispatch`（INV-06 标 covered 是按 CLI 路径钉的）。
- 严重度：中高 —— 别的窗口经 MCP 把工人派进未登记/别的项目的树，租约照占、域照查（查的是本仓 backlog），跨项目污染无从咬起。
- 修法：tool_pool_dispatch 干跑里补 `guards.project_guard(tree, None)`（与 wb_dispatch:1827 同一调用）。

### D-20 `pool_dispatch` 取 pid 靠正则匹配人话「（pid N）」—— 文案一漂就「放出工人却回滚租约」（方向②③）
- 出处：`tools/pool_mcp.py:968::_PID_RE` + `:1099-1109::tool_pool_dispatch`；被匹配的文案在 `tools/wb_dispatch.py:2186`
- 现象：`--detach` 成功的唯一机器通道是「退出码 0 + stdout 里那句（pid N）」。正则抓不到时（文案微调）走「没扔出去 ⇒ registry.release(card) 回滚租约」—— 但只要退出码是 0，工人其实已经扔出去了 ⇒ 工人在跑、租约已还 ⇒ 这棵树被判空可再派 ⇒ 一树两写者。另 `_spawn_worker` 的 subprocess.run 无 timeout，前置登录探针最长 180s，MCP stdio 会被同步冻住。
- 复现：读 pool_mcp.py:1099-1109 与 wb_dispatch.py:2186。
- 真因：成败/身份契约只有人话 stdout 一个通道，没有机器通道。
- 归位：`tools/pool_mcp.py::tool_pool_dispatch` + `tools/wb_dispatch.py::main`（落 pid 的那一侧）。
- 严重度：中 —— 一次文案重构就把「一树一写者」在 MCP 路径上静默拆掉。
- 修法：`--detach` 成功时 wb_dispatch 把 pid 写进租约（或打一行机器行 `PID=<n>`），pool_mcp 读那个，不认人话。

### D-21 `pool/jobs.py` 判「断了」仍是 480s 平直阈值，与看门狗自适应口径语义已漂（方向③⑤）
- 出处：`tools/pool/jobs.py:35`（`STALL_SECONDS = 480`）+ `:226-232::classify_job_state` 对照 `tools/wb_dispatch.py:191-197`（BUSY 1800 / ×2.5 / 封顶 3600）
- 现象：测试钉住了常量相等（480==480），但 wb_dispatch 运行时早已不是这个数：有工具在飞上抬 1800、按历史最长 ×2.5、封顶 3600。工人跑长工具调用期间 jsonl 一个字节不长（心跳落在单独的 .heartbeat.txt），mtime 一老，job_list 就报「断了」—— 别的窗口据此 cancel 或重派，就是把活人当尸体。
- 复现：读 jobs.py:226-246（只看 mtime），对照 wb_dispatch.py:188-197。
- 真因：卡 106 抽公共实现时钉住了「数字同源」，没钉「判据同构」；T-G94 改自适应后 jobs.py 没跟上。
- 归位：`tools/pool/jobs.py::classify_job_state`。
- 严重度：中 —— 冷缓存 ui_flow 十几分钟的正常长调用，在别的窗口眼里就是「断了」，诱发误杀/重派。
- 修法：判「断了」前先看 log 尾部有没有未配对的 tool_use（在飞按 1800 口径），或复用 wb_dispatch 的 inflight 判据。

### D-22 不弹窗扫描只 `rglob('*.py')`，`.mjs` 一个都不扫；`NO_WINDOW` 自称唯一真源实则四份拷贝（方向④⑤）
- 出处：`tests/test_no_window.py:92-96::iter_sources`（只吐 .py）+ `tools/tf_browser.mjs:108`（spawn python 起 serve.py，无 windowsHide）+ `tools/trae_pool.mjs:109`；`tools/pool/no_window.py:1-29`（自称唯一真源）对照 `tools/wb_dispatch.py:122`、`tools/wb_state.py:31`、`harness/wb_state.py:26`
- 现象：① FLAG_TOKENS 里明明躺着 `windowsHide`（JS 生态的 flag），扫描器却不看 9 个 `.mjs`；tf_browser.mjs:108 起的是 console 应用 python.exe，无控制台父进程起它必闪窗 —— 正是门禁链。② 卡 148 立真源时没回灌老文件：wb_dispatch/wb_state/harness 各抄一份（两种写法），test_no_window.py:303 只钉 pool 那份 == CREATE_NO_WINDOW，没钉 wb_dispatch 那份同源。
- 复现：`grep -n spawn tools/*.mjs` + 读 tests/test_no_window.py:92-96 与上述四份拷贝。
- 真因：钉子实现时只做了 Python AST 一路；立真源时白名单外老文件没回灌。
- 归位：`tests/test_no_window.py::iter_sources` + `tools/wb_dispatch.py:122`。
- 严重度：中 —— 用户抱怨的「一直蹦命令行窗口」在 .mjs 链路会复发而钉子全绿；改口径时改一处漏三处。
- 修法：扫描器加一路 .mjs 文本扫（认 spawn(/execFile( 且无 windowsHide）；wb_dispatch/wb_state 改为 from pool.no_window import NO_WINDOW 并补 `is` 钉。

### D-23 `extend --to` 不校验日期合法性：垃圾期限让 deadline 安全阀永久失效（方向③）
- 出处：`tools/pool/task.py:702-722::cmd_extend` + `:505-514::_deadline_passed`
- 现象：`state['deadline'] = args.to` 原样落盘不校验；`_deadline_passed` 对解析不了的值返回 False（不算到）⇒ `extend --to 随便` 之后 `_enforce_deadline` 永远放行，任务永不判死，且无任何报警。对照 cmd_expire（:1021-1025）有「没到不许判死」的校验，extend 这条反向路径是裸的。
- 复现：读 `task.py:505-519`（`except ValueError: return False`）与 `:702-722`。
- 真因：「认不出 ⇒ 保守」的口径在这里选错了方向 —— 解析失败被当成「没到期」而不是「数据坏了」。
- 归位：`tools/pool/task.py::cmd_extend`（与坑总账「expire 不校验 deadline 是否真到 · 已关」配对但未覆盖）。
- 严重度：中 —— 一句手滑就关掉安全阀之一的「过期只判死」，而且静默。
- 修法：extend 落盘前 fromisoformat 校验，非法即拒；`_deadline_passed` 对「有值但解析不了」改判已到期或响亮报错。

### D-24 `landed` 是直写状态的调试入口：任意态可跳终态，不核 commit 存在、不核门禁绿（方向②）
- 出处：`tools/pool/task.py:725-736::cmd_landed`
- 现象：不查当前状态（collecting 0 张申请也能直接 landed）、不查 --commit 是不是真实提交、不查 state['gate'] 是否绿。模块头宣称「放行判据是名单上每张卡都交了成功申请」，而这个入口把整条状态机一步跳到终态；下游 `wb_advcard.py --task` 会拿着假 commit 生成对抗复核卡。
- 复现：读 `task.py:725-736`（函数体只有赋值与写盘）。
- 真因：按「要人显式标」设计，但机器侧没有任何「人来标之前必须满足什么」的判据。
- 归位：`tools/pool/task.py::cmd_landed`（坑总账「advance 复活 landed · 已关」管的是反方向）。
- 严重度：中 —— 栅栏台账可以被写成「已收口」而实际没收口。
- 修法：landed 前校验 state==awaiting-commit 且 `git cat-file -e <commit>` 通过。

### D-25 `advance` 不拒 `gating` 态：门禁在跑时被重置回 collecting ⇒ 门禁双跑、后到读数被丢弃（方向③）
- 出处：`tools/pool/task.py:1001::cmd_advance`（gating 不在拒绝清单）+ `:799-822::_finish_gate/_drive`
- 现象：门禁在锁外跑期间状态是 gating、锁已放掉 ⇒ 此刻任何人跑 advance 都能拿锁，把 gating 重置成 collecting → 再推进 gating → 第二个门禁进程起跑（任务门禁不拿 gate_lock，两趟全量并发在主树跑，端口互掐）。更阴的是收尾：先跑完的把状态推离 gating，后跑完的在 :808 看到状态不符直接丢弃读数 —— 若丢弃的是「修好后那趟绿」，账面留在红，白跑 5-9 分钟且结论过期。
- 复现：读 `task.py:967-1006`（拒绝清单只有 landed/timeout）与 `:799-822`。
- 真因：卡 128 把门禁移出锁外之后，状态机没给 gating 配「进行中不可重入」的判据。
- 归位：`tools/pool/task.py::cmd_advance`。
- 严重度：中 —— 触发姿势就是文档推荐的「状态卡住时 advance 一下」。
- 修法：advance 对 gating 拒（或要求显式 `--abort-gate` 并留痕）。

### D-26 `TF_MODEL_SWITCHES` 环境变量直达生产模型闸：工人自写一份开关文件即可放行任意模型（方向⑥）
- 出处：`tools/pool/models.py:93-101::switch_file_path`（env 覆盖排第一）+ `tools/wb_dispatch.py:268-306::effective_allowed_models/model_rejected`
- 现象：模型闸允许集 = 名单常量 ∪ 开关文件里打开的，而开关文件路径第一优先级是 `TF_MODEL_SWITCHES`。该变量注释自称「只给测试用」，但没有任何代码把它限制在测试路径 —— 工人（本来就是 CLI、能设环境变量）写一份 x.toml 里放行任意模型，`model_rejected` 当场放行，且 --resume/--retry/--detach 全过这道闸。
- 复现：读 `models.py:93-105` 与 `wb_dispatch.py:273-306`。
- 真因：测试逃生口接在生产判据正中间，没有「非测试不生效」的护栏；INV-08 的 note 没提这个变量。
- 归位：`tools/pool/models.py::switch_file_path`。
- 严重度：中 —— 绕过的是「未授权模型一律拒单」这条用户亲口令（对任何能设 env 的调用方，闸门形同虚设）。
- 修法：仅当另一测试专用变量（如 `TF_TEST_ENV=1`）同时在场才认 `TF_MODEL_SWITCHES`。

### D-27 claim 的「证据」只有非空判据：`--files` 不核存在、`--evidence` 自由文本、`--log` 落盘后再无人碰（方向①）
- 出处：`tools/pool/task.py:571-577::cmd_claim` + `:546-568::check_domain` + `:617`
- 现象：`claim success --files tools/a/不存在.py --evidence 'pytest 全绿' --log 任意路径` 全部照收。文件存不存在、在不在卡树、与域一致之外是否真实发生，没有任何一行代码核。「成功」二字在机器层面只等价于「字符串非空」。
- 复现：读 `task.py:571-619`（payload 组装全程无文件系统访问）。
- 真因：证据链设计停在「留痕」层，没走到「可核」层。
- 归位：`tools/pool/task.py::cmd_claim`（与坑总账「--allow/--evidence 漏文件没人咬 · 半关」不同：那条是漏报，这条是谎报）。
- 严重度：中 —— 栅栏的「集齐」可以是全凭空口；它依赖下游 review 兜底，而 review 的域真源本身有 D-08/D-09 的问题。
- 修法：`--files` 逐项核在卡树存在且相对卡树 HEAD 有改动；`--log` 给定时核文件存在且非空。

### D-28 `wb_invariants` 只核「文件存在」：`::符号` 从不核、注释掉的钉子也算、status 防错标判据没有（方向①③）
- 出处：`tools/wb_invariants.py:83-90::judge_path`（`split('::',1)[0]`，符号部分丢弃）+ `:127-129`（只核路径存在）+ `:98-100::_defines`（正则核 `def <名>(`，注释掉的也算）+ `:119-133`
- 现象：① judge 写 `landing.py::main`，main 改名/删掉后台账照样全绿 —— 77 条 INV 的判据指针全部是「死指针不报警」；② nail 只核 def 出现在文件里，不核这个用例遇到反例真的会红；③ status 只有单向判据（covered 缺件会咬），「judge 有牙没有」「该标 partial 却标 covered」没有机器判据 —— 而这张表自己就是用来治「靠人自觉」的。
- 复现：读 `wb_invariants.py:83-150`。
- 真因：判据刻意只做「防台账烂掉」，但 status=covered 向外传递的是「有牙」，两层之间没有对齐判据。
- 归位：`tools/wb_invariants.py::check_entries`。
- 严重度：中 —— 台账会「看着很绿」地基却在烂；每条 covered 都可能只剩一个文件名。
- 修法：judge 带 `::符号` 时核符号存在；对 covered 条目加一条「钉子真跑一遍必须红→绿翻转」的低频自证门。

### D-29 `use` 切号是「并集还原」：目标快照缺的件保留当前号的 ⇒ 家目录变成两个号的混合态（方向③）
- 出处：`D:/repo\infra\pool\codebuddy_accounts.py:223-233::cmd_use`
- 现象：还原时遍历当前家目录里存在的件；目标账号快照里没有这件，打印「跳过 … 保留当前的不动」⇒ 切到 B 后，凡是 A 有而 B 没有的身份件（failover.json、epoch-marker.json、新版 CLI 才写的文件）仍然是 A 的。
- 复现：读 `codebuddy_accounts.py:223-227`（`if not back.exists(): … continue`）。
- 真因：「只增不减」铁律被过度应用到还原方向 —— 不敢删当前件，用保留代替清理；但身份文件不是用户数据，保留 = 串号。
- 归位：`codebuddy_accounts.py::cmd_use`。
- 严重度：中 —— 「半 A 半 B」的登录态（Cookie 是 B 的、device-id 是 A 的）表现为不可复现的认证怪病。
- 修法：use 时把「目标快照没有的当前身份件」一并挪进 `_current-*` 存档并从家目录移除（至少醒目列出混合清单让人确认）。

### D-30 `pool_models.py` 把 stderr 拼进可用集解析，且拉取失败照样覆盖 `models.live.json`（`--require` 也有写副作用）（方向③）
- 出处：`D:/repo\infra\pool\pool_models.py:79-81::live_models` + `:166-174::main`
- 现象：① `out = stdout + stderr` 整段喂给解析 —— stderr 里任何「首 token 含 /」的错误行会被当成可用模型混进 live 集（假绿方向：交集放进一个服务端实际在报错的模型）；② 快照无条件写：bash/codearts 挂了、未授权时 live 解析为空，旧的好快照被「live: []」覆盖；③ `--require`（派活闸，理应只读）每次也写快照 —— 对照 INV-08 对主仓闸的要求「拒单必须零副作用」。
- 复现：读 `pool_models.py:79-81` 与 `:166-174`。
- 真因：输出与错误共用一个管道解析；快照写成无条件动作而非「拉到真表才更新」。
- 归位：`pool_models.py::live_models` + `main`。
- 严重度：中 —— 第三份真源（快照）变成不可信的，事后对账拿不出「当时服务端到底有啥」。（触发①依赖服务端错误文本形状，查不出来，但「stderr 被拼进解析输入」是代码事实。）
- 修法：只解析 stdout；写快照前断言输出含表头，否则保留旧快照并报警；`--require` 不写快照。

### D-31 `cmd_save` 不检测活进程：CLI 在跑时 save 会把写了一半的 SQLite WAL 拷进快照；`--force` 覆盖在日志里与首次保存不可区分（方向③②）
- 出处：`D:/repo\infra\pool\codebuddy_accounts.py:168-192::cmd_save`（`_live_cli` 只在 cmd_use 调，:201）
- 现象：① use 有活进程拒绝，save 没有 —— 快照清单含 workbuddy.db/-shm/-wal，CLI 在跑时 copy2 这三件是非原子的，会存出内部不一致的快照；② `_log` 的 detail 不含 force 标记 ⇒ ACTIONS.log 里「第一次存」与「--force 覆盖旧快照」长得一模一样（「只增不减」被覆盖后无法对账）。
- 复现：读 `codebuddy_accounts.py:168-192`（无 `_live_cli()` 调用）对比 `:201-205`。
- 真因：活进程守卫只加在「会覆盖家目录」的 use 上，没想「读的源头在动」同样是坏快照。
- 归位：`codebuddy_accounts.py::cmd_save`。
- 严重度：中 —— 存出损坏快照而人以为存好了，哪天切回去解不开凭据才发现。
- 修法：save 前同样过 `_live_cli`（可用 --force 越过）；`_log` detail 带上 force=True。

### D-32 `_live_cli` 的子串匹配会把「发起切号的 CodeBuddy 会话本身」算成在跑实例 ⇒ use 恒被要求 --force，守卫退化成习惯（方向③）
- 出处：`D:/repo\infra\pool\codebuddy_accounts.py:127-135::_live_cli`
- 现象：判据是 `'codebuddy' in cmdline.lower() and 'codebuddy_accounts' not in …`。主控的正常用法就是从 CodeBuddy CLI 会话里发起 use —— 会话本身的进程 cmdline 含 codebuddy ⇒ 永远检出「有 codebuddy 在跑」⇒ 永远要 --force。
- 复现：读 `codebuddy_accounts.py:127-135`；在任一 CodeBuddy 会话里调 `_live_cli()` 必返回非空。
- 真因：排除清单只排了脚本自己，没排「调用者链上的 codebuddy CLI」；也没按「该进程的家目录是不是要切的那两个」过滤。
- 归位：`codebuddy_accounts.py::_live_cli`（与坑总账假红家族同根但未登记）。
- 严重度：中 —— 第 3 条铁律（有实例在跑就别切）在实践中恒红 ⇒ 人被训练成一律 --force ⇒ 真该拦的那天（真有工人在跑）也被习惯性 force 掉。守卫不是被删的，是被假红磨没的。
- 修法：按进程的可执行路径精确匹配 CLI 入口，或排除当前进程的祖先链；至少把探测结果分「我自己所在的会话」与「别的实例」两档报。

### D-33 号池 `dispatch.py` 只保留最后一个 step_finish 的 tokens ⇒ usage_report 的总额是「末轮账」（方向③）
- 出处：`D:/repo\infra\pool\dispatch.py:187-189::Runner._parse` + `usage_report.py:53-58`
- 现象：每个 step_finish 事件都执行 `self.tokens = part.get('tokens')`（覆盖，非累加）。多回合会话有多个 step_finish ⇒ meta.json 只剩末步 tokens；usage_report 再拿这个字段合计。README 行 63「单轮约 30,810 tokens ⇒ 满额约 324 轮」的额度账正是这么估的。
- 复现：读 `dispatch.py:183-191`；任一多回合卡 logs/*.jsonl 里各 step_finish tokens 之和必大于 meta.json 的 tokens。
- 真因：把「最新的读数」当成了「本场的总数」—— 单回合碰巧相等，多回合静默少算。
- 归位：`dispatch.py::Runner._parse`。
- 严重度：中低 —— 账面用量系统性偏小，额度耗尽比估算来得早；「本地账 vs 服务端账对不上」会被 README「对不上是正常的」吞掉。
- 修法：tokens 改为累加各 step_finish 的 input/output/total。

### D-34 卡规格「逐字」钉子在源不可达时 skip，而源在 gitignored 目录 —— 新机器上永远不执行（方向③）
- 出处：`tests/test_card_specs_tracked.py:149-151` + `:72-86::_source_diag_dir` + `.gitignore:75-77`
- 现象：钉子③（sha256 逐字对照）在找不到主仓 `gates/diag/` 时 `pytest.skip`。而 `gates/diag/` 被 gitignore，任何新克隆/换机器/CI 都必然 skip —— 逐字对照事实上只在原作者那台机器上跑。钉子①只核「在 git 索引里」，不核内容：把卡规格内容改掉，① 照绿。
- 复现：读 `tests/test_card_specs_tracked.py:145-151`；`grep 'gates/diag' .gitignore`。
- 真因：逐字对照的真源（gates/diag/ 存档）本身不进 git，测试把「真源不在」处理成跳过而不是失败。
- 归位：`tests/test_card_specs_tracked.py`。
- 严重度：中 —— 卡规格进 git 后内容漂移（被改/被截断）无任何机器判据，恰是本仓想防的事。
- 修法：③ 改成钉「`复盘/卡/<名>` 与 git 索引 blob 哈希等于落地时记录的哈希」（哈希写进测试或台账），不依赖 gitignored 的源目录。

### D-35 `tf_commit` 的 `Task:` 判据是形状正则，不是台账成员 —— 拒合法、放非法（方向⑤①）
- 出处：`tools/tf_commit.py:85::_TASK_ID`（`^T-G\d+$`）对照 `scripts/audit_progress.py:329::parse_task_trailers`（按台账实集判成员）
- 现象：两个方向都错 —— ① 台账里合法的非 T-G 编号（T-B5、STEP-*、OP-*、SR-*）会被 tf_commit 退 4 拒掉（假红）；② `Task: T-G99999`（台账里没有）形状合法，第 6 步照过，提交落盘后第 7 步 audit 才红 —— 但提交已经造成了。
- 复现：读 `tf_commit.py:85` 与 `audit_progress.py:329` 对比。
- 真因：tf_commit 另写了一份「什么叫合法 Task」的判据（形状），没复用 audit 的成员判据；两份判据各自漂移。
- 归位：`tools/tf_commit.py::_check_trailers`。
- 严重度：中 —— 合法卡被挡会诱使工人绕过 tf_commit；非法编号放过则把脏提交留进历史。
- 修法：读 `docs/traceability.toml` 的 entries 集合，用与 parse_task_trailers 同一个函数判。

### D-36 `tf_commit` 的 trailer 校验扫全文而非尾部 trailer 块，空值也算「在」（方向③）
- 出处：`tools/tf_commit.py:307-314::_check_trailers`
- 现象：对 `--msg-file` 逐行 match `^([A-Za-z]+):` —— 正文任意位置的 `Task: xxx`（比如复盘引述）都被当成 trailer；且 `Gates:`（空值）也会 append 进 found，missing 判不出来。而 git 只认末尾连续的 trailer 块，audit 用 `%(trailers)` 读 —— tf_commit 认为齐了、git/audit 认为没有，两套口径。
- 复现：读 `tf_commit.py:307-316`；对照 `audit_progress.py:266`（`%(trailers:key=…,valueonly)`）。
- 真因：自写正则模拟 git trailer 语义，只模拟了「行形状」，没模拟「必须在末尾块」与「值非空」。
- 归位：`tools/tf_commit.py::_check_trailers`。
- 严重度：中 —— 缺 trailer 的提交被放行，事后 audit 红时提交已落。
- 修法：改用 `git interpret-trailers --parse` 解析 msg-file，或只取最后一个空行之后的块再匹配，并要求值非空。

### D-37 白名单判据出现第三份副本：`tf_commit` 内联实现（禁 glob），统一的 `outside_allow` 没人调它（方向⑤④）
- 出处：`tools/tf_commit.py:261::step6`（`p not in self.allow_set` 精确匹配）+ `:288-296::_bad_allow`（拒绝 glob）对照 `tools/pool/review.py:24::outside_allow`（自称唯一实现，支持 glob）与 `tools/tf_stage_guard.py:33`
- 现象：卡 106 把 wb_review/wb_dispatch 都收编到 pool.review.outside_allow，但 tf_commit（真正的提交路径）没用它，自己内联了一套语义相反的（禁 glob、纯精确匹配）；tf_stage_guard 建成后 grep 全仓只有测试引用，自动化链路（tf_commit/run_gates/wb_land）谁也不调它。
- 复现：`grep -rn tf_stage_guard tools/ scripts/`（仅测试与文档）；读 tf_commit.py:261 与 :291。
- 真因：去重只收编了「名义上的副本」，提交主路径里的内联判据不在收编清单。
- 归位：`tools/tf_commit.py::step6`。
- 严重度：中 —— 两处白名单语义分叉（一个支持 glob 一个见 glob 退 2），哪天改判据只改一边，越界就漏了。
- 修法：tf_commit.step6 改调 pool.review.outside_allow，删掉 _bad_allow 里的私有口径。

### D-38 `check_layers` 覆盖矩阵硬编 `range(1, 11)`，新增域静默漏检；编号闭合只查单向（方向①④）
- 出处：`scripts/check_layers.py:229-238::main` + `:160-168`
- 现象：① 域数「10」是手打真源 —— 明天加 `F11-*.md`，覆盖矩阵检查不会要求 coverage.md 出现 SR-F11，也不会发现 domains 目录里多了个域（没有反向枚举）；② `missing_sr = spec_srs - impl_srs` 只查「spec 有、impl 没引」，impl 追踪表引用了不存在的 SR（笔误 SR-F99）不红；N 同理。
- 复现：读 `check_layers.py:229-238`、`:160-168`；`ls docs/specification/domains/` 现为 F1-F10。
- 真因：判据按「今天的枚举」写死，集合差只算一个方向 —— 与坑总账已收录的单向判据同族，是又一例。
- 归位：`scripts/check_layers.py::main`。
- 严重度：中 —— 文档体系扩域时护栏自动失明；impl 表里的断编号永远没人发现。
- 修法：域集合改为从 domains/ 目录现算；补 `impl_srs - spec_srs`、`spec_n_refs - n_ids` 两个反向差集。

### D-39 `seam_check` 交集只按符号名、不看路径 —— 不同文件的同名符号报假交集（方向③）
- 出处：`tools/seam_check.py:314-324::find_common`
- 现象：Symbol 明明带 path，交集却只用 s.name 做键。两张卡各自在不同文件加了 `def main(...)`（tools/scripts 下每加一个 CLI 就有一个）、或动了同名形参（name/conn/db 这类高频词），即报「★ 交集 → 必须串行」。
- 复现：读 `seam_check.py:78-83`（Symbol 含 path）与 `:314-324`（键只有 name）。
- 真因：交集粒度从「（符号，文件）」退化成「符号」；path 采了不用。
- 归位：`tools/seam_check.py::find_common`（坑总账「seam_check 把注释字符串当符号 · 半关」的同族另一半）。
- 严重度：中 —— 并行度被假交集毒化：要么白等串行，要么主控学会无视这条输出（更坏）。
- 修法：交集键改成 `(s.name, s.path)`，或对 def 类符号要求同路径才算接缝。

### D-40 「只用相对路径」是君子协定：工人用绝对路径写出卡树外，域检查与复核都看不见（方向②⑥）
- 出处：`复盘/外包-卡表与规矩.md` §18.4.2（自认「worktree 隔离只是君子协定…工人用绝对路径能写到自己树外面（撞过两次）」）+ `tools/wb_review.py:443`（actual 只取卡树 git status）
- 现象：CLI 的 trustedDirectories 覆盖整个仓库，工人以绝对路径能写主树或别树的文件；而 ⑥ 档域检查的「实际改动」只取卡树 diff，收口链也只按白名单从卡树拷文件 —— 写在树外的东西不进任何判据，只能等谁偶然在主树跑 `git status` 才发现。
- 复现：读 `tools/wb_review.py:440-466`（actual 数据来源）与规矩文档 §18.4.2。
- 真因：写权限面（trustedDirectories 整仓）比判据面（卡树 diff）大；两者之间没有机器对账（比如派活前后主树快照对比）。
- 归位：`tools/wb_review.py::run_card_mode`（或派活器收尾加一道主树脏检）。
- 严重度：中 —— 越界写的活不进卡、不进复核，静默留在主树工作区污染下一笔。
- 修法：派活/收口时在主树跑 `git status --porcelain` 快照对比，出现非预期改动即拒并点名。

---

## 低（11 条）

### D-41 「这轮跑完没有」有三份判据，取的不是同一个 result 事件、认的不是同一组字段（方向⑤③）
- 出处：`tools/wb_dispatch.py:1394-1423::finish_verdict`（正向扫留最后一条；不查 is_error）+ `:919-932::round_is_normal_success`（反向扫取最后一条；查 is_error，但谓词是 subtype != error_during_execution）+ `:884-916::quota_error`（正向扫命中即返第一条）
- 现象：同一份 log 出现多个 result 事件时，三个判据读的不是同一条；且 finish_verdict 不认 is_error：`subtype=success` + `is_error=true` + 非空回话 ⇒ finish_verdict 说跑完了，round_is_normal_success 说不是。
- 复现：读 `wb_dispatch.py:1405-1423`（无 is_error）、`:921-932`（有）、`:884-898`。
- 真因：三条判据各自长出来的（T-G89 / 卡 045 ×2），没收敛成一个公共函数。
- 归位：`tools/wb_dispatch.py::finish_verdict`。
- 严重度：低 —— 多 result 或 success+is_error 形态出现时，判决/额度/续跑三路各说各话。（CLI 会不会给子代理发多个 result，查不出来。）
- 修法：抽 `last_result_event(lines)` 统一取最后一条，finish_verdict 补 is_error 判据。

### D-42 MCP 写工具的 `confirm` 是「知道卡号就能过」的自报仪式；`pool_cancel` 不核租约归属（方向④）
- 出处：`tools/pool_mcp.py:1496-1502::call_tool` + `:1125-1174::tool_pool_cancel`
- 现象：confirm 的值就是调用方照抄的卡号，判据只比相等；pool_cancel 只核「登记里有活租约 + pid 映像」，任何持 POOL_MCP_WRITE=1 的窗口都能杀任何卡的工人。核实结论：这是按设计（防手滑不防恶意，stdio 单客户端无身份概念），但 INV-07 的 note 没把「不核归属」这句边界写破。
- 复现：读 `pool_mcp.py:1496-1502`、`:1136-1153`。
- 真因：设计口径 = 防手滑；边界没写破就会被当成「有授权」。
- 归位：`复盘/不变量台账.toml` INV-07 note（补一句边界）。
- 严重度：低 —— 一个拿到写面的窗口误杀/恶杀另一窗口的卡，目前靠「只有用户能开 POOL_MCP_WRITE」兜着。
- 修法：INV-07 note 补「confirm 不核租约归属，防手滑不防越权」。

### D-43 `wb_brief` 白名单提取：取「最后一个」白名单标题 + 兜底正则几乎恒真 ⇒ 小节改名后静默降级、不停工（方向④）
- 出处：`tools/wb_brief.py:292-299::section_whitelist` + `:270-273::SCOPE_PATH_RE`
- 现象：① 多个标题含「白名单」时取最后一个 —— 卡规格末尾若有样张/附录/引用他卡的白名单小节，工人拿到错的白名单而非没有；② 小节改名后走 SCOPE_PATH_RE 兜底，它匹配任何 `a/b` 或 `x.py` 形状的串，一份正常卡规格几乎必中 ⇒ 输出「范围以规格里逐一点名的文件为准」温和放行而不是停工。（有设计理由：卡 112 那套「逐文件点名 + 禁区」规格不该印停工话，卡 108/109/110 三次被骗；但失败路径因此几乎不可达。）
- 复现：读 `wb_brief.py:276-299`；推一份无白名单/禁区标题但正文提到 `tools/x.py` 的规格走一遍分支。
- 真因：「找不到范围声明」的判据被过宽的兜底正则吃掉。
- 归位：`tools/wb_brief.py::section_whitelist`（这是第 5 份「白名单真源」：工人实际照它干活的那份）。
- 严重度：低-中 —— 不直接放行越界（收口侧还有域判据），但让「域」在工人端与收口端静默分叉。
- 修法：兜底分支加一行醒目提示「未找到白名单/禁区小节」并要求工人回话里显式列出自己认定的范围；多命中时取第一个并报警告。

### D-44 `--read-only` 只调回合预算，没有任何写保护 —— 「R 只读复核不许写任何文件」无机器判据（方向②）
- 出处：`tools/wb_dispatch.py:1138-1140::max_turns_default` + `:2193`（read_only 唯一的消费点）
- 现象：`--read-only` 在派活器里唯一的用处是把 max-turns 默认改成 80；工人 CLI 照常 bypassPermissions 起，能写、能提交。协议 10.4 表已诚实写「（预算，不是安全边界）」，但 10.1 角色表与 INV 叙事把「只读」当硬约束讲 —— 本卡（153）自己就是实证：一张只读审核卡，不写报告文件之外的东西全靠自觉。
- 复现：`grep -n read_only tools/wb_dispatch.py`（仅 3 处，全是 max_turns）。
- 真因：CLI 侧没有只读权限模式可映射（或没接）；判据只能落在事后（复核卡树必须干净）。
- 归位：`tools/wb_dispatch.py::main`（或收口侧加「只读卡的树必须零改动」判据）。
- 严重度：低 —— 协议一处写了实话、另一处给人硬约束的错觉；真要靠它防的事（R 卡改证据）防不住。
- 修法：只读卡收口/复核时断言其卡树 `git status` 为空、无新提交，违反即拒收其结论。

### D-45 「每张作者卡先派 R 卡再谈收口」（协议 10.6）与「对抗复核默认提交后异步、不挡」（规矩 §25.1）两处口径并存，且都没有机器判据（方向②⑤）
- 出处：`复盘/长任务执行协议.md` §10.6 对照 `复盘/外包-卡表与规矩.md` §25.1
- 现象：10.6 写「只读复核是强制的…先派一张 R 卡再谈收口」；§25.1（2026-10-02，T-G242）写「对抗复核默认在提交之后跑…不挡收口、不进放行判据」。两份必读文书对「复核何时发生、挡不挡」各说各话；落地侧 landing/task 都不检查有没有 R 卡 —— 哪条都不会红。
- 复现：读两节原文；`grep -n 'R-' tools/pool/landing.py`（无命中）。
- 真因：§25 改口径时没有按铁律 34 全文搜改 10.6；两段话都只有人话。
- 归位：`复盘/长任务执行协议.md` §10.6（仲裁或合并口径）。
- 严重度：低 —— 新窗口照 10.6 办事会空等 R 卡，照 §25.1 办事会跳过复核；实践中 R 卡已没人派。
- 修法：按铁律 34 仲裁一处为准并互相指向；要不要机器判据（落地前必须有 R 卡记录）由主控定。

### D-46 `WORKBUDDY_ITEMS` 是手工维护的封闭清单，没有「家目录出现清单外身份新件」的对账判据（方向②）
- 出处：`D:/repo\infra\pool\codebuddy_accounts.py:60-69`
- 现象：21 件清单照 2026-09-28 那份手工快照逐条对齐；头注自己写「少存一件就可能切不回来」。CLI 升级新增任何身份文件，save/use 都静默不存它 —— 没有任何代码对比「家目录实际文件 vs 清单」。
- 复现：读 `codebuddy_accounts.py:60-69`（清单与头注）；对照 `ls C:/Users/example\.workbuddy`（此刻一致纯属巧合）。
- 真因：风险写在注释里，机器判据一条没有。
- 归位：`codebuddy_accounts.py::_targets`。
- 严重度：低-中 —— 某天 CLI 升级后切号静默失效，save 照跑、日志照绿，会归到「登录为什么短命」堆里误查。
- 修法：save 时列出「家目录里存在但不在清单里的顶层件」作为警告（不自动存，只报告待批）。

### D-47 `profile check --run` 的 300 秒超时是未捕获异常 ⇒ 探测超时直接 traceback，走不到任何分支（方向③）
- 出处：`D:/repo\infra\pool\codebuddy_accounts.py:375-377::cmd_profile_check`
- 现象：`subprocess.run(…, timeout=300)` 没有 try/except —— 超时抛 TimeoutExpired，脚本以 traceback 死掉。（卡 155 已立项修 `duration_ms` 假绿与三态，不重复报；但三态设计假定代码走得到 `?` 分支，当前超时路径根本走不到任何分支。）
- 复现：读 `codebuddy_accounts.py:371-389`，无 try/except。
- 真因：超时参数加了，异常没兜。
- 归位：`codebuddy_accounts.py::cmd_profile_check`（卡 155 落地时一并兜）。
- 严重度：低-中 —— 卡 155 修完判据后，超时仍是 traceback 而不是「没能得出结论」，三态缺一角。
- 修法：`except subprocess.TimeoutExpired` 归入「没能得出结论」态。

### D-48 `login-classmate.cmd` 与 `profile run` 是同一 profile 的两套入口，环境变量集不一致（3 项 vs 6 项）且硬编码 node 版本路径（方向⑤）
- 出处：`D:/repo\infra\pool\login-classmate.cmd:5-7,20` 对照 `codebuddy_accounts.py:249-252::PROFILE_ENV_KEYS` 与 `:273-279::_find_node`
- 现象：.cmd 只设 USERPROFILE/HOME/TF_CODEBUDDY_PROFILE 三项；profile run 设六项（多 APPDATA/LOCALAPPDATA/WORKBUDDY_CONFIG_DIR/CODEBUDDY_CONFIG_DIR）。同一个 profile 两种起法环境不同 ⇒ CLI 哪天开始读 CONFIG_DIR，两条路会把状态写到两个位置，登录态分裂。② .cmd 硬编码 node 22.22.2-3 路径，_find_node 是自动取最新 —— node 一升级 .cmd 就哑。
- 复现：读 login-classmate.cmd 全文（23 行）对照 codebuddy_accounts.py:249-279。
- 真因：.cmd 是手工探路的固化产物，profile run 是后来的工具化；两条路没有归并。
- 归位：`login-classmate.cmd`。
- 严重度：低 —— 短期恰好够用，但这是又一处「两份真源、谁也不从谁派生」。
- 修法：.cmd 改成一行调 `codebuddy_accounts.py profile run tongxue3`。

### D-49 `tests/conftest.py` 用 `setdefault` 设保护变量 —— 外部环境已设时防护静默失效（方向③⑥）
- 出处：`tests/conftest.py:32`（TIMEFLOW_EXPORT__DIR）+ `:36-38`（TF_LOG_PATH）
- 现象：这个文件的存在意义是「测试不许写真 export/」。setdefault 意味着：若 shell 里已 export 同名变量指向真实目录（用户排查问题时完全可能），测试进程沿用外部值 —— 跑一遍 pytest 就用临时库数据覆盖当天真实 md，防护在最需要它的场景静默关闭。
- 复现：读 `tests/conftest.py:30-38`（两个 setdefault）。
- 真因：把「给默认值」误用成「强制覆盖」；防护型变量不该尊重外部环境。
- 归位：`tests/conftest.py`。
- 严重度：低-中 —— 触发条件窄，但一旦触发就是冲掉真实数据，正是本文件要防的事故。
- 修法：改成直接赋值（测试进程内无条件隔离）。

### D-50 `check_toml.toml_files()` 用 `str.split()` 拆 ls-files 输出 —— 带空格路径会把预检打崩（方向③）
- 出处：`scripts/check_toml.py:50::toml_files`
- 现象：`git ls-files` 按行出路径，这里用 `.split()`（任意空白切分）。第一笔带空格的 TOML 提交（如 `docs/my config.toml`）会被劈成两段，`check_one()` 对不存在的路径 read_text 抛 FileNotFoundError 原始栈 —— 这个脚本的存在目的恰恰是「别让用户看原始栈」。当前仓无带空格 TOML（已实测），属潜伏。
- 复现：读 `check_toml.py:45-50`；对照同仓 `tf_commit.py:300` 与 `pin_check.py:87-92` 已用 `-z` + `\0` 拆。
- 真因：按词拆分代替按行/NUL 拆分。
- 归位：`scripts/check_toml.py::toml_files`。
- 严重度：低 —— 第一笔带空格的 TOML 提交会让门禁预检以 traceback 红。
- 修法：ls-files 加 `-z`，按 `\0` 拆。

### D-51 `last.json` 的 `parent` 字段与 `rev` 同为 HEAD —— 名不副实的假字段（方向③）
- 出处：`scripts/run_gates.py:1663-1665`
- 现象：字段名叫 parent，值却是 HEAD 自己（父提交应为 `HEAD^`），与 rev 那行一模一样。任何将来按字面消费 `payload['parent']` 的复核逻辑都会拿到错数据。
- 复现：读 `scripts/run_gates.py:1663-1665`。
- 真因：写字段时复制了上一行，没人消费所以从没炸过。
- 归位：`scripts/run_gates.py::main`（payload 组装）。
- 严重度：低 —— 现在无消费者，是一颗等消费的雷。
- 修法：删掉该字段，或改成 `HEAD^` 并在复核侧对账。

---

## 附：查过但确认没问题的方向（免得便宜工人重查）

1. **`--quick`/`--fast`/`--affected` 冒充全量**：冒充不了。`--quick` 只有 13 道门，wb_review 用 `build_jobs(False,False)` 现读 15 道比数；`--fast` 不落盘；`--affected` 必留 affected 块且 wb_review 见块即判红（`wb_review.py:181-191`）。
2. **NOT RUN 门蒙混**：蒙混不了。not_run 条目 exit_code=3，复核侧 `check_gate_evidence` 会点名（`wb_review.py:146-148`）。
3. **锁文件跨树**：没问题。`gate_lock.main_root()` 走 `git rev-parse --git-common-dir`，锁固定在主仓 `gates/diag/`，所有 worktree 共享同一把；并发名额不超卖（`gate_lock.py:227-294`）。
4. **seal 对红门禁**：拦得住（`run_gates.py:769-771`，ok 非真拒封）。
5. **`gate_cmd` 的 shell 元字符那半**：确已关（`;|&$\`><换行` 全挡 + shlex + shell=False + 引号不成对报错，task.py:338-348）—— 漏的只有 `..`（D-07）。
6. **evidence_map / wb_impact 口径**：都现读唯一真源（前者 import audit_progress.eval_assertion，后者现读 run_gates.DOOR_INPUTS），无第二份。
7. **projects.toml vs 主仓 tools/pool/projects.py**：不是两份真源 —— projects.py 读的就是 infra/pool/projects.toml（投影不是复制）。缺的是 D-13/D-19 的接线。
8. **`_maybe_advance` 计数判据**：claims 的键被 cmd_claim 限制在 declared 名单内，`len(got) < need` 与「每张都交」等价 —— 不是数量冒充名单（task.py:742-776, 588-592）。
9. **registry 死租约判据**：TTL 与日志判死双通道，坚决不用 pid 判活（registry.py:192-198，注释即理由，Windows 上 os.kill(pid,0) 是真杀）—— 方向正确；缺的是 TOCTOU（D-10）。
10. **MCP 写工具存在性即授权**：没 env 时调用方得到 -32602，不存在「没 env 也能调」的缝（pool_mcp.py:1496-1505）；`pool_dispatch` 不透传危险项（无 --force/--allow/--resume/--no-preflight，:940-952）。
11. **429 三拍与「退出码 0 ≠ 跑完」闭环**：候选闸门 + 结构化字段优先 + 探针优先 + 续跑共享 --retry 封顶都在（wb_dispatch.py:894-898, 1577, 2382, 2400-2468）。
12. **plan.py 通配禁写**：队列侧 files 含 `*?[` 直接拒单（plan.py:253-257）—— 与坑总账「已关」一致。
13. **`spin_lock` 陈旧接管 / `resolve_derived_conflicts` 白名单 / stage_card 写后自检**：方向都对（task.py:242-291；landing.py:84-86；stage_card.py:97-137）。
14. **`--commit-only` 跳过①~⑤**：trailer 如实写「复用已绿的那一趟」，wb_review 的 ⓖ 能识别披露形态并留痕 —— 被看住的跳步（landing.py:343-344；wb_review.py:300-302）。
15. **audit_progress verdict 边界 / registered_actions 无界扫描 / sync_counts 与 audit 的匹配数差异**：逐一核过，均注释明说的有意口径或当前零假阳性，不单列。
16. **pin_check 脱钉问题**：被钉文件改名/删除会被 audit_progress 的 `text:` 文件不存在咬住，不构成静默脱钉；未接门禁是其 docstring 明说的现状。
17. **号池仓 .gitignore**：实证兜住了凭证与证据（logs/、models.live.json、*.env、credentials*.csv 全 `!!`）；rotate_credentials 失败方向全部保守（自检失败自动回滚 + 全程掩码）。
18. **infra dispatch.py --resume 不盖第一轮日志**：日志名带秒级时间戳 + 前置挡覆盖（dispatch.py:120）—— 主仓 wb_dispatch「--resume 盖第一轮证据 · 没关」在这条线上不存在。

**查不出来（如实写）**：① codearts CLI 报错行的确切格式（D-30① 的触发依赖服务端错误文本形状，只能确认「stderr 被拼进解析输入」这个代码事实）；② CLI 会不会给子代理发多个 result 事件（D-41 的触发前提）；③ `codearts models` 是否真走认证（rotate 自检有效性依赖这一点，不发请求核不了）；④ 主仓 `tools/pool/landing.py` 的 T-G250 ⓪ 回退在本卡树不存在（卡树 HEAD 早于 a042725），主树实现已评估：三种形态都有分支、回退清单只含派生物，两个小缺口（上一趟别的 task 号残留片段喂给 INV-15 反向缺失；`--no-reset` 是第三个跳步开关、复核侧无字段可感知）记入此条备查。

统计：51 条（高 15 / 中 25 / 低 11）
