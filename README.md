# 欢乐斗地主 · 本地大模型 AI 版

> 由本地大模型（Qwen3-4B）驱动的单机欢乐斗地主：AI 叫地主、AI 出牌、AI 骚话，Token 积分下注，免安装、点开即玩。

![Python](https://img.shields.io/badge/Python-3.13%20(embedded)-blue)
![LLM](https://img.shields.io/badge/LLM-Qwen3--4B%20(GGUF)-purple)
![Runtime](https://img.shields.io/badge/推理-llama.cpp%20Vulkan-green)

**仓库地址**：GitHub · <https://github.com/mw2wbyys6t-sudo/doudizhu-ai> ｜ GitCode · <https://gitcode.com/gcw_VNt8FmMN/121>


## 这是什么

一个**完全跑在你自己电脑上**的 AI 斗地主游戏：

- **两个 AI 对手由本地大模型驱动**——叫地主决策、出牌策略、牌桌"骚话"全部由 Qwen3-4B（GGUF 量化版）推理产生，不联网、不调用任何云端 API；
- **规则引擎 100% 兜底**——代码先枚举所有合法出牌，模型只做策略选择，非法牌会被拦截，永不卡死；模型掉线时自动降级为启发式 AI；
- **Token 积分下注**——开局选底注（50/100/200/500），结算公式 `底注 × 叫分 × 倍数`（炸弹/王炸/春天翻倍），积分持久化到 `wallet.json`，输了一键重置；
- **免安装点开即玩**——整合包内嵌 Python 运行时与 llama.cpp（Vulkan），解压双击一个 bat 即可开玩。

## 一键下载 / 自动发布内容

打包发布时，以下内容**全部自动化**，用户只需双击一个脚本：

| # | 自动发布内容 | 说明 | 触发时机 |
|---|---|---|---|
| 1 | 内嵌 Python 3.13 运行时 | 免安装，已打进整合包，无需用户安装 Python | 解压即用 |
| 2 | llama.cpp 推理服务 | Vulkan 版 `llama-server.exe`，有 N 卡自动 GPU 加速 | 已打进整合包 |
| 3 | **AI 大模型 Qwen3-4B-Q4_K_M.gguf（2.3GB）** | 首次运行自动从魔搭 ModelScope 下载，支持断点续传 | 首次运行自动 |
| 4 | 游戏服务 + 网页前端 | FastAPI 后端自动起在 `127.0.0.1:7860`，浏览器自动打开 | 每次双击自动 |
| 5 | 一键启动脚本 `启动游戏.bat` | 检测模型 → 拉起推理服务 → 拉起游戏 → 开浏览器，全链路自动 | 用户双击 |
| 6 | Token 钱包与积分存档 | `wallet.json` 自动创建/读写/持久化 | 首局自动 |

> 💡 **想直接玩？点击下方链接下载整合包，解压后双击「启动游戏.bat」即可**（模型会在首次启动时自动从魔搭下载，约 2.3 GB，支持断点续传）：
>
> **[⬇ 一键下载整合包（约 50 MB）](https://github.com/mw2wbyys6t-sudo/doudizhu-ai/raw/main/dist/欢乐斗地主AI版_免安装整合包.zip)**
>
> 下载备用：[raw 直链](https://raw.githubusercontent.com/mw2wbyys6t-sudo/doudizhu-ai/main/dist/欢乐斗地主AI版_免安装整合包.zip) ｜ [GitCode 镜像仓库](https://gitcode.com/gcw_VNt8FmMN/121)

## 调用了哪些 Skill（AI 开发过程说明）

本项目由 WorkBuddy AI 助手端到端开发，过程中调用并遵循了以下 Skill 的工程规范：

| Skill | 在本项目中的作用 |
|---|---|
| **dev-expert（编程专家）** | 总体工程纪律：规则引擎的根因式调试（如对局卡死 → 定位到 `logging` 未导入的静默线程死亡链）、FastAPI 分层架构、端到端测试策略（300 局引擎压测 + 3 局全座位 API 回归）、错误码规范（非法出牌 400 / 无效会话 404） |
| **frontend-ui-engineering（前端 UI 工程）** | 前端重做：真实扑克牌面与毡布牌桌的组件化样式、手牌扇形布局与选牌交互、结算弹窗与侧栏对局记录、键盘可访问性（Enter 出牌 / P 不要 / H 提示）、响应式适配 |

## 项目结构

```
doudizhu/
├── server.py            # FastAPI 游戏服务（会话管理 / AI 轮次调度 / 钱包结算）
├── game/
│   ├── cards.py         # 斗地主规则引擎：牌型识别、比较、合法出牌枚举
│   ├── engine.py        # 游戏状态机：发牌、叫分、出牌、结算、春天判定
│   ├── ai.py            # LLM + 规则混合 AI：候选构造、JSON 解析、启发式兜底
│   └── wallet.py        # Token 钱包：余额持久化、结算、历史记录
├── static/              # 网页前端（原生 HTML/CSS/JS，无框架）
├── e2e_test.py          # 端到端测试：拉起服务打完整对局 + 非法输入校验
├── test_engine.py       # 引擎压测：300 局随机种子对局
├── dist/                # 免安装整合包（zip，一键下载即玩）
├── README.md
└── README.html          # 本 README 的 HTML 版本
```

## 本地开发运行

```bash
# 1. 安装依赖
pip install fastapi "uvicorn[standard]" requests

# 2. 启动 AI 推理服务（可选，不起则用启发式 AI）
llama-server.exe -m Qwen3-4B-Q4_K_M.gguf --port 8000 -ngl 99 --no-warmup --jinja

# 3. 启动游戏
python server.py --port 7860

# 4. 浏览器打开 http://127.0.0.1:7860
```

## 技术要点

- **架构**：前端（原生 JS 轮询状态）↔ FastAPI（会话 + 状态机）↔ llama.cpp（OpenAI 兼容 `/v1` 接口）
- **AI 决策**：规则引擎枚举合法牌型 → 构造候选列表 prompt → 模型输出 JSON `{"play": 编号, "say": "骚话"}` → 代码校验 + 启发式兜底
- **量化**：Qwen3-4B Q4_K_M（2.3GB），6GB 显存可全量 offload，实测 GPU 推理流畅

## License

仅供学习交流使用。斗地主玩法规则无版权，Qwen3 模型遵循 Apache-2.0（阿里云通义）。
