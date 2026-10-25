#!/bin/bash
# 把一张卡的「落地门禁」搬到云机跑、产物回传（卡 E35 · T-AG489；从 gates/diag/ 搬入库）。
#
# 用法（本机 Git Bash）：
#   TF_PROJECTS_TOML=<云机上的项目索引路径> bash scripts/cloud/run_gate.sh <卡号> [端口段]
#
# 为什么在库里：原来这份脚本住在 gates/diag/，而 `.gitignore` 的 `gates/diag/*` 把整个目录
# 忽略 ⇒「云机怎么跑门禁」只存在某台机器的磁盘上，换台机器就没有这件事。现在它是被 review 的源码。
#
# 三条口径（卡 E35 判据）：
#   ① 清树用 `git clean -xfdq`（**带 -x**）。不带 -x 时上一趟的 `gates/last.json` 与
#      `gates/logs/` 会留在盘上（它们是被忽略文件），被这一趟读成「上一轮的判定」⇒
#      自指钉子（test_false_success_pins / test_gates_reuse_line）必红。实测踩过。
#   ② 跑之前**断言 `gates/last.json` 不存在**：存在就报错退出（绝不静默沿用上一趟的判定）。
#   ③ 仓外配置（TF_PROJECTS_TOML 等）显式注入，**缺了就报错不跑**（fail fast）——
#      不许「跑一半发现没配」。
#
# 前提：卡树 `.wt/<卡号>` 已存在且已 realign 到当前主树 HEAD；云机 SSH 可用（~/.ssh/id_ed25519_cloud）。
set -u

# ---------------------------------------------------------------- 残留断言（可单测）
# 单独抽成函数：tests/test_cloud_sync.py::test_run_gate_refuses_residual_last_json
# 用 `--check-residue <目录>` 直接打这一针（不必真连云机）。
residue_of() { printf '%s/gates/last.json' "${1%/}"; }

require_no_residue() {
  local dir="${1:?用法: require_no_residue <目录>}"
  local victim
  victim="$(residue_of "$dir")"
  if [ -e "$victim" ]; then
    echo "✗ 残留：$victim 存在 —— 上一趟的判定会被这一趟读到（假绿/假红都算）。" >&2
    echo "  处置：清树要带 -x（git clean -xfdq），或换一个干净的 checkout。本脚本不静默沿用。" >&2
    return 2
  fi
  return 0
}

if [ "${1:-}" = "--check-residue" ]; then
  require_no_residue "${2:?用法: run_gate.sh --check-residue <目录>}"
  exit $?
fi

# ---------------------------------------------------------------- ③ fail fast：仓外配置
card="${1:?用法: TF_PROJECTS_TOML=<路径> bash scripts/cloud/run_gate.sh <卡号> [端口段]}"
port="${2:-9361}"
cloud_dir="${CLOUD_DIR:-C:/eng}"
projects_toml="${TF_PROJECTS_TOML:-}"
model_registry="${TF_MODEL_REGISTRY:-}"

if [ -z "$projects_toml" ]; then
  echo "✗ 缺 TF_PROJECTS_TOML：仓外项目索引必须显式注入（卡 E35 判据 3，fail fast）。" >&2
  echo "  它不在仓里（真身例：D:/repo/infra/pool/projects.toml），缺了 cloud 上" >&2
  echo "  test_pool_* / test_contract_audit 会集体红 —— 那是配置没给，不是代码坏。" >&2
  echo "  例：TF_PROJECTS_TOML='D:/池/infra/pool/projects.toml' bash scripts/cloud/run_gate.sh E35" >&2
  exit 2
fi

KEY="$HOME/.ssh/id_ed25519_cloud"
HOST="${CLOUD_HOST:-administrator@203.0.113.12}"
SSHOPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o BatchMode=yes"
TMP="$(mktemp -d)"
head="$(git rev-parse HEAD)"
short="$(git rev-parse --short HEAD)"

# 云机侧的环境注入串：TF_PROJECTS_TOML 必给；模型注册表给了就一并注入。
# （模型注册表的**真名**是 TF_MODEL_REGISTRY，不是 TF_MODELS_TOML —— 见 tools/pool/model_registry.py:69。）
envset="set \"TF_GATE_PORT_BASE=$port\" && set \"TF_PROJECTS_TOML=$projects_toml\""
if [ -n "$model_registry" ]; then
  envset="$envset && set \"TF_MODEL_REGISTRY=$model_registry\""
fi

echo "=== 0/5 把主树这条分支同步到云机（目标 $cloud_dir）==="
if [ "$cloud_dir" = "C:/eng" ]; then
  git bundle create "$TMP/inc.bundle" line/impl-v1 >/dev/null 2>&1
  echo "bundle $(wc -c < "$TMP/inc.bundle") 字节"
  scp $SSHOPTS -i "$KEY" "$TMP/inc.bundle" "$HOST:C:/inc.bundle" >/dev/null
  ssh $SSHOPTS -i "$KEY" "$HOST" "cd C:/eng && git fetch -q C:/inc.bundle line/impl-v1 && git rev-parse --short FETCH_HEAD"
else
  # 第二处 checkout：同一台机上从 C:/eng 本地 fetch，不重复传包
  ssh $SSHOPTS -i "$KEY" "$HOST" "cd $cloud_dir && git fetch -q C:/eng line/impl-v1 && git rev-parse --short FETCH_HEAD"
fi

echo "=== 0.5/5 云机侧核对仓外配置（缺就不往下走）==="
if ! ssh $SSHOPTS -i "$KEY" "$HOST" "if exist \"$projects_toml\" (exit 0) else (exit 1)"; then
  echo "✗ 云机上找不到 TF_PROJECTS_TOML：$projects_toml（fail fast，门禁一步都还没跑）" >&2
  rm -rf "$TMP"
  exit 3
fi
echo "✓ 云机侧配置就位：$projects_toml"

echo "=== 1/5 导出卡树补丁（卡片 $card @ $short）==="
git -C ".wt/$card" add -A -N
git -C ".wt/$card" diff HEAD --binary > "$TMP/$card.patch"
git -C ".wt/$card" reset -q
echo "补丁 $(wc -c < "$TMP/$card.patch") 字节 / $(grep -c '^diff --git' "$TMP/$card.patch") 个文件"

echo "=== 2/5 云机对齐到同一提交 + 清树（带 -x）+ 断言无残留 ==="
if ! ssh $SSHOPTS -i "$KEY" "$HOST" \
  "cd $cloud_dir && git checkout -f --detach $head && git clean -xfdq && if exist gates\\last.json (echo RESIDUAL_LAST_JSON & exit 4) else (git log --oneline -1)"; then
  echo "✗ 云机清树后仍有 gates/last.json 残留（或 checkout 失败）—— 不跑门禁" >&2
  rm -rf "$TMP"
  exit 4
fi

echo "=== 3/5 传补丁并应用 ==="
scp $SSHOPTS -i "$KEY" "$TMP/$card.patch" "$HOST:C:/card-$card.patch" >/dev/null
ssh $SSHOPTS -i "$KEY" "$HOST" "cd $cloud_dir && git apply --binary C:/card-$card.patch && git status --porcelain | find /c /v \"\""

echo "=== 4/5 云机跑全量门禁（端口段 $port；TF_PROJECTS_TOML 已注入）==="
start=$(date +%s)
ssh $SSHOPTS -i "$KEY" "$HOST" "cd $cloud_dir && $envset && python -X utf8 scripts/run_gates.py && python -X utf8 scripts/run_gates.py --seal" > "$TMP/gate.out" 2>&1
rc=$?
echo "门禁退出码=$rc 用时=$(( $(date +%s) - start ))s"
tail -6 "$TMP/gate.out"

echo "=== 5/5 回传 gates/last.json 与日志 ==="
mkdir -p ".wt/$card/gates/logs"
scp $SSHOPTS -i "$KEY" "$HOST:$cloud_dir/gates/last.json" ".wt/$card/gates/last.json" >/dev/null
scp $SSHOPTS -i "$KEY" "$HOST:$cloud_dir/gates/logs/*.log" ".wt/$card/gates/logs/" >/dev/null 2>&1
mkdir -p gates/diag
cp "$TMP/gate.out" "gates/diag/cloud-gate-$card.log"
python -X utf8 -c "import json,sys; d=json.load(open('.wt/$card/gates/last.json',encoding='utf-8')); print('last.json ok=',d.get('ok'),'rev=',d.get('rev'))"
echo "日志：gates/diag/cloud-gate-$card.log ；产物：.wt/$card/gates/"
rm -rf "$TMP"
exit "$rc"
