# pipe-land —— 人类理解版（NOTES）

> 机器执行版是 `SKILL.md`；这一页写给**接手改它的人**：为什么这么设计、以前怎么摔的、脚本接口在哪。
> ★ 这里不写判据 —— 判据在 `tools/pool/landing.py`。删掉整个 `skills/`，框架仍完整可用。
>
> 三层：元数据 → 正文（六节 + 八步表 + 自查，≤120 行）→ `references/`。
> 本技能的长表在 [落地参数](references/land-steps.md) 与 [本仓绑定](references/repo-bindings.md)（相对链接，只深一层）。

## 这一层在防哪类错误

防「**申报不齐就落地**」、「**重跑当有副作用**」和「**把 `git commit` 当落地**」。

- 落地是一条八步链（⓪ 回退派生物 → ① 迁树 → ② 文书 → ③ sync_counts → ④ 门禁 → ⑤ seal →
  ⑥ 白名单提交 → ⑦ audit + ff → ⑧ 复核），入口条件是**申报已交齐**。
- 反直觉的一条：⓪ 会**回退上一趟的派生物**，所以重跑是幂等的；但谁也不会记得这件事，
  所以 `--no-reset` 这个开关的名字要让人一眼看出「关掉它就会撞」。
- 另一条：`--allow` 是白名单。少写一个文件，它就**真的没进那一笔** —— 这才是「落了但少了东西」的常见形态。

## ★ 两页怎么分（2026-11-08 泛用化）

搬走的是**本仓形状**：入口路径、退出码表、体检 12 条的逐条名字、八步里的子步、封存与锁的具体形状、
环境变量、跨机文档指针、复盘缺口证据链 —— 全在 [`references/repo-bindings.md`](references/repo-bindings.md)；
`SKILL.md` 只留八步链的动作顺序、前置检查、读结果的方法、常见误读。换仓只换 references 一份。

顺手核过体检条数 **11 → 12**（真源 `tools/pool/landing.py` 的 docstring 与打印行；壳层 `tools/wb_land.py`
的帮助文案仍是 11，那是陈旧文案，未改）。共同理由与四条钉子见 [`skills/README.md`](../README.md) §2。

## 失败过什么（带读数）

- **「重跑要先回到干净态」真摔过**：同一笔连跑三趟门禁、每趟 ≈ 11 分钟，代码一次没错、全死在
  派生物 / 记账那层（重复合成 ⇒ `traceability.toml` 报 `Cannot declare ('entries', …) twice`）。
  事后才把「⓪ 回退派生物」前置 —— 经过见交接文档的 `T-G250` 段。
- **封存与提交树不是一回事**：封存指纹含未跟踪文件（`git add -A` 到临时索引再 `write-tree`）⇒
  封存之后再新增文件，「提交树」就 ≠ 「封存树」。台账 / changelog / 复盘必须在跑门禁**之前**就位。
- **卡 209（`T-G318`）加严第一趟**：`check_skills.py` ⇒ rc=1，本技能「怎么读结果」**3 条口径一条都没指向脚本**。
- **卡 A293（本轮）的实测现状**：旧稿 54 行里 `wb_` / `worktree` **0 次**，命令是框架层的
  `land`（薄 CLI 入口）；实测本仓根没有 `pipeline.toml`，那条命令报「配置不存在」。
  新稿改成 `tools/wb_land.py` 真链路（八步 + `--commit-only` / `--no-reset` / `--affected` 的断点口径），
  `wb_` / 树相关出现 **12 次**，88 行、绿。

## 脚本接口与以后怎么改

- 落地：`tools/wb_land.py`（壳）→ `tools/pool/landing.py`（逻辑）。`--card` 与 `--batch` 恰好一个。
- 核实：`tools/wb_verify.py --tree .`（五块）、`tools/wb_reconcile.py`（队列 vs git）、
  `tools/wb_review.py --rev <sha> --json`（复核）。
- **判据**：八步顺序、白名单语义、封存范围（去掉 `gates/**` 的提交树）在 `tools/pool/landing.py`。
  改步骤 / 改回退名单去那里，**别改本技能**。
- 加一步 ⇒ `SKILL.md` 的八步表与 `references/land-steps.md` 的断点表要同时改，否则读者会按旧顺序断点续。
- **换一个仓** ⇒ 只改 `references/repo-bindings.md`（入口路径、退出码、锁、环境变量、文档指针）。
  如果那个仓的落地链形状不同（比如没有封存 / 没有队列），再改 `SKILL.md` 的读法 —— 但先把差异写进
  repo-bindings，别把新仓的路径塞回 SKILL.md。
- 换 harness 要改的只许集中在 `skills/GLUE-harness.md`。
