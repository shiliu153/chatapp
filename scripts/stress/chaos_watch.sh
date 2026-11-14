#!/bin/bash
# 混沌演练期间的 0.5s 健康采样器:把「谁在什么时候挂了/回来」记成时间线。
# 用法:setsid ./chaos_watch.sh > /tmp/chaos_xxx.log 2>&1 < /dev/null &
# 停止:kill $(pgrep -f "chaos_watch[.]sh" | head -1)
# 注意:pgrep 的 pattern 里用 [.] 是为了不让它匹配到 ssh 自己的命令行。
while true; do
  ts=$(date +%H:%M:%S.%3N)
  a=$(curl -s -m 3 -o /dev/null -w '%{http_code}' http://127.0.0.1:9101/internal/readyz)
  b=$(curl -sk -m 5 -o /dev/null -w '%{http_code}' https://127.0.0.1/api/v1/app/config -H 'Host: chat.shiliu153.cn')
  c=$(docker inspect -f '{{.State.Running}}' imserver 2>/dev/null)
  d=$(pgrep -c gunicorn)
  e=$(systemctl is-active mysqld)
  f=$(pgrep -c mysqld)
  echo "$ts readyz=$a http=$b im_run=$c gunicorn=$d mysql=$e mysqld_pid=$f"
  sleep 0.5
done
