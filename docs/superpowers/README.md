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
| `archive/specs/`、`archive/plans/` | 已交付并归档的历史文档(95 份 = 38 份 spec + 57 份 plan,清单见 §4) |

## 2. 当前工作面(5 份)

| 文档 | 状态 | 说明 |
|---|---|---|
| [specs/2026-11-09-batch-r-w-design.md](specs/2026-11-09-batch-r-w-design.md) + [plans/2026-11-09-batch-r-voice-intro.md](plans/2026-11-09-batch-r-voice-intro.md) + [plans/2026-11-09-batch-s-filter-daily.md](plans/2026-11-09-batch-s-filter-daily.md) + [plans/2026-11-10-batch-u-square-likes-favorites.md](plans/2026-11-10-batch-u-square-likes-favorites.md) + [plans/2026-11-10-batch-v-ops-metrics-dashboard.md](plans/2026-11-10-batch-v-ops-metrics-dashboard.md) + [plans/2026-11-10-batch-u-w-handoff.md](plans/2026-11-10-batch-u-w-handoff.md) | **进行中(已定稿)** | 第七轮功能开发 R–W 六批:语音自我介绍 / 发现筛选+精选 / 聊天打磨 / 广场点赞列表+收藏 / 运营看板 / 发版自动化。顺序 W→R→S→U→V→T,主人已授权「每批自行验收后直接合并」,发版留给主人。**W-L1 已交付(PR #200);R 批已交付(#203/#207/#208);S 批已交付(#212/#214/#216);U 批已交付(#221/#224/#226);V 批已交付(#231/#232);T / W-L3 待开工,范围见交接文档** |
| [specs/2026-09-15-ui-design-language-design.md](specs/2026-09-15-ui-design-language-design.md) | **常驻,强制** | 「心跳」UI 设计规则 v1.5。所有 App 端 UI 改动动手前必读;**永远不归档** |
| [specs/2026-11-07-superagent-dev-workflow-design.md](specs/2026-11-07-superagent-dev-workflow-design.md) + [plans/2026-11-07-superagent-dev-workflow.md](plans/2026-11-07-superagent-dev-workflow.md) | 待实施(P0–P4) | 引入 WSL `dsh-superagent` 后的新开发流程:人只开单与验收,实现交给 worker,CI 当唯一裁判。plan 是 P0–P3 的实施计划(流程自身的引导,按约定必须内联做,不派工单) |
| [specs/2026-11-08-superagent-automation-ladder-design.md](specs/2026-11-08-superagent-automation-ladder-design.md) | 进行中(仅 L2 已实现) | 自动化阶梯 L0–L4:把「人出现在流程里的那几处」逐个换成确定性机制。**L2 白名单自动合已上线;L1(closeout 一条命令)/ L3(模拟器进 CI)/ L4(需求自动入队)未做**,各自单独成单 |

`specs/` 中的 [dual-server-load-balancing](archive/specs/2026-10-28-dual-server-load-balancing-design.md) 已在
2026-11-04 拍板「不做双机、暂不升配」,转为历史设计。批次 F–J 已于 2026-11-07 全部交付,
那份 plan 已 `git mv` 到 `archive/plans/` 并在 §4 补了一行。**批次 K(多端在线)与 L(输入中 + 引用回复)
已于 2026-11-09 归档**(K-1~K-4 / L-1~L-2 全部合并进 `master`,已随 **1.0.11** 上线(2026-11-09)),
第四轮安全审计整改 plan 一并归档(其自身状态即「已实施 / 已合并」)。

> **悬空引用已消除(2026-11-09)**:K 与 L 的 spec 里那句「第六轮功能开发拆批(K → L → M → N → O)」
> 当年没有落进 backlog。2026-11-09 已按**主人在 6 个候选中选定 5 项**重新立项为
> [批次 M–Q](archive/specs/2026-11-09-batch-m-q-design.md)(M 登录设备 / N 会话管理 / O 滑卡增强 / P 使用报告 / Q 敏感词),
> 与旧引用的字母编号不冲突,旧引用按本条作废。**该批已于同日全部交付并归档**,见 §4。

**当前全部待办**(跨文档汇总、按批次排好序、每条可直接开新对话执行)见
[`docs/backlog/2026-11-03-todo.md`](../backlog/2026-11-03-todo.md)。

## 3. 命名与写作规范

- 文件名 `YYYY-MM-DD-<主题>.md`;spec 以 `-design` 结尾,plan 同名去掉 `-design`
- plan 顶部必须写:**Spec 链接**、**Goal**、**Architecture**、**Global Constraints**、**验收命令**
- 一个 Task = 一次可独立验证的改动;每个 Task 结束跑该 Task 的验证命令并提交,再进下一个
- 交付后在文件末尾写「执行记录 / 与计划的偏差 / 踩到的坑」,**不要**回头补勾旧 checkbox(见 §4 注)
- 交付即归档:同一提交内 `git mv` 到 `archive/` + 更新本文 §4 + 更新 `CLAUDE.md` 里程碑摘要

## 4. 归档清单(已交付,共 95 份 = 38 份 spec + 57 份 plan)

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
| 11-07 | [feature-batches-f-j](archive/plans/2026-11-05-feature-batches-f-j.md) | — | 第五轮功能开发五批全交付:**F** 暗黑模式(1.0.5)/ **G** 共同点破冰(1.0.6)/ **H** 站内通知中心(1.0.7)/ **I** 广场关注 + 关注流(1.0.9)/ **J** 聊天表情贴纸(1.0.10)。设计决策内嵌该文 §2;J 批的 J-1 闸门核实了 `kind=2 custom` 持久化与补拉,并据实改为「kind=2 + 上行白名单」(计划里「imserver 零改动」的前提被证伪) |
| 11-08 | [security-round4](archive/plans/2026-11-08-security-round4.md) | — | 第四轮安全审计整改 R4:7 张实现单 + 2 项人侧内联全部落地,只剩 A2「Redis 口令」留人侧未做;已上线 `dfa641d`(纯服务端,不升版本) |
| 11-08 | [multi-device-session](archive/plans/2026-11-08-multi-device-session.md) | [✓](archive/specs/2026-11-08-multi-device-session-design.md) | 批次 K 多端在线(1 App + 1 Web):端会话版本下沉 `accounts.DeviceSession` / `im_device_session`、imserver 按端注册·扇出·踢人、跨端已读 `self_read`、统一上报 `X-Client`;K-1~K-4 = PR #150/#151/#154/#155。已随 1.0.11 上线 |
| 11-09 | [typing-and-quote](archive/plans/2026-11-08-typing-and-quote.md) | [✓](archive/specs/2026-11-08-typing-and-quote-design.md) | 批次 L 输入中状态 + 引用回复:`typing` 帧(只发对端、未配对与限流超限一律静默)+ 服务端生成引用快照(`ref_msg_id` / `ref_snapshot`,不信客户端);L-1/L-2 = PR #158/#159。已随 1.0.11 上线(验收结果见 release.md §6.6) |
| 11-09 | [batch-m-q](archive/plans/2026-11-09-batch-m-q.md) | [✓](archive/specs/2026-11-09-batch-m-q-design.md) | 第六轮功能开发五批全交付:**M** 登录设备(列表 + 单端下线,`DeviceSession.last_active_at` / `logged_out_at`)/ **N** 会话管理三件套(置顶·免打扰·删除,imserver `007` + `/im/api/conversations/flags`)/ **O** 滑卡增强(30 秒撤销 + 每日喜欢额度)/ **P** 使用报告(`GET /stats/me` 七项数字)/ **Q** 聊天文字敏感词(本地词库 + AC 自动机)。15 个 PR:立项 #164、M #168/#189/#180/#174、N #175/#187/#188、O #170/#190/#191、P #169/#181/#186、Q #192;`master` 末次合并 `72589f9`。**未发版**(不升版本号、不打 tag、不部署) |

> 文件名用**立项日期**,与「日期」列的交付日期可能不同(如 `2026-11-04-tencent-im-removal.md` 于 11-08 交付)。

---

## 5. 相关文档

- 待办事项总表:[`docs/backlog/2026-11-03-todo.md`](../backlog/2026-11-03-todo.md)
- 里程碑时间线:[`docs/milestones.md`](../milestones.md)
- 全栈工程审查(2026-11-03,待办的来源之一):[`docs/reviews/2026-11-03-fullstack-review.md`](../reviews/2026-11-03-fullstack-review.md)
- 安全审计报告:[`docs/security/`](../security/)
- 踩坑手册:[`docs/pitfalls/README.md`](../pitfalls/README.md)
