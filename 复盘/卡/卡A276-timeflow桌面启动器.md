# 卡 A276 —— timeflow 桌面启动器

## 为什么
timeflow 是用户自己的个人管理工具，**不该依赖 DSH 开着**。要求：桌面有图标、双击即用、
不弹黑窗、起完自动打开页面。

## 做了什么
- `tools/launch_timeflow.pyw`（`.pyw` ⇒ 由 `pythonw.exe` 运行，不弹控制台）：
  1. 先探 `127.0.0.1:8520`；已在听 ⇒ 直接开浏览器（**幂等**，不重复起服务）；
  2. 没起 ⇒ `subprocess.Popen([sys.executable, "tools/stack.py", "start", "timeflow"],
     creationflags=CREATE_NO_WINDOW, stdout/stderr=DEVNULL, cwd=<仓库根>)`；
  3. 等端口最多 20 秒；等不到弹 `tkinter.messagebox.showerror`（附手动排查命令与日志路径），
     **不静默失败**；
  4. `TF_LAUNCH_DRY=1` 时只起服务、不开浏览器（无人值守自测用）。
- `tests/test_launch_timeflow.py`：只读源码的三条钉子（.pyw / CREATE_NO_WINDOW /
  幂等 + 失败可见 + dry 开关）。

## 桌面快捷方式（本机已建，不进仓库）
桌面快捷方式指向 `pythonw.exe` + 本启动器；图标是本机生成的沙漏 ico（gitignored 产物）。
具体路径写在启动器注释与交接文档里，不落进仓库（用户资产）。

## 判据
- `pytest tests/test_launch_timeflow.py -q --no-cov` = 3 passed；
- `ruff check tests/test_launch_timeflow.py` 干净；
- 实测（dry）：退出码 0 → 8520 起来 → `stack.py stop timeflow` 还原。
