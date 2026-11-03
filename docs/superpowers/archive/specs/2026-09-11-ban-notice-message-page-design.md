# 封禁系统消息 + 消息页改版设计

日期:2026-09-11
状态:已与用户逐节确认(方案 A、两节设计、模拟图版式 A),待用户终审
上游:M3 合规(`specs/2026-09-11-m3-compliance-design.md`)、运营台(`specs/2026-09-11-moderation-console-design.md`)
背景:用户要求 —— ①账户被封禁后由系统发一条消息说明封禁原因 + 封了什么;②App 底部「会话」改称「消息」,消息列表做成抖音式(用户选定模拟图版式 A:头像横滑条 + 系统通知置顶 + 抖音风列表)。

## 1. 目标与范围

1. **封禁系统消息**:轻封/重封/解封时,后端自动以「系统通知」身份给用户发一条 IM 消息,说明原因与影响范围。
2. **消息页改版**:底部 tab「会话」→「消息」;消息页重构为抖音式版式 A(页头大标题 + 最近联系人横滑条 + 「系统通知」置顶行 + 抖音风会话行)。
3. **重封禁页补充说明**:整屏封禁页加一行「封禁期间所有功能暂停使用」(重封禁期间消息页不可达,这是他们唯一能看到的「封了什么」)。

**非目标(YAGNI):** 搜索入口(没有搜索功能,不放死按钮)、在线状态小绿点(无在线数据)、聊天页内部改版(气泡/灰条保持现状)、消息页深色模式、系统通知会话被删后的特殊处理、定时消息/批量运营推送。

## 2. 封禁消息:发送链路(方案 A:IM 系统账号)

复用配对灰条(`match_notice`)的全套机制:**固定 IM 账号 + TIMCustomElem + App 拦截渲染**。

### 2.1 系统账号

- 固定账号 `system_notice`,昵称「系统通知」。常量放 `chatapp/im/client.py`:`SYSTEM_NOTICE_IDENTIFIER = "system_notice"`、`SYSTEM_NOTICE_NICK = "系统通知"`。
- `client.py` 新增 `ensure_account(identifier, nickname) -> bool`:调用腾讯建号,**ErrorCode 0(新建)或 7015(已存在)都视为成功**,其余错误记日志返回 False。
- 新增管理命令 `im_setup_system_account`(im app):调 `ensure_account` 建系统账号,成功打印就绪、失败以 CommandError 退出(便于部署脚本发现);可重复执行。开发/生产各跑一次,生产步骤记入 CLAUDE.md。

### 2.2 发送函数(`chatapp/im/client.py`,与 `send_match_notice` 同层,失败只记日志返回 False)

- `send_ban_notice(to_identifier, level, reason)`:`From=system_notice`,Data `{"type":"ban_notice","level":"light"|"heavy"}`,Desc 文案:
  - 轻度:「您的账号因「{原因}」被限制。限制期间无法使用滑卡功能,聊天、资料等其他功能不受影响。如有疑问请联系客服。」
  - 重度:「您的账号因「{原因}」已被封禁。封禁期间所有功能暂停使用,如有疑问请联系客服。」
  - 原因为空(admin 渠道可不填)→ 兜底「违反社区规范」
- `send_ban_lifted(to_identifier)`:Data `{"type":"ban_lifted"}`,Desc:「您的账号限制已解除,所有功能已恢复。请遵守社区规范。」

### 2.3 触发钩子(`chatapp/moderation/services.py::log_ban_change`,admin 与 /ops/ 唯一公共入口)

| 状态变化 | 后台线程派发 |
|---|---|
| → banned_light | `send_ban_notice(im_user_id, "light", reason)` |
| → banned_heavy | `_send_notice_then_kick(im_user_id, reason)`:同一线程**先发消息、后踢下线**(保证顺序) |
| 封禁 → 非封禁 | `send_ban_lifted(im_user_id)` |
| 非封禁态互转 | 无(现状不变) |

失败策略沿用现有约定:IM 抖动只记日志,绝不回滚封禁动作。重封禁用户被封期间消息页不可达,该消息留档、解封后可见(用户已确认接受)。

## 3. 消息页改版(抖音式,版式 A)

参考浏览器模拟图(会话产物,未入库)。只改消息页,不动聊天页内部。

- **页头**:「消息」大标题(左对齐加粗 20px)替代 Material AppBar;不放搜索图标。
- **最近联系人横滑条**:取现有会话数据前 10 个(不含系统通知);圆头像(优先 `avatarUrlFor` 缓存头像,缺省用昵称首字圆底)+ 昵称小字;点按 `context.push('/chat/{peerId}')`;无会话时整条隐藏。
- **「系统通知」置顶行**:会话中 `peerId == system_notice` 的那条拆出、固定置顶(浅蓝底铃铛头像 + 「官方」蓝色小标 + 预览 + 红色角标),下接 8px 浅灰间隔条,不在下方列表重复出现。
- **会话行抖音化**:48px 圆头像 / 昵称 15.5 加粗 / 预览 13 灰 `#8a8f98` / 右侧时间小号 `#9aa0a8` + 红色数字角标 `#FF2C55` / 行高约 70 / 全宽细分割线。底部导航的未读角标同步用同款红。
- **空态**:「还没有消息 / 互相喜欢之后就能开聊了」。

## 4. 前端消息映射与呈现

- `ChatMessageKind` 增加 `banNotice`(覆盖 `ban_notice` 与 `ban_lifted`);`tencent_im_client.dart::_kindOf` 识别 custom 消息 `type` 为 `ban_notice`/`ban_lifted` → `banNotice`,文案取 `customElem.desc`(与 match_notice 同手法)。
- `message_bubble.dart`:`banNotice` 走现有居中灰条分支(不新造视觉;长文案自动折行)。
- 消息列表预览:banNotice → 最后一条文案(空则「系统通知」)。
- 显示名兜底:`match_cache.dart::displayNameFor` 特判 `peerId == system_notice` → 「系统通知」(SDK 会话名拿不到时不裸奔成 id);常量 `systemNoticePeerId` 放 `im_client.dart`(与后端字符串是跨栈契约)。
- **封禁页**(`banned_page.dart`):「账号已被封禁 / 原因:xxx」后加一行「封禁期间所有功能暂停使用」。

## 5. 改名

用户可见文案 3 处(内部类名/路由/注释不动):
- `home_shell.dart` 底部 tab「会话」→「消息」
- `chats_page.dart` 页头「会话」→「消息」(§3 改版后为新页头)
- `chats_page.dart` 空态「还没有会话」→「还没有消息」

## 6. 测试与验证

**后端**(预计 +8~10 个用例,全量 180 保持全绿):
- `send_ban_notice`/`send_ban_lifted` payload:From/To、Data type/level、Desc 文案、原因空兜底
- `log_ban_change`:轻封→发通知;重封→先发后踢;解封→解除通知;既有 2 个断言用例同步更新
- `_send_notice_then_kick`:顺序(先发消息再踢)
- `im_setup_system_account` / `ensure_account`:建号 payload;7015(已存在)视为成功;其余错误返回 False / CommandError

**Flutter**(预计 +5~8 个用例,全量 115 保持全绿,analyze 零告警):
- ban_notice/ban_lifted → kind 映射 + 灰条渲染(文案取 Desc)
- 消息页:系统通知置顶行、横滑条、空态、改名后既有用例更新
- 显示名特判 system_notice

**手测**(模拟器 + /ops/ 操作):
1. 轻封 Bob → Bob 端消息页出现「系统通知」置顶行(红点)→ 点开见灰条文案 → 滑卡被拒、聊天仍通
2. 重封 Bob → 被踢下线、整屏封禁页多一行「封禁期间所有功能暂停使用」
3. 解封 Bob → 登录后收到「限制已解除」消息
4. 双端回归:正常聊天/配对不受影响;消息页版式与模拟图一致

## 7. 关键决策记录

- 投递走 IM 系统账号而非业务库新表:复用已验证链路,改动最小(方案对比后用户选定 A)。
- 重封禁也发消息:留档 + 解封后可见;封禁页补一行覆盖"被封期间看得到"的诉求(用户确认)。
- 解封也发消息:重度用户被封期间看不到消息页,解封消息是其唯一"可回来了"的通知(用户确认)。
- 原因兜底「违反社区规范」:admin 渠道 ban_reason 可不填。
