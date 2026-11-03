#!/bin/bash
# 全栈同时打崩:gunicorn 主进程 + imserver + mysqld(+mysqld_safe) 一起 kill -9,
# 观察哪些能自己回来、多久、哪些必须人工介入。
set -u
G=$(pgrep -f "127.0.0.1:8000 -w 2" | head -1)
I=$(pgrep -f "^/usr/local/bin/imserver" | head -1)
M=$(pgrep -x mysqld | head -1)
S=$(pgrep -f "^/bin/sh /www/server/mysql/bin/mysqld_safe" | head -1)
echo "targets gunicorn=$G imserver=$I mysqld=$M mysqld_safe=$S"
T0=$(date +%s)
echo "--- 同时 kill -9 $(date +%H:%M:%S) ---"
kill -9 "$G" "$I" "$M" "$S" 2>/dev/null

for t in 3 10 20 30 45 60; do
  sleep_to=$t
  now=$(( $(date +%s) - T0 ))
  [ "$now" -lt "$sleep_to" ] && sleep $(( sleep_to - now ))
  http=$(curl -sk -m 5 -o /dev/null -w '%{http_code}' https://127.0.0.1/api/v1/app/config -H 'Host: chat.shiliu153.cn')
  rz=$(curl -s -m 3 -o /dev/null -w '%{http_code}' http://127.0.0.1:9101/internal/readyz)
  mq=$(pgrep -x mysqld >/dev/null && echo UP || echo DOWN)
  echo "T+$(( $(date +%s) - T0 ))s http=$http im_readyz=$rz mysqld=$mq gunicorn=$(pgrep -c -f '127.0.0.1:8000 -w 2')"
done

echo "--- 人工拉起 mysqld $(date +%H:%M:%S) ---"
T1=$(date +%s)
/etc/init.d/mysqld start >/tmp/mysql_start2.log 2>&1
until mysql --defaults-extra-file=/root/.my.im.cnf -N -e 'SELECT 1' >/dev/null 2>&1; do sleep 1; done
echo "db_up_after=$(( $(date +%s) - T1 ))s"
until [ "$(curl -s -m 3 -o /dev/null -w '%{http_code}' http://127.0.0.1:9101/internal/readyz)" = "200" ]; do sleep 1; done
echo "im_readyz_back=$(date +%H:%M:%S)"
echo "full_recovery=$(( $(date +%s) - T0 ))s"
