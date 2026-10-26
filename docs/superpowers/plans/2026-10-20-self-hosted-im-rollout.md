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

- [ ] `MIN_APP_VERSION` 已生效,旧版本被阻塞页挡住
- [ ] 图片二期已交付(否则不做全量)
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

**遗留(不影响门槛判定)**:客户端「下次登录拿腾讯引导包」这一段没在真机验证——服务端已切对,
App 端要按返回的 `backend` 换 SDK,需要在模拟器上点一次(与灰度三项的 UI 侧一起验)。

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
