# 自动提交（Auto Commit）

一有新内容就自动提交并推送到所有远端。分两层，互不冲突：

| 机制 | 触发时机 | 作用 |
|---|---|---|
| **文件监听守护** `tools/autocommit.py` | 工作区文件内容发生变化 | 静止 N 秒后自动 `add → commit → push` |
| **git 钩子** `.githooks/post-commit` | 每次 commit（哪怕是你手动敲的） | 自动推送到所有远端 |

## 怎么用

```
双击 tools\启动自动提交.bat            ← 启动监听（前台运行，Ctrl+C 停止）
双击 tools\启动自动提交.bat --install-hooks   ← 只装 git 钩子，不用常驻监听
```

命令行：

```bash
python tools/autocommit.py                  # 常驻监听
python tools/autocommit.py --once           # 只检查一次（适合放计划任务）
python tools/autocommit.py --dry-run --once # 试跑：只报告将要提交什么
python tools/autocommit.py --status         # 看哪些内容会被自动提交
python tools/autocommit.py --install-hooks  # 启用 post-commit 钩子
python tools/autocommit.py --no-push        # 只提交不推送
python tools/autocommit.py --remotes github # 只推某一个远端
python tools/autocommit.py --include-dist   # 让 dist/*.zip 也参与自动提交
python tools/autocommit.py --verbose        # 打印每一次检测到的变动
```

## 远端与网络

两个远端都会推：`origin` = GitCode，`github` = GitHub。
网页上的远端顺序按 `git remote` 决定。

**GitHub 直连在国内经常连不上**，脚本的处理方式是：先直连，失败后自动探测本机代理
（依次试 7897 / 7890 / 10809 / 10808 / 7891）再重试一次，仍失败就只记日志。
要指定代理：`python tools/autocommit.py --proxy http://127.0.0.1:7897`。

## 不会自动提交什么（重要）

这些被排除，避免把仓库越搞越大：

- **`dist/*.zip`** —— 免安装整合包 51 MB。每次提交一个二进制历史副本会永久留在 git 里，
  仓库会迅速膨胀。整合包改动后想提交，请手动执行：
  ```
  git add dist && git commit -m "chore: 更新整合包" && git push origin main
  ```
  确实想让它也自动提交，就加 `--include-dist`。
- `runtime/`、`model/`、`*.gguf`、`__pycache__/`、`*.pyc`、`*.log`（沿用 `.gitignore`）

## 打包发行（`tools/pack_release.py`）

重新生成免安装整合包并**校验必需条目**，可重复执行：

```bash
python tools/pack_release.py            # 打包到默认位置 + 校验
python tools/pack_release.py --check    # 只检查已有 zip（含 zip 完整性）
python tools/pack_release.py --src <发行暂存目录> --out <产物.zip>
```

默认路径按脚本位置自动推导，不写死盘符：

| 项 | 默认值 |
|---|---|
| 源（发行暂存目录） | `<仓库同级>/release/欢乐斗地主AI版` |
| 产物 | `<仓库同级>/release/欢乐斗地主AI版_免安装整合包.zip` 与 `<仓库>/dist/欢乐斗地主AI版_免安装整合包.zip` |

校验内容：12 项必需条目（启动脚本、`runtime/local_agent.py`、`skills/index.json` 等）+ `zipfile.testzip()`
完整性。**少一项或压缩包损坏就返回非 0**，适合接进 CI。

> ⚠️ 若 README 挂了 `dist/*.zip` 的在线下载链接，发布后必须手动提交一次该 zip，
> 否则用户点击下载拿到的是**旧包**（不报错，但功能缺失）。
> 对照命令：`git cat-file -s HEAD:dist/xxx.zip` 与 `ls -l dist/xxx.zip` 字节数应一致。

## 随仓库分发的技能包（`.workbuddy/skills/`）

4 个技能随仓库一起版本化，供 WorkBuddy 直接读取（项目级技能目录）：

| 技能 | 类型 | 说明 |
|---|---|---|
| `superpowers` | 文档型 | 工程方法论：规格 → 计划 → 红绿 TDD → 评审 |
| `web-design-engineer` | 文档型 | 前端/视觉：页面、仪表盘、原型、动效 |
| `taptap-maker` | 工具型 | 游戏项目工作流（需 Node 环境） |
| `skills-security-check` | 文档型 | 安装第三方技能前的安全审计 |

同一份技能也已打进整合包的 `skills/`，最终用户解压即得；仓库里这份是给开发/协作侧用的。
安全审计结论见 `../skill_audit_report_2026-09-21.md`（均 Benign，无硬编码凭据）。



- **绝不 force push**，绝不自动合并冲突。推送被拒（远端有新提交）只报告，由你处理。
- **合并/变基/拣选进行中不提交**，索引被 `.git/index.lock` 占用时等待。
- 同一个仓库**只允许一个监听进程**（PID 记录在 `.git/autocommit.pid`）。
- 手动提交想临时跳过推送：`SKIP_AUTOPUSH=1 git commit -m "..."`。

## 日志

- `tools/autocommit.log` —— 监听与钩子的全部动作、每次 push 的结果。
- `git config --get core.hooksPath` —— 显示当前是否启用了钩子。
- 关闭钩子：`git config --unset core.hooksPath`

## 开机自启（可选）

把 `tools\启动自动提交.bat` 的快捷方式丢进
`shell:startup`（Win+R 输入即可打开）文件夹，开机就会自动进入监听。
