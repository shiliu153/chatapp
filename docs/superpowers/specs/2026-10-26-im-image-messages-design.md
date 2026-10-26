# 自建 IM 图片消息(图片二期)设计

日期:2026-10-26 · 前置:`docs/superpowers/specs/2026-10-20-self-hosted-im-design.md`
状态:设计已确认,待写实施计划

## 1. 背景与目标

自建 IM(`imserver/`)当前只支持文本与 custom(灰条)消息,图片入口在 App/Web 两端
按 `capabilities.image=false` **隐藏**。而 `2026-10-20-self-hosted-im-design.md` §13.3
把「图片消息可用」列为全量切换(`IM_SELF_GRAYLIST=all`)的**硬门槛**——不带图片切全量
等于功能回退。

本设计交付:**单聊图片消息**,覆盖发送、接收、历史、会话列表、撤回、失败重发、
运营抽审与删除。完成后勾掉核对单里的「图片二期已交付」。

## 2. 已定关键决策(用户确认)

| # | 决策 | 取舍理由 |
|---|---|---|
| D1 | **上传走 Django**(`POST /api/v1/im/images`),imserver 只扩协议 | 复用现成 JWT 鉴权、DRF 限流、ImageField/Pillow 校验、媒体目录、注销清理;imserver 保持「只管消息」,不引 libjpeg/multipart 解析 |
| D2 | **上传即发 + 人工抽审**(不接机器审核) | 测试期灰度只有隔离号;云审核要账号与密钥,列为**上线阻断项**另立项 |
| D3 | **原图 + 服务端 240px 缩略图**(不做多尺寸转码) | Pillow 已是现有依赖;弱网先显缩略图,点开看原图;三档转码属过度设计 |
| D4 | 客户端压缩后上传(`image_picker` 原生参数 / 浏览器 canvas) | App 不加依赖;服务端只校验不转码(EXIF 竖拍例外,见 §4.3) |
| D5 | 顺带修复灰条历史丢 `custom.type`(§7) | 本轮本来就要改 `send()` 的 kind/body 传递,顺路修比单独立项更省 |

## 3. 非目标(YAGNI)

- 一条消息多张图(一次一张);
- 视频 / 语音 / 文件消息;
- 服务端多尺寸转码、CDN、对象存储;
- 图片消息的「保存到相册」、已读回执;
- 图片机器审核(见 D2);
- 聊天图片的容量归档与清理(记待办,见 §12)。

## 4. Django 侧

### 4.1 数据模型(`chatapp/im/models.py` 新增)

```python
class ChatImageStatus(models.TextChoices):
    VISIBLE = "visible", "正常"
    DELETED = "deleted", "已删除"

class ChatImage(models.Model):
    owner = FK(User, CASCADE, related_name="chat_images")
    file = ImageField(upload_to=chat_image_path)          # chat/%Y/%m/<owner>-<uuid16>.<ext>
    thumb = ImageField(upload_to=chat_thumb_path)         # chat/%Y/%m/<owner>-<uuid16>_thumb.jpg
    width, height = PositiveIntegerField()                # 显示尺寸(已按 EXIF 方向校正)
    bytes = PositiveIntegerField()
    status = CharField(max_length=10, choices=..., default=VISIBLE)
    deleted_by = FK(User, null=True, SET_NULL, related_name="+")
    deleted_at = DateTimeField(null=True)
    created_at = DateTimeField(auto_now_add=True)
```

**为什么要建表、不是只落盘**:运营抽审要按「用户 / 时间」查;删除要留审计;
注销账号要能收集文件名(`users/services.py::delete_account` 现有做法);
限流与容量统计也要有行可数。

**命名不可枚举**:文件名含 `uuid4().hex`,不用自增主键——防止顺着
`/media/chat/1.jpg` 遍历别人的私聊图。

### 4.2 上传接口

`POST /api/v1/im/images`,multipart 字段 `file`,需 Bearer JWT。

```json
// 201
{"id": 123,
 "url": "https://<host>/media/chat/2026/10/7-a1b2c3.jpg",
 "thumb_url": "https://<host>/media/chat/2026/10/7-a1b2c3_thumb.jpg",
 "width": 1080, "height": 1440, "size": 345678}
```

- `banned_heavy` 由全局权限类 `IsNotHeavyBanned` 拦 403(白名单只有
  `GET /users/me`、`GET /users/tags`),本接口不额外写检查;
- 限流:`ChatImageThrottle`,`30/hour`(与「反馈 5/小时」同款写法);
- 校验(任一不过 → 400 + 统一错误体):
  | 项 | 规则 | 失败文案 |
  |---|---|---|
  | 真实图片 | `serializers.ImageField`(Pillow 校验) | 请上传图片文件 |
  | 大小 | ≤ 5MB(`CHAT_IMAGE_MAX_BYTES`) | 图片不能超过 5MB |
  | 长边 | ≤ 4096(`CHAT_IMAGE_MAX_SIDE`) | 图片尺寸过大,请先压缩 |
  | 格式 | jpg / png / webp | 只支持 JPG/PNG/WebP |
- **同步执行,不进 Celery**:这条路径只落盘、无任何第三方调用,符合
  「响应路径禁止外部调用」纪律;Pillow 处理 5MB 图约几十毫秒;
- 返回绝对 URL(`request.build_absolute_uri`),客户端直接塞进 WS 帧。

### 4.3 缩略图与方向

- `ImageOps.exif_transpose` 得到显示方向 → 取 `width/height`(存的就是显示尺寸);
- 缩略图:长边 240(`CHAT_IMAGE_THUMB_SIDE`)、JPEG q80、`LANCZOS`,存 `_thumb.jpg`;
- 原图:**EXIF 方向为 1(正常)时按原字节存**;方向不为 1 时重编码成 JPEG q85,
  避免「服务端存的宽高与客户端实际渲染方向不一致」;
- 不做等比二次压缩(客户端已压到长边 1920)。

### 4.4 注销与删除

- `users/services.py::delete_account`:收集 `ChatImage` 的 `file`/`thumb` 路径,
  随现有 `_cleanup()` 一起删磁盘文件(与照片、动态图同一段逻辑);
- 运营删除(§6):删两个文件 + `status=deleted` + 审计字段,**不动 imserver 库里的消息**
  (跨库改消息代价远大于收益;客户端图片加载失败已有占位兜底)。

## 5. 协议扩展(imserver)

### 5.1 帧

`send` 帧新增 `kind:"image"`:

```json
{"v":1,"type":"send","id":"c-7f3a","data":{
  "client_msg_id":"c-7f3a","to":"u9","kind":"image",
  "image":{"url":"https://<host>/media/chat/2026/10/7-a1b2.jpg",
           "thumb_url":"https://<host>/media/chat/2026/10/7-a1b2_thumb.jpg",
           "width":1080,"height":1440,"size":345678}}}
```

`message` 推送与历史 / 会话列表里的载荷同形:

```json
{"msg_id":"123457","seq":43,"from":"u9","to":"u2","kind":"image",
 "image":{"url":"...","thumb_url":"...","width":1080,"height":1440,"size":345678},
 "ts":1760000000456,"revoked":false,
 "from_profile":{"nickname":"小九","avatar":"https://.../a.jpg"}}
```

- 落库:`im_message.kind=3`、`body={"image":{...}}`(现有 1=text、2=custom,3 顺延);
- 帧大小无压力:url 约 120 字节,远低于 8KB 上限;
- 撤回后与现状一致:`kind` 回落为 `text`、不带内容(客户端渲染居中灰字)。

### 5.2 服务端校验(任一不过 → `42201`)

| 项 | 规则 |
|---|---|
| `url` / `thumb_url` | 必须以配置 `IM_MEDIA_PREFIX`(如 `https://<host>/media/chat/`)开头 |
| `width` / `height` | 1–4096 |
| `size` | 1–5MB(5×1024×1024) |
| 字段 | 五项齐全,类型正确 |

**前缀校验是防伪造的关键**:客户端能塞任意 URL 的话,等于给对端发任意图片源
(追踪像素、内网地址、第三方盗链)。`IM_MEDIA_PREFIX` 为空时**拒绝所有图片发送**
(fail closed),启动时缺该配置直接报错退出。

**未知 kind 仍返回 `42201`**(与现网一致,少一处行为变更);
`42202` 语义保留给未来的视频/语音等类型,本轮不产出。

### 5.3 代码改动面

| 文件 | 改动 |
|---|---|
| `src/store/models.h` | `MessageRow.kind` 已是 `int`,无需改 |
| `src/service/message_service.{h,cpp}` | `SendRequest` 加 `kind` + `image`;`send()` 按 kind 分支校验;`body` 由调用方给(不再硬编码 `{"text":...}`) |
| `src/net/ws_server.cpp` | `handle_send` 接受 image 并透传;`on_send_result` 用新帧构造 |
| `src/net/http_api.cpp` | `message_json` 加 image 分支(历史 + 会话列表);`/internal/send` 按 kind 落库 |
| `src/net/frames.h` | `build_message_frame` 改为接收通用 payload |
| `src/config.{h,cpp}`、`deploy/imserver.env.example` | 新增 `IM_MEDIA_PREFIX`(必填) |

## 6. 客户端

两端 IM 抽象层已预留图片字段(`ChatMessage.imageUrl` 缩略图 /
`imageLargeUrl` 原图、`sendImage()` 接口),本轮只填实现。

### 6.1 App(`app/lib/im/`)

| 改动 | 说明 |
|---|---|
| `SelfImClient.capabilities.image => true` | 入口不再隐藏 |
| 新增 `SelfImageUploader` 抽象 + `ApiImageUploader` 实现 | 上传走 Django(要 JWT),而 `SelfImClient` 只跟 imserver 说话——注入上传器,测试注入假实现;不把 Django 的 `ApiClient` 塞进 IM 客户端 |
| `sendImage()` | 上传 → 发 WS `send` 帧 → 等 ack → 返回 `ChatMessage(kind:image, imageUrl:缩略图, imageLargeUrl:原图, localPath:本地路径)` |
| `_PendingSend` 扩展 | 现在只存 `text`;ack 回来要还原成图片消息,需存 `kind` + 载荷 |
| `_messageFromJson` | 加 `'image'` 分支 |
| 选图 | `image_picker` 加 `maxWidth:1920, maxHeight:1920, imageQuality:80`(原生支持,不加依赖) |
| 会话列表 | `lastMessage.kind == image` → 显示 `[图片]` |
| 聊天页气泡 | 复用现有 image 分支(腾讯路径已在用):先显缩略图,点开看原图,加载失败走 `errorBuilder` |

### 6.2 Web(`web/src/im/self/`)

- `capabilities.image = true`;
- `sendImage(peerId, file)`:canvas 压到长边 1920 / JPEG 0.8 → `FormData` POST
  `/api/v1/im/images`(走 `api/http.ts` 的 axios,自动带 token 与刷新)→ WS send → `ChatMessage`;
- 解析 image 分支、会话行 `[图片]`、复用 `MessageImage.vue`(缩略图/原图字段已对齐)。

### 6.3 兼容性

- 旧版自建客户端(`capabilities.image=false`)看不到入口,但**可能收到** image 消息;
  其解析器把未知 kind 落到 text(空文本),表现为空气泡。灰度只有隔离测试号,可接受;
  发版后自然消失;
- 腾讯后端路径(`tencent_im_client.dart` / `im/client.ts`)完全不动。

## 7. 服务端杂项修复(灰条历史)

### 7.1 现状

`/internal/send` 发灰条时,推送帧是 `kind=custom` + `custom`,但**落库硬编码
`kind=1` + `{"text": desc}`**。结果:灰条实时收到正常,翻历史退化成文本气泡
(`custom.type` 丢失)。

### 7.2 修复

- `SendRequest` 增加 `kind`(1=text / 2=custom / 3=image),`body` 由调用方序列化;
- `/internal/send` 传 `kind=2` + `body={"type":..., "desc":..., "data":...}`;
- `message_json` 按 `kind` 分支:`1` → text、`2` → custom、`3` → image;
- 行为变化:历史里的灰条从「文本气泡」变为「灰条」。两端解析器已支持
  `custom.type`,不需要改客户端。

## 8. 运营抽审(`chatapp/ops/`)

照抄 `/ops/photos/` 的 HTMX 形态,新增一节「聊天图片」:

| 路由 | 行为 |
|---|---|
| `GET /ops/chat-images/` | 按时间倒序最多 120 条,缩略图网格 + 发送者 + 时间 + 大小;支持 `?user=<id>` 筛选 |
| `POST /ops/chat-images/<id>/delete` | 删原图 + 缩略图、`status=deleted`、记 `deleted_by/deleted_at`,回吐表格片段 |
| `GET /ops/reports/<id>/`(增强) | 举报详情页加「该用户最近 7 天聊天图片」区块,运营按举报直接看证据 |
| `ops/base.html` | 导航加一项 |

权限复用现有 `staff_required` 装饰器;删除审计直接记在 `ChatImage` 上
(`deleted_by` / `deleted_at`),与 `BanLog` 的「只增不改」审计思路一致。

## 9. 安全与合规

| 项 | 现状 | 结论 |
|---|---|---|
| URL 可访问性 | `/media/` 由 Nginx 直出、无鉴权;文件名随机不可枚举 | 测试期接受,签名 URL 记待办 |
| 内容审核 | 上传即发,靠举报 + 人工抽审 + 拉黑/封禁兜底 | **上线阻断项**:接云内容安全后改异步审核 |
| 伪造外链 | 服务端校验 URL 前缀 | 已覆盖 |
| 盗刷 | 30 次/小时限流 + 5MB 上限 | 已覆盖 |
| 越权删除 | 上传接口只写自己的行;删除只走 ops | 已覆盖 |

## 10. 测试矩阵

| 层 | 用例 |
|---|---|
| Django | 上传成功返回四元组 / 超 5MB / 非图片 / 长边超 4096 / 限流第 31 次 429 / 重封禁 403 / 缩略图真的生成 / EXIF 竖拍方向被校正且宽高互换 / 注销删掉原图+缩略图 / ops 删除置 `deleted` 且两文件消失 / 举报详情含该用户图片 |
| imserver gtest | 合法 image 帧落库 `kind=3` / url 前缀不符 42201 / 宽高越界 42201 / size 越界 42201 / 历史与会话列表返回 image / 未知 kind 仍 42201 / 灰条落库 `kind=2` 且历史还原 `custom.type` |
| App | `sendImage` 成功(上传→WS→ack)/ 上传失败抛 `ImException` / 解析 image / 会话 `[图片]` / `capabilities.image == true` |
| Web | 同上 + canvas 压缩单测(注入假 canvas) |
| 文档 | `docs/api/im.md` 补接口与帧;`ApiDocsCoverageTests` 双向比对必须绿 |

## 11. 部署与灰度

1. Django 迁移 1 个(新表 `im_chatimage`);
2. imserver 镜像重建;**先**把 `IM_MEDIA_PREFIX` 写进容器 env(必填,缺了启动失败)
   **再**重启,否则新版本起不来;
3. Nginx 确认 `/media/chat/` 可访问(`/media/` 已直出,通常不用改);
4. 灰度 7/8 双端互发图 → 历史 → 撤回 → 断网重发 → ops 删除后看占位;
5. 全过 → 勾掉核对单「图片二期已交付」,再进切换日观察。

## 12. 风险与待办(不阻塞本期)

| 项 | 现状 | 后续 |
|---|---|---|
| 图片 URL 公开 | 随机 UUID 文件名,不可枚举但可被转发 | 签名 URL(Nginx `secure_link`) |
| 无机器审核 | 人工抽审兜底 | 云内容安全,**上线阻断项** |
| 磁盘增长 | 不清理,随消息增长 | 按 `created_at` 归档 + 重算 `last_msg` |
| 撤回后文件仍在 | 只改标记,与腾讯行为一致 | 无需处理(ops 可删) |
| 2C2G 上传占 worker | 5MB 上传期间占一个 gunicorn worker | 测试期量小;量上来再拆独立上传进程 |

## 13. 交付物清单

- `chatapp/im/models.py`(`ChatImage`;`im` 应用此前没有本地表,故是 `0001_initial`)、
  `migrations/0001_initial.py`、`views.py::upload_image`、`serializers.py`、
  `throttles.py`、`urls.py`;
- `chatapp/users/services.py`(注销收集聊天图片文件);
- `chatapp/ops/`(聊天图片列表 / 删除 / 举报详情区块 / 导航);
- `imserver/src/{service,net,config}`(kind=3 + 前缀校验 + 灰条落库修复)、
  `deploy/imserver.env.example`;
- `app/lib/im/`(上传器、`sendImage`、解析、capabilities、会话 `[图片]`)+ 测试;
- `web/src/im/self/`(canvas 压缩、上传、解析、capabilities、会话 `[图片]`)+ 测试;
- `docs/api/im.md`、`docs/pitfalls/im.md`、`docs/ops/imserver.md`、
  `docs/superpowers/plans/2026-10-20-self-hosted-im-rollout.md`(勾掉图片二期)。
