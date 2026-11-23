import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/settings/about_page.dart';
import '../../support/heart_theme.dart';

void main() {
  testWidgets('展示应用名、版本与协议入口', (tester) async {
    await tester.pumpWidget(MaterialApp(theme: heartTheme, home: AboutPage()));

    // 版本号以 pubspec.yaml 为唯一事实来源(与 test/core/app_info_test.dart 同口径),
    // 期望值从文件读而不是写死 —— 升版本号时不需要手改本文件。
    final pubspec = File('pubspec.yaml').readAsStringSync();
    final match = RegExp(r'^version:\s*([^\s]+)', multiLine: true).firstMatch(pubspec);
    expect(match, isNotNull, reason: 'pubspec.yaml 必须有 version 行');
    final version = match!.group(1)!.split('+').first;

    expect(find.text('心跳'), findsOneWidget);
    expect(find.byKey(const Key('about.version')), findsOneWidget);
    expect(find.text('版本 $version'), findsOneWidget);
    expect(find.byKey(const Key('about.agreement')), findsOneWidget);
    expect(find.byKey(const Key('about.privacy')), findsOneWidget);
  });
}
