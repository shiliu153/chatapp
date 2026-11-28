import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image_picker/image_picker.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/core/ui/ember_ui.dart';
import 'package:chatapp_app/features/square/post_compose_page.dart';

import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';
import '../../support/heart_theme.dart';

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
    child: MaterialApp(theme: heartTheme, navigatorKey: navigatorKey, home: const Scaffold()),
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

    // E-5.6c:底部主操作换成 `EmberButton`(§8.3 disabled 的判据就是「不可点」)。
    final button = find.byKey(const Key('compose.submit'));
    expect(tester.widget<EmberButton>(button).onPressed, isNull);   // 置灰

    await tester.enterText(find.byKey(const Key('compose.text')), '你好');
    await tester.pump();
    expect(tester.widget<EmberButton>(button).onPressed, isNotNull);
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

  // ───────────────────────────────────────────────────────────────────────
  // 两条上限护栏(#532)。它们原本没有任何用例覆盖:
  //   · 「> 9 张」在生产里**可达** —— 已选 2 张再一次性多选 9 张,循环补到 9 张时命中;
  //   · 「> 5MB」在生产里**够不到** —— `pickImagesFromGallery` 传了
  //     `maxWidth: 1080 / imageQuality: 85`,image_picker 在交给 App 前就降采样了。
  //     它保留为防御性护栏(将来放开 maxWidth 时不至于裸奔),这里用注入的假 picker 让它不再是死码。
  // ───────────────────────────────────────────────────────────────────────

  /// 造 n 个「小图」文件(每个 10 字节,远低于 5MB)。
  List<XFile> smallFiles(int n) => [
        for (var i = 0; i < n; i++)
          XFile.fromData(Uint8List.fromList(List.filled(10, i)), name: 'a$i.png'),
      ];

  testWidgets('一次多选超过剩余额度:只收到 9 张并提示「最多 9 张图片」', (tester) async {
    final adapter = ScriptedAdapter({});
    var round = 0;
    await pumpCompose(tester, adapter, pickImages: () async {
      round++;
      // 第一轮给 2 张,第二轮给 9 张 —— 累计 11,必然溢出 `_maxCount = 9`。
      return smallFiles(round == 1 ? 2 : 9);
    });

    await tester.tap(find.byKey(const Key('compose.add')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('compose.picked.1')), findsOneWidget);

    await tester.tap(find.byKey(const Key('compose.add')));
    await tester.pumpAndSettle();

    // 正好 9 张(第 10、11 张被挡掉),并且弹出提示。
    expect(find.byKey(const Key('compose.picked.8')), findsOneWidget);
    expect(find.byKey(const Key('compose.picked.9')), findsNothing);
    expect(find.text('最多 9 张图片'), findsOneWidget);

    EmberToast.hide();
    await tester.pump();
  });

  testWidgets('单张超过 5MB:拒收该图并提示「单张图片不能超过 5MB」', (tester) async {
    final adapter = ScriptedAdapter({});
    await pumpCompose(tester, adapter, pickImages: () async => [
          // 5MB + 1 字节:刚好越过阈值。
          XFile.fromData(
            Uint8List.fromList(List.filled(5 * 1024 * 1024 + 1, 7)),
            name: 'big.jpg',
          ),
        ]);

    await tester.tap(find.byKey(const Key('compose.add')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('compose.picked.0')), findsNothing);
    expect(find.text('单张图片不能超过 5MB'), findsOneWidget);

    EmberToast.hide();
    await tester.pump();
  });
}
