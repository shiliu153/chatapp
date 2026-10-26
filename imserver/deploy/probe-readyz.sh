#!/usr/bin/env bash
# readyz 探针:由宝塔计划任务每分钟调用一次(任务名「imserver-readyz-探针」)。
#
# 为什么需要:2026-10-22~26 连接池不校验存活,MySQL 掐掉空闲连接后 readyz 一直 503,
# 挂了 3 天没人发现——只看进程/端口是看不出来的,必须看 readyz(SELECT 1 真连库)。
#
# 判定规则:
#   - 单轮内连查两次(间隔 2s),任一次 200 即视为健康,计数清零;
#   - 连续 2 轮都失败才告警(避免网络抖动误报),同一事件只告警一次,恢复后重新计数;
#   - 告警动作:写日志 + 往 stdout 打 ALERT(宝塔「任务日志」里可见)+ 可选 webhook。
#
# 注意:宝塔的任务包装脚本(/www/server/cron/<md5>)不管本脚本退出码是多少都会返回 0,
# 所以不能靠「退出码 1 → 宝塔推送」来告警,必须自己发。
#
# 可覆盖的环境变量:
#   IM_PROBE_URL      默认 http://127.0.0.1:9101/internal/readyz
#   IM_PROBE_STATE    连续失败计数文件
#   IM_PROBE_LOG      失败日志
#   IM_PROBE_WEBHOOK  可选:企业微信/钉钉群机器人 webhook 地址(文本消息)
set -u

URL="${IM_PROBE_URL:-http://127.0.0.1:9101/internal/readyz}"
STATE="${IM_PROBE_STATE:-/www/server/imserver/probe.state}"
LOG="${IM_PROBE_LOG:-/www/wwwlogs/imserver_probe.log}"
WEBHOOK="${IM_PROBE_WEBHOOK:-}"
TS="$(date '+%F %T')"

# 取 HTTP 状态码;连不上时统一成 000。
code() {
  local c
  c="$(curl -s -o /dev/null -m 5 -w '%{http_code}' "$URL" 2>/dev/null)" || true
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

# 企业微信/钉钉群机器人都接受 {"msgtype":"text","text":{"content":...}}。
notify() {
  local text="$1"
  [ -n "$WEBHOOK" ] || return 0
  curl -s -m 8 -H 'Content-Type: application/json' \
    -d "$(printf '{"msgtype":"text","text":{"content":"%s"}}' "$text")" \
    "$WEBHOOK" >/dev/null 2>&1 || true
}

first="$(code)"
if [ "$first" = "200" ]; then
  printf '0\n' > "$STATE"
  exit 0
fi

sleep 2
second="$(code)"
if [ "$second" = "200" ]; then
  printf '0\n' > "$STATE"
  exit 0
fi

rotate
fails=$(( $(cat "$STATE" 2>/dev/null || echo 0) + 1 ))
printf '%s\n' "$fails" > "$STATE"
printf '%s readyz=%s/%s consecutive_failures=%s\n' "$TS" "$first" "$second" "$fails" >> "$LOG"

if [ "$fails" -lt 2 ]; then
  # 单轮失败先只记录,等下一轮确认。
  exit 0
fi

if [ "$fails" -gt 2 ]; then
  # 同一事件已经告警过:继续记录,但不再重复打扰。
  exit 0
fi

alert="[imserver] readyz 连续 ${fails} 轮失败(HTTP ${first}/${second})。排查:docker logs imserver --since 5m | tail -50;容器内 mysql SELECT 1 是否通。"
printf '%s ALERT %s\n' "$TS" "$alert" | tee -a "$LOG"
notify "$alert"
exit 1
