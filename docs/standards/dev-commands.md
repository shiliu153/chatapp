---
状态: 生效中
复核: 每次命令变更时
---

# 开发命令手册

> 从 `CLAUDE.md`「常用命令」与 `README.md` §6「快速开始」搬来(2026-11-14 治理第 6 节:
> 根文档只留导航与指针)。**这里是「怎么把项目跑起来、怎么跑测试」的唯一 owner**;
> 推之前必须跑什么见 [`AGENTS.md`](../../AGENTS.md) §三,门禁清单见
> [`scripts/gates.toml`](../../scripts/gates.toml),发版清单见
> [`docs/ops/release.md`](../ops/release.md)。

## 0. 前置要求

| 依赖 | 版本 | 说明 |
|---|---|---|
| Python | 3.11+ | 后端(本机用 anaconda 环境 `Django`) |
| MySQL | 8.0+ | 业务库(聊天需另建 `chatapp_im`) |
| Redis | 7.x | 验证码 / 限流 / 缓存 / broker,**跑测试与接口前必须先启动** |
| Flutter | 3.47.x | 客户端 |
| imserver | 随仓库构建 | 自建 C++ IM(WS :9100 / HTTP :9101),聊天功能依赖它 |

## 1. 后端首次跑起来(cwd = `chatapp/`)

```bash
# 1. 建库与账号(先把脚本里的 <YOUR_DB_PASSWORD> 换成自己的口令)
mysql -u root -p < chatapp/db_setup.sql

# 2. 环境变量
cd chatapp
cp .env.example .env
#    至少填 SECRET_KEY / DB_PASSWORD / IM_SELF_SECRET / IM_SELF_INTERNAL_SECRET / IM_MEDIA_PREFIX
#    SECRET_KEY 可用: python -c "import secrets;print(secrets.token_urlsafe(50))"

# 3. 依赖(生产与 CI 一律用锁定文件)
pip install -r requirements.lock

# 4. Redis
docker compose -f docker-compose.dev.yml up -d

# 5. 迁移与管理员
python manage.py migrate
python manage.py createsuperuser

# 6. 启动
python manage.py runserver          # http://127.0.0.1:8000
```

需要真实收发消息时,另起 Celery worker(Windows 仅支持 `solo` 池):

```bash
python -m celery -A config worker -l info --pool=solo
```

> 开发期 `SMS_DEV_MODE=1`,验证码固定 `123456`,不接短信服务商;`AUTO_APPROVE=1` 时上传照片自动过审。
> 生产环境二者必须关闭,准入由 `accounts.PhoneAllowlist`(运营入口 `/ops/allowlist/`)收口。

## 2. 后端日常命令(cwd = `chatapp/`)

```bash
python manage.py test              # 全量(前置:Redis 在跑,见下)
python manage.py test accounts     # 单 app
python manage.py runserver         # 开发服务器 :8000
python manage.py makemigrations && python manage.py migrate
python manage.py im_send --from u2 --to u3 --text "你好"   # 手测:代发消息(--notice 发灰条;需先有配对)
python manage.py im_sync_pairs --dry-run                  # 回填现有配对到 imserver(H4 上线必跑)
python manage.py dev_reset_pair --a u8 --b u9              # 手测:清滑卡/配对重演(不清聊天记录)
python manage.py seed_fake_users --count 20                # 造数(幂等;直调 IM 同步,不必等 worker)
python manage.py refresh_shuffle_keys [--dry-run]          # 轮换候选池随机键(建议每天低峰)
python manage.py media_bytes_backfill [--dry-run]          # 回填照片/动态图字节数(M7 上线必跑)
python manage.py media_cleanup [--apply]                   # 清资料图/广场图孤儿文件(默认 dry-run)
python manage.py media_disk_report [--fail-over]           # 媒体磁盘报表;超告警线退出码 1
python manage.py perf_tokens --count 50 --out ../perf/results/headers.jsonl  # 压测:签多账号令牌(写场景用;文件含活令牌,跑完删)
python manage.py allowlist_seed_import [--dry-run]         # 把 .env 的准入名单种子导进库(幂等;不重新启用已停用的号)
```

**Redis / Celery**(验证码、限流、异步 IM 副作用都靠它们):

```bash
docker compose -f docker-compose.dev.yml up -d             # Redis 容器(redis:7, 6379);跑测试/接口前必须起
python -m celery -A config worker -l info --pool=solo      # IM 副作用 worker(Windows 只能 solo);改了任务代码必须重启它
```

## 3. 前端(cwd = `app/`)

```bash
flutter pub get
../flutter/bin/flutter.bat analyze   # 必须零告警
../flutter/bin/flutter.bat test
../flutter/bin/flutter.bat run -d emulator-5554 --dart-define=API_BASE=http://10.0.2.2:8000/api/v1
```

桌面 / 浏览器调试:`flutter run --dart-define=API_BASE=http://127.0.0.1:8000/api/v1`。

## 4. 网页端(cwd = `web/`;端到端需要后端 + Redis + Celery 都在跑)

```bash
npm ci
npm run dev          # 开发(代理到 :8000)
npm run test:run     # 单元/组件测试(vitest)
npm run test:coverage # 带覆盖率门槛(70/60/70/70)
npm run e2e          # 端到端(Playwright;自建 build + preview)
npm run type-check && npm run lint   # 必须零错误 / 零告警
npm run build        # 产物 web/dist
```

## 5. 出签名包

keystore `C:\Users\you\chatapp-release.jks`,口令在 `app/android/key.properties`;
两个文件都不入库,务必备份。

```bash
cd app && ../flutter/bin/flutter.bat build apk --release --dart-define=API_BASE=https://chat.shiliu153.cn/api/v1 --dart-define=ERROR_REPORTING=true
```

产物 `app/build/app/outputs/flutter-apk/app-release.apk`。`--dart-define=ERROR_REPORTING=true`
**必须带**(否则线上崩溃与白屏不会上报,见 backlog A-4);Web 侧对应 `web/.env.production` 的
`VITE_ERROR_REPORTING=1`。

**升版本号 = 三处版本号 + tag + Release 三件事同时做**,清单与命令见
[`docs/ops/release.md`](../ops/release.md)(发版记录 owner 是
[`docs/releases.yml`](../releases.yml))。

## 6. 服务器

`ssh root@<SERVER_IP>`(免密);部署形态与更新流程见
[`docs/ops/runbook.md`](../ops/runbook.md) §10「部署形态与更新流程」。
服务器私有的运维手册(面板口令/路径/端口)不入库,本地保留。
