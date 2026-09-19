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
