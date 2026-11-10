# 交接:批次 U / V / T / W-L3(给新对话)

- **状态**:待接手
- **交接日期**:2026-11-10
- **交接时的 `master`**:`bb2065d`(**接手前先 `git pull --ff-only` 确认已前进**)
- **上位文档**:[批次 R–W 设计](../specs/2026-11-09-batch-r-w-design.md)(总纲)、
  [AGENTS.md](../../../AGENTS.md)(执行约束)、[CLAUDE.md](../../../CLAUDE.md)(契约)、
  [心跳 UI 规则](../specs/2026-09-15-ui-design-language-design.md)(App UI 强制)

---

## 1. 已经做完了什么(不要重做)

| 批次 | PR | 交付内容 |
|---|---|---|
| **W-L1** 发版自动化 | #200 | `scripts/release_prep.py`(前置闸门 + 版本号三处 + 门禁 + notes 草稿 + 待执行命令),23 条自测进 `contract` 轨 |
| **R** 资料语音自我介绍 | #203 #207 #208 | `ProfileVoice` + `POST/DELETE /users/me/voice` + `voice` 字段;App 录音卡(30 秒)+ 播放条;Web 同构 |
| **S** 发现页筛选 + 每日精选 | #212 #214 #216 | `CandidateFilters`(不落库)+ 缓存指纹分桶 + `GET /discovery/daily`;双端筛选面板 + 精选区块 |

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

## 2. 剩余四批的范围

### U 批:广场点赞列表 + 收藏(3 单:backend → app → web)

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

### V 批:运营数据看板(backend 单栈,1–2 单)

**要做什么**

1. `manage.py metrics_daily`(默认算昨天,`--date` 指定,`--backfill N` 回填):
   写 `stats.DailyMetric` 快照 —— DAU(120 秒内有认证请求)、新注册、完善资料数、滑卡数、
   配对率、消息量(读 `chatapp_im`)、活跃时段分布。
2. **cron 每日 03:40**(在备份之后),日志进 `/www/wwwlogs/`。**不引入 Celery beat** ——
   项目惯例是 cron + `manage.py` 命令(见 `deploy/ops/chatapp-backup.sh`)。
3. `/ops/metrics/` 看板页:近 30 天趋势表 + 7 日留存。沿用 `/ops/` 模板与 `StaffSecurityMiddleware`。
4. 只读、服务端渲染,**不进 `/api/v1`**(不受 `ApiDocsCoverageTests` 约束)。

**坑**:① 跨库读 `chatapp_im` 要走 IM 库凭据(`IM_MYSQL_DSN`),不能用应用账号;
② 留存要按「首日注册 cohort」算,别用活跃日反推。

### T 批:聊天体验打磨(3 单:imserver → app → web)

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
两张表;3 分钟仍为 0 就**补发一条新评论**(不要改 issue 正文)。本次实测漏单率不低,
U/V/T 每单都要核。

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

---

## 5. 开新对话提示词(直接复制)

```
读 docs/superpowers/plans/2026-11-10-batch-u-w-handoff.md,按里面的「剩余四批」继续做 U 批。
先 git pull --ff-only 确认 master 已前进,再按文档 §3 的工作流:写 U 批 plan → 开三张工单
(backend / app / web)→ 派给 worker → 逐行验收 → verify 全绿 → CI 全绿 → 合并 → closeout。
文档 §4 的七个坑必须遵守,尤其 §4.1(模拟器手测用 Pillow 量坐标,不要目测)。
主人已授权「每批自行验收后直接合并」;发版(版本号 / tag / Release / 部署)六批做完后由主人统一执行。
```

V / T / W-L3 各自开工时,把提示词里的「U 批」换成对应批次即可。

---

## 6. 全局口径(每批都适用)

- **一单一条栈**;契约联动(openapi / `docs/api/` / WS fixture / tokens)属同栈附带改动,同一次做完。
- 验证唯一入口 `scripts/verify.sh <stack>`;推之前必须绿,输出贴 PR 正文。
- App UI 改动必须在 `emulator-5554` 上逐页手测并截图;PR 开 draft,正文写「等待模拟器验收」。
- **不动版本号、不打 tag、不建 Release、不部署生产** —— 留给主人统一发版。
- 每批合并后立刻 `scripts/superagent-closeout.sh`,并确认输出里 `same=yes`。
