"""一次性脚本：生成 复盘/INDEX.md（只读语料，只写这一个产物）。

输入（同目录，均由前面几个脚本产出）：
  retro_extract.json  路径/字数/mtime/标题/卡号
  retro_theme.json    主题分区 theme_of
  retro_lines.json    每篇一句话结论
  retro_gaps.json     全量缺口 claim
用法：python -X utf8 scripts/retro/retro_index.py [--preview THEME]
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DIAG = ROOT / "gates" / "diag"
OUT = ROOT / "复盘" / "INDEX.md"

THEMES = {
    "handoff": (
        "交接单与现场交接",
        "每张卡做完留给下一个窗口的交接单：来路/做法/教训，是这套复盘的时间轴。",
        ["复盘/交接.d/T-G363.md", "复盘/交接.d/T-G219.md", "复盘/交接-重构进度.md"],
    ),
    "pool": (
        "号池与派活",
        "派活器、看门狗、租约与门禁锁、额度与并发、收口与攒批：工人怎么被叫起来又怎么被收回来。",
        [
            "复盘/外包-卡表与规矩.md",
            "复盘/卡/卡141-掐工人要还租约.md",
            "复盘/卡215-派活不该靠人轮询.md",
        ],
    ),
    "gate": (
        "门禁与判据",
        "门怎么算过、假绿从哪来、跨卡接缝怎么预检、旧判决怎么不冒充当前状态。",
        ["复盘/门禁四要素.md", "复盘/跨卡接缝预检-T-G139.md", "复盘/门禁假绿-PYTHONPATH-T-G157.md"],
    ),
    "framework": (
        "框架与架构",
        "pipe 框架本身：术语契约、骨架设计、事实层、技能三层，以及把它提成独立仓。",
        ["复盘/框架-术语表与契约.md", "复盘/框架-骨架设计.md", "复盘/事实层架构设计复盘.md"],
    ),
    "ledger": (
        "台账、对账与证据",
        "台账怎么记、对账器认什么、证据指针与封存指纹怎么核，以及那本 3 万字的坑总账。",
        ["复盘/坑总账.md", "复盘/证据指针语法-T-G133.md", "复盘/卡/卡228-封存后才翻status.md"],
    ),
    "doc": (
        "文档、口径与漂移",
        "同一事实被写到第 N 处就会漂：口径定案、加注法、第四份投影。",
        ["复盘/口径坑.md", "复盘/文档重整方案.md", "复盘/叙事漂移加注-T-G117.md"],
    ),
    "visual": (
        "视觉与界面判据",
        "审美门、对比度（含非文字）、暗色适配、去 AI 味、界面不解释自己。",
        [
            "复盘/视觉线地图.md",
            "复盘/设计基线-workbench与去AI味-T-G26.md",
            "复盘/非文字对比度-T-G70.md",
        ],
    ),
    "panel": (
        "工作台与面板",
        "一份读数、总览条、幻影行与日志容错、最新在前、六块读数。",
        [
            "复盘/卡/卡207-一份读数.md",
            "复盘/面板幻影行与日志容错-T-G137.md",
            "复盘/卡249-六块读数单元清单.md",
        ],
    ),
    "product": (
        "产品功能线（timeflow）",
        "计划/习惯/学业/复习各个功能面的具体修与结论，含唯一一笔已废弃的活。",
        ["复盘/已废弃-学校通知聚合.md", "复盘/跨端同步合并机制-T-G8.md", "复盘/复习改判-T-G13.md"],
    ),
    "ext": (
        "外部系统与研究",
        "Trae/K3/禅道/MCP/局域网这些外部面的接入结论和问答式研究。",
        ["复盘/Trae-接入结论.md", "复盘/MCP与写操作-T-G65.md", "复盘/研究-禅道22.6.md"],
    ),
    "ai": (
        "AI 协作与提示词",
        "长任务怎么不乱、对抗复核怎么常态化、外部模型用完怎么撤、外包系统怎么审。",
        [
            "复盘/长任务执行协议.md",
            "复盘/审计-GLM53-外包系统对抗审核.md",
            "复盘/对抗复核-T-G249.md",
        ],
    ),
    "dsh": (
        "DSH 插件与宿主",
        "dsh-web 的逐包对照、协议与事实、面板三座位、技能 junction、长会话交接。",
        ["复盘/DSH插件-协议与事实.md", "复盘/DSH插件-参考与结论.md", "复盘/卡240-面板三座位.md"],
    ),
    "defect": (
        "缺陷与事故根因",
        "时区/跨天、幂等、迁移漏档、渲染空、字面星号：一类一类钉住的根因。",
        [
            "复盘/门禁跨午夜暴露的时区口径缺陷-T-D12.md",
            "复盘/黄金跨天漂移-可注入的今天-T-G62.md",
            "复盘/幂等写库-T-G86.md",
        ],
    ),
    "misc": ("其他", "只落了一篇的零散收尾。", ["复盘/工具收尾两小件-T-G125.md"]),
}
ORDER = [
    "handoff",
    "pool",
    "gate",
    "framework",
    "ledger",
    "doc",
    "visual",
    "panel",
    "product",
    "ext",
    "ai",
    "dsh",
    "defect",
    "misc",
]

# 建议落到哪个技能（按 claim 前缀/主题给默认，个别覆盖）
SKILL = {
    "pool": "softeng-manage（派活前必读）+ pipe-workbench",
    "gate": "pipe-gate",
    "ledger": "pipe-forensics",
    "framework": "pipe-init / softeng-manage",
    "doc": "softeng-manage（写文档一节）",
    "ai": "softeng-manage（复核与长任务）",
    "visual": "softeng-manage / 新建 pipe-ui",
    "panel": "pipe-workbench",
    "product": "不落技能（产品线结论，留在复盘）",
    "ext": "GLUE-harness / 新建 pipe-mcp",
    "dsh": "新建 pipe-dsh",
    "defect": "pipe-forensics",
    "misc": "不落技能",
}
SKILL_OVERRIDE = {
    "PO10": "softeng-manage（派活五步）",
    "PO11": "softeng-manage（派活五步）",
    "PO12": "softeng-manage（派活五步）",
    "PO15": "softeng-manage（派活五步）",
    "PO13": "pipe-land",
    "PO8": "pipe-land",
    "PO14": "workflow（定时巡检）",
    "JU1": "pipe-gate（读判决）",
    "JU2": "pipe-gate（读判决）",
    "GV1": "pipe-gate（资源闸）",
    "GV2": "pipe-gate（输入面）",
    "EN2": "pipe-forensics",
    "EN3": "pipe-workbench（起停栈）",
    "HS1": "softeng-manage（禁区清单）",
    "HS2": "pipe-workbench",
    "SK1": "softeng-manage（技能三层）",
    "AI1": "softeng-manage（长任务）",
    "AI2": "softeng-manage（长任务）",
    "AI3": "softeng-manage（复核）",
    "AI4": "softeng-manage（禁区清单）",
    "LD1": "pipe-forensics（对账）",
    "LD2": "pipe-forensics（证据指针）",
    "CF1": "softeng-manage（加注法）",
    "CF2": "softeng-manage（文档投影）",
    "PN1": "pipe-workbench（一份读数）",
    "PN2": "pipe-workbench（容错）",
}

# 已被后面推翻 / 已废弃（读之前先看这一条）
HIST = {
    "复盘/已废弃-学校通知聚合.md": "整笔活已废弃（2026-10-16），只留路标，别照着做",
    "复盘/DESIGN-LEARN撤回与闭环验收恢复.md": "DESIGN/LEARN 已撤回，只保留 ACCEPTANCE 的闭环验收章"
    "节",
    "复盘/C批口径定案.md": "末条「按课程统计投入/产出」2026-09-20 被部分推翻，其余仍有效",
    "复盘/并发实测对账-T-G132.md": "本文的实测推翻了 T-G99 的「2 卡」并发边界声明；引用并发上限别"
    "引用 T-G99",
    "复盘/卡/卡029-派活器三合一.md": "文中「孤儿工人」设想已被 2026-09-26 卡 024 真机探针推翻",
    "复盘/卡/卡A272-对账器只认标题.md": "卡 146 已被卡 166 取代（2026-10-03 裁定），结论留作历史",
    "复盘/台账号到复盘索引-T-G168.md": "原 §2.2「25 份各加一行」整条作废，§1.1 裁定生效",
    "复盘/问题清单-组4.md": "指出 `复盘/口径坑.md` 里有过期条目（第 15 条），别把口径坑全表当现行",
    "复盘/问题清单-组1.md": "指出 `复盘/长任务执行协议.md` §二能力边界表（2026-09-18）已被文末注推"
    "翻",
    "复盘/交接.d/T-G235.md": "GLM-5.3 一次性授权已撤回，§6 第 5 条不再有效",
    "复盘/卡/卡137-GLM53用完就撤.md": "授权已撤回，glm-5.3 回到默认拒绝；本文是「怎么撤」的范例",
    "复盘/交接.d/T-G363.md": "「openResource(url) 是正式口子」被两份独立复核推翻（只收 dsh-resourc"
    "e://），看 UPDATE",
    "复盘/长任务执行协议.md": "10.7 万字巨无霸；§二能力边界表已过期，读之前先看文末注",
}
EMPTY = "（空壳：全文 {n} 字，只有标题/占位，别读）"

# 少数「先读」级大篇：抽取器给的一句话不如直接说清它是什么（只描述体裁/用途，不编结论）
NOTE = {
    "复盘/交接-重构进度.md": "框架重构的进度流水（按卡累加，29 万字）：查「某张卡改了什么 / 重构到"
    "哪一步」来这里，别整篇读",
    "复盘/长任务执行协议.md": "长任务执行协议（10.7 万字）：模式 A = 单线程主控 + 已授权自动执行、"
    "续跑与交还人的条件",
    "复盘/新窗口交接卡.md": "当前状态 + 新窗口第一条消息（照抄即可）：换窗口时先读这一篇",
    "复盘/坑总账.md": "不变量与坑的账本（3.2 万字，逐条带「→ 产物 · 已关/半关」）：查某条规矩有没"
    "有装牙、装在哪",
    "复盘/口径坑.md": "逐条口径陷阱清单（编号 + ★）：写文档 / 写判据前对照；已知第 15 条已过期",
    "复盘/门禁四要素.md": "门的四要素定稿：exit_code / name / seconds / summary，判据以 `scripts/r"
    "un_gates.py` 为唯一真源",
    "复盘/视觉线地图.md": "视觉线的判据地图（2.9 万字）：改界面 / 查对比度与令牌先看这里",
    "复盘/外包-卡表与规矩.md": "外包卡表与规矩（6 万字，§号会被证据指针引用）：派活口径的总表；改"
    "措辞会打穿 `text:` 指针",
    "复盘/框架-骨架设计.md": "框架骨架设计定稿（4.5 万字）：分层、目录与边界，改骨架前先读",
    "复盘/框架-术语表与契约.md": "术语表与契约：同一词在框架里的唯一含义，写文档 / 写卡前对齐用",
    "复盘/DSH插件-协议与事实.md": "DSH 插件协议与实测事实：哪些口子真能用（`openResource` 那条已被"
    "推翻，见 §4）",
    "复盘/已废弃-学校通知聚合.md": "整笔活已废弃（2026-10-16），只留路标，别照着做",
}


def clean(line: str) -> str:
    s = (line or "").strip()
    s = re.sub(r"\*\*|__|`", "", s)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"^[>\-*·]+\s*", "", s)
    return s.strip()


BAD_HEAD = (
    "依据",
    "示例",
    "见 复盘",
    "见复盘",
    "盘点",
    "CREATE ",
    "SELECT ",
    "INSERT ",
    "命令",
    "|",
    "```",
    "(已",
    "（已",
    "- ",
    "#",
)
BAD_SUB = ("CREATE TABLE", "PRIMARY KEY", "def ", "import ")


def usable(line: str) -> bool:
    s = clean(line)
    if len(s) < 18:
        return False
    if sum(1 for ch in s if "\u4e00" <= ch <= "\u9fff") < 12:
        return False
    if s.startswith(BAD_HEAD):
        return False
    return not any(b in s for b in BAD_SUB)


def one_sentence(line: str, cap: int = 110) -> str:
    s = clean(line)
    m = re.split(r"(?<=[。！？])", s, maxsplit=1)
    s = m[0] if m and m[0] else s
    s = s.rstrip("。：，、；: ")
    if len(s) > cap:
        cut = max(s.rfind("；", 0, cap), s.rfind("，", 0, cap), s.rfind("、", 0, cap))
        s = (s[:cut] if cut > cap * 0.55 else s[:cap]) + "…"
    return s


def card_tag(rel: str, meta: dict) -> str:
    cards = meta.get("cards") or []
    kcards = meta.get("kcards") or []
    picks = [c for c in cards if re.fullmatch(r"T-(?:A)?G\d+", c)][:2]
    if not picks and kcards:
        picks = kcards[:2]
    return "〔" + "·".join(picks) + "〕" if picks else ""


def main() -> int:
    ex = json.loads((DIAG / "retro_extract.json").read_text(encoding="utf-8"))
    th = json.loads((DIAG / "retro_theme.json").read_text(encoding="utf-8"))
    lines = json.loads((DIAG / "retro_lines.json").read_text(encoding="utf-8"))
    gaps = json.loads((DIAG / "retro_gaps.json").read_text(encoding="utf-8"))
    rows = ex["rows"] if isinstance(ex, dict) else ex
    meta = {r["rel"]: r for r in rows}
    theme_of = th.get("theme_of", th)
    by_theme = defaultdict(list)
    for r in rows:
        by_theme[theme_of.get(r["rel"], "misc")].append(r["rel"])

    def sort_key(rel: str):
        m = re.search(r"(?:T-A?G|卡A?)(\d+)", rel)
        return (0, -int(m.group(1))) if m else (1, 0)

    preview = sys.argv[sys.argv.index("--preview") + 1] if "--preview" in sys.argv else None

    def doc_line(rel: str) -> str:
        m = meta[rel]
        tags = []
        raw = (lines.get(rel) or {}).get("line", "")
        if rel in NOTE:
            body = NOTE[rel]
        elif m["chars"] < 220:
            body = EMPTY.format(n=m["chars"])
        elif not usable(raw):
            body = "（无单句结论：正文以清单/表格/对话为主，按标题取用）"
        else:
            body = one_sentence(raw)
        if rel in HIST:
            tags.append("历史·" + HIST[rel])
        if m["chars"] >= 40000 and rel not in HIST:
            tags.append(f"巨无霸·{m['chars']}字·按节读")
        t = card_tag(rel, m)
        tail = "".join("〔" + x + "〕" for x in tags)
        return f"- `{rel}` — {body}{t}{tail}"

    if preview:
        for rel in sorted(by_theme[preview], key=sort_key):
            print(doc_line(rel))
        return 0

    n = len(rows)
    per_dir = Counter(
        Path(r["rel"]).parent.as_posix()
        if Path(r["rel"]).parent.as_posix() != "复盘"
        else "复盘/（根）"
        for r in rows
    )
    # 段表三数一律当场算，不许写死 —— 2026-10-26 修：手写 587/268/176/143 早已过期（盘上 769 篇）
    n_root = per_dir.get("复盘/（根）", 0)
    n_card = per_dir.get("复盘/卡", 0)
    n_hand = per_dir.get("复盘/交接.d", 0)
    per_theme = {k: len(v) for k, v in by_theme.items()}
    chars = sorted(r["chars"] for r in rows)
    total_chars = sum(chars)
    months = Counter((r.get("mtime") or "")[:7] for r in rows)
    years = Counter((r.get("mtime") or "")[:4] for r in rows)
    # 卡号段：文件名/正文里的 T-G 号按百位分桶
    seg = Counter()
    for r in rows:
        for c in r.get("cards") or []:
            mm = re.search(r"G(\d+)", c)
            if mm:
                num = int(mm.group(1))
                if num <= 999:
                    seg[f"T-G{num // 100 * 100:03d}–{num // 100 * 100 + 99:03d}"] += 1
                else:
                    seg["T-G1000+"] += 1
    longest = sorted(rows, key=lambda r: -r["chars"])[:20]
    newest = sorted(rows, key=lambda r: r.get("mtime") or "", reverse=True)[:20]
    stubs = [r for r in rows if r["chars"] < 220]

    # 主题词 top20：词表法（词表在脚本里显式声明，逐个统计「出现在几篇的标题或正文前 2 万字里」）
    terms = [
        "门禁",
        "接缝",
        "看门狗",
        "租约",
        "门禁锁",
        "派活",
        "工人",
        "攒批",
        "并发",
        "额度",
        "429",
        "队列",
        "轮询",
        "巡检",
        "域外",
        "收口",
        "落地",
        "基线",
        "钉子",
        "台账",
        "对账",
        "证据",
        "指针",
        "封存",
        "指纹",
        "坑总账",
        "不变量",
        "口径",
        "漂移",
        "加注",
        "投影",
        "文档",
        "索引",
        "面板",
        "读数",
        "图表",
        "左栏",
        "右栏",
        "图标",
        "对比度",
        "暗色",
        "令牌",
        "视觉",
        "审美",
        "文案",
        "插件",
        "技能",
        "宿主",
        "dsh",
        "MCP",
        "Trae",
        "禅道",
        "局域网",
        "配对码",
        "复核",
        "对抗",
        "长任务",
        "续跑",
        "空转",
        "提示词",
        "模型",
        "白名单",
        "时区",
        "跨天",
        "幂等",
        "迁移",
        "缺陷",
        "假绿",
        "判决",
        "判据",
        "框架",
        "事实层",
        "骨架",
        "术语",
        "契约",
        "独立仓",
        "交接",
        "开工",
        "盘点",
        "验收",
        "回归",
        "快照",
    ]
    hits = Counter()
    for r in rows:
        body = (ROOT / r["rel"]).read_text(encoding="utf-8", errors="replace")[:20000]
        head = r["rel"].rsplit("/", 1)[-1]
        for t in terms:
            if t.lower() in (head + body).lower():
                hits[t] += 1
    top_words = hits.most_common(20)

    ok_gap = [g for g in gaps if g["pri"] != "已覆盖"]
    pri_cnt = Counter(g["pri"] for g in gaps)
    theme_gap = Counter(g["theme"] for g in ok_gap)

    out: list[str] = []
    w = out.append
    w(f"# 复盘索引（{n} 篇）")
    w("")
    w(
        "> 这份索引是 `复盘/` 的**指路牌**，不是摘要集：每条只给「这篇解决了什么 / 结论是什么」"
        "的一句话，"
        f"细节一律回原文。全仓 {n} 篇 `.md`（根目录 {n_root}、`卡/` {n_card}、`交接.d/` {n_hand}）"
        f"，约 "
        f"{total_chars / 10000:.0f} 万字 —— 没有人（也没有模型）能一次读完，所以按下面三层用。"
    )
    w("")
    w(
        "> ★ **覆盖范围**：上面这个篇数是**抽取快照**里的篇数（`gates/diag/retro_*.json`，2026-10 底），"
        "不是 `复盘/` 目录今天的篇数 —— 快照之后新写的篇目**没有**收录。查新东西用 `grep -r` 或 "
        "`git -c core.quotepath=false ls-files 复盘` 数篇数，别拿这份索引当全集。"
    )
    w("")
    w("## 0. 怎么用（三层披露）")
    w("")
    w("1. **L0（§1）**：先看主题表，找到你要办的事属于哪个主题，读每行给的 1～3 篇「先读」。")
    w(
        "2. **L1（§2）**：在主题里按一句话结论扫，`grep`/`Ctrl-F` 关键词（卡号、门名、症状）定位到"
        "具体篇。"
    )
    w(
        "3. **回原文**：L1 的一句话都抽自原文（`=== 结论 ===` 段、交接单的「做法/教训」、或动"
        "机段），"
        "但**判决以原文与 `gates/last.json` 为准**，索引不作判据。"
    )
    w("")
    w(
        f"- 读之前先看 **§4 历史与被推翻**：有 {len(HIST)} 篇是已被后面推翻或整笔废弃的，照着旧结"
        f"论干会踩坑。"
    )
    w(
        f"- 要改技能 / 想知道哪些结论该进 `skills/`：直接看 **§5 缺口清单**（{len(ok_gap)} 条，分 "
        f"P0/P1/P2）。"
    )
    w(
        "- 统计口径与读数在 **§3**；脚本在 `scripts/retro/retro_*.py`（**已入库**，可复算，"
        "五个脚本都**不带任何旗标**、按下面的顺序直跑）：`retro_extract.py` → "
        "`retro_themes.py` → `retro_lines.py` → `retro_gaps.py` → `retro_index.py`。"
    )
    w("")
    w("## 1. L0 主题目录")
    w("")
    w("| 主题 | 篇数 | 一句话 | 最该先读 |")
    w("|---|---|---|---|")
    for key in ORDER:
        name, blurb, reads = THEMES[key]
        cnt = per_theme.get(key, 0)
        if not cnt:
            continue
        rr = "<br>".join(
            f"[`{p.split('/')[-1]}`]({p[3:].replace(' ', '%20')})" for p in reads if p in meta
        )
        w(f"| **{name}**（`{key}`） | {cnt} | {blurb} | {rr} |")
    w("")
    w(
        f"> 说明：`交接.d/` 的 {n_hand} 篇是**随时间增长的时间轴**，L1 里按 mtime 倒序（最新在前）"
        f"；"
        "其余主题按篇幅排序，大篇多半是定稿/总账。只有 `复盘/设计/` 没有 md（只有一份 html "
        "候选图）。"
    )
    w("")

    for key in ORDER:
        name, blurb, reads = THEMES[key]
        docs = by_theme.get(key, [])
        if not docs:
            continue
        w(f"## 2.{ORDER.index(key) + 1} {name}（{len(docs)} 篇）")
        w("")
        w(f"*{blurb}* 先读：{'、'.join('`' + p + '`' for p in reads if p in meta)}")
        w("")
        if key == "handoff":
            for rel in sorted(docs, key=lambda r: meta[r].get("mtime") or "", reverse=True):
                w(doc_line(rel))
        else:
            head = [p for p in reads if p in docs]
            rest = sorted((d for d in docs if d not in head), key=lambda r: -meta[r]["chars"])
            for rel in head + rest:
                w(doc_line(rel))
        w("")

    # ---- §3 统计 ----
    w("## 3. 统计（脚本读数为准，可复算）")
    w("")
    w(
        f"- **总数**：{n} 篇 `.md`，合计约 {total_chars / 10000:.0f} 万字（字符计数，含标点/代码/"
        f"英文），中位 {chars[len(chars) // 2]} 字，"
        f"最长 {chars[-1]} 字，最短 {chars[0]} 字。"
    )
    w("- **按目录**：" + "、".join(f"`{k}` {v}" for k, v in per_dir.most_common()) + "。")
    w(
        "- **按主题**："
        + "、".join(f"{THEMES[k][0]} {per_theme[k]}" for k in ORDER if per_theme.get(k))
        + "。"
    )
    w(
        f"- **按年份**：只有 **2026** 一个年份（{years.get('2026', 0)} 篇）—— 这套复盘是 2026 "
        f"年两个多月里长出来的，"
        "**年份分布没有区分度**，所以下面按月给。"
    )
    w("- **按月**：" + "、".join(f"{k} {v}" for k, v in sorted(months.items())) + "。")
    w(
        "- **按卡号段**（正文/文件名里出现 `T-G` 号的按百位分桶，可重复计）："
        + "、".join(f"`{k}` {v}" for k, v in sorted(seg.items()))
        + "。"
    )
    w(f"- **空壳**（<220 字，只有标题/占位）：{len(stubs)} 篇，L1 里已逐条标「空壳…别读」。")
    w("")
    w(
        "**主题词 top20**（口径：脚本里显式声明一张 80 个词的表 —— 门禁/接缝/看门狗/租约/证据"
        "指针/…，"
        "逐个统计「标题或正文前 2 万字里出现过」的**文档数**。是文档频次不"
        "是词频，避免长文垄断；"
        "词表写在 `scripts/retro/retro_index.py` 的 `TERMS` "
        "里，可增删复算）："
    )
    w("")
    w("| # | 词 | 篇数 | # | 词 | 篇数 |")
    w("|---|---|---|---|---|---|")
    half = (len(top_words) + 1) // 2
    for i in range(half):
        a = top_words[i]
        b = top_words[i + half] if i + half < len(top_words) else ("", "")
        w(
            f"| {i + 1} | `{a[0]}` | {a[1]} | {i + 1 + half} | `{b[0]}` | {b[1]} |"
            if b[0]
            else f"| {i + 1} | `{a[0]}` | {a[1]} | | | |"
        )
    w("")
    w("**最长的 20 篇**（按字数；超过 4 万字的建议按节读，别整篇塞进上下文）：")
    w("")
    for i, r in enumerate(longest, 1):
        w(f"{i}. `{r['rel']}` — {r['chars']} 字")
    w("")
    w("**最新的 20 篇**（按 mtime，最新在前）：")
    w("")
    for i, r in enumerate(newest, 1):
        w(f"{i}. `{r['rel']}` — {r.get('mtime')}")
    w("")

    # ---- §4 历史 ----
    w("## 4. 历史与被推翻（读之前先看这一节）")
    w("")
    w(
        "这套复盘是**只追加**的：结论被推翻时通常不删原文，而是另写一篇「更正 / 撤回 / 实测对"
        "账」。"
        "所以下列文件里的部分内容是**过期**的。规则：**后面的卡号 > 前面的卡"
        "号；带「更正/撤回/实测对账/已废弃」的那篇胜**。"
    )
    w("")
    w("| 文件 | 哪部分过期 / 现在以什么为准 |")
    w("|---|---|")
    for p, note in HIST.items():
        w(f"| `{p}` | {note} |")
    w("")
    w(
        "- 另有**结构性风险**（不是废弃）：`复盘/视觉线地图.md` 记着 T-G122 —— 改 `复盘/外包-"
        "卡表与规矩.md` 的措辞"
        "会打穿台账里的 `text:` 证据指针。**改复盘正文前先想清"
        "楚会不会打穿引用**。"
    )
    w(
        "- 11 篇空壳（`复盘/DSH插件-*.md` 5 篇 + `复盘/交接.d/T-AG389/391/392/393/394/395.md` "
        "6 篇）不是废弃，"
        "是**只有标题没有正文**，别指望从里面读出结论。"
    )
    w("")

    # ---- §5 缺口 ----
    w(f"## 5. 该进 `skills/` 但没进的操作性结论（全量 {len(ok_gap)} 条）")
    w("")
    w("### 5.1 怎么算的（可复核）")
    w("")
    w(
        "- **为什么只收「操作性」**：`skills/` 的定位是「怎么干」（顺序、前置检查、常见错），"
        "判据留在库/门里（`skills/README.md`）。所以收进来的是**会让人做错动作的规矩**，不是设计理念。"
    )
    w(
        "- **频次 = 命中文档数**：一篇复盘里必须同时出现这条的 `musts` 词（AND），才算这篇讲到"
        "了它；"
        "词表写在 `scripts/retro/retro_gaps.py` 的 claim 上，`python -X utf8 "
        "scripts/retro/retro_gaps.py "
        "--id XX --full` 可逐条复算。"
    )
    w(
        "- **零覆盖 = 在 `skills/**/SKILL.md|NOTES.md` 与 `softeng-manage/references/*.md` 里 "
        "grep `cove"
        "r` 短语全无命中**；"
        "「partial」= 只有一句术语带过（没"
        "有步骤）。二者都算缺口。"
    )
    w(
        "- **P0 判据**：会让人做错动作 / 丢证据 / 开安全口的（误杀、幽灵锁、假绿、旧判决、接缝"
        "、两处真源、一次性授权留后门、死账）。"
        "**P1**：反复出现（n≥3）且零覆盖且有"
        "可执行命令，但不是事故级。**P2**：n<3，或只有口头规矩没有命令。"
    )
    w(
        f"- **读数**：共 {len(gaps)} 条 claim，其中 **{len(ok_gap)} 条是缺口**；"
        f"P0 **{pri_cnt.get('P0', 0)}** / P1 **{pri_cnt.get('P1', 0)}** / P2 "
        f"**{pri_cnt.get('P2', 0)}**；"
        f"已覆盖 {pri_cnt.get('已覆盖', 0)} 条（`-X utf8`，所有技能都在用，列出来做对照）。"
    )
    w(
        "- **频次 top20 与主题分布**见 5.4；每条的证据都是 1～3 篇**同主题、标题命中**的原文，"
        ""
        "点回去就能核。（巨无霸 `复盘/交接-重构进度.md`、`复盘/长任务执行协议.md` "
        "会被选为证据时避开，"
        "免得读者一上来被 10 万字拦住。）"
    )
    w("")
    w("### 5.2 按主题分组的全量清单")
    w("")
    for key in ORDER:
        gs = [g for g in ok_gap if g["theme"] == key]
        if not gs:
            continue
        w(f"#### {THEMES[key][0]}（{len(gs)} 条）")
        w("")
        w("| ID | 级 | 频次 | 一句话结论 | 证据（1～3 篇） | 建议落点 |")
        w("|---|---|---|---|---|---|")
        for g in sorted(gs, key=lambda x: ({"P0": 0, "P1": 1, "P2": 2}[x["pri"]], -x["n"])):
            ev = "<br>".join(f"`{p}`" for p in g["ev"][:3]) or "—"
            sk = SKILL_OVERRIDE.get(g["id"], SKILL.get(g["theme"], "—"))
            if g["cover_state"] == "partial":
                sk += "（现有只一句带过）"
            w(f"| {g['id']} | {g['pri']} | {g['n']} | {g['claim']} | {ev} | {sk} |")
        w("")
    w("### 5.3 P0 先补（15 条）")
    w("")
    w("| ID | 结论 | 证据 | 落点 |")
    w("|---|---|---|---|")
    for g in sorted([x for x in ok_gap if x["pri"] == "P0"], key=lambda x: -x["n"]):
        ev = "、".join(f"`{p}`" for p in g["ev"][:2])
        w(
            f"| {g['id']} | {g['claim']} | {ev} |"
            f" {SKILL_OVERRIDE.get(g['id'], SKILL.get(g['theme'], '—'))} |"
        )
    w("")
    w("### 5.4 缺口统计")
    w("")
    w(
        "- **按主题**："
        + "、".join(f"{THEMES[k][0]} {theme_gap[k]}" for k in ORDER if theme_gap.get(k))
        + "。"
    )
    w("- **按级**：" + "、".join(f"{k} {v}" for k, v in pri_cnt.most_common()) + "。")
    w("- **频次 top20**（同一结论在多少篇里出现）：")
    w("")
    w("| # | ID | 级 | 篇数 | 结论 |")
    w("|---|---|---|---|---|")
    for i, g in enumerate(sorted(ok_gap, key=lambda x: -x["n"])[:20], 1):
        w(f"| {i} | {g['id']} | {g['pri']} | {g['n']} | {g['claim'][:70]} |")
    w("")
    w("### 5.5 建议：先补哪三条")
    w("")
    w(
        "1. **看门狗判活 + 掐工人还租约**（WD1/LS1/LS2，合计 n=57）—— 落 `softeng-manage` 派活"
        "一节："
        "判活看心跳滑动窗口；退出/超时/强杀/异常四条路径同一处释放租约。这是"
        "「工人被杀在半路」类事故的总根。"
    )
    w(
        "2. **门禁假绿与旧判决**（JU3/JU1，n=44+15）—— 落 `pipe-gate`：读判决前先核 `gates/las"
        "t.json` 的 base/rev；"
        "PYTHONPATH/cwd/编码三项是假绿头号来源。"
    )
    w(
        "3. **证据指针与封存顺序**（LD2/LD3，n=41+29）—— 落 `pipe-forensics`：证据指针固定语法；"
        "先写指纹再翻 status，顺序反了就是「状态说完了、证据说没完」。"
    )
    w("")
    w("## 6. 这份索引自己的边界")
    w("")
    w(
        f"- {n} 篇里 {n_hand} 篇交接单是**流水账**（每篇 400～800 字、只讲一张卡），L1 只抽「标题 "
        f"⇒ 做法」一句，"
        "要细节请按卡号回原文；卡号**不连续**，别拿连号当「中间没发生事」的证据。"
    )
    w("- L1 的一句话是抽取的**动机/做法句**，不是形式化结论；它可能截断（带 `…`），原文永远优先。")
    w(
        "- 主题分区是规则分类（标题 6 分 / 路径 4 分 / 正文 2 分，`scripts/retro/retro_themes."
        "py`），"
        "已知一处误判：`复盘/外包卡-012d-集成.md` 落进了 `dsh`（路径词太宽）"
        "，不影响读。"
    )
    w(
        "- 本索引只覆盖本仓 `复盘/`；OpenMAIC 的复盘在 `../OpenMAIC/复盘/`，`grep -ril openmaic 复"
        "盘/` = 0 篇。"
    )
    w("")

    text = "\n".join(out)
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT} lines={text.count(chr(10)) + 1} chars={len(text)}")
    print("themes", len([k for k in ORDER if per_theme.get(k)]), "docs", n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
