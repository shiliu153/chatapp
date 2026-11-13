#!/usr/bin/env bash
# AWS 双机拓扑的「一键重建 / 自检 / 拆除」。
#
# 背景:这套环境在安全组放行内网业务端口之前,靠两条 SSH 隧道把两台机器缝起来。
# 隧道是手工敲出来的,断了之后要重新推理哪条连哪、目标 IP 是什么 —— 这个脚本把那套
# 知识固化下来,并且把我踩过的坑写进代码:
#
#   * **不要用 `pkill -f "<端口>"` 清隧道** —— 远端 shell 的命令行里含同样的字符串,
#     会把自己这条 ssh 会话杀掉(表现为「无输出 + 退出码 1」)。这里一律用 `fuser -k`。
#   * 容器 IP 在 `docker compose up --force-recreate` 之后会变,所以每次 apply 都重新
#     `docker inspect` 发现,不写死。
#   * APP 上 `chaoxing-web` 占着 127.0.0.1:8000,所以 chatapp 的 Django 副本用 18080。
#   * 两台都有 ufw(INPUT 策略 DROP),隧道端口必须按**网段**放行,否则表现为「连接超时」
#     而不是「拒绝」,极易误判成网络不通。
#
# 用法(在 EDGE 节点上跑):
#   bash topology.sh verify     # 只检查,不动任何东西;任一环节失败退出码 1
#   bash topology.sh apply      # 幂等重建两条隧道 + ufw 规则 + 重载 nginx
#   bash topology.sh teardown   # 摘掉所有隧道(不动容器)
set -uo pipefail

EDGE_PRIVATE="172.31.14.4"
APP_PRIVATE="172.31.35.181"
APP_KEY="$HOME/.ssh/id_ed25519_aws2aws"
APP_DIR="/opt/chatapp-app"
EDGE_DIR="/opt/chatapp-edge"

# 隧道端口(两端约定,改动要同步 nginx 的 upstream)
APP_DB_PORT=13306        # APP -> EDGE 的 MySQL
APP_REDIS_PORT=16379     # APP -> EDGE 的 Redis
APP_IM_WS_PORT=19100     # APP -> EDGE 的 imserver WS
APP_IM_HTTP_PORT=19101   # APP -> EDGE 的 imserver HTTP
EDGE_WEB_PORT=18000      # EDGE -> APP 的 Django
EDGE_IM_WS_PORT=19100    # EDGE -> APP 的 imserver WS
EDGE_IM_HTTP_PORT=19101  # EDGE -> APP 的 imserver HTTP

COMPOSE="sudo docker compose -f docker-compose.yml -f compose.edge.override.yml"

log()  { printf '\033[34m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[32m  ✓\033[0m %s\n' "$*"; }
bad()  { printf '\033[31m  ✗\033[0m %s\n' "$*"; }
warn() { printf '\033[33m  !\033[0m %s\n' "$*"; }

on_app() { ssh -i "$APP_KEY" -o StrictHostKeyChecking=no -o ConnectTimeout=15 \
              ubuntu@"$APP_PRIVATE" "$@"; }

# --- 端口探测 ---------------------------------------------------------------
# 用 bash 的 /dev/tcp 探 TCP,不依赖 curl/nc。
probe_port() {
  local host=$1 port=$2
  timeout 5 bash -c "exec 3<>/dev/tcp/$host/$port" 2>/dev/null
}

probe_http() {
  local url=$1
  curl -sS -m 8 -o /dev/null -w '%{http_code}' "$url" 2>/dev/null || echo "000"
}

# --- apply: 发现容器 IP ------------------------------------------------------
discover_edge_ips() {
  MYSQL_IP=$(sudo docker inspect chatapp-mysql-1 \
    --format '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' | awk '{print $1}')
  REDIS_IP=$(sudo docker inspect chatapp-redis-1 \
    --format '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' | awk '{print $1}')
  IMSERVER_IP=$(sudo docker inspect chatapp-imserver-1 \
    --format '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' | awk '{print $1}')
  if [ -z "$MYSQL_IP" ] || [ -z "$REDIS_IP" ] || [ -z "$IMSERVER_IP" ]; then
    bad "找不到 EDGE 容器 IP(mysql=$MYSQL_IP redis=$REDIS_IP imserver=$IMSERVER_IP)"
    return 1
  fi
  ok "EDGE 容器 IP: mysql=$MYSQL_IP redis=$REDIS_IP imserver=$IMSERVER_IP"
}

# 起一条隧道;先按端口清掉旧的(用 fuser,不用 pkill —— 见文件头说明)。
restart_tunnel() {
  local host=$1; shift
  local ports=("$@")
  if [ "$host" = "app" ]; then
    on_app "for p in ${ports[*]}; do sudo fuser -k \$p/tcp >/dev/null 2>&1; done; sleep 1"
  else
    for p in "${ports[@]}"; do sudo fuser -k "$p/tcp" >/dev/null 2>&1; done
    sleep 1
  fi
}

apply_app_tunnels() {
  log "APP -> EDGE 隧道(数据层 + IM 内部接口)"
  restart_tunnel app "$APP_DB_PORT" "$APP_REDIS_PORT" "$APP_IM_WS_PORT" "$APP_IM_HTTP_PORT"
  on_app "ssh -f -N -o StrictHostKeyChecking=no -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes \
    -L 0.0.0.0:$APP_DB_PORT:$MYSQL_IP:3306 \
    -L 0.0.0.0:$APP_REDIS_PORT:$REDIS_IP:6379 \
    -L 0.0.0.0:$APP_IM_WS_PORT:$IMSERVER_IP:9100 \
    -L 0.0.0.0:$APP_IM_HTTP_PORT:$IMSERVER_IP:9101 \
    -i ~/.ssh/id_ed25519_app2edge ubuntu@$EDGE_PRIVATE" \
    && ok "已建立" || { bad "建立失败"; return 1; }

  # ufw:容器的来源网段是它自己的 compose 网段(实测 172.19.0.0/16)
  on_app "for p in $APP_DB_PORT $APP_REDIS_PORT $APP_IM_WS_PORT $APP_IM_HTTP_PORT; do
      sudo ufw allow from 172.19.0.0/16 to any port \$p proto tcp comment 'chatapp tunnel' >/dev/null 2>&1
    done" && ok "ufw 规则已就位"
}

apply_edge_tunnels() {
  log "EDGE -> APP 隧道(Django 副本 + imserver 副本)"
  restart_tunnel edge "$EDGE_WEB_PORT" "$EDGE_IM_WS_PORT" "$EDGE_IM_HTTP_PORT"
  ssh -f -N -o StrictHostKeyChecking=no -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes \
    -L 172.28.0.1:$EDGE_WEB_PORT:127.0.0.1:18080 \
    -L 172.28.0.1:$EDGE_IM_WS_PORT:127.0.0.1:9100 \
    -L 172.28.0.1:$EDGE_IM_HTTP_PORT:127.0.0.1:9101 \
    -i "$APP_KEY" ubuntu@"$APP_PRIVATE" \
    && ok "已建立" || { bad "建立失败"; return 1; }

  for p in $EDGE_WEB_PORT $EDGE_IM_WS_PORT; do
    sudo ufw allow from 172.28.0.0/16 to any port "$p" proto tcp comment 'chatapp app replica' >/dev/null 2>&1
  done
  ok "ufw 规则已就位"
}

cmd_apply() {
  log "发现 EDGE 容器 IP"
  discover_edge_ips || exit 1
  apply_app_tunnels || exit 1
  apply_edge_tunnels || exit 1
  log "重载 nginx"
  sudo cp "$EDGE_DIR/nginx/conf.d/default.conf" "$EDGE_DIR/nginx/conf.d/default.conf" 2>/dev/null
  sudo docker exec chatapp-nginx-1 nginx -t >/dev/null 2>&1 \
    && sudo docker exec chatapp-nginx-1 nginx -s reload && ok "nginx 已重载" \
    || warn "nginx 重载失败,请手工检查配置"
  echo
  cmd_verify
}

# --- verify -----------------------------------------------------------------
FAILED=0
check() {  # check <描述> <命令...>
  local desc=$1; shift
  if "$@" >/dev/null 2>&1; then ok "$desc"; else bad "$desc"; FAILED=1; fi
}

cmd_verify() {
  log "EDGE 容器"
  for c in chatapp-nginx-1 chatapp-web-1 chatapp-imserver-1 chatapp-mysql-1 chatapp-redis-1; do
    check "$c 运行中" bash -c "sudo docker ps --format '{{.Names}} {{.Status}}' | grep -q '^$c Up'"
  done

  log "APP 容器"
  check "chatapp-app-web-1 可用" bash -c "[ \"\$(ssh -i $APP_KEY -o StrictHostKeyChecking=no ubuntu@$APP_PRIVATE \"sudo docker ps --format '{{.Names}}' | grep -c chatapp-app-web-1\")\" = 1 ]"
  check "chatapp-app-imserver-1 可用" bash -c "[ \"\$(ssh -i $APP_KEY -o StrictHostKeyChecking=no ubuntu@$APP_PRIVATE \"sudo docker ps --format '{{.Names}}' | grep -c chatapp-app-imserver-1\")\" = 1 ]"

  log "链路"
  check "EDGE nginx /healthz" bash -c "[ \"\$(curl -sS -m 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/healthz)\" = 200 ]"
  check "EDGE -> APP web (18000)" bash -c "[ \"\$(curl -sS -m 8 -o /dev/null -w '%{http_code}' http://172.28.0.1:$EDGE_WEB_PORT/api/v1/health)\" != 000 ]"
  check "EDGE -> APP imserver (19101)" bash -c "[ \"\$(curl -sS -m 8 -o /dev/null -w '%{http_code}' http://172.28.0.1:$EDGE_IM_HTTP_PORT/internal/healthz)\" = 200 ]"
  check "APP -> EDGE MySQL (13306)" bash -c "ssh -i $APP_KEY -o StrictHostKeyChecking=no ubuntu@$APP_PRIVATE 'timeout 5 bash -c \"exec 3<>/dev/tcp/127.0.0.1/$APP_DB_PORT\"'"
  check "APP -> EDGE Redis (16379)" bash -c "ssh -i $APP_KEY -o StrictHostKeyChecking=no ubuntu@$APP_PRIVATE 'timeout 5 bash -c \"exec 3<>/dev/tcp/127.0.0.1/$APP_REDIS_PORT\"'"

  log "集群成员"
  EDGE_ID=$(sudo docker logs chatapp-imserver-1 2>&1 | grep delivery_bus_started | tail -1 | sed -n 's/.*"instance_id":"\([^"]*\)".*/\1/p')
  APP_ID=$(ssh -i "$APP_KEY" -o StrictHostKeyChecking=no ubuntu@"$APP_PRIVATE" \
    "sudo docker logs chatapp-app-imserver-1 2>&1 | grep delivery_bus_started | tail -1" 2>/dev/null \
    | sed -n 's/.*"instance_id":"\([^"]*\)".*/\1/p')
  [ -n "$EDGE_ID" ] && ok "EDGE imserver instance_id=$EDGE_ID" || { bad "EDGE imserver 未启用多实例"; FAILED=1; }
  [ -n "$APP_ID" ] && ok "APP imserver instance_id=$APP_ID" || { bad "APP imserver 未启用多实例"; FAILED=1; }
  if [ -n "$EDGE_ID" ] && [ "$EDGE_ID" = "$APP_ID" ]; then
    bad "两个实例的 instance_id 相同($EDGE_ID),跨节点路由会失效"; FAILED=1
  fi

  echo
  if [ "$FAILED" = 0 ]; then
    printf '\033[32mTOPOLOGY ok\033[0m\n'
  else
    printf '\033[31mTOPOLOGY broken\033[0m(见上面 ✗)\n'
    exit 1
  fi
}

# --- teardown ---------------------------------------------------------------
cmd_teardown() {
  log "摘掉 APP 侧隧道"
  restart_tunnel app "$APP_DB_PORT" "$APP_REDIS_PORT" "$APP_IM_WS_PORT" "$APP_IM_HTTP_PORT"
  ok "已摘掉"
  log "摘掉 EDGE 侧隧道"
  restart_tunnel edge "$EDGE_WEB_PORT" "$EDGE_IM_WS_PORT" "$EDGE_IM_HTTP_PORT"
  ok "已摘掉"
  warn "容器未动;nginx upstream 会因对端不可达而自动摘除(需等 max_fails 生效)"
}

case "${1:-}" in
  apply)    cmd_apply ;;
  verify)   cmd_verify ;;
  teardown) cmd_teardown ;;
  *) echo "用法: $0 {apply|verify|teardown}" >&2; exit 2 ;;
esac
