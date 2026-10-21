# 自建 IM 灰度与回退核对单

日期:2026-10-20 · 对应设计:`docs/superpowers/specs/2026-10-20-self-hosted-im-design.md`

## 前置

- [ ] 服务器已部署 imserver,`IM_BACKEND=tencent`(对现网零影响)
- [ ] `curl http://127.0.0.1:9101/internal/healthz` 返回 200
- [ ] MySQL 库 `chatapp_im` 已建,`imserver --migrate` 成功
- [ ] Nginx `/im/ws` 与 `/im/api/` 反代通过,`X-Real-IP` 已设置
- [ ] Django `.env` 的 `IM_SELF_SECRET` 与 `IM_JWT_SECRET` 一致,
      `IM_SELF_INTERNAL_SECRET` 与 `IM_INTERNAL_SECRET` 一致
- [ ] App/Web 新版本已带双后端实现

## 隔离测试号灰度

- [ ] `IM_SELF_GRAYLIST` 只填测试号(测试号之间互聊,不与真实用户配对)
- [ ] 双端登录:两端都拿到 `backend=self`
- [ ] 互发文本、离线补拉(未读数正确)、已读清零
- [ ] 2 分钟内撤回双方变灰;超时撤回失败
- [ ] 同账号第二处登录,第一处被踢并强退
- [ ] 封禁后重连被拒,解封后恢复
- [ ] 拉黑后发送失败,解除后恢复
- [ ] 配对/封禁/举报/评论灰条都能收到

## 全量切换

- [ ] `MIN_APP_VERSION` 已生效,旧版本被阻塞页挡住
- [ ] 图片二期已交付(否则不做全量)
- [ ] 历史迁移完成,或产品书面确认接受「切换点之前不可见」
- [ ] 500 连接压测 p99 < 200ms、RSS < 300MB
- [ ] 切换日 `IM_SELF_GRAYLIST=all`,观察 30 分钟:
      消息成功率、ack 延迟、断线率、`journalctl -u imserver` 无 ERROR 尖峰

## 回退

- [ ] `IM_BACKEND=tencent` → 重启 gunicorn
- [ ] 让用户重启 App(下次登录拿腾讯引导包)
- [ ] 如需立刻止血:先 `systemctl stop imserver`,再改配置、重启 App
- [ ] 自建库保留;回退期间的消息腾讯侧不可见,产品已知情

## 回退演练记录

| 日期 | 执行人 | 结果 | 备注 |
|---|---|---|---|
|  |  |  |  |
