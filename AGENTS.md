# AGENTS.md — 给在这里干活的 agent

本文件只写**执行约束**:什么不准做、怎么做才算对、错了会在哪条测试上红。
项目全貌与文档导航看 [CLAUDE.md](CLAUDE.md);对外接口看 [docs/api/README.md](docs/api/README.md);
排障按主题看 [docs/pitfalls/README.md](docs/pitfalls/README.md)。冲突时以本文件 → 测试 → `docs/` 为准。

## 一、开工前按改动面读三份材料

| 改什么 | 先读 |
|---|---|
| 后端 | [docs/standards/python.md](docs/standards/python.md)、[docs/pitfalls/backend.md](docs/pitfalls/backend.md) |
| IM 协议 / imserver | [imserver/tests/fixtures/ws/README.md](imserver/tests/fixtures/ws/README.md)、[docs/pitfalls/im.md](docs/pitfalls/im.md) |
| App | [docs/superpowers/specs/2026-09-15-ui-design-language-design.md](docs/superpowers/specs/2026-09-15-ui-design-language-design.md)(「心跳」,强制)、[docs/pitfalls/frontend.md](docs/pitfalls/frontend.md) |
| 网页端 | [docs/pitfalls/web.md](docs/pitfalls/web.md) |

## 二、一单一条栈

`backend` / `web` / `imserver` / `app` / `docs` / `flow` 只能挑一条来改;跨栈需求回报主人拆单。

`flow`(2026-11-14 拍板)= 工程脚本 / CI / 部署脚本:`scripts/**`、`.github/**`、`deploy/**`,
验证入口 `scripts/verify.sh contract`。**栈归属 ≠ 改的权限**:`deploy/**` 仍受 §六 禁止,只能由主人改。
口径地图见 [docs/standards/sources-of-truth.md](docs/standards/sources-of-truth.md)。

契约联动属于**同一条栈的附带改动**,必须同一次做完,不做就是 CI 红:

- 改视图 / 序列化器 → 重生成 `docs/api/openapi.yml`,并同改 `docs/api/*.md`
- 改 WS 帧 → `imserver/tests/fixtures/ws/*.json` + imserver + App(`self_im_client.dart`)+ Web(`web/src/im/self/*`)四处同改
- 改视觉 token / 字体 → `app/lib/core/theme/*.dart` 与 `web/src/styles/tokens.css` 双份
- 升版本号 → `app/pubspec.yaml`(唯一事实来源)+ `app/lib/core/app_info.dart` + `web/package.json`,并在 `docs/releases.yml` 记一条(再 `python scripts/releases.py --render`)
- 新增 / 改 `/api/v1` 接口 → `docs/api/` 对应分册

## 三、验证:唯一入口是 `scripts/verify.sh`

| 你改了什么 | 推之前跑 |
|---|---|
| 后端 | `scripts/verify.sh backend` |
| 网页端 | `scripts/verify.sh web` |
| imserver | `scripts/verify.sh imserver` |
| App | `scripts/verify.sh app` |
| 只改文档 | `scripts/verify.sh contract` |

- **推之前必须绿。**把该命令的末尾输出贴进 PR 描述。
- 它和 CI 跑同一套命令、同一套环境变量(`docker-compose.ci.yml`:MySQL 在 13306、Redis 在 16379),所以本地绿 ≈ CI 绿。
- 首次在新工单目录里跑,若报「没有可用的 venv」,先跑 `scripts/verify.sh bootstrap`(一次性)。
- **`web` / `app` 必须在 Linux 文件系统上跑**(工单目录本来就在 `/root` 下)。脚本会拒绝 `/mnt/*` 路径:9p 太慢,vitest/flutter 会超时,那是环境不是代码。
- `web` 需要 **Node 22**(与 CI 一致);Node 24 会让 `profile-store` 的上传照片用例报 `webidl.is.File` 断言失败。
- 跑 `backend` 会起容器;`--keep-deps` 保留它们便于连续调试。
- **部署前跑 `python scripts/deploy_gate.py`**(2026-11-12 起):校验目标 SHA 属于 `origin/main`
  且该 SHA 的 check 全绿。这是「部署只认合并后 SHA」唯一的机械判定入口;闸门不过不许上线。

## 四、门禁:这些不做必红

| 门禁 | 违反后果 |
|---|---|
| 错误响应契约 `{"code","message","request_id"}`;业务码 = HTTP 前 3 位 + 2 位序号(`config/error_codes.py`) | `config/tests.py` 红 |
| 新增 / 改 `/api/v1` 接口必须同改 `docs/api/` 分册 | `ApiDocsCoverageTests` 红 |
| 对外字段变更必须重生成 `docs/api/openapi.yml`(禁止手改) | `verify.sh backend` 的生成物校验红 |
| 新增 / 改 `.py` 必须有模块与函数 docstring,公开函数带 `Args:`(`test_*`、`setUp`、`Meta`、函数内闭包豁免) | `CommentCoverageTests` 红 |
| 版本号三处一致(`app/pubspec.yaml` 是唯一事实来源) | `sync_version.py --check` 红 |
| App 模型读取的字段必须存在于 OpenAPI 契约 | `check_app_models.py` 红 |
| 响应路径禁止任何第三方网络调用;跨系统副作用一律走 Celery 任务 | 代码审查拒 |
| IM 副作用唯一入口是 `im/tasks.py`,任务参数一律 user_id | 代码审查拒 |

## 五、PR 规矩

- 标题 `<type>(<scope>): <中文摘要>`;正文按 `.github/pull_request_template.md` 写四问:**改了什么 / 怎么验的(贴 verify 输出)/ 留了什么给人验 / 遗留**。
- **低风险合并可以直接合**(2026-11-14 主人修订):满足下面**全部**条件的 PR,本机会话自己 squash
  合并即可,不必再单独占一轮确认:
  - diff **只**落在 docstring、`#` 注释、`docs/**`、以及仓库根的说明性文档(`AGENTS.md` /
    `CLAUDE.md` / `README.md` / `CONTRIBUTING.md`)——没有语句、函数签名、常量、迁移、依赖锁、
    生成物变化;
  - 单一栈(§二);
  - 该栈门禁绿(§三)。纯文档 PR 不触发任何 workflow、没有 check runs 属正常,以
    `scripts/verify.sh contract` 绿为准;已触发的 check 必须全部 success(按 paths 跳过的
    `skipped` 不算红)。
  下面这些**永远不算低风险**,一律人工:**改 `app/` 的 UI 可见行为**、`deploy/**`、`.github/**`、
  生成物、版本号、依赖锁、任何**安全策略**变更(例如 fail-closed 口径)、数据迁移。
- **不开 auto-merge**:仓库 `allow_auto_merge=false` 且 `main` 没有 branch protection(2026-11-14
  实测),arm auto-merge ≈ 立即合并、并不会等 CI 绿。「绿了才合」只能靠合并前自己查 check runs。
- 不属于上面低风险的 PR:**不要自己合并**,不开 auto-merge,不运行任何 merge 命令。
- **碰 `app/` 的 UI 可见改动**:你跑不了模拟器(它只在主人的 Windows 上)。PR 开成 **draft**,正文写「等待模拟器验收」,**不得声称 ready**;Before/After 截图由人补。
- 一个 PR 只解决一个 issue。顺手发现的坑写进 PR 正文的「遗留」段,不要顺手改。
- 发现主人已经在同一问题上动手(他们的分支/PR 含本单的代码),按提示词要求关掉自己的 PR 并指明对方那条。

## 六、绝对不要做

- 改 `flutter/`(Windows Flutter SDK 源码,自带独立 .git)
- 改 `.remember/`、`.env`、任何密钥文件
- 升版本号、打 tag、建 Release、执行 `docs/ops/release.md` 里的发版动作
- `ssh` / `scp` / `rsync` 到生产;改 `deploy/` 下任何脚本
- 手改生成物:`docs/api/openapi.yml` 与 `web/src/api/schema.d.ts` 只能由命令生成

## 七、卡住怎么办

提**一个**具体问题,带上已排除的选项与证据;能用默认值就先按默认值干完,并在 PR 正文标注「假定 X」。
不确定方向时宁可标记 `blocked`,不要猜着改一大片。

## 八、superagent 工单闭环(派单侧)

> **本节只约束派单侧(主人 + 本机会话),不授予 worker 任何权限。** 与本文件 §五、§六 冲突时
> 以 §五/§六 为准:worker 永不合并 PR、永不开 auto-merge。**2026-11-14 起 §五 的「低风险合并
> 可以直接合」只授予主人在场的本机会话,worker 不适用 —— worker 读到的永远是「不合并」。**
> 2026-11-12 从全局 `~/.dsh/AGENTS.md` 迁到这里——那三条只对本仓库成立,不该对所有项目生效。

- **先分析,后开单**:需求分析在本机会话做完再提 issue——改什么、属哪条栈、验收口径能否被
  worker 在**不违反本文件**的前提下自证。凡是「合并后才发生」的事(例如「某条 CI 轨被触发」)
  一律写进「留给人验」,不要写成 worker 的验收项。
- **合并后立刻同步本机**:WSL 母体(`/root/src/chatapp`)与 Windows 仓库都要 `pull --ff-only`
  到合并后的默认分支(`main`),**先 pull 再 prune**。母体不会自动跟随 `origin/main`,而
  `scripts/superagent-prune.sh` 就住在母体里,不同步就会用旧脚本、清不掉 worktree。
- **纯文档 PR 直接合并**:只动 `docs/**` 的 PR 不触发任何 workflow,没有 check runs 是正常的;
  本地 `scripts/verify.sh contract` 绿 + 看完 diff 即可直接 squash 合并,不再单独占一轮确认。
  判定口径与 §五「低风险合并」是**同一份**,不要在这里另立一套。

派单、升级、排障的操作细节见 [docs/ops/superagent.md](docs/ops/superagent.md)。
