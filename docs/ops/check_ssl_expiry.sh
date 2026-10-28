#!/bin/bash
# SSL 证书到期巡检（部署到服务器 /root/check_ssl_expiry.sh，由 root cron 每天跑一次）
#
# 为什么需要它：certbot 只在「剩余 < 30 天」时续期，如果 ACME 限流、webroot 权限、
# 磁盘满等原因连续失败，30 天后就是全站握手失败 + App 全体掉线，而当前没有任何告警。
# 本脚本把「磁盘证书」和「线上实际下发的证书」都算一遍剩余天数，低于阈值写 WARN。
#
# 用法：
#   /root/check_ssl_expiry.sh              # 默认阈值 20 天
#   WARN_DAYS=30 /root/check_ssl_expiry.sh # 临时收紧
# 退出码：0 = 全部正常；1 = 有证书临期/解析失败/握手失败。
# 日志：/var/log/ssl-expiry.log（后续接群机器人时从这里取）

set -uo pipefail

WARN_DAYS="${WARN_DAYS:-20}"
LOG="${LOG:-/var/log/ssl-expiry.log}"
HOST="${HOST:-chat.shiliu153.cn}"
rc=0

declare -A seen=()

log() { echo "$(date '+%F %T') $*" >> "$LOG"; }

# 1. 磁盘上的证书（宝塔两种目录都扫；同名域名只报一次）
for base in /www/server/panel/vhost/letsencrypt /www/server/panel/vhost/cert; do
    [ -d "$base" ] || continue
    for c in "$base"/*/fullchain.pem; do
        [ -f "$c" ] || continue
        name="$(basename "$(dirname "$c")")"
        if [ -n "${seen[$name]:-}" ]; then
            continue
        fi
        seen[$name]=1
        end="$(openssl x509 -in "$c" -noout -enddate 2>/dev/null | cut -d= -f2)"
        if [ -z "$end" ]; then
            log "ERROR $name 证书无法解析：$c"
            rc=1
            continue
        fi
        days=$(( ( $(date -d "$end" +%s) - $(date +%s) ) / 86400 ))
        if [ "$days" -lt "$WARN_DAYS" ]; then
            log "WARN  $name 剩余 ${days} 天（阈值 ${WARN_DAYS}）end=$end"
            rc=1
        else
            log "OK    $name 剩余 ${days} 天"
        fi
    done
done

# 2. 线上实际下发的证书（防止「磁盘换了证但 nginx 没 reload」）
end="$(echo | openssl s_client -connect "$HOST:443" -servername "$HOST" 2>/dev/null \
    | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)"
if [ -n "$end" ]; then
    days=$(( ( $(date -d "$end" +%s) - $(date +%s) ) / 86400 ))
    log "LIVE  $HOST 线上证书剩余 ${days} 天"
    if [ "$days" -lt "$WARN_DAYS" ]; then
        rc=1
    fi
else
    log "ERROR $HOST 线上 TLS 握手失败"
    rc=1
fi

exit $rc
