---
状态: 生效中
复核: 每次改推送通道时
---

# 推送(C-1):链路、开关与验证

> **状态(2026-11-05 用户决定):本项目不做离线推送,本条链路不再往下推进。** 通道固定
> `PUSH_PROVIDER=off`,imserver 只累加 `push_skipped_total{reason="provider_off"}`,App 不集成推送 SDK、
> 不再注册极光凭据。**本文档保留为内部契约与实现记录**(排查时仍需知道这条链路存在且是关的),
> 决策与「若要彻底移除该怎么做」见 [backlog §4](../backlog/2026-11-03-todo.md)。
>
> 历史现状(2026-11-05 **已上线** `3ef2b8c`):**链路已打通并端到端验证过,但通道默认关闭(`PUSH_PROVIDER=off`)** ——
> 极光 AppKey/MasterSecret 未注册。接上 key 之后只需改配置 + App 侧上报
> `registration_id` + 真机验收,服务端不用再改代码(**该路径已作废,不要再按它排期**)。
>
> 相关:接口契约 [docs/api/push.md](../api/push.md);imserver 内部事件在本文 §3。
>
> **已实测的端到端证据(2026-11-05)**:`im_send` 给离线用户 → imserver `im_push_total{queued}=1,sent=1`
> → Django `push_sent_total{provider="log",result="ok"}=1` → Celery 日志
> `[推送-日志] devices=1 title=小雨12 alert=推送联调-172952 extras={'deeplink': '/home/chats/12', 'peer': '12'}`;
> 通道改回 `off` 后再发一条,只多一条 `push_skipped_total{reason="provider_off"}`。

## 1. 链路长什么样

```
① 业务事件(Django 自己知道)              ② 离线新消息(只有 imserver 知道)
   喜欢 / 配对成功 / 系统通知                  消息落库后目标不在线
        │                                        │  POST /internal/push/new-message
        │ services.enqueue_push                  │  (HMAC 共享密钥,回环直连)
        ▼                                        ▼
   ┌──────────────────────────────────────────────────────┐
   │ Celery 队列 notify → notifications.tasks              │
   │   send_push(喜欢/配对/系统)  send_message_push(新消息)  │
   │   逐层短路:通道 → 账号 → 封禁 → 偏好 → 设备 → 去重      │
   └──────────────────────────────────────────────────────┘
                            │
                            ▼  get_push_client()
              off(不发) / log(只打日志) / jpush(极光 REST v3)
```

**为什么新消息要绕一圈**:消息是 imserver 直接写 `chatapp_im` 的,Django 根本不知道
「有新消息」。只有 imserver 在**落库之后、目标不在线时**发一次内部事件,Django 才能在
Celery 里发推送。**响应路径与 imserver 发送路径都不做第三方调用** —— 入队即返回。

## 2. 开关与配置

| 变量 | 侧 | 默认 | 说明 |
|---|---|---|---|
| `PUSH_PROVIDER` | Django | `off` | `off` / `log` / `jpush`。**三态显式**,不再用「有没有 key」猜通道 |
| `JPUSH_APP_KEY` / `JPUSH_MASTER_SECRET` | Django | 空 | `jpush` 时必填,缺了第一次发信就 `ImproperlyConfigured`(不静默降级) |
| `JPUSH_APNS_PRODUCTION` | Django | `1` | iOS 走 APNs 生产环境;开发证书联调置 `0` |
| `PUSH_LIKE_COOLDOWN_SECONDS` | Django | `600` | 「新的喜欢」冷却:同一接收者冷却期内最多响一次 |
| `PUSH_DEDUP_TTL` | Django | `3600` | 同一条消息的幂等窗口(按 `msg_id`) |
| `PUSH_INTERNAL_MAX_SKEW` | Django | `300` | 内部事件时间戳允许偏移(秒),超了按重放拒绝 |
| `IM_PUSH_URL` | imserver | 空 | **空 = 关闭**;例 `http://127.0.0.1:8000/internal/push/new-message` |
| `IM_PUSH_TIMEOUT_MS` | imserver | `2000` | 单次事件 HTTP 超时 |
| `IM_PUSH_QUEUE` | imserver | `256` | 事件队列长度;**满了就丢**(绝不反压发送路径) |

> 两侧都要重启才生效:Django 读 `.env` 在启动时(改完重启 `chatapp-web`,
> 约 3 秒 502);imserver 同理(改完 `imserver.env` 后重启容器)。
> 重启命令见 [runbook §3](runbook.md)。

## 3. 内部事件契约(imserver → Django)

`POST /internal/push/new-message`,**不在 `/api/v1` 下**(不进接口文档门禁与 OpenAPI)。

**签名**(与 Django → imserver 方向完全一致,两边共用 `IM_SELF_INTERNAL_SECRET` / `IM_INTERNAL_SECRET`):

```
signing   = f"{timestamp}\nPOST\n/internal/push/new-message\n{body}"
signature = hex(hmac_sha256(secret, signing))
头:X-IM-Timestamp(秒级)、X-IM-Signature
```

**请求体**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| to_user_id | Integer | 是 | 接收者账号 id(>0) |
| from_user_id | Integer | 是 | 发送者账号 id(>0;系统消息不推) |
| msg_id | Integer/String | 是 | 消息 id,用于幂等去重 |
| from_nickname | String | 否 | 发送者昵称,通知标题 |
| preview | String | 否 | 预览文本;imserver 已把图片/语音替换成 `[图片]` / `[语音]` |

**响应**

| 状态码 | 含义 |
|---|---|
| 202 | 已入队(幂等:同一 `msg_id` 重复到只会响一次) |
| 400 | 字段不合法(缺字段、收发相同、不是 JSON) |
| 401 | 验签失败(缺头、时间戳超窗、签名不符、密钥未配) |
| 405 | 方法不是 POST |

**imserver 侧行为**:`PushNotifier` 只做入队,独立线程发 HTTP;队列满丢事件并记
`im_push_total{result="dropped"}`;`kind=2`(灰条/系统通知)与 `from=0` 不推。

## 4. 怎么端到端验证(不需要极光 key)

`log` 通道会把推送内容打进 Django 日志,这就是「链路通不通」的证据。

```bash
# ① 打开两侧开关
#   chatapp/.env:      PUSH_PROVIDER=log
#   imserver.env:      IM_PUSH_URL=http://127.0.0.1:8000/internal/push/new-message
#   然后重启 chatapp-web 与 imserver

# ② 造一个「有设备、有配对、对方离线」的场景
#    (A 上报设备;A 与 B 已配对;B 不连 WS = 离线)
curl -X POST https://chat.shiliu153.cn/api/v1/push/devices \
  -H "Authorization: Bearer <A 的 access>" -H "Content-Type: application/json" \
  -d '{"registration_id":"test-rid-1","platform":"android"}'

# ③ 让 B 给 A 发一条消息(imserver 内部接口,不需要 WS 连接)
cd /www/wwwroot/chatapp/chatapp
python manage.py im_send --from u<B> --to u<A> --text "推送联调"

# ④ 看证据(三处)
journalctl -u chatapp-web --since "2 min ago" | grep '推送-日志'   # Celery 侧日志在 worker
grep '推送-日志' /www/wwwlogs/chatapp/celery.log 2>/dev/null | tail -3
curl -s 127.0.0.1:9101/internal/metrics | grep im_push_total       # imserver 侧计数
```

期望:`im_push_total{result="queued"}` +1、`{result="sent"}` +1,并看到一条
`[推送-日志] devices=1 title=<B 昵称> alert=推送联调 extras={'deeplink': '/home/chats/<B>', ...}`。

> 若 `queued` 涨但 `sent` 不涨:看 Django 侧 `push_skipped_total{reason}` ——
> `provider_off` / `preference_off` / `no_device` / `banned` / `duplicate` 各自对应一种短路。

## 5. 接极光时还差什么

> **本节已作废(2026-11-05)**:本项目不做离线推送,不注册极光凭据、不集成客户端 SDK。
> 仅当项目定位再次变化、且明确需要离线触达时才重新评估;届时按当时的最新契约重写本节,
> 不要照抄下面的步骤。

1. 极光控制台建应用 → 拿 **AppKey / MasterSecret**,填进 `.env` 并 `PUSH_PROVIDER=jpush`;
2. **App 侧**:集成极光 SDK,登录后调 `POST /api/v1/push/devices` 上报 `registration_id`
   (登出调 `DELETE`);Web 端不做推送(浏览器通知不接);
3. **真机验收**:锁屏收到通知 → 点开直达会话(`extras.deeplink` = `/home/chats/<peer>`);
4. iOS 还需要 APNs 证书/密钥在极光后台配好,`JPUSH_APNS_PRODUCTION` 按证书类型设置。

## 6. 排查表

| 现象 | 先看 | 常见原因 |
|---|---|---|
| 完全没推送 | `PUSH_PROVIDER` 两侧配置 | 默认 `off`;imserver 侧 `IM_PUSH_URL` 空 = 不发事件 |
| imserver 计数不动 | `imserver` 日志 `push_notifier_enabled` | `IM_PUSH_URL` 没配/写错;或目标其实**在线**(在线不推) |
| `queued` 涨 `failed` 涨 | Django 访问日志里的 `POST /internal/push/new-message` | 401 验签(两侧密钥不一致)、301(被 HTTPS 强制跳转 —— `SECURE_REDIRECT_EXEMPT` 已含 `^internal/`) |
| `push_skipped_total{reason="no_device"}` | `accounts`/`notifications_pushdevice` 表 | App 没上报设备,或上报后换账号(设备易主) |
| `reason="preference_off"` | `/api/v1/push/preferences` | 用户关掉了对应开关(新消息看 `messages`) |
| `reason="duplicate"` | 同一条消息重复事件 | 正常(幂等);若「一条消息多次响」则是 msg_id 不稳定 |
| 极光返回非 2xx | 日志 `极光推送失败 status=...` | key 不对、`registration_id` 失效、APNs 证书未配 |

## 7. 指标

| 指标 | 位置 | 含义 |
|---|---|---|
| `im_push_total{result=queued\|sent\|failed\|dropped}` | imserver `/internal/metrics` | 事件从 imserver 出去的四个阶段 |
| `push_sent_total{provider,result}` | Django `/metrics` | Celery 侧真正调用通道的结果 |
| `push_skipped_total{reason}` | Django `/metrics` | 为什么**没**推(见 §6) |
