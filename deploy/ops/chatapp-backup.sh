#!/bin/bash
# 生产备份(宝塔形态):两库全量 dump + 媒体目录 + 恢复必需的配置快照。
#
# 设计要点:
#   1. **两库都要备**:`chatapp`(应用库,应用账号)与 `chatapp_im`(自建 IM 库,
#      凭据在 imserver 的 DSN 里)。历史上只备了 IM 的两张表,应用库一次没备过;
#   2. **每个 dump 都做完整性校验**:`gzip -t` + 末行必须是 `-- Dump completed`,
#      否则非零退出 —— 「文件在但内容截断」是最常见的备份翻车方式;
#   3. **与库同盘,所以必须异地**:本脚本只保证「本机有可用备份」,异地靠
#      `deploy/ops/pull-backup.ps1` 每日把最新 dump 拉回个人电脑(零成本);
#   4. **保留 N 天**并自动清理,避免 40G 盘被备份撑爆;
#   5. 任何一步失败都非零退出,cron 日志里能直接看出来。
#
# 用法:
#   chatapp-backup.sh                    # 正常备份
#   KEEP_DAYS=7 chatapp-backup.sh        # 改保留天数
#
# 安装(仓库是唯一事实来源,改完要重新 install):
#   install -m 755 deploy/ops/chatapp-backup.sh /www/server/ops/chatapp-backup.sh
# cron(每天 03:20,避开已有的 03:10/03:30/03:40/03:50/04:00 任务):
#   20 3 * * * flock -xn /www/server/ops/chatapp-backup.lock \
#     -c /www/server/ops/chatapp-backup.sh >> /www/wwwlogs/chatapp-backup.log 2>&1

set -euo pipefail
umask 077

APP_DIR=${APP_DIR:-/www/wwwroot/chatapp/chatapp}      # manage.py 所在层
DEST=${DEST:-/www/wwwroot/chatapp/backups}            # 备份根目录
KEEP_DAYS=${KEEP_DAYS:-14}
STAMP=$(date +%Y%m%d-%H%M%S)

APP_ENV="$APP_DIR/.env"
IM_ENV=/www/server/imserver/imserver.env

log() {
    printf '%s %s\n' "$(date '+%F %T')" "$*"
}

die() {
    log "失败: $*"
    exit 1
}

# 从 KEY=VALUE 文件里取一个值;不用 source,免得值里的特殊字符被 shell 解释
env_get() {
    sed -n "s/^$2=//p" "$1" | head -n 1
}

[ -r "$APP_ENV" ] || die "读不到 $APP_ENV"
[ -r "$IM_ENV" ] || die "读不到 $IM_ENV"

DB_NAME=$(env_get "$APP_ENV" DB_NAME)
DB_USER=$(env_get "$APP_ENV" DB_USER)
DB_PASSWORD=$(env_get "$APP_ENV" DB_PASSWORD)
DB_HOST=$(env_get "$APP_ENV" DB_HOST)
DB_PORT=$(env_get "$APP_ENV" DB_PORT)
DB_HOST=${DB_HOST:-127.0.0.1}
DB_PORT=${DB_PORT:-3306}
[ -n "$DB_NAME" ] && [ -n "$DB_USER" ] && [ -n "$DB_PASSWORD" ] || die "应用库连接信息不全"

# DSN 形如 mysql://user:pass@host:port/dbname;密码可能含特殊字符,按**最后一个** @ 切
IM_MYSQL_DSN=$(env_get "$IM_ENV" IM_MYSQL_DSN)
[ -n "$IM_MYSQL_DSN" ] || die "IM_MYSQL_DSN 缺失"
dsn=${IM_MYSQL_DSN#mysql://}
im_creds=${dsn%@*}
im_rest=${dsn##*@}
IM_USER=${im_creds%%:*}
IM_PASSWORD=${im_creds#*:}
im_hostport=${im_rest%%/*}
IM_DB=${im_rest#*/}
IM_DB=${IM_DB%%\?*}
IM_HOST=${im_hostport%%:*}
IM_PORT=${im_hostport##*:}
[ -n "$IM_USER" ] && [ -n "$IM_PASSWORD" ] && [ -n "$IM_DB" ] || die "IM 库连接信息解析失败"

mkdir -p "$DEST/db" "$DEST/media" "$DEST/config"

# 单个库的 dump:--single-transaction 不锁表;--no-tablespaces 免 PROCESS 权限
dump_db() {
    local user=$1 pass=$2 host=$3 port=$4 db=$5 out=$6
    log "dump $db -> $out"
    if ! MYSQL_PWD="$pass" mysqldump \
            --host="$host" --port="$port" --user="$user" \
            --single-transaction --quick --routines --triggers \
            --no-tablespaces --set-gtid-purged=OFF \
            --default-character-set=utf8mb4 --hex-blob \
            "$db" 2>"$out.err" | gzip -9 >"$out"; then
        cat "$out.err" >&2 || true
        rm -f "$out" "$out.err"
        die "mysqldump 失败: $db"
    fi
    if [ -s "$out.err" ]; then
        log "  mysqldump 警告: $(tr '\n' ' ' <"$out.err")"
    fi
    rm -f "$out.err"

    # 完整性校验:压缩包能解开 + 末行是 mysqldump 的正常收尾
    gzip -t "$out" || die "gzip 校验失败: $out"
    if ! zcat "$out" | tail -n 1 | grep -q '^-- Dump completed'; then
        die "dump 不完整(缺少 Dump completed 尾行): $db"
    fi
    sha256sum "$out" >"$out.sha256"
    chmod 600 "$out" "$out.sha256"
    local tables
    tables=$(zcat "$out" | grep -c '^CREATE TABLE' || true)
    log "  ok $(du -h "$out" | cut -f1),建表语句 $tables 条"
}

dump_db "$DB_USER" "$DB_PASSWORD" "$DB_HOST" "$DB_PORT" "$DB_NAME" \
    "$DEST/db/chatapp-db-$STAMP.sql.gz"
dump_db "$IM_USER" "$IM_PASSWORD" "$IM_HOST" "$IM_PORT" "$IM_DB" \
    "$DEST/db/chatapp-im-db-$STAMP.sql.gz"

# 媒体目录(资料图/广场图/聊天图/语音;聊天媒体 30 天过期,量很小)
MEDIA_OUT="$DEST/media/chatapp-media-$STAMP.tar.gz"
if [ -d "$APP_DIR/media" ]; then
    log "打包 media -> $MEDIA_OUT"
    tar -czf "$MEDIA_OUT" -C "$APP_DIR" media
    sha256sum "$MEDIA_OUT" >"$MEDIA_OUT.sha256"
    chmod 600 "$MEDIA_OUT" "$MEDIA_OUT.sha256"
    log "  ok $(du -h "$MEDIA_OUT" | cut -f1)"
else
    log "跳过 media(目录不存在)"
fi

# 恢复必需的配置快照:没有这些,光有 dump 也起不来
CONF_OUT="$DEST/config/chatapp-config-$STAMP.tar.gz"
conf_files=()
for f in "$APP_ENV" "$IM_ENV" \
         /www/server/panel/vhost/nginx/chat.shiliu153.cn.conf \
         /www/server/panel/plugin/supervisor/profile/chatapp-web.ini \
         /www/server/panel/plugin/supervisor/profile/chatapp-celery.ini \
         /etc/cron.d/mysql-watchdog; do
    if [ -f "$f" ]; then
        conf_files+=("${f#/}")
    fi
done
[ ${#conf_files[@]} -gt 0 ] || die "一个配置文件都没找到,配置快照不能为空"
log "打包配置快照 -> $CONF_OUT(${#conf_files[@]} 个文件)"
tar -czf "$CONF_OUT" -C / "${conf_files[@]}"
sha256sum "$CONF_OUT" >"$CONF_OUT.sha256"
chmod 600 "$CONF_OUT" "$CONF_OUT.sha256"

# 保留策略
log "清理超过 ${KEEP_DAYS} 天的备份"
find "$DEST/db" "$DEST/media" "$DEST/config" -maxdepth 1 -type f \
    \( -name 'chatapp-*.sql.gz*' -o -name 'chatapp-*.tar.gz*' \) \
    -mtime +"$KEEP_DAYS" -print -delete | sed 's/^/  rm /'

log "完成: db=$(du -sh "$DEST/db" | cut -f1) media=$(du -sh "$DEST/media" | cut -f1) config=$(du -sh "$DEST/config" | cut -f1) 磁盘剩余 $(df -h "$DEST" | awk 'NR==2 {print $4}')"
