# 自建 IM 语音消息设计

日期:2026-10-27 · 前置:`docs/superpowers/specs/2026-10-20-self-hosted-im-design.md`、
`2026-10-26-im-image-messages-design.md`、`2026-10-26-chat-image-signing-retention-design.md`
状态:已交付(2026-10-27;实施计划 `docs/superpowers/plans/2026-10-27-im-voice-messages.md`)

## 1. 背景与目标

自建 IM(`imserver/`)现已支持文本、custom(灰条)、图片(`kind=3`)三类消息,
图片链路沉淀了「Django 上传 + 签名 URL + imserver 只扩协议 + 30 天清理 + ops 抽审」
这一整套模式。语音是交友场景里仅次于图片的表达方式,也是全量切换前最后一个
消息类型缺口。

本设计交付:**单聊语音消息**,覆盖录制、上传、发送、接收、历史、会话列表、撤回、
失败重发、运营抽审与清理。完成后自建 IM 具备「文本 + 图片 + 语音」完整表达能力。

## 2. 已定关键决策(用户确认)

| # | 决策 | 取舍理由 |
|---|---|---|
| D1 | **上传走 Django**(`POST /api/v1/im/voices`),imserver 只扩协议 | 与图片完全同构:复用 JWT 鉴权、DRF 限流、媒体目录、签名 URL、注销与清理框架;imserver 不引 multipart 解析与 ffmpeg |
| D2 | **服务端统一转 m4a/AAC**(ffmpeg) | App 录 m4a,Web 的 `MediaRecorder` 输出因浏览器而异(Chrome/Firefox 出 webm/ogg,Safari 可出 mp4);不转码则 iOS 播不了 Web 发来的语音。统一后存储格式唯一、播放器只需支持 AAC |
| D3 | **按住说话**(松手发送 / 上滑取消) | 用户确认;与微信一致,双端交互对齐 |
| D4 | **只做自建后端**,腾讯后端 `capabilities.voice=false` | 用户确认;与搜索一致,腾讯路径已进入退役期,不值得双写 |
| D5 | **ops 抽审本期做**(可播放,不做转写) | 用户确认;语音与图片同属人工抽审兜底,举报详情要能直接听证据 |
| D6 | 时长 **1–60 秒**,单条 ≤ 2MB,上传限流 **60 次/小时** | 60 秒足够表达且控制转码/存储成本;限流与图片同款写法 |

## 3. 非目标(YAGNI)

- 语音转文字(ASR)、变声、降噪、波形可视化;
- 语音消息的「自动播放 / 连续播放」;
- 多条语音合并转发、语音评论;
- 机器内容审核(与图片同列为**上线阻断项**,见 §8);
- 腾讯后端的语音收发;
- 语音消息的「已读回执」(全项目挂起项,不在本批次)。

## 4. Django 侧

### 4.1 数据模型(`chatapp/im/models.py` 新增)

```python
class ChatVoiceStatus(models.TextChoices):
    VISIBLE = "visible", "正常"
    DELETED = "deleted", "已删除"
    EXPIRED = "expired", "已过期清理"

class ChatVoice(models.Model):
    owner = FK(User, CASCADE, related_name="chat_voices")
    file = FileField(upload_to="chat/voices/%Y/%m/")   # 统一 .m4a
    duration_ms = PositiveIntegerField()               # ffprobe 实测,取整毫秒
    bytes = PositiveIntegerField()                     # 转码后字节数
    mime = CharField(max_length=32, default="audio/mp4")
    status = CharField(max_length=10, choices=ChatVoiceStatus.choices,
                       default=ChatVoiceStatus.VISIBLE)
    deleted_by = FK(User, null=True, SET_NULL, related_name="+")
    deleted_at = DateTimeField(null=True)
    expired_at = DateTimeField("过期清理时间", null=True)
    created_at = DateTimeField(auto_now_add=True)
```

- 与 `ChatImage` 字段对齐(状态、审计、过期),不共用模型:图片有 `thumb/width/height`,
  语音有 `duration_ms/mime`,混表会让两边字段各有一半永远为空;
- 文件名 `<owner_id>-<uuid4().hex>.m4a`,不可枚举;`upload_to` 已含
  `chat/voices/%Y/%m/`,保存时**只传文件名**(再拼目录会落成
  `chat/voices/2026/10/chat/voices/2026/10/...`,2026-10-26 图片已踩过);
- `signed_file_url` 属性复用 `im/media_sign.sign_url`,与图片同一把密钥、同一 TTL。

### 4.2 上传接口

`POST /api/v1/im/voices`,multipart 字段 `file` + `duration_ms`,需 Bearer JWT。

```json
// 201
{"id": 45,
 "url": "https://<host>/media/chat/voices/2026/10/7-a1b2c3.m4a?e=...&s=...",
 "duration_ms": 12500,
 "size": 48000}
```

- `banned_heavy` 由全局权限类 `IsNotHeavyBanned` 拦 403(白名单不含本接口);
- 限流:`ChatVoiceThrottle`,`60/hour`(`CHAT_VOICE_RATE`);
- 校验与处理流水线(任一不过 → 400 + 统一错误体):

  | 步骤 | 规则 | 失败文案 |
  |---|---|---|
  | 大小 | 原始文件 ≤ 5MB(`CHAT_VOICE_MAX_BYTES`) | 语音不能超过 5MB |
  | 类型 | `audio/mp4` / `audio/m4a` / `audio/x-m4a` / `audio/aac` / `audio/webm` / `audio/ogg` | 只支持 M4A/AAC/WebM/OGG 音频 |
  | 真实时长 | `ffprobe` 读出 1–60 秒(`CHAT_VOICE_MAX_MS` = 60000) | 语音时长需在 1–60 秒之间 |
  | 转码 | `ffmpeg` 统一转 AAC,单声道 16kHz 32kbps | 音频无法解码,请重新录制 |
  | 产物大小 | 转码后 ≤ 2MB(`CHAT_VOICE_MAX_OUT_BYTES`) | 语音文件过大 |
  | 客户端时长 | `duration_ms` 与实测差值 ≤ 2 秒 | 语音时长不合法 |

- **转码命令**(参数数组,不经 shell):

  ```
  ffmpeg -y -hide_banner -loglevel error -i <in> -vn -ac 1 -ar 16000 \
         -c:a aac -b:a 32k -f mp4 <out>.m4a
  ```

  60 秒音频约 240KB,在 2C2G 上耗时约 0.2–0.5 秒;`subprocess.run(timeout=15)`,
  超时或非零退出按「音频无法解码」处理,临时目录用 `tempfile.TemporaryDirectory()`;
- **ffmpeg 是硬依赖**:请求内 `shutil.which("ffmpeg")` / `ffprobe` 任一缺失 →
  `503 + {"code": 50302, "message": "语音消息暂不可用"}`(新增
  `config/error_codes.py::CHAT_VOICE_UNAVAILABLE = 50302`,`50301` 已被短信占用),
  同时记 `logger.error`,部署核对单必须验证(见 §10);
- 同步执行、不进 Celery:纯本地进程与落盘,无第三方网络调用,符合响应路径纪律;
- 响应 URL 带签名(`media_sign.sign_url`),客户端直接塞进 WS 帧;
- 对外接口总数 42 → 43,`docs/api/im.md` 与 `docs/api/README.md` 总览同步补条目(`ApiDocsCoverageTests` 双向门禁)。

### 4.3 签名与访问

- 文件落在 `/media/chat/voices/`,与聊天图片同在 `/media/chat/` 前缀下:
  nginx 的 `auth_request` location、`/im/images/auth` 验签子请求、imserver 的
  `IM_MEDIA_PREFIX` 前缀校验**全部原样复用**,不需要新增配置;
- 验签接口名仍是 `/im/images/auth`(历史命名),文档里注明它对 `/media/chat/`
  下所有文件生效,避免以后误以为只服务图片。

### 4.4 注销与清理

- `chatapp/users/services.py::delete_account` 收集文件时补 `ChatVoice.file`
  (与 `ChatImage.file/thumb` 同一段逻辑);
- `im_media_cleanup` 扩展:
  - 过期:`created_at < now - CHAT_VOICE_RETENTION_DAYS`(默认 30)→ 删文件 +
    `status=expired` + `expired_at`;
  - 孤儿扫描:`known` 集合**必须**并入 `ChatVoice.file`,否则 `media/chat/voices/`
    下的正常文件会被当成孤儿删掉(与图片同一处坑,见 §11);
  - ops 删除的行:删文件 + `status=deleted`(审计字段)。

## 5. 协议扩展(imserver)

### 5.1 帧

`send` 帧新增 `kind:"voice"`:

```json
{"v":1,"type":"send","id":"c-7f3a","data":{
  "client_msg_id":"c-7f3a","to":"u9","kind":"voice",
  "voice":{"url":"https://<host>/media/chat/voices/2026/10/7-a1b2.m4a",
           "duration_ms":12500,"size":48000}}}
```

`message` 推送、历史(`/im/api/messages`)、会话列表 `last_message` 载荷同形:

```json
{"msg_id":"123457","seq":43,"from":"u9","to":"u2","kind":"voice",
 "voice":{"url":"https://<host>/media/chat/voices/2026/10/7-a1b2.m4a?e=...&s=...",
          "duration_ms":12500,"size":48000},
 "ts":1760000000456,"revoked":false,
 "from_profile":{"nickname":"小九","avatar":"https://.../a.jpg"}}
```

- 落库:`im_message.kind=4`、`body={"voice":{...}}`,URL 存**规范 URL**(去 query),
  读时由 `MediaSigner` 现签(与图片一致,避免存下来的签名过期变死链);
- 撤回后行为不变:`kind` 回落 `text`、不带内容;
- 搜索不受影响(只扫 `kind=1`);
- 帧大小无压力:url + 三个数字约 150 字节。

### 5.2 服务端校验(任一不过 → `42201`)

| 项 | 规则 |
|---|---|
| `url` | 必须以 `IM_MEDIA_PREFIX` 开头(复用 `MediaSigner::canonical`),长度 ≤ 512 |
| `duration_ms` | 1000–60000 |
| `size` | 1–2MB(2×1024×1024) |
| 字段 | 三项齐全、类型正确 |

前缀校验是防伪造的关键(追踪链接、内网地址、第三方盗链);`IM_MEDIA_PREFIX`
为空时拒绝所有语音发送(fail closed),与图片一致。

### 5.3 代码改动面

| 文件 | 改动 |
|---|---|
| `src/util/media_sign.{h,cpp}` | 把「给对象的某个 URL 字段签名」抽成 `sign_media(json&, key)`,`sign_image` 改为薄封装(两处调用) |
| `src/service/message_service.{h,cpp}` | `SendRequest` 加 `voice` 载荷;`send()` 加 `kind==4` 分支与校验 |
| `src/net/ws_server.cpp` | `handle_send` 接受 `kind:"voice"` → `kind=4` |
| `src/net/frames.h` | `kind_name(4)="voice"`;`build_message_frame` 加 voice 分支并签名 |
| `src/net/http_api.cpp` | `message_json` 加 `kind==4` 分支(历史 + 会话列表) |

无需新增环境变量,无需数据库迁移(imserver 侧 `kind` 是 int)。

## 6. 客户端

### 6.1 App(`app/lib/`)

| 改动 | 说明 |
|---|---|
| 依赖 | `record`(录音,`AudioEncoder.aacLc` → m4a)+ `audioplayers`(播放本地/远程音频);版本在实施时按 Flutter 3.47 / Dart SDK 约束锁定 |
| 权限 | `AndroidManifest.xml` 加 `RECORD_AUDIO`;`Info.plist` 加 `NSMicrophoneUsageDescription`(文案:用于发送语音消息) |
| `ImClient` | 加 `sendVoice({peerId, localPath, durationMs})`;`ImCapabilities.voice`;腾讯实现抛 `42202` 且 capability=false |
| `SelfVoiceUploader` | 照抄 `self_image_uploader.dart`:multipart 上传拿 `{url, duration_ms, size}`;测试注入假实现 |
| `ChatMessage` | 加 `voiceUrl` / `voiceDurationMs`,`kind` 加 `voice`;`copyWith` 同步补字段 |
| 录音 | `VoiceRecorderController`(Riverpod):长按开始 → 计时 → 松手停止 → 上传 → 发帧;`<1s` 提示「说话时间太短」;60s 自动停止并发送;上滑超过 60px 进入取消态;录到临时目录,发送成功或取消后删除本地文件 |
| 输入栏 | 麦克风/键盘切换按钮;录音浮层显示计时与「松开发送 / 上滑取消」 |
| 气泡 | `VoiceBubble`:宽度 `60 + duration_s × 2`(上限 180)、播放/暂停图标 + `12″`;`isPending` 显示转圈、`isFailed` 可点重发;播放本地文件优先(发送中也能听) |
| 播放器 | 单例 `AudioPlayer`,点另一条先停上一条;页面销毁时释放 |
| 会话列表 | `lastMessage.kind == voice` → `[语音]` |

### 6.2 Web(`web/src/im/`)

- `capabilities.voice = true`;腾讯 `client.ts` 保持 false;
- 新增 `self/voice.ts`:`getUserMedia({audio:true})` + `MediaRecorder`,MIME 优先级
  `audio/webm;codecs=opus` → `audio/ogg;codecs=opus` → `audio/mp4`,上传时带
  `duration_ms`(由 `performance.now()` 差值计算);
- 输入栏:`pointerdown` 开始、`pointerup` 发送、`pointermove` 上移 60px 取消;
  `getUserMedia` 不可用(非 HTTPS 且非 localhost、无麦克风)时按钮隐藏;
- 播放:单例 `Audio` 元素(`web/src/im/voicePlayer.ts`),播放/暂停切换,切换消息先停上一条;
- 新增 `MessageVoice.vue`(宽度随时长、图标 + 秒数、播放态),`map.ts` 解析
  `kind=voice`,`types.ts` 加 `voiceUrl` / `voiceDurationMs`;
- 会话行 `[语音]`。

### 6.3 兼容性

- 旧版自建客户端(capability 无 voice)看不到入口,但**可能收到** voice 消息:
  解析器把未知 kind 落到 text(空文本),表现为空气泡——灰度只有隔离测试号,可接受,
  发版后消失(与图片二期同一结论);
- 腾讯后端路径完全不动;灰度期跨后端本就不通消息,不存在「腾讯用户收到语音」。

## 7. 运营抽审(`chatapp/ops/`)

照抄「聊天图片」一节的 HTMX 形态:

| 路由 | 行为 |
|---|---|
| `GET /ops/chat-voices/` | 按时间倒序最多 120 条,`<audio controls preload="none">` 直接播放 + 发送者 + 时长 + 大小 + 时间;支持 `?user=<id>` 筛选 |
| `POST /ops/chat-voices/<id>/delete` | 删文件、`status=deleted`、记 `deleted_by/deleted_at`,回吐表格片段 |
| `GET /ops/reports/<id>/`(增强) | 举报详情加「该用户最近 7 天语音」区块,与图片区块并列 |
| `ops/base.html` | 导航加「聊天语音」 |

权限复用 `staff_required`;播放用签名 URL(与列表预览同一套),不做转写。

## 8. 安全与合规

| 项 | 现状 | 结论 |
|---|---|---|
| 内容审核 | 上传即发,举报 + 人工抽审 + 拉黑/封禁兜底 | **上线阻断项**:与图片一并接云内容安全 |
| 伪造外链 | imserver 校验 `IM_MEDIA_PREFIX` 前缀 | 已覆盖 |
| 盗刷 | 60 次/小时 + 5MB 输入 / 2MB 产物 + 15s 转码超时 | 已覆盖 |
| 恶意媒体 | ffmpeg 解析不可信输入,存在解析漏洞面 | 限流 + 超时 + 单进程;量上来再拆独立转码进程 |
| URL 公开性 | 签名 URL(24h)+ 30 天清理 | 与图片一致 |
| 越权删除 | 上传只写自己的行,删除只走 ops | 已覆盖 |

## 9. 测试矩阵

| 层 | 用例 |
|---|---|
| Django | m4a 直传成功返回四元组 / webm 经转码为 m4a(无 ffmpeg 时 `skipUnless`)/ 非音频 400 / 超 5MB 400 / 时长 <1s 与 >60s 400 / 客户端时长与实测差 >2s 400 / 限流第 61 次 429 / 重封禁 403 / 签名 URL 能被 `/im/images/auth` 验过 / 注销删文件 / 清理只删 30 天前的行 / 孤儿扫描不把正常语音当孤儿 |
| imserver gtest | 合法 voice 帧落库 `kind=4` / url 前缀不符 42201 / 时长越界 42201 / size 越界 42201 / 历史与会话列表返回 voice 且 URL 带签名 / 未知 kind 仍 42201 / 撤回后回落 text |
| App | `sendVoice` 成功(上传→WS→ack)/ 上传失败抛 `ImException` / 解析 voice / 会话 `[语音]` / 气泡播放暂停 / 手势:<1s 取消、上滑取消、60s 自动停 |
| Web | 同上 + `MediaRecorder` mock(选择 MIME、计时、取消)/ 非安全上下文隐藏入口 |
| 文档 | `docs/api/im.md` 补接口与帧;`ApiDocsCoverageTests` 双向比对绿 |

## 10. 部署与灰度

1. **先装 ffmpeg**:宝塔软件商店或 `apt install ffmpeg`,验证
   `ffmpeg -version && ffprobe -version`;缺失时语音上传 503(文本/图片不受影响);
2. Django 迁移 1 个(`im_chatvoice`),`collectstatic` 不涉及;
3. imserver 镜像重建并重启(无新增 env;`IM_MEDIA_PREFIX` 已在位);
4. nginx 无需改:`/media/chat/` 的 `auth_request` 与 `/im/api/` 反代已覆盖;
5. ops 重启后可见「聊天语音」;
6. 灰度 7/8 手测:App→Web 发语音、Web→App 发语音(验证转码与 iOS 播放)、
   历史回放、撤回、断网重发、上滑取消、60s 上限、ops 试听与删除。

## 11. 风险与待办(不阻塞本期)

| 项 | 现状 | 后续 |
|---|---|---|
| 无机器审核 | 人工抽审兜底 | 云内容安全,**上线阻断项** |
| 转码占 worker | 60s 音频约 0.2–0.5s,并发上传会占 gunicorn worker | 量上来拆独立转码进程/队列 |
| ffmpeg 缺失 | 接口 503,日志有 error,但探针只测 `readyz` | 探针加「语音可用」检查项 |
| 孤儿清理误删 | 必须在 `known` 集合补 `ChatVoice.file` | 实施时写测试兜住 |
| iOS 静音/后台播放 | 未验证 audioplayers 的 audio session 行为 | 真机手测,必要时配置 `AVAudioSession` |
| Web 非 HTTPS 不可录音 | 浏览器限制(除 localhost) | 生产已规划 HTTPS,文档写明 |
| 旧客户端收到语音 | 空气泡 | 灰度隔离号可接受,发版后消失 |

## 12. 交付物清单

- `chatapp/im/`:模型 + 迁移 `0002_chatvoice`、`views.py::upload_voice`、
  `serializers.py`、`throttles.py`、`urls.py`、`media_sign`(复用)、
  `management/commands/im_media_cleanup.py`;
- `chatapp/users/services.py`(注销收集语音文件);
- `chatapp/ops/`:语音列表 / 删除 / 举报详情区块 / 导航;
- `chatapp/config/settings.py`:`CHAT_VOICE_*` 常量与限流 scope;
- `chatapp/config/error_codes.py`:`CHAT_VOICE_UNAVAILABLE = 50302`;
- `imserver/src/{service,net,util}`(kind=4、通用签名、帧与历史);
- `app/lib/im/`(上传器、`sendVoice`、解析、capability)+ `app/lib/features/chat/`
  (录音控制器、输入栏、气泡、播放器)+ 权限声明 + 测试;
- `web/src/im/`(录音、上传、解析、capability、播放器)+ 气泡组件 + 测试;
- `docs/api/im.md`、`docs/pitfalls/im.md`、`docs/ops/imserver.md`、
  `CLAUDE.md`(下一步与接口表)、本 spec 与实施计划。
