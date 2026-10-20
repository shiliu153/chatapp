# 推送

> 本分册记录推送设备与通知偏好接口。推送通道为极光 JPush:客户端上报 `registration_id`,服务端按「新的喜欢 / 配对成功 / 系统通知」三类偏好投递;点击通知由客户端按 `extras.deeplink` 跳转。

---

## 1. 推送设备

### 1.1 上报推送设备

> `POST` `/api/v1/push/devices` · 需要鉴权 · 无额外限流

**接口描述**

客户端登录后上报本机的极光 `registration_id`,服务端据此投递推送。

- **幂等**:同一 `registration_id` 重复上报只更新归属与版本,不会产生多行;
- **单设备**:同一账号只保留最新上报的一台设备,旧设备记录被删除(与「单设备登录」一致);
- `registration_id` **全局唯一**:同一台手机换账号登录时设备易主,旧账号不再收到该设备的推送;
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

读取账号级通知偏好,三类通知默认全开。没有记录时返回默认值并落库。

- 偏好是**账号级**:App 与网页端改的是同一份设置;
- 网页端不接收推送,设置只影响 App。

**响应参数**

| 参数名称 | 类型 | 描述 |
|---|---|---|
| likes | Boolean | 新的喜欢:有人喜欢你时推送 |
| matches | Boolean | 配对成功:互相喜欢时推送 |
| system | Boolean | 系统通知:举报处理结果、账号限制/解封 |

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
  "system": true
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
- 「新的喜欢」另有 30 分钟冷却:同一接收者 30 分钟内最多收到一条,列表与角标不受影响。

**请求参数**(Body,`application/json`)

| 参数名称 | 必填 | 类型 | 描述 |
|---|---|---|---|
| likes | 否 | Boolean | 新的喜欢开关 |
| matches | 否 | Boolean | 配对成功开关 |
| system | 否 | Boolean | 系统通知开关 |

**响应参数**

同 [2.1 获取通知偏好](#21-获取通知偏好):返回更新后的三个字段。

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
  "system": true
}
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|---|---|---|---|
| 400 | 400 | 字段不是布尔值 | 按提示修正后重试 |
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |
| 403 | 403 | 账号已被封禁(重封禁) | 提示用户账号受限 |
