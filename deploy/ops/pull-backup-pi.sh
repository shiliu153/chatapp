#!/bin/bash
# 树莓派侧:把生产备份拉到本地(异地),并回写状态给服务器日报。
#
# 拓扑与方向很重要:
#   生产服务器在公网(47.116.114.110),树莓派在家里内网(192.168.101.3)。
#   服务器**主动连不到**内网,所以必须是**树莓派主动往外拉**。
#   树莓派用专用只读账号 `backup`(只给读备份目录 + 写一个状态文件),
#   不用 root 的密钥 —— 树莓派被拿下也不至于直接拿到服务器 root。
#
# 为什么不用 rsync:服务器上没装 rsync。整棵树现在只有几 MB,
# 用 `tar over ssh` 只传「本地还没有的文件」就够了。哪天媒体涨到几百 MB
# 再考虑在服务器装 rsync 做真增量。
#
# 安装(树莓派上,**用 moonlinux 而不是 root** —— 这台机器上 moonlinux 有 sudo 但要口令,
# 而这条链完全不需要 root:密钥、备份目录、日志都在自己家目录下):
#   install -m 755 deploy/ops/pull-backup-pi.sh ~/bin/chatapp-pull-backup.sh
# cron(moonlinux 的 crontab,树莓派时区已是 Asia/Shanghai):
#   10 4 * * * flock -xn /home/moonlinux/chatapp-backups/.pull.lock \
#     -c /home/moonlinux/bin/chatapp-pull-backup.sh >> /home/moonlinux/chatapp-backups/pull-backup.log 2>&1

set -euo pipefail
umask 077

REMOTE_USER=${REMOTE_USER:-backup}
REMOTE_HOST=${REMOTE_HOST:-47.116.114.110}
REMOTE_DIR=${REMOTE_DIR:-/www/wwwroot/chatapp/backups}
REMOTE_STATUS=${REMOTE_STATUS:-/var/lib/chatapp-backup/offsite-status.txt}

LOCAL_DIR=${LOCAL_DIR:-/home/moonlinux/chatapp-backups}
KEY=${KEY:-/home/moonlinux/.ssh/id_ed25519_backup}
KEEP_DAYS=${KEEP_DAYS:-14}

SSH="ssh -i $KEY -o BatchMode=yes -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new"
TARGET="$REMOTE_USER@$REMOTE_HOST"

log() {
    printf '%s %s\n' "$(date '+%F %T')" "$*"
}

# 把结果回写给服务器日报(单行覆盖写;日报读不到就当"异地没跑")
# ts 用 ISO 的 T 分隔:带空格的 "%F %T" 会被日报按空白切词切成两段,解析失败。
write_status() {
    local result=$1 detail=$2 files=$3 newest=$4 total=$5
    printf 'ts=%s result=%s files=%s newest=%s total=%s detail=%s\n' \
        "$(date '+%FT%T')" "$result" "$files" "$newest" "$total" "$detail" \
        | $SSH "$TARGET" "cat > $REMOTE_STATUS" || log "状态回写失败(不影响本地备份)"
}

die() {
    log "失败: $*"
    write_status failed "$*" "${FILES:-0}" "${NEWEST:--}" "${TOTAL:-0}"
    exit 1
}

mkdir -p "$LOCAL_DIR"/db "$LOCAL_DIR"/media "$LOCAL_DIR"/config
[ -r "$KEY" ] || die "读不到私钥 $KEY"

# 1) 先确认能连上,并列出远端文件
REMOTE_FILES=$($SSH "$TARGET" "cd $REMOTE_DIR && find db media config -type f -print" 2>/dev/null) \
    || die "连不上 $TARGET 或读不到 $REMOTE_DIR"
[ -n "$REMOTE_FILES" ] || die "远端备份目录是空的"

# 2) 只传本地还没有的
missing=()
while IFS= read -r f; do
    [ -n "$f" ] || continue
    [ -e "$LOCAL_DIR/$f" ] || missing+=("$f")
done <<<"$REMOTE_FILES"

log "远端文件 $(printf '%s\n' "$REMOTE_FILES" | wc -l) 个,本地缺 ${#missing[@]} 个"
if [ ${#missing[@]} -gt 0 ]; then
    # 文件名走 stdin 的 NUL 列表(`tar --null -T -`),**不再**拼进远端 shell 命令行:
    # 原来的 `tar -cf - -- ${missing[*]}` 是把远端 `find` 的输出直接塞进
    # `cd $REMOTE_DIR && tar ...`,备份目录里出现 `a b`、`x; echo pwned` 这类名字时,
    # 分号后的部分会在服务器上以 backup 账号执行(第四轮审计 L-8)。
    # 现在远端只执行一条固定命令,文件名只是数据。
    if ! printf '%s\0' "${missing[@]}" \
        | $SSH "$TARGET" "cd $REMOTE_DIR && tar --null -cf - -T -" \
        | tar -xf - -C "$LOCAL_DIR"; then
        die "拉取失败(tar over ssh)"
    fi
fi

# 3) 完整性校验:用服务器生成的 .sha256 逐个比对本地实际内容
checked=0
while IFS= read -r f; do
    [ -f "$f.sha256" ] || continue
    want=$(awk '{print $1}' "$f.sha256")
    got=$(sha256sum "$f" | awk '{print $1}')
    [ "$want" = "$got" ] || die "校验失败: $f"
    checked=$((checked + 1))
done < <(find "$LOCAL_DIR" -name '*.sql.gz' -type f)
log "sha256 校验通过 $checked 份 dump"

# 4) 本地保留
find "$LOCAL_DIR" -type f \
    \( -name 'chatapp-*.sql.gz*' -o -name 'chatapp-*.tar.gz*' \) \
    -mtime +"$KEEP_DAYS" -print -delete | sed 's/^/  rm /'

# 5) 回写状态给服务器日报
FILES=$(find "$LOCAL_DIR" -name '*.sql.gz' -type f | wc -l)
NEWEST=$(find "$LOCAL_DIR" -name 'chatapp-db-*.sql.gz' -type f -printf '%f\n' | sort | tail -1)
[ -n "$NEWEST" ] || NEWEST='-'
TOTAL=$(du -sh "$LOCAL_DIR" | cut -f1)
FREE=$(df -h "$LOCAL_DIR" | awk 'NR==2 {print $4}')
write_status ok "checked=$checked free=$FREE" "$FILES" "$NEWEST" "$TOTAL"

log "完成: 本地 $FILES 份 dump,最新 $NEWEST,共 $TOTAL,磁盘剩余 $FREE"
