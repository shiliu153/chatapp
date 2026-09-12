# 聊天页 / 资料页微信式改版 + IM 昵称同步 设计

日期:2026-09-12
状态:已与用户逐节确认,待写实施计划
上游文档:测试栈与现有结构见 `specs/2026-09-09-dating-app-mvp-design.md`;聊天现有实现见 `plans/2026-09-10-m2c-im-chat.md`;消息页抖音式版式见 `specs/2026-09-11-ban-notice-message-page-design.md`
视觉决策:经浏览器模拟图(本机 `.superpowers/brainstorm/7075-1789180323/`,仅本地参考不提交)逐项确认

## 1. 背景与目标

1. **修一个手测发现的 bug**:用户 7(Alice)举报并拉黑用户 9(test)后,test 端会话里 Alice 的名字降级成裸 IM id「u7」。
   根因链:拉黑双向不可见 → `GET /matches` 过滤 → 前端 `matchCache` 失去该人 → 降级到「IM 会话名」这一级时,IM 侧昵称**从来就是空的**(注册导入 `import_account` 没传昵称)→ 掉到最底级裸 id。
   → 正式修法:**IM 昵称同步**(§5),修源头,换机/重装/重启都不掉名。
2. **三页改微信式呈现**:聊天页、我的页、别人的资料页 = 微信版式 + 保留品牌粉色调(用户明确:格式用微信的,色调用我们的粉)。
3. **补齐微信对应而 App 未实现的功能**:聊天页 7 项(头像气泡/时间分组/长按菜单/发图片/表情面板/＋面板/失败重发),资料页 4 项(两页行版式、ID 行、相册大图、举报拉黑收进「···」菜单)。

## 2. 范围

**做**:上述三页 + 7+4 项功能 + IM 昵称同步(含存量补数命令)。

**不做**(已与用户确认):
- 语音消息(重,不排期);输入栏**不放**语音按钮
- 已读回执(微信本身没有,不符风格)
- 微信式「微信号」自定义、二维码、备注名、朋友权限
- **消息页(会话列表)不动**:它上一轮已按抖音式定稿(圆形头像等),本轮只间接受益于昵称同步

## 3. 视觉规范(已确认)

| 项 | 值 |
|---|---|
| 总体 | 布局结构照微信;色板用品牌粉 |
| 自己的气泡 | 品牌粉 `#FF2C55` + 白字;靠头像角 2px 圆角,其余 10px |
| 对方气泡 | 白底深字 `#26282C`,对称圆角 |
| 聊天页背景 | 浅粉灰 `#F7F3F5` |
| 头像 | 方形圆角(微信式):聊天页 40px/圆角 6;资料页头部 56px/圆角 8。无图时昵称首字占位 |
| 资料行 | 左=项名(固定列宽),紧跟左对齐的取值,`›` 固定最右;头像行的小头像仍在行内右侧 |
| ID 展示 | 用户 ID 加 `u` 前缀(如 `u7`),与现有 `deleteConversation('u$id')` 约定同源 |
| 灰条 | 配对成功/封禁通知的居中灰条渲染保持现状,只换页面外框 |

## 4. 聊天页设计

### 4.1 结构与组件

- `chat_page.dart` 重构:顶栏(名字居中、右侧「···」→对方资料页)、消息列表、输入栏
- `widgets/message_bubble.dart` 扩展:头像 + 气泡两栏布局;新增图片消息分支;失败态角标。灰条分支不动
- 新增 `widgets/emoji_panel.dart`(表情网格)、`widgets/more_panel.dart`(＋面板)、`widgets/photo_viewer.dart`(全屏看图,与资料页相册共用)
- 时间分组逻辑抽成**纯函数**(便于单测):输入消息列表 → 输出「消息/时间条」混合项

### 4.2 时间分组

- 相邻消息间隔 > 5 分钟(以及列表第一条)插居中灰条
- 格式:今天 `HH:mm` / 昨天 `昨天 HH:mm` / 本年内 `M月d日 HH:mm` / 跨年 `yyyy年M月d日 HH:mm`
- 实现放 `core/format.dart`(现有 `formatMessageTime` 旁),配单测

### 4.3 长按菜单

- 文本消息:复制(Clipboard + SnackBar「已复制」)/ 删除(本机)
- 图片消息:删除(本机)
- 删除走 SDK 删本地消息,「本机」语义与微信一致(对方不受影响)

### 4.4 输入栏 / 表情 / ＋

- 输入栏:`[输入框][😊][＋]`
- 😊:收起键盘、在输入栏下方弹出约 40 个常用 emoji 网格;点选插入光标处;点输入框切回键盘
- ＋:弹出面板(当前仅「相册」一个入口,预留扩展位)

### 4.5 图片消息

- 选图:复用现有 `pickImageFromGallery()` 的压缩参数思路(maxWidth 1080 / quality 85,`profile/widgets/photo_grid.dart` 已有注入式 `PickImage` 测试模式,照搬)
- 发送:走腾讯 IM SDK 图片消息(SDK 负责上传/下载/缩略图),不自建上传通道
- 展示:发送中显示本地文件;成功后显示远程图;失败走 §4.6
- 查看:点图片进全屏查看器(黑底、可左右滑、双指缩放、点关)

### 4.6 发送状态与重发

- 现状:发送失败把消息整个撤掉 + SnackBar(`chat_controller.dart:58`)
- 改为:失败保留消息,气泡旁红色叹号,点叹号重发;发送中半透明(现有 `isPending` 语义保留)
- 该 SDK 版本(9.0.7652+1)**无原生重发 API**(已核实):重发实现 = 移除本地失败消息 + 用原内容重新发送,文本与图片行为等价

### 4.7 IM 抽象层扩展

- `ChatMessage`:`kind` 加 `image`;新增 `localPath`/`imageUrl`(展示优先 localPath)、`isFailed`
- `ImClient` 新增:`sendImage(peerId, imagePath)`、`deleteMessage(message)`、`resend(message)`
- `tencent_im_client.dart`(全项目唯一 import SDK 的文件)做映射:`sendImage` 走 `createImageMessage`(SDK 负责上传);`localPath` ↔ `V2TimImageElem.path`(SDK 约定发送时用于提前上屏);`imageUrl` ← `V2TimImageElem.imageList` 的远程 URL;`test/support/fake_im_client.dart` 同步补齐假实现
- 纪律不变:仿真 SDK 只在手测/真机跑;widget 测试只跑 fake

### 4.8 头像来源

- 对方:`matchCache` 的 `avatarUrlFor`(现有);自己:我的资料里的头像(`Profile.avatar`,首个过审照片);均无图 → 首字占位

## 5. 名字兜底:IM 昵称同步(修源头)

### 5.1 后端新增 `im/client.py::set_profile_nick(identifier, nickname)`

- 腾讯 REST `profile/profile_set_field`,administrator 身份,`Tag_Profile_IM_Nick`
- 对外永不抛异常,失败返回 False 只记日志(与现有函数同一纪律)

### 5.2 触发点

- `users/views.py::me` 的 PATCH 分支:昵称**实际发生变化**时,后台线程同步到 IM(线程模式与 `discovery/services.py::_notify_async` 一致,不阻塞响应)
- 注册时昵称尚不存在(引导流程里才填),故注册导入不带昵称,由本条覆盖

### 5.3 存量补数命令

- 新增管理命令 `im_sync_nicknames`:遍历有昵称的用户逐个同步,幂等,输出成功/失败计数;失败只记日志
- 开发库需跑一次(u7=Alice、u8=Bob、u9=test);生产环境首启记入 M4 清单

### 5.4 前端降级链补齐

- `chat_page.dart` 标题:当前 `displayNameFor(cache, peerId)` **没传 imName**,补上从 `conversationsProvider` 取该 peer 的 `showName`,与消息页 `chats_page.dart` 用法一致
- `im_client.dart` 里「我们没给 IM 设资料,通常是空的」注释随之更新
- 验收:拉黑后会话名仍为真名;改名后另一端重进会话可见新名

## 6. 我的页(my_profile_page.dart)设计

- 改微信「个人信息」分组行:
  - 组 1:头像(行内右侧小方图)/ 昵称 / ID(`u${Profile.id}`)/ 性别(显示映射 男/女)/ 生日 / 城市 / 简介 / 标签
  - 组 2:想找的人 / 设置
- 每行点按 → `/profile/edit`(编辑资料页承载所有编辑);「编辑资料」独立入口删除
- 「资料未完善」提醒条保留在顶部(现逻辑不动)
- 数据源不变(`profileProvider`);不新增接口

## 7. 别人的资料页(user_profile_page.dart)设计

- 顶栏:「详细资料」+ 右上角「···」→ PopupMenu(举报 / 拉黑),复用现有 `_report`/`_block` 流程与确认弹窗;底部两个大按钮删除
- 头部:方形头像 + 昵称·年龄 + `ID:u${userId}`
- 资料行:地区 / 个性签名 / 标签
- 「相册」:现有照片三列网格,点开全屏查看器(与聊天页共用 `photo_viewer.dart`)
- 404(不存在/被封禁/有拉黑关系)错误态与「重试」保留
- 数据源不变(`userProfileProvider`);不新增接口

## 8. 测试与验收

**后端新用例**
- `set_profile_nick`:载荷正确、错误码/网络异常返回 False 不抛
- PATCH 昵称触发同步(mock 线程函数;断言仅在昵称变化时触发)
- `im_sync_nicknames`:幂等、跳过无昵称用户、失败计数

**前端新用例(widget/单元)**
- 气泡+头像两栏布局(自己/对方/无图占位)
- 时间分组纯函数:边界(5 分钟整)、跨天/昨天/跨年
- 长按:复制断言剪贴板、删除断言列表移除
- emoji 面板:点选插入输入框
- ＋面板:注入假 picker → 断言 `sendImage` 调用与图片气泡出现(网络图沿用 `errorBuilder` 兜底纪律)
- 失败重发:fake 先失败后成功,断言叹号出现与重发后正常
- 聊天页标题:无缓存时有 `showName` 用 `showName`,全无才落裸 id
- 我的页:行值渲染(含 ID 行 `u7`)、点行跳转
- 别人的资料页:「···」菜单两个动作、相册点开查看器

**手测清单(双模拟器)**
图文互发与接收、全屏看图、长按复制/删除、跨天时间条、飞行模式失败→点叹号重发、拉黑后会话名仍为真名、改名后另一端可见新名、我的页行版式与跳转、别人资料页相册/···菜单

**回归口径**
- 后端 190+ 与前端 120+ 全量测试绿、`flutter analyze` 零告警
- **无数据库迁移**;消息页(会话列表)UI 零改动(仅 `im_client.dart` 里的注释)

## 9. 风险与边界

- **腾讯昵称生效**:`profile_set_field` 后对端会话名的刷新依赖 IM 推送/重拉,以手测为准;同步失败不影响任何业务链路(仅记日志),名字前端还有 matchCache 与 IM 会话名两级兜底
- **图片消息内容安全**:走腾讯 IM 通道,依赖腾讯侧内容审核能力,生产前在 IM 控制台开启(M4 清单)
- **长按删除语义**:只删本机,不做双向删除(与微信一致)
- **测试纪律沿用**:fake 与真 SDK 分离;含网络图的用例必须兜底
