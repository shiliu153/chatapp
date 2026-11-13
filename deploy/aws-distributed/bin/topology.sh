#!/usr/bin/env bash
# AWS 双机拓扑的「自检」与「部署状态核对」。
#
# ⚠️ 历史说明：本脚本曾经是**隧道时代**的工具（verify / apply / teardown，用 SSH 端口转发
# 把两台机器缝起来）。2026-11-13 安全组放行后已切换成 **VPC 内网直连**，隧道不再需要。
# `apply` / `teardown` 已**删除**，因为它们会重建隧道、覆盖直连配置 —— 留着就是隐患。
# 现在只保留 `verify`：核对「两台机器该跑的都跑着、该通的都通着」。
#
# 用法（在入口机上跑）：
#   bash topology.sh verify     # 全量自检；任一环节失败退出码 1
#
# 注意：verify 只能证明「管道在」，**不能证明数据真的流过去**。
# 跨节点投递的功能验证必须跑 lab_cross_node.py（历史上出现过「端口全通但集群已坏」）。
set -uo pipefail

EDGE_PRIVATE="172.31.14.4"
APP_PRIVATE="172.31.35.181"
APP_KEY="$HOME/.ssh/id_ed25519_aws2aws"
EDGE_DIR="/opt/chatapp-edge"

# 直连端口约定（与安全组、nginx upstream 三处必须一致）
APP_WEB_PORT=8000
APP_IM_WS_PORT=9100
APP_IM_HTTP_PORT=9101
EDGE_DB_PORT=3306
EDGE_REDIS_PORT=6379

log()  { printf '\033[34m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[32m  ✓\033[0m %s\n' "$*"; }
bad()  { printf '\033[31m  ✗\033[0m %s\n' "$*"; }

on_app() { ssh -i "$APP_KEY" -o StrictHostKeyChecking=no -o ConnectTimeout=15 \
              ubuntu@"$APP_PRIVATE" "$@"; }

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
  check "chatapp-app-web-1 运行中" \
    bash -c "ssh -i $APP_KEY -o StrictHostKeyChecking=no ubuntu@$APP_PRIVATE \"sudo docker ps --format '{{.Names}}' | grep -qx chatapp-app-web-1\""
  check "chatapp-app-imserver-1 运行中" \
    bash -c "ssh -i $APP_KEY -o StrictHostKeyChecking=no ubuntu@$APP_PRIVATE \"sudo docker ps --format '{{.Names}}' | grep -qx chatapp-app-imserver-1\""

  log "数据层已发布到内网网卡（Docker 不允许 internal 网络发布端口，必须挂在 dataedge 上）"
  check "EDGE 监听 $EDGE_PRIVATE:$EDGE_DB_PORT" \
    bash -c "ss -tln | grep -q '$EDGE_PRIVATE:$EDGE_DB_PORT'"
  check "EDGE 监听 $EDGE_PRIVATE:$EDGE_REDIS_PORT" \
    bash -c "ss -tln | grep -q '$EDGE_PRIVATE:$EDGE_REDIS_PORT'"

  log "跨机链路（直连，不经隧道）"
  check "EDGE -> APP web ($APP_WEB_PORT)" \
    bash -c "[ \"\$(curl -sS -m 8 -o /dev/null -w '%{http_code}' http://$APP_PRIVATE:$APP_WEB_PORT/api/v1/health)\" != 000 ]"
  check "EDGE -> APP imserver ($APP_IM_HTTP_PORT)" \
    bash -c "[ \"\$(curl -sS -m 8 -o /dev/null -w '%{http_code}' http://$APP_PRIVATE:$APP_IM_HTTP_PORT/internal/healthz)\" = 200 ]"
  check "APP -> EDGE MySQL ($EDGE_DB_PORT)" \
    bash -c "ssh -i $APP_KEY -o StrictHostKeyChecking=no ubuntu@$APP_PRIVATE 'timeout 5 bash -c \"exec 3<>/dev/tcp/$EDGE_PRIVATE/$EDGE_DB_PORT\"'"
  check "APP -> EDGE Redis ($EDGE_REDIS_PORT)" \
    bash -c "ssh -i $APP_KEY -o StrictHostKeyChecking=no ubuntu@$APP_PRIVATE 'timeout 5 bash -c \"exec 3<>/dev/tcp/$EDGE_PRIVATE/$EDGE_REDIS_PORT\"'"

  log "入口机 nginx"
  check "nginx /healthz" \
    bash -c "[ \"\$(curl -sS -m 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/healthz)\" = 200 ]"
  check "nginx /api/v1/app/config" \
    bash -c "[ \"\$(curl -sS -m 8 -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/api/v1/app/config)\" = 200 ]"

  log "集群成员"
  EDGE_ID=$(sudo docker logs chatapp-imserver-1 2>&1 | grep delivery_bus_started | tail -1 \
    | sed -n 's/.*"instance_id":"\([^"]*\)".*/\1/p')
  APP_ID=$(on_app "sudo docker logs chatapp-app-imserver-1 2>&1 | grep delivery_bus_started | tail -1" 2>/dev/null \
    | sed -n 's/.*"instance_id":"\([^"]*\)".*/\1/p')
  if [ -n "$EDGE_ID" ]; then ok "EDGE imserver instance_id=$EDGE_ID"; else bad "EDGE imserver 未启用多实例"; FAILED=1; fi
  if [ -n "$APP_ID" ]; then ok "APP imserver instance_id=$APP_ID"; else bad "APP imserver 未启用多实例"; FAILED=1; fi
  if [ -n "$EDGE_ID" ] && [ "$EDGE_ID" = "$APP_ID" ]; then
    bad "两个实例 instance_id 相同($EDGE_ID)，跨节点路由会失效"; FAILED=1
  fi

  log "不应存在的隧道（直连后残留会掩盖问题）"
  if ss -tln | grep -qE ':(18000|19100|19101|13306|16379) '; then
    bad "EDGE 上仍有隧道端口在监听（18000/19100/19101/13306/16379）"; FAILED=1
  else
    ok "EDGE 无隧道残留"
  fi

  echo
  if [ "$FAILED" = 0 ]; then
    printf '\033[32mTOPOLOGY ok\033[0m\n'
    printf '  提示：这只证明管道在。功能验证请跑 lab_cross_node.py（跨节点投递）。\n'
  else
    printf '\033[31mTOPOLOGY broken\033[0m（见上面 ✗）\n'
    exit 1
  fi
}

case "${1:-}" in
  verify) cmd_verify ;;
  *) echo "用法: $0 verify   （apply/teardown 已在切换直连时删除，见文件头）" >&2; exit 2 ;;
esac
