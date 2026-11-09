# 批次 R 实施计划:资料语音自我介绍

- **Spec 链接**:[批次 R–W 设计](../../specs/2026-11-09-batch-r-w-design.md) §4.1
- **Goal**:用户能给自己的资料录一段 **≤30 秒**语音自我介绍;任何能看他资料的人都能播放。
- **Architecture**:复用聊天语音的整条链路 —— `im/voice.py::normalize`(ffprobe 校验 → ffmpeg 转 m4a/AAC)、
  存储配额(`bytes` 求和,超限 413+`41301`)、`media_sign.sign_url` 限时签名。新增一张 `ProfileVoice`
  一对一表,不动 `Profile` 既有字段,语音**不进**「资料完善」判定。
- **Global Constraints**:一单一条栈;改对外字段必须同改 `docs/api/users.md` + 重生成 `docs/api/openapi.yml`;
  新增 `.py` 补 docstring(`Args:`);App UI 改动遵循「心跳」token,禁裸 hex/字号/间距;
  不动版本号、不发版、不合并 PR。
- **验收命令**:`scripts/verify.sh backend` / `scripts/verify.sh app` / `scripts/verify.sh web`

---

## 现状(已核实,别再查一遍)

| 已有 | 位置 | 复用方式 |
|---|---|---|
| 语音转码 | `chatapp/im/voice.py::normalize` | 直接调用,别手写 ffmpeg |
| 语音模型范式 | `chatapp/im/models.py::ChatVoice`(`file`/`bytes`/`duration_ms`) | 照抄字段与 `file.save(stem.m4a, ContentFile)` 写法 |
| 限时签名 | `chatapp/im/media_sign.py::sign_url` | 公开资料里的语音 URL 必须签名,不能直接给 `file.url` |
| 存储配额 | `USER_STORAGE_QUOTA_MB`(默认 200),四类媒体按 `bytes` 求和 | 语音计入第五类;检查必须在**落盘前** |
| App 录音/播放 | `record: ^7.1.2` + `audioplayers: ^6.8.1`;聊天页已有录音与播放组件 | 抽/复用,不新引依赖 |
| Web 录音/播放 | `web/src/features/chat/useVoiceRecorder.ts`、`VoiceRecordBar.vue`、`MessageVoice.vue` | 直接复用 |
| 错误码 | `41301`(配额)、`50302`(缺 ffmpeg)、`40003/40004/40005` 已占用 | 本批**不新增**业务码,复用既有 |

---

## Task 1 —— backend(先合,契约源头)

**改什么**

1. `chatapp/users/models.py`:新增 `ProfileVoice`(OneToOne → `Profile`,`related_name="voice"`):
   `file`(FileField `voices/%Y/%m/`)、`bytes`、`duration_ms`、`created_at`、`updated_at`。
2. 迁移 `users.000X_profilevoice`。
3. `chatapp/users/views.py`(或既有 profile 视图所在模块):
   - `POST /api/v1/users/me/voice`(multipart 字段 `file`):`voice.normalize` 转码 → 校验时长 **≤30000ms**
     → 配额检查(落盘前)→ 覆盖式保存(同一用户只有一条,重复上传即替换旧文件)→ 201 `{url, duration_ms}`;
   - `DELETE /api/v1/users/me/voice`:幂等 204,同时删物理文件;
   - 两者都挂既有按用户限流(建议 10/小时,新增 `ProfileVoiceThrottle`)。
4. 序列化:`PublicProfileSerializer` 与 `GET /users/me` 新增 `voice: {url, duration_ms} | null`;
   **url 走 `media_sign.sign_url`**(TTL 默认 3600)。
5. 文档:`docs/api/users.md` 两个接口 + 字段表;重生成 `docs/api/openapi.yml`。

**验收口径**

1. `scripts/verify.sh backend` 全绿(含 `CommentCoverageTests` / `ApiDocsCoverageTests` / OpenAPI 生成物校验)。
2. 上传 31 秒音频 → **400**,`message` 含「30 秒」;上传 3 秒 → 201,响应有 `url` 与 `duration_ms`。
3. 重复上传 → 仍只有一条 `ProfileVoice`,旧文件已删(断言目录里只有一个文件)。
4. `GET /users/me` 与 `GET /users/{id}`(他人资料)都返回 `voice`,且 `url` 带签名参数(含 `exp`/`sig`)。
5. `DELETE` 两次 → 两次都 204;第二次后 `voice` 为 `null`。
6. 配额:把 `USER_STORAGE_QUOTA_MB` 调到极小值 → 上传返回 **413 + `41301`**,且**没有落盘文件**。
7. 老行为不变:`status` 判定仍只看昵称/性别/生日/城市/简介 + 1 张过审照片,没有语音的用户 `status` 不退化。

**禁止事项**:不改 `Profile` 既有字段;不动 `ChatVoice`;不给未配对用户开放聊天权限;不新增业务码。

---

## Task 2 —— app(依赖 Task 1 已合并)

**改什么**

1. `app/lib/features/profile/`:编辑资料页新增「语音自我介绍」卡片 —— 按住录音(最长 30 秒自动停)、
   试听、删除、替换;上传前本地校验时长。
2. 他人资料页(`profile` 详情)新增播放条:播放/暂停 + 进度 + 时长;失败(403 签名过期)时给「重试」并重新拉资料。
3. 全部色值/字阶/圆角/间距走 `context.heart` 与「心跳」token;**禁裸 hex**。

**验收口径**

1. `scripts/verify.sh app` 全绿(`flutter analyze` 零告警 + 组件测试)。
2. 新增组件测试:录音状态机(空闲→录制→试听→已保存)、播放器加载态/失败态。
3. `no_raw_colors_test.dart` 仍绿。
4. 模拟器(`emulator-5554`)逐页手测并截图:录音 → 保存 → 换号看资料页 → 播放。
   **PR 必须开 draft**,正文写「等待模拟器验收」。

**禁止事项**:不新引音频依赖;不改聊天页录音逻辑;不动 `flutter/`。

---

## Task 3 —— web(依赖 Task 1 已合并)

**改什么**

1. `web/src/features/profile/`:编辑资料页复用 `useVoiceRecorder` + `VoiceRecordBar` 做录音/试听/删除;
   他人资料页加播放条(HTML5 `<audio>` 或复用 `MessageVoice.vue` 的播放逻辑)。
2. 上传走 `FormData`,字段名 `file`;失败按既有 `ApiError` 提示。

**验收口径**

1. `scripts/verify.sh web` 全绿(`vue-tsc` 零错误 + `eslint --max-warnings 0` + vitest 覆盖率门槛)。
2. 组件测试:上传成功/失败、删除后 UI 回到空态、播放器加载失败提示。
3. `no-raw-color.spec.ts` 与 `tokens.spec.ts` 仍绿。
4. `npm run build` 通过。

**禁止事项**:不直接调 `http`(页面只碰 store);不改 `tokens.css` 既有变量值;不手改 `schema.d.ts`。

---

## 执行记录

(交付时回填:实际改动 / 与计划的偏差 / 踩到的坑 / 各栈测试数)
