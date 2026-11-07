# Superagent 自动化阶梯设计(L0–L4)

> 前置:[2026-11-07 Superagent 本地开发流程设计 v1](2026-11-07-superagent-dev-workflow-design.md)(下称 **v1**)。
> 本文不改 v1 的「一单一条栈 / CI 是唯一裁判 / verify.sh 唯一入口」,只回答一个问题:
> **人出现在流程里的那几处,哪些能换成确定性机制,哪些永远不能。**
> 状态:2026-11-08 起生效;L2 已实现(见 §4)。

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

**本文只实现 L2**;L1/L3/L4 各自单独成单(各自一条栈,见 §6)。

## 4. L2 详细设计(已实现)

### 4.1 谁能被自动合并(白名单)

**白名单 = 路径前缀,单一事实来源在 `.github/workflows/auto-merge.yml` 的 `WHITELIST_PREFIXES`。**

L2 第一版只有一项:

| 白名单 | 理由 |
|---|---|
| `docs/**` | 纯文档:六轨都不触发,`verify.sh contract` 就是它的门;不进构建产物,最坏情况是写错一句话,revert 成本最低 |

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
| 纯文档 PR 有 **0 个 check run** | 「没有红」≠「跑绿了」 | 靠人侧 `verify.sh contract`(v1 硬规矩 #2);这也是白名单只放 `docs/**` 的原因 |
| `blockedCommands` 只按命令名拦 | worker 技术上仍可 `gh pr merge`(靠 `AGENTS.md` 自律) | 见 §5 待办:加 PATH 上的 `gh` 包装器拒 `merge`/`release` 子命令 |

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
| §1 非目标:「**不追求无人值守上线**」 | 保留「**上线/发版/部署永远留给人**」;**合并**在 `docs/**` 白名单内允许由确定性 workflow 完成(L2)。生产发布仍必须人闸 |
| §3.7「合并:**不配 merge CLI**,agent 永不自合;所有 PR 由人 squash」 | 「**LLM 永不自合**(worker 无 merge 能力);白名单内的自动合并由 `.github/workflows/auto-merge.yml` 执行,决策权在确定性规则而非模型;白名单外的 PR 仍由人 squash」 |

其余条款(一单一条栈、verify 唯一入口、`app/` 必须人验、CI 是唯一裁判)不变。

## 6. 度量与红线

| 指标 | 目标 | 怎么算 |
|---|---|---|
| 自动合并占比 | 首月 10–30%(应当只有 docs) | 带 `[auto]` 的合并提交 / 总合并提交 |
| revert 率 | < 5% | 24h 内被 revert 的 `[auto]` 合并数 |
| 误合(本该拦却合了) | **0** | 人工抽查 10% + 每周复盘一次 job summary |
| 人出手次数 | 从 3 降到 **1**(只做需求分析) | 每单记录 |

**红线(出现任一条,立刻 `AUTOMERGE=off` 并回退该级)**:

1. 任何 `chatapp/**`、`app/**`、`imserver/**`、`.github/**` 的改动被自动合并 —— 说明白名单判定有 bug;
2. 一次自动合并导致 master 红超过 30 分钟;
3. 24 小时内自动合并数触及配额上限(说明口径或白名单太宽);
4. 出现「检查未跑完就合并」的实例。

## 7. 未决问题

1. **要不要开分支保护 / ruleset?** 现在 master 无保护,连直推都行。开保护会把「人合」从承诺变成墙,
   但纯文档 PR 有 0 个 check run,无法用「required checks」表达。可选方案:
   - 只开「必须走 PR + 禁 force push」,不设 required checks(推荐,兼容 docs PR);
   - 或给 docs 轨也造一个零成本的 check(`contract` 跑一次),再设 required checks。
   未决期间:靠 §4.2 的 workflow 自身条件 + 人工复核 job summary。
2. **`AUTOMERGE_TOKEN`(PAT)值不值得加?** 加了才有 master `push` 轨的二次确认,代价是多一个 secret。
3. **reviewer worker 要不要做?** 现阶段用「确定性断言 + 人抽查」替代;等 L2 跑满 10 单、拿到误合率再定。
4. **`gh` 包装器**:在 worker 的 PATH 前置一个拒 `merge`/`release` 子命令的 shim,把 §4.4 那条偏差补成硬拦。属 `scripts/` 栈,单独成单。
