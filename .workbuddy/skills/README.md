# 项目级技能（Project-level Skills）

本目录是 **本项目（F:\model 工作区）专属**的技能目录。放在这里的技能只在本工作区生效，
可以随项目一起提交、分享给协作者。

> 用户级技能目录（全局生效、所有项目可用）是 `C:\Users\Administrator\.workbuddy\skills\`。

## 目录结构

```
F:\model\.workbuddy\skills\
├── README.md                  ← 本文件
├── web-design-engineer\       ← 网页设计工程师 v1.3.0（42 个文件，670K）
├── superpowers\               ← Superpowers 工程方法论 v1.0.0（8 个文件，41K）
├── taptap-maker\              ← TapTap 制造 v1.0.0（24 个文件，2.8M，含 MCP + SessionStart hook）
└── skills-security-check\     ← Skill 安全审计工具 v1.0.0（3 个文件，32K）
```

每个技能目录下都有 `SKILL.md`（技能定义入口），WorkBuddy 会自动识别。

## 各技能用途（对照本项目的场景）

| 技能 | 版本 | 在本项目里的用途 |
|---|---|---|
| **web-design-engineer** | 1.3.0 | 斗地主牌桌的视觉设计：布局排版、动效、设计系统、浏览器验收。用于继续打磨 `doudizhu/static/` |
| **superpowers** | 1.0.0 | 工程方法论：先规格 → 可执行计划 → 红绿 TDD → 子代理开发 → 代码评审。用于下一轮给游戏加功能（联机、战绩榜、AI 难度分级） |
| **taptap-maker** | 1.0.0 | TapTap 官方游戏开发插件（CLI + MCP），走游戏项目工作流：创建/同步项目、提交构建、生成素材、接入广告 |
| **skills-security-check** | 1.0.0 | 安装第三方技能前的安全审计（只读：Read / Grep / Glob / Bash） |

## 安全审计结论

四个技能均通过静态安全审计（详见 `F:\model\skill_audit_report_2026-09-21.md`）：

| 技能 | 评分 | 判定 |
|---|---|---|
| web-design-engineer | 100 | ✅ Benign（纯文档 + 方法论，无可执行代码） |
| superpowers | 100 | ✅ Benign（纯 Markdown） |
| taptap-maker | 85 | ✅ Benign（含 CLI/MCP，逻辑透明；hook 只读且改配置前需用户确认） |
| skills-security-check | 100 | ✅ Benign（只读审计工具） |

## 使用说明

- **taptap-maker 的 MCP** 不会自动激活：需在连接器管理页右上角的自定义连接器入口，
  找到 `taptap-maker-plugin` 点「信任」后才会启用。
- 这些技能与用户级目录中的同名技能**同时存在**，技能列表里可能看到两份。
  若只想保留项目级这一份，可在图形界面的技能管理里卸载用户级版本。
- 若要把技能提交进 GitHub / GitCode 仓库：本目录在 `F:\model\.workbuddy\`，
  而 git 仓库根目录是 `F:\model\doudizhu\`。需要额外复制一份到
  `F:\model\doudizhu\.workbuddy\skills\` 才会被 git 跟踪（建议排除 taptap-maker 的 `dist/`，2.8M）。

---

_由 WorkBuddy 于 2026-09-21 从用户级技能目录复制而来。_
