"""一次性脚本：全量挖「复盘里反复出现、但 skills 里没有」的操作性结论。

可复核的口径（写进 INDEX.md 的「怎么算的」一节）：
  · 频次 = **命中文档数**：一篇复盘里 claim.musts 的词全部出现（AND 语义）、且没有 neg 词，
    才算「这篇讲到了这条」。词是我从标题/结论句里挑的，写在 claim 上，可逐条复算。
  · 覆盖 = 在 `skills/**/SKILL.md|NOTES.md` 与 `softeng-manage/references/*.md` 里 grep
    claim.cover 的短语：全无 ⇒ none；只命中泛词/一句话带过 ⇒ partial（人判，附证据行）；
    真有对应的操作步骤 ⇒ full。
  · 优先级：P0 = n≥3 且 cover=none 且 有可执行命令/具体读数；
            P1 = n≥3 且 cover=none 但无命令，或 n=1~2 但属于高代价事故根因；
            P2 = 其余（n<3 且非事故，或 cover=partial 的补强项）。

输出：gates/diag/retro_gaps.json（诊断产物，不入库）
用法：python -X utf8 scripts/retro/retro_gaps.py [--all] [--id ID] [--full]
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DIAG = ROOT / "gates" / "diag"
OUT = DIAG / "retro_gaps.json"

# id, 主题, 一句话结论, musts, negs, cover(短语), cover_state, has_cmd, force_pri
G = [
    # ---------------- 号池 / 派活 ----------------
    (
        "WD1",
        "pool",
        "看门狗判活要看「工人还在不在动」（每次工具调用刷心跳 + 滑动窗口），固定超时会把正在跑长命"
        "令的工人误杀",
        ["看门狗", "心跳"],
        [],
        ["看门狗"],
        "none",
        True,
        "",
    ),
    (
        "WD2",
        "pool",
        "看门狗误杀的真根因是「空转判死 / 阈值衰减 / 只看 stdout 不看进程」，不是「工人太慢」；修"
        "法是判据改成看进程树",
        ["看门狗", "误杀"],
        [],
        ["看门狗"],
        "none",
        True,
        "",
    ),
    (
        "WD3",
        "pool",
        "看守要能区分「在等长命令」与「真卡死」：长命令期间不许判死，否则杀掉的正是干活的人",
        ["看门狗", "长命令"],
        [],
        ["看门狗"],
        "none",
        True,
        "",
    ),
    (
        "LS1",
        "pool",
        "掐工人必须还租约：正常退出 / 超时 / 强杀 / 异常四条路径都落到同一处释放，否则下一张卡撞幽"
        "灵锁",
        ["还租约"],
        [],
        ["还租约", "租约"],
        "none",
        True,
        "",
    ),
    (
        "LS2",
        "pool",
        "强杀（taskkill / kill_tree）之后要清孤儿进程 + 清租约，只 kill 主干会留下占着门的子进程",
        ["强杀", "租约"],
        [],
        ["强杀"],
        "none",
        True,
        "",
    ),
    (
        "LS3",
        "pool",
        "门禁锁要分把并有并发上限：不同门可并行、同一门必须串行，否则并行派活等于自己撞自己",
        ["门禁锁", "分把"],
        [],
        ["门禁锁"],
        "none",
        True,
        "",
    ),
    (
        "LS4",
        "pool",
        "锁要带 TTL + 接管留痕（租约制）：文件在不算占着，锁永留会让后续所有 claim/waive/land 一律"
        " rc=2",
        ["锁", "接管"],
        [],
        ["TTL", "接管"],
        "none",
        True,
        "",
    ),
    (
        "QU1",
        "pool",
        "额度按钟表算（记录时刻 vs 现在），不按「上次探测 + 固定间隔」；否则会判成「还在限流」并空"
        "转等待",
        ["额度", "钟表"],
        [],
        ["额度"],
        "none",
        True,
        "",
    ),
    (
        "QU2",
        "pool",
        "429/限流要四态判（限流中 / 已过期需重探 / 余额耗尽 / 未记录），不许一个「限流中」盖住全部",
        ["429", "限流"],
        [],
        ["429", "四态"],
        "none",
        True,
        "",
    ),
    (
        "PO1",
        "pool",
        "派活不许靠人轮询：队列 + 定时巡检（每日一批）让该派的自己派，人只做判断",
        ["轮询"],
        [],
        ["轮询"],
        "none",
        True,
        "",
    ),
    (
        "PO2",
        "pool",
        "队列登记会漏（写卡不写预声明 / 台账漏一笔）：一卡一号，派活前必须核预声明在不在",
        ["预声明"],
        [],
        ["预声明"],
        "none",
        True,
        "",
    ),
    (
        "PO3",
        "pool",
        "域要细化到符号级（不是文件级），收批时按卡树**实际改动**重算越界，不按工人自报",
        ["符号级"],
        [],
        ["符号级", "域检查"],
        "partial",
        True,
        "",
    ),
    (
        "PO4",
        "pool",
        "两份白名单（`tools/wb_dispatch.py` 的 MODEL_WHITELIST 与 `infra/pool` 注册表）必须对账，"
        "不一致只报告不改名",
        ["white", "roster"],
        [],
        ["MODEL_WHITELIST", "白名单"],
        "partial",
        True,
        "",
    ),
    (
        "PO5",
        "pool",
        "卡树基点会过期：派活时的 base 已被主树推进 ⇒ 落地前必须比基点，算不出就拒",
        ["基点"],
        [],
        ["基点"],
        "none",
        True,
        "",
    ),
    (
        "PO7",
        "pool",
        "收口按增量门禁跑（只跑受影响的输入面），跳过的必须记账，否则等于没跑",
        ["增量门禁"],
        [],
        ["增量"],
        "none",
        True,
        "",
    ),
    (
        "PO8",
        "pool",
        "收口链先把「要提交的文件」同步进卡树，否则文书生成时引用不可达 ⇒ 每笔都可能假红",
        ["同步进卡树"],
        [],
        ["卡树"],
        "none",
        True,
        "",
    ),
    (
        "PO9",
        "pool",
        "攒批固定进工作流：同一波按域分批、批内并行、批间串行；临时拼的并行会撞域",
        ["攒批"],
        [],
        ["攒批"],
        "none",
        True,
        "",
    ),
    (
        "PO10",
        "pool",
        "派活器不许依赖 cwd：`main_tree_root` 从脚本位置反推，否则换个目录起就派到别处",
        ["main_tree_root"],
        [],
        ["main_tree_root"],
        "none",
        True,
        "",
    ),
    (
        "PO11",
        "pool",
        "模型白名单两份真源合一（tools 的 MODEL_WHITELIST 与 infra/pool 注册表），否则一个允许一个"
        "拒",
        ["MODEL_WHITELIST", "合并"],
        [],
        ["MODEL_WHITELIST"],
        "none",
        True,
        "",
    ),
    (
        "PO12",
        "pool",
        "CLI 的 effort / 模型名要透传进工人，否则派活时写的等级不生效、读数全是默认值",
        ["effort"],
        [],
        ["effort"],
        "none",
        True,
        "",
    ),
    (
        "PO13",
        "pool",
        "队列状态要收口：落地即翻状态（同一笔里做完），否则面板永远显示「落了没翻」",
        ["落地即翻"],
        [],
        ["翻状态"],
        "none",
        True,
        "",
    ),
    (
        "PO14",
        "pool",
        "定时巡检分报（队列漏登记 / 队列积压 / 配额），别混在一条里；每日一批不靠人记",
        ["定时巡检"],
        [],
        ["巡检"],
        "partial",
        True,
        "",
    ),
    (
        "PO15",
        "pool",
        "派活按账号分（同一个号不许并发两卡），租约里要记码道/账号，事后才查得出用了哪个号",
        ["按账号"],
        [],
        ["账号"],
        "none",
        True,
        "",
    ),
    # ---------------- 门禁 / 接缝 ----------------
    (
        "SE1",
        "gate",
        "跨卡接缝必须派活前预检（谁改签名、谁还在用旧签名）：事后发现的接缝等于两张卡白做",
        ["接缝", "预检"],
        [],
        ["接缝"],
        "none",
        True,
        "",
    ),
    (
        "SE2",
        "gate",
        "接缝预检会假阳性（桩签名、同名不同参）：要人工复核一次，不许把预检红直接当判决红",
        ["接缝", "假阳"],
        [],
        ["接缝"],
        "none",
        True,
        "",
    ),
    (
        "JU1",
        "gate",
        "旧判决不许冒充当前状态：`gates/last.json` 必须带 base/rev，读的人先核它是不是这一轮的",
        ["旧判决"],
        [],
        ["last.json"],
        "partial",
        True,
        "",
    ),
    (
        "JU2",
        "gate",
        "判决文案要分真因（门没挡住 / 挡住了但不是这条 / 输入没给），否则读判决的人永远在猜",
        ["判决", "真因"],
        [],
        ["真因"],
        "none",
        True,
        "",
    ),
    (
        "JU3",
        "gate",
        "门禁假绿头号来源是环境：PYTHONPATH / cwd / 编码不对时，门会绿在错的输入上",
        ["假绿"],
        [],
        ["PYTHONPATH", "假绿"],
        "none",
        True,
        "",
    ),
    (
        "GV1",
        "gate",
        "门禁峰值要治：并行 pytest + 内存阈值随可用内存自适应，否则门红在 OOM 而不是红在判据",
        ["内存", "自适应"],
        [],
        ["内存"],
        "partial",
        True,
        "",
    ),
    (
        "GV2",
        "gate",
        "门乘输入表：每道门的输入面要显式列出，`--affected` 才有依据裁；匹配不上就当全量跑",
        ["--affected"],
        [],
        ["--affected", "输入面"],
        "none",
        True,
        "",
    ),
    # ---------------- 台账 / 对账 ----------------
    (
        "LD1",
        "ledger",
        "台账对账器只认标题 / 批次围栏 / 证据指针语法，不认「差不多」；对不上的按死账处理，不就地"
        "改数",
        ["对账器"],
        [],
        ["对账"],
        "none",
        True,
        "",
    ),
    (
        "LD2",
        "ledger",
        "证据指针要有固定语法（`文件#段落` / `文件:行`），否则半年后没人能追回那条结论",
        ["证据指针"],
        [],
        ["证据指针"],
        "partial",
        True,
        "",
    ),
    (
        "LD3",
        "ledger",
        "封存之后才翻 status：先写指纹再改状态，顺序反了就是「状态说完了、证据说没完」",
        ["封存", "status"],
        [],
        ["封存"],
        "partial",
        True,
        "",
    ),
    # ---------------- AI 协作 ----------------
    (
        "AI1",
        "ai",
        "长任务按「续跑」设计：检查点 + 断点存档 + 下一轮只读检查点，不许从零重来",
        ["续跑", "检查点"],
        [],
        ["续跑"],
        "partial",
        True,
        "",
    ),
    (
        "AI2",
        "ai",
        "反空转三道：调用前写目的、给无进展设判据、写清交还人的条件；否则一边空转一边报进展",
        ["反空转"],
        [],
        ["反空转"],
        "none",
        True,
        "",
    ),
    (
        "AI3",
        "ai",
        "对抗复核要常态化（另一家模型独立复核 + 引文回溯），自己复核自己等于没复核",
        ["对抗复核"],
        [],
        ["对抗"],
        "partial",
        True,
        "",
    ),
    (
        "AI4",
        "ai",
        "外部模型用完就撤（一次性授权写进白名单再删），长期挂在允许集里等于开后门",
        ["一次性", "授权"],
        [],
        ["一次性"],
        "none",
        True,
        "",
    ),
    (
        "AI5",
        "ai",
        "复核派生物有噪声（把日志/生成物当代码审）：要显式排除派生物，否则复核结论全是噪声",
        ["派生物"],
        [],
        ["派生物"],
        "partial",
        True,
        "",
    ),
    # ---------------- 环境 / 编码 / 端口 ----------------
    (
        "EN1",
        "framework",
        "本仓所有 Python 一律 `-X utf8`：不是习惯而是判据（中文输出、编码比较都依赖它）",
        ["-X utf8"],
        [],
        ["-X utf8"],
        "full",
        True,
        "",
    ),
    (
        "EN2",
        "framework",
        "外部命令 stdout 是系统区域编码（cp936）：用 `locale.getencoding()` 解，不许用 `getpre"
        "ferredencoding(False)`（`"
        "-X utf8` 会让它回 utf-8）",
        ["getencoding"],
        [],
        ["getencoding", "cp936"],
        "none",
        True,
        "",
    ),
    (
        "EN3",
        "framework",
        "端口按树隔离：挑端口用「能不能 bind」，接入前验明正身（PID + 映像名），不许猜一个空号",
        ["bind"],
        [],
        ["bind", "端口"],
        "partial",
        True,
        "",
    ),
    # ---------------- 技能 / 宿主 ----------------
    (
        "SK1",
        "framework",
        "技能要三层（索引 / 操作 / 判据）并维护技能登记表；技能只放操作知识，判据留在库里",
        ["技能登记"],
        [],
        ["技能登记"],
        "none",
        False,
        "",
    ),
    (
        "HS1",
        "dsh",
        "`~/.dsh` 是禁区：派活明令不许改宿主目录，插件验证只能在仓内做",
        ["~/.dsh"],
        [],
        ["~/.dsh"],
        "none",
        True,
        "",
    ),
    # ---------------- 视觉 / 界面 ----------------
    (
        "UI1",
        "visual",
        "面板/图表不许硬编码颜色，一律用主题令牌（`--dsw-alias-*`）；硬编码色在暗色下是白底刺眼条",
        ["硬编码", "颜色"],
        [],
        ["令牌", "硬编码"],
        "none",
        True,
        "",
    ),
    (
        "UI2",
        "visual",
        "非文字元素（图标/边框/状态色）也要过对比度门，只查文字的对比度门会放过真正的暗雷",
        ["非文字"],
        [],
        ["非文字"],
        "none",
        True,
        "",
    ),
    (
        "UI3",
        "visual",
        "界面不解释自己：文案不写「这里可以…」，解释进文档，界面只留动作",
        ["不解释"],
        [],
        ["不解释"],
        "none",
        False,
        "",
    ),
    # ---------------- 文档 / 口径 ----------------
    (
        "CF1",
        "doc",
        "口径漂移用「加注」治：历史结论保留原文 + 顶部加注「已被卡 N 推翻」，不要原地改写",
        ["加注"],
        [],
        ["加注"],
        "none",
        True,
        "",
    ),
    (
        "CF2",
        "doc",
        "同一事实只许有一处投影；命令表 / CLI 文档属于第四份投影，必须脚本对账",
        ["投影"],
        [],
        ["投影"],
        "none",
        True,
        "",
    ),
    # ---------------- 缺陷根因 ----------------
    (
        "DF1",
        "defect",
        "跨天/时区类缺陷的根治是注入「今天」（可注入时钟），不是改判定式",
        ["注入", "今天"],
        [],
        ["注入"],
        "none",
        True,
        "",
    ),
    (
        "DF2",
        "defect",
        "幂等写库：重放同一笔不许产生第二行，判据是「再跑一次读数为 0」",
        ["幂等写库"],
        [],
        ["幂等"],
        "partial",
        True,
        "",
    ),
    # ---------------- 补：面板 / 外部系统 / 框架 / 产品线 ----------------
    (
        "PN1",
        "panel",
        "面板只认「一份读数」单一入口（pipeline_view）：各面板不许自己再算一遍，否则同一现场两个数",
        ["一份读数"],
        [],
        ["一份读数"],
        "none",
        True,
        "",
    ),
    (
        "PN2",
        "panel",
        "面板读日志要容错坏行 / 幻影行：解析失败给 note + 原样行，不许整页崩或静默吞",
        ["幻影行"],
        [],
        ["幻影行"],
        "none",
        True,
        "",
    ),
    (
        "EX1",
        "ext",
        "MCP / 外部调用要开子进程并设超时：长任务冻住 stdio 等于把宿主一起冻死",
        ["子进程", "stdio"],
        [],
        ["子进程", "stdio"],
        "none",
        True,
        "",
    ),
    (
        "EX2",
        "ext",
        "局域网接入用一次性配对码换会话令牌，令牌不许进 URL / 日志 / 证据指针",
        ["配对码"],
        [],
        ["配对码"],
        "none",
        True,
        "",
    ),
    (
        "FW1",
        "framework",
        "事实层是唯一真源：AI 只写「做了什么」的事实回报，结论与产物由库/门产出，不许自证",
        ["事实层"],
        [],
        ["事实层"],
        "none",
        True,
        "",
    ),
    (
        "FW2",
        "framework",
        "框架要能整体提升为独立仓：无隐藏本地依赖，提升前先跑抽取清单，先抽后搬",
        ["独立仓"],
        [],
        ["独立仓"],
        "none",
        True,
        "",
    ),
    (
        "PD1",
        "product",
        "稀疏序号只是显示问题：排序键要显式落库（不许靠序号连续性排序），否则删一行就乱序",
        ["稀疏序号"],
        [],
        ["稀疏序号"],
        "none",
        True,
        "",
    ),
    (
        "PD2",
        "product",
        "跨端同步只许一个合并器（拍平块 + 显式合并规则），两端各写一套 = 永久冲突",
        ["跨端同步"],
        [],
        ["跨端同步"],
        "none",
        True,
        "",
    ),
    (
        "PD3",
        "product",
        "复习/验收的改判要落成「改判记录」并保留原判，不许原地覆盖（覆盖即丢证据）",
        ["改判"],
        [],
        ["改判"],
        "none",
        True,
        "",
    ),
]


# P0 = 会让人做错动作 / 丢证据 / 开安全口的：误杀、幽灵锁、假绿、假日期、接缝、"两处真源"、
#      一次性授权留后门、死账。其余按「n≥3 且有可执行命令」落 P1，剩下的 P2。
P0_IDS = {
    "WD1",
    "WD2",
    "WD3",
    "LS1",
    "LS2",
    "LS3",
    "LS4",
    "QU2",
    "JU3",
    "SE1",
    "EN2",
    "PO5",
    "PO2",
    "LD1",
    "AI4",
}


def load_skills() -> str:
    buf = []
    for p in sorted((ROOT / "skills").rglob("*.md")):
        buf.append(p.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(buf)


def main() -> int:
    ex = json.loads((DIAG / "retro_extract.json").read_text(encoding="utf-8"))
    th = json.loads((DIAG / "retro_theme.json").read_text(encoding="utf-8"))
    theme_of = th["theme_of"]
    rows = ex["rows"]
    texts = {
        r["rel"]: (ROOT / r["rel"]).read_text(encoding="utf-8", errors="replace") for r in rows
    }
    meta = {r["rel"]: r for r in rows}
    skills = load_skills()
    only = set(sys.argv[sys.argv.index("--id") + 1].split(",")) if "--id" in sys.argv else None

    out = []
    for cid, theme, claim, musts, negs, covers, cstate, has_cmd, force in G:
        if only and cid not in only:
            continue
        hits = [
            rel
            for rel, t in texts.items()
            if all(m in t for m in musts) and not any(n in t for n in negs)
        ]
        cov_found = [k for k in covers if k in skills]
        n = len(hits)

        def rank(rel: str, _musts=musts, _theme=theme):
            # 默认参数把两个循环变量钉死（B023）：rank 只在本轮内被 sorted 调一次，
            # 但匿名闭包会让 ruff 认为逃出了循环，显式绑定同时去掉这个歧义。
            named = not any(m.lower() in rel.lower() for m in _musts)
            return (
                theme_of.get(rel) != _theme,
                named,
                meta[rel]["chars"] > 40000,
                -meta[rel]["chars"],
                rel,
            )

        slim = [r for r in hits if meta[r]["chars"] <= 40000]
        ev = sorted(slim or hits, key=rank)[:3]
        pri = force or (
            "P0"
            if cid in P0_IDS
            else "已覆盖"
            if cstate == "full"
            else "P1"
            if (n >= 3 and has_cmd)
            else "P2"
        )
        out.append(
            {
                "id": cid,
                "theme": theme,
                "claim": claim,
                "n": n,
                "pri": pri,
                "ev": ev,
                "cover_state": cstate,
                "cover_found": cov_found,
                "musts": musts,
                "has_cmd": has_cmd,
            }
        )

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    show_all = "--all" in sys.argv
    order = {"P0": 0, "P1": 1, "P2": 2, "已覆盖": 3}
    for o in sorted(out, key=lambda x: (order[x["pri"]], -x["n"])):
        if o["pri"] == "已覆盖" and not show_all:
            continue
        print(f"{o['id']:5s} {o['pri']:4s} n={o['n']:3d} {o['theme']:9s} {o['claim'][:60]}")
        if "--full" in sys.argv:
            for e in o["ev"]:
                print(f"        · {e}")
        print(f"        cover={o['cover_state']} found={o['cover_found']}")
    print("\n" + str(Counter(o["pri"] for o in out)))
    print("gaps", sum(1 for o in out if o["pri"] != "已覆盖"), "of", len(out))
    print("zero-hit:", [o["id"] for o in out if o["n"] == 0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
