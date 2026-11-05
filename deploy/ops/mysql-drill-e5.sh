#!/bin/bash
# E-5 演练:MySQL 双杀(kill -9 mysqld + mysqld_safe),验证「看门狗自动拉起 + 告警到达」。
#
# 背景(docs/backlog/2026-11-03-todo.md E-5 + docs/ops/runbook.md §2.2):
# 2026-11-01 压测发现现网 mysqld 由 mysqld_safe 托管、systemd unit 是 sysv 生成的
# Restart=no,同时 kill 掉 mysqld 与 mysqld_safe 后**没有任何东西拉起**,数据库永久宕机。
# 2026-11-03 上线了「每分钟 cron + mysql-watchdog.sh」兜底,但这条兜底只有安装步骤、
# 没有**实测记录**(MTTR 多少、告警多久到)。本脚本就是那次演练的可复现载体。
#
# 会短暂中断生产 DB(MySQL 库 chatapp + chatapp_im 同实例),只在低峰窗口跑。
#
# 用法(服务器上,root):
#   CONFIRM=1 bash /www/server/ops/mysql-drill-e5.sh
#   # 只做前置检查与快照、不杀进程:
#   DRY_RUN=1 bash /www/server/ops/mysql-drill-e5.sh
#
# 环境变量:
#   CONFIRM=1        真正的演练开关(缺省只做前置检查,防止误跑)
#   DRY_RUN=1        只做前置检查 + 数据库快照,不杀进程
#   APP_DIR          Django 项目根,默认 /www/wwwroot/chatapp/chatapp(读 .env 取库名/账号)
#   MYSQL_CNF        探活 cnf,默认 /root/.my.im.cnf
#   IM_ENV           imserver 环境文件,默认 /www/server/imserver/imserver.env(取 IM 库凭证)
#   MYSQL_START_CMD  人工兜底启动命令,默认 /etc/init.d/mysqld start
#   HARD_TIMEOUT     看门狗未拉起时,脚本自己接手的等待秒数,默认 120
#   OUT_DIR          产物目录,默认 /root/e5-drill-<时间戳>
#
# 产物:$OUT_DIR/{drill.log,samples.log,counts-before.txt,counts-after.txt,summary.txt,pre-drill-*.sql.gz}
# 判读:summary.txt 里有 T0/T1/T2/检测延迟/MTTR/告警到达,以及「恢复后数据行数是否一致」。
set -u

APP_DIR=${APP_DIR:-/www/wwwroot/chatapp/chatapp}
CNF=${MYSQL_CNF:-/root/.my.im.cnf}
IM_ENV=${IM_ENV:-/www/server/imserver/imserver.env}
WD_LOG=${WD_LOG:-/www/wwwlogs/mysql_watchdog.log}
WD_SCRIPT=${WD_SCRIPT:-/www/server/ops/mysql-watchdog.sh}
START_CMD=${MYSQL_START_CMD:-/etc/init.d/mysqld start}
NOTIFY_BIN=${NOTIFY_BIN:-/opt/notify/bin/notify}
HARD_TIMEOUT=${HARD_TIMEOUT:-120}
CONFIRM=${CONFIRM:-0}
DRY_RUN=${DRY_RUN:-0}
OUT_DIR=${OUT_DIR:-/root/e5-drill-$(date +%Y%m%d-%H%M%S)}
LOCK_FILE=/var/lock/mysql-drill.lock

mkdir -p "$OUT_DIR" || exit 2

log() { printf '[%s] %s\n' "$(date '+%F %T.%3N')" "$*" | tee -a "$OUT_DIR/drill.log"; }
sect() { log "===== $* ====="; }
now() { date +%s.%N; }
mysql_ok() { mysql --defaults-extra-file="$CNF" --connect-timeout=2 -N -e 'SELECT 1' >/dev/null 2>&1; }
# Django 在后面挂 SECURE_SSL_REDIRECT,本机 http 会被 301 掉(见 runbook §1),故带 X-Forwarded-Proto。
http_code() { curl -s -o /dev/null -m 3 -H 'X-Forwarded-Proto: https' -w '%{http_code}' "$1" 2>/dev/null || echo 000; }

# ---------- 0. 前置闸门 ----------
[ "$(id -u)" = 0 ] || { echo "必须 root 运行"; exit 2; }

exec 8>"$LOCK_FILE" 2>/dev/null || true
if ! flock -n 8; then echo "另一轮演练正在进行($LOCK_FILE 被占用)"; exit 2; fi

sect "前置检查"
AVAIL_KB=$(df -Pk / | awk 'NR==2 {print $4}')
log "磁盘可用 ${AVAIL_KB}KB"
[ "$AVAIL_KB" -gt 1048576 ] || { log "磁盘可用 <1GB,拒绝演练"; exit 2; }

[ -f "$APP_DIR/.env" ] || { log "找不到 $APP_DIR/.env"; exit 2; }
APP_DB=$(grep -m1 '^DB_NAME=' "$APP_DIR/.env" | cut -d= -f2 | tr -d '"'"'"' ')
APP_DB=${APP_DB:-chatapp}
log "应用库 = ${APP_DB}"

mysql_ok || { log "演练前 MySQL 就不可用,先修好再来"; exit 2; }
log "演练前探活正常"

pgrep -x mysqld >/dev/null || { log "没有 mysqld 进程,异常退出"; exit 2; }
log "mysqld pid = $(pgrep -x mysqld | tr '\n' ' ')"
log "mysqld_safe pid = $(pgrep -f mysqld_safe | tr '\n' ' ')"

if [ -f "$WD_SCRIPT" ]; then
  log "看门狗脚本 md5 = $(md5sum "$WD_SCRIPT" | awk '{print $1}')"
else
  log "警告:找不到看门狗脚本 $WD_SCRIPT"
fi
log "cron 条目 = $(grep -h mysql-watchdog /etc/cron.d/mysql-watchdog 2>/dev/null | head -1)"
log "看门狗日志行数(演练前)= $(wc -l < "$WD_LOG" 2>/dev/null || echo 0)"
log "看门狗状态文件 = $(ls -1 /var/lib/mysql-watchdog 2>/dev/null | tr '\n' ' ')(空 = 之前是健康态)"

# 数据库快照:行数基线 + 一份 dump(演练前保险,不是主备份)。
sect "数据库快照"
snapshot_counts() {
  local out=$1 t c
  : > "$out"
  mysql --defaults-extra-file="$CNF" -N -e \
    "SELECT table_name FROM information_schema.tables WHERE table_schema='${APP_DB}' AND table_type='BASE TABLE' ORDER BY 1" |
  while read -r t; do
    c=$(mysql --defaults-extra-file="$CNF" -N -e "SELECT COUNT(*) FROM \`${t}\`" "$APP_DB" 2>/dev/null || echo ERR)
    printf '%s %s\n' "$t" "$c" >> "$out"
  done
  log "行数基线 $out:$(wc -l < "$out") 张表"
}
snapshot_counts "$OUT_DIR/counts-before.txt"

# 与 chatapp-backup.sh 同一套参数:--single-transaction 不锁表、--no-tablespaces 免 PROCESS 权限。
dump_db() {
  local user=$1 pass=$2 host=$3 port=$4 db=$5 out=$6
  if ! MYSQL_PWD="$pass" mysqldump --host="$host" --port="$port" --user="$user" \
        --single-transaction --quick --routines --triggers --no-tablespaces \
        --set-gtid-purged=OFF --default-character-set=utf8mb4 --hex-blob \
        "$db" 2>"$out.err" | gzip >"$out"; then
    cat "$out.err" >>"$OUT_DIR/drill.log" 2>/dev/null || true
    return 1
  fi
  [ -s "$out.err" ] && log "  mysqldump 警告:$(tr '\n' ' ' <"$out.err")"
  rm -f "$out.err"
  gzip -t "$out" || return 1
  zcat "$out" | tail -n 1 | grep -q '^-- Dump completed' || return 1
  log "  ok $(du -h "$out" | cut -f1),建表语句 $(zcat "$out" | grep -c '^CREATE TABLE' || true) 条"
}

DB_USER=$(grep -m1 '^DB_USER=' "$APP_DIR/.env" | cut -d= -f2 | tr -d '"'"'"' ')
DB_PASS=$(grep -m1 '^DB_PASSWORD=' "$APP_DIR/.env" | cut -d= -f2 | tr -d '"'"'"' ')
DB_HOST=$(grep -m1 '^DB_HOST=' "$APP_DIR/.env" | cut -d= -f2 | tr -d '"'"'"' '); DB_HOST=${DB_HOST:-127.0.0.1}
DB_PORT=$(grep -m1 '^DB_PORT=' "$APP_DIR/.env" | cut -d= -f2 | tr -d '"'"'"' '); DB_PORT=${DB_PORT:-3306}
log "dump 应用库 $APP_DB"
if ! dump_db "$DB_USER" "$DB_PASS" "$DB_HOST" "$DB_PORT" "$APP_DB" "$OUT_DIR/pre-drill-${APP_DB}.sql.gz"; then
  log "演练前 dump 失败,拒绝继续(没有保险不动生产库)"; exit 2
fi

# IM 库与 Django 同实例(127.0.0.1:3306),一并 dump:双杀会把它一起带走。
if [ -r "$IM_ENV" ]; then
  DSN=$(grep -m1 '^IM_MYSQL_DSN=' "$IM_ENV" | cut -d= -f2-)
  IM_USER=$(printf '%s' "$DSN" | sed -E 's#^[a-z]+://([^:@]+).*#\1#')
  IM_PASS=$(printf '%s' "$DSN" | sed -E 's#^[a-z]+://[^:@]+:([^@]*)@.*#\1#')
  IM_DB=$(printf '%s' "$DSN" | sed -E 's#^.*/([^/?]+)[?]?.*#\1#' | cut -d'?' -f1)
  log "dump IM 库 $IM_DB"
  if ! dump_db "$IM_USER" "$IM_PASS" 127.0.0.1 3306 "$IM_DB" "$OUT_DIR/pre-drill-${IM_DB}.sql.gz"; then
    log "警告:IM 库 dump 失败(靠 03:20 全量备份兜底)"
  fi
fi

if [ "$DRY_RUN" = 1 ]; then
  sect "DRY_RUN=1,前置检查与快照完成,未杀进程"
  log "产物目录:$OUT_DIR"
  exit 0
fi
if [ "$CONFIRM" != 1 ]; then
  sect "缺少 CONFIRM=1,只做了前置检查,未杀进程"
  log "确认在低峰窗口后执行:CONFIRM=1 bash $0"
  exit 3
fi

# ---------- 1. 采样器(1s 一次,记录用户可见影响) ----------
sect "启动采样器(1s 粒度)"
WD_BEFORE=$(wc -l < "$WD_LOG" 2>/dev/null || echo 0)
(
  END=$(( $(date +%s) + HARD_TIMEOUT + 120 ))
  while [ "$(date +%s)" -lt "$END" ]; do
    M=DOWN; mysql_ok && M=UP
    printf '%s mysql=%s django_readyz=%s im_readyz=%s\n' \
      "$(now)" "$M" "$(http_code http://127.0.0.1:8000/api/v1/readyz)" \
      "$(http_code http://127.0.0.1:9101/internal/readyz)" >> "$OUT_DIR/samples.log"
    sleep 1
  done
) 8>&- &
SAMPLER_PID=$!
trap 'kill "$SAMPLER_PID" 2>/dev/null' EXIT

# ---------- 2. 双杀 ----------
sect "T0 双杀 mysqld + mysqld_safe"
MYSQLD_PIDS=$(pgrep -x mysqld | tr '\n' ' ')
SAFE_PIDS=$(pgrep -f 'mysqld_safe' | grep -v "^$$\$" | tr '\n' ' ')
T0=$(now)
log "T0=$T0  kill -9 mysqld=[$MYSQLD_PIDS] mysqld_safe=[$SAFE_PIDS]"
# shellcheck disable=SC2086
kill -9 $MYSQLD_PIDS $SAFE_PIDS 2>>"$OUT_DIR/drill.log"

sleep 3
if pgrep -x mysqld >/dev/null; then
  log "注意:3 秒后 mysqld 已重新出现(pid $(pgrep -x mysqld | tr '\n' ' ')),可能是 mysqld_safe 没被杀死"
else
  log "确认 mysqld 与 mysqld_safe 都已消失,静待看门狗"
fi

# ---------- 3. 等看门狗拉起 ----------
sect "等待恢复"
T2=""
ESCALATED=0
while :; do
  if mysql_ok; then T2=$(now); break; fi
  EL=$(awk -v a="$(now)" -v b="$T0" 'BEGIN{printf "%.1f", a-b}')
  if [ "$ESCALATED" = 0 ] && awk -v e="$EL" -v h="$HARD_TIMEOUT" 'BEGIN{exit !(e>h)}'; then
    ESCALATED=1
    log "看门狗 ${HARD_TIMEOUT}s 内没拉起,脚本接手人工兜底:$START_CMD"
    # 8>&- :子进程别继承演练锁 fd(否则拉起的 mysqld 会永久占着它,下一轮演练直接被拒)
    bash -c "$START_CMD" 8>&- >> "$OUT_DIR/drill.log" 2>&1 || log "人工兜底命令返回非 0"
  fi
  if awk -v e="$EL" -v h="$((HARD_TIMEOUT + 90))" 'BEGIN{exit !(e>h)}'; then
    log "超过 $((HARD_TIMEOUT + 90))s 仍未恢复,放弃等待(需要人工处理)"
    break
  fi
  sleep 0.5
done

# ---------- 4. 数据与指标 ----------
sect "恢复后核对"
if [ -n "$T2" ]; then
  MTTR=$(awk -v a="$T2" -v b="$T0" 'BEGIN{printf "%.1f", a-b}')
  log "T2=$T2  MySQL 可达,杀到恢复 ${MTTR}s"
else
  MTTR="N/A"
  log "T2=N/A 直到放弃等待仍未恢复"
fi

snapshot_counts "$OUT_DIR/counts-after.txt"
if diff -q "$OUT_DIR/counts-before.txt" "$OUT_DIR/counts-after.txt" >/dev/null; then
  ROWS="一致"
  log "行数核对:一致"
else
  ROWS="不一致(见 diff)"
  log "行数核对:不一致"
  diff -u "$OUT_DIR/counts-before.txt" "$OUT_DIR/counts-after.txt" >> "$OUT_DIR/drill.log" || true
fi

DETECT="N/A"; T1="N/A"
WD_NEW=$(tail -n +"$((WD_BEFORE + 1))" "$WD_LOG" 2>/dev/null)
if printf '%s' "$WD_NEW" | grep -q 'down, attempting restart'; then
  L=$(printf '%s\n' "$WD_NEW" | grep -m1 'down, attempting restart')
  TS=$(printf '%s' "$L" | sed -E 's/^\[([0-9-]+ [0-9:]+)\].*/\1/')
  T1=$(date -d "$TS" +%s 2>/dev/null || echo N/A)
  if [ "$T1" != N/A ]; then
    DETECT=$(awk -v a="$T1" -v b="$T0" 'BEGIN{printf "%.0f", a-b}')
    log "T1 看门狗发现宕机 = $TS(检测延迟 ${DETECT}s)"
  fi
else
  log "看门狗日志里没有新的 restart 记录(可能被 flock 跳过或没跑到)"
fi
log "看门狗新增日志:"; printf '%s\n' "$WD_NEW" >> "$OUT_DIR/drill.log"

ALERTS=$(curl -s -m 5 http://127.0.0.1:9093/api/v2/alerts 2>/dev/null | head -c 4000)
printf '%s\n' "$ALERTS" > "$OUT_DIR/alertmanager-alerts.json"
FIRING=$(printf '%s' "$ALERTS" | grep -o '"alertname":"[^"]*"' | sort -u | tr '\n' ' ')
log "Alertmanager 当前告警:${FIRING:-无}"
log "mysql_up 指标:$(curl -s -m 5 'http://127.0.0.1:9090/api/v1/query?query=mysql_up' | head -c 300)"
log "邮件发送记录(最近 5 条):"
"$NOTIFY_BIN" log -n 5 2>&1 | tail -5 | while read -r line; do log "  $line"; done

sect "服务状态"
log "mysqld: $(pgrep -x mysqld | tr '\n' ' ')($( /etc/init.d/mysqld status 2>&1 | head -2 | tr '\n' ' '))"
log "Django readyz = $(http_code http://127.0.0.1:8000/api/v1/readyz)"
log "imserver readyz = $(http_code http://127.0.0.1:9101/internal/readyz)"
log "gunicorn 进程数 = $(ps -ef | grep -c '[g]unicorn config.wsgi:application')"
log "imserver 容器: $(docker inspect -f '{{.State.Status}}' imserver 2>/dev/null)"
log "错误日志末尾(crash recovery 证据):"
tail -5 /www/server/data/*.err 2>/dev/null | while read -r line; do log "  $line"; done

# 采样汇总:DOWN 区间
if [ -s "$OUT_DIR/samples.log" ]; then
  DOWN_N=$(grep -c 'mysql=DOWN' "$OUT_DIR/samples.log")
  log "采样中 MySQL 不可达样本数 = ${DOWN_N}"
fi

# ---------- 5. summary ----------
{
  echo "E-5 MySQL 双杀演练 summary"
  echo "时间:$(date '+%F %T %Z')  主机:$(hostname)"
  echo "T0(杀)=$(date -d "@${T0%.*}" '+%F %T' 2>/dev/null || echo "$T0")"
  echo "检测延迟(T1-T0)=${DETECT}s"
  echo "MTTR(T2-T0)=${MTTR}s"
  echo "告警(Alertmanager 抓到的规则)=${FIRING:-无}"
  echo "数据行数核对=${ROWS}"
  echo "产物目录=$OUT_DIR"
} | tee "$OUT_DIR/summary.txt" | while read -r line; do log "$line"; done

sect "演练结束,产物在 $OUT_DIR"
