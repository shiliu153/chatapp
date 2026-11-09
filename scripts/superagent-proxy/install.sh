#!/bin/bash
# 在 WSL 里装一个只听回环的 mihomo 出口代理,给 superagent worker 用。
#
# 为什么是 WSL 内自建,而不是继续用 Windows 上的 Clash:
#   实测(2026-11-09)worker 访问 api.github.com,直连 9/10 成功,
#   走宿主 Clash 7897 只有 5/10 —— 代理不但没帮忙,还更差。
#   链路是 WSL → 宿主 NAT → 宿主 Clash → 境外,中间那跳不可控。
#   自建之后变成 WSL → 机场 IEPL 节点,少一跳、线路可控。
#
# 幂等:重复跑只会补齐缺的东西,不会重装已存在的二进制。
#
# 用法(从 Windows 侧):
#   wsl -e bash -c 'bash /root/src/chatapp/scripts/superagent-proxy/install.sh'
#
# 环境变量:
#   SUB_URL      订阅地址;不给则读 $DIR/subscription.url(不存在就报错退出)
#   MIHOMO_VER   mihomo 版本,默认 v1.19.33
#   HOST_PROXY   下载用的宿主代理,默认自动探测网关:7897(下不到就试直连)
set -uo pipefail

DIR=${DIR:-/root/.dsh/proxy}
BIN=/usr/local/bin/mihomo
UNIT=/etc/systemd/system/superagent-proxy.service
SERVICE=superagent-proxy
MIHOMO_VER=${MIHOMO_VER:-v1.19.33}
GH=https://github.com/MetaCubeX/mihomo/releases/download

say() { echo "[install] $*"; }
die() { echo "[install] 错误:$*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || die "需要 root(要写 /usr/local/bin 与 /etc/systemd/system)"

# 宿主网关:WSL 里访问 Windows 的唯一稳定地址。下载 mihomo / geoip 时用它,
# 因为这些资产在 GitHub 上,而当前这套网络直连 GitHub 有 10% 的失败率。
HOSTIP=$(ip route show default | awk '{print $3}' | head -1)
HOST_PROXY=${HOST_PROXY:-}
if [ -z "$HOST_PROXY" ] && [ -n "$HOSTIP" ]; then
  if timeout 2 bash -c "echo > /dev/tcp/$HOSTIP/7897" 2>/dev/null; then
    HOST_PROXY="http://$HOSTIP:7897"
  fi
fi
say "宿主代理:${HOST_PROXY:-（不可用,下载将走直连）}"

mkdir -p "$DIR"
chmod 700 "$DIR"

# ---------- 1. 订阅地址 ----------
if [ -n "${SUB_URL:-}" ]; then
  printf '%s\n' "$SUB_URL" >"$DIR/subscription.url"
  chmod 600 "$DIR/subscription.url"
  say "订阅地址已写入 $DIR/subscription.url"
elif [ ! -s "$DIR/subscription.url" ]; then
  die "没有订阅地址。请先跑一次:SUB_URL='https://…' bash $0"
fi

# controller 密钥:随机生成,refresh 脚本读它来热重载。
# 只监听回环,所以它不是安全边界;作用是挡住本机其它进程误调 controller。
if [ ! -s "$DIR/controller.secret" ]; then
  head -c 24 /dev/urandom | base64 | tr -d '\n=+/' >"$DIR/controller.secret"
  chmod 600 "$DIR/controller.secret"
  say "已生成 controller 密钥 $DIR/controller.secret"
fi

# ---------- 2. mihomo 二进制 ----------
if [ -x "$BIN" ] && "$BIN" -v 2>/dev/null | grep -q "${MIHOMO_VER#v}"; then
  say "mihomo 已是 ${MIHOMO_VER},跳过下载"
else
  say "下载 mihomo ${MIHOMO_VER} …"
  TMP=$(mktemp -d)
  URL="$GH/${MIHOMO_VER}/mihomo-linux-amd64-${MIHOMO_VER}.gz"
  ok=0
  for mode in "-x $HOST_PROXY" ""; do
    # shellcheck disable=SC2086
    if curl -fsSL -m 180 $mode -o "$TMP/mihomo.gz" "$URL"; then ok=1; break; fi
    say "下载失败(模式:${mode:-直连}),重试另一种…"
  done
  [ "$ok" = 1 ] || { rm -rf "$TMP"; die "下载 mihomo 失败,检查网络/代理后重试"; }
  gunzip -c "$TMP/mihomo.gz" >"$BIN.tmp" || { rm -rf "$TMP"; die "解压失败"; }
  chmod 755 "$BIN.tmp"
  mv "$BIN.tmp" "$BIN"
  rm -rf "$TMP"
  say "已安装 $("$BIN" -v 2>/dev/null | head -1)"
fi

# ---------- 3. GeoIP 数据(鸡生蛋) ----------
# 订阅配置里有 GEOIP,CN 和 GEOIP,NETFLIX 规则,mihomo 首次启动需要
# geoip.metadb;它会自己联网下,但那时我们的代理还没起来 —— 直连 GitHub
# 有 10% 概率卡住。所以在这里先下好,让首次启动不需要外网。
if [ ! -s "$DIR/geoip.metadb" ]; then
  say "预下载 geoip.metadb …"
  # 三个源依次试:GitHub 原始 → jsDelivr 镜像 → 直连。
  # 实测 2026-11-09:GitHub release 直连和经宿主代理都 504,但 mihomo 自己
  # 启动时用它的内置 CDN 能下成功。所以这里下不到**不算失败** ——
  # 只是让首次启动多花 3 秒(mihomo 会自己补),不要因此中断安装。
  for src in \
    "https://github.com/MetaCubeX/meta-rules-dat/releases/download/latest/geoip.metadb" \
    "https://cdn.jsdelivr.net/gh/MetaCubeX/meta-rules-dat@release/geoip.metadb" \
    "https://testingcf.jsdelivr.net/gh/MetaCubeX/meta-rules-dat@release/geoip.metadb"; do
    for mode in "-x $HOST_PROXY" ""; do
      # shellcheck disable=SC2086
      if curl -fsSL -m 120 $mode -o "$DIR/geoip.metadb" "$src" 2>/dev/null; then
        say "geoip.metadb 已下载(${src%%/releases*}${src##*jsdelivr.net})"
        break 2
      fi
    done
  done
  if [ ! -s "$DIR/geoip.metadb" ]; then
    rm -f "$DIR/geoip.metadb"
    say "geoip.metadb 预下载没成功 —— 不致命,mihomo 启动时会自己下(约 3s)"
  fi
else
  say "geoip.metadb 已存在"
fi

# ---------- 4. 渲染配置 ----------
say "渲染 config.yaml …"
python3 "$(dirname "$0")/render-config.py" \
  --url-file "$DIR/subscription.url" \
  --out "$DIR/config.yaml" \
  --override "$(dirname "$0")/override.yaml" \
  --secret-file "$DIR/controller.secret" \
  ${HOST_PROXY:+--host-proxy "$HOST_PROXY"} \
  || die "渲染失败,保留原有配置(若有)"

# ---------- 5. 运行时副本 ----------
# 定时任务不能依赖仓库母体:母体要人工 pull 才会更新,而且 pull 失败时
# 定时任务会跟着静默失效。所以把 refresh 需要的三件套复制到 $DIR/bin,
# 由 install.sh 负责同步 —— 「改了仓库脚本」和「定时任务跑什么」之间
# 只隔一次 install.sh,关系明确。
mkdir -p "$DIR/bin"
install -m 755 "$(dirname "$0")/render-config.py" "$DIR/bin/render-config.py"
install -m 755 "$(dirname "$0")/refresh.sh" "$DIR/bin/refresh.sh"
install -m 755 "$(dirname "$0")/probe.sh" "$DIR/bin/probe.sh"
install -m 644 "$(dirname "$0")/override.yaml" "$DIR/bin/override.yaml"
say "运行时副本已同步到 $DIR/bin"

# ---------- 6. systemd ----------
# 为什么不挂在 DSH 进程树里:代理的生死和 DSH 的生死是两件事。
# DSH 重启不该断代理,代理挂了也不该带崩 DSH —— 而且 start-superagent.sh
# 探测不到代理时会自动回退宿主 7897,这依赖代理是个独立进程。
cat >"$UNIT" <<EOF
[Unit]
Description=superagent egress proxy (mihomo, WSL, loopback only)
After=network-online.target
Wants=network-online.target
# 配置坏了会疯狂重启;限流后停下来,让人看日志而不是刷爆 journal。
# 注意这两个键属于 [Unit],写在 [Service] 里 systemd 只打一行
# "Unknown key name" 就忽略 —— 等于限流根本没生效。
StartLimitBurst=5
StartLimitIntervalSec=120

[Service]
Type=simple
ExecStart=$BIN -d $DIR
Restart=always
RestartSec=3
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null
systemctl restart "$SERVICE"

# 订阅自动刷。为什么要 6 小时一次而不是一天一次:机场的端口是端口池
# 随机分配的(每次拉订阅给的端口都不同),万一某天旧端口被回收,配置里
# 那条就是死地址,worker 会一直连不上直到下次刷新 —— 24h 的失效窗口
# 太长,6 小时可以接受。重载是热重载(不重启进程),影响 <1s。
# 时间点避开服务器已有的 03:20 自建备份 / 03:30 宝塔备份 / 04:10 树莓派拉备份。
cat >/etc/systemd/system/superagent-proxy-refresh.service <<EOF
[Unit]
Description=Refresh superagent proxy subscription
After=network-online.target

[Service]
Type=oneshot
ExecStart=$DIR/bin/refresh.sh
EOF

cat >/etc/systemd/system/superagent-proxy-refresh.timer <<'EOF'
[Unit]
Description=Refresh superagent proxy subscription (every 6h)

[Timer]
OnCalendar=*-*-* 04,10,16,22:20:00
Persistent=true
RandomizedDelaySec=600

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now superagent-proxy-refresh.timer >/dev/null
say "订阅刷新定时器已启用(superagent-proxy-refresh.timer,每 6 小时 :20 分)"

# ---------- 6. 等端口就绪 ----------
# 不能 sleep 2 就冒烟:mihomo 首次启动要加载 867 条规则 + 下 geoip(约 3s),
# 之后才 listen。2026-11-09 第一次装时就是这里误报「冒烟失败」,
# 实际服务是好的 —— 假失败比没检查更糟,会让人去改没问题的地方。
PORT=$(python3 -c "import yaml;print(yaml.safe_load(open('$DIR/config.yaml'))['mixed-port'])")
say "等待 mihomo 监听 127.0.0.1:$PORT …"
ready=0
for i in $(seq 30); do
  if timeout 1 bash -c "echo > /dev/tcp/127.0.0.1/$PORT" 2>/dev/null; then
    ready=1
    say "已监听(等了 ${i}s)"
    break
  fi
  sleep 1
done

if [ "$ready" != 1 ]; then
  echo "--- journalctl -u $SERVICE -n 30 ---" >&2
  journalctl -u "$SERVICE" -n 30 --no-pager >&2
  die "30s 内没监听上 $PORT,见上面的日志"
fi

# ---------- 7. 冒烟 ----------
say "冒烟:经 127.0.0.1:$PORT 访问 api.github.com …"
if curl -fsS -m 15 -x "http://127.0.0.1:$PORT" -o /dev/null \
  -w '  http=%{http_code} 耗时=%{time_total}s\n' https://api.github.com/rate_limit; then
  say "出口通了"
else
  echo "警告:冒烟失败。看日志:journalctl -u $SERVICE -n 50 --no-pager" >&2
  echo "      也可能是刚起、测速组还没选出节点,等 30s 再试。" >&2
fi

cat <<EOF

完成。接下来:
  1) 三路对比,确认真的比现状好:bash $(dirname "$0")/probe.sh
  2) 切换 worker 出口:bash $(dirname "$0")/../superagent-start/install.sh
  3) 日常:systemctl status $SERVICE / journalctl -u $SERVICE -f
EOF
