import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/chat/widgets/chat_bubbles_mark.dart';
import '../../support/heart_theme.dart';

void main() {
  testWidgets('渲染渐变双气泡插画(静态,可直接 settle)', (tester) async {
    await tester.pumpWidget(MaterialApp(theme: heartTheme, 
      home: Scaffold(body: Center(child: ChatBubblesMark())),
    ));
    await tester.pumpAndSettle();

    expect(find.byType(ChatBubblesMark), findsOneWidget);
    expect(find.byType(CustomPaint), findsWidgets);
  });
}
