# 交接:批次 U / V / T / W-L3(给新对话)

- **状态**:**已闭环**(2026-11-11)—— U / V / T 三批于 2026-11-10 交付,W-L3(golden 截图)于 2026-11-11 交付(PR #242,`74c1cef`);六批全部合并进 `master`,发版留给主人
- **交接日期**:2026-11-10
- **交接时的 `master`**:`50ebeac`(**接手前先 `git pull --ff-only` 确认已前进**)
- **上位文档**:[批次 R–W 设计](../specs/2026-11-09-batch-r-w-design.md)(总纲)、
  [AGENTS.md](../../../../AGENTS.md)(执行约束)、[CLAUDE.md](../../../../CLAUDE.md)(契约)、
  [心跳 UI 规则](../../specs/2026-09-15-ui-design-language-design.md)(App UI 强制)

---

## 1. 已经做完了什么(不要重做)

| 批次 | PR | 交付内容 |
|---|---|---|
| **W-L1** 发版自动化 | #200 | `scripts/release_prep.py`(前置闸门 + 版本号三处 + 门禁 + notes 草稿 + 待执行命令),23 条自测进 `contract` 轨 |
| **R** 资料语音自我介绍 | #203 #207 #208 | `ProfileVoice` + `POST/DELETE /users/me/voice` + `voice` 字段;App 录音卡(30 秒)+ 播放条;Web 同构 |
| **S** 发现页筛选 + 每日精选 | #212 #214 #216 | `CandidateFilters`(不落库)+ 缓存指纹分桶 + `GET /discovery/daily`;双端筛选面板 + 精选区块 |
| **U** 广场点赞列表 + 收藏 | #221 #224 #226 | `feed.PostFavorite` + 四个接口(点赞列表 / 收藏 / 取消收藏 / 我的收藏)+ `is_favorited` 用 `Exists` 注解;双端点赞列表页与「我的收藏」 |
| **V** 运营数据看板 | #231 #232 | `users/activity.py` 日活集合(**新增基建**,presence 回填不出 DAU)+ `stats.DailyMetric` + `manage.py metrics_daily` + `/ops/metrics/` |
| **T** 聊天体验打磨 | #238 #239 #240 | `im_message_hidden` + `POST /im/api/messages/delete`(**单方删除、零帧改动**)+ 三处读口径;双端多选删除 / 草稿 / 图片全屏 / 语音进度与倍速 |

各批的执行记录(含踩坑)在:
[R 批](2026-11-09-batch-r-voice-intro.md) §执行记录 · [S 批](2026-11-09-batch-s-filter-daily.md) §执行记录。

**已确认无需再查的事实**:

- 广场**已经支持单条 1–9 张图**(`feed.PostImage` + `PostCreateSerializer` 校验),Web `PostCard` 有 1/2/3 列网格 ——
  所以 U 批的「多图」**不做**,只剩「点赞列表 + 收藏」。
- `scripts/superagent-closeout.sh`(L1)与 `.github/workflows/app-ui.yml`(L3 模拟器轨)**已上线**;
  app-ui 现在跑 `smoke_test.dart` + `discovery_filter_test.dart` 两条 integration_test。
- imserver 迁移到 `007_conversation_flags.sql`,下一张是 `008`。
- `/ops/` 有完整模板体系(`base.html` + 各页面),新增看板页照抄即可。

---

## 2. 剩余批次的范围(W-L3;U、V、T 已于 2026-11-10 交付)

> U / V / T 的原始范围保留在下面并标了 ✅ —— 留着是为了让后续工作知道「这三批做了什么、踩了什么」,
> 执行记录分别在 [U 批](2026-11-10-batch-u-square-likes-favorites.md)、
> [V 批](2026-11-10-batch-v-ops-metrics-dashboard.md)、
> [T 批](2026-11-10-batch-t-chat-polish.md) 的末尾。

### U 批:广场点赞列表 + 收藏(3 单:backend → app → web)—— ✅ 已交付(#221 #224 #226)

**要做什么**

1. `GET /api/v1/posts/{post_id}/likes`:游标分页,返回 `user_id` / 昵称 / 头像;
   可见性同广场(排除双向拉黑与重封禁作者)。
2. `feed.PostFavorite`(`unique(post, user)` + `(user, -created_at)` 索引)+ 迁移;
   `POST` / `DELETE /api/v1/posts/{post_id}/favorite`(幂等 204);
   `GET /api/v1/feed/favorites`(我的收藏,游标分页,帖子被删则自动消失)。
3. `PostSerializer` 新增 `is_favorited` —— **必须批量查**(整页一次 `values_list` 或一条分组查询),
   逐条查会让广场一页 20 条变 20 次 SQL,`config/test_query_budget.py` 会红。
4. 双端:动态卡片长按/更多菜单加「收藏」;点赞数点开进点赞列表页;「我的收藏」入口。
5. 收藏**不发通知**(与关注同口径,避免洪水)。

**验收要点**:后端绿 + `docs/api/feed.md` 与 openapi 同步;点赞列表对拉黑用户不可见;重复收藏幂等;
删帖后收藏列表不再出现;查询预算不超标。

### V 批:运营数据看板(backend 单栈,1–2 单)—— ✅ 已交付(#231 #232)

**要做什么**

1. `manage.py metrics_daily`(默认算昨天,`--date` 指定,`--backfill N` 回填):
   写 `stats.DailyMetric` 快照 —— DAU(120 秒内有认证请求)、新注册、完善资料数、滑卡数、
   配对率、消息量(读 `chatapp_im`)、活跃时段分布。
2. **cron 每日 04:30**(~~03:40~~ —— 03:40 已被 `refresh_shuffle_keys` 占用,见
   `docs/ops/imserver.md` §12.5;03:20 备份、04:00–04:20 媒体维护),日志进 `/www/wwwlogs/`。
   **不引入 Celery beat** —— 项目惯例是 cron + `manage.py` 命令(见 `deploy/ops/chatapp-backup.sh`)。
3. `/ops/metrics/` 看板页:近 30 天趋势表 + 7 日留存。沿用 `/ops/` 模板与 `StaffSecurityMiddleware`。
4. 只读、服务端渲染,**不进 `/api/v1`**(不受 `ApiDocsCoverageTests` 约束)。

**坑**:① 跨库读 `chatapp_im` 要走 IM 库凭据(`IM_MYSQL_DSN`),不能用应用账号;
② 留存要按「首日注册 cohort」算,别用活跃日反推;
③ **DAU 不能从 `presence` 反推**:presence 只有 7 天 TTL 的「最后活跃时间戳」,没有按天去重的历史,
   所以 V 批必须先加 `users/activity.py` 的日活集合(见 §4.8)。这条**已在 V 批做完**,后续批次直接复用。

### T 批:聊天体验打磨(3 单:imserver → app → web)—— ✅ 已交付(#238 #239 #240)

**要做什么**

1. **imserver(唯一动库的一批,零 WS 帧改动)**:迁移 `008` 建 `im_message_hidden(user_id, msg_id, unique)`;
   新 HTTP 接口 `POST /im/api/messages/delete`(body `{ids:[...]}`,上限 50 条/次、幂等、只删自己可见的);
   `GET /im/api/messages` 与 `conversations` 的**未读数与 `last_message` 必须排除已隐藏行**。
   —— 多选删除是「**仅删我这一侧**」,不触碰消息本体、不通知对端(与微信一致)。
2. App / Web:长按消息 → 多选 → 批量删除/复制;发送失败气泡「未发送」+ **手动重发**;
   草稿(App `shared_preferences` / Web `localStorage`,会话列表显示「[草稿]」);
   图片点击全屏(双指缩放 + 左右切);语音进度条可拖 + 1.0x/1.5x/2.0x 倍速。

**不做**:自动重发 / 断线队列(要 `client_msg_id` 幂等键 → 改 `send` 帧 → 三端 fixture 联动,
收益不抵成本,留单独一单)、双向删除、消息编辑。

**坑**:① 隐藏表的 `NOT EXISTS` 要进既有查询,别让历史分页全表扫;② 未读数与 `last_message`
三处口径必须同改,漏一处就是「删了还占未读」。

### W-L3:golden 截图(1 单,内联)

把 `app/integration_test/smoke_test.dart` 从「冷启动到登录页」扩到「登录页 + 一个主页面」的 golden 比对。

**已知陷阱**:像素比对在 **Windows 模拟器**与 **GitHub Ubuntu runner** 之间会不一致 ——
只能在 CI 里生成、在 CI 里比对;本地 `--update-goldens` 产出的基准图**不能**直接当 CI 基准。

---

## 3. 工作流(照这个跑,已验证 6 单)

```
设计 spec / plan(内联写,进 docs/superpowers/)
  → 开 issue(.github/ISSUE_TEMPLATE/agent-task.yml 五段:背景/验收口径/影响栈/禁止事项/不在范围)
  → 评论 @shiliu655 派单
  → 等 PR(约 10–25 分钟;App 单更久)
  → 逐行看 diff + 本地验收
  → scripts/verify.sh <stack> 全绿
  → CI 全绿
  → squash 合并
  → scripts/superagent-closeout.sh(先 pull 母体再 prune)
  → 补 plan 的执行记录 + docs/milestones.md 一行 → 纯文档 PR 直接合并
```

**派单后必须核入队**(`docs/ops/superagent.md` §4.1):等约 2.5 分钟,查 `thread` / `trigger_thread`
两张表;3 分钟仍为 0 就**补发一条新评论**(不要改 issue 正文)。每单都要核。

**但「三张表全空」有两种含义,别混**:
① 真丢单 → 补发;
② **上一轮轮询还在飞**(一轮要串行读完所有订阅 Thread,几分钟很正常)。
区分办法:看 `kv` 里的 `github-since` —— **停在几分钟前的旧时间戳 = 轮在跑;它跟着推进而 230 号这类
新 issue 始终没有 `github-cursor:<n>` = 真丢单**。V 批派 #230 时就是前者:3 分钟全空、第 10 分钟三样
齐全。补发一条是无害的(trigger 幂等),但别因为「空」就去重启 worker。

```bash
wsl -e bash -c 'python3 - <<PY
import sqlite3
db=sqlite3.connect("file:/root/.dsh/state/superagent/orchestrator.sqlite?mode=ro",uri=True);c=db.cursor()
n="<issue号>"
print("thread:", c.execute("select count(*) from thread where key=?",(f"github:{n}",)).fetchone()[0],
      "trigger:", c.execute("select count(*) from trigger_thread where thread=?",(f"github:{n}",)).fetchone()[0])
PY'
```

---

## 4. 必须知道的坑(全是本次踩过的)

### 4.1 模拟器手测:**不要目测坐标**

截图预览会被缩放,目测的 y 与真实像素差过 **300~400px**,表现为「点了没反应」,
极易误判成组件手势 bug —— 本次因此连续两轮误报「筛选面板点不动」,还让实现方白改了一次。
**一律用 Pillow 从原始 PNG 里找目标控件的色块 / 深色文字 bbox 再点**:

```python
from PIL import Image
im = Image.open('shot.png').convert('RGB'); px = im.load()
rows = {}
for y in range(1600, 2100):
    xs = [x for x in range(60, 1020) if sum(px[x, y]) < 520]
    if xs: rows[y] = (min(xs), max(xs))
# 相邻行聚类 → 得到每行控件的 y 范围,取中心点
```

**T 批实测(2026-11-10)**:截图预览与原始像素的缩放比 ≈ **1.125**。按预览坐标点长按菜单的「多选」
落在两个菜单项之间的空隙上,现象是「菜单关了但没进多选」——**差 30px 就点空**。
判据要看「点完之后界面状态有没有变」(顶栏有没有变成「已选 N 条」),不能看「菜单有没有关」。

另外 `adb shell uiautomator dump` 对 Flutter **只给一个空壳节点**(拿不到控件 bounds),
所以坐标只能靠 Pillow 量;长按用 `adb shell input swipe x y x y 900`。

### 4.2 multipart 的 part MIME 必须显式声明

App `MultipartFile.fromBytes` 不传 `contentType` → 退化成 `application/octet-stream` →
后端白名单不含 → **必然 400**。仓库里 `app/lib/im/self_voice_uploader.dart` 早有这条注释。
Web 侧同理(`Blob.type` 为空时),参照 `web/src/api/users.ts::uploadProfileVoice` 的兜底写法。

### 4.3 Android 明文 HTTP:原生播放器失败而 Dart HTTP 不受限

`targetSdk >= 28` 时 audioplayers(ExoPlayer)禁 `http://`,Dio 走 socket 照常通 ——
症状是「接口全通、上传 201、语音/视频播不了」。debug manifest 已放开
(`app/android/app/src/debug/AndroidManifest.xml`),release 仍禁。
`Image.network` 走 `dart:io`,**不受**影响,所以只有原生解码的媒体会中招。

### 4.4 「签名只有在有人验签时才是签名」

给媒体加限时签名前先看 nginx 模板:`/media/chat/` 有 `auth_request`,
`/media/` 是**裸静态**。本次 R 批一度给资料语音签了名但没人校验,等于安全剧场,已改回与照片同口径。

### 4.5 widget 测试绿 ≠ 真机能点

`tester.tap(find.text('旅行'))` 直接命中 widget,不经过真实 hit test。
S 批因此补了 `app/integration_test/discovery_filter_test.dart`(走真实指针事件)。
**碰 App UI 的单,尽量让实现方同时给一条 integration_test**。

### 4.6 本地后端容易跑着旧代码

改了后端之后**必须重启 `runserver`**(`--noreload` 下不会自动加载),
否则会出现「新接口 404」这种假故障(本次 `/discovery/daily` 一开始 404 就是这个原因)。

**它的另一种形态(2026-11-10 U 批踩到):旧进程占着 8000,新进程静默起不来。**
机器上残留着一个几小时前启动的 `runserver`,端口被它占着;我新起的进程绑定失败、
后台 job 只显示一个退出码,**看起来像「服务起来了」**。于是 `/posts/{id}/likes`
与 `/feed/favorites` 全 404、而 `/posts` 正常 —— 极容易被误判成「新接口没注册」。
手测前先确认监听 8000 的是**哪个进程、什么时候启动的**:

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen | ForEach-Object { $_.OwningProcess }
Get-Process python | Select-Object Id, StartTime
```

`StartTime` 早于本次改动 = 旧进程,先 `Stop-Process` 再起。

本地起后端的完整环境变量(Windows + conda `Django` + CI 容器):

```powershell
$env:DB_PORT="13306"; $env:DB_USER="chatapp"; $env:DB_PASSWORD="chatapp_ci"; $env:DB_NAME="chatapp_dev"
$env:REDIS_URL="redis://127.0.0.1:16379/0"; $env:BROKER_URL="redis://127.0.0.1:16379/1"
$env:DEBUG="1"; $env:SMS_DEV_MODE="1"; $env:SMS_PHONE_WHITELIST="13800138000,13900139000,13700137000"
# ffmpeg 走 winget 装的 Gyan.FFmpeg,需把 bin 目录加进 PATH
```

依赖容器:`docker compose -f docker-compose.ci.yml up -d mysql redis`。

### 4.7 单端登录会互顶

用 curl 以 `app` 身份登录会踢掉模拟器上的 App 会话(批次 M 单端互顶)。
需要在后台验接口时,加 `X-Client: web` 头走另一端,别把正在手测的 App 顶掉。

### 4.8 `verify.sh` 不带 `--keep-deps` 会**清空 dev 库**

`scripts/verify.sh` 收尾时 `docker compose down -v` 删卷;MySQL 下次启动重新 initdb,
`chatapp_dev` 里你手测造的数据**全没**。表现很像「口径变了」:V 批实测 `--dry-run` 昨天还
`new=3`,隔一次 `verify` 再跑变 `0` —— 其实是库被重置。

**手测期间一律 `scripts/verify.sh backend --keep-deps`**,要造数据就再造一遍。

### 4.9 想在 `shell` 里看真页面,`ALLOWED_HOSTS` 要含 `127.0.0.1`

不开浏览器也能验服务端渲染的运营页:`manage.py shell` 里用 Django test client 渲染,再正则去标签看正文。
但 dev 的 `ALLOWED_HOSTS` 不含 `testserver`,直接 `client.get(...)` 会 **400 DisallowedHost**。
写法:`client.get("/ops/metrics/", HTTP_HOST="127.0.0.1")` + `export ALLOWED_HOSTS=127.0.0.1,localhost`。
V-2 就是这么验的(staff 200 / 非 staff 403 / 匿名 302 + 逐格核对数字)。

### 4.10 手测「聊天」要一整套 IM 栈,而它不在仓库里

后端手测只要 Django;但**聊天类改动**还要一个能收发的 imserver。仓库里只有 `imserver/docker-compose.test.yml`
(一次性的测试栈),没有 dev compose。T 批这套是这么拼出来的(可复用):

```bash
# 1) 起 imserver 的 MySQL/Redis(带网络 imserver_default)
cd imserver && docker compose -f docker-compose.test.yml up -d mysql redis
# 2) 用 PR 分支的源码构建镜像(含最新迁移),先跑 --migrate 再起常驻容器
docker build -t imserver:handtest -f Dockerfile .
docker run --rm --network imserver_default -e IM_MYSQL_DSN=... imserver:handtest --migrate
docker run -d --name im-handtest --network imserver_default -p 9100:9100 -p 9101:9101 \
  -e IM_LISTEN_WS=0.0.0.0:9100 -e IM_LISTEN_HTTP=0.0.0.0:9101 -e IM_ALLOW_PUBLIC_BIND=1 \
  -e IM_INTERNAL_ALLOW=0.0.0.0/0 ...  imserver:handtest
```

三个坑:

1. **`/internal/*` 默认只认 `127.0.0.1`**:Django 在宿主机、经 Docker 发布端口进来时源 IP 是网桥网关,
   `/internal/send` 一律 **403**。本地一次性手测容器要 `IM_INTERNAL_ALLOW=0.0.0.0/0`。
2. **`IM_JWT_SECRET` 必须等于 Django 的 `IM_SELF_SECRET`**,`IM_INTERNAL_SECRET` 等于 `IM_SELF_INTERNAL_SECRET`
   (`im/token.py::mint_im_token` 用前者签、imserver 用同名密钥验)。
3. **Django 要给模拟器的地址,不是给自己的地址**:`IM_SELF_URL` 用 `http://127.0.0.1:9101`(Django→imserver),
   而 `IM_SELF_WS_URL`/`IM_SELF_HTTP_URL`/`MEDIA_BASE_URL` 必须写 `10.0.2.2`(`/im/user_sig` 会把它们原样发给客户端)。

**还有一个断点**:`/internal/send` 只支持 `kind=text|custom`,**造不出图片/语音消息** ——
想在本地验「图片全屏 / 语音播放」,只能从 App 真实上传(见 T 批遗留 4)。

### 4.11 `flutter build apk` 只能在 Windows 侧跑

WSL 里没有 Android SDK(`No Android SDK found`),`verify.sh app` 跑得动只是因为它是 `analyze` + `test`。
出 APK 装模拟器要在 Windows 仓库里:

```powershell
git fetch origin <agent 分支>; git checkout -B handtest FETCH_HEAD
cd app; ..\flutter\bin\flutter.bat build apk --debug --dart-define=API_BASE=http://10.0.2.2:8000/api/v1
```

debug 包才放开明文 HTTP(§4.3);测完记得 `git checkout master` 并把临时分支删掉。

---

## 5. 开新对话提示词(直接复制)

```
读 docs/superpowers/plans/2026-11-10-batch-u-w-handoff.md,按里面的「剩余批次」做 W-L3(golden 截图)。
先 git pull --ff-only 确认 master 已前进(U、V、T 三批已于 2026-11-10 合并,当前应在 50ebeac 之后)。
W-L3 是**内联做的**(流程自身,不开工单):把 app/integration_test/smoke_test.dart 从「冷启动到登录页」
扩到「登录页 + 一个主页面」的 golden 比对,并进 app-ui.yml。
**已知陷阱**:像素比对在 Windows 模拟器与 GitHub Ubuntu runner 之间会不一致 ——
基准图只能在 CI 里生成、在 CI 里比对;本地 --update-goldens 产出的基准图不能直接当 CI 基准。
文档 §4 的坑都要遵守(尤其 §4.11:APK 只能在 Windows 侧构建)。
做完这一批,六批就齐了:按 spec §6 汇总一份**发版清单**交主人(版本号 / notes / tag / Release / 部署)。
```


---

## 6. 全局口径(每批都适用)

- **一单一条栈**;契约联动(openapi / `docs/api/` / WS fixture / tokens)属同栈附带改动,同一次做完。
- 验证唯一入口 `scripts/verify.sh <stack>`;推之前必须绿,输出贴 PR 正文。
- App UI 改动必须在 `emulator-5554` 上逐页手测并截图;PR 开 draft,正文写「等待模拟器验收」。
- **不动版本号、不打 tag、不建 Release、不部署生产** —— 留给主人统一发版。
- 每批合并后立刻 `scripts/superagent-closeout.sh`,并确认输出里 `same=yes`。
