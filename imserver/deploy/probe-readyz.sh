#!/usr/bin/env bash
# 探针:由宝塔计划任务每分钟调用一次(任务名「imserver-readyz-探针」)。
#
# 为什么需要:2026-10-22~26 连接池不校验存活,MySQL 掐掉空闲连接后 readyz 一直 503,
# 挂了 3 天没人发现——只看进程/端口是看不出来的,必须看 readyz(SELECT 1 真连库)。
#
# 2026-11-05(E-4 ②)改了两件事:
#   1. **粒度从「每分钟 2 次、连续 2 分钟才告警」降到「30 秒 2 次」**。旧的判定实测漏报过
#      一次 90 秒宕机(只记了 1 次失败、没到 2 轮);现在单次故障 30~35 秒内就能邮件触达,
#      与 Prometheus 那条通道(抓取 15s + 规则 for 30s)互为兜底。
#   2. **通知通道换成邮件**,走每天 22:00 服务器日报那条链路(/opt/notify → 阿里云邮件推送)。
#      2026-11-05 用户决定不再接群机器人,PROM_PROBE_WEBHOOK 已废弃。
#
# 判定规则:
#   - 每轮先查所有目标(快),全健康就直接退出(常态下进程只活几十毫秒);
#   - 有目标失败则 sleep 30 再复测,复测成功即视为抖动、计数清零;
#   - 两次都失败 → 计数 +1,计数到 2 就发一封邮件;同一事件只发一封(计数继续涨但静默);
#   - 目标清单默认「imserver readyz + Django health」,覆盖「进程没了」和「DB/Redis 连不上」两类。
#
# 注意:宝塔的任务包装脚本(/www/server/cron/<md5>)不管本脚本退出码是多少都会返回 0,
# 所以不能靠「退出码 1 → 宝塔推送」来告警,必须自己发。
#
# 可覆盖的环境变量(通常写在 /www/server/imserver/probe.env):
#   IM_PROBE_TARGETS   空格分隔的 name=url 列表
#   IM_PROBE_STATE     失败计数文件前缀(每个目标一个后缀)
#   IM_PROBE_LOG       失败日志
#   IM_PROBE_GAP       两次复测之间的间隔秒数,默认 30
#   IM_PROBE_NOTIFY_BIN 默认 /opt/notify/bin/notify
#   IM_PROBE_NOTIFY_CONFIG 默认 /etc/notify/alerts.ini
#   IM_PROBE_ENV       环境文件路径,默认 /www/server/imserver/probe.env
set -u

TARGETS="${IM_PROBE_TARGETS:-im=http://127.0.0.1:9101/internal/readyz api=http://127.0.0.1:8000/api/v1/health}"
STATE="${IM_PROBE_STATE:-/www/server/imserver/probe.state}"
LOG="${IM_PROBE_LOG:-/www/wwwlogs/imserver_probe.log}"
GAP="${IM_PROBE_GAP:-30}"
NOTIFY_BIN="${IM_PROBE_NOTIFY_BIN:-/opt/notify/bin/notify}"
NOTIFY_CONFIG="${IM_PROBE_NOTIFY_CONFIG:-/etc/notify/alerts.ini}"
TS="$(date '+%F %T')"

# 把 webhook 之类的配置放独立文件(600),不要写进计划任务的命令里——
# 面板的任务记录在 sqlite 里,面板 UI 和备份都能看到。
ENV_FILE="${IM_PROBE_ENV:-/www/server/imserver/probe.env}"
if [ -r "$ENV_FILE" ]; then
  # shellcheck disable=SC1090
  . "$ENV_FILE"
fi

# 取 HTTP 状态码;连不上时统一成 000。
code() {
  local c
  c="$(curl -s -o /dev/null -m 5 -w '%{http_code}' "$1" 2>/dev/null)" || true
  [ -n "$c" ] || c=000
  printf '%s' "$c"
}

# 日志超过 1MB 就只留最后 500 行,避免长期运行把磁盘写满。
rotate() {
  local size
  size="$(stat -c%s "$LOG" 2>/dev/null || echo 0)"
  if [ "$size" -gt 1048576 ]; then
    tail -n 500 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG"
  fi
}

# 发一封告警邮件;notify 不存在(比如这台机器没装、或路径变了)时只落日志,不让探针失败。
#
# 参数:
#   $1 标题后缀(如「imserver readyz」)
#   $2 正文
#   $3 去重键
notify_email() {
  local subject="$1" body="$2" key="$3"
  if [ ! -x "$NOTIFY_BIN" ]; then
    printf '%s NOTIFY_SKIPPED %s (找不到 %s)\n' "$TS" "$key" "$NOTIFY_BIN" >> "$LOG"
    return 0
  fi
  printf '%s\n' "$body" | NOTIFY_CONFIG="$NOTIFY_CONFIG" "$NOTIFY_BIN" send \
      --title "[告警] $subject" --body-file - --level error \
      --dedup-key "$key" --dedup-window 60 >> "$LOG" 2>&1 || true
}

# 读某个目标当前的连续失败次数。
fails_of() {
  cat "$STATE.$1" 2>/dev/null || echo 0
}

# 写某个目标的连续失败次数。
set_fails() {
  printf '%s\n' "$2" > "$STATE.$1" 2>/dev/null || true
}

# 第一轮:把所有目标都查一遍,任一失败就先记下来,稍后复测。
bad=""
for target in $TARGETS; do
  name="${target%%=*}"
  url="${target#*=}"
  first="$(code "$url")"
  if [ "$first" != "200" ]; then
    bad="$bad $name"
  fi
done

if [ -z "$bad" ]; then
  # 全健康:清零所有计数(包括本脚本不认识的历史目标文件)。
  for target in $TARGETS; do
    set_fails "${target%%=*}" 0
  done
  exit 0
fi

# 第二轮:只复测失败的目标,间隔 GAP 秒。抖动(两次里有一次 200)不算故障。
sleep "$GAP"
for target in $TARGETS; do
  name="${target%%=*}"
  case " $bad " in *" $name "*) ;; *) set_fails "$name" 0; continue ;; esac
  url="${target#*=}"
  second="$(code "$url")"
  if [ "$second" = "200" ]; then
    set_fails "$name" 0
    rotate
    printf '%s RECOVERED %s first_failed_then_ok\n' "$TS" "$name" >> "$LOG"
    continue
  fi
  rotate
  fails=$(( $(fails_of "$name") + 1 ))
  set_fails "$name" "$fails"
  printf '%s %s consecutive_failures=%s last_two=%s\n' "$TS" "$name" "$fails" "$second" >> "$LOG"
  if [ "$fails" -ne 2 ]; then
    # 第 1 次先只记录;第 3 次起说明同一事件已经通知过,不再重复打扰。
    continue
  fi
  body="$name 连续 2 次探活失败(间隔 ${GAP}s,最后一次 HTTP $second)。
目标: $url
排查: docker logs imserver --since 5m | tail -50;容器内 mysql SELECT 1 是否通;
      Django 侧: curl -s 127.0.0.1:8000/api/v1/readyz | head -c 200
处置顺序见 docs/ops/runbook.md §3。"
  printf '%s ALERT %s\n' "$TS" "$name" | tee -a "$LOG"
  notify_email "$name 探活失败" "$body" "probe:$name:$TS"
done
exit 0
