# Superagent 自动化阶梯设计(L0–L4)

> 前置:[2026-11-07 Superagent 本地开发流程设计 v1](2026-11-07-superagent-dev-workflow-design.md)(下称 **v1**)。
> 本文不改 v1 的「一单一条栈 / CI 是唯一裁判 / verify.sh 唯一入口」,只回答一个问题:
> **人出现在流程里的那几处,哪些能换成确定性机制,哪些永远不能。**
> 状态:2026-11-08 起生效;L2 见 §4(2026-11-08 实现),**L4 见 §6(2026-11-13 实现)**。

## 1. 现状事实(2026-11-08 实测,不是假设)

| 事实 | 值 | 来源 |
|---|---|---|
| 并行上限 | `executor.maxWorkers = 2`(第 3 单排队) | 面板 `/orchestrator/api/settings` |
| 阻塞命令 | `['ssh','scp','rsync']`(按**命令名**拦,**拦不住 `gh pr merge`**) | 同上 |
| 主动能力 | `eval.mode = observe`(只记录,不主动开单) | 同上 |
| worker 是否派子 agent | **否**:`delegationDepth: 0`,preset `dsh-superagent-worker` | 工单会话头 `session.v4.jsonl` |
| 隔离单元 | 一单 = 一个 worktree + 一条 `agent/<slug>` 分支 + 一个独占会话目录 | `/root/.dsh/state/superagent/work/`、`/root/.dsh/sessions/` |
| 分支保护 / ruleset | **无**(`/branches/master/protection` → 404,`/rulesets` → `[]`) | GitHub API |
| Actions variables / secrets | **均为空** | GitHub API |
| 门禁 | 六轨 workflow,靠 `paths` 过滤触发 | `.github/workflows/*` |

结论:**「人合 PR」目前是承诺,不是墙**。`shiliu655` 有写权限,`gh` 也在它 PATH 里(能 `gh pr create`),
所以它**技术上**可以 `gh pr merge` —— v1 §3.7 的「不配 merge CLI」只是没给它配,不是拦住了它。

## 2. 并行模型的澄清(常被误解的一处)

superagent 的并行是**任务并行**,不是**智能体协作**:

- `maxWorkers=2` = 最多 2 张工单同时跑,每张跑在自己的 worktree / 分支 / 会话里;
- 工单之间**不通信、不共享上下文、不协商接口**;同文件冲突由 git 暴露,后合的一方返工;
- worker 内部**不会再拉子 agent**(`delegationDepth: 0`)。

推论(对自动化的直接影响):

1. 想提吞吐 → **多拆互不重叠的工单 + 提 `maxWorkers`**,而不是让 agent 内部分工;
2. 「一单一条栈」既是审查需要,也是**并行不打架的前提**;
3. 并行度越高,自动合并的白名单必须越窄 —— 否则两单同时改同一处,自动合会把冲突推到 master 上。

## 3. 阶梯

每一级只做一件事:**把一个人工闸门换成确定性机制**,并给出可判定的验收口径与回退方式。

| 级别 | 换掉的闸门 | 机制 | 验收口径 | 回退 |
|---|---|---|---|---|
| **L0**(2026-11-07) | — | 人评审 + 人合 + 人发版 + 人同步本机 | v1 §6 | — |
| **L1** 零清单 | 合并后同步 + prune、发版清单 | `scripts/superagent-closeout.sh`(pull 母体 → 同步 Windows → prune)、`release` 一条命令 | 合并后**不需要人记命令**:一条 closeout 命令跑完,`worktree list` 只剩母体 | 手动执行同样命令 |
| **L2** 白名单自动合 | **人合 PR**(仅白名单路径) | `.github/workflows/auto-merge.yml` 定时扫描 + 确定性条件 → squash 合并(**不是 LLM**) | 白名单 PR 在 checks 全绿后 ≤15 分钟自动合并;非白名单 PR 从不被它碰 | repo variable `AUTOMERGE=off` 一键停 |
| **L3** app UI 进 CI | 模拟器手测 | `integration_test` + GitHub Actions 的 Android emulator runner + golden 截图 diff | 关键路径在 CI 上跑通;人工降为**异步视觉抽查** | 关掉 emulator 轨,恢复人工闸门 |
| **L4** 需求自动入队 | 人写 issue | backlog → issue 自动生成(`eval.mode` observe → 白名单 active) | 白名单类(P0/P1 typo、依赖 patch)自动成单且口径机器可判 | `eval.mode=observe` |

> **L4 那一行的「机制 / 回退」两栏已于 2026-11-13 修订**,详见 **§6.2**:执行者是
> 确定性脚本而不是 `eval.mode`,总闸是仓库 variable `L4_INTAKE`。表格保留原文以显示演进。

**本文 §4 实现 L2,§6 实现 L4**;L1/L3 各自单独成单(各自一条栈),实施证据统一记在 §9。

## 4. L2 详细设计(已实现)

### 4.1 谁能被自动合并(白名单)

**白名单 = 路径前缀,单一事实来源在 `.github/workflows/auto-merge.yml` 的 `WHITELIST_PREFIXES`。**

L2 第一版只有一项 `docs/**`。**2026-11-08 收窄**(第四轮安全审计 M-4):`docs/` 里存在
**下一次 agent 会当作指令读**的目录,而「写文档的 worker」与「读文档的下一次 agent」
不是同一信任级 —— worker 账号一旦被拿下,一个「纯文档」PR 就能**无人工审查**地把指令
注入 master,之后每个读到它的 agent 都会照做(本仓库的流程正是「读 pitfalls → 按它改代码」)。

因此白名单只留**没有指令语义**的目录:

| 白名单 | 理由 |
|---|---|
| `docs/api/` | 接口分册:内容受 `ApiDocsCoverageTests` / `test_schema_contract` 双向门禁,写错必红 |
| `docs/security/` | 审计报告:纯记录,不进任何执行路径 |
| `docs/reviews/` | 审查结论文档:同上 |
| `docs/milestones.md` | 时间线:纯记录 |

**显式黑名单(`DENY_PREFIXES`,双保险:即使有人往白名单加前缀,这几处也不会被自动合并)**:

| 黑名单 | 为什么不能自动合 |
|---|---|
| `docs/superpowers/`(specs / plans) | 实施计划与设计规范,worker 与主 agent 都按它干活 |
| `docs/pitfalls/` | 踩坑手册,写代码前必读 —— 天然的指令面 |
| `docs/ops/` | 运维手册(runbook / release / superagent) |
| `docs/learning/` | 学习路径,含「先读什么再做什么」的顺序指令 |
| `CLAUDE.md` / `AGENTS.md` / `CONTRIBUTING.md` / `README.md` | 仓库级约定,改一句就可能改变所有 agent 的行为 |

**永久排除(任何级别都不进白名单)**:

- `chatapp/**` 业务代码、迁移
- `app/**`(含 `pubspec.yaml`)、`web/src/**`
- `imserver/**`(尤其 WS 协议帧)
- `.github/**`(含本 workflow 自己 —— 否则一张 PR 就能删掉护栏,下一张就能自动合任何东西)
- `deploy/**`、`scripts/**`、任何密钥/版本号文件

### 4.2 合并条件(全部满足才合)

1. `vars.AUTOMERGE == 'on'`(仓库开关;`off` 时 workflow 直接退出 0,不算失败)
2. base = `master`,PR 非 draft、未合并、**非跨仓库 fork**
3. 作者是 `shiliu655`(只有 worker 的产出会被自动合,人自己开的 PR 永远走人工)
4. 改动文件 **1–20 个**,且**每一个**都命中白名单前缀
5. 无以下标签:`no-auto-merge`、`blocked`、`needs-human`(**人的否决票**)
6. `statusCheckRollup` 里**没有**未完成项,**没有**失败项(允许 `SUCCESS`/`NEUTRAL`/`SKIPPED`);
   无 check run(纯文档 PR 的正常形态)视为通过 —— 与 v1 硬规矩 #2 一致
7. `mergeable == MERGEABLE`(`UNKNOWN` 说明 GitHub 还没算完 → 本轮跳过,下轮再来)
8. **每日配额**:最近 24 小时带 `[auto]` 标记的合并提交 ≤ `MAX_PER_DAY`(默认 8)

### 4.3 执行者与审计

- 执行者:**GitHub Actions 里的确定性脚本**(`gh` + `jq`),**不是 LLM**。worker 始终没有合并能力。
- 每次合并前在 PR 上留一条评论,写明:命中的白名单、当时的 checks 结论、以及**一行 revert 命令**。
- 每轮扫描写 job summary(合并了谁 / 跳过了谁 / 为什么跳过)—— 这就是人每天扫一眼的「日报」。
- 合并提交标题带 `[auto]` 标记(既做审计,也做配额计数)。

### 4.4 已知偏差

| 偏差 | 影响 | 处置 |
|---|---|---|
| 用 `GITHUB_TOKEN` 合并时,**不会**触发 master 上的 `push` 轨 | 少了「合并后在 master 上再跑一遍」的第二道确认(PR 上的 checks 已覆盖同一棵树) | 若要保留,加 secret `AUTOMERGE_TOKEN`(fine-grained PAT),workflow 会自动优先用它 |
| 纯文档 PR 有 **0 个 check run** | 「没有红」≠「跑绿了」 | 靠人侧 `verify.sh contract`(v1 硬规矩 #2);这也是白名单只放「无指令语义」的 docs 子集的原因(§4.1) |
| `blockedCommands` 只按命令名拦 | worker 技术上仍可 `gh pr merge`(靠 `AGENTS.md` 自律) | 见 §8 未决问题 4:加 PATH 上的 `gh` 包装器拒 `merge`/`release` 子命令 |

### 4.5 紧急停与回滚

```bash
# 停:一键(下轮扫描即退出 0,不合并任何东西)
gh variable set AUTOMERGE --body off --repo shiliu153/chatapp
# 回滚某次自动合并(以 PR 评论里给出的 SHA 为准)
git revert --no-edit <merge-sha> && git push origin master   # 需人做
```

## 5. 对 v1 的修订(不修订就会自相矛盾)

| v1 原文 | 本文修订为 |
|---|---|
| §1 非目标:「**不追求无人值守上线**」 | 保留「**上线/发版/部署永远留给人**」;**合并**在「无指令语义」的 docs 子集(§4.1 白名单)内允许由确定性 workflow 完成(L2)。生产发布仍必须人闸 |
| §3.7「合并:**不配 merge CLI**,agent 永不自合;所有 PR 由人 squash」 | 「**LLM 永不自合**(worker 无 merge 能力);白名单内的自动合并由 `.github/workflows/auto-merge.yml` 执行,决策权在确定性规则而非模型;白名单外的 PR 仍由人 squash」 |

其余条款(一单一条栈、verify 唯一入口、`app/` 必须人验、CI 是唯一裁判)不变。

## 6. L4 详细设计(需求自动入队,2026-11-13 实现)

> L1/L2/L3 换掉的是「人**怎么**做」(记命令 / 点合并 / 手测);**L4 是唯一一级换掉「人决定
> 做什么」**。所以本节的成败标准不是「能自动开单」,而是:**只让机器开那种口径天然机器
> 可判的单,绝不让它生成需求设想**。判据写死成机器条件;判不出来就不开单。

### 6.1 先回答:哪些信号「不需要人做判断」

不用印象清单,用三重机械条件。三条**全满足**才进白名单:

| # | 条件 | 怎么算「满足」 |
|---|---|---|
| **A 事实可判** | 「发生了什么」由命令输出决定(退出码 / API 字段 / 文件内容),**不需要人读日志下结论** | 例如 `npm audit` 的退出码、run 的 `conclusion`、链接目标是否存在 |
| **B 完成可判** | 存在一个**在工单目录里能跑**的验收命令,退出码即结论 —— 落地成「该栈必须在 `scripts/verify.sh` 里有子命令」 | 凡「合并后才发生」的事(某条 CI 轨被触发、某个接口在线上返回正确)都不算 |
| **C 单一归属** | 能**唯一**确定一条栈,且这个判定不依赖产品取舍 | 横跨多栈,或修复动作本身属人(发版、升版本号)⇒ 不满足 |

按这三条筛出的**封闭枚举**(不是「凡是机器可读的都行」):

| 信号 | 事实来源 | 是(= 开单)的机器判据 | 否(= 不开单,为什么) |
|---|---|---|---|
| `ci-red` | 默认分支每条 workflow **最新一次 push run** | ① 该 run 是它所属 workflow 的最新一次;② `conclusion == "failure"`;③ workflow 名 ∈ `CI_RED_STACKS`(`Backend (Django)`→`chatapp/`、`Web (Vue)`→`web/`、`imserver`→`imserver/`、`App (Flutter)`→`app/`)—— 也就是 `verify.sh` 有子命令的那四条栈 | `跨栈契约`(失败横跨四栈,且最常见原因是版本号不一致 —— 升版本号按 `AGENTS.md` 属「绝对不要做」);`App UI (emulator smoke)`、`Web E2E (smoke)`(worker 在工单目录里**无法自证**,不满足 B);三条流程轨自身(含本 workflow,防自环);未登记的 workflow(判不出栈 ⇒ 按判不出来处理) |
| `dep-advisory` | Dependabot 告警 + **仓库锁文件** | ① `state == "open"` 且未 dismiss;② severity ≥ `high`;③ `first_patched_version` **存在**;④ 生态 ∈ {`npm`, `pip`} 且 manifest 落在 `web/` 或 `chatapp/`;⑤ **锁文件里实际装的版本落在 `vulnerable_version_range` 内** | 低/中危(「值不值得修」是判断);**没有修复版本**(绕开 / 接受风险 / 换库 —— 三个方向都是判断);`docker` / `github-actions` 生态(修的是 `deploy/`、`.github/`,worker 不可写或必须人审);⑤不成立 = 告警滞后,漏洞已修好 |
| `mech-docs-links` | `scripts/check_docs_links.py` | `docs/` 下存在相对链接,解析后的路径不存在 | 版本号三处不一致、`openapi.yml` / `schema.d.ts` 与源码不一致 —— **这些已被默认分支 push 轨覆盖**(`contract` / `backend` / `web`),由 `ci-red` 负责;再单列会为同一件事开两张单 |

三处对直觉的修正(都有实测或结构理由):

1. **依赖信号不能信告警的 `state`。** 2026-11-13 实测本仓库:`npm audit` 已经是 0,
   `vite 8.3.8` / `undici 7.30.2` / `follow-redirects 1.16.3` / `minimatch 11.0.8` 全部早已修好,
   而 Dependabot **仍开着 13 条 `open` 告警**(扫描滞后于锁文件)。只看 `state` 会在上线第一天
   为**已经修好的漏洞**开 6 张单 —— 正是「污染待办」那类误判,而且人还得逐条去证伪。
   所以判定改成「读锁文件里实际装的版本,再比对受影响区间」;告警退化为**选题提示**,
   不是事实。
2. **「机械一致性」不是一个独立信号源。** version 三处不一致、生成物与源码不一致,合并后都会让
   默认分支的 `contract` / `backend` / `web` 变红 —— 那已经由 `ci-red` 覆盖。真正**没有 owner**
   的只剩 push 轨根本不读的东西:Markdown 的相对链接。所以这一类只保留断链一项;
   实测它有真信号 —— 本仓库当时有 **6 处**断链(全是「相对深度写错一级」)。
3. **判据是「三重机械条件」,不是「三类信号」的印象清单。** 类名会让人以为「凡机器能读的都行」,
   条件不会。新增任何检测器都必须先逐条过 A/B/C(走法见 §6.8),否则一律留给人。

**明确排除(任何情况都不进白名单)**:凡是需要「产品判断」的信号 —— backlog 里未编号的想法、
「这个功能有没有用」、性能该不该优化、要不要改文案。这些永远留给人。

### 6.2 执行者与总闸:为什么**不是** `eval.mode`

§3 表格把 L4 的机制写成「`eval.mode` 由 `observe` 改为白名单 `active`」。**本节修正这一点**:

| | 原设 | 实际实现 | 为什么改 |
|---|---|---|---|
| 执行者 | `eval.mode=active`(DSH 的 **LLM proactive** 模式) | GitHub Actions 里的确定性脚本:`scripts/l4_intake.py` + `.github/workflows/l4-intake.yml` | `active` 打开的是「模型自己决定开什么单」,那恰好是 L4 唯一真实的风险(替人决定做什么),而且它既不是白名单、也不可枚举、也无法 fail-closed |
| 总闸 | `eval.mode` | 仓库 variable `L4_INTAKE`(与 L2 的 `AUTOMERGE` 同构) | 一处开关,一个文件里判,可一键停;`eval.mode` 是 worker 的 LLM 行为设置,语义不同 |
| 回退 | `eval.mode=observe` | `L4_INTAKE=off`(见 §6.7) | 同上 |

**`eval.mode` 保持 `observe`,并且不该被改成 `active`。** 若将来真要让模型参与需求发现,那是
**另一级**:必须先有「模型只提议、机器判据一票否决」的通道,那一级的开关仍是 `L4_INTAKE`。

顺带说明 L4 与「派单」的边界:**开单是开单,派单仍是人**。L4 只往待办里放规范化的工单;
`@` 派工由人在评论里做(见 §4.1 的入队规矩)。所以自动开单**不会**绕过「一单一条栈」的人工审查
—— 每一张自动单在被派出去之前,仍然会被人读一遍。

### 6.3 判定流程

每天 **09:20 北京时间**(01:20 UTC,刻意排在 `main-health` 的 09:00 之后:先让
「默认分支有红轨」的聚合 issue 落地,再按栈开可接的单):

```
总闸 L4_INTAKE == on ?
   └─ 采集事实(3 条只读 API,不做任何判断)
        ├─ GET /actions/runs?branch=<默认分支>&event=push&per_page=100
        ├─ GET /dependabot/alerts?state=open          ← 读不到 = 判不出来,不是「没有漏洞」
        └─ GET /issues?labels=l4-auto(含已关闭)
   └─ plan   纯离线判定 → 计划 JSON + 日报(job summary)
   └─ apply  计划 → gh 命令(issue create / comment / reopen)
   └─ artifact  保留这一轮的事实快照与计划(人复核「凭什么开单」)
```

事实与判定分开是刻意的:判定器是**纯函数**(输入是 JSON 快照),所以能 100% 离线自测。
`main-health.yml` 与 `l4-intake.yml` 读**同一个解析函数**(`l4_intake.py ci-red-summary`),
不各写一份 jq —— 否则改口径必然只改一边。

### 6.4 去重规则:同一失败绝不重复开单

每张单的正文第一行是**稳定指纹**:

```
<!-- l4-fingerprint: 3f2ac1d09b7e4415 -->
```

| 信号 | 指纹的身份串 | 刻意的取舍 |
|---|---|---|
| `ci-red` | `ci-red|<workflow 显示名>` | **不含 SHA、不含时间** —— 否则同一条红每天都是一个新指纹,去重立刻失效 |
| `dep-advisory` | `dep|<生态>|<包名>|<GHSA 编号>` | 同一公告永远同一张单;同一包的**不同公告**各一张(修法可能不同) |
| `mech-docs-links` | `mech|docs-links|<文件>` | 按**文件**聚合,不按链接 —— 10 处断链在一张单里修完,不是 10 张单 |

判定时先查已有 `l4-auto` issue 的正文指纹,再决定动作:

| 已有单的状态 | 动作 |
|---|---|
| 无 | `create`(受 §6.5 限额约束) |
| `open` | `comment` —— 只追加一条「`<时间>` 再次命中,判据未变」,**不新建** |
| `closed` | `reopen` + `comment` —— 同一失败复发就重开原单(保留历史与讨论),不新开 |

`ci-red` 的指纹**只含 workflow 名**是有意为之:同一 workflow 连红 5 天 = 一张单 + 5 条命中
记录;但「backend 修好了、换成 web 红了」是**两条不同的失败**,各开一张 —— 那确实需要两件事。

### 6.5 限额:每天最多 N 张

- 默认 **5 张/UTC 日**(`L4_MAX_PER_DAY` 可覆盖;`0` = 今天一张都不新建,是第二道刹车)。
- 只对 `create` 计数;`comment` / `reopen` 不占配额(它们不增加待办条目数)。
- 达到上限后剩余候选变 `defer`,原因写进日报(`今日配额已满(5/5),明天再判`)。
- 超限本身是一个信号:**一天里同时冒出 5 个以上白名单信号,通常说明某个检测器的口径变宽了**
  —— 日报里能直接看出来,红线处置见 §7。

### 6.6 审计:每张开单留下什么痕迹

| 痕迹 | 位置 | 内容 |
|---|---|---|
| 稳定指纹 | issue 正文第 1 行 | `<!-- l4-fingerprint: … -->`,去重与追溯都用它 |
| 来源注释 | 正文第 2 行 | `detector` / 判定对象 / 判定时间 |
| 标签 | issue | `l4-auto`(机器创建)+ `l4-sig:<signal>`(哪条判据) |
| 事实表 | 正文「事实(机器生成,勿手改)」 | 全部来自命令输出(run 链接 / 锁定版本 / 受影响区间 / 首个修复版本 / 断链行号) |
| 验收命令 | 正文「验收」 | 可复制执行的那一条(退出码即结论) |
| 日报 | Actions job summary | 这一轮「判了哪些信号 / 开了谁 / 跳过谁 / 为什么跳过 / 哪项判不出来」 |
| 快照 | workflow artifact `l4-plan`(留 14 天) | 事实 JSON + 计划 JSON,人可复核「凭什么开单」 |
| 创建者 | issue | `github-actions[bot]`,不是 worker 账号 |

**正文里不许出现任何 `@提及`**(`_scrub_mentions` 会抹掉 `@`):superagent 把 issue 的
opening body 当作派工触发源,正文里 @ 了 worker 等于**自动派单**,那就绕过了人工审查。
这条有自测钉着。

### 6.7 回退、紧急停与撤单

| 事 | 怎么做 | 影响 |
|---|---|---|
| **关掉 L4**(回退到「人写 issue」) | `gh variable set L4_INTAKE --body off --repo shiliu153/chatapp` | 下一轮直接退出 0,不开单 / 不评论 / 不重开;**已开的单原样留着**(它们是真事实,不是脏数据) |
| **再紧一档**(只保留判定,不落单) | `gh workflow run l4-intake.yml -f dry_run=true --repo shiliu153/chatapp` | 打印将要做的事,一个 gh 写命令都不发 |
| **紧急闸**(今天一张都不许新建) | `gh variable set L4_MAX_PER_DAY --body 0 --repo shiliu153/chatapp` | 去重类的 `comment` / `reopen` 仍然发生(它们不增加条目),但**绝不新建** |
| **撤一张误开的单** | `gh issue list --label l4-auto` → `gh issue close <n> --reason not_planned --comment "L4 误开单:<原因>;机制已修(#<PR>)"` | 关闭的原单会被指纹记住:同一失败若再命中会 **reopen** 那条,因此**改指纹口径前先确认不会原地复发** |
| **修判定器** | 改 `scripts/l4_intake.py` → 它的自测在 `contract` 轨 | 判定器坏了 → 整轮 run **标红**(fail-closed),不会静默 |

需要改的**文件**(回退口径的唯一事实来源都在仓库里,不在面板里):

| 想改 | 改哪里 |
|---|---|
| 总闸 / 默认值 | 仓库 variable `L4_INTAKE`、`L4_MAX_PER_DAY`、`L4_MIN_SEVERITY` |
| 白名单栈 / 留给人 | `scripts/l4_intake.py` 的 `CI_RED_STACKS`、`CI_RED_HUMAN_ONLY` |
| 依赖阈值与生态 | 同文件的 `SEVERITY_ORDER`、`DEP_ECOSYSTEMS` |
| 判定逻辑本身 | 同文件 + `scripts/test_l4_intake.py`(自测先红再改) |
| 跑的时间和频率 | `.github/workflows/l4-intake.yml` 的 `cron` |

### 6.8 自测与「加新检测器」的门槛

自测进 `contract` 轨(`scripts.test_l4_intake`,53 条;`scripts.test_check_docs_links`,15 条),
**全部离线**(输入是 JSON 快照与临时目录)。硬覆盖的四条口径:

| 口径 | 为什么必须钉住 |
|---|---|
| 该开单的信号 → 开单 | 判定器「什么都不开」时看起来最安静,也最难发现 |
| 不该开单的信号 → 不开 | 含判断类信号(低危 / 无修复版本 / 越白名单生态)与**告警滞后**(锁文件已修好) |
| **判定失败 → 不开**(fail-closed) | 见下 |
| 重复失败 → 去重不重开 | open 追加评论、closed 重开,都不新建 |

**fail-closed 的方向与 `ci-scope.sh` 相反,这是刻意的**:

| 判定器 | 判不出来时 | 为什么 |
|---|---|---|
| `ci-scope.sh` | 按「**要跑**」 | 漏跑门禁比多跑一次糟得多(红 CI 会被合并) |
| `l4_intake.py` | 按「**不开单**」+ 整轮 run 标红 | L4 漏开单只是少一件事(人还能自己写);**误开单会污染待办**,而待办是下一轮所有工作的输入 |

「整轮标红」是 fail-closed 的另一半:不开单是安全动作,但**判定器坏掉必须有人知道**,
否则它就成了「永远平静」的假绿。`l4-intake.yml` 自己在 `CI_RED_HUMAN_ONLY` 里(不开自己的单),
所以这条红只会在 Actions 里亮,不会自我繁殖。

**加一个新检测器的步骤**(顺序不能反):① 逐条过 §6.1 的 A/B/C,把「否」的理由写进
`CI_RED_HUMAN_ONLY` 那类表;② 先在 `test_l4_intake.py` 写下「该开 / 不该开 / 判不出来」三类用例;
③ 实现判定(纯函数,输入 JSON 或文件);④ 指纹必须**只含稳定身份**,不含时间与 SHA;
⑤ 在 `l4-intake.yml` 里补一条只读事实采集;⑥ 更新本节表格与 `docs/ops/superagent.md` §14。

## 7. 度量与红线

| 指标 | 目标 | 怎么算 |
|---|---|---|
| 自动合并占比 | 首月 10–30%(应当只有 docs) | 带 `[auto]` 的合并提交 / 总合并提交 |
| revert 率 | < 5% | 24h 内被 revert 的 `[auto]` 合并数 |
| 误合(本该拦却合了) | **0** | 人工抽查 10% + 每周复盘一次 job summary |
| 人出手次数 | 从 3 降到 **1**(只做需求分析) | 每单记录 |
| **L4 误开单率** | **0** | 每周复盘 `l4-auto` 标签的单:被关成 `not_planned` 的比例(> 0 就收紧 §6.1 的判据) |
| **L4 判不出来次数** | 0(出现即修) | `l4-intake` 跑红的次数 |

**红线(出现任一条,立刻 `AUTOMERGE=off` 并回退该级)**:

1. 任何 `chatapp/**`、`app/**`、`imserver/**`、`.github/**` 的改动被自动合并 —— 说明白名单判定有 bug;
2. 一次自动合并导致 master 红超过 30 分钟;
3. 24 小时内自动合并数触及配额上限(说明口径或白名单太宽);
4. 出现「检查未跑完就合并」的实例。

**L4 专属红线(`L4_INTAKE=off`)**:

5. 出现一张**含需求设想 / 判断词**的单(「建议」「可以考虑」「要不要」)—— 说明白名单被放宽了;
6. 出现一张**已修好的问题**的单(例如锁文件版本已不在受影响区间)—— 说明判据退回了「读告警 state」;
7. 出现同一失败**重复开单**(同指纹多张 open)—— 说明指纹里混进了时间或 SHA;
8. 一张自动单被**自动派发**(正文/标题里出现 `@`)—— 说明 `_scrub_mentions` 失效。

## 8. 未决问题

1. **要不要开分支保护 / ruleset?** 现在 master 无保护,连直推都行。开保护会把「人合」从承诺变成墙,
   但纯文档 PR 有 0 个 check run,无法用「required checks」表达。可选方案:
   - 只开「必须走 PR + 禁 force push」,不设 required checks(推荐,兼容 docs PR);
   - 或给 docs 轨也造一个零成本的 check(`contract` 跑一次),再设 required checks。
   未决期间:靠 §4.2 的 workflow 自身条件 + 人工复核 job summary。
2. **`AUTOMERGE_TOKEN`(PAT)值不值得加?** 加了才有 master `push` 轨的二次确认,代价是多一个 secret。
3. **reviewer worker 要不要做?** 现阶段用「确定性断言 + 人抽查」替代;等 L2 跑满 10 单、拿到误合率再定。
4. **`gh` 包装器**:在 worker 的 PATH 前置一个拒 `merge`/`release` 子命令的 shim,把 §4.4 那条偏差补成硬拦。属 `scripts/` 栈,单独成单。
5. **L4 要不要把 `imserver` / `app` 两条栈也放开?** 首版已放进 `CI_RED_STACKS`(因为 `verify.sh`
   有对应子命令),但它们的失败更常是环境问题(容器 / Flutter 缓存)。跑满 5 单后按误开单率决定
   是否收回到「只 backend/web」。
6. **L4 要不要覆盖「P0/P1 typo」这类信号?** 目前**没有**任何机器可判的 typo 检测器(拼写检查
   会为专有名词与中文混排误报),按 §6.1 的 A 条它不达标,所以不进白名单。要做就得先有一个
   「零误报」的检测器,那是另一单。

## 9. 实施记录

| 级别 | 状态 | 证据 |
|---|---|---|
| **L2** | ✅ 2026-11-08 已 armed 并实测 | `AUTOMERGE=on`;首个真实样本 PR #113 由 `github-actions[bot]` 自动合并为 `5cd0c7a`,PR 上留有审计评论与回滚命令,分支自动删除;同内容但由人开的 PR #112 被正确拦下(作者条件) |
| **L1** | ✅ 2026-11-08 | `scripts/superagent-closeout.sh`(fetch→母体 ff→prune→报 Windows 状态,脏/非快进拒绝)+ `scripts/test_superagent_closeout.sh` 11 条自测全通过;实测输出 `CLOSEOUT ok mother=5cd0c7a windows=5cd0c7a same=yes pulled=0 prune=ok(0)`;代理不可用时退回本地 ref 判定并警告,不误报失败 |
| **L3** | ✅ 2026-11-08 | `app/integration_test/smoke_test.dart` + `.github/workflows/app-ui.yml`(android-emulator-runner api 34),PR #117 合并为 `cb85145`;`app-ui` 轨绿 8m38,日志含 `Boot completed in 24731 ms` / `All tests passed!`;主人在 Windows `Pixel_7` 手测通过后才合并(draft → 人验 → squash)。CI 迭代 3 轮全是环境坑(见 plans §9) |
| **L4** | ✅ 2026-11-13 实现并实测判定器 | `scripts/l4_intake.py`(三条机器判据 + 指纹去重 + 5 张/日 + fail-closed)+ `scripts/check_docs_links.py` + `.github/workflows/l4-intake.yml`;自测 **53 + 15 条全离线**,进 `contract` 轨;`main-health.yml` 改为复用同一解析器(不再各写一份 jq)。实测证据:① 依赖判据在真实告警快照上把 13 条 `open` 全部判为「已修好」→ **0 张单**(只信 `state` 会开 6 张);② 断链检测在真实仓库上抓出 **6 处**(5 处给出唯一候选改法);③ 总闸默认 `off`,首次启用须人执行 `gh variable set L4_INTAKE --body on` |


### 补充落地(2026-11-08,未单列成级)

| 项 | 状态 | 证据 |
|---|---|---|
| **master ruleset**(spec §8 未决问题 1 的一半) | ✅ 已开:`master: 必须走 PR + 禁强推`(deletion / non_fast_forward / pull_request,0 approval) | 实测:worker 账号直推 master → `push declined due to repository rule violations`「Changes must be made through a pull request」;推特性分支正常。`shiliu153` 在 bypass 名单 |
| **`gh` 包装器**(spec §8 未决问题 4) | ✅ `scripts/gh-guard/gh` 装到 `/usr/local/bin/gh` | 自测 16 条全过(拒 `pr merge` / `release create|upload` / 改 master 引用 / graphql mergePullRequest / REST 合并与 Release;**放行** `pr create|view|checks`、`issue create|comment|reopen`(2026-11-13 L4 补)、`api` 只读、`auth git-credential`);真实环境 `gh pr merge` 退出 2 并记账 |
| **串行化防护(§4.4 第一条偏差)** | ⬜ 未决 | `GITHUB_TOKEN` 合并不触发 master `push` 轨;要二次确认需加 secret `AUTOMERGE_TOKEN` |
