# superagent-health —— worker 的「还活着吗」巡检

2026-11-13 的两起故障促成的:**worker 的失败方式可以是「绿着但不动」**,而面板上每个健康位
都会显示 `ready`,没有一处会报错。

| 那次故障 | 表现 | 面板 |
|---|---|---|
| mihomo 解析不到机场节点域名 | 106 个节点全 timeout,出网 0%;worker 的 git / 轮询全断 | 7890 在听,`status` 全绿 |
| 模型流 `stream idle timeout` | assignment 卡在 `running` **6 小时**,worktree 0 提交 | `errors: {}` |

所以补的不是「红轨告警」(main-health 已经管),而是**外部周期性探测**:出网真的能通吗、
派出去的评论真的进队列了吗、有没有 assignment 早就跑死了。

## 它多久跑一次 / 谁来跑

systemd timer,**每 15 分钟一轮**,开机 3 分钟后先补一轮(`OnBootSec`)。

> 这台机器会关机。关机期间没有 worker,也就没有可巡检的对象 —— timer 不跑是**正确**的,
> 不是盲区。恢复开机后第一轮会立刻告诉你「现在能不能干活」。所以巡检不依赖任何
> 交互式会话,也不需要有人在电脑前。

## 查什么

| 检查 | 判据 | 异常含义 |
|---|---|---|
| 出网 | 经代理 `GET https://api.github.com/rate_limit` 必须 2xx | worker 的 git / 轮询已经不能工作 |
| 出口节点 | mihomo 当前节点;选到 `HOST-FALLBACK` 只记录不告警 | 机场线路挂了,正在走宿主兜底 |
| 入队三连 | `thread` / `trigger_thread` / `ticket` 三张表都要有该 issue | 评论没进队列(§4.1 的静默丢单) |
| 僵尸 assignment | `state ∈ {running, pending}` 且超过 45 分钟没结束 | 工单跑死了(模型流超时那类) |
| 游标新鲜度 | `kv` 里 `github-cursor:*` 的最新时间落后超过 10 分钟(`SUPERAGENT_CURSOR_STALE_MINUTES`),**且** GitHub 通知里有「未读且 `updated_at` 晚于游标」的条目 | 通知轮询停摆:有活要干却没人读,派工评论不会进队列 |
| worktrees | `work/` 下的目录清单 | 仅供核对,不告警 |

**游标新鲜度只判「有未读但游标没动」**,不是单纯判「游标没动」:闲置时段没有新评论,游标
当然不动,只看时间会天天误报 —— 误报把人训成不看告警,比没有告警更糟。所以先看游标是否落后
阈值,再取 `gh api notifications` 判断「有没有比游标更新的未读」:有 → 异常(告警里打印游标
时间、落后分钟数、未读条数与前 3 条标题);没有 → 闲置,跳过。游标新鲜时**根本不联网**。

同一条告警里还带一个旁证「轮询心跳 `github-since`」:它每轮结束都会前进,**停在很久以前**
⇒ 轮询 loop 自己停了;**新鲜而游标不动** ⇒ 本来就是闲置。它只做旁证,不参与判定。

**默认只告警,不重启 orchestrator**(2026-11-16 起有「安全自愈」,但总闸默认关):
`SUPERAGENT_AUTOREHEAL=1` 且第四项判成停摆时,巡检会在**四道闸全过**的前提下自己跑
`bash /root/start-superagent.sh restart`,把人工那一步省掉;任何一条不过就只告警。

四道闸的**顺序是安全契约**(`superagent_health.py::maybe_autoreheal`,别优化掉):

1. 状态库里**没有** `state ∈ {running, pending}` 的 assignment —— 重启不会杀掉正在跑的会话;
2. `work/` 下每个 worktree 都没有未提交改动(`git status --porcelain` 为空)—— 有改动说明
   有人的活还没落地;**确认不了干净也按脏处理**(fail-closed);
3. 距上一次自愈尝试 ≥ `SUPERAGENT_AUTOREHEAL_MIN_MINUTES`(默认 20 分钟)—— 防抖,
   否则巡检每 15 分钟就会重启一次;
4. 以上全过才调重启回调(测试里注入假回调,生产才真跑 `start-superagent.sh`)。

结果分三种:成功 → 告警里写「**已自动重启**」+ 重启前后游标;回调非零退出 → 告警里带失败
原因、**按未自愈处理**(退出码仍是 1);某道闸不过 → 只告警,并写明是哪条闸、卡在什么上。
每次尝试都追加一行到 `/root/.dsh/state/superagent-health/autoreheal.log`(时间 / 原因 /
前后游标 / 退出码)—— 告警有 6 小时去重,「今天自愈了几次、结果如何」只能靠这个文件看。

**开关默认关**:与 `L4_INTAKE` 同一口径,机制上线不等于开始执行;不写 `SUPERAGENT_AUTOREHEAL`
时行为与本开关上线前**完全一致**(不读状态文件、不算闸门、不多一条检查)。取证与排障口径见
`docs/ops/superagent.md` §15。

**僵尸 assignment 可以「人工作废」**:DSH 没有取消 assignment 的 CLI/API,被模型流打断的那些会
永远停在 `running`。确认「这张单已经由别的单/PR 完成」之后,把 id 前缀填进
`SUPERAGENT_HEALTH_IGNORE_ZOMBIES`,巡检不再为它告警(信息仍打印,标注「已人工确认作废」)。
**不要拿它掩盖新故障** —— 那是把告警噪音化,比没有告警更糟。

`入队三连` 只能核对**已知**要查的 issue(`SUPERAGENT_HEALTH_ISSUES`),因为「哪条评论该进队列」
判不出来;**僵尸 assignment 是自动扫全表的**,不需要配置。

## 装

```bash
# 在 WSL 里,克隆里的任意位置
sudo bash scripts/superagent-health/install.sh          # 装 + 立刻跑一轮
sudo bash scripts/superagent-health/install.sh --no-run # 只装
sudo bash scripts/superagent-health/install.sh --uninstall
```

装到 `/root/.dsh/healthcheck/`(仓库外的运行时目录),于是**在哪个 worktree 里装都不影响正在
跑的那份**;升级 = 再跑一次 install。systemd 单元在 `/etc/systemd/system/superagent-health.{service,timer}`。

## 告警通道(装完必须配一行,否则只落盘)

配置在 `/root/.dsh/superagent-health.env`(chmod 600,不进仓库;模板见 `superagent-health.env.example`)。

优先级:`SUPERAGENT_NOTIFY_CMD` → SMTP → GitHub issue 评论 → 仅落盘 + journal。

- **SMTP(推荐)**:`SUPERAGENT_SMTP_URL="smtps://smtp.qq.com:465"` + `_MAIL_FROM` / `_MAIL_TO` /
  `_SMTP_USER` / `_SMTP_PASS`(QQ 邮箱用授权码)。发信**不走 http 代理**(mihomo 是 HTTP 代理,SMTP 过不去),
  `notify.sh` 里显式 `env -u *_proxy`。
- **GitHub issue 评论**:`SUPERAGENT_GH_ISSUE=<编号>`,用 WSL 已有的 `gh`/`gh-agent` 凭据,
  GitHub 把评论通知投递到账号邮箱 —— 零新增密钥,同时留一份审计记录。

**去重**:同一种异常(指纹相同)每 6 小时只发一次(`SUPERAGENT_HEALTH_RESEND_SECONDS`),
异常消失时状态自动清空。没有去重就是每 15 分钟一封,人会把告警关掉 —— 那比没有告警更糟。

## 手动跑 / 排障

```bash
bash /root/.dsh/healthcheck/run.sh                 # 等于 timer 跑的那一轮(带去重)
python3 /root/src/chatapp/scripts/superagent_health.py          # 只跑判定,不带告警
python3 /root/src/chatapp/scripts/superagent_health.py --json    # 机器可读
# 反证 / 离线复现:阈值设 0(任何游标都算落后)+ 用本地 JSON 冒充未读通知
python3 /root/src/chatapp/scripts/superagent_health.py --cursor-stale-minutes 0 \
  --notifications-file /tmp/notifications.json
systemctl list-timers superagent-health.timer
journalctl -u superagent-health -n 50 --no-pager
cat /root/.dsh/state/superagent-health/last-alert.md   # 最近一条告警原文
# 安全自愈:看今天自愈了几次、每次结果(告警有 6 小时去重,这里是逐次记录)
tail -n 20 /root/.dsh/state/superagent-health/autoreheal.log
# 开关当前是否打开(为空 = 关);打开/关闭都是改 env 文件里那行
grep -n '^SUPERAGENT_AUTOREHEAL' /root/.dsh/superagent-health.env
```

退出码:`0` 正常 / `1` 有异常 / `2` 判不出来(按异常处理 —— 判不出来绝不能算正常)。

## 自测

```bash
python -m unittest scripts.test_superagent_health -v     # 46 条,纯离线
```

自测里有一条是真事故的回放:用 LIKE 匹配原始 JSON 会把带空格的 `"number": 285` 判成 0 张单,
现在是解析 JSON 取 `mandate.basis.scope.number`。

游标新鲜度那组用例钉的是判错的两个方向:**落后 + 有未读 → 报**,**落后 + 无未读 → 不报**
(闲置),**新鲜 → 不报且根本不取通知**(断言取通知的函数没被调用);另有「通知取不到 ⇒
判不出来(退出码 2)」与「游标落后时心跳新鲜也不能洗白」两条。

**安全自愈**那组把四道闸逐条钉住(尤其「本该不重启却重启了」这个方向,那会把别人的活连同
会话一起弄丢):停摆 + 无活跃 assignment + worktree 干净 → **回调刚好被调一次**、告警含
「已自动重启」、`autoreheal.log` 落盘;有 `running` / `pending` 会话、worktree 有未提交改动、
worktree 根本不是 git 目录(确认不了)→ **一次都不调**;游标新鲜、总闸没开(`0`/`off`/空)、
距上次自愈不足 20 分钟 → **一次都不调**;重启回调非零退出 → 告警带失败原因且退出码仍是 1。
**自测里绝不真的调 `start-superagent.sh`** —— 回调是注入的假货,只记调用次数。
