# superagent 运维手册(WSL)

> 面板:`http://127.0.0.1:3082`(Windows 浏览器直接开)。Overview 只列「需要人」的项;健康时是空的。
> 设计见 [docs/superpowers/specs/2026-11-07-superagent-dev-workflow-design.md](../superpowers/specs/2026-11-07-superagent-dev-workflow-design.md),
> 实施计划见 [docs/superpowers/plans/2026-11-07-superagent-dev-workflow.md](../superpowers/plans/2026-11-07-superagent-dev-workflow.md)。

## 1. 启停与身份

| 事 | 命令 |
|---|---|
| 启动 / 查状态 / 停止 | `wsl -e bash /root/start-superagent.sh start` / `status` / `stop` |
| 状态退出码 | `0` 正常 · `1` 没跑 / 跑了两份 / 不响应(可试重启)· `2` 某部件报错(重启无效)· `3` 等设置 |
| agent 账号 | `~/.local/bin/gh-agent api user --jq .login` → `shiliu655` |
| agent 检出 | `/root/dsh-superagent`(升级就是 `git pull && pnpm install && pnpm build`) |
| 仓库母体 | `/root/src/chatapp`;工单 worktree 在 `/root/.dsh/state/superagent/work/` |
| 数据 | `/root/.dsh/state/superagent/orchestrator.sqlite`(**升级前必须备份**) |
| 模型 | `wb-pool` / `cn:deepseek-v4.1-flash`,密钥在 `/root/.dsh/superagent.env` |
| 代理 | `start-superagent.sh` 启动时导出宿主网关 `:7897`;代理挂了表现为 fetch / npm / pub 全部超时 |

**面板当前设置**(2026-11-07):`maxWorkers=2`、`blockedCommands=[ssh, scp, rsync]`、
`prepare` 只做 `git fetch` + `git worktree add`(代理不写在这里)、
prompt `scope`/`delivery` 追加了本项目条款(一单一条栈、verify 唯一入口、app UI 必须 draft)、
eval 模式 `observe`、允许清单只有 `shiliu153`。

## 2. 本地验证环境(worker 靠它自证)

| 组件 | 位置 / 版本 | 说明 |
|---|---|---|
| MySQL + Redis | `docker compose -f docker-compose.ci.yml up -d --wait` | MySQL `127.0.0.1:13306`、Redis `127.0.0.1:16379`;端口刻意避开 Windows 本机 3306/6379 |
| 后端解释器 | `~/venvs/chatapp`(3.12) | `scripts/verify.sh bootstrap` 建;CI 用 3.11,差异见 §6 |
| Node | `~/node22`(22.x,与 `web.yml` 一致) | Node 24 会让 web 一条 jsdom 用例失败 |
| Flutter | `~/flutter`(3.47.2,与 `app.yml` 一致) | **不要**用 `/mnt/d/.../flutter`(Windows SDK) |

一条命令跑全部五栈:`cd <工单目录> && scripts/verify.sh all`。
**web / app 必须在 Linux 文件系统上跑**——`/mnt/*` 是 9p,慢到 vitest/flutter 超时(脚本会拒绝)。

新增 WSL 发行版或换机器时的依赖清单:`docker`(Docker Desktop 的 WSL 集成)、
`python3.12-venv`、`unzip`、`xz-utils`、`git`、`tmux`。

## 3. Ticket 卡住了怎么处理

| 现象 | 处置 |
|---|---|
| `person / blocked`、`person / failed` | 在面板上直接回一句让它继续;或 **Retry**(新 Assignment,同 Session / 同目录 / 同分支) |
| `person / delivery` | Input 没送达,重试是唯一解法,**不要**删工单 |
| `The prepare command failed` | 输出里写着原因(克隆路径、代理、ref 冲突)。修好后 Retry |
| 工单跑到一半不动 | 先看面板 `load` 与 `worker` 健康位;进程在就 Retry,进程没了按 §1 重启 |
| `verify.sh` 报「没有可用的 venv」 | 跑 `scripts/verify.sh bootstrap` |

## 4. 一次工单的完整闭环(人工部分)

1. 面板 / issue 收到「PR #N 就绪」→ 评审 diff(它只是「就绪」,不等于可合)。
2. 碰 `app/` 的:PR 应为 draft → 拉分支到 Windows → 装模拟器 → 逐页手测截图 → 贴进 PR → 勾模板第 4 项。
3. CI 六轨绿 → **squash 合并** → 删分支。
4. 合并后跑 `bash scripts/superagent-prune.sh --apply` 清 worktree 与 `refs/dsh-superagent/*`。

## 5. 升级与回滚

```bash
# 1) 确认没有 Executor 正在跑(面板 Overview 无 Working)
cp /root/.dsh/state/superagent/orchestrator.sqlite /root/.dsh/state/superagent/orchestrator.sqlite.bak-$(date +%F)
cd /root/dsh-superagent && git pull && pnpm install && pnpm build
wsl -e bash /root/start-superagent.sh restart   # 从 Windows 侧执行
wsl -e bash /root/start-superagent.sh status
```

新版迁移过的库**旧版打不开**:回滚必须用上面那份备份。升级后检查面板 Prompts 里标注 `Default updated` 的段。

## 6. 已知偏差(出现「本地绿 CI 红」时先看这里)

| 偏差 | 影响 | 处理 |
|---|---|---|
| 本地 Python 3.12 / CI 3.11 | Django 5.2 两边都支持;极少数库行为不同 | 优先怀疑版本差异;必要时给 compose 加 `python:3.11` 服务 |
| 生成物校验忽略行尾 | Windows 检出是 CRLF,WSL 的 git 会把全仓算成改动 | 脚本用「比内容」而不是 `git diff --exit-code` |
| WSL 用 Docker Desktop 的引擎 | 容器端口发布在 Windows 宿主上 | 所以 13306/16379 避让本机 3306/6379 |

## 7. 授权与边界(改之前想清楚)

- 允许清单只有 `shiliu153`;bots 仅 `dependabot[bot]`;eval 模式 `observe`(proactive 只记录不执行)。
- `blockedCommands` 只是按命令名拦的 shim,**不是安全边界**;真正的边界是
  `/root/.ssh` 保持为空 + 人合 PR + 面板不配 merge CLI。
- agent 以自己的账号(`shiliu655`)提交与评论,所有动作都在仓库可见。
