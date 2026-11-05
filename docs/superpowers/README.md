# docs/superpowers/ — 设计 spec 与实施计划

两类文档:**设计 spec**(`specs/`,回答「做什么、为什么」)与**实施计划**(`plans/`,回答「怎么做、什么顺序、怎么验」)。
计划内的进度**只认 checkbox**;计划交付时在文件末尾追加「执行记录 / 与计划的偏差」。

> **核心约定:一个主题交付并上线后,立即 `git mv` 到 `archive/`,并在 §4 归档表补一行。**
> `specs/` 与 `plans/` 只保留「进行中 / 未启动 / 常驻」的文档 —— **目录本身就是当前工作面**。

---

## 1. 目录结构

| 路径 | 内容 |
|---|---|
| `specs/` | 进行中 / 未启动 / 常驻的设计文档 |
| `plans/` | 进行中 / 未启动的实施计划 |
| `archive/specs/`、`archive/plans/` | 已交付并归档的历史文档(85 份,清单见 §4) |

## 2. 当前工作面(只有 1 份)

| 文档 | 状态 | 说明 |
|---|---|---|
| [specs/2026-09-15-ui-design-language-design.md](specs/2026-09-15-ui-design-language-design.md) | **常驻,强制** | 「心跳」UI 设计规则 v1.5。所有 App 端 UI 改动动手前必读;**永远不归档** |

`plans/` 目录已空:最后一份在办的 [observability-and-capacity](archive/plans/2026-11-02-observability-and-capacity.md)
于 2026-11-05 四轨全部落地后归档;`specs/` 中的
[dual-server-load-balancing](archive/specs/2026-10-28-dual-server-load-balancing-design.md) 已在
2026-11-04 拍板「不做双机、暂不升配」,转为历史设计。**新增工作面文档时再建同名目录即可。**

**当前全部待办**(跨文档汇总、按批次排好序、每条可直接开新对话执行)见
[`docs/backlog/2026-11-03-todo.md`](../backlog/2026-11-03-todo.md)。

## 3. 命名与写作规范

- 文件名 `YYYY-MM-DD-<主题>.md`;spec 以 `-design` 结尾,plan 同名去掉 `-design`
- plan 顶部必须写:**Spec 链接**、**Goal**、**Architecture**、**Global Constraints**、**验收命令**
- 一个 Task = 一次可独立验证的改动;每个 Task 结束跑该 Task 的验证命令并提交,再进下一个
- 交付后在文件末尾写「执行记录 / 与计划的偏差 / 踩到的坑」,**不要**回头补勾旧 checkbox(见 §4 注)
- 交付即归档:同一提交内 `git mv` 到 `archive/` + 更新本文 §4 + 更新 `CLAUDE.md` 里程碑摘要

## 4. 归档清单(已交付,共 85 份)

> **注**:2026-10 之前的计划普遍存在「已交付但 checkbox 未回填」的情况(M0–M2、UI 批次②③、广场楼中楼、自建 IM、账号注销、访客等)。
> 判断是否交付**以本表结论与 git log 为准**,不要以文件内 checkbox 为准。

### 2026-09:M0–M3、UI 整改批次①–③、接口文档体系

| 日期 | 主题 | spec | 交付结论 |
|---|---|---|---|
| 09-09 | [m0-foundation](archive/plans/2026-09-09-m0-foundation.md) | [✓](archive/specs/2026-09-09-dating-app-mvp-design.md) | M0 地基(仓库/环境/CI 骨架);spec 为整体 MVP 设计 |
| 09-10 | [m1a-auth-profile](archive/plans/2026-09-10-m1a-auth-profile.md) | — | M1 后端:鉴权 + 资料 |
| 09-10 | [m1b-im-discovery](archive/plans/2026-09-10-m1b-im-discovery.md) | — | M1 后端:IM + 发现 |
| 09-10 | [m2a-auth-onboarding](archive/plans/2026-09-10-m2a-auth-onboarding.md) | — | M2 前端:登录 + 引导(真机手测当年跳过,仅单测覆盖) |
| 09-10 | [m2b-discovery-matching](archive/plans/2026-09-10-m2b-discovery-matching.md) | — | M2 前端:发现 + 配对 |
| 09-10 | [m2c-im-chat](archive/plans/2026-09-10-m2c-im-chat.md) | — | M2 前端:IM 聊天 |
| 09-11 | [m3-compliance](archive/plans/2026-09-11-m3-compliance.md) | [✓](archive/specs/2026-09-11-m3-compliance-design.md) | M3 合规:审核台 / 举报拉黑 / 重封禁 403 / 协议弹窗 / 签名 APK |
| 09-11 | [moderation-console-design](archive/specs/2026-09-11-moderation-console-design.md)(仅 spec) | — | 审核台设计,已由 m3-compliance 实现 |
| 09-11 | [ops-console](archive/plans/2026-09-11-ops-console.md) | — | 后 M3 ①:ops 审核台(后端 + 模板) |
| 09-11 | [ops-console-ui](archive/plans/2026-09-11-ops-console-ui.md) | [✓](archive/specs/2026-09-11-ops-console-ui-design.md) | ops 审核台 UI |
| 09-11 | [ban-notice-message-page](archive/plans/2026-09-11-ban-notice-message-page.md) | [✓](archive/specs/2026-09-11-ban-notice-message-page-design.md) | 后 M3 ②:封禁系统消息 + 消息页改版 |
| 09-12 | [backend-standardization](archive/plans/2026-09-12-backend-standardization.md) | [✓](archive/specs/2026-09-12-backend-standardization-design.md) | 后端规范化一期 |
| 09-12 | [backend-standardization-phase2](archive/plans/2026-09-12-backend-standardization-phase2.md) | — | 后端规范化二期 |
| 09-12 | [chat-profile-wechat](archive/plans/2026-09-12-chat-profile-wechat.md) | [✓](archive/specs/2026-09-12-chat-profile-wechat-design.md) | 后 M3 ③:微信式聊天 + 资料页(IM 昵称同步) |
| 09-12 | [report-notice](archive/plans/2026-09-12-report-notice.md) | [✓](archive/specs/2026-09-12-report-notice-design.md) | 后 M3 ⑤:举报处理通知(后端 256 / 前端 157 绿) |
| 09-12 | [square-feed](archive/plans/2026-09-12-square-feed.md) | [✓](archive/specs/2026-09-12-square-feed-design.md) | 后 M3 ⑥:广场页(动态流) |
| 09-13 | [online-presence](archive/plans/2026-09-13-online-presence.md) | [✓](archive/specs/2026-09-13-online-presence-design.md) | 后 M3 ⑦:在线状态(自建 presence) |
| 09-13 | [square-profile-presence](archive/plans/2026-09-13-square-profile-presence.md) | [✓](archive/specs/2026-09-13-square-profile-presence-design.md) | 广场作者入口 + 在线绿点 + presence 分片 |
| 09-18 | [m4-deploy-runthrough](archive/plans/2026-09-18-m4-deploy-runthrough.md) | [✓](archive/specs/2026-09-18-m4-deploy-runthrough-design.md) | M4 第一步:宝塔全托管服务器跑通 |
| 09-18 | [ui-revamp-batch1](archive/plans/2026-09-18-ui-revamp-batch1.md) | [✓](archive/specs/2026-09-18-ui-revamp-batch1-design.md) | UI 批次①:底座 + 底栏(220 测试绿) |
| 09-19 | [ui-revamp-batch2](archive/plans/2026-09-19-ui-revamp-batch2.md) | [✓](archive/specs/2026-09-19-ui-revamp-batch2-design.md) | UI 批次②:发现页(233 测试绿) |
| 09-19 | [ui-revamp-batch3](archive/plans/2026-09-19-ui-revamp-batch3.md) | [✓](archive/specs/2026-09-19-ui-revamp-batch3-design.md) | UI 批次③:消息/聊天(247 测试绿) |
| 09-21 | [api-documentation](archive/plans/2026-09-21-api-documentation.md) | [✓](archive/specs/2026-09-21-api-documentation-design.md) | 接口文档体系(`docs/api/` 十册 + 双向门禁) |

### 2026-10:网页端、UI 批次④–⑥、P1 功能、自建 IM、三轮安全整改、HTTPS

| 日期 | 主题 | spec | 交付结论 |
|---|---|---|---|
| 10-05 | [web-frontend](archive/plans/2026-10-05-web-frontend.md) | [✓](archive/specs/2026-10-05-web-frontend-design.md) | 网页端计划一:壳层 / 心跳 token / 基础组件 / 鉴权 / 路由守卫 |
| 10-05 | [web-features](archive/plans/2026-10-05-web-features.md) | — | 网页端计划二:资料 / 发现配对 / 广场 / 设置(21 任务) |
| 10-05 | [web-chat-qa](archive/plans/2026-10-05-web-chat-qa.md) | — | 网页端计划三:聊天 / 端到端 / CI / 部署文档(16 任务) |
| 10-12 | [ui-revamp-batch4](archive/plans/2026-10-12-ui-revamp-batch4.md) | [✓](archive/specs/2026-10-12-ui-revamp-batch4-design.md) | UI 批次④:我的 + 他人资料页(Hero 转场首落地) |
| 10-12 | [ui-revamp-batch5](archive/plans/2026-10-12-ui-revamp-batch5.md) | [✓](archive/specs/2026-10-12-ui-revamp-batch5-design.md) | UI 批次⑤:广场 |
| 10-12 | [ui-revamp-batch6](archive/plans/2026-10-12-ui-revamp-batch6.md) | [✓](archive/specs/2026-10-12-ui-revamp-batch6-design.md) | UI 批次⑥:二级页(表单控件规范定死) |
| 10-13 | [account-deletion](archive/plans/2026-10-13-account-deletion.md) | [✓](archive/specs/2026-10-13-account-deletion-design.md) | 上线合规轨 T-17:账号注销(PR #6) |
| 10-17 | [backend-comment-standardization](archive/plans/2026-10-17-backend-comment-standardization.md) | — | Python 注释规范 + `CommentCoverageTests` 门禁 |
| 10-20 | [likes-received](archive/plans/2026-10-20-likes-received.md) | [✓](archive/specs/2026-10-20-likes-received-design.md) | P1-1 喜欢我的人(PR #8) |
| 10-20 | [settings-completion](archive/plans/2026-10-20-settings-completion.md) | [✓](archive/specs/2026-10-20-settings-completion-design.md) | P1-2 设置页补齐 + `feedback` app |
| 10-20 | [relationship-exits](archive/plans/2026-10-20-relationship-exits.md) | [✓](archive/specs/2026-10-20-relationship-exits-design.md) | P1-3 关系出口(解除配对 + 撤回) |
| 10-20 | [square-comment-threads](archive/plans/2026-10-20-square-comment-threads.md) | [✓](archive/specs/2026-10-20-square-comment-threads-design.md) | 广场评论楼中楼(PR #12) |
| 10-20 | [self-hosted-im](archive/plans/2026-10-20-self-hosted-im.md) | [✓](archive/specs/2026-10-20-self-hosted-im-design.md) | 自建 C++ IM 交付(双跑 + 灰度) |
| 10-20 | [self-hosted-im-rollout](archive/plans/2026-10-20-self-hosted-im-rollout.md) | — | 自建 IM 上服务器 + 灰度核对单 |
| 10-26 | [im-image-messages](archive/plans/2026-10-26-im-image-messages.md) | [✓](archive/specs/2026-10-26-im-image-messages-design.md) | 聊天图片二期(`kind=3` + 人工抽审) |
| 10-26 | [chat-image-signing-retention](archive/plans/2026-10-26-chat-image-signing-retention.md) | [✓](archive/specs/2026-10-26-chat-image-signing-retention-design.md) | 聊天图片签名 URL + 30 天保留清理 |
| 10-26 | [im-message-search](archive/plans/2026-10-26-im-message-search.md) | [✓](archive/specs/2026-10-26-im-message-search-design.md) | 聊天记录搜索(`/im/api/search` + App/Web 定位) |
| 10-27 | [im-voice-messages](archive/plans/2026-10-27-im-voice-messages.md) | [✓](archive/specs/2026-10-27-im-voice-messages-design.md) | 语音消息(`kind=4` + ffmpeg 转码 + 签名) |
| 10-28 | [security-remediation](archive/plans/2026-10-28-security-remediation.md) | — | 第一轮安全审计 P0+P1 整改 |
| 10-28 | [security-round2](archive/plans/2026-10-28-security-round2.md) | — | 第二轮安全审计整改(PR #20) |
| 10-28 | [token-hardening](archive/plans/2026-10-28-token-hardening.md) | [✓](archive/specs/2026-10-28-token-hardening-design.md) | 令牌硬化(Web Cookie / App secure storage / 证书绑定) |
| 10-28 | [chat-shiliu153-cn-https](archive/plans/2026-10-28-chat-shiliu153-cn-https.md) | — | 生产切 `https://chat.shiliu153.cn` |

### 2026-11:访客、语音交互打磨、第三轮安全整改、已读回执、契约体系、推送

| 日期 | 主题 | spec | 交付结论 |
|---|---|---|---|
| 11-01 | [profile-visits](archive/plans/2026-11-01-profile-visits.md) | [✓](archive/specs/2026-11-01-profile-visits-design.md) | 谁看过我(PR #21,已上线) |
| 11-01 | [voice-recording-interaction](archive/plans/2026-11-01-voice-recording-interaction.md) | [✓](archive/specs/2026-11-01-voice-recording-interaction-design.md) | 语音录音交互打磨(Web 点击式 + App 状态机) |
| 11-01 | [security-round3](archive/plans/2026-11-01-security-round3.md) | — | 第三轮安全审计整改(PR #30,已上线) |
| 11-04 | [read-receipt](archive/plans/2026-11-04-read-receipt.md) | [✓](archive/specs/2026-11-04-read-receipt-design.md) | 已读回执(imserver 广播 + peer_read_seq,App/Web 双端;backlog C-2) |
| 11-04 | [cursor-pagination](archive/plans/2026-11-04-cursor-pagination.md) | — | cursor/keyset 分页替代 offset(五个列表接口 + App/Web 双端;backlog D-1 / 审查 N-5) |
| 11-05 | [openapi-and-client-codegen](archive/plans/2026-11-08-openapi-and-client-codegen.md) | — | OpenAPI 契约体系:47 个操作 `@extend_schema` + 字段级双向门禁 + Web 类型/App 字段契约 + 版本号单一来源(backlog D-5,PR #59,已上线 `74f920f1`;C-1 推送新增 4 个操作后为 51 个) |
| 11-05 | [dual-server-load-balancing](archive/specs/2026-10-28-dual-server-load-balancing-design.md)(仅 spec) | — | 双机负载均衡方案 v2:**已决策不做**(2026-11-04 用户拍板选「不做双机、暂不升配」),决策记录见 [ops/dual-server-vs-upgrade](../ops/dual-server-vs-upgrade-2026-11-04.md);升配触发条件写在记录 §5 |
| 11-05 | [observability-and-capacity](archive/plans/2026-11-02-observability-and-capacity.md) | — | 可观测性 + 容量工程 + 削峰整改四轨全部落地(A 可观测 / B 容量 / C 后端深度 / D 叙事);未勾项逐条对应交付证据见文件 §9(PR #53/#50/#69/#70/#71) |
| 11-08 | [tencent-im-removal](archive/plans/2026-11-04-tencent-im-removal.md) | — | 删除腾讯云 IM 分支:App/Web/后端三端 + 配置/CI/文档收敛,灰度开关移除、回退改镜像;backlog D-4 |

> 文件名用**立项日期**,与「日期」列的交付日期可能不同(如 `2026-11-04-tencent-im-removal.md` 于 11-08 交付)。

---

## 5. 相关文档

- 待办事项总表:[`docs/backlog/2026-11-03-todo.md`](../backlog/2026-11-03-todo.md)
- 里程碑时间线:[`docs/milestones.md`](../milestones.md)
- 全栈工程审查(2026-11-03,待办的来源之一):[`docs/reviews/2026-11-03-fullstack-review.md`](../reviews/2026-11-03-fullstack-review.md)
- 安全审计报告:[`docs/security/`](../security/)
- 踩坑手册:[`docs/pitfalls/README.md`](../pitfalls/README.md)
