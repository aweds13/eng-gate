# DSH 插件定点深读·第二批（证据台账 / 对账与墓碑）

> 卡 252（T-G373）。读**源码**不读简介；每条结论带 `文件:行号` + 原样片段。
> 两仓版本（codeload tar.gz 抓取；git clone 直连 github.com 被重置，按卡规格退 tar.gz）：`dsh-research-report` = **8d00f06**，`dsh-session-enhance` = **f7eb9a0**（codeload tar 包**无 `.git`**，sha 取自 GitHub API `commits/main` 的 `sha` 字段短前 7 位，对应本次 tarball 的 commit；非本地 `git rev-parse` 读数，如实注明）。克隆于 `D:/repo/_refs/dsh/research-report-src` 与 `session-enhance-src`。
> 两份 README 本卡未逐字比对（主控已读过简介；本卡只读源码），下文所有片段均出自源码；因此「README 与源码冲突」一条是**没采集**而不是「零冲突」。

## 结论先行（≤10 行）

1. **dsh-research-report 的「内容寻址」= 对快照全文算 SHA-256**：`sha256Of(content)`（`ledger.ts:29-31`），证据对象落 `objects/<sha256>`、同内容只存一份、对象不可变（存在即跳过写，`ledger.ts:184-185`）；**结论文本也按内容寻址**（`claimHash = sha256Of(registration.text)`，`provider-local.ts:583`），证伪记录按 claimHash 记 —— 换卡号重报同一段话照样被认出。
2. **结论绑证据 = append-only JSONL 三本账**：`index.jsonl`（证据）/ `claims.jsonl`（结论，`evidenceIds: string[]` 一对多）/ `verdicts.jsonl`（裁定，**latest per claim wins**）；id 重复注册但内容不同 ⇒ `ID_CONFLICT` 响亮拒绝（`ledger.ts:229-237, 276-281`）。
3. **封存不是只读锁，是哈希封印**：`manifest.json` 记 reportSha256 + 每条证据的 sha256 + 全部裁定；seal hash = **manifest 精确字节的 SHA-256**（`assemble.ts:385-387`）；`verify-sealed.ts` 零网络零模型**重算**全部哈希并逐条重验裁定，防的是「事后被改」而不是「不让改」。
4. **裁定的取值域是五态**：`verified | unverified | contradicted | insufficient | disproven`（`service.ts:62`）；默认裁定者是**确定性字节级检查**（数字/引文必须在绑定快照里逐字可定位，`verify.ts:173-241`），可选模型核验器「是增强，永不是替代」（`verify-sealed.ts:4-5`）；裁定结果 `recordVerdict` 追加回 `verdicts.jsonl`（`provider-local.ts:613-616`）。
5. **交付前重审计 + 漂移即挡**：封存前每条 claim 重新验证，与上轮 verified 比对，漂了 ⇒ 强制 `contradicted` 且计入 `blockedReasons`（`provider-local.ts:590-612, 671-673`）；同文本曾被证伪且证据未变 ⇒ 永远挡住重报 verified（负知识，`provider-local.ts:594-607`）。
6. **session-enhance 的「一键对账」= 以物理 header 为权威修记账**：`persistence.list()` 的物理会话集合 vs storages 记账（归档集合/工作区 sessionIds/投影缓存/header 索引），判据是 **id 集合比对 + realpath 归一 cwd 归属**，不是内容哈希（`domains/sync.js:13-14, 27-61`）；自动修但只修记账侧，失败降级 warn 不阻断；**无 dry-run、无备份**。
7. **墓碑防复活是内存四道检查点**：id + 日志身份（createdAt/cwd）记在 `deletedSessionIds`/`deletedIdentities`（`workspace.js:36-43`，FIFO 上限 4096）；检查点 ① `indexHeader` 跳过墓碑 id（挡 stale list 复活，`workspace.js:277-281`）② `sessionKnown` 冷复用探针按身份区分「同 id 新生命周期」（`workspace.js:257-276`）③ 投影缓存写前挡、写后补删（`projcache.js:100-132`）④ 删除顺序里 `whenIdle()` 落定后才删缓存行（`delete.js:33-35`）。
8. **搬移 = 物理先行、记账后动、失败回滚**：转录目录整体搬 + 工件第一行 header.cwd 改写 + zstd 帧布局重编码 + 读回验证，全过了才动工作区记账（`domains/move.js:29-88`）；漏搬投影缓存身份 ⇒ 标题回退工作区名；帧布局破坏 ⇒ `session.list` 整体 500（`session-move.js:38-43`）。

## 一、dsh-research-report

### 1.1 内容寻址怎么算（文件:行号 + 片段）

**对快照全文算 SHA-256（UTF-8 字节），不是对文件名/快照 id/树**：

`src/ledger.ts:28-31`（原样）：
```ts
/** SHA-256 hex of one UTF-8 string. */
export function sha256Of(content: string): string {
  return createHash('sha256').update(content, 'utf8').digest('hex')
}
```

注册入口 `putEvidence` 现算地址（`src/ledger.ts:225-226`，原样）：
```ts
      const hash = sha256Of(input.content)
      const id = input.id ?? `ev-${hash.slice(0, 12)}`
```

对象落盘布局与不可变语义（`src/ledger.ts:4-9` 文件头，原样）：
```
 * - `objects/<sha256>` — one immutable snapshot per content hash (same content
 *   is stored exactly once; an "update" is a new object, history is never
 *   rewritten).
```

写对象是 **tmp + rename 原子写**，且「已存在就跳过」（`src/ledger.ts:183-185`，原样）：
```ts
    const target = path.join(this.objectsDir, hash)
    try {
      await readFile(target)
      return // object exists — content-addressed storage is immutable
```

**结论文本同样按内容寻址**（`src/provider-local.ts:583`，原样）：`const claimHash = sha256Of(registration.text)` —— 证伪记录 `LedgerDisproofLine` 的键就是 claimHash（`src/ledger.ts:79-82`，原样）：
```ts
  /** SHA-256 of the claim text (content address, independent of the claim id). */
  claimHash: string
```

### 1.2 结论与证据怎么绑

**存哪**：`claims.jsonl` 追加日志，一行一条结论；`LedgerClaimLine`（`src/ledger.ts:62-69`，原样）：
```ts
export interface LedgerClaimLine {
  id: string
  text: string
  evidenceIds: string[]
  dataset?: string
  citations?: Array<{ id: string; path: string; value: number | string; tolerance?: number }>
  registeredAt: string
}
```

**一条结论挂多条证据 = `evidenceIds` 数组**；段落再挂结论（`claimIds`），三层引用在封存时全量校验 —— 结论绑未知证据、段落引未注册结论都是 `RequestValidationError` 响亮拒绝（`src/assemble.ts:127-131, 136-140`，原样）：
```ts
      for (const evidenceId of claim.evidenceIds) {
        if (!evidenceIds.has(evidenceId)) {
          throw new RequestValidationError(`claim "${claim.id}" binds unknown evidence id "${evidenceId}"`)
```

**绑定关系不可改**：同 id 重注册但 text/evidenceIds/dataset 任一不同 ⇒ `ID_CONFLICT`（`src/ledger.ts:276-280`，原样）：
```ts
          if (!same) {
            throw new LedgerError(
              'ID_CONFLICT',
              `claim id "${claim.id}" is already registered with different text or bindings; choose a new claim id — registrations are immutable`,
```

证据侧同款：同 id 不同内容 ⇒ 响亮拒绝（`src/ledger.ts:229-234`：`evidence id "…" is already registered with different content … snapshots are immutable`）。工具入口 `evidence_add` 的 `content` 内联时逐字使用，缺省时按 origin 抓取（URL 走 `ctx.web`、路径走磁盘）（`src/tools/evidence-add.ts:3-5, 130-142`）。

### 1.3 封存与不可篡改

**封存时冻结什么**：`report.md`（确定性渲染）+ `manifest.json` + 两本审计日志（`verification.jsonl` 交付前重审计、`disconfirmation.jsonl` 证伪记录）。manifest 记：reportSha256、**每条证据的 sha256**、全部 claims、全部 verdicts、driftCount、两本日志各自的 sha256 与条数（`src/assemble.ts:278-304` `ReportManifest`）。

**seal hash = manifest 精确字节 SHA-256**，键序由构造固定保证确定性（`src/assemble.ts:7-10` 文件头，原样）：
```
 * Sealing: `report.md` is rendered deterministically from the validated
 * request plus the verdicts; `manifest.json` carries the report hash, every
 * evidence hash, and the verdicts; the seal hash is the SHA-256 of the exact
 * manifest bytes. Recomputing the hashes from the sealed directory always
 * reproduces the seal.
```

**怎么保证之后改不动 —— 不靠只读，靠「读时重算」**：每次读证据都重算哈希比对索引（`src/ledger.ts:14-16` 文件头，原样）：
```
 * Tamper detection is the point of the design: every content read recomputes
 * the SHA-256 of the object file and compares it against the indexed hash —
 * a mismatch surfaces as `tampered`, a deleted object as `missing`.
```
（`src/ledger.ts:385-398` `readContent` 返回 `integrity: 'ok' | 'tampered' | 'missing'`；对象被删不炸，降级为 `missing`。）

独立校验器 `verify-sealed.ts` 是**零网络零模型**的确定性重验：重算 seal、report 哈希、两本日志哈希，逐条 claim 重跑字节级检查比对记录值（`src/verify-sealed.ts:80-122`），并输出 SARIF 2.1.0 / JSON（`:160-314`）。可选的模型核验器定位写在文件头（`src/verify-sealed.ts:4-5`，原样）：`The optional model verifier (spawned over `ctx.jobs`) is an enhancement over this machine check, never a replacement.`

### 1.4 裁定的取值域与回写

**取值域（五态）**（`src/service.ts:62`，原样）：
```ts
export type VerdictStatus = 'verified' | 'unverified' | 'contradicted' | 'insufficient' | 'disproven'
```

**谁来裁**：默认是**确定性机器检查**，不是模型 —— 字节级语义（`src/verify.ts:5-10` 文件头，原样）：
```
 * Byte-level semantics (v1 is deliberately NON-semantic): every number and
 * quoted span in the claim text must be locatable VERBATIM in the bound
 * evidence snapshots. A citation that cannot be located makes the claim
 * `unverified`; a number whose left-context label appears in the snapshot
 * followed by a DIFFERENT number makes the claim `contradicted`.
```
判定分支（`src/verify.ts:219-241`）：有矛盾 ⇒ `disproven`；有引文找不到 ⇒ `insufficient`；全定位 ⇒ `verified`；零证据/无可查引文 ⇒ `unverified`。数字反证的判据很讲究：**先查 claimed 数字在不在，不在时才查「同标签后跟不同数字」**（`verify.ts:194-197` 注释：`The contradiction check runs only when the claimed number is ABSENT`）。可选数字桥 `ctx.dataQuality`（结构化数据集对账，`mismatch → disproven`，`verify.ts:252-270`）与字节级结果**按严重度折叠**（`verified < insufficient < unverified < contradicted < disproven`，`verify.ts:284-286`）。

**回写**：`recordVerdict` 追加进 `verdicts.jsonl`（append-only，`src/ledger.ts:299-305`），读侧折叠 **latest per claim wins**（`src/ledger.ts:347-352`）；每次封存重审计都追加一条新裁定（`src/provider-local.ts:613-616`）并 emit 审计事件（`:617-624`，注释原话 `verdicts.jsonl` is the durable source of truth）。

**两条「不许翻案」的机制**（★ 与我们的「排除项」同型）：
1. **漂移即挡**：封存前每条 claim 重验，与台账里上一轮裁定比对（`src/provider-local.ts:590-591`，原样）：
   ```ts
      const prior = priorByClaim.get(claim.id)
      const drifted = prior !== undefined && prior.status === 'verified' && fresh.status !== 'verified'
   ```
   漂了强制 `contradicted`（`:603-604`：`drift from prior verified verdict: …`），且进 `blockedReasons`（`:671-673`：`verdict drift: claim "…" regressed from a prior verified verdict`）。
2. **负知识**：同一段结论文本曾被证伪且绑定证据哈希集合未变 ⇒ 即使重跑判 verified 也强制打回 `disproven`（`src/provider-local.ts:594-602`，原样）：
   ```ts
      // Negative knowledge: the same claim text was previously disproven and
      // its bound evidence has not changed — block re-reporting it as verified.
      if (priorDisproof !== undefined && sameEvidenceSet(priorDisproof.evidenceHashes, evidenceHashes) && fresh.status === 'verified') {
        final = {
          claimId: claim.id,
          status: 'disproven',
          note: `previously disproven against unchanged evidence: ${priorDisproof.note}`,
   ```
   且 `fresh.status === 'disproven'` 时 `recordDisproof` 落负知识账（`:639-650`）。

### 1.5 呈现接口（给人看/给人核）

- **三个模型工具**：`evidence_add`（注册证据，返回 id + sha256 + 去重标记，`src/tools/evidence-add.ts:120-123`）、`research_report`（封存报告，`src/tools/research-report.ts:231`）、`ledger-query`（未深读，208 行）。
- **封存结果对模型/人同时可见**：counts 五态计数 + 非verified 逐条列名（`research-report.ts:170-187` `renderSealed`）；正文段落按裁定挂**可见标记** `[未核实] / [与证据矛盾] / [证据不足] / [已证伪]`（`src/assemble.ts:22-32`）—— 注释原话 `nothing is silently passed`。
- **四个附录**：A 裁定表、B 证据清单（含 sha256 与会话锚点）、C 封存（seal + 配置指纹）、D 证伪日志（`src/assemble.ts:224-272`）。
- **UI 卡片**：`presentResult` 把 `report.md` + `manifest.json` 两条路径作为**持久化投影**交给界面（`research-report.ts:302-314`，注释 `replay-safe: the paths ride the persisted presentation meta`）。
- **独立核验器**：JSON + SARIF 2.1.0 输出，每条失败检查一个 ruleId（`verify-sealed.ts:252-261`）。

### 1.6 ★ 我们能抄什么 / 不抄什么

**该抄**：① **裁定取值域显式五态**（我们的门禁只有 ok/FAIL 两态 + 文字摘要，「存疑/证据不足」被压扁成红绿 —— 它连「为什么没 verified」都分了型）；② **负知识按内容哈希记**（我们「228 不翻」这类排除项目前是文档口径，没有机器检查点挡「换个说法重报」）；③ **封存 = 重算哈希而非禁止修改**（对应我们 `docs/changelog.d/` 片段 + 封存树指纹 —— 方向一致，可补「每次读台账重验指纹」的读侧检查）。

**不该抄**：内容寻址对象仓（我们已有 git，本身就是内容寻址存储）；`ctx.web` 抓取层；SARIF 输出（无消费方）。

## 二、dsh-session-enhance

### 2.1 对账对的是哪两份

**入口**：`syncRecords`（宿主侧远程方法，`lib/workspace.js:55` 注册；实现在 `lib/domains/sync.js`）。

**拿哪两份对**：① `sessionPersistence.list()` 返回的**物理会话 header 列表**（权威）；② storages 里的**记账**：`state.archivedSessionIds`、各工作区记录的 `sessionIds`、投影缓存表、header 索引。**判据是 id 集合比对**，不是内容哈希（`lib/domains/sync.js:13-14`，原样）：
```js
		const headers = await persistence.list();
		const physicalIds = new Set(headers.map((header) => header.id));
```
文件头口径（`lib/domains/sync.js:2`，原样）：`dsh-session-enhance 记录同步：以物理 header 为权威对账 storages 记账。`

**五步对账**（`sync.js:26-128`，步骤注释原样）：
1. 归档集合清幽灵：`state.archivedSessionIds` 里物理不存在的 id 剔除（`:27-34`）；
2. 工作区：幽灵移除 + **归属修正** —— cwd 经 `realpath` 归一后不属于该工作区的也移出（`:53-71`，注释 `各工作区：幽灵移除 + 归属修正（记错工作区的移出）`）；
3. 漏记补录：物理存在、记账没有、且 cwd 命中某工作区 ⇒ 补进 `sessionIds`（`:72-86`）;
4. 投影缓存：物理不存在的行删除 + 身份（cwd）对齐（`:87-100`）；
4.5. **工件编码卫生**：会话目录里与后端编码相反的遗留工件（如 zstd 旁边的明文 jsonl）直接 `rm`（`:101-125`）；
5. 重建 header 索引：`replaceHeaderIndex(headers)` 以当前物理列表为准（`:126-127`）。

### 2.2 不一致时的处置（含干跑/备份）

**会自动修，无 dry-run、无备份** —— 但修的方向是「**只修记账侧，不动物理侧**」：幽灵剔出、漏记补录、归属搬正，全部是对 storages 记账的写（`table.update` / `setState`），物理会话文件从头到尾不被碰。唯一的例外是 4.5 步：**相反编码的遗留工件会自动物理删除**（`sync.js:108-115`，`rm(join(dir, entry.name), { force: true })`）—— 因为留着它会让严格读取器把 `session.list` 整体 500（依据 `lib/session-move.js:122-126` 注释）。

**失败策略**：降级告警不阻断 —— 投影缓存幽灵清理失败 `logger.warn` 继续（`sync.js:96-98`），编码卫生失败同款（`:122-124`）；整个操作经 `registry.enqueueOperation()` 串行化（`:8`）。返回值是一份**对账报告**（`sync.js:15-23`）：`scanned / archivedRemoved / workspaceRemoved / workspaceAdded / projcacheRemoved / projcacheRehomed / artifactMismatchesRemoved` 七个字段，谁被动了逐条可查。

（对照删除域：真正的**物理删除**走另一条链 `deleteSessionCore`，那里才是「可失败的持久化清理先于不可逆物理删除」+ 删除后验证（`lib/domains/delete.js:4-7, 50` `verifyPhysicalDeletion`）。对账与删除是两个动作，对账不删物理文件。）

### 2.3 ★★ 墓碑记什么、何时查

**墓碑记在哪、记什么**：**纯内存，不落盘**。`lib/workspace.js:36-43`（原样）：
```js
	/** 本进程内已物理删除的会话；阻止父类把 stale list() 重新编入索引。 */
	deletedSessionIds = new Set();
	/** 墓碑插入顺序，用于在上限处淘汰最旧项。 */
	deletedSessionOrder = [];
	/** 墓碑上限：足够挡住 stale list()，又避免长驻进程无限增长。 */
	deletedSessionTombstoneLimit = 4096;
	/** 被删生命周期的日志身份（createdAt/cwd）：冷复用探针区分"同 id 新会话"与 stale list() 的依据。 */
	deletedIdentities = new Map();
```
即：**记 id + 被删生命周期的日志身份（createdAt/cwd）**（身份投影见 `lib/shared/identity.js:7-12`），**不记时间戳与删除原因**。FIFO 淘汰共用一个通用簿记（`lib/tombstone.js:20-27`，原样注释）：
```js
		// id 自身被挤出队列时保留在集合中：宁多挡不错放。
		if (oldest !== void 0 && oldest !== id) {
```

**什么时候登记**：物理删除链的最后一步 —— 先 `forgetIndexedSession`（内含打墓碑）再存身份（`lib/domains/delete.js:51-53`，原样）：
```js
	// 物理删除已成功：此时再清父类索引。失败时保留索引，便于重试。
	registry.forgetIndexedSession(sessionId);
	if (deletedHeader !== void 0) registry.deletedIdentities.set(sessionId, headerIdentity(deletedHeader));
```
（先记身份再删头部的理由写在 `delete.js:26`：`先记录被删生命周期的日志身份：目录删除后头部不可再读。`）投影缓存侧在 `delete(id)` 时登记（`lib/projcache.js:145-148`）。

**四个检查点**：
1. **索引重建时**：`indexHeader` 跳过墓碑 id —— 挡的是「stale list() 复活」（`lib/workspace.js:277-281`，原样）：
   ```js
	/** 父类 indexHeaders 只增不减；跳过墓碑 id，避免 stale list() 复活。 */
	async indexHeader(header) {
		if (this.deletedSessionIds.has(header.id)) return;
   ```
2. **入口探活时**：`sessionKnown` 对墓碑 id 走**冷复用探针** `coldReuseKnown` —— `persistence.list()` 里同 id 出现且 **createdAt/cwd 与墓碑身份不同** 才认作「同 id 新生命周期」，撤墓碑重新索引；身份相同 ⇒ 仍判未知（`lib/workspace.js:249-276`；`:272` 判据原样 `if (listed.createdAt === deletedIdentity.createdAt && listed.cwd === deletedIdentity.cwd) return false`）。
3. **投影缓存写路径**：`write`/`put` **写前挡**（`if (this.deletedSessionIds.has(id)) return`，`projcache.js:110, 120`）+ **写后补删**（写完再查一次墓碑，在 ⇒ `table.delete`，`projcache.js:112, 128`）—— 防的是「删除落在写回进行中，落定的旧数据把行写回复活」。正确性前提写在 `projcache.js:106-108`（原样）：`墓碑正确性依赖：super.write(session) 一次整体写入，返回后不再有后续异步落盘。若上游改成多阶段异步，(C) 补删会漏掉后续写入`。
4. **删除顺序本身**：`projCache?.whenIdle?.()` 等在途写全部落定**之后**才删缓存行（`delete.js:33-35`，注释 `dispose 的写后落盘必须先于缓存行删除完成，否则该行会被写回复活`）。

**撤销**：`clearTombstone`（同 id 新生命周期 / 测试用，`workspace.js:234-239`、`projcache.js:175-180`）。

### 2.4 搬移要带哪些状态（漏搬会怎样）

**编排**（`lib/domains/move.js:13-96`）：实时会话先 `flushLiveSession` + `detachLiveSession`（释放写路径与文件句柄，`:33-38`），然后**物理移动先于记账**（`:29` 注释原样：`物理移动：转录目录 + 工件 header.cwd（先于记账，失败时记账未动可重试）`）。

**要一起搬/改的状态清单**：
1. **转录目录**：整体 rename，跨盘 EXDEV/EPERM 退化拷贝+删除（`lib/session-move.js:98-107`）；
2. **工件内 header.cwd**：只改写第一行、事件行原样保留；zstd 工件按后端帧布局重编码 —— **header 独占第一帧**，写盘前用 `assertFirstFrameIsHeader` 逐字节校验帧布局（`session-move.js:47-97, 166-191`）；
3. **读回验证 + 回滚**：重读工件验证 `verifiedHeader.cwd !== newCwd` 即抛，抛前 `restoreSessionArtifact` 恢复原 header 文本并把目录搬回（`session-move.js:234-245, 192-205`）；
4. **内存索引**：`registry.headers` 的 cwd 与 canonical `sessionPath` 指向新工作区（`move.js:44-52`）;
5. **投影缓存行身份**：`projCache.whenIdle()` 落定在途写后 `rehome(id, { createdAt, cwd })`（`move.js:98-107`）；rehome **只改 createdAt/cwd、保留 isSeeded/inheritedEventCount 谱系字段**，缺了会让 `identityMatches` 判否（`projcache.js:162-171` 注释原样）；
6. **工作区记账**：先从**所有**工作区移除（防重复记账）再加入目标（`move.js:68-88`）；
7. **持久化协调器内存态**：`persistence.prepare(id)` 让 states.meta 以新 cwd 落定（`session-move.js:246-252`）；
8. **相反编码遗留工件**：目录搬移会把它们带进目标工作区，移动后必须清理，否则严格读取器抛 encodingMismatch（`session-move.js:119-146`）。

**漏搬会怎样（源码自答）**：
- 投影缓存身份没 rehome ⇒ `session.list` 的 `cachedSnapshot` 身份校验不过，**会话标题投影回退为工作区名**（`projcache.js:152-157` 注释原样：`identityMatches 重新通过，会话标题等投影恢复服务，侧栏不再回退显示目标工作区名`）—— fail-soft 不炸；
- zstd 帧布局破坏（整篇压进单帧）⇒ **后端严格读取器判废，`session.list` 整体 500、会话无法 resume**（`session-move.js:38-43` 注释原样：`整篇压缩进单帧会让移动后的会话不可读，进而使 session.list 整体 500`）—— 所以写盘前先校验、把破坏变成可回滚的移动失败；
- `persistence.prepare` 没跑 ⇒ 旧 meta 把后续写入导向旧路径（**分裂写入**，`session-move.js:17-19` 注释原样）。

### 2.5 ★ 我们能抄什么 / 不抄什么

**该抄**：① **「物理为权威」的对账方向**（我们 `docs/workbacklog.toml` 台账 vs 卡树实际改动、`gates/last.json` vs 实际产物，判据都应取「实际在盘上的东西」当权威、记账向它修，而不是反过来）；② **对账产出七字段报告**（动了谁逐条可查，而不是一句「已同步」）；③ **墓碑的「身份探针」形状**（挡复活但不挡合法新生命周期：同 id + 同身份 = stale 残影，同 id + 不同身份 = 新事物 —— 对应我们的「同一条被证伪口径换个卡号/换个说法重报」按**内容哈希**认出而不是按字面）；④ **写前挡 + 写后补删**（对一切「删除与写回并发」的缝通用）。

**不该抄**：**内存墓碑不落盘**（它是长驻宿主进程才成立的形状；我们的排除项必须落盘持久，学形状不学存储介质）；zstd 帧编码层（无对应域）；`enqueueOperation` 单飞串行（我们的写竞争面在 git 树，已有锁）。

## 三、★ 三条「直接可用」的建议（指名文件 + 怎么验）

1. **给成送申请的证据加「读时重算哈希」双验（抄 `readContent` 的 tamper-detection）**。
   改哪个文件：`tools/pool/task.py`（claim 成功申请现在只存证据**文字**）—— claim 时若 `--evidence` 指向文件，登记该文件路径 + sha256；`advance`/收口读申请时**重算**文件哈希比对，不一致即把该申请判为无效（`tampered` 级别，挡收口并点名）。依据：`ledger.ts:14-16`（每次读重算哈希比对索引）与 `readContent` 的 `ok | tampered | missing` 三态。
   怎么验：投一份带文件证据的成送申请 ⇒ `status` 显示 ok；把证据文件改一个字节再 `advance` ⇒ 该申请被判「证据哈希不匹配」并列出新旧哈希；恢复文件后 `advance` 重新放行。

2. **给「被证伪口径」立落盘墓碑 + 冷复用探针（抄负知识 + coldReuseKnown 的身份判据）**。
   改哪个文件：新增机器可读墓碑表 `docs/tombstones.toml`（每条：`id`、**被证伪口径的 sha256**、原文、证伪出处（卡/台账号）、`revoked` 撤销标记），并在 `tools/wb_dispatch.py` 的派活前置检查加一步：对即将派出的卡规格文本抽取字面/关键句算哈希比对墓碑表，命中且未 `revoked` ⇒ 拒派并给出墓碑条目与撤销方法。依据：`provider-local.ts:594-607`（同文本曾被证伪且证据未变 ⇒ 挡 verified）+ `workspace.js:257-276`（同 id 不同身份 = 新生命周期，放行）——挡的是**同内容重报**，不挡「新卡新口径」。
   怎么验：把一条已登记墓碑的口径原文塞进新卡 ⇒ 派活被挡，错误信息带墓碑 id 与证伪出处；给该条目加 `revoked = true` 后同一张卡可派（身份探针语义：显式撤销 = 新生命周期）。

3. **收口前对每张成员卡做「交付前重审计」：成送后域文件指纹漂了就挡（抄封存前 drift 重验）**。
   改哪个文件：`tools/pool/task.py` + `tools/pool/landing.py` —— claim 成功申请时**顺手记录该卡 paths 域内被跟踪文件的 sha256 快照**（随申请存档）；`advance`/收口时对当前卡树重算并比对，任一文件自成送后变更 ⇒ 该成员申请失效，收口被 `blockedReasons` 挡下（对齐 `provider-local.ts:671-673` 的 drift-into-blockedReasons 形状）。
   怎么验：卡 A 成送后、收口前改它域内一个文件 ⇒ `advance` 报 `drift: <path> 自成送后变更` 并挡收口；回滚该改动后收口放行；全程未动域文件的卡不受影响（负例）。

## 验收（原样读数）

### 1. 两仓版本

```
（git clone 直连失败：Connection was reset / Could not connect；按卡规格退 codeload tar.gz）
PerryLink/dsh-research-report  main  ⇒ 8d00f06  （GitHub API commits/main sha=8d00f06e87c489e18147a45b4aafa0483cd0b53f，2026-10-12）
Tinger-X/dsh-session-enhance   main  ⇒ f7eb9a0  （GitHub API commits/main sha=f7eb9a0e0697d58a5529132256b5a0b8ad6bde50，2026-09-07）
```
★ 那是**别的仓的 sha**（tarball 无 `.git`，无法本地 `git rev-parse`，取自 API 并如实注明口径），非本仓对象。

### 2. 每仓读过的文件（路径 + 行数；「部分读」指只读了与问题相关的段）

**dsh-research-report**（8d00f06，实读 8 个 ≤10 预算）：
- `src/ledger.ts`（399 行，全读）
- `src/verify.ts`（287 行，全读）
- `src/verify-sealed.ts`（314 行，全读）
- `src/assemble.ts`（409 行，全读）
- `src/tools/evidence-add.ts`（164 行，全读）
- `src/tools/research-report.ts`（434 行，全读）
- `src/service.ts`（372 行，部分读：230-372 + grep 定位 13 处）
- `src/provider-local.ts`（914 行，部分读：560-660 + grep 定位 15 处）

**dsh-session-enhance**（f7eb9a0，实读 10 个 = 预算上限）：
- `lib/tombstone.js`（30 行，全读）
- `lib/domains/sync.js`（131 行，全读）
- `lib/domains/delete.js`（163 行，全读）
- `lib/domains/move.js`（121 行，全读）
- `lib/storage-sweep.js`（169 行，全读）
- `lib/session-move.js`（255 行，全读）
- `lib/workspace.js`（283 行，部分读：1-70、225-283 + grep 定位）
- `lib/projcache.js`（182 行，部分读：95-180）
- `lib/shared/identity.js`（12 行，全读）
- `lib/shared/constants.js`（13 行，全读）

另：两仓顶层 `ls` + 全部源文件 `wc -l`（未计入文件数；`lib/client.js` 5603 行打包产物**未读**，与第一批 gating-hub 同款边界）。

### 3. §三 建议

见上（每条指名改我们哪个文件 + 怎么验）。

### 4. 本卡不碰代码

`ruff` 与 pytest 均未跑（文档层卡、卡规格未要求）；未 commit、未 tag、未装插件、未改 `~/.dsh`、未起服务；pin_check 未跑 —— 本卡是**新增文件**，不改任何既有文件的字面/常量，pin_check 不适用（同第一批口径）。

### 5. 老实说（边界）

- git clone 直连失败（connection reset），按卡规格用 codeload tar.gz 抓取 ⇒ **没有本地 git 对象**，sha 来自 GitHub API 而非 `git rev-parse`，口径差异已注明。
- 「README 与源码冲突」**没采集**（本卡未读两仓 README，主控读的是简介）；如需比对请示下。
- `dsh-session-enhance` 的 `lib/` 疑为直发源码形态（无 src/lib 双份、无构建脚本对应 domains 层），按源码直读；`lib/client.js`（5603 行）是打包产物未读 —— `src/client/` 的浏览器侧（面板/拖拽 UI）本卡四个问题都不涉及，未深读。
- `dsh-research-report` 的 `provider-local.ts`（914 行）与 `service.ts` 只读了裁定回写与漂移相关段；`ledger-query.ts`（208 行）与 `cli.ts`/`gather.ts` 未读（问题 1-5 的必经链不经过它们）。
- §三建议 2/3 涉及新增文件与跨工具接线，属**主控决策**；本卡只给形状与验法，未定案。
