# 卡 A305 —— grill-me 参考落地（前三层共用方法）（T-AG419）

- 决定（2026-10-20）：**不新建 `spec-grill` 技能**。grill-me 属于「前三层（意图/规格/契约）都要做」的方法，
  按用户要求「抓下来、后 refer」，落成一份参考即可。
- 已完成部分：`skills/softeng-manage/references/grill-me.md` 已抓取改写（含来源链接、四条铁律、问题格式、三层映射）。
- 剩余：在 `skills/softeng-manage/references/doc-layers.md` 的前三层各加一句「决策怎么定 → 见 grill-me.md」；
  `skills/README.md` 的占位改成指向该参考。
- 验收：`scripts/check_layers.py` PASS；`npx skills-ref validate ./skills/softeng-manage` Valid。
- 状态：pending（等 A304 落地后合并这几句引用）。
