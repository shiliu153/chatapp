#!/usr/bin/env bash
# 发一条 worker 健康告警。通道按优先级探测,任何一条能发出去就算成功。
#
# 通道(在 /root/.dsh/superagent-health.env 里配,不要写进仓库):
#   1) SUPERAGENT_NOTIFY_CMD   —— 逃生口:一条能吃掉 stdin 为正文的任意命令
#   2) SMTP                     —— SUPERAGENT_SMTP_URL + _MAIL_FROM/_MAIL_TO(+可选 _SMTP_USER/_SMTP_PASS)
#                                  例:SUPERAGENT_SMTP_URL=smtps://smtp.qq.com:465
#   3) GitHub issue 评论        —— SUPERAGENT_GH_ISSUE=<编号>,用 WSL 里已有的 gh 凭据;
#                                  GitHub 会把评论通知投递到账号邮箱,零新增密钥
#   4) 什么都没有               —— 落 /root/.dsh/state/superagent-health/last-alert.md + journal
#
# 用法: notify.sh "<主题>" [正文文件]      (不给正文文件就从 stdin 读)
set -uo pipefail

# 单独调用时也要能拿到通道配置(run.sh 会先 source,这里兜一层,避免「手动测通道」测不出来)。
ENV_FILE=${SUPERAGENT_HEALTH_ENV:-/root/.dsh/superagent-health.env}
# shellcheck source=/dev/null
[ -f "$ENV_FILE" ] && . "$ENV_FILE"

SUBJECT=${1:?用法: notify.sh <主题> [正文文件]}
BODY_FILE=${2:-}
if [ -z "$BODY_FILE" ]; then
  BODY_FILE=$(mktemp)
  cat >"$BODY_FILE"
fi
BODY=$(cat "$BODY_FILE")

STATE_DIR=${SUPERAGENT_HEALTH_STATE:-/root/.dsh/state/superagent-health}
mkdir -p "$STATE_DIR"
printf '%s\n\n%s\n' "$SUBJECT" "$BODY" >"$STATE_DIR/last-alert.md"

send_cmd() {
  [ -n "${SUPERAGENT_NOTIFY_CMD:-}" ] || return 1
  printf '%s\n\n%s\n' "$SUBJECT" "$BODY" | bash -c "$SUPERAGENT_NOTIFY_CMD"
}

send_smtp() {
  [ -n "${SUPERAGENT_SMTP_URL:-}" ] || return 1
  [ -n "${SUPERAGENT_MAIL_FROM:-}" ] || return 1
  [ -n "${SUPERAGENT_MAIL_TO:-}" ] || return 1
  local auth=()
  if [ -n "${SUPERAGENT_SMTP_USER:-}" ]; then
    auth=(--user "${SUPERAGENT_SMTP_USER}:${SUPERAGENT_SMTP_PASS:-}")
  fi
  # 邮件不走 http 代理:mihomo 是 HTTP 代理,SMTP 过不去。
  printf 'From: %s\nTo: %s\nSubject: %s\nDate: %s\n\n%s\n' \
    "$SUPERAGENT_MAIL_FROM" "$SUPERAGENT_MAIL_TO" "$SUBJECT" "$(date -R)" "$BODY" \
    | env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u all_proxy \
        curl -sS --max-time 40 --url "$SUPERAGENT_SMTP_URL" "${auth[@]}" \
        --mail-from "$SUPERAGENT_MAIL_FROM" --mail-rcpt "$SUPERAGENT_MAIL_TO" --upload-file -
}

send_github() {
  [ -n "${SUPERAGENT_GH_ISSUE:-}" ] || return 1
  local gh_bin=${GH_CLI:-}
  if [ -z "$gh_bin" ]; then
    if command -v gh >/dev/null 2>&1; then gh_bin=gh
    elif [ -x /root/.local/bin/gh-agent ]; then gh_bin=/root/.local/bin/gh-agent
    else return 1; fi
  fi
  local repo=${SUPERAGENT_GH_REPO:-shiliu153/chatapp}
  # gh 走直连必超时(国内直连 GitHub 不通),必须经 worker 用的同一出口代理。
  local proxy=${SUPERAGENT_PROXY:-http://127.0.0.1:7890}
  env HTTPS_PROXY="$proxy" HTTP_PROXY="$proxy" https_proxy="$proxy" http_proxy="$proxy" \
    "$gh_bin" issue comment "$SUPERAGENT_GH_ISSUE" --repo "$repo" \
    --body "**$SUBJECT**

$BODY"
}

# 每个通道试两次:经宿主兜底代理时偶发 `Post ...: EOF`(2026-11-13 实测),
# 单次失败就换下一个通道等于白白丢掉一条告警。
attempt() { # attempt <函数名>
  local n=1
  while [ "$n" -le 2 ]; do
    if "$1"; then return 0; fi
    n=$((n + 1))
    [ "$n" -le 2 ] && sleep 5
  done
  return 1
}

if attempt send_cmd; then echo "notify: 已通过 SUPERAGENT_NOTIFY_CMD 发出"; exit 0; fi
if attempt send_smtp; then echo "notify: 已通过 SMTP 发出"; exit 0; fi
if attempt send_github; then echo "notify: 已通过 GitHub issue 评论发出"; exit 0; fi

echo "notify: 没有任何可用通道 —— 只落盘到 $STATE_DIR/last-alert.md" >&2
logger -t superagent-health "告警通道未配置,内容已落盘:$SUBJECT"
exit 3
