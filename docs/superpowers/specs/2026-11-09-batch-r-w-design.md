# 批次 R–W 设计:语音自我介绍 / 发现筛选 / 广场收藏 / 运营看板 / 聊天打磨 / 发版自动化

- 状态:**已定稿**(2026-11-09 主人在 6 个候选中**全选**,并授权「每批自行验收后直接合并」)
- 立项日期:2026-11-09
- 相关:[AGENTS.md](../../../AGENTS.md)(执行约束)、[CLAUDE.md](../../../CLAUDE.md)(契约)、
  [心跳 UI 规则](2026-09-15-ui-design-language-design.md)(App UI 强制)、[docs/api/](../../api/README.md)(接口文档门禁)、
  [自动化阶梯](2026-11-08-superagent-automation-ladder-design.md)(W 批的依据)

---

## 1. 背景与选型

批次 M–Q(15 个 PR)已随 **1.0.12** 上线,`docs/backlog/` §7 只剩四条运维尾巴(对象存储异地 / 树莓派容量 /
TOTP 重绑 / Loki 常驻),**产品向待办为空**。本轮由主人从 6 个候选中**全部选中**:

| 批次 | 功能 | 一句话 |
|---|---|---|
| **R** | 资料语音自我介绍 | 30 秒语音自我介绍,能看我资料的人就能听 |
| **S** | 发现页筛选 + 每日精选 | 候选池当场按年龄/城市/标签筛;每天 N 张高匹配「今日精选」 |
| **T** | 聊天体验打磨 | 多选删除 / 发送失败提示 / 草稿 / 图片全屏 / 语音进度与倍速 |
| **U** | 广场增强 | 点赞列表 + 动态收藏与「我的收藏」 |
| **V** | 运营数据看板 | `/ops/metrics/`:DAU / 新注册 / 配对率 / 消息量 / 留存 |
| **W** | 发版自动化 | `release` 一条命令(版本三处 + 门禁 + notes 草稿)+ L3 golden 截图 |

### 1.1 主人已拍板的两条口径

1. **语音可见性 = 公开**:任何能看我资料的人都能听(与照片同口径,不做「仅配对后可听」)。
2. **合并授权**:每批 verify 对应栈全绿 + CI 全绿 + 看完 diff 即 squash 合并,**不等确认**;
   **发版动作一律不做**(不升版本号、不打 tag、不建 Release、不部署生产),留给主人统一发版。

---

## 2. 现状核实(动手前查过,纠正了三处预判)

| 预判 | 实际 | 影响 |
|---|---|---|
| 广场只支持单图 | **错**:`feed.PostImage` 单条 1–9 张,序列化器校验,Web `PostCard` 有 1/2/3 列网格 | U 批砍掉「多图」,只做点赞列表 + 收藏 |
| W 的 L1 / L3 未做 | **错**:`scripts/superagent-closeout.sh`(+11 条自测)与 `.github/workflows/app-ui.yml`(android-emulator-runner api 34)均已于 2026-11-08 上线 | W 批改为补两个真实缺口:发版一条命令、L3 golden 截图 |
| 聊天多选删除必须动 WS 协议 | **不必然**:imserver 已有 `revoke`(单条,2 分钟)与 `conversation_delete`;批量删除可照 N 批 `/im/api/conversations/flags` 的先例走 **HTTP + 迁移,零 fixture 改动** | T 批风险从「最贵」降到「中等」 |

其余已核实的基建(本轮直接复用):

- **语音**:`POST /api/v1/im/voices` 已有完整链路 —— `im/voice.py::normalize`(ffprobe 校验时长 → ffmpeg 转 m4a/AAC)、
  `ChatVoice` 模型、`media_sign.sign_url` 限时签名、存储配额按 `bytes` 求和、缺 ffmpeg 时 503+`50302`。
- **候选池**:`discovery/services.py` 已按 `Preference`(性别/城市/年龄)服务端过滤,`candidate_pool_ids` 走缓存,
  缓存键带**用户版本 + 全局版本**,`CANDIDATE_CACHE_TTL<=0` 是显式熔断开关。
- **运营后台**:`/ops/` 模板体系与 `StaffSecurityMiddleware` 就绪;项目惯例是 **cron + `manage.py` 命令**(如 `chatapp-backup.sh`),不是 Celery beat。
- **撤回/贴纸/引用/typing**:均已在线,`frames.h` 有 `revoked` / `self_read` / `conversation_deleted` / `typing` 帧。

---

## 3. 批次总览与顺序

| 顺序 | 批次 | 栈与 PR 数 | 为什么排这里 |
|---|---|---|---|
| 1 | **W** 发版自动化 | 内联(1 PR) | 流程自身的引导,**按 AGENTS.md 必须本会话内联做**;先做完,后面 5 批的收尾与最终发版都用得上 |
| 2 | **R** 语音自我介绍 | backend → app → web(3 PR) | 基建已付过账,边际成本最低;先把「拆单→verify→PR→CI→合并→同步」整条链跑顺 |
| 3 | **S** 发现筛选 + 精选 | backend → app → web(3 PR) | 唯一会动缓存键的一批,放链路已验证之后 |
| 4 | **U** 广场点赞列表 + 收藏 | backend → app → web(3 PR) | 纯追加式新表新接口,与 S 零耦合 |
| 5 | **V** 运营看板 | backend 单栈(1–2 PR) | 只读聚合,无回归面;放在动过 backend 的两批之后顺手收口 |
| 6 | **T** 聊天打磨 | imserver → app → web(3 PR) | 唯一要动 imserver 表结构的一批,风险隔离在最后 |

**每批内部固定顺序**:先服务端(契约源头),再 App,再 Web。同一批里后一栈的 PR 依赖前一栈已合并。

---

## 4. 各批设计

### 4.1 R 批:资料语音自我介绍

**做什么**

1. 后端(`users` app,复用 `im/voice.py`):
   - `ProfileVoice`(OneToOne `Profile`,`file` / `bytes` / `duration_ms` / `created_at`);
   - `POST /api/v1/users/me/voice`(multipart `file`,**≤30 秒**、≤5MB、m4a/aac/webm/ogg → 统一转 m4a/AAC,计入存储配额,超限 413+`41301`,缺 ffmpeg 503+`50302`);重复上传 = 覆盖;
   - `DELETE /api/v1/users/me/voice`(幂等 204,同时删文件);
   - `PublicProfileSerializer` / `GET /users/me` 新增 `voice: {url, duration_ms} | null`,**url 走限时签名**(与聊天语音同机制);
   - 语音**不进**「资料完善」判定(完善仍看昵称/性别/生日/城市/简介 + 1 张过审照片),避免老用户突然变 incomplete。
2. App:`profile` 录音(按住录制、试听、删除、时长环)、他人资料页播放器(进度条 + 时长 + 失败重试)。
3. Web:`ProfilePage` 上传/试听/删除 + 他人资料页播放器。

**不做什么**:语音转文字(要 ASR)、语音审核机审(个人项目不接第三方,靠人工听)、配对后才可听(主人已否)。

**验收**:后端 `verify.sh backend` 绿(含新增 docstring / `docs/api/users.md` + openapi 同步);
App `analyze` 零告警 + 组件测试;Web `vue-tsc`+`eslint`+`vitest` 绿;模拟器逐页手测(录音→保存→换号看资料页→播放)。

**风险**:① 安卓录音权限与 `RECORD_AUDIO` 声明;② 签名 URL 过期导致长停留页面播放 403 → 播放失败要能一键刷新重取;
③ 上传的是音频文件,`config/images.py` 不适用,必须走 `voice.normalize`,别手写转码。

### 4.2 S 批:发现页筛选 + 每日精选

**做什么**

1. 后端:
   - `GET /api/v1/discovery/candidates` 新增**可选**查询参数 `age_min` / `age_max` / `city` / `tag_ids`,缺省沿用 `Preference`(即现有行为不变);
   - 缓存键加入**筛选指纹**(排序后的参数哈希),`candidate_pool_ids` 按指纹分桶;`CANDIDATE_CACHE_TTL<=0` 仍能整体熔断;
   - `GET /api/v1/discovery/daily` 每日精选:种子 = `(日期, 用户 id)`,从候选池按**共同标签数 → 同城 → 随机**取 N 张(默认 6),当天结果稳定、跨天自动换;返回结构与 candidates 同构 + `date` 字段;
   - 两者共用同一套排除规则(不重复实现)。
2. App/Web:发现页顶部「筛选」入口(抽屉/面板:年龄区间 + 城市 + 标签多选,「重置」),筛选后重新拉候选池;
   发现页顶部「今日精选」卡(展示 N 张,可直接划或点进资料)。

**不做什么**:把筛选结果**写回** `Preference`(筛选是临时的,preference 仍只在设置里改)、按距离筛选(无位置数据)、精选做成推送(不做推送)。

**验收**:后端绿 + `docs/api/discovery.md` 与 openapi 同步 + `test_query_budget` 不新增超标查询;
筛选参数非法值 400;同一天两次请求 `daily` 结果一致、跨天变化(测试用固定种子断言);
双端筛选态在页面切换后不丢。

**风险**:① 缓存分桶会让命中率下降 —— 必须给「无筛选」保留**原键**(保证默认路径命中率不退化);
② 精选排序含共同标签数,注意别退化成 N+1 或大表 join,查询预算门禁会抓。

### 4.3 T 批:聊天体验打磨

**做什么**

1. imserver(唯一动库的一批,**零 WS 帧改动**):
   - 迁移 `008`:新表 `im_message_hidden(user_id, msg_id, created_at, unique)` —— 多选删除是「**仅删我这一侧**」,不触碰消息本体、不通知对端(与微信一致);
   - 新 HTTP 接口 `POST /im/api/messages/delete`(body `{ids:[...]}`,鉴权同 `/im/api/*`,只允许删自己可见的、上限 50 条/次、幂等);
   - `GET /im/api/messages` 与 `conversations` 的未读数/`last_message` 要排除已隐藏行(否则删了还占未读)。
2. App/Web:
   - 长按消息 → 「多选」→ 勾选 → 底部批量操作条(删除 / 复制文本);
   - 发送失败:气泡显示「未发送」+ 点按**手动重发**(不做自动重发,见「不做什么」);
   - 草稿:退出会话保留输入框内容(App `shared_preferences` / Web `localStorage`),会话列表显示「[草稿]」前缀;
   - 图片消息点击全屏(双指缩放 + 左右切图);
   - 语音消息进度条可拖动 + 1.0x/1.5x/2.0x 倍速。

**不做什么**:自动重发 / 断线队列(要 `client_msg_id` 幂等键,那会改 `send` 帧 → 三端 fixture 联动,收益不抵成本,留作单独一单)、
双向删除(对端也消失)、消息编辑。

**验收**:imserver unit + db + 集成绿(`test_messages_hidden.py`:删后历史不含、未读数减少、对端仍可见、超限 400、重复删幂等);
App/Web 绿;模拟器手测(多选删 3 条 → 重进会话确认消失 → 换号确认对端还在)。

**风险**:① 隐藏表的 `NOT EXISTS` 要进既有查询,别把历史分页搞成全表扫(查询预算);
② 未读数与 `last_message` 三处口径必须同改,漏一处就是「删了还在列表顶部」。

### 4.4 U 批:广场点赞列表 + 收藏

**做什么**

1. 后端:
   - `GET /api/v1/posts/{id}/likes`(游标分页,返回昵称/头像/user_id,可见性同广场:排除拉黑与重封禁);
   - `feed.PostFavorite`(unique(post, user))+ `POST`/`DELETE /api/v1/posts/{id}/favorite`(幂等 204)+ `GET /api/v1/feed/favorites`(我的收藏,游标分页,帖子被删则自动消失);
   - 帖子序列化器新增 `is_favorited`(单条多一次聚合,批量走一条分组查询,不随条数增长);
   - 收藏**不产生通知**。
2. App/Web:动态卡片长按/更多菜单加「收藏」;点赞数点开 → 点赞列表页;广场顶部或「我的」加「我的收藏」入口。

**不做什么**:收藏夹分组、收藏转私密分享、点赞列表按时间倒序之外的排序。

**验收**:后端绿 + `docs/api/` 与 openapi 同步;点赞列表对拉黑用户不可见;重复收藏幂等;删除帖子后收藏列表不再出现;
双端入口可达、状态乐观更新且失败回滚。

**风险**:`is_favorited` 若写成逐条查询,广场一页 20 条就是 20 次 SQL —— 查询预算门禁会红,必须批量。

### 4.5 V 批:运营数据看板

**做什么**

1. `manage.py metrics_daily`(默认算昨天,`--date` 可指定,`--backfill N` 回填):把当日数字写进 `stats.DailyMetric`(或 `ops` app 内)快照表 ——
   DAU(120 秒内认证请求口径)、新注册、完善资料数、滑卡数、配对率、消息量(读 `chatapp_im`)、活跃时段分布;
2. cron 每日 03:40(在备份之后)跑,日志进 `/www/wwwlogs/`;**不引入 Celery beat**(项目惯例是 cron + 命令);
3. `/ops/metrics/` 看板页(沿用 `/ops/` 模板体系 + `StaffSecurityMiddleware`):近 30 天趋势表 + 7 日留存;
4. 只读接口不进 `/api/v1`(运营页服务端渲染,不受 `ApiDocsCoverageTests` 约束)。

**不做什么**:接 Grafana 新面板(现有 Prometheus 已有实时指标,看板解决的是**历史趋势**)、漏斗归因、用户分群。

**验收**:`verify.sh backend` 绿;对已有数据跑一次 `--backfill 30` 能出 30 行;`/ops/metrics/` 在本地 superuser 下可访问、
非 staff 403;口径写进 `docs/ops/capacity-and-reliability.md` 或 `docs/ops/runbook.md`。

**风险**:① 跨库读 `chatapp_im`(消息量)要走 IM 库凭据,别用应用账号;② 留存要按「首日注册 cohort」算,别用活跃日反推。

### 4.6 W 批:发版自动化(内联,不派工单)

> 依据 AGENTS.md「流程自身的引导必须本会话内联做完」;L1 的 closeout 与 L3 的模拟器轨**已完成**,本批只补缺口。

**做什么**

1. `scripts/release-prep.sh`(或 `scripts/release.py`):一条命令做完**主人发版前能自动化的全部** ——
   ① 校验工作区干净且 `HEAD == origin/master`;② 按参数写三处版本号(`app/pubspec.yaml` → `sync_version.py --write`);
   ③ 跑 `sync_version.py --check`;④ 生成 release notes 草稿(从 `git log` 取本批 PR + 固定小节:新增/变更/修复/运维注意);
   ⑤ 打印**待主人执行**的命令(tag / `create_release.py` / 部署清单),但**不执行**。
2. L3 golden 截图:把 `app/integration_test/smoke_test.dart` 从「冷启动到登录页」扩到「登录页 + 一个主页面」的 golden 比对,
   容差与更新方式写进 workflow 注释;本地 `--update-goldens` 一条命令刷新。
3. 两个脚本都配自测(`scripts/test_release_prep.sh`),照 `test_superagent_closeout.sh` 的写法。

**不做什么**:自动打 tag、自动建 Release、自动部署(AGENTS.md 明令禁止);发版本身仍由主人执行。

**验收**:脚本在「脏工作区 / 落后 origin / 版本号已改过」三种情形下都给出确定结论并非零退出;
在真实 master 上 `--dry-run` 输出正确的三处版本号改动与 notes 草稿;golden 轨在 CI 绿。

---

## 5. 全局约束(每批都适用)

- **一单一条栈**;契约联动(openapi / `docs/api/` / WS fixture / tokens)属同栈附带改动,必须同一次做完。
- 每批先写 spec 细化 + 拆单,**需求分析在本会话做完再开单**;「合并后才发生的事」写进「留给人验」。
- 实现走工单(WSL `dsh-superagent` worker);**W 批与流程引导内联做**。
- 验证唯一入口 `scripts/verify.sh <stack>`;推之前必须绿,输出贴进 PR 正文。
- App UI 改动必须在 `emulator-5554` 上逐页手测并截图留证。
- 每批合并后**立刻** `scripts/superagent-closeout.sh`(先 pull 母体再 prune),Windows 仓库同步 `pull --ff-only`。

## 6. 汇报节奏

每批合并后向主人汇报一次:做了什么 / 怎么验的 / 留了什么给人验 / 遗留。
六批全部完成后,汇总一份发版清单交给主人(版本号、notes、tag、Release、部署步骤),由主人统一发版。
