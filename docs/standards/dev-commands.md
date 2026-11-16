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
python manage.py voice_transcode_cleanup [--apply]         # 清语音转码残骸:24h 前的 tmp/voice 文件与 pending 行(默认 dry-run)
python manage.py media_disk_report [--fail-over]           # 媒体磁盘报表;超告警线退出码 1
python manage.py perf_tokens --count 50 --out ../perf/results/headers.jsonl  # 压测:签多账号令牌(写场景用;文件含活令牌,跑完删)
python manage.py allowlist_seed_import [--dry-run]         # 把 .env 的准入名单种子导进库(幂等;不重新启用已停用的号)
```

**Redis / Celery**(验证码、限流、异步 IM 副作用都靠它们):

```bash
docker compose -f docker-compose.dev.yml up -d             # Redis 容器(redis:7, 6379);跑测试/接口前必须起
python -m celery -A config worker -l info --pool=solo      # IM 副作用 worker(Windows 只能 solo);改了任务代码必须重启它
```

**并发跑后端验证**(多个工单 / 多个 worktree 同时跑 `scripts/verify.sh backend`):

```bash
bash scripts/verify.sh backend                    # 依赖栈按检出目录自动派生,互不拆台
CHATAPP_CI_SLOT=7 bash scripts/verify.sh backend  # 同一目录要临时错开(或端口撞了)时指定槽位 0-99
```

每个检出目录起**自己那套**依赖容器:母体检出(`$HOME/src/chatapp`)保持 `chatapp-ci` + MySQL `13306` /
Redis `16379`(文档通篇按这套写);其余目录按路径哈希派生到 `chatapp-ci-s<槽>` + MySQL `13400`-`13499` /
Redis `13500`-`13599`。`MYSQL_PORT` / `REDIS_PORT` / `COMPOSE_PROJECT_NAME` 一旦由外部给出就照用
(CI 就是这么注入它自己那套 service 的)。派生规则只写在 `scripts/stacks/env.sh` 一处,
`scripts/verify.sh backend` 结束时的 `deps down -v` 只拆本项目 —— 这就是两个工单并跑不再互相拆容器的原因。

**母体检出那套常驻栈不是必需项**(2026-11-15 定,原便签「定母体常驻依赖栈去留」):
worker 在自己工单目录里跑 `verify.sh backend` 时自起自拆,与母体的 `chatapp-ci` 无关
(2026-11-15 实测:母体的 `chatapp-ci-mysql` / `chatapp-ci-redis` 两个容器都没起,
而三张工单的 backend 验证全部自给自足跑绿)。所以这两个容器降级为**可选缓存** ——
起了能省一次 `docker up`,没起也照常派单;守门脚本
`scripts/superagent-start/ensure-running.sh` 对它们只报 info,不再报 warn
(此前那句「worker 的验证环境没起」是纯误报)。要手动补缓存(可选):

```bash
cd <任一检出目录> && bash scripts/verify.sh deps        # 只起依赖(不跑门禁)
```

**撞槽兜底与并发上限**(2026-11-15 补):

槽位是「仓库根路径 `cksum % 100`」,两个目录理论上会撞到同一槽(每对约 1%)。撞了不会静默翻车:

- **派生的槽被别的项目占着** → `scripts/stacks/env.sh` 自动顺延到下一个「MySQL / Redis 两个端口
  都空闲」的槽,并在 stderr 打一行
  `[env] 提示:<目录> 派生的槽 9 已被别的项目占用(MySQL 13409 / Redis 13509),顺延到槽 10(…)`;
- **显式 `CHATAPP_CI_SLOT=N` 撞上了** → 不静默改写,直接退出 2 并给出可用槽位(`CHATAPP_CI_SLOT=<空槽>`);
- **本项目自己的栈在跑** → 既不顺延也不报错(那就是复用)。认「自己的栈」按 compose 的
  `project.working_dir` 标签,**不看容器名/项目名前缀**:撞槽的另一个目录起的项目名也叫 `chatapp-ci-s9`;
- 端口探测取两个来源的并集:docker 的已发布宿主端口 + WSL 内 `ss` 的原生监听。**docker 那条不能省**:
  本机 WSL 走 Docker Desktop 的引擎,容器端口发布在 **Windows 宿主** 上,WSL 里的 `ss` 看不到
  (2026-11-15 实测:`chatapp-ci-s9` 明明在跑,WSL 里 13400-13699 的监听列表是空的);
- **野生服务**(宿主上直接装的 MySQL / Redis 占了槽位端口):上面两个探针都看不见,所以再补一次
  「真连一下」(`/dev/tcp`,1s 超时)。连得上但 docker 里没人认领 → **退出 2 并给出空闲槽建议**,
  既不猜着用(可能连到别人的库),也不静默顺延(那会掩盖「段位里有野生服务」这件事)。

顺延出来的栈仍是「同一目录 + 同一规则」算出来的,下次跑还是它。**孤儿栈有机械兜底**(2026-11-15 补):

- `deps.sh up` 成功后会把这个目录起过的**槽**记进状态文件;位置走 `git rev-parse --git-path
  chatapp-ci-slots`(普通检出在 `.git/` 里、worktree 在主仓库 `.git/worktrees/<名>/` 里),
  **不进版本库**,worktree 删掉时一起消失;不在 git 仓库里时退化到 `$TMPDIR`;
- `deps.sh down` 除了拆当前派生的项目,还会把状态里**不是当前槽**的项目一并 `down -v` ——
  前提是该项目的 compose 标签 `project.working_dir` 就是本目录,**别人的栈一律不碰**;
- 所以「占用方消失、派生算回原槽」之后,跑一轮 `bash scripts/verify.sh backend`(收尾会自动 down)
  或 `bash scripts/stacks/deps.sh down`,两套一起收掉,不需要再手记槽位。

**拆除通道**(2026-11-15 补,原来是「拆不掉」的坑):撞槽守卫在 `env.sh` 被 source 的那一刻就跑,
而 `down` 也会 source 它 —— 于是「要拆的栈自己占着那个槽的端口」反而让 `down` 退出 2 并建议换槽,
孤儿栈彻底拆不掉(实测:worker 工单目录被 prune 删掉后留下的 `chatapp-ci-s70`,只能手工
`docker compose -p chatapp-ci-s70 -f docker-compose.ci.yml down -v`)。现在:

- `deps.sh down` 在 source 之前就 `export CHATAPP_CI_NO_COLLISION_GUARD=1`,env.sh 的撞槽判定
  块整块跳过 —— **`down` 不受端口守卫影响**,`CHATAPP_CI_SLOT=N` 撞槽也照拆;
- 守卫跳过之后按 compose 的 `project.working_dir` 标签认领:本目录起的照常 `down -v`;
  项目名下**没有容器也没有卷**就静默放过(干净目录跑一次 `down` 不报错);
  有东西但**不是本目录起的**,默认**拒绝**并打印
  `项目 X 不是本目录起的(working_dir=…,本目录 …);确实要拆就加 CHATAPP_CI_FORCE_DOWN=1`;
- `CHATAPP_CI_FORCE_DOWN=1` 是**孤儿清理通道**:工单目录已被删、`working_dir` 指向不存在的路径时
  用它拆:

```bash
CHATAPP_CI_SLOT=70 CHATAPP_CI_FORCE_DOWN=1 bash scripts/stacks/deps.sh down   # 拆孤儿栈
```

**并发上限**(2026-11-15 两轮实测,15.8GiB 的 WSL,不是推算):

- **单套**:MySQL 390-460MiB + Redis 4-5MiB(空库 388MiB / 4MiB;跑满一轮 backend 全量 1119 个用例后
  458MiB / 5MiB)⇒ **≈0.45GiB/套**;
- **五套同时起**(`/root/work/load1`…`load5`,派生槽 19 / 48 / 56 / 62 / 74,并行 `verify.sh deps`):
  五套全成功,合计 **1907MiB(≈1.86GiB)**,机器还剩 11310MiB 可用 —— 五套只吃 12% 内存;
- **其中两套同时跑 `verify.sh backend` 全量**:各自 `Ran 1119 tests in 114.3s / 114.9s`,两套都
  `全部通过`、4 道门禁全绿;`dmesg` 无 OOM、日志里没有 1053 / 1049 / 1044 那种「拆台」报错。
  对照单跑 100.1s → **并发两套各慢约 14%**,但没有互相拆台。

结论:**同时 5 套是安全的**(内存与端口两笔账都够)。真正的上限不是内存,而是
**槽位空间**(0-99 共 100 个,每套占 1 槽)与 **CPU**(并发跑测试时每套慢 ~14%)。
要超过 5 套并跑,先 `docker stats` 与 `nproc` 各看一眼再决定。

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
