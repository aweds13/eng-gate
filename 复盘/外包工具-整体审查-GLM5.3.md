# 外包工具整体审查（GLM-5.3 · 卡 124 / T-G222）

> 审查对象：号池 / 派活 / 门禁 / 审计 / 收批栅栏 / MCP 面的**框架设计与代码实现**。
> 基线：本树 base `ca64283`；主树 scratch（`gates/diag/_integrate.py`）按索引指针读的主树版本。
> 方法：按 `复盘/外包审查-索引.md` 的 8 条审查者路线走；未跑门禁/测试（卡规定不跑），
> 仅做了两个**只读状态机探针**（临时目录内，随 TemporaryDirectory 清理，读数见 §2-5）。

## 一、结论摘要

1. **【重】默认派活器 `wb_dispatch.py` 完全没接守卫与登记**——需求文档宣称的"派活前守卫干跑（树/域/锁/内存/日志）"只在 MCP 写面和手工 CLI 两条路径成立；走默认 CLI 派活 = 不变量 ①②③⑤ 全部失效，且对其他窗口不可见。
2. **【重】"一张卡的域"有四份互不派生的声明、两套匹配语义**（backlog 精确路径 / 栅栏 fnmatch 通配 / 卡规格散文 / 集成 `--allow` 手打），无任何机器判据要求一致；栅栏还不知道 `PROTECTED_FILES` 的存在。
3. **【重】收批栅栏的锁是一次性自旋锁（无陈旧恢复）且持锁跑门禁**——进程崩溃一次，该任务**永久**拒收后续申请，直到人手工删锁文件；模块头"锁只是省掉白等"的安全声明在崩溃场景不成立。
4. **【中】集成器把 `Gates: 全量门禁绿 + seal` 写死进提交信息**，`--no-gate` 模式下这行是工具自己在伪造门禁结论（违反铁律 4 的机器内嵌版）。
5. 总体判断：**方向是对的**——台账证据逐条求值（`audit_progress.py:154`）、封存指纹固定点口径（`run_gates.py:540-610`）、模型默认拒绝（`wb_dispatch.py:231`）、栅栏五条安全阀的钉子（`tests/test_pool_task.py:40-74`）都是**真会咬的判据**；问题集中在**接线与真源收敛**，不在判据本身。

## 二、逐条发现（按严重度降序）

### 2.1【重】CLI 派活路径绕过全部派活守卫与登记
- **是什么**：`复盘/外包工具-需求与架构.md:106`（§2.3 数据流 1）写"派活：……守卫干跑（树/域/锁/内存/日志/模型）→ 占树"；§4 不变量表把 ①②③⑤ 指给 `tools/pool/guards.py`。实际：`tools/wb_dispatch.py` 全文 **0 处** import guards/registry（grep 证实）；守卫与租约只在 `tools/pool_mcp.py:1048-1052`（MCP 写面）与 `tools/wb_registry.py:106-108`（手工 CLI）接线。
- **为什么是问题**：`wb_dispatch.py --execute` 是文档自认的"本项目默认派活器"（§2.2 组件清单、卡表 §10 模板）。它不写 `pool-registry.json` ⇒ 另一窗口哪怕走 MCP 正规干跑也**看不见**这个活 ⇒ 一树两写者、同文件两写者都不会被咬。卡 100/102 工人跑进主树（口径坑 20）正是"没人知道谁占了哪棵树"这一类事件。
- **建议方向**：把 `registry.reserve/release` 接进 `wb_dispatch` 的 preflight/收尾（或至少 reserve 一次），让"派活"与"占树"在**所有**入口合一。

### 2.2【重】"域"四份声明、两套语义、无一致性判据
- **是什么**：同一概念四处声明：backlog `files`（**精确路径**，`plan.py:147 files_intersect` 按字符串交集、实测 `docs/workbacklog.toml` 全是精确路径）；栅栏 manifest `paths`（**fnmatch 通配**，`task.py:327 check_domain`）；卡规格白名单（散文）；集成 `--allow`（主控手打，`_integrate.py:212-236` 与 staged 精确比对）。没有任何一处从另一处派生，也没有判据要求一致。
- **具体可咬的缝**：
  a) 栅栏 `check_domain` **不知道 `PROTECTED_FILES`**（`plan.py:34`）——manifest 成员写 `paths = ["docs/traceability.toml"]` 照样注册成功、claim 照样收；"受保护共享文件"不变量在收批通道**没有实现**。
  b) `files_intersect` 是精确匹配 ⇒ backlog 里若有人写 `tools/pool/*.py` 这类通配，它与**任何**精确路径都不相交（validate 无"禁通配"检查）＝静默绕过域检查；栅栏侧 fnmatch 的 `*` 又**跨目录分隔符**（`tools/a/*` 匹配 `tools/a/b/c.py`），比 backlog 语义宽。
- **为什么是问题**：每道闸单独都绿，实际域取决于最后一道闸（集成 `--allow`）是谁手打的；四份声明漂移时没有任何机器信号。
- **建议方向**：定一份**权威域**（backlog 或 manifest 二选一），其余从它派生；栅栏 `check_domain` 补 `PROTECTED_FILES` 拒收；backlog validate 补"files 禁通配"。

### 2.3【重】栅栏 spin_lock 无陈旧恢复 + 持锁跑门禁 + MCP 进程内执行
- **是什么**：`task.py:165-192 spin_lock` 用 `O_CREAT|O_EXCL`，10 秒超时，**没有任何陈旧判定/接管**——持有进程一死，`<任务>.json.lock` 永留，此后所有 claim/waive/advance/expire/landed 全部 rc=2"拿不到任务锁"，**直到人手工删锁文件**。而 `task.py:347 cmd_claim` 在**锁内**跑 `_maybe_advance → _run_auto → subprocess.run(gate_cmd, shell=True)`（全量门禁 ≈5-6 分钟；坑 15 实测 `ui_flow` 卡死过 56 分钟）——持锁窗口被放大到门禁时长。
- **放大器**：`pool_mcp.py:1289` 的 `_capture` **进程内**调 `cmd_claim` ⇒ 最后一名 claimant 走 MCP 时，**MCP 服务进程**同步跑完整个门禁：stdio 循环全程冻结（九个只读工具也答不了）；服务中途被杀 ⇒ 锁泄漏 + 状态没落盘。
- **为什么是问题**：模块头（`task.py:43-44`）声称"丢一次投递只会让任务多等（安全方向），锁只是省掉白等"——**在崩溃场景这句话是假的**：不是多等，是永久卡死。这正是 gate_lock 从 pid 判活进化到租约（铁律 25/29）的同族教训，task.py 没吃到。
- **建议方向**：锁改租约制（mtime+ttl 判陈旧，参考 `gate_lock.py`）；`_run_auto` 的门禁移出锁外（状态先落 `gating` 再跑）；MCP 侧改子进程调用。

### 2.4【中】集成器的 Gates trailer 是写死的真话声明
- **是什么**：`gates/diag/_integrate.py:257` 提交信息模板**无条件**写 `"Gates: 全量门禁绿 + seal"`；而同脚本有 `--no-gate`（跳过 ④⑤）与 `--commit-only`（跳过 ①~⑤）两个模式。
- **为什么是问题**：`--no-gate` 路径产出的提交自带一条**假的门禁结论**——这是"不许伪造完成"（铁律 4）被工具自己内嵌违反。`audit_progress` 只查 trailer 存在性；rev 对账（`wb_review`）只在复核时才做，且 `--commit-only` 复用旧 `last.json` 时 rev 恰好可能对得上。
- **建议方向**：trailer 按 ④ 的实际退出码拼接；`--no-gate` 时写"未跑门禁（--no-gate）"。

### 2.5【中】`advance` 能复活 landed、抹掉 timeout（已实测复现）
- **是什么**：`task.py:647 cmd_advance` 对非 awaiting-commit 状态一律 `state="collecting"` 再 `_maybe_advance`。本卡临时目录实测（探针，只读仓库外）：对 **landed** 任务跑 `advance` → 状态变回 `awaiting-commit`（`landed` 字段还挂着 commit 哈希，自相矛盾）；对 **timeout** 任务跑 `advance` → timeout 被抹成 `collecting`（rc=0）。
- **为什么是问题**：安全阀 5"过期只判死、放行要人显式 waive/extend"被 `advance` 绕开；已落地任务可被"再放行"一次（重跑 gate_cmd、重写 draft）。配套问题：`cmd_expire`（`task.py:653`）**不校验 deadline 是否真的到了**——任何人任何时候跑 `expire` 都判死。
- **建议方向**：`advance` 对 landed/timeout 拒绝（提示用 `extend`）；`expire` 校验 `now > deadline`。

### 2.6【中】gate_cmd = 任意 shell，且注册面开在 MCP 写面上
- **是什么**：`task.py:494` 以 `shell=True` 执行 manifest 里的 `gate_cmd`；`pool_mcp.py:1184 task_register`（写面）接受 `manifest_text` 整段 TOML。⇒ `POOL_MCP_WRITE=1` 的**任何** MCP 客户端可注册带任意命令的任务并在集齐时触发执行。"收口只有主控"（号池MCP 设计 §三）靠的是 env 存在性，**不是调用者身份**。
- **同族事实**：模型白名单闸门只拦 `--model` 参数（`wb_dispatch.py:1829`），不经派活器直接起 CLI 的路径没有闸。**本卡即活证据**：本树代码里 `MODEL_WHITELIST = ("deepseek-v4.1-flash", "glm-5.3-flash")`（`wb_dispatch.py:115`），`--model glm-5.3` 会被拒（rc=2）；而本卡确以 glm-5.3 在跑 ⇒ 派活走了某条不经这道闸的路径（或主树名单已改而本卡树未见）。
- **建议方向**：gate_cmd 白名单化（只认仓库内脚本路径）；或 task_register 的 manifest 校验"gate_cmd 必须以 `python -X utf8 scripts/` 开头"。

### 2.7【中】两个模型白名单已经实际发散（评估已知边界：比文档写的更重）
- **是什么**：`wb_dispatch.py:115`（deepseek-v4.1-flash / glm-5.3-flash，**裸名**）与 `infra/pool/models.whitelist.toml`（只有 `huaweicloud-maas/GLM-5.2`，**provider/model 形式**；且其中注明 `glm-5.3-flash`、`deepseek-v4.1-flash` 在码道侧**服务端不可用**）。
- **为什么比"将来会漂"重**：两份名单连 **id 体系**都不同（裸名 vs provider/model），`glm-5.3-flash` 在一份里是替补、在另一份里是"已探明不可用"；`pool_models` MCP 工具读的是 infra 那份，派活闸门读的是本仓这份——同一个问题"现在能用什么模型"两个工具会给出**不同答案**，且没有对账判据。

### 2.8【中】changelog 次序翻转（坑 32）会在自动解决路径里**自动重演**
- **是什么**：`_integrate.py:45-74 resolve_derived_conflicts` 对共享文档冲突取 `--ours`（基线）再跑 `sync_docs.py` 重汇总；而 `tools/sync_docs.py:58 _merge_changelog` 的口径是"新片段按新→旧接在**文件头**"。rebase 场景里基线已含对方（日期更新）的那节，本笔（日期更老）的片段再插到文件头 ⇒ **老日期排在新日期上面**，坑 32 原样重演——但这次是**自动**的，且 `sync_docs --check` 不查次序（坑 32 自己承认"这条缝没人守"）。
- **为什么是问题**：以前只有"主控手工并行提交两笔日期不同的卡"才触发；自动解决让它在每次撞上派生物冲突的并行落地里批量发生。

### 2.9【轻】`--max-turns` 帮助文本与常量漂移
`wb_dispatch.py:1785-1787` 帮助写"写卡 150 / 只读卡 60"，常量是 240/80（`:147-148`）。按帮助文本估预算会低估 60%。

### 2.10【轻】`_integrate.py` ROOT 硬编码
`_integrate.py:26` `ROOT = pathlib.Path(r"D:/repo/engineering")`——换机器即碎（错配 ③ 的实例；收口工具进 git 前必须改）。

### 2.11【轻】`find_spec` 第三档模糊匹配潜伏串卡
`plan.py:372-377`：前两档 miss 后用 `*{card}*.md`，卡号 `12` 会命中 `卡112-*.md` / `卡120-*.md`（按字母序取先）。当前未咬（卡号还没到三位混用），是潜伏而非现实缺陷。

### 2.12【轻】`selftest()` 结束不复原 TF_BATCH_DIR
`task.py:847-1010`：selftest 把 `TF_BATCH_DIR` 指进临时目录，结尾不复原——同进程内后续调用 `batch_dir()` 会拿到已删除路径。CLI 一次性进程里无害。

## 三、判据漏洞专项（"看着绿其实没查"）

1. **最狠的一条：栅栏域检查吃的是自报清单**。`cmd_claim` 的 `--files` 由**交申请的一方自己填**，`check_domain`（`task.py:327`）只对这份自报清单做 fnmatch。**没有任何一处**拿"卡树里实际改了什么（`git status`/`diff`）"与域比对——真实越界只要不自报就全绿。最终兜底只剩集成时主控手打的 `--allow`（2.1/2.2 联手把它弱化）。
2. **Gates trailer 真伪无机器判据**：`audit_progress` 查 trailer 存在性，不查真伪；`--no-gate` 模式下工具自己写假话（2.4）。
3. **deadline 是装饰性的**：状态机图（需求 §2.4）画"到 deadline ⇒ timeout"，实现里 deadline 字段**没有任何自动触发**——要有人跑 `expire`，而 `expire` 又不校验是否真的到期（2.5）。过了期限的任务若无人工介入，会**无限期继续收申请**——与"过期判死"的方向正好相反。
4. **backlog 无"禁通配"校验**：`files` 里写通配的卡与任何人都不相交（2.2b），现在没人这么写，但判据不咬。
5. **已知边界的确认**（非新发现）：复用通过 ≠ 本轮真跑（坑 11）、看门狗只抓完全一样的重复（§5.7）、`sync_docs --check` 单向（坑 30/32）——复验代码属实。

## 四、与需求不符专项

| 需求原文 | 实现现状 | 判据 |
|---|---|---|
| §2.3 数据流 1"派活：守卫干跑→占树" | 默认派活器无守卫无登记 | 见 2.1 |
| §2.4"(到 deadline)→ timeout" | 无自动触发；`expire` 不校验到期 | 见 2.5 / 三.3 |
| §4 不变量 ①②③⑤ 的判据在 guards.py | guards 只在 MCP 与手工 CLI 接线 | 见 2.1 |
| §4 安全阀"逐卡域越界拒收（最重要）" | 只查自报清单；不知 PROTECTED_FILES | 见 2.2 / 三.1 |
| §1.3"收口者=主控（唯一写者）" | 靠 POOL_MCP_WRITE 存在性 + 纪律，无调用者身份判据 | 见 2.6 |
| §1.2 ④ projects.toml"已写未接线" | 已自我声明（不算新发现）；**评估**：它使"树必须在 `.wt/` 里"仍是君子协定——树可以建在任何地方，栅栏/派活都不会拒 | `pool_dispatch` 无 tree_prefixes 检查 |

## 五、排序建议（只做三件事）

1. **把守卫+登记接进 `wb_dispatch`**（治 2.1）：一处改动同时封住不变量 ①②③⑤ 的默认路径缺口——这是四份域声明里**唯一每天真的在跑的入口**，也是"两个窗口互不见"这类事故的根。
2. **域声明收敛成一份派生链**（治 2.2 + 三.1）：集成 `--allow` 从 manifest/backlog 派生、栅栏补 `PROTECTED_FILES`、backlog 补禁通配——让"越界"重新变成机器可判，而不是自报+手打的接力。
3. **task.py 锁改租约 + 门禁移出锁外 + MCP 改子进程**（治 2.3）：不修的话，一次崩溃（或一次 56 分钟的门禁卡死）= 一个任务永久卡死，而且死因在锁文件里**看不出来**（没有"谁在什么时候拿的锁"之外的租约信息）。

## 六、我没 能验证的（如实写）

- **没跑**任何门禁、pytest、audit（卡规定不跑）。只跑了两个**只读状态机探针**（`task.main` 在临时目录里 replay `advance`-on-landed / on-timeout，读数已附 2.5；目录已随 TemporaryDirectory 清理）。
- **没读全文**的：`tools/sync_docs.py`（只读了合并函数的 docstring 与签名，2.8 的结论建立在 `_merge_changelog` 自述"接在文件头"上）、`tools/pool/jobs.py`、`tools/pool/review.py`、`tools/wb_brief.py`、`tools/trae_pool.mjs`、`gates/diag/_stage_card.py`、`tools/wb_status.py`。这些不在我判断链上的证据只有索引转述。
- **没验证**主树真实 `gates/diag/batch/` 里是否存在受 2.3/2.5 影响的现存任务（没碰主树）。
- **没验证** `wb_dispatch` 看门狗/续跑的**运行时**行为（`run_worker` 内部未逐行读）——判决口径四件（`heartbeat_stall_alert`/`quota_error`/`round_is_normal_success`/`kill_tree`）我给的是函数级证据，不是运行读数。
- 2.6 里"本卡以 glm-5.3 在跑"的推断链有一处不确定：主树 `MODEL_WHITELIST` 可能已在本树 base（`ca64283`）之后更新——我**没有**读主树的 `wb_dispatch.py` 现行版（不碰主树），只读了本树版本。
