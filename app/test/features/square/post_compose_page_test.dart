import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image_picker/image_picker.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/features/square/post_compose_page.dart';

import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

/// 直接 pump 单页(push 出来,发布成功后的 pop 不会顶掉根路由),相册用注入的假实现。
Future<void> pumpCompose(WidgetTester tester, ScriptedAdapter adapter,
    {required Future<List<XFile>> Function() pickImages}) async {
  SharedPreferences.setMockInitialValues({});
  final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
  final refreshDio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))
    ..httpClientAdapter = adapter;
  final navigatorKey = GlobalKey<NavigatorState>();
  await tester.pumpWidget(ProviderScope(
    overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(refreshDio),
    ],
    child: MaterialApp(navigatorKey: navigatorKey, home: const Scaffold()),
  ));
  navigatorKey.currentState!.push(MaterialPageRoute(
      builder: (_) => PostComposePage(pickImages: pickImages)));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('空内容发布按钮置灰;输入后可发', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /posts': (options) => ok(postJson(id: 1, text: '你好'), status: 201),
    });
    await pumpCompose(tester, adapter, pickImages: () async => const []);

    final button = find.byKey(const Key('compose.submit'));
    expect(tester.widget<FilledButton>(button).onPressed, isNull);   // 置灰

    await tester.enterText(find.byKey(const Key('compose.text')), '你好');
    await tester.pump();
    expect(tester.widget<FilledButton>(button).onPressed, isNotNull);
  });

  testWidgets('选图后发布带 multipart', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /posts': (options) =>
          ok(postJson(id: 1, text: '', images: ['http://t/a.png']), status: 201),
    });
    await pumpCompose(tester, adapter, pickImages: () async => [
      XFile.fromData(Uint8List.fromList(List.filled(10, 1)), name: 'a.png'),
    ]);

    await tester.tap(find.byKey(const Key('compose.add')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('compose.picked.0')), findsOneWidget);

    await tester.tap(find.byKey(const Key('compose.submit')));
    await tester.pumpAndSettle();
    expect(adapter.log.where((r) => r.method == 'POST' && r.path == '/posts'),
        hasLength(1));
  });
}
