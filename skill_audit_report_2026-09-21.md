# 🔍 Skill 安全审计报告

审计时间：2026-09-21
审计工具：Skill安全审计（云鼎实验室）v1.0.0
审计方式：**纯静态文本分析**（只读，未执行任何被审技能内容）

---

## 📊 执行摘要

| 审计对象 | 版本 | 文件数 | 风险发现 | 评分 | 结论 |
|---|---|---|---|---|---|
| **web-design-engineer**（网页设计工程师） | 1.3.0 | 42 | 0 | **100** | ✅ Benign 可信 |
| **taptap-maker**（TapTap制造） | 1.0.0 | 24 | 0（2 项信息性提醒） | **85** | ✅ Benign 可信 |
| **superpowers**（Superpowers 工程方法论） | 1.0.0 | 8 | 0 | **100** | ✅ Benign 可信 |
| **skills-security-check**（审计工具本身） | 1.0.0 | 3 | 0 | **100** | ✅ Benign 可信 |

- 🔴 Malicious（恶意）：**0 个**
- ⚠️ Suspicious（可疑）：**0 个**
- 📝 信息性提醒：2 个（非风险项，不计入风险总数）

---

## 🔴 Malicious（恶意）风险发现

✅ 未发现 Malicious 风险

---

## ⚠️ Suspicious（可疑）风险发现

✅ 未发现 Suspicious 风险

---

## 📝 信息性提醒（非风险项）

1. **示例代码中的包管理命令**（web-design-engineer，信息性提醒）
   - **位置**：`README.md:411`、`README.zh-CN.md:411`
   - **代码片段**：`cd demo/web-design-engineer-demo && npm install && npm run dev`
   - **说明**：仅出现在 README 的**演示工程运行说明**中，属于教学示例，需用户手动复制执行，技能本身不会自动安装任何依赖。且 `npm install` 作用于本地 `demo/` 目录，不涉及全局安装。
   - **建议**：无需处理。

2. **文档中的 npx 兼容模式说明**（taptap-maker，信息性提醒）
   - **位置**：`docs/MAKER_MCP_CONNECTION_TROUBLESHOOTING.md:162,299,331`、`skills/taptap-maker-local/SKILL.md:395`
   - **代码片段**：`npx -y -p @taptap/maker@<exact-version> taptap-maker ...`
   - **说明**：文档**明确要求固定精确版本**，并多处注明「禁止省略版本误启 npm `latest`」——这是**良好的供应链安全实践**，而非风险。当前默认路径为插件内置 runtime（`bin/run-node` + `dist/maker.js`），npx 仅为显式兼容回退模式。
   - **建议**：无需处理。

---

## 📋 详细检查结果

### 命令执行与权限检查

| 技能 | 命中 | 分析 |
|---|---|---|
| web-design-engineer | 0 | 无任何命令执行代码 |
| superpowers | 0 | 纯 Markdown 方法论文档 |
| taptap-maker | 32（全部为 `dist/maker.js` 内正则 `Regex.exec()` / `unlinkSync` 等运行时库代码） | 逐一核对：命中来自打包依赖（ajv / modelcontextprotocol sdk / execa 等）内部实现，非技能作者新增的可疑执行逻辑 |
| skills-security-check | 0 | 仅声明 `allowed-tools: Read, Grep, Glob, Bash`（只读审计用途） |

`sudo` / `chmod 777` / `runas` / `Set-ExecutionPolicy`：**3 个目标技能中均未发现可用于权限提升的调用**（taptap-maker 中 2 处 `sudo` 字样均出现在文档的**排错说明**里，明确劝阻执行 `chown ~/.npm`）。

### 文件操作与敏感路径检查

- `~/.ssh`、`id_rsa`、`id_ed25519`、`.aws`、`.kube`、`credentials`、`private_key`：**3 个技能全部 0 命中**
- 删除类操作：web-design-engineer / superpowers 均为 0；taptap-maker 的 5 处命中集中在 `dist/maker.js` 的注册状态文件清理（`unlinkSync(statePath)`）与日志轮转删除，目标为插件自身状态文件与日志目录，**不涉及系统路径**
- Windows 敏感路径（`C:\Users`、`%APPDATA%`）批量读取：未发现

### 自动执行入口检查（重点）

taptap-maker 是本批唯一带**自动执行入口**的技能，逐项核对如下：

| 入口 | 内容 | 判定 |
|---|---|---|
| `hooks/hooks.json` | 注册 `SessionStart` 钩子，执行 `node hooks/session-start.cjs` | ⚠️ 需核验 |
| `hooks/session-start.cjs` | 仅做 **只读检查**：调用内置 CLI `plugin inspect --client workbuddy --json`，检测是否存在重复注册的旧 MCP，然后把结果作为上下文输出 | ✅ 安全 |
| 关键行为 | 检出冲突时**明确要求先向用户说明并征求确认**，原文：「只有得到用户明确确认后，才执行 … ；未确认时不得修改配置」——无任何静默修改配置的行为 | ✅ 安全 |
| `bin/run-node` / `run-node.cmd` | Node 运行时定位器：按 `WORKBUDDY_EXTRA_PATHS` → WorkBuddy 托管版本 → PATH 顺序查找，只 `exec` 找到的 node | ✅ 安全 |
| `bin/taptap-maker(.cmd)` | 转发到 `dist/maker.js` | ✅ 安全 |
| `.mcp.json` | 声明 MCP 服务 `taptap-maker-plugin`，命令为内置 `run-node dist/maker.js`，**无远程地址、无外联域名** | ✅ 安全 |

### 网络请求检查

- **web-design-engineer**：120 个 URL，全部为 `cdn.jsdelivr.net` 上的**设计参考图**（README 图示）与 Anthropic / Cursor / Claude Code 官方文档链接，纯文档引用，无自动请求行为
- **superpowers**：0 个 URL
- **taptap-maker**：88 个 URL，主要为 JSON Schema 规范地址（`json-schema.org`、`tools.ietf.org`、`w3.org`）、npm 包内注释地址，以及插件官方仓库 `github.com/taptap/instant-games-open-mcp`
- **Base64 长串检测**：无任何「编码后管道执行」载荷。taptap-maker 的 216 处命中经核验全部为 `dist/maker.js` 中 **webpack/esbuild 打包产物**的模块名与哈希串（如 `_modules/@modelcontextprotocol/sdk/...`），不是隐藏载荷
- **未发现任何 `curl | bash`、`wget | sh`、下载后 eval 的远程执行模式**

### 远程脚本深度分析

本次三个技能**均不存在「自动下载并执行远程脚本」的行为**，故无需触发远程脚本内容抓取分析。

### 依赖安装风险检查

- **全局安装（未固定版本）**：未发现
- **虚拟环境隔离**：taptap-maker 文档要求使用插件内置版本化 runtime，且明确指出「禁止省略版本落到 npm latest」；web-design-engineer 的依赖示例作用于本地 demo 目录
- **非官方源安装**：未发现（无 `--index-url` / `--registry` 指向第三方源的配置）
- **从代码仓库安装**：未发现 `git+https://...@分支` 形式的未固定引用

---

## 💡 总体建议

1. **三个技能均可安全使用**，无投毒风险。
2. **taptap-maker 带 MCP 服务与 SessionStart 钩子**：其 MCP（`taptap-maker-plugin`）在首次启用时需要你在连接器管理页点「信任」才会激活；激活后它会向 TapTap Maker 平台发起游戏项目相关操作（创建/同步项目、提交构建等），这属于其**声明功能范围内**的正常外联，使用前留意即可。
3. **taptap-maker 的钩子会在每次会话启动时做一次只读检查**，用于提醒你是否存在重复的旧 MCP 注册——这是善意设计，不会静默改配置。
4. 本次审计为静态分析；若后续技能自动更新版本，建议重新审计。

---

## ✅ 审计结论

**风险等级**：✅ **Benign（可信）**

**使用建议**：三个技能**可以安全使用**。

- `web-design-engineer`（100 分）— 纯文档 + 设计方法论，无任何可执行代码
- `superpowers`（100 分）— 纯 Markdown 工程方法论
- `taptap-maker`（85 分）— 含可执行 CLI 与 MCP 服务，但脚本逻辑透明、无网络外联硬编码、钩子只读且需用户确认才改配置，作者为 TapTap 官方团队（MIT 协议）
