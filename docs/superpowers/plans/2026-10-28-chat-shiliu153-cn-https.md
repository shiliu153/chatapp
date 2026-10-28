# 交友 App 切换到 `chat.shiliu153.cn`（HTTPS）执行任务

> 状态：**已完成**（2026-10-28 15:00–15:34 生产已切换，脚本验收 + 用户真机手测均通过，执行记录见 §12）。
> 目标：把交友 App 从 `http://47.116.114.110` 切到 `https://chat.shiliu153.cn`，并顺带完成安全整改的上线动作。
> 影响面：交友 App（Web/App/API/IM/媒体）；**不影响** `shiliu153.me`、`shiliu153.cn` 的简历站和 `wb.shiliu153.me`。

## 0. 现状与结论（2026-10-28 只读核对）

| 项 | 现状 |
|---|---|
| 域名 | `shiliu153.cn` / `.me` 已解析到 `47.116.114.110`，`.cn` 已备案 |
| 证书 | `shiliu153.me`、`shiliu153.cn`、`wb.shiliu153.me` 均有证书；**SAN 不含 `chat.` 子域** |
| 443 | `.me`/`.cn` 都反代到简历站 `127.0.0.1:8001`；`wb` 反代 `:7863` |
| 交友 App | 只有 `47.116.114.110:80` vhost，根目录 `/www/wwwroot/chatapp-web`，API 反代 `:8000` |
| 自建 IM | 容器 `imserver:72ae6ea`（旧镜像），`/www/server/imserver`，env 在 `imserver.env` |
| 进程 | supervisord 管理 `chatapp-web`、`chatapp-celery`；配置 `/etc/supervisor/supervisord.conf` |
| 生产 `.env` | `DEBUG=0`；`IM_MEDIA_SIGN_SECRET` 已配；`AUTO_APPROVE`/`OPS_OTP_REQUIRED`/`HTTPS_ENABLED` 未写（走新代码默认） |

结论：差的不是“买域名/证书”，而是**给交友 App 一个独立子域 + 443 vhost + 改 Django/IM 的地址**。

## 1. 前置：先把安全整改代码上线（若还没做）

> 这一步不做，后面的 H3/H4 不会生效；`im_sync_pairs` 也会因 `im_pair` 表不存在而失败。

- [x] 备份：
  ```bash
  cd /www/wwwroot/chatapp
  cp -a chatapp/.env chatapp/.env.bak.$(date +%Y%m%d-%H%M)
  cp -a /www/server/imserver/imserver.env /www/server/imserver/imserver.env.bak.$(date +%Y%m%d-%H%M)
  cp -a /www/server/imserver/.env /www/server/imserver/.env.bak.$(date +%Y%m%d-%H%M)
  cp -a /www/server/panel/vhost/nginx/47.116.114.110.conf /root/47.116.114.110.conf.bak.$(date +%Y%m%d-%H%M)
  mysqldump -u chatapp -p chatapp_im im_message im_user > /root/chatapp_im_backup_$(date +%Y%m%d-%H%M).sql
  ```
  （`im_pair` 表此时还不存在，别放进第一条备份命令；迁移后再补一份全库备份。）
- [x] 推送新代码到 origin（本地仓库根目录）：
  ```bash
  git push origin fix/security-remediation
  ```
- [x] 服务器拉新代码（当前在 `feat/im-voice-messages`，有未跟踪的 `.env.bak` 等，不影响 checkout）：
  ```bash
  cd /www/wwwroot/chatapp
  git fetch origin
  git checkout fix/security-remediation
  git pull --ff-only origin fix/security-remediation
  /www/wwwroot/chatapp-venv/bin/pip install -r chatapp/requirements.txt -q
  cd chatapp && /www/wwwroot/chatapp-venv/bin/python manage.py migrate
  ```
  若服务器不能直连 GitHub，用之前的 bundle 方式：
  ```bash
  # 本地
  git bundle create chatapp-security.bundle fix/security-remediation
  scp chatapp-security.bundle root@47.116.114.110:/root/
  # 服务器
  cd /www/wwwroot/chatapp && git fetch /root/chatapp-security.bundle fix/security-remediation
  git checkout -B fix/security-remediation FETCH_HEAD
  ```
- [x] 构建/加载 imserver 新镜像（本地构建后传服务器，2C2G 不在服务器编译）：
  ```bash
  # 本地仓库根目录
  docker build -t imserver:<new-sha> imserver
  docker save imserver:<new-sha> -o imserver-<new-sha>.tar
  scp imserver-<new-sha>.tar root@47.116.114.110:/root/
  # 服务器
  docker load -i /root/imserver-<new-sha>.tar
  sed -i 's#^IMSERVER_IMAGE=.*#IMSERVER_IMAGE=imserver:<new-sha>#' /www/server/imserver/.env
  cd /www/server/imserver
  docker compose run --rm imserver --migrate   # 显式迁移，entrypoint 不自动跑
  docker compose up -d
  ```
- [x] 回填配对（**必须在 imserver 迁移后立刻跑**）：
  ```bash
  cd /www/wwwroot/chatapp/chatapp
  /www/wwwroot/chatapp-venv/bin/python manage.py im_sync_pairs
  ```
- [x] 重启 Web/Celery：
  ```bash
  /www/server/panel/pyenv/bin/supervisorctl -c /etc/supervisor/supervisord.conf restart chatapp-web chatapp-celery
  ```
- [x] 冒烟：`curl -s http://47.116.114.110/api/v1/health` 200；两个已配对测试号互发消息正常；未配对发送 40302。

## 2. DNS：新增 `chat.shiliu153.cn`

- [x] 加 A 记录（阿里云 DNS API，复用现有 `/root/.profile_acme_env`）：
  ```bash
  set -a; . /root/.profile_acme_env; set +a
  aliyun alidns AddDomainRecord \
    --DomainName shiliu153.cn --RR chat --Type A --Value 47.116.114.110 --TTL 600 \
    --access-key-id "$ALI_KEY" --access-key-secret "$ALI_SECRET" --region cn-hangzhou
  ```
- [x] 验证解析：
  ```bash
  dig +short chat.shiliu153.cn    # 应返回 47.116.114.110
  ```

## 3. 证书：新签 `chat.shiliu153.cn`

现有证书 SAN 不含子域，不能复用。复用已跑通的 DNS-01 脚本：

- [x] 复制脚本并只改域名：
  ```bash
  cp /root/issue_cert_dns.py /root/issue_cert_dns_chat.py
  sed -i 's#^DOMAINS = .*#DOMAINS = ["chat.shiliu153.cn"]#' /root/issue_cert_dns_chat.py
  grep '^DOMAINS' /root/issue_cert_dns_chat.py
  ```
- [x] 签发：
  ```bash
  set -a; . /root/.profile_acme_env; set +a
  export ALI_KEY ALI_SECRET
  cd /www/server/panel && /www/server/panel/pyenv/bin/python -u /root/issue_cert_dns_chat.py
  ```
  首次可能失败（`_acme-challenge.chat` SERVFAIL）——新子域刚建 A 记录时权威 NS 有负缓存，
  等 5–10 分钟原样重跑即可（脚本会自行删掉旧 TXT）。
  记录输出里的 `保存路径`，正常是：
  ```
  /www/server/panel/vhost/letsencrypt/chat.shiliu153.cn/fullchain.pem
  /www/server/panel/vhost/letsencrypt/chat.shiliu153.cn/privkey.pem
  ```
- [x] 校验证书：
  ```bash
  openssl x509 -in /www/server/panel/vhost/letsencrypt/chat.shiliu153.cn/fullchain.pem \
    -noout -subject -ext subjectAltName
  # 应看到 DNS:chat.shiliu153.cn
  ```
- [x] 续期脚本（DNS-01，面板原生续期会被脚本置 `auth_tag=False`，必须自建 cron）：
  ```bash
  cp /root/renew_cert.sh /root/renew_cert_chat.sh
  sed -i 's#/www/server/panel/vhost/letsencrypt/shiliu153.me/fullchain.pem#/www/server/panel/vhost/letsencrypt/chat.shiliu153.cn/fullchain.pem#' /root/renew_cert_chat.sh
  sed -i 's#issue_cert_dns.py#issue_cert_dns_chat.py#g' /root/renew_cert_chat.sh
  sed -i 's#domains = \["shiliu153.me", "www.shiliu153.me"\]#domains = ["chat.shiliu153.cn"]#' /root/renew_cert_chat.sh
  sed -i 's#/var/log/profile-cert-renew.log#/var/log/chat-cert-renew.log#' /root/renew_cert_chat.sh
  chmod 755 /root/renew_cert_chat.sh
  (crontab -l 2>/dev/null; echo '5 3 1,16 * * /root/renew_cert_chat.sh >> /var/log/chat-cert-renew.log 2>&1') | crontab -
  ```

## 4. nginx：新建 443 vhost

- [x] 新建 `/www/server/panel/vhost/nginx/chat.shiliu153.cn.conf`（内容如下；`ssl_certificate` 用第 3 步实际路径）：
  ```nginx
  # 交友 App: chat.shiliu153.cn
  # 证书: ACME DNS-01, 见 /root/renew_cert_chat.sh

  server {
      listen 80;
      server_name chat.shiliu153.cn;

      location ^~ /.well-known/acme-challenge/ {
          root /www/wwwroot/chatapp-web;
          default_type "text/plain";
          access_log off;
      }
      location / { return 301 https://$host$request_uri; }
  }

  server {
      listen 443 ssl;
      http2 on;
      server_name chat.shiliu153.cn;

      ssl_certificate     /www/server/panel/vhost/letsencrypt/chat.shiliu153.cn/fullchain.pem;
      ssl_certificate_key /www/server/panel/vhost/letsencrypt/chat.shiliu153.cn/privkey.pem;
      ssl_protocols       TLSv1.2 TLSv1.3;
      ssl_ciphers         ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305;
      ssl_prefer_server_ciphers off;
      ssl_session_cache   shared:SSL:10m;
      ssl_session_timeout 10m;

      client_max_body_size 20m;
      root /www/wwwroot/chatapp-web;
      index index.html;

      # 安全头（静态页与反代响应都生效）
      add_header Strict-Transport-Security "max-age=3600; includeSubDomains" always;
      add_header X-Content-Type-Options "nosniff" always;
      add_header X-Frame-Options "DENY" always;
      add_header Referrer-Policy "same-origin" always;
      add_header Content-Security-Policy "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self' ws: wss:; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self';" always;

      # Django 静态
      location ^~ /static/ {
          alias /www/wwwroot/chatapp/chatapp/staticfiles/;
          expires 7d;
      }

      # 聊天媒体:先验签,再直出
      location ^~ /media/chat/ {
          auth_request /_im_media_auth;
          alias /www/wwwroot/chatapp/chatapp/media/chat/;
          expires 1h;
      }
      location = /_im_media_auth {
          internal;
          proxy_pass http://127.0.0.1:8000/api/v1/im/images/auth;
          proxy_pass_request_body off;
          proxy_set_header Content-Length "";
          proxy_set_header X-Original-URI $request_uri;
      }

      # 资料图/广场图公开直出
      location ^~ /media/ {
          alias /www/wwwroot/chatapp/chatapp/media/;
          expires 7d;
      }

      location ^~ /assets/ {
          expires 30d;
          add_header Cache-Control "public, immutable";
          # 本 location 有 add_header,必须重复安全头
          add_header Strict-Transport-Security "max-age=3600; includeSubDomains" always;
          add_header X-Content-Type-Options "nosniff" always;
          add_header X-Frame-Options "DENY" always;
          add_header Referrer-Policy "same-origin" always;
          add_header Content-Security-Policy "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self' ws: wss:; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self';" always;
      }
      location ^~ /fonts/ { expires 30d; }

      location = /index.html {
          add_header Cache-Control "no-store";
          add_header Strict-Transport-Security "max-age=3600; includeSubDomains" always;
          add_header X-Content-Type-Options "nosniff" always;
          add_header X-Frame-Options "DENY" always;
          add_header Referrer-Policy "same-origin" always;
          add_header Content-Security-Policy "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self' ws: wss:; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self';" always;
      }

      # 自建 IM: WebSocket / HTTP
      location /im/ws {
          proxy_pass http://127.0.0.1:9100;
          proxy_http_version 1.1;
          proxy_set_header Upgrade $http_upgrade;
          proxy_set_header Connection "upgrade";
          proxy_set_header Host $host;
          proxy_set_header X-Real-IP $remote_addr;
          proxy_set_header X-Forwarded-For $remote_addr;
          proxy_set_header X-Forwarded-Proto $scheme;
          proxy_read_timeout 300s;
      }
      location /im/api/ {
          proxy_pass http://127.0.0.1:9101;
          proxy_set_header Host $host;
          proxy_set_header X-Real-IP $remote_addr;
          proxy_set_header X-Forwarded-For $remote_addr;
      }

      # API / Django admin / 运营台
      location ~ ^/(api|admin|ops)(/|$) {
          proxy_pass http://127.0.0.1:8000;
          proxy_set_header Host $host;
          proxy_set_header X-Real-IP $remote_addr;
          proxy_set_header X-Forwarded-For $remote_addr;   # 覆盖客户端伪造值
          proxy_set_header X-Forwarded-Proto $scheme;
          proxy_read_timeout 120s;
      }

      location / { try_files $uri $uri/ /index.html; }

      access_log /www/wwwlogs/chat.shiliu153.cn.log;
      error_log  /www/wwwlogs/chat.shiliu153.cn.error.log;
  }
  ```
- [x] 测试并加载：
  ```bash
  nginx -t && nginx -s reload
  curl -I https://chat.shiliu153.cn/          # 200
  curl -I https://chat.shiliu153.cn/api/v1/health  # 200
  ```
  此时 Django 还是 `HTTPS_ENABLED=0`，但 nginx 已传 `X-Forwarded-Proto https`，API 应可用。

## 5. Django `.env`（`/www/wwwroot/chatapp/chatapp/.env`）

- [x] 改/加以下键（保留旧值用于回退）：
  ```dotenv
  ALLOWED_HOSTS=47.116.114.110,127.0.0.1,shiliu153.cn,www.shiliu153.cn,shiliu153.me,www.shiliu153.me,chat.shiliu153.cn
  MEDIA_BASE_URL=https://chat.shiliu153.cn
  IM_SELF_WS_URL=wss://chat.shiliu153.cn/im/ws
  IM_SELF_HTTP_URL=https://chat.shiliu153.cn/im/api
  HTTPS_ENABLED=1
  CSRF_TRUSTED_ORIGINS=https://chat.shiliu153.cn
  IM_MEDIA_SIGN_TTL=3600
  # 可选：办公/家庭出口 IP，填了就只允许该 IP 访问 /admin/ /ops/
  # OPS_ALLOWED_IPS=203.0.113.10
  ```
  注意：`IM_SELF_URL` 保持 `http://127.0.0.1:9101`（内部调用，不走域名）。
- [x] `IM_MEDIA_SIGN_TTL` 与 imserver 的 `IM_MEDIA_SIGN_TTL` 保持一致（都 3600）。

## 6. imserver：改媒体前缀 + 重写历史 URL

> 顺序很重要：**先改库里的旧 URL，再改 imserver 的 `IM_MEDIA_PREFIX` 并重启**，否则历史聊天图片/语音会因前缀不匹配而无法签名。

- [x] 备份 + 统计：
  ```bash
  mysql -u chatapp -p chatapp_im -e "
    SELECT COUNT(*) AS msgs FROM im_message WHERE body LIKE '%http://47.116.114.110/media/chat/%';
    SELECT COUNT(*) AS users FROM im_user WHERE avatar_url LIKE 'http://47.116.114.110/media/%';"
  ```
- [x] 重写（`chatapp_im` 库）：
  ```bash
  mysql -u chatapp -p chatapp_im -e "
    UPDATE im_message SET body = REPLACE(body,
      'http://47.116.114.110/media/chat/',
      'https://chat.shiliu153.cn/media/chat/')
    WHERE body LIKE '%http://47.116.114.110/media/chat/%';
    UPDATE im_user SET avatar_url = REPLACE(avatar_url,
      'http://47.116.114.110/media/',
      'https://chat.shiliu153.cn/media/')
    WHERE avatar_url LIKE 'http://47.116.114.110/media/%';"
  ```
- [x] 改 `/www/server/imserver/imserver.env`：
  ```dotenv
  IM_ALLOWED_ORIGINS=https://chat.shiliu153.cn,http://47.116.114.110
  IM_MEDIA_PREFIX=https://chat.shiliu153.cn/media/chat/
  IM_MEDIA_SIGN_TTL=3600
  IM_SEND_PER_MINUTE=120
  ```
- [x] 重启：
  ```bash
  cd /www/server/imserver && docker compose up -d
  curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:9101/internal/readyz  # 200
  ```

## 7. 重启 Web/Celery + IP vhost 收口

- [x] 重启：
  ```bash
  /www/server/panel/pyenv/bin/supervisorctl -c /etc/supervisor/supervisord.conf restart chatapp-web chatapp-celery
  ```
- [x] 验证 Django 不再报配置错误：
  ```bash
  cd /www/wwwroot/chatapp/chatapp
  /www/wwwroot/chatapp-venv/bin/python manage.py check --deploy
  # 预期只剩 security.W021(HSTS preload,故意不默认开)
  ```
- [x] 把 IP vhost 收口成 301（**确认新 APK 已发出后再做**；旧 APK 的 `ws://47...` 会失效）：
  ```bash
  # 备份后，把 47.116.114.110.conf 的 server{} 主体替换为：
  # server { listen 80; server_name 47.116.114.110; return 301 https://chat.shiliu153.cn$request_uri; }
  nginx -t && nginx -s reload
  ```

## 8. 客户端发布

- [x] App 重新打包（旧 APK 指向 HTTP IP，切域名后 IM 会断）：
  ```bash
  cd app
  # 先把 pubspec.yaml 版本从 1.0.0 升到 1.0.1（build number +1）
  ../flutter/bin/flutter.bat build apk --release \
    --dart-define=API_BASE=https://chat.shiliu153.cn/api/v1
  scp build/app/outputs/flutter-apk/app-release.apk \
    root@47.116.114.110:/www/wwwroot/chatapp-web/chatapp-1.0.1.apk
  ```
- [x] 更新 `.env`：
  ```dotenv
  MIN_APP_VERSION=1.0.1
  LATEST_APP_VERSION=1.0.1
  APP_DOWNLOAD_URL=https://chat.shiliu153.cn/chatapp-1.0.1.apk
  ```
  然后重启 `chatapp-web`。旧 App 启动时会被 `/app/config` 拦下。
- [x] Web：`VITE_API_BASE=/api/v1`（同源），**不需要重新构建**；直接访问 `https://chat.shiliu153.cn/` 即可。若之前有 IP 书签，301 会带过去。

## 9. 验收清单

- [x] `dig +short chat.shiliu153.cn` → `47.116.114.110`
- [x] `curl -I http://chat.shiliu153.cn` → `301 https://chat.shiliu153.cn/...`
- [x] `curl -I https://chat.shiliu153.cn/` → 200，且含 `strict-transport-security` / `x-frame-options` / `content-security-policy`
- [x] `curl -I https://chat.shiliu153.cn/api/v1/health` → 200
- [x] `curl -I https://chat.shiliu153.cn/media/chat/<某图>` 无签名 → 403；带 `?e=&s=` → 200
- [x] Web：登录 → 发现 → 配对 → 聊天（wss）→ 发图/语音 → 刷新历史图片仍可看
- [ ] App：新 APK 登录 → 聊天（wss）→ 杀进程重进 → 历史/图片正常（**待真机**）
- [x] H3：A 手机登录后，B 手机再登录，A 的 WS 重连收到 `40101`
- [x] H4：两个未配对账号发消息 → `40302`；配对后正常
- [x] 后台：`https://chat.shiliu153.cn/ops/` 登录 → 首次要求绑定 TOTP → 绑定后可进
- [x] 旧图/旧语音：随机抽 5 条历史消息，图片/语音可加载（验证第 6 步 URL 重写）
- [x] `manage.py check --deploy` 只剩 W021

## 10. 回退

- [ ] 恢复 `.env` / `imserver.env` / nginx vhost 备份：
  ```bash
  cp -a /www/wwwroot/chatapp/chatapp/.env.bak.<时间> /www/wwwroot/chatapp/chatapp/.env
  cp -a /www/server/imserver/imserver.env.bak.<时间> /www/server/imserver/imserver.env
  cp -a /root/47.116.114.110.conf.bak.<时间> /www/server/panel/vhost/nginx/47.116.114.110.conf
  nginx -t && nginx -s reload
  /www/server/panel/pyenv/bin/supervisorctl -c /etc/supervisor/supervisord.conf restart chatapp-web chatapp-celery
  cd /www/server/imserver && docker compose up -d
  ```
- [ ] 如已重写历史 URL，反向替换：
  ```bash
  mysql -u chatapp -p chatapp_im -e "
    UPDATE im_message SET body = REPLACE(body,
      'https://chat.shiliu153.cn/media/chat/',
      'http://47.116.114.110/media/chat/')
    WHERE body LIKE '%https://chat.shiliu153.cn/media/chat/%';"
  ```
- [ ] 旧 APK 仍在 `/www/wwwroot/chatapp-web/chatapp-1.0.0.apk`；把 `APP_DOWNLOAD_URL`/`MIN_APP_VERSION` 改回即可。

## 11. 风险与注意事项

1. **旧 APK 会断**：旧包的 `API_BASE` 写死 `http://47.116.114.110/api/v1`，IP 301 到域名后 Dio 会把 POST 降级成 GET（登录/发送失败）。WS 地址不是写死的——它来自 `/im/bootstrap` 的 `ws_url`，会跟着 `.env` 变——所以真正的断点是 REST。必须发新 APK，并用 `MIN_APP_VERSION` 强制升级。
2. **历史聊天图片/语音**：不改 `im_message.body` 里的旧前缀，切 `IM_MEDIA_PREFIX` 后会全部无法签名；第 6 步不能省。
3. **IM 头像**：`im_user.avatar_url` 里的旧 HTTP 地址在 HTTPS 页面会被浏览器按混合内容拦截；第 6 步一起重写。
4. **`SECURE_SSL_REDIRECT=1`**：Django 会把任何 `X-Forwarded-Proto: http` 的请求 301 到 `https://<Host>`；所以 IP vhost 必须先改成 301 到域名，否则 `https://47.116.114.110` 无证书会报错。
5. **TOTP**：`OPS_OTP_REQUIRED` 在生产默认 1；部署后第一次进 `/ops/` 会被要求绑定，先装验证器 App。
6. **`AUTO_APPROVE`**：生产默认 0；部署后新上传的资料图是 `pending`，要在 `/ops/photos/` 审核。
7. **证书续期**：不要用面板 SSL 页点续签（脚本已把该订单 `auth_tag=False`）；用 `/root/renew_cert_chat.sh` + cron。
8. **CSP**：如果后续接入第三方 CDN/统计，需要同步改 `connect-src`/`img-src`，否则会被浏览器拦。

## 12. 执行记录（2026-10-28 15:00–15:20，生产已切换）

结果：`https://chat.shiliu153.cn` 已全量生效；安全整改代码 + `imserver:7930bf2` 已上线；`http://47.116.114.110` 已 301 到新域名。

| 时间 | 动作 | 结果 |
|---|---|---|
| 14:59 | 备份 `.env` / `imserver.env` / IP vhost / `im_message`+`im_user` | `/root/*.bak.20261028-1459`、`/root/chatapp_im_backup_20261028-1459.sql` |
| 15:00 | git bundle（服务器连不上 GitHub）→ 切 `fix/security-remediation` `7930bf2` | 成功 |
| 15:00 | `migrate`（accounts.0003 / moderation.0002） | OK |
| 15:00 | 本地构建 `imserver:7930bf2` → `docker load` → `--migrate`（v3/v4）→ `up -d` | `readyz=200` |
| 15:01 | `im_sync_pairs` | 成功 3 / 失败 0 |
| 15:00 | 阿里云 DNS 加 `chat` A 记录（TTL 600） | 223.5.5.5 已解析 |
| 15:01 | 首次签发失败（`_acme-challenge.chat` SERVFAIL，新子域负缓存） | 等 7 分钟重试成功，到期 2027-01-26 |
| 15:09 | 443 vhost（`http2 on` + 安全头 + 媒体验签 + IM 反代） | `curl -I` 200 |
| 15:10 | Django `.env`：`ALLOWED_HOSTS`/`MEDIA_BASE_URL`/`IM_SELF_WS_URL`/`IM_SELF_HTTP_URL`/`HTTPS_ENABLED=1`/`CSRF_TRUSTED_ORIGINS`/`IM_MEDIA_SIGN_TTL=3600` | `check --deploy` 只剩 W021 |
| 15:10 | IP vhost 改 301 → 域名 | 已生效 |
| 15:11 | 修 `/_im_media_auth`：补 `Host` 与 `X-Forwarded-Proto https` | 未签名 403 / 已签名 200 |
| 15:12 | 重写 `im_message.body` 旧前缀（2 条）、`im_user.avatar_url`（0 条） | 0 残留 |
| 15:12 | imserver env：`IM_ALLOWED_ORIGINS` / `IM_MEDIA_PREFIX` / `IM_MEDIA_SIGN_TTL=3600` / `IM_SEND_PER_MINUTE=120` | `readyz=200` |
| 15:15 | App `1.0.1+2`（`API_BASE=https://chat.shiliu153.cn/api/v1`）→ `chatapp-1.0.1.apk`；版本三件套 → 1.0.1 | `/app/config` 返回 1.0.1 |
| 15:20 | Web 端同版本发版：`web/package.json` 1.0.0→1.0.1、关于页测试同步、`npm run build` 后覆盖 `dist`（369 测试绿） | 网页端不再被版本门槛挡住 |
| 15:18 | `renew_cert_chat.sh` + cron（每月 1/16 日 03:05） | 语法通过，且只挑 `status=valid` 的订单 |

验收（脚本化，`/root/ws_check.py`、`/root/ws_check2.py`）：

- `wss://chat.shiliu153.cn/im/ws` 首帧 `auth_ok`；错误 `sv` → `40101`；未配对发送 → `40302`（三项 PASS）
- u8 → u12（已配对）发送文本 → `ack`
- 历史语音 URL 读时签名已指向新前缀：无签名 403、带签名 200 `audio/x-m4a`
- Web：浏览器登录（u7）→ 发现/消息/聊天历史均 200，`/im/ws` 101，无 console 报错
- App：`flutter analyze` 零告警、405 测试全绿；APK 72.1MB 已上传

与计划的差异（模板已回写）：

1. 证书首次失败属 DNS 传播问题，重试即可（§3 已补经验）。
2. `/_im_media_auth` 必须显式传 `X-Forwarded-Proto https`，否则 `SECURE_SSL_REDIRECT` 会把子请求 301 掉、未签名媒体变成 500（§4 模板已补）。
3. IP vhost 301 提前到第 5 步之后：`HTTPS_ENABLED=1` 后若 IP 仍按 http 代理，Django 会 301 到 `https://47.116.114.110`（无证书），比直接 301 到域名更糟。
4. 续期脚本的订单查找加了 `status == "valid"`：首次失败会留下一个 pending 订单，否则续期会命中它。
5. **`MIN_APP_VERSION` 也卡网页端**：只把 App 升到 1.0.1、网页端仍是 1.0.0 时，整站被「需要更新后才能继续使用」挡住（实测）。所以发版必须双端同版本——`web/package.json` 也要改并重新 `npm run build` 部署 `dist`。已写进 [docs/pitfalls/web.md](../pitfalls/web.md) 第 23 条。

人工验收（2026-10-28 15:34 用户手测通过）：

- [x] App 真机手测（登录 / 聊天 / 杀进程重进 / 图片语音）
- [x] 首次进 `/ops/` 绑定 TOTP（已绑：`accounts_user.totp_secret` 非空，`last_login=2026-10-28 15:34`）
- [x] 旧 APK 强制升级弹窗实测（旧版启动被 `/app/config` 拦下）

至此本计划全部收口，无遗留动作。

