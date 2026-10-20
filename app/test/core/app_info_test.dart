import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/app_info.dart';

void main() {
  test('appVersion 与 pubspec.yaml 保持一致', () {
    final pubspec = File('pubspec.yaml').readAsStringSync();
    final match = RegExp(r'^version:\s*([^\s]+)', multiLine: true).firstMatch(pubspec);

    expect(match, isNotNull, reason: 'pubspec.yaml 必须有 version 行');
    expect(match!.group(1)!.split('+').first, appVersion);
  });
}
