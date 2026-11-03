#!/bin/bash
# 定向 OOM:把 mysqld 的 oom_score_adj 调到 1000,再用内存压力逼内核杀它,
# 观察 mysqld_safe 是否把它拉回来、拉回来之后还能不能用。
set -u
MYSQL_PID=$(pgrep -x mysqld | head -1)
echo "mysqld pid=$MYSQL_PID"
echo 1000 > "/proc/$MYSQL_PID/oom_score_adj"
echo "oom_score_adj=$(cat /proc/$MYSQL_PID/oom_score_adj)"

echo "--- 开始吃内存 $(date +%H:%M:%S) ---"
setsid /www/wwwroot/chatapp-venv/bin/python /root/oom.py > /tmp/oom_out2.log 2>&1 < /dev/null &
ALLOC=$!
for i in $(seq 1 40); do
  sleep 2
  if ! kill -0 "$MYSQL_PID" 2>/dev/null; then
    echo "[$i] mysqld 已死 $(date +%H:%M:%S)"
    break
  fi
done
sleep 6
echo "--- 6s 后 ---"
pgrep -x mysqld >/dev/null && echo "mysqld=UP pid=$(pgrep -x mysqld | head -1)" || echo "mysqld=DOWN"
echo "--- OOM 记录 ---"
dmesg -T 2>/dev/null | grep -iE "killed process" | tail -4
echo "--- 数据库可用性 ---"
for i in 1 2 3 4 5 6; do
  if mysql --defaults-extra-file=/root/.my.im.cnf -N -e 'SELECT 1' >/dev/null 2>&1; then
    echo "db_ok at $(date +%H:%M:%S)"; break
  fi
  echo "db_fail at $(date +%H:%M:%S)"; sleep 3
done
echo "--- imserver ---"
curl -s -m 3 -o /dev/null -w "readyz=%{http_code}\n" http://127.0.0.1:9101/internal/readyz
kill "$ALLOC" 2>/dev/null
echo "--- 收尾:恢复 oom_score_adj ---"
NEW=$(pgrep -x mysqld | head -1)
[ -n "$NEW" ] && echo 0 > "/proc/$NEW/oom_score_adj" && echo "restored"
