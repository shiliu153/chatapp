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
    expect(find.text('open'), findsOneWidget); // 关回到宿主页
  });
}
