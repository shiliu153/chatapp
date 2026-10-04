# 贡献指南

感谢你有兴趣参与这个项目。这份文档说明本仓库的**硬性约束**与提交流程——
它们不是风格偏好,而是已经在测试里落地、违反就会红的规则。

## 开始之前

```bash
# 后端
cd chatapp
cp .env.example .env          # 填 SECRET_KEY / DB_PASSWORD / IM_SDKAPPID / IM_SECRETKEY
docker compose -f docker-compose.dev.yml up -d   # Redis,跑测试前必须先起
pip install -r requirements.txt
python manage.py migrate

# 前端
cd app
flutter pub get
```

## 提交前必须通过

| 检查 | 命令 | 要求 |
|---|---|---|
| 后端全量测试 | `cd chatapp && python manage.py test` | **全绿**(Redis 必须在跑) |
| 前端静态检查 | `cd app && flutter analyze` | **零告警** |
| 前端测试 | `cd app && flutter test` | 全绿 |

CI 会跑同样的三项。**本地每步全绿再进下一步**是这个项目的既定节奏。

## 硬性约束

改动代码时需要遵守的规则(全部有测试或门禁兜底):

1. **错误契约唯一形状** —— 任何非 2xx 响应必须是
   `{"code": <HTTP状态码>, "message": "<中文>", "request_id": "..."}`。
   新增业务码写进 `chatapp/config/error_codes.py`,前 3 位等于 HTTP 状态码、后 2 位为序号。
2. **改接口必须同一次改动内改文档** —— 增删改任何 `/api/v1` 接口,
   必须同步更新 `docs/api/` 下对应分册;`ApiDocsCoverageTests` 会双向比对,漏写即失败。
3. **响应路径禁止任何第三方网络调用** —— 请求处理过程中不得直接调用腾讯云 REST、
   短信服务商等;跨系统副作用一律通过 `transaction.on_commit(...)` 投递到 Celery 任务。
4. **IM 副作用只走 `chatapp/im/tasks.py`** —— 任务参数只传 `user_id`,任务内部自己查库,
   任务体里不碰 request 对象;`im/client.py` 对外永不抛异常。
5. **测试里 IM 一律 mock** —— 用 `im.tasks.*.delay` 的断言方式,不要真的发消息。
6. **`.env` 里禁用 `CELERY_` 前缀的键** —— broker 地址用 `BROKER_URL`
   (Celery 自身的 `CELERY_BROKER_URL` 会静默压过 Django settings)。
7. **前端不写裸样式值** —— 色板 / 字阶 / 圆角 / 间距 / 动效时长一律走
   [「心跳」设计规则](docs/superpowers/specs/2026-09-15-ui-design-language-design.md)的 token;
   图标统一用 Material `*_rounded` 变体。
8. **前端 401 只走 `AuthInterceptor`** —— 不要在业务代码里另写刷新逻辑。

## 提交信息

采用 `type: 概述` 的格式,常见 type:`feat` / `fix` / `docs` / `refactor` / `test` / `chore`。
一次提交尽量只做一件事;涉及接口的改动在正文里写清影响了哪些接口。

## Issue 与 PR

- **Bug 报告**请附:复现步骤、期望行为、实际行为、后端日志里的 `request_id`(如果有)。
- **功能建议**请说明使用场景,而不只是"想要某个功能"。
- **PR** 请保持改动聚焦;涉及行为变更时,请一并补测试,并在描述里说明验证方式。

## 安全

请不要在 Issue / PR 里贴真实凭据。**发现安全问题请私下联系维护者,不要公开提交 Issue。**
仓库里的 `SECRET_KEY`、数据库口令、腾讯云 IM 密钥都只应存在于 `chatapp/.env`(不入库);
如果你不小心提交了真实密钥,除了删除文件,还要**立刻在服务商侧轮换该密钥**——
从 Git 历史里抹掉内容并不能让已经泄漏的密钥重新变安全(本仓库正是为此做过全历史清洗)。

## 许可

贡献的代码将以本仓库的 [MIT 许可](LICENSE)发布。
