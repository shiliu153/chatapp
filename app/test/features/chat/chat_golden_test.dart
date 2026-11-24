import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/app_theme.dart';
import 'package:chatapp_app/core/ui/ember_ui.dart';
import 'package:chatapp_app/features/chat/widgets/chat_illustration.dart';
import 'package:chatapp_app/features/chat/widgets/conversation_tile.dart';
import 'package:chatapp_app/features/chat/widgets/message_bubble.dart';
import 'package:chatapp_app/im/im_client.dart';

/// 对话线 golden(E-5.3 page spec §6 第 2 条):**16 张**
///
/// | 组 | 张数 | 覆盖 |
/// |---|---|---|
/// | 会话行 `ConversationTile` | 6 | 明 / 暗 × default / 未读 / 草稿 |
/// | 气泡 `MessageBubble` | 8 | 明 / 暗 × 自己 / 对方 / 发送中 / 失败 |
/// | 空态 `EmberEmpty` + unDraw 插画 | 2 | 明 / 暗 |
///
/// 为什么是**组件级 golden**(而不是模拟器整页截图):这里比的是取值 ——
/// 自己气泡 `brand.default` + `brand.on`、对方 `surface.card` + `text.primary`、
/// 圆角 16(靠头像侧上角 6)、时间与摘要的 `text.tertiary` / `text.secondary`、
/// 未读角标 `brand.default` 底、草稿摘要转灰、发送中右下角转圈、失败左侧
/// `status.danger` 感叹号。设备字体、真实照片、手势轨迹属于**模拟器手测**
/// (PR 正文「等待模拟器验收」那一段)。
///
/// 重新生成:`cd app && flutter test --update-goldens test/features/chat/chat_golden_test.dart`
/// (只在**确认视觉改动就是想要的**之后跑,并人工看一眼 diff 图。)
void main() {
  /// 固定视口 + 关掉动效(骨架 / 在线点呼吸这类循环动画会停在中间值,
  /// 截图不会撞上弹簧中间帧)。
  Future<void> pumpScene(
    WidgetTester tester,
    Widget child, {
    required Brightness brightness,
    Size size = const Size(390, 844),
  }) async {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(brightness: brightness),
        themeAnimationDuration: Duration.zero,
        home: MediaQuery(
          data: MediaQueryData(size: size, disableAnimations: true),
          child: Scaffold(body: Align(alignment: Alignment.topLeft, child: child)),
        ),
      ),
    );
    await tester.pump();
    await _precacheAssets(tester);
    await tester.pump();
  }

  Widget tile({
    required String name,
    required String preview,
    String? timeLabel,
    int unread = 0,
    bool draft = false,
    bool muted = false,
  }) =>
      SizedBox(
        width: 390,
        child: ConversationTile(
          peerId: 'u9',
          name: name,
          preview: preview,
          timeLabel: timeLabel,
          unread: unread,
          draft: draft,
          muted: muted,
          onTap: () {},
        ),
      );

  ChatMessage message({
    bool isSelf = false,
    String text = '晚上一起吃饭吗?',
    bool isPending = false,
    bool isFailed = false,
  }) =>
      ChatMessage(
        msgId: 'm1',
        peerId: 'u9',
        isSelf: isSelf,
        timestamp: DateTime(2026, 11, 24, 12, 30).millisecondsSinceEpoch,
        kind: ChatMessageKind.text,
        text: text,
        isPending: isPending,
        isFailed: isFailed,
      );

  Widget bubble(ChatMessage item) => SizedBox(
        width: 390,
        child: MessageBubble(
          message: item,
          peerName: '小红',
          onRetry: item.isFailed ? () {} : null,
        ),
      );

  for (final brightness in Brightness.values) {
    final mode = brightness == Brightness.light ? 'light' : 'dark';

    testWidgets('会话行 golden · $mode · default', (tester) async {
      await pumpScene(
        tester,
        tile(name: '小红', preview: '晚上一起吃饭吗?', timeLabel: '12:30'),
        brightness: brightness,
        size: const Size(390, 120),
      );
      await expectLater(
        find.byType(ConversationTile),
        matchesGoldenFile('goldens/conversation_tile_${mode}_default.png'),
      );
    });

    testWidgets('会话行 golden · $mode · 未读', (tester) async {
      await pumpScene(
        tester,
        tile(name: '小红', preview: '晚上一起吃饭吗?', timeLabel: '12:30', unread: 3),
        brightness: brightness,
        size: const Size(390, 120),
      );
      await expectLater(
        find.byType(ConversationTile),
        matchesGoldenFile('goldens/conversation_tile_${mode}_unread.png'),
      );
    });

    testWidgets('会话行 golden · $mode · 草稿', (tester) async {
      await pumpScene(
        tester,
        tile(
          name: '小红',
          preview: '我还没发出去的话',
          timeLabel: '昨天',
          draft: true,
          muted: true,
        ),
        brightness: brightness,
        size: const Size(390, 120),
      );
      await expectLater(
        find.byType(ConversationTile),
        matchesGoldenFile('goldens/conversation_tile_${mode}_draft.png'),
      );
    });

    testWidgets('气泡 golden · $mode · 自己', (tester) async {
      await pumpScene(
        tester,
        bubble(message(isSelf: true)), brightness: brightness,
        size: const Size(390, 120),
      );
      await expectLater(
        find.byType(MessageBubble),
        matchesGoldenFile('goldens/bubble_${mode}_self.png'),
      );
    });

    testWidgets('气泡 golden · $mode · 对方', (tester) async {
      await pumpScene(
        tester,
        bubble(message(text: '好啊,六点老地方见')),
        brightness: brightness,
        size: const Size(390, 120),
      );
      await expectLater(
        find.byType(MessageBubble),
        matchesGoldenFile('goldens/bubble_${mode}_peer.png'),
      );
    });

    testWidgets('气泡 golden · $mode · 发送中', (tester) async {
      await pumpScene(
        tester,
        bubble(message(isSelf: true, isPending: true)),
        brightness: brightness,
        size: const Size(390, 120),
      );
      // 发送中的转圈是常驻无限动画:只截当前这一帧,不 settle。
      await expectLater(
        find.byType(MessageBubble),
        matchesGoldenFile('goldens/bubble_${mode}_pending.png'),
      );
    });

    testWidgets('气泡 golden · $mode · 失败', (tester) async {
      await pumpScene(
        tester,
        bubble(message(isSelf: true, isFailed: true)),
        brightness: brightness,
        size: const Size(390, 120),
      );
      await expectLater(
        find.byType(MessageBubble),
        matchesGoldenFile('goldens/bubble_${mode}_failed.png'),
      );
    });

    testWidgets('空态 golden · $mode', (tester) async {
      await pumpScene(
        tester,
        SizedBox(
          width: 390,
          child: EmberEmpty(
            illustration: const ChatIllustration(ChatIllustrationKind.emptyThreads),
            title: '还没有对话',
            description: '互相喜欢之后就能开聊了',
            actionLabel: '去遇见',
            onAction: () {},
          ),
        ),
        brightness: brightness,
        size: const Size(390, 520),
      );
      await expectLater(
        find.byType(EmberEmpty),
        matchesGoldenFile('goldens/empty_state_$mode.png'),
      );
    });
  }
}

/// 把树里的**资源图**先解码好再截图(`Image.asset` 的解码是异步的,直接截会截到空)。
Future<void> _precacheAssets(WidgetTester tester) async {
  final elements = find.byType(Image).evaluate().toList();
  await tester.runAsync(() async {
    for (final element in elements) {
      final provider = (element.widget as Image).image;
      if (provider is! AssetImage) continue;
      await precacheImage(provider, element);
    }
  });
}
