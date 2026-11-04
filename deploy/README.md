# 一键从零部署(Docker Compose)

> 目标:一台**全新的 Linux 服务器**,一条命令拉起 chat 服务的全部组件——
> Django(gunicorn)+ Celery + MySQL 8 + Redis 7 + 自建 `imserver` + nginx + Vue 前端,
> 可选自动申请 Let's Encrypt 证书并每日续期。
>
> 这是与现网「宝塔 + supervisor」并行的另一条部署路径,适合新机器、灾备重建、
> 本地/测试环境。**同一台机器上不要和宝塔 nginx 抢 80/443。**

## 1. 架构

```
浏览器 / App
   │  80/443(只有 nginx 发布宿主机端口)
   ▼
nginx 容器(固定 172.28.0.10)
   ├─ /            → Vue dist(镜像内静态文件)
   ├─ /api /admin /ops → web:8000(gunicorn + Django)
   ├─ /im/ws       → imserver:9100(WebSocket)
   ├─ /im/api/     → imserver:9101(HTTP)
   ├─ /media/chat/ → 先 auth_request 到 Django 验签,再直出
   └─ /media/      → 资料图/广场图直出
        │
        ├─ mysql:3306(仅 backend 网络,不发布宿主机)
        └─ redis:6379(仅 backend 网络,不发布宿主机)
```

- 所有容器在固定子网 `172.28.0.0/16` 内;nginx 固定 `172.28.0.10`,
  Django 与 imserver 的 `TRUSTED_PROXY_IPS` 只信任这一个地址(不再是整个子网),
  其他容器无法伪造 `X-Real-IP`(H-2)。
- 两张网络:`default` 负责对外,`backend`(internal)只放 MySQL/Redis,
  只有 web/worker/imserver 同时接入;nginx 与 certbot 没有到 3306/6379 的路由(M-6)。
- imserver 的 `/internal/*` 按 `IM_INTERNAL_ALLOW` 放行来源网段(默认 compose 子网),
  仍校验 HMAC;不再依赖「源地址是回环」这个在容器里不成立的假设(H-1)。
- MySQL root 只允许来自 compose 子网(`MYSQL_ROOT_HOST=172.28.0.%`),不是 `%`(L-9)。
- 应用与 imserver 镜像以非 root(`uid 10001`)运行;每个服务都有内存/进程上限(M-5)。
- MySQL 里有两个库:`chatapp`(Django)与 `chatapp_im`(imserver),账号分离。
- 聊天走自建 IM(唯一后端,腾讯云 IM 分支已于 2026-11-08 删除)。

## 2. 前置条件

| 项 | 要求 |
|---|---|
| 系统 | Linux + systemd;阿里云 Linux 3 / RHEL 系 / Ubuntu 均可 |
| 权限 | root(`sudo`) |
| 资源 | 最低 2C2G;建议 2C4G 以上(imserver 首次编译吃内存) |
| 磁盘 | ≥ 10 GB 可用 |
| 网络 | 能访问 Docker Hub / PyPI / npm(脚本默认走阿里云 pip 与 npmmirror) |
| 域名 | 启用 HTTPS 时,`A` 记录已指向本机公网 IP,且 80 端口可从公网访问 |
| 端口 | 80、443 未被占用(宝塔 nginx、其他站点都会冲突) |

> 2C2G 上**不建议在服务器编译 imserver**。可先在本地
> `docker build -t imserver:local imserver && docker save -o imserver.tar imserver:local`,
> 上传后用 `--imserver-image-tar` 直接加载。

## 3. 一条命令

```bash
# 在仓库根目录
sudo bash deploy/oneclick.sh --domain chat.example.com --email ops@example.com \
    --admin-phone 13800138000 --allow-dev-sms
```

> 最后两个参数不是可选的:公网/TLS 部署必须给 `--admin-phone`;
> 没接真实短信商时还必须显式加 `--allow-dev-sms` 才会写入 `SMS_DEV_MODE=1`。
> 不加 `--allow-dev-sms` 时 `SMS_DEV_MODE=0`,站点将无法用短信登录(这是有意的默认值)。

脚本会依次完成:

1. 检查系统/端口/域名解析;缺 Docker 则安装 Docker CE + compose 插件;
2. 生成密钥(`SECRET_KEY`、数据库口令、IM JWT/HMAC、媒体签名密钥、管理员口令),
   写入 `/opt/chatapp/secrets/`(权限 600);
3. 渲染 `docker-compose.yml`、nginx 配置、应用 `.env`、MySQL 初始化 SQL;
4. 构建后端、Web、imserver 镜像;
5. 启动 MySQL/Redis → 建库 → `migrate` → 启动 web/worker/imserver → 启动 nginx;
6. 创建运营管理员(`/ops/` 用);
7. 启用 HTTPS 时:certbot 签发证书 → 切 nginx 到 443 → 重启 web/worker →
   安装每日续期 systemd timer;
8. 健康检查 `/healthz`、`/api/v1/health`、`/api/v1/readyz`。

只跑 HTTP(IP 或域名):

```bash
sudo bash deploy/oneclick.sh --no-tls
# 或显式指定对外地址
sudo bash deploy/oneclick.sh --no-tls --public-url http://203.0.113.10
```

只生成配置、不装 Docker/不启动(可在本地预演,不需要 root):

```bash
bash deploy/oneclick.sh --render-only --no-tls --app-dir ./deploy-render
```

> 预览目录里有真实密钥(`secrets/values.env`),已加入 `.gitignore`;核对完请
> `rm -rf deploy-render`(L-1)。

## 4. 参数

| 参数 | 说明 |
|---|---|
| `--domain <域名>` | 站点域名;HTTPS 模式必填 |
| `--email <邮箱>` | Let's Encrypt 到期通知;HTTPS 模式必填 |
| `--no-tls` | 只跑 HTTP |
| `--public-url <URL>` | 手动指定对外地址(HTTP 模式) |
| `--app-dir <目录>` | 部署目录,默认 `/opt/chatapp` |
| `--http-port <端口>` | 宿主机 HTTP 端口,默认 80;HTTPS 模式必须是 80 |
| `--https-port <端口>` | 宿主机 HTTPS 端口,默认 443;HTTPS 模式固定 443 |
| `--staging` | 用 Let's Encrypt staging 签证书,避免正式环境限流 |
| `--render-only` | 只渲染配置,不安装/不启动 |
| `--rotate-secrets` | 重新生成应用密钥与数据库口令(会踢下线;root 口令不变) |
| `--skip-docker-install` | 不自动安装 Docker |
| `--no-build` | 跳过镜像构建,直接用现有镜像 |
| `--imserver-image-tar <文件>` | 加载本地 `docker save` 的 imserver 镜像,跳过服务器编译 |
| `--allow-dev-sms` | 允许写入 `SMS_DEV_MODE=1`(固定验证码 `123456`)。**默认不写**;TLS 或非回环地址的部署必须显式加它,否则脚本直接拒绝 |
| `--admin-phone <手机号>` | 运营管理员手机号;公网/TLS 部署**必填**(仅 `--render-only` 本地预览允许占位 `13900000000`) |
| `--admin-password <口令>` | 管理员口令(仅首次创建时生效) |
| `--pip-index-url <URL>` | pip 镜像,默认阿里云 |
| `--npm-registry <URL>` | npm 镜像,默认 npmmirror |
| `--docker-repo-url <URL>` | RHEL 系 Docker CE 仓库,默认阿里云 |

## 5. 生成的文件

```
/opt/chatapp/
├── docker-compose.yml          # 由模板渲染,含绝对路径
├── .env                        # compose 插值(600,含数据库口令)
├── secrets/
│   ├── values.env              # 所有密钥的唯一事实来源(600,务必备份)
│   ├── chatapp.env             # Django 环境变量(600)
│   ├── imserver.env            # imserver 环境变量(600)
│   └── admin.txt               # 运营管理员账号口令(600)
├── mysql/init/01-databases.sql # 建 chatapp_im 与 imserver 账号(幂等)
├── nginx/
│   ├── http.conf               # HTTP 模板渲染结果
│   ├── https.conf              # HTTPS 模板渲染结果
│   └── conf.d/default.conf     # 当前生效的配置(挂进 nginx 容器)
├── bin/
│   ├── chatapp                 # 运维命令(软链到 /usr/local/bin/chatapp)
│   ├── maintenance.sh          # 每日维护(systemd timer 04:00)
│   └── certbot-renew.sh        # 证书续期
├── backups/                    # chatapp backup 的默认输出(700/600)
└── logs/                       # 预留
```

数据卷(显式钉住名字,`docker volume ls` 可见):

| 卷 | 内容 |
|---|---|
| `chatapp_mysql` | MySQL 数据(含 `chatapp`、`chatapp_im`) |
| `chatapp_redis` | Redis AOF |
| `chatapp_static` | `collectstatic` 产物(web 写、nginx 读) |
| `chatapp_media` | 资料图/广场图/聊天图/语音 |
| `chatapp_certs` | Let's Encrypt 证书与续期配置 |
| `chatapp_acme` | ACME HTTP-01 webroot |

## 6. 部署后必做

1. **放行端口**:云厂商安全组 + 本机 firewalld 放行 TCP 80/443
   (脚本只会处理 firewalld,安全组要在控制台点)。
2. **登录 `/ops/`**:用 `secrets/admin.txt` 里的账号;首次登录会要求绑定 TOTP。
3. **审核照片**:`AUTO_APPROVE=0`,新上传资料图是 `pending`,去 `/ops/photos/` 审核。
4. **短信**:默认 `SMS_DEV_MODE=0`(未接短信商时无法登录);封闭测试需在部署时
   显式加 `--allow-dev-sms`,验证码固定 `123456`。**运营账号(staff/superuser)不能
   走短信登录**(接口返回 403),只能从 `/ops/` 用账号口令 + TOTP 登录;
   封闭测试确需用运营账号登 App 时,在 `chatapp.env` 设 `SMS_ALLOW_STAFF_LOGIN=1`
   并重启 web/worker(生产必须保持 0)。
5. **发版**:Web 版本由 `web/package.json` 决定,脚本会把它写进
   `MIN_APP_VERSION`/`LATEST_APP_VERSION`;APK 需另行构建并放到站点可下载路径。
6. **确认定时任务**:`systemctl list-timers 'chatapp-*'` 应看到
   `chatapp-certbot-renew.timer`(仅 HTTPS)与 `chatapp-maintenance.timer`
   (候选池随机键 / **访客记录保留期** / 聊天媒体过期 / 孤儿文件 / 磁盘报表)。

## 7. 日常运维

脚本会安装 `chatapp` 命令(指向 `/opt/chatapp/bin/chatapp`):

```bash
chatapp status                 # docker compose ps
chatapp logs                   # 全部日志;chatapp logs web 只看后端
chatapp restart                # 重启 web/worker/imserver/nginx
chatapp migrate                # 执行迁移
chatapp manage <args...>       # 如 chatapp manage createsuperuser
chatapp shell                  # Django shell
chatapp backup                 # 备份 MySQL(两个库)到 backups/
chatapp restore <文件.sql.gz>  # 恢复(需输入 yes)
chatapp backup-media           # 打包媒体卷
chatapp cert-renew             # 立即续期一次证书
chatapp url                    # 打印站点地址
```

不经过封装也可以直接用 compose:

```bash
cd /opt/chatapp
docker compose ps
docker compose logs -f --tail=200 web
docker compose restart web worker
```

### 更新代码

```bash
cd /path/to/repo
git pull
sudo bash deploy/oneclick.sh --domain chat.example.com --email ops@example.com
```

重跑是幂等的:复用已有密钥与数据卷,只重建镜像、执行迁移、滚动重启。
如果只想更新某一层:

```bash
cd /opt/chatapp
docker compose build web && docker compose up -d --no-deps web
docker compose up -d --no-deps --force-recreate nginx   # 让 nginx 重新解析 web 的 IP
```

> **从 2026-11-03 之前的版本升级**(镜像改为非 root `uid 10001`):已有的
> `chatapp_media` / `chatapp_static` 卷属主还是 root,web 会以
> `Permission denied` 启动失败。先执行一次:
> `docker run --rm -v chatapp_media:/m -v chatapp_static:/s alpine chown -R 10001:10001 /m /s`
> (新建部署不需要,卷会继承镜像里的属主)。

## 8. 备份与恢复

```bash
chatapp backup /root/chatapp-$(date +%F).sql.gz
chatapp backup-media /root/chatapp-media-$(date +%F).tar.gz
```

> 备份含手机号、密码哈希、聊天记录与图片元数据。`chatapp backup` 用 `umask 077`
> 落盘并 `chmod 600`(M-4);仍建议:存到加密卷或 `age`/`gpg` 加密后再离线保存,
> 保留期按合规要求(建议 ≥30 天、≤180 天),不要留在 Web 可访问目录。

恢复前先停应用,避免写入:

```bash
cd /opt/chatapp
docker compose stop web worker
chatapp restore /root/chatapp-2026-10-29.sql.gz
docker compose start web worker
```

`secrets/values.env` 必须单独备份:数据库 root 口令只存在这里,丢了无法从数据卷反推。

## 9. HTTPS 与证书

- 首次签发用 webroot:nginx 的 80 端口先把 `/.well-known/acme-challenge/`
  指向共享卷 `chatapp_acme`,certbot 写入 challenge,再签发。
- 证书在卷 `chatapp_certs` 的 `/etc/letsencrypt/live/<域名>/`。
- 续期:`chatapp-certbot-renew.timer` 每天 03:17(带随机延迟)执行
  `certbot renew` + `nginx -s reload`;日志看 `journalctl -u chatapp-certbot-renew`。
- 手动续期:`chatapp cert-renew`。
- 换域名:用新域名重跑脚本;旧证书目录会保留,不会自动删除。

每日维护由 `chatapp-maintenance.timer`(04:00)执行,内容包括
`refresh_shuffle_keys`、`purge_profile_visits --apply`(访客记录 90 天保留期)、
`im_media_cleanup --apply`、`media_cleanup --apply`、`media_disk_report --fail-over`。
磁盘超 `MEDIA_DISK_WARN_MB` 时服务会以退出码 1 结束(看
`journalctl -u chatapp-maintenance`),但不会自动告警到群机器人。

## 10. 常见问题

| 现象 | 排查 |
|---|---|
| 端口 80/443 被占用 | 先停宝塔 nginx 或其他站点;测试可用 `--http-port 8080 --https-port 8443`(仅 HTTP) |
| certbot 失败 | 域名是否解析到本机、安全组是否放行 80、是否触发 Let's Encrypt 限流;可先加 `--staging` 试 |
| `imserver` 构建 OOM/太慢 | 本地构建后 `docker save`,用 `--imserver-image-tar` 加载 |
| `web` 启动失败 | `chatapp logs web`;常见是 `.env` 缺 `SECRET_KEY`/`IM_MEDIA_SIGN_SECRET`,或 MySQL 口令不一致 |
| 502 | `chatapp status`;web/imserver 是否 healthy;nginx 是否在 web 重建后没重启 |
| 聊天图 403 | 检查 `IM_MEDIA_SIGN_SECRET` 在 Django 与 imserver 是否一致、`IM_MEDIA_PREFIX` 是否等于 `MEDIA_BASE_URL + /media/chat/` |
| 所有请求都像来自 127.0.0.1 | nginx 是否设置 `X-Real-IP`;`TRUSTED_PROXY_IPS` 是否包含 nginx 的固定地址 `172.28.0.10` |
| 聊天全挂 / `user_sig` 503 | 从 web 容器 `curl http://imserver:9101/internal/healthz`:403 说明 `IM_INTERNAL_ALLOW` 没包含 compose 子网(H-1);200 再看 HMAC 密钥是否两边一致 |
| 登录一直提示版本过低 | `MIN_APP_VERSION` 与 Web/APK 版本不一致;改 `.env` 后重启 web |

## 11. 与宝塔现网的关系

现网(`https://chat.shiliu153.cn`)是 **宝塔 + supervisor + 本机 MySQL/Redis + imserver 容器**,
本文这套是 **全 Docker Compose**。两者:

- **不要在同一台机器同时占用 80/443**;
- 数据格式相同(MySQL 库名/表结构一致),可以用 `mysqldump` 在两边迁移;
- 密钥变量名一致(`IM_SELF_SECRET` = `IM_JWT_SECRET` 等),但值要各自生成,不要混用;
- 现网升级仍按 `docs/ops/imserver.md` 与 `README.md` 的宝塔流程走,不要直接套用本脚本。

## 12. 安全说明

- MySQL/Redis/Django/imserver 都**没有发布宿主机端口**,只经 nginx 访问;
- 网络分段:`backend`(internal)只承载 MySQL/Redis,nginx/certbot 无法访问它们(M-6);
- 容器权限:web/worker/imserver 以非 root 运行,`cap_drop: ALL` + `no-new-privileges`;
  每个服务有 `mem_limit`/`pids_limit`,单服务失控不会拖垮 2C2G 整机(M-5);
- `secrets/` 与 `.env` 均为 600,`values.env` 是唯一需要离线备份的密钥文件;
- 生产默认 `DEBUG=0`、`AUTO_APPROVE=0`、`OPS_OTP_REQUIRED=1`、`HTTPS_ENABLED=1`、
  `SMS_DEV_MODE=0`、`SMS_ALLOW_STAFF_LOGIN=0`;
- 仍存在的已知风险:
  - 未接真实短信商时,封闭测试必须显式 `--allow-dev-sms`(固定验证码);
  - 聊天图片/语音没有机器审核,只有 `/ops/` 人工抽审;
  - 媒体存本地磁盘,未接对象存储/CDN;
  - nginx 容器仍是 root master(绑 80/443 需要),未改 `nginx-unprivileged`(改动大,记录为已知项);
  - 备份文件未自动加密,需运维按 §8 自行加密/离线保存;
  - Redis 未设 `requirepass`(imserver 的 `parse_redis_url` 尚不支持 AUTH),
    靠网络隔离兜底,后续接口令需要两边同时改。
