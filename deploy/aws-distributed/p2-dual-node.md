# P2 双机编排：确切改动清单（未实施 / 未验证）

> 状态：**草案**。P2 需要跨机内网端口放行，而 AWS 安全组当前未放行（安全组只开 22，
> 且 `aws login` 会话过期无法改）。本文把「安全组一开就要做哪些确切改动」先固化下来，
> 避免临场再推理。**本文里的配置没有任何一条被实测过**，落地时必须逐条验证。

角色分配见设计稿 §3.1：EDGE = `13.211.212.232`（172.31.14.4）/ APP = `32.236.245.150`（172.31.35.181）。

---

## 1. 安全组（P2 的前置，必须由人/AWS CLI 做）

| 目标 | 端口 | 来源 | 说明 |
|---|---|---|---|
| EDGE | 80, 443 | `0.0.0.0/0` | 入口与 Let's Encrypt HTTP-01 |
| EDGE | 3306, 6379 | `172.31.35.181/32`（APP 内网） | 只给 APP 副本，**不要**对公网 |
| APP | 8000, 9100, 9101 | `172.31.14.4/32`（EDGE 内网） | 供 EDGE 的 nginx 反代 |

> 内网端口一律**按对端单个 IP** 放行，不要用 `172.31.0.0/16`。
> 本文档早期版本曾写整段 VPC，属过度放行。

## 2. EDGE 侧：把数据层暴露到内网（新增 override，不改既有模板）

```yaml
# deploy/aws-distributed/compose.edge.data-ports.override.yml
services:
  mysql:
    ports:
      # 只绑内网网卡，不对公网监听
      - "172.31.14.4:3306:3306"
  redis:
    ports:
      - "172.31.14.4:6379:6379"
```

同时 `MYSQL_ROOT_HOST` 与业务账号的 host 要能匹配 APP 的地址。
P1 已把 `MYSQL_ROOT_HOST` 放宽到 `172.%`（见 `compose.edge.override.yml` 注释）；
业务账号 `chatapp@'%'` / `imserver@'%'` 由 `db-init` 建，天然可连。

## 3. APP 侧：新增 compose（两个服务，不发布公网端口）

```yaml
# deploy/aws-distributed/compose.app.yml
name: chatapp-app

x-app: &app
  image: chatapp-web:local
  env_file: ["./secrets/chatapp.app.env"]
  restart: unless-stopped
  cap_drop: [ALL]
  security_opt: ["no-new-privileges:true"]
  pids_limit: 256
  logging:
    driver: json-file
    options: {max-size: "20m", max-file: "5"}

services:
  web:
    <<: *app
    command: ["gunicorn", "config.wsgi:application", "-b", "0.0.0.0:8000",
              "-w", "2", "--timeout", "120", "--access-logfile", "-"]
    ports:
      - "172.31.35.181:8000:8000"     # 仅内网，供 EDGE nginx
    mem_limit: 384m
    # 迁移不在这里跑：统一由 EDGE 的 migrate 容器执行（见 §5）

  imserver:
    image: chatapp-imserver:local
    env_file: ["./secrets/imserver.app.env"]
    ports:
      - "172.31.35.181:9100:9100"     # WS
      - "172.31.35.181:9101:9101"     # 内部 HTTP
    mem_limit: 256m
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    healthcheck:
      test: ["CMD-SHELL", "bash -c 'exec 3<>/dev/tcp/127.0.0.1/9101' || exit 1"]
      interval: 15s
      timeout: 5s
      retries: 20
      start_period: 30s
```

**注意**：APP 上 `chaoxing-web` 只监听 `127.0.0.1:8000`，因此绑 `172.31.35.181:8000`
不冲突；但**部署前必须再确认一次**（`ss -tlnp | grep :8000`）。

### APP 侧环境变量差异（相对 P1 的 `chatapp.env`）

| 键 | P1（同机） | P2（APP 副本） |
|---|---|---|
| `DB_HOST` | `mysql` | `172.31.14.4` |
| `REDIS_URL` | `redis://redis:6379/0` | `redis://172.31.14.4:6379/0` |
| `BROKER_URL` | `redis://redis:6379/1` | `redis://172.31.14.4:6379/1` |
| `IM_SELF_URL` | `http://imserver:9101` | `http://127.0.0.1:9101`（同机 imserver-b） |
| `TRUSTED_PROXY_IPS` | `127.0.0.1,::1,172.28.0.10` | `127.0.0.1,::1,172.31.14.4`（EDGE nginx） |

imserver 侧同理：`IM_MYSQL_DSN` / `IM_REDIS_URL` 指向 `172.31.14.4`；
`IM_TRUSTED_PROXIES` 加 `172.31.14.4`；`IM_INTERNAL_ALLOW` 加 `172.31.14.4`
（否则 Django→imserver 的 `/internal/*` 会 403）；新增 `IM_INSTANCE_ID=edge|app`。

## 4. EDGE 侧 nginx：双 upstream + 媒体写路径钉死

```nginx
upstream chatapp_api {
    least_conn;                                  # 不要用 ip_hash：移动端 CGNAT 会把
    server web:8000 max_fails=3 fail_timeout=10s;         # 整个运营商出口压到一台
    server 172.31.35.181:8000 max_fails=3 fail_timeout=10s;
    keepalive 32;
}
upstream chatapp_im {
    least_conn;
    server imserver:9100 max_fails=3 fail_timeout=10s;
    server 172.31.35.181:9100 max_fails=3 fail_timeout=10s;
}

# 写媒体的接口钉到本机（媒体卷只在 EDGE，见设计稿 §5）
location ~ ^/api/v1/(im/images|im/voices|users/me/photos)$ {
    proxy_pass http://web:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    client_max_body_size 20m;
}
location /api/v1/posts {
    limit_except GET { proxy_pass http://web:8000; }   # POST 落图钉本机，GET 双副本
    proxy_pass http://chatapp_api;
    ...
}
location ~ ^/(api|admin|ops)(/|$) { proxy_pass http://chatapp_api; ... }
location /im/ws  { proxy_pass http://chatapp_im; ... 原有 Upgrade 头 ... }
location /im/api/ { proxy_pass http://chatapp_im; ... }
```

> `limit_except` 与 `proxy_pass` 的组合需要实测；若不成立，退化为用 `map $request_method`
> 或直接在 Django 侧接受「上传落到哪个副本都行」——但那样媒体卷就不共享，**不能退化**。
> 这是 P2 落地时第一个要验的点。

## 5. 迁移与定时任务只在一处跑

- `migrate` / `db-init` / `imserver --migrate` **只在 EDGE 跑**（APP 不跑，避免并发迁移）。
- Celery worker **只跑 EDGE 一份**（定时任务重复执行会互相打架）。
- `media_cleanup` / `media_bytes_backfill` **只能在 EDGE 跑**（只有它有媒体卷）。

## 6. 落地后必须验的顺序

1. APP 侧两个服务 healthy；`curl http://172.31.35.181:8000/api/v1/app/config` 从 EDGE 通。
2. EDGE nginx `upstream` 里两台都 up（`/healthz` 双副本各打一次，看 `docker logs web` 交替出现）。
3. **摘一台验证**：`docker stop` APP 的 web → 只靠 EDGE 单副本，接口仍 200（fail_timeout 生效）。
4. IM：`lab_cross_node.py` 的 `split_a_b` 在 **#288 合并后**应为 `delivered=True`。
5. 媒体：从任一副本上传图片 → 立刻从另一副本读（应 404，因为卷在 EDGE）→ 确认写路径确实钉住了。

## 7. 已知会挡路的因素

| 项 | 状态 |
|---|---|
| 安全组未放行 | 阻塞全部 P2 |
| `aws login` 过期 | 阻塞安全组变更 |
| #288（imserver 多实例）未合并 | 阻塞 §6.4；不阻塞 HTTP 层双副本 |
| `t3.small` 内存 | APP 侧 757MB 已被 `chaoxing` 占用，只剩 ~1.1G；web 384m + imserver 256m ≈ 640m 可以放下，但无余量 |
