---
状态: 生效中
复核: 每次新增 / 归档手册时
---

# docs/ops/ — 运维手册(常驻)

这里放**现在还在用**的运维手册:部署、排障、发版、容量口径、安全基线。
它们的共同点是**每次动手前要读、读完按步骤做**,而不是「某一次测出来的记录」。

> **完整清单见 [`docs/README.md`](../README.md)**(由 `scripts/docs_index.py` 扫描生成,
> 禁止手改)。下面这张表是**精选入口**(什么时候读 / 强制程度),不承诺穷举 ——
> 穷举由生成物保证,本表只回答「这件事该读哪份」。

> **一次性测量报告不在这里**,在 [`docs/reports/`](../reports/README.md)。
> 两边冲突时:**「现在该按哪个数字判」看
> [capacity-and-reliability.md](capacity-and-reliability.md)**,报告的原始数字只作证据。

## 1. 分册索引

| 手册 | 什么时候读 | 强制程度 |
|---|---|---|
| [runbook.md](runbook.md) | **出故障时**:告警处置、备份恢复、名单维护、巡检;**部署与更新**见 §10 | 按场景执行 |
| [imserver.md](imserver.md) | 改 IM / 排 IM 故障 / 看 WS 协议与探针 | 必读 |
| [release.md](release.md) | **每次发版**:8 步清单、tag、Release 正文规范、发版记录表 | 强制清单 |
| [superagent.md](superagent.md) | 派单、升级 worker、worker 全断排障、出口代理 | 操作前读 |
| [certificates.md](certificates.md) | 证书续期与到期巡检 | 操作前读 |
| [observability.md](observability.md) | 指标 / 看板 / 告警规则的取数与判读 | 改告警前读 |
| [capacity-and-reliability.md](capacity-and-reliability.md) | **引用任何容量数字之前** | 数字唯一 owner |
| [nginx-security.md](nginx-security.md) | 配反代、安全头、后台 IP 白名单、媒体验签 | 操作前读 |
| [push.md](push.md) | 推送链路契约(通道固定 `off`,只留接口与代码) | 改推送相关时读 |
| [dual-server-vs-upgrade-2026-11-04.md](dual-server-vs-upgrade-2026-11-04.md) | 问「要不要上双机 / 要不要升配」时 | 决策记录,结论已定 |

## 2. 相关目录

| 去哪 | 找什么 |
|---|---|
| [`docs/reports/`](../reports/README.md) | 一次性测量报告(压测、基线、规模、削峰) |
| [`scripts/ops/`](../../scripts/ops/) | 运维脚本(证书到期巡检 `check_ssl_expiry.sh`) |
| [`deploy/`](../../deploy) | 部署脚本、备份、看门狗、观测栈配置(**agent 禁改**,见 `AGENTS.md` §六) |
| [`docs/security/`](../security/README.md) | 安全审计报告 |
| [`docs/pitfalls/`](../pitfalls/README.md) | 踩坑手册(排障时按主题查) |

## 3. 本目录的两条规矩

1. **手册写「怎么做」,报告写「测出了什么」。** 一次性的数字不要抄进手册;手册只引用
   `capacity-and-reliability.md` 的口径行,口径行再点到报告。
2. **脚本不放在这里。** 2026-11-14 治理第 2 节把 `docs/ops/` 下的脚本、补丁、配置样本
   全部搬走了(压测脚本 → `scripts/stress/`,补丁 → `scripts/patches/`,
   证书巡检 → `scripts/ops/`,nginx 样本 → 本目录的 `nginx-security.md`)。
   `python scripts/docs_lint.py` 会拦住「又放回来」。
