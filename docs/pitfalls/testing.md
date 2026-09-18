# 踩坑手册 · 测试

> 索引见 [README.md](README.md)。测试纪律是硬要求:后端 `python manage.py test` 全绿、`flutter analyze` 零告警、每步全绿再进下一步。

## 后端(Django)

- 前置:本地 Redis 在跑(`docker compose -f docker-compose.dev.yml up -d`);测试自动用 DB15(缓存)/ DB14(broker),不碰开发数据。
- ⚠️ **测 `on_commit`**:`notify_match` / 登录后 `sync_login` / 拉黑/封禁/资料同步的入队都走 `transaction.on_commit`,测试必须 `with self.captureOnCommitCallbacks(execute=True):` 包住请求,否则断言永远不触发。
- ⚠️ **测试里 Celery 任务只入队、不执行**(无 worker):断言「入队了什么」用 `patch("im.tasks.ban_notice.delay")` / `patch("im.tasks.sync_profile.delay")` 之类;要测任务体直接 `task.run(...)`,此时 mock `im.client.*`,腾讯 REST 一次都不能真打。
- ⚠️ **凡会触发 IM 调用的用例都要 mock**:漏 mock 会真打腾讯云(用例仍绿,因为业务函数吞异常——靠跑测试时日志里有没有 `IM ... 返回错误` 发现),且变慢、依赖网络。
- ⚠️ 限流用例要 `cache.clear()`:计数在 Redis,跨用例残留会导致偶发 429(DB15 与开发 DB0 隔离,clear 不误伤)。

## 前端(Flutter widget 测试)

- 脚手架:`test/support/harness.dart::pumpApp`(真实 provider + 假网络 + 假 IM,可传 `imClient:` 自定义);假网络按 `"METHOD path"` 铺响应,没铺的路由返回 404 提示你。
- ⚠️ **widget 测试里别裸 `await` 走 dio 的 provider**(如 `container.read(xxxProvider.future)`):假时钟不推进 dio 内部定时器,测试直接**死锁**(曾挂 7 分钟,连超时都不触发)。要么让调用发生在 widget 树里(靠 `pumpAndSettle` 推进),要么把 provider override 成目标状态(见 `chat_page_test.dart` 的 `_LoggedInImManager`)。
- ⚠️ **含无限动画的页面别 `pumpAndSettle`**(启动页转圈、倒计时):永不 settle 会超时;用有限次 `pump` 推进(见 `test/features/legal/agreement_gate_test.dart`),尾部 `await tester.pumpWidget(const SizedBox())` 卸载页面取消 Timer。
- ⚠️ 假网络对所有图片请求返回 400:网络图片必须自兜底(`Image.network(errorBuilder:)` / `CircleAvatar(onBackgroundImageError:)`),不兜底直接报错。
- ⚠️ **等真实 dio 往返别用固定 `Future.delayed`**:高负载(双套件并行)下必 flake;改条件轮询(见 `presence_controller_test.dart::waitFor`,10ms 步进、上限 1s,超时断言给出原因)。
- 有心跳/轮询定时器的页面:`heartbeatIntervalProvider` / `presenceRefreshIntervalProvider` 在 pumpApp 里默认 override 成 null(关掉定时器)。
- 断言请求顺序别用 `adapter.log.last`(自动续拉 GET 可能排在 POST 后),用 `lastWhere((r) => r.method == 'POST')`。
