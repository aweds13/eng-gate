# DSH 插件改造 —— 落地验收单（2026-10-15）

> 用途：**重启 DSH 之后**，照这张单子逐条对，确认每一条是真生效还是没生效。
> 每条都写清：**期望看到什么** / **怎么自己验** / **没生效时先查哪里**。
> 规矩：**没看到就说没看到** ✗ —— 别把"我以为生效了"当成生效 ✓。

## 一、你要做的两下（只有这两件我替不了）

| # | 动作 | 说明 |
|---|---|---|
| 1 | **重启 DSH** | 换已挂载包的 manifest **必须重启**（客户端 bundle 在组合阶段被快照进内存，刷新页面不够 ✓ 这是生态共识） |
| 2 | **禅道安装向导** | 双击 `D:\zentao\ZenTao\ZenTao.exe`（ZenPanel）→ 点启 Apache 与 MySQL → 走安装向导（选库、建管理员账号）。**GUI 向导只能你点** ✓ |

## 二、重启后逐条验收

| # | 期望 | 怎么验 | 没生效先查 |
|---|---|---|---|
| 1 | **左栏出现三行**：工作台 / 禅道 / timeflow（图标是**矢量图标**，不再是 `▦` 这类文字符号） | 看左栏；点任一行看是否切到那个面板 | 组合里那一行在不在：`dsh plugin --profile desktop list`；或看合成结果里有没有 `- id: workbench-panel`（主控可以现场 dump ✓） |
| 2 | **点一行 = 打开真实页面**（在**右侧栏**里，对话留在中间） | 点「工作台」那行 → 右侧栏出现 `http://127.0.0.1:8787/` 的页面（标题「工人状态」） | ① 页面本身活着吗：`curl -s -o NUL -w "%{http_code}" http://127.0.0.1:8787/` 要 200；② 服务在跑吗：`python -X utf8 tools/stack.py status` |
| 3 | **目标页没起时，面板显式说「没起 + 怎么起」** | 先停服务（`python -X utf8 tools/stack.py stop board`）再点那一行 ⇒ 应看到一条明确的错误与"怎么起"，**不是白屏** | 若白屏 ⇒ 那是缺陷，报我（面板的失败可见分支被破坏 ✗） |
| 4 | **设置里出现「插件市场」** | 设置 → 找市场/插件那一栏（装的是 `dshmarket`） | `python -c "import json,pathlib,os;d=json.loads(pathlib.Path(os.path.expanduser('~/.dsh/profiles/desktop/package.json')).read_text('utf-8'));print(d['dsh']['profile']['bundles'])"` 里应含 `dshmarket` ✓ |
| 5 | **禅道那一行**（装完向导后）能打开 `http://127.0.0.1/zentao/` | 装完向导后点那一行 | 端口 80 是否 LISTEN；Apache 是否只绑回环（`netstat` 里应是 `127.0.0.1:80`，不是 `0.0.0.0:80` ✓ 我们已改过 conf ✓） |
| 6 | **一起起 / 分别停** | 双击桌面 `start-all.cmd` ⇒ 应打印每件的状态（`closer/timeflow/board/zentao/trae`）；单独停：`python -X utf8 tools/stack.py stop <名>` | `python -X utf8 tools/stack.py list` 看组件表 |

## 三、现在已经验过的（真读数，不用你再验）

| 事实 | 读数 |
|---|---|
| 三个目标页活着 | `8787` → `http=200`，标题「工人状态」✓ · `8520` → `http=200`，280 KB，标题「timeflow」✓ |
| 栈能一起起、分别停 | `closer` pid 34684 ✓ · `timeflow` :8520 ✓ · **`board` :8787 ✓**（卡 243 新加的那件 ✓，且是"等端口真起来才报成功" ✓）· `zentao` **如实拒**（要 GUI ✓ 不假装）· `trae` :9333 ✓ |
| 面板装法是官方的 | 包自带 `dsh.bundle.patch` ✓；profile 的 `dsh.profile.bundles` 里有它 ✓；`--dump-config` 里那一行带 `config.root` ✓；装进去那份与仓库源 **逐字节一致** ✓；宿主半裸导入 `OK` ✓ |
| 市场装的也是官方的 | `dshmarket` 在 `bundles` 里 ✓；合成里有 `- id: dsh-market / name: dshmarket` ✓ |
| `git clone` 修好了 | `git ls-remote https://github.com/chenxiachan/thoughtdag HEAD` 返回 sha ✓ |
| 三个目标 URL **过白名单** | 侧栏浏览器的白名单核过：内嵌凭据 ⇒ 拒（`credentials`）✗、非 http/https ⇒ 拒（`protocol`）✗、其余 http/https（含 loopback）⇒ 通过 ✓（`url.d.ts` + 实现 client.js:385-405 + i18n 原话「只支持 HTTP 和 HTTPS 地址」）⇒ 我们要开的三个地址都合规 ✓ |
| Kimi K3 那条道通了 | `[trae] … DONE … out=…/kimi.md`，回话 `Kimi-K3 收到：Kimi-K3` ✓ |
| GLM-5.3 那条道在用 | 卡 244/245/246 都是 `--model glm-5.3-flash` 派出去的 ✓ |

## 四、明知还没做 / 还在路上（**别当成已完成** ✗）

| 项 | 状态 |
|---|---|
| 右栏**常驻**页签（`keepMounted`）· 包级显示链路（`icon.svg` + `locale` 的 meta + 两个导出）· **底部入口**（绕时序坑） | **卡 247**：规格已写好（含开工前复核结论），**等卡 244 腾出同一个文件再派** ⏳ |
| 面板的 `openTabIn` 逃生门 · `peerDependencies["@deepseek-ai/dsh"]` · 包内图标 · 右栏页签 | **卡 244 正在跑** ⏳ |
| Trae 驱动器两处硬伤（模型下拉要滚到可见 / 发送必须核验） | **卡 245 正在跑** ⏳（真机那步由主控代跑 ✓ 已验通 Kimi ✓） |
| 三个候选的源码级深读（widgets / gating-hub / pilot） | **卡 246 正在跑** ⏳ |
| **面板在真 DSH 里的实际观感**（图标好不好看、右侧栏顺不顺手） | ★ **只有你重启后才能判** —— 主控没有你的眼睛 ✓ |

## 五、要退回旧样子怎么做（都可逆）

| 想退的 | 怎么做 |
|---|---|
| 退掉市场 | `dsh plugin --profile desktop remove dshmarket` |
| 退掉面板那一行 | 从 `~/.dsh/profiles/desktop/package.json` 的 `dsh.profile.bundles` 里删掉 `dsh-client-ui-workbench-panel`（备份：`.bak-before-bundle-*`） |
| 退回旧的 profile 写法 | `cordis.patch.yml` 与 `package.json` 各有 `.bak-before-*` 备份 ✓（`cp` 回去即可） |
