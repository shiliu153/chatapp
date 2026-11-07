# 踩坑手册 · 测试

> 索引见 [README.md](README.md)。测试纪律是硬要求:后端 `python manage.py test` 全绿、`flutter analyze` 零告警、每步全绿再进下一步。
>
> 本地复刻 CI 的统一入口是 `scripts/verify.sh <stack>`(`backend` / `web` / `imserver` / `app` / `contract` / `all`),命令序列与环境变量逐项对齐 `.github/workflows/*.yml`;用法与依赖安装见 [docs/ops/superagent.md](../ops/superagent.md) 与根目录 [AGENTS.md](../../AGENTS.md)。下面「在 WSL / Linux 本地跑验证」一节是它的环境坑。

## 后端(Django)

- 前置:本地 Redis 在跑(`docker compose -f docker-compose.dev.yml up -d`);测试自动用 DB15(缓存)/ DB14(broker),不碰开发数据。
- ⚠️ **别并发跑两套后端测试**:两个测试进程会抢同一个测试库名 `test_chatapp_dev`,清理失败后,下一次 `manage.py test` 会停在 `Type 'yes' if you would like to try deleting the test database ...` 并因 stdin 不是终端抛 `EOFError` 退出(实测 2026-10-09)。脚本/CI 里一律加 `--noinput`,会自动丢弃旧测试库。
- ⚠️ **测 `on_commit`**:`notify_match` / 登录后 `sync_login` / 拉黑/封禁/资料同步的入队都走 `transaction.on_commit`,测试必须 `with self.captureOnCommitCallbacks(execute=True):` 包住请求,否则断言永远不触发。
- ⚠️ **测试里 Celery 任务只入队、不执行**(无 worker):断言「入队了什么」用 `patch("im.tasks.ban_notice.delay")` / `patch("im.tasks.sync_profile.delay")` 之类;要测任务体直接 `task.run(...)`,此时 mock `im.client.*`,腾讯 REST 一次都不能真打。
- ⚠️ **凡会触发 IM 调用的用例都要 mock**:漏 mock 会真打腾讯云(用例仍绿,因为业务函数吞异常——靠跑测试时日志里有没有 `IM ... 返回错误` 发现),且变慢、依赖网络。
- ⚠️ 限流用例要 `cache.clear()`:计数在 Redis,跨用例残留会导致偶发 429(DB15 与开发 DB0 隔离,clear 不误伤)。

## 在 WSL / Linux 本地跑验证(`scripts/verify.sh`)

这一节只讲**环境**坑:四条都在 WSL 里实测踩到、现已由 `scripts/verify.sh` 兜住(2026-11-07)。看到类似报错先怀疑环境,别当业务用例红了去改用例。

### 1. 测试模式不读 `REDIS_URL`

- **现象**:`manage.py test` 大面积报 `ConnectionInterrupted: Error 111 connecting to 127.0.0.1:6379`(实测 875 个用例里 359 个 error),凡是碰缓存 / 限流计数 / `on_commit` 入队的用例几乎全中;可 Redis 明明在跑(只是不在 6379)。
- **原因**:`chatapp/config/settings.py` 在 `TESTING`(`sys.argv[1:2] == ["test"]`)分支下**不用 `REDIS_URL`**,而是读 `TEST_REDIS_HOST` / `TEST_REDIS_PORT`(默认 `127.0.0.1:6379`)重新拼地址,并强制切到 **DB15(缓存)/ DB14(broker)** 以免清库误伤开发数据。所以把 `REDIS_URL` 指到 16379 完全不起作用,测试照样去连 6379。
- **处置**:Redis 不在 6379 时(CI 容器在 16379)把两个变量**一起**指过去:`export TEST_REDIS_HOST=127.0.0.1 TEST_REDIS_PORT=16379`。`scripts/verify.sh backend` 已内置这对变量,并且连 `BROKER_URL` 一起对齐,别只改一半。

### 2. Windows 检出是 CRLF,WSL 的 git 会把全仓算成改动

- **现象**:校验生成物(OpenAPI / `schema.d.ts`)在 WSL 里永远红:`git diff --exit-code` 或 `git status` 把 **1094 个文件**都判成已改,哪怕你一个字节都没动、生成物也确实是刚生成的。
- **原因**:仓库在 Windows 上检出、以 CRLF 入库,`.gitattributes` **刻意**不做全局换行归一化(做了会制造一次全仓巨型 diff);而 WSL 里的 git 按 LF 读索引,于是每个文件都被判成「行尾变了」。`git diff --exit-code` 在 WSL 里等于恒红,和生成物对不对无关。
- **处置**:校验生成物要**比内容、忽略行尾**——两边都 `tr -d '\r'` 再去掉差异比较。`scripts/verify.sh` 的 `check_artifact()` 就是这么做的(`git show HEAD:<file> | tr -d '\r'` vs `tr -d '\r' < <file>`),失败时还会贴前 40 行 diff。不要把它退回 `git diff --exit-code`。

### 3. Node 必须是 22(与 `.github/workflows/web.yml` 一致)

- **现象**:`web/tests/unit/profile-store.spec.ts` 的「上传照片走 multipart」用例挂掉,断言里出现 `webidl.is.File`;其余用例全绿,而且没人动过那段业务代码。
- **原因**:那条用例跑 jsdom + undici,`File` 的 webidl 校验在 Node 24 上与 Node 22 行为不同;CI 钉的是 Node 22,所以这是 **jsdom/undici 的环境差异**,不是业务 bug(报错位置也不在你的代码里)。
- **处置**:`web` 一律用 **Node 22**。`scripts/verify.sh` 默认优先用 `$HOME/node22`,并校验 major(不对就报错退出,可用 `CHATAPP_NODE_MAJOR` 覆盖);安装方式见 [docs/ops/superagent.md](../ops/superagent.md)。**不要为此改用例或放宽断言。**

### 4. `/mnt/*` 上跑不了 `web` / `app`

- **现象**:在 `/mnt/c/...`、`/mnt/d/...` 下的克隆里跑 `npm run test:run`,vitest 直接起不来,报 `[vitest-pool]: Failed to start forks worker … Timeout waiting for worker to respond`;`flutter test` 同样慢到超时。看起来像用例红了,其实一条都没跑。
- **原因**:WSL 的 `/mnt/*` 是 9p 挂载,读 `node_modules`(几万个小文件)与 Flutter 缓存的延迟比 Linux 原生文件系统高一个数量级,worker 启动阶段就超时。
- **处置**:在 **Linux 文件系统上的克隆 / worktree** 里跑(工单 worktree 本来就在 `/root` 下)。`scripts/verify.sh web|app` 已内置 `assert_linux_fs()`:命中 `/mnt/*` 立即拒绝并给出提示,免得你等二十分钟才发现是环境。

## 前端(Flutter widget 测试)

- 脚手架:`test/support/harness.dart::pumpApp`(真实 provider + 假网络 + 假 IM,可传 `imClient:` 自定义);假网络按 `"METHOD path"` 铺响应,没铺的路由返回 404 提示你。
- ⚠️ **widget 测试里别裸 `await` 走 dio 的 provider**(如 `container.read(xxxProvider.future)`):假时钟不推进 dio 内部定时器,测试直接**死锁**(曾挂 7 分钟,连超时都不触发)。要么让调用发生在 widget 树里(靠 `pumpAndSettle` 推进),要么把 provider override 成目标状态(见 `chat_page_test.dart` 的 `_LoggedInImManager`)。
- ⚠️ **含无限动画的页面别 `pumpAndSettle`**(启动页转圈、倒计时、`HeartRipple` 涟漪、`AppSkeleton` 骨架、`BreathingDot` 在线点):永不 settle 会超时;用有限次 `pump`/`pumpFrames` 推进(见 `test/features/legal/agreement_gate_test.dart`),尾部 `await tester.pumpWidget(const SizedBox())` 卸载页面取消 Timer。
  - ⚠️ 注意 `IndexedStack`:**未选中的 Tab 也一直跑动画** —— 广场空态的 `HeartRipple` 会让「消息 Tab 角标」这类看似无关的用例 `pumpAndSettle` 超时(2026-10-12 实测)。
- ⚠️ **AppToast 的 2s 自动消失 Timer 会以 *A Timer is still pending* 弄挂用例**:触发过 Toast(删除成功/点赞失败/举报结果)的用例收尾必须 `await drainToast(tester)`(`test/support/harness.dart` 提供,pump 3s 推过超时点)。
- ⚠️ **`find.byX` 默认 `skipOffstage: true`**:被 push 盖住的路由(仍在树里)默认找不到;要检查它得显式传 `skipOffstage: false`。反过来,`CardHero`/`AvatarHero` 这类「tag 为 null 时只返回 child」的包装组件,判断是否真的参与 Hero 要看 `tag != null` 而不是 `find.byType`。
- ⚠️ **异步请求链中途界面停止调度帧时,`pumpAndSettle` 会提前静止**:它只在「有新帧被调度」时继续推进假时钟;若请求链里有平台通道/定时器步骤(如读凭证 `SharedPreferences`),而此刻界面恰好没动画(例:单卡滑出去后列表变空、卡组被空态替换),时钟不再前进、请求冻在半路(SnackBar 不出现,还报 *A Timer is still pending*)。修法:先 `pumpAndSettle()` 走完动画,**再 `pump(100ms)` 显式推一次时钟放行**,最后 `pumpAndSettle()` 收敛(见 `discovery_page_test.dart` 的「滑卡失败」用例)。
- ⚠️ 假网络对所有图片请求返回 400:网络图片必须自兜底(`Image.network(errorBuilder:)` / `CircleAvatar(onBackgroundImageError:)`),不兜底直接报错。
- ⚠️ **等真实 dio 往返别用固定 `Future.delayed`**:高负载(双套件并行)下必 flake;改条件轮询(见 `presence_controller_test.dart::waitFor`,10ms 步进、上限 1s,超时断言给出原因)。
- 有心跳/轮询定时器的页面:`heartbeatIntervalProvider` / `presenceRefreshIntervalProvider` 在 pumpApp 里默认 override 成 null(关掉定时器)。
- 断言请求顺序别用 `adapter.log.last`(自动续拉 GET 可能排在 POST 后),用 `lastWhere((r) => r.method == 'POST')`。
