import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/theme/ember_colors.dart';
import 'package:chatapp_app/core/ui/ember_ui.dart';

import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

const _loggedIn = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 7};

/// 进「我的 → 编辑资料」。
Future<void> openEditPage(WidgetTester tester, ScriptedAdapter adapter) async {
  await pumpApp(tester, adapter, prefs: _loggedIn);
  await tester.pumpAndSettle();
  await tester.tap(navTab('我'));
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(const Key('my.card.identity')));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('改昵称保存 → PATCH 带上表单内容', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'GET /users/tags': (options) => ok([tagJson(1, '运动')]),
      'PATCH /users/me': (options) => ok(profileJson(nickname: '新昵称')),
    });
    await openEditPage(tester, adapter);

    await tester.enterText(find.byKey(const Key('edit.nickname')), '新昵称');
    await tester.tap(find.byKey(const Key('edit.save')));
    await tester.pumpAndSettle();

    final patch = adapter.log.lastWhere((r) => r.method == 'PATCH').data as Map<String, dynamic>;
    expect(patch['nickname'], '新昵称');
    expect(patch['tag_ids'], isEmpty);
    expect(find.text('已保存'), findsOneWidget);
    await drainToast(tester); // EmberToast 2s Timer 收尾
  });

  testWidgets('昵称为空 → 字段下方红字 + 不发请求 + 不弹全局 Toast(page spec §5)', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'GET /users/tags': (options) => ok([]),
      'PATCH /users/me': (options) => ok(profileJson()),
    });
    await openEditPage(tester, adapter);

    await tester.enterText(find.byKey(const Key('edit.nickname')), '');
    await tester.tap(find.byKey(const Key('edit.save')));
    await tester.pumpAndSettle();

    // 校验说明落在字段下方(13 / status.danger),字段描边转红由 EmberField 负责。
    final error = tester.widget<Text>(find.text('请填写昵称'));
    expect(error.style!.color, EmberColors.light.statusDanger);
    expect(error.style!.fontSize, 13);
    // 不发请求,也没有全局 Toast(改版前这里弹 AppToast)。
    expect(adapter.log.where((r) => r.method == 'PATCH'), isEmpty);
    expect(find.byType(ToastPill), findsNothing);
  });

  testWidgets('后端 400(如违规词)→ 表单底部提示条,保留已填内容', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'GET /users/tags': (options) => ok([]),
      'PATCH /users/me': (options) => jsonError(400, '昵称包含违规内容,请修改'),
    });
    await openEditPage(tester, adapter);

    await tester.enterText(find.byKey(const Key('edit.nickname')), '新昵称');
    await tester.tap(find.byKey(const Key('edit.save')));
    await tester.pumpAndSettle();

    // page spec §5「提交失败」:底部 status.danger 提示条 + 保留已填内容。
    expect(find.text('昵称包含违规内容,请修改'), findsOneWidget);
    expect(find.byType(ToastPill), findsNothing);
    expect(find.text('新昵称'), findsOneWidget);
  });
}
