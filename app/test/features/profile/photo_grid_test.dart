import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image_picker/image_picker.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/features/profile/widgets/photo_grid.dart';

import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

Future<void> pumpGrid(WidgetTester tester, ScriptedAdapter adapter,
    {required Future<XFile?> Function() pickImage}) async {
  SharedPreferences.setMockInitialValues({});
  final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
  final refreshDio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
  await tester.pumpWidget(ProviderScope(
    overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(refreshDio),
    ],
    child: MaterialApp(
      home: Scaffold(body: PhotoGrid(pickImage: pickImage)),
    ),
  ));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('选图 → 上传 → 刷新资料', (tester) async {
    var meCalls = 0;
    final adapter = ScriptedAdapter({
      'GET /users/me': (options) {
        meCalls++;
        return ok(profileJson());
      },
      'POST /users/me/photos': (options) => ok(photoJson(9), status: 201),
    });
    await pumpGrid(tester, adapter,
        pickImage: () async =>
            XFile.fromData(Uint8List.fromList(List.filled(10, 1)), name: 'a.png'));

    await tester.tap(find.byKey(const Key('photo.add')));
    await tester.pumpAndSettle();

    expect(adapter.log.where((r) => r.path == '/users/me/photos'), hasLength(1));
    expect(meCalls, 2); // 初次加载 + 上传后刷新
  });

  testWidgets('超过 5MB → 本地拦截,不发请求', (tester) async {
    final adapter = ScriptedAdapter({'GET /users/me': (options) => ok(profileJson())});
    await pumpGrid(tester, adapter,
        pickImage: () async =>
            XFile.fromData(Uint8List(5 * 1024 * 1024 + 1), name: 'big.png'));

    await tester.tap(find.byKey(const Key('photo.add')));
    await tester.pumpAndSettle();

    expect(find.text('图片不能超过 5MB'), findsOneWidget);
    expect(adapter.log.where((r) => r.path == '/users/me/photos'), isEmpty);
  });
}
