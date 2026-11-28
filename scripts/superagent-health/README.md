# superagent-health —— worker 的「还活着吗」巡检

2026-11-13 的两起故障促成的:**worker 的失败方式可以是「绿着但不动」**,而面板上每个健康位
都会显示 `ready`,没有一处会报错。

| 那次故障 | 表现 | 面板 |
|---|---|---|
| mihomo 解析不到机场节点域名 | 106 个节点全 timeout,出网 0%;worker 的 git / 轮询全断 | 7890 在听,`status` 全绿 |
| 模型流 `stream idle timeout` | assignment 卡在 `running` **6 小时**,worktree 0 提交 | `errors: {}` |

所以补的不是「红轨告警」(那是另一类问题),而是**外部周期性探测**:出网真的能通吗、
派出去的评论真的进队列了吗、有没有 assignment 早就跑死了。

> **2026-11-16 起多了一项**:默认分支的 **CI 红轨**也在这里查。原先它由
> `.github/workflows/main-health.yml` 每天建一条 GitHub issue 承载 —— issue 是待办不是告警,
> 没人订阅就没人看见。现在红轨与 worker 巡检走**同一个出口(邮件)**,判据仍然复用
> `scripts/l4_intake.py::red_runs`(与 L4 自动入队同一个函数)。已知偏差:WSL 关机期间
> 没人报红轨,开机后第一轮(`OnBootSec`)补报。

## 它多久跑一次 / 谁来跑

systemd timer,**每 15 分钟一轮**,开机 3 分钟后先补一轮(`OnBootSec`)。

> 这台机器会关机。关机期间没有 worker,也就没有可巡检的对象 —— timer 不跑是**正确**的,
> 不是盲区。恢复开机后第一轮会立刻告诉你「现在能不能干活」。所以巡检不依赖任何
> 交互式会话,也不需要有人在电脑前。

## 查什么

| 检查 | 判据 | 异常含义 |
|---|---|---|
| 出网(经代理,2026-11-28 收窄) | **经 mihomo** `GET https://api.github.com/rate_limit` 必须 2xx(探针时临时摘掉 `no_proxy`,否则量到的是直连) | mihomo 那条腿断了:凡是需要出国的东西都会挂(`npm ci` / `pub get` / 机场订阅) |
| 出网(直连,2026-11-28 新增) | **不经任何代理** `GET https://api.github.com/rate_limit` 必须 2xx(`ProxyHandler({})`,无视 `http_proxy`) | GitHub 直连断了 —— worker 的轮询与 `gh` 全走这条腿,而这条腿原先**没有观测点** |
| 出口节点 | mihomo 当前节点;选到 `HOST-FALLBACK` 只记录不告警 | 机场线路挂了,正在走宿主兜底 |
| WSL 继承代理(2026-11-17 起) | 进程环境里的 `http(s)_proxy` 排除 worker 自 export 的那个值后,对剩下的值做一次 TCP 探针(3 秒);不通才算红 | 继承到的是死端口:`wsl -e bash -c '…'` 的联网命令会**静默挂住**(mirrored 的 autoProxy 把 Windows 系统代理导进了 WSL) |
| 入队三连 | `thread` / `trigger_thread` / `ticket` 三张表都要有该 issue | 评论没进队列(§4.1 的静默丢单) |
| 僵尸 assignment | `state ∈ {running, pending}` 且超过 45 分钟没结束 | 工单跑死了(模型流超时那类) |
| 游标新鲜度 | `kv` 里 `github-cursor:*` 的最新时间落后超过 10 分钟(`SUPERAGENT_CURSOR_STALE_MINUTES`),**且** GitHub 通知里有「未读且 `updated_at` 晚于游标」的条目 | 通知轮询停摆:有活要干却没人读,派工评论不会进队列 |
| CI 红轨(默认关) | 默认分支上每条 workflow 的最新一次 push run 都不是红的(`scripts/l4_intake.py::red_runs` 判据) | 合并后的红没人管(2026-11-11 那条红挂了 20 小时) |
| worktrees | `work/` 下的目录清单 | 仅供核对,不告警 |

**游标新鲜度只判「有未读但游标没动」**,不是单纯判「游标没动」:闲置时段没有新评论,游标
当然不动,只看时间会天天误报 —— 误报把人训成不看告警,比没有告警更糟。所以先看游标是否落后
阈值,再取 `gh api notifications` 判断「有没有比游标更新的未读」:有 → 异常(告警里打印游标
时间、落后分钟数、未读条数与前 3 条标题);没有 → 闲置,跳过。游标新鲜时**根本不联网**。

**出网为什么要两条腿**(2026-11-28):worker 的出口口径是
「GitHub 各域 + `wb.shiliu153.me` 走**直连**,其余走 mihomo」,这份 `no_proxy` 写在
`/root/start-superagent.sh` 里。原先巡检只有「经代理」一项,而它坑在两个地方:

1. `urllib` 的 `ProxyHandler` 会照着 `no_proxy` 把请求改成直连 —— 探针主机正是
   `api.github.com`,于是「经代理探」**一直在探直连**,死端口也判绿(自测里
   `test_dead_proxy_reports_bad_without_raising` 就是这么在本机红的);
2. 于是**直连那条腿完全没有观测点**:GitHub 直连一断,worker 拉不到通知、派工评论不进队,
   巡检却全绿(2026-11-25 的实际盲区);反过来机场抽风时巡检报红而 worker 其实没事
   (同日 16:15 / 16:30 各一次误报)。

现在两条腿分开报:「经代理」那一支在探针期间临时摘掉 `no_proxy`(见
`_proxy_bypass_disabled`),「直连」那一支用 `ProxyHandler({})` 显式不用代理。
巡检里所有 `gh` 子进程也统一走 `worker_gh_env()`:代理变量指向 mihomo,`no_proxy` 显式写成
worker 的那一份 —— 不再继承「巡检自己是怎么被拉起来的」。

同一条告警里还带一个旁证「轮询心跳 `github-since`」:它每轮结束都会前进,**停在很久以前**
⇒ 轮询 loop 自己停了;**新鲜而游标不动** ⇒ 本来就是闲置。它只做旁证,不参与判定。

**「WSL 继承代理」判的是「继承到的值指向死端口」,不是「有继承值就红」**(2026-11-17 起)。
mirrored 模式下 WSL 的 `autoProxy`(默认开)会把 Windows 的系统代理导进**它派生的每一个进程**
的环境,`wsl -e bash -c 'echo $https_proxy'` 实测就有值(`http://127.0.0.1:7897`)。Clash 开着时
一切正常,Clash 一关那些命令就**静默挂住**:没有报错、没有退出码。所以判据是两层的:① 排除
**worker 自己 export 的那个值**(`start-superagent.sh` 的 `--proxy`,默认 `127.0.0.1:7890`)——
不排除就会在一切正常时天天报红;② 对剩下的值做一次 TCP 建连(3 秒),**通 = 绿但文案写明
「潜伏态」,不通 = 红**,并指向根治动作:`.wslconfig` 加 `autoProxy=false` 后 `wsl --shutdown`
(Windows 侧,仓库改不了)。开关:`--skip-proxy-inherit` 单独跳过;`--skip-egress` 一并跳过
(离线自测只写后者)。

已知局限(不是 bug):systemd timer 拉起的巡检进程**通常看不到**注入值(注入发生在 `wsl.exe`
派生的进程环境里,`/proc/1/environ` 与 `systemctl show-environment` 都是干净的),那时这一项
判绿。它主要在人 / agent 用 `wsl -e bash -c` 跑巡检、以及 worker 会话里生效 —— 正好就是
「会被继承代理坑到」的那两个场景。

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

优先级:`SUPERAGENT_NOTIFY_CMD`(逃生口)→ 统一邮件内核 → 仅落盘 + journal。

- **邮件内核(推荐)**:`MAIL_SMTP_URL="smtps://smtpdm.aliyun.com:465"` + `MAIL_FROM` /
  `MAIL_TO` / `MAIL_USER` / `MAIL_PASS`。**与服务器日报同一个发信账号**,于是收件箱里
  worker 告警与服务器日报来自同一发信人、共用同一份额度(5/分钟、50/天)。
  邮件**不走 http 代理**(mihomo 是 HTTP 代理,SMTP 过不去),`notify.sh` 里显式 `env -u *_proxy`
  的老写法已删掉 —— 内核用 `smtplib` 直连,本来就不吃代理变量。
- **逃生口**:`SUPERAGENT_NOTIFY_CMD`,一条能吃掉 stdin 为正文的任意命令。内核装不上时用它兜。

**主题规范**(`docs/ops/mail.md` 是唯一事实来源):`[chatapp·类别] 对象 — 结论`,三段固定,
类别封闭枚举。worker 巡检固定发 `[chatapp·巡检] worker — <第一个异常项名>`,结论里**不带数字**。

> 2026-11-16 起**删掉了「GitHub issue 评论」通道**(`SUPERAGENT_GH_ISSUE`):issue 是待办不是告警,
> 没人订阅就没人看见,而且类别与结论会被 GitHub 的通知模板抹平。

**去重**:同一种异常(指纹相同)每 6 小时只发一次(`SUPERAGENT_HEALTH_RESEND_SECONDS`),
异常消失时状态自动清空。指纹只含「检查名 + 状态」,**不含任何每轮都会变的数字**。
没有去重就是每 15 分钟一封,人会把告警关掉 —— 那比没有告警更糟。

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
cat /root/.dsh/state/superagent-health/last-alert.md   # 最近一条告警原文(第一行就是主题)
# 安全自愈:看今天自愈了几次、每次结果(告警有 6 小时去重,这里是逐次记录)
tail -n 20 /root/.dsh/state/superagent-health/autoreheal.log
# 开关当前是否打开(为空 = 关);打开/关闭都是改 env 文件里那行
grep -n '^SUPERAGENT_AUTOREHEAL' /root/.dsh/superagent-health.env
# CI 红轨那一项(默认关):先手动跑一轮看判据与指纹对不对
python3 /root/src/chatapp/scripts/superagent_health.py --skip-egress --skip-cursor \
  --ci-red 1 --runs-file /tmp/runs.json      # 用真快照:gh api "repos/shiliu153/chatapp/actions/runs?branch=main&event=push&per_page=100" > /tmp/runs.json
# 「WSL 继承代理」那一项造红:把它指向一个死端口,应当红并指出 autoProxy(不联网)
https_proxy=http://127.0.0.1:1 python3 /root/src/chatapp/scripts/superagent_health.py \
  --skip-cursor --skip-ci-red --skip-enqueue
# 发信配置齐不齐 / 主题长什么样(都不联网、不发信)
python3 /root/src/chatapp/scripts/lib/mail.py check --env-file /root/.dsh/superagent-health.env
python3 /root/src/chatapp/scripts/lib/mail.py subject --category 巡检 --subject worker --verdict 游标停摆
```

退出码:`0` 正常 / `1` 有异常 / `2` 判不出来(按异常处理 —— 判不出来绝不能算正常)。

## 自测

```bash
python -m unittest scripts.test_superagent_health -v     # 纯离线,不联网不碰真库
python -m unittest scripts.test_mail -v                  # 发信内核:主题 / 去重 / 配额 / 失败语义
```

自测里有一条是真事故的回放:用 LIKE 匹配原始 JSON 会把带空格的 `"number": 285` 判成 0 张单,
现在是解析 JSON 取 `mandate.basis.scope.number`。

游标新鲜度那组用例钉的是判错的两个方向:**落后 + 有未读 → 报**,**落后 + 无未读 → 不报**
(闲置),**新鲜 → 不报且根本不取通知**(断言取通知的函数没被调用);另有「通知取不到 ⇒
判不出来(退出码 2)」与「游标落后时心跳新鲜也不能洗白」两条。

**CI 红轨**那组钉三件事:判据与 `l4_intake.red_runs` 完全一致(`cancelled` / `timed_out` /
`startup_failure` 都算红、`skipped` / 还在跑不算红)、**每条红轨一个检查名**(否则新红一条会被
旧红的 6 小时去重吞掉)、形状不对或取不到快照一律算「判不出来」而不是「全绿」。

**WSL 继承代理**那组钉两个方向:**继承值指向死端口 → 红且文案指向 `autoProxy`**,
**只有 worker 自 export 的 7890 → 绿**(否则一切正常时天天报红,人会去关告警)。
另外「活着 → 绿但写明潜伏态」「大写变量也查」「裸 `host:port` 也解析」「畸形值不许静默跳过」
各一条;探针只用本机回环监听套接字与死端口,**不联网**。

**出网两条腿**那组(2026-11-28)钉的是「别量错对象」:`no_proxy` 含探针主机时经代理那一支
**仍必须真的走代理**(对着死端口必须判红 —— 这是原先骗人的那段);直连那一支在
`http_proxy` 指向死端口时照旧成功;死端口上判红;`worker_gh_env` 覆盖掉继承来的 `no_proxy`
并把 `WORKER_NO_PROXY` 里该有的主机逐个点名。靶子是本机回环上的临时 HTTP 服务,**不联网**。

**安全自愈**那组把四道闸逐条钉住(尤其「本该不重启却重启了」这个方向,那会把别人的活连同
会话一起弄丢):停摆 + 无活跃 assignment + worktree 干净 → **回调刚好被调一次**、告警含
「已自动重启」、`autoreheal.log` 落盘;有 `running` / `pending` 会话、worktree 有未提交改动、
worktree 根本不是 git 目录(确认不了)→ **一次都不调**;游标新鲜、总闸没开(`0`/`off`/空)、
距上次自愈不足 20 分钟 → **一次都不调**;重启回调非零退出 → 告警带失败原因且退出码仍是 1。
**自测里绝不真的调 `start-superagent.sh`** —— 回调是注入的假货,只记调用次数。
