---
状态: 常驻
复核: 每次新增 / 改发信点时
---

# 邮件:主题规范与发信点

> 一句话:自动邮件不再一律叫「服务器日报」。主题固定成
> `[chatapp·<类别>] <对象> — <结论>` 三段,类别是**封闭枚举**,谁发信谁填三段,格式只有一处实现。

## 1. 为什么改(2026-11-16)

改之前主题是「ini 里的前缀 + 调用方自己拼的标题」:服务器侧的 `[日报]` / `[chatapp]` 写在
`/opt/notify` 的两份配置里,WSL 侧的 `[superagent] worker 健康检查异常(rc=1)` 硬编码在
`scripts/superagent-health/notify.sh` 里。三个后果:

1. **一份服务器日报和一条 MySQL 宕机告警长得一模一样** —— 收件箱里筛不出「哪些是告警」;
2. **看不出对象** —— 「worker 健康检查异常」不说是哪台机器、哪个环节;
3. **看不出结论** —— 标题只说「异常」,不说「游标停摆」还是「出网不通」,点开才知道。

判据是:**主题必须能被机器与人都当索引读**。类别给「该看代码还是该看机器」,对象给
「哪台/哪个」,结论给「要不要现在处理」。

## 2. 主题规范

格式:

```text
[chatapp·<类别>] <对象> — <结论>
```

| 字段 | 取值 | 谁决定 |
|---|---|---|
| 项目标签 | 固定 `chatapp` | `scripts/lib/mail.py::PROJECT_TAG` |
| 类别 | **封闭枚举**:`日报` / `巡检` / `告警` / `CI` / `备份` / `部署` / `会话` | `scripts/lib/mail.py::CATEGORIES` |
| 对象 | 哪台机器 / 哪个服务 / 哪条告警 | 发信点 |
| 结论 | 发生了什么 / 处理到哪一步 | 发信点 |

三条硬规则:

1. **数字不进主题。** 落后几分钟、几条未读、耗时几秒每轮都在变,混进主题就等于没有去重
   (同一故障会变成收件箱里几十封「不同的信」)。数字一律进正文。
2. **类别不许自由发挥。** 新增一类要走 `CATEGORIES` + 本表 + 用例三处同改;
   `scripts/test_mail.py` 会把本表与代码双向比对,单改一边即红。
3. **主题里不许有换行。** 主题是邮件头,换行等于让人往头里塞额外字段(header 注入),
   渲染时会直接拒掉。

**为什么 `CI` 与 `巡检` 分开**:前者要去看代码 / 门禁,后者要去看这台机器还能不能干活。
合成一类,收到信的人还得点开才知道该找谁。

## 3. 发信点清单(主题表)

| 发信点 | 何时 | 主题 | 级别 | 抑制重复 |
|---|---|---|---|---|
| 服务器日报(22:00) | 每天一次 | `[chatapp·日报] 服务器 — 无硬故障` | info | 一天一封,不需要 |
| 备份核验(随日报) | 每天一次 | `[chatapp·备份] 自建双库 03:20 — 已完成` | info / error | 随日报 |
| worker 巡检(WSL) | 15 分钟一轮,异常才发 | `[chatapp·巡检] worker — 游标停摆` | error | 指纹(检查名+状态)6 小时 |
| CI 红轨(随 worker 巡检) | 同上 | `[chatapp·CI] 默认分支 — 有红轨` | error | 同上 |
| Alertmanager 告警 | 告警触发 / 恢复 | `[chatapp·告警] ApiHighErrorRate — firing` | error / info | `groupKey + status`,60 分钟窗口 |
| MySQL 看门狗 | 宕机 / 拉起 / 恢复 | `[chatapp·告警] MySQL 看门狗 — 已自动拉起` | error | 脚本内「只报一次」状态文件 |
| 探针(imserver readyz / Django health) | 30 秒一轮,失败才发 | `[chatapp·告警] 探针 — imserver readyz 不通` | error | 脚本内失败态去重 |
| 部署 | 手工 | `[chatapp·部署] chatapp — 已完成` | info / error | 不需要 |
| DSH 会话通知 | 每轮结束 / 需要人选择 | `[chatapp·会话] chat_app — 第 3 轮结束` | info / warn | 插件内节流(最小间隔 + 每日上限) |

> 上表的示例主题就是**规范本身**:`scripts/test_mail.py::DocsTableTests` 会把每条示例
> 拿回 `render_subject()` 重新渲染,不一致即红。改格式必须同一次改代码、本表与用例。

## 4. 通道与实现

```
WSL(worker 巡检)  ─> scripts/lib/mail.py ─┐
服务器脚本(日报 / 看门狗 / 探针 / relay) ─> /opt/notify ─┴─> 阿里云邮件推送 ─> 同一收件箱
DSH 会话通知(经 SSH)  ─> /opt/notify ─────┘
```

| 侧 | 实现 | 主题怎么来 |
|---|---|---|
| 仓库 / WSL | `scripts/lib/mail.py`(本模块:主题渲染 + SMTP + 去重 + 配额 + JSONL 日志) | `render_subject()` 一处生成 |
| 服务器 | `/opt/notify/bin/notify`(不在仓库,`deploy/**` 由主人维护) | 调用方按本表拼 `--title` |

**服务器上的四份配置(2026-11-17 起各自有身份)**,主题 = `subject_prefix` + `级别标记` + `title`:

| 配置 | 谁用 | `from_name` | `subject_prefix` |
|---|---|---|---|
| `/root/.config/notify/config.ini` | **默认配置**:未显式指定 `NOTIFY_CONFIG` 的调用方 → 目前只有 DSH 会话通知 | `chatapp 会话` | `[chatapp·会话]` |
| `/etc/notify/daily.ini` | 22:00 服务器日报(`daily-digest.sh` 显式指定) | `chatapp 日报` | `[chatapp·日报]` |
| `/etc/notify/alerts.ini` | Alertmanager relay / MySQL 看门狗 / imserver 探针 | `chatapp 告警` | `[chatapp·告警]` |
| WSL `/root/.dsh/superagent-health.env` | worker 巡检(直连同一阿里云账号的 SMTP) | — | 主题由 `mail.py` 渲染 `[chatapp·巡检]` |

> 为什么默认配置绑「会话」而不是「日报」:DSH 的 `dsh-email-push` 插件是**唯一不传
> `NOTIFY_CONFIG` 的调用方**,原先它落到日报那份配置上,于是每封会话通知都顶着
> 「服务器日报」的名字 —— 这正是 2026-11-16 那次「所有邮件都叫服务器日报」的根因。
> 其余三个发信方各自显式指定 ini,互不干扰。

**为什么没把 `/opt/notify` 搬进仓库**:它正在服务器上跑,自带配额 / 去重 / 发送日志 / 状态库,
日报脚本也在服务器上;迁移的收益(少一份实现)小于风险(把一条在用的通道改坏)。
两边共享的是**同一份主题规范**,不是同一份代码 —— 所以本表是唯一事实来源。

**为什么邮件不走 http 代理**:mihomo 是 HTTP 代理,SMTP 过不去。`mail.py` 用 `smtplib`
直连,`notify.sh` 也显式 `env -u *_proxy`。

## 5. 配额预算

阿里云邮件推送的发信额度是**共享的**(日报、告警、会话通知、worker 巡检同一个账号):
每分钟 5 封、每天 **200** 封(`/etc/notify/daily.ini` 与 `alerts.ini` 的 `per_day` 是权威值;
`deploy/observability/notify-alerts.ini.tmpl` 里写的 50 是旧值,见 issue #403)。
按上面这张表算,正常一天的量级是:日报 1 封 + 备份随日报 + 巡检告警(每指纹 6 小时一次,
一个持续故障一天最多 4 封)+ 告警(去重窗口 60 分钟)+ 探针(失败态去重)+ 会话通知(插件内
最小间隔 + 每日上限)。留足余量,但**不要**把去重窗口调短来「看得更勤」—— 那会先耗尽额度,
再让真告警发不出去。

配额耗尽的语义是**失败**(`MailError`),不是静默跳过:那一刻我们确实没把告警发出去。

## 6. 开关

| 开关 | 默认 | 作用 |
|---|---|---|
| `MAIL_SMTP_URL` / `MAIL_FROM` / `MAIL_TO` | 空 | 发信三要素;缺一个就发不出去(`mail.py check` 会点名缺哪个) |
| `MAIL_USER` / `MAIL_PASS` | 空 | SMTP 认证(阿里云用发信密码) |
| `MAIL_STATE_DB` / `MAIL_LOG` | `~/.local/state/mail/` | 去重与配额状态库 / JSONL 发送日志 |
| `MAIL_PER_MINUTE` / `MAIL_PER_DAY` | 5 / 50 | 配额(本机按账号实际额度设成 5 / 200,与服务器 ini 对齐) |
| `MAIL_DRY_RUN` | 关 | 只渲染不投递(演练 / 排障) |
| `SUPERAGENT_HEALTH_CI_RED` | 关 | worker 巡检里「CI 红轨」那一项的开关 |

配置写在 `/root/.dsh/superagent-health.env`(600,仓库外);旧变量名
`SUPERAGENT_SMTP_URL` / `_MAIL_FROM` / `_MAIL_TO` / `_SMTP_USER` / `_SMTP_PASS`
由 `notify.sh` 自动映射到 `MAIL_*`,不必一次性改完。

## 7. 排障

```bash
# 配置齐不齐(不联网、不发信;--env-file 只补缺,shell 里已 export 的键优先)
python3 scripts/lib/mail.py check --env-file /root/.dsh/superagent-health.env
# 主题长什么样(不联网、不发信)
python3 scripts/lib/mail.py subject --category 巡检 --subject worker --verdict 游标停摆
# 真发一封(演练)
MAIL_DRY_RUN=1 python3 scripts/lib/mail.py send --category 巡检 \
    --subject worker --verdict 演练 --body "只渲染不投递"
# 最近发了什么、有没有被去重跳过
tail -n 20 ~/.local/state/mail/mail.jsonl
# 服务器侧(不在仓库):三份配置各渲染一次,不发信
NOTIFY_CONFIG=/etc/notify/daily.ini  /opt/notify/bin/notify send --title 服务器 --body x --dry-run --json
NOTIFY_CONFIG=/etc/notify/alerts.ini /opt/notify/bin/notify send --title 看门狗 --body x --dry-run --json
/opt/notify/bin/notify send --title "会话验证" --body x --dry-run --json   # 默认配置 = 会话
/opt/notify/bin/notify log -n 10
```
