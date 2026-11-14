---
状态: 生效中
复核: 每次接口变更时
---

# 推送

> **本能力不启用(2026-11-05 用户决定):本项目不需要离线推送。** 通道固定 `PUSH_PROVIDER=off`,
> 不产生任何外部调用,客户端不集成推送 SDK,也不再采购极光凭据。接口与本文档**保留**(已进 OpenAPI
> 契约与字段级门禁,删除会牵动 `openapi.yml` 与客户端类型生成,收益为零);决策口径与「若要彻底移除
> 该怎么做」见 [backlog §4](../backlog/2026-11-03-todo.md)。**新功能不要依赖本分册的接口。**
>
> 本分册记录推送设备与通知偏好接口。推送通道为极光 JPush:客户端上报 `registration_id`,服务端按「新的喜欢 / 配对成功 / 新消息 / 系统通知 / 动态互动」五类偏好投递;点击通知由客户端按 `extras.deeplink` 跳转。
> 
> **新消息推送的触发方是 imserver**:消息由 imserver 直接写库,Django 收不到「有新消息」,所以由 imserver 在目标不在线时回调 `/internal/push/new-message`(HMAC 共享密钥,不进本分册),再由 Celery 发推送。运维口径见 [docs/ops/push.md](../ops/push.md)。
>
> 通道由 `PUSH_PROVIDER` 三态决定:`off`(默认,不发)/ `log`(只打日志)/ `jpush`(真通道,缺 key 时第一次发信即报错)。

---

## 1. 推送设备

### 1.1 上报推送设备

> `POST` `/api/v1/push/devices` · 需要鉴权 · 无额外限流

**接口描述**

客户端登录后上报本机的极光 `registration_id`,服务端据此投递推送。

- **幂等**:同一 `registration_id` 重复上报只更新归属与版本,不会产生多行;
- **单设备**:同一账号只保留最新上报的一台设备,旧设备记录被删除(与「单设备登录」一致);
- `registration_id` **全局唯一**:同一台手机换账号登录时设备易主,旧账号不再收到该设备的推送;
- **设备易主会留痕并通知原账号**(2026-11-08):当这个 `registration_id` 原本挂在**别的账号**
  名下时,服务端写一条 `push_device_transfer` 日志,并在事务提交后给**原账号**发一条站内通知
  (类型 `system`,文案「你的设备已在另一账号登录,推送已切换」)。同一账号重复上报、或首次登记
  新设备都**不会**产生这条日志与通知。提醒**受原账号的 `system` 通知开关约束**:对方在
  `PATCH /push/preferences` 里关掉 `system` 后,就只剩服务端的 `push_device_transfer` 日志
  (接口仍返回 `200`,不因为通知被关而失败);
- **归属校验仍未加**:知道别人 `registration_id` 的人照样能把设备抢走(推送通道当前固定
  `off`,实际后果仅限归属记录与推送目标),需要时再加「先解绑」或设备指纹绑定;
- 重封禁账号返回 `403`。

**请求参数**(Body,`application/json`)

| 参数名称 | 必填 | 类型 | 描述 |
|---|---|---|---|
| registration_id | 是 | String | 极光 registration_id,≤128 字符 |
| platform | 是 | String | `android` / `ios` |
| app_version | 否 | String | App 版本号,≤32 字符;未传为空串 |

**响应参数**

| 参数名称 | 类型 | 描述 |
|---|---|---|
| registration_id | String | 已登记的 registration_id |
| platform | String | 平台 |

**请求示例**

```bash
curl -X POST "http://<域名>/api/v1/push/devices" \
  -H "Authorization: Bearer <access>" \
  -H "Content-Type: application/json" \
  -d '{"registration_id":"190e35f7e0a7c3b2d1","platform":"android","app_version":"1.0.0"}'
```

**响应示例**

```json
{
  "registration_id": "190e35f7e0a7c3b2d1",
  "platform": "android"
}
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|---|---|---|---|
| 400 | 400 | `registration_id` 为空或超长 / `platform` 不是 `android`、`ios` | 按提示修正后重试 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |
| 403 | 403 | 账号已被封禁(重封禁) | 提示用户账号受限 |

---

### 1.2 解绑推送设备

> `DELETE` `/api/v1/push/devices/{registration_id}` · 需要鉴权 · 无额外限流

**接口描述**

登出时解绑本机设备,之后不再收到推送。

- **幂等**:设备不存在、或不属于当前账号,一律返回 `204`(不泄漏他人设备是否存在);
- 只删除当前账号名下的设备记录;
- 网络失败不影响登出:下次登录上报新设备时,服务端会清理同账号旧设备。

**路径参数**

| 参数名称 | 必填 | 类型 | 描述 |
|---|---|---|---|
| registration_id | 是 | String | 要解绑的极光 registration_id |

**响应参数**

无响应体,HTTP `204`。

**请求示例**

```bash
curl -X DELETE "http://<域名>/api/v1/push/devices/190e35f7e0a7c3b2d1" \
  -H "Authorization: Bearer <access>"
```

**响应示例**

```
HTTP/1.1 204 No Content
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|---|---|---|---|
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |
| 403 | 403 | 账号已被封禁(重封禁) | 提示用户账号受限 |

---

## 2. 通知偏好

### 2.1 获取通知偏好

> `GET` `/api/v1/push/preferences` · 需要鉴权 · 无额外限流

**接口描述**

读取账号级通知偏好,五类通知默认全开。没有记录时返回默认值并落库。

- 偏好是**账号级**:App 与网页端改的是同一份设置;
- 网页端不接收推送,设置只影响 App;
- `social` 是站内通知中心(批次 H)的开关,**也作用于站内通知**:关掉后动态被赞 /
  被评论 / 评论被回复都不再落库(见 [notifications.md](notifications.md))。

**响应参数**

| 参数名称 | 类型 | 描述 |
|---|---|---|
| likes | Boolean | 新的喜欢:有人喜欢你时推送 |
| matches | Boolean | 配对成功:互相喜欢时推送,同时控制站内通知的 `match` |
| messages | Boolean | 新消息:对方发来消息且你不在线时推送(这就是「免打扰」开关) |
| system | Boolean | 系统通知:举报处理结果、账号限制/解封;同时控制站内通知的 `report_handled` |
| social | Boolean | 动态互动:你的动态被赞 / 被评论、你的评论被回复(站内通知) |

**请求示例**

```bash
curl "http://<域名>/api/v1/push/preferences" \
  -H "Authorization: Bearer <access>"
```

**响应示例**

```json
{
  "likes": true,
  "matches": true,
  "messages": true,
  "system": true,
  "social": true
}
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|---|---|---|---|
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |
| 403 | 403 | 账号已被封禁(重封禁) | 提示用户账号受限 |

---

### 2.2 修改通知偏好

> `PATCH` `/api/v1/push/preferences` · 需要鉴权 · 无额外限流

**接口描述**

局部更新通知偏好:只修改传入的字段,未传的保持不变;返回更新后的完整对象。

- 关闭某一类后,服务端不再为该类事件入队推送(已入队的任务会在执行时再次校验);
- 「新的喜欢」另有冷却(PUSH_LIKE_COOLDOWN_SECONDS,默认 10 分钟):同一接收者冷却期内最多收到一条,列表与角标不受影响。

**请求参数**(Body,`application/json`)

| 参数名称 | 必填 | 类型 | 描述 |
|---|---|---|---|
| likes | 否 | Boolean | 新的喜欢开关 |
| matches | 否 | Boolean | 配对成功开关 |
| messages | 否 | Boolean | 新消息开关(关掉后离线消息不再推送) |
| system | 否 | Boolean | 系统通知开关 |
| social | 否 | Boolean | 动态互动开关(关掉后站内通知不再落库) |

**响应参数**

同 [2.1 获取通知偏好](#21-获取通知偏好):返回更新后的五个字段。

**请求示例**

```bash
curl -X PATCH "http://<域名>/api/v1/push/preferences" \
  -H "Authorization: Bearer <access>" \
  -H "Content-Type: application/json" \
  -d '{"likes":false}'
```

**响应示例**

```json
{
  "likes": false,
  "matches": true,
  "messages": true,
  "system": true,
  "social": true
}
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|---|---|---|---|
| 400 | 400 | 字段不是布尔值 | 按提示修正后重试 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |
| 403 | 403 | 账号已被封禁(重封禁) | 提示用户账号受限 |
