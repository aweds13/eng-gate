# 卡 155 —— **`profile check --run` 的判据是假绿源**：`duration_ms` ≠ 已登录（T-G255）

> ★ **本卡在 `infra` 仓执行**（`D:/repo\infra\pool\codebuddy_accounts.py`），
> **不进 timeflow 仓的队列、不走本仓那 17 道门**。本文件是**留档**（放在本仓 `复盘/卡/` 只为可追溯）。
> 本仓对它的要求只有一条：**别在别处再抄一份这个判据**。

**成员号**：任务 `B-SUBTYPE` 的 **M-1**（在 `infra` 仓里交；本仓无预声明）

## 来路（2026-10-02 晚：判据自己会错）

`infra/pool/codebuddy_accounts.py::cmd_profile_check` 现在这么判：

```python
if "Authentication required" in blob:
    ...  # 判定「未登录」
if "duration_ms" in blob:
    ...  # 判定「已经登录（拿到会话了）」
```

★ **`duration_ms` 不是「成功」的证据** —— 它是 CLI 的**计时字段**，
**429 限流的响应里也可能带它**。也就是说：**拿它当「已登录」，会在 429 的时候给出假绿。**

★ 反过来那半也不好：真因认不出时它只打一行「**? 没认出结果（退出码 N）**」，
**既不告诉人怎么办、也不区分「探失败」与「没登录」** —— 与**卡 154**（派活器那侧）是**同一条缝**。

## 正确判据（本会话已实测过）

解析 `result` 事件，**看 `subtype == "success"`**：

```python
# 实测过的判法（2026-10-02 夜）
# 输出可能是「多个 JSON 文档拼在一起」—— 别 json.loads 整个 blob，要逐段 raw_decode
dec = json.JSONDecoder(); i = 0; sub = None
while i < len(raw):
    while i < len(raw) and raw[i] in " \r\n\t": i += 1
    if i >= len(raw): break
    try: obj, j = dec.raw_decode(raw, i)
    except Exception: break
    if isinstance(obj, list):
        for el in obj:
            if isinstance(el, dict) and el.get("type") == "result":
                sub = el.get("subtype")
    i = j
# 登录有效 ⇔ sub == "success"
```

★ **顺手把「逐段 raw_decode」这件事也钉住** —— 当晚我用 `json.loads` 直接解整块，被 `Extra data`
打回来一次（CLI 的 `--output-format json` 输出是**多段**的）。这是个**真实咬过一次**的坑。

## 要做的事（三件）

1. **判据换成 `subtype == "success"`**（上面的判法）；`duration_ms` 只准当**辅助读数**（打印出来给人看），
   **不许**再当「已登录」的依据。
2. **三态**（与卡 154 对齐，口径别写第二份）：`success` ⇒ 登录有效；`Authentication required` ⇒ 真没登录；
   其余（解析失败 / 超时 / 非零退出 / 没有 result 事件）⇒ **「没能得出结论」**，要单独报，**不许**归到「未登录」。
3. ★ **加反例钉子**（`infra` 仓自己的自检 / 用例）：造三段**假的** CLI 输出 ——
   ① `result.subtype=success` ⇒ 判「已登录」；
   ② 含 `Authentication required`（**同时**含 `duration_ms`）⇒ 判「未登录」（★ 这条专治假绿）；
   ③ 带 `duration_ms` 但**没有** `result` / `subtype` 不是 success ⇒ **判「没能得出结论」**，不许判「已登录」。
   ★ 这三条钉子就是「**判据自己会错**」这个病根的解药 —— **没有它们，改完还是没人能证明它有牙。**

## 验收（照这个报）

- `python -X utf8 -m py_compile pool/codebuddy_accounts.py`；`infra` 仓自己的自检（若有）尾行；
- ★ 真读数（**只读、不改任何号的登录态**）：拿**当前**那个 profile 跑一次 `profile check --run`，
  贴**原样输出**，并指出它现在归到哪一态；
- ★ **不许**为了跑测试去登出 / 重登任何号（备用号是**别人**的，动了就是越界）。

## 禁区

- 只改 `infra` 仓：`pool/codebuddy_accounts.py` + 它自己的自检/用例。
- ★ **不许**动 `~/codebuddy-accounts/` 下任何 profile 的登录态（不是你的东西）。
- 不许把「登录态固化」那套（`save`/`use`）**当成**能恢复登录的手段 —— 见
  `infra/复盘-登录态固化与并存.md`：**整树拷贝也在演练里失败过**，正解是**并存**（一个号一个家）。

## 边界（如实写）

- 本卡**不解决**「登录为什么短命/翻来覆去」这个根因 —— **至今没量到**，不许编。
- 本卡只保证：**判据不再假绿**、**三态分得开**。
