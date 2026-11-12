# 贡献指南

感谢你有兴趣参与这个项目。这份文档说明本仓库的**硬性约束**与提交流程——
它们不是风格偏好,而是已经在 CI / 测试里落地、违反就会红的规则。
更细的执行约束(什么不准做、错了会在哪条测试上红)见 [AGENTS.md](AGENTS.md)。

## 开始之前

```bash
# 后端(cwd = chatapp/)
cp .env.example .env                              # 填 SECRET_KEY / DB_PASSWORD / IM_SELF_*
docker compose -f docker-compose.dev.yml up -d    # Redis(跑测试前必须先起)
pip install -r requirements.lock                  # 装锁定文件,与 CI / 生产镜像一致
python manage.py migrate

# 前端(cwd = app/)
flutter pub get

# 网页端(cwd = web/)
npm ci
```

## 提交前必须通过:唯一入口是 `scripts/verify.sh`

| 你改了什么 | 推之前跑 |
|---|---|
| 后端 | `scripts/verify.sh backend` |
| 网页端 | `scripts/verify.sh web` |
| imserver | `scripts/verify.sh imserver` |
| App | `scripts/verify.sh app` |
| 只改文档 / 脚本 | `scripts/verify.sh contract` |

- **推之前必须绿**,把该命令的末尾输出贴进 PR 描述。
- 它和 CI 跑同一套命令与依赖(`docker-compose.ci.yml`:MySQL 13306 / Redis 16379),
  所以本地绿 ≈ CI 绿。
- 首次在新目录跑若报「没有可用的 venv」,先跑 `scripts/verify.sh bootstrap`(一次性)。
- `web` / `app` 必须在 **Linux 文件系统**上跑(WSL 的 `/mnt/*` 太慢,vitest/flutter 会超时)。
- `web` 需要 **Node 22**(与 CI 一致);Node 24 会让一条 jsdom 用例假红。
- **部署前**跑 `python scripts/deploy_gate.py`:校验目标 SHA 属于 `origin/main` 且该 SHA
  的 check 全绿。闸门不过不许上线。

## CI 是怎么跑的(知道这个能省很多时间)

六条轨:`跨栈契约` / `Backend (Django)` / `Web (Vue)` / `Web E2E` / `App (Flutter)` / `imserver`。

- `contract`(秒级)与两条 `scope` 判定**每个 PR 都跑**;
- backend / web 的**重活按改动面跑**:没碰 `chatapp/**`、`perf/**`、`docs/api/**`、
  `app/pubspec.yaml` 就不跑后端全量;没碰 `web/**`、`imserver/tests/fixtures/**` 就不跑网页端。
  无关时对应 job 是 `skipped`,不占 CI 时间;
- 判定逻辑坏了会**按「要跑」处理**(fail-closed),不会静默跳过。

## 硬性约束

改动代码时需要遵守的规则(全部有测试或门禁兜底):

1. **错误契约唯一形状** —— 任何非 2xx 响应必须是
   `{"code": <HTTP状态码>, "message": <中文>, "request_id": "..."}`。
   新增业务码写进 `chatapp/config/error_codes.py`,前 3 位等于 HTTP 状态码、后 2 位为序号。
2. **改接口必须同一次改动内改文档** —— 增删改任何 `/api/v1` 接口,必须同步更新
   `docs/api/` 下对应分册;`ApiDocsCoverageTests` 双向比对,漏写即红。
3. **对外字段变更必须重生成 `docs/api/openapi.yml`**(禁止手改,命令见 CLAUDE.md)。
4. **响应路径禁止任何第三方网络调用**;跨系统副作用一律走 Celery 任务。
5. **IM 副作用只走 `chatapp/im/tasks.py`**,任务参数只传 `user_id`,任务体内自己查库。
6. **测试里 IM 一律 mock**(`im.tasks.*.delay`),不要真的发消息。
7. **`.env` 里禁用 `CELERY_` 前缀的键** —— broker 地址用 `BROKER_URL`。
8. **前端不写裸样式值** —— 色板/字阶/圆角/间距/动效时长一律走「心跳」token。
9. **新增/改 `.py` 必须有模块与函数 docstring,公开函数带 `Args:`** —— `CommentCoverageTests` 红。
10. **版本号三处一致**,事实来源只有 `app/pubspec.yaml`;发版记录见 `docs/ops/release.md`。

## 提交信息与 PR

- 提交信息 `type(scope): 概述`,常见 type:`feat` / `fix` / `docs` / `refactor` / `test` / `chore` / `ci`。
- PR 标题 `<type>(<scope>): <中文摘要>`;正文按 `.github/pull_request_template.md` 写四问:
  **改了什么 / 怎么验的(贴 verify 输出)/ 留了什么给人验 / 遗留**。
- 一个 PR 只解决一个 issue;顺手发现的坑写进「遗留」段,不要顺手改。

## 安全

请不要在 Issue / PR 里贴真实凭据。**发现安全问题请私下联系维护者,不要公开提交 Issue。**
仓库里的 `SECRET_KEY`、数据库口令、IM 密钥都只应存在于 `chatapp/.env`(不入库);
如果你不小心提交了真实密钥,除了删除文件,还要**立刻在服务商侧轮换该密钥**——
从 Git 历史里抹掉内容并不能让已经泄漏的密钥重新变安全(本仓库正是为此做过全历史清洗)。

## 许可

贡献的代码将以本仓库的 [MIT 许可](LICENSE)发布。
