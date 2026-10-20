# 推送:新的喜欢 / 配对成功 / 系统通知(设计)

日期:2026-10-20 · 状态:已交付(2026-10-20;代码与三端门禁全绿,真机推送待极光 key)
上游:P1「留存闭环」第四小批(拆分见 `2026-10-20-likes-received-design.md` §1)。
下游:实施计划 `docs/superpowers/plans/2026-10-20-push-notifications.md`。

## 1. 背景与定位

P1-1 / P1-2 / P1-3 已交付并合入 master。P1 只剩最后一块:**用户离开 App 后,没有任何回访理由**。

- 有人喜欢了你,但你不知道 —— 「喜欢我的人」列表只有打开 App 才看得到;
- 互相喜欢那一刻,先喜欢的一方可能已经退出,配对灰条要等他下次打开 IM 才看到;
- 举报处理完、账号被限制,同样只有进 App 才知道。

**目标:** 在 App 不在前台时,用系统通知把这三类事件送到用户手上,点击直达对应页面。

**本批只做「业务通知」**,不做聊天消息推送。原因是两条技术路线现在都不通:

| 方案 | 卡点 |
|---|---|
| 腾讯云 IM 自带离线推送 | 要在华为/小米/OPPO/vivo 开发者平台登记应用并配厂商证书;应用尚未上架 |
| IM 回调 → Django → 极光 | 腾讯要求回调地址是 **HTTPS**;当前服务器只有 `IP:80`,没有备案域名与证书 |

聊天消息推送挂起为 **P1-4b**,前置条件与接入点见 §8。

**非目标(本批不做):**

- 聊天消息推送(P1-4b,见 §8);
- 评论 / 点赞推送(已有 IM 灰条,推送价值低、打扰高);
- 通知中心 / 站内消息列表(点击直达目标页,不新建收件箱);
- Web 推送(浏览器没有稳定的推送渠道;Web 只做设置入口);
- 按设备维度的偏好(偏好是账号级,单设备登录下没有意义);
- 厂商通道(华为/小米/OPPO/vivo/荣耀)—— 需要应用上架与证书,后续单独做;
- 推送到达率统计、埋点、A/B 文案。

## 2. 已定关键决策(用户确认)

| 决策点 | 结论 | 落选理由 |
|---|---|---|
| 推送通道 | **极光 JPush**(官方 Flutter 插件 `jpush_flutter 3.5.8`) | 自有 TCP 通道不需要厂商证书,注册即可真机验证;腾讯 TPNS 配置更重、同样要证书;IM 离线推送只覆盖聊天消息 |
| 本批范围 | **新的喜欢 / 配对成功 / 系统通知** | 聊天消息推送被 HTTPS 回调与厂商证书卡住,硬做只能造假 |
| 通知开关 | **三项真开关**:新的喜欢 / 配对成功 / 系统通知;「新消息」改为灰字说明 | 保留一个永远点不动的占位行,等于骗用户 |
| 喜欢推送频率 | **同一接收者 30 分钟内最多一条** | 被连续喜欢时逐条推会把用户逼去关通知 |
| Web 开关 | **可编辑**,页头注明「网页端不接收推送」 | 偏好存在服务端、账号级;两端不一致反而更困惑 |
| 单设备 | **上报新设备即删除同账号旧设备记录** | 与「单设备登录」一致;旧设备已被顶号,不该继续收推送 |

## 3. 后端设计

### 3.1 数据模型

新增 `chatapp/notifications/models.py`:

```python
class PushPlatform(models.TextChoices):
    ANDROID = "android", "Android"
    IOS = "ios", "iOS"


class PushDevice(models.Model):
    """一台接收推送的设备(极光 registration_id 唯一)。"""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="push_devices")
    registration_id = models.CharField(max_length=128, unique=True)
    platform = models.CharField(max_length=16, choices=PushPlatform.choices)
    app_version = models.CharField(max_length=32, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class NotificationPreference(models.Model):
    """账号级通知偏好;没有行时按默认全开处理。"""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name="notification_preference")
    likes = models.BooleanField(default=True)
    matches = models.BooleanField(default=True)
    system = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)
```

要点:

- `registration_id` **全局唯一**:同一台手机换账号登录时,`update_or_create` 把 `user` 改到新账号,
  旧账号自然失去这台设备(符合单设备语义);
- `NotificationPreference` 不预建:读取用 `get_or_create` 默认全开,注销时随 `CASCADE` 删除;
  模型上提供 `for_user(user)` 类方法,视图与任务共用,避免两处各写一遍 `get_or_create`;
- 账号注销硬删除用户 → 设备与偏好一并删除,不需要额外清理任务。

### 3.2 接口(4 个,接口数 36 → 40)

新增 `chatapp/notifications/urls.py`,在 `config/api_urls.py` 挂 `path("push/", include("notifications.urls"))`。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/push/devices` | 上报设备(幂等 upsert;同账号只保留这一台) |
| DELETE | `/api/v1/push/devices/{registration_id}` | 登出解绑(幂等 204) |
| GET | `/api/v1/push/preferences` | 读三类开关 |
| PATCH | `/api/v1/push/preferences` | 改三类开关(局部更新) |

**`POST /push/devices`**

- body:`{"registration_id": "...", "platform": "android|ios", "app_version": "1.0.0"}`;
- `registration_id` 必填、非空、≤128;`platform` 必须是枚举值;`app_version` 可空;
- 事务内:`update_or_create(registration_id=..., defaults={user, platform, app_version})`,
  再 `PushDevice.objects.filter(user=me).exclude(registration_id=...).delete()`;
- 返回 `200 {"registration_id": ..., "platform": ...}`(幂等,重复上报不报错);
- 重封禁 403 由全局权限类覆盖,无需单独判断。

**`DELETE /push/devices/{registration_id}`**

- 只删**自己的**设备行;不存在 / 属于别人一律 204(不泄漏他人设备是否存在);
- 登出时调用;网络失败不回滚登出(下次登录时 §3.2 的清理会兜底)。

**`GET/PATCH /push/preferences`**

- `GET` 返回 `{"likes": true, "matches": true, "system": true}`(无行时返回默认值并落库);
- `PATCH` 只接受上述三个布尔字段,未传的保持不变;返回更新后的完整对象;
- 偏好是账号级:Web 改、App 生效。

### 3.3 推送客户端(可插拔)

`chatapp/notifications/push.py`:

```python
class PushClient(Protocol):
    def send(self, registration_ids: list[str], *, title: str, alert: str,
             extras: dict) -> bool: ...


class LogPushClient:
    """开发 / 测试:只打日志,永不触网。"""


class JPushClient:
    """极光 REST API v3:POST https://api.jpush.cn/v3/push。"""
```

- 认证:`Authorization: Basic base64(JPUSH_APP_KEY:JPUSH_MASTER_SECRET)`;
- 载荷:`audience.registration_id` 列表;`notification.android` 与 `notification.ios` 各带
  `title` / `alert` / `extras`(iOS 额外 `sound: "default"`、`badge: "+1"`);
- `options`: `apns_production=False`(当前只有 Android 测试包)、`time_to_live=86400`;
- **对外永不抛异常**:网络错误 / 非 2xx 一律记日志并返回 `False`,由任务层决定是否重试;
- 选择器 `get_push_client()`:`settings.PUSH_ENABLED` 为真且 key 齐全时返回 `JPushClient`,
  否则返回 `LogPushClient`。测试永远落在日志后端。

### 3.4 任务与入队

`chatapp/notifications/tasks.py` 新增:

```python
@shared_task(autoretry_for=(Exception,), retry_backoff=True, retry_jitter=True, max_retries=3)
def send_push(user_id: int, kind: str, title: str, alert: str, extras: dict) -> None:
    """按偏好与设备发送一条推送;用户不存在 / 关闭了该类通知 / 没有设备时静默返回。"""
```

任务内顺序:

1. 查用户(不存在 → 静默);
2. 查偏好(`NotificationPreference.for_user(user)`),`kind` 被关闭 → 静默;
3. 查设备 registration_id 列表,为空 → 静默;
4. `kind == "like"` 时做 30 分钟冷却:Redis `cache.add(f"push:like:{user_id}", 1, 1800)`,
   抢不到 → 静默;发送失败时 `cache.delete` 掉,让重试仍有机会;
5. 调 `get_push_client().send(...)`;返回 `False` 时抛异常触发 Celery 重试(最多 3 次)。

`chatapp/notifications/services.py`:

```python
def enqueue_push(user_id: int, kind: str, *, title: str, alert: str, extras: dict) -> None:
    """业务侧唯一入口:on_commit 后入队,broker 抖动不影响主流程。"""
    transaction.on_commit(lambda: send_push.delay(user_id, kind, title, alert, extras),
                          robust=True)
```

> 为什么冷却放在任务里而不是入队时:任务可能重试,入队时判断会在重试路径上失效;
> 放在任务里只判断一次,且与「是否真的发出去了」同一处。

### 3.5 触发点(3 类事件,4 个位置)

| 事件 | 位置 | 收件人 | 标题 / 正文 | 深链 |
|---|---|---|---|---|
| 新的喜欢(未配对) | `discovery/views.py::swipe` | 被喜欢的人 | 「有人喜欢了你」/「去看看是谁」 | `/likes` |
| 配对成功 | `discovery/services.py::notify_match` | **先喜欢的一方**(不是正在滑卡的人) | 「配对成功」/「你和 {昵称} 互相喜欢」 | `/chat/{对方 id}` |
| 举报处理完成 | `moderation/services.py::notify_report_handled` | 举报者 | 「举报已处理」/「你提交的举报已处理完成」 | `/chat/system_notice` |
| 封禁 / 解封 | `moderation/services.py::log_ban_change` | 当事人 | 「账号受限」/「限制已解除」 | `/chat/system_notice` |

实现细节:

- **新的喜欢**:只在 `Swipe` 是**本次新建**(`created`)且 `action=like` 且**没有形成配对**时入队。
  幂等重放、重复提交、已配对都不推 —— 否则对方每点一次就收一条;
- **配对成功**:`notify_match(match, actor_id)` 增加 `actor_id` 参数(调用方传当前用户 id),
  推给 `match.other_user(actor)`;正在滑卡的人已经看到配对动画,不再推;
- **封禁**:heavy 封禁的推送与「踢下线」同一事务提交后入队,顺序不保证;推送是尽力而为,
  踢下线才是硬约束;
- 评论 / 点赞**不推**(见 §1 非目标)。

### 3.6 配置

`chatapp/config/settings.py`:

```python
PUSH_ENABLED = os.getenv("PUSH_ENABLED", "0") == "1"
JPUSH_APP_KEY = os.getenv("JPUSH_APP_KEY", "")
JPUSH_MASTER_SECRET = os.getenv("JPUSH_MASTER_SECRET", "")
PUSH_LIKE_COOLDOWN_SECONDS = int(os.getenv("PUSH_LIKE_COOLDOWN_SECONDS", "1800"))
```

`chatapp/.env.example` 补三个键(值留空/默认),并注明「PUSH_ENABLED=1 且 key 齐全才真的发推送」。

## 4. App 设计

### 4.1 依赖与原生配置

- `app/pubspec.yaml` 增加 `jpush_flutter: ^3.5.8`;
- `app/android/app/build.gradle.kts` 的 `defaultConfig` 增加:

```kotlin
manifestPlaceholders["JPUSH_PKGNAME"] = "com.chatapp.chatapp_app"
manifestPlaceholders["JPUSH_APPKEY"] = keystoreProperties["jpush.appKey"] as String? ?: ""
manifestPlaceholders["JPUSH_CHANNEL"] = keystoreProperties["jpush.channel"] as String? ?: "developer-default"
```

- `app/android/key.properties`(gitignored)增加 `jpush.appKey` / `jpush.channel`;
- `AndroidManifest.xml` 主 Activity 增加 `flutter_deeplinking_enabled=false`
  —— 极光 README 明确:Flutter 3.29+ 默认开启深链,点厂商通道通知会被当成路由,打开白屏;
- 显式声明 `POST_NOTIFICATIONS` 权限(Android 13+ 运行时申请);
- Dart 侧 `app/lib/core/config.dart` 增加 `jpushAppKey = String.fromEnvironment('JPUSH_APP_KEY')`,
  给 `setup()` 用;Android 原生仍以 manifest placeholder 为准,两处填同一个值。

### 4.2 抽象层(照 `ImClient` 的套路)

`app/lib/core/push/push_service.dart`:

```dart
abstract class PushService {
  Future<void> start({required void Function(String deeplink) onOpen});
  Future<String?> registrationId();
  Future<bool> isNotificationEnabled();
  Future<void> openNotificationSettings();
  Future<void> stop();
}
```

- `JPushPushService`:唯一 import `jpush_flutter` 的文件;
  - `start`: `setup(appKey, channel, production: !kDebugMode)` → `setUnShowAtTheForeground(true)`
    → `addEventHandler(onOpenNotification: ...)` → `requestRequiredPermission()`;
  - 点击通知:从 `extras['deeplink']` 取路径;取不到就忽略;
  - 冷启动:`getLaunchAppNotification()` 兜底取一次(Android 通常由 onOpenNotification 触发);
  - 所有原生调用包 `try/catch`:插件缺失(测试环境)或初始化失败都不能影响 App 启动;
- `FakePushService`(放 `app/test/support/`):记录 `start/stop`、可注入 registration_id、
  可手动触发深链回调。

Provider:`pushServiceProvider` 默认 `JPushPushService`;`test/support/harness.dart` 的 `pumpApp`
统一 override 成 `FakePushService`。

### 4.3 生命周期

`app/lib/core/push/push_controller.dart`(`Notifier<PushStatus>`):

- 监听 `sessionProvider`:
  - `SessionLoggedIn` 且未启动 → `start()` → 取 registration_id → `POST /push/devices`;
  - `SessionLoggedOut` → 若有 registration_id → `DELETE /push/devices/{id}` → `stop()`;
- 深链回调:已登录时 `ref.read(routerProvider).go(path)`;未登录忽略(登录后路由会回首页);
- 失败只记日志,不阻塞登录(推送是增强能力,不是登录前置条件);
- 在 `ChatApp.build` 里 `ref.watch(pushControllerProvider)` 激活。

### 4.4 通知设置页

`app/lib/features/settings/notification_settings_page.dart` 重写:

- 三项开关:新的喜欢 / 配对成功 / 系统通知;进入页面 `GET /push/preferences`,切换即 `PATCH`;
- 加载中显示骨架/禁用态;失败显示错误 + 重试;写失败回滚开关并 `AppToast` 提示;
- 顶部权限提示:`isNotificationEnabled()` 为假时显示一行「系统通知未开启」+「去开启」
  (跳系统设置);为真时不显示;
- 底部灰字:「新消息提醒需要接入离线推送,将在后续版本开放」;
- 组件仍用 `AppRowGroup` / `AppListRow` / `Switch.adaptive`,不新增裸样式。

### 4.5 深链路由

复用现有路由,不新增页面:

- `/likes` → 喜欢我的人;
- `/chat/{peerId}` → 聊天页(配对成功直达对方会话);
- `/chat/system_notice` → 系统通知会话(已有页面支持)。

## 5. Web 设计

`web/src/features/settings/NotificationSettingsPage.vue`:

- 新增 `web/src/api/push.ts`(`getPushPreferences` / `updatePushPreferences`)与
  `web/src/stores/push.ts`(state: prefs/loading/error;actions: load/toggle);
- 三个可点开关,写失败回滚并提示;页头注明「网页端不接收推送,这里的设置只影响 App」;
- 保留现有视觉与 token,不新增裸色值。

## 6. 接口文档

- 新增 `docs/api/push.md`:4 个接口,按 7 元素写(信息行 / 描述 / 请求参数 / 响应参数 / 示例 / 错误码);
- `docs/api/README.md`:目录表加一行,接口一览加 4 行,总数 **36 → 40**;
- `ApiDocsCoverageTests` 双向门禁必须绿。

## 7. 测试策略

**后端**(`notifications/tests.py` + 各触发点 app):

- 模型:设备唯一、偏好默认值、注销级联;
- 接口:上报幂等、同账号旧设备被删、换账号设备易主、删除他人设备 204、偏好局部更新;
- 任务:偏好关闭不发、无设备不发、like 冷却、发送失败重试、日志后端不触网;
- 触发点:swipe 新建 like 入队 / 幂等重放不入队 / 配对只推先喜欢方;举报、封禁入队;
- 门禁:`ApiDocsCoverageTests`、`CommentCoverageTests`。

**App**:

- `PushController`:登录后上报、登出解绑、registration_id 为空不上报、失败不阻塞;
- `JPushPushService` 不直接测(原生),测 `FakePushService` + 控制器;
- 设置页:加载、切换成功/失败回滚、权限提示、底部说明;
- 深链:`onOpen('/likes')` 后路由到 `/likes`。

**Web**:

- store 的 load/toggle/回滚;页面渲染三个开关与说明文案。

## 8. P1-4b:聊天消息推送(挂起)

**要做的前置条件(二选一):**

1. 备案域名 + HTTPS 证书 → 在腾讯云 IM 控制台配置第三方回调
   `C2C.CallbackAfterSendMsg` → Django 收到后入队推送;
2. 应用上架 + 各厂商开发者账号 → 在 IM 控制台配置离线推送证书(或继续用极光 + 厂商通道)。

**接入点(本批预留):**

- 回调视图放在 `chatapp/notifications/`(新建 `im_callbacks.py`),校验 `SdkAppid` 与签名;
- 复用本批的 `enqueue_push(kind="message")`,只需给 `NotificationPreference` 加一个
  `messages` 字段与设置页一行开关;
- 回调必须 2 秒内应答,推送一律异步,不在回调里查重表。

## 9. 验收清单

**门禁**

- 后端 `python manage.py test` 全绿(含文档 / 注释门禁);
- App `flutter analyze` 零告警、`flutter test` 全绿;
- Web `vue-tsc` / `eslint --max-warnings 0` / `npm run test:coverage` 全绿。

**真机(需要极光 key)**

1. 登录后 `POST /push/devices` 成功,后台能看到 registration_id;
2. B 喜欢 A → A 收到「有人喜欢了你」,点击进 `/likes`;
3. A 回喜欢 B → B 收到「配对成功」,点击进与 A 的聊天页;
4. 关掉「新的喜欢」开关 → 再有人喜欢 A,A 不再收到;
5. 举报被处理 → 举报者收到「举报已处理」,点击进系统通知会话;
6. 同账号在第二台设备登录 → 第一台不再收到推送(设备记录被删);
7. 登出后再收不到;重新登录恢复。

**快速自检(不依赖业务事件)**

填完 key、重装 APK 并在 App 登录过一次后,可以直接给这台设备发三类测试推送:

```powershell
cd chatapp
python manage.py push_test --user 3 --kind all --peer 9
```

`--user` 是接收者账号 id,`--peer` 是「配对成功」通知点进去要打开的聊天对象;
`--force` 可忽略「新的喜欢」30 分钟冷却。命令会打印设备数、通道是否开启,以及每条通知的深链。

**没有 key 时**

- 后端日志出现 `[推送-日志]` 行,App 不报错(初始化跳过),其余功能不受影响。

## 10. 风险与取舍

| 风险 | 处理 |
|---|---|
| 极光自有通道在进程被杀后可能收不到(国内 ROM) | 文档如实写明;厂商通道留到上架后(P1-4b) |
| `jpush_flutter` 与 Flutter 3.47 的兼容性 | 先跑 `flutter pub get` + 构建;失败则锁 3.5.x 最新可用版本 |
| Android 13 通知权限被拒 | 设置页显示「未开启」并可跳系统设置;服务端照常入队,系统拦截是客户端行为 |
| 推送轰炸 | like 30 分钟冷却;配对 / 系统通知低频,不加冷却 |
| 设备记录泄漏他人信息 | `DELETE` 只删自己的;响应不区分「不存在」与「不是你的」 |
| 业务事件在事务内入队导致推送早于落库 | 统一 `transaction.on_commit(..., robust=True)` |
