#!/bin/bash
# MySQL 看门狗:每分钟探活一次,发现 MySQL 不可用就拉起并告警。
#
# 背景(2026-11-01 压测 P0-2):现网 mysqld 由 mysqld_safe 托管,systemd unit 是
# sysv 生成的、Restart=no。同时 kill 掉 mysqld 与 mysqld_safe 后**没有任何东西拉起**,
# 实测永久宕机,只能人工 /etc/init.d/mysqld start。
#
# 用法(cron,每分钟):
#   * * * * * /www/server/ops/mysql-watchdog.sh >> /www/wwwlogs/mysql_watchdog.log 2>&1
#
# 环境变量:
#   MYSQL_CNF        带账号密码的 cnf,默认 /root/.my.im.cnf
#   PROBE_WEBHOOK    企业微信/钉钉机器人地址,留空则只落日志
#   MYSQL_START_CMD  自定义启动命令,默认依次尝试 systemctl / init.d
#   WATCHDOG_STATE   记录上次告警状态的目录,默认 /var/lib/mysql-watchdog
set -u

CNF=${MYSQL_CNF:-/root/.my.im.cnf}
WEBHOOK=${PROBE_WEBHOOK:-}
STATE_DIR=${WATCHDOG_STATE:-/var/lib/mysql-watchdog}
LOCK_FILE=${WATCHDOG_LOCK:-/var/lock/mysql-watchdog.lock}
START_CMD=${MYSQL_START_CMD:-}

mkdir -p "$STATE_DIR" 2>/dev/null || true

now() { date '+%Y-%m-%d %H:%M:%S'; }

log() { echo "[$(now)] $*"; }

# 同一时刻只允许一个实例:上一分钟的恢复动作可能还没结束。
exec 9>"$LOCK_FILE" 2>/dev/null || true
if ! flock -n 9; then
  log "skip: previous run still in progress"
  exit 0
fi

mysql_ok() {
  mysql --defaults-extra-file="$CNF" --connect-timeout=3 -N -e 'SELECT 1' >/dev/null 2>&1
}

notify() {
  local text=$1
  [ -z "$WEBHOOK" ] && return 0
  curl -s -m 5 -H 'Content-Type: application/json' \
    -d "{\"msgtype\":\"text\",\"text\":{\"content\":\"[MySQL看门狗] $text\"}}" \
    "$WEBHOOK" >/dev/null 2>&1 || true
}

if mysql_ok; then
  # 上一次是宕机状态,现在恢复:补一条恢复通知并清状态。
  if [ -f "$STATE_DIR/down" ]; then
    rm -f "$STATE_DIR/down"
    log "recovered"
    notify "$(hostname) MySQL 已恢复(探活 SELECT 1 成功)"
  fi
  exit 0
fi

log "mysql down, attempting restart"

start_mysql() {
  if [ -n "$START_CMD" ]; then
    bash -c "$START_CMD"
    return $?
  fi
  if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files mysqld.service >/dev/null 2>&1; then
    systemctl start mysqld
    return $?
  fi
  if [ -x /etc/init.d/mysqld ]; then
    /etc/init.d/mysqld start
    return $?
  fi
  log "no start method found"
  return 1
}

start_mysql

# 最多等 60 秒:InnoDB 崩溃恢复 + 表空间校验,慢的时候要十几秒。
for _ in $(seq 1 60); do
  if mysql_ok; then
    log "restarted successfully"
    notify "$(hostname) MySQL 曾宕机,看门狗已拉起(耗时 ≤60s)"
    exit 0
  fi
  sleep 1
done

# 拉起失败:每分钟重试,但只告警一次,避免刷屏。
if [ ! -f "$STATE_DIR/down" ]; then
  : > "$STATE_DIR/down"
  log "restart FAILED, alerting"
  notify "$(hostname) MySQL 宕机且自动拉起失败,需要人工介入(/etc/init.d/mysqld start)"
else
  log "still down"
fi
exit 1
