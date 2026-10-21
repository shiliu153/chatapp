# 自建 IM 运维手册

> 具体服务器地址、面板口令与密钥不入库;本文件只写可复制的步骤。

## 1. 首次部署

1. 建库与账号(与 Django 同实例,独立库):

```sql
CREATE DATABASE chatapp_im DEFAULT CHARSET utf8mb4;
CREATE USER 'imserver'@'127.0.0.1' IDENTIFIED BY '<强口令>';
GRANT ALL PRIVILEGES ON chatapp_im.* TO 'imserver'@'127.0.0.1';
```

2. 部署二进制与迁移:

```bash
mkdir -p /www/server/imserver
cp imserver /usr/local/bin/imserver
cp -r migrations /usr/local/share/imserver/
chmod 600 /www/server/imserver/imserver.env
/usr/local/bin/imserver --migrate
```

3. systemd:

```bash
cp deploy/imserver.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now imserver
systemctl status imserver
```

4. Nginx:把 `deploy/nginx-im.conf` 的两个 `location` 粘贴进现有 `server{}`,
`nginx -t && nginx -s reload`。

5. Django `.env` 配 `IM_BACKEND`、`IM_SELF_*`(见 `chatapp/.env.example`),
重启 gunicorn 与 Celery。

## 2. 健康检查

```bash
curl http://127.0.0.1:9101/internal/healthz
curl http://127.0.0.1:9101/internal/readyz
curl http://127.0.0.1:9101/internal/stats   # 需 HMAC,一般用脚本
```

- `healthz` 只证明进程存活;
- `readyz` 检查 MySQL + Redis,失败返回 503。

## 3. 升级

```bash
systemctl stop imserver
cp imserver /usr/local/bin/imserver
/usr/local/bin/imserver --migrate
systemctl start imserver
```

迁移按 `im_schema_version` 逐版执行,重复执行安全。

## 4. 回退到腾讯 IM

1. `chatapp/.env` 改 `IM_BACKEND=tencent`;
2. 重启 gunicorn;
3. 让用户重启 App(下次登录会拿到腾讯引导包);
4. 如需立刻止血:先停 imserver,再改配置、重启 App。

回退后自建期间的消息仍在 `chatapp_im` 库中,但腾讯侧看不到;回退前需产品知情。

## 5. 备份

- `chatapp_im` 随现有 MySQL 备份一起 `mysqldump`;
- Redis 只存在线态与封禁键,丢失可自愈;封禁以 Django 403 兜底。

## 6. 常见问题

| 现象 | 排查 |
|---|---|
| 客户端连不上 WS | Nginx `/im/ws` 是否带 `Upgrade`/`Connection`;`proxy_read_timeout` ≥ 90s |
| 所有请求都像来自 127.0.0.1 | Nginx 是否设置 `X-Real-IP` |
| `readyz` 503 | MySQL 连接串/Redis 地址;看 `journalctl -u imserver` |
| 封禁后仍能重连 | `/internal/kick` 是否 `block=true`;Redis `im:block:<uid>` 是否存在 |
| 消息重复 | 客户端是否复用 `client_msg_id`;服务端唯一键是否生效 |
