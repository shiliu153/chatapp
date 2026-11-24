import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image_picker/image_picker.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/core/theme/app_theme.dart';
import 'package:chatapp_app/features/square/post_compose_page.dart';

import '../../support/scripted_adapter.dart';

/// E-5.6c page spec §6 第 2 条:发帖 **2 张 golden**(明 / 暗)。
///
/// 比的是取值:§9.4 顶栏 52、正文 `EmberField`(52 起、`radius.md`、占位
/// `text.tertiary`)、字数计数 13 / `text.tertiary`、加号格(`surface.sunken` +
/// 1px `border.divider` + `radius.sm`)、底部主操作「发布」(52 高 + `radius.pill`
/// + `emberGlow`;**空内容时 disabled** = `surface.sunken` 底 + `text.tertiary` 字)。
///
/// 重新生成:`cd app && flutter test --update-goldens test/features/square/post_compose_golden_test.dart`
/// (只在**确认视觉改动就是想要的**之后跑,并人工看一眼 diff 图。)
Future<void> _pumpCompose(
  WidgetTester tester, {
  required Brightness brightness,
}) async {
  tester.view.physicalSize = const Size(390, 844);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);

  SharedPreferences.setMockInitialValues({});
  final adapter = ScriptedAdapter({});
  final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))
    ..httpClientAdapter = adapter;
  final navigatorKey = GlobalKey<NavigatorState>();
  await tester.pumpWidget(ProviderScope(
    overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(dio),
    ],
    child: MaterialApp(
      theme: buildAppTheme(brightness: brightness),
      themeAnimationDuration: Duration.zero,
      navigatorKey: navigatorKey,
      home: const Scaffold(),
    ),
  ));
  navigatorKey.currentState!.push(MaterialPageRoute(
    builder: (_) => PostComposePage(pickImages: () async => const <XFile>[]),
  ));
  await tester.pumpAndSettle();
}

void main() {
  for (final brightness in Brightness.values) {
    final mode = brightness == Brightness.light ? 'light' : 'dark';

    testWidgets('发帖 golden · $mode', (tester) async {
      await _pumpCompose(tester, brightness: brightness);
      await expectLater(
        find.byType(PostComposePage),
        matchesGoldenFile('goldens/post_compose_$mode.png'),
      );
    });
  }
}
