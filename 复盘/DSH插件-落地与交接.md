# DSH 插件 —— 落地与交接

> 本文合并：长任务计划（`DSH插件-长任务计划.md`，含 R1–R34 进度与收官交接）、落地验收单（`DSH插件-落地验收单.md`）、成果盘点（`DSH插件-成果盘点与待用清单.md`）。
> 旧文档正文在 git 历史。反例与踩坑收在「已决问题索引」。

## 结论先行

1. 面板三行（工作台 / 禅道 / timeflow）已落地：点一行 = 右栏打开真实页面，图标是内联 SVG，包补了 `dsh.bundle.patch`。
2. 已落地的提交：`10ec620` / `ad8effb` / `952568d` / `1672139` / `63b9a2f` / `6b109d2` / `690cd15` / `5e4f3d9` / `7258275` / `8e8c19d` / `bab50df`。
3. 用户能自己验的两件：重启 DSH；走禅道安装向导。其余 6 条验收照本页 §三逐条对。
4. 自举（用户点名要的机制）三轮就收敛：词表两轮收敛、方面覆盖一轮收敛，剩下的价值全在定点深读与落地收口。
5. 所有动作都可逆（§五给退回法）。

## 一、已落地（提交可查）

| 提交 | 内容 |
|---|---|
| `10ec620` / `ad8effb` / `952568d` | 面板三座位 + 只读缝 / 一起起-分别停 `tools/stack.py` / 补回 `inject` 禁列 |
| `1672139` / `63b9a2f` | 面板仓库根从 config 取（DSH 桌面版宿主 cwd 是 profile 目录）/ 队列账目翻正 |
| `6b109d2` | 工作台页纳入「一起起」（`board`=8787）+ 修 `trae` 判活两处 |
| `690cd15` | 面板三行改快捷入口：点开＝真实页面 + 图标改内联 SVG + 包补 `dsh.bundle.patch` |
| `5e4f3d9` | 卡 244：`openTabIn` 逃生门 · `peerDependencies["@deepseek-ai/dsh"]` · 包内 `icon.svg` · 右栏页签（74 条判据） |
| `7258275` | 卡 245：Trae 驱动器模型切换要能点到 + 发送必须核验（`selftest` 24 条全绿；真机 `Kimi-K3` 收发成功） |
| `8e8c19d` | 卡 246：定点深读第一批（三仓源码逐文件读） |
| `bab50df` | 卡 247：右栏常驻页签 + 包级显示链路 + 底部入口 + 三行图标按用户指定换 B/B/C |

自举的实测结论：第一轮回填 22 词 ⇒ 挤出 `dsh-pilot`、`dsh-url-router`；第二轮回填 17 词 ⇒ 只挤出 1 个真候选；第三轮改口径量 16 方面覆盖 ⇒ 零覆盖的方面 = 无（16/16 都有）。⇒ 扩词 / 换口径都不再值钱，价值在定点深读与落地收口。

环境侧两处修复（可逆）：`git clone` 修好（补 `git-remote-https.exe`）；插件市场装好（`dsh plugin --profile desktop add dshmarket` ⇒ 自动进 bundles）。

## 二、在飞 / 待派

| 卡 | 批 | 树 | task | 内容 | 状态 |
|---|---|---|---|---|---|
| 247 | `B-20261034` | `.wt/panelresident` | T-G368 | 右栏常驻页签 + 包级显示链路 + 补丁层三纪律 | 已落 `bab50df` |
| 248 | `B-20261035` | `.wt/stampfix` | T-G369 | 盖章不许代写申请 | 落地中 |
| 249 | `B-20261036` | `.wt/blocks` | T-G370 | 六块读数单元清单 + `STALE-WHILE-ERROR` | 落地中 |
| 250 | `B-20261037` | `.wt/portid` | T-G371 | 挑端口 bind + 验明正身 | 落地中 |
| 252 | `B-20261039` | `.wt/deepread2` | T-G373 | 定点深读第二批（证据台账 / 对账与墓碑） | 落地中 |
| 251 | `B-20261038` | `.wt/tokens` | T-G372 | 面板不许硬编码颜色 | 待派（与 247 同文件，须等 247 落地） |
| 253 | — | — | — | 一键启动 + 内存账本 + 面板「点开才读」 | 待派 |
| 254 | — | — | — | 受影响的测试选择（省门禁峰值） | 在跑 |
| 255 | — | — | — | 读数器内容哈希缓存 + 只读尾部 + git 只调一次 | 待派 |

## 三、重启 DSH 后逐条验收

用户能自己做的两件：重启 DSH（换已挂载包的 manifest 必须重启）；走禅道安装向导（GUI 向导只能用户点）。

| # | 期望 | 怎么验 |
|---|---|---|
| 1 | 左栏出现三行（工作台 / 禅道 / timeflow），图标是矢量图标 | 看左栏；点任一行看是否切到那个面板；组合里那一行在不在 `dsh plugin --profile desktop list` |
| 2 | 点一行 = 右栏打开真实页面，对话留在中间 | 点「工作台」→ 右栏出现 `http://127.0.0.1:8787/`（标题「工人状态」）；`curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8787/` 要 200 |
| 3 | 目标页没起时，面板显式说「没起 + 怎么起」 | 先 `python -X utf8 tools/stack.py stop board` 再点那一行 ⇒ 应看到明确错误与「怎么起」 |
| 4 | 设置里出现「插件市场」 | 设置 → 市场 / 插件那一栏；`~/.dsh/profiles/desktop/package.json` 的 `dsh.profile.bundles` 里应含 `dshmarket` |
| 5 | 禅道那一行（装完向导后）能打开 `http://127.0.0.1/zentao/` | 装完向导后点那一行；端口 80 是否 LISTEN、是否只绑回环 |
| 6 | 一起起 / 分别停 | 双击 `start-all.cmd` ⇒ 打印每件状态；单独停 `python -X utf8 tools/stack.py stop <名>` |

已经验过的（真读数，不用用户再验）：三个目标页活着（`8787` http=200 标题「工人状态」· `8520` http=200 标题「timeflow」）；栈能一起起、分别停（`closer`/`timeflow`/`board`/`trae` 起得来，`zentao` 如实拒要 GUI）；面板装法是官方的（包自带 `dsh.bundle.patch`、在 `dsh.profile.bundles` 里、装进去那份与仓库源逐字节一致）；市场装的也是官方的；`git clone` 修好；三个目标 URL 过侧栏浏览器白名单（内嵌凭据拒 / 非 http(s) 拒 / 其余 http(s) 含 loopback 通过）；Kimi K3 那条道通了；GLM-5.3 那条道在用。

## 四、接手步骤（每张在飞卡都一样，四步）

1. 等它的 `gates/diag/wb-<卡>.verdict.txt` 出现「正常收工」。
2. 在它的树里跑域内判据（卡里「验收」段点名的那几条命令）并抄下原样读数。
3. 写 `gates/diag/_text_<task>.md`（三节：`=== gaps ===` / `=== changelog ===` / `=== checkpoint ===`；gaps 里每条指针必须在本仓解析得到）。
4. `python -X utf8 tools/wb_land.py --card <卡> --tree . --task <task> --title "…" --allow <该卡 paths> docs/workbacklog.toml <规格文件> docs/changelog.md docs/traceability.toml "复盘/交接-重构进度.md"`。

收口：`closer`（`stack.py start closer`）能自动落单树批，跨两棵树的批会停下来问人。

## 五、退回旧样子（都可逆）

| 想退的 | 怎么做 |
|---|---|
| 退掉市场 | `dsh plugin --profile desktop remove dshmarket` |
| 退掉面板那一行 | 从 `~/.dsh/profiles/desktop/package.json` 的 `dsh.profile.bundles` 里删掉 `dsh-client-ui-workbench-panel`（备份：`.bak-before-bundle-*`） |
| 退回旧的 profile 写法 | `cordis.patch.yml` 与 `package.json` 各有 `.bak-before-*` 备份，`cp` 回去即可 |

## 六、盘点：这轮还产出了什么（还没被采纳的）

40 轮除「面板三行 / 图标 / 禅道」这些已落地的，还产出大量没被采纳的建议，逐条挖出来给「出处指针」与「建议落点」：

- 已采纳的：`openTab` 开真实页面（`690cd15`）· `openTabIn` 逃生门 + `peerDependencies` + 包内 `icon.svg`（`5e4f3d9`）· 右栏常驻页签 + 包级显示链路 + 底部入口（`bab50df`，图标随卡 247 落地）· 六块读数 `BLOCKS` 唯一口径源 + `STALE-WHILE-ERROR`（卡 249）· 端口 bind + 验明正身（卡 250）· ⑨ 盖章不许代写申请（卡 248）· 一键启动 + 内存账本 + 面板「点开才读」（卡 253）· 受影响的测试选择（卡 254）· 读数器内容哈希缓存（卡 255）。
- A 级（与门禁 / 收口直接相关）：成送证据「读时重算哈希」· 被证伪口径的落盘墓碑表 · 收口前「交付重审计」。
- B 级（把门禁 / 裁定做得更可审）：非证据码成对列出（给门禁加「为什么没挡住」一栏）· 解析不确定 ⇒ 整批只报告不写盘 · 动作留痕 + 每条自带一键回滚命令 · 运行期冒烟当判据。
- C 级（形态 / 能力扩张）：让 agent「点着走」禅道（CDP 驱动 + cockpit）· 深链（`#/panel/<panelId>`）· 跨会话共享任务板 + 消息总线 · 只读展示不再开 HTTP 服务（插件面板自己渲染，可省 board/timeflow 两服务约 93 MB）。

（A/B/C 级的具体建议与验法见 `DSH插件-参考与结论.md` §五。）

## 七、边界（如实写）

- 本页合并的三份来源文档中，`DSH插件-成果盘点与待用清单.md` 与本页同目录的旧文档在卡树里并不存在（它们是主控 / 另一张卡未提交的产物）；本页只读其内容并收结论，未创建、未修改那份文件。
- 「面板在真 DSH 里的实际观感」只有用户重启后才能判。
- 禅道安装向导只能用户点（GUI）。
