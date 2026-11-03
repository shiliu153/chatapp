# 客户端错误上报

> 本分册记录前端(Web / App)未捕获异常的上报接口。它服务于**可观测性**,不是业务功能:
> 服务端 Prometheus 只能看到自己返回了 5xx,而前端白屏、JS 运行时异常、Flutter 崩溃
> 完全不会出现在服务端指标里 —— 用户不刷新就没人知道。

---

## 1. 上报错误

### 1.1 上报一条客户端错误

> `POST` `/api/v1/client-errors` · 不需要鉴权 · 限流 120 次/小时(按 IP)

**接口描述**

Web 的 `window.onerror` / `unhandledrejection` / Vue `errorHandler`,以及 App 的
`FlutterError.onError` / `PlatformDispatcher.onError` 捕获到未处理异常后调用。

- **允许匿名**:登录页白屏、启动即崩这类最有价值的错误发生时,客户端还没有令牌;
- **不落库**:错误写进服务端单行 JSON 日志(`logger = chatapp.client_error`),
  由 Loki / Grafana 按 `request_id`、`platform`、`route` 检索,并累加指标
  `client_errors_total{platform}`;
- **幂等性无关**:纯上报,不产生任何业务副作用;
- 客户端**不应当**因为它失败而影响自身流程(建议 fire-and-forget,失败静默丢弃)。

**请求参数**(Body,`application/json`)

| 参数名称 | 必填 | 类型 | 描述 |
|---|---|---|---|
| platform | 是 | String | `web` 或 `app` |
| message | 是 | String | 错误摘要,≤500 字 |
| stack | 否 | String | 堆栈文本,≤8000 字;超长请客户端自行截断 |
| route | 否 | String | 出错的页面/路由,如 `/chats/u9`,≤200 字 |
| app_version | 否 | String | 客户端版本号,≤32 字 |
| request_id | 否 | String | 客户端最后收到的 `X-Request-Id`,用来与服务端日志对账,≤64 字 |

**响应参数**

成功返回 `204 No Content`,无响应体。

**请求示例**

```bash
curl -X POST "http://<域名>/api/v1/client-errors" \
  -H "Content-Type: application/json" \
  -d '{
    "platform": "web",
    "message": "TypeError: Cannot read properties of undefined (reading \"peerId\")",
    "stack": "at ChatPage.vue:42",
    "route": "/chats/u9",
    "app_version": "1.0.2",
    "request_id": "9f8c1b2e4d5a"
  }'
```

**响应示例**

```
HTTP/1.1 204 No Content
X-Request-Id: 3f2a...
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|---|---|---|---|
| 400 | 400 | `platform` 不在白名单 / 缺 `message` / 字段超长 | 客户端代码有 bug,按提示修正上报字段 |
| 429 | 429 | 上报过于频繁(120 次/小时/IP) | 客户端应丢弃后续错误,不要重试 |
| 500 | 500 | 服务端内部错误 | 静默丢弃,不影响用户流程 |

**观测入口**

- 日志:`level=error`, `logger=chatapp.client_error`, 字段 `platform` / `client_message` /
  `client_stack` / `client_route` / `app_version` / `client_request_id` / `user_id` / `user_agent`;
- 指标:`client_errors_total{platform="web|app"}`(见 `GET /metrics`);
- 开关:Web 端 `VITE_ERROR_REPORTING=1`、App 端 `--dart-define=ERROR_REPORTING=true`,
  **本地与测试默认关闭**。
