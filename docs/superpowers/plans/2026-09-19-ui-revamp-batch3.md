# UI 整改批次③:消息页 + 聊天页 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按「心跳」规则 v1.2 整改消息页与会话聊天页(行为零变化,两处已批准例外),233 测试全绿 + analyze 零告警 + 双模拟器手测。

**Architecture:** 视觉层迁移:tokens(`AppColors/AppText/AppSpacing/AppRadius/AppShadows`)→ 共享组件(`AppAvatar` 加首字占位、新 `AppErrorView`)→ 聊天域新组件(骨架 ×2、空态插画)→ 两个页面逐块重排。行为、状态机、provider、路由、key 一律不动。

**Tech Stack:** Flutter 3.47(`../flutter/bin/flutter.bat`)、Riverpod、go_router、flutter_test(真实 provider + 假网络 `ScriptedAdapter` + 假 IM `FakeImClient`)。

**Spec:** `docs/superpowers/specs/2026-09-19-ui-revamp-batch3-design.md`(一切视觉细节以它 + 规则文档 v1.2 附录 B 为准)

## Global Constraints

- 所有视觉值走 token,**禁止新代码出现裸 hex / 裸字号 / 裸间距 / 裸圆角**(§1 铁律 3);确需新值先加 token 文件。
- 行为零变化;唯一例外(已批准):聊天顶栏删「⋯」按钮、聊天空态加副文案、聊天错误态加重试(`ref.invalidate`)。
- 无限动画(骨架/呼吸点/涟漪)可见的测试**一律有限 pump**(`pumpFrames`),禁 `pumpAndSettle`(见 `docs/pitfalls/testing.md`)。
- 每任务收尾必须:全量 `flutter analyze` 零告警 + 全量 `flutter test` 绿 + 提交。
- 所有 flutter/dart 命令 cwd = `app/`;后端相关命令 cwd = `chatapp/`,Python 用 anaconda 环境 `Django`。
- key 契约(不得改名):`chats.strip`、`chats.stripItem:{peerId}`、`chats.systemNotice`、`chats.tile:{peerId}`、`chats.retry`、`chat.input`、`chat.send`、`chat.emoji.button`、`chat.more.button`、`chat.emoji.panel`、`chat.more.panel`、`chat.more.image`、`chat.image`、`chat.retry`、`chat.time`、`chat.notice`、`chat.title`、`viewer.page`、`viewer.close`。
- 新增 key:`chats.skeleton`、`chat.skeleton`、`chat.back`、`chat.onlineDot`(仅测试与后续引用,无既有断言)。
- 提交信息中文,前缀沿用仓库风格(`feat(ui):` / `fix(ui):` / `test(ui):` / `docs:`),尾行 `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`。

---

### Task 0: 建分支 + 基线验证

**Files:** 无代码改动

**Interfaces:**
- Produces: 分支 `ui/batch3`(后续全部任务在此分支提交)

- [ ] **Step 1: 建分支**

```bash
git checkout -b ui/batch3
```

- [ ] **Step 2: 基线全绿(必须通过才继续)**

```bash
cd app
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
```

Expected: analyze 零告警;test 233 全绿(批次②收官的基线数字)。

---

### Task 1: 规则文档升 v1.2 + 附录 B(§9 边界流程,先于代码)

**Files:**
- Modify: `docs/superpowers/specs/2026-09-15-ui-design-language-design.md`(头部状态行 + 文末追加附录 B)

**Interfaces:**
- Produces: 附录 B 条款(后续任务所有新数值的规则依据:B.1 横滑条 / B.2 聊天顶栏 62 / B.3 气泡 18·6·72% / B.4 输入框 40 / B.5 时间条与灰条 / B.6 渐变双气泡 / B.7 系统通知行 / B.8 首字占位)

- [ ] **Step 1: 改头部状态行**

第 4 行原文:

```markdown
状态:**v1.1(2026-09-19 增补附录 A:发现页落地补充),设计内容已获用户批准**(浏览器视觉评审通过);本文件是**常驻规则文档**
```

改为:

```markdown
状态:**v1.2(2026-09-19 增补附录 B:消息/聊天页落地补充),设计内容已获用户批准**(浏览器视觉评审通过);本文件是**常驻规则文档**
```

- [ ] **Step 2: 文末追加附录 B(整段粘贴)**

```markdown
## 附录 B:消息/聊天页落地补充(2026-09-19,批次③)

本附录是 §9 边界流程的产出:以下场景规则正文未覆盖,经浏览器模拟图评审确认后定稿;后续页面遇同类场景以此为准。

### B.1 最近联系人横滑条(消息页专属)

- 高 88;水平内边距 16、间距 14;**头像 48**(首字占位,见 B.8)+ 在线呼吸点 11(白描边);名字 12 `text2` 居中、宽 56 截断;无会话整条隐藏(不含系统通知)

### B.2 聊天页顶栏

- 高 **62**(§5.2 二级页 52 的**例外**,为「名字 + 状态」两行留空间);返回箭头 22 `text1`;右侧无按钮(资料入口 = 点名字)
- 标题区两行居中:名字 17/w600 `text1` + 状态行 12:在线 = 8px 绿点(`green` 呼吸)+「在线」`text2`;离线 =「x 分钟前在线」`text2`;状态未知 = 不渲染状态行、名字单行居中

### B.3 聊天气泡

- 自己:brand 实底白字;对方:白底(`bgCard`)`text1`;**R18,靠头像侧上角 6**;内边距 12/14;最大宽 **72%**
- 头像 40 圆形(§5.3);图片消息 140×140、R12;发送失败 = `error_rounded` 20 `danger`
- 灰条(配对/封禁提示):`divider` 底、`text2` 字、全圆角、内边距 6×12、12 号

### B.4 聊天输入栏

- 输入框高 **40**(§7 输入框 52 的**聊天场景例外**)、R16、1px `divider` 描边、聚焦 1.5px `brand` + 光晕 `rgba(255,44,85,.12)`
- 发送 = **纯图标** 24 `send_rounded`:输入为空 `text3`、有字 `brand`;表情/＋ = rounded 24 `text2`
- 表情面板 / ＋面板:白底 + 顶部 1px `divider` 分隔线;＋面板入口块 56、R16、`brand` 12% 底、图标 `brand`

### B.5 时间条与灰条(消息页/聊天页)

- 时间条:12 `text3` 居中、上下边距 12
- 消息页系统通知行:圆头像 `gradientSystem` 渐变底 + 白铃铛 24;「官方」标 = `violet` 描边 1px、10/w500、R8
- 消息页会话行:高 72;头像 48;行名 16/w600;预览 13 `text2`;右侧时间 12 `text3` + 渐变角标(AppBadge)

### B.6 空态插画「渐变双气泡」(ChatBubblesMark)

- 渐变大气泡(`gradientHeart`)+ 白色小气泡(错落叠放,各带小尾巴),约 118 宽,**静态**;消息/聊天空态大号元素以此为默认,与发现页 HeartRipple 并列

### B.7 头像首字占位(AppAvatar.fallbackText)

- 无图且给了名字时:底 = `brand`/`violet`/`green`/`amber` 各 12% 透明度(按名字内容稳定映射,同一人始终同色)、首字 `text1`;不给名字时保持「`divider` 底 + person 图标」

### B.8 错误态(AppErrorView)

- 标题 17/w600 + 原因 13 `text2` 居中 + 可选「重试」次按钮;错误原因一律取接口中文 message,非 ApiException 兜底「加载失败,稍后再试」;**禁止显示裸异常串**
```

- [ ] **Step 3: 提交**

```bash
git add docs/superpowers/specs/2026-09-15-ui-design-language-design.md
git commit -m "$(cat <<'EOF'
docs: 「心跳」规则升 v1.2,新增附录 B(消息/聊天页落地补充:横滑条/顶栏 62/气泡 18·72%/输入框 40/渐变双气泡/首字占位/错误态)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `apiMessageOf` + `AppErrorView` 组件,发现页换用

**Files:**
- Modify: `app/lib/core/api_exception.dart`(追加顶层函数)
- Create: `app/lib/core/widgets/app_error_view.dart`
- Create: `app/test/core/widgets/app_error_view_test.dart`
- Modify: `app/lib/features/discovery/discovery_page.dart`(删 `_messageOf` 与 `_ErrorView`,两处 error 分支换 `AppErrorView`)

**Interfaces:**
- Produces: `String apiMessageOf(Object error)`(core/api_exception.dart);`AppErrorView({Key? key, String title = '没能加载出来', required String message, VoidCallback? onRetry, Key? retryKey})`
- Consumes: `AppButton`(已有,`variant: AppButtonVariant.secondary`)

- [ ] **Step 1: 写失败测试**

Create `app/test/core/widgets/app_error_view_test.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/api_exception.dart';
import 'package:chatapp_app/core/widgets/app_error_view.dart';

void main() {
  testWidgets('渲染标题、原因与重试回调', (tester) async {
    var retried = 0;
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: AppErrorView(
          message: '网络开小差了',
          retryKey: const Key('demo.retry'),
          onRetry: () => retried++,
        ),
      ),
    ));
    expect(find.text('没能加载出来'), findsOneWidget);
    expect(find.text('网络开小差了'), findsOneWidget);
    await tester.tap(find.byKey(const Key('demo.retry')));
    expect(retried, 1);
  });

  testWidgets('不给 onRetry 时不渲染重试', (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(body: AppErrorView(message: '没网')),
    ));
    expect(find.text('重试'), findsNothing);
  });

  test('apiMessageOf:ApiException 取 message,其他兜底', () {
    expect(apiMessageOf(ApiException('对方的消息')), '对方的消息');
    expect(apiMessageOf(Exception('boom')), '加载失败,稍后再试');
  });
}
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd app
../flutter/bin/flutter.bat test test/core/widgets/app_error_view_test.dart
```

Expected: 编译失败(`app_error_view.dart` 不存在、`apiMessageOf` 未定义)。

- [ ] **Step 3: 实现**

在 `app/lib/core/api_exception.dart` 末尾追加:

```dart
/// 错误展示统一入口:ApiException 取其中文 message,其他异常兜底。
String apiMessageOf(Object error) =>
    error is ApiException ? error.message : '加载失败,稍后再试';
```

Create `app/lib/core/widgets/app_error_view.dart`:

```dart
import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_spacing.dart';
import '../theme/app_typography.dart';
import 'app_button.dart';

/// 「心跳」附录 B.8 错误态:标题 17/w600 + 原因 13 text2 + 可选「重试」。
/// 页面统一用它;原因取接口中文 message,不显示裸异常串。
class AppErrorView extends StatelessWidget {
  const AppErrorView({
    super.key,
    this.title = '没能加载出来',
    required this.message,
    this.onRetry,
    this.retryKey,
  });

  final String title;
  final String message;
  final VoidCallback? onRetry;
  final Key? retryKey;

  @override
  Widget build(BuildContext context) => Center(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.xxl),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(title, style: AppText.subtitle.copyWith(fontSize: 17)),
              const SizedBox(height: AppSpacing.sm),
              Text(
                message,
                textAlign: TextAlign.center,
                style: AppText.caption.copyWith(color: AppColors.text2),
              ),
              if (onRetry != null) ...[
                const SizedBox(height: AppSpacing.lg),
                AppButton(
                  key: retryKey,
                  label: '重试',
                  variant: AppButtonVariant.secondary,
                  onPressed: onRetry,
                ),
              ],
            ],
          ),
        ),
      );
}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd app
../flutter/bin/flutter.bat test test/core/widgets/app_error_view_test.dart
```

Expected: 3 用例 PASS。

- [ ] **Step 5: 发现页换用共享组件**

`app/lib/features/discovery/discovery_page.dart`:

1. 顶部删除:

```dart
/// 错误统一取 ApiException 的中文 message(不显示裸异常串)。
String _messageOf(Object error) =>
    error is ApiException ? error.message : '加载失败,稍后再试';
```

2. 文件末尾删除整个 `_ErrorView` 类(第 168–201 行)。
3. import 调整:`import '../../core/api_exception.dart';` 保留(改成供 `apiMessageOf` 使用前仍需要——`ApiException` 在 `_decide` 里还被 catch,保留);新增 `import '../../core/widgets/app_error_view.dart';`。
4. 两处 error 分支改为:

```dart
error: (error, _) => AppErrorView(
  message: apiMessageOf(error),
  onRetry: () => ref.read(profileProvider.notifier).reload(),
),
```

```dart
error: (error, _) => AppErrorView(
  message: apiMessageOf(error),
  onRetry: () => ref.read(discoveryProvider.notifier).reload(),
),
```

- [ ] **Step 6: 跑发现页测试 + 全量**

```bash
cd app
../flutter/bin/flutter.bat test test/features/discovery
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
```

Expected: discovery 33 用例全绿(错误态用例断言标题「没能加载出来」与「重试」文字,不受组件搬家影响);analyze 零告警;全量 236 绿(233 + 新增 3)。

- [ ] **Step 7: 提交**

```bash
git add app/lib/core/api_exception.dart app/lib/core/widgets/app_error_view.dart app/test/core/widgets/app_error_view_test.dart app/lib/features/discovery/discovery_page.dart
git commit -m "$(cat <<'EOF'
feat(ui): 提炼共享 AppErrorView + apiMessageOf,发现页换用(第三份错误态出现时提炼)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `AppAvatar.fallbackText` 首字占位

**Files:**
- Modify: `app/lib/core/widgets/app_avatar.dart`
- Modify: `app/test/core/widgets/app_avatar_test.dart`

**Interfaces:**
- Produces: `AppAvatar({..., String? fallbackText})`——无图且 `fallbackText` 非空时,占位 = 首字 + 柔色底(4 色 token 12%,按名字稳定映射);不传时保持原「divider 底 + person_rounded」。
- 消费方(本批):消息页横滑条/会话行、聊天气泡头像。

- [ ] **Step 1: 写失败测试**

在 `app/test/core/widgets/app_avatar_test.dart` 的 `main()` 里追加:

```dart
  testWidgets('fallbackText:无图时显示首字、不显示人形图标', (tester) async {
    await tester.pumpWidget(wrap(const AppAvatar(fallbackText: '小雨')));
    expect(find.text('小'), findsOneWidget);
    expect(find.byIcon(Icons.person_rounded), findsNothing);
  });

  testWidgets('不给 fallbackText 时仍是人形图标占位', (tester) async {
    await tester.pumpWidget(wrap(const AppAvatar(imageUrl: null, fallbackText: null)));
    expect(find.byIcon(Icons.person_rounded), findsOneWidget);
  });
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd app
../flutter/bin/flutter.bat test test/core/widgets/app_avatar_test.dart
```

Expected: 编译失败(`fallbackText` 参数不存在)。

- [ ] **Step 3: 实现**

`app/lib/core/widgets/app_avatar.dart`:

1. 构造器加参数:

```dart
  const AppAvatar({
    super.key,
    this.imageUrl,
    this.size = 48,
    this.halo = false,
    this.showOnlineDot = false,
    this.dotBorderColor = Colors.white,
    this.fallbackText,
  });
```

```dart
  /// 无图时的首字占位(附录 B.7);为空则保持人形图标占位。
  final String? fallbackText;
```

2. 新增 import `import '../theme/app_typography.dart';`
3. 类内加色板与改 `_placeholder`:

```dart
  static const _fallbackTints = [
    AppColors.brand,
    AppColors.violet,
    AppColors.green,
    AppColors.amber,
  ];
```

```dart
  Widget _placeholder() {
    final text = fallbackText;
    if (text == null || text.isEmpty) {
      return Container(
        color: AppColors.divider,
        child: Center(
          child: Icon(Icons.person_rounded, color: AppColors.text3, size: size * 0.6),
        ),
      );
    }
    final tint = _fallbackTints[
        text.codeUnits.fold<int>(0, (sum, unit) => sum + unit) % _fallbackTints.length];
    return Container(
      color: tint.withValues(alpha: 0.12),
      child: Center(
        child: Text(
          text.substring(0, 1),
          style: AppText.subtitle.copyWith(fontSize: size * 0.38, color: AppColors.text1),
        ),
      ),
    );
  }
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd app
../flutter/bin/flutter.bat test test/core/widgets/app_avatar_test.dart
../flutter/bin/flutter.bat test
```

Expected: 组件 5 用例 PASS;全量 238 绿。

- [ ] **Step 5: 提交**

```bash
git add app/lib/core/widgets/app_avatar.dart app/test/core/widgets/app_avatar_test.dart
git commit -m "$(cat <<'EOF'
feat(ui): AppAvatar 支持 fallbackText 首字柔色占位(消息列表/聊天气泡人像基础)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: `ChatBubblesMark` 空态插画

**Files:**
- Create: `app/lib/features/chat/widgets/chat_bubbles_mark.dart`
- Create: `app/test/features/chat/chat_bubbles_mark_test.dart`

**Interfaces:**
- Produces: `ChatBubblesMark({Key? key, double size = 118})`——静态 CustomPaint,渐变大气泡(`brand`→`heartOrange`)+ 白色小气泡(描边 `divider`)+ 双小尾。
- 消费方(本批):消息页空态、聊天页空态。

- [ ] **Step 1: 写失败测试**

Create `app/test/features/chat/chat_bubbles_mark_test.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/chat/widgets/chat_bubbles_mark.dart';

void main() {
  testWidgets('渲染渐变双气泡插画(静态,可直接 settle)', (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(body: Center(child: ChatBubblesMark())),
    ));
    await tester.pumpAndSettle();

    expect(find.byType(ChatBubblesMark), findsOneWidget);
    expect(find.byType(CustomPaint), findsWidgets);
  });
}
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd app
../flutter/bin/flutter.bat test test/features/chat/chat_bubbles_mark_test.dart
```

Expected: 编译失败(文件不存在)。

- [ ] **Step 3: 实现**

Create `app/lib/features/chat/widgets/chat_bubbles_mark.dart`:

```dart
import 'dart:ui' as ui;

import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';

/// 「心跳」附录 B.6 空态插画:渐变大气泡 + 白色小气泡(各带小尾),静态。
/// 消息页/聊天页空态的大号元素;发现页的 HeartRipple 仍归发现页。
class ChatBubblesMark extends StatelessWidget {
  const ChatBubblesMark({super.key, this.size = 118});

  final double size;

  @override
  Widget build(BuildContext context) => SizedBox(
        width: size,
        height: size * 0.88,
        child: CustomPaint(painter: _BubblesPainter()),
      );
}

class _BubblesPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final w = size.width;
    final h = size.height;

    // 白色小气泡(右上,先画、被渐变气泡压住一角)
    final back = RRect.fromRectAndRadius(
      Rect.fromLTWH(w * 0.36, 0, w * 0.62, h * 0.52),
      Radius.circular(w * 0.14),
    );
    final white = Paint()..color = AppColors.bgCard;
    final backTail = Path()
      ..moveTo(w * 0.86, h * 0.44)
      ..lineTo(w * 0.97, h * 0.60)
      ..lineTo(w * 0.78, h * 0.54)
      ..close();
    canvas.drawPath(backTail, white);
    canvas.drawRRect(back, white);
    canvas.drawRRect(
      back,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1
        ..color = AppColors.divider,
    );

    // 渐变大气泡(左下)
    final frontRect = Rect.fromLTWH(0, h * 0.36, w * 0.76, h * 0.60);
    final front = RRect.fromRectAndRadius(
      frontRect,
      Radius.circular(w * 0.17),
    );
    final heart = Paint()
      ..shader = ui.Gradient.linear(
        frontRect.topLeft,
        frontRect.bottomRight,
        const [AppColors.brand, AppColors.heartOrange],
      );
    final frontTail = Path()
      ..moveTo(w * 0.20, h * 0.90)
      ..lineTo(w * 0.09, h)
      ..lineTo(w * 0.34, h * 0.955)
      ..close();
    canvas.drawPath(frontTail, heart);
    canvas.drawRRect(front, heart);
  }

  @override
  bool shouldRepaint(covariant _BubblesPainter oldDelegate) => false;
}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd app
../flutter/bin/flutter.bat test test/features/chat/chat_bubbles_mark_test.dart
../flutter/bin/flutter.bat analyze
```

Expected: PASS + 零告警。

- [ ] **Step 5: 提交**

```bash
git add app/lib/features/chat/widgets/chat_bubbles_mark.dart app/test/features/chat/chat_bubbles_mark_test.dart
git commit -m "$(cat <<'EOF'
feat(ui): 新增空态插画 ChatBubblesMark(渐变双气泡,静态)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: 骨架组件 ×2 + `AppRadius.bubble` token

**Files:**
- Modify: `app/lib/core/theme/app_radius.dart`(+`bubble = 18`)
- Create: `app/lib/features/chat/widgets/chats_skeleton.dart`
- Create: `app/lib/features/chat/widgets/chat_skeleton.dart`
- Create: `app/test/features/chat/skeletons_test.dart`

**Interfaces:**
- Produces: `ChatsSkeleton()`(key `chats.skeleton`,6 行:48 圆块 + 两文字条);`ChatSkeleton()`(key `chat.skeleton`,4 行左右交错:40 圆块 + 气泡块);`AppRadius.bubble = 18.0`
- Consumes: `AppSkeleton({width, height, radius})`(已有)

- [ ] **Step 1: 写失败测试**

Create `app/test/features/chat/skeletons_test.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/chat/widgets/chat_skeleton.dart';
import 'package:chatapp_app/features/chat/widgets/chats_skeleton.dart';

Widget _wrap(Widget child) => MaterialApp(home: Scaffold(body: child));

void main() {
  // 骨架屏是无限呼吸动画:只用有限 pump,禁 pumpAndSettle(pitfalls/testing.md)。
  testWidgets('消息页骨架渲染', (tester) async {
    await tester.pumpWidget(_wrap(const ChatsSkeleton()));
    await tester.pump(const Duration(milliseconds: 100));

    expect(find.byKey(const Key('chats.skeleton')), findsOneWidget);
  });

  testWidgets('聊天页骨架渲染', (tester) async {
    await tester.pumpWidget(_wrap(const ChatSkeleton()));
    await tester.pump(const Duration(milliseconds: 100));

    expect(find.byKey(const Key('chat.skeleton')), findsOneWidget);
  });
}
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd app
../flutter/bin/flutter.bat test test/features/chat/skeletons_test.dart
```

Expected: 编译失败(两个文件不存在)。

- [ ] **Step 3: 实现**

`app/lib/core/theme/app_radius.dart` 追加:

```dart
  static const bubble = 18.0; // 聊天气泡(附录 B.3)
```

Create `app/lib/features/chat/widgets/chats_skeleton.dart`:

```dart
import 'package:flutter/material.dart';

import '../../../core/theme/app_radius.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/widgets/app_skeleton.dart';

/// 消息页行骨架:圆头像块 + 两行文字条 ×6。
/// 呼吸动画为无限循环——可见它的测试只用有限 pump。
class ChatsSkeleton extends StatelessWidget {
  const ChatsSkeleton({super.key});

  @override
  Widget build(BuildContext context) => Column(
        key: const Key('chats.skeleton'),
        children: [
          for (var i = 0; i < 6; i++)
            const Padding(
              padding: EdgeInsets.symmetric(
                  horizontal: AppSpacing.pageH, vertical: AppSpacing.md),
              child: Row(
                children: [
                  AppSkeleton(width: 48, height: 48, radius: AppRadius.full),
                  SizedBox(width: AppSpacing.md),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        AppSkeleton(width: 120, height: 14),
                        SizedBox(height: AppSpacing.sm),
                        AppSkeleton(width: 180, height: 12),
                      ],
                    ),
                  ),
                ],
              ),
            ),
        ],
      );
}
```

Create `app/lib/features/chat/widgets/chat_skeleton.dart`:

```dart
import 'package:flutter/material.dart';

import '../../../core/theme/app_radius.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/widgets/app_skeleton.dart';

/// 聊天页消息骨架:左右交错的头像圆块 + 气泡块 ×4。
/// 呼吸动画为无限循环——可见它的测试只用有限 pump。
class ChatSkeleton extends StatelessWidget {
  const ChatSkeleton({super.key});

  @override
  Widget build(BuildContext context) => Padding(
        key: const Key('chat.skeleton'),
        padding: const EdgeInsets.all(AppSpacing.lg),
        child: const Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _BubbleRow(alignEnd: false, bubbleWidth: 180),
            _BubbleRow(alignEnd: true, bubbleWidth: 140),
            _BubbleRow(alignEnd: false, bubbleWidth: 220),
            _BubbleRow(alignEnd: true, bubbleWidth: 160),
          ],
        ),
      );
}

class _BubbleRow extends StatelessWidget {
  const _BubbleRow({required this.alignEnd, required this.bubbleWidth});

  final bool alignEnd;
  final double bubbleWidth;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: AppSpacing.md),
        child: Row(
          mainAxisAlignment:
              alignEnd ? MainAxisAlignment.end : MainAxisAlignment.start,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (!alignEnd) ...[
              const AppSkeleton(width: 40, height: 40, radius: AppRadius.full),
              const SizedBox(width: AppSpacing.sm),
            ],
            AppSkeleton(width: bubbleWidth, height: 40, radius: AppRadius.bubble),
            if (alignEnd) ...[
              const SizedBox(width: AppSpacing.sm),
              const AppSkeleton(width: 40, height: 40, radius: AppRadius.full),
            ],
          ],
        ),
      );
}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd app
../flutter/bin/flutter.bat test test/features/chat/skeletons_test.dart
../flutter/bin/flutter.bat analyze
```

Expected: PASS + 零告警。

- [ ] **Step 5: 提交**

```bash
git add app/lib/core/theme/app_radius.dart app/lib/features/chat/widgets/chats_skeleton.dart app/lib/features/chat/widgets/chat_skeleton.dart app/test/features/chat/skeletons_test.dart
git commit -m "$(cat <<'EOF'
feat(ui): 消息页/聊天页呼吸骨架组件 + AppRadius.bubble token

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: 消息页页壳(大标题 / 骨架 / 错误 / 空态)+ harness `overrides` 参数

**Files:**
- Modify: `app/test/support/harness.dart`(`pumpApp` 加 `overrides` 可选参数)
- Modify: `app/lib/features/chat/chats_page.dart`(页壳部分)
- Modify: `app/test/features/chat/chats_page_test.dart`(新增骨架接线用例;错误用例保持)

**Interfaces:**
- Consumes: `ChatsSkeleton`(T5)、`AppErrorView`/`apiMessageOf`(T2)、`ChatBubblesMark`(T4)、`AppEmptyState`
- Produces: `pumpApp(..., List<Override> overrides = const [])`(后续任务沿用);消息页四态(标题 32/w800、骨架、错误、空态)

- [ ] **Step 1: harness 扩展**

`app/test/support/harness.dart` 的 `pumpApp` 签名与 overrides 列表改为:

```dart
Future<FakeImClient> pumpApp(WidgetTester tester, ScriptedAdapter adapter,
    {Map<String, Object> prefs = const {},
    FakeImClient? imClient,
    List<Override> overrides = const []}) async {
```

```dart
    overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(refreshDio),
      imClientProvider.overrideWithValue(fake),
      // 默认关掉登录态心跳:避免测试里周期性假请求干扰用例,心跳用例自己 override
      heartbeatIntervalProvider.overrideWithValue(null),
      // 同样默认关掉在线状态的周期刷新;需要测定时的用例自己 override
      presenceRefreshIntervalProvider.overrideWithValue(null),
      ...overrides,
    ],
```

- [ ] **Step 2: 写失败测试(chats_page_test 追加)**

在 `app/test/features/chat/chats_page_test.dart` 顶部 import 区追加:

```dart
import 'package:chatapp_app/features/chat/widgets/chats_skeleton.dart';
import 'package:chatapp_app/im/im_manager.dart';
```

并在 `main()` 前追加:

```dart
/// IM 一直处于连接中,用来验证骨架态接线(不让登录完成)。
class _ConnectingImManager extends ImManager {
  @override
  ImStatus build() => const ImConnecting();

  // 启动流程会调 login():压住不让真实登录把状态推进到已登录
  @override
  Future<void> login() async {}

  @override
  Future<void> retry() async {}
}
```

`main()` 末尾追加用例:

```dart
  testWidgets('IM 连接中 → 行骨架(有限 pump,不 settle)', (tester) async {
    final fake = FakeImClient()..conversations = [_conversation()];
    await pumpApp(tester, _adapter(),
        prefs: _loggedIn,
        imClient: fake,
        overrides: [imStatusProvider.overrideWith(_ConnectingImManager.new)]);
    await pumpFrames(tester);
    await tester.tap(navTab('消息'));
    await pumpFrames(tester);

    expect(find.byType(ChatsSkeleton), findsOneWidget);
  });
```

- [ ] **Step 3: 跑测试确认失败**

```bash
cd app
../flutter/bin/flutter.bat test test/features/chat/chats_page_test.dart
```

Expected: 编译失败(`overrides` 参数不存在 / `ChatsSkeleton` 未接线)。先确认 harness 已加参数后,该用例应 FAIL(找不到 ChatsSkeleton,现实现是转圈)。

- [ ] **Step 4: 实现页壳**

`app/lib/features/chat/chats_page.dart` 顶部 import 追加:

```dart
import '../../core/api_exception.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_typography.dart';
import '../../core/widgets/app_empty_state.dart';
import '../../core/widgets/app_error_view.dart';
import 'widgets/chat_bubbles_mark.dart';
import 'widgets/chats_skeleton.dart';
```

`ChatsPage.build` 改为:

```dart
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final status = ref.watch(imStatusProvider);
    return Scaffold(
      body: SafeArea(
        bottom: false,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(
                  AppSpacing.pageH, AppSpacing.lg, AppSpacing.pageH, AppSpacing.md),
              child: Text('消息',
                  style: AppText.display.copyWith(color: AppColors.text1)),
            ),
            Expanded(
              child: switch (status) {
                ImConnecting() => const ChatsSkeleton(),
                ImFailed(:final message) => AppErrorView(
                    message: message,
                    retryKey: const Key('chats.retry'),
                    onRetry: () => ref.read(imStatusProvider.notifier).retry(),
                  ),
                _ => const _ConversationList(),
              },
            ),
          ],
        ),
      ),
    );
  }
```

删除 `_FailedView` 类。`_ConversationList` 的 loading 与 error 分支改为:

```dart
      loading: () => const ChatsSkeleton(),
      error: (error, _) => AppErrorView(
        message: apiMessageOf(error),
        retryKey: const Key('chats.retry'),
        onRetry: () => ref.read(conversationsProvider.notifier).reload(),
      ),
```

`data` 分支空列表处改为:

```dart
        if (items.isEmpty) {
          return const Center(
            child: AppEmptyState(
              mark: ChatBubblesMark(),
              title: '还没有消息',
              description: '互相喜欢之后就能开聊了',
            ),
          );
        }
```

并删除 `_EmptyView` 类。

- [ ] **Step 5: 跑测试确认通过**

```bash
cd app
../flutter/bin/flutter.bat test test/features/chat/chats_page_test.dart
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
```

Expected: chats_page 10 用例全绿(空态「还没有消息」、IM 失败 `6001`+`chats.retry` 不变);analyze 零告警;全量 242 绿。

- [ ] **Step 6: 提交**

```bash
git add app/test/support/harness.dart app/lib/features/chat/chats_page.dart app/test/features/chat/chats_page_test.dart
git commit -m "$(cat <<'EOF'
feat(ui): 消息页页壳改心跳规格(display 大标题/骨架/AppErrorView/双气泡空态),harness 支持 overrides

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: 消息页列表重制(横滑条 / 系统通知行 / 会话行 / 渐变角标)

**Files:**
- Modify: `app/lib/features/chat/chats_page.dart`(`_RecentStrip`、`_SystemNoticeTile`、`_ConversationTile`、`_TimeBadge`;删 `_Avatar`、`_UnreadBadge`)
- Modify: `app/test/features/chat/chats_page_test.dart`(在线点断言 OnlineDot→BreathingDot;两个在线用例改有限 pump)

**Interfaces:**
- Consumes: `AppAvatar(fallbackText:)`(T3)、`BreathingDot`(`core/widgets/breathing_dot.dart`)、`AppBadge`、`AppGradients.system`、`AppText` 字阶
- Produces: 消息页列表全行心跳规格;presence 在线 = `BreathingDot` ×2(横滑条 + 行)

- [ ] **Step 1: 更新测试(先红)**

`app/test/features/chat/chats_page_test.dart`:

1. import 改动:删 `import 'package:chatapp_app/features/presence/online_dot.dart';`,加 `import 'package:chatapp_app/core/widgets/breathing_dot.dart';`。
2. `'在线的人头像带绿点;离线与系统通知没有'` 用例改为:

```dart
  testWidgets('在线的人头像带绿点;离线与系统通知没有', (tester) async {
    final fake = FakeImClient()..conversations = [_conversation(), _systemConversation()];
    final adapter = _adapter();
    adapter.routes['GET /presence'] = (options) => ok({
          'results': [
            {'user_id': 9, 'online': true, 'last_active_at': '2026-09-13T14:30:00+08:00'},
          ],
        });
    await pumpApp(tester, adapter, prefs: _loggedIn, imClient: fake);
    await pumpFrames(tester);
    await tester.tap(navTab('消息'));
    await pumpFrames(tester);

    // 横滑条 + 列表行各一个呼吸点;系统通知(非真人)没有。呼吸点是无限动画,禁 settle。
    expect(find.byType(BreathingDot), findsNWidgets(2));
  });
```

3. `'配对缓存为空时在线状态照常显示(公开,不依赖配对)'` 用例同样把三处 `pumpAndSettle()` 换成 `pumpFrames(tester)`,`expect(find.byType(OnlineDot), findsNWidgets(2));` 改为 `expect(find.byType(BreathingDot), findsNWidgets(2));`。
4. `'离线不显示绿点'` 用例:`expect(find.byType(OnlineDot), findsNothing);` → `expect(find.byType(BreathingDot), findsNothing);`(无在线者,pumpAndSettle 可保留)。

- [ ] **Step 2: 跑测试确认失败**

```bash
cd app
../flutter/bin/flutter.bat test test/features/chat/chats_page_test.dart
```

Expected: `在线的人头像带绿点` FAIL(findsNWidgets(2) 实际 0——还是旧 `OnlineDot`)。

- [ ] **Step 3: 实现列表**

`app/lib/features/chat/chats_page.dart`:

1. 顶部 import 追加:

```dart
import '../../core/theme/app_gradients.dart';
import '../../core/widgets/app_avatar.dart';
import '../../core/widgets/app_badge.dart';
```

删 `import '../presence/online_dot.dart';`(在线点由 `AppAvatar` 内建的 `BreathingDot` 承担)。

2. `_RecentStrip` 整个 build 替换:

```dart
  @override
  Widget build(BuildContext context) {
    final recent = friends.take(10).toList();
    return SizedBox(
      height: 88,
      child: ListView.separated(
        key: const Key('chats.strip'),
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.fromLTRB(
            AppSpacing.pageH, AppSpacing.xs, AppSpacing.pageH, AppSpacing.md),
        itemCount: recent.length,
        separatorBuilder: (_, _) => const SizedBox(width: 14),
        itemBuilder: (context, index) {
          final conversation = recent[index];
          final name =
              displayNameFor(cache, conversation.peerId, imName: conversation.showName);
          final avatar =
              avatarUrlFor(cache, conversation.peerId, imFaceUrl: conversation.faceUrl);
          final uid = userIdFromImId(conversation.peerId);
          final online = uid != null && (presenceById[uid]?.online ?? false);
          return InkWell(
            key: Key('chats.stripItem:${conversation.peerId}'),
            onTap: () => context.push('/chat/${conversation.peerId}'),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                AppAvatar(
                    imageUrl: avatar,
                    size: 48,
                    showOnlineDot: online,
                    fallbackText: name),
                const SizedBox(height: AppSpacing.xs),
                SizedBox(
                  width: 56,
                  child: Text(
                    name,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    textAlign: TextAlign.center,
                    style: AppText.micro.copyWith(color: AppColors.text2),
                  ),
                ),
              ],
            ),
          );
        },
      ),
    );
  }
```

3. `_SystemNoticeTile` 的 leading / title / subtitle 替换为:

```dart
      leading: Container(
        width: 48,
        height: 48,
        decoration: const BoxDecoration(
          shape: BoxShape.circle,
          gradient: AppGradients.system,
        ),
        child: const Icon(Icons.notifications_rounded, color: Colors.white, size: 24),
      ),
      title: Row(
        children: [
          Text('系统通知', style: AppText.subtitle),
          const SizedBox(width: AppSpacing.sm),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
            decoration: BoxDecoration(
              border: Border.all(color: AppColors.violet),
              borderRadius: BorderRadius.circular(AppRadius.chip),
            ),
            child: Text('官方',
                style: AppText.micro.copyWith(
                    fontSize: 10,
                    fontWeight: FontWeight.w500,
                    color: AppColors.violet)),
          ),
        ],
      ),
      subtitle: Text(_previewOf(last),
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: AppText.caption.copyWith(color: AppColors.text2)),
```

(需 import `'../../core/theme/app_radius.dart';`)

4. `_ConversationTile` 替换为:

```dart
    return ListTile(
      key: Key('chats.tile:${conversation.peerId}'),
      onTap: () => context.push('/chat/${conversation.peerId}'),
      leading: AppAvatar(
          imageUrl: avatar, size: 48, showOnlineDot: online, fallbackText: name),
      title: Text(name,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: AppText.subtitle.copyWith(color: AppColors.text1)),
      subtitle: Text(_previewOf(conversation.lastMessage),
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: AppText.caption.copyWith(color: AppColors.text2)),
      trailing: _TimeBadge(last: conversation.lastMessage, unread: conversation.unreadCount),
    );
```

5. `_TimeBadge` 替换为:

```dart
  @override
  Widget build(BuildContext context) => Column(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          if (last != null)
            Text(
              formatMessageTime(DateTime.fromMillisecondsSinceEpoch(last!.timestamp)),
              style: AppText.micro.copyWith(color: AppColors.text3),
            ),
          const SizedBox(height: AppSpacing.xs),
          AppBadge(count: unread),
        ],
      );
```

6. 删除 `_Avatar`、`_UnreadBadge` 两个类;`_ConversationList` 里系统通知与列表之间的色带改 `Container(height: AppSpacing.sm, color: AppColors.bgPage)`;分割线 `Color(0xFFF5F6F7)` → `AppColors.divider`。

- [ ] **Step 4: 跑测试确认通过**

```bash
cd app
../flutter/bin/flutter.bat test test/features/chat/chats_page_test.dart
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
```

Expected: chats_page 10 用例全绿;analyze 零告警;全量 242 绿。

- [ ] **Step 5: 提交**

```bash
git add app/lib/features/chat/chats_page.dart app/test/features/chat/chats_page_test.dart
git commit -m "$(cat <<'EOF'
feat(ui): 消息页列表心跳化(横滑条 AppAvatar+呼吸点/系统通知渐变头像+官方标/会话行/渐变角标)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: 聊天页顶栏(两行居中,删「⋯」)

**Files:**
- Modify: `app/lib/features/chat/chat_page.dart`(去 `AppBar`,加 `_ChatHeader`;删 `chat.more` IconButton)
- Modify: `app/test/features/chat/chat_page_test.dart`(`pumpChat` 加 `settle` 参数;在线用例改断言)

**Interfaces:**
- Consumes: `BreathingDot`、`AppText`、`AppColors`、`presenceLabel`(离线文案,不改函数本身)
- Produces: `_ChatHeader`(key `chat.title` 在名字上、key `chat.back` 在返回钮);在线状态 = key `chat.onlineDot` + 文案「在线」

- [ ] **Step 1: 更新测试(先红)**

`app/test/features/chat/chat_page_test.dart`:

1. `pumpChat` 加 `settle` 参数(尾部两行改):

```dart
  Future<void> pumpChat(WidgetTester tester,
      {String peerId = 'u9', PickImage? pickImage, bool settle = true}) async {
```

```dart
    await tester.pumpWidget(UncontrolledProviderScope(
      container: container,
      child: MaterialApp.router(routerConfig: router),
    ));
    if (settle) {
      await tester.pumpAndSettle();
    } else {
      await pumpFrames(tester); // 含无限动画(在线呼吸点)时用有限推进
    }
  }
```

(import 行加 `import '../../support/harness.dart';`——`pumpFrames` 在 harness 里。)

2. `'对方在线 → 标题下「● 在线」'` 改为:

```dart
  testWidgets('对方在线 → 标题下呼吸绿点 + 「在线」', (tester) async {
    adapter.routes['GET /presence'] = (options) => ok({
          'results': [
            {'user_id': 9, 'online': true, 'last_active_at': '2026-09-13T14:30:00+08:00'},
          ],
        });
    await pumpChat(tester, settle: false);

    expect(find.byKey(const Key('chat.onlineDot')), findsOneWidget);
    expect(find.text('在线'), findsOneWidget);
  });
```

3. `'没有配对缓存时标题仍显示在线状态(公开,不依赖配对)'` 改为 `await pumpChat(tester, settle: false);` + 同样两个断言(原本是 `find.text('● 在线')`,改为 `find.byKey(const Key('chat.onlineDot'))` 一行即可)。
4. `'拿不到状态 → 不显示小字'` 的 `expect(find.text('● 在线'), findsNothing);` 改为 `expect(find.text('在线'), findsNothing);`。

- [ ] **Step 2: 跑测试确认失败**

```bash
cd app
../flutter/bin/flutter.bat test test/features/chat/chat_page_test.dart
```

Expected: 在线用例 FAIL(找不到 chat.onlineDot)。

- [ ] **Step 3: 实现顶栏**

`app/lib/features/chat/chat_page.dart`:

1. import 追加:

```dart
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/theme/app_typography.dart';
import '../../core/widgets/breathing_dot.dart';
```

2. `build` 中 `return Scaffold(appBar: AppBar(...), body: Column(...))` 改为(`appBar:` 整块删除,含 `chat.more` IconButton):

```dart
    return Scaffold(
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            _ChatHeader(
              name: peerName,
              presence: peerPresence,
              onTapTitle: () => _openProfile(context, cache),
            ),
            Expanded(
```

(Column 的其余 children 原样保留:Expanded(messages.when(...))、`_InputBar`、`if (_showEmoji) ... else if (_showMore) ...`。)

3. 文件内新增 `_ChatHeader`:

```dart
/// 「心跳」附录 B.2:高 62;返回 22;标题两行居中(名字 + 状态行)。
class _ChatHeader extends StatelessWidget {
  const _ChatHeader({required this.name, required this.presence, required this.onTapTitle});

  final String name;
  final Presence? presence;
  final VoidCallback onTapTitle;

  @override
  Widget build(BuildContext context) {
    final online = presence?.online ?? false;
    // 在线单独组装(绿点 + 「在线」);离线才用 presenceLabel 的「x 分钟前在线」
    final statusLabel = online ? '在线' : presenceLabel(presence);
    return SizedBox(
      height: 62,
      child: Row(
        children: [
          IconButton(
            key: const Key('chat.back'),
            onPressed: () => Navigator.of(context).maybePop(),
            icon: const Icon(Icons.arrow_back_ios_new_rounded,
                size: 22, color: AppColors.text1),
          ),
          Expanded(
            child: GestureDetector(
              key: const Key('chat.title'),
              behavior: HitTestBehavior.opaque,
              onTap: onTapTitle,
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Text(name,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: AppText.subtitle
                          .copyWith(fontSize: 17, color: AppColors.text1)),
                  if (statusLabel != null) ...[
                    const SizedBox(height: 1),
                    Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        if (online) ...[
                          const BreathingDot(
                              key: Key('chat.onlineDot'),
                              size: 8,
                              borderColor: AppColors.bgPage),
                          const SizedBox(width: AppSpacing.xs),
                        ],
                        Text(statusLabel,
                            style: AppText.micro.copyWith(color: AppColors.text2)),
                      ],
                    ),
                  ],
                ],
              ),
            ),
          ),
          // 与返回键等宽占位,保证名字视觉居中
          const SizedBox(width: 52),
        ],
      ),
    );
  }
}
```

4. `build` 中不再使用 `peerStatusLabel` 变量——删掉这一行(保留 `peerPresence`)。

- [ ] **Step 4: 跑测试确认通过**

```bash
cd app
../flutter/bin/flutter.bat test test/features/chat/chat_page_test.dart
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
```

Expected: chat_page 18 用例全绿;analyze 零告警;全量 242 绿。

- [ ] **Step 5: 提交**

```bash
git add app/lib/features/chat/chat_page.dart app/test/features/chat/chat_page_test.dart
git commit -m "$(cat <<'EOF'
feat(ui): 聊天页顶栏改心跳规格(62 两行居中/呼吸绿点+在线/删重复「⋯」按钮)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: 消息气泡重做(圆形头像 / R18·角 6 / 72% / 灰条 pill)

**Files:**
- Modify: `app/lib/core/theme/app_radius.dart`(+`image = 12`)
- Modify: `app/lib/features/chat/widgets/message_bubble.dart`
- Modify: `app/lib/features/chat/chat_page.dart`(`_TimeSeparator` 时间条:12/text3/上下边距 12)
- Modify: `app/test/features/chat/message_bubble_test.dart`

**Interfaces:**
- Consumes: `AppAvatar(fallbackText:)`(T3)、`AppRadius.bubble`(T5)、`AppRadius.image`(本任务)
- Produces: 气泡视觉(§附录 B.3);废除 `_SquareAvatar`

- [ ] **Step 1: 写失败测试**

`app/test/features/chat/message_bubble_test.dart` 追加:

```dart
  testWidgets('头像用圆形 AppAvatar + 首字', (tester) async {
    await _pump(tester, MessageBubble(message: _m(), peerName: '小红'));

    expect(find.byType(AppAvatar), findsOneWidget);
    expect(find.text('小'), findsOneWidget);
  });
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd app
../flutter/bin/flutter.bat test test/features/chat/message_bubble_test.dart
```

Expected: 新用例 FAIL(旧实现是方头像 `_SquareAvatar`,找不到 `AppAvatar`)。

(import 加 `import 'package:chatapp_app/core/widgets/app_avatar.dart';`;上面新用例用 `find.byType(AppAvatar)` 与 `find.text('小')` 两个断言,对旧实现为红、对新实现为绿。)

- [ ] **Step 3: 实现**

1. `app/lib/core/theme/app_radius.dart` 追加:

```dart
  static const image = 12.0; // 内容图(§5.3 相册/照片网格)
```

2. `app/lib/features/chat/widgets/message_bubble.dart` 整体替换为:

```dart
import 'dart:io';

import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_radius.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/theme/app_typography.dart';
import '../../../core/widgets/app_avatar.dart';
import '../../../im/im_client.dart';

/// 单条消息(「心跳」附录 B.3):自己=brand 实底白字、对方=白底,
/// 圆形头像 40;match_notice/ban_notice 渲染成居中 pill 灰条。
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
      final label = switch (message.kind) {
        ChatMessageKind.matchNotice => message.text.isEmpty ? noticeFallback : message.text,
        ChatMessageKind.banNotice => message.text.isEmpty ? '系统通知' : message.text,
        _ => '[暂不支持的消息]',
      };
      return Padding(
        key: const Key('chat.notice'),
        padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
        child: Center(
          child: Container(
            padding: const EdgeInsets.symmetric(
                horizontal: AppSpacing.md, vertical: 6),
            decoration: BoxDecoration(
              color: AppColors.divider,
              borderRadius: BorderRadius.circular(AppRadius.full),
            ),
            child: Text(label, style: AppText.micro.copyWith(color: AppColors.text2)),
          ),
        ),
      );
    }

    final isSelf = message.isSelf;
    final avatar = AppAvatar(
      imageUrl: isSelf ? selfAvatarUrl : peerAvatarUrl,
      size: 40,
      fallbackText: isSelf ? '我' : (peerName ?? ''),
    );
    final bubble = GestureDetector(
      onLongPress: onLongPress,
      child: Opacity(
        opacity: message.isPending ? 0.6 : 1,
        child: ConstrainedBox(
          constraints:
              BoxConstraints(maxWidth: MediaQuery.sizeOf(context).width * 0.72),
          child: _bubbleContent(context),
        ),
      ),
    );

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md, vertical: AppSpacing.xs),
      child: Row(
        mainAxisAlignment: isSelf ? MainAxisAlignment.end : MainAxisAlignment.start,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (!isSelf) ...[avatar, const SizedBox(width: AppSpacing.sm)],
          if (isSelf && message.isFailed) ...[
            IconButton(
              key: const Key('chat.retry'),
              onPressed: onRetry,
              icon: const Icon(Icons.error_rounded, color: AppColors.danger, size: 20),
              visualDensity: VisualDensity.compact,
            ),
          ],
          bubble,
          if (isSelf) ...[const SizedBox(width: AppSpacing.sm), avatar],
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
          borderRadius: BorderRadius.circular(AppRadius.image),
          child: SizedBox(width: 140, height: 140, child: _image()),
        ),
      );
    }
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: message.isSelf ? AppColors.brand : AppColors.bgCard,
        borderRadius: BorderRadius.only(
          topLeft: Radius.circular(message.isSelf ? AppRadius.bubble : 6),
          topRight: Radius.circular(message.isSelf ? 6 : AppRadius.bubble),
          bottomLeft: Radius.circular(AppRadius.bubble),
          bottomRight: Radius.circular(AppRadius.bubble),
        ),
      ),
      child: Text(message.text,
          style: AppText.body
              .copyWith(color: message.isSelf ? Colors.white : AppColors.text1)),
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
        color: AppColors.divider,
        child: const Center(child: Icon(Icons.image_rounded, color: AppColors.text3)),
      );
}
```

(`_SquareAvatar` 类整个删除。)

3. `app/lib/features/chat/chat_page.dart` 的 `_TimeSeparator` 改为(附录 B.5:12 `text3`、上下边距 12):

```dart
  @override
  Widget build(BuildContext context) => Padding(
        key: const Key('chat.time'),
        padding: const EdgeInsets.symmetric(vertical: AppSpacing.md),
        child: Center(
          child: Text(label, style: AppText.micro.copyWith(color: AppColors.text3)),
        ),
      );
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd app
../flutter/bin/flutter.bat test test/features/chat
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
```

Expected: message_bubble 5 用例全绿(含既有「头像首字」「居中灰条」);chat 目录全绿;analyze 零告警;全量 243 绿。

- [ ] **Step 5: 提交**

```bash
git add app/lib/core/theme/app_radius.dart app/lib/features/chat/widgets/message_bubble.dart app/test/features/chat/message_bubble_test.dart
git commit -m "$(cat <<'EOF'
feat(ui): 消息气泡心跳化(圆形头像首字/自己 brand 实底/R18 上角 6/最大宽 72%/灰条 pill)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: 输入栏 + 表情/＋面板

**Files:**
- Modify: `app/lib/features/chat/chat_page.dart`(`_InputBar`)
- Modify: `app/lib/features/chat/widgets/emoji_panel.dart`
- Modify: `app/lib/features/chat/widgets/more_panel.dart`
- Modify: `app/test/features/chat/chat_page_test.dart`(新增发送钮变色用例)

**Interfaces:**
- Produces: 输入栏(§附录 B.4):输入框 40/R16/聚焦 brand 光晕;发送 = 纯图标变色(text3↔brand);面板白底 + 顶部分隔线
- 行为不变:发送仍始终可点、空发无效;面板切换/键盘收起逻辑不动

- [ ] **Step 1: 写失败测试**

`app/test/features/chat/chat_page_test.dart` 追加:

```dart
  testWidgets('发送钮:空输入 text3,有字变 brand', (tester) async {
    await pumpChat(tester);

    Icon sendIcon() => tester.widget<Icon>(find.descendant(
        of: find.byKey(const Key('chat.send')), matching: find.byType(Icon)));

    expect(sendIcon().color, AppColors.text3);

    await tester.enterText(find.byKey(const Key('chat.input')), '在吗');
    await tester.pump();
    expect(sendIcon().color, AppColors.brand);

    await tester.enterText(find.byKey(const Key('chat.input')), '');
    await tester.pump();
    expect(sendIcon().color, AppColors.text3);
  });
```

(import 加 `import 'package:chatapp_app/core/theme/app_colors.dart';`)

- [ ] **Step 2: 跑测试确认失败**

```bash
cd app
../flutter/bin/flutter.bat test test/features/chat/chat_page_test.dart
```

Expected: 新用例 FAIL(现发送 Icon 无 color 设定,取到 null 而非 text3)。

- [ ] **Step 3: 实现输入栏**

`app/lib/features/chat/chat_page.dart` 的 `_InputBar.build` 整体替换:

```dart
  @override
  Widget build(BuildContext context) => Container(
        color: AppColors.bgCard,
        child: SafeArea(
          top: false,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(
                AppSpacing.md, AppSpacing.sm, AppSpacing.xs, AppSpacing.sm),
            child: Row(
              children: [
                Expanded(
                  child: ListenableBuilder(
                    listenable: focusNode,
                    builder: (context, child) => Container(
                      decoration: BoxDecoration(
                        borderRadius: BorderRadius.circular(AppRadius.input),
                        boxShadow: focusNode.hasFocus
                            ? [
                                BoxShadow(
                                  color: AppColors.brand.withValues(alpha: .12),
                                  blurRadius: 12,
                                ),
                              ]
                            : null,
                      ),
                      child: child,
                    ),
                    child: SizedBox(
                      height: 40,
                      child: TextField(
                        key: const Key('chat.input'),
                        controller: controller,
                        focusNode: focusNode,
                        textInputAction: TextInputAction.send,
                        onSubmitted: (_) => onSend(),
                        textAlignVertical: TextAlignVertical.center,
                        style: AppText.body.copyWith(color: AppColors.text1),
                        decoration: InputDecoration(
                          hintText: '说点什么…',
                          hintStyle: AppText.body.copyWith(color: AppColors.text3),
                          isDense: true,
                          filled: true,
                          fillColor: AppColors.bgCard,
                          contentPadding: const EdgeInsets.symmetric(horizontal: 14),
                          enabledBorder: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(AppRadius.input),
                            borderSide: const BorderSide(color: AppColors.divider),
                          ),
                          focusedBorder: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(AppRadius.input),
                            borderSide:
                                const BorderSide(color: AppColors.brand, width: 1.5),
                          ),
                        ),
                      ),
                    ),
                  ),
                ),
                IconButton(
                  key: const Key('chat.emoji.button'),
                  onPressed: onToggleEmoji,
                  icon: const Icon(Icons.emoji_emotions_rounded, color: AppColors.text2),
                ),
                IconButton(
                  key: const Key('chat.more.button'),
                  onPressed: onToggleMore,
                  icon: const Icon(Icons.add_circle_rounded, color: AppColors.text2),
                ),
                IconButton(
                  key: const Key('chat.send'),
                  onPressed: sending ? null : onSend,
                  icon: ListenableBuilder(
                    listenable: controller,
                    builder: (context, _) => Icon(
                      Icons.send_rounded,
                      color: controller.text.trim().isEmpty
                          ? AppColors.text3
                          : AppColors.brand,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      );
```

(import 追加 `import '../../core/theme/app_radius.dart';`)

- [ ] **Step 4: 面板白底**

`app/lib/features/chat/widgets/emoji_panel.dart` 的 `build` 改为:

```dart
  @override
  Widget build(BuildContext context) => Container(
        key: const Key('chat.emoji.panel'),
        height: 220,
        decoration: const BoxDecoration(
          color: AppColors.bgCard,
          border: Border(top: BorderSide(color: AppColors.divider)),
        ),
        child: GridView.count(
          crossAxisCount: 8,
          padding: const EdgeInsets.all(AppSpacing.sm),
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
```

(import 追加 `import '../../../core/theme/app_colors.dart';` 与 `app_spacing.dart`)

`app/lib/features/chat/widgets/more_panel.dart` 的 `build` 改为:

```dart
  @override
  Widget build(BuildContext context) => Container(
        key: const Key('chat.more.panel'),
        height: 160,
        decoration: const BoxDecoration(
          color: AppColors.bgCard,
          border: Border(top: BorderSide(color: AppColors.divider)),
        ),
        padding: const EdgeInsets.all(AppSpacing.lg),
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
                    color: AppColors.brand.withValues(alpha: .12),
                    borderRadius: BorderRadius.circular(AppRadius.input),
                  ),
                  child: const Icon(Icons.photo_library_rounded,
                      size: 26, color: AppColors.brand),
                ),
                const SizedBox(height: 6),
                Text('相册', style: AppText.micro.copyWith(color: AppColors.text2)),
              ],
            ),
          ),
        ),
      );
```

(import 追加 `app_colors.dart`、`app_radius.dart`、`app_spacing.dart`、`app_typography.dart`)

- [ ] **Step 5: 跑测试确认通过**

```bash
cd app
../flutter/bin/flutter.bat test test/features/chat
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
```

Expected: chat 全绿(含表情面板/＋面板/发送钮变色);analyze 零告警;全量 244 绿。

- [ ] **Step 6: 提交**

```bash
git add app/lib/features/chat/chat_page.dart app/lib/features/chat/widgets/emoji_panel.dart app/lib/features/chat/widgets/more_panel.dart app/test/features/chat/chat_page_test.dart
git commit -m "$(cat <<'EOF'
feat(ui): 聊天输入栏心跳化(输入框 40 R16 聚焦光晕/rounded 图标/发送钮纯图标变色)+ 面板白底

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 11: 聊天页空态 / 骨架 / 错误重试(+FakeImClient 扩展)

**Files:**
- Modify: `app/test/support/fake_im_client.dart`(加 `historyError` / `historyGate`)
- Modify: `app/lib/features/chat/chat_page.dart`(messages.when 三分支)
- Modify: `app/test/features/chat/chat_page_test.dart`(新增三个用例)

**Interfaces:**
- Consumes: `ChatBubblesMark`(T4)、`ChatSkeleton`(T5)、`AppErrorView`/`apiMessageOf`(T2)
- Produces: 聊天页空态「打个招呼吧/发条消息,开始你们的故事」;错误态重试 = `ref.invalidate(chatProvider(peerId))`

- [ ] **Step 1: FakeImClient 扩展 + 写失败测试**

`app/test/support/fake_im_client.dart`:

1. 顶部加 `import 'dart:async';`(如已有则跳过)。
2. 字段区加:

```dart
  /// 置上就让 fetchHistory 抛这个错(测聊天页错误态)。
  Object? historyError;

  /// 置上则 fetchHistory 挂起直到 complete(测加载骨架)。
  Completer<void>? historyGate;
```

3. `fetchHistory` 改为:

```dart
  @override
  Future<List<ChatMessage>> fetchHistory(String peerId, {int count = 50}) async {
    log.add('fetchHistory:$peerId');
    if (historyError != null) throw historyError!;
    final gate = historyGate;
    if (gate != null) await gate.future;
    return history[peerId] ?? const [];
  }
```

`app/test/features/chat/chat_page_test.dart` `main()` 末尾追加:

```dart
  testWidgets('没有消息 → 空态「打个招呼吧」+ 副文案', (tester) async {
    await pumpChat(tester);

    expect(find.text('打个招呼吧'), findsOneWidget);
    expect(find.text('发条消息,开始你们的故事'), findsOneWidget);
  });

  testWidgets('历史加载中 → 气泡骨架(有限 pump,不 settle)', (tester) async {
    fake.historyGate = Completer<void>();
    fake.history = {
      'u9': [_text('m1', isSelf: false, text: '你好')],
    };
    await pumpChat(tester, settle: false);

    expect(find.byKey(const Key('chat.skeleton')), findsOneWidget);

    fake.historyGate!.complete();
    fake.historyGate = null;
    await pumpFrames(tester);
  });

  testWidgets('历史加载失败 → 错误态;点重试恢复', (tester) async {
    fake.historyError = Exception('boom');
    fake.history = {
      'u9': [_text('m1', isSelf: false, text: '你好')],
    };
    await pumpChat(tester);

    expect(find.text('没能加载出来'), findsOneWidget);

    fake.historyError = null;
    await tester.tap(find.text('重试'));
    await tester.pumpAndSettle();

    expect(find.text('你好'), findsOneWidget);
    expect(fake.log.where((l) => l == 'fetchHistory:u9').length, 2);
  });
```

(import 加 `import 'dart:async';`)

- [ ] **Step 2: 跑测试确认失败**

```bash
cd app
../flutter/bin/flutter.bat test test/features/chat/chat_page_test.dart
```

Expected: 三个新用例 FAIL(空态只有「打个招呼吧」无副文案 → 第二断言红;骨架未接线 → 红;错误态无「没能加载出来」→ 红)。

- [ ] **Step 3: 实现**

`app/lib/features/chat/chat_page.dart`:

1. import 追加:

```dart
import '../../core/api_exception.dart';
import '../../core/widgets/app_empty_state.dart';
import '../../core/widgets/app_error_view.dart';
import 'widgets/chat_bubbles_mark.dart';
import 'widgets/chat_skeleton.dart';
```

2. `messages.when` 三分支改为:

```dart
            child: messages.when(
              loading: () => const ChatSkeleton(),
              error: (error, _) => AppErrorView(
                message: apiMessageOf(error),
                onRetry: () => ref.invalidate(chatProvider(widget.peerId)),
              ),
              data: (items) {
                if (items.isEmpty) {
                  return const Center(
                    child: AppEmptyState(
                      mark: ChatBubblesMark(),
                      title: '打个招呼吧',
                      description: '发条消息,开始你们的故事',
                    ),
                  );
                }
```

(其余 data 分支不动。)

- [ ] **Step 4: 跑测试确认通过**

```bash
cd app
../flutter/bin/flutter.bat test test/features/chat
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
```

Expected: chat 目录全绿;analyze 零告警;全量 247 绿。

- [ ] **Step 5: 提交**

```bash
git add app/test/support/fake_im_client.dart app/lib/features/chat/chat_page.dart app/test/features/chat/chat_page_test.dart
git commit -m "$(cat <<'EOF'
feat(ui): 聊天页空态插画/气泡骨架/错误态重试(invalidate),FakeImClient 支持历史失败与挂起

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 12: 门槛验证 + 打包上模拟器(手测准备)

**Files:** 无代码改动(产物 = 双模拟器上的 release APK + 手测清单)

**Interfaces:**
- Consumes: 前 11 个任务全部产出

- [ ] **Step 1: 全量门槛**

```bash
cd app
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
```

Expected: analyze 零告警;247 用例全绿(233 基线 + 14 新增)。

- [ ] **Step 2: 打 release 包(连测试服务器)**

```bash
cd app
../flutter/bin/flutter.bat build apk --release --dart-define=API_BASE=http://<SERVER_IP>/api/v1
```

- [ ] **Step 3: 装两台模拟器**

模拟器未启动先启动(见 `docs/pitfalls/android-emulator.md`);确认在线后:

```bash
adb devices
adb -s emulator-5554 install -r app/build/app/outputs/flutter-apk/app-release.apk
adb -s emulator-5556 install -r app/build/app/outputs/flutter-apk/app-release.apk
```

(cwd = 仓库根;`app/build/...` 相对路径按实际 cwd 调整。)

- [ ] **Step 4: 备好手测数据**

```bash
cd chatapp
python manage.py dev_reset_pair --a u8 --b u21     # Bob(u8) / 可欣21(u21) 重演配对
python manage.py im_send --from u21 --to u8 --text "在吗"     # 代发消息铺会话
```

- [ ] **Step 5: 汇报手测清单(用户亲测)**

- 消息页:骨架 → 列表;横滑条(头像首字/在线呼吸点);系统通知行(渐变头像 + 官方标);会话行(渐变角标、时间、预览);空态(无会话账号);错误态(断网点「消息」或杀 IM)
- 聊天页:顶栏两行(在线/离线/未知三态);气泡(圆形头像、自己 pink、R18);时间条与配对灰条;输入栏(聚焦描边光晕、发送钮变色、表情/＋面板);图片消息与长按菜单;发送失败重发;空会话「打个招呼吧」
- 弱网/错误:飞行模式下各重试入口
- 系统「减弱动态效果」开:呼吸点/骨架降级无异常
- 封禁账号:整屏不受影响(回归)

- [ ] **Step 6: 待用户手测通过后收尾(另一步执行)**

用户确认观感后:更新 `CLAUDE.md` 里程碑(批次③交付 + 测试数)→ 提交 → `ui/batch3` 合回 `master`(ff)→ 删分支 → `git push origin master`。

---

## 计划自查记录

- **Spec 覆盖**:§1 消息页(页壳 T6、横滑条/通知行/会话行 T7、四态 T6+T5)→;§2 聊天页(顶栏 T8、气泡 T9、输入栏/面板 T10、空态/骨架/错误 T11、看大图明确不做)→;§3 新组件(T4/T5)→;§4 共享层(T2/T3)→;§5 规则附录(T1)→;§6 测试与验收(T2–T11 各带测试 + T12 门槛/手测)→。
- **类型/命名一致性**:`apiMessageOf`(T2 定义,T6/T11 消费)、`ChatBubblesMark(size=118)`(T4 定义,T6/T11 消费)、`ChatsSkeleton`/`ChatSkeleton`(T5 定义,T6/T11 消费)、`AppRadius.bubble`(T5 定义,T9 消费)、`AppRadius.image`(T9 定义并消费)、`AppAvatar.fallbackText`(T3 定义,T7/T9 消费)、`historyError`/`historyGate`(T11 定义并消费)、`pumpChat(settle:)`(T8 定义,T11 消费)。
- **行为零变化例外**已全部显式列出(T8 删「⋯」、T11 加副文案与重试)。
- **无限动画纪律**:骨架/呼吸点可见的用例全部 `pumpFrames` 或有限 `pump`(T5/T6/T7/T8/T11)。
