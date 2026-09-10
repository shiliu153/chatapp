import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/onboarding/onboarding_page.dart';

import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

const _loggedIn = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7};

void main() {
  test('向导校验函数', () {
    expect(validateBasicStep(nickname: '', gender: 'male', birthday: DateTime(2000)),
        '请填写昵称');
    expect(validateBasicStep(nickname: '小明', gender: null, birthday: DateTime(2000)),
        '请选择性别');
    expect(validateBasicStep(nickname: '小明', gender: 'male', birthday: DateTime(2010)),
        '未满 18 周岁,无法使用本应用');
    expect(validateBasicStep(nickname: '小明', gender: 'male', birthday: DateTime(2000)), isNull);
    expect(validateAboutStep(city: '', bio: '你好'), '请填写城市');
    expect(validateAboutStep(city: '上海', bio: ''), '请填写简介');
    expect(validateAboutStep(city: '上海', bio: '你好'), isNull);
  });

  testWidgets('从发现页引导卡进入向导;第 1 步已有数据 → 下一步 PATCH 基本资料', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson(
            missing: ['city', 'bio', 'photos'],
            city: '',
            bio: '',
          )),
      'GET /users/tags': (options) => ok([tagJson(1, '运动')]),
      'PATCH /users/me': (options) => ok(profileJson(missing: ['photos'])),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('discovery.goOnboarding')));
    await tester.pumpAndSettle();
    expect(find.text('第 1 步 / 共 3 步'), findsOneWidget);

    await tester.tap(find.byKey(const Key('onboarding.next')));
    await tester.pumpAndSettle();

    final patch = adapter.log.lastWhere((r) => r.method == 'PATCH').data as Map<String, dynamic>;
    expect(patch, {'nickname': '小明', 'gender': 'male', 'birthday': '2000-01-01'});
    expect(find.text('第 2 步 / 共 3 步'), findsOneWidget);
  });

  testWidgets('第 2 步校验:缺城市 → 提示且不发请求', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson(
            missing: ['city', 'bio', 'photos'],
            city: '',
            bio: '',
          )),
      'GET /users/tags': (options) => ok([]),
      'PATCH /users/me': (options) => ok(profileJson(missing: ['photos'])),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('discovery.goOnboarding')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('onboarding.next')));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('onboarding.next')));
    await tester.pumpAndSettle();

    expect(find.text('请填写城市'), findsOneWidget);
    expect(adapter.log.where((r) => r.method == 'PATCH'), hasLength(1)); // 只有第 1 步那次
    expect(find.text('第 2 步 / 共 3 步'), findsOneWidget); // 没翻页
  });
}
