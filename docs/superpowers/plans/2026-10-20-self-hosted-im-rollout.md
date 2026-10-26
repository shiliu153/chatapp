# 自建 IM 灰度与回退核对单

日期:2026-10-20 · 对应设计:`docs/superpowers/specs/2026-10-20-self-hosted-im-design.md`

> **2026-10-22 已在生产服务器完成部署**(容器形态),勾选项为当日实测;
> 未勾选项是「还没验」,不是「验过失败」。

## 前置

- [x] 服务器已部署 imserver(`imserver:ea8a91d` 容器,`IM_BACKEND=self`)
- [x] `curl http://127.0.0.1:9101/internal/healthz` 返回 200
- [x] MySQL 库 `chatapp_im` 已建,`imserver --migrate` 成功
- [x] Nginx `/im/ws` 与 `/im/api/` 反代通过,`X-Real-IP` 已设置
- [x] Django `.env` 的 `IM_SELF_SECRET` 与 `IM_JWT_SECRET` 一致,
      `IM_SELF_INTERNAL_SECRET` 与 `IM_INTERNAL_SECRET` 一致
- [x] App/Web 新版本已带双后端实现(仓库 `ea8a91d`;客户端发版另计)

## 隔离测试号灰度

- [x] `IM_SELF_GRAYLIST` 只填测试号(`7,8`,即 13300133001/13300133002)
- [x] 双端登录:两端都拿到 `backend=self`
- [x] 互发文本、离线补拉(未读数正确)、已读清零
- [x] 2 分钟内撤回双方变灰;超时撤回失败
- [x] 同账号第二处登录,第一处被踢并强退
      (2026-10-26 脚本验:`kicked{reason=multi_device}` + 关闭码 4001;第二处仍可 ping)
- [x] 封禁后重连被拒,解封后恢复
      (2026-10-26 脚本验:在线连接收 `kicked{banned}`+4001;重连 `error 40301`+4003;
      解封后 `auth_ok`)
- [x] 拉黑后发送失败,解除后恢复
      (2026-10-26 脚本验:拉黑后 `error 40302` 且对端零投递;解除后 ack + 对端收到)
- [x] 配对/封禁/举报/评论灰条都能收到(服务端 `/internal/send` 投递已验证;
      客户端展示待手测)
- [x] 非灰度账号(如 13900000001)仍返回 `backend=tencent`,现网零影响

## 全量切换

- [x] 最小版本拦截**机制**已双端验证(2026-10-26:App 与 Web 都被阻塞页挡住,见下节)
- [ ] `MIN_APP_VERSION` 生产值仍是默认 `1.0.0`(`.env` 未配置)→ **实际挡不住任何旧版本**,
      切换前必须按发版版本填,并配 `LATEST_APP_VERSION` / `APP_DOWNLOAD_URL`
- [x] 图片二期已交付(2026-10-26:上传接口 `POST /im/images` + 缩略图 + EXIF 校正;
      imserver `kind=3` + `IM_MEDIA_PREFIX` 前缀校验;App/Web `sendImage`;ops `/ops/chat-images/` 抽审;
      **注意 `IM_MEDIA_PREFIX` 是必填项,部署时要与 Django 的 `MEDIA_BASE_URL` 对齐**)
- [x] 历史迁移完成,或产品书面确认接受「切换点之前不可见」
      (2026-10-26 用户确认:测试阶段,现有用户历史聊天记录可以直接移除,
      不做腾讯侧导出/导入;切换后只保留 `chatapp_im` 里的新消息)
- [x] 500 连接压测 p99 < 200ms、RSS < 300MB
      (2026-10-22:500 连接 / 50 msg/s 公网经 nginx,p99 93ms、RSS 22MB;
      1000 条瞬时突发 4.7s ≈ 215 msg/s,已是 2C2G 上限)
- [ ] 切换日 `IM_SELF_GRAYLIST=all`,观察 30 分钟:
      消息成功率、ack 延迟、断线率、`docker compose logs imserver` 无 ERROR 尖峰

## 回退

- [x] `IM_BACKEND=tencent` → 重启 gunicorn
      (2026-10-26 演练:`sed` 改 `.env` + `supervisorctl restart 'chatapp-web:*'`;
      `/im/user_sig` 从 `backend=self` 变 `backend=tencent` 并带出真实 `user_sig`)
- [x] 让用户重启 App(下次登录拿腾讯引导包)
      (演练只验服务端契约;客户端切换需真机/模拟器点一次,见「遗留」)
- [x] 如需立刻止血:先 `docker compose stop imserver`,再改配置、重启 App
      (演练按此顺序执行;停机时 `/im/api/*`、`/im/ws` 实测都是 **502**,不是 401)
- [x] 自建库保留;回退期间的消息腾讯侧不可见,产品已知情
      (演练后 `im_message` 行数不变 = 7,数据未丢;产品确认见上方历史消息项)

**演练暴露的两个坑(已写进 `docs/ops/imserver.md` §4)**:

1. supervisor 程序名要带组前缀:`chatapp-web` 会报 `no such process`,必须 `chatapp-web:*`;
   写错时 `.env` 已改、进程未重载,会留下「imserver 已停 + 后端仍按 self 跑」的空窗(约 2 分钟)。
2. **只重启 gunicorn 不够**:Celery 也缓存 `IM_BACKEND`,灰条/系统通知等异步副作用仍走旧后端,
   必须一起重启 `chatapp-celery:*`。

**遗留(不影响门槛判定)**:~~客户端「下次登录拿腾讯引导包」没在真机验证~~ ——
2026-10-26 已补:切 `tencent` 后 App 重启登录,消息页空态且无错误;恢复 `self` 后历史回来
(见上表最后一行)。

## 2026-10-26 客户端与配置核验(P0 收尾)

| 项 | 做法 | 结果 |
|---|---|---|
| Web 构建是否最新 | 检查 `/www/wwwroot/chatapp-web` | ❌ **仍是 10-12 的产物**,不含版本拦截与自建 IM;已用当日 `master` 重新构建部署(旧目录备份为 `chatapp-web.bak.20261026`) |
| 根路径白屏 | 登录态访问 `http://<IP>/` | ❌ 路由表没有 `/`,守卫放行后 `RouterView` 空白;已补 `redirect → home` + 单测(`6a15a65`),重新部署后验证:未登录 → `/login`,已登录 → `/home/discovery` |
| 最小版本拦截(App) | 服务器临时 `MIN_APP_VERSION=9.9.9` → 重启 web → 冷启 App | ✅ 显示「需要更新后才能继续使用 / 当前版本 1.0.0,最低要求 9.9.9」 |
| 最小版本拦截(Web) | 同上,刷新页面 | ✅ 显示强制更新页 |
| 配置恢复 | 还原 `.env` 并重启 | ✅ `/app/config` 回到 `1.0.0`;App 重启后正常进登录页 |
| Web 自建 IM | 测试号 7 登录 → 消息页/会话 | ✅ `/im/user_sig` 返回 `backend=self` + `token`;`/im/api/conversations` 200;聊天页输入栏无图片按钮 |
| App 自建 IM | 模拟器装当日 debug 包(API 指向生产)登录测试号 7 | ✅ 进发现页,WS 连接建立(服务端 `online=1`) |
| 被踢提示(App) | 服务端 `/internal/kick` 踢 uid=7 | ✅ 回到登录页并提示「账号已在其他设备登录,请重新登录」 |
| 被踢提示(Web) | App 登录同一账号顶掉 Web | ✅ 全屏 `alertdialog`「账号已在其他设备登录」+「重新登录」 |
| 回退到腾讯(客户端侧) | `IM_BACKEND=tencent` + 重启 web/celery → App 重启登录测试号 7 → 恢复 `self` 再重启 | ✅ 腾讯下消息页为空态(自建历史不可见,符合预期)、无错误态;恢复后会话与历史全部回来 |

**同批发现(不属 IM,但影响上线)**:

1. **`SMS_DEV_MODE` 在生产是开的**:`.env` 没写这个键,而 `settings.py` 默认 `1`
   → 验证码固定 `123456`,登录页还直接把「开发模式:验证码固定 123456」显示给用户。
   **这是上线阻断项**,必须显式写 `SMS_DEV_MODE=0`(改完重启 web + celery)。
2. `MIN_APP_VERSION` / `LATEST_APP_VERSION` / `APP_DOWNLOAD_URL` 都没配,
   版本门槛形同虚设(见上节)。
3. 封禁踢线时服务端发的 `kicked.reason="banned"`,但两端都按「其他设备登录」提示;
   重封禁用户下一次拉 `/users/me` 才会看到封禁页。属提示文案问题,已记入待办,不挡切换。
4. **聊天图片没有机器审核**(2026-10-26 图片二期交付时确认):上传即发,靠 ops 人工抽审
   + 举报/拉黑兜底。接云内容安全(异步审核)前,列为**上线阻断项**;图片 URL 也是公开可访问的
   (`/media/chat/` 随机文件名不可枚举),后续可升级为签名 URL。


## 部署记录

| 日期 | 内容 | 结果 |
|---|---|---|
| 2026-10-22 | 服务器建 `chatapp_im` + `imserver` 账号;容器加载镜像 `imserver:ea8a91d`;`--migrate` 到 schema v1 | ✅ |
| 2026-10-22 | Nginx 站点加 `/im/ws`、`/im/api/`,外网 401 JSON、WS 40101/4002 均符合契约 | ✅ |
| 2026-10-22 | 后端代码从 `74fe893` 同步到 `ea8a91d`(git bundle,含自建 IM 与 P1 功能);迁移 3 个,`readyz` 绿 | ✅ |
| 2026-10-22 | 灰度 7/8 端到端:auth_ok → 发消息 ack → 对端 message → 历史 → 已读 → 撤回 → 离线补拉 → 未读 1 | ✅ |
| 2026-10-22 | 容器重启后数据保留(`im_message` 3 行),`readyz` 绿;`docker` 开机自启已 enable | ✅ |
| 2026-10-22 | 500 连接压测:稳态 50 msg/s 经 nginx p99 93ms / RSS 22MB;冷启动 1000 条突发 0 失败 | ✅ |
| 2026-10-22 | 压测修复:`im_user` 改为缓存 + SELECT 优先(消除 115ms 间隙锁);发送事务对 1213/1205 重试 3 次 | ✅ |
| 2026-10-26 | **事故**:MySQL `wait_timeout`(8h)掐掉池内空闲连接,池不校验存活 → 自 10-22 晚起 `readyz` 503、发消息 50001、`/internal/blacklist` 422,持续约 3 天(仅灰度测试号 7/8,无真实用户)。重启容器即恢复 | ⚠️ |
| 2026-10-26 | **修复**:`MysqlPool::acquire()` 空闲 ≥ `IM_DB_IDLE_PING_MS`(默认 5000)先 ping、失败重连;`Lease::query()` 遇 2006/2013/2055 丢弃连接;`WsSession::run_db()` 兜住 DB 线程池异常。新增 DB 测试 `PoolReconnectsAfterServerKill` | ✅ |
| 2026-10-26 | 灰度三项脚本化验证(`imserver/scripts/verify_graylist.py`,17 条断言全过):互踢/封禁拒连/拉黑拦截 | ✅ |

## 回退演练记录

| 日期 | 执行人 | 结果 | 备注 |
|---|---|---|---|
| 2026-10-26 | Claude(用户授权) | ✅ 通过 | 完整走一遍「止血 → 切腾讯 → 恢复」:①`docker compose stop imserver`,外部 `/im/api/*`、`/im/ws` 均 502;②`IM_BACKEND=tencent` + 重启 `chatapp-web:*`,`/im/user_sig` → `backend=tencent` + 真实 userSig;③恢复 `IM_BACKEND=self` + 起容器 + 重启两个进程,`readyz` 200、`/im/user_sig` → `backend=self`、`im_message` 行数不变(7→8,新增的是恢复后灰度脚本自己发的那条)、`verify_graylist.py` 17/17 全过。影响面:仅灰度测试号 7/8,约 5 分钟不可聊;无真实用户。发现两个坑:supervisor 程序名要带 `:*`;Celery 必须一起重启 |
