import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/square/widgets/post_images.dart';

// 测试面板宽 800;卡内(内外各 16+16)可用宽 736
Future<void> _pump(WidgetTester tester, int count) async {
  await tester.pumpWidget(MaterialApp(
    home: Scaffold(
      body: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: PostImages(urls: List.generate(count, (i) => 'http://x/$i.png')),
        ),
      ),
    ),
  ));
  await tester.pump(); // 触发假网络 400 → errorBuilder 占位
}

void main() {
  testWidgets('1 张:通栏大图,宽撑满、高 240、R12', (tester) async {
    await _pump(tester, 1);
    expect(find.byKey(const Key('post.image.0')), findsOneWidget);
    expect(find.byType(GridView), findsNothing); // 不走网格
    final size = tester.getSize(find.byKey(const Key('post.image.0')));
    expect(size.width, 736);
    expect(size.height, 240);
  });

  testWidgets('2 张(旧两列混排场景):同样 3 列网格,格宽 (736-16)/3', (tester) async {
    await _pump(tester, 2);
    expect(find.byType(GridView), findsOneWidget);
    final size = tester.getSize(find.byKey(const Key('post.image.0')));
    expect(size.width, closeTo((736 - 2 * 8.0) / 3, 0.5)); // 8 = AppSpacing.sm(间距 8,附录 D.2)
    expect(size.height, size.width); // AspectRatio 1 正方
  });

  testWidgets('5 张:3 列网格', (tester) async {
    await _pump(tester, 5);
    expect(find.byType(GridView), findsOneWidget);
    expect(find.byKey(const Key('post.image.4')), findsOneWidget);
  });

  testWidgets('图挂了:divider 底占位仍在(key 保留)', (tester) async {
    await _pump(tester, 1);
    expect(find.byIcon(Icons.image_rounded), findsOneWidget);
  });
}
