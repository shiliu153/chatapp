# Superagent 本地开发流程设计(v1)

- 状态:**待实施**(P0–P4)
- 决策日期:2026-11-07
- 相关:[docs/ops/release.md](../../ops/release.md)(发版清单)、[CONTRIBUTING.md](../../../CONTRIBUTING.md)(硬约束)、[CLAUDE.md](../../../CLAUDE.md)(项目全貌)

## 1. 背景与目标

本机 WSL(Ubuntu-24.04)已装好 `dsh-superagent`(DeepSeek Harness 的**主动型编程智能体** bundle)。它监听 GitHub 仓库,把「允许的人发出的请求」变成 Ticket,在自己的 Session 与 git worktree 里干活,产物是 PR 或一条结论,然后回到原对话里回话。

原流程(见 CLAUDE.md「核心契约与纪律」「发布流程」)是**单人在 Windows 会话内联完成一切**:设计、写码、跑测试、开 PR、手测、合并、发版。这条流程本身已经相当严格(六条 CI 轨 + 一堆同改门禁),但它的人力和上下文成本全部压在一个人身上,而且「本地全绿」依赖 Windows 上的 anaconda + Windows Flutter + 安卓模拟器,与 CI(Linux)不同源。

**目标**:把「实现」这一段移交给 WSL 里的 worker,**人的注意力只花在两处——开单确认与 PR 结论**;同时不降低既有的契约门禁与发版纪律。

**非目标**:不追求「无人值守上线」——**发版、部署、生产运维永远留给人**。
合并已按 [2026-11-08 自动化阶梯设计](2026-11-08-superagent-automation-ladder-design.md) 分级:
`docs/**` 白名单内可由**确定性 workflow**(不是模型)自动 squash 合并(L2),其余路径仍由人合;详见该文 §5 的修订表。

## 2. 现状事实(2026-11-07 实测,不是假设)

| 项 | 实测值 |
|---|---|
| WSL | Ubuntu-24.04,NAT 模式,20 核 / 15 GB;`/mnt/d/pycharmproject/chat_app` 可读写 |
| dsh | `@deepseek-ai/dsh@0.2.1-rc.5`(全局 npm) |
| superagent 检出 | `/root/dsh-superagent`(含 `scripts/dsh-superagent`) |
| superagent profile | `/root/.dsh/profiles/superagent`(port **3082**,Feishu Source 关闭) |
| stateDir | `/root/.dsh/state/superagent`(含 `orchestrator.sqlite`、`worker-bin/gh`、`work/`) |
| 模型 | provider `wb-pool` / `cn:deepseek-v4.1-flash`(`WB_POOL_API_KEY` 在 `/root/.dsh/superagent.env`) |
| 启动方式 | `bash /root/start-superagent.sh start|status|stop`(已内置宿主代理与 PATH) |
| 仓库绑定 | `shiliu153/chatapp`;克隆在 `/root/src/chatapp`(worktree 母体) |
| agent 账号 | **`shiliu655`**(`gh-agent` wrapper 在 `/root/.local/bin/gh-agent`) |
| 授权 | 允许清单只有 `shiliu153`;bots 含 `dependabot[bot]`;eval 模式 **`observe`**;`maxWorkers=3` |
| 团队规则 | 内置两条:`Copy fixes`、`Visual fixes` |
| prepare 命令 | `export https_proxy=http://<宿主网关>:7897 … && git fetch … && git worktree add -b agent/<短名> …` |
| 已验证的一单 | Issue #92(README 标点)→ PR #95,**当前仍 OPEN 未合并**(3 增 3 删) |
| WSL 缺口 | 无 MySQL/Redis;`docker` 命令不可用(Docker Desktop 未开 WSL 集成);`flutter` 指向 `/mnt/d/.../flutter`(Windows SDK);`/root/.ssh` 为空(无生产密钥) |

结论:**管道是通的**(Issue → Ticket → worktree → PR),缺的是「worker 能不能自己证明代码是对的」以及「PR 就绪之后谁收尾」。

## 3. 设计

### 3.1 一句话

**人只说需求,agent 只交 PR;CI 是唯一裁判,合并与发布永远留给人。**

### 3.2 角色与边界

| 角色 | 干什么 | 明确不干什么 |
|---|---|---|
| 人 + Windows 侧 DSH 会话 | 把口语需求写成带验收口径的 Issue;评审 PR;碰 `app/` 的必须模拟器手测留证;squash 合并;发版/部署/生产运维;superagent 自身运维(巡检、retry、升级) | 不写实现细节 |
| WSL superagent worker | 在独立 worktree 里实现 + 写测试 + 改文档;**本地 `scripts/verify.sh` 全绿再推**;开 PR;在自己 Thread 里回应 CI 红与 review 意见;卡住就 `blocked` 提一个具体问题 | 不自合、不碰生产、不改 `flutter/`、不做发版 |
| CI(六条轨) | backend / app / web / web-e2e / imserver / contract,唯一真值 | — |

### 3.3 工单生命周期

```
需求(口语,跟人说人话)
  → Windows 会话**先做需求分析**(改什么 / 属哪条栈 / 验收口径能否被 worker 在不违规前提下自证)
  → Windows 会话写成 Issue(模板:背景/验收口径/影响面/禁止事项/该跑哪条栈)
  → 评论 @shiliu655 触发(或新 Issue 正文直接提及)
  → superagent 评估 → Ticket → worker 在 worktree 实现
  → scripts/verify.sh <该跑的栈> 全绿 → push + PR
  → CI 六轨绿 → 面板 Overview 与 Issue 收到「PR #N 就绪」
  → 人:评审 + (碰 app/ 则模拟器手测) → squash 合并 → 删分支
  → **合并后立刻同步本机**:WSL 母体与 Windows 仓库都 pull 到合并后的 master(先 pull,再 prune)
  → bash scripts/superagent-prune.sh --apply 清 worktree 与 refs/dsh-superagent/*
  → (要上线时)Windows 侧按 docs/ops/release.md 发版
```

沿用既有铁律,不因 agent 参与而放宽:**分支 → PR → CI 全绿 → squash 合并 → 同步本机 → 只部署 `origin/master` 的 SHA**。

**三条硬规矩(2026-11-07 首单验收后补,依据见 plans §6–§7):**

1. **合并后必须同步本机,不是「下次再说」。** 母体 `/root/src/chatapp` 不会自己跟随 `origin/master`,
   而人要跑的 `superagent-prune.sh` 就住在母体里 —— 不同步就会用旧版脚本(#105 之前按
   `merge-base --is-ancestor` 判定,squash 合并必然判 `merged=no`,worktree 清不掉)。
   顺序固定:**先 `pull --ff-only`,再 prune**;Windows 仓库同时 pull(人读的 `docs/` 在那儿)。
2. **纯文档 PR 直接合并。** 只动 `docs/**` 的 PR 六轨 `paths` 都不含它,**没有 check runs 是正常的**;
   本地 `scripts/verify.sh contract` 绿 + 人看完 diff 即可 squash 合并,不再单独占一轮「等确认」。
3. **先分析,后提 issue。** 需求分析在本机会话里做完再开单:改什么、属哪条栈、
   验收口径能不能被 worker 在**不违反 `AGENTS.md`** 的前提下自证。
   凡是「合并后才发生」的事(例如「某条轨被触发」)一律写进「留给人验」,不要写成 worker 的验收项。

### 3.4 「一单」的边界

- **一单只碰一条栈**(backend / web / imserver / app / 纯文档)。跨栈必须拆单。
- 契约类联动算同一条栈的附带改动:OpenAPI 重生成、`docs/api/*.md`、WS fixture 三端同步、注释覆盖、版本号三处、心跳 token 双份 —— 触发即必须在同一 PR 内做完,不做就是 CI 红。
- 一单 = **一次可独立验收的改动**,不是「一个想法」。想法先落 Issue,再由人拆单。

### 3.5 验证前移:WSL 自足验证环境(P0 核心)

当前 worker 在 WSL 里跑不了后端测试,只能靠 CI 反复红绿——这是最烧人注意力的一环,必须先修。

1. **Docker Desktop → Settings → Resources → WSL integration 打开 Ubuntu-24.04**,WSL 内可用 `docker`。
2. 新增 **`docker-compose.ci.yml`**(仓库根):把 `.github/workflows/backend.yml` 的 `services` 抽成 compose,参数与 CI 逐项对齐:
   - `mysql:8.0`,`MYSQL_DATABASE=chatapp_dev` / 用户 `chatapp` / 密码 `chatapp_ci`,端口 3306
   - `redis:7-alpine`,端口 6379
   - 关键坑同步:`DB_SSL_DISABLED=0`(CI 走 TLS,因为 MySQL 8 `caching_sha2_password` 在非 TLS 连接上做 RSA 交换会让 PyMySQL 崩);测试库 `test_chatapp_dev` 需 `GRANT` 给 `chatapp` 用户(CI 里已有这一步,compose 用 init SQL 落地)
3. 新增 **`scripts/verify.sh`**(POSIX sh,Linux / WSL / Git Bash 通用),按栈分派:

   | 子命令 | 做什么 |
   |---|---|
   | `backend` | 起 compose 依赖 → `manage.py migrate` → `manage.py test` → `manage.py spectacular --file ../docs/api/openapi.yml --validate` + `git diff --exit-code` → `python -m unittest perf.test_run` |
   | `web` | `npm ci` → `npm run gen:api` → diff → `type-check` → `lint` → `test:run` → `build` |
   | `imserver` | `docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test_http.sh` |
   | `app` | `flutter analyze`(零告警)→ `flutter test` |
   | `contract` | `python scripts/sync_version.py --check` → `python scripts/check_app_models.py` |
   | `all` | 依次跑全部(CI 等价) |

   约定:未指定子命令时打印用法退出 1;任一栈失败即非零退出;`--keep-deps` 不拆容器(便于连续跑)。**该脚本是 CI 的镜像,不是 CI 的替代**:CI 的 workflow 不改成调它,以免一处出错两边同时瞎。
4. WSL 内装 **Linux Flutter 3.47.2** 到 `~/flutter`(与 `app.yml` 的 `flutter-version` 一致),加入 worker 的 `PATH`。**不使用** `/mnt/d/.../flutter`(Windows SDK 跨盘运行,不可靠且慢)。
5. 依赖/环境变量单一来源:`chatapp/.env`(开发)与 compose 内联环境(CI 等价)分开,不互相覆盖;`verify.sh` 打 CI 等价变量。
6. 代理:目前硬编码在 `prepare` 里(`http://<宿主网关>:7897`)。迁移到 `/root/start-superagent.sh` 已导出的环境变量 + worker 会话环境,`prepare` 里只留 `git fetch/worktree`。

### 3.6 仓库里给 agent 的说明书(P1)

仓库目前**没有 `AGENTS.md`**,worker 只能读 `CLAUDE.md`(人读的全景导航 + 大量历史)。新增:

- **`AGENTS.md`(仓库根)** —— 只放执行约束:
  - 硬契约清单(逐条给「违反→哪条测试红」):错误契约、IM 副作用唯一入口 `im/tasks.py`、心跳 token 双份、WS fixture 三端同改、API 文档与 OpenAPI 同改、Python 注释规范、版本号三处、`docs/ops/release.md` 记录行
  - **verify 命令表**(3.5 的子命令)
  - PR 规矩:一 PR 一栈、commit message 规范(现有 `feat(scope):`/`docs(scope):` 风格)、PR 描述必须写「改了什么 / 怎么验的 / 留了什么给人验」
  - 禁止事项:不自合、不 ssh/scp 生产、不改 `flutter/`、不改 `.remember/`、不发版、不动 `.env` 与密钥
  - 冲突时以 `docs/` 与测试为准
- **`.github/ISSUE_TEMPLATE/agent-task.yml`**:背景 / 验收口径(可执行、可判断)/ 影响面(哪条栈)/ 禁止事项 / 该跑哪条 verify 栈 / 是否碰 `app/`
- **`.github/pull_request_template.md`**:同上四问 + 「App 手测证据(仅 app/ 改动)」勾选项

同时修改全局约定 `~/.dsh/AGENTS.md`:现有「superpowers 任务一律内联、不派子 agent」与新流程冲突,改为 **「设计与评审内联;实现类工作走 superagent 工单」**。

### 3.7 授权、门禁与禁止

- 允许清单:仅 `shiliu153`;bots:`dependabot[bot]`。
- eval 模式:**保持 `observe`**,直到 P0–P2 跑通约 10 单;之后再评估是否对「文档/typo」类开主动规则。主动规则一开就必须先观察一轮再放开。
- 规则集:保留 `Copy fixes`、`Visual fixes`;建议新增 `deps`(patch 级依赖升级且 CI 绿)。明确**不自动做**:跨栈重构、DB 迁移、imserver 协议帧、发版。
- `blockedCommands`:`ssh`、`scp`、`rsync`、`gh pr merge`、`gh release`、以及任何生产 compose/部署脚本。**注意:shim 只按名字拦,不是安全边界**(worker 可用绝对路径绕过)。真正的边界是「WSL 里没有生产密钥」——`/root/.ssh` 现在为空,保持为空。
- 合并:**LLM 永不自合** —— worker 没有合并能力(不给它配 `gh pr merge`,并在 `AGENTS.md` 写死禁止)。
  白名单(`docs/**`)内的自动合并由 `.github/workflows/auto-merge.yml` 执行,**决策权在确定性规则而非模型**;
  白名单外的 PR 仍由人 squash。见 [自动化阶梯设计](2026-11-08-superagent-automation-ladder-design.md) §4。

### 3.8 巡检与 superagent 自身运维

- 面板:Windows 浏览器开 `http://127.0.0.1:3082`(Overview 只列「等人」的项,健康时为空)。
- **每小时巡检**(官方要求):在 Windows 常用 profile 建定时任务,跑
  `wsl -e bash /root/start-superagent.sh --profile superagent status`,按退出码处置 ——
  `0` 静默 / `2`、`3` 只报告不重启 / `1` 用
  `wsl -e bash /root/start-superagent.sh --profile superagent --respect-stop restart`。
  注意该任务必须建在**常用 profile** 而不是 `superagent` profile 里(服务挂掉时巡检还要能跑)。
- 新增 **`docs/ops/superagent.md`**:启动停止、Ticket 卡 `blocked/failed` 怎么 retry、prepare 失败怎么读、worktree 清理、升级步骤(先备份 `orchestrator.sqlite`)、数据库不可降级的回滚前提。

### 3.9 注意力预算(噪音控制)

- `maxWorkers` 先降到 **1–2**,观察一周再回到 3。
- worker 的报告只写结论与「需要人做什么」;过程细节留在面板,不进对话。
- 每个 PR 只请求一次注意:CI 绿之前不通知人。

## 4. 与旧流程的差异(哪些作废)

| 旧 | 新 |
|---|---|
| 所有实现都在 Windows 会话内联做 | 实现默认交给 WSL worker;Windows 只做决策/验收/发布 |
| 「本地全绿」= Windows anaconda + Windows Flutter | 「本地全绿」= `scripts/verify.sh`(WSL 与 CI 同源) |
| 手写 PR 描述、凭记忆守契约门禁 | Issue/PR 模板 + `AGENTS.md` 强制 |
| 分支随手建 | 分支由 Ticket 派生 `agent/<短名>`,工单结束即删 |
| superpowers plans「一律内联执行」 | 设计与评审内联;实现走工单,specs 仍是设计真相,plans 变成工单来源 |
| 一人串行 | 人做的部分仍是串行,实现可 1–3 并行 |

**不动的部分**:六条 CI 轨及其门禁、发版清单与 `create_release.py`、模拟器验收要求、生产运维手册。

## 5. 落地阶段(每步可独立验收)

| 阶段 | 内容 | 验收口径 |
|---|---|---|
| **P0 环境** | WSL docker 集成、`docker-compose.ci.yml`、`scripts/verify.sh`、Linux Flutter 3.47.2、代理迁移 | 在 WSL 里 `scripts/verify.sh backend web app` 三条栈全绿;与 CI 同一次提交结果一致 |
| **P1 说明书** | `AGENTS.md`、Issue 模板、PR 模板、改 `~/.dsh/AGENTS.md` 全局约定 | 用一个纯文档工单跑通:worker 自己跑 verify、开 PR、CI 一次绿 |
| **P2 调 prompt** | 团队段:披露行、review bots、commit author;**删掉 auto-merge 段落** | 新开一单,PR 描述带出模板要求的四项 |
| **P3 巡检** | 每小时 schedule、`docs/ops/superagent.md`、故障与回滚流程 | 手工 kill 服务后巡检自动恢复并在必要时只报告 |
| **P4 度量** | 记录两周指标 | 见 §6 |

## 6. 验收标准

- **主指标**:一个工单从开单到「可合 PR」,人只需出手 **2 次**(开单确认 + PR 结论),CI 往返 **≤1 轮**。
- 副指标:Issue→合并时长;每单 token 消耗;`blocked` 单占比;巡检误报次数。
- 红线(出现即回退流程):CI 反复红 >2 轮;agent 产出需要人重写 >50%;任何一次越过禁止事项。

## 7. 风险与对策

| 风险 | 对策 |
|---|---|
| App UI 无法在 WSL 自测(模拟器只在 Windows) | worker 只负责码与 analyze/test;PR 模板强制「已模拟器手测」勾选才合 |
| 并行 worker 吃掉 token 预算 | 先 1–2 个;按单计成本 |
| worktree 堆积 | 工单结束即 `git worktree prune` + 删 `refs/dsh-superagent/*` |
| worker 越权碰生产 | 无生产密钥 + blockedCommands + 人合门禁,三道 |
| WSL 代理失效导致 fetch 假失败 | 代理写进 WSL shell 环境;巡检带连通性检查 |
| 本地 verify 与 CI 漂移 | compose 参数逐项对齐 CI;每季度用一次红单校验 |
| 说明书写成第二份 CLAUDE.md | `AGENTS.md` 只写「怎么做对」,不写历史;与 CLAUDE.md 交叉引用 |

## 8. 未决问题(P0 不依赖它们,选定前按括号内默认值执行)

1. PR #95(纯文档,3 增 3 删)是**按新流程评审后合并**,还是关掉重开一单作为 P1 验收样本?(默认:评审后合并,当作第一条「人合」样本)
2. `maxWorkers` 最终值?(默认:先 2)
3. 是否给 worker 开「依赖升级」主动规则?(默认:不开,继续只接显式请求)

## 附录 A:本机速查

```bash
# 服务
bash /root/start-superagent.sh start|status|stop
# 面板
http://127.0.0.1:3082
# 管理 API(只读示例)
curl -s -H 'x-orchestrator-request: 1' http://127.0.0.1:3082/orchestrator/api/settings | jq .blocks
# agent 身份与 PR
~/.local/bin/gh-agent api user --jq .login         # → shiliu655
~/.local/bin/gh-agent pr list --repo shiliu153/chatapp
# worktree
git -C /root/src/chatapp worktree list
```
