# docs/superpowers/ — 设计 spec 与实施计划

两类文档:**设计 spec**(`specs/`,回答「做什么、为什么」)与**实施计划**(`plans/`,回答「怎么做、什么顺序、怎么验」)。
计划内的进度**只认 checkbox**;计划交付时在文件末尾追加「执行记录 / 与计划的偏差」。

> **核心约定:一个主题交付并上线后,立即 `git mv` 到 `archive/`,再跑一次
> `python scripts/docs_index.py --write` 刷新归档清单(清单是生成物,不是手写的表)。**
> `specs/` 与 `plans/` 只保留「进行中 / 未启动 / 常驻」的文档 —— **目录本身就是当前工作面**。

---

## 1. 目录结构

| 路径 | 内容 |
|---|---|
| `specs/` | 进行中 / 未启动 / 常驻的设计文档 |
| `plans/` | 进行中 / 未启动的实施计划 |
| `archive/specs/`、`archive/plans/` | 已交付并归档的历史文档 —— 份数与逐份清单见 [archive/INDEX.md](archive/INDEX.md)(生成物,禁止手改) |

## 2. 当前工作面(目录即事实;份数见 [docs/README.md](../README.md))

| 文档 | 状态 | 说明 |
|---|---|---|
| [specs/2026-09-15-ui-design-language-design.md](specs/2026-09-15-ui-design-language-design.md) | **常驻,强制** | 「心跳」UI 设计规则 v1.5。所有 App 端 UI 改动动手前必读;**永远不归档** |
| [specs/2026-11-07-superagent-dev-workflow-design.md](specs/2026-11-07-superagent-dev-workflow-design.md) | **已交付;spec 常驻** | 引入 WSL `dsh-superagent` 后的开发流程:人只开单与验收,实现交给 worker,CI 当唯一裁判。P0–P3 的实施计划(流程自身的引导,按约定必须内联做、不派工单)已于 2026-11-11 执行完毕,plan 已归档到 [archive/plans/](archive/plans/2026-11-07-superagent-dev-workflow.md);**spec 保留在 `specs/` 作常驻流程参考**(运维手册见 [docs/ops/superagent.md](../ops/superagent.md)) |
| [specs/2026-11-08-superagent-automation-ladder-design.md](specs/2026-11-08-superagent-automation-ladder-design.md) | 进行中(**L1–L4 已实现**,L4 总闸默认未开) | 自动化阶梯 L0–L4:把「人出现在流程里的那几处」逐个换成确定性机制。**L1(closeout 一条命令)/ L2(白名单自动合)/ L3(模拟器进 CI)/ L4(需求自动入队)均已实现**(实施记录见该 spec §9):L4 是唯一「替人决定做什么」的一级,所以只开三类机器可判的信号、判不出来就不开单、派单仍由人;执行者是确定性 workflow,`eval.mode` 保持 `observe`(spec §6.2)。总闸 `L4_INTAKE` **默认 `off`**,启用是人的一次显式动作 |
| [specs/2026-11-13-aws-distributed-deployment-design.md](specs/2026-11-13-aws-distributed-deployment-design.md) | **设计稿,待拍板**(无实施计划) | AWS 两台悉尼机的分布式部署设计:把「单机 + 宝塔」换成「两台机 + 托管数据库」。输入是 [双机 v2 设计](archive/specs/2026-10-28-dual-server-load-balancing-design.md) 与 [双机 vs 升配决策](../ops/dual-server-vs-upgrade-2026-11-04.md)。**未改任何业务代码**,是否实施等主人拍板 |

`specs/` 中的 [dual-server-load-balancing](archive/specs/2026-10-28-dual-server-load-balancing-design.md) 已在
2026-11-04 拍板「不做双机、暂不升配」,转为历史设计。批次 F–J 已于 2026-11-07 全部交付,
那份 plan 已 `git mv` 到 `archive/plans/` 并在 §4 补了一行。**批次 K(多端在线)与 L(输入中 + 引用回复)
已于 2026-11-09 归档**(K-1~K-4 / L-1~L-2 全部合并进 `master`,已随 **1.0.11** 上线(2026-11-09)),
第四轮安全审计整改 plan 一并归档(其自身状态即「已实施 / 已合并」)。

> **悬空引用已消除(2026-11-09)**:K 与 L 的 spec 里那句「第六轮功能开发拆批(K → L → M → N → O)」
> 当年没有落进 backlog。2026-11-09 已按**主人在 6 个候选中选定 5 项**重新立项为
> [批次 M–Q](archive/specs/2026-11-09-batch-m-q-design.md)(M 登录设备 / N 会话管理 / O 滑卡增强 / P 使用报告 / Q 敏感词),
> 与旧引用的字母编号不冲突,旧引用按本条作废。**该批已于同日全部交付并归档**,见 §4。
>
> **2026-11-12 的 CI 流程门禁整改(P0/P1/P2)已完成并归档**,见
> [archive/specs/2026-11-12-ci-flow-gates-design.md](archive/specs/2026-11-12-ci-flow-gates-design.md)。
> 它**不计入工作面**:立项与交付同日完成,所以没有在 `specs/` 停留过;该文 §6 是这批的未收尾台账
> (已同步到 [backlog §7](../backlog/2026-11-03-todo.md))。

**当前全部待办**(跨文档汇总、按批次排好序、每条可直接开新对话执行)见
[`docs/backlog/2026-11-03-todo.md`](../backlog/2026-11-03-todo.md)。

## 3. 命名与写作规范

- 文件名 `YYYY-MM-DD-<主题>.md`;spec 以 `-design` 结尾,plan 同名去掉 `-design`
- plan 顶部必须写:**Spec 链接**、**Goal**、**Architecture**、**Global Constraints**、**验收命令**
- 一个 Task = 一次可独立验证的改动;每个 Task 结束跑该 Task 的验证命令并提交,再进下一个
- 交付后在文件末尾写「执行记录 / 与计划的偏差 / 踩到的坑」,**不要**回头补勾旧 checkbox(见 §4 注)
- 交付即归档:同一提交内 `git mv` 到 `archive/` + 跑 `python scripts/docs_index.py --write`
  刷新 [archive/INDEX.md](archive/INDEX.md) + 更新 `CLAUDE.md` 里程碑摘要

## 4. 归档清单(已交付)

> **本节不再手写清单**。逐份的日期 / 主题 / plan ↔ spec 对照在
> [`archive/INDEX.md`](archive/INDEX.md) —— 由 `scripts/docs_index.py` 扫描目录生成,
> **禁止手改**;份数也只在那里报(`python scripts/docs_index.py --check` 会拦)。
> 本节只留人写的「这段时期交付了什么」的脉络。

> **注**:2026-10 之前的计划普遍存在「已交付但 checkbox 未回填」的情况(M0–M2、UI 批次②③、
> 广场楼中楼、自建 IM、账号注销、访客等)。判断是否交付以 `git log` 与
> [`docs/milestones.md`](../milestones.md) 为准,不要以文件内 checkbox 为准。

### 交付脉络

- **2026-09**:M0 地基 → M1/M2 后端与前端 → M3 合规 → 后 M3 ①–⑦(ops 审核台 / 封禁消息页 /
  微信式聊天与资料页 / 举报通知 / 广场 / 在线状态)→ M4 服务器跑通;另有 UI 整改批次①–③
  与接口文档体系(十册 + 双向门禁)。
- **2026-10**:网页端三份计划、UI 批次④–⑥、P1 功能群(喜欢我 / 设置补齐 / 关系出口 /
  评论楼中楼 / 自建 IM / 灰度核对单)、聊天图片·语音·记录搜索、多轮安全审计整改与令牌硬化、
  HTTPS 切换。
- **2026-11**:访客、语音录音交互、安全审计整改、已读回执、游标分页、OpenAPI 契约体系、
  可观测性与容量、腾讯云 IM 分支删除、第五轮 F–J 批次、安全审计整改、批次 K(多端在线)/
  L(输入中 + 引用回复)/ M–Q(第六轮五批)/ R–W(第七轮六批)、superagent 开发流程、
  CI 流程门禁整改、**文档与脚本治理 6 节**(口径地图 → 文件归位 → 索引生成 → 门禁注册表 →
  脚本公共层 → docs-lint 收口与写作规范,2026-11-14 全部落地并归档)。

逐条结论(哪天交付、哪个 PR、上线 SHA)以 [`docs/milestones.md`](../milestones.md) 为唯一 owner ——
本节不重复,那正是「同一事实两处手写」要消灭的东西。

> 文件名用**立项日期**,与「日期」列的交付日期可能不同(如 `2026-11-04-tencent-im-removal.md` 于 11-08 交付)。

---

## 5. 相关文档

- 待办事项总表:[`docs/backlog/2026-11-03-todo.md`](../backlog/2026-11-03-todo.md)
- 里程碑时间线:[`docs/milestones.md`](../milestones.md)
- 全栈工程审查(2026-11-03,待办的来源之一):[`docs/reviews/2026-11-03-fullstack-review.md`](../reviews/2026-11-03-fullstack-review.md)
- 安全审计报告:[`docs/security/`](../security/)
- 踩坑手册:[`docs/pitfalls/README.md`](../pitfalls/README.md)
