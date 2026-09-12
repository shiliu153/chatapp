# 聊天页/资料页微信式改版 + IM 昵称同步 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 三页(聊天页/我的页/别人的资料页)改微信版式+品牌粉色调,补齐聊天页 7 项功能,并以「IM 昵称同步」修掉拉黑后会话名降级成裸 id 的问题。

**Architecture:** 后端只做 IM 昵称同步(新 REST 函数+后台线程钩子+存量补数命令),业务接口与数据库零改动;前端在 `lib/im/` 抽象层扩展图片消息/删除/重发,聊天页与资料页按新组件拆分重构;所有 SDK 能力沿用「真实现在 tencent_im_client.dart,测试用 FakeImClient」纪律。

**Tech Stack:** Flutter 3.47.2 + Riverpod 3.4 + go_router + tencent_cloud_chat_sdk 9.0.7652+1 + image_picker(已依赖);Django 5.2 + DRF + MySQL。

**Spec:** `docs/superpowers/specs/2026-09-12-chat-profile-wechat-design.md`

## Global Constraints

- Flutter 版本 3.47.2 **勿动**;前端命令一律 `../flutter/bin/flutter.bat`,后端 cwd = `chatapp/`
- `flutter analyze` 必须零告警;后端全量测试全绿(当前 190+,前端 120+)
- **测试纪律**:真实 SDK 只出现在 `tencent_im_client.dart`;widget 测试只跑 `FakeImClient`;带网络图的 widget 必须 `errorBuilder` 兜底;widget 测试里不裸 `await` 走 dio 的 provider;含无限动画/轮询页面不用 `pumpAndSettle`
- **后端 IM 纪律**:`im/client.py` 的函数对外**永不抛异常**,失败返回 False 只记日志;测试中任何触发 IM 的路径 mock 线程分派点(`users.services._dispatch_async` / `moderation.services._dispatch_async`)
- 不改消息页(chats_page)UI;不引入语音/已读;**无数据库迁移**
- 提交信息用中文,风格同现有(`feat(app):` / `feat(backend):` / `test:` / `docs:`)

---

### Task 1: 后端 — 昵称同步函数 `set_profile_nick`

**Files:**
- Modify: `chatapp/im/client.py`(末尾追加)
- Test: `chatapp/im/tests.py`

**Interfaces:**
- Produces: `set_profile_nick(identifier: str, nickname: str) -> bool`(Task 2/3 使用)

- [ ] **Step 1: 写失败测试**(`chatapp/im/tests.py`,与现有 `test_import_account_payload` 同风格)

```python
@patch("im.client._request", return_value={"ErrorCode": 0})
def test_set_profile_nick_payload(self, request):
    self.assertTrue(set_profile_nick("u1", "小明"))
    args, _ = request.call_args
    self.assertEqual(args[0], "profile")
    self.assertEqual(args[1], "profile_set_field")
    self.assertEqual(args[2]["From_Account"], "u1")
    self.assertEqual(args[2]["ProfileItem"],
                     [{"Tag": "Tag_Profile_IM_Nick", "Value": "小明"}])

@patch("im.client._request", side_effect=Exception("boom"))
def test_set_profile_nick_network_error_returns_false(self, request):
    self.assertFalse(set_profile_nick("u1", "小明"))
```

顶部 import 区补:`set_profile_nick`(加入现有 from .client import 列表)。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd chatapp && python manage.py test im` → ImportError/NameError

- [ ] **Step 3: 实现**(`chatapp/im/client.py` 末尾)

```python
def set_profile_nick(identifier: str, nickname: str) -> bool:
    """把昵称同步到 IM 资料(会话列表 showName 的来源,名字降级兜底的根)。"""
    payload = {
        "From_Account": identifier,
        "ProfileItem": [{"Tag": "Tag_Profile_IM_Nick", "Value": nickname}],
    }
    try:
        result = _request("profile", "profile_set_field", payload)
    except Exception:
        logger.exception("IM profile_set_field 调用失败 identifier=%s", identifier)
        return False
    return _check(result, "profile_set_field")
```

- [ ] **Step 4: 跑测试确认通过** — `python manage.py test im` 全绿

- [ ] **Step 5: 提交**

```bash
git add chatapp/im/client.py chatapp/im/tests.py
git commit -m "feat(backend): im.client 增加 set_profile_nick 昵称同步"
```

---

### Task 2: 后端 — 改昵称后台同步 + 视图钩子

**Files:**
- Modify: `chatapp/users/services.py`(加 `_dispatch_async` / `sync_im_nickname`)
- Modify: `chatapp/users/views.py:19-33`(`me` 的 PATCH 分支加钩子)
- Test: `chatapp/users/tests.py`

**Interfaces:**
- Consumes: Task 1 的 `im_client.set_profile_nick`
- Produces: `users.services.sync_im_nickname(user) -> None`;`users.services._dispatch_async(fn, *args) -> None`(测试 mock 点)

- [ ] **Step 1: 写失败测试**(`chatapp/users/tests.py`,找现有 `test_patch...` 昵称用例所在类)

```python
@patch("users.services._dispatch_async")
def test_patch_nickname_triggers_im_sync(self, dispatch):
    resp = self.client.patch("/api/v1/users/me", {"nickname": "新名字"}, format="json")
    self.assertEqual(resp.status_code, 200)
    from im import client as im_client
    dispatch.assert_called_once_with(im_client.set_profile_nick, self.user.im_user_id, "新名字")

@patch("users.services._dispatch_async")
def test_patch_same_nickname_no_sync(self, dispatch):
    self.client.patch("/api/v1/users/me", {"nickname": self.user.profile.nickname},
                      format="json")
    dispatch.assert_not_called()

@patch("users.services._dispatch_async")
def test_patch_other_field_no_sync(self, dispatch):
    self.client.patch("/api/v1/users/me", {"city": "杭州"}, format="json")
    dispatch.assert_not_called()
```

⚠️ 同时给**现有**会改昵称的用例(约 L121 的 PATCH 测试)补 `@patch("users.services._dispatch_async")` 装饰器 + 参数——否则会真的起线程打腾讯 REST。

- [ ] **Step 2: 跑测试确认失败** — `python manage.py test users`

- [ ] **Step 3: 实现服务层**(`chatapp/users/services.py` 末尾)

```python
import threading

from im import client as im_client


def sync_im_nickname(user) -> None:
    """昵称变更后同步到 IM 资料(后台线程;失败只记日志,不影响业务)。"""
    nickname = getattr(getattr(user, "profile", None), "nickname", "")
    if not nickname:
        return
    _dispatch_async(im_client.set_profile_nick, user.im_user_id, nickname)


def _dispatch_async(fn, *args) -> None:
    """IM 调用丢后台线程,接口响应不等腾讯 REST(同 moderation.services._dispatch_async)。"""
    threading.Thread(target=fn, args=args, daemon=True).start()
```

- [ ] **Step 4: 实现视图钩子**(`chatapp/users/views.py`)

import 行改为 `from .services import get_profile, sync_im_nickname`;`me()` 的 PATCH 分支:

```python
    if request.method == "PATCH":
        serializer = ProfileUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        tag_ids = data.pop("tag_ids", None)
        old_nickname = profile.nickname
        for field, value in data.items():
            setattr(profile, field, value)
        profile.save()
        if tag_ids is not None:
            profile.tags.set(Tag.objects.filter(id__in=tag_ids))
        profile.refresh_status()
        if profile.nickname != old_nickname:
            sync_im_nickname(profile.user)
```

- [ ] **Step 5: 跑测试确认通过** — `python manage.py test users` 全绿;再全量 `python manage.py test` 全绿

- [ ] **Step 6: 提交**

```bash
git add chatapp/users/services.py chatapp/users/views.py chatapp/users/tests.py
git commit -m "feat(backend): 改昵称时后台同步到 IM 资料"
```

---

### Task 3: 后端 — 存量补数命令 `im_sync_nicknames`

**Files:**
- Create: `chatapp/im/management/commands/im_sync_nicknames.py`
- Test: `chatapp/im/tests.py`

**Interfaces:**
- Consumes: Task 1 的 `set_profile_nick`
- Produces: 管理命令(执行记录里手跑一次)

- [ ] **Step 1: 写失败测试**

```python
@patch("im.management.commands.im_sync_nicknames.set_profile_nick", return_value=True)
def test_sync_nicknames_iterates_profiles(self, sync):
    from django.core.management import call_command
    from users.models import Profile
    Profile.objects.update_or_create(user=self.user, defaults={"nickname": "小明"})
    call_command("im_sync_nicknames")
    sync.assert_any_call(self.user.im_user_id, "小明")

@patch("im.management.commands.im_sync_nicknames.set_profile_nick", return_value=True)
def test_sync_nicknames_skips_empty(self, sync):
    from django.core.management import call_command
    call_command("im_sync_nicknames")
    sync.assert_not_called()
```

(按现有 im/tests.py 的建用户方式准备 `self.user`;若已有同类 setUp 直接复用。)

- [ ] **Step 2: 跑测试确认失败** — `python manage.py test im`

- [ ] **Step 3: 实现**(参照 `im_setup_system_account.py` 风格)

```python
"""一次性/随时可跑:把本地昵称全量同步到腾讯 IM(幂等,失败只记日志)。

用法:
    python manage.py im_sync_nicknames
"""

from django.core.management.base import BaseCommand

from im.client import set_profile_nick
from users.models import Profile


class Command(BaseCommand):
    help = "把用户昵称全量同步到腾讯 IM(幂等)"

    def handle(self, *args, **options):
        ok = fail = 0
        for profile in Profile.objects.exclude(nickname="").select_related("user"):
            if set_profile_nick(profile.user.im_user_id, profile.nickname):
                ok += 1
            else:
                fail += 1
        style = self.style.WARNING if fail else self.style.SUCCESS
        self.stdout.write(style(f"昵称同步完成:成功 {ok},失败 {fail}"))
```

- [ ] **Step 4: 跑测试确认通过** — `python manage.py test im`

- [ ] **Step 5: 对开发库真跑一次**(补 u7/u8/u9)

Run: `cd chatapp && python manage.py im_sync_nicknames`
Expected: `昵称同步完成:成功 3,失败 0`(看具体人数;失败>0 时查 IM 日志)

- [ ] **Step 6: 提交**

```bash
git add chatapp/im/management/commands/im_sync_nicknames.py chatapp/im/tests.py
git commit -m "feat(backend): im_sync_nicknames 存量昵称补数命令"
```

---

### Task 4: 前端 — IM 抽象层扩展(图片消息/删除)

**Files:**
- Modify: `app/lib/im/im_client.dart`
- Modify: `app/lib/im/tencent_im_client.dart`
- Modify: `app/test/support/fake_im_client.dart`
- Test: `app/test/im/tencent_im_client_test.dart`

**Interfaces:**
- Produces(后续所有任务依赖):
  - `enum ChatMessageKind { text, matchNotice, banNotice, image, other }`
  - `ChatMessage` 新字段:`localPath`(String?)、`imageUrl`(String? 缩略)、`imageLargeUrl`(String? 原图)、`isFailed`(bool,默认 false);新方法 `copyWith({bool? isPending, bool? isFailed, String? imageUrl})`
  - `ImClient.sendImage({required String peerId, required String imagePath}) → Future<ChatMessage>`
  - `ImClient.deleteMessage(ChatMessage message) → Future<void>`
  - `ImClient.resend(ChatMessage message) → Future<ChatMessage>`(抽象类里的**具体**方法:image 走 sendImage,其余走 sendText)
  - `FakeImClient.log` 新增流水格式:`sendImage:$peerId:$path` / `delete:$msgId`

- [ ] **Step 1: 写失败测试**(`app/test/im/tencent_im_client_test.dart` 追加;复用文件里现有 `sdkMessage` 帮助函数)

```dart
Map<String, dynamic> imageElem({
  String path = '/tmp/a.png',
  String? thumbUrl = 'https://x/thumb.png',
  String? originUrl = 'https://x/origin.png',
}) =>
    {
      'elem_type': CElemType.ElemImage,
      'image_elem_orig_path': path,
      'image_elem_thumb_url': thumbUrl,
      'image_elem_orig_url': originUrl,
      'image_elem_large_url': originUrl,
    };

test('图片消息:kind=image,localPath 取 path,缩略/原图取对应 url', () {
  final message = chatMessageFromSdk(sdkMessage(isSelf: true, elem: imageElem()));
  expect(message.kind, ChatMessageKind.image);
  expect(message.localPath, '/tmp/a.png');
  expect(message.imageUrl, 'https://x/thumb.png');
  expect(message.imageLargeUrl, 'https://x/origin.png');
});

test('图片消息:没有缩略图时 imageUrl 落回原图', () {
  final message =
      chatMessageFromSdk(sdkMessage(isSelf: false, elem: imageElem(thumbUrl: null)));
  expect(message.imageUrl, 'https://x/origin.png');
});
```

- [ ] **Step 2: 跑测试确认失败** — `cd app && ../flutter/bin/flutter.bat test test/im/tencent_im_client_test.dart`

- [ ] **Step 3: 扩展领域模型与接口**(`app/lib/im/im_client.dart`)

```dart
enum ChatMessageKind { text, matchNotice, banNotice, image, other }
```

`ChatMessage` 加字段(构造参数可选):

```dart
    this.localPath,
    this.imageUrl,
    this.imageLargeUrl,
    this.isFailed = false,
```

```dart
  /// 图片消息的本机文件(发送中先上屏;接收方通常为 null)。
  final String? localPath;
  /// 远程缩略图(气泡里展示用)。
  final String? imageUrl;
  /// 远程原图(全屏查看用)。
  final String? imageLargeUrl;

  /// 发送失败(可点重发)。
  final bool isFailed;

  ChatMessage copyWith({bool? isPending, bool? isFailed, String? imageUrl}) => ChatMessage(
        msgId: msgId,
        peerId: peerId,
        isSelf: isSelf,
        timestamp: timestamp,
        kind: kind,
        text: text,
        isPending: isPending ?? this.isPending,
        isFailed: isFailed ?? this.isFailed,
        localPath: localPath,
        imageUrl: imageUrl ?? this.imageUrl,
        imageLargeUrl: imageLargeUrl,
      );
```

`ImClient` 增:

```dart
  Future<ChatMessage> sendImage({required String peerId, required String imagePath});

  /// 删除本地消息(对方不受影响);本地未发出的消息可直接忽略此调用。
  Future<void> deleteMessage(ChatMessage message);

  /// 该 SDK 版本无原生重发:等价于用原内容重新发送。
  Future<ChatMessage> resend(ChatMessage message) {
    if (message.kind == ChatMessageKind.image && message.localPath != null) {
      return sendImage(peerId: message.peerId, imagePath: message.localPath!);
    }
    return sendText(peerId: message.peerId, text: message.text);
  }
```

同时更新 `ImConversation.showName` 的注释(IM 侧昵称现在会同步,不再是「通常为空」):

```dart
  /// IM 侧的名字/头像:昵称已由后端同步(改昵称→profile_set_field),展示优先本地 matches 缓存。
```

- [ ] **Step 4: 实现 SDK 映射**(`app/lib/im/tencent_im_client.dart`)

import 区加:`import 'package:tencent_cloud_chat_sdk/enum/image_types.dart';`

`_kindOf` 增加分支:

```dart
  if (message.elemType == MessageElemType.V2TIM_ELEM_TYPE_IMAGE) {
    return ChatMessageKind.image;
  }
```

`chatMessageFromSdk` 的 text switch 加 `ChatMessageKind.image => '',`,并补字段:

```dart
    localPath: kind == ChatMessageKind.image ? message.imageElem?.path : null,
    imageUrl: kind == ChatMessageKind.image
        ? (_pickImageUrl(message.imageElem?.imageList, V2TIM_IMAGE_TYPE.V2TIM_IMAGE_TYPE_THUMB) ??
            _pickImageUrl(message.imageElem?.imageList, V2TIM_IMAGE_TYPE.V2TIM_IMAGE_TYPE_ORIGIN))
        : null,
    imageLargeUrl: kind == ChatMessageKind.image
        ? (_pickImageUrl(message.imageElem?.imageList, V2TIM_IMAGE_TYPE.V2TIM_IMAGE_TYPE_ORIGIN) ??
            _pickImageUrl(message.imageElem?.imageList, V2TIM_IMAGE_TYPE.V2TIM_IMAGE_TYPE_LARGE))
        : null,
```

文件内加帮助函数(用 dynamic 避开 web 条件导入):

```dart
String? _pickImageUrl(List<dynamic>? list, int type) {
  if (list == null) return null;
  for (final item in list) {
    final url = item?.url;
    if (item?.type == type && url is String && url.isNotEmpty) return url;
  }
  return null;
}
```

`TencentImClient` 加两个方法(照抄 `sendText` 的 id+message 双传模式):

```dart
  @override
  Future<ChatMessage> sendImage({required String peerId, required String imagePath}) async {
    final manager = TencentImSDKPlugin.v2TIMManager.getMessageManager();
    final created = await manager.createImageMessage(imagePath: imagePath);
    _check(created.code, created.desc);
    final sent = await manager.sendMessage(
      // ignore: deprecated_member_use
      id: created.data!.id,
      message: created.data!.messageInfo,
      receiver: peerId,
      groupID: '',
    );
    _check(sent.code, sent.desc);
    return chatMessageFromSdk(sent.data!);
  }

  @override
  Future<void> deleteMessage(ChatMessage message) async {
    final result = await TencentImSDKPlugin.v2TIMManager
        .getMessageManager()
        .deleteMessageFromLocalStorage(msgID: message.msgId);
    _check(result.code, result.desc);
  }
```

- [ ] **Step 5: 补齐 FakeImClient**(`app/test/support/fake_im_client.dart`)

```dart
  @override
  Future<ChatMessage> sendImage({required String peerId, required String imagePath}) async {
    log.add('sendImage:$peerId:$imagePath');
    if (sendError != null) throw sendError!;
    return ChatMessage(
      msgId: 'sent-${++_seq}',
      peerId: peerId,
      isSelf: true,
      timestamp: DateTime.now().millisecondsSinceEpoch,
      kind: ChatMessageKind.image,
      localPath: imagePath,
    );
  }

  @override
  Future<void> deleteMessage(ChatMessage message) async => log.add('delete:${message.msgId}');
```

- [ ] **Step 6: 跑测试与全量** — `../flutter/bin/flutter.bat test test/im` 通过;`../flutter/bin/flutter.bat test` 全绿(else 分支的 switch 若报穷尽性,按提示补 `ChatMessageKind.image` 分支——已知点在 `chats_page.dart` 的 `_previewOf`,补 `ChatMessageKind.image => '[图片]'`);`analyze` 零告警

- [ ] **Step 7: 提交**

```bash
git add app/lib/im app/test/support/fake_im_client.dart app/test/im app/lib/features/chat/chats_page.dart
git commit -m "feat(app): IM 抽象层支持图片消息与本地删除"
```

---

### Task 5: 前端 — 时间分组纯函数

**Files:**
- Modify: `app/lib/core/format.dart`
- Create: `app/lib/features/chat/chat_items.dart`
- Test: `app/test/features/chat/chat_items_test.dart`(新建;format 若已有测试文件则补在其中)

**Interfaces:**
- Produces:
  - `formatChatTimestamp(DateTime time, {DateTime? now}) → String`
  - `sealed class ChatItem`;`ChatMessageItem(ChatMessage message)`;`ChatTimeItem(String label)`
  - `buildChatItems(List<ChatMessage> messages, {DateTime? now}) → List<ChatItem>`(输入正序,输出正序)

- [ ] **Step 1: 写失败测试**

```dart
import 'package:flutter_test/flutter_test.dart';
import 'package:chatapp_app/core/format.dart';
import 'package:chatapp_app/features/chat/chat_items.dart';
import 'package:chatapp_app/im/im_client.dart';

ChatMessage _m(String id, DateTime time) => ChatMessage(
      msgId: id, peerId: 'u9', isSelf: false,
      timestamp: time.millisecondsSinceEpoch, kind: ChatMessageKind.text, text: id,
    );

void main() {
  test('formatChatTimestamp:今天/昨天/更早', () {
    final now = DateTime(2026, 9, 12, 10, 0);
    expect(formatChatTimestamp(DateTime(2026, 9, 12, 9, 5), now: now), '09:05');
    expect(formatChatTimestamp(DateTime(2026, 9, 11, 22, 30), now: now), '昨天 22:30');
    expect(formatChatTimestamp(DateTime(2026, 3, 1, 8, 0), now: now), '3月1日 08:00');
    expect(formatChatTimestamp(DateTime(2025, 12, 31, 23, 59), now: now), '2025年12月31日 23:59');
  });

  test('buildChatItems:首条必有时间条,间隔超 5 分钟才插新的', () {
    final base = DateTime(2026, 9, 12, 10, 0);
    final items = buildChatItems([
      _m('a', base),
      _m('b', base.add(const Duration(minutes: 5))),   // 正好 5 分钟:不插
      _m('c', base.add(const Duration(minutes: 11))),  // 超 5 分钟:插
    ], now: base);
    expect(items.whereType<ChatTimeItem>().length, 2);
    expect(items.whereType<ChatMessageItem>().length, 3);
  });

  test('buildChatItems:空列表空输出', () {
    expect(buildChatItems(const [], now: DateTime(2026)), isEmpty);
  });
}
```

- [ ] **Step 2: 跑测试确认失败** — `../flutter/bin/flutter.bat test test/features/chat/chat_items_test.dart`

- [ ] **Step 3: 实现**(`app/lib/core/format.dart` 追加)

```dart
/// 聊天页时间条:今天 HH:mm / 昨天 HH:mm / 本年 M月d日 HH:mm / 跨年 yyyy年M月d日 HH:mm。
String formatChatTimestamp(DateTime time, {DateTime? now}) {
  final n = now ?? DateTime.now();
  final hm = '${time.hour.toString().padLeft(2, '0')}:${time.minute.toString().padLeft(2, '0')}';
  final today = DateTime(n.year, n.month, n.day);
  final day = DateTime(time.year, time.month, time.day);
  if (day == today) return hm;
  if (day == today.subtract(const Duration(days: 1))) return '昨天 $hm';
  if (time.year == n.year) return '${time.month}月${time.day}日 $hm';
  return '${time.year}年${time.month}月${time.day}日 $hm';
}
```

新建 `app/lib/features/chat/chat_items.dart`:

```dart
import '../../core/format.dart';
import '../../im/im_client.dart';

sealed class ChatItem {
  const ChatItem();
}

class ChatMessageItem extends ChatItem {
  const ChatMessageItem(this.message);
  final ChatMessage message;
}

class ChatTimeItem extends ChatItem {
  const ChatTimeItem(this.label);
  final String label;
}

/// 相邻消息间隔 > 5 分钟(或首条)插一条时间条;输入/输出均为旧→新。
List<ChatItem> buildChatItems(List<ChatMessage> messages, {DateTime? now}) {
  const gap = Duration(minutes: 5).inMilliseconds;
  final items = <ChatItem>[];
  int? prevTimestamp;
  for (final message in messages) {
    if (prevTimestamp == null || message.timestamp - prevTimestamp! > gap) {
      items.add(ChatTimeItem(formatChatTimestamp(
          DateTime.fromMillisecondsSinceEpoch(message.timestamp), now: now)));
    }
    items.add(ChatMessageItem(message));
    prevTimestamp = message.timestamp;
  }
  return items;
}
```

- [ ] **Step 4: 跑测试确认通过** — 同上命令;`analyze` 零告警

- [ ] **Step 5: 提交**

```bash
git add app/lib/core/format.dart app/lib/features/chat/chat_items.dart app/test/features/chat/chat_items_test.dart
git commit -m "feat(app): 聊天时间分组纯函数与时间条格式"
```

---

### Task 6: 前端 — MessageBubble 重构(头像/图片/失败态)

**Files:**
- Modify: `app/lib/features/chat/widgets/message_bubble.dart`
- Test: `app/test/features/chat/message_bubble_test.dart`(新建)

**Interfaces:**
- Consumes: Task 4 的 ChatMessage 扩展
- Produces:`MessageBubble({required ChatMessage message, String? peerName, String? peerAvatarUrl, String? selfAvatarUrl, VoidCallback? onLongPress, VoidCallback? onRetry, VoidCallback? onTapImage})`;组件内 Key:`'chat.retry'`(失败叹号)、`'chat.image'`(图片气泡)

- [ ] **Step 1: 写失败测试**

```dart
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:chatapp_app/features/chat/widgets/message_bubble.dart';
import 'package:chatapp_app/im/im_client.dart';

ChatMessage _m({
  bool isSelf = false,
  ChatMessageKind kind = ChatMessageKind.text,
  String text = '你好',
  bool isFailed = false,
  String? localPath,
}) =>
    ChatMessage(
      msgId: 'm1', peerId: 'u9', isSelf: isSelf, timestamp: 1,
      kind: kind, text: text, isFailed: isFailed, localPath: localPath,
    );

Future<void> _pump(WidgetTester tester, Widget child) => tester.pumpWidget(
    MaterialApp(home: Scaffold(body: child)));

void main() {
  testWidgets('对方气泡:头像首字 + 白色气泡', (tester) async {
    await _pump(tester, MessageBubble(message: _m(), peerName: '小红'));
    expect(find.text('小'), findsOneWidget);   // 头像占位
    expect(find.text('你好'), findsOneWidget);
  });

  testWidgets('失败态:出现重发叹号,点击回调', (tester) async {
    var retried = 0;
    await _pump(tester,
        MessageBubble(message: _m(isSelf: true, isFailed: true), onRetry: () => retried++));
    await tester.tap(find.byKey(const Key('chat.retry')));
    expect(retried, 1);
  });

  testWidgets('图片消息:本地文件不存在也走 errorBuilder 不炸', (tester) async {
    await _pump(tester,
        MessageBubble(message: _m(kind: ChatMessageKind.image, text: '', localPath: 'not_exist.png')));
    await tester.pump();   // 让 errorBuilder 生效
    expect(find.byKey(const Key('chat.image')), findsOneWidget);
  });

  testWidgets('match_notice 仍是居中灰条', (tester) async {
    await _pump(tester, MessageBubble(message: _m(kind: ChatMessageKind.matchNotice, text: '你们已互相喜欢,开始聊天吧')));
    expect(find.byKey(const Key('chat.notice')), findsOneWidget);
  });
}
```

- [ ] **Step 2: 跑测试确认失败** — `../flutter/bin/flutter.bat test test/features/chat/message_bubble_test.dart`

- [ ] **Step 3: 实现**(整体重写 `message_bubble.dart`;灰条分支保持现状)

```dart
import 'dart:io';

import 'package:flutter/material.dart';

import '../../../im/im_client.dart';

/// 单条消息:对方=方头像+白气泡(左),自己=品牌粉气泡+方头像(右);
/// match_notice/ban_notice 渲染成居中灰条。
class MessageBubble extends StatelessWidget {
  const MessageBubble({
    super.key,
    required this.message,
    this.peerName,
    this.peerAvatarUrl,
    this.selfAvatarUrl,
    this.onLongPress,
    this.onRetry,
    this.onTapImage,
  });

  final ChatMessage message;
  final String? peerName;
  final String? peerAvatarUrl;
  final String? selfAvatarUrl;
  final VoidCallback? onLongPress;
  final VoidCallback? onRetry;
  final VoidCallback? onTapImage;

  static const noticeFallback = '你们已互相喜欢,开始聊天吧';

  @override
  Widget build(BuildContext context) {
    if (message.kind != ChatMessageKind.text && message.kind != ChatMessageKind.image) {
      // 灰条分支:与改版前一致
      final label = switch (message.kind) {
        ChatMessageKind.matchNotice => message.text.isEmpty ? noticeFallback : message.text,
        ChatMessageKind.banNotice => message.text.isEmpty ? '系统通知' : message.text,
        _ => '[暂不支持的消息]',
      };
      return Padding(
        key: const Key('chat.notice'),
        padding: const EdgeInsets.symmetric(vertical: 8),
        child: Center(
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
            decoration: BoxDecoration(
              color: Colors.black12,
              borderRadius: BorderRadius.circular(12),
            ),
            child: Text(label, style: const TextStyle(color: Colors.black54, fontSize: 12)),
          ),
        ),
      );
    }

    final isSelf = message.isSelf;
    final avatar = _SquareAvatar(
      name: isSelf ? '我' : (peerName ?? ''),
      url: isSelf ? selfAvatarUrl : peerAvatarUrl,
    );
    final bubble = GestureDetector(
      onLongPress: onLongPress,
      child: Opacity(
        opacity: message.isPending ? 0.6 : 1,
        child: ConstrainedBox(
          constraints: BoxConstraints(maxWidth: MediaQuery.sizeOf(context).width * 0.66),
          child: _bubbleContent(context),
        ),
      ),
    );

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 5),
      child: Row(
        mainAxisAlignment: isSelf ? MainAxisAlignment.end : MainAxisAlignment.start,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (!isSelf) ...[avatar, const SizedBox(width: 8)],
          if (isSelf && message.isFailed) ...[
            IconButton(
              key: const Key('chat.retry'),
              onPressed: onRetry,
              icon: const Icon(Icons.error, color: Colors.red, size: 20),
              visualDensity: VisualDensity.compact,
            ),
          ],
          bubble,
          if (isSelf) ...[const SizedBox(width: 8), avatar],
        ],
      ),
    );
  }

  Widget _bubbleContent(BuildContext context) {
    if (message.kind == ChatMessageKind.image) {
      return GestureDetector(
        key: const Key('chat.image'),
        onTap: onTapImage,
        child: ClipRRect(
          borderRadius: BorderRadius.circular(8),
          child: SizedBox(width: 140, height: 140, child: _image()),
        ),
      );
    }
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
      decoration: BoxDecoration(
        color: message.isSelf ? const Color(0xFFFF2C55) : Colors.white,
        borderRadius: BorderRadius.only(
          topLeft: const Radius.circular(10),
          topRight: const Radius.circular(10),
          bottomLeft: Radius.circular(message.isSelf ? 10 : 2),
          bottomRight: Radius.circular(message.isSelf ? 2 : 10),
        ),
      ),
      child: Text(message.text,
          style: TextStyle(
              fontSize: 15,
              color: message.isSelf ? Colors.white : const Color(0xFF26282C))),
    );
  }

  Widget _image() {
    final path = message.localPath;
    if (path != null && path.isNotEmpty) {
      return Image.file(File(path), fit: BoxFit.cover, errorBuilder: _fallback);
    }
    final url = message.imageUrl;
    if (url != null && url.isNotEmpty) {
      return Image.network(url, fit: BoxFit.cover, errorBuilder: _fallback);
    }
    return _fallback(null, null, null);
  }

  Widget _fallback(BuildContext? c, Object? e, StackTrace? s) => Container(
        color: const Color(0xFFEFE3E7),
        child: const Center(child: Icon(Icons.image_outlined, color: Colors.white70)),
      );
}

/// 方形圆角头像(微信式);无图显示首字。
class _SquareAvatar extends StatelessWidget {
  const _SquareAvatar({required this.name, this.url});

  final String name;
  final String? url;

  @override
  Widget build(BuildContext context) {
    final image = url;
    return Container(
      width: 40,
      height: 40,
      decoration: BoxDecoration(
        color: const Color(0xFFF3B8C8),
        borderRadius: BorderRadius.circular(6),
      ),
      clipBehavior: Clip.antiAlias,
      child: image == null || image.isEmpty
          ? Center(
              child: Text(name.isEmpty ? '?' : name.substring(0, 1),
                  style: const TextStyle(color: Colors.white, fontSize: 15)))
          : Image.network(image, fit: BoxFit.cover,
              errorBuilder: (c, e, s) => Center(
                  child: Text(name.isEmpty ? '?' : name.substring(0, 1),
                      style: const TextStyle(color: Colors.white, fontSize: 15)))),
    );
  }
}
```

- [ ] **Step 4: 跑测试确认通过** — 同上;再跑 `../flutter/bin/flutter.bat test test/features/chat` 看 chat_page 旧用例损伤(气泡结构变化:原「发送失败→SnackBar+气泡撤掉」用例会在 Task 7 改,若此刻红,先记录,Task 7 修复)

- [ ] **Step 5: 提交**

```bash
git add app/lib/features/chat/widgets/message_bubble.dart app/test/features/chat/message_bubble_test.dart
git commit -m "feat(app): 消息气泡改微信式(方头像/粉气泡/图片/失败态)"
```

---

### Task 7: 前端 — ChatController 发送状态改造

**Files:**
- Modify: `app/lib/features/chat/chat_controller.dart`
- Modify: `app/test/features/chat/chat_page_test.dart`(改「发送失败」用例)

**Interfaces:**
- Consumes: Task 4 的 `ImClient.sendImage/resend`、Task 6 的失败态气泡
- Produces:`ChatController.send(String text)`、`sendImage(String path)`、`retry(ChatMessage message)`、`deleteLocal(ChatMessage message)`(send 不再抛异常)

- [ ] **Step 1: 改失败测试**(`chat_page_test.dart` 把「发送失败 → SnackBar 提示,气泡撤掉」改为)

```dart
  testWidgets('发送失败 → 气泡保留 + 叹号;点叹号重发成功', (tester) async {
    fake.sendError = const ImException(6013, 'network');
    await pumpChat(tester);

    await tester.enterText(find.byKey(const Key('chat.input')), '你好');
    await tester.tap(find.byKey(const Key('chat.send')));
    await tester.pumpAndSettle();

    expect(find.text('你好'), findsOneWidget);                 // 消息还在
    expect(find.byKey(const Key('chat.retry')), findsOneWidget); // 有叹号

    fake.sendError = null;                                     // 网络恢复
    await tester.tap(find.byKey(const Key('chat.retry')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('chat.retry')), findsNothing);
    expect(fake.log.where((l) => l == 'send:u9:你好').length, 2); // 重发走了 send
  });
```

- [ ] **Step 2: 跑测试确认失败** — `../flutter/bin/flutter.bat test test/features/chat/chat_page_test.dart`

- [ ] **Step 3: 实现**(`chat_controller.dart`)

```dart
  Future<void> send(String text) => _sendOut(ChatMessage(
        msgId: 'local-${DateTime.now().microsecondsSinceEpoch}',
        peerId: peerId,
        isSelf: true,
        timestamp: DateTime.now().millisecondsSinceEpoch,
        kind: ChatMessageKind.text,
        text: text,
        isPending: true,
      ));

  Future<void> sendImage(String imagePath) => _sendOut(ChatMessage(
        msgId: 'local-${DateTime.now().microsecondsSinceEpoch}',
        peerId: peerId,
        isSelf: true,
        timestamp: DateTime.now().millisecondsSinceEpoch,
        kind: ChatMessageKind.image,
        localPath: imagePath,
        isPending: true,
      ));

  /// 失败不抛异常、消息保留 isFailed;重发复用同一条(msgId 不变,_append 会去重)。
  Future<void> _sendOut(ChatMessage pendingMessage) async {
    _append(pendingMessage);
    final client = ref.read(imClientProvider);
    try {
      final sent = await client.resend(pendingMessage);
      _replace(pendingMessage.msgId, sent);
    } catch (_) {
      _replace(pendingMessage.msgId, pendingMessage.copyWith(isPending: false, isFailed: true));
    }
  }

  Future<void> retry(ChatMessage message) =>
      _sendOut(message.copyWith(isPending: true, isFailed: false));

  /// 删除本地消息:本地未发出的直接移出列表;已发出的尽力删 SDK 本地库。
  Future<void> deleteLocal(ChatMessage message) async {
    if (!message.msgId.startsWith('local-')) {
      try {
        await ref.read(imClientProvider).deleteMessage(message);
      } catch (_) {}
    }
    final current = state.value ?? const <ChatMessage>[];
    state = AsyncValue.data(current.where((item) => item.msgId != message.msgId).toList());
  }

  void _replace(String msgId, ChatMessage next) {
    final current = state.value ?? const <ChatMessage>[];
    state = AsyncValue.data(
        [for (final item in current) if (item.msgId == msgId) next else item]);
  }
```

注意:`_sendOut` 里 pending → 成功时用返回消息替换;`send()` 不再 rethrow,`chat_page.dart::_send` 的 try/catch 与 SnackBar 同步删除(Task 8 一起做;本任务先把控制器与用例做绿,页面里残留的 catch 不会导致测试红)。

- [ ] **Step 4: 跑测试确认通过** — 同上命令全绿;`analyze` 零告警

- [ ] **Step 5: 提交**

```bash
git add app/lib/features/chat/chat_controller.dart app/test/features/chat/chat_page_test.dart
git commit -m "feat(app): 发送失败保留气泡可重发,新增发图与本地删除"
```

---

### Task 8: 前端 — ChatPage 版式重做(顶栏/时间条/长按菜单/标题降级)

**Files:**
- Modify: `app/lib/features/chat/chat_page.dart`
- Test: `app/test/features/chat/chat_page_test.dart`

**Interfaces:**
- Consumes: Task 5 `buildChatItems`;Task 6 `MessageBubble`;Task 7 controller 方法
- Produces:页面 Key:`'chat.title'`(保留)、`'chat.more'`(顶栏 ···)、`'chat.menu.copy'`/`'chat.menu.delete'`(长按菜单项);标题降级:matchCache → IM 会话名 → 裸 id

- [ ] **Step 1: 写失败测试**(追加到 `chat_page_test.dart`)

```dart
  testWidgets('超过 5 分钟的两个消息之间出现时间条', (tester) async {
    final base = DateTime.now().subtract(const Duration(hours: 1));
    fake.history = {
      'u9': [
        _textAt('m1', base, text: '早'),
        _textAt('m2', base.add(const Duration(minutes: 6)), text: '晚'),
      ],
    };
    await pumpChat(tester);
    // 时间条组件实现时带 Key('chat.time');首条与第 6 分钟各一条,共 2
    expect(find.byKey(const Key('chat.time')), findsNWidgets(2));
  });
```

```dart
  testWidgets('长按消息 → 复制进剪贴板', (tester) async {
    final calls = <MethodCall>[];
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        SystemChannels.platform,
        (call) async { calls.add(call); return null; });
    addTearDown(() => tester.binding.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform, null));

    fake.history = {'u9': [_text('m1', isSelf: false, text: '你好')]};
    await pumpChat(tester);

    await tester.longPress(find.text('你好'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('chat.menu.copy')));
    await tester.pumpAndSettle();

    expect(calls.any((c) => c.method == 'Clipboard.setData'), isTrue);
  });

  testWidgets('长按消息 → 删除本机', (tester) async {
    fake.history = {'u9': [_text('m1', isSelf: false, text: '再见')]};
    await pumpChat(tester);

    await tester.longPress(find.text('再见'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('chat.menu.delete')));
    await tester.pumpAndSettle();

    expect(find.text('再见'), findsNothing);
    expect(fake.log, contains('delete:m1'));
  });

  testWidgets('缓存里没有对方时,标题降级用 IM 会话名', (tester) async {
    adapter = ScriptedAdapter({'GET /matches': (o) => ok([])});
    fake.conversations = [
      const ImConversation(peerId: 'u9', unreadCount: 0, showName: '小鹿'),
    ];
    await pumpChat(tester);
    expect(find.text('小鹿'), findsOneWidget);
  });
```

import 区补 `import 'package:flutter/services.dart';`(MethodCall/SystemChannels)。`_textAt` 帮助函数:

```dart
ChatMessage _textAt(String id, DateTime time, {required String text, bool isSelf = false}) =>
    ChatMessage(msgId: id, peerId: 'u9', isSelf: isSelf,
        timestamp: time.millisecondsSinceEpoch, kind: ChatMessageKind.text, text: text);
```

- [ ] **Step 2: 跑测试确认失败** — `../flutter/bin/flutter.bat test test/features/chat/chat_page_test.dart`

- [ ] **Step 3: 实现页面**(`chat_page.dart` 重写 build 与辅助)

要点(按此改):
- 顶栏:`AppBar(title: InkWell(key: 'chat.title', ..., child: Text(displayNameFor(cache, widget.peerId, imName: _imNameOf(ref)))))`,actions 加 `IconButton(key: Key('chat.more'), icon: Icon(Icons.more_horiz), onPressed: _openProfile 同款跳转)`
- 标题降级链:

```dart
  String? _imNameOf(WidgetRef ref) {
    final conversations = ref.watch(conversationsProvider).value;
    if (conversations == null) return null;
    for (final conversation in conversations) {
      if (conversation.peerId == widget.peerId) return conversation.showName;
    }
    return null;
  }
```

- 列表:用 `buildChatItems(items)`;`reverse: true` 渲染 `items[items.length-1-index]`;时间条:

```dart
class _TimeSeparator extends StatelessWidget {
  const _TimeSeparator(this.label);
  final String label;
  @override
  Widget build(BuildContext context) => Padding(
        key: const Key('chat.time'),
        padding: const EdgeInsets.symmetric(vertical: 8),
        child: Center(
          child: Text(label,
              style: const TextStyle(fontSize: 11, color: Color(0xFF9AA0A8))),
        ),
      );
}
```

- 气泡渲染传参:peerName/peerAvatar 来自 cache(`displayNameFor`/`avatarUrlFor`),self 头像来自 `ref.watch(profileProvider).value?.avatar?.url`;`onLongPress: () => _showMessageMenu(context, ref, message)`;`onRetry: () => ref.read(chatProvider(widget.peerId).notifier).retry(message)`;`onTapImage: () => _openViewer(context, message)`(Task 10 接 PhotoViewer,先留空方法调 Navigator 占位到 Task 10 完成——**Task 8 先不实现 onTapImage 跳转**,保持 null)
- 长按菜单(showMenu):

```dart
  Future<void> _showMessageMenu(BuildContext context, WidgetRef ref, ChatMessage message) async {
    final box = context.findRenderObject() as RenderBox?;
    final position = box == null
        ? RelativeRect.fill
        : RelativeRect.fromLTRB(box.globalToLocal(Offset.zero).dx,
            box.size.height, box.size.width, 0);
    final action = await showMenu<String>(
      context: context,
      position: position,
      items: [
        if (message.kind == ChatMessageKind.text)
          const PopupMenuItem(
              key: Key('chat.menu.copy'), value: 'copy', child: Text('复制')),
        const PopupMenuItem(
            key: Key('chat.menu.delete'), value: 'delete', child: Text('删除')),
      ],
    );
    if (!context.mounted || action == null) return;
    if (action == 'copy') {
      await Clipboard.setData(ClipboardData(text: message.text));
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('已复制')));
      }
    } else if (action == 'delete') {
      await ref.read(chatProvider(widget.peerId).notifier).deleteLocal(message);
    }
  }
```

- 删除 `_send` 里的 try/catch/SnackBar(`send` 不再抛):

```dart
  Future<void> _send() async {
    final text = _input.text.trim();
    if (text.isEmpty || _sending) return;
    setState(() => _sending = true);
    await ref.read(chatProvider(widget.peerId).notifier).send(text);
    _input.clear();
    if (mounted) setState(() => _sending = false);
  }
```

import 补:`package:flutter/services.dart`、`conversations_controller.dart`、`../../../core/format.dart`(经 chat_items)、`chat_items.dart`。

- [ ] **Step 4: 跑测试确认通过** — 该文件全绿;`../flutter/bin/flutter.bat test test/features/chat` 全绿(旧「点标题进资料卡」用例应仍过;`find.text('小红')` 标题用例因缓存命中不受影响)

- [ ] **Step 5: 提交**

```bash
git add app/lib/features/chat/chat_page.dart app/test/features/chat/chat_page_test.dart
git commit -m "feat(app): 聊天页微信式版式(时间条/方头像长按菜单/标题降级链)"
```

---

### Task 9: 前端 — 全屏看图 PhotoViewer

**Files:**
- Create: `app/lib/features/chat/widgets/photo_viewer.dart`
- Test: `app/test/features/chat/photo_viewer_test.dart`

**Interfaces:**
- Produces:`PhotoViewerPage({required List<String> urls, int initialIndex = 0})`,Key:`'viewer.page'`;静态帮助 `openPhotoViewer(BuildContext, {required List<String> urls, int initialIndex = 0})`(Navigator.push 封装,聊天页与资料页共用)

- [ ] **Step 1: 写失败测试**

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:chatapp_app/features/chat/widgets/photo_viewer.dart';

void main() {
  testWidgets('显示指定图片并能左右滑;点关闭退出', (tester) async {
    await tester.pumpWidget(MaterialApp(
        home: Builder(
            builder: (context) => TextButton(
                onPressed: () => openPhotoViewer(context,
                    urls: const ['https://x/1.png', 'https://x/2.png']),
                child: const Text('open')))));
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('viewer.page')), findsOneWidget);
    await tester.drag(find.byKey(const Key('viewer.page')), const Offset(-400, 0));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('viewer.close')));
    await tester.pumpAndSettle();
    expect(find.text('open'), findsOneWidget);   // 关回到宿主页
  });
}
```

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现**

```dart
import 'package:flutter/material.dart';

/// 全屏看图:黑底、左右滑、双指缩放、点右上角关闭。聊天图片与资料页相册共用。
class PhotoViewerPage extends StatefulWidget {
  const PhotoViewerPage({super.key, required this.urls, this.initialIndex = 0});

  final List<String> urls;
  final int initialIndex;

  @override
  State<PhotoViewerPage> createState() => _PhotoViewerPageState();
}

class _PhotoViewerPageState extends State<PhotoViewerPage> {
  late final PageController _controller =
      PageController(initialPage: widget.initialIndex);

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        backgroundColor: Colors.black,
        body: Stack(
          children: [
            PageView.builder(
              key: const Key('viewer.page'),
              controller: _controller,
              itemCount: widget.urls.length,
              itemBuilder: (context, index) => InteractiveViewer(
                maxScale: 4,
                child: Center(
                  child: Image.network(
                    widget.urls[index],
                    fit: BoxFit.contain,
                    errorBuilder: (c, e, s) =>
                        const Icon(Icons.broken_image_outlined, color: Colors.white38, size: 64),
                  ),
                ),
              ),
            ),
            SafeArea(
              child: Align(
                alignment: Alignment.topRight,
                child: IconButton(
                  key: const Key('viewer.close'),
                  onPressed: () => Navigator.of(context).pop(),
                  icon: const Icon(Icons.close, color: Colors.white),
                ),
              ),
            ),
          ],
        ),
      );
}

void openPhotoViewer(BuildContext context, {required List<String> urls, int initialIndex = 0}) {
  if (urls.isEmpty) return;
  Navigator.of(context).push(MaterialPageRoute(
    builder: (_) => PhotoViewerPage(urls: urls, initialIndex: initialIndex),
  ));
}
```

- [ ] **Step 4: 跑测试确认通过** — 同上;`analyze` 零告警

- [ ] **Step 5: 提交**

```bash
git add app/lib/features/chat/widgets/photo_viewer.dart app/test/features/chat/photo_viewer_test.dart
git commit -m "feat(app): 全屏看图组件(聊天与相册共用)"
```

---

### Task 10: 前端 — 输入栏扩展(表情面板/＋面板/发图片)

**Files:**
- Create: `app/lib/features/chat/widgets/emoji_panel.dart`
- Create: `app/lib/features/chat/widgets/more_panel.dart`
- Create: `app/lib/core/image_pick.dart`(把 picker 帮助从 profile 挪到 core,两处共用)
- Modify: `app/lib/features/profile/widgets/photo_grid.dart`(改 import,删本地定义)
- Modify: `app/lib/features/chat/chat_page.dart`
- Test: `app/test/features/chat/chat_page_test.dart`

**Interfaces:**
- Produces:
  - `core/image_pick.dart`:`typedef PickImage = Future<XFile?> Function();`、`pickImageFromGallery()`
  - `EmojiPanel({required ValueChanged<String> onSelect})`,Key:`'chat.emoji.panel'`、`'chat.emoji:$emoji'`
  - `MorePanel({required VoidCallback onPickImage})`,Key:`'chat.more.panel'`、`'chat.more.image'`
  - `ChatPage` 构造参数新增 `final PickImage pickImage;`(默认 `pickImageFromGallery`)

- [ ] **Step 1: 写失败测试**(`chat_page_test.dart`;`pumpChat` 帮助函数增加 `pickImage` 参数并传进 `ChatPage`,默认 `() async => null`)

```dart
  testWidgets('表情面板:点选插入输入框', (tester) async {
    await pumpChat(tester);
    await tester.tap(find.byKey(const Key('chat.emoji.button')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('chat.emoji.panel')), findsOneWidget);

    await tester.tap(find.byKey(const Key('chat.emoji.😀')));
    await tester.pumpAndSettle();
    expect(tester.widget<TextField>(find.byKey(const Key('chat.input'))).controller!.text,
        contains('😀'));
  });

  testWidgets('＋面板选图 → 发出图片消息', (tester) async {
    await pumpChat(tester, pickImage: () async => XFile('fake.png'));
    await tester.tap(find.byKey(const Key('chat.more.button')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('chat.more.image')));
    await tester.pumpAndSettle();

    expect(fake.log, contains('sendImage:u9:fake.png'));
    expect(find.byKey(const Key('chat.image')), findsWidgets);
  });

  testWidgets('点图片气泡 → 打开全屏查看', (tester) async {
    fake.history = {
      'u9': [ChatMessage(msgId: 'i1', peerId: 'u9', isSelf: false, timestamp: 1,
          kind: ChatMessageKind.image, imageUrl: 'https://x/1.png')],
    };
    await pumpChat(tester);
    await tester.tap(find.byKey(const Key('chat.image')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('viewer.page')), findsOneWidget);
  });
```

`XFile` import:`package:image_picker/image_picker.dart`(或 `package:cross_file/cross_file.dart`)。

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现**

`core/image_pick.dart`:

```dart
import 'package:image_picker/image_picker.dart';

typedef PickImage = Future<XFile?> Function();

Future<XFile?> pickImageFromGallery() => ImagePicker().pickImage(
      source: ImageSource.gallery,
      maxWidth: 1080,
      imageQuality: 85,
    );
```

`photo_grid.dart`:删本地 `typedef PickImage` 与 `pickImageFromGallery`,改 `import '../../../core/image_pick.dart';`。

`emoji_panel.dart`:

```dart
import 'package:flutter/material.dart';

const chatEmojis = ['😀', '😄', '😁', '😊', '🥰', '😍', '😘', '😜', '🤗', '🤔',
  '😐', '😴', '😭', '😅', '😂', '🙈', '👍', '👎', '👏', '🙏',
  '💪', '🎉', '❤️', '💔', '🔥', '✨', '🌹', '🍀', '☀️', '🌙',
  '⭐', '🎈', '☕', '🍺', '🍜', '⚽', '🎵', '📷', '✈️', '🚗'];

/// 基础表情面板:点选把 emoji 回给调用方。
class EmojiPanel extends StatelessWidget {
  const EmojiPanel({super.key, required this.onSelect});

  final ValueChanged<String> onSelect;

  @override
  Widget build(BuildContext context) => Container(
        key: const Key('chat.emoji.panel'),
        height: 220,
        color: const Color(0xFFF7F3F5),
        child: GridView.count(
          crossAxisCount: 8,
          padding: const EdgeInsets.all(8),
          children: [
            for (final emoji in chatEmojis)
              InkWell(
                key: Key('chat.emoji.$emoji'),
                onTap: () => onSelect(emoji),
                child: Center(child: Text(emoji, style: const TextStyle(fontSize: 24))),
              ),
          ],
        ),
      );
}
```

`more_panel.dart`:

```dart
import 'package:flutter/material.dart';

/// ＋面板:目前只有「相册」,后续入口加在这里。
class MorePanel extends StatelessWidget {
  const MorePanel({super.key, required this.onPickImage});

  final VoidCallback onPickImage;

  @override
  Widget build(BuildContext context) => Container(
        key: const Key('chat.more.panel'),
        height: 160,
        color: const Color(0xFFF7F3F5),
        padding: const EdgeInsets.all(16),
        child: Align(
          alignment: Alignment.topLeft,
          child: InkWell(
            key: const Key('chat.more.image'),
            onTap: onPickImage,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Container(
                  width: 56,
                  height: 56,
                  decoration: BoxDecoration(
                    color: Colors.white,
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: const Icon(Icons.photo_library_outlined, size: 28),
                ),
                const SizedBox(height: 6),
                const Text('相册', style: TextStyle(fontSize: 12)),
              ],
            ),
          ),
        ),
      );
}
```

`chat_page.dart` 接入:
- 构造加 `this.pickImage = pickImageFromGallery`
- state 加 `bool _showEmoji = false; bool _showMore = false;`
- 输入栏区:表情按钮 `key: Key('chat.emoji.button')`,＋按钮 `key: Key('chat.more.button')`;点表情:切 `_showEmoji`、关 `_showMore`、`FocusScope.of(context).unfocus()`;点 ＋ 对称;点输入框(FocusNode listener `hasFocus`)时两个都关
- 面板渲染在输入栏下方:

```dart
        if (_showEmoji)
          EmojiPanel(onSelect: _insertEmoji)
        else if (_showMore)
          MorePanel(onPickImage: _pickAndSendImage),
```

```dart
  void _insertEmoji(String emoji) {
    final selection = _input.selection;
    final start = selection.start >= 0 ? selection.start : _input.text.length;
    final end = selection.end >= 0 ? selection.end : _input.text.length;
    final text = _input.text.replaceRange(start, end, emoji);
    _input.value = TextEditingValue(
      text: text,
      selection: TextSelection.collapsed(offset: start + emoji.length),
    );
  }

  Future<void> _pickAndSendImage() async {
    final file = await widget.pickImage();
    if (file == null || !mounted) return;
    setState(() => _showMore = false);
    await ref.read(chatProvider(widget.peerId).notifier).sendImage(file.path);
  }
```

- 图片气泡点击接 Task 9:`onTapImage: () => openPhotoViewer(context, urls: [message.imageLargeUrl ?? message.imageUrl ?? ''], initialIndex: 0)`(urls 里过滤空串)

- [ ] **Step 4: 跑测试确认通过** — `test/features/chat` 全绿;`test/features/profile` 与全量 `flutter test` 全绿(photo_grid 挪 import 不应有行为变化);`analyze` 零告警

- [ ] **Step 5: 提交**

```bash
git add app/lib/features/chat/widgets/emoji_panel.dart app/lib/features/chat/widgets/more_panel.dart app/lib/core/image_pick.dart app/lib/features/profile/widgets/photo_grid.dart app/lib/features/chat/chat_page.dart app/test/features/chat/chat_page_test.dart
git commit -m "feat(app): 输入栏表情/＋面板与图片消息发送查看"
```

---

### Task 11: 前端 — 我的页改「个人信息」行版式

**Files:**
- Modify: `app/lib/features/profile/my_profile_page.dart`
- Test: 更新/新增 `app/test/features/profile/my_profile_test.dart`(若不存在则新建;先 `ls app/test/features/profile/` 查现有文件名)

**Interfaces:**
- 行 Key:`'my.row.avatar'`/`'my.row.nickname'`/`'my.row.id'`/`'my.row.gender'`/`'my.row.birthday'`/`'my.row.city'`/`'my.row.bio'`/`'my.row.tags'`/`'my.row.preference'`/`'my.row.settings'`;ID 文案 `u{Profile.id}`

- [ ] **Step 1: 写失败测试**(沿用该文件现有 pump 方式;断言)

```dart
    expect(find.text('u7'), findsOneWidget);        // ID 行(测试用户 id=7)
    expect(find.text('小雨'), findsWidgets);         // 昵称行取值
    expect(find.text('未填'), findsWidgets);         // 空值占位
    expect(find.byKey(const Key('my.row.id')), findsOneWidget);
```

以及点行跳转:`tap(find.byKey(const Key('my.row.city')))` → 出现占位路由(参照现有编辑页路由测试写法)。

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现页面**

结构(替换现 body 的 data 分支;留顶部不完善 Card 与两条设置行):

```dart
        data: (data) => ListView(
          children: [
            if (!data.isComplete) ... /* 现有「资料还没完善」Card 原样保留 */,
            _Group(children: [
              _InfoRow(rowKey: 'my.row.avatar', label: '头像', trailing: _avatarThumb(data),
                  onTap: () => context.push('/profile/edit')),
              _InfoRow(rowKey: 'my.row.nickname', label: '昵称', value: data.nickname, onTap: ...),
              _InfoRow(rowKey: 'my.row.id', label: 'ID', value: 'u${data.id}', onTap: ...),
              _InfoRow(rowKey: 'my.row.gender', label: '性别', value: _genderLabel(data.gender), onTap: ...),
              _InfoRow(rowKey: 'my.row.birthday', label: '生日', value: data.birthday ?? '', onTap: ...),
              _InfoRow(rowKey: 'my.row.city', label: '城市', value: data.city, onTap: ...),
              _InfoRow(rowKey: 'my.row.bio', label: '简介', value: data.bio, onTap: ...),
              _InfoRow(rowKey: 'my.row.tags', label: '标签',
                  value: data.tags.map((t) => t.name).join('、'), onTap: ...),
            ]),
            _Group(children: [
              _InfoRow(rowKey: 'my.row.preference', label: '想找的人', onTap: () => context.push('/preference')),
              _InfoRow(rowKey: 'my.row.settings', label: '设置', onTap: () => context.push('/settings')),
            ]),
          ],
        ),
```

`_InfoRow` 与 `_Group` 为文件内私有组件:值左对齐(标签列 `SizedBox(width: 72)`)、`›` 最右、分隔线 `Color(0xFFF5F6F7)`;空值显示 `未填`;`_genderLabel`:`male→男 / female→女 / 其他→未填`。头像行 trailing 为 38x38 圆角 6 方图(`data.avatar`,网络图带 errorBuilder)。删除原「编辑资料」入口行、原居中大头像区块(即 `_Avatar` 类可删)。

- [ ] **Step 4: 跑测试确认通过** — 该文件 + `flutter test` 全绿;`analyze` 零告警

- [ ] **Step 5: 提交**

```bash
git add app/lib/features/profile/my_profile_page.dart app/test/features/profile
git commit -m "feat(app): 我的页改微信「个人信息」行版式"
```

---

### Task 12: 前端 — 别人的资料页改「详细资料」版式

**Files:**
- Modify: `app/lib/features/profile/user_profile_page.dart`(注:该文件在 `features/profile/`,不在 `features/moderation/`)
- Test: `app/test/features/profile/user_profile_test.dart` 及所有涉及 `user.report`/`user.block` 的用例(先 `grep -rl "user.report\|user.block" app/test` 全量找出)

**Interfaces:**
- Key:`'user.more'`(顶栏 ··· 菜单按钮)、菜单项沿用 `'user.report'`/`'user.block'`(现有用例只需在点击前多一步 `tap('user.more')`);相册 `'user.album'`、照片格 `'user.album.photo:{i}'`

- [ ] **Step 1: 写/改失败测试**

```dart
  testWidgets('··· 菜单:举报入口', (tester) async {
    await pumpUserProfile(tester);           // 沿用文件里现有 pump 帮助
    await tester.tap(find.byKey(const Key('user.more')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('user.report')), findsOneWidget);
    expect(find.byKey(const Key('user.block')), findsOneWidget);
  });

  testWidgets('相册照片点开全屏查看', (tester) async {
    await pumpUserProfile(tester);
    await tester.tap(find.byKey(const Key('user.album.photo:0')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('viewer.page')), findsOneWidget);
  });
```

现有举报/拉黑全流程用例:改为先 `tap(find.byKey(const Key('user.more')))` + `pumpAndSettle()` 再点原按钮,其余断言不动。

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现**

- AppBar:`title: Text('详细资料')`,`actions: [PopupMenuButton<String>(key: Key('user.more'), onSelected: (v) => v == 'report' ? _report(context, ref) : _block(context, ref), itemBuilder: ...)]`;菜单项:

```dart
        PopupMenuItem(key: const Key('user.report'), value: 'report', child: Text('举报')),
        PopupMenuItem(key: const Key('user.block'), value: 'block', child: Text('拉黑')),
```

- `_ProfileBody` 重排:
  - 头部:56 方图(圆角 8,首字占位/网络图兜底)+ `昵称${age==null?'':' · $age 岁'}` + `ID:u${profile.userId}`
  - 资料行:地区(`profile.city`,空则 `未填`)/ 个性签名(`profile.bio`)/ 标签(空显示 `未填`)
  - 相册:标题「相册」+ `GridView.count(crossAxisCount: 3)` 照片(`Image.network` + errorBuilder,`Key('user.album.photo:$i')`),`onTap: () => openPhotoViewer(context, urls: profile.photos.map((p) => p.url).toList(), initialIndex: i)`
  - 删除底部「举报/拉黑」Row;`_report`/`_block` 方法体保留不动(仅入口变)

- [ ] **Step 4: 跑测试确认通过** — `grep -rl` 找到的测试文件全部更新并绿;全量 `flutter test`;`analyze` 零告警

- [ ] **Step 5: 提交**

```bash
git add app/lib/features/profile/user_profile_page.dart app/test
git commit -m "feat(app): 别人的资料页改微信「详细资料」版式(···菜单/相册大图)"
```

---

### Task 13: 收尾 — 全量回归、文档与手测清单

**Files:**
- Modify: `CLAUDE.md`(进度段与踩坑段)
- Modify: 本计划(勾选执行记录)

- [ ] **Step 1: 全量回归**

```bash
cd chatapp && python manage.py test          # 期望:全绿(190+ 用例)
cd ../app && ../flutter/bin/flutter.bat test # 期望:全绿(120+ 用例)
../flutter/bin/flutter.bat analyze           # 期望:No issues found
```

任何红:按 systematic-debugging 找根因再修,不许绕过。

- [ ] **Step 2: 手测清单(双模拟器;后端 runserver 已起)**

1. 互发文本/图片:图片发送中方显示本地图,发出后对方收到,点开全屏可缩放
2. 长按文本:复制;长按删除:本机消失,对方仍在
3. 时间条:跨 5 分钟/跨天显示格式正确
4. 飞行模式发消息 → 红色叹号 → 恢复网络点叹号重发成功
5. 表情面板选 emoji 插入;＋面板发图
6. 拉黑后:被拉黑方会话里仍显示真名(不再是 u7);重进 App 仍显示
7. 改昵称后:另一端(重启 App 或重进会话)看到新昵称
8. 我的页:行版式、ID 行、点行进编辑页;别人的资料页:···菜单举报/拉黑、相册大图

- [ ] **Step 3: 更新 `CLAUDE.md`**:进度段(M3 后追加部分)加一行本次改版说明(设计/计划文档路径);「前端约定」段补新踩坑(图片消息字段映射、SDK 无重发 API 的重发实现、`deleteMessageFromLocalStorage`、时间条 Key);「腾讯云 IM」段补「昵称同步」条(profile_set_field/钩子/补数命令)

- [ ] **Step 4: 提交**

```bash
git add CLAUDE.md docs/superpowers/plans/2026-09-12-chat-profile-wechat.md
git commit -m "docs: 聊天/资料页微信式改版收尾(CLAUDE.md/计划勾选)"
```

- [ ] **Step 5: 合回 master**(按项目惯例 `--no-ff`,合并后跑一次双端回归;分支名执行时定,建议 `wechat-redesign`)

---

## Self-Review 记录(写完即查)

- **Spec 覆盖**:§3 视觉规范 → Task 6/7/8/11/12;§4 聊天页 7 项 → 头像气泡 6、时间分组 5+8、长按 8、发图 4+10、表情 10、＋面板 10、失败重发 7;§5 昵称同步 → 1/2/3 + 8(前端降级链);§6 我的页 → 11;§7 别人资料页 → 12;§8 测试口径 → 各任务内 + 13;§9 风险无遗漏。无缺口。
- **占位扫描**:无 TBD/TODO;Task 8 的时间条断言已注明用 `chat.time` Key 写死(Task 8 Step 1 中较软的初稿断言已用括号说明替换为 Key 断言,执行时以 Key 为准)。
- **类型一致性**:`ChatMessage` 新字段(localPath/imageUrl/imageLargeUrl/isFailed)、`ImClient.sendImage/deleteMessage/resend`、`buildChatItems/ChatItem/ChatMessageItem/ChatTimeItem`、`PhotoViewerPage/openPhotoViewer`、`PickImage` 在后续任务引用处签名一致;`chat_controller` 的 `_sendOut/_replace/retry/deleteLocal` 与 Task 8 页面调用一致。
