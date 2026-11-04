# 腾讯 IM 分支删除计划（backlog D-4）

- 日期：2026-11-04
- 状态：**清单与顺序已出，待执行**（执行窗口见 §5）
- 依据：[backlog D-4](../backlog/2026-11-03-todo.md)、[fullstack review §四 D-2](../reviews/2026-11-03-fullstack-review.md)

## 0. 一句话

自建 IM 已全量（`IM_SELF_GRAYLIST=all`，2026-10-20 起），腾讯分支从「灰度开关」退化成
**一条永远走不到的死代码 + 一层分发 + 一堆文档噪音**。删掉它，同时把「灰度回退」的语义
从「切回腾讯」改成「回退镜像 / 回退后端 SHA」。

**待删代码规模**（不含历史文档）：后端 12 个文件、App 8 个文件、Web 6 个文件、CI 2 个文件。

## 1. 引用清单（按删除难度排序，已用 `git grep -i 'tencent|腾讯'` 全仓核对）

### 1.1 可以直接整文件删除

| 文件 | 说明 |
|---|---|
| `chatapp/im/signature.py` | 腾讯 userSig 的 base64 变体 + 签名/解码，自建走 `im/token.py`（JWT），整个文件是腾讯专用 |
| `app/lib/im/tencent_im_client.dart` | Flutter 侧腾讯 SDK 客户端（23 处引用） |
| `app/lib/im/routing_im_client.dart` | App 侧按 `backend` 字段分发到腾讯/自建（5 处） |
| `web/src/im/routing.ts` | Web 侧同上的分发层 |
| `app/test/im/tencent_im_client_test.dart` | 腾讯客户端单测（5 处） |

### 1.2 需要改逻辑（不能整删）

| 文件 | 腾讯痕迹 | 改成什么 |
|---|---|---|
| `chatapp/im/client.py`（17） | 腾讯 REST 客户端本体（`_call`、`ErrorCode`、`account_import`、`kick`、`block`…） | **保留模块名与公开函数签名**（调用点遍布 tasks/views/management commands），内部改为「只转调 `self_client`」的薄壳；腾讯 REST 实现整段删除 |
| `chatapp/im/backend.py`（2） | `use_self_im` / `self_enabled_for` 按 `IM_BACKEND` + 灰度名单判定 | 删掉判定，两函数恒 `True`（或直接删函数、调用点改成 `True`）——**推荐保留函数名**，改动面最小 |
| `chatapp/config/settings.py`（3） | `IM_BACKEND`、`IM_SELF_GRAYLIST`、`IM_SIG_EXPIRE`、腾讯凭据（SDKAppID/密钥/管理员） | 全删；`IM_SIG_EXPIRE` 若只服务腾讯也删 |
| `chatapp/im/views.py`（4） | `POST /im/user_sig` 双分支、响应里的 `backend: "tencent"` | 只留自建分支，响应固定 `backend: "self"`；**接口路径不变**（老客户端仍在调） |
| `chatapp/im/tasks.py`（2） | 注释里的腾讯语义 + 可能的双分支 | 只留自建路径；`delete_account` 的 `im_user_id` 例外不变 |
| `chatapp/im/models.py`（1）、`im/self_client.py`（1）、`im/apps.py`（1） | 注释/常量里的腾讯字样 | 注释改写 |
| `chatapp/im/management/commands/im_send.py`（2）、`im_setup_system_account.py`（1）、`im_sync_nicknames.py`（2） | 分支判定 + 腾讯管理员账号假设 | 只留自建 |
| `chatapp/accounts/models.py`（1）、`accounts/tests.py`（1）、`seed_fake_users.py`（1） | `im_user_id` 注释 / 腾讯账号假设 | 注释与用例改写 |
| `chatapp/moderation/services.py`（2）、`text_check.py`（1）、`notifications/backends.py`（1）、`users/presence.py`（1） | 注释里「腾讯后端没有 X」 | 注释改写 |
| `chatapp/im/tests.py`（15） | 腾讯分支用例（`IM_BACKEND=tencent` 下的行为） | 删除腾讯用例，保留自建用例 |
| `app/lib/im/im_client.dart`（10）、`im_bootstrap.dart`（4）、`im_repository.dart`（2） | 能力位 / 分发 / `backend` 字段 | 固定自建；`readReceipt` 能力位恒 true（删掉「腾讯 false 不渲染」的假状态分支） |
| `app/lib/features/chat/*`（4 个文件）、`legal_texts.dart`（1） | 注释与协议文本里的「腾讯云 IM」 | 协议文本**不能删**（用户已同意过的条款），只把产品名改成中性表述或保留历史版本说明 |
| `app/pubspec.yaml`（1）、`web/package*.json` | 腾讯 SDK 依赖 | 删除依赖（确认没有别的引用） |
| `web/src/im/client.ts`（5）、`map.ts`（3）、`types.ts`（9）、`stores/chat.ts`（2）、`features/chat/*` | 腾讯类型与分支 | 只留自建 |
| `web/tests/**`（5 个文件） | 同上 | 断言改成自建口径 |
| `.github/workflows/backend.yml`（1）、`web.yml`（1） | 腾讯相关环境变量 | 删 |
| `chatapp/.env.example`（2）、`deploy/docker-compose.yml.tmpl`（1）、`deploy/README.md`（1） | 腾讯凭据占位 | 删 |

### 1.3 只改文档（不动代码）

| 文件 | 处理 |
|---|---|
| `CLAUDE.md`（4） | 「核心契约」里 `IM_BACKEND=tencent|self`、灰度分发、腾讯 `user_sig` 全部改写为「只有自建 IM」 |
| `README.md`（15） | 架构图与 IM 一节去掉腾讯；「灰度回退」改成「回退镜像/后端 SHA」 |
| `docs/api/im.md`（10） | 删腾讯分支的响应字段（`user_sig`/`sdkappid`），`POST /im/user_sig` 只描述自建 `token` |
| `docs/api/README.md`、`docs/api/users.md` | 同上的一两处引用 |
| `docs/ops/imserver.md`（7） | 「腾讯分支」段落删掉；灰度回退方案改镜像回退 |
| `docs/pitfalls/im.md`（12）、`testing.md`（2）、`web.md`（3）、`android-emulator.md`（2） | 保留踩坑记录，但每条前面加一句「（腾讯分支已于 2026-11-XX 删除，此坑仅对历史分支有效）」 |
| `docs/security/*`（3 份审计报告）、`docs/reviews/*` | **历史文档不改正文**，只在文首加一行「本文描述的腾讯分支已于 2026-11-XX 删除」 |
| `docs/superpowers/archive/**`（40+ 份） | **完全不动**（历史存档） |

## 2. 删除顺序（每步都能独立跑测试，不出现「删一半红一片」）

1. **先删客户端**（App + Web）：`tencent_im_client.dart` / `routing_im_client.dart` / `routing.ts` + 各自测试；
   `im_bootstrap` 直接构造自建客户端；能力位收敛。
   验收：`flutter analyze` 零告警 + `flutter test` 全绿；`npm run type-check` / `lint` / `test:run` 全绿。
   （后端此时仍保留分发层，接口响应不变 → 老版本 App 不受影响。）
2. **再删后端分发层**：`im/backend.py` 恒 True；`im/client.py` 变薄壳转调 `self_client`；`im/signature.py` 删除；
   `views.py` 只留自建分支。验收：`python manage.py test` 全绿（删腾讯用例后）。
3. **最后删配置与文档**：settings / `.env.example` / CI / docker-compose 模板 / 上述文档。
   验收：`git grep -i 'tencent|腾讯'` 只剩「历史文档的状态注记」与 `docs/superpowers/archive/**`。
4. **线上验证**：`/api/v1/im/user_sig` 返回 `{backend: "self", token, ...}`；WS 握手 101；
   发一条消息 ack；`/internal/healthz` 200。**回滚方案 = 回退后端 SHA + imserver 镜像**（不再有「切回腾讯」这条路）。

## 3. 风险

| 风险 | 缓解 |
|---|---|
| 老版本 App（1.0.1–1.0.4）仍读 `user_sig` 响应里的腾讯字段 | 只删字段不改路径；老 App 走的是 `backend` 字段判断，`self` 分支已存在且是默认 |
| 灰度名单里还有个别账号留在腾讯？ | 已确认 `IM_SELF_GRAYLIST=all`（全量），且 C-2 已读回执只对自建实现 → 腾讯路径实际上已无人使用 |
| 历史审计报告里提到腾讯分支 | 只加状态注记，不改正文（可追溯） |
| `im/client.py` 改名会牵动很多调用点 | **不改名**，只把内部实现换成转调 `self_client`，把改动面压到最小 |

## 4. 需要一并更新的「回退语义」

现在运维文档里写着「灰度回退 = 把 `IM_SELF_GRAYLIST` 改回某几个 uid」。删除后改为：

> **IM 出问题时的回退**：回退 imserver 镜像 tag（`docker compose run --rm imserver --migrate` 无需，直接 `up -d`），
> 或回退后端 SHA。**不再存在「切回腾讯」的路径** —— 这条要写进 `docs/ops/imserver.md` 与 `docs/pitfalls/im.md`。

## 5. 执行窗口

- **建议日期：2026-11-08（周六）低峰时段**。理由：这是纯删除重构，改完要跑三端全量测试
  （后端 751 + App 447 + Web 429 + imserver），一次完整验证约 30–40 分钟；周末低峰重启影响最小。
- 若想更早：随时可做，但**必须三端一起改**（客户端先、后端后、配置最后），别分两天。
- 删除当天需要：`flutter analyze` / `flutter test`、`npm run type-check && npm run lint && npm run test:run`、
  `python manage.py test`、`imserver` 的 `test_ws.sh` / `test_http.sh`，然后按发布流程（分支 → PR → CI → squash → 部署）。
