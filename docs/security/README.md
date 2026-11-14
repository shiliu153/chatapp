# docs/security/ — 安全审计报告(只增不改)

这里放**每一轮**安全审计的完整报告:审计范围、发现的每条问题、修法与验收证据。
口径是**目录即事实**:轮次与数量看这个目录,不看任何手写计数。

> **完整清单见 [`docs/README.md`](../README.md)**(由 `scripts/docs_index.py` 扫描生成,
> 禁止手改)。下面这张表是**精选入口**(审计日期 / 状态注记),轮次与份数不在这里手写。

> **规矩:只增不改。** 报告是历史记录,发现结论过期就在报告顶部加「状态注记」,
> 不改原结论(见下表的注记行)。「现在是什么状态」看 [`docs/ops/`](../ops/README.md)
> 与代码,不看历史报告。

## 1. 轮次索引

| 轮次 | 报告 | 审计日期 | 状态注记 |
|---|---|---|---|
| 第一轮 | [2026-10-27-api-security-audit.md](2026-10-27-api-security-audit.md) | 2026-10-27 | 描述的腾讯云 IM 分支已于 2026-11-08 删除(D-4),相关表述仅作历史记录 |
| 第二轮 | [2026-10-28-api-security-audit-round2.md](2026-10-28-api-security-audit-round2.md) | 2026-10-28 | 同上 |
| 第三轮 | [2026-11-01-api-security-audit-round3.md](2026-11-01-api-security-audit-round3.md) | 2026-11-01 | 同上 |
| 第四轮 | [2026-11-08-api-security-audit-round4.md](2026-11-08-api-security-audit-round4.md) | 2026-11-08 | 纯服务端整改,已随当次上线 |

## 2. 怎么用这些报告

- **想知道「某条安全设计为什么长这样」**:按日期找到引入它的那一轮,读「问题 → 修法」。
  踩坑手册里对应的条目通常写了「见第 N 轮审计 M-x」。
- **想复核某条整改是否还在**:看代码 + 门禁,不看报告 —— 报告记录的是**当时**的证据。
- **新增一轮**:直接在本目录加一份 `YYYY-MM-DD-api-security-audit-roundN.md`,
  然后在本表加一行。**不要**在别处手写「N 轮审计」的计数(那正是治理要消灭的漂移)。

## 3. 相关

| 去哪 | 找什么 |
|---|---|
| [`docs/ops/nginx-security.md`](../ops/nginx-security.md) | 反代与安全头基线(审计结论落地的地方之一) |
| [`docs/ops/certificates.md`](../ops/certificates.md) | 证书与到期巡检 |
| [`docs/standards/sources-of-truth.md`](../standards/sources-of-truth.md) | 口径地图(哪条事实谁说了算) |
| [`docs/reviews/`](../reviews/2026-11-03-fullstack-review.md) | 全栈工程审查(与安全审计不同:那是工程质量视角) |
