import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/app.dart';
import 'package:chatapp_app/core/providers.dart';

import 'scripted_adapter.dart';

/// 起整个 App(真实 provider + 假网络)。prefs 里塞 {'auth.refresh': 'r', ...} 模拟已登录。
Future<void> pumpApp(WidgetTester tester, ScriptedAdapter adapter,
    {Map<String, Object> prefs = const {}}) async {
  SharedPreferences.setMockInitialValues(prefs);
  final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
  final refreshDio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
  await tester.pumpWidget(ProviderScope(
    overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(refreshDio),
    ],
    child: const ChatApp(),
  ));
}

/// 底部导航栏里的 Tab 标签(避开与各页 AppBar 标题重名)。
Finder navTab(String label) =>
    find.descendant(of: find.byType(NavigationBar), matching: find.text(label));
