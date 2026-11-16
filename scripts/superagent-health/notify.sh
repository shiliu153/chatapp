#!/usr/bin/env bash
# 发一条 worker 巡检告警。通道按优先级探测,任何一条能发出去就算成功。
#
# 通道(在 /root/.dsh/superagent-health.env 里配,不要写进仓库):
#   1) SUPERAGENT_NOTIFY_CMD —— 逃生口:一条能吃掉 stdin 为正文的任意命令
#   2) 统一发信内核 scripts/lib/mail.py —— 阿里云邮件推送,与服务器日报同一个发信账号;
#      配置项是 MAIL_SMTP_URL / MAIL_FROM / MAIL_TO / MAIL_USER / MAIL_PASS
#   3) 什么都没有 —— 落 /root/.dsh/state/superagent-health/last-alert.md + journal
#
# 2026-11-16 起**删掉了「GitHub issue 评论」通道**:issue 是待办不是告警 —— 没人订阅就
# 没人看见,而且 GitHub 会把它统一渲染成一条讨论,类别与结论全被抹平。主题规范见
# docs/ops/mail.md(三段:类别 / 对象 / 结论),由 mail.py 一处渲染。
#
# 去重**不在这一层**:同一种异常 6 小时内只发一次由 run.sh 的指纹负责。内核的去重窗口
# 是给「同一条告警会反复触发」的发信点用的,两边都开等于双重抑制,更难查。
#
# 用法: notify.sh <类别> <对象> <结论> [正文文件]   (不给正文文件就从 stdin 读)
set -uo pipefail

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# 单独调用时也要能拿到通道配置(run.sh 会先 source,这里兜一层,避免「手动测通道」测不出来)。
ENV_FILE=${SUPERAGENT_HEALTH_ENV:-/root/.dsh/superagent-health.env}
# shellcheck source=/dev/null
[ -f "$ENV_FILE" ] && . "$ENV_FILE"

CATEGORY=${1:?用法: notify.sh <类别> <对象> <结论> [正文文件]}
NAME=${2:?用法: notify.sh <类别> <对象> <结论> [正文文件]}
VERDICT=${3:?用法: notify.sh <类别> <对象> <结论> [正文文件]}
BODY_FILE=${4:-}
if [ -z "$BODY_FILE" ]; then
  BODY_FILE=$(mktemp)
  cat >"$BODY_FILE"
fi
BODY=$(cat "$BODY_FILE")

STATE_DIR=${SUPERAGENT_HEALTH_STATE:-/root/.dsh/state/superagent-health}
mkdir -p "$STATE_DIR"

# 旧变量名映射:老 env 文件里写的是 SUPERAGENT_SMTP_URL / _MAIL_FROM / _SMTP_USER 那一套。
# 映射一次就够,免得升级时因为「配置还在、名字变了」而静默退化成只落盘。
: "${MAIL_SMTP_URL:=${SUPERAGENT_SMTP_URL:-}}"
: "${MAIL_FROM:=${SUPERAGENT_MAIL_FROM:-}}"
: "${MAIL_TO:=${SUPERAGENT_MAIL_TO:-}}"
: "${MAIL_USER:=${SUPERAGENT_SMTP_USER:-}}"
: "${MAIL_PASS:=${SUPERAGENT_SMTP_PASS:-}}"
# source 进来的变量不会自动进子进程环境(python 读不到),这里逐个显式 export。
for name in MAIL_SMTP_URL MAIL_FROM MAIL_TO MAIL_USER MAIL_PASS \
            MAIL_STATE_DB MAIL_LOG MAIL_PER_MINUTE MAIL_PER_DAY MAIL_DRY_RUN; do
  value=${!name:-}
  if [ -n "$value" ]; then export "$name=$value"; fi
done

# 仓库里跑时内核在 scripts/lib/;装到 /root/.dsh/healthcheck/ 后在 lib/ 下(install.sh 拷的)。
if [ -f "$HERE/lib/mail.py" ]; then
  MAIL_PY="$HERE/lib/mail.py"
elif [ -f "$HERE/../lib/mail.py" ]; then
  MAIL_PY="$HERE/../lib/mail.py"
else
  MAIL_PY=""
fi

# 主题只在 mail.py 里渲染(格式只有一处实现)。没有内核 / 内核跑不起来时退化成同一格式的
# 手拼,让「内核没装上」也能把信发出去 —— 但那是例外,不是常态(手拼这行会随格式一起改)。
SUBJECT=""
if [ -n "$MAIL_PY" ]; then
  SUBJECT=$(python3 "$MAIL_PY" subject \
    --category "$CATEGORY" --subject "$NAME" --verdict "$VERDICT" 2>/dev/null) || SUBJECT=""
fi
if [ -z "$SUBJECT" ]; then
  SUBJECT="[chatapp·$CATEGORY] $NAME — $VERDICT"
fi

printf '%s\n\n%s\n' "$SUBJECT" "$BODY" >"$STATE_DIR/last-alert.md"

send_cmd() {
  [ -n "${SUPERAGENT_NOTIFY_CMD:-}" ] || return 1
  printf '%s\n\n%s\n' "$SUBJECT" "$BODY" | bash -c "$SUPERAGENT_NOTIFY_CMD"
}

send_mail() {
  [ -n "$MAIL_PY" ] || return 1
  [ -n "${MAIL_SMTP_URL:-}" ] || return 1
  # 内核自己会重试两次,这里不再套一层重试(套了就是 4 次,把一次故障拖成几十秒)。
  python3 "$MAIL_PY" send \
    --category "$CATEGORY" --subject "$NAME" --verdict "$VERDICT" \
    --body-file "$BODY_FILE" --level "${SUPERAGENT_MAIL_LEVEL:-error}"
}

# 逃生口试两次:经宿主兜底代理时偶发 `Post ...: EOF`(2026-11-13 实测),
# 单次失败就换通道等于白白丢掉一条告警。
attempt_cmd() {
  local n=1
  while [ "$n" -le 2 ]; do
    if send_cmd; then return 0; fi
    n=$((n + 1))
    [ "$n" -le 2 ] && sleep 5
  done
  return 1
}

if attempt_cmd; then echo "notify: 已通过 SUPERAGENT_NOTIFY_CMD 发出"; exit 0; fi
if send_mail; then echo "notify: 已通过邮件内核发出 · $SUBJECT"; exit 0; fi

echo "notify: 没有任何可用通道 —— 只落盘到 $STATE_DIR/last-alert.md" >&2
logger -t superagent-health "告警通道未配置或不可用,内容已落盘:$SUBJECT"
exit 3
