# 贡献指南

感谢你有兴趣参与这个项目。这份文档说明本仓库的**提交流程**与协作约定。
硬性约束(什么不准做、怎么做才算对、错了会在哪条测试上红)的 owner 是 [AGENTS.md](AGENTS.md) ——
本文件**只保留指针**,不再维护第二份清单(2026-11-14 治理第 6 节,见 C6)。

## 开始之前

环境、依赖、首次启动的**完整步骤**在 [docs/standards/dev-commands.md](docs/standards/dev-commands.md)
(前置要求表 → 后端 setup 六步 → Redis / Celery → 前端 → 网页端 → 出签名包)。

三句话版本:`cp chatapp/.env.example chatapp/.env` 并填密钥;**跑测试与接口前 Redis 必须先起**;
`web/` 与 `app/` 必须在 **Linux 文件系统**上跑(`/mnt/*` 的 9p 太慢,vitest / flutter 会超时)。

## 提交前必须通过:唯一入口是 `scripts/verify.sh`

「你改了什么 → 推之前跑哪条」的对照表由 [AGENTS.md](AGENTS.md) §三 说了算
(后端 `backend` / 网页端 `web` / imserver `imserver` / App `app` / 只改文档与脚本 `contract`)。
**推之前必须绿**,并把该命令的末尾输出贴进 PR 描述。

- 它与 CI 跑**同一份**门禁清单([`scripts/gates.toml`](scripts/gates.toml))与**同一个**执行器
  ([`scripts/run_gates.py`](scripts/run_gates.py)),所以本地绿 ≈ CI 绿。
- 首次在新目录跑若报「没有可用的 venv」,先跑 `scripts/verify.sh bootstrap`(一次性)。
- **部署前**跑 `python scripts/deploy_gate.py`:校验目标 SHA 属于 `origin/main` 且该 SHA 的 check 全绿。

## CI 是怎么跑的(知道这个能省很多时间)

- `contract`(秒级)与改动面判定(`scripts/ci-scope.sh`)**每个 PR 都跑**;
- backend / web 的**重活按改动面跑**:没碰 `chatapp/**`、`perf/**`、`docs/api/**`、`app/pubspec.yaml`
  就不跑后端全量;没碰 `web/**`、`imserver/tests/fixtures/**` 就不跑网页端。无关时对应 job 是
  `skipped`,不占 CI 时间;
- 判定逻辑坏了会**按「要跑」处理**(fail-closed),不会静默跳过;
- 只动 `docs/**` 的 PR **不触发任何 workflow**,没有 check runs 是正常的 —— 本地
  `scripts/verify.sh contract` 绿 + 人看完 diff 即可合并。

## 硬性约束

硬性约束(错误契约 / 接口文档同步 / OpenAPI 生成物 / 注释规范 / 版本号 / IM 副作用入口 / 前端 token 等)
的 owner 是 [AGENTS.md](AGENTS.md) §四「门禁:这些不做必红」与 [CLAUDE.md](CLAUDE.md)
「核心契约与纪律」。**本文件不再抄第二份**(两份清单会漂移,这正是治理要消灭的东西)。

写代码前的必读材料按改动面选:[AGENTS.md](AGENTS.md) §一。

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
