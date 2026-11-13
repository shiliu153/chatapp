# AWS 分布式部署（悉尼两台 t3.small）

设计稿见 [docs/superpowers/specs/2026-11-13-aws-distributed-deployment-design.md](../../docs/superpowers/specs/2026-11-13-aws-distributed-deployment-design.md)。

本目录存放**与既有单机栈并行**的 AWS 双机编排。它不改动 `deploy/` 下的既有脚本与模板
（`AGENTS.md` §六 禁止改 `deploy/` 下任何脚本），只新增文件。

## 当前状态

| 阶段 | 状态 |
|---|---|
| P1 单机跑通（入口机 13.211.212.232） | ✅ 2026-11-13 实测通过，见下 |
| P2 跨机扩容 | 未开始 |
| P3 imserver 多实例 | 未开始 |
| P4 容量验收 | 未开始（卡在 t3.small CPU 积分，见设计稿 §7.1） |

## P1：入口机单机栈

复用仓库自带的 `deploy/oneclick.sh --render-only` 渲染配置，再用 `compose.edge.override.yml`
覆盖 t3.small 撑不住的部分。**没有**走 `oneclick.sh` 的完整部署路径，因此下面第 2 步必须手工补。

```bash
# 0) 代码上机（仓库是私有 SSH remote，用 git bundle 传，不依赖 GitHub 凭证）
git bundle create /tmp/chatapp.bundle feat/aws-distributed
scp /tmp/chatapp.bundle ubuntu@13.211.212.232:/tmp/
ssh ubuntu@13.211.212.232 'mkdir -p ~/src && git clone -b feat/aws-distributed /tmp/chatapp.bundle ~/src/chatapp'

# 1) 构建镜像（在入口机上构建：2C2G 编译 imserver 需要额外 swap，见下）
sudo fallocate -l 2G /swapfile2 && sudo chmod 600 /swapfile2 && sudo mkswap -q /swapfile2 && sudo swapon /swapfile2
cd ~/src/chatapp
docker build -f deploy/docker/Dockerfile --build-arg PIP_INDEX_URL=https://pypi.org/simple/ --build-arg APT_MIRROR= -t chatapp-web:local .
docker build -t chatapp-imserver:local imserver
docker build -f deploy/docker/web.Dockerfile --build-arg NPM_REGISTRY=https://registry.npmjs.org -t chatapp-nginx:local .

# 2) 渲染配置（部署目录必须在 /opt 等 755 目录下，见「坑 2」）
sudo bash deploy/oneclick.sh --render-only --no-tls \
    --public-url http://127.0.0.1:8080 --http-port 8080 --https-port 8443 \
    --allow-dev-sms --admin-phone 13900000000 --app-dir /opt/chatapp-edge

# 3) 权限归一（cap_drop:[ALL] 下 root 失去 CAP_DAC_OVERRIDE，读不了属主不符的 600 文件）
sudo find /opt/chatapp-edge -type d -exec chmod 755 {} \;
sudo find /opt/chatapp-edge -type f -exec chmod 644 {} \;
sudo chmod 600 /opt/chatapp-edge/secrets/*.env /opt/chatapp-edge/.env

# 4) 补 imserver 迁移 —— 关键！oneclick.sh 完整路径里有这一句（:744），
#    手工 up 会漏掉，后果是 chatapp_im 一张表都没有、/im/user_sig 一直 503。
cd /opt/chatapp-edge
sudo cp <本目录>/compose.edge.override.yml .
sudo docker compose -f docker-compose.yml -f compose.edge.override.yml up -d
sudo docker compose -f docker-compose.yml -f compose.edge.override.yml run --rm --no-deps imserver --migrate
sudo docker compose -f docker-compose.yml -f compose.edge.override.yml restart imserver
```

访问：`ssh -L 8080:127.0.0.1:8080 ubuntu@13.211.212.232`，然后本机开 `http://127.0.0.1:8080`。
安全组只开 22，**不对公网暴露**。

## P1 实测结果（2026-11-13，t3.small / 1905MB）

| 验证点 | 结果 |
|---|---|
| nginx `/healthz` | `200 ok` |
| `GET /api/v1/app/config` | `200 {"min_app_version":"1.0.13",...}` |
| 前端首页 `/` | `200 text/html` |
| `POST /auth/sms/send`（名单内） | `200` |
| `POST /auth/sms/send`（名单外） | `403 40301` 封闭测试拒绝 ✅ |
| `POST /auth/sms/verify` | `200` 拿到 JWT，`is_new_user=true` |
| `GET /users/me`（带 JWT） | `200` |
| `POST /im/user_sig` | `200`，`im_user_id=u1`、给出 ws_url |
| **WebSocket 鉴权** `/im/ws` | **`auth_ok`（uid=2, heartbeat_sec=25）** |

容器内存实测（限额内）：mysql 400MB/512m、web 143MB/256m、worker 108MB/160m、
imserver 12MB/224m、nginx 10MB/48m、redis 5MB/160m；整机 used ≈1185MB / 1905MB。

## P1 踩到的 4 个模板缺陷（都已在 P1 绕开，P2 要正式修）

| # | 缺陷 | 现象 | P1 处置 |
|---|---|---|---|
| 1 | 只有 `default` 网络配了 ipam，`backend`(internal) 被 Docker 自动分到 `172.18.0.0/16`，而 `MYSQL_ROOT_HOST` 从 `DOCKER_SUBNET` 推导成 `172.28.0.%` | `db-init` 报 `Access denied for user 'root'@'172.18.0.4'`，首次部署必然失败 | override 里把 `MYSQL_ROOT_HOST` 放开到 `172.%`（MySQL 在 internal 网、不发布端口） |
| 2 | 容器以 `cap_drop:[ALL]` 运行，root 因此失去 `CAP_DAC_OVERRIDE`；把部署目录放在 `750` 的 `/home/xxx` 下时遍历都会被拒 | `db-init` 报 `/init/01-databases.sql: Permission denied` | 部署目录固定到 `/opt`（755、root 属主）+ 权限归一 |
| 3 | redis 官方镜像启动时用 `setpriv` 降权，而 `cap_drop:[ALL]` 去掉了 `CAP_SETUID` | `setpriv: setresuid failed: Operation not permitted`，redis 无限重启 | override 里 `user: "999:1000"` 直接以 redis 用户启动，跳过降权 |
| 4 | imserver 运行镜像是 `ubuntu:24.04`，**没有 curl/wget**，但 compose 的 healthcheck 用 `curl` | 容器永远 unhealthy → `depends_on` 卡住 nginx 起不来 | override 改用 `bash -c 'exec 3<>/dev/tcp/127.0.0.1/9101'` 探端口 |

> 第 4 条在阿里云生产上同样成立（同一个 Dockerfile），只是生产的 `oneclick.sh` 路径里
> nginx 的 `depends_on` 时机不同、没被暴露出来。**建议单独开一单修**：给 imserver 运行镜像
> 装 curl（或在镜像里提供 `--healthz` 子命令），不要在部署侧长期绕过。

## 另一处文档与实现不一致

`chatapp/accounts/checks.py:40-45` 的 `accounts.E001` 只读 `SMS_PHONE_WHITELIST`，
**不读 `SMS_ALLOWLIST_STRICT`**，但它的 hint 把「设 `SMS_ALLOWLIST_STRICT=0`」列为第三条出路。
照 hint 做会继续红。P1 用的是第一条出路（配名单种子）。

## 已知的一处环境妥协

`ALLOWED_HOSTS` 里加了 `nginx` / `imserver` 两个容器名：容器间互调时 `Host` 就是服务名，
不加会被 Django 判 `DisallowedHost` 返回 400。生产由真实域名访问，不受影响。
