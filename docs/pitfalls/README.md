# 踩坑手册(索引)

> 沉淀自 M0–M4 的实测坑。**写代码 / 排障前,先读对应主题的这一份**,每条含现象/根因/处理。
> 服务器部署与运维的坑不在这里 → 见 [`../deploy-runbook.md`](../deploy-runbook.md)。

| 主题 | 文件 | 什么时候读 |
|---|---|---|
| 腾讯云 IM 全栈(userSig / REST / SDK / 踢人 / 消息类型 / 聊天 UI) | [im.md](im.md) | 动 IM、聊天、消息页、单设备登录相关 |
| 前端 Flutter / Riverpod | [frontend.md](frontend.md) | 改 App UI、状态管理、卡片流、广场前端、构建环境 |
| 后端 Django / 接口 / 数据 | [backend.md](backend.md) | 改接口、模型、任务、限流、合规、feed、presence |
| 模拟器与 Android 构建 | [android-emulator.md](android-emulator.md) | 跑模拟器手测、打 APK、模拟器排障 |
| 测试 | [testing.md](testing.md) | 写 / 跑前后端测试 |
| 部署与运维 | [`../deploy-runbook.md`](../deploy-runbook.md) | 部署、更新服务器、看日志、服务器排障 |

另:设计与计划在 `docs/superpowers/{specs,plans}/`;UI 规范在 `specs/2026-09-15-ui-design-language-design.md`(强制);接口文档在 [`../api/README.md`](../api/README.md)。
