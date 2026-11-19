# 卡 A375：F82 Remote magpie —— 把另一台机器当 provider，收敛成「显式登记的远端平台」

> 台账号 `T-AG663`｜分区 A（magpie 移植 / 号池 pool）｜树 `.wt/A375`｜层 判据层 + 数据形状｜基准 `7a4cc513`（立卡时主树 HEAD，2026-11-19 23:50 实读）｜depends E94、A348
> depends 说明：**E94**（`tools/pool/gateway.py` 的七值分类 / `route_once` / 四条回环 HTTP 面 / `pick_endpoint`）是本卡唯一的落点，本卡只在它里面加一条「远端平台」分支，**不新开模块**；**A348**（`tools/pool/callers.py` 调用方名册）持有「本模块不持有凭据」这条边界，本卡不越过它去发明 gateway key。两张都已 done（`docs/workbacklog.toml:5550`、`:4777`）。
> 基准说明：起草期间主树 HEAD 动过三次（`5156b414` → `08364825` → `466a2578`），`tools/pool/gateway.py` 从 1141 行变成 **1193 行**、`tests/test_pool_gateway.py` 从 1040 行变成 **1150 行**（并行工人在改同一批文件）。**本文行号以 `466a2578` 逐条重核过**；落地前仍须按当时 HEAD 再核一遍。
> 依据：`gates/diag/_magpie_scope.md:90` 逐字「| F82 | Remote magpie：把另一台机器当 provider | PORT | no | 无跨机 provider 概念（同协议远端转发，不违红线） |」；magpie 原件 `D:/repo/program/_ext/_magpie_features.md:688-693`；源码 `D:/repo/program/_ext/magpie-main/` 下 `internal/provider/remote_magpie.go`、`internal/gateway/remote_magpie.go`、`internal/provider/remote_quotas.go`、`internal/provider/remote_key_limits.go`、`internal/gateway/quotas_scope.go`、`internal/gateway/allow.go`、`internal/access/access.go`。

## 前情

- magpie 那条功能清单逐字（`_magpie_features.md:690-692`）：「解决：办公室那台有很多账号，家里这台不想再登一遍。｜入口：Settings → Network and sharing → Share on local network；magpie provider add remote-magpie sk-magpie-… url=http://192.168.1.20:3425 id=office；远端模型 id office/relay-a/claude-sonnet-5；GET /v1/magpie/quotas/cards、POST /v1/magpie/quotas/refresh（每卡最多 **30 秒**一次）。｜实现：internal/gateway/remote_magpie.go、internal/provider/remote_key_limits.go（RemoteKeyLimitPath）、internal/gateway/quotas_scope.go。」
- 它在 magpie 里是**三块**，必须分开判：
  1. **provider 类型**：`internal/provider/remote_magpie.go:68` 的 `const RemoteMagpiePreset = "remote-magpie"`、`:71` 的 `func (p Provider) IsRemoteMagpie() bool { return p.Preset == RemoteMagpiePreset }`；一个地址派生四个 base —— `:106-107` 逐字 `p.Chat, p.Responses, p.Anthropic = root+"/v1", root+"/v1", root` 与 `p.Decide = p.Chat`，做法写在 `:74-76` 的注释里：「remoteMagpieEndpoints puts every API on the address given, however it was typed: the bare host and port (plain http, which magpie serves), …/v1, or the Anthropic root.」（实现是剥掉 14 个已知后缀再拼 `/v1`）。
  2. **调用方身份跨机透传**：`internal/gateway/remote_magpie.go:27-30` 的 `AgentHeader = "X-Magpie-Agent"` / `ViaHeader = "X-Magpie-Via"`；`passOnCaller()` 把它们与 session 一起写回去，注释逐字「Only a remote magpie is sent them; a vendor never is.」，而它们「come off every request as it arrives」。
  3. **远端配额 / 钥匙限额读取**：`internal/provider/remote_quotas.go:33` `RemoteCardsPath = "/v1/magpie/quotas/cards"`、`:38` `RemoteRefreshPath = "/v1/magpie/quotas/refresh"`、`:43` `const remoteCardsFor = 30 * time.Second`；`internal/provider/remote_key_limits.go:28` `const RemoteKeyLimitPath = "/v1/magpie/limit"`；`internal/gateway/quotas_scope.go:122-133` 的 `cards()` 只外传 `q.From == ""` 的本机卡（别人的远端卡不再转手）。
- 它成立的前提是本仓**明令不做**的三件事：magpie 自己开着对 LAN 的监听面（`internal/gateway/allow.go:16-21` 包注释「the addresses other computers may reach magpie from at all, as IPs and CIDR ranges … This computer (loopback, and the computer’s own addresses) is always let in.」）、命名 gateway key（`internal/access/access.go:27-29` 的 `Prefix = "sk-magpie-key-"` / `legacyLANPrefix = "sk-magpie-"`，`:90-118` 的 `ownSecret()` 用 `subtle.ConstantTimeCompare` 校验）、allow 名单（`const AllowIPsEnv = "MAGPIE_ALLOW_IPS"`）。

## 本仓今天有没有这个东西（grep 读数，排除 `.wt/`）

**结论：不是「有代码没接线」，是完全没有。** 平台表里没有远端字段、网关里没有远端概念、派活器里没有跨机参数；唯一真实转发实现 `forward_http` 存在，但**零测试、零真机**。

- `grep -rn remote tools/pool/*.py tools/*.py` 只有两条命中，都不是本功能：`tools/pool/landing.py:1280` 的 `def mirror_remote() -> pathlib.Path | None:`（云门禁机的镜像路径）、`tools/dsh_panel.py:3154`（前端 slots 注释）。
- `grep -c remote tools/pool/platforms.toml` = **0**；`tomllib` 实读九段的键集合 = `amount_path / auth_kind / base_urls / chat_urls / claim_flow / label / local_archive / pitfalls / probe / probe_url / quota_flow / source / supported / token_env / token_file / token_key / unit / verified` —— **没有 `remote`，没有 host/port，没有「另一端机器」的任何字段**。
- 五个 magpie 专有词（`X-Magpie` / `magpie/limit` / `magpie/quotas` / `sk-magpie` / `RemoteMagpiePreset`）扫 `tools/ scripts/ tests/ docs/` ⇒ **零命中（含 tests/）**。
- `--host` / `--ssh` / `--remote` / `--transport` 在 `tools/wb_dispatch.py`（4246 行）⇒ **零命中**；派活器所有起进程都是 `subprocess.Popen` / `subprocess.run`（`:1159`、`:1193`、`:1208`、`:2536` 一带），`build_parser()`（`:3234`）那三十几个选项里没有跨机项。
- **有实现、但从来没被跑过**（最该说清的一条）：`tools/pool/gateway.py:808` 的 `def forward_http(model: str, account: str, url: str, payload: bytes, *, timeout: float = 120.0) -> Reply` 是唯一真实转发实现，`grep -rn forward_http tests/` ⇒ **零命中**（连 tests/ 都不碰它）；引用点只有 `:1112`、`:1138`、`:1093` 三个默认参数，加 `:71-78` 的 `__all__`。`docs/traceability.toml:11755` 自己写着：「九平台 chat_urls 全为空数组 —— 同协议直通这一段**没有对任何真上游跑过**（forward_http / resolve_token / _account_platform / _iter_stream 四段是桩驱动验的）」。
- 本仓对「另一台机器」的既有口径是**隧道，不是自建跨机协议**：`tools/pool/gateway.py:85` 逐字「#: 只认回环。**没有例外**：不给 0.0.0.0 开口子（远程访问走 SSH / frp 隧道）。」、`:86` `ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})`；`tools/pool/mcp_http.py:17-18`「**只绑回环（SHOULD）**：只收 127.0.0.1 / localhost / ::1；别的值**退 2**，不给 0.0.0.0 开口子（要暴露交给隧道）。」
- 另有五处逐字写着「不跨机」，但**说的是状态文件，不是请求**：`tools/pool/ledger.py:44`「锁在 gates/diag/ledger.lock ⇒ **跨机器不互斥**」；`tools/pool/task.py:41`「**只治单机**，跨机不做也不假装能做」；`tools/pool/sticky.py:45`「**不做跨机同步**」；`tools/pool/jobs.py:477`「进程号跨重启/跨机器都不可判」；`tools/pool/quota_history.py:22`「3. 不做 magpie 的 mergeQuotaHist（跨机合并）：pool 没有多机共用一份曲线的场景」。
  ⇒ **辨析（本卡立论的支点）**：前四条与 F82 不冲突 —— 本卡让**请求**转出去，本机不存对方状态。第五条正好是 magpie F82 的第三块（把远端配额读进来），那条**撞**在本仓既有口径上 ⇒ 见缺口 5，本卡 SKIP 它。

## 缺口（逐条带现场原文与 文件:行号）

### 缺口 1 · 平台表九段无一能表达「另一端是一台机器」

`tools/pool/platforms.toml` 九段的段头行号：`:29` codearts、`:58` workbuddy、`:86` qoder、`:111` trae、`:137` minimax、`:164` lobsterai、`:185` opencode、`:205` meoo、`:231` codebuddy。每段的 `base_urls` 是**站点根**（额度 / 签到页所在），不是 provider 地址（`:39` 是 `["https://snap-access.cn-north-4.myhuaweicloud.com"]`、`:237` 是 `[]`）；九段 `chat_urls` **全空**且都写着同一条注释（`:40` / `:65` / `:93` / `:118` / `:144` / `:171` / `:192` / `:212` / `:238`：`chat_urls = []  # 空 = 没登记，不是不支持（见文件头）`）。文件头 `:13-20` 逐字：

```toml
# 各段 `chat_urls`（卡 E94）：这个平台**可以直接转发 chat 补全请求**的端点清单，
# 只放端点，不放凭据（凭据仍走 `token_env` / `token_file`）。
#   * 空数组 `[]` = **没登记**这个平台的 chat 端点，**不是**「不支持」——
#     网关遇到空表一律 403 并点名「这个平台没登记 chat 端点」，绝不退化成
#     「拿 base_urls 随便试一个」；
#   * 表里这些平台大多是 IDE / 面板的凭据，没有公开的 chat 补全入口，所以现在**全是空的**；
#   * 填之前必须真机验证过（`verified = true` 且写明 `source`），
#     否则填了也仍算 `verified = false`，网关不认。
```

★ 最后两行是一条**今天没有读者的承诺**：`grep -rn verified tools/pool_accounts.py tools/pool/gateway.py` ⇒ 零命中；`grep -rn '"supported"' tools/ scripts/` ⇒ 零命中。两个字段都只是文档。本卡若要「远端段必须 `verified = true` 才认」，**判据 1 就是给它装上的第一个读者** —— 不许只写注释。

### 缺口 2 · magpie 的「一个地址派生四个 base」直接撞本仓 `pick_endpoint` 的明令

`tools/pool/gateway.py:247-262` 逐字：

```python
def pick_endpoint(urls: Sequence[str] | None, protocol: str, *,
                  platform: str) -> tuple[str | None, str]:
    """从平台的 chat_urls 里挑一个**同协议**端点。挑不到回 (None, 点名原因)。

    ★ 另一种做法是「拿 base_urls 拼一个路径试试」—— **禁止**：base_urls 是站点根
      （额度/签到页所在），不是 chat 端点；试着发就是伪造能力。
    """
    clean = tuple(str(u).strip() for u in (urls or ()) if str(u).strip())
    if not clean:
        return None, (f"这个平台没登记 chat 端点：平台 {platform!r} 的 chat_urls 是空的"
                      "（空 = 没登记，不是不支持）")
    for url in clean:
        if endpoint_protocol(url) == protocol:
            return url, ""
    return None, (f"平台 {platform!r} 登记了端点，但没有 {protocol} 协议的端点："
                  "本网关只做同协议直通，不做协议翻译")
```

`tools/pool/gateway.py:238-244`（`endpoint_protocol`）逐字 docstring：「只看 URL 的路径尾巴判协议。认不出回空串 —— **不猜、不试、不发请求**。」

而 magpie 的 `remoteMagpieEndpoints()` 做的正是「拿用户随手敲的地址拼出四个 base」：`internal/provider/remote_magpie.go:106-107` `p.Chat, p.Responses, p.Anthropic = root+"/v1", root+"/v1", root`。这条**不许搬**（不违红线，违的是 E94 已经钉死的那条钉子）。

### 缺口 3 · 远端连不上会被当成普通 5xx，**静默换下一个号**，文案里连机器名都没有

`tools/pool/gateway.py:831-835`（`forward_http` 的连接层失败分支）逐字：

```python
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        message = f"上游连不上：{exc}"
        return Reply(status=502, headers={"Content-Type": "application/json; charset=utf-8"},
                     body=json.dumps({"error": {"type": "api_error", "message": message}},
                                     ensure_ascii=False).encode("utf-8"))
```

实测这条文案里**没有 URL、没有 host、没有平台名**：拿一个连不上的回环端口真跑一次 `urlopen`（`python -X utf8 -c`），异常字符串是 `<urlopen error timed out>`，拼出来就是 `上游连不上：<urlopen error timed out>`。

然后这个 502 落到分类器 ⇒ `KIND_SERVER` ⇒ `tools/pool/gateway.py:602` 逐字 `continue  # server / other ⇒ 换下一个号，不降权` ⇒ 换下一个账号，把同一个连不上的地址再超时一遍（`forward_http` 默认 `timeout: float = 120.0`，见 `:809`）⇒ 最后 `:677` `return _fail(protocol, 502, f"全部候选都失败了：{detail}", attempts=attempts, logged=logged)`。整条链上**没有任何一处说得出「是那台机器连不上」**。

magpie 那边口径正相反：`internal/provider/remote_quotas.go:75` `const errRemoteUnreachable = "couldn't reach the remote magpie"`，`:406` 逐字 `return fmt.Errorf("%s %s: %w", errRemoteUnreachable, remoteName(p), err)` —— **机器名进错误**。

### 缺口 4 · 「被连的那一端」整套前置本仓明令不做

F82 要成立，另一台机器必须：开一个对 LAN 的监听面、配 allow 名单、发命名 key。本仓三件都不做（见上一节逐字），且 `ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})`（`tools/pool/gateway.py:86`）把这条路封到「隧道」为止。⇒ **F82 在本仓只能是单向的**：本仓会去连别人，永远不会被连。这一条进「未坐实项 5」，落地文案里也不许暗示「本仓可被别人当 provider」。

### 缺口 5 · 远端配额 / 钥匙限额依赖 gateway key，撞 `callers.py` 的「不持有凭据」

`tools/pool/callers.py:5-7` 逐字：「1. **本模块不持有凭据**：不生成任何密钥、不做常量时间比较、不写 `0600` 权限。理由：pool 的写面是本地 stdio 的 MCP，对手是「同一台机器上的另一个进程」—— 密钥与文件权限都挡不住同一个用户；把凭据搬进来只会让人**误以为**「有它就安全」。」

而 magpie 的远端配额面要 `GET /v1/magpie/limit`（`remote_key_limits.go:28`）与 `GET /v1/magpie/quotas/cards`（`remote_quotas.go:33`），且 `remote_key_limits.go:140-176` 的 `remoteKeyCardOf` 缓存键是 `p.ID + "\x00" + keyID(key)` —— **一切以「我们有那把 key」为前提**。再加上 `tools/pool/quota_history.py:22` 已立的「不做跨机合并」，这一块在本仓**没有落点**。

### 缺口 6 · 网关照旧不知道「哪些平台是远端」，因为平台表里没有这个字段

`tools/pool/gateway.py:680-687`（`_platform_endpoints`，全仓唯一的生产读者：`grep -rn _platform_endpoints tools/` 只有定义 `:680` 与调用 `:533` 两处，tests/ 只有 `:625` 的 monkeypatch）逐字：

```python
def _platform_endpoints() -> dict[str, list[str]]:
    """读 platforms.toml 的 chat_urls（只放端点，不放凭据）。"""
    table = pool_accounts.load_platforms()
    out: dict[str, list[str]] = {}
    for name, row in table.items():
        urls = row.get("chat_urls") if isinstance(row, dict) else None
        out[str(name)] = [str(u) for u in (urls or [])]
    return out
```

它只回 URL，**丢掉了「这一段是不是远端」这半个事实** —— 所以 `route_once`（`:494-503`）即使拿到端点，也没有任何依据做「远端失败不换号」的分支。

## 判据（六条，逐条给「怎么证明」）

### 判据 1 · 远端 = 平台表里**显式登记的一段**，一段一址，且只多这一段

`tools/pool/platforms.toml` 新增**恰好一段** `[platform.remote-magpie]`，必须同时满足：`remote = true`、`auth_kind = "bearer"`、`token_env` 非空、`base_urls = []`、`chat_urls` **恰好一条**且 `gateway.endpoint_protocol(那条) == "chat"`、`source` 匹配既有正则（`tests/test_pool_accounts.py:666` 用的 `^(github:[\w.-]+/[\w.-]+/\S+:\S+|local:\S+:\d+)$`）、`verified = true`。其余九段**一个字节都不许动**（`chat_urls` 仍为 `[]`，仍无 `remote` 键）。

**怎么证明**：新建 本卡新建的测试文件里那条 test_remote_platform_is_registered_explicitly，体例照 `tests/test_pool_gateway.py:233-241`（读真文件 + `tomllib`，不桩）：

```python
data = tomllib.loads((ROOT / "tools" / "pool" / "platforms.toml").read_text(encoding="utf-8"))
rows = data["platform"]
assert len(rows) == 10, sorted(rows)
row = rows["remote-magpie"]
assert row["remote"] is True and row["auth_kind"] == "bearer"
assert row["base_urls"] == [] and len(row["chat_urls"]) == 1
assert gateway.endpoint_protocol(row["chat_urls"][0]) == "chat"
assert re.match(r"^(github:[\w.-]+/[\w.-]+/\S+:\S+|local:\S+:\d+)$", row["source"])
assert row["verified"] is True and row["token_env"].strip()
for name, other in rows.items():
    if name != "remote-magpie":
        assert other["chat_urls"] == [] and other.get("remote") is not True, name
```

★ 同一张卡里必须改 `tests/test_pool_gateway.py:240` 的 `assert len(platforms) == 9, sorted(platforms)` 与 `:234` 那句 docstring「九平台各有一列 `chat_urls`，且**全空**」，以及文件头钉子表 `:12` 同一句话 —— `grep -rn len(platforms) tests/ tools/ scripts/` 实读**全仓只有这一处**，没有第二个投影。

### 判据 2 · 一个地址**不派生**第二个端点（反向钉 magpie 的 `remoteMagpieEndpoints`）

**怎么证明**：同文件 `test_remote_address_never_derives_a_second_endpoint`（与既有 `tests/test_pool_gateway.py:258-268` 同形，只换平台名与地址）：

```python
root = "https://magpie.example.test:3425"          # 裸根：magpie 那边会派生出 /v1
assert gateway.endpoint_protocol(root) == ""
assert gateway.pick_endpoint((root,), "chat", platform="remote-magpie")[0] is None
assert "不做协议翻译" in gateway.pick_endpoint((root,), "chat", platform="remote-magpie")[1]
assert gateway.endpoint_protocol(root + "/v1") == ""
assert gateway.pick_endpoint((root + "/v1/messages",), "chat", platform="remote-magpie")[0] is None
one = "https://magpie.example.test:3425/v1/chat/completions"
assert gateway.pick_endpoint((one,), "chat", platform="remote-magpie") == (one, "")
assert gateway.pick_endpoint((one,), "messages", platform="remote-magpie")[0] is None
```

### 判据 3 · 远端连不上 ⇒ 点名那台机器，且**不静默换号**（本卡最难的一条）

两条都要：(a) `forward_http` 的连接层失败文案必须带 `urlsplit(url).netloc`；(b) `route_once` 在「远端平台 + 连接层失败」时**当场停**，不再拿同一个地址去问下一个号（`forward_http` 默认 `timeout: float = 120.0`，`:809`；换 N 个号就是把 120 秒乘 N；今天的口径恰好相反，见 `tests/test_pool_gateway.py:443` 那条「继续换下一个号」）。

**怎么证明**：(a) 真 socket、仍在回环 —— 一个只 listen 不 accept 的裸 socket，体例照 `tests/test_serve_port.py:52-66` 的 `class _BareSocket`；(b) 桩 + 新参数。

```python
# (a)
with _BareSocket() as bare:
    reply = gateway.forward_http("m", "seat", f"http://127.0.0.1:{bare.port}/v1/chat/completions",
                                 b"{}", timeout=0.3)
assert reply.status == 502
body = reply.body.decode("utf-8")
assert f"127.0.0.1:{bare.port}" in body
assert "上游连不上" in body

# (b) 远端平台的一次连接层失败之后，第二个号一次都不许试
class _Unreachable:
    calls = 0
    def __call__(self, model, account, url, payload):
        type(self).calls += 1
        return gateway.Reply(status=502, headers={"Content-Type": "application/json"},
                             body=b'{"error":{"type":"api_error","message":"上游连不上：<urlopen error timed out>"}}')
fwd = _Unreachable()
out = _run(env, fwd, rows=(_row("remote-1", platform="remote-magpie"),
                           _row("remote-2", platform="remote-magpie")),
           endpoints={"remote-magpie": ["https://magpie.example.test:3425/v1/chat/completions"]},
           remote={"remote-magpie"})
assert out.status == 502 and fwd.calls == 1          # 没换号
assert "全部候选都失败了" in out.body.decode("utf-8")
```

★ **不许发明第八个 kind 来做这件事**：`tools/pool/gateway.py:135` 逐字「#: 七值闭集：**不许发明第八个**（卡 E94 判据 1）。」，既有钉子 `tests/test_pool_gateway.py:148-150` 断言 `gateway.KINDS == ("rate","quota","auth","overflow","server","bad_request","other")`。本卡的判定走「平台是不是远端」+「文案是不是连接层失败」两个既有事实，**不动闭集**。

### 判据 4 · 凭据只走 `token_env`，不新造 key 体系

**怎么证明**：同文件 `test_remote_token_comes_only_from_env` + 一条 grep 断言。

```python
monkeypatch.delenv("TF_POOL_REMOTE_MAGPIE_TOKEN", raising=False)
with pytest.raises(gateway.ConfigError) as ei:
    gateway.resolve_token("remote-magpie")
assert "凭据不在 env 里" in str(ei.value)
monkeypatch.setenv("TF_POOL_REMOTE_MAGPIE_TOKEN", "tkn")
assert gateway.resolve_token("remote-magpie") == "tkn"
```

```bash
grep -n "sk-magpie\|X-Magpie-\|compare_digest\|chmod" tools/pool/gateway.py tools/pool/platforms.toml   # 必须无输出
```

第二条照 `tests/test_pool_callers.py:214-217` 的既有钉法（那条对 `callers.py` 断言 `compare_digest / Bearer / chmod / secret / masked` 零命中）；`platforms.toml` 无凭据形状的既有钉子 `tests/test_pool_accounts.py:261`（`assert "Bearer " not in text` + `SECRET_RE`）本卡**不放宽**。

### 判据 5 · 「不移植」的三块钉成可核证据（SKIP 论证，不是空口）

| 不移植的块 | 为什么 | 怎么钉 |
|---|---|---|
| magpie 的一址派生四 base（`remote_magpie.go:89-107` 剥 14 个后缀 + `root+"/v1"`） | 撞 E94 的「不猜、不试、不发请求」（`gateway.py:239`、`:251`） | 判据 2 的五条 None 断言 |
| `X-Magpie-Agent` / `X-Magpie-Via` 跨机身份透传 | 本仓 `X-Pool-Caller`（`gateway.py:1025`）是**纯标签**，没有 key 可证身；本仓明令不持有凭据 | `grep -rn` 零命中 + 一条 `@pytest.mark.xfail(strict=True, reason="F82 不移植跨机身份")` 包住的「应零命中」断言（真出现即 xpass ⇒ 红） |
| `/v1/magpie/limit`、`/v1/magpie/quotas/cards|refresh` 远端配额转发 | 撞 `quota_history.py:22`「不做跨机合并」+ `callers.py:5-7` 不持有凭据 | `grep -rn "magpie/limit\|magpie/quotas\|RemoteCardsPath" tools/ scripts/` 零命中；`assert set(gateway.PATHS) == {"/v1/chat/completions","/v1/messages","/v1/models","/v1/pool/routes"}` |

另加两条「边界没被挪动」的断言：`gateway.ALLOWED_HOSTS == frozenset({"127.0.0.1","localhost","::1"})` 与 `build_server(host="0.0.0.0", ...)` 抛 `ConfigError`（既有钉子 `tests/test_pool_gateway.py:517`/`:538` 已经咬住，本卡只复核、不重写）；`wb_dispatch.build_parser()` 的选项串里没有 `--host/--ssh/--remote/--transport`（**新钉子**，读真 parser，不读源码文本）。

### 判据 6 · 反向变异 ≥3 条（真改真跑真复原，sha256 自证）+ 一条安静对照

脚本落 `gates/diag/_rev_F82.py`（体例照 `gates/diag/_rev_A368.py`，末行打「结论：N/N 条全部咬住，收尾绿。」）。每条改前存 sha256、改后跑指定用例、复原后再核 sha256。

| # | 改哪一行（锚点原文） | 哪条判据红 |
|---|---|---|
| ① | `tools/pool/gateway.py:602` 的 `continue  # server / other ⇒ 换下一个号，不降权` —— 把远端分支撤掉，让远端失败也走到这里 | 判据 3(b)：`fwd.calls == 1` 变 2 |
| ② | `tools/pool/gateway.py:832` 的 `message = f"上游连不上：{exc}"` —— 改回不含 netloc | 判据 3(a)：`127.0.0.1:{port}` 断言红 |
| ③ | `tools/pool/platforms.toml` 远端段的 `chat_urls` 加第二条（另一个 host 的同协议端点） | 判据 1：`len(row["chat_urls"]) == 1` 红 |
| ④ | **安静对照**：只改 `tools/pool/gateway.py:85` 那条注释（`#: 只认回环。**没有例外**：…` 换措辞） | 六条**全绿**；若不绿，说明有判据在读注释，是假钉子 |
| ⑤ | **外部钉子**（证明既有判据没被放宽）：给 `classify` 加 `KIND_REMOTE = "remote"` 并塞进 `KINDS` | 既有 `tests/test_pool_gateway.py:148-150` 当场红 |
| ⑥ | 把 `tools/pool/gateway.py:251` 那句「拿 base_urls 拼一个路径试试 —— **禁止**」删掉，改成从 `base_urls` 兜底拼 `/v1` | 判据 2 的 `pick_endpoint((root,), "chat", …)[0] is None` 红 |

## 交付（逐文件，精确路径）

- `tools/pool/platforms.toml` —— 加 `[platform.remote-magpie]` 一段（判据 1 的八个字段）；文件头 `:13-20` 补两句：「`remote = true` 是什么意思」「为什么一个远端段只许一条 `chat_urls`」；`[meta] updated_at` 改当天。
- `tools/pool/gateway.py` —— ① `forward_http` 的连接层失败文案带 `urlsplit(url).netloc`（判据 3a，锚点 `:832`）；② 新增 `_remote_platforms() -> frozenset[str]`（读 platforms.toml 的 `remote` 布尔，体例照 `_platform_endpoints()` `:680-687`）；③ `route_once` 加一个默认 `None` 的关键字参数 `remote: Collection[str] | None = None`（None ⇒ 现读文件，与 `endpoints` 同体例），命中「远端 + 连接层失败」时 `break`；④ 导出新名字时同步 `__all__`（`:71-78`）。
- tests/test_pool_gateway_remote.py（新建）—— 判据 1/2/3/4/5 的钉子；全用桩 + 回环 socket，**出网零字节**（体例照 `tests/test_pool_gateway.py:30`「★ 全部用桩 … 一个字节都不出网」）。
- `tests/test_pool_gateway.py` —— **只改一处**：`test_platform_table_chat_urls_all_empty`（`:233-241`）的 `assert len(platforms) == 9` → `== 10`，并把 `:234` docstring 与文件头钉子表 `:12` 那句「九平台 … 全空」改成「除远端段外全空」。其余钉子**一个字都不许动**。
- `docs/subsystems/pool/modules.toml` —— `:247` 的 duty「九个平台的端点」→「十个平台（含一个远端 magpie）」；`:57` 的 `gateway.py` duty 补一句「远端平台的连接层失败不换号、文案带机器」。
- `docs/subsystems/pool/README.md` —— **只许**由 `python -X utf8 scripts/gen_pool_readme.py` 重写（`<!-- pool-margin:begin -->` 与 `<!-- pool-margin:end -->` 之间），**不许手改**。
- `复盘/卡/卡A375-F82远端provider显式登记.md` —— 本卡规格（本草稿转正）。
- docs/changelog.d/T-AG663.md —— 一条。
- `docs/workbacklog.toml` —— `[[cards]]` 条目（id/task/title/tree/spec/files/depends/risk/status，体例照 `:6476` 的 A368）。

卡域 `files`（精确字符串，供 `docs/workbacklog.toml`；`tools/pool/plan.py:284-291` 拒通配、按精确字符串相交判冲突）：

```toml
files = [
  "tools/pool/platforms.toml",
  "tools/pool/gateway.py",
  "tests/test_pool_gateway.py",
  "tests/test_pool_gateway_remote.py",
  "docs/subsystems/pool/modules.toml",
  "docs/subsystems/pool/README.md",
  "复盘/卡/卡A375-F82远端provider显式登记.md",
  "docs/changelog.d/T-AG663.md",
  "docs/workbacklog.toml",
]
```

★ `docs/subsystems/pool/README.md` 落在生成器标记之间，改它必须走生成器（`scripts/gen_pool_readme.py --check` 退 0 才算数）；`docs/workbacklog.toml` 只加本卡自己的条目。

## 验收

```bash
cd .wt/A375
python -X utf8 -m pytest tests/test_pool_gateway_remote.py tests/test_pool_gateway.py \
    tests/test_pool_accounts.py tests/test_pool_callers.py -q -o addopts= --no-cov
python -X utf8 -m ruff check tools/pool/gateway.py tests/test_pool_gateway_remote.py
python -X utf8 scripts/gen_pool_readme.py --check          # 退 0
python -X utf8 -c "from pool import gateway; assert len(gateway.PATHS) == 4; assert gateway.ALLOWED_HOSTS == frozenset({'127.0.0.1','localhost','::1'})"
python -X utf8 gates/diag/_rev_F82.py                       # 末行：「结论：N/N 条全部咬住，收尾绿。」
```

已知噪音：`tests/test_pool_gateway.py` 现有的七十来条钉子里有一批直接断言「只绑回环 / 四条 PATHS / 从不猜端点」（`:258-268`、`:517-570`、`:673-870` 的真 socket 段），本卡**一条都不许放宽** —— 判据 5 就是靠它们守住的。另：`tests/test_pool_jobs.py:368` 的 `test_gen_pool_readme_check_is_green` 会在 README 与 `modules.toml` 不同步时红，那是设计意图（先跑生成器）。

## 不许做

- **不许**动 `tests/test_pool_gateway.py` 里除 `test_platform_table_chat_urls_all_empty` 之外的任何断言，尤其 `test_pick_endpoint_never_guesses_from_base_url`（`:258-268`）、`test_empty_chat_urls_is_403_and_named`（`:247`）、`test_kind_vocabulary_is_seven_values`（`:148-150`）、`test_forward_exception_does_not_kill_the_gateway`（`:443-459`）。
- **不许**给 `KINDS` 加第八个值（`tools/pool/gateway.py:135` 逐字「不许发明第八个」）。
- **不许**改 `pick_endpoint` / `endpoint_protocol` 的语义（不猜、不试、不发请求，`gateway.py:239`、`:251`），也不许让它们读 `base_urls`。
- **不许**改 `ALLOWED_HOSTS` / `check_host` / `build_server` 的回环口径（`gateway.py:85-86`、`:861`）；不许为 F82 给网关开第二个监听口或绑非回环地址。
- **不许**搬 magpie 的 `remoteMagpieEndpoints`（14 个后缀剥除 + `root+"/v1"` 派生四 base）与 `passOnCaller`（`X-Magpie-Agent` / `X-Magpie-Via`）。
- **不许**引入 gateway key 的签发 / 校验 / 常量时间比较；**不许**新建 `remote.toml` 之类的第二份平台表 —— 平台的唯一真源是 `tools/pool/platforms.toml`。
- **不许**调 `/v1/magpie/limit`、`/v1/magpie/quotas/cards`、`/v1/magpie/quotas/refresh`；**不许**给 `gateway.PATHS`（`:98-103`）加第五条路径。
- **不许**改 `tools/wb_dispatch.py` 的派活路径（不加 `--host` / `--ssh` / `--remote`；跨机派活不在本卡域内）。
- **不许**手改 `docs/subsystems/pool/README.md` 标记之间那一段，也不许改 `scripts/gen_pool_readme.py` 的判据来「让它绿」。
- **不许**碰 `tools/pool/plan.py:46-53` 的六份 `PROTECTED_FILES`（`docs/traceability.toml`、`docs/changelog.md`、`复盘/交接-重构进度.md`、`复盘/新窗口交接卡.md`、`gates/last.json`、`gates/reuse.json`）；卡域 `files` 不许写通配（`plan.py:284-291`）。
- **不许**改仓外任何文件：`D:/repo/infra/**`（账本、`callers.toml`、策略文件）一个字节都不动；本卡**不许**往里加「远端账号」。
- **不许**伪造 `local_archive`：`gates/diag/repos/ref` 下**没有** magpie 存档（实读只有 dsh-codearts-auth / dsh-credit-hub / dsh-multi-agent-gateway / dsh-workbuddy-trae-qoder-connect），所以远端段只写 `source = "github:yetone/magpie/..."`（上游 `go.mod` 首行 `module github.com/yetone/magpie`），不写 `local_archive`。

## 与本仓已完成卡的关系

- **E94**（号池网关，done）：本卡是它判据面上的一小块，落点全在 `gateway.py` / `platforms.toml` / `tests/test_pool_gateway.py` 三份文件里；**不改**它的四条硬边界（`gateway.py:7-14`：不做协议翻译 / 不做凭据发现 / 不做定时器 / 不复制判据）。
- **A348**（调用方名册，done）：本卡不碰 `callers.py`，只在立论上借用它的「不持有凭据」。
- **E103**（路由名归一，done）：本卡不动 `--routing` 的任何取值。
- **A365**（MCP HTTP 传输，done）：它已经立了「要暴露交给隧道」；本卡是**反方向**（去连别人），不冲突。

## 未坐实项（草稿如实标注，别当成结论）

1. **行号漂移**：勘察期间主树 HEAD 动过三次（`5156b414` → `08364825` → `466a2578`），`tools/pool/gateway.py` 1141 → 1193 行、`tests/test_pool_gateway.py` 1040 → 1150 行。本文行号是按 `466a2578` 逐条重核的，**落地前仍须再核一遍**。
2. **一条 pytest 都没跑**（本卡禁令）⇒ 六条判据是「设计成可跑」，不是「今天已验证通过」。判据 3(b) 依赖新增的 `remote=` 参数，属**待实现**，不是既有行为。
3. **`verified` 与 `supported` 两个平台字段今天零读者**（grep 实读）；判据 1 给 `verified` 装的是**第一个读者**，`supported` 仍无 —— 本卡不假装它俩已被执行。
4. **magpie 侧只读源码，没跑实例**：本仓 `POST /v1/chat/completions` 与 magpie 的 `POST /v1/chat/completions`（`internal/gateway/gateway.go:799` 路由注册；远端配额面在 `:780-785`）是否字节级兼容，**未真机验证**。
5. **单向**：本仓不提供「被连的那一端」（不开 LAN 监听、无 allow 名单、无命名 key）⇒ F82 在本仓永远是「去连另一台跑着 magpie 的机器」。落地文案不许暗示本仓可被别人当 provider。
6. **卡号 / 台账号已定**：`A375` / `T-AG663` / `.wt/A375`（立卡时主树 HEAD `7a4cc513`，队列里最大 A 卡号当时是 A372，本卡顺延取 A373–A375）。
7. **判据 3(a) 的「连不上」是回环裸 socket 造的**，与「另一台机器掉线」在 TCP 层同形但不完全同因（DNS / 路由 / 防火墙 / 中间设备剪连接不在覆盖内）；这一类要真机验，本卡不声称覆盖。
8. **`remote = true` 是本卡新造的字段名**（magpie 侧对应物是 `Provider.Preset == "remote-magpie"`，见 `internal/provider/remote_magpie.go:68-71`）；本仓没有既有命名可照，若立卡时改用别的名字，判据 1 与 `_remote_platforms()` 要同步改 —— 但**只能有一个名字**，不许出现第二种口径。
