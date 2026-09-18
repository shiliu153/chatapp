import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/widgets/app_badge.dart';
import 'package:chatapp_app/features/shell/app_bottom_bar.dart';

Widget wrap(Widget bar, {bool disableAnimations = false}) => MaterialApp(
      home: MediaQuery(
        data: MediaQueryData(disableAnimations: disableAnimations),
        child: Scaffold(bottomNavigationBar: bar),
      ),
    );

void main() {
  testWidgets('四个 Tab 渲染,点击回调索引', (tester) async {
    final taps = <int>[];
    await tester.pumpWidget(wrap(AppBottomBar(currentIndex: 0, onTap: taps.add)));
    for (final label in ['发现', '广场', '消息', '我的']) {
      expect(find.text(label), findsOneWidget);
    }
    await tester.tap(find.text('广场'));
    expect(taps, [1]);
  });

  testWidgets('未读角标:0 不显示,3 显示数字,120 显示 99+', (tester) async {
    await tester.pumpWidget(wrap(AppBottomBar(currentIndex: 2, onTap: (_) {}, unreadCount: 0)));
    expect(find.byType(AppBadge), findsNothing);

    await tester.pumpWidget(wrap(AppBottomBar(currentIndex: 2, onTap: (_) {}, unreadCount: 3)));
    expect(find.text('3'), findsOneWidget);

    await tester.pumpWidget(wrap(AppBottomBar(currentIndex: 2, onTap: (_) {}, unreadCount: 120)));
    expect(find.text('99+'), findsOneWidget);
  });

  testWidgets('减弱动态效果下切换正常', (tester) async {
    await tester.pumpWidget(
      wrap(AppBottomBar(currentIndex: 0, onTap: (_) {}), disableAnimations: true),
    );
    await tester.tap(find.text('我的'));
    await tester.pump(const Duration(milliseconds: 400)); // 有限推进即可
    expect(find.text('我的'), findsOneWidget);
  });
}
