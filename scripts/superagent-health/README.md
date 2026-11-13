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
| worktrees | `work/` 下的目录清单 | 仅供核对,不告警 |

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
systemctl list-timers superagent-health.timer
journalctl -u superagent-health -n 50 --no-pager
cat /root/.dsh/state/superagent-health/last-alert.md   # 最近一条告警原文
```

退出码:`0` 正常 / `1` 有异常 / `2` 判不出来(按异常处理 —— 判不出来绝不能算正常)。

## 自测

```bash
python -m unittest scripts.test_superagent_health -v     # 16 条,纯离线
```

自测里有一条是真事故的回放:用 LIKE 匹配原始 JSON 会把带空格的 `"number": 285` 判成 0 张单,
现在是解析 JSON 取 `mandate.basis.scope.number`。
