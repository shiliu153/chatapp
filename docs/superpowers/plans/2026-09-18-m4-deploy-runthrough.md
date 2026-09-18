# M4 部署·第一步(服务器跑通)实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把后端全栈部署到阿里云轻量服务器(`<SERVER_IP>`)并在 IP:80 上跑通,模拟器连服务器可走核心链路。

**Architecture:** 宝塔全托管——nginx(反代 + 静态直出)→ gunicorn(127.0.0.1:8000)→ Django;MySQL/Redis 本机;Celery worker 常驻;两条进程由宝塔「进程守护管理器」托管;代码经 GitHub deploy key(只读)拉取。

**Tech Stack:** Django 5.2 + DRF、gunicorn、Celery、MySQL 8.0.45、Redis 7.4.11、nginx 1.30.5、Python 3.11.13、宝塔面板、Alibaba Cloud Linux 3。

**关联文档:** 设计 spec `docs/superpowers/specs/2026-09-18-m4-deploy-runthrough-design.md`

## Global Constraints(全局约束,每个任务都适用)

- 服务器:`ssh root@<SERVER_IP>`(本机已免密);宝塔面板端口 **<PANEL_PORT>**;包管理 **dnf**;防火墙两层(主机 firewalld + 阿里云控制台)。
- MySQL root 口令 `cf123456`(仅管理用);业务一律用专用库/账号 **chatapp**(不用 root)。
- IM 副作用只走 `im/tasks.py`;改任务代码后服务器 worker 必须重启。
- `.env` 禁用 `CELERY_` 前缀键(broker 用 `BROKER_URL`)。
- 密码/密钥只写服务器 `/www/wwwroot/chatapp/chatapp/.env`(chmod 600),永不入 git。
- 纪律:后端 `python manage.py test` 全绿(前置:本地 Redis 容器在跑);`flutter analyze` 零告警;每个 Task 结束提交一次。
- 本阶段**不动 App 源码**;模拟器测试仅换 `--dart-define=API_BASE`。
- 步骤标注:**【用户操作】** = 用户按指引在宝塔/GitHub 上点(Claude 给出精确参数);**【Claude 执行】** = Claude 经 SSH/本机终端执行。执行时生成的秘密值(DB 口令、SECRET_KEY)当场告知用户并写入服务器 .env。

## 文件结构(本计划涉及)

- 修改 `chatapp/accounts/views.py` — 新增 `readyz` 与两个探针函数
- 修改 `chatapp/config/api_urls.py` — 新增路由
- 修改 `chatapp/accounts/tests.py` — 新增 `ReadyZTests`
- 修改 `chatapp/config/settings.py` — 新增 `STATIC_ROOT`
- 修改 `chatapp/requirements.txt` — 新增 gunicorn
- 服务器新建:代码 `/www/wwwroot/chatapp/`;venv `/www/wwwroot/chatapp-venv/`;`.env`;日志目录 `/www/wwwlogs/chatapp/`;nginx 站点 conf(宝塔生成后改写)
- 新建 `docs/deploy-runbook.md`(部署/运维手册)
- 修改 `CLAUDE.md`(M4 段落)

---

### Task 1: `/api/v1/readyz` 健康检查(TDD)

**Files:**
- Modify: `chatapp/accounts/views.py`(health 函数下方)
- Modify: `chatapp/config/api_urls.py`
- Test: `chatapp/accounts/tests.py`

**Interfaces:**
- Produces: `GET /api/v1/readyz` → 200 `{"status":"ok","checks":{"db":"ok","redis":"ok"}}`;任一探针失败 → 503,同结构、对应项为 `"error"`。无鉴权(与 `/api/v1/health` 同权)。
- Produces(内部,patch 点):`accounts.views._probe_db()`、`accounts.views._probe_redis()`。

- [ ] **Step 0: 建分支**

```bash
git checkout master && git checkout -b m4-deploy
git status --short        # 期望:干净(工作区无未提交改动)
```

- [ ] **Step 1: 写失败测试**(`chatapp/accounts/tests.py`,紧跟 `HealthTests` 之后)

```python
class ReadyZTests(APITestCase):
    def test_readyz_ok(self):
        resp = self.client.get("/api/v1/readyz")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok", "checks": {"db": "ok", "redis": "ok"}})

    def test_readyz_db_down_returns_503(self):
        with patch("accounts.views._probe_db", side_effect=RuntimeError("db down")):
            resp = self.client.get("/api/v1/readyz")
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()["checks"], {"db": "error", "redis": "ok"})

    def test_readyz_redis_down_returns_503(self):
        with patch("accounts.views._probe_redis", side_effect=RuntimeError("redis down")):
            resp = self.client.get("/api/v1/readyz")
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()["checks"], {"db": "ok", "redis": "error"})
```

- [ ] **Step 2: 跑测试确认失败**

Run(cwd=`chatapp/`,前置:本地 Redis 容器已起 `docker compose -f docker-compose.dev.yml up -d`):
`python manage.py test accounts.tests.ReadyZTests -v 1`
Expected: FAIL——`readyz` 路由还不存在,返回 404(断言 404 != 200 或 checks 取不到)。

- [ ] **Step 3: 最小实现**(`chatapp/accounts/views.py`)

顶部 import 区补:

```python
from django.db import connection
from django_redis import get_redis_connection
```

`health` 函数下方新增:

```python
def _probe_db():
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")


def _probe_redis():
    conn = get_redis_connection("default")
    conn.set("readyz:probe", "1", ex=10)
    if conn.get("readyz:probe") != b"1":
        raise RuntimeError("redis round-trip mismatch")


@api_view(["GET"])
@permission_classes([AllowAny])
def readyz(request):
    checks = {}
    for name, probe in (("db", _probe_db), ("redis", _probe_redis)):
        try:
            probe()
            checks[name] = "ok"
        except Exception:
            logger.exception("readyz 探针失败: %s", name)
            checks[name] = "error"
    ok = all(v == "ok" for v in checks.values())
    return Response(
        {"status": "ok" if ok else "unavailable", "checks": checks},
        status=200 if ok else 503,
    )
```

- [ ] **Step 4: 挂路由**(`chatapp/config/api_urls.py`)

```python
from accounts.views import health, readyz      # 改这一行
...
    path("readyz", readyz),                    # 加在 path("health", health) 之后
```

- [ ] **Step 5: 跑测试确认通过 + 全量回归**

Run: `python manage.py test accounts.tests.ReadyZTests && python manage.py test`
Expected: 新 3 条绿;全量绿(基线 327 + 3 = 330)。

- [ ] **Step 6: 提交**

```bash
git add chatapp/accounts/views.py chatapp/config/api_urls.py chatapp/accounts/tests.py
git commit -m "feat(health): /api/v1/readyz 探 MySQL+Redis,异常 503(标准化第 3 期)"
```

---

### Task 2: STATIC_ROOT + gunicorn 依赖

**Files:**
- Modify: `chatapp/config/settings.py:179` 附近
- Modify: `chatapp/requirements.txt`

**Interfaces:**
- Produces: `collectstatic` 产物目录 `chatapp/staticfiles/`(nginx alias 目标,Task 7 引用);生产依赖含 gunicorn。

- [ ] **Step 1: settings.py 加 STATIC_ROOT**(`STATIC_URL = "static/"` 行下方)

```python
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"   # collectstatic 产物目录;生产由 nginx 直出(.gitignore 已忽略)
```

- [ ] **Step 2: requirements.txt 末尾加一行**

```
gunicorn>=21.2
```

- [ ] **Step 3: 验证 collectstatic 可跑**

Run(cwd=`chatapp/`): `python manage.py collectstatic --noinput`
Expected: 输出 `N static files copied`;目录 `chatapp/staticfiles/` 生成(含 `ops/vendor/`、admin 等)。

- [ ] **Step 4: 全量测试**

Run: `python manage.py test`
Expected: 330 全绿(本任务不改行为)。

- [ ] **Step 5: 提交**

```bash
git add chatapp/config/settings.py chatapp/requirements.txt
git commit -m "chore(deploy): STATIC_ROOT + gunicorn 生产依赖"
```

---

### Task 3: 宝塔建站 + 建库(用户操作 + Claude 核对)

**Interfaces:**
- Produces: 站点目录 `/www/wwwroot/chatapp/`(若面板强制默认目录则退化为 `/www/wwwroot/<SERVER_IP>/`,Task 7 的 alias 是绝对路径不受影响);MySQL 库 `chatapp` + 账号 `chatapp`。

- [ ] **Step 1:【Claude 执行】生成业务库口令并交给用户**

Run(本机): `/usr/bin/python3.11 -c "import secrets;print(secrets.token_urlsafe(12))"` 或服务器同款命令;把结果作为「数据库密码」在下一步告知用户(同时留档,Task 5 写 .env 用)。

- [ ] **Step 2:【用户操作】宝塔面板建站**

网站 → 添加站点:
- 域名:`<SERVER_IP>`
- 根目录:填 `/www/wwwroot/chatapp`(面板若不允许自定义,就用默认路径,告知 Claude 即可,不影响后续)
- 不勾 FTP、不勾数据库、PHP 版本随意(反代后不生效)

- [ ] **Step 3:【用户操作】建库**

数据库 → 添加数据库:库名 `chatapp`、用户名 `chatapp`、密码 = Step 1 生成的口令;字符集 `utf8mb4`。

- [ ] **Step 4:【Claude 执行】核对**

```bash
ssh root@<SERVER_IP> 'ls /www/wwwroot/; mysql -u chatapp -p<口令> -e "SELECT 1" chatapp; ls /www/server/panel/vhost/nginx/'
```

Expected: 站点目录存在;MySQL 返回 1;vhost 目录下能看到该站点 conf(路径 Task 7 用)。

---

### Task 4: deploy key + 拉代码 + venv

**Interfaces:**
- Produces: `/www/wwwroot/chatapp/`(完整仓库,master);`/www/wwwroot/chatapp-venv/`(Python 3.11 venv,装好 requirements)。

- [ ] **Step 1:【Claude 执行】服务器生成部署密钥 + SSH 配置**

```bash
ssh root@<SERVER_IP> 'ssh-keygen -t ed25519 -f /root/.ssh/chatapp_deploy -N "" -C "chatapp-deploy" && cat >> /root/.ssh/config <<EOF

Host github.com
  HostName ssh.github.com
  Port 443
  User git
  IdentityFile /root/.ssh/chatapp_deploy
  IdentitiesOnly yes
  StrictHostKeyChecking accept-new
EOF
chmod 600 /root/.ssh/config'
```

- [ ] **Step 2:【Claude 执行】打印公钥 → 【用户操作】加到 GitHub**

Claude 展示 `cat /root/.ssh/chatapp_deploy.pub` 的内容;用户打开 GitHub 仓库 `yourname/chatapp` → Settings → Deploy keys → Add deploy key → 粘贴,**不勾** Allow write access → Add。

- [ ] **Step 3:【Claude 执行】验证连通并拉代码**

```bash
ssh root@<SERVER_IP> 'ssh -T git@github.com; git clone git@github.com:yourname/chatapp.git /tmp/chatapp-src && cp -a /tmp/chatapp-src/. /www/wwwroot/chatapp/ && rm -rf /tmp/chatapp-src && git -C /www/wwwroot/chatapp log --oneline -1'
```

Expected: `Hi yourname/chatapp! You've successfully authenticated...`;clone 成功;显示 master 最新 short hash。

- [ ] **Step 4:【Claude 执行】venv + 依赖**

```bash
ssh root@<SERVER_IP> '/usr/bin/python3.11 -m venv /www/wwwroot/chatapp-venv && /www/wwwroot/chatapp-venv/bin/pip install -U pip -i https://mirrors.aliyun.com/pypi/simple/ -q && /www/wwwroot/chatapp-venv/bin/pip install -r /www/wwwroot/chatapp/chatapp/requirements.txt -i https://mirrors.aliyun.com/pypi/simple/ -q && /www/wwwroot/chatapp-venv/bin/python -c "import django,rest_framework,celery,redis,django_redis,pymysql,PIL,dotenv; print(\"deps OK\", django.get_version())"'
```

Expected: `deps OK 5.2.x`。

---

### Task 5: 服务器 .env + migrate + collectstatic

**Interfaces:**
- Produces: `/www/wwwroot/chatapp/chatapp/.env`(600,内容见下表);数据库迁移完成(空库);`staticfiles/` 产物。

- [ ] **Step 1:【Claude 执行】生成 SECRET_KEY**

```bash
ssh root@<SERVER_IP> '/usr/bin/python3.11 -c "import secrets;print(secrets.token_urlsafe(50))"'
```

- [ ] **Step 2:【Claude 执行】写 .env + 日志目录**

用 heredoc 一次性写入(值替换后整块执行;`<DB口令>`=Task 3 生成;`<SECRET_KEY>`=Step 1):

```bash
ssh root@<SERVER_IP> "cat > /www/wwwroot/chatapp/chatapp/.env <<'EOF'
…(下表全键值,逐行写入)…
EOF"
```

.env 全表:

```ini
SECRET_KEY=<SECRET_KEY>
DEBUG=0
ALLOWED_HOSTS=<SERVER_IP>,127.0.0.1
DB_NAME=chatapp
DB_USER=chatapp
DB_PASSWORD=<DB口令>
DB_HOST=127.0.0.1
DB_PORT=3306
DB_SSL_DISABLED=1
REDIS_URL=redis://127.0.0.1:6379/0
BROKER_URL=redis://127.0.0.1:6379/1
IM_SDKAPPID=<与开发 .env 相同>
IM_SECRETKEY=<与开发 .env 相同>
SMS_DEV_MODE=1
AUTO_APPROVE=1
MEDIA_BASE_URL=http://<SERVER_IP>
LOG_FILE=/www/wwwlogs/chatapp/app.log
```

```bash
ssh root@<SERVER_IP> 'mkdir -p /www/wwwlogs/chatapp && chmod 600 /www/wwwroot/chatapp/chatapp/.env'
```

⚠️ IM 两个凭据从本地 `chatapp/.env` 读取后填(执行时操作,不落计划文本)。

- [ ] **Step 3:【Claude 执行】migrate + collectstatic + 连通自检**

```bash
ssh root@<SERVER_IP> 'cd /www/wwwroot/chatapp/chatapp && /www/wwwroot/chatapp-venv/bin/python manage.py migrate --noinput && /www/wwwroot/chatapp-venv/bin/python manage.py collectstatic --noinput | tail -1 && /www/wwwroot/chatapp-venv/bin/python manage.py shell -c "from django.db import connection; connection.cursor().execute(\"SELECT 1\"); from django.core.cache import cache; cache.set(\"x\",\"1\"); assert cache.get(\"x\")==\"1\"; print(\"db+redis OK\")"'
```

Expected: 迁移全部 applied;`N static files copied`;`db+redis OK`。

---

### Task 6: 进程守护两条进程(用户操作 + Claude 核对)

**Interfaces:**
- Produces: `chatapp-web`(gunicorn 127.0.0.1:8000)与 `chatapp-celery` 两条守护进程,开机自启。

- [ ] **Step 1:【用户操作】宝塔 → 软件商店 → 进程守护管理器 → 添加守护进程**(照下表加两条)

| 字段 | chatapp-web | chatapp-celery |
|---|---|---|
| 名称 | `chatapp-web` | `chatapp-celery` |
| 启动用户 | root | root |
| 运行目录 | `/www/wwwroot/chatapp/chatapp` | `/www/wwwroot/chatapp/chatapp` |
| 启动命令 | `/www/wwwroot/chatapp-venv/bin/gunicorn config.wsgi:application -b 127.0.0.1:8000 -w 2 --timeout 120` | `/www/wwwroot/chatapp-venv/bin/celery -A config worker -l info --concurrency=1` |
| 进程数量 | 1 | 1 |
| 开机启动 | 勾选 | 勾选 |

- [ ] **Step 2:【Claude 执行】核对**

```bash
ssh root@<SERVER_IP> 'ss -tlnp | grep 8000; curl -s http://127.0.0.1:8000/api/v1/health; echo; curl -s http://127.0.0.1:8000/api/v1/readyz; echo; ps -ef | grep "[c]elery" | head -3'
```

Expected: 8000 有 gunicorn 监听;health 返回 `{"status":"ok"}`;readyz 返回 checks 双 ok;celery 进程在。

---

### Task 7: nginx 反代 + 静态直出

**Interfaces:**
- Consumes: Task 6 的 `127.0.0.1:8000`;Task 5 的 `staticfiles/`;搬迁前的 `media/` 目录(Task 8 才填内容,先建空目录避免 404 报错)。
- Produces: `http://<SERVER_IP>/` 全站可达。

- [ ] **Step 1:【Claude 执行】定位并备份站点 conf**

```bash
ssh root@<SERVER_IP> 'ls /www/server/panel/vhost/nginx/; cp <站点conf> <站点conf>.bak.20260918'
```

- [ ] **Step 2:【Claude 执行】改写 server 块**(保留宝塔原有 #SSL/日志等注释结构与 include,只替换 `server {}` 主体)

```nginx
server {
    listen 80;
    server_name <SERVER_IP>;
    client_max_body_size 60m;

    location /static/ {
        alias /www/wwwroot/chatapp/chatapp/staticfiles/;
    }
    location /media/ {
        alias /www/wwwroot/chatapp/chatapp/media/;
    }
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }
}
```

```bash
ssh root@<SERVER_IP> 'mkdir -p /www/wwwroot/chatapp/chatapp/media && nginx -t && nginx -s reload'
```

Expected: `syntax is ok` / `test is successful`。

- [ ] **Step 3: 端到端验证**

Run(【Claude 执行】服务器):`curl -s http://127.0.0.1/api/v1/health; curl -s http://127.0.0.1/api/v1/readyz`
Run(【Claude 执行】本机):`curl -s http://<SERVER_IP>/api/v1/health; curl -sI http://<SERVER_IP>/static/<collectstatic 实际产物,如 ops/vendor/...>`
Expected: 外部 health/readyz 200;静态文件 200。

---

### Task 8: 数据搬迁(dump + media + IM 头像刷新)

**Interfaces:**
- Consumes: 本地 `chatapp/.env`(读 DB 口令);服务器 chatapp 库/账号(Task 3)。
- Produces: 服务器库=开发库快照;`media/` 照片就位;腾讯 IM 侧头像 URL 刷新为服务器地址。

- [ ] **Step 1:【Claude 执行】本地导出**

```bash
"/c/Program Files/MySQL/MySQL Server 8.0/bin/mysqldump.exe" -h127.0.0.1 -u chatapp -p<本地口令> \
  --single-transaction --default-character-set=utf8mb4 chatapp_dev | gzip > /tmp/chatapp_dev.sql.gz
ls -lh /tmp/chatapp_dev.sql.gz
```

- [ ] **Step 2:【Claude 执行】上传 + 导入**

```bash
scp /tmp/chatapp_dev.sql.gz root@<SERVER_IP>:/tmp/
ssh root@<SERVER_IP> 'gunzip -c /tmp/chatapp_dev.sql.gz | mysql -u chatapp -p<服务器口令> chatapp && mysql -u chatapp -p<服务器口令> chatapp -e "SELECT COUNT(*) FROM users_user; SELECT COUNT(*) FROM users_photo; SELECT COUNT(*) FROM feed_post;"'
```

Expected: 三张表计数与本地一致(本地查同样三条对比)。

- [ ] **Step 3:【Claude 执行】media 上传**

```bash
cd /d/pycharmproject/chat_app && tar czf /tmp/media.tar.gz -C chatapp media
scp /tmp/media.tar.gz root@<SERVER_IP>:/tmp/
ssh root@<SERVER_IP> 'tar xzf /tmp/media.tar.gz -C /www/wwwroot/chatapp/chatapp/ && du -sh /www/wwwroot/chatapp/chatapp/media'
```

- [ ] **Step 4:【Claude 执行】IM 头像 URL 刷新**(把腾讯 IM 侧头像指到服务器地址)

```bash
ssh root@<SERVER_IP> 'cd /www/wwwroot/chatapp/chatapp && /www/wwwroot/chatapp-venv/bin/python manage.py shell -c "
from django.contrib.auth import get_user_model
from im.tasks import sync_profile
ids = list(get_user_model().objects.filter(photos__status=\"approved\").distinct().values_list(\"id\", flat=True))
print(\"avatars to sync:\", len(ids))
for uid in ids:
    sync_profile.run(uid, \"avatar\")
print(\"done\")
"'
```

- [ ] **Step 5:【Claude 执行】照片可访问性抽查**

服务器上挑一张实际照片路径(`ls /www/wwwroot/chatapp/chatapp/media/photos/*/*/ | head`),本机 `curl -sI http://<SERVER_IP>/media/photos/...` → 期望 200。

---

### Task 9: 端到端验收(App 重打包 + 用户手测)

- [ ] **Step 1:【Claude 执行】接口层验收**

```bash
curl -s http://<SERVER_IP>/api/v1/health
curl -s http://<SERVER_IP>/api/v1/readyz
curl -sI http://<SERVER_IP>/ops/     # 期望 302 跳登录页
```

- [ ] **Step 2:【Claude 执行】重打模拟器包**

```bash
cd app && ../flutter/bin/flutter.bat build apk --release --dart-define=API_BASE=http://<SERVER_IP>/api/v1
```

产物:`app/build/app/outputs/flutter-apk/app-release.apk`

- [ ] **Step 3:【用户操作】安装 + 手测**(模拟器在线时 `adb -s emulator-5554 install -r <apk>`)

手测清单:
1. 登录(搬迁过来的测试号,验证码 123456);
2. 发现卡:有照片、能滑;
3. 配对:两个测试号互滑(按搬迁时的实际配对状态;要重演用服务器上 `manage.py dev_reset_pair --a uX --b uY`);
4. 聊天:收发消息(IM 直连腾讯,与服务器数据无关但需登录态);
5. 消息页绿点 / 广场发帖点赞评论 / 我的页资料;
6. 浏览器 `http://<SERVER_IP>/ops/` 用 staff 账号登录,举报队列可见。

- [ ] **Step 4:【Claude 执行】面板侧验证**:进程守护里两条进程「运行中」;把 `chatapp-web` 重启一次,10 秒后 `curl -s http://<SERVER_IP>/api/v1/health` 恢复 200(验证崩溃拉起)。

---

### Task 10: 部署手册 + CLAUDE.md + 合并推送

- [ ] **Step 1: 写 `docs/deploy-runbook.md`**

内容:服务器概况(IP/面板端口/路径/venv)、更新六步(本地 push → 服务器 pull → pip → migrate → collectstatic → 面板重启)、常见操作(看日志 / 连数据库 / 跑管理命令 / dev_reset_pair)、本阶段已知事项(未备案、面板 SSH 密码登录未关、AUTO_APPROVE=1、备份待做)。

- [ ] **Step 2: 更新 `CLAUDE.md`**:「当前进度」段追加 M4 部署第一步摘要;「常用命令」补服务器操作入口(指向 runbook)。

- [ ] **Step 3: 提交 + 合并 + 推送**

```bash
git add docs/deploy-runbook.md CLAUDE.md
git commit -m "docs: M4 部署手册(服务器跑通)+ CLAUDE.md 更新"
cd chatapp && python manage.py test    # 最终回归,全绿
cd .. && ../flutter/bin/flutter.bat analyze   # (cwd=app) 零告警
git checkout master && git merge --ff-only m4-deploy && git branch -d m4-deploy && git push origin master
```

---

## 自查记录(写计划时已核对)

- spec §3-§9 全部有对应 Task(§3↔T4/§4↔T7/§5↔T3+T5/§6↔T8/§7↔T1+T2/§8↔T9/§9↔各任务内)。
- 接口签名与既有代码核对过:`health` 在 `accounts/views.py`、路由在 `config/api_urls.py`、`sync_profile(user_id: int, kind: str)` 在 `im/tasks.py:113`、`.gitignore` 已忽略 `staticfiles/`+`media/`+`.env`。
- 执行时生成的值(DB 口令、SECRET_KEY)属运行时秘密,非占位符。
