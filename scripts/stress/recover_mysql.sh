#!/bin/bash
# 数据库宕机期间的用户侧表现 + 手动恢复耗时测量
TOK="$1"
echo "=== DB 宕机期间 ==="
curl -sk -m 10 -o /tmp/dbdown.json -w 'users_me code=%{http_code} time=%{time_total}\n' \
  https://127.0.0.1/api/v1/users/me -H 'Host: chat.shiliu153.cn' -H "Authorization: Bearer $TOK"
head -c 200 /tmp/dbdown.json; echo
curl -sk -m 10 -o /dev/null -w 'app_config code=%{http_code}\n' \
  https://127.0.0.1/api/v1/app/config -H 'Host: chat.shiliu153.cn'

echo "=== 手动拉起 mysqld at $(date +%H:%M:%S.%3N) ==="
T0=$(date +%s.%N)
/etc/init.d/mysqld start >/tmp/mysql_start.log 2>&1
until mysql --defaults-extra-file=/root/.my.im.cnf -N -e 'SELECT 1' >/dev/null 2>&1; do sleep 0.5; done
T1=$(date +%s.%N)
echo "mysql_ready_in=$(echo "$T1 - $T0" | awk '{printf "%.1f", $1-$3}')s"

until curl -s -m 3 -o /dev/null -w '%{http_code}' http://127.0.0.1:9101/internal/readyz | grep -q 200; do sleep 0.5; done
echo "imserver_readyz_back_at=$(date +%H:%M:%S.%3N)"

until curl -sk -m 10 -o /dev/null -w '%{http_code}' https://127.0.0.1/api/v1/users/me \
  -H 'Host: chat.shiliu153.cn' -H "Authorization: Bearer $TOK" | grep -q 200; do sleep 0.5; done
echo "http_users_me_back_at=$(date +%H:%M:%S.%3N)"
