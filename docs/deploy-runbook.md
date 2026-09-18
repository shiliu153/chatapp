# 服务器部署与运维手册(M4 第一步:跑通版)

更新于 2026-09-18 · 服务器:阿里云轻量应用服务器 2C2G(中国大陆,`<SERVER_IP>`)

## 概况

| 项 | 值 |
|---|---|
| 服务器 | `<SERVER_IP>`,root 免密 SSH(本机 `~/.ssh/<YOUR_KEY>`) |
| 宝塔面板 | `http://<SERVER_IP>:<PANEL_PORT>`(需阿里云控制台防火墙放行 <PANEL_PORT>) |
| 系统 | Alibaba Cloud Linux 3(`dnf` + `firewalld`);swap 1G |
| 代码 | `/www/wwwroot/chatapp`(git,远程 `github.com:yourname/chatapp`,deploy key 只读) |
| Python | `/www/wwwroot/chatapp-venv`(python3.11);依赖 = `chatapp/requirements.txt` |
| 站点配置 | 宝塔「网站」→ <SERVER_IP>;nginx conf:`/www/server/panel/vhost/nginx/<SERVER_IP>.conf`(面板可编辑,已备份 `.bak.20260918`) |
| 数据库 | MySQL 8.0.45,库 `chatapp` / 账号 `chatapp`(口令在 `chatapp/.env`) |
| Redis | 7.4.11,`127.0.0.1:6379`(DB0 缓存 / DB1 任务队列) |
| 进程 | 宝塔「进程守护管理器」两条:`chatapp-web`(gunicorn `127.0.0.1:8000`)/ `chatapp-celery`;supervisord 主进程配置 `/etc/supervisor/supervisord.conf` |
| 日志 | Django:`/www/wwwlogs/chatapp/app.log`;nginx:`/www/wwwlogs/<SERVER_IP>.log` / `.error.log` |

## 日常更新代码(六步)

```bash
# 1. 本地改完提交并推送
git push

# 2. 服务器拉取
ssh root@<SERVER_IP> 'cd /www/wwwroot/chatapp && git pull'

# 3~5. 依赖/迁移/静态有变化时(没有变化可跳过)
ssh root@<SERVER_IP> 'cd /www/wwwroot/chatapp/chatapp && \
  /www/wwwroot/chatapp-venv/bin/pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/ && \
  /www/wwwroot/chatapp-venv/bin/python manage.py migrate && \
  /www/wwwroot/chatapp-venv/bin/python manage.py collectstatic --noinput'

# 6. 面板 → 进程守护 → 重启 chatapp-web / chatapp-celery(改了 im/tasks.py 必须重启 celery)
```

## 常见操作

- **看日志**:`tail -f /www/wwwlogs/chatapp/app.log`(带 request_id);排查 502 看 nginx 错误日志。
- **跑管理命令**:`cd /www/wwwroot/chatapp/chatapp && /www/wwwroot/chatapp-venv/bin/python manage.py <命令>`,例如 `dev_reset_pair --a u8 --b u12`、`seed_fake_users --count 5`、`im_send --from u8 --to u12 --text hi`。
- **连数据库**:面板「数据库」→ 管理;或 `mysql -u chatapp -p chatapp`。
- **改 nginx 配置**:面板「网站」→ 设置 → 配置文件,改完保存即 reload;命令行验证 `nginx -t`。
- **回滚代码**:`cd /www/wwwroot/chatapp && git log --oneline` 找目标版本 `git checkout <hash>`,然后重启两条进程。
- **内存观察**:`free -h`;紧张时把 `chatapp-web` 的 `-w 2` 降为 `-w 1`(面板改启动命令后重启)。

### ⚠️ 运维坑(已踩过)

- **`pkill -f "gunicorn config.wsgi"` 会杀掉自己那条 SSH 命令**(命令行里含同样字符串,被 `-f` 匹配)。要按名杀进程用方括号技巧:`pkill -f "[g]unicorn config.wsgi"`。
- **服务器本机 curl 用 `127.0.0.1` 测站点会 404**:nginx 按 `server_name` 分流,`127.0.0.1` 落到宝塔默认站点。本机自测要么带 Host:`curl -H "Host: <SERVER_IP>" http://127.0.0.1/...`,要么直连 `http://127.0.0.1:8000`(gunicorn)。
- **放行端口要做两层**:主机 `firewalld` + 阿里云控制台防火墙,缺一层就不通。
- **`git pull` 不受 `.env` 影响**(gitignored);但**改 `.env` 后必须重启两条进程**(env 只在进程启动时读)。

## 本阶段已知事项(「上线阶段」待办)

- 无域名、未 HTTPS:备案完成后切域名 + 面板一键证书;**换域名时记得同步改 `MEDIA_BASE_URL` 并重刷 IM 头像**(见下)。
- 面板 <PANEL_PORT> 暴露公网、SSH 仍允许密码登录:上线前做加固(强口令/白名单/关密码登录)。
- `AUTO_APPROVE=1`、`SMS_DEV_MODE=1`:测试期开关,上线阶段关闭并接内容安全/短信。
- 备份未配:建议尽快在面板加 MySQL 计划任务备份 + 云快照。
- 服务器 Django 5.2.17(本地 5.2.9,同 5.2 线,可接受)。
- 本地开发库与服务器库是两份(测试期独立,互不同步)。

### 换域名后刷 IM 头像(一次性)

```bash
cd /www/wwwroot/chatapp/chatapp && /www/wwwroot/chatapp-venv/bin/python manage.py shell -c "
from django.contrib.auth import get_user_model
from im.tasks import sync_profile
ids = list(get_user_model().objects.filter(photos__status='approved').distinct().values_list('id', flat=True))
for uid in ids:
    sync_profile.run(uid, 'avatar')
print('done', len(ids))
"
```
