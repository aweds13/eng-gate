# 卡 A277 —— 面板路由 404 第二跳：cordis 4 里 apply 必须用第二形参拿 config

## 现象（真机）

面板 UI 能显示，但客户端现读全部报「服现读失败」；`GET /dsh-panel/stack-status` → 404 空体。
卡 A275 修了 `inject` 声明与 `ctx.webServer.register`，404 依旧。

探针插件把宿主半的 `apply(ctx)` 调起来，拿到原样异常：

```
Error: cannot get property "config" without inject
    at Module.apply (…/dsh-client-ui-workbench-panel/lib/index.js:316:25)
```

## 根因

cordis 4 里 `ctx.config` 是**要 inject 才允许取的属性**。插件行的 config 已经作为数据写进补丁层
（`root:`），但入口是 `apply(ctx, config)` 的**第二个形参**。读 `ctx.config` 会在 apply 第一行
抛异常 ⇒ `ctx.webServer.register` / `ctx.tools.register` 一行都没跑 ⇒ 面板能显示、路由全 404。

## 改法

- `tools/dsh_panel.py` 宿主半：`export function apply(ctx, config)`，根取 `config?.root`。
- 自检两条钉子：必须有 `apply(ctx, config)`；出现 `ctx?.config?.root` / `ctx.config.root` 判红。
- `tools/verify_panel_routes.py` 进仓（原来在 gitignore 的 `gates/diag/` 里，等于没有回归钉子）。

## 证据（2026-10-17 真机）

probe profile（`--profile probe --port 54399`）装同一份包：

```
✓ /dsh-panel/stack-status    → HTTP 200 {"ok":true,…}
✓ /dsh-panel/skills          → HTTP 200 {"ok":true,"items":[…]}
✓ /dsh-panel/workbench-board → HTTP 200 {"ok":true,"reading":{…}}
[OK ] 运行时路由全绿：宿主半已加载。
```

修前同端口同脚本：三条全 404。

## 坑

- 探端口前先确认端口是**本次实例**：旧实例占着时新实例静默 bind 失败退出（exit 0），探测全打在旧代码上。
- `package.json` 带 UTF-8 BOM 会让宿主启动直接失败。
- 同机 `dsh-panel-wenyou` 也有同样的 `ctx.config` 写法，会让整个 profile 启动失败（不在本卡范围）。
