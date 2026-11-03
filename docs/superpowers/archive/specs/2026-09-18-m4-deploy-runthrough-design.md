# M4 部署·第一步:服务器跑通(设计)

日期:2026-09-18 · 状态:设计已获用户认可(对话确认:宝塔全托管 / 数据整体搬迁 / deploy key 上线通道)
关联:`2026-09-12-backend-standardization-design.md`(第 3 期「部署形态」)、`2026-09-09-dating-app-mvp-design.md`(M4 上线)

## 1. 背景与目标

服务器已就位:阿里云轻量应用服务器 2C2G(中国大陆,`<SERVER_IP>`),Alibaba Cloud Linux 3(`dnf` + `firewalld`),swap 1G;用户按宝塔路线已装:宝塔面板(端口 <PANEL_PORT>)、nginx 1.30.5、MySQL 8.0.45、Redis 7.4.11、进程守护管理器;Python 3.11.13 与 git 由 dnf 安装;80 端口外网可达。

现状约束:**无域名、ICP 备案进行中** → 本阶段以 `http://<SERVER_IP>`(IP + 80)跑通;域名/HTTPS 切换属后续阶段。短信、内容安全、COS 未接真,维持开发期开关。

**目标(本阶段验收)**:后端全栈(Django + Celery + MySQL + Redis + nginx)在服务器跑通,模拟器连服务器走完核心链路;建立「本地 push → 服务器 pull → 面板重启」更新通道;补齐标准化第 3 期欠账(`/readyz`、`STATIC_ROOT`、gunicorn 依赖)。

**非目标(后续阶段)**:域名/HTTPS/备案切换、短信/内容安全/COS 接真、商店上架、iOS 打包、监控告警、压测。

**路线决策**:全宝塔托管(用户选定)。与标准化第 3 期的差异:**systemd 由宝塔「进程守护管理器」替代**(同目标:开机自启、崩溃拉起);gunicorn、`/readyz`、部署文档照旧承接。2C2G 上不叠加 systemd 托管的应用进程,避免两套进程管理。

## 2. 架构

```
模拟器 ──HTTP :80──> nginx(宝塔站点 + 反向代理)
                      ├─ /api /admin /ops ──> gunicorn 127.0.0.1:8000 ──> Django(python3.11 venv)
                      ├─ /static/ ──> /www/wwwroot/chatapp/chatapp/staticfiles/(collectstatic 产物)
                      └─ /media/  ──> /www/wwwroot/chatapp/chatapp/media/(用户照片)
MySQL 8.0.45(127.0.0.1:3306)← Django / Celery
Redis 7.4.11(127.0.0.1:6379)← 缓存/限流/presence/任务队列(BROKER)
Celery worker ──> 腾讯云 IM REST(异步副作用,与开发一致)
```

进程托管(宝塔「进程守护管理器」,两条):

| 名称 | 启动目录 | 命令 |
|---|---|---|
| chatapp-web | `/www/wwwroot/chatapp/chatapp` | `/www/wwwroot/chatapp-venv/bin/gunicorn config.wsgi:application -b 127.0.0.1:8000 -w 2 --timeout 120` |
| chatapp-celery | `/www/wwwroot/chatapp/chatapp` | `/www/wwwroot/chatapp-venv/bin/celery -A config worker -l info --concurrency=1` |

⚠️ 启动目录必须是 `manage.py` 所在层(`chatapp/chatapp`),否则 `config.wsgi`/`-A config` 找不到;`--timeout 120` 是为慢速大图上传(默认 30s 会掐断请求)。

## 3. 代码与目录

- 仓库(私有):服务器以 **deploy key(只读)** 从 GitHub 拉取 `yourname/chatapp`。
  - 服务器生成专用密钥 `/root/.ssh/chatapp_deploy`;公钥由用户添加到 GitHub 仓库 Settings → Deploy keys(read-only)。
  - 服务器 `~/.ssh/config`:`Host github.com → HostName ssh.github.com, Port 443, IdentityFile /root/.ssh/chatapp_deploy`(国内到 GitHub 22 端口常不通,走 443;与本机现有配置同思路)。
- 代码路径:`/www/wwwroot/chatapp`(= 站点根);venv:`/www/wwwroot/chatapp-venv`(仓库外,不污染 git 工作区)。
- **更新流程**(手动,写入部署手册):
  1. 本地 `git push`;2. 服务器 `git -C /www/wwwroot/chatapp pull`;
  3. 依赖有变 → `venv/bin/pip install -r chatapp/requirements.txt`;
  4. 迁移有变 → `venv/bin/python chatapp/manage.py migrate`;
  5. 静态有变 → `venv/bin/python chatapp/manage.py collectstatic --noinput`;
  6. 面板重启两条进程。

## 4. nginx 站点(宝塔「网站」)

- 新建站点:域名栏填 `<SERVER_IP>`(若面板拒纯 IP:用占位域名,default server 仍应答 IP);站点根目录指向 `/www/wwwroot/chatapp`。
- 反向代理(面板「反向代理」功能):目标 `http://127.0.0.1:8000`。
- 站点配置文件补充(面板「配置文件」直接改):
  - `client_max_body_size 60m;`(动态最多 9 图 × 5MB;宝塔默认值因版本而异,显式声明最稳,否则 413);
  - `location /static/ { alias /www/wwwroot/chatapp/chatapp/staticfiles/; }`
  - `location /media/  { alias /www/wwwroot/chatapp/chatapp/media/; }`
- `/api/v1/health`、`/api/v1/readyz` 走反代直达 Django,不加额外规则。

## 5. MySQL / Redis / .env

- 面板「数据库」:建库 `chatapp`(utf8mb4)+ 专用账号 `chatapp`(随机口令;业务不用 root)。
- Redis 复用已装实例(仅 127.0.0.1;测试期不设口令)。
- `.env`(服务器 `chatapp/.env`,权限 600,不入 git):

| 键 | 值 | 说明 |
|---|---|---|
| SECRET_KEY | 新随机生成 | 与开发不同;旧 JWT 自然失效(重登即可) |
| DEBUG | 0 | 生产形态 |
| ALLOWED_HOSTS | <SERVER_IP>,127.0.0.1 | 本机 curl 也合法 |
| DB_NAME / DB_USER / DB_PASSWORD | chatapp / chatapp / \<生成\> | |
| DB_HOST / DB_PORT | 127.0.0.1 / 3306 | |
| DB_SSL_DISABLED | 1 | 本机连接无 TLS |
| REDIS_URL | redis://127.0.0.1:6379/0 | |
| BROKER_URL | redis://127.0.0.1:6379/1 | ⚠️ 不要用 `CELERY_` 前缀键 |
| IM_SDKAPPID / IM_SECRETKEY | 与开发一致 | 同一个 IM 应用 |
| SMS_DEV_MODE | 1 | 固定码 123456(测试期) |
| AUTO_APPROVE | 1 | 照片免审(测试期;上线阶段关并接内容安全) |
| MEDIA_BASE_URL | http://<SERVER_IP> | IM 头像同步用绝对地址 |
| LOG_FILE | /www/wwwlogs/chatapp/app.log | 轮转 5MB×3 |

## 6. 数据搬迁(整体搬迁,用户选定)

1. 本地导出:`mysqldump --single-transaction --default-character-set=utf8mb4 chatapp_dev | gzip > chatapp_dev.sql.gz`(本地 MySQL 8 → 服务器 8.0.45,同大版本);
2. scp 上传 → 服务器导入 `mysql -u chatapp -p chatapp < …`(或面板导入);
3. `media/` 打包(`tar czf media.tar.gz media`,本地 `chatapp/` 下)→ scp → 解到 `/www/wwwroot/chatapp/chatapp/media/`;
4. 导入后跑 `migrate`(防御,应为 no-op)与 `collectstatic`;
5. **IM 头像 URL 刷新**:库里照片与腾讯 IM 侧头像地址仍指向开发地址(`10.0.2.2` / `127.0.0.1`);对全部有已过审照片的用户执行一次 `sync_profile(uid, "avatar")`(一次性 shell,精确命令在计划内);
6. 校验:`u8/u12/u39` 等账号在;照片可经 `http://<SERVER_IP>/media/…` 访问。

为什么搬迁:腾讯 IM 侧聊天记录与账号是 `u{id}` 跨栈约定,新库重造会串号(设计对话已确认)。

## 7. 本地代码改动(部署前完成,TDD)

| 项 | 内容 |
|---|---|
| `/api/v1/readyz` | 与现有 `/api/v1/health` 同处新增(命名以现状为准;**标准化第 3 期的 `/healthz` 命名作废**,存活检查沿用 `/api/v1/health`)。探 MySQL(`SELECT 1`)+ Redis(读写往返),任一挂回 503 且 JSON 带各探针状态;不鉴权(同 health)。用例:依赖全通 200 / 单项故障 503 |
| STATIC_ROOT | 设为 `BASE_DIR/"staticfiles"`;urls.py 的 media `static()` 仅 DEBUG 生效(现状即如此),生产由 nginx 直出,无需改 |
| gunicorn | 加入 `chatapp/requirements.txt`(Windows 上装而不用,无副作用;保持单一依赖文件) |
| 其余 | 不动。HTTPS 安全项(CSRF/HSTS/`SECURE_PROXY_SSL_HEADER`)等域名阶段再加 |

纪律:后端全量测试绿;`flutter analyze` 零告警(本阶段不动前端代码)。

## 8. 验收(手测清单)

1. 服务器本机与外部:`curl http://127.0.0.1/api/v1/health`、`/api/v1/readyz` 经 nginx 均 200;
2. 模拟器装 `--dart-define=API_BASE=http://<SERVER_IP>/api/v1` 的新包:登录(123456)→ 发现卡有照片 → u8×u12 互滑配对(双方灰条)→ 聊天收发 → 消息页绿点 → 广场(发/赞/评)→ 我的页正常;
3. ops 台(浏览器 `http://<SERVER_IP>/ops/`)可登录、举报队列可见;admin 同理;
4. 面板:两条进程在线、日志可见;重启 web 进程后服务自动恢复;
5. (可选)依赖演练:停 Redis → `/api/v1/readyz` 503 → 起 Redis → 200。

## 9. 风险与对策

| 风险 | 对策 |
|---|---|
| 2C2G 内存紧(MySQL ~400M + 面板 ~200M + 2×gunicorn + celery ≈ 1.2G) | swap 已备;观察 `free -h`;紧张时 gunicorn 降 1 worker / 调 MySQL buffer pool |
| 宝塔站点不接受纯 IP 域名 | 占位域名建站(default server 仍应答 IP),或手工改 server_name |
| 服务器 → GitHub 22 端口不通 | 已按 443(`ssh.github.com`)配置;deploy key 走 SSH |
| 未备案 IP:80 若被拦 | 退路:站点加 `listen 8080` + 阿里云控制台放行 |
| 本地与服务器数据分叉 | 测试期服务器数据即测试环境;本地继续开发不冲突(代码走 git,数据不回流) |
| 面板暴露公网 | 测试期接受;上线阶段统一做面板加固(强口令/SSL/白名单) |

## 10. 后续阶段(另立项)

域名 + 备案完成 → HTTPS(BT 证书)+ 安全加固(关 SSH 密码登录、HSTS/`CSRF_TRUSTED_ORIGINS` 复查)→ 短信接真 → 内容安全接真(`AUTO_APPROVE=0`)→ 图片 COS/OSS → 备份策略(面板计划任务 + 云快照)→ 商店上架材料。
