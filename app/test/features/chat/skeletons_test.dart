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
