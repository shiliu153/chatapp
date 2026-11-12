# CI 流程门禁整改(P0/P1/P2)

> **本文与交付同批落档**:立项、审计、实现、合并都在 2026-11-12 同一天完成,所以不经过
> `specs/` 中转,按 [`docs/superpowers/README.md`](../../README.md) §3「交付即归档」直接写进 `archive/`。
> 操作手册(怎么用、怎么停、怎么回滚)在 [`docs/ops/superagent.md`](../../../ops/superagent.md) §8/§8.1
> 与 [`docs/ops/release.md`](../../../ops/release.md) §3;本文只回答**为什么改、改了什么、还剩什么**。

## 0. 一句话

把「CI 绿才合并、只部署合并后的 SHA」这两条**靠人记住的纪律**,换成 **GitHub 自己会拒绝的机制**。
审计出 10 处「门禁看着有、其实没生效」,9 处已闭合;剩下 1 处(`AUTOMERGE_TOKEN`)需要人建 token。

## 1. 触发:三起「全绿但其实没验」的事故

| 事故 | 现象 | 根因 |
|---|---|---|
| 2026-11-11 默认分支红 20 小时 | 1.0.13 的版本号 PR 在 PR 轨上绿,合并后默认分支的 web 轨红;**当天下午照常完成了发版** | 默认分支的红色没有 owner —— CI 只被当成 PR 门禁,合并后既无告警也无 issue |
| `master` → `main` 改名 | ruleset 的 `include` 仍写 `refs/heads/master`,**`main` 实际裸奔约 20 小时**(`GET /rules/branches/main` 返回空) | 改名只改了分支,没改仓库设置;另有 4 处脚本/徽章写死 `master`,其中两处**静默失效**(不报错、日志全绿、功能不做) |
| 纯文档 PR 的「绿」 | 纯 `docs/**` 的 PR 没有 check run,而 auto-merge 把「0 个 check」当通过 | 用「没有红」代替「跑绿了」;且 `paths` 过滤与 required check 天然冲突 |

## 2. P0 审计发现(逐条:问题 → 后果 → 证据)

| # | 问题 | 后果 |
|---|---|---|
| 1 | auto-merge 把 **0 个 check run** 视为通过 | workflow 没触发 / paths 不匹配 / GitHub 抖动时,PR 在**零验证**下被合进默认分支 |
| 2 | ruleset **没有任何 required status check**(`required_approving_review_count` 也是 0) | GitHub 层面允许合并红 CI 的 PR;「CI 全绿才合并」纯靠人 |
| 3 | `web.yml` 跑 `test:run` 而不是 `test:coverage` | 文档宣称的覆盖率门槛 70/60/70/70 **在 CI 里从未执行过** |
| 4 | `backend.yml` / `web-e2e.yml` / `verify.sh bootstrap` 装 `requirements.txt` 区间 | 生产镜像装的是 `requirements.lock`;「CI 绿」推不出「生产可用」 |
| 5 | 部署没有机械闸门 | 「只部署合并后 SHA」无法判定,1.0.13 在红着的情况下上线 |
| 6 | 发版三处松口:tag 指向准备时 HEAD、`sync_version.py` 接受「待建」、`create_release.py` 允许 tag 不存在(GitHub 自动建轻量 tag) | 1.0.4 的 Release 挂了整整一周;附注 tag 纪律可被绕过 |
| 7 | `accounts.E001`(固定验证码 + 空白名单)**从未被任何流水线执行** | CI 全程 `DEBUG=1`(检查直接返回)、`migrate` 不跑 system checks、部署脚本没有 `manage.py check` —— 门禁不可达 = 等于不存在 |
| 8 | `gh-guard` 只按命令名拦,`gh api -X PUT .../pulls/N/merge`、`gh api -X POST .../releases` 直接放行 | worker 唯一机械拦截有绕过口 |
| 9 | `deploy/**`(备份 / 一键部署 / 看门狗 / 恢复演练)不在任何 CI 轨 | 34 个 `.sh` 里最危险的一批没有任何语法/逻辑检查 |
| 10 | 没有依赖更新通道,也没有 `AUTOMERGE_TOKEN` | 依赖靠人肉盯;自动合并用 `GITHUB_TOKEN` 不触发默认分支 `push` 轨(二次确认缺失) |

## 3. 整改(三批)

### P0 止血

- **默认分支健康**:新增 `.github/workflows/main-health.yml`(每天 09:00 北京时间)—— 检查默认分支上每条 workflow
  **最新一次 push run**,有红就建/更新 issue,全绿自动关。用 issue 而不是外部告警,不引入新凭据。
- **0-check 放行改判**:`auto-merge.yml` 要求**至少 1 个 check 结论是 SUCCESS**。
- **覆盖率门槛真跑**:`web.yml` 改 `test:coverage`。
- **装锁定依赖**:三条轨 + `verify.sh bootstrap` 统一装 `requirements.lock`。

### P1 流程闸门

- **required checks + 重活按改动面跑**:三条轨**去掉 `paths` 过滤**(required check 必须每次 PR 都出现),
  backend / web 先跑秒级 `scope` job([`scripts/ci-scope.sh`](../../../../scripts/ci-scope.sh))判本次改动是否触及该栈;
  无关时 `test` / `check` job 被跳过(check 结论 `skipped`,required 语义里视为满足);**判定失败一律按「要跑」处理**(fail-closed)。
  [`scripts/apply_ruleset.py`](../../../../scripts/apply_ruleset.py) 幂等设置 `contract` / `backend` / `web` 为必需检查。
- **部署闸门**:[`scripts/deploy_gate.py`](../../../../scripts/deploy_gate.py) —— 目标 SHA ∈ `origin/main` 且该 SHA 的 check 全绿
  (0 个 check 视为不通过;`skipped` / `neutral` 视为通过)。这是「只部署合并后 SHA」唯一的机械判定入口。
- **发版门禁**:`release_prep.py` 的 tag 命令改成占位符;`sync_version.py` 拒绝「待建」;`create_release.py` 在 tag 不存在时直接拒绝。
- **`accounts.E001` 可达**:补 5 个单测 + `backend.yml` 加 `DEBUG=0` 自检 step。
- **gh-guard 补漏**:拦 REST 合并 / Release 端点,21 条自测进 `contract` 轨。

### P2 供应链与运维覆盖

- **dependabot**:只开低噪音两生态(github-actions weekly / docker monthly);pip / npm / pub 交给 security updates。
- **`deploy/**` 进 CI**:先 `bash -n`(语法),再升到 `shellcheck -S error`(逻辑类 error)。
- **白名单收窄**:移出 `docs/security/`、`docs/reviews/` —— 审计报告里「验收:…」「建议修复批次 A→B→C→D」对下一个 agent 是**强指令**语义。
- **Actions pin 到 40 位 SHA**(21 处):tag 可移动,SHA 不可。
- **`AUTOMERGE_TOKEN` 写入工具**:[`scripts/set_automerge_token.py`](../../../../scripts/set_automerge_token.py)(libsodium sealed box);
  **PAT 必须人建**(fine-grained、只对本仓库、Contents + Pull requests 读写),脚本只负责加密写入。
- **`pip check`** 进 backend 轨;**`CONTRIBUTING.md`** 按六/九轨现状重写(原文还写着已删除的腾讯云 IM 配置)。

## 4. 交付清单(2026-11-12,同日 8 个 PR + 1 个探针)

| # | PR | 主题 | 关键落点 |
|---|---|---|---|
| 1 | #251 | superagent 流程文档收尾 | plan 归档 / README 状态修正 / §13.1 命令改 `pwsh -File` |
| 2 | #252 | macOS 生成物平台内收口 | `app/macos/.gitignore` |
| 3 | #253 | 去掉 `key.properties` 硬依赖 | 缺文件回落 debug 签名,`app-ui` 轨不再现造 keystore |
| 4 | #254 | 默认分支改名连带修复 | 自动合并 / closeout / prune / 发版闸门 / README 徽章 |
| 5 | #255 | worker 提交身份规则 | `noreply` 前缀,2026-11-10 归因事故 |
| 6 | **#256** | **P0 门禁止血 + P1 流程闸门** | main-health / 0-check 改判 / 覆盖率 / lock / required checks / deploy_gate / 发版门禁 / E001 / gh-guard |
| 7 | **#258** | **P2 供应链与运维覆盖** | dependabot / `bash -n` / 白名单收窄 / set_automerge_token / CONTRIBUTING |
| 8 | **#271** | **P2 收尾** | Actions pin 21 处 / `shellcheck -S error` / `pip check` / 1.0.4 Release 归档口径 |
| — | #257 | 探针 PR(关闭不合并) | 验证纯文档 PR 的 `backend` / `web` 被 skipped 后仍可合并 |

## 5. 验证(实测,不是断言)

| 机制 | 证据 |
|---|---|
| required checks 已生效 | ruleset API 实测 `required_status_checks = [contract, backend, web]`,`include = refs/heads/main + refs/heads/master`,0 approval |
| 默认分支健康检查能跑 | `main-health.yml` 手动触发 run `43202087415`(10:38 UTC)`workflow_dispatch` → **success**;当时无红轨,故未建 issue |
| required check 接受 `skipped` | 探针 PR **#257**:`backend=skipped`、`web=skipped`、`contract=success`,`mergeable_state=clean` —— 纯文档 PR 不再被卡 |
| scope 判定不会漏真改动 | PR #271 改了 `backend.yml` / `web.yml` → `backend` / `web` 全量执行(而非跳过) |
| Actions pin 后 dependabot 仍工作 | 12 个 dependabot PR 已开(5 actions + 4 docker + 3 npm),PR 轨全绿 |
| 纯文档 PR 现在有 check | 本批之后 `contract` / `backend` / `web` 任何 PR 都会出现 —— 「没有 check」不再是正常形态 |

## 6. 未收尾台账(已同步到 [backlog §7](../../../backlog/2026-11-03-todo.md))

| 项 | 缺什么 | 谁能做 |
|---|---|---|
| `AUTOMERGE_TOKEN` | 需人在 GitHub 网页建 fine-grained PAT 并跑 `set_automerge_token.py`;现在自动合并仍用 `GITHUB_TOKEN`,**不触发默认分支 push 轨** | 人(网页建 token) |
| npm security updates 持续失败 | `minimatch` 的修复路径会**降级** `@eslint/js`(10.0.1 → 9.39.5),dependabot 判 `downgrades_dependencies` 后报错 → 默认分支上常驻一条红色 `Dependabot` check(不阻塞合并,规则只要求 contract/backend/web) | worker(`web/` 栈:加 `overrides` 或升 `@eslint/js`) |
| 12 个 dependabot PR 待裁决 | 4 个 docker 大版本与项目约束冲突(python 3.15 / node 25 / ubuntu 25.10 / nginx 1.31);5 个 Actions 大版本 + 3 个 npm patch 需人点合并 | 人(合并动作) |
| L4「需求自动入队」 | 阶梯 spec 的 L4 未做,且**还没有对应 issue** | 人先立项 |
| `requirements.lock` 无 `--hash` | 供应链完整性缺口(跨平台精确生成较麻烦) | worker(单开一单) |
| `deploy/**` shellcheck 只到 error 级 | warning / info 未开(现有脚本风格项太多) | worker(逐步开) |
| `ensure-running.ps1` 仍是 UTF-8 无 BOM | Windows PowerShell 5.1 按 ANSI 解码 → 中文段落 `ParserError`;`.EXAMPLE` 还在示范 `powershell` | worker(`scripts/` 栈) |
| `profile_voice_card_test.dart` 偶发不稳定 | 用例真实等 1100ms,被测逻辑最短 1000ms,余量只有 100ms | worker(`app/` 栈) |
| `key.properties` 存在但缺键仍崩 | 回落只覆盖「文件不存在」 | 按需另开单 |

## 7. 取舍与偏差(为什么不选另一条路)

1. **去掉 `paths` 但保留 `scope` job**:required check 必须「每次 PR 都出现」,而全量后端(MySQL + 1100 用例)不该每个 PR 都跑。
   用「job 总是出现、重活按改动面跑」同时满足两者;**代价**是多一个秒级 job,且判定器本身成了新风险 ——
   所以它有自己的 17 条离线自测进 `contract` 轨,且判定失败一律 fail-closed。
2. **0-check 从「通过」改「拒绝」**:纯文档 PR 从此也有 check(三条必跑轨),代价是每次 PR 多 1–2 分钟,
   换来「没有红 ≠ 跑绿了」这条歧义消失。
3. **白名单收窄而不是关掉 L2**:自动合并保留,但只留 `docs/api/` 与 `docs/milestones.md` —— 这两类改动
   机械可判(接口文档有 `ApiDocsCoverageTests`,里程碑只有一行);`docs/superpowers/`、`docs/ops/`、`docs/pitfalls/`
   仍走人。
4. **1.0.4 的 Release 不补建**:APK 产物已不可得,建一个无附件的 Release 反而破坏「版本号 / tag / Release / APK 四者对齐」的纪律;
   规则从 1.0.5 起真正执行,`sync_version.py` 从此拒绝「待建」。
5. **`AUTOMERGE_TOKEN` 只做工具不做决定**:是否多一个 secret 由人拍板;当前补偿是 PR 轨已全量跑过 + `main-health.yml` 每天兜底。

## 8. 相关文档

- 流程与自动化阶梯:[superagent 开发流程 spec](../../specs/2026-11-07-superagent-dev-workflow-design.md)、
  [自动化阶梯 spec](../../specs/2026-11-08-superagent-automation-ladder-design.md)(L4 仍未做)
- 运维手册:[`docs/ops/superagent.md`](../../../ops/superagent.md) §8(自动合并)/ §8.1(required checks)/ §9(gh-guard)
- 发版:[`docs/ops/release.md`](../../../ops/release.md) §3(步骤 4 前跑部署闸门)/ §5(发版记录)/ §6(1.0.4 历史说明)
- 待办:[`docs/backlog/2026-11-03-todo.md`](../../../backlog/2026-11-03-todo.md) §7
