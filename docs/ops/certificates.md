# 证书与续期（生产）

> 适用：`47.116.114.110` 这台服务器上的全部站点证书。最后更新 2026-10-28。

## 1. 一句话

所有证书统一由 **certbot** 续期，唯一调度是 root crontab 的 `17 3 * * * certbot renew`。
面板（宝塔）的"自动续签"在这台机器上**空转**——`sites` 表为空，它一张证书都不会续，别依赖它。

## 2. 证书清单

| 域名 | 用途 | 验证方式 | webroot |
|---|---|---|---|
| `chat.shiliu153.cn` | 交友 App（Web/API/WSS） | webroot | `/www/wwwroot/chatapp-web` |
| `shiliu153.cn` | 简历站 | webroot | `/www/wwwroot/profile` |
| `shiliu153.me` | 简历站 | webroot | `/www/wwwroot/profile` |
| `wb.shiliu153.me` | 微博备份站 | webroot | `/www/wwwroot/wb.shiliu153.me` |
| `tts.shiliu153.me` | TTS 服务 | webroot | `/www/wwwroot/tts.shiliu153.me` |

五张都是 Let's Encrypt、ECDSA、90 天有效，当前均在 2027-01 到期。

## 3. 路径地图

```
调度    /var/spool/cron/root                          ← 17 3 * * * certbot renew
配置    /etc/letsencrypt/renewal/<域名>.conf           ← 每张证书一条（认证方式/webroot/hook）
权威源  /etc/letsencrypt/live/<域名>/                  ← certbot 写这里
nginx   /www/server/panel/vhost/letsencrypt/<域名>/    ← vhost 实际读这里（由 hook 复制）
钩子    /root/certbot_deploy_hook.sh                   ← 复制 + nginx -t + reload
日志    /var/log/letsencrypt/letsencrypt.log           ← ACME 全过程
        /var/log/certbot-deploy.log                    ← 复制与 reload 记录
        /var/log/certbot-renew.log                     ← --quiet，只在动作/报错时写
```

链路：ACME 签发 → `/etc/letsencrypt/live/` → deploy hook 复制到面板目录（先写 `.new` 再 `mv`，避免 nginx 读到半个文件）→ `nginx -t` 通过才 reload。

## 4. 新增一个域名（照抄）

前提：该域名的 80 端口能访问到 `/.well-known/acme-challenge/`（vhost 里要有
`location ^~ /.well-known/acme-challenge/ { root <站点根>; }`，且 80 不被整站 301 掉）。

```bash
# 先探一下 80 通道（把 _probe.txt 放进 webroot 再 curl，应回 200 + 内容）
mkdir -p /www/wwwroot/<站点根>/.well-known/acme-challenge
echo ok > /www/wwwroot/<站点根>/.well-known/acme-challenge/_probe.txt
curl -s http://<域名>/.well-known/acme-challenge/_probe.txt
rm -f /www/wwwroot/<站点根>/.well-known/acme-challenge/_probe.txt

# 签发（--deploy-hook 会被写进 renewal conf 的 renew_hook，续期时自动跑）
/root/certbot-venv/bin/certbot certonly --webroot -w /www/wwwroot/<站点根> \
  -d <域名> --cert-name <域名> --key-type ecdsa \
  --deploy-hook /root/certbot_deploy_hook.sh --non-interactive
```

> 通配符（`*.shiliu153.cn`）需要 DNS-01，而本机 certbot 只装了 `standalone`/`webroot`
> 两个插件，没有 DNS 插件——要签通配符得先装 `certbot-dns-aliyun` 并配凭据。

## 5. 验证与排障

```bash
# 续期演练（不会真的换证；--non-interactive 会随机睡 0–6 分钟，别以为卡住）
/root/certbot-venv/bin/certbot renew --cert-name <域名> --dry-run

# 看全部证书到期
for d in /www/server/panel/vhost/letsencrypt/*/; do
  printf "%-28s %s\n" "$(basename "$d")" "$(openssl x509 -in "$d/fullchain.pem" -noout -enddate)"
done

# 看线上实际在用的证书（序列号应与文件一致）
echo | openssl s_client -connect 127.0.0.1:443 -servername <域名> 2>/dev/null \
  | openssl x509 -noout -serial -enddate
```

常见失败：

| 现象 | 原因 |
|---|---|
| `Invalid response ... 404` | webroot 路径写错，或 80 的 vhost 把 `/.well-known/` 也 301 了 |
| `Timeout during connect` | 80 端口被安全组/防火墙挡了 |
| `too many certificates` | LE 限流（同名同集合 5 次/周），等一周或用 `--dry-run` 调试 |
| hook 里 `nginx -t` 失败 | 证书已复制但没 reload，修好配置后手动 `nginx -s reload` |

## 6. 已知坑

1. **面板"自动续签已开启"是假象**：`/www/server/panel/data/check_ssl_cron.pl` 只是标记文件；
   真正跑的 `acme_v2.py --renew_v2=1` 遍历 `sites` 表，而本机 `sites` 为空（站点全是手写 vhost），
   所以它一张都不续。不要在面板 SSL 页点"续签"，会和 certbot 互相覆盖。
2. **`--quiet` 让失败静默**：certbot 出错只写 `letsencrypt.log`，没人看就等于没有告警。
   已补巡检：`/root/check_ssl_expiry.sh`（源码 [check_ssl_expiry.sh](check_ssl_expiry.sh)），
   root cron 每天 `0 8 * * *` 跑一次，扫五张磁盘证书 + 线上实际下发证书，剩余 < 20 天写
   `WARN` 到 `/var/log/ssl-expiry.log` 并以非零退出。
3. **App 证书绑定只信 ISRG Root X1/X2**（Let's Encrypt）：换 CA 前必须先发新版 App，否则全量连不上。
4. **证书文件权限**：hook 用 `install -m 600`，别手动 `chmod 644`（私钥可读面越小越好）。

## 7. 历史

- **2026-10-28 18:40**：`chat.shiliu153.cn` 从自建 DNS-01 脚本迁移到 certbot（webroot）。
  旧脚本 `/root/renew_cert_chat.sh`、`/root/issue_cert_dns_chat.py` 归档到
  `/root/archive/cert-2026-10-28/`，cron 已删；`renew --dry-run` 通过。
- 更早：`/root/renew_cert.sh`（简历站）、`/root/renew_cert_wb.sh`（wb）是 certbot 之前的老方案，
  已不在 cron 里，仅作回退参考。
